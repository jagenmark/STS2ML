"""Kaiser search decisions and the units of their public successor scores."""
from dataclasses import replace

import pytest

from sts2rl.combat_search_v2 import planner
from sts2rl.combat_search_v2.kaiser_future import future_defense
from sts2rl.combat_search_v2.state import END_TURN, Intent, Move, Relic, project, set_power
from sts2rl.combat_search_v2.transitions import advance, legal
from sts2rl.combat_search_v2.value import interim
from test_combat_search_v2 import STRIKE, card, enemy, powers, view


def fight(hand=STRIKE, *, turn=1, chip=0, armor=0, block=50):
    crusher = enemy("CRUSHER", hp=200 - chip, hit=14, block=armor)
    crusher["max_hp"] = 200
    rocket = enemy("ROCKET", hp=200, hit=6, block=armor)
    if turn == 3:
        crusher["intents"] = [{"type": "Attack", "damage": 7, "hits": 2}, {"type": "Debuff"}]
        rocket["intents"] = [{"type": "Buff"}]
    board = view(hand, block=block, enemies=[crusher, rocket], power=powers(SURROUNDED=1))
    board["context"].update(act=2, room_type="Boss")
    board["round"] = turn
    p = project(board)
    return replace(p, state=replace(p.state, late=True, v61_rules=True, kaiser_v63=True,
                                    kaiser_v63b=True, facing=0, preview_facing=0))


def choose(p, treatment=True):
    config = planner.Config(width=2, v61_boss_safe=True, kaiser_v63=True, kaiser_v63b=treatment)
    result = planner.search(p, legal(p.state), END_TURN, config)
    assert not result.fallback and result.line.state.outcome == "completed"
    return result


def test_free_turn_is_visible_to_narrow_beam_and_completed_leaf():
    p = fight(armor=90)
    left, right = (advance(p.state, Move("play_card", 0, target)) for target in (0, 1))
    assert all(e.hp == 200 for e in (*left.enemies, *right.enemies))
    assert all(a > b for a, b in zip(interim(right, 7, boss_safe=True), interim(left, 7, boss_safe=True)))
    assert choose(p, False).line.state.facing == 0
    line = choose(p).line
    assert line.state.facing == 1 and line.state.hp == p.state.hp
    # With insufficient Block turning around exposes Thrash from behind now.
    assert choose(fight(armor=90, block=20)).line.state.facing == 0


def test_weak_tracks_successors_strength_and_paper_krane():
    p = fight(card("LEG_SWEEP", 2, target="AnyEnemy", upgrade=1), turn=3)
    assert choose(p).choice == Move("play_card", 0, 1)
    leaf = advance(p.state, END_TURN)
    assert leaf.outcome == "completed"
    for idx, strength, saved in [(0, 0, 0), (1, 3, 38 * 1.5)]:
        arm = leaf.enemies[idx]
        weak = replace(arm, powers=set_power(arm.powers, "WEAK", 1))
        assert dict(arm.powers).get("STRENGTH", 0) == strength
        weakened = list(leaf.enemies)
        weakened[idx] = weak
        for relic, rate in [((), .25), ((Relic("PAPER_KRANE", None, False),), .4),
                            ((Relic("PAPER_KRANE", None, True),), .25)]:
            board = replace(leaf, relics=relic)
            assert (future_defense(replace(board, enemies=tuple(weakened)))
                    - future_defense(board)) == pytest.approx(saved * rate)
    crusher, rocket = leaf.enemies
    two = replace(crusher, powers=set_power(crusher.powers, "WEAK", 2))
    # Adapt adds three Strength before the discounted 14-damage Guarded Strike.
    assert future_defense(replace(leaf, enemies=(two, rocket))) - future_defense(leaf) == .5 * .25 * 17


def test_focus_survives_early_chip_and_switches_for_a_near_kill():
    # Disable facing to isolate concentration from future rear exposure.
    p = fight(chip=15)
    p = replace(p, state=replace(p.state, powers=()))
    assert choose(p, False).choice.target == 0
    assert choose(p).choice.target == 1
    crusher, rocket = p.state.enemies
    near = replace(p, state=replace(p.state, enemies=(replace(crusher, hp=15), rocket)))
    assert choose(near).choice.target == 0


def test_turns_back_to_crusher_before_recharge_and_values_delayed_laser():
    p = fight(armor=90, block=70)
    crusher, rocket = p.state.enemies
    crusher = replace(crusher, intents=(Intent("Buff"),))
    rocket = replace(rocket, intents=(Intent("Attack", 38),), powers=(("STRENGTH", 3),), preview_strength=3)
    p = replace(p, state=replace(p.state, round=4, facing=1, preview_facing=1, enemies=(crusher, rocket)))
    assert choose(p, False).line.state.facing == 1
    assert choose(p).line.state.facing == 0

    # Precision Beam -> Charge Up -> Laser. One remaining Weak expires on the
    # buff. A second stack covers the later 35+3 head-on hit.
    p = fight()
    crusher, rocket = p.state.enemies
    crusher = replace(crusher, intents=(Intent("Attack", 6),))
    rocket = replace(rocket, intents=(Intent("Attack", 20),))
    leaf = advance(replace(p.state, round=2, facing=1, preview_facing=1, enemies=(crusher, rocket)), END_TURN)
    crusher, rocket = leaf.enemies
    one = replace(rocket, powers=(("WEAK", 1),))
    two = replace(rocket, powers=(("WEAK", 2),))
    assert future_defense(replace(leaf, enemies=(crusher, one))) == future_defense(leaf)
    assert future_defense(replace(leaf, enemies=(crusher, two))) - future_defense(leaf) == .5 * .25 * 38
