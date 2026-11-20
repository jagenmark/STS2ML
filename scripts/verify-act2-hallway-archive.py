"""Verify the portable Act 2 policy, held-out outcomes, and optionally replay one seed."""

import argparse
import gzip
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from sts2rl.native import NativeSession, ReplayFork, digest
from sts2rl.run_bundle import load_bundle

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive", type=Path)
    p.add_argument("--host", type=Path)
    p.add_argument("--seed", help="An archived locked test seed to replay on the supplied host")
    a = p.parse_args()
    folder = a.archive
    for line in (folder / "SHA256SUMS").read_text().splitlines():
        checksum, name = line.split("  ", 1)
        if sha256((folder / name).read_bytes()).hexdigest() != checksum:
            raise ValueError(f"Checksum mismatch: {name}")
    with ZipFile(folder / "policy.zip") as z, TemporaryDirectory() as tmp:
        for file in (folder / "challenger").iterdir():
            contents = z.read("challenger/" + file.name)
            if contents != file.read_bytes():
                raise ValueError("Inference package differs from the source files")
            (Path(tmp) / file.name).write_bytes(contents)
        load_bundle(Path(tmp) / "policy.json")
    lock = json.loads((folder / "seed-lock.json").read_bytes())
    groups = {k: set(v) for k, v in lock["seeds"].items()}
    if any(len(v) != len(lock["seeds"][k]) for k, v in groups.items()) or sum(
        map(len, groups.values())
    ) != len(set.union(*groups.values())):
        raise ValueError("Seed lists overlap or repeat")
    with gzip.open(folder / "test-games.jsonl.gz", "rt") as f:
        games = {r["seed"]: r for line in f if (r := json.loads(line))}
    if set(games) != groups["test"]:
        raise ValueError("Wrong test cohort")
    report = json.loads((folder / "test-report.json").read_bytes())
    for arm, tally in report["arms"].items():
        for key in ("a1_clear", "a2_clear", "boss2", "win"):
            if tally[key] != sum(r[arm][key] for r in games.values()):
                raise ValueError(f"Published metric differs for {arm}/{key}")
        if tally["terminal_replays"] != sum(r[arm]["verified"] for r in games.values()):
            raise ValueError("Wrong terminal replay count")
    selection = json.loads((folder / "selection.json").read_bytes())
    if (
        selection["candidate_sha256"]
        != sha256((folder / "challenger/policy.json").read_bytes()).hexdigest()
    ):
        raise ValueError("The packaged challenger differs from the frozen choice")
    print(f"Verified the Silent A10 policy and {len(games)} matched lobby seeds")
    if bool(a.host) != bool(a.seed):
        p.error("--host and --seed are used together")
    if a.seed:
        if a.seed not in games:
            p.error("Use a seed in the archived test split")
        with gzip.open(folder / "test-action-histories.jsonl.gz", "rt") as stream:
            history = next(row for line in stream if (row := json.loads(line))["seed"] == a.seed)
        commands = history["paths"][history["arms"]["challenger"]]
        expected = games[a.seed]["challenger"]
        spec = {"seed": a.seed, "ascension": 10, "act_list": "seeded"}
        with (
            TemporaryDirectory() as tmp,
            NativeSession(
                ROOT, Path(tmp) / "replay", host_path=a.host, act_list="seeded"
            ) as native,
        ):
            opening = native.reset(a.seed)
            if digest(opening) != expected["opening"]:
                raise ValueError(
                    "Different native lobby. Check the game build, standard unlocks, and "
                    "localization_eng five directories above Sts2Headless.dll."
                )
            state = native.restore(ReplayFork(spec, tuple(commands), expected["terminal"]))
            if (
                state["decision"] != "game_over"
                or state["victory"] != expected["win"]
                or digest(state) != expected["terminal"]
            ):
                raise ValueError("Native replay differs from the archived outcome")
        print(f"Replayed {a.seed} through all {len(commands)} decisions")


if __name__ == "__main__":
    main()
