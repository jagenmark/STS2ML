"""One opt-in sampled player turn beyond a certified one-turn frontier."""
from collections import Counter
from dataclasses import replace
from hashlib import blake2b
from time import perf_counter_ns

from . import late_encounters
from .next_intent import COVERED, next_intent
from .state import HAND_CAP, Card, power
from .transitions import PASSIVE_RELICS, card_supported, legal
from .value import SURVIVED, VICTORY


# Only fixed-cost variants whose cost survives the hand/pile transition. Excludes
# X, Confused, Pinpoint, Enlightenment, escalating Escape and draw triggers (Void).
_FIXED = {
    0: {"DEFLECT", "NEUTRALIZE", "SLICE", "SHIV", "BACKSTAB", "ADRENALINE", "DAZED", "WOUND"},
    1: {"STRIKE_SILENT", "DEFEND_SILENT", "DEADLY_POISON", "POISONED_STAB", "DAGGER_SPRAY",
        "SURVIVOR", "BLADE_DANCE", "CLOAK_AND_DAGGER", "BACKFLIP", "BLUR", "FOOTWORK", "AFTERIMAGE",
        "NOXIOUS_FUMES", "ACCURACY", "BECKON", "DAGGER_THROW", "LEADING_STRIKE", "INFINITE_BLADES",
        "PHANTOM_BLADES", "SUCKER_PUNCH", "SNAKEBITE", "ACCELERANT", "ACROBATICS"},
    2: {"DASH", "LEG_SWEEP", "PREDATOR", "SNAKEBITE", "ACCELERANT"},
}
# Start triggers not qualified by this extension are left with the control.
_RELICS = PASSIVE_RELICS | {"RING_OF_THE_SNAKE", "RUNIC_PYRAMID", "ICE_CREAM", "HORN_CLEAT",
                            "CAPTAINS_WHEEL", "ANCHOR", "PAPER_KRANE", "BAG_OF_PREPARATION",
                            "LANTERN", "STRAWBERRY", "PEAR", "MANGO"}
_BLOCKED_POWERS = {"CONFUSED", "BARRICADE", "CHAINS_OF_BINDING", "TOOLS_OF_THE_TRADE", "NIGHTMARE",
                   "GIGANTIFICATION", "WELL_LAID_PLANS", "PHANTOM_BLADES"}


def _identity(v):
    # Pile stats are native UI previews and are absent on cards just discarded.
    return (v.name, v.upgrade, v.kind, v.target, v.cost, v.keywords, v.flags, v.modifier)


def public_key(root):
    fields = (root.round, root.hp, root.block, root.energy, root.powers,
              tuple((e.name, e.hp, e.block, e.powers, e.intents) for e in root.enemies),
              tuple(_identity(c.variant) for c in root.hand),
              tuple(sorted(_identity(v) for v in root.draw)), tuple(sorted(_identity(v) for v in root.discard)))
    return blake2b(repr(fields).encode(), digest_size=16).digest()


def _deal(pile, count, key):
    copies = Counter()
    ranked = []
    for v in sorted(pile):
        identity = _identity(v)
        ordinal = copies[identity]
        copies[identity] += 1
        priority = blake2b(repr((identity, ordinal)).encode(), key=key, digest_size=16).digest()
        ranked.append((priority, v))
    ranked.sort()
    return [v for _, v in ranked[:count]], tuple(sorted(v for _, v in ranked[count:]))


def sample_hand(state, root_key, index):
    """Independent per-world priority permutation, shared between candidate lines."""
    count = state.boundary.count
    key = root_key + bytes([index])
    drawn, remaining = _deal(state.draw, count, key + b'D')
    discard = state.discard
    if count > len(drawn):
        extra, remaining = _deal(discard, count - len(drawn), key + b'R')
        drawn.extend(extra)
        discard = ()
    cards = tuple(Card(state.next_slot + i, replace(v, stats=())) for i, v in enumerate(drawn))
    return replace(state, hand=state.hand + cards, next_slot=state.next_slot + len(cards),
                   draw=remaining, discard=discard, boundary=None, outcome="")


