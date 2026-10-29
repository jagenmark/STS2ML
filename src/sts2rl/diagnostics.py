"""Read-only installation fingerprints and an optional, explicitly selected torch smoke.

Only standard Steam libraries are discovered automatically. Pass ``game_root``
or set ``STS2_GAME_ROOT`` for other libraries. No game, upstream bridge, save,
or external process is loaded or started by this module.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import platform
from pathlib import Path
import re
import sys
from typing import Any

from .adapters.divine import (
    INSPECTED_REVISION,
    SUPPORTED_ASSEMBLY_SHA256,
    SUPPORTED_GAME_VERSION,
    SUPPORTED_PCK_SHA256,
)
from .target import ASCENSION, CHARACTER, GAME_VERSION, STEAM_BRANCH


def _game_path(explicit: str | Path | None) -> tuple[Path | None, str]:
    supplied = explicit if explicit is not None else os.environ.get("STS2_GAME_ROOT")
    if supplied is not None:
        return Path(supplied).expanduser(), "argument" if explicit is not None else "environment"
    libraries = [Path.home() / ".steam/steam", Path.home() / ".local/share/Steam"]
    for variable in ("ProgramFiles(x86)", "PROGRAMFILES(X86)", "ProgramFiles"):
        if os.environ.get(variable):
            libraries.append(Path(os.environ[variable]) / "Steam")
    for library in libraries:
        candidate = library / "steamapps/common/Slay the Spire 2"
        if candidate.is_dir():
            return candidate, "discovered"
    return None, "discovered"


def _fingerprint(path: Path, root: Path) -> dict[str, Any]:
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return {"path": path.relative_to(root).as_posix(), "bytes": size, "sha256": digest.hexdigest()}


def _inspect_game(root: Path | None, source: str) -> dict[str, Any]:
    game: dict[str, Any] = {
        "status": "not_found", "root": str(root) if root is not None else None,
        "path_source": source, "release": None, "files": [], "errors": [],
        "discovery_note": "Other Steam libraries require --game-root or STS2_GAME_ROOT.",
        "divine_bridge": {
            "revision": INSPECTED_REVISION, "expected_product_version": SUPPORTED_GAME_VERSION,
            "expected_files": {"SlayTheSpire2.pck": SUPPORTED_PCK_SHA256,
                               "data_sts2_windows_x86_64/sts2.dll": SUPPORTED_ASSEMBLY_SHA256},
            "status": "unsupported", "compatibility_certified": False,
            "headless_runtime_tested": False,
        },
    }
    if root is None or not root.exists():
        return game
    game["status"] = "invalid"
    if not root.is_dir():
        game["errors"].append("Game root is not a directory")
        return game
    try:
        release = json.loads((root / "release_info.json").read_text(encoding="utf-8-sig"))
        if not isinstance(release, dict) or any(
            not isinstance(release.get(key), str) or not release[key].strip()
            for key in ("version", "commit")
        ):
            raise ValueError("release_info.json requires nonempty version and commit strings")
        game["release"] = {key: release.get(key) for key in ("version", "commit", "branch")}
    except (OSError, ValueError, UnicodeError) as error:
        game["errors"].append(f"release_info.json: {error}")

    artifacts = [root / "SlayTheSpire2.pck"]
    assemblies = sorted(root.glob("data_sts2_*/sts2.dll"))
    assemblies = [path for path in assemblies if re.match(r"data_sts2_(windows|linux)", path.parent.name)]
    if not assemblies:
        game["errors"].append("No Windows/Linux data_sts2_*/sts2.dll found")
    artifacts.extend(assemblies)
    artifacts.extend(path.parent / "GodotSharp.dll" for path in assemblies
                     if (path.parent / "GodotSharp.dll").is_file())
    for path in artifacts:
        try:
            game["files"].append(_fingerprint(path, root))
        except OSError as error:
            game["errors"].append(f"{path.name}: {error}")

    # Read only these two fields from the installation manifest, never account data/saves.
    manifest = root.parent.parent / "appmanifest_2868840.acf"
    if manifest.is_file():
        try:
            text = manifest.read_text(encoding="utf-8-sig")
            game["steam_manifest"] = {"path": str(manifest)}
            for key in ("buildid", "BetaKey"):
                match = re.search(r'"' + key + r'"\s*"([^"\r\n]*)"', text, re.IGNORECASE)
                game["steam_manifest"][key] = match.group(1) if match else None
        except (OSError, UnicodeError) as error:
            game["manifest_error"] = str(error)
    files = {item["path"]: item["sha256"] for item in game["files"]}
    matches = (
        files.get("SlayTheSpire2.pck") == SUPPORTED_PCK_SHA256
        and files.get("data_sts2_windows_x86_64/sts2.dll") == SUPPORTED_ASSEMBLY_SHA256
    )
    game["divine_bridge"]["status"] = "fingerprint_match" if matches else "unsupported"
    if not game["errors"]:
        game["status"] = "identified"
    return game


def _inspect_torch(device: str, enabled: bool) -> dict[str, Any]:
    runtime: dict[str, Any] = {
        "device": device, "torch": {"checked": enabled},
        "smoke_test": {"status": "skipped", "reason": "Torch check disabled"},
    }
    if not enabled:
        return runtime
    try:
        torch = importlib.import_module("torch")
        runtime["torch"].update({
            "available": True, "version": str(torch.__version__),
            "cuda": torch.version.cuda, "hip": torch.version.hip,
        })
        try:
            available = bool(torch.cuda.is_available())
            runtime["torch"]["accelerator_available"] = available
            runtime["torch"]["device_names"] = (
                [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
                if available else []
            )
        except Exception as error:
            runtime["torch"]["device_query_error"] = str(error)
        # Never select an accelerator implicitly. This small operation includes autograd.
        value = torch.tensor([[1.0, 2.0], [3.0, 4.0]], device=device, requires_grad=True)
        result = (value @ value).sum()
        result.backward()
        if value.grad is None or not bool(torch.isfinite(value.grad).all().item()):
            raise RuntimeError("Matmul backward returned missing or non-finite gradients")
        runtime["smoke_test"] = {
            "status": "passed", "operation": "2x2 matmul, sum, backward",
            "result": float(result.item()),
        }
    except Exception as error:
        runtime["torch"].setdefault("available", False)
        runtime["smoke_test"] = {"status": "failed", "error": f"{type(error).__name__}: {error}"}
    return runtime


def inspect_environment(
    game_root: str | Path | None = None, *, device: str = "cpu", check_torch: bool = True,
) -> dict[str, Any]:
    """Return JSON-safe diagnostics; fingerprints alone never certify compatibility."""
    try:
        root, source = _game_path(game_root)
        game = _inspect_game(root, source)
    except (OSError, ValueError) as error:
        game = {"status": "invalid", "errors": [str(error)]}
    return {
        "schema_version": 1, "diagnostic_only": True, "headless_runtime_tested": False,
        "target": {"game_version": GAME_VERSION, "character": CHARACTER,
                   "ascension": ASCENSION, "steam_branch": STEAM_BRANCH},
        "python": {"version": platform.python_version(), "executable": sys.executable},
        "platform": {"system": platform.system(), "release": platform.release(),
                     "machine": platform.machine()},
        "game": game, "runtime": _inspect_torch(device, check_torch),
    }
