"""Build or verify the portable data and checkpoints for the Silent A10 boss experiment."""

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import zipfile

from sts2rl.run_bundle import load_bundle

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "releases/silent-a10-boss-conversion"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def build(study, destination):
    sources = {}

    def file(name, path):
        if name in sources or not path.is_file():
            raise ValueError(f"Missing or duplicate archive entry {name}")
        sources[name] = path

    def direct(prefix, base, patterns):
        for pattern in patterns:
            paths = sorted(base.glob(pattern))
            for path in paths:
                if path.is_file():
                    file(prefix + "/" + path.name, path)

    for name, folder in (
        ("incumbent", ROOT / "releases/silent-a10-encounter-draft/challenger"),
        ("challenger", RELEASE / "challenger"),
    ):
        load_bundle(folder / "policy.json")
        direct("models/" + name, folder, ["*.json"])
    for name in (
        "selection",
        "seed-lock",
        "replication-seed-lock",
        "selection-rule",
        "fit",
        "diagnostics",
        "draft-experiment",
        "native-mechanics",
    ):
        file(name + ".json", RELEASE / (name + ".json"))
    file("replication-selection.json", study / "replication-selection.json")
    file("windows-mechanics.json", study / "windows-mechanics.json")
    file("README.md", RELEASE / "README.md")
    for name, folder in (
        ("training", "boss-training"),
        ("development", "boss-dev"),
        ("previous-development", "boss-previous-dev"),
        ("transfer", "boss-fresh"),
    ):
        direct("roots/" + name, study / folder, ["*.json.gz", "*.json"])
    for name in (
        "valid-training",
        "valid-development",
        "camp-training",
        "camp-development",
        "camp-recovered-training",
        "camp-recovered-development",
        "transfer",
        "upgrade-training",
        "upgrade-development",
    ):
        direct("labels/" + name, study / name, ["*.json.gz", "*.json"])
    direct("bowlbug", study / "bowlbug", ["*.json"])
    for path in (study / "bowlbug/runs").glob("*/*/game/rpc.jsonl"):
        file("bowlbug/runs/" + path.relative_to(study / "bowlbug/runs").as_posix(), path)
        result = path.parent.parent / "result.json"
        file("bowlbug/runs/" + result.relative_to(study / "bowlbug/runs").as_posix(), result)
    for name in (
        "corrected-plans.json",
        "selected-plans.json",
        "prep-input.zip",
        "prep-out-logs.zip",
        "upgrade-report.json",
    ):
        file("experiments/" + name, study / name)
    for name, replays in (("primary", "replays"), ("replication", "replication-replays")):
        for f in ("test-games.jsonl.gz", "test-action-histories.jsonl.gz", "test-report.json"):
            file(f"evaluation/{name}/{f}", study / (name + "-evidence") / f)
        for f in ("baseline.json", "challenger.json", "summary.json"):
            file(f"evaluation/{name}/replays/{f}", study / replays / f)
        file(f"evaluation/{name}/bosses.json", study / (name + "-bosses.json"))
    manifest = {
        "format": 1,
        "experiment": "silent-a10-boss-conversion",
        "selection_commit": "ff66b0a19e156f212bd382694f3e4f3286066105",
        "training_collector_commit": "9ee8e8640b15145091c50b9ff54f966b690991f8",
        "files": {},
    }
    with zipfile.ZipFile(destination, "x", zipfile.ZIP_DEFLATED, compresslevel=7) as archive:
        for name, path in sorted(sources.items()):
            data = path.read_bytes()
            manifest["files"][name] = {"bytes": len(data), "sha256": sha(data)}
            archive.writestr(name, data)
        archive.writestr("archive-manifest.json", json.dumps(manifest, indent=2) + "\n")


