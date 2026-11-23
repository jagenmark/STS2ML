"""Room gates and boss utility using only the current public projection."""
from dataclasses import replace
from pathlib import Path

import pytest

from sts2rl.combat_search_v2.artifact import CombatValueModel
from sts2rl.combat_search_v2.planner import Config, search
from sts2rl.combat_search_v2.state import END_TURN, Boundary, project
from sts2rl.combat_search_v2.transitions import legal
from sts2rl.combat_search_v2.value import interim, leaf_value
from test_combat_search_v2 import DEFEND, STRIKE, card, enemy, powers, view


@pytest.mark.parametrize("act,room,v6,hallways,full", [
    (1, "Monster", False, False, False), (1, "Boss", False, False, False),
    (2, "Monster", False, True, True), (2, "Elite", False, True, True),
    (2, "Boss", True, False, True), (2, "Event", False, False, False), (3, "Boss", True, True, True),
])
def test_room_ablation(act, room, v6, hallways, full):
    assert not Config().late_root(act, room)
    assert Config(v6_late_coverage=True).late_root(act, room) == v6
    assert Config(v61_act2_hallways_act3=True).late_root(act, room) == hallways
    assert Config(v61_boss_safe=True).late_root(act, room) == full


@pytest.fixture(params=["heuristic", "schema3"])
def model(request):
    if request.param == "schema3":
        return CombatValueModel.load(Path(__file__).resolve().parents[1] /
                                     "releases/silent-a10-v2-tactics/challenger/combat_value_v2.npz")
    return None


def test_urgent_escape_beats_a_nonlethal_attack(model):
    public = view(STRIKE, card("FRANTIC_ESCAPE", kind="Status"), energy=1, enemies=[
        enemy("THE_INSATIABLE", hp=130, hit=10, power=powers(SANDPIT=2))])
    public["context"].update(act=2, room_type="Boss")
    p = project(public)
    moves = legal(p.state)
    result = search(p, moves, moves[0], Config(v61_boss_safe=True), model=model)
    assert not result.fallback and result.choice == moves[1]


def test_rage_penalty_prices_survivors_remaining_hp(model):
    p = project(view(DEFEND, enemies=[enemy("CRUSHER", hp=0), enemy("ROCKET", hp=130, power=powers(STRENGTH=6))]))
    s = replace(p.state, outcome="completed", boundary=Boundary("next turn", 1))
    weak = replace(s, enemies=(s.enemies[0], replace(s.enemies[1], hp=5)))
    def price(state):
        return leaf_value(state, 7, model)[1] - leaf_value(state, 7, model, boss_safe=True)[1]
    assert price(s) > price(weak) > 0
    assert price(replace(s, outcome="victory")) == 0


def test_sloth_reserves_a_play_for_the_visible_high_impact_card(model):
    p = project(view(card("DASH", cost=2, kind="Attack", target="AnyEnemy", keywords=["Retain"]),
                     DEFEND, power=powers(SLOTH=3)))
    state = replace(p.state, sloth_plays=2)
    assert interim(state, 7, boss_safe=True) > interim(replace(state, sloth_plays=3), 7, boss_safe=True)
    leaf = replace(state, outcome="completed", sloth_plays=0, boundary=Boundary("next turn"))
    assert leaf_value(leaf, 7, model, boss_safe=True) > leaf_value(leaf, 7, model)


def test_hallway_arm_keeps_frozen_boss_root():
    p = project(view(STRIKE, enemies=[enemy("KNOWLEDGE_DEMON")]))
    p = replace(p, state=replace(p.state, act=2, room="Boss"))
    assert search(p, legal(p.state), END_TURN, Config(v61_act2_hallways_act3=True)) == search(p, legal(p.state), END_TURN)
