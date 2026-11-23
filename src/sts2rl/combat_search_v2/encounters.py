"""Encounter-specific hooks with visible preconditions."""
from dataclasses import replace

from .state import Boundary, Intent, Variant, add_power, power, set_power

BEETLE = "SHRINKER_BEETLE"
STRANGLER = "SLITHERING_STRANGLER"
JAXFRUIT = "SNAPPING_JAXFRUIT"
INSATIABLE = "THE_INSATIABLE"
PRISM = "INFESTED_PRISM"
ORDINARY = {BEETLE, STRANGLER, JAXFRUIT, "TWIG_SLIME_M", "TWIG_SLIME_S", "WRIGGLER",
            "NIBBIT", "FUZZY_WURM_CRAWLER", "MAWLER", "LEAF_SLIME_M", "LEAF_SLIME_S"}
SLIMED_COUNT = {"TWIG_SLIME_M": 1, "TWIG_SLIME_S": 1, "LEAF_SLIME_M": 2, "LEAF_SLIME_S": 1}
FORMATIONS = ORDINARY | {
    INSATIABLE, PRISM, "KIN_FOLLOWER", "KIN_PRIEST", "CEREMONIAL_BEAST", "FLYCONID",
    "TUNNELER", "CHOMPER", "CUBEX_CONSTRUCT", "VANTOM", "INKLET", "SOUL_FYSH",
    "LAGAVULIN_MATRIARCH", "WATERFALL_GIANT", "BOWLBUG_ROCK", "BOWLBUG_EGG",
    "BOWLBUG_NECTAR", "ENTOMANCER", "BYRDONIS", "EXOSKELETON", "HUNTER_KILLER",
    "VINE_SHAMBLER", "SPINY_TOAD", "LOUSE_PROGENITOR", "MYTE",
    "THE_OBSCURA", "PARAFRIGHT", "THIEVING_HOPPER",
}
DAZED = Variant("DAZED", "Status", 0, "None", keywords=("Ethereal", "Unplayable"))
WOUND = Variant("WOUND", "Status", 0, "None", keywords=("Unplayable",))
BECKON = Variant("BECKON", "Status", 1, "None")
TOXIC = Variant("TOXIC", "Status", 1, "None", keywords=("Exhaust",))
STUN = (Intent("Stun"),)

# These profiles need latent phase, move or generated-card state.
ENCOUNTER_BOUNDARIES = {
    "MECHA_KNIGHT": "mecha reattach", "MECHA_KNIGHT_SEGMENT": "mecha reattach",
    "KNOWLEDGE_DEMON": "knowledge demon prompt/sloth",
    "CRUSHER": "kaiser facing", "ROCKET": "kaiser facing", "KAISER_CRAB": "kaiser facing",
    "ROCK_BOWLBUG": "bowlbug stun source", "AXEBOT": "axebot stock",
}


def encounter_reason(state):
    living = tuple(e.name for e in state.enemies if e.hp > 0)
    if not living:
        return "no living enemy"
    for name in living:
        if name not in FORMATIONS:
            return ENCOUNTER_BOUNDARIES.get(name, f"profile/{name}")
    if INSATIABLE in living and living != (INSATIABLE,):
        return "sandpit formation"
    if PRISM in living and living != (PRISM,):
        return "vital spark formation"
    if "KIN_FOLLOWER" in living and living.count("KIN_PRIEST") != 1:
        return "kin leader dependency"
    if any(power(e.powers, "MINION") and e.name not in ("KIN_FOLLOWER", "PARAFRIGHT")
           for e in state.enemies if e.hp > 0):
        return "unqualified minion dependency"
    if "THE_OBSCURA" in living and state.round > 1 and "PARAFRIGHT" not in living:
        return "obscura hidden revival state"
    if power(state.powers, "CONSTRICT") and living.count(STRANGLER) != 1:
        return "constrict source"
    if power(state.powers, "SHRINK") and living.count(BEETLE) != 1:
        return "shrink source"
    return None


