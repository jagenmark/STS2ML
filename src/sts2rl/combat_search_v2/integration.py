"""Opt-in bridge from stamped public choices to the pure beam."""
from collections import Counter
from copy import copy, deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from time import perf_counter_ns

from ..native import NativeError, runtime_identity
from .encounters import encounter_reason
from . import late_encounters
from .end_turn import attack_amount
from .planner import Config, search
from .state import SCHEMA, Unsupported, entry, project, root_move
from .transitions import admission, advance, legal


def _variant_key(variant, outside_actionable_hand=False):
    # Hidden-pile resolved costs can reflect the last hand discount, preview
    # history, or the next reveal. Their card identities remain comparable.
    cost = None if outside_actionable_hand and variant.name != "FRANTIC_ESCAPE" else variant.cost
    target = None if outside_actionable_hand and variant.name == "SHIV" else variant.target
    return (variant.name, variant.kind, cost, target, variant.upgrade,
            variant.keywords, variant.modifier)


def _zone(cards):
    return Counter(_variant_key(card, outside_actionable_hand=True) for card in cards)


def _board(state):
    return (state.hp, state.max_hp, state.block, state.energy, state.max_energy,
            state.round, state.powers, state.relics,
            tuple((e.name, e.hp, e.max_hp, e.block, e.powers) for e in state.enemies if e.hp > 0),
            tuple((p.name, p.target, p.usable, p.stats) for p in state.potions), state.seal_gold)


def _positions(state):
    return (tuple(_variant_key(c.variant) for c in state.hand), _zone(state.draw),
            _zone(state.discard), _zone(state.exhaust), _zone(state.play))


def _intents(state):
    return tuple(tuple((i.kind, i.hits, attack_amount(state, e, i) if i.damage is not None else None)
                       for i in e.intents) for e in state.enemies if e.hp > 0)


def _prompt_signature(state):
    if state.prompt is None:
        return None
    prompt = state.prompt
    if prompt.operation == "KNOWLEDGE_CURSE":
        return (prompt.operation, state.curse_options, prompt.minimum, prompt.maximum)
    positions = {c.slot: i for i, c in enumerate(state.hand)}
    return (prompt.operation, tuple(positions[i] for i in prompt.candidates),
            prompt.minimum, prompt.maximum)


def _normalized_legal(state):
    hand = {c.slot: i for i, c in enumerate(state.hand)}
    enemies = {e.slot: i for i, e in enumerate(e for e in state.enemies if e.hp > 0)}
    potions = {p.slot: i for i, p in enumerate(state.potions)}
    return tuple((m.kind, hand[m.slot] if m.kind == "play_card" else potions.get(m.slot, -1)
                  if m.kind == "use_potion" else -1, enemies.get(m.target, -1),
                  m.selection if state.curse_options else tuple(hand[i] for i in m.selection)) for m in legal(state))


def _native_legal(projected, actions):
    return tuple(root_move(projected, action.kind, action.args) for action in actions)


def _completed_zones(state):
    return (_zone((*state.draw, *state.discard, *(c.variant for c in state.hand))),
            _zone(state.exhaust), _zone(state.play))


def _deadline_escape(public, enumerate_actions):
    if public.get("decision") != "combat_play":
        return None
    ctx = public.get("context") or {}
    if ctx.get("act") != 2 or ctx.get("room_type") != "Boss":
        return None
    if not any(e["id"] == "MONSTER.THE_INSATIABLE" and e["hp"] > 0 and any(
            p["id"] == "POWER.SANDPIT_POWER" and 0 < p["amount"] <= 2 for p in e.get("powers") or ())
            for e in public["enemies"]):
        return None
    escapes = [c for c in public["hand"] if c["id"] == "CARD.FRANTIC_ESCAPE" and c["can_play"]]
    if escapes:
        slot = min(escapes, key=lambda c: (c["cost"], c["index"]))["index"]
        return next(a for a in enumerate_actions(public) if a.kind == "play_card" and a.args["card_index"] == slot)
    return None


