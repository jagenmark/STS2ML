"""Label deck, event, merchant and camp actions using matched complete native continuations."""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
from random import Random
from statistics import fmean

from sts2rl.act1 import save_json
from sts2rl.encounter import EncounterPolicy
from sts2rl.native import NativeSession
from sts2rl.offer_policy import OfferModel, offer_type
from sts2rl.routing import RoomModel
from sts2rl.run_bundle import load_bundle
from sts2rl.run_policy import RunPolicy, RunWeights
from sts2rl.strategy import StrategyModel, strategy_arms, strategy_kind
from sts2rl.trajectory import strategy_roots
from sts2rl.turn_planning import choose_turn

ROOT = Path(__file__).resolve().parents[1]


def follow(game, state, actor, router, opening, initial, start_act):
    action = initial
    boss_damage = 0.0
    for _ in range(1100):
        ctx = state["context"]
        if state["decision"] == "combat_play" and ctx["room_type"] == "Boss":
            enemies = state["enemies"]
            if enemies:
                boss_damage = max(
                    boss_damage,
                    1 - sum(e["hp"] for e in enemies) / max(1, sum(e["max_hp"] for e in enemies)),
                )
        if state["decision"] == "game_over" or ctx["act"] > start_act:
            clear = ctx["act"] > start_act or state.get("victory", False)
            floor = 17 if clear else ctx["floor"]
            # Absolute outcome values are compared only within a matched decision.
            return {
                "clear": clear,
                "floor": floor,
                "hp": state["player"]["hp"],
                "return": floor
                + 10 * clear
                + 2 * boss_damage
                + 0.05 * state["player"]["hp"] * clear,
            }
        if action is None:
            if state["decision"] == "map_select":
                action = router.choose(state, game.public_map())
            elif state["decision"] == "combat_play":
                action = (
                    actor(state)
                    if isinstance(actor, EncounterPolicy)
                    else choose_turn(state, actor)
                )
            elif offer_type(state) and opening:
                action = opening.choose(state, actor)
            else:
                action = actor(state)
        if state["decision"] == "rest_site" and any(
            o.get("option_id") == "SMITH" and o["index"] == action.args.get("option_index")
            for o in state["options"]
        ):
            actor.selection = "upgrade"
        state = game.step(action)
        action = None
    raise RuntimeError("Continuation exceeded action budget")


