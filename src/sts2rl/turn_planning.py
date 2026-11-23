"""Bounded search over cards and targets visible in the current hand.

Future draws are never expanded. The game executes just the first legal action
before the resulting public hand, costs and intents are scored again.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from .combat_effects import block_preview, debuff_order
from .enemy_forecast import WATERFALL_GIANT, attack_hits, solo_waterfall_forecast, waterfall_forecast
from .native import legal_actions
from .run_policy import _cost, _damage, _draw_count, _hits, _power, _shiv_count
from .teacher import incoming


@dataclass(frozen=True, slots=True)
class Move:
    action_index: int
    source: int
    cost: int
    x_cost: bool
    target: int | None
    damage: tuple
    block: float
    weak: int
    weak_order: tuple
    debuffs: tuple
    extra: float
    tender_hits: int = 0
    tender_block: bool = False


@dataclass(frozen=True, slots=True)
class Hand:
    damage: tuple
    block: float
    weak: int
    artifact: tuple
    used: int
    energy: int
    extra: float
    first: int | None


def choose_turn(state, policy, *, width=6, depth=5, survival_priority=False, facing=None, score_adjust=None):
    if survival_priority:
        actions = legal_actions(state)
        if state["decision"] != "combat_play" or len(actions) <= 1:
            return policy(state)
        best, _ = _search_survival_lines(
            state,
            policy,
            actions,
            width=max(width, 8),
            depth=depth,
            facing=facing,
            score_adjust=score_adjust,
        )
        return actions[best[-1]]
    actions = legal_actions(state)
    if state["decision"] != "combat_play" or len(actions) <= 2:
        return policy(state)
    scores = policy.combat_scores(state, actions)
    enemies = [e for e in state["enemies"] if e["hp"] > 0]
    size = len(enemies)
    if size == 0:
        return actions[max(range(len(actions)), key=scores.__getitem__)]
    hp = tuple(e["hp"] + e.get("block", 0) for e in enemies)
    legacy = getattr(policy, "legacy_features", False)
    giant = None if legacy else solo_waterfall_forecast(state, enemies)
    intents = (0,) if giant and giant.eruption_forced else tuple(incoming(e) for e in enemies)
    w = policy.weights
    focus = tuple(1 + w.focus * (1 - e["hp"] / max(1, e["max_hp"])) if size > 1 else 1 for e in enemies)
    player = state["player"]
    starting_block = player["block"] + max(0, _power(state.get("player_powers"), "PLATING"))
    need = max(0, sum(intents) - starting_block)
    block_weight = w.block * (1 + min(2., need / max(1, player["hp"])))
    revive = any(_power(e.get("powers"), "ILLUSION") or _power(e.get("powers"), "INFESTED") for e in enemies)
    cards = {c["index"]: c for c in state["hand"]}
    potions = {p["index"]: p for p in player["potions"]}
    tender = getattr(policy, "tender", False) and any(
        p["id"] == "POWER.TENDER_POWER" for p in state.get("player_powers") or []
    )
    card_mask = sum(1 << index for index in cards) if tender else 0
    legacy_dex = _power(state.get("player_powers"), "DEXTERITY") if legacy else 0
    shields = tuple(max(0, _power(e.get("powers"), "ARTIFACT")) for e in enemies)
    if legacy or not any(shields):
        shields = ()
    energy = state["energy"]

    def board(damage, block, weak, *, terminal):
        offense, threat, alive = 0., 0., 0
        for i, hits in enumerate(damage):
            offense += min(hp[i], hits) * focus[i]
            if hits >= hp[i]:
                if not (giant and giant.eruption_damage is not None):
                    offense += 14
            else:
                alive += 1
                threat += intents[i] * (.75 if weak & (1 << i) else 1.)
        loss = max(0., threat - starting_block - block)
        value = offense + block_weight * (need - loss)
        if terminal:
            if not alive and not revive and not (giant and giant.eruption_damage is not None):
                value += 35
            if loss >= player["hp"]:
                value -= 30
        return value

    moves = []
    end = next(i for i, a in enumerate(actions) if a.kind == "end_turn")
    for j, a in enumerate(actions):
        if j == end:
            continue
        potion = a.kind == "use_potion"
        if potion:
            item = potions[a.args["potion_index"]]
            stats = {k.lower(): v for k, v in (item.get("vars") or {}).items()}
            source = max(cards, default=-1) + 1 + item["index"]
            cost = 0
        else:
            item = cards[a.args["card_index"]]
            stats = item.get("stats") or {}
            source = item["index"]
            cost = _cost(item)
        indices = [i for i, e in enumerate(enemies) if e["index"] == a.args.get("target_index")]
        target = indices[0] if indices else None
        targets = [target] if target is not None else range(size)
        d = [0.] * size
        weak = 0
        weak_order = [0] * size
        debuffs = [0] * size
        for i in targets:
            if potion:
                d[i] = stats.get("damage", 0)
            elif item.get("type") == "Attack":
                d[i] = _damage(item, enemies[i])
            if item.get("target_type") == "RandomEnemy" and size > 1:
                d[i] /= size
            if giant and (giant.final_phase or giant.eruption_forced):
                d[i] = 0
            if shields:
                effects = debuff_order(item, stats, enemies[i], energy=energy)
                if item.get("target_type") == "RandomEnemy" and size > 1:
                    # No particular enemy is guaranteed to lose a stack.
                    continue
                debuffs[i] = len(effects)
                if item.get("id") == "CARD.EXPOSE":
                    debuffs[i] += shields[i]
                if not _power(enemies[i].get("powers"), "WEAK"):
                    weak_order[i] = next((n for n, (kind, _) in enumerate(effects, 1) if kind == "weak"), 0)
                if weak_order[i] > shields[i]:
                    weak |= 1 << i
            elif stats.get("weakpower", 0) and not _power(enemies[i].get("powers"), "WEAK"):
                weak |= 1 << i
        block = block_preview(stats, legacy_dex=0 if potion else legacy_dex)
        intrinsic = scores[j] * max(1, cost) ** w.cost_exponent
        # Replace the one-card damage and block estimates with their joint
        # effect. Keep the scorer's utility for draw, poison, powers and items.
        residual = intrinsic - board(d, block, weak, terminal=False)
        moves.append(Move(j, 1 << source, cost, bool(item.get("costs_x")), target,
                          tuple(d), block, weak, tuple(weak_order), tuple(debuffs), residual,
                          _hits(item) if tender and not potion and item.get("type") == "Attack" else 0,
                          bool(tender and not potion and ("block" in stats or "calculatedblock" in stats))))

    start = Hand((0.,) * size, 0., 0, shields, 0, energy, 0., None)
    beam = [start]
    best = (board(start.damage, 0., 0, terminal=True), scores[end], -end)
    choice = end
    for _ in range(depth):
        next_hands = {}
        for hand in beam:
            for m in moves:
                if hand.used & m.source or hand.energy < m.cost or (m.x_cost and hand.energy != energy):
                    continue
                if m.target is not None and hand.damage[m.target] >= hp[m.target]:
                    continue
                damage = tuple(min(h, prev + delta) for h, prev, delta in zip(hp, hand.damage, m.damage, strict=True))
                block, weak = hand.block + m.block, hand.weak | m.weak
                if tender:
                    # Current native previews already include cards actually played. Only
                    # projected cards reduce subsequent values. Drinking a potion plays no card.
                    prior_cards = (card_mask & hand.used).bit_count()
                    if prior_cards and m.tender_hits:
                        damage = tuple(min(h, prev + max(0.0, delta - prior_cards * m.tender_hits))
                                       for h, prev, delta in zip(hp, hand.damage, m.damage, strict=True))
                    if prior_cards and m.tender_block:
                        block = hand.block + max(0.0, m.block - prior_cards)
                artifact = hand.artifact
                if artifact:
                    for i, remaining in enumerate(artifact):
                        if m.weak_order[i] > remaining:
                            weak |= 1 << i
                    artifact = tuple(max(0, n - k) for n, k in zip(artifact, m.debuffs, strict=True))
                extra = hand.extra + m.extra
                first = m.action_index if hand.first is None else hand.first
                projection = Hand(damage, block, weak, artifact, hand.used | m.source, hand.energy - m.cost, extra, first)
                quality = (board(damage, block, weak, terminal=True) + extra, scores[first], -first)
                if quality > best:
                    best, choice = quality, first
                if all(hits >= health for hits, health in zip(damage, hp, strict=True)):
                    continue
                key = (projection.used, projection.damage, projection.weak, artifact)
                previous = next_hands.get(key)
                if previous is None or quality > previous[0]:
                    next_hands[key] = (quality, projection)
        if not next_hands:
            break
        beam = [h for _, h in sorted(next_hands.values(), key=lambda pair: pair[0], reverse=True)[:width]]
    return actions[choice]


_REDRAW_ITEMS = frozenset({
    "CALCULATED_GAMBLE",
    "STORM_OF_STEEL",
    "GAMBLERS_BREW",
    "GLOWWATER_POTION",
    "BOTTLED_POTENTIAL",
    "SNECKO_OIL",
})
_MANDATORY_DISCARD_CARDS = frozenset({
    "SURVIVOR",
    "PREPARED",
    "DAGGER_THROW",
    "ACROBATICS",
    "HIDDEN_DAGGERS",
})
_ESCAPE_DRAW_ITEMS = frozenset({
    "ACROBATICS",
    "ADRENALINE",
    "BACKFLIP",
    "ESCAPE_PLAN",
    "EXPERTISE",
    "FINESSE",
    "FLASH_OF_STEEL",
    "MASTER_OF_STRATEGY",
    "PREPARED",
    "DAGGER_THROW",
    "SWIFT_POTION",
    "CLARITY",
    "CURE_ALL",
    "SMOKE_BOMB",
})


@dataclass(frozen=True, slots=True)
class _SurvivalMove:
    action_index: int
    source: int
    name: str
    cost: int
    x_cost: bool
    energy_gain: int
    target: int | None
    is_attack: bool
    hits: int
    damage: tuple
    guaranteed_damage: tuple
    card_block: float
    is_fortifier: bool
    afterimage_gain: int
    weak_order: tuple
    poison_apps: tuple
    str_drop: tuple
    debuffs: tuple
    clears_block: bool
    requires_existing_poison: bool
    intangible: int
    buffer: int
    self_hp_loss: float
    foul_damage: float
    potion: bool
    stops_expansion: bool
    has_escape: bool
    extra: float
    tender_hits: int = 0
    tender_block: bool = False
    is_skill: bool = False
    is_knife_trap: bool = False
    knife_trap_shivs: int = 0
    shadowmeld_gain: int = 0
    strength_gain: int = 0
    burst_gain: int = 0
    debilitate_order: tuple = ()
    delayed_only: bool = False
    precise_extra: int = 0
    hand_delta: int = 0
    escapes_sandpit: bool = False
    applies_no_block: bool = False
    per_hit_x_damage: tuple = ()
    x_malaise_amt: int = 0
    shivs_added: int = 0
    draws_added: int = 0
    precise_raw_base: tuple = ()
    is_random_multi: bool = False


@dataclass(frozen=True, slots=True)
class _SurvivalHand:
    damage: tuple
    guaranteed_damage: tuple
    enemy_block: tuple
    enemy_buffer: tuple
    enemy_slippery: tuple
    poison: tuple
    block: float
    weak: int
    str_drop: tuple
    artifact: tuple
    intangible: int
    buffer: int
    afterimage: int
    self_hp_loss: float
    potions_used: int
    has_escape: bool
    used: int
    energy: int
    extra: float
    first: int | None
    stopped: bool = False
    enemy_curl_up: tuple = ()
    facing: int | None = None
    skills_played: int = 0
    shadowmeld: int = 0
    strength_gain: int = 0
    giga_rem: int = 0
    burst_rem: int = 0
    dup_rem: int = 0
    debilitate: int = 0
    hand_delta: int = 0
    escaped_sandpit: bool = False
    no_block: bool = False
    hand_size: int = 0
    rem_draws: int | None = None


def _poison_tick_loss(stacks, accelerant, intangible, slippery=0, buffer=0, hard_cap=0):
    if stacks <= 0:
        return 0
    n_stacks = int(stacks)
    if n_stacks <= 0:
        return 0
    ticks = min(n_stacks, 1 + max(0, int(accelerant)))
    if buffer <= 0 and slippery <= 0 and hard_cap <= 0:
        if intangible:
            return ticks
        return ticks * n_stacks - ticks * (ticks - 1) // 2
    total = 0
    rem_buf = max(0, int(buffer))
    rem_sl = max(0, int(slippery))
    for t in range(ticks):
        if rem_buf > 0:
            rem_buf -= 1
            continue
        if intangible:
            dmg = 1
        elif rem_sl > 0:
            dmg = 1
            rem_sl -= 1
        else:
            dmg = n_stacks - t
        if hard_cap > 0:
            dmg = min(dmg, int(hard_cap))
        total += dmg
    return total


def _hand_burn_hits(hand, intangible, *, include_wither=False, used_mask=0):
    hits = []
    for c in hand:
        idx = c.get("index")
        if used_mask and idx is not None and idx >= 0 and (used_mask & (1 << idx)):
            continue
        cid = c.get("id")
        if cid == "CARD.BURN":
            dmg = max(0, (c.get("stats") or {}).get("damage", 2))
            if dmg > 0:
                hits.append(1.0 if intangible else float(dmg))
        elif include_wither and cid == "CARD.WITHER":
            dmg = max(0, (c.get("stats") or {}).get("damage", 3))
            if dmg > 0:
                hits.append(1.0 if intangible else float(dmg))
    return hits


def _apply_hit_damage(hit_dmg, block, buffer_stacks, intangible):
    """Resolve one damage event against current Block, Buffer, and Intangible."""
    if hit_dmg <= 0:
        return 0.0, block, buffer_stacks
    dmg = min(1.0, float(hit_dmg)) if intangible else float(hit_dmg)
    if block >= dmg:
        return 0.0, block - dmg, buffer_stacks
    rem = dmg - block
    block = 0.0
    if buffer_stacks > 0:
        return 0.0, block, buffer_stacks - 1
    return rem, block, buffer_stacks


def _resolve_attack_hits(
    raw_damage,
    hits,
    e_block,
    e_buffer,
    e_slippery,
    e_hard_cap,
    e_intangible,
    e_curl_up=0.0,
    *,
    triggers_curl_up=True,
    slippery_after_block=False,
    curl_up_per_hit=False,
    enemy_hp=None,
    return_hits_landed=False,
):
    """Resolve an attack's per-hit damage against enemy Block, Buffer, Slippery, Curl Up, and caps."""
    if raw_damage <= 0 or hits <= 0 or (enemy_hp is not None and enemy_hp <= 0):
        if return_hits_landed:
            return 0.0, e_block, e_buffer, e_slippery, e_curl_up, 0
        return 0.0, e_block, e_buffer, e_slippery, e_curl_up
    per_hit = raw_damage / hits
    hp_loss = 0.0
    hits_landed = 0
    for _ in range(int(hits)):
        if enemy_hp is not None and hp_loss >= enemy_hp:
            break
        hits_landed += 1
        h = per_hit
        if not slippery_after_block and e_slippery > 0:
            h = min(h, 1.0)
            e_slippery -= 1
        if e_hard_cap > 0:
            h = min(h, float(e_hard_cap))
        if e_intangible:
            h = min(h, 1.0)
        if e_block >= h:
            e_block -= h
        else:
            rem = h - e_block
            e_block = 0.0
            if e_buffer > 0:
                e_buffer -= 1
            else:
                if slippery_after_block and e_slippery > 0:
                    rem = min(rem, 1.0)
                    e_slippery -= 1
                hp_loss += rem
                if curl_up_per_hit and rem > 0 and triggers_curl_up and e_curl_up > 0:
                    e_block += e_curl_up
                    e_curl_up = 0.0
    if not curl_up_per_hit and hp_loss > 0 and triggers_curl_up and e_curl_up > 0:
        # Native Curl Up triggers once after the full powered attack card resolves.
        e_block += e_curl_up
        e_curl_up = 0.0
    if return_hits_landed:
        return hp_loss, e_block, e_buffer, e_slippery, e_curl_up, hits_landed
    return hp_loss, e_block, e_buffer, e_slippery, e_curl_up


