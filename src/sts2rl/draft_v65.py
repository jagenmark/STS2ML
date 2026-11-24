"""Silent solo acquisition rules and marginal role values for the opt-in v6.5 draft."""

from math import comb
import re

from .unified_draft import FORCE_SKIP, deck_context, effects, normalize

DEFENSIVE = {"AFTERIMAGE", "BLUR", "FOOTWORK", "MALAISE"}
SCALING = set(
    """
    ACCELERANT ACCURACY ENVENOM INFINITE_BLADES NOXIOUS_FUMES OUTBREAK
    PHANTOM_BLADES SERPENT_FORM SPEEDSTER STRANGLE KNIFE_TRAP
""".split()
)
# Orb-dependent offers, including a channel that requires an earlier channel.
ORB_PAYOFF = set(
    """
    BARRAGE BIASED_COGNITION CAPACITOR COMPILE_DRIVER COOLANT DEFRAGMENT DUALCAST
    FOCUSED_STRIKE HAILSTORM HOTFIX LOOP MULTI_CAST QUADCAST SHATTER SYNCHRONIZE
    TESLA_COIL THUNDER VOLTAIC
""".split()
)
OFFCLASS = re.compile(r"\b(?:osty|summon|doom|forge|sovereign blade)\b", re.I)
CHANNEL = re.compile(r"\bchannel\b", re.I)


def generator(c):
    return c["id"] != "VOLTAIC" and bool(CHANNEL.search(c["description"]))


def prohibited(c, max_energy, channels):
    return bool(
        c["id"] in FORCE_SKIP
        or c["id"] == "NEUROSURGE"
        or c["multiplayer_only"]
        or (c["star_cost"] or 0) > 0
        or c["stars_x"]
        or "ostydamage" in c["stats"]
        or OFFCLASS.search(c["description"])
        or (c["id"] == "BURY" and c["cost"] > max_energy)
        or (c["id"] in ORB_PAYOFF and not channels)
    )


def cleanup(card, score, ctx, info, scale=1):
    c = normalize(card)
    counts, copies = info
    if prohibited(c, ctx["max_energy"], counts["generators"]):
        return -1_000_000.0
    if c["id"] in {"AFTERIMAGE", "WELL_LAID_PLANS"}:
        return score + scale * 18 / (1 + 3 * copies[c["id"]])
    return score


def same_turn_draw(c, e):
    # Count a playable draw instruction on this card, excluding triggered powers,
    # future turns and draws conditional on an empty hand or a board prerequisite.
    if c["type"] == "Power" or c["id"] in {
        "PREDATOR",
        "GUIDING_STAR",
        "PALE_BLUE_DOT",
        "RELAX",
        "PLOT",
        "RESTLESSNESS",
        "IMPATIENCE",
        "COMPILE_DRIVER",
        "FETCH",
    }:
        return 0
    return 1 if c["id"] == "PILLAGE" else e.draw


def roles(c, e):
    s = c["stats"]
    name = c["id"]
    damage = max(s.get("damage", 0), s.get("calculateddamage", 0))
    attack = c["type"] == "Attack"
    solid = (
        attack and (damage >= 7 or e.poison or c["costs_x"] or name == "DAGGER_SPRAY")
    ) or e.shivs >= 2
    weak = s.get("weakpower", 0) > 0 or name in {"MALAISE", "SHOCKWAVE", "UPPERCUT"}
    vulnerable = s.get("vulnerablepower", 0) > 0 or name in {"EXPOSE", "SHOCKWAVE", "UPPERCUT"}
    scaling = name in SCALING or s.get("poisonperturn", 0) > 0
    return dict(
        front=int(bool(solid)),
        area=int(c["target_type"] == "AllEnemies" and bool(damage or e.shivs or e.poison)),
        scaling=int(scaling),
        guard=int(name in DEFENSIVE),
        weak=int(weak and name != "NEUTRALIZE"),
        vulnerable=int(vulnerable),
        attack_damage=damage * attack + 4 * e.shivs,
        generators=int(generator(c)),
    )


def role_context(deck, energy):
    n, copies = deck_context(deck)
    for raw in deck:
        c = normalize(raw)
        e = effects(c)
        n.update(roles(c, e))
        draw = same_turn_draw(c, e)
        n["filtering"] += draw
        # Acquisition bans do not disable an already-owned card's independent
        # draw instruction (e.g. Big Bang). Star costs still require Stars.
        if draw and not c["stars_x"] and (c["star_cost"] or 0) <= 0 and c["cost"] <= energy - 1:
            n["wave_sources"] += 1
            n["wave_draw"] += draw
    return n, copies


