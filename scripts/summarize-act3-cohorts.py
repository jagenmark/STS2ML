"""Combine sealed cohort reports and describe the last rooms of native Act 3 arrivals."""

import argparse
from collections import Counter
import json
from math import comb
from pathlib import Path

from sts2rl.act1 import save_json


def read(p):
    return json.loads(p.read_bytes())


def paired(pairs, metric):
    gained = [r["seed"] for r in pairs if r["challenger"][metric] and not r["incumbent"][metric]]
    lost = [r["seed"] for r in pairs if r["incumbent"][metric] and not r["challenger"][metric]]
    n = len(gained) + len(lost)
    p = min(1.0, 2 * sum(comb(n, k) for k in range(min(len(gained), len(lost)) + 1)) / (2**n))
    return {"gained": gained, "lost": lost, "paired_exact_p": p}


def room_outcomes(rows):
    deaths, exit_hp, victories = Counter(), [], []
    for r in rows:
        rooms = [v for v in r["rooms"] if v["act"] == 3]
        fought = {floor for act, floor in r["boss_fights"] if act == 3}
        if fought:
            first = next(v for v in rooms if v["icon"] == "Boss")
            exit_hp.append(
                {
                    "seed": r["seed"],
                    "hp": first["before"]["hp"],
                    "max_hp": first["before"]["max_hp"],
                }
            )
        elif rooms and rooms[-1]["died"]:
            enemies = "+".join(sorted(e.removeprefix("MONSTER.") for e in r["last_enemies"]))
            deaths[(rooms[-1]["icon"], enemies)] += 1
        if r["win"]:
            victories.append(r["seed"])
    return {
        "first_boss_entry": exit_hp,
        "full_victory_seeds": victories,
        "terminal_enemies_before_boss": [
            {"map_icon": icon, "surviving_enemies": ids, "deaths": n}
            for (icon, ids), n in deaths.most_common()
        ],
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--study", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args()
    study = a.study
    reports, combined, seeds = {}, [], set()
    for cohort, base, arms in (
        ("primary", "baseline-test", ("combat",)),
        ("secondary", "route-test-baseline", ("combat", "route")),
    ):
        cohort_report = {}
        entries = read(study / f"held-{cohort}/entries.json")
        arrivals = {r["seed"] for r in entries}
        if arrivals & seeds:
            raise ValueError("Overlapping cohort entries")
        seeds.update(arrivals)
        cohort_report["incumbent_room_outcomes"] = room_outcomes(
            [
                read(study / base / "candidate" / f"run-{r['index']:04d}" / "result.json")
                for r in entries
            ]
        )
        for arm in arms:
            folder = study / (
                "primary-report" if cohort == "primary" else f"secondary-{arm}-report"
            )
            result = read(folder / "summary.json")
            pairs = [r for r in read(folder / "pairs.json") if r["origin_map"]]
            if {p["seed"] for p in pairs} != arrivals or len(pairs) != len(arrivals):
                raise ValueError("Incomplete comparison")
            if arm == "combat":
                combined.extend(pairs)
            cohort_report[arm] = {
                "test": result,
                "comparisons": {m: paired(pairs, m) for m in ("first", "second", "win")},
                "room_outcomes": room_outcomes(
                    [read(study / f"{cohort}-{arm}" / r["seed"] / "result.json") for r in entries]
                ),
            }
        reports[cohort] = cohort_report
    both = {
        "lobbies": sum(c["combat"]["test"]["full"]["lobbies"] for c in reports.values()),
        "act3_entries": len(combined),
        "totals": {
            arm: {
                metric: sum(int(r[arm][metric]) for r in combined)
                for metric in ("first", "second", "win")
            }
            for arm in ("incumbent", "challenger")
        },
        "comparisons": {m: paired(combined, m) for m in ("first", "second", "win")},
    }
    save_json(a.output, {"cohorts": reports, "combat_across_disjoint_cohorts": both})
    print(json.dumps(both))


if __name__ == "__main__":
    main()
