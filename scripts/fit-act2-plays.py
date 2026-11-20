"""Fit a Hunter Killer action ranker with seed-grouped validation of native alternatives."""

import argparse
from hashlib import sha256
import json
from pathlib import Path

from sts2rl.act1 import save_json
from sts2rl.offer_policy import OfferModel
from sts2rl.run_bundle import freeze_bundle, load_bundle


def value(result):
    return (
        40 * result["won"]
        + 0.65 * result["hp"]
        + 2 * result["potions"]
        + 3 * (1 - result["remaining"])
    )


def fit_rows(records):
    return [
        {
            "arms": [
                {
                    "features": a["features"],
                    "prior": 0.18 * a["prior"],
                    "return": value(a["outcome"]),
                }
                for a in r["arms"]
            ]
        }
        for r in records
    ]


def evaluate(records, model, scale, margin):
    changes = wins = hp = 0
    gain = 0.0
    for row in records:
        arms = row["arms"]
        old = next(i for i, a in enumerate(arms) if a["id"] == row["baseline"])
        scores = [0.18 * a["prior"] + scale * model.predict(0, a["features"]) for a in arms]
        best = max(range(len(arms)), key=scores.__getitem__)
        if scores[best] <= scores[old] + margin:
            best = old
        b, a = arms[old]["outcome"], arms[best]["outcome"]
        changes += best != old
        wins += a["won"] - b["won"]
        hp += a["hp"] - b["hp"]
        gain += value(a) - value(b)
    return {
        "positions": len(records),
        "changes": changes,
        "net_fight_wins": wins,
        "net_exit_hp": hp,
        "gain": gain,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for k in ("labels", "teacher-bundle", "bundle", "seed-lock", "output"):
        p.add_argument("--" + k, type=Path, required=True)
    p.add_argument(
        "--fit-inventory",
        type=Path,
        help="Reproduce the same frozen training and validation positions",
    )
    a = p.parse_args()
    src = a.labels / "receipt.json"
    stamp = sha256(src.read_bytes()).hexdigest()
    receipt = json.loads(src.read_bytes())
    if (
        receipt["bundle"] != sha256(a.teacher_bundle.read_bytes()).hexdigest()
        or receipt["seed_lock"] != sha256(a.seed_lock.read_bytes()).hexdigest()
    ):
        raise ValueError("Training teacher or seed lock mismatch")
    lock = json.loads(a.seed_lock.read_bytes())["seeds"]
    protected = set(lock["development"]) | set(lock["test"])
    groups = {False: [], True: []}
    seeds = {False: set(), True: set()}
    inventory = None
    if a.fit_inventory:
        previous = json.loads(a.fit_inventory.read_bytes())
        if previous["receipt"] != stamp:
            raise ValueError("Different frozen teacher receipt")
        inventory = set(previous["train_decisions"] + previous["validation_decisions"])
    for root in receipt["roots"]:
        path = a.labels / (root + ".json")
        if not path.is_file():
            continue
        row = json.loads(path.read_bytes())
        if row["opening"] != root or row["receipt_sha256"] != stamp or row["seed"] in protected:
            raise ValueError("Invalid supervised native root")
        validation = int.from_bytes(sha256(row["seed"].encode()).digest()[:4], "big") % 5 == 0
        for pos in row["decisions"]:
            if inventory is not None and pos["digest"] not in inventory:
                continue
            groups[validation].append(pos)
            seeds[validation].add(row["seed"])
    train, valid = groups[False], groups[True]
    if inventory is not None and {r["digest"] for r in train + valid} != inventory:
        raise ValueError("Missing frozen action decisions")
    if len(train) < 10 or len(valid) < 5:
        raise ValueError("Too few independent seed-grouped examples")
    options = []
    for ridge in (12, 48, 160):
        model = OfferModel.fit(fit_rows(train), ridge=ridge)
        for scale in (0.35, 0.7, 1.0):
            for margin in (0.5, 1.5):
                measured = evaluate(valid, model, scale, margin)
                options.append(
                    (measured["gain"], -measured["changes"], ridge, scale, margin, model, measured)
                )
    _, _, ridge, scale, margin, model, metrics = max(options, key=lambda p: p[:2])
    role, options_bundle = load_bundle(a.bundle)
    config = json.loads(options_bundle["encounter_model"].read_bytes())
    config["act2_action_ranker"] = {
        "weights": model.weights,
        "formations": [receipt["formation"]],
        "scale": scale,
        "prior_scale": 0.18,
        "margin": margin,
    }
    a.output.mkdir(parents=True, exist_ok=False)
    save_json(a.output / "encounter.json", config)
    options_bundle["encounter_model"] = a.output / "encounter.json"
    freeze_bundle({"args": {**options_bundle, "roles": [role]}}, a.output / "policy")
    save_json(
        a.output / "fit.json",
        {
            "receipt": stamp,
            "input_bundle": sha256(a.bundle.read_bytes()).hexdigest(),
            "train_seeds": sorted(seeds[False]),
            "validation_seeds": sorted(seeds[True]),
            "train_decisions": [r["digest"] for r in train],
            "validation_decisions": [r["digest"] for r in valid],
            "chosen": {"ridge": ridge, "scale": scale, "margin": margin},
            "train": evaluate(train, model, scale, margin),
            "validation": metrics,
            "validation_grid": [
                {"ridge": r, "scale": s, "margin": m, **v} for _, _, r, s, m, _, v in options
            ],
        },
    )
    print(json.dumps(metrics))


if __name__ == "__main__":
    main()
