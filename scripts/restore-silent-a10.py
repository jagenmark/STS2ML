"""Install a versioned Silent A10 release from GitHub or local copies of its ZIPs."""

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from urllib.request import Request, urlopen
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "releases/silent-a10-2026-11-19.json"


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def relative_name(name):
    path = PurePosixPath(name)
    if (
        not path.parts or path.as_posix() != name or path.is_absolute()
        or ".." in path.parts or "\\" in name or ":" in name
    ):
        raise ValueError(f"Invalid archive path {name!r}")
    return path


def listed_files(folder, asset):
    manifest = folder / "sha256.json"
    if not manifest.is_file() or sha256(manifest) != asset["manifest_sha256"]:
        raise ValueError(f"Missing or different release manifest in {folder}")
    files = json.loads(manifest.read_text(encoding="utf-8"))
    if not files:
        raise ValueError(f"Empty release manifest in {folder}")
    return {relative_name(name): checksum for name, checksum in files.items()}


def verify_folder(folder, asset):
    files = listed_files(folder, asset)
    for name, expected in files.items():
        path = folder / name
        if not path.is_file() or sha256(path) != expected:
            raise ValueError(f"Missing or modified release file: {path}")
    return len(files)


def restore(asset, output, archives):
    target = output / relative_name(asset["directory"])
    if target.exists():
        count = verify_folder(target, asset)
        print(f"Verified {count} installed files in {target}", flush=True)
        return target

    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".silent-release-", dir=output) as temp:
        staging = Path(temp)
        if archives is None:
            archive = staging / "download.zip"
            request = Request(asset["url"], headers={"User-Agent": "STS2ML-release-restore/1"})
            print(f"Downloading {asset['name']}", flush=True)
            with closing(urlopen(request, timeout=120)) as response, archive.open("xb") as stream:
                shutil.copyfileobj(response, stream)
        else:
            archive = archives / relative_name(asset["name"])
        if archive.stat().st_size != asset["bytes"] or sha256(archive) != asset["sha256"]:
            raise ValueError(f"Release archive size or SHA-256 mismatch: {archive}")

        unpacked = staging / "unpacked"
        unpacked.mkdir()
        with ZipFile(archive) as bundle:
            # Validate the embedded inventory before creating any published paths.
            (unpacked / "sha256.json").write_bytes(bundle.read("sha256.json"))
            files = listed_files(unpacked, asset)
            expected = {p.as_posix() for p in files} | {"sha256.json"}
            if len(bundle.infolist()) != len(expected) or set(bundle.namelist()) != expected:
                raise ValueError(f"ZIP members differ from the release inventory: {archive}")
            for name in files:
                path = unpacked / name
                path.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(name.as_posix()) as source, path.open("xb") as stream:
                    shutil.copyfileobj(source, stream)
        count = verify_folder(unpacked, asset)
        try:
            unpacked.rename(target)
        except OSError:
            if not target.is_dir():
                raise
            verify_folder(target, asset)  # A concurrent restore may have finished first.
    print(f"Installed {count} verified files in {target}", flush=True)
    return target


def check_training(models, training):
    import gzip

    import numpy as np
    import torch

    from sts2rl.return_policy import ReturnPolicy
    from sts2rl.run_bundle import load_bundle
    from sts2rl.run_policy import RunWeights
    from sts2rl.tactical_student import TacticalStudent, pack

    for policy in sorted(models.glob("*/policy.json")):
        load_bundle(policy)
    _, incumbent = load_bundle(models / "incumbent/policy.json")
    adviser = ReturnPolicy(training / "checkpoints/returns/returns.pt")
    if adviser.prior.weights != RunWeights.load(incumbent["weights"]):
        raise ValueError("Released return adviser does not use its training feature weights")
    student = TacticalStudent(incumbent["tactical_student"])
    labels = sorted((training / "imitation/planner/candidate").glob("run-*/actions.jsonl.gz"))
    for label in labels:
        with gzip.open(label, "rt", encoding="utf-8") as stream:
            first = stream.readline()
        if first:
            decision = json.loads(first)
            break
    else:
        raise ValueError("No native teacher decision in the training release")
    with torch.inference_mode():
        scores = student.model(*pack([decision], student.vocab))
    if scores.shape != (1, len(decision["choices"])) or not torch.isfinite(scores).all():
        raise ValueError("Neural inference failed on an archived decision")

    info = json.loads((training / "training.json").read_text(encoding="utf-8"))
    collections = [training / "rooms" / key for key in info["room_collections"]]
    reference = json.loads((models / "development-late-room-model.json").read_text(encoding="utf-8"))
    with TemporaryDirectory(prefix="silent-route-check-") as temp:
        model = Path(temp) / "routes.json"
        run = subprocess.run(
            [sys.executable, str(ROOT / "scripts/fit-room-model.py"), "--survival",
             *map(str, collections), "--output", str(model)],
            check=True, stdout=subprocess.PIPE, text=True,
        )
        stats = json.loads(run.stdout)
        fitted = json.loads(model.read_text(encoding="utf-8"))
    expected = {
        "training_seeds": info["training_seeds"],
        "unconfirmed_episodes_excluded": len(info["excluded_unconfirmed"]),
        "transitions": info["room_transitions"],
    }
    if stats != expected or any(fitted[k] != reference[k] for k in ("cells", "boss_counts")):
        raise ValueError("Route training corpus or fitted room statistics differ from the release")
    for act in reference["boss_coefficients"]:
        np.testing.assert_allclose(
            fitted["boss_coefficients"][act], reference["boss_coefficients"][act], rtol=1e-8, atol=1e-9,
        )
    print(f"Verified neural inference, return feature weights and {stats['transitions']:,} refitted room transitions.")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    p.add_argument("--artifacts", type=Path, default=ROOT / "artifacts", help="Destination parent")
    p.add_argument("--archives", type=Path, help="Read already-downloaded ZIPs from this directory")
    p.add_argument("--models-only", action="store_true", help="Install the model and benchmark archive")
    p.add_argument("--check-training", action="store_true", help="Refit the released route model and run neural inference")
    args = p.parse_args()
    if args.models_only and args.check_training:
        p.error("--check-training requires the training data")
    try:
        assets = json.loads(args.manifest.read_text(encoding="utf-8"))["assets"]
        models = restore(assets["models"], args.artifacts.resolve(), args.archives)
        if not args.models_only:
            training = restore(assets["training"], args.artifacts.resolve(), args.archives)
            if args.check_training:
                check_training(models, training)
    except (OSError, ValueError) as exc:
        p.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
