"""Reusable deployed-bundle decision and observation lifecycle for evaluation & macro training."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from .act1 import is_combat_choice
from .deck_policy import DeckPolicy
from .encounter import EncounterModel
from .encounter_draft import WeakEncounterPool
from .merchant import PendingRelicPurchase
from .native import legal_actions
from .offer_policy import OfferModel, offer_type
from .routing import RoomModel
from .run_bundle import load_bundle
from .run_policy import RunPolicy, RunWeights
from .strategy import StrategyModel, strategy_kind
from .turn_planning import choose_turn


_UNSUPPORTED_BUNDLE_KEYS = (
    "tactical_student",
    "micro",
    "return_model",
    "boss_search",
    "combat_search",
    "combat_search_deployed",
)


class DeployedController:
    """Stateful wrapper matching ``run_evaluation`` precedence for on-policy macro rollouts."""

    def __init__(
        self,
        policy: RunPolicy,
        *,
        late_weights=None,
        router=None,
        late_router=None,
        offers=None,
        strategy=None,
        deck_model=None,
        encounter=None,
        turn_search: bool = False,
        combat_v2=None,
    ):
        self.policy = policy
        self.late_weights = late_weights
        self.router = router
        self.late_router = late_router
        self.offers = offers
        self.strategy = strategy
        self.deck_model = deck_model
        self.encounter = encounter
        self.turn_search = bool(turn_search)
        self.combat_v2 = combat_v2
        self.paid_relics = PendingRelicPurchase()
        self.pool = None
        self.act = 0
        self.act3_normal_count = 0
        self._last_proposed_command = None
        self._boss_tactics_before = None
        self._last_step_used_encounter = False

    @classmethod
    def from_bundle(cls, bundle_path: Path, *, macro_seed: int = 0) -> DeployedController:
        role, settings = load_bundle(bundle_path)
        if role != "candidate":
            raise ValueError(
                f"DeployedController only supports role='candidate' bundles (got {role!r})"
            )
        unsupported = [k for k in _UNSUPPORTED_BUNDLE_KEYS if settings.get(k)]
        if unsupported:
            raise ValueError(
                f"DeployedController does not support bundle component(s): {', '.join(unsupported)}"
            )
        weights = RunWeights.load(settings["weights"])
        policy = RunPolicy(
            weights,
            macro_seed=macro_seed,
            deck_effects=bool(settings.get("deck_effects", False)),
        )
        combat_v2 = None
        if settings.get("combat_search_v2") or settings.get("combat_search_v2_shadow"):
            from .combat_search_v2.integration import CombatSearchV2

            combat_v2 = CombatSearchV2.from_options(settings)
        return cls(
            policy,
            late_weights=RunWeights.load(settings["late_weights"]) if settings.get("late_weights") else None,
            router=RoomModel.load(settings["room_model"]) if settings.get("room_model") else None,
            late_router=RoomModel.load(settings["late_room_model"]) if settings.get("late_room_model") else None,
            offers=OfferModel.load(settings["offer_model"]) if settings.get("offer_model") else None,
            strategy=StrategyModel.load(settings["strategy_model"]) if settings.get("strategy_model") else None,
            deck_model=DeckPolicy.load(settings["deck_model"]) if settings.get("deck_model") else None,
            encounter=EncounterModel.load(settings["encounter_model"]) if settings.get("encounter_model") else None,
            turn_search=bool(settings.get("turn_search", False)),
            combat_v2=combat_v2,
        )

    def clone(self) -> DeployedController:
        return deepcopy(self)

    def _sync_act(self, state):
        act = (state.get("context") or {}).get("act", self.act)
        if self.pool is None:
            track = (self.strategy and self.strategy.uses_matchups) or getattr(
                self.router, "act1_context", None
            )
            if track and state.get("context"):
                self.pool = WeakEncounterPool(state)
        if act != self.act:
            self.act = act
            if act >= 2 and self.late_weights is not None:
                self.policy.weights = self.late_weights
            if act >= 2 and self.late_router is not None:
                self.router = self.late_router

    def choose(self, state, game):
        self._sync_act(state)
        self._boss_tactics_before = None
        self._last_step_used_encounter = False
        act = (state.get("context") or {}).get("act", self.act)
        combat = is_combat_choice(state)
        if state["decision"] == "map_select" and self.router is not None:
            if act == 3 and getattr(self.router, "act3_context", None):
                action = self.router.choose(state, game.public_map(), normal_count=self.act3_normal_count)
            elif self.pool is not None and getattr(self.router, "act1_context", None):
                action = self.router.choose(state, game.public_map(), normal_count=self.pool.normal_count)
            else:
                action = self.router.choose(state, game.public_map())
        elif self.encounter is not None and self.encounter.applies(state) and combat:
            if state["decision"] == "combat_play":
                self.encounter.prepare(state, self.policy)
                if self.encounter.boss_tactics is not None:
                    self._boss_tactics_before = deepcopy(self.encounter.boss_tactics)
            if self.combat_v2 is None:
                action = self.encounter.choose(state, self.policy)
            else:
                from .combat_search_v2.integration import choose_encounter

                action = choose_encounter(self.combat_v2, self.encounter, state, self.policy, legal_actions)
            self._last_step_used_encounter = True
        elif self.deck_model is not None and not combat and (
            state["decision"] in self.deck_model.scope
            or (
                state["decision"] == "card_select"
                and (self.deck_model.to_upgrade or self.deck_model.prompt)
            )
        ):
            action = self.deck_model.choose(state, self.policy)
        elif self.strategy is not None and strategy_kind(state) in self.strategy.kinds:
            action = self.strategy.choose(
                state,
                self.policy,
                self.offers,
                group_probability=self.pool.group_probability if self.pool else None,
            )
        elif self.turn_search and state["decision"] == "combat_play":
            action = choose_turn(state, self.policy)
        elif self.offers is not None and offer_type(state):
            action = self.offers.choose(state, self.policy)
        else:
            action = self.policy(state)

        corrected = self.paid_relics.corrected_view(state, action)
        if corrected is not None:
            if self.deck_model is not None and "shop" in self.deck_model.scope:
                replacement = self.deck_model.choose(corrected, self.policy)
            elif self.strategy is not None and strategy_kind(corrected) in self.strategy.kinds:
                replacement = self.strategy.choose(
                    corrected,
                    self.policy,
                    self.offers,
                    group_probability=self.pool.group_probability if self.pool else None,
                )
            elif self.offers is not None and offer_type(corrected):
                replacement = self.offers.choose(corrected, self.policy)
            else:
                replacement = self.policy(corrected)
            action = next(a for a in legal_actions(state) if a.command() == replacement.command())
        self._last_proposed_command = action.command()
        return action

    def observe(self, before, action, after):
        """Commit the actually executed action (including forced root arms) to all stateful observers."""
        if self.combat_v2 is not None:
            self.combat_v2.observe(action, after, legal_actions)
        self._sync_act(before)
        if (
            self.encounter is not None
            and before.get("decision") == "combat_play"
            and self.encounter.applies(before)
        ):
            if not self._last_step_used_encounter:
                self.encounter.prepare(before, self.policy)
                if self.encounter.boss_tactics is not None:
                    self.encounter.boss_tactics.observe(action)
            elif (
                self.encounter.boss_tactics is not None
                and self._last_proposed_command is not None
                and action.command() != self._last_proposed_command
            ):
                if self._boss_tactics_before is not None:
                    self.encounter.boss_tactics = self._boss_tactics_before
                self.encounter.boss_tactics.observe(action)
        self._last_proposed_command = None
        self._boss_tactics_before = None
        self._last_step_used_encounter = False

        if before.get("decision") == "rest_site":
            is_smith = any(
                o.get("option_id") == "SMITH" and o["index"] == action.args.get("option_index")
                for o in before.get("options", ())
            )
            self.policy.selection = "upgrade" if is_smith else None
            if self.deck_model is not None and "rest_site" in self.deck_model.scope:
                self.deck_model.to_upgrade = is_smith
        elif self.deck_model is not None and before.get("decision") == "card_select":
            self.deck_model.to_upgrade = False
        if self.deck_model is not None:
            self.deck_model.observe(before, action)
        self.paid_relics.observe(before, action, after)
        act = (before.get("context") or {}).get("act", self.act)
        if act == 3 and action.kind == "select_map_node":
            if (after.get("context") or {}).get("room_type") == "Monster":
                self.act3_normal_count += 1
        if self.pool is not None:
            self.pool.observe(action.kind, after)
        self._sync_act(after)
