"""Compare a pre-boss adviser from the same natural Act 2 maps and macro seeds."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path

from sts2rl.act1 import save_json
from sts2rl.run_bundle import load_bundle
from sts2rl.run_evaluation import act_start, play_episode
from sts2rl.run_policy import RunWeights

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for flag in ("source", "bundle", "seed-lock", "host", "output"):
        p.add_argument("--" + flag, required=True, type=Path)
    p.add_argument("--workers", type=int, default=2)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    role, opts = load_bundle(args.bundle)
    weights = asdict(RunWeights.load(opts["weights"]))
    lock = json.loads(args.seed_lock.read_bytes())["seeds"]["development"]
    cases = {
        r["seed"]: (f, r)
        for f in args.source.glob("run-*/result.json")
        if (r := json.loads(f.read_bytes()))["status"] == "complete"
    }
    if set(cases) != set(lock):
        raise ValueError("Expected all natural development episodes from the locked seed list")
    tasks, roots = [], {}
    for index, seed in enumerate(lock):
        f, r = cases[seed]
        if not r["a1_clear"]:
            continue
        trace = f.parent / "game/rpc.jsonl"
        fork = act_start(trace, 2)
        roots[seed] = fork.expected_digest
        tasks.append(
            (
                ROOT,
                args.host.resolve(),
                args.output / "candidate" / f"run-{index:04d}",
                seed,
                index,
                role,
                weights,
                opts.get("micro"),
                {
                    **opts,
                    "start_trace": str(trace),
                    "curriculum_act": 2,
                    "seeded_acts": True,
                    "rooms": True,
                },
            )
        )
    save_json(
        args.output / "openings.json",
        {
            "roots": roots,
            "bundle_sha256": sha256(args.bundle.read_bytes()).hexdigest(),
            "host_sha256": sha256(args.host.read_bytes()).hexdigest(),
            "natural_development_seeds": len(lock),
        },
    )
    with ProcessPoolExecutor(args.workers) as pool:
        rows = list(pool.map(play_episode, tasks))
    save_json(
        args.output / "report.json",
        {
            "starts": len(tasks),
            "complete": sum(r["status"] == "complete" for r in rows),
            "boss_entries": sum(any(a == 2 for a, _ in r["boss_fights"]) for r in rows),
            "act3_entries": sum(r["a2_clear"] for r in rows),
            "wins": sum(r["win"] for r in rows),
            "mean_floor": sum(17 if r["a2_clear"] else r["floor"] for r in rows)
            / max(1, len(rows)),
        },
    )


if __name__ == "__main__":
    main()
