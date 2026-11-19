"""Public next-turn attack mechanics for Silent A10 on game build 41cef1ea."""
from dataclasses import dataclass

from .combat_effects import debuff_order, landed_debuffs, power


WATERFALL_GIANT = "MONSTER.WATERFALL_GIANT"
# The native game displays infinite HP after the first knockout.
_INFINITE_HP = 999_999_999


def attack_hits(enemy):
    """The native exporter puts damage fields on AttackIntent subclasses, including DeathBlow."""
    return sum(
        intent.get("hits", 1) for intent in enemy.get("intents") or ()
        if "damage" in intent or "total_damage" in intent
        or "Attack" in intent.get("type", "") or intent.get("type") == "DeathBlow"
    )


def waterfall_final_phase(enemy):
    return enemy.get("id") == WATERFALL_GIANT and enemy.get("max_hp") == _INFINITE_HP


@dataclass(frozen=True, slots=True)
class GiantForecast:
    normal_damage: int | None  # Next intent if this ordinary move executes.
    eruption_damage: int | None  # Base damage if the Giant is defeated before that move.
    eruption_forced: bool
    final_phase: bool = False

    @property
    def certain_damage(self):
        if self.eruption_forced:
            return self.eruption_damage
        if self.eruption_damage is None:
            return self.normal_damage
        return None


def waterfall_forecast(enemy, round_number, *, hp_loss=0, added_poison=0, accelerant=0):
    """One enemy turn ahead. hp_loss is direct damage already resolved against block.

    DeathBlow in the current intent is due this turn. Its native preview already
    includes damage modifiers, and the Giant removes itself after the attack.
    """
    if enemy.get("id") != WATERFALL_GIANT or enemy["hp"] <= 0:
        return None
    intents = {i["type"] for i in enemy.get("intents") or ()}
    stacks = power(enemy.get("powers"), "STEAM_ERUPTION")
    if "DeathBlow" in intents:
        return GiantForecast(None, None, False, final_phase=True)
    if waterfall_final_phase(enemy):
        winding_up = intents == {"Stun"} and stacks > 0
        return GiantForecast(None, stacks if winding_up else None, winding_up, final_phase=True)
    # Poison bypasses block. Each extra trigger spends one stack before the next tick.
    poison = max(0, power(enemy.get("powers"), "POISON") + added_poison)
    ticks = min(poison, 1 + max(0, accelerant))
    poison_loss = ticks * poison - ticks * (ticks - 1) // 2
    if power(enemy.get("powers"), "INTANGIBLE") > 0:
        poison_loss = ticks
    knockout = hp_loss + poison_loss >= enemy["hp"]
    if stacks <= 0:
        normal = 16 if round_number == 1 and intents == {"Buff"} and not knockout else None
        return GiantForecast(normal, None, False)

    # Pressurize gives 20 at A10. Each completed ordinary move adds three.
    # Using the displayed stack count keeps the cycle aligned across an ordinary stun.
    completed, remainder = divmod(stacks - 20, 3)
    normal = None
    if completed >= 0 and remainder == 0:
        phase = completed % 5
        expected = ({"Attack", "Buff", "Debuff"}, {"Attack", "Buff"}, {"Heal", "Buff"},
                    {"Attack", "Buff"}, {"Attack", "Buff"})
        if intents == expected[phase]:
            normal = (11, 0, 23 + 5 * (completed // 5), 14, 16)[phase]
    return GiantForecast(normal, stacks, knockout)


def solo_waterfall_forecast(state, enemies):
    if len(enemies) != 1 or enemies[0].get("id") != WATERFALL_GIANT:
        return None
    return waterfall_forecast(enemies[0], state["round"],
                              accelerant=power(state.get("player_powers"), "ACCELERANT"))


def eruption_intangible_savings(forecast, duration, gained):
    """Extra protection on the *next* player turn from extending Intangible through the wind-up."""
    if forecast and forecast.eruption_forced and duration < 2 <= duration + gained:
        return max(0, forecast.eruption_damage - 1)
    return 0


def waterfall_after_card(enemy, round_number, card, *, accelerant=0):
    """Lower bound for one targeted Silent card, before any further decisions or draws."""
    name = card.get("id")
    hp_loss = 0
    if name in {"CARD.STRIKE_SILENT", "CARD.DASH", "CARD.NEUTRALIZE", "CARD.SUCKER_PUNCH",
                "CARD.SHIV", "CARD.DAGGER_THROW", "CARD.POISONED_STAB"}:
        preview = next((p for p in card.get("damage_by_target") or []
                        if p["target_index"] == enemy["index"]), {})
        damage = preview.get("total_damage", preview.get("damage", 0))
        if power(enemy.get("powers"), "INTANGIBLE") > 0:
            damage = min(1, damage)
        if power(enemy.get("powers"), "BUFFER") <= 0:
            hp_loss = max(0, damage - enemy.get("block", 0))
    added_poison = 0
    if name in {"CARD.DEADLY_POISON", "CARD.POISONED_STAB"}:
        applications = debuff_order(card, card.get("stats") or {}, enemy)
        effects = landed_debuffs(card, applications, power(enemy.get("powers"), "ARTIFACT"))
        added_poison = effects.get("poison", 0)
    return waterfall_forecast(enemy, round_number, hp_loss=hp_loss, added_poison=added_poison,
                              accelerant=accelerant)
