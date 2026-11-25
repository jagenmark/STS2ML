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

SCHEMA4_EXTRA_POWERS = (
    "ENVENOM", "ACCELERANT", "PHANTOM_BLADES", "INFINITE_BLADES", "SERPENT_FORM",
    "MASTER_PLANNER", "CORROSIVE_WAVE", "THORNS", "A_THOUSAND_CUTS",
    "DRAW_CARDS_NEXT_TURN", "ENERGY_NEXT_TURN", "BLOCK_NEXT_TURN", "RETAIN_HAND",
)
SCHEMA4_PILE_BINS = 24
SCHEMA4_NAMES = (
    *FEATURE_NAMES,
    *(f"player.power4.{name}" for name in SCHEMA4_EXTRA_POWERS),
    "draw_fraction",
    "draw_upgrades",
    "discard_upgrades",
    *(f"draw.{kind}" for kind in CARD_TYPES),
    *(f"discard.{kind}" for kind in CARD_TYPES),
    *(f"draw.card.{i}" for i in range(SCHEMA4_PILE_BINS)),
    *(f"discard.card.{i}" for i in range(SCHEMA4_PILE_BINS)),
    "draw_role_block",
    "draw_role_draw",
    "draw_role_poison",
    "draw_role_shiv",
    "round_mod_2",
    "round_mod_3",
    "round_mod_4",
    "enemy_total_vuln",
    "enemy_total_weak",
    "enemy_total_strangle",
    "enemy_next_poison_tick",
    "blur_carryover_block",
    "sandpit_timer",
)

_S4_BLOCK = frozenset(
    "DEFEND_SILENT DEFLECT BACKFLIP BLUR DASH DODGE_AND_ROLL HAND_TRICK CLOAK_AND_DAGGER SURVIVOR LEG_SWEEP PIERCING_WAIL ESCAPE_PLAN".split()
)
_S4_DRAW = frozenset(
    "ACROBATICS ADRENALINE BACKFLIP CALCULATED_GAMBLE DAGGER_THROW ESCAPE_PLAN PREPARED EXPERTISE".split()
)
_S4_POISON = frozenset(
    "DEADLY_POISON POISONED_STAB SNAKEBITE BOUNCING_FLASK NOXIOUS_FUMES ENVENOM BUBBLE_BUBBLE CORROSIVE_WAVE".split()
)
_S4_SHIV = frozenset(
    "BLADE_DANCE CLOAK_AND_DAGGER HIDDEN_DAGGERS LEADING_STRIKE INFINITE_BLADES BLADE_OF_INK UP_MY_SLEEVE SHIV".split()
)

