"""Opt-in Silent card rules from the pinned v0.111.0 models."""
from dataclasses import replace

from .state import Card, Effect, Play, add_power, power, set_power

PROMOTED = {
    "ACCURACY", "ASSASSINATE", "BOUNCING_FLASK", "ECHOING_SLASH", "ENVENOM",
    "EXTERMINATE", "HAND_TRICK", "HIDDEN_DAGGERS", "INFINITE_BLADES", "OUTBREAK",
    "PHANTOM_BLADES", "PINPOINT", "SIDESTEP", "THE_HUNT",
}
WAVE = {
    "BLADE_OF_INK", "EXPOSE", "PIERCING_WAIL", "SERPENT_FORM", "ABRASIVE", "DODGE_AND_ROLL",
    "KNIFE_TRAP", "TRACKING", "BULLET_TIME", "UP_MY_SLEEVE", "FINISHER", "POUNCE",
    "MEMENTO_MORI", "RICOCHET", "SHADOW_STEP", "SHADOWMELD", "CORROSIVE_WAVE", "STRANGLE",
    "SPEEDSTER", "STORM_OF_STEEL", "MURDER", "ESCAPE_PLAN",
}
PLAYER = {
    "ENVENOM", "THE_HUNT", "INFINITE_BLADES", "RETAIN_HAND", "SERPENT_FORM", "TRACKING",
    "FREE_SKILL", "BLOCK_NEXT_TURN", "SHADOW_STEP", "DOUBLE_DAMAGE", "SHADOWMELD",
    "CORROSIVE_WAVE", "SPEEDSTER",
}
ENEMY = {"STRANGLE", "PIERCING_WAIL"}
ATTACKS = {"STRANGLE": (8, 10), "RICOCHET": (3, 3), "POUNCE": (14, 20),
           "FINISHER": (6, 8), "MEMENTO_MORI": (9, 11), "MURDER": (1, 1)}
INK = (("enchantment_state", "INKY", 1),)