def collect(task):
    folder, source, host, bundle, split_seed, max_roots, kinds, min_act, style, room_path = task
    folder.mkdir(parents=True, exist_ok=False)
    _, settings = load_bundle(bundle)
    weights = RunWeights.load(settings["weights"])
    router = RoomModel.load(room_path or settings["room_model"])
    opening = OfferModel.load(settings["offer_model"]) if settings.get("offer_model") else None
    roots = defaultdict(list)
    seed = None
    for state, fork in strategy_roots(source):
        seed = fork.specification["seed"]
        kind = strategy_kind(state)
        if (
            kind
            and (not kinds or kind in kinds)
            and state["context"]["act"] >= min_act
            and len(strategy_arms(state, RunPolicy(weights), opening)) > 1
        ):
            roots[(state["context"]["act"], kind)].append((state, fork))
    rng = Random(f"{split_seed}/{seed}")
    chosen = []
    for (act, kind), candidates in roots.items():
        n = 2 if kind == "card" else 1
        chosen.extend(
            (act, rng.random(), kind, s, fork)
            for s, fork in rng.sample(candidates, min(n, len(candidates)))
        )
    chosen.sort(key=lambda sample: (-sample[0], sample[1]))
    session = None
    errors, rows = [], []
    try:
        for _, _, kind, state, fork in chosen[:max_roots]:
            arms = strategy_arms(state, RunPolicy(weights), opening)
            # Sample expensive merchant inventories uniformly, retaining leave as the reference.
            if kind == "shop" and len(arms) > 6:
                leave = next(a for a in arms if a[0].kind == "leave_room")
                arms = rng.sample([a for a in arms if a != leave], 5) + [leave]
            outcomes = []
            for arm, prior, features in arms:
                try:
                    if session is None or session.closed:
                        session = NativeSession(
                            ROOT,
                            folder / f"engine-{len(errors):03d}",
                            host_path=host,
                            ascension=10,
                            timeout=45,
                            act_list=fork.specification.get("act_list", "default"),
                        )
                    confirmed = session.restore(fork)
                    continuation = (
                        EncounterPolicy(weights, macro_seed=split_seed, style=style)
                        if style
                        else RunPolicy(weights, macro_seed=split_seed)
                    )
                    result = follow(
                        session,
                        confirmed,
                        continuation,
                        router,
                        opening,
                        arm,
                        state["context"]["act"],
                    )
                    outcomes.append({"id": arm.id, "prior": prior, "features": features, **result})
                except Exception as exc:
                    errors.append({"root": fork.expected_digest, "arm": arm.id, "error": str(exc)})
                    if session is not None:
                        session.close()
                        session = None
                    break
            if len(outcomes) == len(arms):
                rows.append(
                    {
                        "group": seed,
                        "kind": kind,
                        "act": state["context"]["act"],
                        "root": fork.expected_digest,
                        "arms": outcomes,
                    }
                )
    finally:
        if session is not None:
            session.close()
    save_json(folder / "labels.json", {"seed": seed, "roots": rows, "errors": errors})
    return len(rows), len(errors)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=("collect", "fit"))
    p.add_argument("--source", type=Path, nargs="+", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--host", type=Path)
    p.add_argument("--bundle", type=Path)
    p.add_argument("--seeds", type=int, default=250)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--roots", type=int, default=4)
    p.add_argument("--min-act", type=int, choices=(1, 2, 3), default=1)
    p.add_argument(
        "--kinds", nargs="+", choices=("card", "camp", "shop", "neow", "ancient", "event")
    )
    p.add_argument("--style", help="Use a fight-aware continuation policy for labels")
    p.add_argument("--room-model", type=Path)
    p.add_argument("--ridge", type=float, default=16.0)
    p.add_argument("--strength", type=float, default=1.0)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    if args.mode == "collect":
        if not args.host or not args.bundle:
            p.error("Collection requires --host and --bundle")
        sources = [
            path.parent
            for folder in args.source
            for path in sorted(folder.glob("run-*/result.json"))
            if (result := json.loads(path.read_text()))["status"] == "complete"
            and result.get("opening_partition") != "test"
            and result["act"] >= args.min_act
            and path.with_name("strategy.jsonl.gz").exists()
        ]
        if len(sources) < args.seeds:
            p.error(f"Only {len(sources)} complete recorded games available")
        tasks = [
            (
                args.output / f"run-{i:04d}",
                source,
                args.host,
                args.bundle,
                8321 + i,
                args.roots,
                args.kinds,
                args.min_act,
                args.style,
                args.room_model,
            )
            for i, source in enumerate(sources[: args.seeds])
        ]
        with ProcessPoolExecutor(args.workers) as pool:
            for i, result in enumerate(pool.map(collect, tasks), 1):
                if i % 10 == 0:
                    print(i, result, flush=True)
        return
    roots = [
        r
        for folder in args.source
        for path in sorted(folder.glob("run-*/labels.json"))
        for r in json.loads(path.read_text())["roots"]
    ]
    if len({(r["group"], r["root"]) for r in roots}) != len(roots):
        raise ValueError("Duplicate native roots in training inputs")

    def validation(root):
        return int.from_bytes(hashlib.sha256(root["group"].encode()).digest()[:4], "big") % 5 == 0

    train = [r for r in roots if not validation(r)]
    if not train:
        raise ValueError("No training roots")
    model = StrategyModel(
        OfferModel.fit(train, ridge=args.ridge).weights, {r["kind"] for r in train}, args.strength
    )
    model.save(args.output / "strategy.json")
    metrics = {}
    for kind in model.kinds:
        dev = [r for r in roots if validation(r) and r["kind"] == kind]
        if dev:

            def gain(r):
                arms = r["arms"]
                initial = max(arms, key=lambda a: a["prior"])
                fitted = max(
                    arms,
                    key=lambda a: a["prior"] + args.strength * model.predict(0.0, a["features"]),
                )
                return fitted["return"] - initial["return"]

            metrics[kind] = {"roots": len(dev), "mean_gain": fmean(map(gain, dev))}
    report = {
        "roots": len(roots),
        "seeds": len({r["group"] for r in roots}),
        "fit_seeds": len({r["group"] for r in train}),
        "fit_roots": len(train),
        "branches": sum(len(r["arms"]) for r in roots),
        "by_kind": dict(Counter(r["kind"] for r in roots)),
        "validation": metrics,
    }
    save_json(args.output / "report.json", report)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
