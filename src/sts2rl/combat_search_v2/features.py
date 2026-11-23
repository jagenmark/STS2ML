"""Public float32 features at the completed End Turn boundary.

Physical slots, mutable card previews, potion inventory and upcoming intents are
excluded. Card identities are counted across the live zones before encoding.
"""
from collections import Counter
from functools import lru_cache
from math import log1p
from zlib import crc32

import numpy as np

from .state import Unsupported, entry

VERSION = 3
HP_CAP = 2000
PLAYER_POWERS = (
    "STRENGTH", "DEXTERITY", "WEAK", "VULNERABLE", "FRAIL", "AFTERIMAGE", "BLUR",
    "BUFFER", "INTANGIBLE", "CONSTRICT", "SHRINK", "ARTIFACT", "POISON", "FOOTWORK",
    "WELL_LAID_PLANS", "TOOLS_OF_THE_TRADE", "NOXIOUS_FUMES", "ACCURACY", "ENERVENOM",
    "WRAITH_FORM", "TAINTED", "ENERGIZED", "NIGHTMARE", "SPEEDSTER",
)
ENEMY_POWERS = (
    "STRENGTH", "WEAK", "VULNERABLE", "POISON", "ARTIFACT", "BUFFER", "INTANGIBLE",
    "VITAL_SPARK", "SANDPIT", "SLIPPERY", "PLOW", "CURL_UP", "MINION", "RITUAL",
)
CARD_TYPES = ("Attack", "Skill", "Power", "Status", "Curse")
ROOM_TYPES = ("Monster", "Elite", "Boss")
FORMATION_BINS, CARD_BINS = 24, 48

SCHEMA2_NAMES = (
    "player.hp", "player.max_hp", "player.hp_fraction", "player.block", "player.max_energy",
    "player.energy_buff", "round", "floor", "act.1", "act.2", "act.3",
    *(f"room.{room}" for room in ROOM_TYPES),
    "living_count", "living_hp", "living_max_hp", "living_block",
    *(f"player.power.{name}" for name in PLAYER_POWERS), "player.power.other",
    *(f"enemy.power.{name}" for name in ENEMY_POWERS), "enemy.power.other",
    *(f"enemy.{i}.{key}" for i in range(4) for key in ("hp", "max_hp", "block")),
    *(f"formation.{i}" for i in range(FORMATION_BINS)),
    "live_count", "exhaust_count", "draw_count_before_draw", "discard_count_before_draw",
    "retained_count", "live_upgrades", "retained_upgrades",
    *(f"live.{kind}" for kind in CARD_TYPES), *(f"retained.{kind}" for kind in CARD_TYPES),
    *(f"live.card.{i}" for i in range(CARD_BINS)),
    *(f"retained.card.{i}" for i in range(16)),
)

FEATURE_NAMES = (*SCHEMA2_NAMES, "sentinel_enemy", "living_log_hp", "damage_dealt_fraction",
                 "effective_poison_progress", *(f"enemy.{i}.hp_fraction" for i in range(4)),
                 *(f"enemy.{i}.log_hp" for i in range(4)))


@lru_cache(maxsize=4096)
def _bin(name, width):
    return crc32(name.encode("utf-8")) % width


def _card_fields(cards):
    return Counter((entry(card["id"]), card["type"], card.get("upgrades", 0)) for card in cards)


def _snapshot_cards(cards):
    return Counter({(entry(card["id"]), card["type"], card["upgrades"]): card["count"] for card in cards})


def _power_fields(rows):
    return tuple(sorted((entry(p["id"]).removesuffix("_POWER"), p["amount"]) for p in rows or ()))


def _combat_board(view):
    player = view["player"]
    return (player["hp"], player["max_hp"], player.get("block", 0), view["max_energy"], view["round"],
            _power_fields(view.get("player_powers")),
            tuple((entry(e["id"]), e["hp"], e["max_hp"], e.get("block", 0), _power_fields(e.get("powers")))
                  for e in view["enemies"] if e["hp"] > 0))


def _witness_board(witness):
    player = witness["player"]
    return (player["hp"], player["max_hp"], player["block"], witness["max_energy"], witness["round"],
            _power_fields(player["powers"]),
            tuple((entry(e["id"]), e["board"]["hp"], e["board"]["max_hp"], e["board"]["block"],
                   _power_fields(e["board"]["powers"])) for e in witness["enemies"]))


def _powers_vector(powers, names):
    return [*(powers[name] for name in names), sum(abs(n) for k, n in powers.items() if k not in names)]


def _card_vector(cards, width):
    buckets = [0] * width
    kinds = Counter()
    upgrades = 0
    for (name, kind, upgrade), count in cards.items():
        buckets[_bin(name, width)] += count
        kinds[kind] += count
        upgrades += count * upgrade
    return buckets, kinds, upgrades


