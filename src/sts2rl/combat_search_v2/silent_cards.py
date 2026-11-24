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
        if name not in ("CARD.MURDER", "CARD.MEMENTO_MORI", "CARD.SHIV"):
            continue
        # CalculatedDamage incorporates powers and damage relics. Restrict inversion
        # to an unmodified preview with no possible multiplicative/flat ambiguity.
        if (c.get("enchantment") or c.get("affliction") or any(k in dict(state.powers) for k in
                ("WEAK", "SHRINK", "VIGOR", "DOUBLE_DAMAGE", "GIGANTIFICATION", "SURROUNDED"))
                or any(r.name in ("PEN_NIB", "MINIATURE_CANNON", "MYSTIC_LIGHTER") for r in state.relics)):
            continue
        if name == "CARD.SHIV" and (phantom := power(state.powers, "PHANTOM_BLADES")):
            base = 4 + 2 * c.get("upgrades", 0) + power(state.powers, "ACCURACY") + power(state.powers, "STRENGTH")
            if base > 0 and stats.get("damage") in (base, base + phantom):
                result["shivs_this_turn"] = int(stats["damage"] == base)
            continue
        if {"calculateddamage", "calculationbase", "extradamage"} <= stats.keys():
            surplus = stats["calculateddamage"] - power(state.powers, "STRENGTH") - stats["calculationbase"]
            if stats["calculateddamage"] > 0 and surplus >= 0 and surplus % stats["extradamage"] == 0:
                key = "draws_this_combat" if name == "CARD.MURDER" else "discards_this_turn"
                result[key] = int(surplus // stats["extradamage"])
    return result


def tender_discard_plays(state, view):
    # Tender removes one Strength per finished card. On an uninterrupted draw/discard
    # with only these automatic plays, the public Strength delta counts them exactly.
    allowed = {"TACTICIAN", "REFLEX", "RICOCHET", "ABRASIVE", "FLICK_FLACK", "UNTOUCHABLE"}
    if any(r.name in ("SHURIKEN", "REPTILE_TRINKET") for r in state.relics):
        return None
    cards = (*state.draw, *state.discard, *(c.variant for c in state.hand))
    if any(v.name not in allowed for v in cards if "Sly" in v.keywords or "sly_this_turn" in v.flags):
        return None
    strength = next((p["amount"] for p in view.get("player_powers") or () if p["id"] == "POWER.STRENGTH_POWER"), 0)
    finished = power(state.powers, "STRENGTH") - strength
    return finished if finished > 0 else None


def hand_trick_slots(state):
    return tuple(c.slot for c in state.hand if c.variant.kind == "Skill" and
                 "Sly" not in c.variant.keywords and "sly_this_turn" not in c.variant.flags)


def grant_sly(state, slot):
    return replace(state, hand=tuple(replace(c, variant=replace(c.variant, flags=(*c.variant.flags, "sly_this_turn")))
                                     if c.slot == slot else c for c in state.hand))


def retain_shivs(state):
    def retain(v):
        return replace(v, keywords=tuple(sorted((*v.keywords, "Retain"))),
                       flags=tuple(sorted(set((*v.flags, "retain_this_turn"))))) if (
            v.name == "SHIV" and "Retain" not in v.keywords) else v
    return replace(state, hand=tuple(replace(c, variant=retain(c.variant)) for c in state.hand),
                   **{z: tuple(sorted(retain(v) for v in getattr(state, z))) for z in ("draw", "discard", "exhaust")})


def draw_known(state, count, escape_plan):
    from .transitions import _damage, _debuff, block_gain, boundary

    initial = state
    shuffled = count > len(state.draw)
    for _ in range(count):
        if not state.draw:
            state = replace(state, draw=state.discard, discard=())
        card = state.draw[0]
        if (any(v != card for v in state.draw) or card.flags or card.modifier or
                card.name in ("PINPOINT", "VOID", "FRANTIC_ESCAPE", "UP_MY_SLEEVE") or
                power(state.powers, "CONFUSED") or power(state.powers, "FREE_SKILL") or
                card.free_skill_cost >= 0):
            return boundary(initial, "draw", count, shuffled)
        drawn = replace(card, stats=())
        state = replace(state, hand=(*state.hand, Card(state.next_slot, drawn)), next_slot=state.next_slot + 1,
                        draw=state.draw[1:], draws_this_combat=(
                            state.draws_this_combat + 1 if state.draws_this_combat >= 0 else -1))
        for enemy in state.enemies:
            if enemy.hp <= 0:
                continue
            if wave := power(state.powers, "CORROSIVE_WAVE"):
                state = _debuff(state, enemy.slot, "POISON", wave)
                if state.boundary:
                    return state
            if speed := power(state.powers, "SPEEDSTER"):
                state = _damage(state, enemy.slot, speed)
                if state.boundary or state.outcome:
                    return state
        if escape_plan and drawn.kind == "Skill":
            if any(r.name == "VAMBRACE" and r.status == "Active" for r in state.relics):
                return boundary(initial, "vambrace first card block")
            state = replace(state, block=state.block + block_gain(3 + 2 * escape_plan.upgrade + nimble(escape_plan), state.powers))
    return state


def finish_tools_start(state):
    from .transitions import _debuff

    powers = set_power(state.powers, "DRAW_CARDS_NEXT_TURN", 0)
    for name in ("PLATING", "CLARITY"):
        if power(powers, name):
            powers = add_power(powers, name, -1)
    state = replace(state, powers=powers)
    relics = list(state.relics)
    for i, r in enumerate(relics):
        if r.used:
            continue
        if r.name == "POCKETWATCH":
            relics[i] = replace(r, status="Active" if (r.counter or 0) <= 3 else "Normal")
        if r.name == "LETTER_OPENER":
            relics[i] = replace(r, counter=0, status="Normal")
        if r.name == "SEAL_OF_GOLD" and state.seal_gold >= 3:
            state = replace(state, seal_gold=state.seal_gold - 3, energy=state.energy + power(r.stats, "energy"))
    state = replace(state, relics=tuple(relics))
    if fumes := power(powers, "NOXIOUS_FUMES"):
        for e in state.enemies:
            if e.hp > 0:
                state = _debuff(state, e.slot, "POISON", fumes)
                if state.boundary:
                    return state
    return state


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


def nimble(v):
    return sum(amount for kind, name, amount in v.modifier if kind == "enchantment_state" and name == "NIMBLE")


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
        return draw(state, 1, escape_plan=v)
    if name == "DODGE_AND_ROLL":
        if any(r.name == "VAMBRACE" and r.status == "Active" for r in state.relics):
            return boundary(state, "vambrace first card block")
        block = block_gain(4 + 2 * up + nimble(v), state.powers)
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
