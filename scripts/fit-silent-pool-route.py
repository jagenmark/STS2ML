"""Fit biome, ordinary-fight tier and boss resource values from archived Act 1 runs."""

import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path

import numpy as np

from sts2rl.act1 import save_json
from sts2rl.survival_route import _strength


def fit(args):
    base = json.loads(args.router.read_bytes())
    if base["version"] != 2:
        raise ValueError("Expected the pooled v2 survival router")
    protected = {
        s for split in json.loads(args.seed_lock.read_bytes())["seeds"].values() for s in split
    }
    cells = defaultdict(lambda: np.zeros(9))
    unknown = defaultdict(Counter)
    bosses = defaultdict(list)
    seeds = set()
    unresolved = 0
    for directory in args.source:
        for path in sorted(directory.glob("run-*/result.json")):
            result = json.loads(path.read_bytes())
            trace = path.with_name("strategy.jsonl.gz")
            if (
                result["status"] != "complete"
                or not trace.exists()
                or result.get("opening_partition") == "test"
            ):
                continue
            seed = result["seed"]
            if seed in protected or seed in seeds:
                raise ValueError(f"Duplicate or reserved route seed {seed}")
            seeds.add(seed)
            observed = defaultdict(set)
            with gzip.open(trace, "rt", encoding="utf-8") as stream:
                opening = json.loads(next(stream))["state"]["context"]
                for line in stream:
                    state = json.loads(line)["state"]
                    ctx = state["context"]
                    if ctx["act"] != 1:
                        break
                    if ctx["room_type"] != "Map":
                        observed[ctx["floor"] - 1].add(ctx["room_type"])
            biome = opening["act_name"]
            boss = (opening.get("boss") or {}).get("id")
            low = high = 0
            for room in result["rooms"]:
                if room["act"] != 1:
                    break
                icon = room["icon"]
                before, after, died = room["before"], room["after"], room["died"]
                if icon == "Boss":
                    if boss:
                        bosses[boss].append((_strength(before), float(not died)))
                    continue
                obs = [
                    1,
                    died,
                    *(
                        0 if died else after[k] - before[k]
                        for k in ("hp", "gold", "relics", "upgrades", "potions", "cards", "max_hp")
                    ),
                ]
                cells[f"{biome}/{icon}"] += obs
                if icon in ("Unknown", "Monster"):
                    if high < 3 or low >= 3:
                        phase = "weak" if high < 3 else "regular"
                        cells[f"{biome}/{icon}/{phase}"] += obs
                    else:
                        unresolved += 1
                if icon == "Monster":
                    low += 1
                    high += 1
                elif icon == "Unknown":
                    types = observed[room["row"]]
                    if types == {"Monster"}:
                        low += 1
                        high += 1
                        unknown[biome]["fight"] += 1
                    elif not types or "Monster" in types:
                        # The archive can omit a room decision or include a nested event fight.
                        high += 1
                    else:
                        unknown[biome]["other"] += 1

    coefficients = {}
    prior = np.asarray(base["boss_coefficients"]["1"])
    penalty = np.array([8, 16, 20, 20, 24, 24, 30])
    for boss, cases in bosses.items():
        x = np.asarray([case[0] for case in cases])
        y = np.asarray([case[1] for case in cases])
        beta = prior.copy()
        for _ in range(18):
            p = 1 / (1 + np.exp(-np.clip(x @ beta, -20, 20)))
            gradient = x.T @ (y - p) - penalty * (beta - prior)
            step = np.linalg.solve((x.T * (p * (1 - p))) @ x + np.diag(penalty), gradient)
            beta += step
            if abs(step).max() < 1e-7:
                break
        coefficients[boss] = beta.tolist()
    context = {
        "rooms": {k: v.tolist() for k, v in cells.items()},
        "boss_coefficients": coefficients,
        "unknown_fight_probability": {k: c["fight"] / sum(c.values()) for k, c in unknown.items()},
        "blend": args.blend,
    }
    save_json(args.output / "room_model.json", {**base, "version": 3, "act1_context": context})
    save_json(
        args.output / "fit.json",
        {
            "seeds": sorted(seeds),
            "censored_tiers": unresolved,
            "boss_openings": {k: len(v) for k, v in bosses.items()},
            "observed_unknown_rooms": {k: dict(v) for k, v in unknown.items()},
            "room_counts": {k: int(v[0]) for k, v in cells.items()},
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("router", "seed-lock", "output"):
        parser.add_argument("--" + flag, required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path, nargs="+")
    parser.add_argument("--blend", type=float, default=0.5)
    args = parser.parse_args()
    if not 0 < args.blend <= 1:
        parser.error("Choose a blend in (0, 1]")
    args.output.mkdir(parents=True, exist_ok=False)
    fit(args)
