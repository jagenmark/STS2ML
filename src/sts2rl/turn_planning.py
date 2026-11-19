"""Bounded search over cards and targets visible in the current hand.

Future draws are never expanded. The game executes just the first legal action
before the resulting public hand, costs and intents are scored again.
"""
from __future__ import annotations

from dataclasses import dataclass

from .combat_effects import block_preview, debuff_order
from .native import legal_actions
from .run_policy import _cost, _damage, _power
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


def choose_turn(state, policy, *, width=6, depth=5):
    actions = legal_actions(state)
    if state["decision"] != "combat_play" or len(actions) <= 2:
        return policy(state)
    scores = policy.combat_scores(state, actions)
    enemies = [e for e in state["enemies"] if e["hp"] > 0]
    size = len(enemies)
    if size == 0:
        return actions[max(range(len(actions)), key=scores.__getitem__)]
    hp = tuple(e["hp"] + e.get("block", 0) for e in enemies)
    intents = tuple(incoming(e) for e in enemies)
    w = policy.weights
    focus = tuple(1 + w.focus * (1 - e["hp"] / max(1, e["max_hp"])) if size > 1 else 1 for e in enemies)
    player = state["player"]
    starting_block = player["block"] + max(0, _power(state.get("player_powers"), "PLATING"))
    need = max(0, sum(intents) - starting_block)
    block_weight = w.block * (1 + min(2., need / max(1, player["hp"])))
    revive = any(_power(e.get("powers"), "ILLUSION") or _power(e.get("powers"), "INFESTED") for e in enemies)
    cards = {c["index"]: c for c in state["hand"]}
    potions = {p["index"]: p for p in player["potions"]}
    legacy = getattr(policy, "legacy_features", False)
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
                offense += 14
            else:
                alive += 1
                threat += intents[i] * (.75 if weak & (1 << i) else 1.)
        loss = max(0., threat - starting_block - block)
        value = offense + block_weight * (need - loss)
        if terminal:
            if not alive and not revive:
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
                          tuple(d), block, weak, tuple(weak_order), tuple(debuffs), residual))

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
