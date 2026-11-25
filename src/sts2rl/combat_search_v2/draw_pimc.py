"""Opt-in PIMC (determinized draw-pile sampling) evaluator for mid-turn draw roots.

Strictly legal public-information search: samples realizations uniformly without
replacement from the known public `state.draw` multiset (reshuffling `state.discard`
when needed), resolves queued card effects/prompts, and runs a fast bounded mini-beam
to score draw roots instead of aborting as UNRESOLVED.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import random

from . import silent_cards
from .state import END_TURN, Card, power
from .transitions import _damage, _debuff, _drain, advance, block_gain, card_supported, legal
from .value import DEAD, SURVIVED, VICTORY, interim, leaf_value

_MINI_WIDTH = 4
_MINI_DEPTH = 5
_MINI_CHILDREN = 40
_PROMPT_CAP = 8


def _sample_rng(state, root_index: int, sample_index: int) -> random.Random:
    key = (
        state.act,
        state.floor,
        state.round,
        state.hp,
        state.block,
        state.energy,
        len(state.hand),
        len(state.draw),
        len(state.discard),
        root_index,
        sample_index,
    )
    seed = int.from_bytes(hashlib.blake2b(repr(key).encode(), digest_size=8).digest(), "little")
    return random.Random(seed)


def _apply_sampled_draw(state, count: int, rng: random.Random):
    """Realize `count` sampled draws from public draw/discard piles and drain the queue."""
    s = replace(state, boundary=None)
    escape_plan = s.play[-1] if (s.play and s.play[-1].name == "ESCAPE_PLAN") else None
    draw_pile = list(s.draw)
    discard_pile = list(s.discard)
    for _ in range(count):
        if not draw_pile:
            if not discard_pile:
                break
            draw_pile = discard_pile
            discard_pile = []
        idx = rng.randrange(len(draw_pile))
        card = draw_pile.pop(idx)
        drawn = replace(card, stats=())
        s = replace(
            s,
            hand=(*s.hand, Card(s.next_slot, drawn)),
            next_slot=s.next_slot + 1,
            draws_this_combat=s.draws_this_combat + 1 if s.draws_this_combat >= 0 else -1,
        )
        for enemy in s.enemies:
            if enemy.hp <= 0:
                continue
            if wave := power(s.powers, "CORROSIVE_WAVE"):
                s = _debuff(s, enemy.slot, "POISON", wave)
                if s.boundary:
                    return s
            if speed := power(s.powers, "SPEEDSTER"):
                s = _damage(s, enemy.slot, speed)
                if s.boundary or s.outcome:
                    return s
        if escape_plan is not None and drawn.kind == "Skill":
            s = replace(
                s,
                block=s.block
                + block_gain(3 + 2 * escape_plan.upgrade + silent_cards.nimble(escape_plan), s.powers),
            )
    s = replace(s, draw=tuple(sorted(draw_pile)), discard=tuple(sorted(discard_pile)))
    return _drain(s)


def _discard_priority(state, selection: tuple[int, ...]) -> tuple[int, int, int]:
    """Heuristic ordering to keep prompt branching small in the mini-beam."""
    by_slot = {c.slot: c.variant for c in state.hand}
    sly = 0
    junk = 0
    unplayable = 0
    for slot in selection:
        v = by_slot.get(slot)
        if v is None:
            continue
        if "Sly" in v.keywords or "sly_this_turn" in v.flags:
            sly += 1
        if v.kind in ("Curse", "Status") or v.name in ("STRIKE_SILENT", "DEFEND_SILENT"):
            junk += 1
        if v.cost > state.energy or v.cost < 0:
            unplayable += 1
    return (sly, junk, unplayable)


def _mini_moves(state):
    moves = legal(state)
    if state.prompt:
        if len(moves) <= _PROMPT_CAP:
            return moves
        return tuple(
            sorted(moves, key=lambda m: _discard_priority(state, m.selection), reverse=True)[:_PROMPT_CAP]
        )
    by_slot = {c.slot: c.variant for c in state.hand}
    out = []
    for m in moves:
        if m.kind == "use_potion":
            continue
        if m.kind == "play_card":
            v = by_slot.get(m.slot)
            if v is None or not card_supported(
                v,
                state.late,
                kaiser=state.kaiser_v63,
                silent_cards_v66=state.silent_cards_v66,
                silent_cards_v67=state.silent_cards_v67,
            ):
                continue
        out.append(m)
    return tuple(out)


def _mini_beam(start, config, model, boss_safe: bool):
    """Fast non-recursive bounded beam from a realized post-draw state."""
    if start.outcome:
        return leaf_value(
            start,
            config.potion_reserve,
            model,
            config.value_win_weight,
            boss_safe=boss_safe,
            power_leaf_v62=config.power_leaf_v62,
            value_v68=config.value_v68,
        )
    if start.boundary:
        return None

    best = None
    attempts = 0
    seen = set()

    def record_leaf(st):
        nonlocal best
        if not st.outcome:
            return
        sc = leaf_value(
            st,
            config.potion_reserve,
            model,
            config.value_win_weight,
            boss_safe=boss_safe,
            power_leaf_v62=config.power_leaf_v62,
            value_v68=config.value_v68,
        )
        if best is None or sc > best:
            best = sc

    def finish(st):
        nonlocal attempts
        if st.prompt is None and attempts < _MINI_CHILDREN:
            attempts += 1
            end = advance(st, END_TURN)
            if end.outcome:
                record_leaf(end)

    frontier = [start]
    finish(start)

    for _ in range(_MINI_DEPTH):
        if not frontier or attempts >= _MINI_CHILDREN:
            break
        nxt = []
        for st in frontier:
            if attempts >= _MINI_CHILDREN:
                break
            for m in _mini_moves(st):
                if m == END_TURN:
                    continue
                if attempts >= _MINI_CHILDREN:
                    break
                attempts += 1
                child = advance(st, m)
                if child.outcome:
                    record_leaf(child)
                    continue
                if child.boundary:
                    continue
                if child in seen:
                    continue
                seen.add(child)
                finish(child)
                pr = interim(
                    child,
                    config.potion_reserve,
                    boss_safe=boss_safe,
                    power_leaf_v62=config.power_leaf_v62,
                    value_v68=config.value_v68,
                )
                nxt.append((pr, child))
        if not nxt:
            break
        nxt.sort(key=lambda x: x[0], reverse=True)
        frontier = [c for _, c in nxt[:_MINI_WIDTH]]

    return best


def evaluate_draw_pimc(
    boundary_state,
    root_index: int,
    config,
    model,
    boss_safe: bool,
) -> tuple[int, float] | None:
    """Evaluate a root draw boundary via K deterministic samples from the public draw pile."""
    b = boundary_state.boundary
    if b is None or b.reason != "draw" or b.count <= 0:
        return None
    if not boundary_state.draw and not boundary_state.discard:
        return None

    k = max(2, int(config.pimc_samples))
    outcomes: list[tuple[int, float]] = []
    for sample_idx in range(k):
        rng = _sample_rng(boundary_state, root_index, sample_idx)
        realized = _apply_sampled_draw(boundary_state, b.count, rng)
        sc = _mini_beam(realized, config, model, boss_safe)
        if sc is not None and sc[0] in (DEAD, SURVIVED, VICTORY):
            outcomes.append(sc)

    if len(outcomes) < max(1, k // 2):
        return None

    n_dead = sum(cat == DEAD for cat, _ in outcomes)
    n_win = sum(cat == VICTORY for cat, _ in outcomes)
    mapped = []
    for cat, val in outcomes:
        if cat == VICTORY:
            mapped.append(val + 60.0)
        elif cat == DEAD:
            mapped.append(-float(boundary_state.max_hp) - 80.0)
        else:
            mapped.append(val)
    mean_val = sum(mapped) / len(mapped)

    if n_win == len(outcomes):
        eff_cat = VICTORY
    elif n_dead == 0:
        eff_cat = SURVIVED
    else:
        eff_cat = DEAD
    return eff_cat, round(mean_val, 8)
