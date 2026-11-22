"""Escape-aware native fight rollout for v2 counterfactual combat labels."""

from __future__ import annotations

from .encounter import EncounterModel
from .native import legal_actions
from .turn_planning import choose_turn


def _is_smoke_bomb(state, action):
    if action.kind != "use_potion":
        return False
    slot = action.args.get("potion_index")
    for potion in state.get("player", {}).get("potions") or ():
        if potion["index"] == slot:
            return "SMOKE_BOMB" in potion.get("id", "")
    return False


def fight_v2(game, state, actor, *, beam=False, survival_beam=False, first=None, base_policy=None):
    """Play out one fight, distinguishing Smoke Bomb escapes from true combat victories."""
    if isinstance(actor, EncounterModel) and base_policy is None:
        raise ValueError("fight_v2 with an EncounterModel requires base_policy")
    room = state["context"]["room_type"]
    floor = state["context"]["floor"]
    round_number = 0
    last_fraction = 1.0
    escaped_action = False
    for _ in range(600):
        if (
            state["decision"] == "game_over"
            or state.get("in_combat") is False
            or state["context"]["floor"] != floor
        ):
            if state["decision"] == "game_over":
                won = state.get("victory") is True
                escaped = False
            elif escaped_action:
                won = False
                escaped = True
            else:
                won = True
                escaped = False
            return {
                "schema": "fight-outcome-v2",
                "won": won,
                "escaped": escaped,
                "hp": state["player"]["hp"] if (won or escaped) else 0,
                "round": round_number,
                "potions": len(state["player"]["potions"]),
                "remaining": 0.0 if won else last_fraction,
            }
        if state["context"]["room_type"] != room:
            raise ValueError("Combat room changed without a reward or map boundary")
        # If Smoke Bomb was attempted on a previous step and combat continued, clear escape flag.
        escaped_action = False
        if state["decision"] == "combat_play":
            alive = [e for e in state["enemies"] if e["hp"] > 0]
            main = [
                e
                for e in alive
                if not any(p["id"] == "POWER.MINION_POWER" for p in e.get("powers") or [])
            ] or alive
            if main:
                last_fraction = sum(e["hp"] for e in main) / max(1, sum(e["max_hp"] for e in main))
            round_number = state["round"]
            if first is not None:
                if isinstance(actor, EncounterModel):
                    actor.prepare(state, base_policy)
                    if actor.boss_tactics is not None:
                        actor.boss_tactics.observe(first)
                action = first
            elif isinstance(actor, EncounterModel):
                action = actor.choose(state, base_policy)
            elif beam or survival_beam:
                action = choose_turn(state, actor, survival_priority=survival_beam)
            else:
                action = actor.combat(state, legal_actions(state))
        else:
            if first is not None:
                action = first
            elif isinstance(actor, EncounterModel):
                action = actor.choose(state, base_policy)
            else:
                action = actor(state)
        first = None
        escaped_action = _is_smoke_bomb(state, action)
        state = game.step(action)
    raise RuntimeError("Fight exceeded the decision budget")
