"""Run the locked Silent A10 release suite with compact per-lobby receipts."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
from tempfile import TemporaryDirectory

from sts2rl.act1 import save_json
from sts2rl.deployed_controller import DeployedController
from sts2rl.run_bundle import load_bundle
from sts2rl.run_evaluation import play_episode
from sts2rl.run_policy import RunWeights

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "releases/silent-a10-v2-tactics"
ARMS = ("all_v2_p1_v4", "all_v2_search_v5", "all_v2_search_heur_v5")
HOST = "7408d040c28416331279a84e299b52ff35086d80b4cb9711aefd0f91168d8f20"
GAME = "14b57dbaee1b58cb919625a662831054fd714b3b75b13b7449eac0e95b98a3e4"
BUNDLE_HASHES = dict(zip(ARMS, (
    "8636337a6082264bffffe9a79b50528bdf30ed9096b74ff33fd20a8e844fa51b",
    "a686db12c8b217bd476ea5c8e60cf6f486b060665536ef9354e8f09c21c81fcb",
    "85de8c968e2b973a2928719bedab2697ddd305e0c55c2654064fcf5f9ebd93c4",
), strict=True))


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def episode(job):
    output, host, arm, suite, index, seed, mode, role, weights, settings = job
    with TemporaryDirectory(dir=output) as scratch:
        row = play_episode((ROOT, host, Path(scratch) / "run", seed, index, role, weights, None,
                            {**settings, "seeded_acts": mode == "seeded", "compact_combat_summary": True}))
    row.update(arm=arm, suite=suite)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, choices=(12,), default=12)
    parser.add_argument("--smoke", action="store_true", help="Use only fresh, unofficial names")
    args = parser.parse_args()
    host = args.host.resolve()
    if checksum(host) != HOST or checksum(ROOT / "artifacts/upstreams/sts2-cli/lib/sts2.dll") != GAME:
        raise ValueError("Pinned host or game assembly mismatch")
    if any(os.environ.get(k) != "1" for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS")):
        raise ValueError("Set both BLAS and OMP thread limits to one")
    if os.environ.get("DOTNET_STARTUP_HOOKS"):
        raise ValueError("Unexpected native startup hook")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    build = runpy.run_path(str(ROOT / "scripts/build-batch1-challengers.py"))["build_batch1_bundle"]
    seed_order = json.loads((RELEASE / "benchmark.json").read_bytes())["seed_order"]
    lock = hashlib.sha256(json.dumps(seed_order, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if lock != "1279618f5423cfa7734a0fa04db7596b4179c481981a98663aee6235ea146a94":
        raise ValueError("Official lobby order, macro indices or act-list modes changed")
    if {k: len(v) for k, v in seed_order.items()} != {"val256": 256, "seeded128": 128, "rep512": 512}:
        raise ValueError("Unexpected suite sizes")
    if len({seed for rows in seed_order.values() for _, seed, _ in rows}) != 896:
        raise ValueError("Seed overlap")
    if args.smoke:
        seed_order = {"smoke": [[i, f"CSV5PACKAGING_{i:04d}", mode]
                                for i, mode in enumerate(("default", "seeded"))]}
    arms = {}
    bundles = {}
    for arm in ARMS:
        path = build(ROOT / "releases/silent-a10-mecha-knight/challenger/policy.json", output / arm, profile=arm)
        role, settings = load_bundle(path)
        DeployedController.from_bundle(path)
        bundles[arm] = checksum(path)
        arms[arm] = role, asdict(RunWeights.load(settings["weights"])), settings
    if bundles != BUNDLE_HASHES:
        raise ValueError("Pre-registered bundle checksums differ")
    save_json(output / "manifest.json", {
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "bundles": bundles, "host": HOST, "game": GAME, "workers": args.workers,
        "blas_threads": 1, "omp_threads": 1, "seed_order": seed_order, "official_registry_sha256": lock,
    })
    jobs = [(output, host, arm, suite, index, seed, mode, *arms[arm])
            for suite, rows in seed_order.items() for index, seed, mode in rows for arm in ARMS]
    errors = 0
    with ProcessPoolExecutor(args.workers) as pool, (output / "episodes.jsonl").open("x", encoding="utf-8") as receipts:
        for i, row in enumerate(pool.map(episode, jobs), 1):
            receipts.write(json.dumps(row, separators=(",", ":")) + "\n")
            receipts.flush()
            errors += row["status"] != "complete" or bool(row.get("abandoned"))
            if i % 48 == 0 or i == len(jobs):
                print(f"{i}/{len(jobs)} receipts, {errors} incomplete", flush=True)
    if errors:
        raise RuntimeError(f"{errors} incomplete episodes")


if __name__ == "__main__":
    main()