def prepare(state):
    if (state.outcome != "completed" or state.boundary is None or state.boundary.reason != "next turn"
            or state.queue or state.prompt or state.play):
        return None, "turn boundary"
    if not 0 <= state.boundary.count <= min(HAND_CAP - len(state.hand), len(state.draw) + len(state.discard)):
        return None, "draw count"
    for relic in state.relics:
        if relic.name not in _RELICS:
            return None, f"start trigger/relic {relic.name}"
    for name, _ in state.powers:
        if name in _BLOCKED_POWERS or (name == "INFINITE_BLADES" and not state.late):
            return None, f"start trigger/power {name}"
    for v in (*state.draw, *state.discard, *(c.variant for c in state.hand)):
        if (not card_supported(v, state.late) or v.name not in _FIXED.get(v.cost, ()) or v.modifier
                or any(f != "retain_this_turn" or "Retain" not in v.keywords for f in v.flags)
                or v.name in late_encounters.CARDS and not state.late):
            return None, f"card or cost/{v.name} (cost {v.cost})"
    enemies = []
    for e in state.enemies:
        intents = next_intent(state, e) if e.hp else ()
        if intents is None:
            return None, "intent"
        enemies.append(replace(e, intents=intents, preview_strength=power(e.powers, "STRENGTH"),
                               preview_weak=power(e.powers, "WEAK") > 0, attack_delta=0))
    return replace(state, enemies=tuple(enemies), preview_vulnerable=power(state.powers, "VULNERABLE") > 0,
                   preview_intangible=power(state.powers, "INTANGIBLE") > 0, preview_facing=state.facing,
                   bound_used=False, tender_plays=0), ""


def _world_score(worlds):
    # Compare utility only between candidates with the same outcome counts.
    n = len(worlds)
    return (sum(category >= SURVIVED for category, _ in worlds) / n,
            sum(category == VICTORY for category, _ in worlds) / n,
            sum(value for _, value in worlds) / n)


def rerank(root, first, control):
    from .planner import _Search

    lines = sorted((line for line in first.certified if line), key=first.key, reverse=True)
    if control.fallback or not lines or lines[0].score[0] == VICTORY:
        return control
    candidates = []
    for line in lines:
        if line.score[0] == SURVIVED and all(line.state != prior.state for prior in candidates):
            candidates.append(line)
            if len(candidates) == 2:
                break
    if len(candidates) != 2:
        return control
    info = {"eligible": True, "active": False}

    def skip(reason):
        gate, _, detail = reason.partition("/")
        return replace(control, pilot={**info, "reason": gate, **({"detail": detail} if detail else {})})

    if any(e.name not in COVERED for e in root.enemies if e.hp):
        return skip("formation")
    starts = []
    for line in candidates:
        state, reason = prepare(line.state)
        if reason:
            return skip(reason)
        starts.append(state)
    key = public_key(root)
    config = replace(first.config, width=6, children=96, depth=8, two_turn_pilot=False)
    scores = []
    details = []
    search_ns = 0
    attempts = 0
    for line, state in zip(candidates, starts, strict=True):
        worlds = []
        for i in range(4):
            sampled = sample_hand(state, key, i)
            moves = legal(sampled)
            # End Turn is always legal. Tie priority is deterministic in imagined worlds.
            search = _Search(moves, len(moves) - 1, config, None, False, first.boss_safe, first.curse_preferences)
            started = perf_counter_ns() if first.record_timing else 0
            search.run(sampled)
            if started:
                search_ns += perf_counter_ns() - started
            attempts += search.attempts
            best = max((v for v in search.certified if v), key=search.key, default=None)
            if best is None or (best.score[0] < SURVIVED and any(v is None for v in search.certified)):
                return skip("uncertified sampled world")
            worlds.append(best.score)
        scores.append(_world_score(worlds))
        if first.record_timing:
            details.append({"root": line.root, "one_turn": line.score, "two_turn": scores[-1], "worlds": worlds,
                            "hp": state.hp, "enemy_hp": [e.hp for e in state.enemies],
                            "pressure": sum((i.damage or 0) * i.hits for e in state.enemies for i in e.intents)})
    winner = candidates[int(scores[1] > scores[0])]
    choice = first.root_moves[winner.root]
    return replace(control, choice=choice, line=winner, pilot={**info, "active": True,
                   "changed": choice != control.choice, "scores": tuple(scores), "control": control.choice,
                   "world_search_ns": search_ns, "world_attempts": attempts, "candidates": details})
