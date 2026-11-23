"""Run an audited arm on the locked CSV4DEV lobbies."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import hashlib
import json
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from sts2rl.run_bundle import load_bundle
from sts2rl.run_evaluation import play_episode
from sts2rl.run_policy import RunWeights

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "releases/silent-a10-v2-tactics/challenger/policy.json"
LOCK = ROOT / "docs/combat-search-v2/v6-dev-lock.json"


def episode(job):
    output, host, arm, config, index, seed, mode = job
    role, settings = load_bundle(POLICY)
    if arm != "v5":
        settings["combat_search_v2_config"] = str(config)
    if arm == "heuristic":
        settings.pop("combat_value_v2")
    with TemporaryDirectory(dir=output) as scratch:
        folder = Path(scratch) / "episode"
        row = play_episode((ROOT, host, folder, seed, index, role, asdict(RunWeights.load(settings["weights"])),
                            None, {**settings, "seeded_acts": mode == "seeded", "compact_combat_summary": True,
                                   "audit_compact": True, "audit_frozen_right_hand": arm == "v5", "time_combat_decisions": True}))
        row["arm"] = arm
        row["combat_ns"] = json.loads((folder / "combat-decision-ns.json").read_bytes())
    return row


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--arm", choices=("v5", "schema3", "heuristic"), required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--workers", type=int, choices=(12,), default=12)
    args = p.parse_args()
    host = Path(os.environ["CSV2DEV_HOST"])
    assert sha(host) == "7408d040c28416331279a84e299b52ff35086d80b4cb9711aefd0f91168d8f20"
    assert sha(ROOT / "artifacts/upstreams/sts2-cli/lib/sts2.dll") == "14b57dbaee1b58cb919625a662831054fd714b3b75b13b7449eac0e95b98a3e4"
    assert all(os.environ[k] == "1" for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS"))
    assert not os.environ.get("DOTNET_STARTUP_HOOKS")
    assert sha(POLICY) == "a686db12c8b217bd476ea5c8e60cf6f486b060665536ef9354e8f09c21c81fcb"
    assert sha(LOCK) == "96d62dae6b90dd1086b387a64e721c35a47ae2aab17a5f2420fb6a7a2ca63964"
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    config = output / "v6-config.json"
    if args.arm != "v5":
        settings = json.loads(POLICY.with_name("combat_search_v2_config.json").read_bytes())
        config.write_text(json.dumps({**settings, "v6_late_coverage": True}))
    manifest = {"arm": args.arm, "workers": args.workers, "git": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(), "host_sha256": sha(host),
        "game_sha256": sha(ROOT / "artifacts/upstreams/sts2-cli/lib/sts2.dll"), "policy_sha256": sha(POLICY),
        "lock_sha256": sha(LOCK), "config_sha256": sha(config if args.arm != "v5" else
        POLICY.with_name("combat_search_v2_config.json")), "openblas_threads": 1, "omp_threads": 1}
    (output / (args.arm + "-manifest.json")).write_text(json.dumps(manifest, indent=2))
    jobs = [(output, host, args.arm, config, *row) for row in json.loads(LOCK.read_bytes())]
    with (output / (args.arm + ".jsonl")).open("x", encoding="utf8") as f, ProcessPoolExecutor(args.workers) as pool:
        for i, row in enumerate(pool.map(episode, jobs), 1):
            f.write(json.dumps(row, separators=(",", ":")) + "\n")
            f.flush()
            if row["status"] != "complete" or row.get("abandoned"):
                raise ValueError(row.get("error", row["status"]))
            if i % 16 == 0:
                print(i, flush=True)


if __name__ == "__main__":
    main()
