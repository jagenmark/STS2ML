"""Deterministic player actions and visible operation continuations."""
from dataclasses import replace
from itertools import combinations
from . import late_encounters

from .state import (END_TURN, HAND_CAP, Boundary, Card, Effect, Move, Play, Prompt, Variant,
                    add_power, power)

# Base, upgraded values from the pinned card models. Hand damage/block fields
# are mutable previews and are deliberately excluded from the projection.
ATTACKS = {
    "STRIKE_SILENT": (6, 9), "NEUTRALIZE": (3, 4), "SHIV": (4, 6),
    "SLICE": (6, 9), "DASH": (10, 13), "DAGGER_THROW": (9, 12),
    "POISONED_STAB": (6, 8), "SUCKER_PUNCH": (8, 10), "BACKSTAB": (11, 15),
    "DAGGER_SPRAY": (4, 6), "FLICK_FLACK": (7, 9), "SKEWER": (8, 11),
    "PREDATOR": (15, 20), "LEADING_STRIKE": (3, 6), "PECK": (2, 2),
    "GRAND_FINALE": (60, 75), "FLECHETTES": (5, 7), "PRECISE_CUT": (13, 16),
}
BLOCKS = {
    "DEFEND_SILENT": (5, 8), "SURVIVOR": (8, 11), "DASH": (10, 13),
    "DEFLECT": (4, 7), "BLUR": (5, 8), "CLOAK_AND_DAGGER": (6, 6),
    "LEG_SWEEP": (11, 14), "BACKFLIP": (5, 8),
}
STATUS = {"BURN", "WITHER", "DAZED", "ASCENDERS_BANE", "VOID", "SLIMED", "INFECTION",
          "CLUMSY", "CURSE_OF_THE_BELL", "FOLLY", "GUILTY", "INJURY", "GREED", "WOUND",
          "SPOILS_MAP", "POOR_SLEEP", "BECKON", "TOXIC"}
UNPLAYABLE = STATUS - {"SLIMED", "TOXIC", "BECKON"}
SKILLS = {
    "ADRENALINE", "BURST", "SURVIVOR", "ACROBATICS", "PREPARED", "CALCULATED_GAMBLE",
    "REFLEX", "TACTICIAN", "BLADE_DANCE", "CLOAK_AND_DAGGER", "MALAISE",
    "DEADLY_POISON", "DEFEND_SILENT", "DEFLECT", "BLUR",
    "FRANTIC_ESCAPE", "SLIMED",
    "SNAKEBITE", "BUBBLE_BUBBLE", "HAZE", "LEG_SWEEP", "BACKFLIP", "ANTICIPATE",
}
CARD_BOUNDARIES = {"NIGHTMARE", "TOOLS_OF_THE_TRADE", "ECHOING_SLASH", "POUNCE", "RICOCHET",
                   "FINISHER", "MEMENTO_MORI", "UP_MY_SLEEVE", "PANIC_BUTTON",
                   "OUTBREAK"}
