from copy import deepcopy
import json
import math
import random

import pytest
import torch

from sts2rl.data import dataset_digest, grouped_split, load_records, write_records
from sts2rl.demo import make_demo_records
from sts2rl.encoding import MAX_ACTIONS, Vocabulary, collate_records
from sts2rl.schema import MAX_CANDIDATES, SchemaError, validate_record
from sts2rl.training import TrainConfig, evaluate, load_checkpoint, predict, train


@pytest.fixture(autouse=True)
def one_cpu_thread():
    old = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


def tiny_config(**overrides):
    values = dict(epochs=2, batch_size=32, d_model=32, n_heads=4, n_layers=1, threads=1)
    return TrainConfig(**(values | overrides))


def test_demo_is_valid_deterministic_and_jsonl_roundtrips(tmp_path):
    records = make_demo_records(runs=12, seed=123)
    assert len(records) == 36
    assert records == make_demo_records(runs=12, seed=123)
    for record in records:
        validate_record(record)
        assert record["observation"]["state_quality"] == "synthetic"
    path = tmp_path / "decisions.jsonl.gz"
    write_records(path, records + [deepcopy(records[0])])
    assert load_records(path) == records
    assert dataset_digest(list(reversed(records))) == dataset_digest(records)
    conflicting = deepcopy(records[0])
    conflicting["chosen_action_id"] = "skip"
    write_records(path, [records[0], conflicting])
    with pytest.raises(SchemaError, match="conflicting duplicate"):
        load_records(path)


def test_grouped_split_preserves_transitive_run_seed_links_and_order_independence():
    base = make_demo_records(runs=48)
    bridge = deepcopy(base[0])
    bridge["decision_id"] = "bridge"
    bridge["split_group"] = base[3]["split_group"]
    second_bridge = deepcopy(base[3])
    second_bridge["decision_id"] = "bridge"
    second_bridge["split_group"] = base[6]["split_group"]
    rows = base + [bridge, second_bridge]
    split, manifest = grouped_split(rows)
    shuffled = list(rows)
    random.Random(31).shuffle(shuffled)
    shuffled_split, shuffled_manifest = grouped_split(shuffled)
    assert manifest == shuffled_manifest
    run_partition, seed_partition = {}, {}
    for partition, records in split.items():
        for record in records:
            previous = run_partition.setdefault(record["run_id"], partition)
            assert previous == partition
            previous_seed = seed_partition.setdefault(record["split_group"], partition)
            assert previous_seed == partition
        assert {(r["run_id"], r["decision_id"]) for r in records} == {
            (r["run_id"], r["decision_id"]) for r in shuffled_split[partition]
        }
    assert run_partition[base[0]["run_id"]] == run_partition[base[3]["run_id"]]
    assert run_partition[base[0]["run_id"]] == run_partition[base[6]["run_id"]]
    assert sum(manifest["counts"].values()) == len(rows)
    assert sum(manifest["group_counts"].values()) == 46


@pytest.mark.parametrize("hidden_key", ["seed", "state_hash", "draw_order", "final_deck", "win"])
def test_schema_rejects_hidden_observation_fields(hidden_key):
    record = make_demo_records(runs=3)[0]
    record["observation"][hidden_key] = "must-not-be-a-feature"
    with pytest.raises(SchemaError, match="unrecognized observation"):
        validate_record(record)
    assert MAX_ACTIONS == MAX_CANDIDATES


def test_training_checkpoint_prediction_and_unlabelled_split_bridge(tmp_path):
    records = make_demo_records(runs=48)
    initial, _ = grouped_split(records)
    # An unlabelled capture still carries run/seed identity. Removing it before
    # connected-component splitting can leak the same family across partitions.
    bridge = deepcopy(initial["train"][0])
    bridge["decision_id"] = "unlabelled-bridge"
    bridge["split_group"] = initial["validation"][0]["split_group"]
    bridge["chosen_action_id"] = None
    bridge["outcome"] = None
    records.append(bridge)
    partitions, expected_manifest = grouped_split(records)
    held_out = partitions["test"][0]
    held_out["observation"]["deck"] = [{"id": "HELDOUT_ONLY", "upgrades": None}]
    report = train(records, tmp_path / "run", tiny_config())
    assert report["split"]["assignments"] == expected_manifest["assignments"]
    assert len(report["history"]) == 2
    assert report["best_epoch"] in (1, 2)
    assert report["test"]["decisions"] == len(partitions["test"])
    assert report["test"]["policy_labels"] == len(partitions["test"])
    assert sum(report["test"]["value_label_counts"].values()) == report["test"]["value_labels"]
    assert math.isfinite(report["test"]["policy_nll"])
    assert math.isfinite(report["test"]["value_bce"])
    assert json.loads((tmp_path / "run/report.json").read_text())["best_epoch"] == report["best_epoch"]
    progress = json.loads((tmp_path / "run/progress.json").read_text())
    assert progress["status"] == "complete"
    assert progress["epoch"] == progress["epochs"] == 2
    assert progress["best_epoch"] == report["best_epoch"]
    assert progress["history"] == json.loads((tmp_path / "run/report.json").read_text())["history"]
    model, vocab, checkpoint = load_checkpoint(tmp_path / "run/best.pt")
    assert model.parameter_count == report["parameter_count"]
    assert "entity:HELDOUT_ONLY" not in vocab.token_to_id
    expected_vocab = Vocabulary.build([
        row for row in partitions["train"]
        if row["chosen_action_id"] is not None or row["outcome"] is not None
    ])
    assert vocab.to_dict() == expected_vocab.to_dict()
    assert collate_records([held_out], vocab)["state_tokens"][0, 0].item() == 1
    recomputed = evaluate(model, partitions["test"], vocab, baselines=checkpoint["baselines"])
    assert recomputed["policy_nll"] == pytest.approx(report["test"]["policy_nll"])
    result = predict(tmp_path / "run/best.pt", held_out)
    assert {row["action_id"] for row in result["ranked_actions"]} == {
        candidate["action_id"] for candidate in held_out["candidates"]
    }
    assert sum(row["probability"] for row in result["ranked_actions"]) == pytest.approx(1.0)
    assert result["value_head_trained"]
    assert 0 <= result["outcome_probability"] <= 1


