"""Deterministic player actions and visible operation continuations."""
from dataclasses import replace
from itertools import combinations

from .state import (END_TURN, HAND_CAP, Boundary, Card, Effect, Move, Play, Prompt, Variant,
                    Unsupported, add_power, power, set_power)

# Base, upgraded values from the pinned card models. Hand damage/block fields
# are mutable previews and are deliberately excluded from the projection.
ATTACKS = {
    "STRIKE_SILENT": (6, 9), "NEUTRALIZE": (3, 4), "SHIV": (4, 4),
    "SLICE": (6, 9), "DASH": (10, 13), "DAGGER_THROW": (9, 12),
    "POISONED_STAB": (6, 8), "SUCKER_PUNCH": (8, 10), "BACKSTAB": (11, 15),
    "DAGGER_SPRAY": (4, 6), "FLICK_FLACK": (7, 10), "SKEWER": (7, 10),
}
BLOCKS = {
    "DEFEND_SILENT": (5, 8), "SURVIVOR": (8, 11), "DASH": (10, 13),
    "DEFLECT": (4, 7), "BLUR": (5, 8), "CLOAK_AND_DAGGER": (6, 6),
}
STATUS = {"BURN", "WITHER", "DAZED", "ASCENDERS_BANE", "VOID", "SLIMED", "INFECTION"}
SKILLS = {
    "ADRENALINE", "BURST", "SURVIVOR", "ACROBATICS", "PREPARED", "CALCULATED_GAMBLE",
    "REFLEX", "TACTICIAN", "BLADE_DANCE", "CLOAK_AND_DAGGER", "MALAISE",
    "DEADLY_POISON", "CRIPPLING_CLOUD", "DEFEND_SILENT", "DEFLECT", "BLUR",
    "FRANTIC_ESCAPE", "SLIMED",
}
CARD_BOUNDARIES = {"NIGHTMARE", "TOOLS_OF_THE_TRADE"}
POWER_CARDS = {"AFTERIMAGE", "WELL_LAID_PLANS", "BUFFER"}
CARDS = ATTACKS.keys() | BLOCKS.keys() | STATUS | SKILLS | POWER_CARDS | CARD_BOUNDARIES
POTIONS = {
    "ENERGY_POTION": ("energy", "energy"), "BLOCK_POTION": ("block", "block"),
    "FIRE_POTION": ("damage", "damage"), "EXPLOSIVE_AMPOULE": ("damage", "damage"),
    "POISON_POTION": ("poison", "poisonpower"), "WEAK_POTION": ("weak", "weakpower"),
    "DEXTERITY_POTION": ("dexterity", "dexteritypower"),
    "STRENGTH_POTION": ("strength", "strengthpower"),
    "GHOST_IN_A_JAR": ("intangible", "intangiblepower"), "SWIFT_POTION": ("draw", "cards"),
    "DUPLICATOR": ("duplication", None),
}
PLAYER_POWERS = {
    "STRENGTH", "DEXTERITY", "WEAK", "VULNERABLE", "FRAIL", "AFTERIMAGE", "BURST",
    "DUPLICATION", "WELL_LAID_PLANS", "BLUR", "BUFFER", "INTANGIBLE", "CONSTRICT", "SHRINK",
    "ARTIFACT", "POISON", "NO_DRAW", "TOOLS_OF_THE_TRADE", "NIGHTMARE", "TAINTED",
}
ENEMY_POWERS = {
    "STRENGTH", "WEAK", "VULNERABLE", "POISON", "ARTIFACT", "BUFFER", "INTANGIBLE",
    "VITAL_SPARK", "SANDPIT", "SLIPPERY",
}
RELICS = {
    "RING_OF_THE_SNAKE", "CLOAK_CLASP", "LANTERN", "STRAWBERRY", "PEAR", "MANGO",
    "ANCHOR", "BAG_OF_PREPARATION", "BLOOD_VIAL", "ORICHALCUM", "HAPPY_FLOWER",
}
KEYWORDS = {"Exhaust", "Ethereal", "Innate", "Retain", "Sly", "Unplayable"}
MAX_EVENTS = 40


