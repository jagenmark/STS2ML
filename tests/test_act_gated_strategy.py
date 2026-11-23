"""Act-scoped card weights on the deployed v4 draft path."""

import json
from pathlib import Path

import pytest

from sts2rl.run_policy import IDENTITY, RunPolicy, RunWeights
from sts2rl.strategy import StrategyModel

ROOT = Path(__file__).resolve().parents[1]
V4 = ROOT / "releases/silent-a10-v2-tactics/challenger"


def draft(act):
    state = {
        "runtime_identity": IDENTITY,
        "decision": "card_reward",
        "context": {"act": act, "floor": 8, "boss": {"id": "WATERFALL_GIANT_BOSS"}},
        "player": {"hp": 41, "max_hp": 70, "deck": []},
        "cards": [
            {"index": 0, "id": "CARD.PREDATOR", "type": "Attack", "cost": 2, "stats": {"damage": 15}},
            {"index": 1, "id": "CARD.DEFEND_SILENT", "type": "Skill", "cost": 1, "stats": {"block": 5}},
        ],
        "can_skip": True,
    }
    return state, RunPolicy(RunWeights.load(V4 / "weights.json"))


def scores(model, act):
    state, policy = draft(act)
    trace = {}
    chosen = model.choose(state, policy, explanation=trace)
    assert chosen == model.choose(state, policy)
    return trace["chosen"], [o["total"].hex() for o in trace["options"]]


@pytest.mark.parametrize("act", [1, 2, 3])
def test_legacy_v4_scores_match_prechange_binary64(act, tmp_path):
    model = StrategyModel.load(V4 / "strategy_model.json")
    assert scores(model, act) == (
        "CARD.PREDATOR", ["0x1.66c2755d5ed7ep+1", "-0x1.d0c96aa06342ap-2", "0x0.0p+0"],
    )
    path = tmp_path / "model.json"
    model.save(path)
    assert json.loads(path.read_bytes()) == json.loads((V4 / "strategy_model.json").read_bytes())


@pytest.mark.parametrize("split", [False, True])
def test_gate_uses_only_active_card_weights_and_roundtrips(split, tmp_path):
    raw = json.loads((V4 / "strategy_model.json").read_bytes())
    bands = {"act2_plus": {"card:take": -20}}
    if split:
        bands["act1"] = {"card:DEFEND_SILENT": 20}
    gated = StrategyModel.from_data({**raw, "card_residuals_by_act": bands})
    path = tmp_path / "gated.json"
    gated.save(path)
    for act in (1, 2, 3):
        weights = dict(raw["weights"])
        for key, delta in bands.get("act1" if act == 1 else "act2_plus", {}).items():
            weights[key] = weights.get(key, 0.0) + delta
        expected = StrategyModel.from_data({**raw, "weights": weights})
        state, policy = draft(act)
        reference = {}
        action = expected.choose(state, policy, explanation=reference)
        for model in (gated, StrategyModel.load(path)):
            observed = {}
            assert model.choose(state, policy, explanation=observed) == action
            assert observed == reference
        assert reference["chosen"] == (
            ("CARD.DEFEND_SILENT" if split else "CARD.PREDATOR") if act == 1 else "skip"
        )