def after_death(state, enemy):
    if enemy.name not in FORMATIONS:
        reason = ENCOUNTER_BOUNDARIES.get(enemy.name, f"death phase/{enemy.name}")
        return replace(state, boundary=Boundary(reason))
    if power(enemy.powers, "STEAM_ERUPTION"):
        return replace(state, boundary=Boundary("steam eruption on death"))
    if power(enemy.powers, "THORNS"):
        return replace(state, boundary=Boundary("lethal thorns ordering"))
    if enemy.name == "PARAFRIGHT":
        return replace(state, boundary=Boundary("illusion revival"))
    if enemy.name in ("KIN_PRIEST", "THE_OBSCURA"):
        minion = "KIN_FOLLOWER" if enemy.name == "KIN_PRIEST" else "PARAFRIGHT"
        state = replace(state, enemies=tuple(replace(e, hp=0) if e.name == minion else e
                                             for e in state.enemies))
    if not any(e.hp > 0 for e in state.enemies):
        return replace(state, outcome="victory", queue=(), prompt=None)
    removed = {BEETLE: "SHRINK", STRANGLER: "CONSTRICT"}.get(enemy.name)
    return replace(state, powers=set_power(state.powers, removed, 0)) if removed else state


def after_damage(state, before, enemy):
    if enemy.hp == 0:
        return after_death(state, enemy)
    powers = enemy.powers
    if power(powers, "BURROWED") and before.block > 0 and enemy.block == 0:
        return _update(state, enemy.slot, powers=set_power(powers, "BURROWED", 0), intents=STUN)
    if enemy.hp < before.hp:
        if (plow := power(powers, "PLOW")) and enemy.hp <= plow:
            powers = set_power(set_power(powers, "PLOW", 0), "STRENGTH", 0)
            return _update(state, enemy.slot, powers=powers, intents=STUN)
        if power(powers, "ASLEEP"):
            powers = set_power(set_power(powers, "ASLEEP", 0), "PLATING", 0)
            return _update(state, enemy.slot, powers=powers, intents=STUN)
    return state


def add_cards(state, zone, card, amount):
    return replace(state, **{zone: tuple(sorted((*getattr(state, zone), *((card,) * amount))))})


def after_attack(state, before, enemy):
    if enemy.hp <= 0:
        return state
    powers = enemy.powers
    if enemy.hp < before.hp and (flutter := power(powers, "FLUTTER")):
        if flutter == 1:
            return replace(state, boundary=Boundary("flutter stun transition"))
        state = _update(state, enemy.slot, powers=add_power(powers, "FLUTTER", -1))
    if hive := power(powers, "PERSONAL_HIVE"):
        state = add_cards(state, "draw", DAZED, hive)
    if enemy.hp < before.hp and (curl := power(powers, "CURL_UP")):
        state = _update(state, enemy.slot, block=enemy.block + curl, powers=set_power(powers, "CURL_UP", 0))
    if thorns := power(powers, "THORNS"):
        from .end_turn import _hurt

        return _hurt(state, thorns)
    return state


def player_debuff(state, name, amount):
    if power(state.powers, "ARTIFACT"):
        return replace(state, powers=add_power(state.powers, "ARTIFACT", -1))
    return replace(state, powers=add_power(state.powers, name, amount))


def _strength(state, enemy, amount):
    return _update(state, enemy.slot, powers=add_power(enemy.powers, "STRENGTH", amount))


def escape(state):
    source = next((e for e in state.enemies if e.name == INSATIABLE and e.hp > 0), None)
    if source is None or not power(source.powers, "SANDPIT"):
        return replace(state, boundary=Boundary("escape source"))
    enemies = tuple(replace(e, powers=add_power(e.powers, "SANDPIT", 1))
                    if e.slot == source.slot else e for e in state.enemies)
    return replace(state, enemies=enemies)


def before_move(state, enemy):
    countdown = power(enemy.powers, "SANDPIT")
    if enemy.name != INSATIABLE or countdown <= 0:
        return state
    if countdown == 1:
        return replace(state, hp=0, outcome="dead")
    enemies = tuple(replace(e, powers=add_power(e.powers, "SANDPIT", -1))
                    if e.slot == enemy.slot else e for e in state.enemies)
    return replace(state, enemies=enemies)


