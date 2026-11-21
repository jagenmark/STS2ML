"""Compare the first observed Windup and Heavy Cleave in paired native combat logs."""

import argparse
from collections import Counter
import json
from pathlib import Path

from sts2rl.act1 import save_json


def read(path):
    return json.loads(path.read_bytes())


def first_cycle(row):
    wind = next((d for d in row["decisions"] if d["phase"] == "windup"), None)
    if not wind:
        return None
    rnd = wind["round"]
    cleave = next(
        (d for d in row["decisions"] if d["round"] == rnd + 1 and d["phase"] == "cleave"), None
    )
    after = next((t for t in row["turns"] if t["round"] == rnd + 2), None)
    potions = [
        d["item"] for d in row["decisions"] if d["round"] == rnd and d["item"].startswith("POTION.")
    ]
    return {
        "round": rnd,
        "root": wind["root"],
        "windup_hp": wind["hp"],
        "cleave_hp": cleave["hp"] if cleave else None,
        "post_cleave_hp": after["hp"] if after else row["hp"],
        "post_cleave_enemy_hp": after["foe_hp"] if after else None,
        "reached_next_turn": after is not None,
        "early_victory": after is None and row["won"],
        "survived_cycle": after is not None or row["won"],
        "fight_won": row["won"],
        "last_round": row["turns"][-1]["round"],
        "windup_potions": potions,
    }


def panel(path):
    sides = ("incumbent", "challenger")
    files = [{f.name for f in (path / side).glob("*.json")} for side in sides]
    if not files[0] or files[0] != files[1]:
        raise ValueError("Incomplete matched panel")
    result = []
    for name in sorted(files[0]):
        a, b = [read(path / side / name) for side in sides]
        if any("error" in r for r in (a, b)) or any(
            a[k] != b[k] for k in ("seed", "case", "opening", "kind", "partition")
        ):
            raise ValueError("Incompatible combat logs")
        if a["partition"] != "test":
            raise ValueError("Expected the frozen evaluation cohort")
        x, y = map(first_cycle, (a, b))
        if (x is None) != (y is None) or (x and x["root"] != y["root"]):
            raise ValueError("Challenger changed the path before the first Windup")
        result.append(
            {
                "seed": a["seed"],
                "case": a["case"],
                "kind": a["kind"],
                "incumbent": x,
                "challenger": y,
            }
        )
    return result


def summarize(rows):
    group = [r for r in rows if r["incumbent"] is not None]
    both = [
        r for r in group if all(r[k]["cleave_hp"] is not None for k in ("incumbent", "challenger"))
    ]
    totals = {}
    for side in ("incumbent", "challenger"):
        x = [r[side] for r in group]
        loss = sum(r[side]["windup_hp"] - r[side]["cleave_hp"] for r in both)
        total = sum(v["survived_cycle"] for v in x)
        totals[side] = {
            "net_hp_lost_during_windup": loss,
            "survived_first_cycle": total,
            "early_victories": sum(v["early_victory"] for v in x),
            "full_fight_wins": sum(v["fight_won"] for v in x),
            "windup_potions": dict(
                sorted(Counter(p for v in x for p in v["windup_potions"]).items())
            ),
        }
    return {
        "matched_fights": len(rows),
        "same_first_windup": len(group),
        "both_reached_first_cleave": len(both),
        **totals,
        "first_cycle_survival_gains": [
            r["seed"]
            for r in group
            if r["challenger"]["survived_cycle"] and not r["incumbent"]["survived_cycle"]
        ],
        "first_cycle_survival_losses": [
            r["seed"]
            for r in group
            if r["incumbent"]["survived_cycle"] and not r["challenger"]["survived_cycle"]
        ],
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--practice", type=Path, nargs="+", required=True)
    p.add_argument("--natural", type=Path)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    rows = [row for folder in a.practice for row in panel(folder)]
    if len(set(r["seed"] for r in rows)) != len(rows) or any(r["kind"] != "practice" for r in rows):
        raise ValueError("Held practice requires one entry per distinct seed")
    report = {"held_practice": summarize(rows), "practice_cases": rows}
    if a.natural:
        real = panel(a.natural)
        if any(r["kind"] != "natural" for r in real):
            raise ValueError("Natural panel contains an intervention")
        report.update(natural=summarize(real), natural_cases=real)
    save_json(a.output, report)
    print(json.dumps({k: v for k, v in report.items() if not k.endswith("cases")}))


if __name__ == "__main__":
    main()
