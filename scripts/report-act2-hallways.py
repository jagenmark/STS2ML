"""Compare matched native Silent A10 trajectories, including independent terminal replays."""

import argparse
from hashlib import sha256
import gzip
import json
from math import comb
from pathlib import Path

from sts2rl.act1 import save_json
from sts2rl.run_evaluation import act_start


def discordance(pairs, metric):
    gained = [s for s, base, candidate in pairs if candidate[metric] and not base[metric]]
    lost = [s for s, base, candidate in pairs if base[metric] and not candidate[metric]]
    d = len(gained) + len(lost)
    p = min(1.0, 2 * sum(comb(d, i) for i in range(min(len(gained), len(lost)) + 1)) / 2**d)
    return {
        "pairs": len(pairs),
        "gained": gained,
        "lost": lost,
        "delta": len(gained) - len(lost),
        "paired_exact_p": p,
    }


def arm_data(path, replay_path, seeds):
    files = {
        r["seed"]: (f, r)
        for f in (path / "candidate").glob("run-*/result.json")
        if (r := json.loads(f.read_bytes()))
    }
    if set(files) != set(seeds) or len(files) != len(
        list((path / "candidate").glob("run-*/result.json"))
    ):
        raise ValueError("Missing, extra or duplicate lobby seed")
    receipts = {r["seed"]: r for r in json.loads(replay_path.read_bytes())}
    if receipts.keys() != files.keys():
        raise ValueError("Mismatched independent replay inventory")
    results, histories = {}, {}
    for seed in seeds:
        path, r = files[seed]
        if r["status"] != "complete" or r["ascension"] != 10 or r["start_act"] != 1:
            raise ValueError(f"Unfinished or nonstandard native episode: {seed}")
        with (path.parent / "game/rpc.jsonl").open() as stream:
            start = json.loads(next(stream))
            spec = start["command"]
            if spec != {
                "cmd": "training_restore",
                "act_list": "seeded",
                "seed": seed,
                "ascension": 10,
                "history": [],
            }:
                raise ValueError("A benchmark run did not start in the standard native lobby")
            records = [json.loads(line) for line in stream]
        if any(e["command"]["cmd"] not in ("action", "get_map") for e in records):
            raise ValueError("Invalid command in natural episode")
        commands = [e["command"] for e in records if e["command"]["cmd"] == "action"]
        terminal = records[-1]["response_digest"]
        receipt = receipts[seed]
        if receipt["verified"] and terminal != receipt["terminal"]:
            raise ValueError("Independent terminal differs")
        root2 = (
            act_start(path.parent / "game/rpc.jsonl", 2).expected_digest if r["a1_clear"] else None
        )
        arm = {
            k: r[k]
            for k in (
                "a1_clear",
                "a2_clear",
                "win",
                "act",
                "floor",
                "last_enemies",
                "boss_fights",
                "act_names",
            )
        }
        arm.update(
            boss2=any(a == 2 for a, _ in r["boss_fights"]),
            opening=start["response_digest"],
            act2_opening=root2,
            terminal=terminal,
            actions=len(commands),
            verified=receipt["verified"],
        )
        if not receipt["verified"]:
            arm["replay_error"] = receipt.get("stepwise_failure", receipt.get("error"))
        results[seed] = arm
        histories[seed] = commands
    return results, histories


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for k in (
        "baseline",
        "published",
        "challenger",
        "baseline-replays",
        "published-replays",
        "challenger-replays",
        "seed-lock",
        "selection",
        "output",
    ):
        p.add_argument("--" + k, type=Path, required=True)
    a = p.parse_args()
    selection = json.loads(a.selection.read_bytes())
    if sha256(a.seed_lock.read_bytes()).hexdigest() != selection["seed_lock_sha256"]:
        raise ValueError("Wrong seed registry")
    seeds = json.loads(a.seed_lock.read_bytes())["seeds"]["test"]
    arms = {}
    histories = {}
    for name in ("baseline", "published", "challenger"):
        arms[name], histories[name] = arm_data(
            getattr(a, name), getattr(a, name + "_replays"), seeds
        )
    if any(len({arm[s]["opening"] for arm in arms.values()}) != 1 for s in seeds):
        raise ValueError("The policies received different natural starts")
    a.output.mkdir(parents=True, exist_ok=True)
    summary = {
        "selection_sha256": sha256(a.selection.read_bytes()).hexdigest(),
        "seeds": len(seeds),
        "arms": {},
        "contrasts": {},
    }
    metrics = ["a1_clear", "boss2", "a2_clear", "win"]
    for name, data in arms.items():
        summary["arms"][name] = {
            "complete": len(data),
            "terminal_replays": sum(row["verified"] for row in data.values()),
            **{m: sum(row[m] for row in data.values()) for m in metrics},
        }
    for name in ("baseline", "published"):
        pairs = [(s, arms[name][s], arms["challenger"][s]) for s in seeds]
        verified = [p for p in pairs if p[1]["verified"] and p[2]["verified"]]
        summary["contrasts"][name] = {
            "full": {m: discordance(pairs, m) for m in metrics},
            "replay_verified": {m: discordance(verified, m) for m in metrics},
            "same_act2_entrance_or_both_out": sum(
                b["act2_opening"] == c["act2_opening"] for _, b, c in pairs
            ),
            "same_commands": sum(histories[name][s] == histories["challenger"][s] for s in seeds),
        }
    with (
        gzip.open(a.output / "test-games.jsonl.gz", "wt") as games,
        gzip.open(a.output / "test-action-histories.jsonl.gz", "wt") as history,
    ):
        for seed in seeds:
            games.write(
                json.dumps(
                    {"seed": seed, **{n: d[seed] for n, d in arms.items()}}, separators=(",", ":")
                )
                + "\n"
            )
            # Deduplicate identical action sequences for this seed, retaining all arm assignments.
            paths = []
            indexes = {}
            for n in arms:
                seq = histories[n][seed]
                if seq not in paths:
                    paths.append(seq)
                indexes[n] = paths.index(seq)
            history.write(
                json.dumps({"seed": seed, "arms": indexes, "paths": paths}, separators=(",", ":"))
                + "\n"
            )
    save_json(a.output / "test-report.json", summary)
    print(json.dumps(summary["arms"]))


if __name__ == "__main__":
    main()
