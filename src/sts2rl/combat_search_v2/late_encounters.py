"""Pinned v0.111.0 late-encounter hooks, enabled only on v6 late roots."""
from dataclasses import replace

from .state import Boundary, Prompt, Variant, add_power, power, set_power

PROFILES = {
    "CRUSHER", "ROCKET", "KNOWLEDGE_DEMON", "SCROLL_OF_BITING", "LIVING_SHIELD", "TURRET_OPERATOR",
    "SLIMED_BERSERKER", "TEST_SUBJECT", "TORCH_HEAD_AMALGAM", "QUEEN", "AXEBOT", "OWL_MAGISTRATE",
    "THE_LOST", "THE_FORGOTTEN", "GLOBE_HEAD", "MECHA_KNIGHT", "FROG_KNIGHT", "AEONGLASS",
    "FLAIL_KNIGHT", "MAGI_KNIGHT", "SPECTRAL_KNIGHT", "FABRICATOR", "NOISEBOT", "ZAPBOT",
}
PLAYER = {"SURROUNDED", "MIND_ROT", "WASTE_AWAY", "SLOTH", "CHAINS_OF_BINDING",
          "ENVENOM", "FLEX_POTION", "INFINITE_BLADES", "HEX", "DAMPEN", "RETAIN_HAND", "CONFUSED"}
ENEMY = {"BACK_ATTACK_LEFT", "BACK_ATTACK_RIGHT", "CRAB_RAGE", "PAPER_CUTS", "RAMPART",
         "ADAPTABLE", "ENRAGE", "STOCK", "SOAR", "POSSESS_STRENGTH", "POSSESS_SPEED", "DEXTERITY", "GALVANIC",
         "WITHERING_PRESENCE", "DEMISE", "PAINFUL_STABS", "HIGH_VOLTAGE"}

WITHER = Variant("WITHER", "Status", 0, "None", keywords=("Unplayable",), stats=(("damage", 3),))


def bound(v):
    return any(m[:2] == ("affliction_state", "BOUND") for m in v.modifier)


def unbind(v):
    return replace(v, modifier=tuple(m for m in v.modifier if m[:2] != ("affliction_state", "BOUND"))) if bound(v) else v


def untracked_plays(state, card):
    from .transitions import card_supported

    if not card_supported(card, True) or power(state.powers, "DUPLICATION"):
        return True
    if card.kind == "Skill" and power(state.powers, "BURST"):
        return True
    return card.name in ("ACROBATICS", "PREPARED", "SURVIVOR", "DAGGER_THROW", "CALCULATED_GAMBLE",
                         "HIDDEN_DAGGERS") and any("Sly" in c.variant.keywords or "sly_this_turn" in c.variant.flags
                                                   for c in state.hand)


def reason(state):
    if any(r.name == "TOY_BOX" for r in state.relics) and any(r.status == "Disabled" for r in state.relics):
        return "disabled wax relic"
    if power(state.powers, "SURROUNDED") and (state.facing < 0 or state.preview_facing < 0):
        return "unwitnessed facing"
    if power(state.powers, "SLOTH") and state.sloth_plays < 0:
        return "unwitnessed sloth count"
    if any(e.name == "AEONGLASS" for e in state.enemies) and state.aeon_plays < 0:
        return "unwitnessed wither count"
    return None


def curse_options(ordinal):
    return (("DISINTEGRATION", 6 + ordinal), (("MIND_ROT", 1), ("SLOTH", 3), ("WASTE_AWAY", 1))[ordinal])


def choose_curse(state, index):
    from .end_turn import _start_player, _tick
    from .encounters import player_debuff

    name, amount = state.curse_options[index]
    if power(state.powers, "ARTIFACT"):
        return replace(state, boundary=Boundary("knowledge curse artifact"))
    prior = state.powers
    state = player_debuff(state, name, amount)
    if name == "WASTE_AWAY":
        state = replace(state, max_energy=state.max_energy - amount)
    enemy, = state.enemies
    if demise := power(enemy.powers, "DEMISE"):
        if enemy.hp <= demise or power(enemy.powers, "INTANGIBLE"):
            return replace(state, boundary=Boundary("demise lethal or intangible"))
        enemy = replace(enemy, hp=enemy.hp - demise)
    enemy = replace(enemy, powers=_tick(enemy.powers, ("WEAK", "VULNERABLE", "INTANGIBLE")), attack_delta=0)
    return _start_player(replace(state, enemies=(enemy,), prompt=None, curse_options=()), prior)


