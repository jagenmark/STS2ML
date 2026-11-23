"""Audited natural Silent A10 episodes on the locked CSV5 census and dev panels."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from unittest.mock import patch

from sts2rl.combat_search_v2 import episode_summary
from sts2rl.run_bundle import load_bundle
from sts2rl.run_evaluation import play_episode
from sts2rl.run_policy import RunWeights

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "docs/combat-search-v2/v61-cohorts.json"
POLICY = ROOT / "releases/silent-a10-v2-tactics/challenger/policy.json"
ARMS = ("v5", "hallways", "boss-safe", "heuristic")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Measurements(episode_summary.EpisodeSummary):
    """Read-only post-step measurements. None of these fields reach the controller."""

    def __init__(self):
        super().__init__()
        self.fights = []
        self.entry_hp = None

    def observe(self, before, after, fallback):
        previous = self.fight
        super().observe(before, after, fallback)
        if not before.get("in_combat"):
            return
        view = before.get("combat_state", before)
        act, floor, room = self.fight
        if previous != self.fight:
            self.entry_hp = view["player"]["hp"]
        group = "act1" if act == 1 else "act2_" + room.lower() if act == 2 and room in ("Monster", "Elite") else None
        eligible = (before["decision"] != "combat_play" or any(c["can_play"] for c in view["hand"])
                    or any(p["can_use"] for p in view["player"].get("potions", ())))
        if group and eligible and fallback is not None:
            self.coverage[group][fallback or "covered"] += 1
            if act == 2:
                self.coverage[group + "/" + self.formation][fallback or "covered"] += 1
        if not after.get("in_combat") or after["decision"] == "game_over":
            died = after["decision"] == "game_over" and not after.get("victory")
            self.fights.append([act, floor, room, self.formation, self.entry_hp,
                                0 if died else after["player"]["hp"], not died])


def episode(job):
    output, host, arm, config, index, seed, mode = job
    role, options = load_bundle(POLICY)
    if arm != "v5":
        options["combat_search_v2_config"] = str(config)
    if arm == "heuristic":
        options.pop("combat_value_v2")
    measurements = Measurements()
    with TemporaryDirectory(dir=output) as tmp, patch.object(episode_summary, "EpisodeSummary", return_value=measurements):
        folder = Path(tmp) / "episode"
        row = play_episode((ROOT, host, folder, seed, index, role, asdict(RunWeights.load(options["weights"])),
                            None, {**options, "seeded_acts": mode == "seeded", "compact_combat_summary": True,
                                   "audit_compact": True, "audit_frozen_right_hand": arm == "v5",
                                   "time_combat_decisions": True}))
        row["arm"] = arm
        row["fights"] = measurements.fights
        row["combat_ns"] = json.loads((folder / "combat-decision-ns.json").read_bytes())
        row.pop("late_fights", None)
        return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=ARMS, required=True)
    parser.add_argument("--cohort", choices=("CENSUS", "DEV"), required=True)
    parser.add_argument("--workers", type=int, choices=(12,), default=12)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    host = Path(os.environ["CSV2DEV_HOST"])
    game = ROOT / "artifacts/upstreams/sts2-cli/lib/sts2.dll"
    pins = {host: "7408d040c28416331279a84e299b52ff35086d80b4cb9711aefd0f91168d8f20",
            game: "14b57dbaee1b58cb919625a662831054fd714b3b75b13b7449eac0e95b98a3e4",
            POLICY: "a686db12c8b217bd476ea5c8e60cf6f486b060665536ef9354e8f09c21c81fcb",
            LOCK: "c49e77b83a761acbc68f3e5f6e8e07ec076ce65493acabe8790e7b0b79a3e11d"}
    for path, expected in pins.items():
        if sha(path) != expected:
            raise ValueError(f"Integrity check failed for {path}")
    if any(os.environ.get(k) != "1" for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS")) or os.environ.get("DOTNET_STARTUP_HOOKS"):
        raise ValueError("Use single-threaded BLAS/OpenMP with the unmodified native host")
    panel = json.loads(LOCK.read_bytes())[args.cohort]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    config = POLICY.with_name("combat_search_v2_config.json")
    stem = args.cohort.lower() + "-" + args.arm
    if args.arm != "v5":
        settings = json.loads(config.read_bytes())
        settings["v61_act2_hallways_act3"] = True
        settings["v61_boss_safe"] = args.arm in ("boss-safe", "heuristic")
        config = output / (stem + "-config.json")
        config.write_bytes(json.dumps(settings, sort_keys=True).encode())
    manifest = dict(arm=args.arm, cohort=args.cohort, workers=args.workers, git=subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(), host_sha256=sha(host),
        game_sha256=sha(game), policy_sha256=sha(POLICY), lock_sha256=sha(LOCK), config_sha256=sha(config),
        model_sha256=None if args.arm == "heuristic" else sha(POLICY.with_name("combat_value_v2.npz")),
        openblas_threads=1, omp_threads=1)
    jobs = [(output, host, args.arm, config, *item) for item in panel]
    with (output / (stem + ".jsonl.gz")).open("xb") as file, gzip.GzipFile(
        filename="", mode="wb", fileobj=file, mtime=0) as stream, ProcessPoolExecutor(args.workers) as pool:
        (output / (stem + "-manifest.json")).write_text(json.dumps(manifest, indent=2))
        futures = [pool.submit(episode, job) for job in jobs]
        counts = Counter()
        for i, future in enumerate(as_completed(futures), 1):
            row = future.result()
            stream.write((json.dumps(row, separators=(",", ":")) + "\n").encode())
            stream.flush()
            if row["status"] != "complete" or row.get("abandoned"):
                raise ValueError(row.get("error", row["status"]))
            counts.update(row["native"])
            if i % 16 == 0 or row["mismatches"]:
                print(i, dict(counts), row["seed"], flush=True)


if __name__ == "__main__":
    main()