def _after_draw_prompt(suspended, public):
    """Resume only the witnessed discard prompt of this just-executed play."""
    if (suspended.boundary.reason != "draw" or public.get("decision") != "card_select"
            or not suspended.queue or suspended.queue[0].kind != "prompt"):
        return None
    current = project(public, late_prompts=True).state if suspended.late else project(public).state
    event, *tail = suspended.queue
    if (current.prompt.operation != event.play.card.variant.name or not tail
            or any(op.kind not in ("after_play", "finish") for op in tail)
            or current.prompt.minimum != current.prompt.maximum
            or current.prompt.minimum != min(len(current.hand), event.amount)
            or _board(suspended) != _board(current) or _intents(suspended) != _intents(current)
            or len(current.hand) != len(suspended.hand) + suspended.boundary.count
            or _completed_zones(suspended) != _completed_zones(current)):
        return None
    # The draw is now public. The queued after-play/finish operations refer
    # only to the source card. Use its public play-zone variant when finishing.
    source, = current.play
    return replace(current, queue=tuple(replace(op, play=replace(op.play,
                   card=replace(op.play.card, variant=source))) for op in tail))


def _difference(predicted, actual):
    """Compare deterministic attributes. Completed turns cross the native reveal."""
    for name, expected, observed in zip(
        ("hp", "max_hp", "block", "energy", "max_energy", "round", "powers", "relics", "enemies", "potions", "seal_gold"),
        _board(predicted), _board(actual),
    ):
        if name == "energy" and predicted.outcome == "completed":
            continue
        if expected != observed:
            return f"board/{name}"
    if predicted.outcome == "completed":
        if predicted.late and (chains := dict(predicted.powers).get("CHAINS_OF_BINDING")):
            count = sum(late_encounters.bound(c.variant) for c in actual.hand)
            if count != min(chains, predicted.boundary.count):
                return "drawn bound count"
            actual = replace(actual, hand=tuple(replace(c, variant=late_encounters.unbind(c.variant))
                                                for c in actual.hand))
        if _completed_zones(predicted) != _completed_zones(actual):
            return "completed zones"
        return ""
    if _positions(predicted) != _positions(actual):
        return "zones"
    if _intents(predicted) != _intents(actual):
        return "intent"
    if _prompt_signature(predicted) != _prompt_signature(actual):
        return "prompt"
    return ""


@lru_cache(maxsize=8)
def _load_value(path, sha256):
    from .artifact import CombatValueModel

    return CombatValueModel.load(path)


