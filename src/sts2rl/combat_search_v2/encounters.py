"""Encounter-specific hooks with visible preconditions."""
from dataclasses import replace

from .state import Boundary, Variant, add_power, power, set_power

BEETLE = "SHRINKER_BEETLE"
STRANGLER = "SLITHERING_STRANGLER"
JAXFRUIT = "SNAPPING_JAXFRUIT"
INSATIABLE = "THE_INSATIABLE"
PRISM = "INFESTED_PRISM"
ORDINARY = {BEETLE, STRANGLER, JAXFRUIT, "TWIG_SLIME_M", "TWIG_SLIME_S", "WRIGGLER",
            "NIBBIT", "FUZZY_WURM_CRAWLER", "MAWLER", "LEAF_SLIME_M", "LEAF_SLIME_S"}
SLIMED_COUNT = {"TWIG_SLIME_M": 1, "TWIG_SLIME_S": 1, "LEAF_SLIME_M": 2, "LEAF_SLIME_S": 1}
FORMATIONS = ORDINARY | {INSATIABLE, PRISM}
# These profiles need latent phase, move or generated-card state.
ENCOUNTER_BOUNDARIES = {
    "CEREMONIAL_BEAST": "plow",
    "VANTOM": "vantom slippery and move hooks",
    "KIN_FOLLOWER": "kin leader dependency", "KIN_PRIEST": "kin leader dependency",
    "WATERFALL_GIANT": "waterfall eruption", "MECHA_KNIGHT": "mecha reattach",
    "MECHA_KNIGHT_SEGMENT": "mecha reattach", "ROCK_BOWLBUG": "bowlbug stun source",
    "BOWLBUG_ROCK": "bowlbug stun source",
    "ENTOMANCER": "entomancer dazed", "KNOWLEDGE_DEMON": "knowledge demon prompt/sloth",
    "KAISER_CRAB": "kaiser facing", "AXEBOT": "axebot stock",
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
    if power(state.powers, "CONSTRICT") and living.count(STRANGLER) != 1:
        return "constrict source"
    if power(state.powers, "SHRINK") and living.count(BEETLE) != 1:
        return "shrink source"
    return None


def after_death(state, enemy):
    if enemy.name not in FORMATIONS:
        reason = ENCOUNTER_BOUNDARIES.get(enemy.name, f"death phase/{enemy.name}")
        return replace(state, boundary=Boundary(reason))
    if not any(e.hp > 0 for e in state.enemies):
        return replace(state, outcome="victory", queue=(), prompt=None)
    removed = {BEETLE: "SHRINK", STRANGLER: "CONSTRICT"}.get(enemy.name)
    return replace(state, powers=set_power(state.powers, removed, 0)) if removed else state


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
    if not kinds or kinds == {"Stun"}:
        return state
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
        state = replace(state, draw=tuple(sorted((*state.draw, status, status, status))),
                        discard=tuple(sorted((*state.discard, status))))
        return _update(state, enemy.slot, powers=add_power(enemy.powers, "SANDPIT", 4))
    if enemy.name == PRISM and kinds == {"Defend"}:
        return _update(state, enemy.slot, block=13)
    if enemy.name == PRISM and kinds == {"Buff", "Defend"}:
        return _update(state, enemy.slot, block=22, powers=add_power(enemy.powers, "VITAL_SPARK", 3))
    return replace(state, boundary=Boundary(f"enemy intent/{enemy.name}/{'+'.join(sorted(kinds))}"))


def _update(state, slot, **changes):
    return replace(state, enemies=tuple(replace(e, **changes) if e.slot == slot else e for e in state.enemies))