POWER_CARDS = {"AFTERIMAGE", "WELL_LAID_PLANS", "BUFFER", "FOOTWORK", "NOXIOUS_FUMES", "FAN_OF_KNIVES", "ACCELERANT"}
CARDS = ATTACKS.keys() | BLOCKS.keys() | STATUS | SKILLS | POWER_CARDS | CARD_BOUNDARIES
POTIONS = {
    "ENERGY_POTION": ("energy", "energy"), "BLOCK_POTION": ("block", "block"),
    "FIRE_POTION": ("damage", "damage"), "EXPLOSIVE_AMPOULE": ("damage", "damage"),
    "POISON_POTION": ("poison", "poisonpower"), "WEAK_POTION": ("weak", "weakpower"),
    "VULNERABLE_POTION": ("vulnerable", "vulnerablepower"),
    "DEXTERITY_POTION": ("dexterity", "dexteritypower"),
    "STRENGTH_POTION": ("strength", "strengthpower"),
    "GHOST_IN_A_JAR": ("intangible", "intangiblepower"), "SWIFT_POTION": ("draw", "cards"),
    "DUPLICATOR": ("duplication", None),
    "SPEED_POTION": ("speed", "dexteritypower"), "GIGANTIFICATION_POTION": ("gigantification", None),
    "LIQUID_BRONZE": ("thorns", "thornspower"), "HEART_OF_IRON": ("plating", "platingpower"),
}
PLAYER_POWERS = {
    "STRENGTH", "DEXTERITY", "WEAK", "VULNERABLE", "FRAIL", "AFTERIMAGE", "BURST",
    "DUPLICATION", "WELL_LAID_PLANS", "BLUR", "BUFFER", "INTANGIBLE", "CONSTRICT", "SHRINK",
    "ARTIFACT", "POISON", "NO_DRAW", "TOOLS_OF_THE_TRADE", "NIGHTMARE", "TAINTED",
    "SPEED_POTION", "GIGANTIFICATION", "DRAW_CARDS_NEXT_TURN", "NOXIOUS_FUMES", "PLATING",
    "THORNS", "ANTICIPATE",
    "ENERGY_NEXT_TURN", "FAN_OF_KNIVES", "ACCELERANT", "VIGOR", "ACCURACY", "RITUAL", "DISINTEGRATION", "REGEN", "CLARITY", "RADIANCE",
    "PHANTOM_BLADES",
}
ENEMY_POWERS = {
    "STRENGTH", "WEAK", "VULNERABLE", "POISON", "ARTIFACT", "BUFFER", "INTANGIBLE",
    "VITAL_SPARK", "SANDPIT", "SLIPPERY",
    "PLOW", "BURROWED", "MINION", "ASLEEP", "PLATING", "HARD_TO_KILL", "IMBALANCED",
    "TERRITORIAL", "STEAM_ERUPTION", "PERSONAL_HIVE", "CURL_UP", "THORNS",
    "FLUTTER", "SWIPE", "ESCAPE_ARTIST", "ILLUSION", "RAVENOUS", "RITUAL", "HATCH", "INFESTED", "SLUMBER", "REATTACH",
}
# These hooks finish before the first decision or act after the combat exit.
PASSIVE_RELICS = {
    "LOST_COFFER", "LARGE_CAPSULE", "SWORD_OF_STONE", "GOLDEN_PEARL", "LEAD_PAPERWEIGHT",
    "NUTRITIOUS_OYSTER", "POMANDER", "STONE_HUMIDIFIER", "FESTIVE_POPPER", "SMALL_CAPSULE",
    "AMETHYST_AUBERGINE", "BOOK_OF_FIVE_RINGS", "REGAL_PILLOW", "RED_MASK", "NEW_LEAF",
    "GORGET", "ODDLY_SMOOTH_STONE", "POTION_BELT", "WHETSTONE", "ETERNAL_FEATHER",
    "BAG_OF_MARBLES", "PLANISPHERE", "WINGED_BOOTS", "JUZU_BRACELET", "PAELS_TOOTH",
    "VERY_HOT_COCOA", "YUMMY_COOKIE", "SAND_CASTLE", "WAR_PAINT", "ALCHEMICAL_COFFER",
    "PAELS_HORN", "BING_BONG", "TOUCH_OF_OROBAS", "MEAL_TICKET", "FISHING_ROD",
    "GAMBLING_CHIP", "LUCKY_FYSH", "ASTROLABE", "VAJRA", "BRONZE_SCALES",
    "ELECTRIC_SHRYMP",
    "SCROLL_BOXES", "NEOWS_TALISMAN", "VENERABLE_TEA_SET", "PETRIFIED_TOAD",
    "TEA_OF_DISCOURTESY", "TWISTED_FUNNEL", "STONE_CRACKER",
    "TINY_MAILBOX", "PRAYER_WHEEL", "BELLOWS", "FROZEN_EGG", "MOLTEN_EGG", "TOXIC_EGG",
    "GIRYA", "VEXING_PUZZLEBOX", "PAELS_WING", "LASTING_CANDY", "PANTOGRAPH", "GLASS_EYE",
    "BOWLER_HAT", "SIGNET_RING", "WAR_HAMMER", "SILKEN_TRESS",
    "PHILOSOPHERS_STONE", "ECTOPLASM", "WHITE_BEAST_STATUE", "CALLING_BELL",
    "AKABEKO", "BLOOD_SOAKED_ROSE", "LAVA_ROCK", "ARCANE_SCROLL", "NINJA_SCROLL",
    "LEES_WAFFLE", "SOZU", "NUTRITIOUS_SOUP", "SHOVEL", "MINIATURE_TENT",
    "SEA_GLASS", "WHITE_STAR", "THE_COURIER", "OLD_COIN", "MAW_BANK", "EMPTY_CAGE",
    "MEMBERSHIP_CARD", "BLESSED_ANTLER", "BLACK_STAR",
}
RELICS = PASSIVE_RELICS | {
    "RING_OF_THE_SNAKE", "CLOAK_CLASP", "LANTERN", "STRAWBERRY", "PEAR", "MANGO",
    "ANCHOR", "BAG_OF_PREPARATION", "BLOOD_VIAL", "ORICHALCUM", "HAPPY_FLOWER",
    "BOOMING_CONCH", "KALEIDOSCOPE", "LAVA_LAMP", "NEOWS_SACRIFICE", "PHIAL_HOLSTER",
    "PRECISE_SCISSORS", "SILVER_CRUCIBLE", "CURSED_PEARL", "RING_OF_THE_DRAKE",
    "SPARKLING_ROUGE", "PAELS_BLOOD", "PAELS_TEARS", "UNCEASING_TOP",
    "PUMPKIN_CANDLE", "PRISMATIC_GEM", "PAELS_FLESH", "CANDELABRA",
    "RIPPLE_BASIN", "KUSARIGAMA", "PAPER_KRANE", "DAUGHTER_OF_THE_WIND",
    "PENDULUM", "HORN_CLEAT", "STRIKE_DUMMY", "MINIATURE_CANNON", "TUNING_FORK",
    "LIZARD_TAIL", "GAME_PIECE", "MUMMIFIED_HAND", "REPTILE_TRINKET", "PERMAFROST",
    "CENTENNIAL_PUZZLE", "GREMLIN_HORN",
    "LETTER_OPENER", "CAPTAINS_WHEEL", "UNSETTLING_LAMP", "PARRYING_SHIELD", "TINGSHA",
    "SNECKO_SKULL", "NUNCHAKU", "ORNAMENTAL_FAN", "CHANDELIER", "PEN_NIB",
    "SEAL_OF_GOLD", "ART_OF_WAR", "VELVET_CHOKER", "POCKETWATCH", "VAMBRACE", "JOSS_PAPER",
}
KEYWORDS = {"Exhaust", "Ethereal", "Innate", "Retain", "Sly", "Unplayable", "Eternal"}
MAX_EVENTS = 40
SIMPLE_CARDS = {"STRIKE_SILENT", "DEFEND_SILENT", "SLICE", "SHIV", "DEFLECT", "BACKSTAB", "DASH"}
DEBUFFS = {
    "NEUTRALIZE": (("WEAK", 1, 1),), "SUCKER_PUNCH": (("WEAK", 1, 1),),
    "DEADLY_POISON": (("POISON", 5, 2),), "POISONED_STAB": (("POISON", 3, 1),),
    "SNAKEBITE": (("POISON", 7, 3),), "LEG_SWEEP": (("WEAK", 2, 1),),
    "HAZE": (("POISON", 4, 2), ("WEAK", 1, 1)),
}


