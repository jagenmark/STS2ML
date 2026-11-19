"""Play out one native fight for offline counterfactual labels."""

from .native import legal_actions
from .turn_planning import choose_turn


def fight(game, state, actor, beam=False, first=None):
    room = state["context"]["room_type"]
    floor = state["context"]["floor"]
    round_number = 0
    last_fraction = 1.0
    for _ in range(600):
        if (
            state["decision"] == "game_over"
            or state.get("in_combat") is False
            or state["context"]["floor"] != floor
        ):
            won = state["decision"] != "game_over" or state.get("victory") is True
            return {
                "won": won,
                "hp": state["player"]["hp"] if won else 0,
                "round": round_number,
                "potions": len(state["player"]["potions"]),
                "remaining": 0 if won else last_fraction,
            }
        if state["context"]["room_type"] != room:
            raise ValueError("Combat room changed without a reward or map boundary")
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
            action = first or (
                choose_turn(state, actor) if beam else actor.combat(state, legal_actions(state))
            )
        else:
            action = first or actor(state)
        first = None
        state = game.step(action)
    raise RuntimeError("Fight exceeded the decision budget")