def card_supported(v):
    tainted = (len(v.modifier) == 1 and v.modifier[0][:2] == ("affliction_state", "TAINTED")
               and v.kind == "Skill")
    return (v.name in CARDS and v.upgrade in (0, 1) and (not v.modifier or tainted)
            and all(k in KEYWORDS for k in v.keywords)
            and all(f in ("costs_x", "exhaust_on_next_play", "retain_this_turn", "sly_this_turn")
                    for f in v.flags)
            and ("costs_x" in v.flags) == (v.name in ("MALAISE", "SKEWER")))


def can_play(state, v):
    return (v.name not in STATUS - {"SLIMED"} and "Unplayable" not in v.keywords
            and ("costs_x" in v.flags or 0 <= v.cost <= state.energy))


def admission(projected):
    state = projected.state
    for name, _ in state.powers:
        if name not in PLAYER_POWERS:
            return f"player power/{name}"
    for relic in state.relics:
        if relic.name not in RELICS or relic.stacks != 1:
            return f"relic/{relic.name}"
    for card, playable in zip(state.hand, projected.playable):
        v = card.variant
        if not card_supported(v):
            return f"card/{v.name}"
        if v.modifier and not any(
            e.name == "INFESTED_PRISM" and power(e.powers, "VITAL_SPARK") == v.modifier[0][2]
            for e in state.enemies
        ):
            return f"tainted source/{v.name}"
        # During a pending prompt CanPlay is a UI preview rather than an action.
        if not state.prompt and playable != can_play(state, v):
            return f"legality/{v.name}"
    for enemy in state.enemies:
        for name, _ in enemy.powers:
            if name not in ENEMY_POWERS:
                return f"enemy power/{name}"
    for v in state.play:
        if not state.prompt:
            return f"active play pile/{v.name}"
    return None


def targets(state, target):
    if target == "AnyEnemy":
        return tuple(enemy.slot for enemy in state.enemies if enemy.hp > 0)
    return (-1,)


def legal(state):
    if state.outcome or state.boundary:
        return ()
    if state.prompt:
        p = state.prompt
        return tuple(Move("select_cards", selection=slots) for count in range(p.minimum, p.maximum + 1)
                     for slots in combinations(p.candidates, count))
    return (*(
        Move("play_card", c.slot, target) for c in state.hand if can_play(state, c.variant)
        for target in targets(state, c.variant.target)
    ), *(
        Move("use_potion", potion.slot, target) for potion in state.potions if potion.usable
        for target in targets(state, potion.target)
    ), END_TURN)


def boundary(state, reason, count=0, shuffle=False):
    return replace(state, boundary=Boundary(reason, count, shuffle))


def draw(state, count):
    count = min(count, HAND_CAP - len(state.hand), len(state.draw) + len(state.discard))
    if count > 0 and not power(state.powers, "NO_DRAW"):
        return boundary(state, "draw", count, count > len(state.draw))
    return state


def _put(state, zone, variant):
    # Hand-only metadata does not persist; explicit Retain/Exhaust keywords do.
    variant = replace(variant, flags=tuple(flag for flag in variant.flags
                                          if flag not in ("exhaust_on_next_play", "retain_this_turn",
                                                          "sly_this_turn")))
    return replace(state, **{zone: tuple(sorted((*getattr(state, zone), variant)))})


def block_gain(base, powers, modified=True):
    if modified:
        base = max(0, base + power(powers, "DEXTERITY"))
        if power(powers, "FRAIL"):
            base = base * 3 // 4
    return max(0, base)