def wave_hand(n):
    """The candidate occupies one slot. Sample the other four without replacement."""
    population, sources = n["n"], n["wave_sources"]
    slots = min(population, 4)
    hit = 1 - comb(population - sources, slots) / comb(population, slots)
    return hit, 4 * n["wave_draw"] / max(4, population)


def wave_value(c, n, copies):
    hit, expected = wave_hand(n)
    dead = 1 - hit
    value = 3.4 * c["stats"]["corrosivewave"] * expected - 10 * dead - 4 - 5 * copies
    return min(value, -dead) if hit < 0.58 else value


def marginal_adjustment(c, ctx, info, e, damage, aoe):
    """Adjust the v6.4 numerator before energy normalization and the take threshold."""
    n, copies = info
    name, s = c["id"], c["stats"]
    act, floor = ctx["act"], ctx.get("floor", 1)
    early = act == 1 and floor <= 10
    opening = act == 1 and floor <= 6
    length = max(1, n["n"])
    energy = ctx.get("max_energy", 3)
    role = roles(c, e)
    # As the deck fills a role its next unit buys progressively less.
    need = 1 / (1 + (n["front"] / (3.2 if early else 2.3)) ** 2)
    delta = damage * ((0.08 if early else -0.40) + (1.05 if early else 0.70) * need)
    if role["area"]:
        delta += (7 if early else 9) / (1 + 2 * n["area"]) - 2
    synergy_ready = (
        (name not in {"ACCURACY", "PHANTOM_BLADES", "KNIFE_TRAP"} or n["shiv"] > 0)
        and (name not in {"OUTBREAK", "ACCELERANT"} or n["poison"] > 0)
        and (name != "SPEEDSTER" or n["filtering"] > 0)
    )
    if role["scaling"] and synergy_ready:
        delta += (4 if opening else 14 if act == 1 else 23) / (1 + 1.7 * n["scaling"]) - 5
    density = n["block"] / length
    delta += e.block * (0.44 - min(0.68, density * 1.3))
    if role["guard"]:
        delta += (4 if early else 12) / (1 + 2 * n["guard"]) - 2
    if role["weak"]:
        delta += (10 + 4 * ctx.get("paper_krane", False)) / (1 + (n["weak"] / 1.5) ** 2) - 3
    # Filtering replaces the legacy fixed 5.2 per card. Gamble exchanges the hand:
    # retain its actual draws/discards for payoffs but price only the refresh here.
    if e.draw:
        capacity = max(1, 0.40 * length * energy / 3)
        draw_need = 1 / (1 + (n["filtering"] / capacity) ** 2.2)
        weight = (2.8 if early else 3.7) + 2.1 * draw_need
        units = 1.8 if name == "CALCULATED_GAMBLE" else e.draw
        delta += weight * units * draw_need - 5.2 * e.draw
        if name == "CALCULATED_GAMBLE":
            delta += min(7, 2 * (copies["REFLEX"] + copies["TACTICIAN"])) - 4.5 * copies[name]
    if name == "PIERCING_WAIL":
        delta += s["strengthloss"] * ((1.75 if early else 2.2) - 2.9 * aoe)
        delta += 3 - 5 * density - 2 * n["guard"] - 5 * copies[name]
    if name == "EXPOSE":
        swing = min(22, 2.7 * n["attack_damage"] / length)
        delta += (4 + s["power"] * swing / 2) / (1 + n["vulnerable"]) - (8 + 3.5 * s["power"])
    if name == "SKEWER":
        delta += (10 if early else 4) + 2 * (energy - 3)
    if name == "ACCELERANT":
        if n["poison"]:
            delta += min(15, 2.6 * n["poison"]) / (1 + copies[name])
        else:
            delta -= 18
    if role["generators"]:
        delta += 9 if not n["generators"] else 5
    elif name in ORB_PAYOFF and n["generators"]:
        delta += 11 + min(6, 1.5 * n["generators"])
    if c["cost"] >= 2 and not c["costs_x"]:
        delta -= 12 * (c["cost"] - 1) * (n["cost_two_plus"] / length) * 3 / energy
    return delta
