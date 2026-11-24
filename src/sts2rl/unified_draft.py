"""Public draft inputs for Silent, normalized against the pinned v0.111.0 card models."""

from collections import Counter
from dataclasses import dataclass
from functools import cache
import gzip
import json
from pathlib import Path
import re


@cache
def catalog():
    return json.loads(
        gzip.decompress(Path(__file__).with_name("card_catalog_v01110.json.gz").read_bytes())
    )


@cache
def _names():
    names = {row["name"].casefold(): key for key, row in catalog().items()}
    return {**names, "strike": "STRIKE_SILENT", "defend": "DEFEND_SILENT"}


def identity(card):
    if card.get("id"):
        return card["id"].removeprefix("CARD.").upper()
    name = (card.get("name") or "").strip().rstrip("+")
    return _names().get(name.casefold(), name.upper().replace(" ", "_"))


def normalize(card):
    name = identity(card)
    row = catalog().get(name, {})
    variants = row.get("variants", [{}])
    level = card.get("upgrades", card.get("upgraded"))
    if level is None:
        # The legacy shop omits the level. An upgradable model with a null upgrade
        # preview is maxed out. Bundles supply an explicit level.
        level = (
            len(variants) > 1
            and ("after_upgrade" in card and card["after_upgrade"] is None)
            or (card.get("name") or "").endswith("+")
        )
    index = min(int(level), len(variants) - 1)
    model = variants[index]
    keywords = frozenset(
        card.get("keywords") if card.get("keywords") is not None else model.get("keywords", ())
    )
    next_model = variants[index + 1] if index + 1 < len(variants) else {}
    preview = card.get("after_upgrade") or {}
    next_keywords = set(next_model.get("keywords", keywords))
    next_keywords.update(preview.get("added_keywords") or ())
    next_keywords.difference_update(preview.get("removed_keywords") or ())
    has_price = "is_stocked" in card or "gold_cost" in card and "cost" not in card
    cost = card.get(
        "card_cost", model.get("cost", 1) if has_price else card.get("cost", model.get("cost", 1))
    )
    return dict(
        id=name,
        upgraded=bool(level),
        type=card.get("type", model.get("card_type")),
        cost=cost,
        gold_cost=card.get("gold_cost", card.get("cost") if "is_stocked" in card else None),
        stats={**model.get("stats", {}), **(card.get("stats") or {})},
        keywords=keywords,
        after_upgrade=(
            {
                **next_model,
                **preview,
                "keywords": frozenset(next_keywords),
                "added_keywords": frozenset(next_keywords - keywords),
                "removed_keywords": frozenset(keywords - next_keywords),
            }
            if next_model or preview
            else None
        ),
        description=row.get("description", card.get("description") or ""),
        **{
            k: card.get(k, model.get(k))
            for k in ("target_type", "costs_x", "star_cost", "stars_x", "multiplayer_only")
        },
    )


_DRAW = re.compile(r"\bdraw\s+(?:\{cards\b|([0-9]+)\s+(?:additional\s+)?cards?\b)", re.I)
_DISCARD = re.compile(r"\bdiscard\s+(?:(\d+)\s+cards?\b|\{cards\b|(?:your|any number of)\s+)", re.I)


@dataclass(frozen=True)
class Effects:
    draw: float
    discard: float
    shivs: float
    poison: float
    block: float
    energy: float


def effects(c):
    name, s = c["id"], c["stats"]
    desc = re.sub(r"\[/?\w+\]", "", c["description"])
    draw_match = _DRAW.search(desc)
    draw = (int(draw_match[1]) if draw_match[1] else s.get("cards", 0)) if draw_match else 0
    discard_match = _DISCARD.search(desc)
    discard = (
        (int(discard_match[1]) if discard_match[1] else s.get("cards", 1)) if discard_match else 0
    )
    if name == "CALCULATED_GAMBLE":
        draw = discard = 4
    elif name == "SCRAWL":
        draw = 5
    shivs = s.get("shivs", 0)
    if name in {"BLADE_DANCE", "CLOAK_AND_DAGGER", "UP_MY_SLEEVE", "BLADE_OF_INK"}:
        shivs = s.get("cards", 0)
    poison = s.get("poisonpower", 0) * max(1, s.get("repeat", 1))
    block = s.get("calculatedblock", s.get("block", 0))
    if name == "MAD_SCIENCE":
        block = block if c["type"] == "Skill" else 0
    energy = s.get("energy", 0) if re.search(r"\bgain\s+\{Energy\b", desc, re.I) else 0
    return Effects(draw, discard, shivs, poison, block, energy)


