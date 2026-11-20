"""Complete a native fight and record survival and resources carried out."""


def outcome(game, state, actor, macro):
    room = state["context"]["room_type"]
    remaining = 1.0
    turns = 0
    for _ in range(500):
        if state["decision"] == "game_over" or not state.get("in_combat"):
            won = state["decision"] != "game_over" or state.get("victory") is True
            return {
                "won": won,
                "hp": state["player"]["hp"] if won else 0,
                "potions": len(state["player"]["potions"]),
                "rounds": turns,
                "remaining": 0 if won else remaining,
            }
        if state["context"]["room_type"] != room:
            raise ValueError("Unconfirmed combat boundary")
        if state["decision"] == "combat_play":
            enemies = [e for e in state["enemies"] if e["hp"] > 0]
            remaining = sum(e["hp"] for e in enemies) / max(1, sum(e["max_hp"] for e in enemies))
            turns = state["round"]
        state = game.step(actor.choose(state, macro))
    raise ValueError("Combat exceeded 500 real decisions")
