"""Two-turn card and potion values for the visible Mecha Knight attack cycle."""

from .act3_combat import affordable_hits
from .combat_effects import block_preview, debuff_order, landed_debuffs, power
from .run_policy import _cost, _damage
from .teacher import incoming


def phase(state, windup_round=0):
    if state.get("decision") != "combat_play":
        return None
    ctx = state["context"]
    if ctx["act"] != 3 or ctx["room_type"] != "Elite":
        return None
    living = [e for e in state["enemies"] if e["hp"] > 0]
    if len(living) != 1 or living[0]["id"] != "MONSTER.MECHA_KNIGHT":
        return None
    intents = {i["type"] for i in living[0].get("intents") or []}
    if intents == {"Defend", "Buff"}:
        return "windup"
    if intents == {"Attack"} and windup_round and state["round"] > windup_round:
        return "cleave"
    return None


def burn_damage(hand):
    return sum(max(0, c.get("stats", {}).get("damage", 2)) for c in hand if c["id"] == "CARD.BURN")


def block_in_hand(hand, energy):
    values = [0] * (energy + 1)
    for card in hand:
        cost = _cost(card)
        block = block_preview(card.get("stats") or {})
        if not card.get("can_play") or not block or cost > energy:
            continue
        for n in range(energy, cost - 1, -1):
            values[n] = max(values[n], values[n - cost] + block)
    return values[-1]