def move(state, enemy, kinds):
    from .encounters import _strength, _update, add_cards, player_debuff

    name = enemy.name
    if name in ("CRUSHER", "ROCKET"):
        if kinds == {"Buff"}:
            return _strength(state, enemy, 3)
        if name == "CRUSHER" and kinds == {"Debuff"}:
            return player_debuff(player_debuff(state, "WEAK", 2), "FRAIL", 2)
        if name == "CRUSHER" and kinds == {"Defend"}:
            return _update(state, enemy.slot, block=18)
        if name == "ROCKET" and kinds == {"Sleep"}:
            return state
    if name == "KNOWLEDGE_DEMON":
        if kinds == {"Debuff"}:
            if state.curse_number in range(3):
                relics = tuple(replace(r, counter=0, status="Normal") if r.name == "KUSARIGAMA"
                               else replace(r, status="Normal") if r.name == "RIPPLE_BASIN" else r
                               for r in state.relics)
                return replace(state, prompt=Prompt("KNOWLEDGE_CURSE", (0, 1), 1, 1),
                               relics=relics, curse_options=curse_options(state.curse_number))
            return replace(state, boundary=Boundary("unwitnessed knowledge curse sequence"))
        if kinds == {"Buff", "Heal"}:
            return _update(state, enemy.slot, hp=min(enemy.max_hp, enemy.hp + 30),
                           powers=add_power(enemy.powers, "STRENGTH", 3))
    if name == "SCROLL_OF_BITING" and kinds == {"Buff"}:
        return _strength(state, enemy, 2)
    if name == "TURRET_OPERATOR":
        if kinds == {"Buff"}:
            state = _strength(state, enemy, 1)
        if not kinds or kinds == {"Buff"}:
            return state
    if name == "SLIMED_BERSERKER":
        if kinds == {"StatusCard"}:
            slimed = Variant("SLIMED", "Status", 1, "None", keywords=("Exhaust",), stats=(("cards", 1),))
            return add_cards(state, "discard", slimed, 10)
        if kinds == {"Buff", "Debuff"}:
            return player_debuff(_strength(state, enemy, 3), "WEAK", 3)
    if name == "TEST_SUBJECT" and kinds == {"Debuff"}:
        if not power(enemy.powers, "ENRAGE"):
            return replace(state, boundary=Boundary("test subject transformed debuff"))
        return player_debuff(state, "VULNERABLE", 1)
    if name == "FLAIL_KNIGHT" and kinds == {"Buff"}:
        return _strength(state, enemy, 3)
    if name == "MAGI_KNIGHT" and kinds == {"Defend"}:
        return _update(state, enemy.slot, block=9)
    if name == "ZAPBOT" and not kinds:
        return _strength(state, enemy, power(enemy.powers, "HIGH_VOLTAGE"))
    if name == "NOISEBOT" and kinds == {"StatusCard"}:
        from .encounters import DAZED
        return add_cards(state, "discard", DAZED, 2)
    if name == "QUEEN" and kinds == {"Defend", "Buff"}:
        allies = [e for e in state.enemies if e.hp > 0 and e.name == "TORCH_HEAD_AMALGAM"]
        if len(allies) == 1:
            return _strength(_update(state, enemy.slot, block=20), allies[0], 1)
    if name == "QUEEN" and kinds == {"CardDebuff"}:
        return player_debuff(state, "CHAINS_OF_BINDING", 3)
    if name == "QUEEN" and kinds == {"Debuff"}:
        if power(state.powers, "ARTIFACT"):
            return replace(state, boundary=Boundary("queen artifact order"))
        for debuff in ("FRAIL", "WEAK", "VULNERABLE"):
            state = player_debuff(state, debuff, 99)
        return state
    if name == "AEONGLASS":
        if kinds == {"Defend"}:
            return _update(state, enemy.slot, block=33)
        if kinds == {"StatusCard", "Buff"}:
            return add_cards(_strength(state, enemy, 4), "discard", WITHER, 2)
    if name == "AXEBOT" and kinds == {"Debuff"}:
        return player_debuff(player_debuff(state, "WEAK", 2), "FRAIL", 2)
    if name == "OWL_MAGISTRATE":
        if kinds == {"Buff"}:
            return _update(state, enemy.slot, powers=set_power(enemy.powers, "SOAR", 1))
        if kinds == {"Debuff"} and power(enemy.powers, "SOAR"):
            return player_debuff(_update(state, enemy.slot, powers=set_power(enemy.powers, "SOAR", 0)),
                                 "VULNERABLE", 4)
    if name == "THE_LOST" and kinds == {"Debuff", "Buff"}:
        return player_debuff(_strength(state, enemy, 2), "STRENGTH", -2)
    if name == "THE_FORGOTTEN" and kinds == {"Debuff", "Buff", "Defend"}:
        dex = power(enemy.powers, "DEXTERITY")
        return player_debuff(_update(state, enemy.slot, block=8 + dex,
                             powers=add_power(enemy.powers, "DEXTERITY", 2)), "DEXTERITY", -2)
    if name == "GLOBE_HEAD":
        if kinds == {"Debuff"}:
            return player_debuff(state, "FRAIL", 2)
        if kinds == {"Buff"}:
            return _strength(state, enemy, 2)
    if name == "MECHA_KNIGHT" and kinds == {"Defend", "Buff"}:
        return _strength(_update(state, enemy.slot, block=15), enemy, 5)
    if name == "FROG_KNIGHT":
        plating = max(0, power(enemy.powers, "PLATING") - int(state.round > 1))
        state = _update(state, enemy.slot, block=plating, powers=set_power(enemy.powers, "PLATING", plating))
        if kinds == {"Buff"}:
            return _strength(state, state.enemies[enemy.slot], 5)
        if kinds == {"Debuff"}:
            return player_debuff(state, "FRAIL", 2)
    if not kinds:
        return state
    return replace(state, boundary=Boundary(f"enemy intent/{name}/{'+'.join(sorted(kinds))}"))

