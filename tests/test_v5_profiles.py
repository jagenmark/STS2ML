import hashlib
from pathlib import Path
import runpy

import pytest

from sts2rl.combat_search_v2.planner import Config
from sts2rl.deployed_controller import DeployedController
from sts2rl.run_bundle import load_bundle


def test_v5_profiles_preserve_v4_and_verify_checkpoint(tmp_path):
    root = Path(__file__).resolve().parents[1]
    build = runpy.run_path(str(root / "scripts/build-batch1-challengers.py"))["build_batch1_bundle"]
    base = root / "releases/silent-a10-mecha-knight/challenger/policy.json"
    v4 = build(base, tmp_path / "v4", profile="all_v2_p1_v4")
    assert hashlib.sha256(v4.read_bytes()).hexdigest() == "8636337a6082264bffffe9a79b50528bdf30ed9096b74ff33fd20a8e844fa51b"
    assert DeployedController.from_bundle(v4).combat_v2 is None
    for arm in ("all_v2_search_v5", "all_v2_search_heur_v5"):
        bundle = build(base, tmp_path / arm, profile=arm)
        for path in v4.parent.iterdir():
            if path != v4:
                assert (bundle.parent / path.name).read_bytes() == path.read_bytes()
        mode = DeployedController.from_bundle(bundle).combat_v2
        assert not mode.shadow and mode.config == Config(width=16, children=512)
        if arm == "all_v2_search_v5":
            assert mode.model.schema == 3
            assert mode.model_sha256 == "24debeaaa81c0095cf252807e05e858cf53b8dcbf23ed2e9eb274f267112cb0b"
            (bundle.parent / "combat_value_v2.npz").write_bytes(b"corrupt")
            with pytest.raises(ValueError, match="checksum mismatch"):
                load_bundle(bundle)
        else:
            assert mode.model is None and not list(bundle.parent.glob("*.npz"))
