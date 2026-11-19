"""Verify the portable Silent A10 encounter experiment and its embedded seed identities."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

from sts2rl.run_bundle import load_bundle


def verify(folder):
    for line in (folder / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        expected, name = line.split("  ", 1)
        path = folder / name
        if not path.resolve().is_relative_to(folder.resolve()):
            raise ValueError("Unexpected checksum path")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Archive checksum mismatch: {name}")
    bundle = folder / "challenger/policy.json"
    load_bundle(bundle)
    with ZipFile(folder / "policy.zip") as portable:
        for path in bundle.parent.glob("*.json"):
            if portable.read("challenger/" + path.name) != path.read_bytes():
                raise ValueError(f"Downloadable checkpoint differs from the checked-out {path.name}")
    selection = json.loads((folder / "selection.json").read_bytes())
    if hashlib.sha256(bundle.read_bytes()).hexdigest() != selection["bundle_sha256"]:
        raise ValueError("Bundle differs from the pre-test freeze")
    partitions = json.loads((folder / "seed-lock.json").read_bytes())["seeds"]
    test = set(partitions["test"])
    protected = test | set(partitions["development"])
    if len(protected) != sum(map(len, partitions.values())):
        raise ValueError("Repeated or overlapping reserved seeds")
    with ZipFile(folder / "training-state.zip") as archive:
        if archive.testzip() is not None:
            raise ValueError("Damaged training archive")
        for name in archive.namelist():
            if not name.endswith("/labels.json"):
                continue
            shard = json.loads(archive.read(name))
            seeds = {shard["seed"]} if "seed" in shard else set()
            for root in shard["roots"]:
                seeds.add(root["seed"] if "seed" in root else root["group"])
            if seeds & protected:
                raise ValueError(f"Reserved seed in fitting data: {name}")
    with ZipFile(folder / "draft-scores.zip") as archive:
        expected = {s + "/draft-scores.jsonl.gz" for s in test}
        if archive.testzip() is not None or set(archive.namelist()) != expected:
            raise ValueError("Incomplete draft score archive")
    with gzip.open(folder / "test-games.jsonl.gz", "rt", encoding="utf-8") as stream:
        games = {r["seed"]: r for r in map(json.loads, stream)}
    if set(games) != test:
        raise ValueError("Terminal receipt seed identities differ from the lock")
    seen = set()
    with gzip.open(folder / "test-action-histories.jsonl.gz", "rt", encoding="utf-8") as stream:
        for row in map(json.loads, stream):
            seed, arm = row["seed"], row["arm"]
            if (seed, arm) in seen:
                raise ValueError("Duplicate action history")
            seen.add((seed, arm))
            native = games[seed][arm]["replay"]
            if (
                row["start"].get("seed") != seed
                or row["opening_digest"] != games[seed]["opening_digest"]
                or (
                    native["verified"]
                    and (
                        row["terminal_digest"] != native["terminal"]
                        or len(row["history"]) != native["actions"]
                    )
                )
            ):
                raise ValueError("Action history differs from its native receipt")
    if seen != {(s, a) for s in test for a in ("release", "control", "candidate")}:
        raise ValueError("Missing full-game action histories")
    return len(seen), len(test)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "folder",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "releases/silent-a10-encounter-draft",
    )
    args = parser.parse_args()
    count, seeds = verify(args.folder)
    print(
        f"Verified the portable bundle, training split, {count} action histories and draft logs for {seeds} seeds."
    )
