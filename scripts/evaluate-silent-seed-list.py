"""Play a contiguous shard of a locked natural A10 seed list with stable macro indices."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from sts2rl.act1 import save_json
from sts2rl.run_bundle import load_bundle
from sts2rl.run_evaluation import play_episode
from sts2rl.run_policy import RunWeights

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("seed-lock", "host", "output", "bundle"):
        p.add_argument("--"+name, required=True, type=Path)
    p.add_argument("--partition", choices=["train", "development", "test"], required=True)
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--stop", type=int)
    p.add_argument("--workers", type=int, default=3)
    a = p.parse_args()
    splits = json.loads(a.seed_lock.read_bytes())["seeds"]
    all_seeds = [s for split in splits.values() for s in split]
    seeds = splits[a.partition]
    stop = len(seeds) if a.stop is None else a.stop
    if len(all_seeds) != len(set(all_seeds)) or not 0 <= a.start < stop <= len(seeds):
        raise ValueError("Overlapping seeds or invalid seed interval")
    role, opts = load_bundle(a.bundle)
    weights = asdict(RunWeights.load(opts["weights"]))
    a.output.mkdir(parents=True, exist_ok=False)
    stamp = {k:hashlib.sha256(v.read_bytes()).hexdigest() for k,v in
             (("seed_lock",a.seed_lock),("bundle",a.bundle),("native_host",a.host))}
    save_json(a.output/"config.json", {**stamp,"start":a.start,"stop":stop,"partition":a.partition})
    tasks = [(ROOT,a.host.resolve(),a.output/role/f"run-{i:04d}",seeds[i],i,role,weights,
              opts.get("micro"),{**opts,"seeded_acts":True,"rooms":True}) for i in range(a.start,stop)]
    with ProcessPoolExecutor(a.workers) as pool:
        rows = list(pool.map(play_episode,tasks))
    errors = [r["seed"] for r in rows if r["status"] != "complete" or r["start_act"] != 1]
    save_json(a.output/"report.json",{"seeds":len(rows),"errors":errors})
    if errors:
        raise ValueError(f"Incomplete natural runs: {errors}")


if __name__=="__main__":
    main()
