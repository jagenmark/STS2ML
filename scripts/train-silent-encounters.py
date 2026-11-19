"""Fit a public fight-opening policy using paired outcomes from natural A10 fights."""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
from statistics import fmean

import numpy as np

from sts2rl.act1 import save_json
from sts2rl.encounter import EncounterPolicy, STYLES, combat_features
from sts2rl.native import NativeSession
from sts2rl.fight_rollout import fight
from sts2rl.run_policy import IDENTITY, RunWeights
from sts2rl.trajectory import map_combat_openings, strategy_roots

ROOT = Path(__file__).resolve().parents[1]


def collect(task):
    folder, source, host, weights, styles, beam, hallways, min_act = task
    rows, errors = [], []
    session = None
    folder.mkdir(parents=True, exist_ok=False)
    try:
        source_roots = (
            map_combat_openings(source, min_act, hallways) if hallways else strategy_roots(source)
        )
        for state, fork in source_roots:
            if state is not None and (
                state["decision"] != "combat_play" or state["context"]["room_type"] != "Boss"
            ):
                continue
            outcomes = {}
            for style in styles:
                try:
                    if session is None:
                        session = NativeSession(
                            ROOT,
                            folder / f"engine-{len(errors):03d}",
                            host_path=host,
                            ascension=10,
                            timeout=45,
                            act_list=fork.specification.get("act_list", "default"),
                        )
                    start = session.restore(fork)
                    if state is None:
                        state = start
                    if hallways and (
                        start["decision"] != "combat_play"
                        or start["context"]["room_type"] not in ("Monster", "Elite")
                    ):
                        break
                    actor = EncounterPolicy(weights, style=style)
                    outcomes[style] = fight(session, start, actor, beam)
                except Exception as exc:
                    errors.append({"root": fork.expected_digest, "style": style, "error": str(exc)})
                    if session is not None:
                        session.close()
                        session = None
                    break
            if len(outcomes) == len(styles):
                ctx = state["context"]
                rows.append(
                    {
                        "seed": fork.specification["seed"],
                        "root": fork.expected_digest,
                        "act": ctx["act"],
                        "encounter": "|".join(e["id"] for e in state["enemies"])
                        if hallways
                        else (ctx.get("boss") or {}).get("id"),
                        "room": ctx["room_type"],
                        "enemies": [
                            {"id": e["id"], "powers": e.get("powers"), "intents": e.get("intents")}
                            for e in state["enemies"]
                        ],
                        "features": combat_features(state),
                        "styles": outcomes,
                        "beam": beam,
                    }
                )
    finally:
        if session is not None:
            session.close()
    save_json(folder / "labels.json", {"roots": rows, "errors": errors})
    return len(rows), len(errors)


def value(end):
    return 24 * end["won"] + 0.16 * end["hp"] + 5 * (1 - end["remaining"]) + 0.12 * end["potions"]


def fit(roots, ridge, default):
    columns = sorted({k for r in roots for k in r["features"]})
    x = np.array([[r["features"].get(k, 0.0) for k in columns] for r in roots])
    styles = list(roots[0]["styles"])
    values = np.array([[value(r["styles"][s]) for s in styles] for r in roots])
    values -= values.mean(axis=1, keepdims=True)
    betas = np.linalg.solve(x.T @ x + np.eye(len(columns)) * ridge, x.T @ values)
    return {
        "version": 1,
        "runtime_identity": IDENTITY,
        "default": default,
        "beam": roots[0]["beam"],
        "models": {
            s: dict(zip(columns, beta.tolist(), strict=True))
            for s, beta in zip(styles, betas.T, strict=True)
        },
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=("collect", "fit"))
    p.add_argument("--source", type=Path, nargs="+", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--host", type=Path)
    p.add_argument("--weights", type=Path)
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--seeds", type=int, default=250)
    p.add_argument("--styles", choices=STYLES, nargs="+", default=list(STYLES))
    p.add_argument("--beam", action="store_true")
    p.add_argument(
        "--hallways",
        type=int,
        default=0,
        help="Sample this many map-entry fights per run, excluding bosses",
    )
    p.add_argument("--min-act", type=int, choices=(1, 2, 3), default=1)
    p.add_argument("--default", choices=STYLES, default="balanced")
    p.add_argument("--ridge", type=float, default=8.0)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    if args.mode == "collect":
        if not args.host or not args.weights:
            p.error("Collection requires --host and --weights")
        sources = []
        for directory in args.source:
            for f in sorted(directory.glob("run-*/result.json")):
                result = json.loads(f.read_text())
                if result["status"] == "complete" and (
                    result["act"] >= args.min_act
                    if args.hallways
                    else result["boss_fights"] and f.with_name("strategy.jsonl.gz").exists()
                ):
                    sources.append(f.parent)
        if len(sources) < args.seeds:
            p.error(f"Only {len(sources)} complete games met the collection criteria")
        weights = RunWeights.load(args.weights)
        with ProcessPoolExecutor(args.workers) as pool:
            tasks = [
                (
                    args.output / f"run-{i:04d}",
                    source,
                    args.host,
                    weights,
                    args.styles,
                    args.beam,
                    args.hallways,
                    args.min_act,
                )
                for i, source in enumerate(sources[: args.seeds])
            ]
            for i, _ in enumerate(pool.map(collect, tasks), 1):
                if i % 10 == 0:
                    print(i, flush=True)
        return
    roots = [
        r
        for directory in args.source
        for f in sorted(directory.glob("run-*/labels.json"))
        for r in json.loads(f.read_text())["roots"]
    ]
    if not roots or len({(r["seed"], r["root"]) for r in roots}) != len(roots):
        raise ValueError("Expected distinct recorded boss openings")
    if len({(r["beam"], tuple(r["styles"])) for r in roots}) != 1:
        raise ValueError("All boss roots must share a candidate portfolio")
    valid = {
        r["seed"]
        for r in roots
        if int.from_bytes(hashlib.sha256(r["seed"].encode()).digest()[:4], "big") % 5 == 0
    }
    train = [r for r in roots if r["seed"] not in valid]
    model = fit(train, args.ridge, args.default)
    model["model_rooms"] = sorted({r.get("room", "Boss") for r in train})
    model["model_min_act"] = min(r["act"] for r in train)
    save_json(args.output / "encounters.json", model)
    scores = defaultdict(list)
    for r in roots:
        if r["seed"] not in valid:
            continue
        name = max(
            model["models"],
            key=lambda s: sum(v * model["models"][s].get(k, 0.0) for k, v in r["features"].items()),
        )
        for s, outcome in {**r["styles"], "fitted": r["styles"][name]}.items():
            scores[s].append(outcome)
    report = {
        "roots": len(roots),
        "seeds": len({r["seed"] for r in roots}),
        "fit_roots": len(train),
        "validation_seeds": len(valid),
        "encounters": dict(Counter(r["encounter"] for r in roots)),
        "fights": sum(len(r["styles"]) for r in roots),
        "validation": {
            s: {
                "fights": len(o),
                "wins": sum(e["won"] for e in o),
                "mean_value": fmean(map(value, o)),
            }
            for s, o in scores.items()
        },
    }
    save_json(args.output / "report.json", report)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
