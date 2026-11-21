"""Summarize matched native Mecha fights, keeping natural, placed and potion scenarios visible."""

import argparse
from collections import Counter
import json
from pathlib import Path

from sts2rl.act1 import save_json


def read(path):
    return json.loads(path.read_bytes())


def summary(panels, expected):
    by_arm = {}
    for panel in panels:
        for folder in sorted(p for p in panel.iterdir() if p.is_dir()):
            if folder.name in by_arm:
                raise ValueError(f"Repeated policy {folder.name}")
            rows = {f.stem: read(f) for f in folder.glob("*.json")}
            if set(rows) != set(expected):
                raise ValueError(f"Incomplete panel for {folder.name}")
            by_arm[folder.name] = rows
    base = by_arm["incumbent"]
    errors = {}
    for key, case in expected.items():
        starts = set()
        for arm, rows in by_arm.items():
            r = rows[key]
            if (r["case"], r["seed"], r["kind"], r["partition"]) != (
                key,
                case["seed"],
                case["kind"],
                case["partition"],
            ):
                raise ValueError("Case registry mismatch")
            if "error" in r:
                errors.setdefault(key, {})[arm] = r["error"]
            else:
                starts.add(r["opening"])
        if len(starts) > 1:
            raise ValueError("The arms faced different native starting hands")
    output = {
        "registered": len(expected),
        "complete_pairs": len(expected) - len(errors),
        "errors": errors,
        "arms": {},
    }
    categories = {
        "all": list(set(r["kind"] for r in expected.values())),
        "carried_inventory": ["natural", "practice"],
        "natural": ["natural"],
        "practice": ["practice"],
        "potion_practice": ["potion_practice"],
    }
    for arm, rows in by_arm.items():
        totals = {}
        output["arms"][arm] = totals
        for name, kinds in categories.items():
            keys = sorted(k for k in expected if k not in errors and rows[k]["kind"] in kinds)
            group = [rows[k] for k in keys]
            potions = Counter(
                (d["phase"], d["item"])
                for r in group
                for d in r["decisions"]
                if d["action"]["action"] == "use_potion"
            )
            totals[name] = {
                "n": len(keys),
                "seeds": len({r["seed"] for r in group}),
                "wins": sum(r["won"] for r in group),
                "exit_hp": sum(r["hp"] for r in group),
                "gains": [k for k in keys if rows[k]["won"] and not base[k]["won"]],
                "losses": [k for k in keys if base[k]["won"] and not rows[k]["won"]],
                "windup_seen": sum(
                    any(d["phase"] == "windup" for d in r["decisions"]) for r in group
                ),
                "potion_uses": {f"{p}/{i}": n for (p, i), n in sorted(potions.items())},
            }
    return output


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cases", type=Path, required=True)
    p.add_argument("--panels", type=Path, nargs="+", required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    expected = {v["case"]: v for v in read(a.cases / "index.json")}
    result = summary(a.panels, expected)
    save_json(a.output, result)
    print(
        json.dumps(
            {
                name: {k: [v["wins"], v["n"], v["exit_hp"]] for k, v in groups.items()}
                for name, groups in result["arms"].items()
            }
        )
    )


if __name__ == "__main__":
    main()