def card_supported(v, late=False):
    tainted = (len(v.modifier) == 1 and v.modifier[0][:2] == ("affliction_state", "TAINTED")
               and v.kind == "Skill")
    ember = len(v.modifier) == 1 and v.modifier[0][:2] == ("enchantment_state", "TEZCATARAS_EMBER")
    hexed = (late and len(v.modifier) == 1 and v.modifier[0][:2] == ("affliction_state", "HEXED")
             and "Ethereal" in v.keywords)
    enchanted = late and len(v.modifier) == 1 and v.modifier[0][:2] in (
        ("enchantment_state", "NIMBLE"), ("enchantment_state", "PERFECT_FIT"))
    return ((v.name in CARDS or (late and v.name in late_encounters.CARDS))
            and v.upgrade in (0, 1) and (not v.modifier or tainted or ember or hexed or enchanted or
                                         (late and len(v.modifier) == 1 and late_encounters.bound(v)))
            and all(k in KEYWORDS for k in v.keywords)
            and all(f in ("costs_x", "exhaust_on_next_play", "retain_this_turn", "sly_this_turn")
                    for f in v.flags)
            and ("costs_x" in v.flags) == (v.name in ("MALAISE", "SKEWER")))


def can_play(state, v):
    if state.late and state.bound_used and late_encounters.bound(v):
        return False
    if state.late and (limit := power(state.powers, "SLOTH")) and state.sloth_plays >= limit:
        return False
    return (not any(r.name == "VELVET_CHOKER" and (r.counter or 0) >= power(r.stats, "cards") for r in state.relics)
            and v.name not in UNPLAYABLE and "Unplayable" not in v.keywords
            and (v.name != "GRAND_FINALE" or not state.draw)
            and ("costs_x" in v.flags or 0 <= v.cost <= state.energy))


def admission(projected):
    return next(admission_reasons(projected), None)


def admission_reasons(projected):
    state = projected.state
    for name, _ in state.powers:
        if name not in PLAYER_POWERS and not (state.late and name in late_encounters.PLAYER):
            yield f"player power/{name}"
    for relic in state.relics:
        if relic.name == "VAMBRACE" and relic.status == "Active" and (
            power(state.powers, "AFTERIMAGE") or any(r.name in ("ORNAMENTAL_FAN", "DAUGHTER_OF_THE_WIND", "TUNING_FORK")
                                                     for r in state.relics)
        ):
            yield "vambrace triggered block ordering"
        if (relic.name not in RELICS and not (state.late and relic.name in late_encounters.RELICS)) or relic.stacks != 1:
            yield f"relic/{relic.name}"
    for card, playable in zip(state.hand, projected.playable):
        v = card.variant
        if not card_supported(v, state.late):
            yield f"card/{v.name}"
        elif v.modifier and v.modifier[0][:2] == ("affliction_state", "TAINTED") and not any(
            e.name == "INFESTED_PRISM" and power(e.powers, "VITAL_SPARK") == v.modifier[0][2]
            for e in state.enemies
        ):
            yield f"tainted source/{v.name}"
        # During a pending prompt CanPlay is a UI preview rather than an action.
        elif not state.prompt and playable != can_play(state, v):
            yield f"legality/{v.name}"
    for enemy in state.enemies:
        for name, _ in enemy.powers:
            if name not in ENEMY_POWERS and not (state.late and name in late_encounters.ENEMY):
                yield f"enemy power/{name}"
    for v in state.play:
        if not state.prompt:
            yield f"active play pile/{v.name}"


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
    if state.late and any(r.name == "FIDDLE" and not r.used for r in state.relics):
        return state
    count = min(count, HAND_CAP - len(state.hand), len(state.draw) + len(state.discard))
    if count > 0 and not power(state.powers, "NO_DRAW"):
        return boundary(state, "draw", count, count > len(state.draw))
    return state


def outside_hand(variant):
    # Hand-only metadata does not persist; explicit Retain/Exhaust keywords do.
    flags = tuple(flag for flag in variant.flags
                  if flag not in ("exhaust_on_next_play", "retain_this_turn", "sly_this_turn"))
    return replace(variant, flags=flags) if flags != variant.flags else variant


def _put(state, zone, variant):
    variant = outside_hand(variant)
    return replace(state, **{zone: tuple(sorted((*getattr(state, zone), variant)))})


