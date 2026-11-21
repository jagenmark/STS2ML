"""Value the next enemy turn using transitions observed in Act 3 training fights."""

from .combat_effects import power
from .enemy_forecast import attack_hits
from .run_policy import _cost, _damage
from .teacher import incoming


def intent_signature(enemy):
    intents = enemy.get("intents") or []
    parts = [i.get("type", "") + (f"/{i.get('hits', 1)}" if "damage" in i else "") for i in intents]
    return "+".join(sorted(parts)) or "none"


def forecast_keys(enemy, round_number):
    name = enemy["id"]
    move = name + "|" + intent_signature(enemy)
    return [move + ("|opening" if round_number == 1 else "|later"), move, name]


def predicted_damage(table, enemy, round_number):
    for key in forecast_keys(enemy, round_number):
        if key in table:
            return table[key]
    return incoming(enemy)


def adjust_for_next_turn(config, state, actions, scores):
    enemies = [e for e in state["enemies"] if e["hp"] > 0]
    next_damage = {
        e["index"]: predicted_damage(config["table"], e, state["round"]) for e in enemies
    }
    threat = sum(incoming(e) for e in enemies)
    next_threat = sum(next_damage.values())
    player = state["player"]
    hp = max(1, player["hp"])
    powers = state.get("player_powers") or []
    need = max(0, threat - player["block"] - max(0, power(powers, "PLATING")))
    next_guard = min(16.0, 1.5 + 0.27 * next_threat)
    pressure = min(1.0, (need + 0.55 * next_threat) / hp)
    hand = {c["index"]: c for c in state["hand"]}
    potions = {p["index"]: p for p in player["potions"]}
    for i, action in enumerate(actions):
        if action.kind == "end_turn":
            continue
        potion = action.kind == "use_potion"
        item = potions[action.args["potion_index"]] if potion else hand[action.args["card_index"]]
        stats = (
            {k.lower(): v for k, v in (item.get("vars") or {}).items()}
            if potion
            else item.get("stats") or {}
        )
        name = item["id"].split(".")[-1]
        correction = 0.0
        # Intangible and carried block can cover an attack announced on the next turn.
        if name in ("WRAITH_FORM", "GHOST_IN_A_JAR") and power(powers, "INTANGIBLE") < 2:
            if stats.get("intangiblepower", 1) >= 2:
                correction += 0.55 * max(0.0, next_threat - 5)
            elif potion and need < 4:
                correction -= 0.35 * next_threat
        if name in ("DODGE_AND_ROLL", "BLUR"):
            carry = stats.get("calculatedblock", stats.get("block", 0))
            if name == "BLUR":
                carry = max(0, player["block"] + carry - threat)
            correction += 0.65 * min(next_threat, carry)
        if (
            name == "PANIC_BUTTON"
            and not power(powers, "ARTIFACT")
            and power(powers, "INTANGIBLE") < 2
        ):
            correction -= next_guard * min(2, stats.get("turns", 1))
        # A scaling power only deals its projected damage if Silent lives to see the ticks.
        if stats.get("poisonperturn"):
            correction -= pressure * min(32.0, 4.0 * stats["poisonperturn"] * len(enemies))
        target = action.args.get("target_index")
        targets = [e for e in enemies if e["index"] == target] if target is not None else enemies
        if item.get("target_type") == "RandomEnemy":
            factor = 1 / max(1, len(targets))
        else:
            factor = 1.0
        for enemy in targets:
            future = next_damage[enemy["index"]]
            enemy_hp = enemy["hp"] + enemy.get("block", 0)
            damage = _damage(item, enemy) if item.get("type") == "Attack" else 0
            if potion and item.get("target_type") in ("AnyEnemy", "AllEnemies"):
                damage = stats.get("damage", 0)
            if damage > 0 and enemy_hp > 0:
                if damage >= enemy_hp:
                    correction += factor * 0.65 * future
                elif len(enemies) > 1:
                    correction += factor * 0.4 * future * min(1.0, damage / enemy_hp)
            if stats.get("weakpower", 0) >= 2 and not power(enemy.get("powers"), "ARTIFACT"):
                if power(enemy.get("powers"), "WEAK") < 2:
                    correction += factor * 0.20 * future
            if power(enemy.get("powers"), "PAPER_CUTS"):
                # Each unblocked hit also removes max HP. Multihit prevention is worth more here.
                save = (
                    stats.get("strengthloss", 0) * attack_hits(enemy)
                    if not power(enemy.get("powers"), "ARTIFACT")
                    else 0
                )
                correction += factor * min(need, save, incoming(enemy)) * 0.28
        cost = 0 if potion else max(0, _cost(item))
        scores[i] += config["weight"] * correction / max(1, cost) ** 0.74