def deck_context(deck):
    counts, copies = Counter(n=len(deck)), Counter()
    for raw in deck:
        c = normalize(raw)
        name, s, keywords = c["id"], c["stats"], c["keywords"]
        e = effects(c)
        copies[name] += 1
        counts[c["type"]] += 1
        counts["summoners"] += s.get("summon", 0) > 0
        counts["channel_sources"] += "[gold]Channel[/gold]" in c["description"]
        counts["cost_two_plus"] += c["cost"] >= 2 and not c["costs_x"]
        counts["block"] += e.block > 0
        counts["draw"] += e.draw if name != "REFLEX" else 0
        counts["discard"] += e.discard
        counts["sly"] += "Sly" in keywords
        counts["shiv"] += e.shivs
        counts["poison"] += (e.poison if name != "BUBBLE_BUBBLE" else 0) + 3 * s.get(
            "poisonperturn", 0
        )
        counts["exhaust"] += ("Exhaust" in keywords or "Ethereal" in keywords) + e.shivs
        counts["ethereal"] += "Ethereal" in keywords
        counts["dexterity"] += (
            s.get("dexteritypower", 0) * (0.25 if name == "ANTICIPATE" else 1)
            if not c["multiplayer_only"]
            else 0
        )
        counts["accuracy"] += s.get("accuracypower", 0)
        counts["unupgraded"] += not c["upgraded"] and c["after_upgrade"] is not None
    return counts, copies


ENERGY_RELICS = frozenset(
    """BLESSED_ANTLER BLOOD_SOAKED_ROSE ECTOPLASM PHILOSOPHERS_STONE PRISMATIC_GEM
    PUMPKIN_CANDLE SOZU SPIKED_GAUNTLETS VELVET_CHOKER WHISPERING_EARRING""".split()
)


def public_context(state, *, v65=False):
    p = state["player"]
    relics = {
        r.get("id", "").removeprefix("RELIC."): r
        for r in p.get("relics", ())
        if not r.get("is_used_up")
    }
    energy = 3 + sum(
        (relics[k].get("vars") or {}).get("Energy", 1) for k in ENERGY_RELICS & relics.keys()
    )
    ctx = state["context"]
    return {
        **ctx,
        **({"paper_krane": "PAPER_KRANE" in relics} if v65 else {}),
        "max_energy": state.get("max_energy", p.get("max_energy", ctx.get("max_energy", energy))),
        "stone_dex": int("ODDLY_SMOOTH_STONE" in relics),
    }


FORCE_SKIP = {"GRAND_FINALE", "THE_GAMBIT", "PANIC_BUTTON", "CLASH"}


