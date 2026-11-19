"""Select whole-run deck and map parameters on common, disjoint native seed blocks."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import json
from pathlib import Path
from random import Random
from statistics import fmean

from sts2rl.act1 import save_json
from sts2rl.run_bundle import load_bundle
from sts2rl.run_evaluation import play_episode
from sts2rl.run_policy import IDENTITY, RunWeights

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("bundle", "router", "encounter", "host", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--prefix", required=True)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--population", type=int, default=9)
    p.add_argument("--stages", nargs="+", type=int, default=[24, 48, 72])
    args = p.parse_args()
    if args.population < 2 or min(args.stages + [args.workers]) < 1:
        p.error("Invalid search budget")
    actor, config = load_bundle(args.bundle)
    weights = asdict(RunWeights.load(config.pop("weights")))
    options = {k: str(v) if isinstance(v, Path) else v for k, v in config.items()}
    router = json.loads(args.router.read_text())
    rng = Random(816348)
    args.output.mkdir(parents=True, exist_ok=False)
    save_json(args.output / "config.json", json.loads(json.dumps(vars(args), default=str)))
    params = []
    bounds = [
        ("risk", 1.1, 5.0),
        ("health", 0.60, 1.85),
        ("reward", 0.5, 2.7),
        ("elite", -0.25, 0.2),
        ("scaling", 0.75, 1.85),
        ("threshold", 6.0, 14.0),
        ("defense", 0.68, 1.4),
        ("duplicate", 0.6, 2.9),
    ]
    # Stratification covers each parameter range in the first block.
    grids = {k: rng.sample(range(args.population - 1), args.population - 1) for k, _, _ in bounds}
    for i in range(args.population):
        param = (
            {
                "risk": 2.5,
                "health": 1.0,
                "reward": 1.0,
                "elite": 0.0,
                "scaling": 1.0,
                "threshold": 9.0,
                "defense": 1.0,
                "duplicate": 1.6,
            }
            if i == 0
            else {
                k: lo + (hi - lo) * (grids[k][i - 1] + rng.random()) / (args.population - 1)
                for k, lo, hi in bounds
            }
        )
        folder = args.output / f"p{i:02d}"
        folder.mkdir()
        save_json(folder / "params.json", param)
        save_json(folder / "room_model.json", {**router, **{k: param[k] for k, _, _ in bounds[:4]}})
        save_json(
            folder / "deck_model.json",
            {"version": 1, "runtime_identity": IDENTITY, **{k: param[k] for k, _, _ in bounds[4:]}},
        )
        params.append(folder)
    active = list(range(args.population))
    stage_scores = {i: [] for i in active}
    with ProcessPoolExecutor(args.workers) as pool:
        for stage, n in enumerate(args.stages):
            tasks = []
            for j in range(n):
                for i in active:
                    folder = params[i]
                    opts = {
                        **options,
                        "room_model": str(folder / "room_model.json"),
                        "deck_model": str(folder / "deck_model.json"),
                        "encounter_model": str(args.encounter),
                    }
                    tasks.append(
                        (
                            ROOT,
                            args.host,
                            folder / f"stage-{stage}" / f"run-{j:04d}",
                            f"{args.prefix}G{stage}S{j:04d}",
                            j,
                            actor,
                            weights,
                            None,
                            opts,
                        )
                    )
            results = list(pool.map(play_episode, tasks))
            pairs = [[results[j * len(active) + i] for i in range(len(active))] for j in range(n)]
            common = [pair for pair in pairs if all(r["status"] == "complete" for r in pair)]
            if len(common) < 0.6 * n:
                raise ValueError("Too few complete matches for parameter search")
            metrics = {}
            for j, i in enumerate(active):
                rows = [pair[j] for pair in common]
                vals = [
                    (r["act"] - 1) * 19
                    + r["floor"]
                    + 4 * r["a1_clear"]
                    + 12 * r["a2_clear"]
                    + 70 * r["win"]
                    + (1 - r["boss_hp_fraction"] if r["boss_hp_fraction"] is not None else 0.0)
                    for r in rows
                ]
                stage_scores[i].extend(vals)
                metrics[i] = {
                    "pairs": len(rows),
                    "act2": sum(r["a1_clear"] for r in rows),
                    "act3": sum(r["a2_clear"] for r in rows),
                    "wins": sum(r["win"] for r in rows),
                    "mean": fmean(vals),
                    "cumulative": fmean(stage_scores[i]),
                }
            ranked = sorted(active, key=lambda i: metrics[i]["cumulative"], reverse=True)
            active = ranked[: max(1, (len(ranked) + 1) // 2)]
            save_json(args.output / f"stage-{stage}.json", {"metrics": metrics, "next": active})
            print(stage, metrics, flush=True)
    save_json(
        args.output / "winner.json",
        {"selected": active[0], "source": str(params[active[0]]), "stages": args.stages},
    )


if __name__ == "__main__":
    main()
