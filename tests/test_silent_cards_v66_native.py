"""Public transition differentials for the v6.6 all-act rules."""
from dataclasses import replace
import gzip
import json
from pathlib import Path

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


def check(o, a, *, expected_boundary=None, continuation=None):
    p = project(o.public, silent_cards_v66=True)
    assert not admission(p)
    assert _native_legal(p, legal_actions(o.public)) == legal(p.state)
    move = root_move(p, a.kind, a.args)
    if continuation is not None and move.kind == "select_cards":
        indices = [p.state.prompt.candidates.index(slot) for slot in move.selection]
        move = replace(move, selection=tuple(continuation.prompt.candidates[i] for i in indices))
    predicted = advance(continuation or p.state, move)
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


LEGACY_POOL = set("""
ACCELERANT ACROBATICS ADRENALINE AFTERIMAGE ANTICIPATE BACKFLIP BACKSTAB BLADE_DANCE BLUR BUBBLE_BUBBLE
BURST CALCULATED_GAMBLE CLOAK_AND_DAGGER DAGGER_SPRAY DAGGER_THROW DASH DEADLY_POISON DEFEND_SILENT
DEFLECT FAN_OF_KNIVES FLECHETTES FLICK_FLACK FOOTWORK GRAND_FINALE HAZE LEADING_STRIKE LEG_SWEEP
MALAISE NEUTRALIZE NIGHTMARE NOXIOUS_FUMES POISONED_STAB PRECISE_CUT PREDATOR PREPARED REFLEX SKEWER
SLICE SNAKEBITE STRIKE_SILENT SUCKER_PUNCH SURVIVOR TACTICIAN TOOLS_OF_THE_TRADE WELL_LAID_PLANS
""".split())


@pytest.mark.parametrize("name", sorted(silent_cards.WAVE | silent_cards.PROMOTED | LEGACY_POOL))
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
        check(o, action(o, "play_card", name), expected_boundary="nightmare" if name == "NIGHTMARE" else None)
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


@pytest.mark.parametrize("on_top", [False, True])
def test_hidden_autoplay_precedes_enemy_resolution(tmp_path, on_top):
    from sts2rl.combat_search_v2.state import END_TURN

    fixture = json.loads(gzip.decompress((Path(__file__).parent / "fixtures/v65-unordered-autoplay.json.gz").read_bytes()))
    with NativeSession(ROOT, tmp_path / "engine", host_path=HOST) as game:
        public = game.reset(fixture["seed"])
        for cmd in fixture["history"]:
            public = game._request(cmd)
        p = project(public, silent_cards_v66=True)
        frozen = advance(p.state, END_TURN)
        assert frozen.boundary.reason == "I Am Invincible on unordered draw pile"
        assert replace(frozen, boundary=None) == p.state
        order = sorted((c["id"].split(".")[-1] for c in public["draw_pile"]),
                       key=lambda n: (n != "I_AM_INVINCIBLE", n), reverse=not on_top)
        game._request({"cmd": "set_draw_order", "cards": order})
        actual = game._request(legal_actions(public)[0].command())
        assert actual["player"]["hp"] == (49 if on_top else 43)


@pytest.mark.parametrize("name", ["RICOCHET", "SERPENT_FORM", "ESCAPE_PLAN"])
def test_random_subcase_admits_root(tmp_path, name):
    with NativeSession(ROOT, tmp_path / "engine", host_path=HOST) as game:
        o = Oracle(game)
        o.start(name, [name] * 8 + ["SLICE"] * 8, encounter="NIBBITS_NORMAL", seed="CSV11FIX_RANDOM_" + name)
        if name == "SERPENT_FORM":
            check(o, action(o, "play_card", name))
        a = action(o, "play_card", "SLICE" if name == "SERPENT_FORM" else name)
        result = check(o, a, expected_boundary="draw" if name == "ESCAPE_PLAN" else
                       ("serpent form random target" if name == "SERPENT_FORM" else "ricochet random target"))
        assert not replace(result, boundary=None).outcome


@pytest.mark.parametrize("name", ("EXPOSE", "PIERCING_WAIL"))
def test_artifact(tmp_path, name):
    with NativeSession(ROOT, tmp_path / "engine", host_path=HOST) as game:
        o = Oracle(game)
        o.start(name, [name], encounter="PUNCH_CONSTRUCT_NORMAL", seed="CSV11FIX_ARTIFACT")
        assert dict(o.simulated.enemies[0].powers)["ARTIFACT"] > 0
        check(o, action(o, "play_card"))
        check(o, action(o, "end_turn"))


