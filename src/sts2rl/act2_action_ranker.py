"""Rank current legal Act 2 plays with a residual learned from matched native fights."""

from .enemy_forecast import attack_hits
from .run_policy import _cost, _damage, _draw_count, _hits, _power, _shiv_count
from .teacher import incoming


def action_features(state, actions, scores, *, tactical=False):
    enemies = [e for e in state["enemies"] if e["hp"] > 0]
    hand = {c["index"]: c for c in state["hand"]}
    potions = {p["index"]: p for p in state["player"]["potions"]}
    powers = state.get("player_powers") or []
    tender = any(p["id"] == "POWER.TENDER_POWER" for p in powers)
    player = state["player"]
    threat = max(
        0, sum(incoming(e) for e in enemies) - player["block"] - max(0, _power(powers, "PLATING"))
    )
    hp = player["hp"]
    energy = state["energy"]
    early = 1.0 / max(1, state["round"])
    danger = min(2.0, threat / max(1, hp))
    income = min(2.0, threat / 16)
    affordable = sum(c.get("can_play", False) and _cost(c) <= energy for c in hand.values())
    rows = []
    for action, score in zip(actions, scores, strict=True):
        name = action.kind
        is_potion = name == "use_potion"
        c = (
            potions[action.args["potion_index"]]
            if is_potion
            else hand[action.args["card_index"]]
            if name == "play_card"
            else {}
        )
        stats = (
            {k.lower(): v for k, v in (c.get("vars") or {}).items()}
            if is_potion
            else c.get("stats") or {}
        )
        key = c.get("id", "end")
        typ = "potion" if is_potion else c.get("type", "end")
        target = next((e for e in enemies if e["index"] == action.args.get("target_index")), None)
        targets = [target] if target else enemies
        damage = (
            sum(_damage(c, e) for e in targets)
            if c.get("type") == "Attack"
            else stats.get("damage", 0)
            if is_potion
            else 0
        )
        block = stats.get("calculatedblock", stats.get("block", 0))
        poison = stats.get("poisonpower", 0) + 3 * stats.get("poisonperturn", 0)
        weak = stats.get("weakpower", 0)
        cost = 0 if is_potion or not c else energy if c.get("costs_x") else _cost(c)
        features = {
            "id/" + key: 1.0,
            "kind/" + typ: 1.0,
            "deadline/" + typ: danger,
            "early/" + typ: early,
            "safe/" + typ: float(threat == 0),
            "lowhp/" + typ: 1 - hp / max(1, player["max_hp"]),
            "score": min(4.0, max(-4.0, score / 15)),
            "cost": cost / 2,
            "damage": min(4.0, damage / 10),
            "damage/early": damage * early / 15,
            "block": min(4.0, block / 8),
            "useful-block": min(threat, block) / 8,
            "block/danger": min(threat, block) * danger / 8,
            "poison": poison / 4,
            "weak": weak,
            "weak/threat": weak * income,
            "draw": _draw_count(c) / 2 if c else 0,
            "shivs": _shiv_count(c) / 3 if c else 0,
            "potion/count": len(potions) * is_potion / 2,
            "end/options": float(name == "end_turn") * min(5, affordable) / 3,
            "end/risk": float(name == "end_turn") * danger,
            "free/options": float(bool(c) and not is_potion and cost == 0) * min(5, affordable) / 3,
        }
        if target:
            features.update(
                {
                    "target/threat": incoming(target) / 16,
                    "target/kill": float(damage >= target["hp"] + target.get("block", 0)),
                    "target/wounded": 1 - target["hp"] / max(1, target["max_hp"]),
                }
            )
        if tactical:
            drop = stats.get("strengthloss", 0) or (
                stats.get("strengthpower", 0) if key == "POTION.SHACKLING_POTION" else 0
            )
            strength_saved = sum(
                min(incoming(e), drop * attack_hits(e))
                for e in targets
                if not _power(e.get("powers"), "ARTIFACT")
            )
            hits = sum(attack_hits(e) for e in enemies)
            power = float(typ == "Power")
            features.update(
                {
                    "strength-saved": min(threat, strength_saved) / 10,
                    "strength-saved/danger": min(threat, strength_saved) * danger / 10,
                    "power/targets": power * len(enemies) / 3,
                    "power/pressure": power * min(2.5, threat / 13),
                    "denies-block/hits": float(key == "CARD.PANIC_BUTTON") * hits / 4,
                    "draw/energy": _draw_count(c) * max(0, energy - cost) / 4 if c else 0,
                    "potion/pressure": float(is_potion) * min(2.5, threat / 13),
                    "block/multihit": min(threat, block) * min(6, hits) / 30,
                    "kill/immediate-danger": float(
                        bool(target) and damage >= target["hp"] + target.get("block", 0)
                    )
                    * danger,
                }
            )
        if tender and c:
            features.update(
                {
                    "tender/" + typ: 1.0,
                    "tender/multihit": min(5, _hits(c)) / 3 if typ == "Attack" else 0,
                    "tender/damage": damage / 12,
                    "tender/block": min(threat, block) / 8,
                    "tender/shivs": _shiv_count(c) / 3,
                    "tender/energy": cost / max(1, energy),
                }
            )
        rows.append({k: float(v) for k, v in features.items() if v})
    return rows


def rerank(config, state, actions, original, policy):
    scores = policy.combat_scores(state, actions)
    features = action_features(
        state, actions, scores, tactical=config.get("tactical_features", False)
    )
    weights = config["weights"]
    values = [
        config["prior_scale"] * s
        + config["scale"] * sum(weights.get(k, 0) * v for k, v in x.items())
        for s, x in zip(scores, features, strict=True)
    ]
    best = max(range(len(actions)), key=values.__getitem__)
    if values[best] > values[actions.index(original)] + config.get("margin", 0):
        return actions[best]
    return original
