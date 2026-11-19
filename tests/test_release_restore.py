import hashlib
import json
from pathlib import Path
import runpy
from zipfile import ZipFile

import pytest

restore = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/restore-silent-a10.py")
)["restore"]


def fixture_zip(folder):
    payload = b'{"weight": 3}\n'
    inventory = json.dumps({"weights/policy.json": hashlib.sha256(payload).hexdigest()}).encode()
    archive = folder / "model.zip"
    with ZipFile(archive, "x") as z:
        z.writestr("weights/policy.json", payload)
        z.writestr("sha256.json", inventory)
    return {
        "name": archive.name, "directory": "installed-model",
        "bytes": archive.stat().st_size, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "manifest_sha256": hashlib.sha256(inventory).hexdigest(),
    }


def test_release_restore_verifies_offline_and_preserves_local_work(tmp_path):
    asset = fixture_zip(tmp_path)
    output = tmp_path / "artifacts"
    installed = restore(asset, output, tmp_path)
    user_file = installed / "experiment.txt"
    user_file.write_text("my results")
    assert restore(asset, output, None) == installed  # The verified copy needs no download.
    assert user_file.read_text() == "my results"
    (installed / "weights/policy.json").write_text("changed")
    with pytest.raises(ValueError, match="modified"):
        restore(asset, output, tmp_path)
    assert (installed / "weights/policy.json").read_text() == "changed"


@pytest.mark.parametrize("field", ["sha256", "manifest_sha256"])
def test_incomplete_or_different_release_never_appears_installed(tmp_path, field):
    asset = fixture_zip(tmp_path)
    asset[field] = "0" * 64
    output = tmp_path / "artifacts"
    with pytest.raises(ValueError):
        restore(asset, output, tmp_path)
    assert list(output.iterdir()) == []