def verify(path, refit=False):
    with zipfile.ZipFile(path) as z, tempfile.TemporaryDirectory() as folder:
        names = z.namelist()
        if len(names) != len(set(names)) or any(
            PurePosixPath(n).is_absolute() or ".." in PurePosixPath(n).parts or "\\" in n
            for n in names
        ):
            raise ValueError("Unsafe or repeated archive name")
        manifest = json.loads(z.read("archive-manifest.json"))
        if manifest.get("format") != 1 or set(names) != set(manifest["files"]) | {
            "archive-manifest.json"
        }:
            raise ValueError("Archive inventory mismatch")
        for name, expected in manifest["files"].items():
            data = z.read(name)
            if len(data) != expected["bytes"] or sha(data) != expected["sha256"]:
                raise ValueError("Checksum mismatch in " + name)
        root = Path(folder)
        z.extractall(root)
        frozen = json.loads((root / "selection.json").read_bytes())
        for arm, key in (("incumbent", "incumbent_sha256"), ("challenger", "policy_sha256")):
            policy = root / "models" / arm / "policy.json"
            load_bundle(policy)
            if sha(policy.read_bytes()) != frozen[key]:
                raise ValueError("Frozen bundle mismatch")
        seen = set()
        summary = {}
        for name, lock in (
            ("primary", "seed-lock.json"),
            ("replication", "replication-seed-lock.json"),
        ):
            lock_data = json.loads(z.read(lock))
            seeds = lock_data["seeds"]["test"]
            if len(set(seeds)) != len(seeds) or len(seeds) != 1024 or seen.intersection(seeds):
                raise ValueError("Held-out seed registry mismatch")
            seen.update(seeds)
            base = f"evaluation/{name}/"
            games = [
                json.loads(line)
                for line in gzip.decompress(z.read(base + "test-games.jsonl.gz")).splitlines()
            ]
            histories = [
                json.loads(line)
                for line in gzip.decompress(
                    z.read(base + "test-action-histories.jsonl.gz")
                ).splitlines()
            ]
            if [r["seed"] for r in games] != seeds or [r["seed"] for r in histories] != seeds:
                raise ValueError("Missing natural episode or command history")
            report = json.loads(z.read(base + "test-report.json"))
            summary[name] = {}
            for arm in ("baseline", "challenger"):
                counts = Counter()
                for r, h in zip(games, histories, strict=True):
                    row = r[arm]
                    commands = h["paths"][h["arms"][arm]]
                    spec = {"seed": r["seed"], "ascension": 10, "act_list": "seeded"}
                    fingerprint = sha(
                        json.dumps(
                            [spec, commands, row["terminal"], row["win"]],
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode()
                    )
                    if fingerprint != row["physical_history_sha256"]:
                        raise ValueError("Unbound physical history for " + r["seed"])
                    for k in ("a1_clear", "boss2", "a2_clear", "win"):
                        counts[k] += bool(row[k])
                    counts["terminal_replays"] += bool(row["verified"])
                if any(report["arms"][arm][k] != v for k, v in counts.items()):
                    raise ValueError("Held-out counts differ from matched games")
                summary[name][arm] = dict(counts)
        for name in (
            "valid-training",
            "valid-development",
            "camp-training",
            "camp-development",
            "transfer",
        ):
            labels = json.loads(z.read("labels/" + name + "/design.json"))
            if set(labels["seeds"]) & seen or not labels.get("label_provenance"):
                raise ValueError("Invalid training partition or teacher provenance")
        if refit:
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/fit-act2-boss-conversion.py"),
                    "--training",
                    str(root / "labels/valid-training"),
                    "--development",
                    str(root / "labels/valid-development"),
                    "--camp-training",
                    str(root / "labels/camp-training"),
                    "--camp-development",
                    str(root / "labels/camp-development"),
                    "--bundle",
                    str(root / "models/incumbent/policy.json"),
                    "--seed-lock",
                    str(root / "seed-lock.json"),
                    "--output",
                    str(root / "refit"),
                ],
                check=True,
            )
            if sha((root / "refit/challenger/policy.json").read_bytes()) != frozen["policy_sha256"]:
                raise ValueError("Refitted parameters differ from the frozen checkpoint")
    print(
        json.dumps(
            {
                "files": len(names),
                "archive_sha256": sha(path.read_bytes()),
                "scores": summary,
                "refit": refit,
            }
        )
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=("build", "verify"))
    p.add_argument("--archive", required=True, type=Path)
    p.add_argument("--study", type=Path)
    p.add_argument("--refit", action="store_true")
    a = p.parse_args()
    if a.mode == "build":
        if not a.study:
            p.error("--study is required for build")
        build(a.study, a.archive)
    verify(a.archive, a.refit)


if __name__ == "__main__":
    main()