def block_gain(base, powers, modified=True):
    if modified:
        base = max(0, base + power(powers, "DEXTERITY"))
        if power(powers, "FRAIL"):
            base = base * 3 // 4
    return max(0, base)


def lose_hp(hp, block, powers, amount, *, bypass=False, reduction=0):
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
    if amount and (cap := power(powers, "HARD_TO_KILL")):
        amount = min(amount, cap)
    return max(0, hp - max(0, amount - reduction)), block, powers


def _enemy_change(state, slot, fn):
    prior = state.enemies[slot]
    if prior.hp <= 0:
        return state
    enemy = fn(prior)
    enemies = (*state.enemies[:slot], enemy, *state.enemies[slot + 1:])
    state = replace(state, enemies=enemies)
    if enemy.hp < prior.hp or enemy.block < prior.block:
        from .encounters import after_damage
        return after_damage(state, prior, enemy)
    return state


def _damage(state, slot, base, *, attacker_powers=None, gigantification=False):
    if state.late and attacker_powers is not None and power(state.enemies[slot].powers, "SOAR"):
        return boundary(state, "soaring owl damage")
    def resolve(enemy):
        value = base
        if attacker_powers is not None:
            value = max(0, value + power(attacker_powers, "STRENGTH"))
            # Multiply before truncating because previews and attacks round once.
            weak = 3 if power(attacker_powers, "WEAK") else 4
            vulnerable = 3 if power(enemy.powers, "VULNERABLE") else 2
            shrink = 7 if power(attacker_powers, "SHRINK") else 10
            flutter = 160 if power(enemy.powers, "FLUTTER") else 80
            value = value * weak * vulnerable * shrink * (3 if gigantification else 1) // flutter
        hp, block, powers = lose_hp(enemy.hp, enemy.block, enemy.powers, value)
        return replace(enemy, hp=hp, block=block, powers=powers)
    previous = state.enemies[slot]
    state = _enemy_change(state, slot, resolve)
    if attacker_powers is not None and previous.hp > 0 and not state.outcome and not state.boundary:
        from .encounters import after_attack
        if state.late and state.enemies[slot].hp < previous.hp and (venom := power(state.powers, "ENVENOM")):
            state = _debuff(state, slot, "POISON", venom)
            if state.boundary:
                return state
        return after_attack(state, previous, state.enemies[slot])
    return state


def _debuff(state, slot, name, amount):
    if amount <= 0:
        return state
    if name == "POISON" and any(r.name == "SNECKO_SKULL" and not r.used for r in state.relics):
        amount += 1
    if any(r.name == "UNSETTLING_LAMP" and r.status == "Active" and not r.used for r in state.relics):
        return boundary(state, "unsettling lamp first debuff")

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


