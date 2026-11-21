"""Attribute held-out Act 3 entries to native bosses from identical first hands."""

import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import tempfile

from sts2rl.act1 import save_json
from sts2rl.native import NativeError, NativeSession, digest
from sts2rl.trajectory import act2_boss_root

ROOT = Path(__file__).resolve().parents[1]


def opening(task):
    first, second, host = task
    base, candidate = (json.loads((f / "result.json").read_bytes()) for f in (first, second))
    fork = act2_boss_root(first)
    if act2_boss_root(second) != fork:
        raise ValueError("Paired models did not receive the same native boss opening")
    errors = []
    for attempt in range(3):
        try:
            with tempfile.TemporaryDirectory() as temp:
                with NativeSession(
                    ROOT, Path(temp) / "host", host_path=host, act_list="seeded", timeout=90
                ) as game:
                    if attempt < 2:
                        state = game.restore(fork)
                    else:
                        state = game.reset(fork.specification["seed"])
                        for command in fork.history:
                            state = game._request(command)
                        if digest(state) != fork.expected_digest:
                            raise ValueError("The stepwise boss opening diverged")
            break
        except (NativeError, ValueError, TimeoutError) as exc:
            errors.append(str(exc))
    else:
        raise RuntimeError(f"Cannot verify boss {base['seed']}: {errors}")
    if (
        state["decision"] != "combat_play"
        or state["round"] != 1
        or state["context"]["room_type"] != "Boss"
    ):
        raise ValueError("Expected first hand in a boss fight")
    return {
        "seed": base["seed"],
        "boss": state["context"]["boss"]["id"],
        "opening": fork.expected_digest,
        "hp": state["player"]["hp"],
        "baseline": base["a2_clear"],
        "challenger": candidate["a2_clear"],
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("baseline", "challenger", "host", "seed-lock", "selection", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--workers", type=int, default=3)
    a = p.parse_args()
    if (
        hashlib.sha256(a.seed_lock.read_bytes()).hexdigest()
        != json.loads(a.selection.read_bytes())["seed_lock_sha256"]
    ):
        raise ValueError("Registry does not match the frozen evaluation")
    seeds = json.loads(a.seed_lock.read_bytes())["seeds"]["test"]
    tasks = []
    for i, seed in enumerate(seeds):
        pair = [f / "candidate" / f"run-{i:04d}" for f in (a.baseline, a.challenger)]
        rows = [json.loads((f / "result.json").read_bytes()) for f in pair]
        if any(
            r["status"] != "complete" or r["seed"] != seed or r["start_act"] != 1 or r["index"] != i
            for r in rows
        ):
            raise ValueError("Wrong or incomplete natural pair")
        reached = [any(act == 2 for act, _ in r["boss_fights"]) for r in rows]
        if reached[0] != reached[1]:
            raise ValueError("Boss-only policy changed which seeds reached the boss")
        if reached[0]:
            tasks.append((*pair, a.host.resolve()))
    with ProcessPoolExecutor(a.workers) as pool:
        rows = list(pool.map(opening, tasks))
    groups = defaultdict(list)
    for row in rows:
        groups[row["boss"]].append(row)
    summary = {
        k: {
            "arrivals": len(g),
            "baseline": sum(r["baseline"] for r in g),
            "challenger": sum(r["challenger"] for r in g),
            "gained": sum(r["challenger"] and not r["baseline"] for r in g),
            "lost": sum(r["baseline"] and not r["challenger"] for r in g),
        }
        for k, g in groups.items()
    }
    save_json(a.output, {"summary": summary, "games": rows})


if __name__ == "__main__":
    main()
