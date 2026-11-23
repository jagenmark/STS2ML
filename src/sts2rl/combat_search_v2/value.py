"""Frozen Phase 1 utilities in HP-equivalent units."""
from .state import power

VICTORY = 3
SURVIVED = 2
UNRESOLVED = 1
DEAD = 0


def _progress(state):
    progress = 0
    pressure = 0
    deadline = 0
    for enemy in state.enemies:
        if enemy.hp > 0:
            poison = power(enemy.powers, "POISON")
            # Leaving a foe already doomed by the next poison tick is valuable.
            progress += min(enemy.hp, poison) * 0.8
            if poison < enemy.hp:
                pressure += sum((i.damage or 0) * i.hits for i in enemy.intents)
            if sandpit := power(enemy.powers, "SANDPIT"):
                deadline += 9 / sandpit
            progress -= enemy.block * 0.08
        progress += enemy.max_hp - enemy.hp
    return progress, pressure, deadline


def leaf_value(state, reserve_price):
    progress, pressure, deadline = _progress(state)
    persistent = sum(power(state.powers, name) * weight for name, weight in (
        ("AFTERIMAGE", 3.5), ("WELL_LAID_PLANS", 4), ("STRENGTH", 1.5),
        ("DEXTERITY", 1.5), ("INTANGIBLE", 3), ("BUFFER", 2),
    ))
    category = {"victory": VICTORY, "completed": SURVIVED, "dead": DEAD}.get(
        state.outcome, UNRESOLVED)
    utility = state.hp - reserve_price * state.spent
    if category != VICTORY:
        utility += 0.35 * progress - 0.035 * pressure - deadline + persistent
        if category == SURVIVED:
            utility += 0.35 * state.block + 0.22 * len(state.hand)
    return category, round(utility, 8)


def interim(state, reserve_price):
    """Cheap beam sorting for stable states and compulsory prompts."""
    progress = 0
    pressure = 0
    for enemy in state.enemies:
        progress += enemy.max_hp - enemy.hp
        if enemy.hp > 0:
            poison = power(enemy.powers, "POISON")
            progress += min(enemy.hp, poison) * 0.8
            if poison < enemy.hp:
                pressure += sum((i.damage or 0) * i.hits for i in enemy.intents)
            if power(enemy.powers, "SANDPIT") == 1:
                pressure += state.hp + state.block
    setup = 2 * state.energy + 4 * power(state.powers, "BURST") + 3 * power(state.powers, "DUPLICATION")
    safety = state.hp - max(0, pressure - state.block) + 0.6 * setup
    development = progress + setup - reserve_price * state.spent + 0.2 * min(state.block, pressure)
    return safety - reserve_price * state.spent, development
