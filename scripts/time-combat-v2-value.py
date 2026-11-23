"""Measure feature packing, NumPy forward pass and calibration on CPU."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from time import perf_counter_ns
from dataclasses import replace

from sts2rl.combat_search_v2.state import Card, Enemy, State, Variant
from sts2rl.combat_search_v2.transitions import ATTACKS, CARDS, STATUS


def fixtures():
    cards = tuple(Variant(name, "Attack" if name in ATTACKS else "Status" if name in STATUS else "Skill",
                          1, "Self", upgrade=i % 2) for i, name in enumerate(sorted(CARDS)))
    for i in range(24):
        enemies = tuple(Enemy(j, name, (j + 1) * 9, 60, 3 * j, (("WEAK", 1), ("POISON", j)), (), 0, True)
                        for j, name in enumerate(("NIBBIT", "NIBBIT", "WRIGGLER", "SHRINKER_BEETLE",
                                                  "VANTOM", "THE_INSATIABLE")[:1 + i % 6]))
        retain = tuple(Card(j, cards[j]) for j in range(i % 5))
        yield State(21 + i, 70, i % 7, 3, 3, 2 + i // 4, 1 + i % 3, "Elite",
                    (("DEXTERITY", 2), ("BLUR", 1), ("AFTERIMAGE", 2)), enemies, retain,
                    cards[4:10 + i], cards[:i], outcome="completed", floor=9)


def main():
    # Configure BLAS before loading NumPy or the value module.
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "BLIS_NUM_THREADS"):
        os.environ[name] = "1"
    import numpy as np

    from sts2rl.combat_search_v2.artifact import CombatValueModel
    from sts2rl.combat_search_v2.features import FEATURE_NAMES, extract_leaf_features

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", type=Path, required=True)
    args = parser.parse_args()
    states = tuple(fixtures())
    results = {}
    for name in ("linear", "mlp32", "mlp64", "residual"):
        path = args.models / f"{name}.npz"
        if name == "residual" and not path.is_file():
            continue
        model = CombatValueModel.load(path)
        for _ in range(50):
            for state in states:
                model.leaf(state)
        elapsed = []
        for _ in range(320):
            for state in states:
                start = perf_counter_ns()
                model.leaf(state)
                elapsed.append((perf_counter_ns() - start) / 1e6)
        p50, p95 = np.percentile(elapsed, [50, 95])
        # Vary each formerly collapsed coordinate independently and also run
        # a physically realizable one-damage intervention through both packers.
        features = np.stack([extract_leaf_features(state, schema=model.schema) for state in states])

        def expected_hp(x):
            return model.predict(x).prod(axis=1) * x[:, 1]

        baseline = expected_hp(features)
        sensitivity = {}
        for key in ("enemy.0.hp", "living_hp"):
            changed = features.copy()
            changed[:, FEATURE_NAMES.index(key)] -= 1
            sensitivity[key] = float(np.median(expected_hp(changed) - baseline))
        damaged = [replace(s, enemies=(replace(s.enemies[0], hp=s.enemies[0].hp - 1), *s.enemies[1:]))
                   for s in states]
        sensitivity["one_damage"] = float(np.median(expected_hp(np.stack(
            [extract_leaf_features(s, schema=model.schema) for s in damaged])) - baseline))
        results[name] = {"p50_ms": float(p50), "p95_ms": float(p95), "samples": len(elapsed),
                         "damage_sensitivity": sensitivity,
                         "artifact_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    (args.models / "cpu-latency.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results), flush=True)


if __name__ == "__main__":
    main()
