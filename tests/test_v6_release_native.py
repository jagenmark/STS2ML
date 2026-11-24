"""Replay the physical transitions reported by CSV6DEV on the pinned host."""
from dataclasses import replace
import gzip
import json
from pathlib import Path

import pytest

from sts2rl.combat_search_v2.integration import _difference, _native_legal, _normalized_legal
from sts2rl.combat_search_v2.state import project, root_move
from sts2rl.combat_search_v2.transitions import advance, legal
from sts2rl.native import NativeSession, digest, legal_actions
from test_combat_search_v2_native import HOST, ROOT

FIXTURES = json.loads(gzip.decompress((Path(__file__).parent / "fixtures/csv6dev-native.json.gz").read_bytes()))


@pytest.mark.skipif(not HOST, reason="requires pinned v0.111.0 host")
def test_rocket_poison_death_before_crusher_defends(tmp_path):
    path = Path(__file__).parent / "fixtures/v6-crab-rage.json.gz"
    data = json.loads(gzip.decompress(path.read_bytes()))
    with NativeSession(ROOT, tmp_path / "host", host_path=HOST) as host:
        public = host.reset(data["seed"])
        for command in data["history"]:
            public = host._request(command)
        assert digest(public) == data["before"]
        end, = legal_actions(public)
        assert end.kind == "end_turn" and end.command() == data["action"]
        p = project(public, late_prompts=True)
        # The final targeted card faced Crusher, native enemy index zero.
        state = replace(p.state, late=True, v61_rules=True, facing=0, preview_facing=0)
        predicted = advance(state, root_move(p, end.kind, end.args))
        after = host._request(end.command())
        assert digest(after) == data["after"]
        actual = project(after).state
        assert [(e.name, e.hp, e.block) for e in actual.enemies] == [("CRUSHER", 12, 117)]
        assert predicted.outcome == "completed" and not _difference(predicted, actual)


@pytest.mark.skipif(not HOST, reason="requires pinned v0.111.0 host")
def test_candelabra_energy_after_mittens_selection(tmp_path):
    path = Path(__file__).parent / "fixtures/v6-candelabra-mittens.json.gz"
    data = json.loads(gzip.decompress(path.read_bytes()))
    steps = {s["index"]: s for s in data["steps"]}
    with NativeSession(ROOT, tmp_path / "host", host_path=HOST, act_list=data["mode"]) as host:
        public = host.reset(data["seed"])
        for index, command in enumerate(data["history"]):
            if index not in steps:
                public = host._request(command)
                continue
            step = steps[index]
            assert digest(public) == step["before"]
            p = project(public, late_prompts=True)
            state = replace(p.state, **step["witness"])
            assert state.prompt.operation == "TOASTY_MITTENS" and state.round == 2 and state.energy == 3
            action = next(a for a in legal_actions(public) if a.command() == command)
            predicted = advance(state, root_move(p, action.kind, action.args))
            public = host._request(command)
            assert digest(public) == step["after"]
            actual = project(public, late_prompts=True)
            assert predicted.energy == actual.state.energy == 5
            assert not predicted.boundary and not _difference(predicted, actual.state)
            assert _normalized_legal(predicted) == _normalized_legal(replace(actual.state, late=True))


@pytest.mark.skipif(not HOST, reason="requires pinned v0.111.0 host")
@pytest.mark.parametrize("seed", sorted(FIXTURES))
def test_csv6dev_reported_physical_transitions(tmp_path, seed):
    data = FIXTURES[seed]
    spec = data["spec"]
    reasons = {"board/powers": "toasty mittens delayed start triggers",
               "board/relics": "toasty mittens delayed start triggers",
               "board/hp": "aeonglass wither damage level", "legality": "sloth automatic discard play"}
    with NativeSession(ROOT, tmp_path / "host", host_path=HOST, act_list=spec.get("act_list", "default")) as host:
        public = host.reset(seed)
        steps = {step["index"]: step for step in data["steps"]}
        for index, command in enumerate([*data["history"], data["steps"][-1]["action"]]):
            if index not in steps:
                public = host._request(command)
                continue
            step = steps[index]
            assert digest(public) == step["before"] and command == step["action"]
            p = project(public, late_prompts=True)
            state = replace(p.state, late=True, v61_rules=True, right_hand_return=True,
                            sloth_plays=step["plays"], aeon_plays=step["aeon"], facing=step["facing"],
                            preview_facing=step["facing"])
            action = next(a for a in legal_actions(public) if a.command() == step["action"])
            predicted = advance(state, root_move(p, action.kind, action.args))
            after = public = host._request(command)
            assert digest(after) == step["after"]
            if step["reason"] in reasons:
                assert not predicted.outcome and predicted.boundary.reason == reasons[step["reason"]]
            else:
                actual = project(after, late_prompts=True)
                assert not predicted.boundary and not _difference(predicted, actual.state)
                assert _normalized_legal(predicted) == _normalized_legal(actual.state)
                assert _native_legal(actual, legal_actions(after)) == legal(actual.state)
