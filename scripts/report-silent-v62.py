"""Recompute the preregistered CSV6DEV decision from compact native receipts."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np

ARMS = ("v5", "heuristic", "power", "accelerant_only", "scaling_powers_4")
LOCK = Path(__file__).resolve().parents[1] / "docs/combat-search-v2/v62-dev-lock.json"


def evaluate(directory):
    if hashlib.sha256(LOCK.read_bytes()).hexdigest() != "3f166462911e3a53b863cf48bbcae7ee5fae8796abde68bc44ee4993183b4c04":
        raise ValueError("Dev lock changed")
    panel = json.loads(LOCK.read_bytes())
    floors, table = {}, {}
    for arm in ARMS:
        with gzip.open(directory / (arm + ".jsonl.gz"), "rt") as stream:
            receipts = [json.loads(line) for line in stream]
        by_seed = {r["seed"]: r for r in receipts}
        if len(by_seed) != len(receipts) or len(receipts) != len(panel):
            raise ValueError("Duplicate or incomplete receipts")
        rows = []
        native = Counter()
        for index, seed, mode in panel:
            row = by_seed[seed]
            if (row["index"], row["act_list"], row["arm"], row["status"], row["ascension"]) != (index, mode, arm, "complete", 10):
                raise ValueError((arm, seed, "invalid receipt"))
            if row["native"].get("mismatch", 0) != len(row["mismatches"]):
                raise ValueError((arm, seed, "audit inconsistency"))
            native.update(row["native"])
            rows.append(row)
        floors[arm] = np.array([17 * (r["act"] - 1) + r["floor"] for r in rows])
        table[arm] = dict(n=len(rows), floor=float(floors[arm].mean()), native=dict(native),
                          a1=sum(r["a1_clear"] for r in rows), a2_boss=sum(any(a == 2 for a, _ in r["boss_fights"]) for r in rows),
                          a2=sum(r["a2_clear"] for r in rows), wins=sum(r["win"] for r in rows))
    pairs = [(arm, "v5") for arm in ARMS[1:]] + [(ARMS[a-1], ARMS[b-1]) for a, b in ((3, 2), (4, 3), (5, 4), (4, 2), (5, 2))]
    modes = [[i for i, (_, _, m) in enumerate(panel) if m == mode] for mode in ("default", "seeded")]
    diffs = [floors[a] - floors[b] for a, b in pairs]
    draws = [[] for _ in pairs]
    rng = np.random.default_rng(620)
    for _ in range(100):
        sample = np.concatenate([rng.choice(ids, (500, len(ids))) for ids in modes], axis=1)
        for acc, diff in zip(draws, diffs, strict=True):
            acc.extend(diff[sample].mean(axis=1))
    contrasts = {}
    eligible = []
    clean = all(row["native"].get("mismatch", 0) == 0 and row["native"].get("match", 0) > 0 for row in table.values())
    for (a, b), draw, diff in zip(pairs, draws, diffs, strict=True):
        alpha = 0.0125 if b == "v5" else 0.05
        ci = np.quantile(draw, (alpha / 2, 1 - alpha / 2)).tolist()
        contrasts[f"{a}-{b}"] = dict(delta=float(diff.mean()), ci=ci, wlt=[int(f.sum()) for f in (diff > 0, diff < 0, diff == 0)])
        if b == "v5" and clean and ci[0] > 0 and all(table[a][k] >= table[b][k] for k in ("a1", "a2_boss", "a2")):
            eligible.append(a)
    winner = max(eligible, key=lambda a: table[a]["floor"], default=None)
    return dict(arms=table, contrasts=contrasts, eligible=eligible, winner=winner)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("directory", type=Path)
    print(json.dumps(evaluate(p.parse_args().directory), indent=2))
