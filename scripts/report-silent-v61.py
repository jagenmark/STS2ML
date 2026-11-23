"""Recompute the four-arm CSV5DEV metrics from compact, per-lobby audit receipts."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "docs/combat-search-v2/v61-cohorts.json"
ARMS = ("v5", "hallways", "boss-safe", "heuristic")
BOSSES = {"KAISER_CRAB_BOSS": "CRUSHER+ROCKET", "KNOWLEDGE_DEMON_BOSS": "KNOWLEDGE_DEMON",
          "THE_INSATIABLE_BOSS": "THE_INSATIABLE"}


def pack(directory, destination):
    with destination.open("xb") as file, gzip.GzipFile(filename="", mode="wb", fileobj=file, mtime=0) as archive:
        for arm in ARMS:
            with gzip.open(directory / f"dev-{arm}.jsonl.gz", "rb") as stream:
                for line in stream:
                    if json.loads(line)["arm"] != arm:
                        raise ValueError("Wrong input arm")
                    archive.write(line)


def summary(path):
    if hashlib.sha256(LOCK.read_bytes()).hexdigest() != "c49e77b83a761acbc68f3e5f6e8e07ec076ce65493acabe8790e7b0b79a3e11d":
        raise ValueError("CSV5 cohort lock changed")
    registry = json.loads(LOCK.read_bytes())["DEV"]
    mode_indices = [[i for i, (_, _, m) in enumerate(registry) if m == mode] for mode in ("default", "seeded")]
    rng = np.random.default_rng(561)
    resamples = np.concatenate([rng.choice(ids, (10000, len(ids))) for ids in mode_indices], axis=1)
    with gzip.open(path, "rt", encoding="utf8") as stream:
        receipts = [json.loads(line) for line in stream]
    by_lobby = {(r["arm"], r["seed"]): r for r in receipts}
    if len(receipts) != len(by_lobby) or len(receipts) != len(registry) * len(ARMS):
        raise ValueError("Duplicate or incomplete panel")
    results, floors = {}, {}
    reference = None
    for arm in ARMS:
        rows = [by_lobby[arm, seed] for _, seed, _ in registry]
        fights = []
        for (index, seed, mode), row in zip(registry, rows, strict=True):
            if ((row["index"], row["act_list"], row["status"]) != (index, mode, "complete")
                    or row.get("abandoned") or row["ascension"] != 10):
                raise ValueError(f"Invalid terminal receipt for {arm}/{seed}")
            these = {tuple(f[:4]): f[4:] for f in row["fights"]}
            if len(these) != len(row["fights"]):
                raise ValueError("Duplicate fight key")
            fights.append(these)
        if reference is None:
            reference = fights
        floors[arm] = np.array([(r["act"] - 1) * 17 + r["floor"] for r in rows])
        coverage = {}
        census = {}
        for group in sorted({k for r in rows for k in r["coverage"]}):
            counts = Counter()
            for r in rows:
                counts.update(r["coverage"].get(group, {}))
            coverage[group] = [counts["covered"], counts.total()]
            if group in ("act2_monster", "act2_elite"):
                census[group] = dict(counts.most_common())
        coverage["act2_monster_elite"] = [sum(pair) for pair in zip(coverage["act2_monster"], coverage["act2_elite"], strict=True)]
        paired_hp = {}
        for group, act, rooms in (("hallway", 2, {"Monster"}), ("elite", 2, {"Elite"}), ("boss", 2, {"Boss"}),
                                  ("act3", 3, None)):
            pairs = [(current[key], base[key]) for current, base in zip(fights, reference, strict=True)
                     for key in sorted(current.keys() & base.keys()) if key[0] == act and (rooms is None or key[2] in rooms)]
            if pairs:
                hp = np.array([[c[:2], b[:2]] for c, b in pairs], dtype=float)
                diff = hp[:, 0] - hp[:, 1]
                paired_hp[group] = dict(n=len(pairs), entry_hp=hp[:, 0, 0].mean(), exit_hp=hp[:, 0, 1].mean(),
                                        v5_entry_hp=hp[:, 1, 0].mean(), v5_exit_hp=hp[:, 1, 1].mean(),
                                        delta_entry=diff[:, 0].mean(), delta_exit=diff[:, 1].mean(),
                                        delta_net_loss=(diff[:, 0] - diff[:, 1]).mean())
        bosses = [f for r in rows for f in r["fights"] if f[0] == 2 and f[2] == "Boss"]
        entered = sum(any(a == 2 for a, _ in r["boss_fights"]) for r in rows)
        assert len(bosses) == entered and all(f[3] in BOSSES.values() for f in bosses)
        assert sum(f[6] for f in bosses) == sum(r["a2_clear"] for r in rows)
        # The historical 22.2 HP separator was cumulative across regular
        # hallways. Compare that same unit among paired boss entrants.
        loss_pairs = []
        for current, base in zip(fights, reference, strict=True):
            if not any(k[0] == 2 and k[2] == "Boss" for k in current.keys() & base.keys()):
                continue
            loss_pairs.append([sum(hp[0] - hp[1] for k, hp in group.items() if k[0] == 2 and k[2] == "Monster")
                               for group in (current, base)])
        losses = np.array(loss_pairs)
        delta = floors[arm] - floors["v5"]
        results[arm] = dict(n=len(rows), mean_floor=floors[arm].mean(), delta_floor=delta.mean(),
                            ci=np.quantile(delta[resamples].mean(axis=1), [.025, .975]).tolist(),
                            a1_clear=sum(r["a1_clear"] for r in rows), a2_boss=entered,
                            a2_clear=sum(r["a2_clear"] for r in rows),
                            a3_boss=sum(any(a == 3 for a, _ in r["boss_fights"]) for r in rows),
                            wins=sum(r["win"] for r in rows), boss_entry_hp=np.mean([f[4] for f in bosses]),
                            boss_survival={k: [sum(f[6] for f in bosses if f[3] == name), sum(f[3] == name for f in bosses)]
                                           for k, name in BOSSES.items()},
                            coverage=coverage, fallbacks=census, paired_hp=paired_hp,
                            paired_boss_entrant_hallway_loss=dict(n=len(losses), arm=losses[:, 0].mean(),
                                                                  v5=losses[:, 1].mean(), delta=(losses[:, 0] - losses[:, 1]).mean()),
                            latency_ms=(np.quantile([n for r in rows for n in r["combat_ns"]], [.50, .95]) / 1e6).tolist(),
                            native=dict(sum((Counter(r["native"]) for r in rows), Counter())))
    for lhs, rhs in (("boss-safe", "hallways"), ("heuristic", "boss-safe")):
        diff = floors[lhs] - floors[rhs]
        results[f"{lhs}_minus_{rhs}"] = dict(delta=diff.mean(), ci=np.quantile(diff[resamples].mean(axis=1), [.025, .975]).tolist())
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipts", type=Path)
    parser.add_argument("--pack", type=Path, help="combine the four arm receipts before summarizing")
    args = parser.parse_args()
    if args.pack:
        pack(args.pack, args.receipts)
    print(json.dumps(summary(args.receipts), indent=2, allow_nan=False))