SCHEMA5_EXTRA_POWERS = (
    "SHADOW_STEP", "DOUBLE_DAMAGE", "FREE_SKILL", "TRACKING", "VIGOR", "PLATING",
    "REGEN", "MIND_ROT", "SLOTH", "SURROUNDED", "CHAINS_OF_BINDING", "DISINTEGRATION",
)
SCHEMA5_RELICS = (
    "KUNAI", "SHURIKEN", "ORNAMENTAL_FAN", "PAPER_KRANE", "TOUGH_BANDAGES", "TINGSHA",
    "LETTER_OPENER", "TUNING_FORK", "KUSARIGAMA", "DAUGHTER_OF_THE_WIND",
    "SNECKO_SKULL", "PEN_NIB", "NUNCHAKU", "POCKETWATCH", "UNCEASING_TOP",
    "HAPPY_FLOWER", "ART_OF_WAR", "ICE_CREAM", "RUNIC_PYRAMID", "VELVET_CHOKER",
    "MUMMIFIED_HAND", "ORICHALCUM", "CLOAK_CLASP", "RIPPLE_BASIN", "PARRYING_SHIELD",
    "STURDY_CLAMP", "TUNGSTEN_ROD", "LIZARD_TAIL", "CENTENNIAL_PUZZLE", "BEATING_REMNANT",
    "HORN_CLEAT", "CAPTAINS_WHEEL", "STRIKE_DUMMY", "MERCURY_HOURGLASS", "MR_STRUGGLES",
    "TOASTY_MITTENS",
)
SCHEMA5_RELIC_BINS = 16
SCHEMA5_NAMES = (
    *SCHEMA4_NAMES,
    # 1. Next-turn exact public resources & survival context (8)
    "s5.next_energy",
    "s5.next_draw_count",
    "s5.will_shuffle",
    "s5.next_hand_size",
    "s5.missing_hp",
    "s5.below_half_hp",
    "s5.block_carry",
    "s5.total_deck_size",
    # 2. Additional player powers (12)
    *(f"s5.player.power.{name}" for name in SCHEMA5_EXTRA_POWERS),
    # 3. Combat relics, counters & hashed relic bins (36 + 10 + 16 = 62)
    *(f"s5.relic.{name}" for name in SCHEMA5_RELICS),
    "s5.relic_count",
    "s5.ctr_pen_nib",
    "s5.ctr_nunchaku",
    "s5.ctr_happy_flower",
    "s5.ctr_tuning_fork",
    "s5.ctr_stone_calendar",
    "s5.act_art_of_war",
    "s5.act_pocketwatch",
    "s5.act_lizard_tail",
    "s5.remnant_floor",
    *(f"s5.relic.bin.{i}" for i in range(SCHEMA5_RELIC_BINS)),
    # 4. Per-enemy rich tactical slots (4 * 9 = 36)
    *(
        f"s5.e{i}.{field}"
        for i in range(4)
        for field in (
            "poison", "strength", "weak", "vulnerable", "defense_power",
            "doomed_poison", "last_dmg", "last_hits", "last_non_atk",
        )
    ),
    # 5. Aggregate enemy threat, poison horizon & boss mechanics (12)
    "s5.living_non_doomed",
    "s5.min_enemy_log_hp",
    "s5.max_enemy_log_hp",
    "s5.poison_3t_ratio",
    "s5.last_total_dmg",
    "s5.last_total_hits",
    "s5.enemy_total_strength",
    "s5.kaiser_crusher_hp",
    "s5.kaiser_rocket_hp",
    "s5.kaiser_facing",
    "s5.frantic_escapes_live",
    "s5.status_curse_ratio",
    # 6. Analytical expected next-turn draw composition (8)
    "s5.exp_draw_block",
    "s5.exp_draw_attack",
    "s5.exp_draw_draw",
    "s5.exp_draw_poison",
    "s5.exp_draw_shiv",
    "s5.exp_draw_power",
    "s5.exp_draw_weak_wail",
    "s5.exp_draw_junk",
    # 7. Retained-hand functional composition (8)
    "s5.ret_block",
    "s5.ret_attack",
    "s5.ret_weak_wail",
    "s5.ret_power",
    "s5.ret_draw_energy",
    "s5.ret_zero_cost",
    "s5.ret_escape",
    "s5.ret_avg_cost",
)

_S5_WEAK_WAIL = frozenset(
    "NEUTRALIZE LEG_SWEEP SUCKER_PUNCH PIERCING_WAIL MALAISE HAZE".split()
)
_S5_DRAW_ENERGY = frozenset(
    (*_S4_DRAW, "TACTICIAN", "CONCENTRATE", "OUTMANEUVER", "DOPPELGANGER", "FLYING_KNEE", "REFLEX")
)


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
        if schema >= 3:
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
                effective_poison / max(1, ordinary_max), *fractions, *log_hp) if schema >= 3 else ()
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


