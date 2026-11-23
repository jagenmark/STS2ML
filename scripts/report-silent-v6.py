"""Summarize the three audited CSV4DEV arms, preserving lobby pairing."""
import argparse
from collections import Counter
import gzip
import json
import shutil
from pathlib import Path

import numpy as np

ARMS = ("v5", "schema3", "heuristic")
ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "docs/combat-search-v2/v6-dev-lock.json"


def pack(directory, path):
    with path.open("xb") as file, gzip.GzipFile(filename="", mode="wb", fileobj=file, mtime=0) as archive:
        for arm in ARMS:
            with (directory / (arm + ".jsonl")).open("rb") as stream:
                shutil.copyfileobj(stream, archive)


def summarize(path):
    with gzip.open(path, "rt", encoding="utf8") as stream:
        receipts = [json.loads(line) for line in stream]
    registry = [tuple(row) for row in json.loads(LOCK.read_bytes())]
    assert len(receipts) == 3 * len(registry) == 768
    arms = {}
    for arm in ARMS:
        rows = {r["seed"]: r for r in receipts if r["arm"] == arm}
        arms[arm] = [rows[s] for _, s, _ in registry]
        for (i, s, m), r in zip(registry, arms[arm], strict=True):
            assert (r["index"], r["seed"], r["act_list"]) == (i, s, m)
            assert r["status"] == "complete" and not r.get("abandoned")

    rng = np.random.default_rng(406)
    strata = []
    for mode in ("default", "seeded"):
        indices = [i for i, row in enumerate(registry) if row[2] == mode]
        strata.append(rng.choice(indices, (10000, len(indices))))
    resamples = np.concatenate(strata, axis=1)

    def pairs(rows):
        return [{tuple(f[:4]): f[4] for f in r["late_fights"]} for r in rows]

    def floors(rows):
        return np.array([17 * (r["act"] - 1) + r["floor"] for r in rows])

    reference = arms["v5"]
    reference_fights = pairs(reference)
    metrics = {}
    for arm, rows in arms.items():
        delta = floors(rows) - floors(reference)
        native = sum((Counter(r["native"]) for r in rows), Counter())
        coverage = {}
        for key in sorted({k for r in rows for k in r["coverage"]}):
            counts = sum((Counter(r["coverage"].get(key, {})) for r in rows), Counter())
            coverage[key] = {"covered": counts["covered"], "eligible": sum(counts.values()),
                             "fallbacks": dict((k, n) for k, n in counts.most_common() if k != "covered")}
        fights = [f for r in rows for f in r["late_fights"]]
        matched = {}
        arm_fights = pairs(rows)
        for act in (2, 3):
            observations = [(a[k], b[k]) for a, b in zip(arm_fights, reference_fights, strict=True)
                            for k in a.keys() & b.keys() if k[0] == act]
            values = np.asarray(observations)
            matched[act] = {"fights": len(values), "exit_hp": values[:, 0].mean(),
                            "v5_exit_hp": values[:, 1].mean(), "delta": (values[:, 0] - values[:, 1]).mean()}
        boss = {f[3] for f in fights if f[0] == 2}
        metrics[arm] = dict(
            mean_floor=floors(rows).mean(), delta=delta.mean(),
            ci=np.quantile(delta[resamples].mean(axis=1), [0.025, 0.975]).tolist(),
            a1_clear=sum(r["a1_clear"] for r in rows), a2_boss=sum(any(a == 2 for a, _ in r["boss_fights"]) for r in rows),
            a2_clear=sum(r["a2_clear"] for r in rows), a3_boss=sum(any(a == 3 for a, _ in r["boss_fights"]) for r in rows),
            wins=sum(r["win"] for r in rows), native=dict(native), matched_hp=matched,
            ms=(np.quantile([n for r in rows for n in r["combat_ns"]], [.5, .95]) / 1e6).tolist(),
            coverage=coverage,
            boss_survival={b: [sum(f[5] for f in fights if f[0] == 2 and f[3] == b),
                               sum(1 for f in fights if f[0] == 2 and f[3] == b)] for b in sorted(boss)},
            act3_deaths=dict(Counter((r["death"].get("formation") or r["death"]["room"]) for r in rows
                             if r.get("death") and r["death"]["act"] == 3)),
        )
    control = arms["v5"]
    metrics["v5"]["independent_native"] = dict(sum((Counter(r["independent_native"]) for r in control), Counter()))
    gap = floors(arms["heuristic"]) - floors(arms["schema3"])
    metrics["heuristic_minus_schema3"] = {"delta": gap.mean(),
            "ci": np.quantile(gap[resamples].mean(axis=1), [0.025, 0.975]).tolist()}
    return metrics


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("receipts", type=Path)
    p.add_argument("--pack", type=Path, help="create receipts from three audited arm JSONL files before summarizing")
    args = p.parse_args()
    if args.pack:
        pack(args.pack, args.receipts)
    print(json.dumps(summarize(args.receipts), indent=2))
