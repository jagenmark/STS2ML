"""Public transition differentials for the v6.6 all-act rules."""
from dataclasses import replace

import pytest

from sts2rl.combat_search_v2 import silent_cards
from sts2rl.combat_search_v2.integration import _difference, _native_legal, _normalized_legal
from sts2rl.combat_search_v2.state import project, root_move
from sts2rl.combat_search_v2.transitions import admission, advance, legal
from sts2rl.native import NativeSession, legal_actions
from test_combat_search_v2_native import HOST, ROOT, Oracle

pytestmark = pytest.mark.skipif(not HOST, reason="requires pinned v0.111.0 host")


def action(o, kind, name=None):
    return next(a for a in legal_actions(o.public) if a.kind == kind and (
        name is None or o.public["hand"][a.args["card_index"]]["id"] == "CARD." + name))


def check(o, a, *, expected_boundary=None):
    p = project(o.public, silent_cards_v66=True)
    assert not admission(p)
    assert _native_legal(p, legal_actions(o.public)) == legal(p.state)
    predicted = advance(p.state, root_move(p, a.kind, a.args))
    o.public = o.command(**a.command())
    if expected_boundary:
        assert not predicted.outcome and predicted.boundary.reason == expected_boundary
        return predicted
    assert not predicted.boundary or predicted.outcome == "completed", predicted.boundary
    if predicted.outcome == "victory":
        assert not o.public.get("in_combat")
        return predicted
    actual = project(o.public, silent_cards_v66=True)
    assert not _difference(predicted, actual.state), (predicted, actual.state)
    if not predicted.outcome:
        assert _normalized_legal(predicted) == _normalized_legal(actual.state)
        assert _native_legal(actual, legal_actions(o.public)) == legal(actual.state)
    return predicted


@pytest.mark.parametrize("name", sorted(silent_cards.WAVE | silent_cards.PROMOTED | {"TOOLS_OF_THE_TRADE"}))
@pytest.mark.parametrize("upgraded", (False, True), ids=("base", "upgraded"))
def test_act_one_card(tmp_path, name, upgraded):
    with NativeSession(ROOT, tmp_path / "engine", host_path=HOST) as game:
        o = Oracle(game)
        game.reset("CSV11FIX_" + name)
        o.command(cmd="set_player", hp=70, deck=[name])
        if upgraded:
            rest = o.command(cmd="enter_room", type="rest")
            o.command(**next(a for a in legal_actions(rest) if a.args["option_index"] == 1).command())
        o.public = o.command(cmd="enter_room", type="monster", encounter="WATERFALL_GIANT_BOSS")
        assert o.public["context"]["act"] == 1 and o.public["hand"][0]["upgrades"] == int(upgraded)
        check(o, action(o, "play_card", name))
        check(o, action(o, "end_turn"))


@pytest.mark.parametrize("name,follow", [
    ("BLADE_OF_INK", "SHIV"), ("SERPENT_FORM", "SLICE"), ("STRANGLE", "SLICE"),
    ("SHADOWMELD", "DEFEND_SILENT"), ("ENVENOM", "SLICE"), ("TRACKING", "SLICE"),
    ("POUNCE", "DEFEND_SILENT"), ("BULLET_TIME", "DEFEND_SILENT"),
    ("ABRASIVE", "DEFLECT"), ("STORM_OF_STEEL", "SHIV"),
])
def test_followup(tmp_path, name, follow):
    with NativeSession(ROOT, tmp_path / "engine", host_path=HOST) as game:
        o = Oracle(game)
        deck = [name, "DEFEND_SILENT" if follow == "SHIV" else follow]
        if name == "TRACKING":
            deck.append("NEUTRALIZE")
        o.start(name, deck, encounter="WATERFALL_GIANT_BOSS", seed="CSV11FIX_FOLLOW_" + name)
        if name == "TRACKING":
            check(o, action(o, "play_card", "NEUTRALIZE"))
        check(o, action(o, "play_card", name))
        check(o, action(o, "play_card", follow))


def test_tools_prompt_and_discard(tmp_path):
    with NativeSession(ROOT, tmp_path / "engine", host_path=HOST) as game:
        o = Oracle(game)
        o.start("TOOLS", ["TOOLS_OF_THE_TRADE"] * 8, encounter="WATERFALL_GIANT_BOSS", seed="CSV11FIX_TOOLS_PROMPT")
        check(o, action(o, "play_card"))
        end = check(o, action(o, "end_turn"))
        assert end.outcome == "completed" and end.boundary.count == len(o.public["cards"]) == 6
        check(o, action(o, "select_cards"))


@pytest.mark.parametrize("name", ["RICOCHET", "SERPENT_FORM", "ESCAPE_PLAN"])
def test_random_subcase_admits_root(tmp_path, name):
    with NativeSession(ROOT, tmp_path / "engine", host_path=HOST) as game:
        o = Oracle(game)
        o.start(name, [name] * 4 + ["SLICE"] * 4, encounter="NIBBITS_NORMAL", seed="CSV11FIX_RANDOM_" + name)
        if name == "SERPENT_FORM":
            check(o, action(o, "play_card", name))
        a = action(o, "play_card", "SLICE" if name == "SERPENT_FORM" else name)
        result = check(o, a, expected_boundary="draw" if name == "ESCAPE_PLAN" else
                       ("serpent form random target" if name == "SERPENT_FORM" else "ricochet random target"))
        assert not replace(result, boundary=None).outcome