def _enemy_attack_hits_list(
    intent_total,
    hits_count,
    already_weak,
    newly_weak,
    str_drop,
    intangible,
    *,
    already_debilitated=False,
    newly_debilitated=False,
):
    """Compute per-hit enemy attack values applying Strength delta (positive=loss, negative=gain) BEFORE Weak."""
    if intent_total <= 0:
        return ()
    n = max(1, int(hits_count))
    per_hit = intent_total / n
    old_mult = (0.5 if already_debilitated else 0.75) if already_weak else 1.0
    weak_after = already_weak or newly_weak
    new_mult = (0.5 if (already_debilitated or newly_debilitated) else 0.75) if weak_after else 1.0
    if str_drop > 0:
        if already_weak:
            # Displayed intent already reflects current Weak; recover conservative upper bound.
            base = math.ceil(per_hit / old_mult)
            adj = max(0, base - str_drop)
            per_hit = float(math.floor(adj * new_mult))
        else:
            adj = max(0.0, per_hit - str_drop)
            per_hit = float(math.floor(adj * new_mult)) if weak_after else adj
    elif str_drop < 0:
        gain = -str_drop
        if already_weak:
            # Largest integer base satisfying floor(base * old_mult) <= per_hit.
            base = math.ceil((per_hit + 1) / old_mult) - 1
            adj = base + gain
            per_hit = float(math.floor(adj * new_mult))
        else:
            adj = per_hit + gain
            per_hit = float(math.floor(adj * new_mult)) if weak_after else adj
    elif newly_weak and not already_weak:
        per_hit = float(math.floor(per_hit * new_mult))
    elif already_weak and newly_debilitated and not already_debilitated:
        base = math.ceil(per_hit / 0.75)
        per_hit = float(math.floor(base * 0.5))
    if per_hit <= 0:
        return ()
    if intangible:
        per_hit = min(per_hit, 1.0)
    return (per_hit,) * n


