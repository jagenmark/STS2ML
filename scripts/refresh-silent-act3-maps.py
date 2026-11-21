"""Replay historical training decisions to a boss, then use the frozen legal policy into Act 3."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import gzip
import json
from pathlib import Path

from sts2rl.act1 import save_json
from sts2rl.native import digest, legal_actions, selected_cards
from sts2rl.run_bundle import load_bundle
from sts2rl.run_evaluation import act_start, play_episode
from sts2rl.run_policy import RunWeights

ROOT = Path(__file__).resolve().parents[1]


def refresh(task):
    source, host, bundle, out = task
    with gzip.open(source, "rt") as stream:
        r = json.load(stream)
    seed = r["seed"]
    prefix = r["history"]
    index = 0
    confirmed = False

    def reproduce(state, action):
        nonlocal index, confirmed
        if index == len(prefix):
            if not confirmed:
                if digest(state) != r["root"]:
                    raise ValueError("Historical boss opening diverged")
                confirmed = True
            return action
        command = prefix[index]
        index += 1
        if action.command() == command:
            return action
        if command["action"] in ("select_cards", "skip_select"):
            choices = command["args"].get("indices", "")
            return selected_cards(state, [int(i) for i in choices.split(",") if i])
        return next(a for a in legal_actions(state) if a.command() == command)

    role, opts = load_bundle(bundle)
    folder = out / "runs" / seed
    game = play_episode(
        (
            ROOT,
            host,
            folder,
            seed,
            r["index"],
            role,
            asdict(RunWeights.load(opts["weights"])),
            opts.get("micro"),
            {
                **opts,
                "rooms": True,
                "opening_partition": "train",
                "seeded_acts": r["specification"].get("act_list") == "seeded",
            },
        ),
        decision_hook=reproduce,
    )
    if game["status"] != "complete" or not confirmed or not game["a2_clear"]:
        raise ValueError(f"Expected a legal Act 3 continuation on {seed}: {game.get('error')}")
    trace = folder / "game/rpc.jsonl"
    fork = act_start(trace, 3)
    dest = out / "maps" / seed
    dest.mkdir(parents=True)
    clipped = dest / "rpc.jsonl"
    act, last_row = 1, -1
    with trace.open() as source, clipped.open("w", encoding="utf-8", newline="\n") as target:
        for line in source:
            target.write(line)
            cmd = json.loads(line)["command"]
            if cmd.get("action") == "select_map_node":
                row = cmd["args"]["row"]
                act += int(row < last_row)
                last_row = row
                if act == 3:
                    break
    if act_start(clipped, 3) != fork:
        raise ValueError("Exported Act 3 map differs")
    return {
        "seed": seed,
        "index": r["index"],
        "partition": "train",
        "boss": r["boss"],
        "boss_digest": r["root"],
        "map_digest": fork.expected_digest,
        "act_list": r["specification"].get("act_list", "default"),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("bundle", "host", "output", "selected", "seed-lock"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--openings", type=Path, nargs="+", required=True)
    p.add_argument("--workers", type=int, default=3)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    seeds = json.loads(a.selected.read_bytes())
    blocked = json.loads(a.seed_lock.read_bytes())["seeds"]
    if set(seeds) & (set(blocked["test"]) | set(blocked["development"])) or len(set(seeds)) != len(
        seeds
    ):
        raise ValueError("Only distinct training openings may be refreshed")
    files = [
        f
        for d in a.openings
        for f in d.glob("*.json.gz")
        if f.name.removesuffix(".json.gz") in seeds
    ]
    if len(files) != len(seeds) or len({f.name for f in files}) != len(seeds):
        raise ValueError("Missing or duplicated training opening")
    with ProcessPoolExecutor(a.workers) as pool:
        rows = list(pool.map(refresh, [(f, a.host.resolve(), a.bundle, a.output) for f in files]))
    save_json(a.output / "maps/index.json", sorted(rows, key=lambda r: r["seed"]))
    print(len(rows), "verified training maps", flush=True)


if __name__ == "__main__":
    main()
