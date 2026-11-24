"""Reproduce the diagnostic paired tables from the native receipts."""
import argparse
from collections import Counter
import gzip
import json
import sys

import numpy as np


def interval(values):
    if not values:
        return "—"
    rng = np.random.default_rng(64002)
    samples = rng.choice(values, (20000, len(values)), replace=True).mean(axis=1)
    low, high = np.percentile(samples, [2.5, 97.5])
    return f"{np.mean(values):+.2f} [{low:+.2f}, {high:+.2f}]"


def pct(n, d):
    return f"{100 * n / d:.1f}%" if d else "—"


def times(rows, *, active=False):
    ns = [r[0] for row in rows for r in row["latency"] if not active or r[1]]
    if not ns:
        return "—"
    lo, hi = np.percentile(ns, (50, 95)) / 1e6
    return f"{lo:.1f}/{hi:.1f}"


def compare(pairs):
    ctrl, pilot = zip(*pairs, strict=True)
    counts = sum((Counter(p["counts"]) for p in pilot), Counter())
    paired = [b["hp"] - a["hp"] for a, b in pairs]
    matched = [delta for delta, (a, b) in zip(paired, pairs) if a["win"] and b["win"]]
    changed = [(a, b) for a, b in pairs if b["counts"]["changed"]]
    wins = sum(not a["win"] and b["win"] for a, b in pairs)
    losses = sum(a["win"] and not b["win"] for a, b in pairs)
    audits = sum((Counter(row["counts"]) for row in (*ctrl, *pilot)), Counter())
    mismatch = sum(len(row["errors"]) for row in (*ctrl, *pilot))
    delta_wins = sum(b["win"] - a["win"] for a, b in changed)
    return [len(pairs), f"{sum(a['win'] for a in ctrl)}→{sum(b['win'] for b in pilot)}",
            f"{wins}/{losses}/{len(pairs) - wins - losses}", interval(paired), f"{len(matched)} · {interval(matched)}",
            pct(counts["active"], counts["eligible"]), pct(counts["changed"], counts["active"]),
            len(changed), interval([b["hp"] - a["hp"] for a, b in changed]),
            f"{100 * delta_wins / len(changed):+.1f}" if changed else "—",
            times(ctrl), times(pilot), times(pilot, active=True),
            f"{audits['match']}/{audits['intent']}/{audits['start']}/{mismatch}"]


def read_pairs(path):
    with gzip.open(path) as stream:
        rows = [json.loads(line) for line in stream]
    pairs = list(zip(rows[::2], rows[1::2], strict=True))
    assert len({a["opening"] for a, b in pairs}) == len(pairs) == 100
    for a, b in pairs:
        assert not a["pilot"] and b["pilot"]
        for field in ("encounter", "index", "archive", "opening", "entry"):
            assert a[field] == b[field]
    return pairs


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipts")
    pairs = read_pairs(parser.parse_args().receipts)
    groups = [("All", pairs)] + [(k, [(a, b) for a, b in pairs if a["encounter"] == k])
                                 for k in dict.fromkeys(a["encounter"] for a, b in pairs)]
    rows = [(name.removesuffix("_BOSS").removesuffix("_WEAK").removesuffix("_NORMAL")
             .replace("_", " ").title(), compare(group)) for name, group in groups]
    tables = (
        (["Encounter", "Pairs", "Wins 1T→2T", "Win W/L/T", "Δ HP [95% CI]", "Matched wins · Δ HP [95% CI]"],
         (0, 1, 2, 3, 4)),
        (["Encounter", "Active / eligible", "Changed / active", "Changed fights", "Changed Δ HP [95% CI]",
          "Changed Δ win (pp)"], (5, 6, 7, 8, 9)),
        (["Encounter", "1T all (ms)", "2T all (ms)", "2T active (ms)", "Steps / intents / starts / mismatches"],
         (10, 11, 12, 13)),
    )
    for columns, indices in tables:
        print("| " + " | ".join(columns) + " |")
        print("| " + " | ".join("---" for _ in columns) + " |")
        for name, values in rows:
            print("| " + " | ".join([name, *(str(values[i]) for i in indices)]) + " |")
        print()
