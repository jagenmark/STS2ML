"""Estimate persistent Silent effects from visible card text variables and the current deck."""

from .combat_effects import power

def deck_engines(deck):
    shivs = poison = 0
    for card in deck:
        stats = card.get("stats") or {}
        if card.get("id") in ("CARD.CLOAK_AND_DAGGER", "CARD.BLADE_DANCE", "CARD.UP_MY_SLEEVE"):
            shivs += stats.get("cards", 0)
        shivs += stats.get("shivs", 0)
        poison += stats.get("poisonpower", 0) + 2 * stats.get("poisonperturn", 0)
    return shivs, poison


def persistent_value(card, engines):
    stats = card.get("stats") or {}
    shivs, poison = engines
    value = (3.5 * stats.get("afterimagepower", 0) + 2 * stats.get("thornspower", 0)
             + 2.5 * stats.get("speedsterpower", 0) + min(4, shivs) * stats.get("accuracypower", 0)
             + min(3, shivs) * stats.get("phantombladespower", 0)
             + min(9, poison) * stats.get("accelerant", 0))
    if card.get("id") == "CARD.INFINITE_BLADES":
        value += 5
    return value


def hand_value(card, state, enemies, engines, incoming, block_weight):
    stats = card.get("stats") or {}
    name = card.get("id")
    threats = [incoming(e) for e in enemies]
    need = max(0, sum(threats) - state["player"]["block"])
    hit_counts = [sum(i.get("hits", 1) for i in (e.get("intents") or []) if i.get("type") == "Attack") for e in enemies]
    hits = sum(hit_counts)
    bonus = persistent_value(card, engines) * (1.8 if state["context"]["room_type"] in ("Boss", "Elite") else 1)
    if stats.get("intangiblepower", 0):
        has_intangible = any(p["id"] == "POWER.INTANGIBLE_POWER" for p in state.get("player_powers") or [])
        bonus += (2 if has_intangible else max(0, need - hits)) * block_weight
    if stats.get("strengthloss", 0):
        drop = stats["strengthloss"]
        exposed = [power(e.get("powers"), "ARTIFACT") <= 0 for e in enemies]
        prevention = sum(min(threat, drop * count) for threat, count, ok in zip(threats, hit_counts, exposed, strict=True) if ok)
        old = drop * sum(e.get("intends_attack", False) for e, ok in zip(enemies, exposed, strict=True) if ok)
        bonus += block_weight * (min(need, prevention) - min(need, old))
    if name == "CARD.BULLET_TIME":
        energy_saved = sum(min(3, max(0, c.get("cost", 0))) for c in state["hand"]
                           if c["index"] != card["index"] and c.get("type") in ("Attack", "Skill", "Power"))
        bonus += 3.5 * max(0, energy_saved - state["energy"] + card["cost"])
    return bonus