# The first group has completed its in-combat effect by the first public
# decision. Mutable counters and triggers in the second group have explicit hooks.
PASSIVE_RELICS = {
    "ROYAL_POISON", "LOOMING_FRUIT", "SLING_OF_COURAGE", "PANDORAS_BOX", "DRAGON_FRUIT",
    "MEAT_ON_THE_BONE", "MEAT_CLEAVER", "HEFTY_TABLET", "ORRERY", "BIG_MUSHROOM", "TOOLBOX",
    "GNARLED_HAMMER", "MYSTIC_LIGHTER", "SPIKED_GAUNTLETS", "DIAMOND_DIADEM", "TOY_BOX",
}
RELICS = PASSIVE_RELICS | {
    "FORGOTTEN_SOUL", "SHURIKEN", "KUNAI", "MERCURY_HOURGLASS", "MR_STRUGGLES", "IRON_CLUB",
    "TOUGH_BANDAGES", "STONE_CALENDAR", "STURDY_CLAMP", "FIDDLE", "HELICAL_DART",
    "TOASTY_MITTENS", "TUNGSTEN_ROD", "BREAD", "ICE_CREAM", "SNECKO_EYE", "RUNIC_PYRAMID", "BELT_BUCKLE",
}
ATTACKS = {"ASSASSINATE": (10, 13), "THE_HUNT": (10, 15), "ULTIMATE_STRIKE": (14, 20),
           "DRAMATIC_ENTRANCE": (11, 15), "ECHOING_SLASH": (10, 13), "PINPOINT": (15, 19)}
CARDS = ATTACKS.keys() | {"RELAX", "DANSE_MACABRE", "PREP_TIME", "HIDDEN_DAGGERS", "INFINITE_BLADES",
                         "SIDESTEP", "ENLIGHTENMENT", "DECAY", "BOUNCING_FLASK", "SHRUG_IT_OFF",
                         "HAND_TRICK", "SEEKER_STRIKE", "ACCURACY", "PHANTOM_BLADES"}
PLAYER |= {"DANSE_MACABRE", "PREP_TIME"}


def on_exhaust(state, count=1):
    from .transitions import _damage, boundary

    relic = next((r for r in state.relics if r.name == "FORGOTTEN_SOUL" and not r.used), None)
    if not relic or not count:
        return state
    living = [e for e in state.enemies if e.hp > 0]
    damage = power(relic.stats, "damage")
    if len(living) != 1 or living[0].hp <= damage * count:
        return boundary(state, "forgotten soul target or lethal")
    for _ in range(count):
        state = _damage(state, living[0].slot, damage)
        if state.boundary or state.outcome:
            break
    return state
