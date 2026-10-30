from pathlib import Path
import json
import runpy

import pytest


def test_failed_micro_fit_is_recorded_and_cannot_look_like_running_training(tmp_path, monkeypatch):
    module = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/train-micro.py"))
    def collected(index, *args):
        return {"index": index, "status": "complete", "decisions": 2}
    module["main"].__globals__["collect_episode"] = collected
    def failed(*args, **kwargs):
        raise RuntimeError("GPU unavailable")
    monkeypatch.setattr("sts2rl.micro.fit_micro", failed)
    monkeypatch.setattr("sys.argv", ["train-micro", "--output", str(tmp_path), "--episodes", "10"])
    with pytest.raises(RuntimeError, match="GPU unavailable"):
        module["main"]()
    status = json.loads((tmp_path / "status.json").read_text())
    assert status["stage"] == "failed"
    assert status["error"] == "RuntimeError: GPU unavailable"
    assert not (tmp_path / "model/best.pt").exists()
