"""Frozen Phase 1 utilities in HP-equivalent units."""
from .state import power

VICTORY = 3
SURVIVED = 2
UNRESOLVED = 1
DEAD = 0


def _damage_progress(enemy):
    # In the Giant's eruption phase its displayed HP is infinite until the
    # scripted exit. Attacking that display cannot advance the knockout.
    if enemy.name == "WATERFALL_GIANT" and enemy.max_hp == 999_999_999:
        return 0
    return enemy.max_hp - enemy.hp


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
        progress += _damage_progress(enemy)
    return progress, pressure, deadline


def _boss_adjustment(state):
    """Price public consequences extending beyond this turn for either evaluator."""
    value = 0.0
    for enemy in state.enemies:
        if enemy.hp <= 0:
            continue
        if enemy.name == "THE_INSATIABLE" and (timer := power(enemy.powers, "SANDPIT")):
            # At one tick the next hand must supply an escape or a knockout.
            # Price that obligation without predicting a card in the next draw.
            value -= {1: state.max_hp + 20, 2: 12, 3: 4}.get(timer, 0)
        if enemy.name in ("CRUSHER", "ROCKET") and any(
                other.hp == 0 and other.name in ("CRUSHER", "ROCKET") for other in state.enemies):
            # The surviving arm keeps six Strength. Charge more when it will
            # survive several turns, and for rage block still on the board.
            value -= min(36, enemy.hp / 3) + 0.12 * min(99, enemy.block, enemy.hp)
    if limit := power(state.powers, "SLOTH"):
        # These cards are still in the *simulated* hand. At a completed leaf
        # this can include only known retained cards. Spare play slots are
        # valuable when a high-impact card is still available this turn.
        impact = {"DASH": 4, "PREDATOR": 4, "LEG_SWEEP": 4, "SNAKEBITE": 3, "NOXIOUS_FUMES": 5,
                  "AFTERIMAGE": 5, "MALAISE": 4, "GRAND_FINALE": 5}
        remaining = max(0, limit - state.sloth_plays)
        high = sorted((impact[c.variant.name] for c in state.hand if c.variant.name in impact), reverse=True)
        value += sum(high[:remaining])
    return value


def leaf_value(state, reserve_price, model=None, win_weight=0.0, *, boss_safe=False):
    adjustment = _boss_adjustment(state) if boss_safe and state.outcome == "completed" else 0
    if model is not None and state.outcome == "completed":
        win_probability, win_hp_fraction = model.leaf(state)
        value = win_probability * (state.max_hp * win_hp_fraction + win_weight)
        return SURVIVED, round(value - reserve_price * state.spent + adjustment, 8)
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
    return category, round(utility + adjustment, 8)


def interim(state, reserve_price, *, boss_safe=False):
    """Cheap beam sorting for stable states and compulsory prompts."""
    progress = 0
    pressure = 0
    for enemy in state.enemies:
        progress += _damage_progress(enemy)
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
    adjustment = _boss_adjustment(state) if boss_safe else 0
    return safety - reserve_price * state.spent + adjustment, development + adjustment
