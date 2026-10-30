import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

from sts2rl.data import write_records
from sts2rl.demo import make_demo_records
from sts2rl.target import GAME_VERSION


def script():
    path = Path(__file__).resolve().parents[1] / "scripts/train-workstation.py"
    spec = importlib.util.spec_from_file_location("workstation", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_all_replays_collects_before_training_and_filters_header_versions(tmp_path, monkeypatch):
    module = script()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["train", "--output", str(tmp_path / "result"),
                                    "--all-replays", "--all-patches", "--device", "cpu"])
    examples = make_demo_records(runs=64)
    for example in examples:
        example["game_version"] = GAME_VERSION
        example["observation"]["character"] = "SILENT"
    other_patch = dict(examples[0], game_version="v0.other", run_id="other-run")
    calls = []

    def collect(folder, **kwargs):
        calls.append("collect")
        assert kwargs["game_version"] is None
        assert folder == Path("data/replays/silent-a10/raw")
        return {"status": "collected", "discovery_complete": True, "records": {}}

    def cli(args):
        calls.append("import")
        assert args[0] == "import-replay"
        write_records(args[args.index("--output") + 1], [*examples, other_patch])
        return 0

    def train(rows, output, config):
        calls.append("train")
        assert len(rows) == len(examples)
        assert all(row["game_version"] == GAME_VERSION for row in rows)
        assert output.name == "final"
        return {"best_epoch": 2}

    with patch("sts2rl.collection.collect_all_replays", side_effect=collect), \
            patch.object(module, "cli", side_effect=cli), patch.object(module, "train", side_effect=train):
        assert module.main() == 0
    assert calls == ["collect", "import", "train"]
    state = json.loads((tmp_path / "result/status.json").read_text(encoding="utf-8"))
    assert state["stage"] == "complete"
    audit = json.loads((tmp_path / "result/audit.json").read_text(encoding="utf-8"))
    assert audit["target_filter_excluded_decisions"] == 1


def test_failed_full_collection_cannot_publish_a_final_fit(tmp_path, monkeypatch):
    module = script()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["train", "--output", str(tmp_path / "result"), "--all-replays"])
    with patch("sts2rl.collection.collect_all_replays", side_effect=TimeoutError("offline")), \
            patch.object(module, "cli") as importer, patch.object(module, "train") as train:
        assert module.main() == 1
    importer.assert_not_called()
    train.assert_not_called()
    assert json.loads((tmp_path / "result/status.json").read_text(encoding="utf-8"))["stage"] == "failed"
