"""Fit Act 3 hallway, unknown-room and elite costs from distinct native training visits."""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

import numpy as np

from sts2rl.act1 import save_json
from sts2rl.native import digest
from sts2rl.run_bundle import freeze_bundle, load_bundle
from sts2rl.survival_route import _keys


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("base", "maps", "output"):
        p.add_argument("--" + key, required=True, type=Path)
    p.add_argument("--source", required=True, nargs="+", type=Path)
    p.add_argument("--prior", type=float, default=8)
    p.add_argument("--risk", type=float)
    p.add_argument("--health", type=float)
    p.add_argument("--elite", type=float)
    a = p.parse_args()
    entries = json.loads((a.maps / "index.json").read_bytes())
    if any(e["partition"] != "train" for e in entries) or a.prior < 0:
        p.error("Expected training maps and a nonnegative prior")
    keys = {e["seed"]: e["map_digest"] for e in entries}
    role, opts = load_bundle(a.base)
    model = json.loads(opts["late_room_model"].read_bytes())
    seen = set()
    cells = defaultdict(lambda: np.zeros(9))
    counts, deaths = Counter(), Counter()
    for source in a.source:
        for path in sorted(source.glob("*/result.json")):
            run = json.loads(path.read_bytes())
            if (
                run["status"] != "complete"
                or run["start_act"] != 3
                or run["seed"] not in keys
                or run["start_digest"] != keys[run["seed"]]
            ):
                raise ValueError("Expected a complete training run from its signed Act 3 map")
            for r in run["rooms"]:
                icon, before, after = r["icon"], r["before"], r["after"]
                if r["act"] != 3 or icon not in ("Elite", "Monster", "Unknown"):
                    continue
                mark = digest([run["seed"], r])
                if mark in seen:
                    continue
                seen.add(mark)
                counts[icon] += 1
                deaths[icon] += int(r["died"])
                vector = np.array(
                    [
                        1,
                        r["died"],
                        *[
                            0 if r["died"] else after[k] - before[k]
                            for k in (
                                "hp",
                                "gold",
                                "relics",
                                "upgrades",
                                "potions",
                                "cards",
                                "max_hp",
                            )
                        ],
                    ]
                )
                for key in _keys(
                    icon, 3, r["row"], before["hp"] / before["max_hp"], before["gold"]
                )[1:]:
                    cells[key] += vector
    if not seen:
        raise ValueError("No training visits")
    for key, observed in cells.items():
        old = np.array(model["cells"].get(key, [0.0] * 9), dtype=float)
        prior = old * (min(a.prior, old[0]) / old[0]) if old[0] else old
        model["cells"][key] = (observed + prior).tolist()
    overrides = {k: getattr(a, k) for k in ("risk", "health", "elite") if getattr(a, k) is not None}
    if overrides:
        model["act3_weights"] = overrides
    a.output.mkdir(parents=True, exist_ok=False)
    save_json(a.output / "late-room.json", model)
    opts["late_room_model"] = a.output / "late-room.json"
    freeze_bundle({"args": {**opts, "roles": [role]}}, a.output / "policy")
    save_json(
        a.output / "fit.json",
        {
            "training_maps": keys,
            "unique_visits": dict(counts),
            "deaths": dict(deaths),
            "visits_sha256": digest(sorted(seen)),
            "prior": a.prior,
            "act3_weights": overrides,
            "base_sha256": hashlib.sha256(a.base.read_bytes()).hexdigest(),
        },
    )
    print(dict(counts), dict(deaths))


if __name__ == "__main__":
    main()