def _search_survival_lines(
    state,
    policy,
    actions,
    *,
    width=8,
    depth=5,
    forced_first=None,
    facing=None,
    score_adjust=None,
    return_plow=False,
):
    scores = policy.combat_scores(state, actions)
    if score_adjust is not None:
        score_adjust(scores)
    end = next(i for i, a in enumerate(actions) if a.kind == "end_turn")
    enemies = [e for e in state["enemies"] if e["hp"] > 0]
    size = len(enemies)
    if size == 0:
        idx = max(range(len(actions)), key=scores.__getitem__)
        best = (1, 1, 0, scores[idx], scores[idx], -idx, idx)
        if return_plow:
            return best, {idx: best}, None, {}
        return best, {idx: best}

    act2_mech = bool(getattr(policy, "act2_mechanics", False))
    enemy_mech = bool(getattr(policy, "enemy_mechanics", False))
    card_pot_mech = bool(getattr(policy, "card_potion_mechanics", False))
    fixes_v4 = bool(getattr(policy, "combat_fixes_v4", False))
    v3_mech = enemy_mech or card_pot_mech
    v3_or_v4 = v3_mech or fixes_v4
    e_hp = tuple(e["hp"] for e in enemies)
    e_block = tuple(float(e.get("block", 0)) for e in enemies)
    e_total = tuple(e["hp"] + e.get("block", 0) for e in enemies)
    e_poison = tuple(max(0, _power(e.get("powers"), "POISON")) for e in enemies)
    e_intangible = tuple(_power(e.get("powers"), "INTANGIBLE") > 0 for e in enemies)
    e_buffer = tuple(max(0, _power(e.get("powers"), "BUFFER")) for e in enemies)
    e_slippery = tuple(max(0, _power(e.get("powers"), "SLIPPERY")) for e in enemies)
    e_hard_cap = tuple(max(0, _power(e.get("powers"), "HARD_TO_KILL")) for e in enemies)
    e_thorns = tuple(max(0, _power(e.get("powers"), "THORNS")) for e in enemies)
    e_reflect = tuple(_power(e.get("powers"), "REFLECT") > 0 for e in enemies)
    e_curl_up = (
        tuple(float(max(0, _power(e.get("powers"), "CURL_UP"))) for e in enemies)
        if act2_mech
        else (0.0,) * size
    )
    e_crab_rage = (
        tuple(_power(e.get("powers"), "CRAB_RAGE") > 0 for e in enemies)
        if act2_mech
        else (False,) * size
    )
    e_plow = (
        tuple(max(0, _power(e.get("powers"), "PLOW")) for e in enemies)
        if enemy_mech
        else (0,) * size
    )
    e_strength = (
        tuple(max(0, _power(e.get("powers"), "STRENGTH")) for e in enemies)
        if enemy_mech
        else (0,) * size
    )
    e_vital_spark = (
        tuple(max(0, _power(e.get("powers"), "VITAL_SPARK")) for e in enemies)
        if enemy_mech
        else (0,) * size
    )
    any_vital_spark = any(e_vital_spark)
    e_minion = tuple(_power(e.get("powers"), "MINION") > 0 for e in enemies)
    has_leader = any(not m for m in e_minion)
    e_weak = tuple(_power(e.get("powers"), "WEAK") > 0 for e in enemies)
    e_vuln = tuple(_power(e.get("powers"), "VULNERABLE") > 0 for e in enemies)
    e_debilitate = (
        tuple(_power(e.get("powers"), "DEBILITATE") > 0 for e in enemies)
        if card_pot_mech
        else (False,) * size
    )
    e_hits = tuple(attack_hits(e) for e in enemies)
    e_intents = tuple(incoming(e) for e in enemies)
    shields = tuple(max(0, _power(e.get("powers"), "ARTIFACT")) for e in enemies)
    solo_giant = size == 1 and enemies[0].get("id") == WATERFALL_GIANT
    giant_deathblow = solo_giant and any(
        i.get("type") == "DeathBlow" for i in (enemies[0].get("intents") or ())
    )

    w = policy.weights
    cost_exp = getattr(policy, "cost_exponent", w.cost_exponent)
    focus = tuple(
        1 + w.focus * (1 - e["hp"] / max(1, e["max_hp"])) if size > 1 else 1 for e in enemies
    )
    player = state["player"]
    player_hp = player["hp"]
    powers = state.get("player_powers") or []
    start_block = float(player["block"])
    plating = float(max(0, _power(powers, "PLATING")))
    start_intangible = max(0, _power(powers, "INTANGIBLE"))
    start_buffer = max(0, _power(powers, "BUFFER"))
    start_afterimage = max(0, _power(powers, "AFTERIMAGE"))
    start_shadowmeld = max(0, _power(powers, "SHADOWMELD")) if card_pot_mech else 0
    start_giga = max(0, _power(powers, "GIGANTIFICATION")) if card_pot_mech else 0
    start_burst = max(0, _power(powers, "BURST")) if v3_or_v4 else 0
    start_dup = (
        sum(max(0, int(p.get("amount", 0))) for p in powers if "DUPLICAT" in p.get("id", ""))
        if v3_or_v4
        else 0
    )
    accelerant = max(0, _power(powers, "ACCELERANT"))
    constrict = max(0, _power(powers, "CONSTRICT")) if fixes_v4 else 0
    strangler_indices = (
        tuple(i for i, e in enumerate(enemies) if e.get("id") == "MONSTER.SLITHERING_STRANGLER")
        if fixes_v4
        else ()
    )
    sandpit_idx = (
        next((i for i, e in enumerate(enemies) if _power(e.get("powers"), "SANDPIT") == 1), None)
        if fixes_v4
        else None
    )
    no_block = fixes_v4 and _power(powers, "NO_BLOCK") > 0
    player_weak = _power(powers, "WEAK") > 0
    shiv_damage = max(0, 4 + _power(powers, "STRENGTH") + _power(powers, "ACCURACY"))
    surrounded = (
        act2_mech and facing is not None and size == 2 and _power(powers, "SURROUNDED") > 0
    )
    start_facing_pos = (
        next((i for i, e in enumerate(enemies) if e["index"] == facing), None)
        if surrounded
        else None
    )
    revive = any(
        _power(e.get("powers"), "ILLUSION")
        or _power(e.get("powers"), "INFESTED")
        or (enemy_mech and _power(e.get("powers"), "ADAPTABLE"))
        for e in enemies
    )
    leader_revive = (
        any(
            (not e_minion[i])
            and (
                _power(e.get("powers"), "ILLUSION")
                or _power(e.get("powers"), "INFESTED")
                or (enemy_mech and _power(e.get("powers"), "ADAPTABLE"))
            )
            for i, e in enumerate(enemies)
        )
        if act2_mech
        else revive
    )
    cards = {c["index"]: c for c in state["hand"]}
    potions = {p["index"]: p for p in player["potions"]}
    tender = getattr(policy, "tender", False) and any(
        p["id"] == "POWER.TENDER_POWER" for p in powers
    )
    slots = getattr(policy, "sloth_slots", None)
    card_mask = sum(1 << index for index in cards) if tender or slots is not None else 0
    energy = state["energy"]
    hand_list = list(state["hand"])
    start_hand_size = len(hand_list)
    has_precise_cut = fixes_v4 and any(c.get("id") == "CARD.PRECISE_CUT" for c in hand_list)
    start_rem_draws = (
        (int(state.get("draw_pile_count", 0)) + int(state.get("discard_pile_count", 0)))
        if (fixes_v4 and ("draw_pile_count" in state or "discard_pile_count" in state))
        else None
    )

    def evaluate_state(
        damage,
        guaranteed_damage,
        poison,
        cur_block,
        weak_mask,
        str_drop,
        intangible,
        buffer_stacks,
        self_loss,
        cur_facing=None,
        cur_slippery=None,
        cur_ebuf=None,
        skills_played=0,
        debilitate_mask=0,
        escaped_sandpit=False,
        used_mask=0,
        total_shadowmeld=0,
    ):
        giant = None
        if solo_giant:
            giant = waterfall_forecast(
                enemies[0],
                state["round"],
                hp_loss=int(guaranteed_damage[0]),
                added_poison=poison[0],
                accelerant=accelerant,
            )
        giant_eruption = bool(giant and giant.eruption_damage is not None)
        offense = 0.0
        direct_killed = [False] * size
        killed_flags = [False] * size
        plow_stunned_flags = [False] * size
        for i in range(size):
            slip_i = (cur_slippery[i] if cur_slippery is not None else e_slippery[i]) if v3_mech else 0
            buf_i = (cur_ebuf[i] if cur_ebuf is not None else e_buffer[i]) if v3_mech else 0
            p_loss = _poison_tick_loss(
                e_poison[i] + poison[i],
                accelerant,
                e_intangible[i],
                slippery=slip_i,
                buffer=buf_i,
                hard_cap=e_hard_cap[i] if fixes_v4 else 0,
            )
            direct_killed[i] = (
                (not giant_eruption) and (not giant_deathblow) and (guaranteed_damage[i] >= e_hp[i])
            )
            g_killed = (not giant_eruption) and (not giant_deathblow) and (
                guaranteed_damage[i] + p_loss >= e_hp[i]
            )
            soft_killed = (damage[i] >= e_total[i]) or (
                max(0.0, damage[i] - e_block[i]) + p_loss >= e_hp[i]
            )
            offense += min(e_total[i], damage[i]) * focus[i]
            if soft_killed and not giant_eruption and not giant_deathblow:
                offense += 14.0
            killed_flags[i] = g_killed
            # Native Plow stuns on any positive HP damage landing at or below the threshold.
            if (
                enemy_mech
                and not g_killed
                and e_plow[i] > 0
                and (guaranteed_damage[i] + p_loss) > 0
                and (e_hp[i] - guaranteed_damage[i] - p_loss) <= e_plow[i]
            ):
                plow_stunned_flags[i] = True
                offense += 14.0 + 3.0 * e_strength[i]

        direct_leaders_dead = has_leader and all(
            direct_killed[i] for i in range(size) if not e_minion[i]
        )
        direct_clears = (
            fixes_v4
            and (not giant_eruption)
            and (not giant_deathblow)
            and ((all(direct_killed) and not revive) or (direct_leaders_dead and not leader_revive))
        )
        if direct_clears:
            return offense, 0.0, self_loss, (self_loss < player_hp), True, any(plow_stunned_flags)

        # Killing all non-minion leaders ends the encounter immediately (minions flee).
        leaders_dead = has_leader and all(
            killed_flags[i] for i in range(size) if not e_minion[i]
        )
        if leaders_dead and not leader_revive and not giant_eruption:
            all_hits = []
            guaranteed_alive = 0
        else:
            guaranteed_alive = sum(not k for k in killed_flags)
            ally_died = any(killed_flags)
            both_alive_surrounded = (
                surrounded
                and start_facing_pos is not None
                and cur_facing is not None
                and cur_facing != start_facing_pos
                and not killed_flags[0]
                and not killed_flags[1]
            )
            all_hits = []
            for i in range(size):
                if killed_flags[i] or plow_stunned_flags[i]:
                    continue
                inc_i = 0 if (giant and giant.eruption_forced) else e_intents[i]
                if inc_i > 0:
                    hits_i = max(1, int(e_hits[i]))
                    if both_alive_surrounded:
                        per_hit = inc_i / hits_i
                        inc_i = hits_i * (
                            math.floor(per_hit * 1.5)
                            if i == start_facing_pos
                            else math.ceil(per_hit / 1.5)
                        )
                    elif ally_died and surrounded and start_facing_pos is not None and i != start_facing_pos:
                        # When one enemy dies, Silent turns toward the sole survivor (losing Back Attack bonus).
                        per_hit = inc_i / hits_i
                        inc_i = hits_i * math.ceil(per_hit / 1.5)
                    if ally_died and e_crab_rage[i]:
                        # Crab Rage grants +6 Strength at A10 immediately when the partner dies.
                        inc_i += 6 * hits_i
                    net_str_drop = str_drop[i] - (skills_played * e_vital_spark[i] if enemy_mech else 0)
                    all_hits.extend(
                        _enemy_attack_hits_list(
                            inc_i,
                            e_hits[i],
                            e_weak[i],
                            bool(weak_mask & (1 << i)),
                            net_str_drop,
                            intangible > 0,
                            already_debilitated=e_debilitate[i],
                            newly_debilitated=bool(debilitate_mask & (1 << i)),
                        )
                    )

        # End-of-turn resolution: Plating applies, then Burns/Wither/Constrict (player end), then Poison -> enemy hits.
        plating_eff = plating * (1 << total_shadowmeld) if (fixes_v4 and card_pot_mech) else plating
        rem_block = cur_block + plating_eff
        rem_buf = buffer_stacks
        end_turn_loss = 0.0
        for bh in _hand_burn_hits(
            hand_list, intangible > 0, include_wither=fixes_v4, used_mask=used_mask if fixes_v4 else 0
        ):
            loss, rem_block, rem_buf = _apply_hit_damage(bh, rem_block, rem_buf, intangible > 0)
            end_turn_loss += loss
        if constrict > 0 and (
            not strangler_indices or any(not direct_killed[idx] for idx in strangler_indices)
        ):
            loss, rem_block, rem_buf = _apply_hit_damage(
                float(constrict), rem_block, rem_buf, intangible > 0
            )
            end_turn_loss += loss
        # Under combat_fixes_v4, preserve native enemy execution order; legacy keeps worst-case descending sort.
        ordered_hits = all_hits if fixes_v4 else sorted(all_hits, reverse=True)
        for eh in ordered_hits:
            loss, rem_block, rem_buf = _apply_hit_damage(eh, rem_block, rem_buf, False)
            end_turn_loss += loss

        hp_loss = self_loss + end_turn_loss
        sandpit_dead = (
            sandpit_idx is not None
            and not killed_flags[sandpit_idx]
            and not (fixes_v4 and leaders_dead and not leader_revive and not giant_eruption)
            and not escaped_sandpit
        )
        survives = (hp_loss < player_hp) and not sandpit_dead
        # Surviving a displayed DeathBlow ends combat (Giant removes itself after DeathBlow).
        clears = (
            (giant_deathblow and survives)
            or (guaranteed_alive == 0 and not leader_revive and not giant_eruption)
        )
        return offense, end_turn_loss, hp_loss, survives, clears, any(plow_stunned_flags)

    root_offense, root_end_loss, root_hp_loss, _, _, _ = evaluate_state(
        (0.0,) * size,
        (0.0,) * size,
        (0,) * size,
        start_block,
        0,
        (0,) * size,
        start_intangible,
        start_buffer,
        0.0,
        cur_facing=start_facing_pos,
        cur_slippery=e_slippery,
        cur_ebuf=e_buffer,
        skills_played=0,
        debilitate_mask=0,
        used_mask=0,
        total_shadowmeld=start_shadowmeld,
    )
    block_weight = w.block * (1.0 + min(2.0, root_end_loss / max(1, player_hp)))

    def board_value(offense, end_loss):
        return offense + block_weight * (root_end_loss - end_loss)

    root_board = board_value(root_offense, root_end_loss)

    def line_quality_and_meta(hand, first_idx):
        offense, end_loss, hp_loss, survives, clears, plow_stunned = evaluate_state(
            hand.damage,
            hand.guaranteed_damage,
            hand.poison,
            hand.block,
            hand.weak,
            hand.str_drop,
            hand.intangible,
            hand.buffer,
            hand.self_hp_loss,
            cur_facing=hand.facing,
            cur_slippery=hand.enemy_slippery,
            cur_ebuf=hand.enemy_buffer,
            skills_played=hand.skills_played,
            debilitate_mask=hand.debilitate,
            escaped_sandpit=hand.escaped_sandpit,
            used_mask=hand.used,
            total_shadowmeld=start_shadowmeld + hand.shadowmeld,
        )
        utility = board_value(offense, end_loss) + hand.extra
        if clears:
            utility += 35.0
        if survives:
            q = (
                1,
                int(clears),
                -hand.potions_used if clears else 0,
                utility,
                scores[first_idx],
                -first_idx,
                first_idx,
            )
            plow_q = (
                (1, int(clears), -hand.potions_used, utility, -hp_loss, scores[first_idx], first_idx)
                if plow_stunned
                else None
            )
            return q, plow_q, hp_loss, hand.potions_used
        deficit = hp_loss - player_hp + 1.0
        q = (
            0,
            int(hand.has_escape),
            -deficit,
            utility,
            scores[first_idx],
            -first_idx,
            first_idx,
        )
        return q, None, hp_loss, hand.potions_used

    def _build_move(action_index, item, *, potion, target, delayed_only=False):
        if potion:
            stats = {k.lower(): v for k, v in (item.get("vars") or {}).items()}
            source = max(cards, default=-1) + 1 + item["index"]
            cost = 0
        else:
            stats = item.get("stats") or {}
            source = item["index"]
            cost = _cost(item)
        name = item.get("id", "").split(".")[-1]
        is_x = bool(item.get("costs_x"))
        effective_cost = energy if is_x else cost
        is_self_only = fixes_v4 and item.get("target_type") in ("Self", "AnyPlayer", "AnyAlly")
        targets = () if is_self_only else ([target] if target is not None else range(size))
        random_multi = (
            item.get("target_type") == "RandomEnemy" or name == "BOUNCING_FLASK"
        ) and size > 1
        is_attack = (not potion) and item.get("type") == "Attack"
        is_skill = (not potion) and item.get("type") == "Skill"
        hits = _hits(item)
        if is_x and name in ("SKEWER", "VOLLEY", "STARDUST"):
            hits = energy
        k_shivs = (
            int(stats.get("calculatedshivs", 0))
            if (card_pot_mech and not potion and name == "KNIFE_TRAP")
            else 0
        )
        is_knife_trap = k_shivs > 0
        if is_knife_trap:
            hits = k_shivs

        d = [0.0] * size
        gd = [0.0] * size
        weak_order = [0] * size
        debilitate_order = [0] * size
        poison_apps = [() for _ in range(size)]
        str_drop = [() for _ in range(size)]
        debuffs = [0] * size
        per_hit_x_dmg = [0.0] * size
        x_malaise_amt = (
            int(bool(item.get("upgrades") or item.get("upgraded")))
            if (fixes_v4 and not potion and is_x and name == "MALAISE")
            else 0
        )

        for i in targets:
            raw_d = 0.0
            if potion and item.get("target_type") in ("AnyEnemy", "AllEnemies", "RandomEnemy"):
                raw_d = float(stats.get("damage", 0))
            elif is_attack:
                if is_x:
                    if fixes_v4 and name in ("SKEWER", "VOLLEY", "STARDUST"):
                        preview = next(
                            (
                                p
                                for p in (item.get("damage_by_target") or ())
                                if p.get("target_index") == enemies[i]["index"]
                            ),
                            {},
                        )
                        if energy > 0 and "total_damage" in preview and hits > 0:
                            ph = float(preview["total_damage"]) / hits
                        else:
                            ph = float(
                                preview.get(
                                    "damage", stats.get("calculateddamage", stats.get("damage", 0))
                                )
                            )
                        per_hit_x_dmg[i] = ph / size if random_multi else ph
                        raw_d = ph * hits if hits > 0 else 0.0
                    else:
                        raw_d = float(stats.get("damage", 0) * hits) if hits > 0 else 0.0
                else:
                    raw_d = float(_damage(item, enemies[i]))
            elif is_knife_trap:
                raw_d = float(k_shivs * shiv_damage)
            if random_multi:
                d[i] = raw_d / size
                gd[i] = 0.0
            else:
                d[i] = raw_d
                gd[i] = raw_d

            if not random_multi:
                effects = list(debuff_order(item, stats, enemies[i], energy=energy))
                if card_pot_mech and not potion and not is_self_only:
                    esl = int(stats.get("enemystrengthloss", 0))
                    if esl > 0:
                        effects.append(("strength_loss", esl))
                    deb_amt = int(stats.get("debilitatepower", 0))
                    if deb_amt > 0:
                        effects.append(("debilitate", deb_amt))
                if item.get("id") == "CARD.EXPOSE":
                    debuffs[i] = len(effects) + shields[i]
                else:
                    debuffs[i] = len(effects)
                if not e_weak[i]:
                    weak_order[i] = next(
                        (n for n, (kind, _) in enumerate(effects, 1) if kind == "weak"), 0
                    )
                if card_pot_mech and not e_debilitate[i]:
                    debilitate_order[i] = next(
                        (n for n, (kind, _) in enumerate(effects, 1) if kind == "debilitate"), 0
                    )
                poison_apps[i] = tuple(
                    (n, amount) for n, (kind, amount) in enumerate(effects, 1) if kind == "poison"
                )
                str_drop[i] = tuple(
                    (n, amount)
                    for n, (kind, amount) in enumerate(effects, 1)
                    if kind == "strength_loss"
                )

        card_block = 0.0 if (no_block and not potion) else float(block_preview(stats))
        is_fortifier = potion and name == "FORTIFIER"
        afterimage_gain = int(stats.get("afterimagepower", 0)) if not potion else 0
        burst_gain = int(stats.get("skills", 1)) if (v3_or_v4 and not potion and name == "BURST") else 0
        shadowmeld_gain = (
            int(stats.get("power", 1))
            if (card_pot_mech and not potion and name == "SHADOWMELD")
            else 0
        )
        strength_gain = (
            int(stats.get("strengthpower", 0))
            if (card_pot_mech and potion and name in ("FLEX_POTION", "STRENGTH_POTION", "FYSH_OIL"))
            else (
                -int(stats.get("playerstrengthloss", 0))
                if (card_pot_mech and not potion and name == "SHARED_FATE")
                else 0
            )
        )
        intangible_gain = (
            int(stats.get("intangiblepower", 1)) if name in ("WRAITH_FORM", "GHOST_IN_A_JAR") else 0
        )
        buffer_gain = int(stats.get("bufferpower", 0))
        self_loss = float(stats.get("hploss", 0))
        foul_damage = float(stats.get("damage", 0)) if potion and name == "FOUL_POTION" else 0.0
        e_gain = (
            int(stats.get("energy", 0))
            if (
                (potion and name == "ENERGY_POTION")
                or (fixes_v4 and not potion and name == "ADRENALINE")
            )
            else 0
        )
        precise_extra = (
            int(stats.get("extradamage", 2))
            if (fixes_v4 and not potion and name == "PRECISE_CUT")
            else 0
        )
        precise_raw_base = ()
        if precise_extra > 0:
            up_pc = bool(item.get("upgrades") or item.get("upgraded"))
            native_base = float((16 if up_pc else 13) + _power(powers, "STRENGTH"))
            bases = [0.0] * size
            root_other = max(0, start_hand_size - 1)
            for i in targets:
                root_mult = (
                    (1.5 if e_vuln[i] else 1.0)
                    * (0.75 if player_weak else 1.0)
                    * (3.0 if (card_pot_mech and start_giga > 0) else 1.0)
                )
                expected_root = math.floor(
                    max(0.0, native_base - precise_extra * root_other) * root_mult
                )
                if expected_root == int(round(d[i])):
                    bases[i] = native_base
                elif d[i] > 0:
                    bases[i] = float(
                        math.ceil(d[i] / max(1e-6, root_mult)) + precise_extra * root_other
                    )
                else:
                    bases[i] = native_base
            precise_raw_base = tuple(bases)
        shivs_added = _shiv_count(item) if (fixes_v4 and not potion) else 0
        draws_added = _draw_count(item) if (fixes_v4 and not potion) else 0
        hand_delta_m = (1 - _shiv_count(item)) if (fixes_v4 and not potion) else 0
        escapes_sp = fixes_v4 and not potion and name == "FRANTIC_ESCAPE"
        applies_nb = fixes_v4 and not potion and name == "PANIC_BUTTON"
        # Stop speculative chaining on redraws AND mandatory discards (remaining hand cannot be guaranteed).
        stops = name in _REDRAW_ITEMS or (not potion and name in _MANDATORY_DISCARD_CARDS)
        draws = (
            (name in _REDRAW_ITEMS)
            or name in _ESCAPE_DRAW_ITEMS
            or (not potion and _draw_count(item) > 0)
            or (potion and stats.get("cards", 0) > 0)
        )
        clears_block = item.get("id") == "CARD.EXPOSE"
        req_poison = item.get("id") == "CARD.BUBBLE_BUBBLE"

        if delayed_only:
            residual = 0.0
        else:
            # Single-step delta from root so residual reconstructs intrinsic with zero double-counting.
            step_gd = [0.0] * size
            step_eslip = list(e_slippery)
            step_ebuf = list(e_buffer)
            step_weak = 0
            step_debilitate = 0
            step_poison = [0] * size
            step_str = [0] * size
            step_sm_after = start_shadowmeld + shadowmeld_gain
            if is_fortifier:
                fort_s = 2.0 * start_block * ((1 << start_shadowmeld) if (fixes_v4 and card_pot_mech) else 1)
                step_block = start_block + fort_s
            elif potion and card_pot_mech and start_shadowmeld > 0 and card_block > 0:
                step_block = start_block + card_block * (1 << start_shadowmeld)
            else:
                step_block = start_block + card_block
            if not potion and (fixes_v4 or not no_block):
                ai_mult = (1 << step_sm_after) if card_pot_mech else 1
                ai_triggers = 1 + (k_shivs if is_knife_trap else 0)
                step_block += ai_triggers * start_afterimage * ai_mult
            step_buf = start_buffer + buffer_gain
            step_int = start_intangible + intangible_gain
            step_self = 0.0
            if fixes_v4 and self_loss > 0:
                s_hp_d, _, step_buf = _apply_hit_damage(self_loss, 0.0, step_buf, step_int > 0)
                step_self += s_hp_d
            elif not fixes_v4:
                step_self = self_loss
            for i in range(size):
                if gd[i] > 0:
                    eb = 0.0 if clears_block else e_block[i]
                    res_hit = _resolve_attack_hits(
                        gd[i],
                        max(1, hits) if (is_attack or is_knife_trap) else 1,
                        eb,
                        e_buffer[i],
                        e_slippery[i],
                        e_hard_cap[i],
                        e_intangible[i],
                        e_curl_up[i],
                        triggers_curl_up=is_attack or is_knife_trap,
                        slippery_after_block=v3_mech,
                        curl_up_per_hit=is_knife_trap,
                        enemy_hp=float(e_hp[i]) if fixes_v4 else None,
                        return_hits_landed=fixes_v4,
                    )
                    if fixes_v4:
                        hp_dmg, _, ebuf_after, eslip_after, _, landed_h = res_hit
                    else:
                        hp_dmg, _, ebuf_after, eslip_after, _ = res_hit
                        landed_h = max(1, hits)
                    step_gd[i] = hp_dmg
                    step_eslip[i] = eslip_after
                    step_ebuf[i] = ebuf_after
                    if is_attack or is_knife_trap:
                        for _ in range(landed_h):
                            if e_thorns[i] > 0:
                                loss, step_block, step_buf = _apply_hit_damage(
                                    e_thorns[i], step_block, step_buf, step_int > 0
                                )
                                step_self += loss
                        if e_reflect[i] and eb > 0:
                            loss, step_block, step_buf = _apply_hit_damage(
                                min(gd[i], eb), step_block, step_buf, step_int > 0
                            )
                            step_self += loss
                rem = 0 if clears_block else shields[i]
                if weak_order[i] > rem:
                    step_weak |= 1 << i
                if card_pot_mech and debilitate_order[i] > rem:
                    step_debilitate |= 1 << i
                if not req_poison or e_poison[i] > 0:
                    step_poison[i] = sum(amt for order, amt in poison_apps[i] if order > rem)
                step_str[i] = sum(amt for order, amt in str_drop[i] if order > rem)
            if foul_damage > 0:
                loss, step_block, step_buf = _apply_hit_damage(
                    foul_damage, step_block, step_buf, step_int > 0
                )
                step_self += loss

            step_skill_plays = 0
            if enemy_mech and is_skill:
                step_skill_plays = 1 + int(start_dup > 0) + int(start_burst > 0)
            # Keep cur_facing=start_facing_pos for residual extraction because scores[j]
            # (from combat_scores + adjust_focus) does not include the Surrounded facing delta.
            s_off, s_end_loss, _, _, _, _ = evaluate_state(
                tuple(d),
                tuple(step_gd),
                tuple(step_poison),
                step_block,
                step_weak,
                tuple(step_str),
                step_int,
                step_buf,
                step_self,
                cur_facing=start_facing_pos,
                cur_slippery=tuple(step_eslip),
                cur_ebuf=tuple(step_ebuf),
                skills_played=step_skill_plays,
                debilitate_mask=step_debilitate,
                used_mask=1 << source,
                total_shadowmeld=step_sm_after,
            )
            step_delta = board_value(s_off, s_end_loss) - root_board
            intrinsic = scores[action_index] * max(1, effective_cost) ** cost_exp
            if e_gain > 0:
                intrinsic -= e_gain * min(7.0, max(0.0, (len(cards) - energy - 1) * 2.5))
            if card_pot_mech and shadowmeld_gain > 0:
                # Beam computes Shadowmeld's value directly from doubled chained Block cards.
                intrinsic = 0.0
            if card_pot_mech and potion and name == "FLEX_POTION":
                # Keep the potion reserve penalty while letting chained attacks supply the damage gain.
                rt = state.get("context", {}).get("room_type")
                w_pot = getattr(getattr(policy, "style", None), "potion", 1.0)
                base_res = (7.0 if rt == "Boss" else 10.5 if rt == "Elite" else 14.0) * w_pot
                est_res = base_res / (
                    1.0 + 0.53 * (len(potions) >= 2) + min(2.0, root_end_loss / max(1, player_hp))
                )
                intrinsic = -est_res
            residual = intrinsic - step_delta

        return _SurvivalMove(
            action_index,
            1 << source,
            name,
            effective_cost,
            is_x,
            e_gain,
            target,
            is_attack,
            max(1, hits) if (is_attack or is_knife_trap) else 1,
            tuple(d),
            tuple(gd),
            card_block,
            is_fortifier,
            afterimage_gain,
            tuple(weak_order),
            tuple(poison_apps),
            tuple(str_drop),
            tuple(debuffs),
            clears_block,
            req_poison,
            intangible_gain,
            buffer_gain,
            self_loss,
            foul_damage,
            potion,
            stops,
            draws,
            residual,
            _hits(item) if tender and is_attack else 0,
            bool(
                tender
                and not potion
                and ("block" in stats or "calculatedblock" in stats)
            ),
            is_skill=is_skill,
            is_knife_trap=is_knife_trap,
            knife_trap_shivs=k_shivs,
            shadowmeld_gain=shadowmeld_gain,
            strength_gain=strength_gain,
            burst_gain=burst_gain,
            debilitate_order=tuple(debilitate_order),
            delayed_only=delayed_only,
            precise_extra=precise_extra,
            hand_delta=hand_delta_m,
            escapes_sandpit=escapes_sp,
            applies_no_block=applies_nb,
            per_hit_x_damage=tuple(per_hit_x_dmg),
            x_malaise_amt=x_malaise_amt,
            shivs_added=shivs_added,
            draws_added=draws_added,
            precise_raw_base=precise_raw_base,
            is_random_multi=random_multi,
        )

    moves = []
    for j, a in enumerate(actions):
        if j == end:
            continue
        potion = a.kind == "use_potion"
        item = potions[a.args["potion_index"]] if potion else cards[a.args["card_index"]]
        indices = [i for i, e in enumerate(enemies) if e["index"] == a.args.get("target_index")]
        target = indices[0] if indices else None
        moves.append(_build_move(j, item, potion=potion, target=target, delayed_only=False))

    # Unlock unaffordable-at-root hand cards when an Energy Potion or Adrenaline (+Burst/Duplication) is available.
    max_e_gain = 0
    if fixes_v4:
        burst_in_hand = sum(
            1 for c in hand_list if c.get("can_play") and c.get("id") == "CARD.BURST"
        )
        adren_replays = 1 + min(
            2,
            int(start_burst + burst_in_hand > 0) + int(start_dup > 0),
        )
        seen_e_sources = set()
        for m in moves:
            if m.energy_gain > 0 and m.source not in seen_e_sources:
                seen_e_sources.add(m.source)
                mult = adren_replays if (not m.potion and m.is_skill) else 1
                max_e_gain += m.energy_gain * mult
    if fixes_v4 and max_e_gain > 0:
        normal_sources = {m.source for m in moves if not m.potion}
        for item in hand_list:
            if item.get("can_play") or (1 << item["index"]) in normal_sources:
                continue
            if (
                "Unplayable" in (item.get("keywords") or ())
                or item.get("id") in ("CARD.GRAND_FINALE", "CARD.CLASH")
                or item.get("star_cost", 0) > state.get("stars", 0)
                or (
                    item.get("type") == "Attack"
                    and (_power(powers, "ENTANGLED") > 0 or _power(powers, "NO_ATTACKS") > 0)
                )
                or (
                    item.get("type") in ("Curse", "Status", "Quest")
                    and item.get("id") != "CARD.FRANTIC_ESCAPE"
                )
            ):
                continue
            c_is_x = bool(item.get("costs_x"))
            c_cost = _cost(item)
            if c_is_x:
                if energy > 0:
                    continue
            elif c_cost <= energy or c_cost > energy + max_e_gain:
                continue
            ttype = item.get("target_type")
            t_options = list(range(size)) if ttype == "AnyEnemy" else [None]
            for tgt in t_options:
                moves.append(_build_move(-1, item, potion=False, target=tgt, delayed_only=True))

    start = _SurvivalHand(
        (0.0,) * size,
        (0.0,) * size,
        e_block,
        e_buffer,
        e_slippery,
        (0,) * size,
        start_block,
        0,
        (0,) * size,
        shields,
        start_intangible,
        start_buffer,
        start_afterimage,
        0.0,
        0,
        False,
        0,
        energy,
        0.0,
        None,
        enemy_curl_up=e_curl_up,
        facing=start_facing_pos,
        giga_rem=start_giga,
        burst_rem=start_burst,
        dup_rem=start_dup,
        no_block=no_block,
        hand_size=start_hand_size,
        rem_draws=start_rem_draws,
    )
    end_quality, end_plow, _, _ = line_quality_and_meta(start, end)
    best_overall = end_quality
    best_by_first = {end: end_quality}
    best_plow_overall = end_plow
    best_plow_by_first = {end: end_plow} if end_plow is not None else {}

    beam = [start]
    for step_idx in range(depth):
        next_hands = {}
        for hand in beam:
            if hand.stopped:
                continue
            for m in moves:
                if step_idx == 0 and m.delayed_only:
                    continue
                if step_idx == 0 and forced_first is not None and m.action_index != forced_first:
                    continue
                if hand.used & m.source:
                    continue
                if slots is not None and not m.potion and (card_mask & hand.used).bit_count() >= slots:
                    continue
                if m.target is not None:
                    if act2_mech:
                        if hand.guaranteed_damage[m.target] >= e_hp[m.target]:
                            continue
                    elif hand.damage[m.target] >= e_total[m.target]:
                        continue

                cur_burst = hand.burst_rem
                cur_dup = hand.dup_rem
                replays = 1
                if v3_or_v4 and not m.potion:
                    if cur_dup > 0:
                        replays += 1
                        cur_dup -= 1
                    if m.is_skill and cur_burst > 0:
                        replays += 1
                        cur_burst -= 1
                    n_exec_burst = replays if fixes_v4 else 1
                    cur_burst += m.burst_gain * n_exec_burst
                cur_skills_played = hand.skills_played + (replays if (enemy_mech and m.is_skill) else 0)
                n_exec = replays if fixes_v4 else 1

                if m.x_cost:
                    if fixes_v4:
                        if hand.energy < 0:
                            continue
                        x_energy = hand.energy
                        next_energy = 0
                    else:
                        if hand.energy != energy:
                            continue
                        x_energy = energy
                        next_energy = 0
                else:
                    if hand.energy < m.cost:
                        continue
                    x_energy = 0
                    next_energy = hand.energy - m.cost + (m.energy_gain * n_exec if fixes_v4 else m.energy_gain)

                prior_cards = (card_mask & hand.used).bit_count() if tender else 0

                if fixes_v4:
                    cur_damage = list(hand.damage)
                    new_gd = list(hand.guaranteed_damage)
                    cur_block = hand.block
                    cur_shadowmeld = hand.shadowmeld
                    cur_no_block = hand.no_block
                    cur_afterimage = hand.afterimage
                    cur_str_gain = hand.strength_gain
                    cur_giga = hand.giga_rem
                    cur_int = hand.intangible
                    cur_buf = hand.buffer
                    cur_self = hand.self_hp_loss
                    cur_hand_size = hand.hand_size
                    cur_rem_draws = hand.rem_draws
                    new_eblock = list(hand.enemy_block)
                    new_ebuf = list(hand.enemy_buffer)
                    new_eslip = list(hand.enemy_slippery)
                    new_ecurl = list(hand.enemy_curl_up) if hand.enemy_curl_up else [0.0] * size
                    weak = hand.weak
                    debilitate = hand.debilitate
                    poison = list(hand.poison)
                    str_drop = list(hand.str_drop)
                    new_artifact = list(hand.artifact)

                    for _exec_i in range(n_exec):
                        exec_hits = (
                            max(0, x_energy)
                            if (m.x_cost and m.is_attack and m.name in ("SKEWER", "VOLLEY", "STARDUST"))
                            else m.hits
                        )
                        exec_dmg = [0.0] * size
                        exec_gd = [0.0] * size
                        for i in range(size):
                            if m.target is not None and m.target != i:
                                continue
                            if m.precise_extra > 0 and m.is_attack:
                                if m.precise_raw_base:
                                    eff_other = max(0, cur_hand_size - (1 if _exec_i == 0 else 0))
                                    raw_val = max(
                                        0.0,
                                        m.precise_raw_base[i]
                                        + cur_str_gain
                                        - m.precise_extra * eff_other,
                                    )
                                    mult = (
                                        (1.5 if e_vuln[i] else 1.0)
                                        * (0.75 if player_weak else 1.0)
                                        * (3.0 if (card_pot_mech and cur_giga > 0) else 1.0)
                                    )
                                    val = float(math.floor(raw_val * mult))
                                    if tender and prior_cards and m.tender_hits and val > 0:
                                        val = max(0.0, val - prior_cards * m.tender_hits)
                                    exec_dmg[i] = val
                                    exec_gd[i] = val
                            elif m.x_cost and m.is_attack and m.name in ("SKEWER", "VOLLEY", "STARDUST"):
                                if exec_hits > 0 and m.per_hit_x_damage:
                                    ph = m.per_hit_x_damage[i]
                                    if ph > 0:
                                        if card_pot_mech and start_giga > 0 and cur_giga <= 0:
                                            ph = float(math.floor(ph / 3.0))
                                        if card_pot_mech and cur_str_gain != 0:
                                            mult = (
                                                (1.5 if e_vuln[i] else 1.0)
                                                * (0.75 if player_weak else 1.0)
                                                * (3.0 if (card_pot_mech and cur_giga > 0) else 1.0)
                                            )
                                            if cur_str_gain > 0:
                                                ph += float(math.floor(cur_str_gain * mult))
                                            else:
                                                ph = max(0.0, ph - float(math.ceil((-cur_str_gain) * mult)))
                                        tot = ph * exec_hits
                                        if tender and prior_cards and m.tender_hits:
                                            tot = max(0.0, tot - prior_cards * exec_hits)
                                        exec_dmg[i] = tot
                                        exec_gd[i] = 0.0 if m.is_random_multi else tot
                            else:
                                dd = m.damage[i]
                                gdd = m.guaranteed_damage[i]
                                if card_pot_mech and start_giga > 0 and m.is_attack and cur_giga <= 0:
                                    if dd > 0:
                                        dd = float(math.floor(dd / 3.0))
                                    if gdd > 0:
                                        gdd = float(math.floor(gdd / 3.0))
                                if card_pot_mech and cur_str_gain != 0 and m.is_attack:
                                    mult = (
                                        (1.5 if e_vuln[i] else 1.0)
                                        * (0.75 if player_weak else 1.0)
                                        * (3.0 if (card_pot_mech and cur_giga > 0) else 1.0)
                                    )
                                    if cur_str_gain > 0:
                                        str_delta = float(math.floor(cur_str_gain * mult) * exec_hits)
                                    else:
                                        str_delta = -float(math.ceil((-cur_str_gain) * mult) * exec_hits)
                                    if dd > 0:
                                        dd = max(0.0, dd + str_delta)
                                    if gdd > 0:
                                        gdd = max(0.0, gdd + str_delta)
                                if tender and prior_cards and m.tender_hits:
                                    if dd > 0:
                                        dd = max(0.0, dd - prior_cards * m.tender_hits)
                                    if gdd > 0:
                                        gdd = max(0.0, gdd - prior_cards * m.tender_hits)
                                exec_dmg[i] = dd
                                exec_gd[i] = gdd
                        if m.is_attack and cur_giga > 0:
                            cur_giga -= 1

                        pre_ai = cur_afterimage
                        if m.is_fortifier:
                            fort_gain = 2.0 * cur_block * (
                                (1 << (start_shadowmeld + cur_shadowmeld)) if card_pot_mech else 1
                            )
                            cur_block += fort_gain
                        elif not (cur_no_block and not m.potion):
                            c_blk = (
                                max(0.0, m.card_block - prior_cards)
                                if (tender and prior_cards and m.tender_block)
                                else m.card_block
                            )
                            if card_pot_mech and c_blk > 0:
                                if m.potion:
                                    c_blk *= 1 << (start_shadowmeld + cur_shadowmeld)
                                elif cur_shadowmeld > 0:
                                    c_blk *= 1 << cur_shadowmeld
                            cur_block += c_blk

                        cur_shadowmeld += m.shadowmeld_gain
                        if m.applies_no_block:
                            cur_no_block = True
                        cur_int += m.intangible
                        cur_buf += m.buffer
                        cur_str_gain += m.strength_gain
                        cur_afterimage += m.afterimage_gain
                        if m.self_hp_loss > 0:
                            s_loss, _, cur_buf = _apply_hit_damage(
                                m.self_hp_loss, 0.0, cur_buf, cur_int > 0
                            )
                            cur_self += s_loss

                        for i in range(size):
                            if new_gd[i] >= e_hp[i]:
                                continue
                            if m.clears_block and (m.target is None or m.target == i):
                                new_eblock[i] = 0.0
                            if exec_gd[i] > 0 and exec_hits > 0:
                                pre_eb = new_eblock[i]
                                pre_gd = new_gd[i]
                                (
                                    hp_dmg,
                                    eb_after,
                                    ebuf_after,
                                    eslip_after,
                                    ecurl_after,
                                    landed_hits,
                                ) = _resolve_attack_hits(
                                    exec_gd[i],
                                    exec_hits,
                                    new_eblock[i],
                                    new_ebuf[i],
                                    new_eslip[i],
                                    e_hard_cap[i],
                                    e_intangible[i],
                                    new_ecurl[i],
                                    triggers_curl_up=m.is_attack or m.is_knife_trap,
                                    slippery_after_block=v3_mech,
                                    curl_up_per_hit=m.is_knife_trap,
                                    enemy_hp=max(0.0, float(e_hp[i]) - new_gd[i]),
                                    return_hits_landed=True,
                                )
                                new_gd[i] = min(float(e_hp[i]), new_gd[i] + hp_dmg)
                                new_eblock[i] = eb_after
                                new_ebuf[i] = ebuf_after
                                new_eslip[i] = eslip_after
                                new_ecurl[i] = ecurl_after
                                if pre_gd < e_hp[i] <= new_gd[i]:
                                    # Crab Rage immediately grants surviving partners 99 Block on ally death.
                                    for j in range(size):
                                        if j != i and e_crab_rage[j] and new_gd[j] < e_hp[j]:
                                            new_eblock[j] += 99.0
                                if m.is_attack or m.is_knife_trap:
                                    for _ in range(landed_hits):
                                        if e_thorns[i] > 0:
                                            loss, cur_block, cur_buf = _apply_hit_damage(
                                                e_thorns[i], cur_block, cur_buf, cur_int > 0
                                            )
                                            cur_self += loss
                                    if e_reflect[i] and pre_eb > 0:
                                        loss, cur_block, cur_buf = _apply_hit_damage(
                                            min(exec_gd[i], pre_eb), cur_block, cur_buf, cur_int > 0
                                        )
                                        cur_self += loss
                            rem = 0 if m.clears_block else new_artifact[i]
                            if m.x_cost and m.name == "MALAISE":
                                if m.target is None or m.target == i:
                                    x_mal = x_energy + m.x_malaise_amt
                                    if x_mal > 0:
                                        if 1 > rem:
                                            str_drop[i] += x_mal
                                        if 2 > rem and not e_weak[i]:
                                            weak |= 1 << i
                                        new_artifact[i] = max(0, new_artifact[i] - 2)
                            else:
                                if m.weak_order[i] > rem:
                                    weak |= 1 << i
                                if card_pot_mech and m.debilitate_order[i] > rem:
                                    debilitate |= 1 << i
                                if (not m.requires_existing_poison) or (e_poison[i] + poison[i] > 0):
                                    for order, amt in m.poison_apps[i]:
                                        if order > rem:
                                            poison[i] += amt
                                for order, amt in m.str_drop[i]:
                                    if order > rem:
                                        str_drop[i] += amt
                                new_artifact[i] = max(0, new_artifact[i] - m.debuffs[i])
                            cur_damage[i] = min(e_total[i], cur_damage[i] + exec_dmg[i])

                        if m.is_random_multi and (m.is_attack or m.is_knife_trap) and exec_hits > 0:
                            worst_thorns = max(
                                (e_thorns[i] for i in range(size) if new_gd[i] < e_hp[i]),
                                default=0,
                            )
                            if worst_thorns > 0:
                                for _ in range(exec_hits):
                                    loss, cur_block, cur_buf = _apply_hit_damage(
                                        worst_thorns, cur_block, cur_buf, cur_int > 0
                                    )
                                    cur_self += loss

                        if not m.potion and pre_ai > 0:
                            ai_mult = (1 << (start_shadowmeld + cur_shadowmeld)) if card_pot_mech else 1
                            ai_triggers = 1 + (m.knife_trap_shivs if m.is_knife_trap else 0)
                            cur_block += ai_triggers * pre_ai * ai_mult

                        actual_draws = (
                            min(m.draws_added, cur_rem_draws)
                            if cur_rem_draws is not None
                            else m.draws_added
                        )
                        if cur_rem_draws is not None:
                            cur_rem_draws = max(0, cur_rem_draws - actual_draws)
                        cur_hand_size = min(
                            10,
                            max(
                                0,
                                cur_hand_size
                                - (1 if (_exec_i == 0 and not m.potion) else 0)
                                + m.shivs_added
                                + actual_draws,
                            ),
                        )

                    damage = tuple(cur_damage)
                else:
                    damage_deltas = list(m.damage)
                    gd_deltas = list(m.guaranteed_damage)
                    if card_pot_mech and start_giga > 0 and m.is_attack and hand.giga_rem <= 0:
                        # Root previews include active Gigantification (3x); subsequent attacks deal unmultiplied damage.
                        for i in range(size):
                            if damage_deltas[i] > 0:
                                damage_deltas[i] = float(math.floor(damage_deltas[i] / 3.0))
                            if gd_deltas[i] > 0:
                                gd_deltas[i] = float(math.floor(gd_deltas[i] / 3.0))
                    if card_pot_mech and hand.strength_gain != 0 and m.is_attack:
                        for i in range(size):
                            mult = (1.5 if e_vuln[i] else 1.0) * (0.75 if player_weak else 1.0)
                            if hand.strength_gain > 0:
                                str_delta = float(math.floor(hand.strength_gain * mult) * m.hits)
                            else:
                                str_delta = -float(math.ceil((-hand.strength_gain) * mult) * m.hits)
                            if damage_deltas[i] > 0:
                                damage_deltas[i] = max(0.0, damage_deltas[i] + str_delta)
                            if gd_deltas[i] > 0:
                                gd_deltas[i] = max(0.0, gd_deltas[i] + str_delta)
                    if tender and prior_cards and m.tender_hits:
                        for i in range(size):
                            if damage_deltas[i] > 0:
                                damage_deltas[i] = max(0.0, damage_deltas[i] - prior_cards * m.tender_hits)
                            if gd_deltas[i] > 0:
                                gd_deltas[i] = max(0.0, gd_deltas[i] - prior_cards * m.tender_hits)

                    damage = tuple(
                        min(h, prev + delta)
                        for h, prev, delta in zip(e_total, hand.damage, damage_deltas, strict=True)
                    )

                    # Block: Fortifier triples current projected Block; Shadowmeld doubles owner Block gains (incl. Afterimage & potions).
                    cur_shadowmeld = hand.shadowmeld + m.shadowmeld_gain
                    total_sm = start_shadowmeld + cur_shadowmeld
                    cur_block = hand.block
                    if m.is_fortifier:
                        cur_block += 2.0 * cur_block
                    else:
                        c_blk = max(0.0, m.card_block - prior_cards) if (tender and prior_cards and m.tender_block) else m.card_block
                        if card_pot_mech and c_blk > 0:
                            if m.potion:
                                c_blk *= 1 << total_sm
                            elif hand.shadowmeld > 0:
                                c_blk *= 1 << hand.shadowmeld
                        cur_block += c_blk
                    if not m.potion:
                        ai_mult = (1 << total_sm) if card_pot_mech else 1
                        ai_triggers = 1 + (m.knife_trap_shivs if m.is_knife_trap else 0)
                        cur_block += ai_triggers * hand.afterimage * ai_mult
                    cur_afterimage = hand.afterimage + m.afterimage_gain
                    cur_str_gain = hand.strength_gain + m.strength_gain
                    cur_giga = max(0, hand.giga_rem - int(m.is_attack)) if card_pot_mech else 0
                    cur_int = hand.intangible + m.intangible
                    cur_buf = hand.buffer + m.buffer
                    cur_self = hand.self_hp_loss + m.self_hp_loss
                    cur_no_block = False
                    cur_hand_size = 0
                    cur_rem_draws = None

                    new_eblock = list(hand.enemy_block)
                    new_ebuf = list(hand.enemy_buffer)
                    new_eslip = list(hand.enemy_slippery)
                    new_ecurl = list(hand.enemy_curl_up) if hand.enemy_curl_up else [0.0] * size
                    new_gd = list(hand.guaranteed_damage)
                    weak = hand.weak
                    debilitate = hand.debilitate
                    poison = list(hand.poison)
                    str_drop = list(hand.str_drop)
                    new_artifact = list(hand.artifact)

                    for i in range(size):
                        if m.clears_block and (m.target is None or m.target == i):
                            new_eblock[i] = 0.0
                        if gd_deltas[i] > 0:
                            pre_eb = new_eblock[i]
                            pre_gd = new_gd[i]
                            hp_dmg, eb_after, ebuf_after, eslip_after, ecurl_after = _resolve_attack_hits(
                                gd_deltas[i],
                                m.hits,
                                new_eblock[i],
                                new_ebuf[i],
                                new_eslip[i],
                                e_hard_cap[i],
                                e_intangible[i],
                                new_ecurl[i],
                                triggers_curl_up=m.is_attack or m.is_knife_trap,
                                slippery_after_block=v3_mech,
                                curl_up_per_hit=m.is_knife_trap,
                            )
                            new_gd[i] = min(float(e_hp[i]), new_gd[i] + hp_dmg)
                            new_eblock[i] = eb_after
                            new_ebuf[i] = ebuf_after
                            new_eslip[i] = eslip_after
                            new_ecurl[i] = ecurl_after
                            if pre_gd < e_hp[i] <= new_gd[i]:
                                # Crab Rage immediately grants surviving partners 99 Block on ally death.
                                for j in range(size):
                                    if j != i and e_crab_rage[j] and new_gd[j] < e_hp[j]:
                                        new_eblock[j] += 99.0
                            if m.is_attack or m.is_knife_trap:
                                for _ in range(m.hits):
                                    if e_thorns[i] > 0:
                                        loss, cur_block, cur_buf = _apply_hit_damage(
                                            e_thorns[i], cur_block, cur_buf, cur_int > 0
                                        )
                                        cur_self += loss
                                if e_reflect[i] and pre_eb > 0:
                                    loss, cur_block, cur_buf = _apply_hit_damage(
                                        min(gd_deltas[i], pre_eb), cur_block, cur_buf, cur_int > 0
                                    )
                                    cur_self += loss
                        rem = 0 if m.clears_block else hand.artifact[i]
                        if m.weak_order[i] > rem:
                            weak |= 1 << i
                        if card_pot_mech and m.debilitate_order[i] > rem:
                            debilitate |= 1 << i
                        if (not m.requires_existing_poison) or (e_poison[i] + hand.poison[i] > 0):
                            for order, amt in m.poison_apps[i]:
                                if order > rem:
                                    poison[i] += amt
                        for order, amt in m.str_drop[i]:
                            if order > rem:
                                str_drop[i] += amt
                        new_artifact[i] = max(0, hand.artifact[i] - m.debuffs[i])

                if m.foul_damage > 0:
                    loss, cur_block, cur_buf = _apply_hit_damage(
                        m.foul_damage, cur_block, cur_buf, cur_int > 0
                    )
                    cur_self += loss

                artifact_t = tuple(new_artifact)
                next_facing = m.target if (surrounded and m.target is not None) else hand.facing
                first = m.action_index if hand.first is None else hand.first
                projection = _SurvivalHand(
                    damage,
                    tuple(new_gd),
                    tuple(new_eblock),
                    tuple(new_ebuf),
                    tuple(new_eslip),
                    tuple(poison),
                    cur_block,
                    weak,
                    tuple(str_drop),
                    artifact_t,
                    cur_int,
                    cur_buf,
                    cur_afterimage,
                    cur_self,
                    hand.potions_used + int(m.potion),
                    hand.has_escape or m.has_escape,
                    hand.used | m.source,
                    next_energy,
                    hand.extra + m.extra,
                    first,
                    stopped=m.stops_expansion,
                    enemy_curl_up=tuple(new_ecurl),
                    facing=next_facing,
                    skills_played=cur_skills_played,
                    shadowmeld=cur_shadowmeld,
                    strength_gain=cur_str_gain,
                    giga_rem=cur_giga,
                    burst_rem=cur_burst,
                    dup_rem=cur_dup,
                    debilitate=debilitate,
                    hand_delta=(hand.hand_delta + m.hand_delta) if fixes_v4 else 0,
                    escaped_sandpit=hand.escaped_sandpit or m.escapes_sandpit,
                    no_block=cur_no_block,
                    hand_size=cur_hand_size,
                    rem_draws=cur_rem_draws if fixes_v4 else None,
                )
                quality, plow_q, _, _ = line_quality_and_meta(projection, first)
                if quality > best_overall:
                    best_overall = quality
                prev_first = best_by_first.get(first)
                if prev_first is None or quality > prev_first:
                    best_by_first[first] = quality
                if plow_q is not None:
                    if best_plow_overall is None or plow_q > best_plow_overall:
                        best_plow_overall = plow_q
                    prev_pf = best_plow_by_first.get(first)
                    if prev_pf is None or plow_q > prev_pf:
                        best_plow_by_first[first] = plow_q

                if quality[0] == 1 and quality[1] == 1:
                    continue
                if projection.stopped:
                    continue
                key = (
                    projection.used,
                    projection.energy,
                    projection.damage,
                    projection.guaranteed_damage if (act2_mech or v3_mech) else (),
                    projection.enemy_block if (act2_mech or v3_mech) else (),
                    projection.enemy_buffer if v3_mech else (),
                    projection.enemy_curl_up if act2_mech else (),
                    projection.enemy_slippery if v3_mech else (),
                    projection.poison,
                    projection.block,
                    projection.weak,
                    projection.str_drop if v3_mech else (),
                    projection.self_hp_loss if v3_mech else 0.0,
                    projection.intangible,
                    projection.buffer,
                    projection.afterimage,
                    artifact_t,
                    projection.facing,
                    projection.skills_played if any_vital_spark else 0,
                    projection.shadowmeld if card_pot_mech else 0,
                    projection.strength_gain if card_pot_mech else 0,
                    projection.giga_rem if card_pot_mech else 0,
                    projection.burst_rem if v3_or_v4 else 0,
                    projection.dup_rem if v3_or_v4 else 0,
                    projection.debilitate if card_pot_mech else 0,
                    projection.escaped_sandpit if fixes_v4 else False,
                    projection.no_block if fixes_v4 else False,
                    projection.hand_size if has_precise_cut else 0,
                    projection.rem_draws if has_precise_cut else None,
                )
                previous = next_hands.get(key)
                if previous is None or quality > previous[0]:
                    next_hands[key] = (quality, projection)
        if not next_hands:
            break
        candidates = list(next_hands.values())
        by_quality = sorted(candidates, key=lambda pair: pair[0], reverse=True)
        keep_n = max(1, width // 2)
        kept = by_quality[:keep_n]
        kept_ids = {id(pair[1]) for pair in kept}
        by_progress = sorted(
            candidates,
            key=lambda pair: (pair[0][1], pair[0][3], pair[0][4]),
            reverse=True,
        )
        for pair in by_progress:
            if len(kept) >= width:
                break
            if id(pair[1]) not in kept_ids:
                kept.append(pair)
                kept_ids.add(id(pair[1]))
        beam = [h for _, h in kept]
    if return_plow:
        return best_overall, best_by_first, best_plow_overall, best_plow_by_first
    return best_overall, best_by_first


def choose_turn_survival(
    state, policy, proposed, *, width=8, depth=5, facing=None, score_adjust=None
):
    """Override a proposed greedy combat action only when a lethal threat demands a better line."""
    actions = legal_actions(state)
    if state["decision"] != "combat_play" or len(actions) <= 1:
        return proposed
    enemies = [e for e in state["enemies"] if e["hp"] > 0]
    if not enemies:
        return proposed

    # Fast path: skip search only when End Turn survives (incl. Burns) AND proposed has no lethal recoil/self-damage.
    player = state["player"]
    powers = state.get("player_powers") or []
    start_block = float(player["block"])
    plating = float(max(0, _power(powers, "PLATING")))
    intangible = _power(powers, "INTANGIBLE") > 0
    buf_stacks = max(0, _power(powers, "BUFFER"))
    accelerant = max(0, _power(powers, "ACCELERANT"))
    giant = solo_waterfall_forecast(state, enemies)
    giant_eruption = bool(giant and giant.eruption_damage is not None)
    act2_mech = bool(getattr(policy, "act2_mechanics", False))
    enemy_mech = bool(getattr(policy, "enemy_mechanics", False))
    card_pot_mech = bool(getattr(policy, "card_potion_mechanics", False))
    fixes_v4 = bool(getattr(policy, "combat_fixes_v4", False))
    v3_mech = enemy_mech or card_pot_mech
    start_shadowmeld = max(0, _power(powers, "SHADOWMELD")) if (fixes_v4 and card_pot_mech) else 0
    plating_eff = plating * (1 << start_shadowmeld) if (fixes_v4 and card_pot_mech) else plating
    surrounded_flip = act2_mech and (
        (
            facing is not None
            and len(enemies) == 2
            and _power(powers, "SURROUNDED") > 0
            and proposed.args.get("target_index") is not None
            and proposed.args.get("target_index") != facing
        )
        or any(_power(e.get("powers"), "CRAB_RAGE") > 0 for e in enemies)
    )
    # Native Plow triggers on any positive HP damage landing at or below the threshold (even if HP already <= threshold).
    plow_in_range = enemy_mech and any(
        e["hp"] - _power(e.get("powers"), "PLOW") <= 55 and incoming(e) > 0
        for e in enemies
        if _power(e.get("powers"), "PLOW") > 0
    )

    self_risk = 0.0
    if proposed.kind == "play_card":
        card = next((c for c in state["hand"] if c["index"] == proposed.args["card_index"]), {})
        card_replays = (
            (
                1
                + int(any("DUPLICAT" in p.get("id", "") and p.get("amount", 0) > 0 for p in powers))
                + int(card.get("type") == "Skill" and _power(powers, "BURST") > 0)
            )
            if fixes_v4
            else 1
        )
        self_risk += float((card.get("stats") or {}).get("hploss", 0)) * card_replays
        if enemy_mech and card.get("type") == "Skill" and not intangible:
            skill_plays = (
                1
                + int(any("DUPLICAT" in p.get("id", "") and p.get("amount", 0) > 0 for p in powers))
                + int(_power(powers, "BURST") > 0)
            )
            for e in enemies:
                vs = max(0, _power(e.get("powers"), "VITAL_SPARK"))
                if vs > 0 and incoming(e) > 0:
                    self_risk += skill_plays * attack_hits(e) * float(vs)
        is_kt = (
            card_pot_mech
            and card.get("id") == "CARD.KNIFE_TRAP"
            and int((card.get("stats") or {}).get("calculatedshivs", 0)) > 0
        )
        if card.get("type") == "Attack" or is_kt:
            cname_p = card.get("id", "").split(".")[-1]
            if is_kt:
                hits = int((card.get("stats") or {}).get("calculatedshivs", 0))
            elif fixes_v4 and card.get("costs_x") and cname_p in ("SKEWER", "VOLLEY", "STARDUST"):
                hits = max(0, state["energy"])
            else:
                hits = max(1, _hits(card))
            target_idx = proposed.args.get("target_index")
            affected = [e for e in enemies if e["index"] == target_idx] if target_idx is not None else enemies
            for e in affected:
                thorns = max(0, _power(e.get("powers"), "THORNS"))
                if thorns > 0:
                    self_risk += card_replays * hits * (1.0 if intangible else float(thorns))
                if _power(e.get("powers"), "REFLECT") > 0 and e.get("block", 0) > 0:
                    self_risk += card_replays * (1.0 if intangible else float(e.get("block", 0)))
    elif proposed.kind == "use_potion":
        pot = next(
            (p for p in player["potions"] if p["index"] == proposed.args["potion_index"]), {}
        )
        if pot.get("id") == "POTION.FOUL_POTION":
            self_risk += 1.0 if intangible else float((pot.get("vars") or {}).get("Damage", 0))

    # Resolve End Turn damage (Plating -> Burns/Wither/Constrict -> Poison -> enemy hits).
    rem_block = start_block + plating_eff
    rem_buf = buf_stacks
    end_loss = 0.0
    for bh in _hand_burn_hits(state["hand"], intangible, include_wither=fixes_v4):
        loss, rem_block, rem_buf = _apply_hit_damage(bh, rem_block, rem_buf, intangible)
        end_loss += loss
    if fixes_v4:
        constrict = max(0, _power(powers, "CONSTRICT"))
        if constrict > 0:
            loss, rem_block, rem_buf = _apply_hit_damage(
                float(constrict), rem_block, rem_buf, intangible
            )
            end_loss += loss
    sandpit_lethal = False
    if not (giant and giant.eruption_forced):
        all_hits = []
        for e in enemies:
            p_loss = _poison_tick_loss(
                max(0, _power(e.get("powers"), "POISON")),
                accelerant,
                _power(e.get("powers"), "INTANGIBLE") > 0,
                slippery=max(0, _power(e.get("powers"), "SLIPPERY")) if v3_mech else 0,
                buffer=max(0, _power(e.get("powers"), "BUFFER")) if v3_mech else 0,
                hard_cap=max(0, _power(e.get("powers"), "HARD_TO_KILL")) if fixes_v4 else 0,
            )
            if p_loss >= e["hp"] and not giant_eruption:
                continue
            if fixes_v4 and _power(e.get("powers"), "SANDPIT") == 1:
                sandpit_lethal = True
            inc = incoming(e)
            if inc > 0:
                all_hits.extend(_enemy_attack_hits_list(inc, attack_hits(e), False, False, 0, intangible))
        ordered_hits = all_hits if fixes_v4 else sorted(all_hits, reverse=True)
        for eh in ordered_hits:
            loss, rem_block, rem_buf = _apply_hit_damage(eh, rem_block, rem_buf, False)
            end_loss += loss

    non_lethal_plow_only = (
        plow_in_range
        and not surrounded_flip
        and not sandpit_lethal
        and end_loss + self_risk < player["hp"]
    )
    if (
        not surrounded_flip
        and not plow_in_range
        and not sandpit_lethal
        and end_loss + self_risk < player["hp"]
    ):
        return proposed

    proposed_idx = next((i for i, a in enumerate(actions) if a == proposed), None)
    best_overall, best_by_first, best_plow_overall, best_plow_by_first = _search_survival_lines(
        state,
        policy,
        actions,
        width=width,
        depth=depth,
        facing=facing,
        score_adjust=score_adjust,
        return_plow=True,
    )
    best_proposed = best_by_first.get(proposed_idx) if proposed_idx is not None else None
    best_proposed_plow = best_plow_by_first.get(proposed_idx) if proposed_idx is not None else None
    probed_indices = set()
    # All-dead beam fallback: if narrow global beam found no surviving line, probe distinct first moves.
    if fixes_v4 and best_overall[0] == 0:
        cand_indices = [
            i for i, a in enumerate(actions) if a.kind != "end_turn"
        ]
        # Rank candidate probes by best_by_first quality (highest utility/lowest deficit first).
        cand_indices.sort(
            key=lambda i: best_by_first.get(i, (0, 0, -1e9, -1e9, -1e9, -i, i)),
            reverse=True,
        )
        seen_sig = set()
        probes = []
        cards_by_i = {c["index"]: c for c in state["hand"]}
        pots_by_i = {p["index"]: p for p in player["potions"]}
        for i in cand_indices:
            a = actions[i]
            if a.kind == "play_card":
                c = cards_by_i.get(a.args["card_index"], {})
                sig = (
                    "card",
                    c.get("id"),
                    _cost(c),
                    c.get("upgrades", 0),
                    bool(c.get("upgraded")),
                    c.get("enchantment"),
                    c.get("enchantment_amount"),
                    tuple(sorted((c.get("stats") or {}).items())),
                    tuple(
                        (p.get("target_index"), p.get("damage"), p.get("total_damage"))
                        for p in (c.get("damage_by_target") or ())
                    ),
                    a.args.get("target_index"),
                )
            else:
                p = pots_by_i.get(a.args["potion_index"], {})
                sig = (
                    "pot",
                    p.get("id"),
                    tuple(sorted((p.get("vars") or {}).items())),
                    a.args.get("target_index"),
                )
            if sig in seen_sig:
                continue
            seen_sig.add(sig)
            probes.append(i)
            if len(probes) >= 6:
                break
        for probe_idx in probes:
            probed_indices.add(probe_idx)
            _, forced_p, _, forced_p_plow = _search_survival_lines(
                state,
                policy,
                actions,
                width=width,
                depth=depth,
                forced_first=probe_idx,
                facing=facing,
                score_adjust=score_adjust,
                return_plow=True,
            )
            if probe_idx in forced_p:
                cand_q = forced_p[probe_idx]
                if probe_idx not in best_by_first or cand_q > best_by_first[probe_idx]:
                    best_by_first[probe_idx] = cand_q
                if cand_q > best_overall:
                    best_overall = cand_q
                if probe_idx == proposed_idx and (best_proposed is None or cand_q > best_proposed):
                    best_proposed = cand_q
            if probe_idx in forced_p_plow:
                cand_pq = forced_p_plow[probe_idx]
                prev_pf = best_plow_by_first.get(probe_idx)
                if prev_pf is None or cand_pq > prev_pf:
                    best_plow_by_first[probe_idx] = cand_pq
                if best_plow_overall is None or cand_pq > best_plow_overall:
                    best_plow_overall = cand_pq
                if probe_idx == proposed_idx and (best_proposed_plow is None or cand_pq > best_proposed_plow):
                    best_proposed_plow = cand_pq
            if best_overall[0] == 1 and best_overall[1] == 1 and best_overall[2] == 0:
                break
    # Before overriding a proposal, run a dedicated forced-first pass in case width pruning dropped its continuation.
    needs_forced = (
        proposed_idx is not None
        and proposed_idx not in probed_indices
        and (
            best_proposed is None
            or best_proposed[:3] < best_overall[:3]
            or (non_lethal_plow_only and best_plow_overall is not None and best_proposed_plow is None)
        )
    )
    if needs_forced:
        _, forced, _, forced_plow = _search_survival_lines(
            state,
            policy,
            actions,
            width=width,
            depth=depth,
            forced_first=proposed_idx,
            facing=facing,
            score_adjust=score_adjust,
            return_plow=True,
        )
        if proposed_idx in forced and (best_proposed is None or forced[proposed_idx] > best_proposed):
            best_proposed = forced[proposed_idx]
        if proposed_idx in forced_plow and (
            best_proposed_plow is None or forced_plow[proposed_idx] > best_proposed_plow
        ):
            best_proposed_plow = forced_plow[proposed_idx]
    if best_proposed is None:
        return actions[best_overall[-1]]
    if non_lethal_plow_only:
        # On a non-lethal turn, override for a clear or a Plow stun that proposed misses without wasting a potion.
        if best_overall[0] == 1 and best_overall[1] > best_proposed[1]:
            return actions[best_overall[-1]]
        if best_plow_overall is not None and best_proposed_plow is None:
            potions_spent = -best_plow_overall[2]
            if potions_spent == 0 or end_loss >= 10.0:
                return actions[best_plow_overall[-1]]
        return proposed
    if best_proposed[0] == 1 and best_proposed[:3] >= best_overall[:3]:
        return proposed
    if best_proposed[0] == 0 and best_overall[0] == 0 and best_proposed[:3] >= best_overall[:3]:
        return proposed
    return actions[best_overall[-1]]
