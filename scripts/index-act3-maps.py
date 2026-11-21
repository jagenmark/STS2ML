"""Index true Act 3 arrivals in scored natural lobbies and save their physical entry histories."""

import argparse
import gzip
import json
from pathlib import Path

from sts2rl.act1 import save_json
from sts2rl.run_evaluation import act_start


def clip(source, target):
    fork = act_start(source, 3)
    act, last_row = 1, -1
    with (
        source.open(encoding="utf-8") as stream,
        target.open("x", encoding="utf-8", newline="\n") as out,
    ):
        for line in stream:
            r = json.loads(line)
            out.write(line)
            cmd = r["command"]
            if cmd.get("action") == "select_map_node":
                row = cmd["args"]["row"]
                act += int(row < last_row)
                last_row = row
                if act == 3:
                    break
    if act_start(target, 3) != fork:
        raise ValueError("Exported Act 3 map lost its physical history")
    return fork


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ("source", "output"):
        p.add_argument("--" + arg, required=True, type=Path)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--seed-lock", type=Path)
    group.add_argument(
        "--entries", type=Path, help="Explicit indexed lobbies for historical development"
    )
    p.add_argument("--partition", choices=("train", "development", "test"), required=True)
    a = p.parse_args()
    if a.seed_lock:
        registry = json.loads(a.seed_lock.read_bytes())["seeds"]
        seeds = registry[a.partition]
        if len(set(sum(registry.values(), []))) != sum(map(len, registry.values())):
            raise ValueError("Overlapping registered seeds")
        expected = {s: i for i, s in enumerate(seeds)}
    else:
        entries = json.loads(a.entries.read_bytes())
        expected = {e["seed"]: e["index"] for e in entries}
        if len(expected) != len(entries):
            raise ValueError("Duplicate entries")
    results = sorted(a.source.glob("*/result.json"))
    records = {}
    for path in results:
        row = json.loads(path.read_bytes())
        seed = row["seed"]
        if (
            seed not in expected
            or seed in records
            or row["index"] != expected[seed]
            or row["status"] != "complete"
            or row["ascension"] != 10
            or row["start_act"] != 1
        ):
            raise ValueError(f"Unexpected or incomplete natural lobby {seed}")
        records[seed] = (path, row)
    if set(records) != set(expected):
        raise ValueError(f"Missing {len(set(expected) - set(records))} registered games")
    a.output.mkdir(parents=True, exist_ok=False)
    maps = a.output / "maps"
    maps.mkdir()
    registered, arrivals = [], []
    with gzip.open(a.output / "games.jsonl.gz", "wt", encoding="utf-8") as games:
        for seed, (path, row) in sorted(records.items()):
            summary = {
                k: row[k]
                for k in (
                    "seed",
                    "index",
                    "act_list",
                    "act",
                    "floor",
                    "a1_clear",
                    "a2_clear",
                    "win",
                    "boss_fights",
                    "last_enemies",
                )
            }
            games.write(json.dumps(summary, separators=(",", ":")) + "\n")
            if not row["a2_clear"]:
                continue
            target = maps / seed
            target.mkdir()
            fork = clip(path.parent / "game/rpc.jsonl", target / "rpc.jsonl")
            entry = {
                "seed": seed,
                "index": row["index"],
                "partition": a.partition,
                "act_list": row["act_list"],
                "map_digest": fork.expected_digest,
            }
            registered.append(entry)
            arrivals.append({**entry, "boss_fights": row["boss_fights"], "win": row["win"]})
    save_json(maps / "index.json", registered)
    save_json(a.output / "entries.json", arrivals)
    print(f"{len(records)} complete natural games, {len(arrivals)} Act 3 arrivals")


if __name__ == "__main__":
    main()
