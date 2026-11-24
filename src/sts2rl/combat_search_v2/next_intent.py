"""Public next-intent rules on completed A10 states, before the next draw."""
from ..enemy_forecast import waterfall_forecast
from .state import Intent, power


def attack(base, hits=1, *effects):
    return (Intent("Attack", base, hits), *(Intent(kind) for kind in effects))


def effects(*names):
    return tuple(Intent(name) for name in names)


# Current intent types and hit counts uniquely identify these ordinary moves.
_CYCLES = {
    "VANTOM": (attack(8), attack(7, 2), attack(30, 1, "StatusCard"), effects("Buff")),
    "SOUL_FYSH": (effects("StatusCard"), attack(18), attack(8, 1, "StatusCard"),
                  effects("Buff"), attack(15, 1, "Debuff")),
    "LOUSE_PROGENITOR": (attack(10, 1, "Debuff"), effects("Defend", "Buff"), attack(16)),
    "THE_INSATIABLE": (attack(9, 2), attack(31), effects("Buff")),
    "LAGAVULIN_MATRIARCH": (attack(21), attack(10, 2), attack(14, 1, "Defend"), effects("Debuff", "Buff")),
}


COVERED = frozenset(_CYCLES) | {"WATERFALL_GIANT", "CEREMONIAL_BEAST", "SLUMBERING_BEETLE",
                                "TUNNELER", "SHRINKER_BEETLE"}


def _signature(intents):
    return tuple((i.kind, i.hits) for i in intents)


def _base(state, enemy):
    """The enemy still carries its executed intent. Powers are already ticked."""
    kinds = tuple(i.kind for i in enemy.intents)
    if enemy.name == "WATERFALL_GIANT":
        steam = power(enemy.powers, "STEAM_ERUPTION")
        if enemy.max_hp == 999_999_999 or steam < 20:
            return None
        prior = steam - 3 if steam > 20 else 0
        public = {"id": "MONSTER.WATERFALL_GIANT", "hp": enemy.hp, "max_hp": enemy.max_hp,
                  "intents": [{"type": k} for k in kinds],
                  "powers": [{"id": "POWER.STEAM_ERUPTION_POWER", "amount": prior}]}
        prediction = waterfall_forecast(public, state.round - 1)
        base = prediction.normal_damage
        if base is None:
            return None
        if base == 0:
            return effects("Heal", "Buff")
        return attack(base, 1, "Debuff", "Buff") if (steam - 20) % 15 == 0 else attack(base, 1, "Buff")
    if enemy.name == "CEREMONIAL_BEAST" and power(enemy.powers, "PLOW") and kinds in (
            ("Buff",), ("Attack", "Buff")):
        return attack(20, 1, "Buff")
    if enemy.name == "LAGAVULIN_MATRIARCH" and kinds == ("Sleep",):
        return effects("Sleep") if power(enemy.powers, "ASLEEP") else attack(21)
    if enemy.name == "THE_INSATIABLE":
        if kinds == ("Buff", "StatusCard"):
            return attack(9, 2)
        # The two successive multiattacks later in the loop share a telegraph.
        # Only the first opening multiattack has an unambiguous successor.
        if kinds == ("Attack",) and enemy.intents[0].hits == 2 and state.round != 3:
            return None
    if enemy.name == "SLUMBERING_BEETLE" and kinds in (("Sleep",), ("Attack", "Buff")):
        return effects("Sleep") if power(enemy.powers, "SLUMBER") else attack(18, 1, "Buff")
    if enemy.name == "TUNNELER":
        if kinds in (("Attack",), ("Buff", "Defend")) and power(enemy.powers, "BURROWED"):
            return attack(26)
        if kinds == ("Attack",):
            return effects("Buff", "Defend")
    if enemy.name == "SHRINKER_BEETLE":
        if kinds == ("DebuffStrong",):
            return attack(8)
        if kinds == ("Attack",):
            # Invert the old public preview only when it identifies one move.
            previous = [n for n in (8, 14) if _shown(n, enemy.preview_strength, enemy.preview_weak,
                        state.preview_vulnerable, state.preview_intangible, state) == enemy.intents[0].damage]
            if len(previous) == 1:
                return attack(14 if previous[0] == 8 else 8)
    cycle = _CYCLES.get(enemy.name, ())
    for index, current in enumerate(cycle):
        if _signature(current) == _signature(enemy.intents):
            return cycle[(index + 1) % len(cycle)]
    return None


def _shown(base, strength, weak, vulnerable, intangible, state):
    factor = (12 if any(r.name == "PAPER_KRANE" and not r.used for r in state.relics) else 15) if weak else 20
    damage = max(0, base + strength) * factor * (3 if vulnerable else 2) // 40
    return min(1, damage) if intangible else damage


def next_intent(state, enemy):
    """Return a new public preview or None for an uncertified branch."""
    if state.outcome != "completed" or not enemy.hp or power(state.powers, "SURROUNDED"):
        return None
    intents = _base(state, enemy)
    if intents is None:
        return None
    return tuple(i if i.damage is None else Intent(i.kind, _shown(i.damage, power(enemy.powers, "STRENGTH"),
                 power(enemy.powers, "WEAK") > 0, power(state.powers, "VULNERABLE") > 0,
                 power(state.powers, "INTANGIBLE") > 0, state), i.hits) for i in intents)
