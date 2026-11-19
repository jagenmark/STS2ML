"""Public Act 1 encounter history and card features for boss-aware drafting."""

from .card_effects import deck_engines, persistent_value
from .run_policy import _card_id, _hits, _shiv_count


# The pinned, fully unlocked solo lobby draws its first three normal fights
# without replacement from four equally weighted encounters in each biome.
_WEAK = {
    "Underdocks": {
        "SEAPUNK": False,
        "SLUDGE_SPINNER": False,
        "TOADPOLE": True,
        "CORPSE_SLUG": True,
    },
    "Overgrowth": {
        "FUZZY_WURM_CRAWLER": False,
        "NIBBIT": False,
        "SHRINKER_BEETLE": False,
        "SLIMES": True,
    },
}
_SLIMES = {"LEAF_SLIME_S", "TWIG_SLIME_S", "LEAF_SLIME_M", "TWIG_SLIME_M"}


class WeakEncounterPool:
    def __init__(self, initial_state):
        ctx = initial_state.get("context") or {}
        self.biome = ctx.get("act_name")
        self.from_opening = (
            ctx.get("act") == 1
            and ctx.get("floor") == 1
            and initial_state.get("decision") in ("event_choice", "map_select")
        )
        self.available = dict(_WEAK.get(self.biome, {})) if self.from_opening else {}
        self.visited = 0

    @property
    def normal_count(self):
        return min(3, self.visited) if self.from_opening else None

    @property
    def group_probability(self):
        if self.available and self.visited < 3:
            return sum(self.available.values()) / len(self.available)
        return None

    def observe(self, action_kind, state):
        ctx = state.get("context") or {}
        if ctx.get("act") != 1:
            self.available.clear()
            return
        if action_kind != "select_map_node" or ctx.get("room_type") != "Monster":
            return
        self.visited += 1
        if self.visited > 3 or not self.available:
            return
        enemies = state.get("enemies") or []
        ids = {e["id"].removeprefix("MONSTER.") for e in enemies}
        key = next(iter(ids)) if len(ids) == 1 else None
        if ids and ids <= _SLIMES:
            key = "SLIMES"
        # An unknown formation makes the remaining-bag inference unreliable.
        if key not in self.available or self.available[key] != (len(enemies) > 1):
            self.available.clear()
        else:
            del self.available[key]


def matchup_features(card, deck, context, group_probability):
    """Score candidate capabilities against public threats, independent of the seed."""
    act = context.get("act")
    if act not in (1, 2, 3):
        return {}
    boss = (context.get("boss") or {}).get("id")
    stats = card.get("stats") or {}
    hits = _hits(card)
    damage = stats.get("calculateddamage", stats.get("damage", 0))
    block = stats.get("calculatedblock", stats.get("block", 0))
    shivs = _shiv_count(card)
    poison = stats.get("poisonpower", 0)
    if _card_id(card) == "BOUNCING_FLASK":
        poison *= stats.get("repeat", 1)
    poison += 3 * stats.get("poisonperturn", 0)
    area = "all enemies" in (card.get("description") or "").lower()
    area_value = (
        float(area)
        * (
            damage * hits
            + 2 * poison
            + 2 * stats.get("strengthloss", 0)
            + 3 * stats.get("weakpower", 0)
        )
        / 8
    )
    stage = "opening" if act == 1 else "late"
    shared = f"matchup/{stage}/"
    features = {shared + "card/" + _card_id(card): 1.0}
    if act == 1 and area_value and group_probability is not None:
        existing = sum("all enemies" in (c.get("description") or "").lower() for c in deck)
        features["matchup/pool/area"] = group_probability * area_value / (1 + existing)
    if boss:
        prefix = f"matchup/{boss}/"
        capabilities = {
            "take": 1.0,
            "damage": (damage * hits + 4 * shivs) / 10,
            "block": (block + 4 * stats.get("weakpower", 0)) / 8,
            "poison": poison / 5,
            "persistent": (
                persistent_value(card, deck_engines(deck)) + 3 * stats.get("envenompower", 0)
            )
            / 6,
            "area": area_value,
        }
        if boss == "LAGAVULIN_MATRIARCH_BOSS":
            capabilities["after-siphon"] = (max(0, damage - 2) * hits + 2 * shivs) / 10
        features.update({prefix + key: value for key, value in capabilities.items() if value})
        features.update({shared + key: value for key, value in capabilities.items() if value})
    return features
