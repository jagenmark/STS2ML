"""Recompute the paired Silent A10 v6 gate and descriptive stopped-panel metrics."""
import argparse
from collections import Counter, defaultdict
import gzip
import json
from math import comb
from pathlib import Path
import runpy

import numpy as np


def summarize(rows, timings):
    native = Counter()
    bosses = defaultdict(lambda: [0, 0])
    for row in rows:
        native.update(row["native"])
        for _, _, _, formation, _, cleared in row["a2_fights"]:
            bosses[formation][0] += 1
            bosses[formation][1] += int(cleared)
    bins = sorted((int(us), count) for us, count in timings.items())
    us, counts = zip(*bins)
    cumulative = np.cumsum(counts)
    latency = [us[np.searchsorted(cumulative, int(np.ceil(p * cumulative[-1])))] / 1000 for p in (.5, .95)]
    return dict(mean_floor=float(np.mean([floor(r) for r in rows])), native=dict(native), a2_by_boss=dict(bosses),
                latency_p50_p95_ms=latency, latency_samples=int(cumulative[-1]),
                a1_clear=sum(r["a1_clear"] for r in rows), a2_clear=sum(r["a2_clear"] for r in rows),
                a2_boss=sum(any(a == 2 for a, _ in r["boss_fights"]) for r in rows),
                a3_boss=sum(any(a == 3 for a, _ in r["boss_fights"]) for r in rows),
                wins=sum(r["win"] for r in rows))


def floor(row):
    return 17 * (row["act"] - 1) + row["floor"]


def analyze(directory, panel):
    with gzip.open(directory / "episodes.jsonl.gz", "rt") as stream:
        receipts = [json.loads(line) for line in stream]
    with gzip.open(directory / "latency-us.json.gz", "rt") as stream:
        timings = json.load(stream)
    rows = {}
    for row in receipts:
        key = (row["suite"], row["index"], row["seed"], row["act_list"], row["arm"])
        if (key in rows or row["status"] != "complete" or row["abandoned"] or row["start_act"] != 1
                or row["ascension"] != 10 or row["native"].get("mismatch", 0) != len(row["mismatches"])):
            raise ValueError(f"Duplicate, invalid or incomplete receipt {key}")
        rows[key] = row
    keys = panel[:len(receipts) // 2]
    if not keys or set(rows) != {(*k, arm) for k in keys for arm in ("v5", "v6")}:
        raise ValueError("Receipts are not complete consecutive pairs from the lock")
    if any(rows[*k, "v5"]["act_names"][0] != rows[*k, "v6"]["act_names"][0] for k in keys):
        raise ValueError("Opening act differs within a pair")
    arms = {arm: summarize([rows[*k, arm] for k in keys], timings[arm]) for arm in ("v5", "v6")}
    diffs = np.array([floor(rows[*k, "v6"]) - floor(rows[*k, "v5"]) for k in keys])
    rng = np.random.default_rng(621)
    strata = defaultdict(list)
    for key, diff in zip(keys, diffs, strict=True):
        strata[key[0], key[-1]].append(diff)
    totals = np.zeros(50000)
    for tag in sorted(strata):
        values = strata[tag]
        for start in range(0, len(totals), 500):
            totals[start:start + 500] += rng.choice(values, (500, len(values))).sum(axis=1)
    ci = np.quantile(totals / len(keys), (.025, .975)).tolist()
    w, l, t = (int(x.sum()) for x in (diffs > 0, diffs < 0, diffs == 0))
    n = w + l
    p = min(1., 2 * sum(comb(n, k) for k in range(min(w, l) + 1)) / (1 << n))
    gates = dict(complete=len(keys) == len(panel), audit=arms["v6"]["native"].get("mismatch", 0) == 0
                 and arms["v6"]["native"].get("match", 0) > 0, floor=ci[0] > 0, sign=p < .01)
    for milestone in ("a1_clear", "a2_boss", "a2_clear"):
        gates[milestone] = arms["v6"][milestone] >= arms["v5"][milestone]
    return dict(n=len(keys), target=len(panel), arms=arms, delta=float(diffs.mean()), ci95=ci, sign_p=p,
                wlt=[w, l, t], gates=gates, passes=all(gates.values()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    folder = parser.parse_args().directory
    registry = runpy.run_path(str(Path(__file__).with_name("verify-silent-v6.py")))["registry"]
    panel = json.loads((folder / "manifest.json").read_bytes())["panel"]
    print(json.dumps(analyze(folder, registry(panel)), indent=2))