class CombatSearchV2:
    def __init__(self, config=Config(), *, shadow=False, record=False, model=None, model_sha256=None):
        self.config = config
        self.shadow = shadow
        self.records = [] if record else None
        self.model = model
        self.model_sha256 = model_sha256
        self.last_fallback = None
        self._prompt = None
        self._decision = None
        self._round_key = None
        self._plays = -1
        self._played_from = None
        self._bound_used = False
        self._aeon_plays = -1
        self._remnant_start_hp = None

    def clone(self):
        clone = copy(self)
        clone.records = deepcopy(self.records)
        return clone

    @classmethod
    def from_options(cls, options, *, record=False):
        act = options.get("combat_search_v2", False)
        shadow = options.get("combat_search_v2_shadow", False)
        if act and shadow:
            raise ValueError("Choose either active or shadow combat search v2")
        path = options.get("combat_search_v2_config")
        config = Config(**json.loads(Path(path).read_bytes())) if path else Config()
        model_path = options.get("combat_value_v2")
        sha256 = hashlib.sha256(Path(model_path).read_bytes()).hexdigest() if model_path else None
        model = _load_value(Path(model_path).resolve(), sha256) if model_path else None
        return cls(config, shadow=shadow, record=record, model=model, model_sha256=sha256)

    def _record(self, record):
        if self.records is not None:
            self.records.append(record)

    def write(self, folder):
        if self.records is None:
            return
        config = asdict(self.config)
        for switch in ("v6_late_coverage", "v61_act2_hallways_act3", "v61_boss_safe"):
            if not config[switch]:
                del config[switch]
        canonical = json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
        metadata = {"schema": SCHEMA, "config": config, "config_sha256": hashlib.sha256(canonical).hexdigest(),
                    "mode": "shadow" if self.shadow else "act"}
        if self.model_sha256 is not None:
            metadata["combat_value_v2_sha256"] = self.model_sha256
        with (Path(folder) / "combat-search-v2.jsonl").open("w", encoding="utf-8") as stream:
            stream.write(json.dumps(metadata, separators=(",", ":")) + "\n")
            for row in self.records:
                stream.write(json.dumps(row, separators=(",", ":")) + "\n")

    def choose(self, public, champion, enumerate_actions, *, facing=None, curse_preferences=None):
        started = perf_counter_ns() if self.records is not None else 0
        projected = None
        previous_prompt, self._prompt = self._prompt, None
        self._decision = None
        result = None
        fallback = ""
        changed = False
        actual = champion
        try:
            if public.get("runtime_identity") != runtime_identity(10):
                raise Unsupported("runtime")
            ctx = public.get("combat_state", public).get("context") or {}
            late_root = self.config.late_root(ctx.get("act"), ctx.get("room_type"))
            projected = project(public, late_prompts=late_root)
            state = projected.state
            if (late_root or self.config.v6_late_coverage) and any(v.name == "RIGHT_HAND_HAND" for v in state.discard):
                state = replace(state, right_hand_return=True)
                projected = replace(projected, state=state)
            if late_root:
                key = (state.act, state.floor, state.round)
                side = projected.enemy_indices.index(facing) if facing in projected.enemy_indices else -1
                if len(state.enemies) == 1 and state.enemies[0].name in ("CRUSHER", "ROCKET"):
                    side = 0
                plays = self._plays if self._round_key == key else -1
                self._played_from = state
                floor = None
                if (self._round_key == key and self._remnant_start_hp is not None and
                        any(r.name == "BEATING_REMNANT" for r in state.relics)):
                    floor = max(0, self._remnant_start_hp - 20)
                projected = replace(projected, state=replace(state, late=True, facing=side, preview_facing=side,
                                                             sloth_plays=plays, bound_used=self._bound_used,
                                                             aeon_plays=self._aeon_plays, tender_plays=plays,
                                                             remnant_floor=floor, v61_rules=self.config.v61_act2_hallways_act3
                                                             or self.config.v61_boss_safe))
            if self.config.v61_boss_safe and state.act == 2 and state.room == "Boss" and state.curse_options:
                # The champion has already selected a physical card in this
                # observed offer. Resume search on the next combat-play root.
                raise Unsupported("champion knowledge curse")
            if projected.state.prompt:
                if previous_prompt is None or _difference(previous_prompt, projected.state):
                    raise Unsupported("unreconciled prompt")
                projected = replace(projected, state=replace(previous_prompt, spent=0))
            actions = enumerate_actions(public)
            moves = _native_legal(projected, actions)
            primary = root_move(projected, champion.kind, champion.args)
            result = search(projected, moves, primary, self.config, model=self.model,
                            record_timing=self.records is not None, curse_preferences=curse_preferences)
            fallback = result.fallback
            changed = result.choice != primary
            if changed and not self.shadow and not fallback:
                actual = actions[moves.index(result.choice)]
            if (result.attempts or result.fallback == "forced") and primary in moves:
                self._decision = projected, moves
        except (Unsupported, NativeError, KeyError, TypeError, ValueError) as error:
            fallback = str(error) if isinstance(error, Unsupported) else f"projection/{type(error).__name__}"
        if (self.config.v61_boss_safe and not self.shadow and public.get("runtime_identity") == runtime_identity(10)
                and not (result and not fallback and result.line and len(result.line.path) == 1
                         and result.line.state.outcome == "victory")):
            escape = _deadline_escape(public, enumerate_actions)
            if escape is not None and escape != actual:
                actual, changed, fallback = escape, escape != champion, "sandpit deadline"
        if self.records is not None:
            view = public.get("combat_state", public)
            formation = [entry(e["id"]) for e in view.get("enemies", ())]
            row = {
                "act": (view.get("context") or {}).get("act"), "formation": formation,
                "decision": public.get("decision"), "fallback": fallback, "changed": changed,
                "ns": perf_counter_ns() - started, "attempts": result.attempts if result else 0,
            }
            if result is not None:
                row.update(roots=result.root_count, covered_roots=result.covered_roots,
                           child_cap=result.child_cap, depth_cap=result.depth_cap,
                           depth=result.reached_depth, dedup=result.duplicates,
                           width_pruned=result.width_pruned, boundaries=dict(result.boundary_counts),
                           no_potion=result.no_potion.score if result.no_potion else None,
                           with_potion=result.with_potion.score if result.with_potion else None)
                if result.leaf_ns is not None:
                    row["leaf_ns"] = result.leaf_ns
            self._record(row)
        self.last_fallback = fallback
        return actual

    def audit_right_hand(self, action, after, enumerate_actions):
        """Evaluate the independent v6 card rule on a frozen choice without updating this controller."""
        if self._decision is None:
            return None
        projected, moves = self._decision
        if not any(v.name == "RIGHT_HAND_HAND" for v in projected.state.discard):
            return None
        observer = copy(self)
        observer.records = [{}]
        observer._decision = replace(projected, state=replace(projected.state, right_hand_return=True)), moves
        observer.observe(action, after, enumerate_actions)
        return observer.records[0].get("oracle")

    def observe(self, action, after, enumerate_actions):
        if self.config.v6_late_coverage or self.config.v61_act2_hallways_act3 or self.config.v61_boss_safe:
            prior, self._played_from = self._played_from, None
            view = after.get("combat_state", after)
            ctx = view.get("context") or {}
            key = (ctx.get("act"), ctx.get("floor"), view.get("round"))
            uncertain = action.kind == "play_card" and (
                prior is None or late_encounters.untracked_plays(prior, prior.hand[action.args["card_index"]].variant))
            if self.config.v61_act2_hallways_act3 or self.config.v61_boss_safe:
                if key != self._round_key:
                    # The cap resets at player-side start. Only witness an
                    # ordinary new turn with no start-turn self-damage.
                    witnessed = ((key[-1] == 1 or (action.kind == "end_turn" and prior and
                                  not dict(prior.powers).get("POISON"))) and
                                 any(r["id"] == "RELIC.BEATING_REMNANT" for r in view.get("player", {}).get("relics", ())))
                    self._remnant_start_hp = view["player"]["hp"] if witnessed else None
                elif self._remnant_start_hp is not None and (uncertain or prior is None or
                        action.kind == "use_potion" or view["player"]["hp"] != prior.hp):
                    self._remnant_start_hp = None
            if key != self._round_key:
                self._plays = 0
                self._bound_used = False
            elif action.kind == "play_card" and self._plays >= 0:
                # Automatic plays and replays may count towards Sloth. Resume at
                # the next observed turn start if their count was not witnessed.
                if uncertain:
                    self._plays = -1
                else:
                    self._plays += 1
            if action.kind == "play_card" and prior and key == self._round_key:
                card = prior.hand[action.args["card_index"]].variant
                self._bound_used |= late_encounters.bound(card)
            if (self._round_key is None or key[:2] != self._round_key[:2]
                    or (view.get("round") == 1 and self._round_key[-1] is None)):
                self._aeon_plays = 0 if view.get("round") == 1 else -1
            elif action.kind == "play_card" and self._aeon_plays >= 0:
                if uncertain:
                    self._aeon_plays = -1
                else:
                    self._aeon_plays += 1
            self._round_key = key
        context, self._decision = self._decision, None
        self._prompt = None
        if context is None:
            return
        projected, moves = context
        state = projected.state
        if encounter_reason(state) or admission(projected):
            return
        try:
            move = root_move(projected, action.kind, action.args)
            if move not in moves:
                return
            predicted = advance(state, move)
        except (Unsupported, ValueError, KeyError):
            return
        evidence = ""
        reason = ""
        if predicted.boundary and not predicted.outcome:
            evidence = "unresolved"
            reason = predicted.boundary.reason
            if reason == "draw" and after.get("decision") == "card_select":
                try:
                    self._prompt = _after_draw_prompt(predicted, after)
                    if self._prompt and predicted.late:
                        self._prompt = replace(self._prompt, late=True, facing=predicted.facing,
                                               preview_facing=predicted.facing, sloth_plays=self._plays,
                                               bound_used=self._bound_used, aeon_plays=self._aeon_plays,
                                               tender_plays=predicted.tender_plays,
                                               remnant_floor=predicted.remnant_floor,
                                               v61_rules=predicted.v61_rules,
                                               right_hand_return=predicted.right_hand_return)
                except (Unsupported, ValueError, KeyError, TypeError):
                    self._prompt = None
        elif predicted.outcome in ("victory", "dead"):
            matches = (after.get("decision") == "game_over" and after["player"]["hp"] == 0
                       if predicted.outcome == "dead" else not after.get("in_combat"))
            evidence = "match" if matches else "mismatch"
            reason = "" if matches else "outcome"
        elif (self.records is not None or predicted.prompt or (predicted.late and predicted.outcome == "completed"
                and after.get("decision") == "card_select")):
            try:
                actual = project(after, late_prompts=predicted.late)
                if predicted.late:
                    actual = replace(actual, state=replace(actual.state, late=True, facing=predicted.facing,
                                     preview_facing=predicted.facing, sloth_plays=self._plays,
                                     bound_used=self._bound_used, aeon_plays=self._aeon_plays,
                                     v61_rules=predicted.v61_rules, tender_plays=self._plays))
                reason = _difference(predicted, actual.state)
                if not reason and not predicted.outcome:
                    expected = _normalized_legal(predicted)
                    native = _native_legal(actual, enumerate_actions(after))
                    if native != legal(actual.state) or expected != _normalized_legal(actual.state):
                        reason = "legality"
                evidence = "mismatch" if reason else "match"
                if (predicted.late and predicted.outcome == "completed" and not reason and actual.state.prompt
                        and actual.state.prompt.operation == "TOASTY_MITTENS"):
                    self._prompt = actual.state
                elif predicted.prompt and not reason:
                    self._prompt = predicted
            except (Unsupported, NativeError, KeyError, ValueError, TypeError) as error:
                evidence, reason = "mismatch", str(error)
        if self.records is not None and evidence:
            mechanic = move.kind
            if move.kind == "play_card":
                mechanic = next(c.variant.name for c in state.hand if c.slot == move.slot)
            elif move.kind == "use_potion":
                mechanic = next(p.name for p in state.potions if p.slot == move.slot)
            elif move.kind == "select_cards":
                mechanic = state.prompt.operation + "/discard"
            self.records[-1]["oracle"] = [mechanic, evidence, reason]
            if evidence == "mismatch":
                # Post-action diagnostics only. The after-board deliberately
                # omits hands, energy and intentions across a turn boundary.
                def summary(board):
                    return {"hp": board.hp, "block": board.block, "powers": board.powers,
                            "enemies": [(e.name, e.hp, e.block, e.powers) for e in board.enemies if e.hp > 0],
                            "relics": [(r.name, r.counter, r.status) for r in board.relics]}

                details = {"floor": state.floor, "round": state.round, "root": summary(state),
                           "expected": summary(predicted), "decision": after.get("decision")}
                try:
                    details["observed"] = summary(project(after).state)
                except (Unsupported, KeyError, ValueError, TypeError):
                    pass
                self.records[-1]["difference"] = details


def choose_encounter(mode, encounter, public, policy, enumerate_actions):
    """Preserve the legacy boss observer if the opt-in arm changes its proposal."""
    if public["decision"] == "combat_play" and not mode.shadow:
        encounter.prepare(public, policy)
    tactics = encounter.boss_tactics
    original_facing = tactics.facing if tactics is not None else None
    champion = encounter.choose(public, policy)
    if mode.config.v61_boss_safe:
        preferences = tactics.plan.get("curse") if tactics is not None else None
        action = mode.choose(public, champion, enumerate_actions, facing=original_facing, curse_preferences=preferences)
    elif mode.config.v6_late_coverage:
        action = mode.choose(public, champion, enumerate_actions, facing=original_facing)
    else:
        action = mode.choose(public, champion, enumerate_actions)
    if tactics is not None and action is not champion:
        tactics.facing = original_facing
        tactics.observe(action)
    return action