def _schema4_tail(state):
    p_map = dict(state.powers)
    draw_c = Counter((v.name, v.kind, v.upgrade) for v in state.draw)
    disc_c = Counter((v.name, v.kind, v.upgrade) for v in state.discard)
    draw_bins, draw_kinds, draw_ups = _card_vector(draw_c, SCHEMA4_PILE_BINS)
    disc_bins, disc_kinds, disc_ups = _card_vector(disc_c, SCHEMA4_PILE_BINS)
    tot_pile = max(1, len(state.draw) + len(state.discard))
    draw_frac = len(state.draw) / tot_pile
    d_den = max(1, len(state.draw))
    d_blk = sum(v.name in _S4_BLOCK for v in state.draw) / d_den
    d_drw = sum(v.name in _S4_DRAW for v in state.draw) / d_den
    d_poi = sum(v.name in _S4_POISON for v in state.draw) / d_den
    d_shv = sum(v.name in _S4_SHIV for v in state.draw) / d_den

    accel = p_map.get("ACCELERANT", 0)
    vuln = weak = strangle = next_poison = sandpit = 0
    for e in state.enemies:
        if e.hp <= 0:
            continue
        ep = dict(e.powers)
        vuln += ep.get("VULNERABLE", 0)
        weak += ep.get("WEAK", 0)
        strangle += ep.get("STRANGLE", 0)
        if sp := ep.get("SANDPIT", 0):
            sandpit = sp
        if poi := ep.get("POISON", 0):
            ticks = min(poi, 1 + accel)
            next_poison += min(e.hp, ticks * poi - ticks * (ticks - 1) // 2)
    blur_blk = state.block if p_map.get("BLUR", 0) > 0 else 0
    return np.asarray(
        (
            *(p_map.get(name, 0) for name in SCHEMA4_EXTRA_POWERS),
            draw_frac,
            draw_ups,
            disc_ups,
            *(draw_kinds[k] for k in CARD_TYPES),
            *(disc_kinds[k] for k in CARD_TYPES),
            *draw_bins,
            *disc_bins,
            d_blk,
            d_drw,
            d_poi,
            d_shv,
            state.round % 2,
            state.round % 3,
            state.round % 4,
            vuln,
            weak,
            strangle,
            next_poison,
            blur_blk,
            sandpit,
        ),
        dtype=np.float32,
    )


def _schema5_tail(state):
    """Rich combat features missing from Schema 4: exact next-turn resources, relics & counters,
    per-enemy powers/intents, poison 3-turn horizon, boss state, expected next-K draw mix,
    and retained-hand functional composition. Strictly public, deterministic, no potion double-count.
    """
    p_map = dict(state.powers)
    next_draw = state.boundary.count if state.boundary is not None else 5
    will_shuffle = float(bool(state.boundary and state.boundary.shuffle))
    next_hand = len(state.hand) + next_draw
    missing_hp = max(0, state.max_hp - state.hp)
    below_half = float(state.hp * 2 <= state.max_hp)
    tot_deck = len(state.hand) + len(state.draw) + len(state.discard)

    # 3. Relics, counters & hashed relic bins
    active_relics = {}
    relic_bins = [0] * SCHEMA5_RELIC_BINS
    active_count = 0
    for r in state.relics:
        if r.used:
            continue
        active_count += 1
        active_relics[r.name] = r
        relic_bins[_bin(r.name, SCHEMA5_RELIC_BINS)] += 1

    def _ctr(name):
        r = active_relics.get(name)
        return float(r.counter) if (r is not None and r.counter is not None) else 0.0

    def _act(name):
        r = active_relics.get(name)
        return 1.0 if (r is not None and r.status == "Active") else 0.0

    # 4 & 5. Per-enemy rich slots + aggregate threat + boss mechanics
    accel = p_map.get("ACCELERANT", 0)
    e_slots = [0.0] * 36
    living_non_doomed = 0
    non_doomed_hps = []
    tot_living_hp = 0
    tot_poison_3t = 0
    last_tot_dmg = 0
    last_tot_hits = 0
    tot_enemy_str = 0
    crusher_hp = 0.0
    rocket_hp = 0.0
    slot_idx = 0

    for e in state.enemies:
        if e.hp <= 0:
            continue
        ep = dict(e.powers)
        hp_capped = min(e.hp, HP_CAP) if e.max_hp > HP_CAP else e.hp
        max_capped = HP_CAP if e.max_hp > HP_CAP else max(1, e.max_hp)
        if e.max_hp <= HP_CAP:
            tot_living_hp += hp_capped

        poi = ep.get("POISON", 0)
        e_str = ep.get("STRENGTH", 0)
        e_weak = ep.get("WEAK", 0)
        e_vuln = ep.get("VULNERABLE", 0)
        e_def = (
            ep.get("INTANGIBLE", 0)
            + ep.get("SLIPPERY", 0)
            + ep.get("BUFFER", 0)
            + ep.get("HARD_TO_KILL", 0)
            + ep.get("PLOW", 0)
        )
        ticks_1 = min(poi, 1 + accel)
        next_poi = ticks_1 * poi - ticks_1 * (ticks_1 - 1) // 2
        doomed = 1.0 if (poi > 0 and next_poi >= e.hp and e_def == 0) else 0.0
        ticks_3 = min(poi, 3 * (1 + accel))
        poi_3t = min(hp_capped, ticks_3 * poi - ticks_3 * (ticks_3 - 1) // 2)
        if e.max_hp <= HP_CAP:
            tot_poison_3t += poi_3t

        e_dmg = 0
        e_hits = 0
        e_non_atk = 0.0
        for it in e.intents:
            if it.damage is not None:
                e_dmg += it.damage * it.hits
                e_hits += it.hits
            else:
                e_non_atk = 1.0

        last_tot_dmg += e_dmg
        last_tot_hits += e_hits
        tot_enemy_str += e_str
        if doomed == 0.0:
            living_non_doomed += 1
            non_doomed_hps.append(hp_capped)

        if e.name == "CRUSHER":
            crusher_hp = hp_capped / max_capped
        elif e.name == "ROCKET":
            rocket_hp = hp_capped / max_capped

        if slot_idx < 4:
            base_i = slot_idx * 9
            e_slots[base_i : base_i + 9] = (
                float(poi),
                float(e_str),
                float(e_weak),
                float(e_vuln),
                float(e_def),
                doomed,
                float(e_dmg),
                float(e_hits),
                e_non_atk,
            )
            slot_idx += 1

    min_e_log = log1p(min(non_doomed_hps)) if non_doomed_hps else 0.0
    max_e_log = log1p(max(non_doomed_hps)) if non_doomed_hps else 0.0
    poison_3t_ratio = min(1.5, tot_poison_3t / max(1, tot_living_hp))

    all_live = (*(c.variant for c in state.hand), *state.draw, *state.discard)
    frantic_live = sum(v.name == "FRANTIC_ESCAPE" for v in all_live)
    junk_live = sum(v.kind in ("Status", "Curse") for v in all_live)
    junk_ratio = junk_live / max(1, len(all_live))

    # 6. Analytical expected next-K draw composition (handles draw + reshuffle of discard!)
    n_draw = len(state.draw)
    n_disc = len(state.discard)
    if next_draw <= 0:
        w_draw, w_disc = 0.0, 0.0
    elif next_draw <= n_draw:
        w_draw, w_disc = next_draw / max(1, n_draw), 0.0
    else:
        w_draw = 1.0
        rem = next_draw - n_draw
        w_disc = min(1.0, rem / max(1, n_disc)) if n_disc > 0 else 0.0

    def _exp_count(pred):
        val = 0.0
        if w_draw > 0.0 and n_draw:
            val += w_draw * sum(pred(v) for v in state.draw)
        if w_disc > 0.0 and n_disc:
            val += w_disc * sum(pred(v) for v in state.discard)
        return val

    exp_blk = _exp_count(lambda v: v.name in _S4_BLOCK)
    exp_atk = _exp_count(lambda v: v.kind == "Attack")
    exp_drw = _exp_count(lambda v: v.name in _S4_DRAW)
    exp_poi = _exp_count(lambda v: v.name in _S4_POISON)
    exp_shv = _exp_count(lambda v: v.name in _S4_SHIV)
    exp_pwr = _exp_count(lambda v: v.kind == "Power")
    exp_ww = _exp_count(lambda v: v.name in _S5_WEAK_WAIL)
    exp_jnk = _exp_count(lambda v: v.kind in ("Status", "Curse"))

    # 7. Retained-hand functional composition
    ret_vs = [c.variant for c in state.hand]
    ret_blk = sum(v.name in _S4_BLOCK for v in ret_vs)
    ret_atk = sum(v.kind == "Attack" for v in ret_vs)
    ret_ww = sum(v.name in _S5_WEAK_WAIL for v in ret_vs)
    ret_pwr = sum(v.kind == "Power" for v in ret_vs)
    ret_de = sum(v.name in _S5_DRAW_ENERGY for v in ret_vs)
    ret_zero = sum(v.cost == 0 and v.kind not in ("Status", "Curse") for v in ret_vs)
    ret_esc = sum(v.name == "FRANTIC_ESCAPE" for v in ret_vs)
    playable_costs = [v.cost for v in ret_vs if v.cost >= 0 and v.kind not in ("Status", "Curse")]
    ret_avg_cost = (sum(playable_costs) / len(playable_costs)) if playable_costs else 0.0

    return np.asarray(
        (
            float(state.energy),
            float(next_draw),
            will_shuffle,
            float(next_hand),
            float(missing_hp),
            below_half,
            float(state.block),
            float(tot_deck),
            *(float(p_map.get(name, 0)) for name in SCHEMA5_EXTRA_POWERS),
            *(1.0 if name in active_relics else 0.0 for name in SCHEMA5_RELICS),
            float(active_count),
            _ctr("PEN_NIB"),
            _ctr("NUNCHAKU"),
            _ctr("HAPPY_FLOWER"),
            _ctr("TUNING_FORK"),
            _ctr("STONE_CALENDAR"),
            _act("ART_OF_WAR"),
            _act("POCKETWATCH"),
            1.0 if "LIZARD_TAIL" in active_relics else 0.0,
            float(state.remnant_floor or 0),
            *relic_bins,
            *e_slots,
            float(living_non_doomed),
            min_e_log,
            max_e_log,
            poison_3t_ratio,
            float(last_tot_dmg),
            float(last_tot_hits),
            float(tot_enemy_str),
            crusher_hp,
            rocket_hp,
            float(state.facing),
            float(frantic_live),
            junk_ratio,
            exp_blk,
            exp_atk,
            exp_drw,
            exp_poi,
            exp_shv,
            exp_pwr,
            exp_ww,
            exp_jnk,
            float(ret_blk),
            float(ret_atk),
            float(ret_ww),
            float(ret_pwr),
            float(ret_de),
            float(ret_zero),
            float(ret_esc),
            ret_avg_cost,
        ),
        dtype=np.float32,
    )


def extract_leaf_features(state, *, schema=VERSION):
    """Encode the resolver's completed state, at its pre-reveal boundary."""
    if state.outcome != "completed":
        raise Unsupported("leaf is outside the next-turn boundary")
    board, live, retained, sizes = _state_inputs(state)
    # The frozen training schema encodes only the pre-turn sources in _energy_buff.
    buff = state.energy - state.max_energy - state.additional_public_energy
    base = _pack(board, state.act, state.floor, state.room, buff,
                 live, retained, sizes, schema)
    if schema == 4:
        return np.concatenate((base, _schema4_tail(state)))
    if schema == 5:
        return np.concatenate((base, _schema4_tail(state), _schema5_tail(state)))
    return base


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
