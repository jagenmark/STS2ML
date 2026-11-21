"""Play indexed Silent lobbies from the beginning and check any registered Act 3 entry."""

import argparse
import hashlib
import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

from sts2rl.act1 import save_json
from sts2rl.run_bundle import load_bundle
from sts2rl.run_evaluation import act_start, play_episode
from sts2rl.run_policy import RunWeights

ROOT = Path(__file__).resolve().parents[1]


def play(task):
    entry, host, bundle, output = task
    seed, index = entry["seed"], entry["index"]
    role, opts = load_bundle(bundle)
    folder = output / seed
    row = play_episode(
        (
            ROOT,
            host,
            folder,
            seed,
            index,
            role,
            asdict(RunWeights.load(opts["weights"])),
            opts.get("micro"),
            {
                **opts,
                "rooms": True,
                "seeded_acts": entry["act_list"] == "seeded",
                "ascension": entry.get("ascension", 10),
            },
        )
    )
    if row["status"] != "complete":
        raise ValueError(f"Failed to finish {seed}: {row.get('error')}")
    reached = act_start(folder / "game/rpc.jsonl", 3).expected_digest if row["a2_clear"] else None
    if "map_digest" in entry and reached != entry["map_digest"]:
        raise ValueError(f"Act 3 entry diverged on {seed}")
    return {
        "seed": seed,
        "index": index,
        "act_list": entry["act_list"],
        "map_digest": reached,
        "boss_fights": row["boss_fights"],
        "win": row["win"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("entries", "host", "bundle", "output"):
        parser.add_argument("--" + key, required=True, type=Path)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    entries = json.loads(args.entries.read_bytes())
    if len({e["seed"] for e in entries}) != len(entries) or any(
        e["act_list"] not in ("default", "seeded") or type(e["index"]) is not int for e in entries
    ):
        raise ValueError("A distinct seed, original index and lobby act list are required")
    args.output.mkdir(parents=True, exist_ok=False)
    save_json(
        args.output / "design.json",
        {
            k + "_sha256": hashlib.sha256(path.read_bytes()).hexdigest()
            for k, path in [("entries", args.entries), ("bundle", args.bundle), ("host", args.host)]
        },
    )
    with ProcessPoolExecutor(args.workers) as pool:
        rows = list(
            pool.map(play, [(e, args.host.resolve(), args.bundle, args.output) for e in entries])
        )
    save_json(args.output / "games.json", rows)


if __name__ == "__main__":
    main()