def lose_hp(hp, block, powers, amount, *, bypass=False):
    if amount <= 0:
        return hp, block, powers
    if power(powers, "INTANGIBLE"):
        amount = min(amount, 1)
    if not bypass:
        absorbed = min(block, amount)
        block -= absorbed
        amount -= absorbed
    if amount and power(powers, "BUFFER"):
        powers = add_power(powers, "BUFFER", -1)
        amount = 0
    if amount and power(powers, "SLIPPERY"):
        amount = 1
        powers = add_power(powers, "SLIPPERY", -1)
    return max(0, hp - amount), block, powers


def _enemy_change(state, slot, fn):
    enemy = state.enemies[slot]
    if enemy.hp <= 0:
        return state
    enemy = fn(enemy)
    enemies = (*state.enemies[:slot], enemy, *state.enemies[slot + 1:])
    state = replace(state, enemies=enemies)
    if enemy.hp == 0:
        from .encounters import after_death
        return after_death(state, enemy)
    return state


def _damage(state, slot, base, *, attack):
    def resolve(enemy):
        value = base
        if attack:
            value = max(0, value + power(state.powers, "STRENGTH"))
            # Multiply before truncating because previews and attacks round once.
            weak = 3 if power(state.powers, "WEAK") else 4
            vulnerable = 3 if power(enemy.powers, "VULNERABLE") else 2
            shrink = 7 if power(state.powers, "SHRINK") else 10
            value = value * weak * vulnerable * shrink // 80
        hp, block, powers = lose_hp(enemy.hp, enemy.block, enemy.powers, value)
        return replace(enemy, hp=hp, block=block, powers=powers)
    return _enemy_change(state, slot, resolve)


def _debuff(state, slot, name, amount):
    if amount <= 0:
        return state

    def resolve(enemy):
        powers = enemy.powers
        if power(powers, "ARTIFACT"):
            powers = add_power(powers, "ARTIFACT", -1)
        else:
            powers = add_power(powers, name, -amount if name == "STRENGTH" else amount)
        return replace(enemy, powers=powers)
    return _enemy_change(state, slot, resolve)


def _add_player_power(state, name, amount):
    return replace(state, powers=add_power(state.powers, name, amount))


def _queue(state, *events):
    return replace(state, queue=(*events, *state.queue))


def _shiv(state, count):
    in_hand = min(count, HAND_CAP - len(state.hand))
    variant = Variant("SHIV", "Attack", 0, "AnyEnemy", keywords=("Exhaust",))
    return replace(state, hand=(*state.hand, *(Card(state.next_slot + i, variant) for i in range(in_hand))),
                   discard=tuple(sorted((*state.discard, *((variant,) * (count - in_hand))))),
                   next_slot=state.next_slot + in_hand)


def _card_targets(state, variant, target):
    if variant.target in ("All", "AllEnemies"):
        return tuple(e.slot for e in state.enemies if e.hp > 0)
    return (target,) if target >= 0 else ()


