"""Reconstruct natural Act 2 boss openings and measure paired, native fight continuations."""
import argparse
import gzip
import hashlib
import json
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from sts2rl.act1 import save_json
from sts2rl.encounter import EncounterModel
from sts2rl.native import NativeError, NativeSession, ReplayFork, digest
from sts2rl.run_bundle import load_bundle
from sts2rl.run_policy import RunPolicy, RunWeights
from sts2rl.trajectory import natural_specification

ROOT = Path(__file__).resolve().parents[1]


def read_boss_root(directory):
    with (directory / "game/rpc.jsonl").open(encoding="utf-8") as stream:
        first = json.loads(next(stream))
        spec = natural_specification(first["command"])
        previous = first["response_digest"]
        act, last_row = 1, -1
        history, last_fight = [], None
        waiting = False
        for line in stream:
            row = json.loads(line)
            cmd = row["command"]
            if cmd["cmd"] == "get_map":
                continue
            if cmd["cmd"] != "action":
                raise ValueError("Unexpected command in natural history")
            kind = cmd["action"]
            if kind == "select_map_node":
                y = cmd["args"]["row"]
                act += int(y < last_row)
                last_row = y
                if act > 2:
                    break
                waiting = act == 2
                if waiting:
                    last_fight = None
            elif waiting and kind in ("play_card", "end_turn", "use_potion"):
                last_fight = (len(history), previous)
                waiting = False
            history.append(cmd)
            previous = row["response_digest"]
    if not last_fight:
        raise ValueError("No combat action at last Act 2 node")
    index, digest = last_fight
    return ReplayFork(spec, tuple(history[:index]), digest)


def run_fight(game, state, actor, macro, trace=False):
    rounds, events, remaining = [], [], 1.0
    for _ in range(600):
        if state["decision"] == "game_over" or not state.get("in_combat"):
            won = state["decision"] != "game_over" or state.get("victory") is True
            return {"won": won, "hp": state["player"]["hp"] if won else 0,
                    "remaining": 0 if won else remaining, "potions": len(state["player"]["potions"]),
                    "rounds": len(rounds), **({"turns": rounds, "events": events} if trace else {})}
        action = actor.choose(state, macro)
        if state["decision"] == "combat_play":
            enemies = [e for e in state["enemies"] if e["hp"] > 0]
            remaining = sum(e["hp"] for e in enemies) / max(1, sum(e["max_hp"] for e in state["enemies"]))
            if not rounds or rounds[-1]["round"] != state["round"]:
                rounds.append({"round": state["round"]})
                if trace:
                    rounds[-1].update(hp=state["player"]["hp"], enemies=enemies,
                                      powers=state.get("player_powers"), plays=[])
            if trace:
                item = next((c["id"] for c in state["hand"] if c["index"] == action.args.get("card_index")), action.kind)
                rounds[-1]["plays"].append([item, action.args.get("target_index")])
        elif trace:
            events.append({"decision": state["decision"], "keys": list(state.keys()),
                           "source": state.get("selection_source"), "options": state.get("options"),
                           "cards": [c.get("id") for c in state.get("cards") or []], "action": action.command()})
        state = game.step(action)
    raise ValueError("Native boss fight exceeded decision budget")


