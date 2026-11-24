"""Kaiser-only differentials against v0.111.0, including actual hidden draw permutations."""
from dataclasses import replace

import pytest

from sts2rl.combat_search_v2 import planner
from sts2rl.combat_search_v2.integration import CombatSearchV2, _difference
from sts2rl.combat_search_v2.state import END_TURN, project, root_move
from sts2rl.combat_search_v2.transitions import admission, advance, legal
from sts2rl.native import NativeSession, legal_actions
from test_combat_search_v2_native import HOST, ROOT, Oracle
from test_combat_search_v6_native import action, load_relics

pytestmark = pytest.mark.skipif(not HOST, reason="requires pinned v0.111.0 host")


def kaiser_public(view):
    view["context"].update(act=2, room_type="Boss", floor=16)
    return view


def projected(view, facing, **witness):
    p = project(kaiser_public(view), late_prompts=True)
    return replace(p, state=replace(p.state, late=True, v61_rules=True, kaiser_v63=True,
                                    facing=facing, preview_facing=facing, **witness))


def test_kaiser_rounded_preview_and_relics(tmp_path):
    with NativeSession(ROOT, tmp_path / "game", host_path=HOST) as host:
        o = Oracle(host)
        load_relics(o, tmp_path, {"GHOST_SEED", "CAULDRON"},
                    ["NEUTRALIZE"] * 14 + ["STRIKE_SILENT"] * 14, "KAISER_CRAB_BOSS")
        facing = 1
        order = sorted((c["id"].split(".")[-1] for c in o.public["draw_pile"]))
        o.command(cmd="set_draw_order", cards=order)
        o.public = o.command(**action(o, "end_turn").command())
        assert o.public["round"] == 2
        for target in (1, 0):
            p = projected(o.public, facing)
            assert not admission(p)
            play = next(a for a in legal_actions(o.public) if a.kind == "play_card" and
                        a.args.get("target_index") == target and
                        o.public["hand"][a.args["card_index"]]["id"] == "CARD.NEUTRALIZE")
            move = root_move(p, play.kind, play.args)
            predicted = advance(p.state, move)
            if target == 0:
                assert advance(replace(p.state, kaiser_v63=False), move).boundary.reason == "ambiguous attack preview"
            assert not predicted.boundary
            o.public = o.command(**play.command())
            assert not _difference(predicted, projected(o.public, target).state)
            facing = target
        p = projected(o.public, facing)
        predicted = advance(p.state, END_TURN)
        o.public = o.command(**action(o, "end_turn").command())
        assert predicted.outcome == "completed" and not _difference(predicted, projected(o.public, facing).state)


def test_kaiser_puzzle_witness_and_native_draw_order(tmp_path):
    results, hands = [], []
    for rev in (False, True):
        folder = tmp_path / str(rev)
        folder.mkdir()
        with NativeSession(ROOT, folder / "game", host_path=HOST) as host:
            o = Oracle(host)
            load_relics(o, folder, {"CENTENNIAL_PUZZLE"}, ["STRIKE_SILENT"] * 20 + ["DEFEND_SILENT"] * 20,
                        "KAISER_CRAB_BOSS")
            mode = CombatSearchV2(planner.Config(v61_boss_safe=True, kaiser_v63=True), record=True)
            public = kaiser_public(o.public)
            end = action(o, "end_turn")
            mode.choose(public, end, legal_actions, facing=1)
            assert not mode._decision[0].state.puzzle_triggered
            o.public = kaiser_public(o.command(**end.command()))
            mode.observe(end, o.public, legal_actions)
            assert mode.records[-1]["oracle"][1:] == ["unresolved", "centennial puzzle draw"]
            end = action(o, "end_turn")
            order = sorted((c["id"].split(".")[-1] for c in o.public["draw_pile"]), reverse=rev)
            o.command(cmd="set_draw_order", cards=order)
            mode.choose(o.public, end, legal_actions, facing=1)
            p = mode._decision[0]
            assert p.state.puzzle_triggered
            result = planner.search(p, legal(p.state), END_TURN, mode.config)
            results.append((result.choice, result.root_scores, result.fallback, result.attempts))
            after = kaiser_public(o.command(**end.command()))
            hands.append([c["id"] for c in after["hand"]])
            mode.observe(end, after, legal_actions)
            assert mode.records[-1]["oracle"][1:] == ["match", ""]
    assert results[0] == results[1] and hands[0] != hands[1]


def test_kaiser_remnant_witness(tmp_path):
    with NativeSession(ROOT, tmp_path / "game", host_path=HOST) as host:
        o = Oracle(host)
        load_relics(o, tmp_path, {"BEATING_REMNANT"}, ["DEFEND_SILENT"] * 20, "KAISER_CRAB_BOSS")
        p = projected(o.public, 1)
        assert admission(p) == "relic/BEATING_REMNANT"
        p = replace(p, state=replace(p.state, remnant_floor=p.state.hp - 20))
        assert not admission(p)
        predicted = advance(p.state, END_TURN)
        o.public = o.command(**action(o, "end_turn").command())
        assert predicted.hp == p.state.hp - 20 and predicted.outcome == "completed"
        assert not _difference(predicted, projected(o.public, 1).state)

@pytest.mark.parametrize("card", ("EXTERMINATE", "ENVENOM", "OUTBREAK"))
@pytest.mark.parametrize("upgraded", (False, True))
def test_kaiser_poison_and_area_cards(tmp_path, card, upgraded):
    with NativeSession(ROOT, tmp_path / "game", host_path=HOST) as host:
        o = Oracle(host)
        host.reset("CSV7FIX_POISON")
        o.command(cmd="set_player", deck=[card], hp=70)
        if upgraded:
            rest = o.command(cmd="enter_room", type="rest")
            o.command(**next(a for a in legal_actions(rest) if a.args["option_index"] == 1).command())
        o.public = o.command(cmd="enter_room", type="monster", encounter="KAISER_CRAB_BOSS")
        for kind in ("play_card", "end_turn"):
            p = projected(o.public, 1)
            assert not admission(p)
            chosen = action(o, kind)
            predicted = advance(p.state, root_move(p, kind, chosen.args))
            assert not predicted.boundary or predicted.outcome == "completed"
            o.public = o.command(**chosen.command())
            assert not _difference(predicted, projected(o.public, 1).state)
