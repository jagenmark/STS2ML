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
from .run_policy import _cost, _damage, _draw_count, _hits, _power
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


def choose_turn(state, policy, *, width=6, depth=5, survival_priority=False):
    if survival_priority:
        actions = legal_actions(state)
        if state["decision"] != "combat_play" or len(actions) <= 1:
            return policy(state)
        best, _ = _search_survival_lines(state, policy, actions, width=max(width, 8), depth=depth)
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


def _poison_tick_loss(stacks, accelerant, intangible):
    if stacks <= 0:
        return 0
    ticks = min(stacks, 1 + accelerant)
    if intangible:
        return ticks
    return ticks * stacks - ticks * (ticks - 1) // 2


def _hand_burn_hits(hand, intangible):
    hits = []
    for c in hand:
        if c.get("id") == "CARD.BURN":
            dmg = max(0, (c.get("stats") or {}).get("damage", 2))
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


def _resolve_attack_hits(raw_damage, hits, e_block, e_buffer, e_slippery, e_hard_cap, e_intangible):
    """Resolve an attack's per-hit damage against enemy Block, Buffer, Slippery, and caps."""
    if raw_damage <= 0 or hits <= 0:
        return 0.0, e_block, e_buffer, e_slippery
    per_hit = raw_damage / hits
    hp_loss = 0.0
    for _ in range(int(hits)):
        h = per_hit
        if e_slippery > 0:
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
                hp_loss += rem
    return hp_loss, e_block, e_buffer, e_slippery


def _enemy_attack_hits_list(intent_total, hits_count, already_weak, newly_weak, str_drop, intangible):
    """Compute per-hit enemy attack values applying Strength loss BEFORE Weak."""
    if intent_total <= 0:
        return ()
    n = max(1, int(hits_count))
    per_hit = intent_total / n
    if str_drop > 0:
        if already_weak:
            # Displayed intent already reflects Weak (floor(base * 0.75)); recover upper bound.
            base = math.ceil(per_hit / 0.75)
            adj = max(0, base - str_drop)
            per_hit = float(math.floor(adj * 0.75))
        else:
            adj = max(0.0, per_hit - str_drop)
            per_hit = float(math.floor(adj * 0.75)) if newly_weak else adj
    elif newly_weak and not already_weak:
        per_hit = float(math.floor(per_hit * 0.75))
    if per_hit <= 0:
        return ()
    if intangible:
        per_hit = min(per_hit, 1.0)
    return (per_hit,) * n


