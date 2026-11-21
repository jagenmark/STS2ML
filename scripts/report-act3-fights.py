"""Summarize frozen Act 3 fight comparisons on identical first playable hands."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

from sts2rl.act1 import save_json


def panel(directory, selection_hash, protected):
    raw = (directory / "receipt.json").read_bytes()
    receipt = json.loads(raw)
    stamp = hashlib.sha256(raw).hexdigest()
    if receipt["selection_sha256"] != selection_hash or receipt["purpose"] != "test-diagnostic":
        raise ValueError("Expected the frozen post-selection diagnostic")
    rows, errors, identities = [], [], set()
    for root in receipt["roots"]:
        r = json.loads((directory / (root + ".json")).read_bytes())
        identity = (r["seed"], r["formation"])
        if (
            r["receipt_sha256"] != stamp
            or r["root"] != root
            or r["seed"] not in protected
            or identity in identities
        ):
            raise ValueError("Unmatched native opening or test seed")
        identities.add(identity)
        if "error" in r:
            errors.append(
                {"seed": r["seed"], "formation": r["formation"], "root": root, "error": r["error"]}
            )
        else:
            if set(r["outcomes"]) != {"baseline", "candidate"}:
                raise ValueError("Both policies must play each scored fight")
            rows.append(r)
    return rows, errors


def metrics(rows):
    def score(arm):
        picked = [r["outcomes"][arm] for r in rows]
        return {
            "won": sum(v["won"] for v in picked),
            "exit_hp_sum": sum(v["hp"] for v in picked),
            "potions_left_sum": sum(v["potions"] for v in picked),
        }

    return {
        "openings": len(rows),
        "seeds": len({r["seed"] for r in rows}),
        "incumbent": score("baseline"),
        "combat": score("candidate"),
        "gained": sum(
            not r["outcomes"]["baseline"]["won"] and r["outcomes"]["candidate"]["won"] for r in rows
        ),
        "lost": sum(
            r["outcomes"]["baseline"]["won"] and not r["outcomes"]["candidate"]["won"] for r in rows
        ),
    }


def summarize(study, selection, registry):
    stamp = hashlib.sha256(selection.read_bytes()).hexdigest()
    seeds = set(json.loads(registry.read_bytes())["seeds"]["test"])
    if (
        json.loads(selection.read_bytes())["seed_lock_sha256"]
        != hashlib.sha256(registry.read_bytes()).hexdigest()
    ):
        raise ValueError("Different test seed registry")
    result = {}
    for name, sub in (("natural", "held-natural-fights"), ("elite_pool", "held-elite-fights")):
        rows, errors = panel(study / sub, stamp, seeds)
        if name == "elite_pool" and any(r["room"] != "Elite" for r in rows):
            raise ValueError("Pooled panel contains a non-elite fight")
        result[name] = {
            "overall": metrics(rows),
            "errors": errors,
            "rooms": {
                k: metrics([r for r in rows if r["room"] == k])
                for k in sorted({r["room"] for r in rows})
            },
            "formations": {
                k: metrics([r for r in rows if r["formation"] == k])
                for k in sorted({r["formation"] for r in rows})
            },
        }
    for folder, key in (
        ("held-natural-roots", "original_route"),
        ("held-probe-roots", "elite_seeking_route"),
    ):
        root = study / folder
        report = json.loads((root / "manifest.json").read_bytes())
        failures = []
        for f in root.glob("*.json.gz"):
            with gzip.open(f, "rt", encoding="utf-8") as inp:
                group = json.load(inp)
            if group["error"]:
                failures.append({"seed": group["seed"], "error": group["error"]})
        result[key] = {
            "maps": len(report["seeds"]),
            "physical_starts": report["starts"],
            "restore_errors": failures,
        }
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("study", "selection", "registry", "output"):
        p.add_argument("--" + name, required=True, type=Path)
    a = p.parse_args()
    result = summarize(a.study, a.selection, a.registry)
    save_json(a.output, result)
    for name in ("natural", "elite_pool"):
        print(name, result[name]["rooms"])


if __name__ == "__main__":
    main()
