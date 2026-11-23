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


def test_act_scoped_fit_uses_only_its_roots_and_keeps_other_band(tmp_path):
    import runpy

    fit = runpy.run_path(str(ROOT / "scripts/train-silent-strategy.py"))["fit_strategy_roots"]
    raw = json.loads((V4 / "strategy_model.json").read_bytes())
    stamp = {"continuation": "bundle", "horizon": "run", "unified_draft": True,
             "deck_size_penalty": 0.0}
    labels = tmp_path / "labels"
    for seed in ("fit-seed", "second-seed", "third-seed", "fourth-seed"):
        rows = []
        for act in (1, 2, 3):
            rows.append({
                "group": seed, "kind": "card", "act": act, "root": str(act), "label_provenance": stamp,
                "arms": [
                    {"id": "take", "prior": 0, "features": {f"card:ONLY_IN_ACT_{act}": 1}, "return": 20},
                    {"id": "skip", "prior": 0, "features": {}, "return": 10},
                ],
            })
        folder = labels / f"run-{seed}"
        folder.mkdir(parents=True)
        (folder / "labels.json").write_text(json.dumps({"roots": rows, "label_provenance": stamp}))

    args = dict(continuation="bundle", horizon="run", unified_draft=True, deck_size_penalty=0)
    late, report = fit([labels], base_strategy=V4 / "strategy_model.json",
                       residual_act_band="act2_plus", **args)
    assert report["roots"] == 8
    assert set(late.card_residuals_by_act["act2_plus"]) == {"card:ONLY_IN_ACT_2", "card:ONLY_IN_ACT_3"}
    saved = tmp_path / "late.json"
    late.save(saved)
    split, report = fit([labels], base_strategy=saved, residual_act_band="act1", **args)
    assert report["roots"] == 4
    assert set(split.card_residuals_by_act["act1"]) == {"card:ONLY_IN_ACT_1"}
    assert split.card_residuals_by_act["act2_plus"] == late.card_residuals_by_act["act2_plus"]
    assert split.weights == late.weights == raw["weights"]


@pytest.mark.parametrize("band", ["act1", "act2_plus"])
def test_active_card_residual_does_not_change_events(band):
    raw = json.loads((V4 / "strategy_model.json").read_bytes())
    base = StrategyModel.from_data(raw)
    act = 1 if band == "act1" else 2
    state, policy = draft(act)
    state.update(decision="event_choice", options=[
        {"index": 0, "text_key": "LEFT", "description": ""},
        {"index": 1, "text_key": "RIGHT", "description": ""},
    ])
    state["player"]["gold"] = 10
    assert base.choose(state, policy).args == {"option_index": 0}
    gated = StrategyModel.from_data({**raw, "card_residuals_by_act": {band: {"event:RIGHT": 999}}})
    assert gated.choose(state, policy) == base.choose(state, policy)
