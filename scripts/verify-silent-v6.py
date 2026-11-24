"""Evaluate a frozen pair on FINAL768, then optionally on the official continuity panel."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import gzip
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
from tempfile import TemporaryDirectory

from sts2rl.deployed_controller import DeployedController
from sts2rl.run_bundle import load_bundle
from sts2rl.run_evaluation import play_episode
from sts2rl.run_policy import RunWeights

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs/combat-search-v2"
RELEASE = ROOT / "releases/silent-a10-v2-tactics"
LOCK = DOC / "v6-final768-lock.json"
LOCK_SHA = "0afc2bac154b2bf564c41b36cf54ca3337b4d8cd6231a411e3d7567093735aa0"
PINS = {"v5": "a686db12c8b217bd476ea5c8e60cf6f486b060665536ef9354e8f09c21c81fcb",
        "v6": "4b5fe32e78a96ca656cca805f316410b19baa9c4f2c227d25b77a6d1306c93a9"}
HOST_SHA = "7408d040c28416331279a84e299b52ff35086d80b4cb9711aefd0f91168d8f20"
GAME_SHA = "14b57dbaee1b58cb919625a662831054fd714b3b75b13b7449eac0e95b98a3e4"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def registry(panel):
    if sha(LOCK.read_bytes()) != LOCK_SHA:
        raise ValueError("FINAL768 lock checksum mismatch")
    if panel == "final768":
        return [(panel, *triple) for triple in json.loads(LOCK.read_bytes())]
    official = json.loads((RELEASE / "benchmark.json").read_bytes())["seed_order"]
    if sha(json.dumps(official, sort_keys=True, separators=(",", ":")).encode()) != (
        "1279618f5423cfa7734a0fa04db7596b4179c481981a98663aee6235ea146a94"
    ):
        raise ValueError("Official continuity lock checksum mismatch")
    return [(suite, *triple) for suite, triples in official.items() for triple in triples]


def paired(job):
    output, host, triple, arms = job
    suite, index, seed, mode = triple
    pair = []
    for arm, role, weights, options in arms:
        with TemporaryDirectory(dir=output) as tmp:
            folder = Path(tmp) / "episode"
            row = play_episode((ROOT, host, folder, seed, index, role, weights, None,
                                {**options, "seeded_acts": mode == "seeded", "compact_combat_summary": True,
                                 "time_combat_decisions": True, "audit_compact": True,
                                 "audit_frozen_right_hand": arm == "v5"}))
            keys = ("index", "seed", "act_list", "act_names", "status", "start_act", "ascension", "act",
                    "floor", "steps", "a1_clear", "a2_clear", "boss_fights", "win", "native", "mismatches")
            receipt = {k: row.get(k) for k in keys}
            receipt.update(arm=arm, suite=suite, error=row.get("error"), abandoned=bool(row.get("abandoned")),
                           a2_fights=[x for x in row.get("late_fights", []) if x[0] == 2])
            timings = json.loads((folder / "combat-decision-ns.json").read_bytes())
            pair.append((receipt, Counter((ns + 500) // 1000 for ns in timings)))
    return pair


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--panel", choices=("final768", "pooled896"), required=True)
    p.add_argument("--workers", type=int, choices=(12,), default=12)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    host = Path(os.environ["CSV2DEV_HOST"])
    game = ROOT / "artifacts/upstreams/sts2-cli/lib/sts2.dll"
    if (sha(host.read_bytes()) != HOST_SHA or sha(game.read_bytes()) != GAME_SHA or os.getenv("DOTNET_STARTUP_HOOKS")
            or any(os.getenv(k) != "1" for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS"))):
        raise ValueError("Runtime or thread limits differ from protocol")
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT).strip():
        raise ValueError("Commit the complete evaluation before opening the panel")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    panel = registry(args.panel)
    root = args.output.resolve()
    report = runpy.run_path(str(ROOT / "scripts/report-silent-v6-release.py"))
    if args.panel == "pooled896" and not report["analyze"](root / "final768", registry("final768"))["passes"]:
        raise ValueError("POOLED896 requires a complete passing FINAL768")
    out = root / args.panel
    out.mkdir(parents=True, exist_ok=False)
    build = runpy.run_path(str(ROOT / "scripts/build-batch1-challengers.py"))["build_batch1_bundle"]
    arms = []
    for arm, checksum in PINS.items():
        path = build(ROOT / "releases/silent-a10-mecha-knight/challenger/policy.json", out / arm,
                     profile="all_v2_search_" + arm)
        if sha(path.read_bytes()) != checksum:
            raise ValueError(f"Frozen {arm} manifest checksum mismatch")
        DeployedController.from_bundle(path)
        role, options = load_bundle(path)
        arms.append((arm, role, asdict(RunWeights.load(options["weights"])), options))
    manifest = dict(commit=head, panel=args.panel, lock=LOCK_SHA, bundles=PINS, host=HOST_SHA, game=GAME_SHA,
                    workers=args.workers, blas_threads=1, omp_threads=1, retries=0)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    hists = {arm: Counter() for arm in PINS}
    with gzip.open(out / "episodes.jsonl.gz", "xt", encoding="utf8") as receipts, ProcessPoolExecutor(12) as pool:
        for start in range(0, len(panel), 12):
            stop = False
            jobs = [(out, host, triple, arms) for triple in panel[start:start + 12]]
            for pair in pool.map(paired, jobs):
                for row, hist in pair:
                    receipts.write(json.dumps(row, separators=(",", ":")) + "\n")
                    hists[row["arm"]].update(hist)
                    stop |= row["status"] != "complete" or row["abandoned"]
                    stop |= args.panel == "final768" and row["arm"] == "v6" and bool(row["mismatches"])
            receipts.flush()
            print(args.panel, min(start + 12, len(panel)), "pairs; stop =", stop, flush=True)
            if stop:
                break
    with gzip.open(out / "latency-us.json.gz", "wt") as f:
        json.dump(hists, f, separators=(",", ":"))
    print(json.dumps(report["analyze"](out, panel), indent=2))


if __name__ == "__main__":
    main()