def after_move(state, enemy):
    """Resolve the pinned non-attack portion of a known current move."""
    kinds = {intent.kind for intent in enemy.intents if intent.damage is None}
    profile = enemy.name
    if profile == "SPINY_TOAD":
        if kinds == {"Buff"}:
            return _update(state, enemy.slot, powers=set_power(enemy.powers, "THORNS", 5))
        if power(enemy.powers, "THORNS"):
            return _update(state, enemy.slot, powers=set_power(enemy.powers, "THORNS", 0))
    if profile == "BYRDONIS" and not kinds:
        return _strength(state, enemy, power(enemy.powers, "TERRITORIAL"))
    if profile == "THIEVING_HOPPER":
        if "Escape" in kinds or "CardDebuff" in kinds:
            return replace(state, boundary=Boundary("thieving hopper steal or escape"))
        powers = add_power(enemy.powers, "ESCAPE_ARTIST", -1)
        if kinds == {"Buff"}:
            powers = add_power(powers, "FLUTTER", 5)
        if not kinds or kinds in ({"Buff"}, {"Stun"}):
            return _update(state, enemy.slot, powers=powers)
    if not kinds or kinds == {"Stun"}:
        return state
    if profile == "THE_OBSCURA":
        if kinds == {"Defend"}:
            return _update(state, enemy.slot, block=7)
        if kinds == {"Buff"}:
            for living in state.enemies:
                if living.hp > 0:
                    state = _strength(state, living, 3)
            return state
    if profile == "CEREMONIAL_BEAST":
        if kinds == {"Buff"} and state.round == 1:
            return _update(state, enemy.slot, powers=add_power(enemy.powers, "PLOW", 160))
        if kinds == {"Buff"}:
            return _strength(state, enemy, 2 if power(enemy.powers, "PLOW") else 4)
        if kinds == {"Debuff"}:
            return replace(state, boundary=Boundary("ceremonial ringing affliction"))
    if profile in ("KIN_PRIEST", "KIN_FOLLOWER") and kinds == {"Buff"}:
        return _strength(state, enemy, 3)
    if profile == "KIN_PRIEST" and kinds == {"Debuff"} and state.round % 4 in (1, 2):
        return player_debuff(state, "FRAIL" if state.round % 4 == 1 else "WEAK", 1)
    if profile == "FLYCONID" and kinds == {"Debuff"}:
        return player_debuff(state, "FRAIL" if any(i.damage is not None for i in enemy.intents)
                             else "VULNERABLE", 2)
    if profile == "TUNNELER" and kinds == {"Buff", "Defend"}:
        return _update(state, enemy.slot, block=37, powers=add_power(enemy.powers, "BURROWED", 1))
    if profile == "CHOMPER" and kinds == {"StatusCard"}:
        return add_cards(state, "discard", DAZED, 3)
    if profile in ("CUBEX_CONSTRUCT", "EXOSKELETON", "VANTOM") and kinds == {"Buff"}:
        return _strength(state, enemy, 2)
    if profile == "VANTOM" and kinds == {"StatusCard"}:
        return add_cards(state, "discard", WOUND, 3)
    if profile == "BOWLBUG_EGG" and kinds == {"Defend"}:
        return _update(state, enemy.slot, block=8)
    if profile == "BOWLBUG_NECTAR" and kinds == {"Buff"}:
        return _strength(state, enemy, 16)
    if profile == "ENTOMANCER" and kinds == {"Buff"}:
        return _update(state, enemy.slot, powers=add_power(add_power(enemy.powers, "STRENGTH", 1),
                                                          "PERSONAL_HIVE", 1))
    if profile == "HUNTER_KILLER" and kinds == {"Debuff"}:
        return player_debuff(state, "TENDER", 1)
    if profile == "VINE_SHAMBLER" and kinds == {"CardDebuff"}:
        return replace(state, boundary=Boundary("vine entangled affliction"))
    if profile == "MYTE":
        if kinds == {"StatusCard"}:
            return add_cards(state, "draw", TOXIC, 2)
        if kinds == {"Buff"}:
            return _strength(state, enemy, 3)
    if profile == "LOUSE_PROGENITOR":
        if kinds == {"Debuff"}:
            return player_debuff(state, "FRAIL", 2)
        if kinds == {"Buff", "Defend"}:
            return _strength(_update(state, enemy.slot, block=18), enemy, 7)
    if profile == "SOUL_FYSH":
        if kinds == {"StatusCard"}:
            state = add_cards(state, "draw", BECKON, 1)
            return state if any(i.damage is not None for i in enemy.intents) else add_cards(
                state, "discard", BECKON, 1)
        if kinds == {"Buff"}:
            return _update(state, enemy.slot, powers=add_power(enemy.powers, "INTANGIBLE", 1))
        if kinds == {"Debuff"}:
            return player_debuff(state, "VULNERABLE", 3)
    if profile == "LAGAVULIN_MATRIARCH":
        if kinds == {"Sleep"} and (asleep := power(enemy.powers, "ASLEEP")):
            powers = add_power(enemy.powers, "ASLEEP", -1)
            plating = max(0, power(powers, "PLATING") - (asleep == 2)) if asleep > 1 else 0
            return _update(state, enemy.slot, block=plating, powers=set_power(powers, "PLATING", plating))
        if kinds == {"Defend"}:
            return _update(state, enemy.slot, block=14)
        if kinds == {"Buff", "Debuff"}:
            state = player_debuff(player_debuff(state, "STRENGTH", -2), "DEXTERITY", -2)
            return _strength(state, enemy, 2)
    if profile == "WATERFALL_GIANT" and kinds in ({"Buff"}, {"Buff", "Debuff"}, {"Heal", "Buff"}):
        current = power(enemy.powers, "STEAM_ERUPTION")
        hp = min(enemy.hp + 15, enemy.max_hp) if "Heal" in kinds else enemy.hp
        state = _update(state, enemy.slot, hp=hp,
                        powers=set_power(enemy.powers, "STEAM_ERUPTION", current + 3 if current else 20))
        return player_debuff(state, "WEAK", 1) if "Debuff" in kinds else state
    if enemy.name == BEETLE and kinds == {"DebuffStrong"}:
        if power(state.powers, "ARTIFACT"):
            return replace(state, powers=add_power(state.powers, "ARTIFACT", -1))
        return replace(state, powers=set_power(state.powers, "SHRINK", -1))
    if enemy.name == STRANGLER and kinds == {"Debuff"}:
        if power(state.powers, "ARTIFACT"):
            return replace(state, powers=add_power(state.powers, "ARTIFACT", -1))
        return replace(state, powers=add_power(state.powers, "CONSTRICT", 3))
    if enemy.name == STRANGLER and kinds == {"Defend"}:
        return _update(state, enemy.slot, block=5)
    if enemy.name == JAXFRUIT and kinds == {"Buff"}:
        return _update(state, enemy.slot, powers=add_power(enemy.powers, "STRENGTH", 2))
    if enemy.name == "NIBBIT" and kinds == {"Buff"}:
        return _update(state, enemy.slot, powers=add_power(enemy.powers, "STRENGTH", 3))
    if enemy.name == "NIBBIT" and kinds == {"Defend"}:
        return _update(state, enemy.slot, block=6)
    if enemy.name == "FUZZY_WURM_CRAWLER" and kinds == {"Buff"}:
        return _update(state, enemy.slot, powers=add_power(enemy.powers, "STRENGTH", 7))
    if enemy.name == "MAWLER" and kinds == {"Debuff"}:
        if power(state.powers, "ARTIFACT"):
            return replace(state, powers=add_power(state.powers, "ARTIFACT", -1))
        return replace(state, powers=add_power(state.powers, "VULNERABLE", 3))
    if enemy.name in SLIMED_COUNT and kinds == {"StatusCard"}:
        status = Variant("SLIMED", "Status", 1, "None", keywords=("Exhaust",), stats=(("cards", 1),))
        return replace(state, discard=tuple(sorted(state.discard + (status,) * SLIMED_COUNT[enemy.name])))
    if enemy.name == "WRIGGLER" and kinds in ({"Buff"}, {"Buff", "StatusCard"}):
        if "StatusCard" in kinds:
            status = Variant("INFECTION", "Status", 0, "None", keywords=("Unplayable",),
                             stats=(("damage", 3),))
            state = replace(state, discard=tuple(sorted((*state.discard, status))))
        return _update(state, enemy.slot, powers=add_power(enemy.powers, "STRENGTH", 2))
    if enemy.name == INSATIABLE and kinds == {"Buff"}:
        return _update(state, enemy.slot, powers=add_power(enemy.powers, "STRENGTH", 3))
    if enemy.name == INSATIABLE and kinds == {"Buff", "StatusCard"} and not power(enemy.powers, "SANDPIT"):
        status = Variant("FRANTIC_ESCAPE", "Status", 1, "Self")
        state = add_cards(add_cards(state, "draw", status, 3), "discard", status, 3)
        return _update(state, enemy.slot, powers=add_power(enemy.powers, "SANDPIT", 4))
    if enemy.name == PRISM and kinds == {"Defend"}:
        return _update(state, enemy.slot, block=13)
    if enemy.name == PRISM and kinds == {"Buff", "Defend"}:
        return _update(state, enemy.slot, block=22, powers=add_power(enemy.powers, "VITAL_SPARK", 3))
    return replace(state, boundary=Boundary(f"enemy intent/{enemy.name}/{'+'.join(sorted(kinds))}"))


def _update(state, slot, **changes):
    return replace(state, enemies=tuple(replace(e, **changes) if e.slot == slot else e for e in state.enemies))
