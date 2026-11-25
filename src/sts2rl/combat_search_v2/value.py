"""Frozen Phase 1 utilities in HP-equivalent units."""
from .state import power

VICTORY = 3
SURVIVED = 2
UNRESOLVED = 1
DEAD = 0
SLOTH_RETAIN_VALUE = {"DASH": 4, "PREDATOR": 4, "LEG_SWEEP": 4, "SNAKEBITE": 3, "NOXIOUS_FUMES": 5,
                      "AFTERIMAGE": 5, "MALAISE": 4, "GRAND_FINALE": 5}


def _damage_progress(enemy):
    # In the Giant's eruption phase its displayed HP is infinite until the
    # scripted exit. Attacking that display cannot advance the knockout.
    if enemy.name == "WATERFALL_GIANT" and enemy.max_hp == 999_999_999:
        return 0
    return enemy.max_hp - enemy.hp


def _poison_damage(enemy, poison, accelerant):
    """Next enemy-side start, with diminishing ticks and the public HP cap."""
    ticks = min(poison, 1 + accelerant)
    if ticks and any(name in ("INTANGIBLE", "SLIPPERY", "HARD_TO_KILL", "BUFFER") for name, _ in enemy.powers):
        from .transitions import lose_hp

        hp, block, powers = enemy.hp, enemy.block, enemy.powers
        for i in range(ticks):
            hp, block, powers = lose_hp(hp, block, powers, poison - i, bypass=True)
        return enemy.hp - hp
    return min(enemy.hp, ticks * poison - ticks * (ticks - 1) // 2)


_SHIV_SOURCES = {"BLADE_DANCE", "CLOAK_AND_DAGGER", "HIDDEN_DAGGERS", "LEADING_STRIKE", "INFINITE_BLADES"}
_POISON_SOURCES = {"DEADLY_POISON", "POISONED_STAB", "SNAKEBITE", "BOUNCING_FLASK", "NOXIOUS_FUMES", "ENVENOM"}
_DRAW_SOURCES = {"ACROBATICS", "ADRENALINE", "BACKFLIP", "CALCULATED_GAMBLE", "DAGGER_THROW", "ESCAPE_PLAN", "PREPARED"}
_BLOCK_SOURCES = {"DEFEND_SILENT", "DEFLECT", "BACKFLIP", "BLUR", "DASH", "DODGE_AND_ROLL", "HAND_TRICK",
                  "CLOAK_AND_DAGGER", "SURVIVOR", "LEG_SWEEP"}
_SCALING = {"ACCELERANT", "NOXIOUS_FUMES", "ACCURACY", "PHANTOM_BLADES", "INFINITE_BLADES",
            "ENVENOM", "THORNS", "A_THOUSAND_CUTS", "SERPENT_FORM", "TOOLS_OF_THE_TRADE", "BLUR",
            "AFTERIMAGE", "DEXTERITY"}


def _power_value(state, *, value_v68=False):
    """Discount future uses by public HP remaining and density in the live piles."""
    extra = {"WELL_LAID_PLANS", "TRACKING", "SPEEDSTER", "BLOCK_NEXT_TURN", "SHADOW_STEP",
             "DOUBLE_DAMAGE", "FREE_SKILL", "CORROSIVE_WAVE", "SHADOWMELD"} if state.silent_cards_v66 else ()
    if state.silent_cards_v67:
        extra = {*extra, "MASTER_PLANNER", "WRAITH_FORM", "INTANGIBLE"}
    if not any(name in _SCALING or name in extra for name, _ in state.powers):
        return 0.0
    p = dict(state.powers)
    living = [e for e in state.enemies if e.hp > 0]
    poison = sum(power(e.powers, "POISON") for e in living)
    remaining = sum(min(180, e.hp - _poison_damage(e, power(e.powers, "POISON"), p.get("ACCELERANT", 0)))
                    for e in living)
    # One ordinary damage turn has little setup runway. Cap the discounted
    # horizon so a boss's large health pool cannot justify arbitrary HP loss.
    turns = min(4.0, max(0, remaining - 14) / 22)
    immediate = 0.0
    if state.silent_cards_v66:
        immediate += 0.6 * p.get("BLOCK_NEXT_TURN", 0) + 2 * p.get("FREE_SKILL", 0)
        immediate += 3 * (p.get("DOUBLE_DAMAGE", 0) + p.get("SHADOW_STEP", 0))
        if state.energy >= 0:
            playable = [c.variant for c in state.hand if 0 <= c.variant.cost <= state.energy]
            extra_draw = sum(c.name in _DRAW_SOURCES for c in playable) if not p.get("NO_DRAW") else 0
            immediate += 0.7 * p.get("CORROSIVE_WAVE", 0) * min(3, extra_draw) * len(living)
            immediate += p.get("SHADOWMELD", 0) * min(4, 2 * sum(c.name in _BLOCK_SOURCES for c in playable))
    if not turns:
        return immediate
    cards = (*state.draw, *state.discard, *(c.variant for c in state.hand))
    fraction = 5 / max(5, len(cards))
    shivs = min(3, p.get("INFINITE_BLADES", 0) + fraction * sum(
        2 if c.name in _SHIV_SOURCES else int(c.name == "SHIV") for c in cards))
    fumes = p.get("NOXIOUS_FUMES", 0)
    venom = p.get("ENVENOM", 0)
    supply = min(4, poison / 3 + fumes + venom + 4 * fraction * sum(c.name in _POISON_SOURCES for c in cards))
    per_turn = (0.65 * fumes * len(living) + 0.65 * p.get("ACCELERANT", 0) * supply
                + 0.35 * (p.get("ACCURACY", 0) * shivs + p.get("PHANTOM_BLADES", 0) * min(1, shivs))
                + 1.4 * p.get("INFINITE_BLADES", 0)
                + 0.65 * venom * min(3, fraction * sum(c.kind == "Attack" for c in cards))
                + 0.5 * p.get("THORNS", 0) + 1.05 * p.get("A_THOUSAND_CUTS", 0) * len(living)
                + 1.05 * p.get("SERPENT_FORM", 0) + p.get("TOOLS_OF_THE_TRADE", 0)
                + 1.6 * p.get("AFTERIMAGE", 0) + 0.8 * p.get("DEXTERITY", 0))
    if state.silent_cards_v66:
        per_turn += (2.2 * bool(p.get("WELL_LAID_PLANS")) + 0.025 * p.get("TRACKING", 0)
                     * min(2, sum(bool(power(e.powers, "WEAK")) for e in living))
                     + 0.6 * p.get("SPEEDSTER", 0))
    if state.silent_cards_v67:
        if p.get("MASTER_PLANNER"):
            discarders = sum(c.name in {"SURVIVOR", "PREPARED", "ACROBATICS", "DAGGER_THROW", "CALCULATED_GAMBLE",
                                        "HIDDEN_DAGGERS", "STORM_OF_STEEL"} for c in cards)
            per_turn += min(2, fraction * (discarders + p.get("TOOLS_OF_THE_TRADE", 0))) * min(
                2, fraction * sum(c.kind == "Skill" and "Sly" not in c.keywords for c in cards))
        immediate += 2.5 * min(turns, p.get("INTANGIBLE", 0))
        per_turn -= 0.7 * p.get("WRAITH_FORM", 0)
    blur_carry = (
        min(turns, p.get("BLUR", 0)) * min(10.0, 0.45 * state.block)
        if value_v68
        else min(turns, p.get("BLUR", 0)) * min(2, 0.2 * state.block)
    )
    return immediate + turns * per_turn + blur_carry


def _progress(state, power_leaf_v62=False):
    progress = 0
    pressure = 0
    deadline = 0
    for enemy in state.enemies:
        if enemy.hp > 0:
            poison = power(enemy.powers, "POISON")
            if power_leaf_v62:
                poison = _poison_damage(enemy, poison, power(state.powers, "ACCELERANT"))
            # Leaving a foe already doomed by the next poison tick is valuable.
            progress += min(enemy.hp, poison) * 0.8
            if poison < enemy.hp:
                pressure += sum((i.damage or 0) * i.hits for i in enemy.intents)
            if sandpit := power(enemy.powers, "SANDPIT"):
                deadline += 9 / sandpit
            if state.silent_cards_v66 and (strangle := power(enemy.powers, "STRANGLE")):
                plays = sum(0 <= c.variant.cost <= state.energy for c in state.hand)
                progress += 0.6 * min(enemy.hp, strangle * min(3, plays))
            progress -= enemy.block * 0.08
        progress += _damage_progress(enemy)
    return progress, pressure, deadline


def _boss_adjustment(state, *, kaiser_scaling_v69=False):
    """Price public consequences extending beyond this turn for either evaluator."""
    if state.kaiser_v63:
        if kaiser_scaling_v69:
            # Concave HP valuation: taking chip damage at high HP (50+) is cheap
            # compared to bringing scaling powers online early, while low HP (<25)
            # stays strongly protected and gates future scaling payoff.
            low_hp = min(state.hp, 25)
            mid_hp = max(0, min(state.hp, 50) - 25)
            high_hp = max(0, state.hp - 50)
            value = 4.5 * low_hp + 2.0 * mid_hp + 1.1 * high_hp
            living = [e for e in state.enemies if e.hp > 0]
            rem_hp = sum(e.hp for e in living)
            survive = min(1.0, max(0.0, state.hp - 5) / 25.0)
            runway = min(1.0, rem_hp / 160.0) * survive
            p = dict(state.powers)
            # Full scaling power credit (Accelerant, Footwork, Afterimage, Fumes,
            # Envenom, Accuracy, Well-Laid Plans, Infinite Blades, Tools, etc.)
            value += 1.8 * survive * _power_value(state, value_v68=True)
            # Extra Turn-1/2 Accelerant credit when poison cards are in the deck
            if accel := p.get("ACCELERANT", 0):
                cards = (*state.draw, *state.discard, *(c.variant for c in state.hand))
                poi_cards = sum(c.name in _POISON_SOURCES for c in cards)
                if poi_cards or p.get("NOXIOUS_FUMES") or p.get("ENVENOM"):
                    value += runway * 7.0 * min(3, accel) * min(1.5, 0.5 + 0.25 * poi_cards)
            value += runway * (
                7.0 * p.get("DEXTERITY", 0)
                + 9.0 * p.get("AFTERIMAGE", 0)
                + 5.5 * p.get("NOXIOUS_FUMES", 0)
                + 7.0 * bool(p.get("WELL_LAID_PLANS"))
            )
            focus = 0.0
            for e in state.enemies:
                poison = power(e.powers, "POISON")
                ticks = min(5, poison, 3 * (1 + p.get("ACCELERANT", 0))) if e.hp > 0 else 0
                future = min(e.hp, ticks * poison - ticks * (ticks - 1) // 2)
                progress = e.max_hp - e.hp + future
                focus = max(focus, progress * (1.15 if e.name == "ROCKET" else 1))
                if e.hp:
                    value += 1.5 * future + 6 * min(3, power(e.powers, "WEAK")) - 6 * power(e.powers, "STRENGTH")
                else:
                    value += 22
            value += 6 * p.get("INTANGIBLE", 0) + 5 * p.get("BUFFER", 0) + 4 * p.get("THORNS", 0)
            return value + 0.55 * focus
        # Value concentrated damage and poison's next several ticks. Early removal
        # cuts the number of incoming attacks even after the survivor gains rage.
        focus = 0.0
        value = 4.0 * state.hp + 14.0 * power(state.powers, "DEXTERITY")
        value += 15.0 * power(state.powers, "AFTERIMAGE") + 10.0 * power(state.powers, "NOXIOUS_FUMES")
        for e in state.enemies:
            poison = power(e.powers, "POISON")
            ticks = min(5, poison, 3 * (1 + power(state.powers, "ACCELERANT"))) if e.hp > 0 else 0
            future = min(e.hp, ticks * poison - ticks * (ticks - 1) // 2)
            progress = e.max_hp - e.hp + future
            focus = max(focus, progress * (1.15 if e.name == "ROCKET" else 1))
            if e.hp:
                value += 1.5 * future + 6 * min(3, power(e.powers, "WEAK")) - 6 * power(e.powers, "STRENGTH")
            else:
                value += 18
        value += 5 * power(state.powers, "INTANGIBLE") + 4 * power(state.powers, "BUFFER")
        return value + 0.45 * focus + 4 * power(state.powers, "THORNS")
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
        remaining = max(0, limit - state.sloth_plays)
        high = sorted((SLOTH_RETAIN_VALUE.get(c.variant.name, 0) for c in state.hand), reverse=True)
        value += sum(high[:remaining])
    return value


def _carryover_debuffs(state):
    """Value Vulnerable and Weak still active on living enemies for upcoming turns."""
    bonus = 0.0
    for enemy in state.enemies:
        if enemy.hp <= 10 or (enemy.name == "WATERFALL_GIANT" and enemy.max_hp == 999_999_999):
            continue
        if vuln := power(enemy.powers, "VULNERABLE"):
            bonus += 1.8 * min(2, vuln) * min(1.0, enemy.hp / 40.0)
        if weak := power(enemy.powers, "WEAK"):
            bonus += 1.6 * min(2, weak) * min(1.0, enemy.hp / 35.0)
    return min(8.0, bonus)


def leaf_value(state, reserve_price, model=None, win_weight=0.0, *, boss_safe=False, power_leaf_v62=False, value_v68=False, kaiser_scaling_v69=False, kaiser_pure_neural_v69=False):
    if model is not None and state.outcome == "completed":
        adjustment = (
            0
            if (kaiser_pure_neural_v69 and state.kaiser_v63)
            else (_boss_adjustment(state, kaiser_scaling_v69=kaiser_scaling_v69) if boss_safe else 0)
        )
        win_probability, win_hp_fraction = model.leaf(state)
        value = win_probability * (state.max_hp * win_hp_fraction + win_weight)
        return SURVIVED, round(value - reserve_price * state.spent + adjustment, 8)
    adjustment = _boss_adjustment(state, kaiser_scaling_v69=kaiser_scaling_v69) if boss_safe and state.outcome == "completed" else 0
    progress, pressure, deadline = _progress(state, power_leaf_v62)
    persistent = sum(power(state.powers, name) * weight for name, weight in (
        ("AFTERIMAGE", 3.5), ("WELL_LAID_PLANS", 4), ("STRENGTH", 1.5),
        ("DEXTERITY", 1.5), ("INTANGIBLE", 3), ("BUFFER", 2),
    ))
    if state.silent_cards_v66:
        persistent -= 4 * power(state.powers, "WELL_LAID_PLANS")
    if power_leaf_v62 or state.silent_cards_v66:
        persistent += _power_value(state, value_v68=value_v68) - 3.5 * power(state.powers, "AFTERIMAGE") - 1.5 * power(state.powers, "DEXTERITY")
    category = {"victory": VICTORY, "completed": SURVIVED, "dead": DEAD}.get(
        state.outcome, UNRESOLVED)
    utility = state.hp - reserve_price * state.spent
    if category != VICTORY:
        utility += 0.35 * progress - 0.035 * pressure - deadline + persistent
        if category == SURVIVED:
            if value_v68:
                retain_bonus = sum(
                    0.50 if c.variant.name not in ("STRIKE_SILENT", "DEFEND_SILENT") and c.variant.kind not in ("Curse", "Status") else 0.15
                    for c in state.hand
                )
                utility += 0.35 * state.block + retain_bonus + _carryover_debuffs(state)
            else:
                utility += 0.35 * state.block + 0.22 * len(state.hand)
    return category, round(utility + adjustment, 8)


def interim(state, reserve_price, *, boss_safe=False, power_leaf_v62=False, value_v68=False, kaiser_scaling_v69=False):
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
    if power_leaf_v62 or state.silent_cards_v66:
        # Development uses damage units, whereas completed leaves price damage
        # at 0.35 HP. Keep the independent safety quota exactly as before.
        development += _power_value(state, value_v68=value_v68) / 0.35
        for enemy in state.enemies:
            poison = power(enemy.powers, "POISON")
            if enemy.hp > 0 and poison:
                development += 0.8 * (_poison_damage(enemy, poison, power(state.powers, "ACCELERANT"))
                                      - min(enemy.hp, poison))
    adjustment = _boss_adjustment(state, kaiser_scaling_v69=kaiser_scaling_v69) if boss_safe else 0
    return safety - reserve_price * state.spent + adjustment, development + adjustment