def _pack(board, act, floor, room, energy_buff, live, retained, sizes, schema=VERSION):
    hp, max_hp, block, energy, round_number, powers, enemies = board
    enemy_powers = Counter()
    formation = [0] * FORMATION_BINS
    slots = [0] * 12
    fractions = [0.] * 4
    log_hp = [0.] * 4
    sentinel = damage = effective_poison = 0
    ordinary_max = 0
    total_hp = total_max_hp = total_block = 0
    for i, (name, current, maximum, shield, active) in enumerate(enemies):
        if schema == 3:
            if maximum > HP_CAP:
                sentinel += 1
                current, maximum = min(current, HP_CAP), HP_CAP
            else:
                ordinary_max += maximum
                damage += maximum - current
                effective_poison += min(current, max(0, dict(active).get("POISON", 0)))
            if i < 4:
                fractions[i] = current / max(1, maximum)
                log_hp[i] = log1p(current)
        total_hp += current
        total_max_hp += maximum
        total_block += shield
        formation[_bin(name, FORMATION_BINS)] += 1
        enemy_powers.update(dict(active))
        if i < 4:
            slots[i * 3:i * 3 + 3] = current, maximum, shield
    card_bins, kinds, upgrades = _card_vector(live, CARD_BINS)
    retain_bins, retain_kinds, retain_upgrades = _card_vector(retained, 16)
    progress = (sentinel, log1p(total_hp), damage / max(1, ordinary_max),
                effective_poison / max(1, ordinary_max), *fractions, *log_hp) if schema == 3 else ()
    return np.asarray((
        hp, max_hp, hp / max_hp, block, energy, energy_buff, round_number, floor,
        act == 1, act == 2, act == 3, *(room == r for r in ROOM_TYPES),
        len(enemies), total_hp, total_max_hp, total_block,
        *_powers_vector(Counter(dict(powers)), PLAYER_POWERS),
        *_powers_vector(enemy_powers, ENEMY_POWERS),
        *slots, *formation, sum(live.values()), *sizes, sum(retained.values()), upgrades, retain_upgrades,
        *(kinds[k] for k in CARD_TYPES), *(retain_kinds[k] for k in CARD_TYPES),
        *card_bins, *retain_bins, *progress,
    ), dtype=np.float32)


def _energy_buff(pre):
    powers = dict(_power_fields(pre.get("player_powers")))
    energized = powers.get("ENERGIZED", 0) + powers.get("ENERGY_NEXT_TURN", 0)
    for relic in pre["player"].get("relics", ()):
        if relic.get("is_used_up"):
            continue
        name = entry(relic["id"])
        counter = relic.get("counter_rule") or {}
        if name == "HAPPY_FLOWER" and counter.get("remaining") == 1:
            energized += counter["effect_amount"]
        if ((name == "PAELS_TEARS" and pre["energy"] > 0)
                or (name == "CANDELABRA" and pre["round"] == 1)):
            energized += (relic.get("vars") or {}).get("Energy", 0)
    return energized


def _retained_before_eot(pre):
    powers = dict(_power_fields(pre.get("player_powers")))
    retain_all = powers.get("WELL_LAID_PLANS") or powers.get("RETAIN_HAND") or (
        pre["round"] == 1 and any(entry(relic["id"]) == "RINGING_TRIANGLE" and not relic.get("is_used_up")
                                 for relic in pre["player"].get("relics", ())))
    return _card_fields(card for card in pre["hand"]
                        if "Ethereal" not in (card.get("keywords") or ())
                        and (retain_all or card.get("retain_this_turn") or
                             "Retain" in (card.get("keywords") or ())))


def _state_inputs(state):
    board = (state.hp, state.max_hp, state.block, state.max_energy, state.round, state.powers,
             tuple((e.name, e.hp, e.max_hp, e.block, e.powers) for e in state.enemies if e.hp > 0))
    retained = Counter((v.name, v.kind, v.upgrade) for v in (c.variant for c in state.hand))
    live = retained.copy()
    live.update((v.name, v.kind, v.upgrade) for v in state.draw)
    live.update((v.name, v.kind, v.upgrade) for v in state.discard)
    return board, live, retained, (len(state.exhaust), len(state.draw), len(state.discard))


def extract_leaf_features(state, *, schema=VERSION):
    """Encode the resolver's completed state, at its pre-reveal boundary."""
    if state.outcome != "completed":
        raise Unsupported("leaf is outside the next-turn boundary")
    board, live, retained, sizes = _state_inputs(state)
    return _pack(board, state.act, state.floor, state.room, state.energy - state.max_energy,
                 live, retained, sizes, schema)


def extract_post_eot_features(s_pre_eot, s_next_turn, *, witness=None):
    """Encode a native completed turn. Missing or draw-sensitive rows raise Unsupported."""
    before = s_pre_eot.get("combat_state", s_pre_eot)
    after = s_next_turn.get("combat_state", s_next_turn)
    if after.get("decision") != "combat_play" or after["round"] != before["round"] + 1:
        raise Unsupported("next turn not observed")
    ctx = before["context"]
    if any(ctx[k] != after["context"][k] for k in ("act", "floor", "room_type")):
        raise Unsupported("room changed")
    board = _combat_board(after)
    if witness is None:
        from .end_turn import resolve
        from .state import project
        from .transitions import admission

        root = project(before)
        if admission(root):
            raise Unsupported("missing pre-draw witness")
        projected = resolve(root.state)
        if projected.outcome != "completed" or _state_inputs(projected)[0] != board:
            raise Unsupported("missing pre-draw witness")
        _, live, retained, sizes = _state_inputs(projected)
    else:
        if witness["early_draw"]:
            raise Unsupported("earlier draw before normal hand draw")
        if board != _witness_board(witness):
            raise Unsupported("board changed during reveal")
        live = _snapshot_cards(witness["live"])
        retained = _snapshot_cards(witness["retained"])
        sizes = witness["exhaust_count"], witness["draw_count"], witness["discard_count"]
    observed = _card_fields((*after["hand"], *after["draw_pile"], *after["discard_pile"]))
    if sum(live.values()) != sum(observed.values()):
        raise Unsupported("live deck size changed during reveal")
    if live != observed or sizes[0] != len(after["exhaust_pile"]):
        raise Unsupported("card multiset changed during reveal")
    expected_retained = _retained_before_eot(before)
    if retained != expected_retained:
        raise Unsupported("retained hand changed before draw")
    return _pack(board, ctx["act"], ctx["floor"], ctx["room_type"], _energy_buff(before),
                 live, expected_retained, sizes)
