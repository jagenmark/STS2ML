from collections import Counter
from dataclasses import replace
import gzip
import json
from pathlib import Path

import pytest

from sts2rl.combat_search_v2 import two_turn
from sts2rl.combat_search_v2.planner import Config, Line, Result, _Search
from sts2rl.combat_search_v2.state import Boundary, Card, END_TURN, Enemy, Intent, Move, State, Variant
from sts2rl.combat_search_v2.value import DEAD, SURVIVED, VICTORY


def card(name, cost=1):
    return Variant(name, "Skill", cost, "Self")


def completed(**changes):
    enemy = Enemy(0, "SHRINKER_BEETLE", 30, 45, 0, (), (Intent("DebuffStrong"),), 0, False)
    state = State(23, 70, 4, 4, 3, 2, 1, "Monster", (), (enemy,), (),
                  boundary=Boundary("next turn", 5), outcome="completed")
    return replace(state, **changes)


def test_crn_order_invariance_reshuffle_and_multiset_conservation():
    a, b, c = card("DEFEND_SILENT"), card("BLUR"), card("BACKFLIP")
    state = completed(draw=(c, a), discard=(a, b, c, a, b, b), hand=(Card(0, b),), next_slot=4, spent=1)
    shuffled = replace(state, draw=state.draw[::-1], discard=state.discard[::-1])
    key = two_turn.public_key(state)
    assert key == two_turn.public_key(shuffled)
    for index in range(4):
        hand = two_turn.sample_hand(state, key, index)
        assert hand == two_turn.sample_hand(shuffled, key, index)
        assert (hand.hp, hand.block, hand.energy, hand.spent) == (23, 4, 4, 1)
        assert hand.hand[0] == state.hand[0]
        assert [c.slot for c in hand.hand] == [0, 4, 5, 6, 7, 8]
        assert Counter(c.variant for c in hand.hand[1:3]) == Counter(state.draw)
        assert Counter(c.variant for c in hand.hand[3:]) + Counter(hand.draw) == Counter(state.discard)
        assert not hand.discard and len(hand.draw) == 3
        # Adding one copy can displace at most one previously selected card.
        changed = two_turn.sample_hand(replace(state, discard=(*state.discard, c)), key, index)
        overlap = Counter(c.variant for c in hand.hand) & Counter(c.variant for c in changed.hand)
        assert overlap.total() >= len(hand.hand) - 1


def test_no_reshuffle_until_draw_is_exhausted():
    state = completed(draw=(card("BLUR"),) * 5, discard=(card("BACKFLIP"),))
    world = two_turn.sample_hand(state, b"root", 0)
    assert len(world.hand) == 5 and world.draw == () and world.discard == state.discard


def test_forecast_resets_preview_anchors_and_rejects_unknown_draws():
    state = completed(draw=(card("DEFEND_SILENT"),) * 5, powers=(("INTANGIBLE", 1), ("VULNERABLE", 2)))
    enemy = replace(state.enemies[0], powers=(("STRENGTH", 2), ("WEAK", 1)), attack_delta=8)
    state = replace(state, enemies=(enemy,))
    fresh, reason = two_turn.prepare(state)
    assert not reason
    assert fresh.enemies[0].intents == (Intent("Attack", 1),)
    assert fresh.enemies[0].preview_strength == 2 and fresh.enemies[0].preview_weak
    assert fresh.enemies[0].attack_delta == 0 and fresh.preview_vulnerable and fresh.preview_intangible
    for bad in (replace(state, draw=(card("UNKNOWN"),) * 5), replace(state, discard=(card("PINPOINT"),)),
                replace(state, discard=(card("VOID"),)), replace(state, powers=(("CONFUSED", 1),)),
                replace(state, powers=(("BARRICADE", 1),)),
                replace(state, enemies=(replace(enemy, name="UNVERIFIED"),))):
        assert two_turn.prepare(bad)[0] is None


def rerank_with_world_scores(monkeypatch, scores):
    first = _Search((Move("play_card", 0), END_TURN), 0, Config(), None, False, False, None)
    a = completed(draw=(card("DEFEND_SILENT"),) * 5)
    b = replace(a, hp=24, spent=1)
    lines = [Line(a, (first.root_moves[0],), (SURVIVED, 90), 0),
             Line(b, (END_TURN,), (SURVIVED, 80), 1)]
    first.certified = lines
    control = Result(first.root_moves[0], lines[0])
    observed = []
    outcomes = iter(scores)

    def result(search, world):
        observed.append(world.spent)
        line = Line(world, (END_TURN,), next(outcomes), 0)
        search.certified = [line] * len(search.root_moves)
        return Result(END_TURN, line)

    monkeypatch.setattr(_Search, "run", result)
    selected = two_turn.rerank(a, first, control)
    assert observed == [0] * 4 + [1] * 4
    return first, control, selected


def test_common_world_averages_and_immediate_victory_or_single_root(monkeypatch):
    worlds = [(SURVIVED, 1000), (DEAD, -3), (DEAD, -4), (DEAD, -5)] + [(SURVIVED, 8)] * 4
    first, control, selected = rerank_with_world_scores(monkeypatch, worlds)
    assert selected.choice == END_TURN and selected.pilot["scores"] == ((0.25, 0, 247), (1, 0, 8))
    lines = first.certified
    a = control.line.state
    for other in (None, replace(lines[1], state=a), replace(lines[1], score=(VICTORY, 0)),
                  replace(lines[1], score=(DEAD, -5))):
        first.certified = [lines[0], other]
        assert two_turn.rerank(a, first, control) is control


@pytest.mark.parametrize(("encounter", "index", "example", "control", "pilot"), [
    ("LAGAVULIN_MATRIARCH_BOSS", 1, 0, "DASH@3", "DEFLECT@2"),
    ("SOUL_FYSH_BOSS", 2, 0, "DASH@2", "DEFLECT@5"),
    ("SOUL_FYSH_BOSS", 2, 1, "DEADLY_POISON@2", "end_turn"),
    ("TUNNELER_WEAK", 7, 0, "POISONED_STAB@4", "BLUR@2"),
    ("SHRINKER_BEETLE_WEAK", 3, 0, "POISONED_STAB@2", "AFTERIMAGE@1"),
])
def test_recorded_four_world_victories(monkeypatch, encounter, index, example, control, pilot):
    receipts = Path(__file__).resolve().parents[1] / "docs/combat-search-v2/two-turn-pilot-receipts.jsonl.gz"
    with gzip.open(receipts) as stream:
        row = next(r for r in map(json.loads, stream) if r["pilot"] and r["encounter"] == encounter
                   and r["index"] == index)
    decision = row["examples"][example]
    assert (decision["control"], decision["pilot"]) == (control, pilot)
    win, ongoing = decision["candidates"]
    assert win["two_turn"] < ongoing["two_turn"]
    _, original, selected = rerank_with_world_scores(monkeypatch, win["worlds"] + ongoing["worlds"])
    a, b = selected.pilot["scores"]
    assert a[:2] == (1, 1) and b[:2] == (1, 0)
    assert selected.choice == original.choice


def test_mixed_worlds_prioritize_survival_then_kills_then_utility():
    score = two_turn._world_score
    win, live, dead = (VICTORY, 1), (SURVIVED, 500), (DEAD, 0)
    assert score([live] * 4) > score([win] * 3 + [dead])
    assert score([win, win, live, live]) > score([live, live, live, win])
    assert score([win, win, live, live]) == score([live, win, live, win])
    assert score([(VICTORY, 2), win, live, live]) > score([win, win, live, live])