def measure(task, stepwise=False):
    source, bundle, host, output, variants, collect = task
    if collect:
        result = json.loads(source.read_bytes())
        seed, index = result["seed"], result["index"]
        fork = read_boss_root(source.parent)
    else:
        with gzip.open(source, "rt", encoding="utf-8") as stream:
            entry = json.load(stream)
        seed, index = entry["seed"], entry["index"]
        fork = ReplayFork(entry["specification"], tuple(entry["history"]), entry["root"])
    _, settings = load_bundle(bundle)
    macro = RunPolicy(RunWeights.load(settings["weights"]), macro_seed=7103 + index)
    model = json.loads(settings["encounter_model"].read_bytes())
    with tempfile.TemporaryDirectory(dir=output) as tmp:
        with NativeSession(ROOT, Path(tmp)/"host", host_path=host, timeout=90,
                           act_list=fork.specification.get("act_list", "default")) as game:
            outcomes = {}
            for name, additions in variants.items():
                if not collect and additions and entry["boss"] not in additions.get("act2_boss_plans", {}):
                    continue
                if stepwise:
                    state = game.reset(seed)
                    for command in fork.history:
                        state = game._request(command)
                    if digest(state) != fork.expected_digest:
                        raise ValueError("Stepwise replay differs from the recorded boss opening")
                    game.state = state
                    game.history = list(fork.history)
                else:
                    state = game.restore(fork)
                ctx = state["context"]
                if (ctx["act"], ctx["room_type"], state.get("round"), state["decision"]) != (2, "Boss", 1, "combat_play"):
                    raise ValueError(f"Opening is not the first Act 2 boss hand on {seed}")
                boss = ctx["boss"]["id"]
                actor = EncounterModel({**model, **additions})
                outcomes[name] = run_fight(game, state, actor, macro, collect)
            if collect:
                data = {"seed": seed, "index": index, "specification": fork.specification, "history": fork.history,
                        "root": fork.expected_digest, "boss": boss, "opening": state, "outcomes": outcomes}
            else:
                data = {"seed": seed, "root": fork.expected_digest, "boss": boss, "outcomes": outcomes}
    with gzip.open(output/(seed+".json.gz"), "wt", encoding="utf-8") as stream:
        json.dump(data, stream, separators=(",", ":"))
    return boss


def checked(task):
    seed = json.loads(task[0].read_bytes())["seed"] if task[-1] else task[0].name.removesuffix(".json.gz")
    errors = []
    for mode in (False, False, True):
        try:
            return measure(task, mode)
        except (NativeError, ValueError, TimeoutError) as exc:
            errors.append(str(exc))
    save_json(task[3]/(seed+".error.json"), {"seed": seed, "attempts": errors})
    return "replay error"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=["collect", "compare"])
    p.add_argument("--source", type=Path, nargs="+", required=True)
    for name in ("bundle", "host", "output", "seed-lock"):
        p.add_argument("--"+name, type=Path, required=True)
    p.add_argument("--variants", type=Path)
    p.add_argument("--partition", choices=["training", "development"], required=True)
    p.add_argument("--workers", type=int, default=3)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    seeds = json.loads(a.seed_lock.read_bytes())["seeds"]
    forbidden = set(seeds["test"]) | (set(seeds["development"]) if a.partition == "training" else set(seeds["train"]))
    collect = a.mode == "collect"
    variants = {"control": {}} if collect else json.loads(a.variants.read_bytes())
    seen, tasks = set(), []
    for folder in a.source:
        for file in sorted(folder.glob("run-*/result.json" if collect else "*.json.gz")):
            if collect:
                row = json.loads(file.read_bytes())
                if row["status"] != "complete" or not any(act == 2 for act, floor in row["boss_fights"]):
                    continue
                seed = row["seed"]
            else:
                seed = file.name.removesuffix(".json.gz")
            if seed in forbidden or seed in seen:
                raise ValueError(f"Duplicate or reserved seed {seed}")
            seen.add(seed)
            tasks.append((file, a.bundle, a.host.resolve(), a.output, variants, collect))
    if not tasks:
        raise ValueError("No eligible boss openings")
    save_json(a.output/"design.json", {"partition": a.partition, "seeds": sorted(seen), "variants": variants,
              "bundle_sha256": hashlib.sha256(a.bundle.read_bytes()).hexdigest(),
              "host_sha256": hashlib.sha256(a.host.read_bytes()).hexdigest()})
    with ProcessPoolExecutor(a.workers) as pool:
        for i, boss in enumerate(pool.map(checked, tasks), 1):
            if i%10 == 0 or i == len(tasks):
                print(i, len(tasks), boss, flush=True)


if __name__ == "__main__":
    main()