def _card_effect(state, play):
    v = play.card.variant
    name, up = v.name, v.upgrade
    slots = _card_targets(state, v, play.target)
    if name in CARD_BOUNDARIES:
        return boundary(state, name.lower())
    if name in ATTACKS:
        hits = {"SKEWER": play.x, "DAGGER_SPRAY": 2}.get(name, 1)
        for slot in slots:
            for _ in range(hits):
                state = _damage(state, slot, ATTACKS[name][up], attack=True)
                if state.outcome or state.boundary:
                    return state
    if name in BLOCKS:
        state = replace(state, block=state.block + block_gain(BLOCKS[name][up], state.powers))
    if name in ("SURVIVOR", "ACROBATICS", "PREPARED", "DAGGER_THROW"):
        events = [Effect("prompt", 1 + up if name == "PREPARED" else 1, play)]
        count = {"ACROBATICS": 3 + up, "PREPARED": 1 + up, "DAGGER_THROW": 1}.get(name)
        if count:
            events.insert(0, Effect("draw", count))
        return _queue(state, *events)
    if name == "CALCULATED_GAMBLE":
        return _queue(state, Effect("discard", slots=tuple(c.slot for c in state.hand)),
                      Effect("draw", len(state.hand)))
    if name in ("ADRENALINE", "TACTICIAN"):
        state = replace(state, energy=state.energy + 1 + up)
    if name in ("ADRENALINE", "REFLEX"):
        return _queue(state, Effect("draw", 2 + (up if name == "REFLEX" else 0)))
    if name == "SLIMED":
        return _queue(state, Effect("draw", 1))
    if name in ("BLADE_DANCE", "CLOAK_AND_DAGGER"):
        return _shiv(state, 3 + up if name == "BLADE_DANCE" else 1 + up)
    if name in ("AFTERIMAGE", "WELL_LAID_PLANS", "BURST", "BLUR"):
        return _add_player_power(state, name, 1 + (up if name == "BURST" else 0))
    if name == "BUFFER":
        return _add_player_power(state, "BUFFER", 1 + up)
    if name == "FRANTIC_ESCAPE":
        from .encounters import escape
        return escape(state, play)
    debuffs = {
        "NEUTRALIZE": (("WEAK", 1 + up),), "SUCKER_PUNCH": (("WEAK", 1 + up),),
        "MALAISE": (("STRENGTH", play.x + up), ("WEAK", play.x + up)),
        "DEADLY_POISON": (("POISON", 5 + 2 * up),), "POISONED_STAB": (("POISON", 3 + up),),
        "CRIPPLING_CLOUD": (("POISON", 4 + 3 * up), ("WEAK", 2)),
    }
    for slot in slots:
        for effect, amount in debuffs.get(name, ()):
            state = _debuff(state, slot, effect, amount)
    return state


def _start_play(state, play):
    v = play.card.variant
    if play.target >= 0 and state.enemies[play.target].hp <= 0:
        return boundary(state, "replay target died")
    if not play.replay:
        copies = 0
        for name in ("DUPLICATION", "BURST"):
            if power(state.powers, name) and (name != "BURST" or v.kind == "Skill"):
                copies += 1
                state = _add_player_power(state, name, -1)
        state = _queue(state, *(Effect("play", play=replace(play, replay=True)) for _ in range(copies)),
                       Effect("finish", play=play))
    return _queue(state, Effect("body", play=play), Effect("after_play", power(state.powers, "AFTERIMAGE"), play))


def _after_play(state, play, afterimage):
    state = replace(state, block=state.block + afterimage)
    if play.card.variant.kind == "Skill":
        for enemy in state.enemies:
            if enemy.hp > 0 and (spark := power(enemy.powers, "VITAL_SPARK")):
                state = _enemy_change(state, enemy.slot,
                                      lambda e: replace(e, attack_delta=e.attack_delta + spark))
                state = _add_player_power(state, "TAINTED", spark)
    return state


def _discard_cards(state, slots):
    cards = tuple(c for c in state.hand if c.slot in slots)
    state = replace(state, hand=tuple(c for c in state.hand if c.slot not in slots))
    triggered = []
    for card in cards:
        v = card.variant
        state = _put(state, "discard", v)
        if "Sly" in v.keywords or "sly_this_turn" in v.flags:
            triggered.append(Effect("sly", play=Play(card)))
    return _queue(state, *triggered)


def _sly(state, card):
    v = card.variant
    if not card_supported(v) or "costs_x" in v.flags:
        return boundary(state, "sly modifier")
    candidates = targets(state, v.target)
    if len(candidates) != 1 or v.target == "RandomEnemy":
        return boundary(state, "sly target")
    discarded = []
    blank = _put(replace(state, discard=()), "discard", v).discard[0]
    for item in state.discard:
        if item == blank and blank is not None:
            blank = None
        else:
            discarded.append(item)
    return _queue(replace(state, discard=tuple(discarded), play=(*state.play, v)),
                  Effect("play", play=Play(card, candidates[0])))

