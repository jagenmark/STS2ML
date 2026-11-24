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
