"""Play every legal first action in failed Act 3 training fights to the end of the run."""

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

from sts2rl.act1 import save_json
from sts2rl.native import digest, legal_actions
from sts2rl.run_bundle import load_bundle
from sts2rl.run_evaluation import act_start, play_episode
from sts2rl.run_policy import RunWeights

ROOT = Path(__file__).resolve().parents[1]


def terminal(trace):
    last = None
    with trace.open(encoding="utf-8") as stream:
        for line in stream:
            last = line
    if last is None:
        raise ValueError(f"Empty intervention trace {trace}")
    return json.loads(last)["response_digest"]


def trial(task):
    data, bundle, host, output, entry, candidate, expected = task
    seed, floor = entry["seed"], entry["floor"]
    seen = {}

    def intervene(state, action):
        ctx = state["context"]
        if seen or (ctx.get("act"), ctx.get("floor")) != (3, floor):
            return action
        if state["decision"] not in ("card_select", "combat_play"):
            return action
        if (state["decision"] == "combat_play" and state["round"] != 1) or ctx[
            "room_type"
        ] == "Boss":
            raise ValueError("Expected the opening hand of the training encounter")
        options = legal_actions(state)
        seen.update(
            opening=digest(state),
            original=action.id,
            hp=state["player"]["hp"],
            decision=state["decision"],
            enemies=[e["id"] for e in state.get("enemies") or []],
            hand=state.get("hand") or [],
            selection=state.get("cards") or [],
            potions=state["player"]["potions"],
            options=[dict(id=a.id, **a.command()) for a in options],
        )
        if expected and seen["opening"] != expected:
            raise ValueError("First hand changed between paired interventions")
        if candidate is None:
            return action
        return next(a for a in options if a.id == candidate)

    role, opts = load_bundle(bundle)
    trace = data / "maps" / seed / "rpc.jsonl"
    fork = act_start(trace, 3)
    if fork.expected_digest != entry["map_digest"] or fork.specification["seed"] != seed:
        raise ValueError("Training map mismatch")
    folder = output / seed / (candidate or "control")
    result = play_episode(
        (
            ROOT,
            host,
            folder,
            seed,
            entry["index"],
            role,
            asdict(RunWeights.load(opts["weights"])),
            opts.get("micro"),
            {
                **opts,
                "start_trace": trace,
                "curriculum_act": 3,
                "rooms": True,
                "seeded_acts": fork.specification.get("act_list") == "seeded",
            },
        ),
        decision_hook=intervene,
    )
    if result["status"] != "complete" or (candidate is not None and not seen):
        raise ValueError(f"Could not play the original encounter on {seed}: {result.get('error')}")
    room = next(r for r in result["rooms"] if r["act"] == 3 and r["row"] == floor - 1)
    end = terminal(folder / "game" / "rpc.jsonl")
    if candidate is None:
        source = data / "runs" / "act3-continuations" / "engine" / seed / "game" / "rpc.jsonl"
        if end != terminal(source) or not room["died"]:
            raise ValueError(f"Control diverged on {seed}")
    return {
        "seed": seed,
        "first_action": candidate or seen.get("original"),
        "survived_fight": not room["died"],
        "hp_after_room": room["after"]["hp"],
        "floor": result["floor"],
        "reached_boss": any(act == 3 for act, _ in result["boss_fights"]),
        "win": result["win"],
        "terminal": end,
        **(
            {"public_choice": seen or {"options": [], "decision": None}}
            if candidate is None
            else {}
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True, help="Extracted act3-training-maps.zip")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--host", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    data = args.data
    maps = {r["seed"]: r for r in json.loads((data / "maps/index.json").read_bytes())}
    outcomes = json.loads((data / "act3-outcomes.json").read_bytes())
    failures = [
        r for r in outcomes if r["plan"] == "engine" and not r["win"] and not r["boss_fights"]
    ]
    if any(maps[r["seed"]]["partition"] != "train" for r in failures):
        raise ValueError("Expected training maps")
    args.output.mkdir(parents=True, exist_ok=False)
    tasks = [
        (
            data,
            args.bundle,
            args.host.resolve(),
            args.output,
            {**maps[r["seed"]], "floor": r["floor"]},
        )
        for r in failures
    ]
    with ProcessPoolExecutor(args.workers) as pool:
        controls = list(pool.map(trial, [(*t, None, None) for t in tasks]))
        save_json(args.output / "controls.json", controls)
        alternatives = []
        for task, control in zip(tasks, controls, strict=True):
            choice = control["public_choice"]
            alternatives.extend(
                (*task, option["id"], choice["opening"])
                for option in choice["options"]
                if option["id"] != control["first_action"]
            )
        print(f"{len(controls)} exact controls, {len(alternatives)} alternatives", flush=True)
        results = list(pool.map(trial, alternatives))
    save_json(args.output / "alternatives.json", results)
    print(
        f"Fight rescued on {len({r['seed'] for r in results if r['survived_fight']})} training seeds",
        flush=True,
    )


if __name__ == "__main__":
    main()
