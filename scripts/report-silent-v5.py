"""Analyze the complete frozen release receipts. Requires NumPy and SciPy."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

import numpy as np
from scipy.stats import binomtest, t as student_t


ARMS = ("all_v2_p1_v4", "all_v2_search_v5", "all_v2_search_heur_v5")
MILESTONES = ("a1_boss", "a1_clear", "a2_boss", "a2_clear", "a3_boss", "win")


def exact(wins, losses):
    return float(binomtest(wins, wins + losses).pvalue) if wins + losses else 1.0


def compare(ref, cur, strata):
    x, y = (np.array([r["global_floor"] for r in arm]) for arm in (ref, cur))
    diff = y - x
    rng = np.random.default_rng(20261123)
    draws = np.zeros(10000)
    for key in sorted(set(strata)):
        values = diff[[i for i, s in enumerate(strata) if s == key]]
        draws += rng.choice(values, (len(draws), len(values))).sum(axis=1)
    ci = np.percentile(draws / len(diff), (2.5, 97.5)).tolist()
    delta = float(diff.mean())
    se = float(diff.std(ddof=1) / np.sqrt(len(diff)))
    t = delta / se if se else None
    wins, losses = int(sum(diff > 0)), int(sum(diff < 0))
    out = {"n": len(ref), "avg_floor": {"ref": float(x.mean()), "cur": float(y.mean()), "delta": delta,
           "ci95": ci, "se": se, "t": t, "paired_t_p": float(2 * student_t.sf(abs(t), len(diff) - 1))
           if t is not None else float(delta == 0), "p": exact(wins, losses), "w": wins, "l": losses,
           "ties": len(diff) - wins - losses}}
    for field in MILESTONES:
        counts = Counter((a[field], b[field]) for a, b in zip(ref, cur, strict=True))
        gain, loss = counts[False, True], counts[True, False]
        same = counts[True, True]
        out[field] = {"ref": same + loss, "cur": same + gain, "gain": gain, "loss": loss, "p": exact(gain, loss)}
    return out


def analyze(folder):
    manifest = json.loads((folder / "manifest.json").read_bytes())
    registry = manifest["seed_order"]
    if {k: len(v) for k, v in registry.items()} != {"val256": 256, "seeded128": 128, "rep512": 512}:
        raise ValueError("Expected official 896-lobby registry")
    rows = {}
    for line in (folder / "episodes.jsonl").read_text().splitlines():
        r = json.loads(line)
        key = (r["suite"], r["index"], r["seed"], r["act_list"], r["arm"])
        if key in rows or r["status"] != "complete" or r.get("abandoned") or r["start_act"] != 1 or r["ascension"] != 10:
            raise ValueError(f"Duplicate or invalid receipt: {key}")
        r["global_floor"] = 17 * (r["act"] - 1) + r["floor"]
        for act in (1, 2, 3):
            r[f"a{act}_boss"] = any(a == act for a, _ in r["boss_fights"])
        rows[key] = r
    ordered = [(suite, *triple) for suite, triples in registry.items() for triple in triples]
    if set(rows) != {(*key, arm) for key in ordered for arm in ARMS}:
        raise ValueError("Missing or unexpected arm–lobby receipts")
    if any(len({rows[*key, arm]["act_names"][0] for arm in ARMS}) != 1 for key in ordered):
        raise ValueError("Paired opening biomes differ")
    panels = {}
    for suite in (*registry, "pooled896"):
        keys = [key for key in ordered if suite == "pooled896" or key[0] == suite]
        contrasts = {}
        for ref, cur in ((ARMS[0], ARMS[1]), (ARMS[0], ARMS[2]), (ARMS[1], ARMS[2])):
            contrasts[f"{cur} vs {ref}"] = compare([rows[*k, ref] for k in keys], [rows[*k, cur] for k in keys],
                                                   [(k[0], k[3]) for k in keys])
        panels[suite] = contrasts
    gate = {}
    for suite in ("pooled896", "rep512"):
        c = panels[suite][f"{ARMS[1]} vs {ARMS[0]}"]
        gate[suite] = {"positive_ci": c["avg_floor"]["ci95"][0] > 0, "p_under_001": c["avg_floor"]["p"] < .01,
                       **{m: c[m]["cur"] >= c[m]["ref"] for m in ("a1_clear", "a2_boss", "a2_clear")}}
    primary_passed = all(all(checks.values()) for checks in gate.values())
    heuristic_wins = panels["pooled896"][f"{ARMS[2]} vs {ARMS[1]}"]["avg_floor"]["ci95"][0] > 0
    selected = (ARMS[2] if heuristic_wins else ARMS[1]) if primary_passed else ARMS[0]
    diagnostics = {}
    for arm in ARMS:
        deaths, coverage = defaultdict(Counter), defaultdict(Counter)
        for key in ordered:
            r = rows[*key, arm]
            for region, reasons in r["coverage"].items():
                coverage[region].update(reasons)
            death = r["death"]
            if death and death["act"] == 2 and death["room"] == "Boss":
                deaths["act2_boss"][death["boss"]] += 1
            if death and death["act"] == 3:
                deaths["act3"][death["boss"] or death["formation"] or f"noncombat/{death['room']}"] += 1
        diagnostics[arm] = {"deaths": deaths, "coverage": coverage}
    return {"freeze": {k: v for k, v in manifest.items() if k != "seed_order"},
            "attempts": len(rows), "complete_per_arm": 896, "retries": 0, "incomplete": 0,
            "comparisons": panels, "diagnostics": diagnostics, "primary_gate": gate,
            "heuristic_superior": heuristic_wins, "selected": selected}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("folder", type=Path)
    args = p.parse_args()
    result = analyze(args.folder)
    (args.folder / "summary.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(result["selected"], result["primary_gate"])
