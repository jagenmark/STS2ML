"""Offline checks for the selected collection target and diagnostic handoff."""

import json
import hashlib
from copy import deepcopy
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from sts2rl.adapters.spire_codex import list_replays
from sts2rl.cli import main
from sts2rl.data import write_records
from sts2rl.demo import make_demo_records


def test_replay_listing_filters_the_actual_api_build_id():
    with patch("sts2rl.adapters.spire_codex._json_get", return_value={"runs": []}) as fetch:
        list_replays()
    query = parse_qs(urlparse(fetch.call_args.args[0]).query)
    assert query["character"] == ["SILENT"]
    assert query["ascension"] == ["10"]
    assert query["build_id"] == ["v0.111.0"]
    assert query["players"] == ["single"]
    with patch("sts2rl.adapters.spire_codex._json_get", return_value={"runs": []}) as fetch:
        list_replays(character="DEFECT", game_version="v0.107.1")
    assert parse_qs(urlparse(fetch.call_args.args[0]).query)["build_id"] == ["v0.107.1"]


def test_fetch_refuses_a_listing_for_another_patch_before_downloading(tmp_path):
    with (
        patch("sts2rl.adapters.spire_codex.list_replays", return_value={
            "runs": [{"run_hash": "example", "build_id": "v0.107.1"}],
        }),
        patch("sts2rl.adapters.spire_codex.download_replay") as download,
    ):
        assert main(["fetch-replays", "--output", str(tmp_path / "raw")]) == 2
    download.assert_not_called()
    assert not (tmp_path / "raw").exists()


def test_default_fetch_output_and_manifest_are_patch_scoped(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("sts2rl.adapters.spire_codex.list_replays", return_value={"runs": [], "total": 0}):
        assert main(["fetch-replays"]) == 0
    manifest = json.loads((tmp_path / "data/v0.111.0/silent-a10/raw/downloads-page-1.json").read_text())
    assert manifest["game_version"] == "v0.111.0"
    assert manifest["character"] == "SILENT"
    assert manifest["listing"]["total"] == 0


def test_doctor_saves_failure_report_for_handoff(tmp_path):
    report = {"game": {"status": "not_found"}, "runtime": {"smoke_test": {"status": "failed"}}}
    target = tmp_path / "reports/doctor.json"
    with patch("sts2rl.diagnostics.inspect_environment", return_value=report):
        assert main(["doctor", "--output", str(target)]) == 2
    assert json.loads(target.read_text()) == report


def test_fetch_preserves_listing_and_download_hash_after_interruption(tmp_path):
    listing = {"runs": [
        {"run_hash": "first", "build_id": "v0.111.0"},
        {"run_hash": "second", "build_id": "v0.111.0"},
    ]}
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "first.jsonl.gz").write_bytes(b"existing-replay")
    with (
        patch("sts2rl.adapters.spire_codex.list_replays", return_value=listing),
        patch("sts2rl.adapters.spire_codex.download_replay", side_effect=OSError("interrupted")),
        patch("sts2rl.cli.time.sleep"),
    ):
        assert main(["fetch-replays", "--output", str(raw)]) == 2
    manifest = json.loads((raw / "downloads-page-1.json").read_text())
    assert manifest["listing"] == listing
    assert len(manifest["downloads"]) == 1
    assert manifest["downloads"][0]["sha256"] == hashlib.sha256(b"existing-replay").hexdigest()
    assert not (raw / "second.jsonl.gz").exists()


def test_train_validates_run_identity_before_target_filtering(tmp_path):
    row = make_demo_records(runs=3)[0]
    row["game_version"] = "v0.111.0"
    row["observation"]["character"] = "SILENT"
    contradictory = deepcopy(row)
    contradictory["decision_id"] = "other-patch"
    contradictory["game_version"] = "v0.107.1"
    data = tmp_path / "contradictory.jsonl"
    write_records(data, [row, contradictory])
    output = tmp_path / "model"
    with patch("sts2rl.training.train") as train:
        assert main(["train", str(data), "--output", str(output)]) == 2
    train.assert_not_called()
    assert not output.exists()