def _finish(state, play):
    v = play.card.variant
    # Powers are consumed. Frantic Escape remains the same copy, with a combat
    # cost increase, after its play.
    remaining = list(state.play)
    remaining.remove(v)
    state = replace(state, play=tuple(remaining))
    if v.kind == "Power":
        return state
    exhausted = "Exhaust" in v.keywords or "exhaust_on_next_play" in v.flags
    if v.name == "FRANTIC_ESCAPE":
        v = replace(v, cost=v.cost + 1)
    if "costs_x" in v.flags:
        v = replace(v, cost=play.x)
    return _put(state, "exhaust" if exhausted else "discard", v)


def _drain(state):
    for _ in range(MAX_EVENTS):
        if state.boundary or state.outcome or state.prompt or not state.queue:
            return state
        event, *tail = state.queue
        state = replace(state, queue=tuple(tail))
        match event.kind:
            case "play":
                state = _start_play(state, event.play)
            case "body":
                state = _card_effect(state, event.play)
            case "after_play":
                state = _after_play(state, event.play, event.amount)
            case "finish":
                state = _finish(state, event.play)
            case "draw":
                state = draw(state, event.amount)
            case "prompt":
                slots = tuple(c.slot for c in state.hand)
                count = min(len(slots), event.amount)
                if count:
                    state = replace(state, prompt=Prompt(event.play.card.variant.name, slots, count, count))
            case "discard":
                state = _discard_cards(state, event.slots)
            case "sly":
                state = _sly(state, event.play.card)
    return boundary(state, "automatic event cap") if state.queue else state


def _potion(state, move):
    potion = next(p for p in state.potions if p.slot == move.slot)
    state = replace(state, potions=tuple(p for p in state.potions if p.slot != move.slot),
                    spent=state.spent + 1)
    rule = POTIONS.get(potion.name)
    if rule is None:
        return boundary(state, f"potion/{potion.name}")
    kind, key = rule
    amount = power(potion.stats, key) if key else 1
    if amount <= 0:
        return boundary(state, f"potion amount/{potion.name}")
    if kind == "energy":
        return replace(state, energy=state.energy + amount)
    if kind == "block":
        return replace(state, block=state.block + amount)
    if kind == "draw":
        return draw(state, amount)
    if kind in ("strength", "dexterity", "duplication", "intangible"):
        return _add_player_power(state, kind.upper(), amount)
    slots = tuple(e.slot for e in state.enemies if e.hp > 0) if kind == "damage" and move.target < 0 else (move.target,)
    for slot in slots:
        if slot < 0:
            return boundary(state, "potion target")
        state = (_damage(state, slot, amount, attack=False) if kind == "damage" else
                 _debuff(state, slot, kind.upper(), amount))
        if state.outcome or state.boundary:
            break
    return state


def advance(state, move):
    """Apply a previously enumerated local move."""
    if move.kind == "end_turn":
        from .end_turn import resolve
        return resolve(state)
    if move.kind == "select_cards":
        if not state.queue and state.play:
            v, = state.play
            state = _queue(state, Effect("after_play", power(state.powers, "AFTERIMAGE"), Play(Card(-1, v))),
                           Effect("finish", play=Play(Card(-1, v))))
        return _drain(_queue(replace(state, prompt=None), Effect("discard", slots=move.selection)))
    if move.kind == "use_potion":
        return _potion(state, move)
    card = next(c for c in state.hand if c.slot == move.slot)
    v = card.variant
    if not card_supported(v):
        return boundary(state, f"card/{v.name}")
    x = state.energy if "costs_x" in v.flags else 0
    state = replace(state, energy=state.energy - (x if "costs_x" in v.flags else v.cost),
                    hand=tuple(c for c in state.hand if c.slot != move.slot), play=(*state.play, v))
    return _drain(_queue(state, Effect("play", play=Play(card, move.target, x))))