def item_features(state, actions, stage):
    """Estimate marginal effects using visible previews, hand contents and current powers."""
    player, hand = state["player"], state["hand"]
    enemy = next(e for e in state["enemies"] if e["hp"] > 0)
    powers = state.get("player_powers") or []
    ep = enemy.get("powers") or []
    artifacts = power(ep, "ARTIFACT")
    strength = power(ep, "STRENGTH")
    energy = state["energy"]
    hp = player["hp"]
    burn = burn_damage(hand)
    shield = player["block"] + max(0, power(powers, "PLATING"))
    wound = sum(c["id"] == "CARD.BURN" for c in hand)
    protected = power(powers, "INTANGIBLE")
    wind = stage == "windup"
    # The pinned A10 move gains five Strength before its base-40 single hit.
    cleave = 45 + strength if wind else incoming(enemy)
    if wind and power(ep, "WEAK") >= 2:
        cleave = int(cleave * 0.75)
    if wind and power(powers, "VULNERABLE") >= 2:
        cleave = int(cleave * 1.5)
    present = 0 if wind else incoming(enemy)
    if protected:
        present = min(1, present)
        burn = min(wound, burn)
    uncovered = max(0, present + burn - shield)
    burn_exposure = min(burn, uncovered)
    potential = block_in_hand(hand, energy)
    expected = max(0, uncovered - potential)
    cards = {c["index"]: c for c in hand}
    pots = {p["index"]: p for p in player["potions"]}
    for a in actions:
        if a.kind == "end_turn":
            yield {}
            continue
        potion = a.kind == "use_potion"
        item = pots[a.args["potion_index"]] if potion else cards[a.args["card_index"]]
        name = item["id"].split(".")[-1]
        stats = (
            {k.lower(): v for k, v in (item.get("vars") or {}).items()}
            if potion
            else item.get("stats") or {}
        )
        cost = 0 if potion else _cost(item)
        block = block_preview(stats)
        benefit = {"burn": 0.0, "carry": 0.0, "potions": 0.0, "attack": 0.0, "guard": 0.0}
        benefit["burn"] = min(block, burn_exposure)
        discard = (
            wound
            if name in ("CALCULATED_GAMBLE", "STORM_OF_STEEL", "GAMBLERS_BREW", "GLOWWATER_POTION")
            else min(wound, stats.get("cards", 1) if name == "PREPARED" else 1)
            if name
            in (
                "SURVIVOR",
                "PREPARED",
                "ACROBATICS",
                "DAGGER_THROW",
                "HIDDEN_DAGGERS",
                "TOOLS_OF_THE_TRADE",
            )
            else 0
        )
        if wind:
            benefit["burn"] += min(burn_exposure, 2 * discard)
            if name in ("DODGE_AND_ROLL", "TORIC_TOUGHNESS", "SHIP_IN_A_BOTTLE"):
                benefit["carry"] += min(cleave, block)
            if name == "BLUR":
                benefit["carry"] += min(cleave, max(0, shield + block - burn))
            if power(powers, "BLUR") or power(powers, "BARRICADE"):
                benefit["carry"] += min(block, max(0, cleave - shield + burn))
            if name == "WRAITH_FORM" and stats.get("intangiblepower", 0) >= 2 and protected < 2:
                benefit["carry"] += max(0, cleave - 3) * 0.8
            if name == "PANIC_BUTTON" and not power(powers, "ARTIFACT") and protected < 2:
                benefit["carry"] -= min(23, cleave * 0.48)
            weak = landed_debuffs(
                item, debuff_order(item, stats, enemy, energy=energy), artifacts
            ).get("weak", 0)
            if weak + power(ep, "WEAK") >= 2 and power(ep, "WEAK") < 2:
                benefit["carry"] += cleave * 0.25
            if stats.get("dexteritypower", 0) and name not in ("SPEED_POTION", "ANTICIPATE"):
                benefit["carry"] += min(12, 2.1 * stats["dexteritypower"])
            if stats.get("energynextturn", 0):
                benefit["carry"] += 6 * stats["energynextturn"]
            draw = (
                stats.get("cards", 0)
                if name in ("SWIFT_POTION", "GLOWWATER_POTION", "PREPARED", "ACROBATICS")
                else stats.get("draw", 0)
            )
            if energy > cost:
                benefit["attack"] += min(wound, 3) * min(draw, 3) * 1.7
            if item.get("type") == "Attack":
                benefit["attack"] += 0.32 * _damage(item, enemy)
        else:
            benefit["guard"] = min(uncovered, block) * (0.35 + min(1.4, uncovered / max(1, hp)))
        if potion:
            if name in ("GHOST_IN_A_JAR", "LUCKY_TONIC"):
                if wind:
                    benefit["potions"] -= max(8, min(cleave, 40) * 0.8)
                elif not protected and not power(powers, "BUFFER"):
                    benefit["potions"] += max(0, expected - 1) * 0.9
            elif name == "BLOCK_POTION":
                benefit["potions"] += (
                    min(block, expected) if not wind else -min(10, max(0, block - burn_exposure))
                )
            elif name in ("SWIFT_POTION", "GLOWWATER_POTION", "GAMBLERS_BREW"):
                if wind and energy:
                    benefit["potions"] += min(3, wound) * min(3, energy) * 2.5
                elif not wind and energy:
                    benefit["potions"] += min(17, expected) * 0.75
            elif name == "ENERGY_POTION":
                excess = max(
                    0,
                    sum(_cost(c) for c in hand if c["type"] in ("Attack", "Skill", "Power"))
                    - energy,
                )
                benefit["potions"] += min(stats.get("energy", 2), excess) * (3.5 if wind else 5.5)
            elif name == "FLEX_POTION":
                benefit["potions"] += (
                    min(32, affordable_hits(hand, energy, 1) * stats.get("strengthpower", 0)) * 0.8
                )
            elif name in ("WEAK_POTION", "FEAR_POTION", "VULNERABLE_POTION") and artifacts:
                benefit["potions"] -= 8
            if stats.get("damage", 0) >= enemy["hp"] + enemy.get("block", 0) and item.get(
                "target_type"
            ) in ("AnyEnemy", "AllEnemies"):
                benefit["potions"] += 40
        denom = max(1, cost) ** 0.74
        yield {k: v / denom for k, v in benefit.items()}


class MechaTactics:
    def __init__(self, plan):
        self.plan = plan
        self.windup_round = 0

    def observe(self, state):
        stage = phase(state, self.windup_round)
        if stage == "windup":
            self.windup_round = state["round"]
        return stage

    def adjust(self, state, actions, scores):
        stage = self.observe(state)
        if not stage:
            return
        weights = self.plan.get("weights", {})
        for i, features in enumerate(item_features(state, actions, stage)):
            scores[i] += sum(weights.get(k, 0) * v for k, v in features.items())
