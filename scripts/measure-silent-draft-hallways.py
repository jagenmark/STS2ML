"""Measure each draft option's HP after the next ordinary fight on matched native openings."""

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from sts2rl.act1 import is_combat_choice, save_json
from sts2rl.encounter import EncounterModel
from sts2rl.encounter_draft import matchup_features
from sts2rl.native import NativeSession, legal_actions
from sts2rl.offer_policy import OfferModel, offer_type
from sts2rl.routing import RoomModel
from sts2rl.run_bundle import load_bundle
from sts2rl.run_policy import RunPolicy, RunWeights
from sts2rl.strategy import StrategyModel, strategy_kind
from sts2rl.trajectory import strategy_roots

ROOT = Path(__file__).resolve().parents[1]


def next_fight(game, fork, action, settings, strategy, offers, router):
    game.restore(fork)
    actor = RunPolicy(RunWeights.load(settings["weights"]))
    encounter = EncounterModel.load(settings["encounter_model"])
    enemies = None
    for _ in range(240):
        state = game.step(action)
        ctx = state.get("context") or {}
        decision = state["decision"]
        if enemies and (decision == "game_over" or not state.get("in_combat")):
            return {
                "enemies": enemies,
                "hp": max(0, state["player"]["hp"]),
                "won": decision != "game_over",
            }
        if decision == "game_over" or ctx.get("act") != 1:
            return None
        if decision == "combat_play" and ctx["room_type"] == "Monster" and enemies is None:
            enemies = sorted(e["id"] for e in state["enemies"])
        if decision == "map_select":
            action = router.choose(state, game.public_map())
        elif is_combat_choice(state):
            action = encounter.choose(state, actor)
        elif strategy_kind(state) in strategy.kinds:
            action = strategy.choose(state, actor, offers)
        elif offer_type(state):
            action = offers.choose(state, actor)
        else:
            action = actor(state)
    return None


def collect(task):
    source, context_file, bundle, host = task
    context = json.loads(context_file.read_bytes())
    possibilities = []
    for state, fork in strategy_roots(source):
        probability = context["odds"].get(fork.expected_digest)
        if (
            state["decision"] != "card_reward"
            or state.get("in_combat")
            or state["context"]["act"] != 1
            or probability is None
            or probability < 0.5
        ):
            continue
        area = {
            card["index"]: matchup_features(
                card, state["player"]["deck"], state["context"], probability
            ).get("matchup/pool/area", 0)
            for card in state["cards"]
        }
        if any(area.values()):
            possibilities.append((probability, state, fork, area))
    if not possibilities:
        return None
    probability, state, fork, area = max(possibilities, key=lambda item: item[0])
    row = {"seed": context["seed"], "root": fork.expected_digest, "odds": probability}
    _, settings = load_bundle(bundle)
    strategy = StrategyModel.load(settings["strategy_model"])
    offers = OfferModel.load(settings["offer_model"])
    router = RoomModel.load(settings["room_model"])
    trace = {}
    strategy.choose(
        state,
        RunPolicy(RunWeights.load(settings["weights"])),
        offers,
        group_probability=probability,
        explanation=trace,
    )
    arms = []
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
            for action, option in zip(legal_actions(state), trace["options"], strict=True):
                if action.command() != option["action"]:
                    raise ValueError("Mismatched draft option")
                result = next_fight(game, fork, action, settings, strategy, offers, router)
                if result is None:
                    return {**row, "error": "No complete next hallway battle on every arm"}
                arms.append(
                    {
                        **result,
                        "card": option["card"],
                        "prior": option["total"],
                        "area": area.get(action.args.get("card_index"), 0),
                    }
                )
    except (TimeoutError, RuntimeError, ValueError) as error:
        return {**row, "error": str(error)}
    if len({tuple(arm["enemies"]) for arm in arms}) != 1:
        return {**row, "error": "Different next hallway enemies"}
    return {**row, "arms": arms}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", nargs="+", required=True, type=Path)
    for flag in ("contexts", "host", "bundle", "seed-lock", "output"):
        parser.add_argument("--" + flag, required=True, type=Path)
    parser.add_argument("--workers", default=2, type=int)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    protected = {
        s for seeds in json.loads(args.seed_lock.read_bytes())["seeds"].values() for s in seeds
    }
    tasks = []
    seen = set()
    for folder in args.source:
        for path in sorted(folder.glob("run-*/result.json")):
            row = json.loads(path.read_bytes())
            context = args.contexts / (row["seed"] + ".json")
            if (
                row["status"] != "complete"
                or row.get("opening_partition") == "test"
                or not context.is_file()
            ):
                continue
            if row["seed"] in protected or row["seed"] in seen:
                raise ValueError(f"Duplicate or reserved seed {row['seed']}")
            seen.add(row["seed"])
            tasks.append((path.parent, context, args.bundle.resolve(), args.host.resolve()))
    with ProcessPoolExecutor(args.workers) as pool:
        for row in pool.map(collect, tasks):
            if row is not None:
                save_json(args.output / (row["seed"] + ".json"), row)
    save_json(
        args.output / "manifest.json",
        {
            "bundle_sha256": sha256(args.bundle.read_bytes()).hexdigest(),
            "host_sha256": sha256(args.host.read_bytes()).hexdigest(),
            "seed_lock_sha256": sha256(args.seed_lock.read_bytes()).hexdigest(),
            "inspected_seeds": sorted(seen),
        },
    )


if __name__ == "__main__":
    main()
