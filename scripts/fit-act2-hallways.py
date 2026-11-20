"""Fit and validate a pre-boss combat-plan selector from paired native outcomes."""

import argparse
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path

import numpy as np

from sts2rl.act1 import save_json
from sts2rl.run_bundle import freeze_bundle, load_bundle


def grouped_validation(seed):
    return int.from_bytes(sha256(seed.encode()).digest()[:4], "big") % 5 == 0


def value(outcome):
    return (
        40 * outcome["won"]
        + 0.65 * outcome["hp"]
        + 2 * outcome["potions"]
        + 3 * (1 - outcome["remaining"])
    )


def read_rows(directory, lock, bundle):
    receipt_path = directory / "receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    stamp = sha256(receipt_path.read_bytes()).hexdigest()
    if receipt.get("purpose", "train") != "train":
        raise ValueError("Only training receipts may fit the combat policy")
    if (
        receipt["bundle_sha256"] != sha256(bundle.read_bytes()).hexdigest()
        or receipt["seed_lock_sha256"] != sha256(lock.read_bytes()).hexdigest()
    ):
        raise ValueError("Incompatible teacher bundle or seed lock")
    protected = json.loads(lock.read_bytes())["seeds"]
    reserved = set(protected["development"]) | set(protected["test"])
    rows = []
    for root in receipt["roots"]:
        path = directory / (root + ".json")
        if not path.exists():
            continue
        row = json.loads(path.read_bytes())
        if row["seed"] in reserved or row["root"] != root or row["receipt_sha256"] != stamp:
            raise ValueError("Misidentified or protected training root")
        if "error" in row:
            continue
        if set(row["outcomes"]) != set(receipt["plans"]):
            raise ValueError("Incomplete paired case")
        rows.append(row)
    return receipt, stamp, rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("labels", "bundle", "seed-lock", "output"):
        p.add_argument("--" + key, required=True, type=Path)
    p.add_argument("--mode", choices=("table", "linear"), default="table")
    p.add_argument("--min-cases", type=int, default=5)
    p.add_argument("--margin", type=float, default=0.6)
    p.add_argument("--ridge", type=float, default=26)
    p.add_argument(
        "--fit-inventory", type=Path, help="Reproduce a frozen fit from a larger label archive"
    )
    p.add_argument(
        "--hunter-model",
        type=Path,
        help="Use the separately fitted Hunter plan on that exact formation",
    )
    args = p.parse_args()
    receipt, stamp, rows = read_rows(args.labels, args.seed_lock, args.bundle)
    if args.fit_inventory:
        previous = json.loads(args.fit_inventory.read_bytes())
        roots = set(previous["train_roots"] + previous["validation_roots"])
        rows = [r for r in rows if r["root"] in roots]
        if previous["receipt"] != stamp or {r["root"] for r in rows} != roots:
            raise ValueError("Missing or incompatible frozen fit inventory")
    names = [n for n in receipt["plans"] if n != "baseline"]
    plans = {n: receipt["plans"][n] for n in names}
    train = [r for r in rows if not grouped_validation(r["seed"])]
    valid = [r for r in rows if grouped_validation(r["seed"])]
    if not train:
        raise ValueError("Empty training split")
    groups = defaultdict(list)
    for r in train:
        groups[r["formation"]].append(r)

    def gain(r, name):
        return value(r["outcomes"][name]) - value(r["outcomes"]["baseline"])

    def table_value(subset, name):
        return sum(gain(r, name) for r in subset) / (5 + len(subset))

    by_formation = {}
    for formation, subset in groups.items():
        choice = max(names, key=lambda n: table_value(subset, n))
        if len(subset) >= args.min_cases and table_value(subset, choice) > args.margin:
            by_formation[formation] = choice
    hallway = {"plans": plans, "by_formation": by_formation}
    if args.mode == "linear":
        keys = sorted({k for r in train for k in r["features"]})
        matrix = np.array([[r["features"].get(k, 0) for k in keys] for r in train])
        targets = np.array([[gain(r, n) for n in names] for r in train])
        matrix_weights = np.linalg.solve(
            matrix.T @ matrix + args.ridge * np.eye(len(keys)), matrix.T @ targets
        )
        hallway.update(
            linear={
                n: dict(zip(keys, matrix_weights[:, i].tolist(), strict=True))
                for i, n in enumerate(names)
            },
            margin=args.margin,
        )
    if args.hunter_model:
        if args.mode == "linear":
            p.error("Use table mode for an exact formation override")
        _, other = load_bundle(args.hunter_model)
        hs = json.loads(other["encounter_model"].read_bytes())["act2_hallways"]
        by_formation.pop("HUNTER_KILLER", None)
        if "HUNTER_KILLER" in hs["by_formation"]:
            plan = hs["plans"][hs["by_formation"]["HUNTER_KILLER"]]
            plans["hunter_specialist"] = plan
            by_formation["HUNTER_KILLER"] = "hunter_specialist"

    def predict(r):
        name = by_formation.get(r["formation"], "baseline")
        if name not in r["outcomes"]:
            return None
        if args.mode == "linear":
            est = {
                n: sum(v * m.get(k, 0) for k, v in r["features"].items())
                for n, m in hallway["linear"].items()
            }
            best = max(est, key=est.get)
            if est[best] > max(0.0, est.get(name, 0)) + args.margin:
                name = best
        return name

    def report(subset):
        pairs = [(r, n) for r in subset if (n := predict(r)) is not None]

        def stats(items):
            return {
                "wins": sum(i["won"] for i in items),
                "exit_hp": sum(i["hp"] for i in items),
                "potions_left": sum(i["potions"] for i in items),
            }

        base = [r["outcomes"]["baseline"] for r, n in pairs]
        picked = [r["outcomes"][n] for r, n in pairs]
        return {
            "scored_roots": len(pairs),
            "baseline": stats(base),
            "selected": stats(picked),
            "gain": sum(gain(r, n) for r, n in pairs),
            "per_arm": {n: stats([r["outcomes"][n] for r in subset]) for n in ("baseline", *names)},
        }

    args.output.mkdir(parents=True, exist_ok=False)
    _, settings = load_bundle(args.bundle)
    enc = json.loads(settings["encounter_model"].read_bytes())
    enc["act2_hallways"] = hallway
    save_json(args.output / "encounter.json", enc)
    role, options = load_bundle(args.bundle)
    options["encounter_model"] = args.output / "encounter.json"
    freeze_bundle({"args": {**options, "roles": [role]}}, args.output / "policy")
    save_json(
        args.output / "fit.json",
        {
            "receipt": stamp,
            "parameters": {
                "mode": args.mode,
                "ridge": args.ridge,
                "margin": args.margin,
                "min_cases": args.min_cases,
            },
            "train_roots": [r["root"] for r in train],
            "validation_roots": [r["root"] for r in valid],
            "separate_hunter_bundle": sha256(args.hunter_model.read_bytes()).hexdigest()
            if args.hunter_model
            else None,
            "formations": by_formation,
            "train": report(train),
            "validation": report(valid),
        },
    )
    print(
        json.dumps(
            {"formations": by_formation, "train": report(train), "validation": report(valid)}
        )
    )


if __name__ == "__main__":
    main()