def _shiv(state, count, upgrade=0):
    if state.late and power(state.powers, "HEX"):
        return boundary(state, "hexed created shiv")
    in_hand = min(count, HAND_CAP - len(state.hand))
    target = "AllEnemies" if power(state.powers, "FAN_OF_KNIVES") else "AnyEnemy"
    variant = Variant("SHIV", "Attack", 0, target, upgrade, keywords=("Exhaust",))
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
    if v.kind == "Power" and any(r.name in ("GAME_PIECE", "MUMMIFIED_HAND", "PERMAFROST")
                                 and not r.used for r in state.relics):
        return boundary(state, "power-triggered relic")
    if v.modifier and v.modifier[0][0] == "enchantment_state" and not state.late:
        return boundary(state, "enchanted attack")
    if power(state.powers, "PHANTOM_BLADES") and name in ("SHIV", "BLADE_DANCE", "LEADING_STRIKE",
                                                          "CLOAK_AND_DAGGER", "FAN_OF_KNIVES"):
        return boundary(state, "phantom blades shiv trigger")
    if name in CARD_BOUNDARIES and not (state.late and name == "ECHOING_SLASH"):
        return boundary(state, name.lower())
    if name in BLOCKS and any(r.name == "VAMBRACE" and r.status == "Active" for r in state.relics):
        return boundary(state, "vambrace first card block")
    if name == "DASH":
        bonus = v.modifier[0][2] if state.late and v.modifier and v.modifier[0][1] == "NIMBLE" else 0
        state = replace(state, block=state.block + block_gain(BLOCKS[name][up] + bonus, state.powers))
    if name in ATTACKS or (state.late and name in late_encounters.ATTACKS):
        hits = {"SKEWER": play.x, "DAGGER_SPRAY": 2, "PECK": 3 + up}.get(name, 1)
        if name == "FLECHETTES":
            hits = sum(c.variant.kind == "Skill" for c in state.hand)
        if hits > 1 and any(power(state.enemies[slot].powers, "CURL_UP") for slot in slots):
            return boundary(state, "multi-hit curl up ordering")
        damage = (ATTACKS[name] if name in ATTACKS else late_encounters.ATTACKS[name])[up]
        if state.late and v.modifier and v.modifier[0][0] == "enchantment_state":
            if v.modifier[0][1] == "TEZCATARAS_EMBER":
                damage += 3
            damage += sum(power(r.stats, "damage") for r in state.relics if r.name == "MYSTIC_LIGHTER" and not r.used)
        if name == "PRECISE_CUT":
            damage = max(0, damage - 2 * len(state.hand))
        if power(state.powers, "VIGOR"):
            return boundary(state, "vigor consumption timing")
        if any(r.name == "PEN_NIB" and r.counter == 9 for r in state.relics):
            return boundary(state, "pen nib damage ordering")
        if name == "SHIV":
            damage += power(state.powers, "ACCURACY")
        for relic in state.relics:
            if not relic.used and ((relic.name == "STRIKE_DUMMY" and (name in ("STRIKE_SILENT", "LEADING_STRIKE")
                                    or (state.late and name == "ULTIMATE_STRIKE")))
                                   or (relic.name == "MINIATURE_CANNON" and up)):
                damage += power(relic.stats, "extradamage")
        gigantic = power(state.powers, "GIGANTIFICATION") > 0
        if gigantic:
            state = _add_player_power(state, "GIGANTIFICATION", -1)
        for _ in range(hits):
            # One AoE hit uses the modifiers present at the start of that hit.
            # The next repeated hit sees the removal of a killed power source.
            attacker_powers = state.powers
            for slot in slots:
                before = state
                state = _damage(state, slot, damage, attacker_powers=attacker_powers, gigantification=gigantic)
                if (state.late and len(slots) > 1 and slot != slots[-1] and not state.enemies[slot].hp
                        and power(state.enemies[slot].powers, "CRAB_RAGE")):
                    return boundary(before, "crab rage area hit ordering")
                if state.outcome or state.boundary:
                    return state
                if state.late and name == "ECHOING_SLASH" and not state.enemies[slot].hp:
                    return boundary(state, "echoing slash repeats after kill")
    if state.late:
        if name in ("SEEKER_STRIKE", "HAND_TRICK"):
            return boundary(state, "card selection/" + name)
        if name == "SIDESTEP":
            return _add_player_power(state, "ENERGY_NEXT_TURN", 1 + up)
        if name in ("PHANTOM_BLADES", "ACCURACY"):
            return _add_player_power(state, name, 9 + 3 * up if name == "PHANTOM_BLADES" else 4 + 2 * up)
        if name == "ENLIGHTENMENT":
            if any(c.variant.name in ("FRANTIC_ESCAPE", "PINPOINT") for c in state.hand):
                return boundary(state, "enlightenment changing combat cost")
            return replace(state, hand=tuple(replace(c, variant=replace(c.variant, cost=1)) if c.variant.cost > 1
                                             and "costs_x" not in c.variant.flags else c for c in state.hand))
        if name == "BOUNCING_FLASK":
            living = [e.slot for e in state.enemies if e.hp > 0]
            if len(living) != 1:
                return boundary(state, "bouncing flask random target")
            for _ in range(3 + up):
                state = _debuff(state, living[0], "POISON", 3)
                if state.boundary:
                    break
            return state
        if name == "SHRUG_IT_OFF":
            if any(r.name == "VAMBRACE" and r.status == "Active" for r in state.relics):
                return boundary(state, "vambrace first card block")
            return _queue(replace(state, block=state.block + block_gain(8 + 3 * up, state.powers)), Effect("draw", 1))
        if name == "HIDDEN_DAGGERS":
            if power(state.powers, "PHANTOM_BLADES"):
                return boundary(state, "phantom blades created shiv")
            return _queue(state, Effect("prompt", 2, play), Effect("hidden_daggers_shivs", up))
        if name == "INFINITE_BLADES":
            return _add_player_power(state, name, 1)
        if name == "ASSASSINATE":
            return _debuff(state, play.target, "VULNERABLE", 1 + up)
        if name in ("DANSE_MACABRE", "PREP_TIME"):
            return _add_player_power(state, name, 4 + 2 * up)
        if name == "RELAX":
            if any(r.name == "VAMBRACE" and r.status == "Active" for r in state.relics):
                return boundary(state, "vambrace first card block")
            state = replace(state, block=state.block + block_gain(16 + 2 * up, state.powers))
            return _add_player_power(_add_player_power(state, "DRAW_CARDS_NEXT_TURN", 2 + up),
                                     "ENERGY_NEXT_TURN", 2 + up)
    if name in BLOCKS and name != "DASH":
        bonus = v.modifier[0][2] if state.late and v.modifier and v.modifier[0][1] == "NIMBLE" else 0
        state = replace(state, block=state.block + block_gain(BLOCKS[name][up] + bonus, state.powers))
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
    if name == "BACKFLIP":
        return _queue(state, Effect("draw", 2))
    if name == "PREDATOR":
        return _add_player_power(state, "DRAW_CARDS_NEXT_TURN", 2)
    if name == "LEADING_STRIKE":
        return _shiv(state, 2)
    if name == "FOOTWORK":
        return _add_player_power(state, "DEXTERITY", 2 + up)
    if name == "ANTICIPATE":
        amount = 2 + up * 2
        return _add_player_power(_add_player_power(state, "DEXTERITY", amount), "ANTICIPATE", amount)
    if name == "NOXIOUS_FUMES":
        return _add_player_power(state, "NOXIOUS_FUMES", 2 + up)
    if name == "ACCELERANT":
        return _add_player_power(state, "ACCELERANT", 1 + up)
    if name == "FAN_OF_KNIVES":
        if power(state.powers, "FAN_OF_KNIVES"):
            return boundary(state, "stacked fan of knives")
        hand = tuple(replace(c, variant=replace(c.variant, target="AllEnemies"))
                     if c.variant.name == "SHIV" else c for c in state.hand)
        return _shiv(_add_player_power(replace(state, hand=hand), "FAN_OF_KNIVES", 1), 4 + up)
    if name == "BUBBLE_BUBBLE":
        return (_debuff(state, play.target, "POISON", 9 + up * 3)
                if power(state.enemies[play.target].powers, "POISON") else state)
    if name in ("BLADE_DANCE", "CLOAK_AND_DAGGER"):
        return _shiv(state, 3 + up if name == "BLADE_DANCE" else 1 + up)
    if name in ("AFTERIMAGE", "WELL_LAID_PLANS", "BURST", "BLUR"):
        return _add_player_power(state, name, 1 + (up if name == "BURST" else 0))
    if name == "BUFFER":
        return _add_player_power(state, "BUFFER", 1 + up)
    if name == "FRANTIC_ESCAPE":
        from .encounters import escape
        return escape(state)
    debuffs = (("STRENGTH", play.x, 1), ("WEAK", play.x, 1)) if name == "MALAISE" else DEBUFFS.get(name, ())
    for slot in slots:
        for effect, amount, upgrade in debuffs:
            state = _debuff(state, slot, effect, amount + up * upgrade)
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
                       Effect("finish", 1 + copies, play))
    return _queue(state, Effect("body", play=play), Effect("after_play", power(state.powers, "AFTERIMAGE"), play))