def raw_grade(card, ctx, info, *, size_penalty, threshold, duplicate, v65=False):
    c = normalize(card)
    name, s, keys = c["id"], c["stats"], c["keywords"]
    if v65:
        from .draft_v65 import marginal_adjustment, prohibited, wave_value

        counts, copies = info
        if prohibited(c, ctx.get("max_energy", 3), counts["generators"]):
            return -1_000_000.0
        if name == "CORROSIVE_WAVE":
            return wave_value(c, counts, copies[name])
    if name in FORCE_SKIP or c["multiplayer_only"] or (c["star_cost"] or 0) > 0 or c["stars_x"]:
        return -100.0
    if c["type"] in ("Curse", "Status", "Quest"):
        return -35.0
    n, copies = info
    length = max(1, n["n"])
    e = effects(c)
    dex = n["dexterity"] + ctx.get("stone_dex", 0)
    block_density = min(1, n["block"] / length)
    skills = n["Skill"] / length
    attacks = n["Attack"] / length
    cost = max(0, c["cost"])
    max_energy = ctx.get("max_energy", 3)
    # Meteor Strike channels Plasma after it is paid for. Midnight is solo-ineligible.
    if name == "KINGLY_KICK":
        cost = max(1, cost - 1)
    elif name == "BANSHEES_CRY":
        cost = max(1, cost - s.get("energy", 0) * n["ethereal"])
    elif name == "PINPOINT":
        cost = max(1, cost - 3 * skills)
    if cost > max_energy and not c["costs_x"] and name not in ("TACTICIAN", "REFLEX"):
        return -25.0 - (cost - max_energy)

    repeated_damage = re.search(r"damage[^.\n]*\{Repeat|hits \{Repeat", c["description"], re.I)
    hits = max(1, s.get("repeat", 1)) if repeated_damage else 1
    if name in ("TWIN_STRIKE", "UPROAR", "DAGGER_SPRAY", "FIGHT_ME", "REFRACT"):
        hits = 2
    if name == "FINISHER":
        hits = min(5, 2.6 * attacks + 0.5 * n["shiv"])
    if name == "FLECHETTES":
        hits = min(5, 4.5 * skills)
    if c["costs_x"]:
        # Typical remaining energy when drawn. Investing the full turn also has a cost.
        hits = cost = min(2, max_energy)
    damage = s.get("calculateddamage", s.get("damage", 0)) * hits
    if name == "RIGHT_HAND_HAND" and n["summoners"]:
        # A summon source makes Osty available. Expensive plays recur the card.
        recurrence = min(2, 4 * n["cost_two_plus"] / length)
        damage = s.get("ostydamage", 0) * (1 + recurrence)
    if name == "HEAVENLY_DRILL" and max_energy >= s.get("energy", 4):
        # Sometimes reserve the whole turn to reach the doubling breakpoint.
        damage += 0.25 * (2 * max_energy - hits) * s.get("damage", 0)
    if name == "MAD_SCIENCE" and c["type"] != "Attack":
        damage = 0
    damage += e.shivs * (4 + 0.7 * n["accuracy"])
    aoe = 1.35 if c["target_type"] == "AllEnemies" else 1
    early = ctx["act"] == 1 and ctx.get("floor", 1) < 10
    offense = damage * aoe * (1.12 if early and attacks < 0.55 else 1)
    poison = e.poison if name != "BUBBLE_BUBBLE" or n["poison"] else 0
    offense += poison * (2.0 if early else 2.5) * aoe + 8 * s.get("poisonperturn", 0)
    block = e.block + (dex if e.block else 0)
    if name == "DODGE_AND_ROLL":
        block *= 2
    elif name == "BLUR":
        block += 1 + 9 * block_density + 0.55 * dex
    elif name == "TORIC_TOUGHNESS":
        block *= 1 + 0.8 * s.get("turns", 0)
    elif name == "FISTICUFFS":
        block += damage
    block += 0.85 * s.get("blocknextturn", 0)
    if name == "MIRAGE":
        block += min(28, n["poison"] * 1.6)
    value = offense + block + 5.2 * e.draw + 4.5 * e.energy
    value += min(5, e.draw * (copies["SPEEDSTER"] + copies["CORROSIVE_WAVE"]))
    value += 0.9 * min(4, e.discard) + min(6, e.discard * n["sly"])
    value += 3.6 * s.get("weakpower", 0) + 3 * s.get("vulnerablepower", 0)
    value += 2.9 * s.get("strengthloss", 0) * aoe + 15 * s.get("intangiblepower", 0)
    dex_weight = 1.3 if name == "ANTICIPATE" else 4.5 + 7 * block_density
    value += s.get("dexteritypower", 0) * dex_weight
    strength = s.get("strengthpower", 0)
    value += strength * (
        -5 if name == "FRIENDSHIP" else 1.25 if name in ("FEEDING_FRENZY", "SETUP_STRIKE") else 5
    )
    value += 18 * s.get("afterimagepower", 0) + 12 * s.get("envenompower", 0)
    value += s.get("accuracypower", 0) * min(5, 0.6 + 0.6 * n["shiv"])
    value += 7 * s.get("serpentformpower", 0) + 3.2 * s.get("thornspower", 0)
    value -= 2.6 * s.get("hploss", 0) + 5 * s.get("enemystrength", 0)
    # These variables describe conditional or delayed effects, not immediate resources.
    if name == "CORROSIVE_WAVE":
        if not n["draw"]:
            return -30.0
        value += s["corrosivewave"] * min(14, 3.4 * n["draw"])
    if name == "PACTS_END":
        if n["exhaust"] < s["cards"]:
            return -30.0
        value *= min(1.2, 0.7 + 0.08 * n["exhaust"])
    if name == "ACCELERANT":
        value += min(22, 2.0 * n["poison"]) * (1 + 0.4 * (s["accelerant"] - 1)) / (1 + copies[name])
    if name in ("TACTICIAN", "REFLEX"):
        # Sly is free on discard. Manual play still costs three energy.
        free_fraction = min(0.92, n["discard"] * 0.19)
        payoff = 16 * e.energy if name == "TACTICIAN" else 8 * e.draw
        value = payoff * free_fraction + (1 - free_fraction) * value / max(1, cost)
        cost = 1
    elif "Sly" in keys:
        cost *= 1 - min(0.8, 0.13 * n["discard"])

    bonuses = {
        "FRIENDSHIP": 7,
        "NEUROSURGE": -9 * s.get("neurosurgepower", 0),
        "BRIGHTEST_FLAME": -8 * s.get("maxhp", 0),
        "CRASH_LANDING": -26,
        "DODGE_AND_ROLL": 2.5,
        "GUNK_UP": -5,
        "COLLISION_COURSE": -4,
        "BORROWED_TIME": -12 * s.get("extracost", 0),
        "WRAITH_FORM": -3 * s.get("wraithformpower", 0),
        "HYPERBEAM": -1.5 * s.get("focuspower", 0),
        "WELL_LAID_PLANS": 28,
        "TOOLS_OF_THE_TRADE": 11 + min(5, n["sly"]),
        "PREPARED": 3.5,
        "EXPOSE": 8 + 3.5 * s.get("power", 0),
        "SHOCKWAVE": 9 * s.get("power", 0),
        "UPPERCUT": 8 * s.get("power", 0),
        "MASTER_PLANNER": 18 + 8 * skills + min(6, n["discard"]),
        "SPEEDSTER": s.get("speedsterpower", 0) * (6 + min(10, n["draw"])),
        "KNIFE_TRAP": min(38, (6 if c["upgraded"] else 4.5) * n["shiv"]),
        "MURDER": 16 + min(16, n["draw"]),
        "STRANGLE": s.get("stranglepower", 0) * (3 + min(3, n["shiv"])),
        "SHADOWMELD": 9 + 15 * block_density,
        "SHADOW_STEP": 9 + 12 * attacks,
        "BLADE_OF_INK": 4,
        "FAN_OF_KNIVES": 5 + min(7, n["shiv"]),
        "POUNCE": 7 * min(1, skills * 3),
        "NIGHTMARE": 25,
        "BULLET_TIME": 28,
        "BURST": 14 * s.get("skills", 0),
        "APOTHEOSIS": 19 + min(18, n["unupgraded"]),
        "ALCHEMIZE": 18,
        "SECRET_TECHNIQUE": 12,
        "SECRET_WEAPON": 12,
        "WISH": 16,
        "DISCOVERY": 16,
        "PURITY": 7 + 2 * s.get("cards", 0),
        "PANACHE": s.get("panachedamage", 0) * (1 + min(1, n["shiv"] * 0.12)),
        "THE_BOMB": s.get("bombdamage", 0) * 0.73,
        "ETERNAL_ARMOR": 3.5 * s.get("platingpower", 0),
        "INFINITE_BLADES": 13 + n["accuracy"],
        "PHANTOM_BLADES": 11 + min(10, n["shiv"]),
        "OUTBREAK": min(22, 1.4 * n["poison"]),
        "MALAISE": 19 + 6 * c["upgraded"],
        "TEMPEST": 6 * (hits + c["upgraded"]),
        "CASCADE": 8 * (hits + c["upgraded"]),
        "DIRGE": 4 * hits,
        "MULTI_CAST": min(1, n["channel_sources"] / 2) * 8 * (hits + c["upgraded"]),
        "METEOR_STRIKE": 14,
    }
    value += bonuses.get(name, 0)
    if v65:
        value += marginal_adjustment(c, ctx, info, e, damage, aoe)
    value += 2 if "Retain" in keys else 0
    value += 1.5 if "Innate" in keys and value > 0 else 0
    value /= max(1, cost) ** 0.78
    if name in ("SKEWER", "VOLLEY", "ERADICATE", "HEAVENLY_DRILL"):
        value *= 0.78
    return (
        value
        + 2.2 * (cost == 0 and value > 0)
        - threshold
        - duplicate * copies[name]
        + size_penalty * max(0, n["n"] - 14) / 6
    )