def test_conflicting_outcomes_within_run_are_rejected(tmp_path):
    records = make_demo_records(runs=48)
    assert records[0]["run_id"] == records[1]["run_id"]
    records[1]["outcome"] = 1.0 - records[0]["outcome"]
    with pytest.raises(ValueError, match="outcome"):
        train(records, tmp_path / "conflict", tiny_config(epochs=1))


def test_no_labels_are_rejected_and_zero_value_weight_has_no_probability(tmp_path):
    records = make_demo_records(runs=48)
    unlabelled = deepcopy(records)
    for record in unlabelled:
        record["chosen_action_id"] = None
        record["outcome"] = None
    with pytest.raises(ValueError, match="label|empty"):
        train(unlabelled, tmp_path / "unlabelled", tiny_config(epochs=1))
    report = train(records, tmp_path / "policy_only", tiny_config(epochs=1, value_weight=0.0))
    assert report["best_epoch"] == 1
    result = predict(tmp_path / "policy_only/best.pt", records[0])
    assert result["value_head_trained"] is False
    assert result["outcome_probability"] is None
    no_outcomes = deepcopy(records)
    for record in no_outcomes:
        record["outcome"] = None
    report = train(no_outcomes, tmp_path / "no_outcomes", tiny_config(epochs=1))
    assert report["test"]["value_labels"] == 0
    assert report["test"]["value_bce"] is None
    result = predict(tmp_path / "no_outcomes/best.pt", records[0])
    assert result["value_head_trained"] is False
    assert result["outcome_probability"] is None


def test_mixed_patches_cannot_train_even_when_each_run_is_consistent(tmp_path):
    records = make_demo_records(runs=48)
    for record in records:
        record["game_version"] = "v0.111.0" if record["run_id"] == records[0]["run_id"] else "v0.107.1"
    with pytest.raises(ValueError, match="exactly one game version"):
        train(records, tmp_path / "mixed", tiny_config(epochs=1))
    assert not (tmp_path / "mixed").exists()


def test_patch_identity_blocks_inference_and_output_reuse_and_loads_legacy(tmp_path):
    records = make_demo_records(runs=48)
    for record in records:
        record["game_version"] = "v0.111.0"
    folder = tmp_path / "beta"
    train(records, folder, tiny_config(epochs=1))
    assert predict(folder / "best.pt", records[0])["game_version"] == "v0.111.0"
    other_patch = deepcopy(records)
    for record in other_patch:
        record["game_version"] = "v0.107.1"
    with pytest.raises(ValueError, match="does not match"):
        predict(folder / "best.pt", other_patch[0])
    original = {p.name: p.read_bytes() for p in folder.iterdir()}
    with pytest.raises(ValueError, match="different game version"):
        train(other_patch, folder, tiny_config(epochs=1))
    assert original == {p.name: p.read_bytes() for p in folder.iterdir()}
    # Existing v1 checkpoints can recover their exact patch from the saved audit.
    checkpoint = torch.load(folder / "best.pt", weights_only=True)
    checkpoint.pop("game_version")
    torch.save(checkpoint, tmp_path / "legacy.pt")
    assert load_checkpoint(tmp_path / "legacy.pt")[2]["game_version"] == "v0.111.0"
    # A copied legacy checkpoint must also protect a directory without a scope file.
    legacy_folder = tmp_path / "legacy-output"
    legacy_folder.mkdir()
    torch.save(checkpoint, legacy_folder / "best.pt")
    with pytest.raises(ValueError, match="different game version"):
        train(other_patch, legacy_folder, tiny_config(epochs=1))
    checkpoint["training_audit"]["versions"]["v0.107.1"] = 1
    torch.save(checkpoint, tmp_path / "mixed.pt")
    with pytest.raises(ValueError, match="exactly one game version"):
        load_checkpoint(tmp_path / "mixed.pt")