def history_counts(hand, state):
    """Read history-dependent previews only when their underlying count is unambiguous."""
    result = {}
    for c in hand:
        name = c["id"]
        stats = c.get("stats") or {}
        if name == "CARD.FINISHER" and "calculatedhits" in stats:
            result["attacks_this_turn"] = int(stats["calculatedhits"])
        if name not in ("CARD.MURDER", "CARD.MEMENTO_MORI"):
            continue
        # CalculatedDamage incorporates powers and damage relics. Restrict inversion
        # to an unmodified preview with no possible multiplicative/flat ambiguity.
        if (c.get("enchantment") or c.get("affliction") or any(k in dict(state.powers) for k in
                ("WEAK", "SHRINK", "VIGOR", "DOUBLE_DAMAGE", "GIGANTIFICATION", "SURROUNDED"))
                or any(r.name in ("PEN_NIB", "MINIATURE_CANNON", "MYSTIC_LIGHTER") for r in state.relics)):
            continue
        if {"calculateddamage", "calculationbase", "extradamage"} <= stats.keys():
            surplus = stats["calculateddamage"] - power(state.powers, "STRENGTH") - stats["calculationbase"]
            if stats["calculateddamage"] > 0 and surplus >= 0 and surplus % stats["extradamage"] == 0:
                key = "draws_this_combat" if name == "CARD.MURDER" else "discards_this_turn"
                result[key] = int(surplus // stats["extradamage"])
    return result


def retain_shivs(state):
    def retain(v):
        return replace(v, keywords=tuple(sorted((*v.keywords, "Retain")))) if (
            v.name == "SHIV" and "Retain" not in v.keywords) else v
    return replace(state, hand=tuple(replace(c, variant=retain(c.variant)) for c in state.hand),
                   **{z: tuple(sorted(retain(v) for v in getattr(state, z))) for z in ("draw", "discard", "exhaust")})


def free_skills(state):
    hand = []
    for c in state.hand:
        v = c.variant
        if v.kind == "Skill" and "costs_x" not in v.flags:
            v = replace(v, free_skill_cost=v.cost if v.free_skill_cost < 0 else v.free_skill_cost, cost=0)
        hand.append(replace(c, variant=v))
    return replace(state, hand=tuple(hand))


def consume_free_skill(state):
    from .transitions import boundary

    state = replace(state, powers=add_power(state.powers, "FREE_SKILL", -1))
    if power(state.powers, "FREE_SKILL"):
        return state
    hand = []
    for c in state.hand:
        v = c.variant
        if v.kind == "Skill" and "costs_x" not in v.flags:
            if v.free_skill_cost < 0:
                return boundary(state, "free skill underlying cost")
            v = replace(v, cost=v.free_skill_cost, free_skill_cost=-1)
        hand.append(replace(c, variant=v))
    return replace(state, hand=tuple(hand))


def card_effect(state, play, slots):
    from .transitions import (_add_player_power, _debuff, _enemy_change, _queue, _shiv,
                              block_gain, boundary, draw)

    v = play.card.variant
    name, up = v.name, v.upgrade
    amounts = {"TOOLS_OF_THE_TRADE": 1, "SERPENT_FORM": 4 + 2 * up, "TRACKING": 50,
               "SHADOWMELD": 1, "CORROSIVE_WAVE": 2 + up, "SPEEDSTER": 2}
    if name in amounts:
        return _add_player_power(state, name, amounts[name])
    if name == "ABRASIVE":
        return _add_player_power(_add_player_power(state, "DEXTERITY", 1), "THORNS", 4 + 2 * up)
    if name == "ESCAPE_PLAN":
        return draw(state, 1)
    if name == "DODGE_AND_ROLL":
        if any(r.name == "VAMBRACE" and r.status == "Active" for r in state.relics):
            return boundary(state, "vambrace first card block")
        block = block_gain(4 + 2 * up, state.powers)
        return _add_player_power(replace(state, block=state.block + block), "BLOCK_NEXT_TURN", block)
    if name == "EXPOSE":
        state = _enemy_change(state, play.target, lambda e: replace(e, block=0, powers=set_power(e.powers, "ARTIFACT", 0)))
        return _debuff(state, play.target, "VULNERABLE", 2 + up)
    if name == "PIERCING_WAIL":
        for slot in slots:
            previous = power(state.enemies[slot].powers, "ARTIFACT")
            state = _debuff(state, slot, name, 6 + 2 * up)
            if state.boundary:
                return state
            if not previous:
                state = _enemy_change(state, slot, lambda e: replace(e, powers=add_power(e.powers, "STRENGTH", -6 - 2 * up)))
        return state
    if name in ("UP_MY_SLEEVE", "BLADE_OF_INK"):
        return _shiv(state, (3 if name == "UP_MY_SLEEVE" else 2) + up, modifier=INK if name == "BLADE_OF_INK" else ())
    if name == "BULLET_TIME":
        hand = tuple(replace(c, variant=replace(c.variant, cost=0, free_skill_cost=0))
                     if "costs_x" not in c.variant.flags else c for c in state.hand)
        powers = (add_power(state.powers, "ARTIFACT", -1) if power(state.powers, "ARTIFACT")
                  else set_power(state.powers, "NO_DRAW", 1))
        return replace(state, hand=hand, powers=powers)
    if name in ("STORM_OF_STEEL", "SHADOW_STEP"):
        slots = tuple(c.slot for c in state.hand)
        follow = Effect("storm_shivs", len(slots), play) if name == "STORM_OF_STEEL" else Effect("shadow_step")
        return _queue(state, Effect("discard", slots=slots), follow)
    if name == "KNIFE_TRAP":
        shivs = tuple(v for v in state.exhaust if v.name == "SHIV")
        if len(set(shivs)) > 1:
            return boundary(state, "knife trap unordered exhaust")
        return _queue(state, *(Effect("knife_trap", up, Play(Card(-1, shiv), play.target)) for shiv in shivs))
    return None
