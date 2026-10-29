"""Small fake installations verify diagnostic boundaries without a running game/GPU."""

import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from sts2rl import diagnostics


@pytest.fixture
def game_root(tmp_path):
    root = tmp_path / "steamapps/common/Slay the Spire 2"
    root.mkdir(parents=True)
    (root / "release_info.json").write_text(json.dumps({
        "version": "v0.111.0", "commit": "41cef1ea", "branch": "v0.111.0",
    }))
    (root / "SlayTheSpire2.pck").write_bytes(b"fake-pck")
    for platform in ("windows_x86_64", "linuxbsd_x86_64"):
        directory = root / f"data_sts2_{platform}"
        directory.mkdir()
        (directory / "sts2.dll").write_bytes(platform.encode())
        (directory / "GodotSharp.dll").write_bytes(b"fake-godot")
    (tmp_path / "steamapps/appmanifest_2868840.acf").write_text(
        '"AppState" { "buildid" "24724944" "UserConfig" { "BetaKey" "public-beta" } }'
    )
    return root


def test_installation_metadata_hashes_and_no_false_certification(game_root):
    report = diagnostics.inspect_environment(game_root, check_torch=False)
    assert report["schema_version"] == 1
    assert report["target"] == {"game_version": "v0.111.0", "character": "SILENT",
                                "ascension": 10, "steam_branch": "public-beta"}
    assert report["diagnostic_only"] and not report["headless_runtime_tested"]
    game = report["game"]
    assert game["status"] == "identified"
    assert game["release"]["commit"] == "41cef1ea"
    assert game["steam_manifest"]["buildid"] == "24724944"
    assert game["steam_manifest"]["BetaKey"] == "public-beta"
    assert len(game["files"]) == 5
    pck = next(item for item in game["files"] if item["path"] == "SlayTheSpire2.pck")
    assert pck == {"path": "SlayTheSpire2.pck", "bytes": 8,
                   "sha256": hashlib.sha256(b"fake-pck").hexdigest()}
    assert game["divine_bridge"]["status"] == "unsupported"
    json.dumps(report, allow_nan=False)


def test_matching_pins_only_report_fingerprint_match(game_root, monkeypatch):
    monkeypatch.setattr(diagnostics, "SUPPORTED_PCK_SHA256", hashlib.sha256(b"fake-pck").hexdigest())
    monkeypatch.setattr(diagnostics, "SUPPORTED_ASSEMBLY_SHA256",
                        hashlib.sha256(b"windows_x86_64").hexdigest())
    bridge = diagnostics.inspect_environment(game_root, check_torch=False)["game"]["divine_bridge"]
    assert bridge["status"] == "fingerprint_match"
    assert bridge["compatibility_certified"] is False
    assert bridge["headless_runtime_tested"] is False


def test_missing_path_and_invalid_installation(tmp_path, game_root):
    assert diagnostics.inspect_environment(tmp_path / "absent", check_torch=False)["game"]["status"] == "not_found"
    (game_root / "release_info.json").write_text("{broken")
    report = diagnostics.inspect_environment(game_root, check_torch=False)
    assert report["game"]["status"] == "invalid"
    assert report["game"]["errors"]
    assert report["game"]["files"]  # Still useful even when metadata is malformed.
    (game_root / "release_info.json").write_text("[]")
    assert diagnostics.inspect_environment(game_root, check_torch=False)["game"]["status"] == "invalid"


def test_explicit_path_overrides_environment_and_known_library(game_root, tmp_path, monkeypatch):
    monkeypatch.setenv("STS2_GAME_ROOT", str(game_root))
    assert diagnostics.inspect_environment(check_torch=False)["game"]["path_source"] == "environment"
    assert diagnostics.inspect_environment(tmp_path / "absent", check_torch=False)["game"]["status"] == "not_found"
    monkeypatch.delenv("STS2_GAME_ROOT")
    fake_home = tmp_path / "home"
    discovered = fake_home / ".local/share/Steam/steamapps/common/Slay the Spire 2"
    discovered.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
    report = diagnostics.inspect_environment(check_torch=False)
    assert report["game"]["root"] == str(discovered)
    assert report["game"]["status"] == "invalid"


def test_no_process_launch_or_personal_save_reads_and_skip_never_imports_torch(game_root, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("A diagnostic must not launch processes or import runtime modules")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(diagnostics.importlib, "import_module", forbidden)
    (game_root / "personal.save").write_text("must never be read")
    original_open = Path.open

    def guarded_open(path, *args, **kwargs):
        assert path.suffix != ".save"
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    report = diagnostics.inspect_environment(game_root, check_torch=False)
    assert report["game"]["status"] == "identified"
    assert report["runtime"]["smoke_test"]["status"] == "skipped"


def test_torch_import_failure_is_json_not_exception(game_root, monkeypatch):
    def missing(name):
        raise ModuleNotFoundError("torch unavailable")

    monkeypatch.setattr(diagnostics.importlib, "import_module", missing)
    report = diagnostics.inspect_environment(game_root)
    assert report["runtime"]["smoke_test"]["status"] == "failed"
    assert "ModuleNotFoundError" in report["runtime"]["smoke_test"]["error"]
    json.dumps(report, allow_nan=False)


def test_driver_failure_retains_torch_metadata_and_requested_device(game_root, monkeypatch):
    requested = []

    def tensor(*args, **kwargs):
        requested.append(kwargs["device"])
        raise RuntimeError("driver unavailable")

    fake = SimpleNamespace(__version__="test", version=SimpleNamespace(cuda=None, hip="test-hip"),
                           cuda=SimpleNamespace(is_available=lambda: False), tensor=tensor)
    monkeypatch.setattr(diagnostics.importlib, "import_module", lambda name: fake)
    report = diagnostics.inspect_environment(game_root, device="cuda:3")
    assert requested == ["cuda:3"]
    assert report["runtime"]["torch"]["hip"] == "test-hip"
    assert report["runtime"]["smoke_test"]["status"] == "failed"
    assert "driver unavailable" in report["runtime"]["smoke_test"]["error"]


def test_cpu_matmul_backward_smoke(game_root, monkeypatch):
    torch = pytest.importorskip("torch")
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    report = diagnostics.inspect_environment(game_root)
    assert report["runtime"]["device"] == "cpu"
    assert report["runtime"]["smoke_test"] == {
        "status": "passed", "operation": "2x2 matmul, sum, backward", "result": 54.0,
    }