@pytest.mark.parametrize("name,deck", [
    ("FINISHER", ["SLICE", "FINISHER"]),
    ("MEMENTO_MORI", ["SURVIVOR", "SLICE", "MEMENTO_MORI"]),
    ("KNIFE_TRAP", ["SHIV", "KNIFE_TRAP"]),
    ("PHANTOM_BLADES", ["PHANTOM_BLADES", "SHIV", "SHIV"]),
    ("SHADOW_STEP", ["SHADOW_STEP", "ABRASIVE"]),
    ("DODGE_AND_ROLL", ["FOOTWORK", "DODGE_AND_ROLL"]),
    ("ABRASIVE", ["ABRASIVE", "DEFEND_SILENT"]),
    ("HAND_TRICK", ["HAND_TRICK", "SURVIVOR", "DEFEND_SILENT"]),
])
def test_witnessed_triggers(tmp_path, name, deck):
    with NativeSession(ROOT, tmp_path / "engine", host_path=HOST) as game:
        o = Oracle(game)
        o.start(name, deck, encounter="WATERFALL_GIANT_BOSS", seed="CSV11FIX_TRIGGER_" + name)
        source = None
        for card in deck:
            if card == "SLICE" and name == "MEMENTO_MORI":
                a = next(a for a in legal_actions(o.public) if a.kind == "select_cards" and
                         o.public["cards"][int(a.args["indices"])]["id"] == "CARD.SLICE")
                check(o, a)
            elif name == "HAND_TRICK" and card == "SURVIVOR":
                p = project(o.public, silent_cards_v66=True)
                assert p.state.prompt.operation == name
                check(o, action(o, "select_cards"), continuation=source)
                break
            elif any(c["id"] == "CARD." + card and c["can_play"] for c in o.public.get("hand", ())):
                source = check(o, action(o, "play_card", card))
        if o.public["decision"] == "combat_play":
            check(o, action(o, "end_turn"))


@pytest.mark.parametrize("power_name", ["CORROSIVE_WAVE", "SPEEDSTER"])
def test_draw_power_known_card(tmp_path, power_name):
    with NativeSession(ROOT, tmp_path / "engine", host_path=HOST) as game:
        o = Oracle(game)
        o.start(power_name, [power_name, "ESCAPE_PLAN"] + ["DEFEND_SILENT"] * 6,
                encounter="WATERFALL_GIANT_BOSS", seed="CSV11FIX_DRAW_POWER")
        check(o, action(o, "play_card", power_name))
        before = project(o.public, silent_cards_v66=True).state
        assert [v.name for v in before.draw] == ["DEFEND_SILENT"]
        after = check(o, action(o, "play_card", "ESCAPE_PLAN"))
        assert after.block - before.block == 3


REGRESSIONS = json.loads(gzip.decompress((Path(__file__).parent /
                         "fixtures/v66-csv11-regressions.json.gz").read_bytes()))


@pytest.mark.parametrize("key", sorted(REGRESSIONS))
def test_csv11_original_commands(tmp_path, key):
    from sts2rl.combat_search_v2.integration import CombatSearchV2
    from sts2rl.combat_search_v2.planner import Config
    from sts2rl.native import digest

    fixture = REGRESSIONS[key]
    steps = {i: (before, after, card, reason) for i, before, after, card, reason in fixture["steps"]}
    mode = CombatSearchV2(Config(v61_boss_safe=True, v61_act2_hallways_act3=True, wax_fan_v64=True,
                                 kaiser_v63=True, silent_cards_v66=True), record=True)
    with NativeSession(ROOT, tmp_path / "engine", host_path=HOST, act_list=fixture["mode"]) as game:
        public = game.reset(fixture["seed"])
        for i, command in enumerate(fixture["history"]):
            if public["decision"] in ("combat_play", "card_select") and public.get("in_combat"):
                a = next(a for a in legal_actions(public) if a.command() == command)
                mode.choose(public, a, legal_actions)
            else:
                from sts2rl.native import Action
                a = Action("", command["action"], command["args"], "")
            if i in steps:
                assert digest(public) == steps[i][0]
            public = game._request(command)
            mode.observe(a, public, legal_actions)
            if i in steps:
                assert digest(public) == steps[i][1]
                verdict = mode.records[-1].get("oracle")
                assert verdict and verdict[0] == steps[i][2], mode.records[-1]
                assert verdict[1:] in (["match", ""], ["unresolved", "tools start-turn hook ordering"],
                                       ["unresolved", "slumber wake on damage"]), verdict