def _search_survival_lines(state, policy, actions, *, width=8, depth=5, forced_first=None):
    scores = policy.combat_scores(state, actions)
    end = next(i for i, a in enumerate(actions) if a.kind == "end_turn")
    enemies = [e for e in state["enemies"] if e["hp"] > 0]
    size = len(enemies)
    if size == 0:
        idx = max(range(len(actions)), key=scores.__getitem__)
        best = (1, 1, 0, scores[idx], scores[idx], -idx, idx)
        return best, {idx: best}

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
    e_minion = tuple(_power(e.get("powers"), "MINION") > 0 for e in enemies)
    has_leader = any(not m for m in e_minion)
    e_weak = tuple(_power(e.get("powers"), "WEAK") > 0 for e in enemies)
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
    accelerant = max(0, _power(powers, "ACCELERANT"))
    revive = any(
        _power(e.get("powers"), "ILLUSION") or _power(e.get("powers"), "INFESTED") for e in enemies
    )
    cards = {c["index"]: c for c in state["hand"]}
    potions = {p["index"]: p for p in player["potions"]}
    tender = getattr(policy, "tender", False) and any(
        p["id"] == "POWER.TENDER_POWER" for p in powers
    )
    card_mask = sum(1 << index for index in cards) if tender else 0
    energy = state["energy"]
    hand_list = list(state["hand"])

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
        killed_flags = [False] * size
        for i in range(size):
            p_loss = _poison_tick_loss(e_poison[i] + poison[i], accelerant, e_intangible[i])
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

        # Killing all non-minion leaders ends the encounter immediately (minions flee).
        leaders_dead = has_leader and all(
            killed_flags[i] for i in range(size) if not e_minion[i]
        )
        if leaders_dead and not revive and not giant_eruption:
            all_hits = []
            guaranteed_alive = 0
        else:
            guaranteed_alive = sum(not k for k in killed_flags)
            all_hits = []
            for i in range(size):
                if killed_flags[i]:
                    continue
                inc_i = 0 if (giant and giant.eruption_forced) else e_intents[i]
                if inc_i > 0:
                    all_hits.extend(
                        _enemy_attack_hits_list(
                            inc_i,
                            e_hits[i],
                            e_weak[i],
                            bool(weak_mask & (1 << i)),
                            str_drop[i],
                            intangible > 0,
                        )
                    )

        # End-of-turn resolution: Plating applies, then Burns in hand, then enemy hits in order.
        rem_block = cur_block + plating
        rem_buf = buffer_stacks
        end_turn_loss = 0.0
        for bh in _hand_burn_hits(hand_list, intangible > 0):
            loss, rem_block, rem_buf = _apply_hit_damage(bh, rem_block, rem_buf, intangible > 0)
            end_turn_loss += loss
        # Order enemy hits conservatively (largest unblocked potential).
        for eh in sorted(all_hits, reverse=True):
            loss, rem_block, rem_buf = _apply_hit_damage(eh, rem_block, rem_buf, False)
            end_turn_loss += loss

        hp_loss = self_loss + end_turn_loss
        survives = hp_loss < player_hp
        # Surviving a displayed DeathBlow ends combat (Giant removes itself after DeathBlow).
        clears = (
            (giant_deathblow and survives)
            or (guaranteed_alive == 0 and not revive and not giant_eruption)
        )
        return offense, end_turn_loss, hp_loss, survives, clears

    root_offense, root_end_loss, root_hp_loss, _, _ = evaluate_state(
        (0.0,) * size,
        (0.0,) * size,
        (0,) * size,
        start_block,
        0,
        (0,) * size,
        start_intangible,
        start_buffer,
        0.0,
    )
    block_weight = w.block * (1.0 + min(2.0, root_end_loss / max(1, player_hp)))

    def board_value(offense, end_loss):
        return offense + block_weight * (root_end_loss - end_loss)

    root_board = board_value(root_offense, root_end_loss)

    def line_quality(hand, first_idx):
        offense, end_loss, hp_loss, survives, clears = evaluate_state(
            hand.damage,
            hand.guaranteed_damage,
            hand.poison,
            hand.block,
            hand.weak,
            hand.str_drop,
            hand.intangible,
            hand.buffer,
            hand.self_hp_loss,
        )
        utility = board_value(offense, end_loss) + hand.extra
        if clears:
            utility += 35.0
        if survives:
            return (
                1,
                int(clears),
                -hand.potions_used if clears else 0,
                utility,
                scores[first_idx],
                -first_idx,
                first_idx,
            )
        deficit = hp_loss - player_hp + 1.0
        return (
            0,
            int(hand.has_escape),
            -deficit,
            utility,
            scores[first_idx],
            -first_idx,
            first_idx,
        )

    moves = []
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
        name = item.get("id", "").split(".")[-1]
        is_x = bool(item.get("costs_x"))
        effective_cost = energy if is_x else cost
        indices = [i for i, e in enumerate(enemies) if e["index"] == a.args.get("target_index")]
        target = indices[0] if indices else None
        targets = [target] if target is not None else range(size)
        random_multi = (
            item.get("target_type") == "RandomEnemy" or name == "BOUNCING_FLASK"
        ) and size > 1
        is_attack = (not potion) and item.get("type") == "Attack"
        hits = _hits(item)
        if is_x and name in ("SKEWER", "VOLLEY", "STARDUST"):
            hits = energy

        d = [0.0] * size
        gd = [0.0] * size
        weak_order = [0] * size
        poison_apps = [() for _ in range(size)]
        str_drop = [() for _ in range(size)]
        debuffs = [0] * size

        for i in targets:
            raw_d = 0.0
            if potion and item.get("target_type") in ("AnyEnemy", "AllEnemies", "RandomEnemy"):
                raw_d = float(stats.get("damage", 0))
            elif is_attack:
                if is_x:
                    raw_d = float(stats.get("damage", 0) * hits) if hits > 0 else 0.0
                else:
                    raw_d = float(_damage(item, enemies[i]))
            if random_multi:
                d[i] = raw_d / size
                gd[i] = 0.0
            else:
                d[i] = raw_d
                gd[i] = raw_d

            if not random_multi:
                effects = debuff_order(item, stats, enemies[i], energy=energy)
                if item.get("id") == "CARD.EXPOSE":
                    debuffs[i] = len(effects) + shields[i]
                else:
                    debuffs[i] = len(effects)
                if not e_weak[i]:
                    weak_order[i] = next(
                        (n for n, (kind, _) in enumerate(effects, 1) if kind == "weak"), 0
                    )
                poison_apps[i] = tuple(
                    (n, amount) for n, (kind, amount) in enumerate(effects, 1) if kind == "poison"
                )
                str_drop[i] = tuple(
                    (n, amount)
                    for n, (kind, amount) in enumerate(effects, 1)
                    if kind == "strength_loss"
                )

        card_block = float(block_preview(stats))
        is_fortifier = potion and name == "FORTIFIER"
        afterimage_gain = int(stats.get("afterimagepower", 0)) if not potion else 0
        intangible_gain = (
            int(stats.get("intangiblepower", 1)) if name in ("WRAITH_FORM", "GHOST_IN_A_JAR") else 0
        )
        buffer_gain = int(stats.get("bufferpower", 0))
        self_loss = float(stats.get("hploss", 0))
        foul_damage = float(stats.get("damage", 0)) if potion and name == "FOUL_POTION" else 0.0
        e_gain = int(stats.get("energy", 0)) if potion and name == "ENERGY_POTION" else 0
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

        # Single-step delta from root so residual reconstructs intrinsic with zero double-counting.
        step_gd = [0.0] * size
        step_weak = 0
        step_poison = [0] * size
        step_str = [0] * size
        step_block = start_block + (2.0 * start_block if is_fortifier else card_block)
        if not potion:
            step_block += start_afterimage
        step_buf = start_buffer + buffer_gain
        step_int = start_intangible + intangible_gain
        step_self = self_loss
        for i in range(size):
            if gd[i] > 0:
                eb = 0.0 if clears_block else e_block[i]
                hp_dmg, _, _, _ = _resolve_attack_hits(
                    gd[i], max(1, hits) if is_attack else 1, eb, e_buffer[i], e_slippery[i], e_hard_cap[i], e_intangible[i]
                )
                step_gd[i] = hp_dmg
                if is_attack:
                    for _ in range(max(1, hits)):
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
            if not req_poison or e_poison[i] > 0:
                step_poison[i] = sum(amt for order, amt in poison_apps[i] if order > rem)
            step_str[i] = sum(amt for order, amt in str_drop[i] if order > rem)
        if foul_damage > 0:
            loss, step_block, step_buf = _apply_hit_damage(
                foul_damage, step_block, step_buf, step_int > 0
            )
            step_self += loss

        s_off, s_end_loss, _, _, _ = evaluate_state(
            tuple(d),
            tuple(step_gd),
            tuple(step_poison),
            step_block,
            step_weak,
            tuple(step_str),
            step_int,
            step_buf,
            step_self,
        )
        step_delta = board_value(s_off, s_end_loss) - root_board
        intrinsic = scores[j] * max(1, effective_cost) ** cost_exp
        if e_gain > 0:
            intrinsic -= e_gain * min(7.0, max(0.0, (len(cards) - energy - 1) * 2.5))
        residual = intrinsic - step_delta
        moves.append(
            _SurvivalMove(
                j,
                1 << source,
                name,
                effective_cost,
                is_x,
                e_gain,
                target,
                is_attack,
                max(1, hits) if is_attack else 1,
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
            )
        )

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
    )
    end_quality = line_quality(start, end)
    best_overall = end_quality
    best_by_first = {end: end_quality}

    beam = [start]
    for step_idx in range(depth):
        next_hands = {}
        for hand in beam:
            if hand.stopped:
                continue
            for m in moves:
                if step_idx == 0 and forced_first is not None and m.action_index != forced_first:
                    continue
                if hand.used & m.source:
                    continue
                if m.x_cost:
                    if hand.energy != energy:
                        continue
                    next_energy = 0
                else:
                    if hand.energy < m.cost:
                        continue
                    next_energy = hand.energy - m.cost + m.energy_gain
                if m.target is not None and hand.damage[m.target] >= e_total[m.target]:
                    continue

                prior_cards = (card_mask & hand.used).bit_count() if tender else 0
                damage_deltas = list(m.damage)
                gd_deltas = list(m.guaranteed_damage)
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

                # Block: Fortifier doubles current projected Block; Tender reduces card Block BEFORE After Image.
                cur_block = hand.block
                if m.is_fortifier:
                    cur_block += 2.0 * cur_block
                else:
                    c_blk = max(0.0, m.card_block - prior_cards) if (tender and prior_cards and m.tender_block) else m.card_block
                    cur_block += c_blk
                if not m.potion:
                    cur_block += hand.afterimage
                cur_afterimage = hand.afterimage + m.afterimage_gain
                cur_int = hand.intangible + m.intangible
                cur_buf = hand.buffer + m.buffer
                cur_self = hand.self_hp_loss + m.self_hp_loss

                new_eblock = list(hand.enemy_block)
                new_ebuf = list(hand.enemy_buffer)
                new_eslip = list(hand.enemy_slippery)
                new_gd = list(hand.guaranteed_damage)
                weak = hand.weak
                poison = list(hand.poison)
                str_drop = list(hand.str_drop)
                new_artifact = list(hand.artifact)

                for i in range(size):
                    if m.clears_block and (m.target is None or m.target == i):
                        new_eblock[i] = 0.0
                    if gd_deltas[i] > 0:
                        pre_eb = new_eblock[i]
                        hp_dmg, eb_after, ebuf_after, eslip_after = _resolve_attack_hits(
                            gd_deltas[i],
                            m.hits,
                            new_eblock[i],
                            new_ebuf[i],
                            new_eslip[i],
                            e_hard_cap[i],
                            e_intangible[i],
                        )
                        new_gd[i] = min(float(e_hp[i]), new_gd[i] + hp_dmg)
                        new_eblock[i] = eb_after
                        new_ebuf[i] = ebuf_after
                        new_eslip[i] = eslip_after
                        if m.is_attack:
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
                )
                quality = line_quality(projection, first)
                if quality > best_overall:
                    best_overall = quality
                prev_first = best_by_first.get(first)
                if prev_first is None or quality > prev_first:
                    best_by_first[first] = quality

                if quality[0] == 1 and quality[1] == 1:
                    continue
                if projection.stopped:
                    continue
                key = (
                    projection.used,
                    projection.energy,
                    projection.damage,
                    projection.poison,
                    projection.block,
                    projection.weak,
                    projection.intangible,
                    projection.buffer,
                    projection.afterimage,
                    artifact_t,
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
    return best_overall, best_by_first


def choose_turn_survival(state, policy, proposed, *, width=8, depth=5):
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

    self_risk = 0.0
    if proposed.kind == "play_card":
        card = next((c for c in state["hand"] if c["index"] == proposed.args["card_index"]), {})
        self_risk += float((card.get("stats") or {}).get("hploss", 0))
        if card.get("type") == "Attack":
            hits = max(1, _hits(card))
            target_idx = proposed.args.get("target_index")
            affected = [e for e in enemies if e["index"] == target_idx] if target_idx is not None else enemies
            for e in affected:
                thorns = max(0, _power(e.get("powers"), "THORNS"))
                if thorns > 0:
                    self_risk += hits * (1.0 if intangible else float(thorns))
                if _power(e.get("powers"), "REFLECT") > 0 and e.get("block", 0) > 0:
                    self_risk += 1.0 if intangible else float(e.get("block", 0))
    elif proposed.kind == "use_potion":
        pot = next(
            (p for p in player["potions"] if p["index"] == proposed.args["potion_index"]), {}
        )
        if pot.get("id") == "POTION.FOUL_POTION":
            self_risk += 1.0 if intangible else float((pot.get("vars") or {}).get("Damage", 0))

    # Resolve worst-case End Turn damage (Burns + enemy hits) in order against Block + Plating + Buffer.
    rem_block = start_block + plating
    rem_buf = buf_stacks
    end_loss = 0.0
    for bh in _hand_burn_hits(state["hand"], intangible):
        loss, rem_block, rem_buf = _apply_hit_damage(bh, rem_block, rem_buf, intangible)
        end_loss += loss
    if not (giant and giant.eruption_forced):
        all_hits = []
        for e in enemies:
            p_loss = _poison_tick_loss(
                max(0, _power(e.get("powers"), "POISON")),
                accelerant,
                _power(e.get("powers"), "INTANGIBLE") > 0,
            )
            if p_loss >= e["hp"] and not giant_eruption:
                continue
            inc = incoming(e)
            if inc > 0:
                all_hits.extend(_enemy_attack_hits_list(inc, attack_hits(e), False, False, 0, intangible))
        for eh in sorted(all_hits, reverse=True):
            loss, rem_block, rem_buf = _apply_hit_damage(eh, rem_block, rem_buf, False)
            end_loss += loss

    if end_loss + self_risk < player["hp"]:
        return proposed

    proposed_idx = next((i for i, a in enumerate(actions) if a == proposed), None)
    best_overall, best_by_first = _search_survival_lines(
        state, policy, actions, width=width, depth=depth
    )
    best_proposed = best_by_first.get(proposed_idx) if proposed_idx is not None else None
    # Before overriding a proposal, run a dedicated forced-first pass in case width pruning dropped its continuation.
    if proposed_idx is not None and (best_proposed is None or best_proposed[:3] < best_overall[:3]):
        _, forced = _search_survival_lines(
            state, policy, actions, width=width, depth=depth, forced_first=proposed_idx
        )
        if proposed_idx in forced and (best_proposed is None or forced[proposed_idx] > best_proposed):
            best_proposed = forced[proposed_idx]
    if best_proposed is None:
        return actions[best_overall[-1]]
    if best_proposed[0] == 1 and best_proposed[:3] >= best_overall[:3]:
        return proposed
    if best_proposed[0] == 0 and best_overall[0] == 0 and best_proposed[:3] >= best_overall[:3]:
        return proposed
    return actions[best_overall[-1]]
