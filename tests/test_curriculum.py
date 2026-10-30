from copy import deepcopy
import json

import pytest
import torch

from sts2rl.act1 import act1_profile, existing_act1_results, save_json
from sts2rl.act1_evaluation import compare_act1
from sts2rl.combat import combat_entities
from sts2rl.micro import collate_micro, curriculum_scope, fit_micro, load_micro, micro_vocabulary, partition_records, teacher_targets
from sts2rl.native import ACT1_SAMPLER, CURRICULUM_SAMPLER, NativeError, NativeSession, ReplayFork, digest, legal_actions, runtime_identity
from test_act1_evaluation import row as result_row
from test_micro import record, state


def conditioned_state(ascension=7):
    obs = state()
    obs["runtime_identity"] = runtime_identity(ascension)
    return obs


def curriculum_row(index, ascension=7):
    return {**record(conditioned_state(ascension)), "group": f"seed-{index}",
            "schema_version": 1, "sampler": CURRICULUM_SAMPLER, "ascension": ascension}


def test_explicit_profile_and_native_identity_reject_unsupported_difficulty():
    assert act1_profile() == ACT1_SAMPLER
    assert act1_profile(7) == act1_profile(8) == act1_profile(10, True) == CURRICULUM_SAMPLER
    for unsupported in (0, 9, 11, True, "7", None):
        with pytest.raises(ValueError, match="Qualified ascensions"):
            runtime_identity(unsupported)
    session = NativeSession.__new__(NativeSession)
    session.identity = runtime_identity(7)
    with pytest.raises(NativeError, match="Replay ascension"):
        session.restore(ReplayFork({"seed": "same", "ascension": 10}, (), "unused"))
    with pytest.raises(NativeError, match="Legacy sampler"):
        session.sample(1)


def test_ascension_enters_only_conditioned_models_and_nested_choices():
    a, b = conditioned_state(7), conditioned_state(10)
    legacy = micro_vocabulary([a])
    old_a, old_b = collate_micro([a], legacy), collate_micro([b], legacy)
    for key in old_a:
        torch.testing.assert_close(old_a[key], old_b[key])
    vocab = micro_vocabulary([a], condition_ascension=True)
    assert "field:ascension" in vocab.tokens
    new_a = collate_micro([a], vocab, condition_ascension=True)
    new_b = collate_micro([b], vocab, condition_ascension=True)
    assert not torch.equal(new_a["numbers"], new_b["numbers"])
    nested = {"decision": "card_reward", "runtime_identity": runtime_identity(7),
              "combat_state": deepcopy(a), "cards": a["hand"], "can_skip": True}
    nested["combat_state"].pop("runtime_identity")
    original = deepcopy(nested)
    assert combat_entities(nested, condition_ascension=True)[0].attributes["ascension"] == 7
    assert nested == original
    nested["combat_state"]["runtime_identity"] = runtime_identity(10)
    with pytest.raises(ValueError, match="Nested combat runtime identity"):
        combat_entities(nested, condition_ascension=True)


def test_same_seed_at_multiple_difficulties_cannot_leak_across_splits():
    rows = [curriculum_row(i, a) for i in range(20) for a in (7, 10)]
    partitions, split = partition_records(rows)
    assert curriculum_scope(rows, partitions) == [7, 10]
    for name, part in partitions.items():
        assert all(split[r["group"]] == name for r in part)
        assert {r["ascension"] for r in part} == {7, 10}
    bad = deepcopy(rows)
    bad[0]["ascension"] = 10
    with pytest.raises(ValueError, match="disagrees"):
        curriculum_scope(bad, partitions)
    partitions["test"] = [r for r in partitions["test"] if r["ascension"] == 7]
    with pytest.raises(ValueError, match="test split"):
        curriculum_scope(rows, partitions)


def test_v3_fit_checkpoint_and_live_scope_roundtrip(tmp_path):
    rows = [curriculum_row(i) for i in range(10)]
    path = tmp_path / "teacher.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    report = fit_micro([path], tmp_path / "model", epochs=1, width=8)
    assert report["trained_ascensions"] == [7]
    assert report["condition_ascension"]
    assert report["split_groups"] == {"test": 1, "validation": 1, "train": 8}
    checkpoint = tmp_path / "model/best.pt"
    policy = load_micro(checkpoint)
    assert policy(rows[0]["observation"]) in legal_actions(rows[0]["observation"])
    with pytest.raises(ValueError, match="runtime identity"):
        policy(conditioned_state(10))
    saved = torch.load(checkpoint, weights_only=True)
    assert saved["micro_version"] == 3
    saved["sampler"] = ACT1_SAMPLER
    torch.save(saved, checkpoint)
    with pytest.raises(ValueError, match="version and curriculum"):
        load_micro(checkpoint)
    row = curriculum_row(0)
    for estimate in row["estimates"].values():
        estimate["mean_return"] = 200
    assert teacher_targets([row])[1].item() == pytest.approx(1)


def test_resume_and_paired_evaluation_refuse_mixed_difficulties(tmp_path):
    folder = tmp_path / "run-00000"
    folder.mkdir()
    save_json(folder / "result.json", {**result_row(0), "group": digest("PREFIX000000"),
                                      "ascension": 7, "sampler": CURRICULUM_SAMPLER})
    (folder / "teacher.jsonl").write_text("fixture", encoding="utf-8")
    complete, pending = existing_act1_results(tmp_path, 1, "PREFIX", ascension=7)
    assert len(complete) == 1 and not pending
    with pytest.raises(ValueError, match="ascension/profile"):
        existing_act1_results(tmp_path, 1, "PREFIX")
    with pytest.raises(ValueError, match="ascensions differ"):
        compare_act1({"a": [{**result_row(0), "ascension": 7}], "b": [result_row(0)]})