def _after_play(state, play, afterimage):
    if state.late:
        if play.card.variant.kind == "Skill":
            if any(c.variant.name == "PINPOINT" for c in state.hand):
                state = replace(state, hand=tuple(replace(c, variant=replace(c.variant, cost=max(0, c.variant.cost - 1)))
                                if c.variant.name == "PINPOINT" else c for c in state.hand))
            state = replace(state, enemies=tuple(replace(e, powers=add_power(e.powers, "STRENGTH", n))
                            if e.hp > 0 and (n := power(e.powers, "ENRAGE")) else e for e in state.enemies))
        if (play.x if "costs_x" in play.card.variant.flags else play.card.variant.cost) >= 2:
            state = replace(state, block=state.block + power(state.powers, "DANSE_MACABRE"))
        for i, relic in enumerate(state.relics):
            if relic.used or relic.name != "IRON_CLUB":
                continue
            count = ((relic.counter or 0) + 1) % power(relic.stats, "cards")
            updated = replace(relic, counter=count, status="Active" if count == power(relic.stats, "cards") - 1 else "Normal")
            state = replace(state, relics=(*state.relics[:i], updated, *state.relics[i + 1:]))
            if not count:
                state = draw(state, 1)
                if state.boundary:
                    return state
    for i, relic in enumerate(state.relics):
        if relic.name not in ("VELVET_CHOKER", "POCKETWATCH") or relic.used:
            continue
        count = (relic.counter or 0) + 1
        if relic.name == "VELVET_CHOKER":
            if count >= power(relic.stats, "cards"):
                return boundary(state, "velvet choker cap")
            updated = replace(relic, counter=count)
        else:
            if count >= 4:
                return boundary(state, "pocketwatch card limit")
            updated = replace(relic, counter=count)
        state = replace(state, relics=(*state.relics[:i], updated, *state.relics[i + 1:]))
    if afterimage:
        state = replace(state, block=state.block + afterimage)
    if play.card.variant.kind == "Skill":
        for i, relic in enumerate(state.relics):
            if relic.name in ("TUNING_FORK", "LETTER_OPENER") and not relic.used:
                threshold = power(relic.stats, "cards")
                if not threshold or relic.counter is None:
                    return boundary(state, "skill relic counter")
                n = (relic.counter + 1) % threshold
                updated = replace(relic, counter=n, status="Active" if n == threshold - 1 else "Normal")
                state = replace(state, relics=(*state.relics[:i], updated, *state.relics[i+1:]),
                                block=state.block + (0 if n else power(relic.stats, "block")))
                if n == 0 and relic.name == "LETTER_OPENER":
                    for enemy in state.enemies:
                        if enemy.hp > 0:
                            state = _damage(state, enemy.slot, power(relic.stats, "damage"))
                            if state.boundary or state.outcome:
                                return state
        for enemy in state.enemies:
            if enemy.hp > 0 and (spark := power(enemy.powers, "VITAL_SPARK")):
                state = _enemy_change(state, enemy.slot,
                                      lambda e: replace(e, attack_delta=e.attack_delta + spark))
                state = _add_player_power(state, "TAINTED", spark)
    if play.card.variant.kind == "Attack":
        state = _attack_relics(state)
    return state


