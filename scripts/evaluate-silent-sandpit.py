"""Test Frantic Escape thresholds against complete, matched native boss openings."""

import argparse
import gzip
import json
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from sts2rl.act1 import save_json
from sts2rl.encounter import EncounterModel
from sts2rl.native import NativeSession
from sts2rl.run_bundle import load_bundle
from sts2rl.run_policy import RunPolicy, RunWeights
from sts2rl.trajectory import strategy_roots

ROOT = Path(__file__).resolve().parents[1]


def is_boss_opening(state):
    ctx = state.get("context") or {}
    return (
        state["decision"] == "combat_play"
        and ctx.get("act") == 2
        and ctx.get("room_type") == "Boss"
        and (ctx.get("boss") or {}).get("id") == "THE_INSATIABLE_BOSS"
    )


def test_root(task):
    source, host, bundle = task
    _, settings = load_bundle(bundle)
    config = json.loads(settings["encounter_model"].read_bytes())
    weights = RunWeights.load(settings["weights"])
    _, fork = next((s, f) for s, f in strategy_roots(source) if is_boss_opening(s))
    row = {"seed": fork.specification["seed"], "root": fork.expected_digest}
    outcomes = {}
    try:
        with (
            TemporaryDirectory() as tmp,
            NativeSession(
                ROOT,
                Path(tmp) / "game",
                host_path=host,
                act_list=fork.specification.get("act_list", "default"),
            ) as game,
        ):
            for threshold in range(5):
                state = game.restore(fork)
                encounter = EncounterModel({**config, "sandpit_threshold": threshold})
                policy = RunPolicy(weights)
                for _ in range(300):
                    if state["decision"] == "game_over" or not state.get("in_combat"):
                        break
                    if state["decision"] == "combat_play":
                        enemy_hp = state["enemies"][0]["hp"]
                        last_round = state["round"]
                    state = game.step(encounter.choose(state, policy))
                else:
                    raise RuntimeError("Combat action budget exhausted")
                won = state["decision"] != "game_over"
                outcomes[str(threshold)] = {
                    "won": won,
                    "hp": state["player"]["hp"],
                    "enemy": 0 if won else enemy_hp,
                    "round": last_round,
                }
    except (ValueError, RuntimeError, TimeoutError) as error:
        return {**row, "error": str(error)}
    return {**row, "outcomes": outcomes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("host", "bundle", "output"):
        parser.add_argument("--" + flag, required=True, type=Path)
    parser.add_argument("--source", nargs="+", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    tasks = []
    seen = set()
    for parent in args.source:
        for path in sorted(parent.glob("run-*/result.json")):
            result = json.loads(path.read_bytes())
            strategy = path.with_name("strategy.jsonl.gz")
            if (
                result["status"] != "complete"
                or result.get("opening_partition") == "test"
                or not any(a == 2 for a, _ in result["boss_fights"])
                or not strategy.is_file()
            ):
                continue
            with gzip.open(strategy, "rt", encoding="utf-8") as stream:
                if not any(is_boss_opening(json.loads(line)["state"]) for line in stream):
                    continue
            if result["seed"] in seen:
                raise ValueError(f"Duplicate source seed {result['seed']}")
            seen.add(result["seed"])
            tasks.append((path.parent, args.host.resolve(), args.bundle.resolve()))
    with ProcessPoolExecutor(args.workers) as pool:
        for row in pool.map(test_root, tasks):
            save_json(args.output / (row["seed"] + ".json"), row)
    save_json(
        args.output / "manifest.json",
        {
            "reference_sha256": sha256(args.bundle.read_bytes()).hexdigest(),
            "host_sha256": sha256(args.host.read_bytes()).hexdigest(),
            "seeds": sorted(seen),
        },
    )


if __name__ == "__main__":
    main()
