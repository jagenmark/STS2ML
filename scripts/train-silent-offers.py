"""Train an A10 opening and card-reward ranker by replaying legal counterfactual choices."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from statistics import fmean

from sts2rl.act1 import save_json
from sts2rl.native import NativeSession, digest, legal_actions
from sts2rl.offer_policy import OfferModel, offer_features, offer_type
from sts2rl.routing import RoomModel
from sts2rl.run_policy import RunPolicy, RunWeights

ROOT = Path(__file__).resolve().parents[1]


def decide(state, policy, router, game):
    if router and state["decision"] == "map_select":
        return router.choose(state, game.public_map())
    return policy(state)


def continuation(game, action, policy, router):
    state = game.step(action)
    max_floor, last_act, hp_samples = 0, 1, []
    visited = set()
    repeats = Counter()
    for _ in range(1600):
        ctx = state.get("context") or {}
        act = ctx.get("act", last_act)
        floor = ctx.get("floor", max_floor)
        if (act, floor) not in visited:
            hp_samples.append(state["player"]["hp"] / state["player"]["max_hp"])
            visited.add((act, floor))
        if act > 1:
            return {"return": 22 + 3 * state["player"]["hp"] / state["player"]["max_hp"] + fmean(hp_samples),
                    "clear": True, "floor": max_floor}
        last_act, max_floor = act, max(floor, max_floor)
        if state["decision"] == "game_over":
            if state.get("victory") is not False:
                raise RuntimeError("Unexpected Act 1 victory")
            return {"return": max_floor + fmean(hp_samples), "clear": False, "floor": max_floor}
        key = digest(state)
        repeats[key] += 1
        if repeats[key] > 3:
            raise RuntimeError("Repeated counterfactual decision")
        state = game.step(decide(state, policy, router, game))
    raise RuntimeError("Counterfactual continuation truncated")


def collect(task):
    output, host, seed, i, weights, room_model = task
    folder = Path(output) / f"run-{i:04d}"
    folder.mkdir(exist_ok=False)
    rows = []
    try:
        w = RunWeights(**weights)
        router = RoomModel.load(room_model) if room_model else None
        policy = RunPolicy(w, macro_seed=7103 + i)
        with NativeSession(ROOT, folder / "actor", host_path=host, timeout=12) as actor, \
             NativeSession(ROOT, folder / "branch", host_path=host, timeout=12) as branch:
            state = actor.reset(seed)
            card_number = 0
            for step in range(800):
                if state["decision"] == "game_over" or state["context"]["act"] > 1:
                    break
                kind = offer_type(state)
                if kind == "card":
                    card_number += 1
                if kind == "neow" or (kind == "card" and card_number == 1 + i % 4):
                    fork = actor.fork()
                    actions = legal_actions(state)
                    arms = []
                    for action in actions:
                        branch.restore(fork)
                        other = RunPolicy(w, macro_seed=9400 + i)
                        prior, features = offer_features(state, action, policy)
                        outcome = continuation(branch, action, other, router)
                        arms.append({"id": action.id, "features": features, "prior": prior, **outcome})
                    if len(arms) > 1:
                        rows.append({"kind": kind, "group": seed, "root": fork.expected_digest, "arms": arms})
                    if kind == "card":
                        break
                action = decide(state, policy, router, actor)
                state = actor.step(action)
        status = {"status": "complete", "seed": seed, "roots": rows}
    except Exception as exc:
        status = {"status": "error", "seed": seed, "error": f"{type(exc).__name__}: {exc}", "roots": []}
    save_json(folder / "labels.json", status)
    return status


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--host", type=Path, required=True)
    p.add_argument("--weights", type=Path, required=True)
    p.add_argument("--room-model", type=Path)
    p.add_argument("--prefix", required=True)
    p.add_argument("--runs", type=int, default=120)
    p.add_argument("--workers", type=int, default=2)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    weights = RunWeights.load(args.weights)
    save_json(args.output / "config.json", {**json.loads(json.dumps(vars(args), default=str)), "weights": weights.checkpoint(),
              "host_sha256": hashlib.sha256(args.host.read_bytes()).hexdigest(),
              "room_sha256": hashlib.sha256(args.room_model.read_bytes()).hexdigest() if args.room_model else None})
    tasks = [(args.output, args.host, f"{args.prefix}{i:04d}", i, asdict(weights), args.room_model) for i in range(args.runs)]
    rows = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for i, result in enumerate(pool.map(collect, tasks), 1):
            rows.append(result)
            if i % 5 == 0:
                print(json.dumps({"completed": i, "errors": sum(r["status"] != "complete" for r in rows)}), flush=True)
    roots = [root for r in rows for root in r["roots"]]
    if not roots:
        raise RuntimeError("No usable paired continuations")
    # Split by seed, so alternate offers from one game cannot cross partitions.
    valid = {r["seed"] for i, r in enumerate(rows) if i % 5 == 0}
    model = OfferModel.fit([r for r in roots if r["group"] not in valid])
    metrics = {}
    for kind in ("neow", "card"):
        subset = [r for r in roots if r["group"] in valid and r["kind"] == kind]
        if subset:
            def regret(root, learned):
                arms = root["arms"]
                chosen = max(arms, key=lambda a: model.predict(a["prior"], a["features"]) if learned else a["prior"])
                return max(a["return"] for a in arms) - chosen["return"]
            metrics[kind] = {"validation_roots": len(subset), "prior_regret": fmean(regret(r, False) for r in subset),
                             "model_regret": fmean(regret(r, True) for r in subset)}
    model.save(args.output / "offers.json")
    save_json(args.output / "report.json", {"episodes": len(rows), "errors": sum(r["status"] != "complete" for r in rows),
              "roots": dict(Counter(r["kind"] for r in roots)), "branches": sum(len(r["arms"]) for r in roots),
              "validation": metrics})


if __name__ == "__main__":
    main()