def _attack_relics(state):
    target = None
    extra_damage = 0
    relics = []
    for relic in state.relics:
        if state.late and not relic.used and relic.name in ("SHURIKEN", "KUNAI"):
            count = ((relic.counter or 0) + 1) % power(relic.stats, "cards")
            if not count:
                name = "STRENGTH" if relic.name == "SHURIKEN" else "DEXTERITY"
                state = _add_player_power(state, name, power(relic.stats, name.lower() + "power"))
            relic = replace(relic, counter=count, status="Active" if count == power(relic.stats, "cards") - 1 else "Normal")
        if not relic.used and relic.name == "PEN_NIB":
            counter = (relic.counter or 0) + 1
            relic = replace(relic, counter=counter, status="Active" if counter == 9 else "Normal")
        if not relic.used and relic.name in ("RIPPLE_BASIN", "ART_OF_WAR"):
            relic = replace(relic, status="Normal")
        if not relic.used and relic.name == "DAUGHTER_OF_THE_WIND":
            state = replace(state, block=state.block + power(relic.stats, "block"))
        if not relic.used and relic.name in ("KUSARIGAMA", "NUNCHAKU", "ORNAMENTAL_FAN"):
            threshold = power(relic.stats, "cards")
            if relic.counter is None or not 0 <= relic.counter < threshold:
                return boundary(state, "kusarigama counter")
            counter = (relic.counter + 1) % threshold
            if counter == 0 and relic.name == "NUNCHAKU":
                state = replace(state, energy=state.energy + power(relic.stats, "energy"))
            if counter == 0 and relic.name == "ORNAMENTAL_FAN":
                state = replace(state, block=state.block + power(relic.stats, "block"))
            if counter == 0 and relic.name == "KUSARIGAMA":
                enemies = tuple(e.slot for e in state.enemies if e.hp > 0)
                if len(enemies) != 1:
                    return boundary(state, "kusarigama random target")
                target, = enemies
                extra_damage = power(relic.stats, "damage")
            relic = replace(relic, counter=counter, status="Active" if counter == threshold - 1 else "Normal")
        relics.append(relic)
    state = replace(state, relics=tuple(relics))
    return _damage(state, target, extra_damage) if target is not None else state


def _discard_cards(state, slots):
    if slots and any(r.name == "TINGSHA" and not r.used for r in state.relics):
        return boundary(state, "tingsha discard target")
    cards = tuple(c for c in state.hand if c.slot in slots)
    if state.late and cards:
        gain = sum(power(r.stats, "block") for r in state.relics if r.name == "TOUGH_BANDAGES" and not r.used)
        state = replace(state, block=state.block + gain * len(cards))
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
    discarded = list(state.discard)
    discarded.remove(outside_hand(v))
    return _queue(replace(state, discard=tuple(discarded), play=(*state.play, v)),
                  Effect("play", play=Play(card, candidates[0])))

def _finish(state, play, plays):
    v = play.card.variant
    # Powers are consumed. Frantic Escape remains the same copy, with a combat
    # cost increase, after its play.
    remaining = list(state.play)
    remaining.remove(v)
    return _finish_card(replace(state, play=tuple(remaining)), play, plays)


def _finish_card(state, play, plays=1):
    v = play.card.variant
    if state.right_hand_return and (play.x if "costs_x" in v.flags else v.cost) >= 2:
        returns = [copy for copy in state.discard if copy.name == "RIGHT_HAND_HAND"]
        if returns:
            if len(returns) != 1 or len(state.hand) >= HAND_CAP or plays != 1:
                return boundary(state, "right hand return ordering")
            state = replace(state, discard=tuple(c for c in state.discard if c.name != "RIGHT_HAND_HAND"),
                            hand=(*state.hand, Card(state.next_slot, returns[0])), next_slot=state.next_slot + 1)
    if v.kind != "Power":
        exhausted = "Exhaust" in v.keywords or "exhaust_on_next_play" in v.flags
        if exhausted and any(r.name == "JOSS_PAPER" for r in state.relics):
            return boundary(state, "joss paper exhaust counter")
        if v.name == "FRANTIC_ESCAPE":
            v = replace(v, cost=v.cost + plays)
        if "costs_x" in v.flags:
            v = replace(v, cost=play.x)
        state = _put(state, "exhaust" if exhausted else "discard", v)
        if state.late and exhausted:
            state = late_encounters.on_exhaust(state)
            if state.outcome or state.boundary:
                return state
    if not state.hand and any(r.name == "UNCEASING_TOP" and not r.used for r in state.relics):
        return draw(state, 1)
    return state


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
                state = _finish(state, event.play, event.amount)
            case "draw":
                state = draw(state, event.amount)
            case "prompt":
                slots = tuple(c.slot for c in state.hand)
                count = min(len(slots), event.amount)
                if count and count == len(slots):
                    state = _discard_cards(state, slots)
                elif count:
                    state = replace(state, prompt=Prompt(event.play.card.variant.name, slots, count, count))
            case "discard":
                state = _discard_cards(state, event.slots)
            case "sly":
                state = _sly(state, event.play.card)
            case "hidden_daggers_shivs":
                state = _shiv(state, 2, event.amount)
    return boundary(state, "automatic event cap") if state.queue else state


def _potion(state, move):
    if state.late and len(state.potions) == 1 and any(r.name == "BELT_BUCKLE" for r in state.relics):
        return boundary(state, "belt buckle last potion")
    if any(r.name == "REPTILE_TRINKET" and not r.used for r in state.relics):
        return boundary(state, "reptile trinket temporary strength")
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
    if kind == "speed":
        return _add_player_power(_add_player_power(state, "DEXTERITY", amount), "SPEED_POTION", amount)
    if kind in ("strength", "dexterity", "duplication", "intangible", "gigantification", "plating", "thorns"):
        return _add_player_power(state, kind.upper(), amount)
    slots = tuple(e.slot for e in state.enemies if e.hp > 0) if kind == "damage" and move.target < 0 else (move.target,)
    for slot in slots:
        if slot < 0:
            return boundary(state, "potion target")
        state = (_damage(state, slot, amount) if kind == "damage" else
                 _debuff(state, slot, kind.upper(), amount))
        if state.outcome or state.boundary:
            break
    return state


