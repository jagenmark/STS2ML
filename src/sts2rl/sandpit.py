"""Reserve energy for Frantic Escape while The Insatiable's public timer is low."""

from .run_policy import _cost, _damage, _power


def escape_action(state, actions, original, threshold):
    if not threshold or state.get("decision") != "combat_play":
        return original
    enemy = next((e for e in state["enemies"] if e["id"] == "MONSTER.THE_INSATIABLE"), None)
    if enemy is None:
        return original
    countdown = _power(enemy.get("powers"), "SANDPIT")
    if not 0 < countdown <= threshold:
        return original
    hand = {c["index"]: c for c in state["hand"]}
    escapes = [
        a
        for a in actions
        if a.kind == "play_card" and hand[a.args["card_index"]]["id"] == "CARD.FRANTIC_ESCAPE"
    ]
    if not escapes or original.kind == "use_potion":
        return original
    escape = min(escapes, key=lambda a: _cost(hand[a.args["card_index"]]))
    if original.kind == "play_card":
        card = hand[original.args["card_index"]]
        if _damage(card, enemy) >= enemy["hp"] + enemy.get("block", 0):
            return original
        cost = state["energy"] if card.get("costs_x") else _cost(card)
        if state["energy"] - cost >= _cost(hand[escape.args["card_index"]]):
            return original
    if _power(enemy.get("powers"), "POISON") >= enemy["hp"]:
        return original
    return escape
