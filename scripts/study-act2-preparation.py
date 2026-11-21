"""Compare frozen card-draft policies from identical naturally reached Act 2 maps."""
import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

from sts2rl.act1 import save_json
from sts2rl.native import digest
from sts2rl.run_bundle import load_bundle
from sts2rl.run_evaluation import act2_start, play_episode
from sts2rl.run_policy import RunWeights

ROOT = Path(__file__).resolve().parents[1]


def play(task):
    entry, trace, folder, host, bundle = task
    role, opts = load_bundle(bundle)
    fork = act2_start(trace)
    if fork.expected_digest != entry["map_digest"] or fork.specification["seed"] != entry["seed"]:
        raise ValueError("Act 2 starting point differs from the frozen map")
    result = play_episode((ROOT, host, folder, entry["seed"], entry["index"], role,
                           asdict(RunWeights.load(opts["weights"])), opts.get("micro"),
                           {**opts, "seeded_acts": True, "start_trace": trace, "curriculum_act": 2, "rooms": True}))
    return {k:result.get(k) for k in ("seed","status","act","floor","a2_clear","win","boss_fights","error")}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--openings", required=True, type=Path)
    p.add_argument("--bundles", required=True, type=Path, nargs="+")
    p.add_argument("--host", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--workers", type=int, default=3)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    entries = json.loads((a.openings/"index.json").read_bytes())
    if len({r["seed"] for r in entries}) != len(entries) or any(r["partition"] not in ("train","development") for r in entries):
        raise ValueError("Expected distinct training and development seeds")
    manifest = {"openings_sha256":digest(entries), "bundles":{b.parent.name:digest(json.loads(b.read_bytes())) for b in a.bundles}}
    save_json(a.output/"design.json",manifest)
    tasks = [(r,a.openings/r["seed"]/"rpc.jsonl",a.output/b.parent.name/r["seed"],a.host.resolve(),b)
             for r in entries for b in a.bundles]
    with ProcessPoolExecutor(a.workers) as pool:
        for i, row in enumerate(pool.map(play,tasks),1):
            if row["status"] != "complete":
                raise ValueError(str(row))
            if i%12==0 or i==len(tasks):
                print(i,len(tasks),flush=True)


if __name__=="__main__":
    main()