def advance(state, move):
    if state.late and move.target >= 0 and power(state.powers, "SURROUNDED"):
        state = replace(state, facing=move.target)
    result = _advance(state, move)
    if result.late and (not result.boundary or result.outcome == "completed"):
        for i, relic in enumerate(result.relics):
            if relic.name == "MEAT_ON_THE_BONE" and not relic.used:
                status = "Active" if result.hp * 2 <= result.max_hp else "Normal"
                if relic.status != status:
                    result = replace(result, relics=(*result.relics[:i], replace(relic, status=status), *result.relics[i + 1:]))
    if (result.late and not result.boundary and not result.outcome and result.facing != result.preview_facing
            or not result.outcome and not result.boundary and result.enemies != state.enemies
            and any(e.preview_weak or e.attack_delta or state.preview_intangible for e in result.enemies)):
        from .end_turn import attack_amount

        if any(attack_amount(result, e, intent) is None for e in result.enemies if e.hp > 0
               for intent in e.intents if intent.damage is not None):
            return boundary(result, "ambiguous attack preview")
    return result


def _advance(state, move):
    """Apply a previously enumerated local move."""
    if move.kind == "end_turn":
        from .end_turn import resolve
        return resolve(state)
    if move.kind == "select_cards":
        if state.late and state.prompt.operation == "KNOWLEDGE_CURSE":
            return late_encounters.choose_curse(state, move.selection[0])
        if state.late and state.prompt.operation == "TOASTY_MITTENS":
            card = next(c for c in state.hand if c.slot == move.selection[0])
            if any(r.name == "JOSS_PAPER" for r in state.relics):
                return boundary(state, "joss paper exhaust counter")
            state = replace(state, prompt=None, hand=tuple(c for c in state.hand if c.slot != card.slot))
            state = late_encounters.on_exhaust(_put(state, "exhaust", card.variant))
            if state.boundary or state.outcome:
                return state
            if power(state.powers, "PLATING"):
                state = _add_player_power(state, "PLATING", -1)
            return _add_player_power(state, "STRENGTH", 1)
        if not state.queue and state.play:
            v, = state.play
            state = _queue(state, Effect("after_play", power(state.powers, "AFTERIMAGE"), Play(Card(-1, v))),
                           Effect("finish", play=Play(Card(-1, v))))
        return _drain(_queue(replace(state, prompt=None), Effect("discard", slots=move.selection)))
    if move.kind == "use_potion":
        return _potion(state, move)
    card = next(c for c in state.hand if c.slot == move.slot)
    v = card.variant
    if state.late:
        if late_encounters.bound(v):
            state = replace(state, bound_used=True)
        if any(power(e.powers, "WITHERING_PRESENCE") for e in state.enemies):
            if late_encounters.untracked_plays(state, v) or state.aeon_plays < 0:
                return boundary(state, "withering presence automatic play count")
            if state.aeon_plays % 6 == 5:
                return boundary(state, "withering presence creates wither")
            state = replace(state, aeon_plays=state.aeon_plays + 1)
        if power(state.powers, "SLOTH"):
            if late_encounters.untracked_plays(state, v):
                return boundary(state, "sloth automatic play count")
            state = replace(state, sloth_plays=state.sloth_plays + 1)
    if not card_supported(v, state.late):
        return boundary(state, f"card/{v.name}")
    x = state.energy if "costs_x" in v.flags else 0
    state = replace(state, energy=state.energy - (x if "costs_x" in v.flags else v.cost),
                    hand=tuple(c for c in state.hand if c.slot != move.slot))
    play = Play(card, move.target, x)
    if state.late and v.name == "SHIV" and any(r.name == "HELICAL_DART" for r in state.relics):
        return boundary(state, "helical dart temporary dexterity")
    if (v.name in SIMPLE_CARDS and not (state.late and (power(state.powers, "DANSE_MACABRE") or
            any(c.variant.name == "PINPOINT" for c in state.hand) or
            any(power(e.powers, "ENRAGE") for e in state.enemies) or
            any(r.name in ("IRON_CLUB", "SHURIKEN", "KUNAI") for r in state.relics)))
            and not any(r.name in ("VELVET_CHOKER", "POCKETWATCH", "ART_OF_WAR", "PEN_NIB") for r in state.relics)
            and not any(power(state.powers, p) for p in ("DUPLICATION", "BURST", "AFTERIMAGE"))
            and (v.kind != "Attack" or not any(
                r.name in ("KUSARIGAMA", "RIPPLE_BASIN", "DAUGHTER_OF_THE_WIND", "NUNCHAKU", "ORNAMENTAL_FAN")
                and not r.used for r in state.relics))
            and (v.kind != "Skill" or (not any(power(e.powers, "VITAL_SPARK") for e in state.enemies)
                                       and not any(r.name in ("TUNING_FORK", "LETTER_OPENER") for r in state.relics)))):
        # With no listening triggers this play cannot suspend or replay.
        state = _card_effect(state, play)
        return state if state.outcome or state.boundary else _finish_card(state, play)
    return _drain(_queue(replace(state, play=(*state.play, v)), Effect("play", play=play)))

