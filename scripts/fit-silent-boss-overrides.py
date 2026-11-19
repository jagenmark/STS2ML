"""Fit a small boss-to-style table from matched native training fights."""

from argparse import ArgumentParser
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path

from sts2rl.act1 import save_json
from sts2rl.provenance import read_encounter_runs
from sts2rl.run_bundle import load_bundle
from sts2rl.run_policy import RunWeights


def value(outcome):
    return (
        24 * outcome["won"]
        + 0.16 * outcome["hp"]
        + 5 * (1 - outcome["remaining"])
        + 0.12 * outcome["potions"]
    )


def main():
    parser = ArgumentParser(description=__doc__)
    for key in ("labels", "bundle", "seed-lock", "output"):
        parser.add_argument("--" + key, required=True, type=Path)
    args = parser.parse_args()
    _, settings = load_bundle(args.bundle)
    model = json.loads(settings["encounter_model"].read_bytes())
    protected = {
        s for split in json.loads(args.seed_lock.read_bytes())["seeds"].values() for s in split
    }
    collector = Path(__file__).with_name("train-silent-encounters.py")
    roots = [
        r
        for _, rows in read_encounter_runs(
            [args.labels], collector, RunWeights.load(settings["weights"])
        )
        for r in rows
        if r["room"] == "Boss"
    ]
    if (
        not roots
        or any(r["seed"] in protected for r in roots)
        or len({r["root"] for r in roots}) != len(roots)
    ):
        raise ValueError("Invalid or reserved boss roots")
    by_boss = defaultdict(list)
    validation = []
    for root in roots:
        if int.from_bytes(sha256(root["seed"].encode()).digest()[:4], "big") % 5 == 0:
            validation.append(root)
        else:
            by_boss[root["encounter"]].append(root)
    overrides = {}
    counts = {}
    for boss, group in by_boss.items():
        default = model.get("by_act", {}).get(str(group[0]["act"]), model["default"])
        scores = {
            s: (
                sum(r["styles"][s]["won"] for r in group),
                sum(value(r["styles"][s]) for r in group),
            )
            for s in group[0]["styles"]
        }
        best = max(scores, key=lambda s: (*scores[s], s == default))
        if (
            len(group) >= 6
            and scores[best][0] > scores[default][0]
            and scores[best][1] > scores[default][1]
        ):
            overrides[boss] = best
        counts[boss] = {"roots": len(group), "scores": scores}
    base_wins = selected_wins = 0
    for r in validation:
        default = model.get("by_act", {}).get(str(r["act"]), model["default"])
        base_wins += r["styles"][default]["won"]
        selected_wins += r["styles"][overrides.get(r["encounter"], default)]["won"]
    args.output.mkdir(parents=True, exist_ok=False)
    save_json(
        args.output / "encounter_model.json",
        {**model, "overrides": {**model.get("overrides", {}), **overrides}},
    )
    save_json(
        args.output / "fit.json",
        {
            "label_provenance": roots[0]["label_provenance"],
            "training": counts,
            "overrides": overrides,
            "validation_fights": len(validation),
            "validation_wins": {"base": base_wins, "selected": selected_wins},
            "training_seeds": sorted({r["seed"] for rs in by_boss.values() for r in rs}),
            "validation_seeds": sorted({r["seed"] for r in validation}),
        },
    )


if __name__ == "__main__":
    main()
