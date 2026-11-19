"""Compare Act 2 combat plans on identical natural native fight openings."""

import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
import gzip
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from sts2rl.act1 import save_json
from sts2rl.encounter import EncounterModel, combat_features
from sts2rl.native import NativeSession, ReplayFork
from sts2rl.run_bundle import load_bundle
from sts2rl.run_policy import RunPolicy, RunWeights

ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=8)
def read_group(path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def outcome(game, state, actor, macro):
    room = state["context"]["room_type"]
    remaining = 1.0
    turns = 0
    for _ in range(500):
        if state["decision"] == "game_over" or not state.get("in_combat"):
            won = state["decision"] != "game_over" or state.get("victory") is True
            return {"won": won, "hp": state["player"]["hp"] if won else 0,
                    "potions": len(state["player"]["potions"]), "rounds": turns, "remaining": 0 if won else remaining}
        if state["context"]["room_type"] != room:
            raise ValueError("Unconfirmed combat boundary")
        if state["decision"] == "combat_play":
            enemies = [e for e in state["enemies"] if e["hp"] > 0]
            remaining = sum(e["hp"] for e in enemies) / max(1, sum(e["max_hp"] for e in enemies))
            turns = state["round"]
        state = game.step(actor.choose(state, macro))
    raise ValueError("Combat exceeded 500 real decisions")


def shard(task):
    cases, host, models, weight_path, output, receipt, profile = task
    weights = RunWeights.load(weight_path)
    game = None
    with TemporaryDirectory() as tmp:
        try:
            for index, (path, pos) in enumerate(cases):
                group = read_group(path)
                start = group["starts"][pos]
                key = start["root"]
                fork = ReplayFork(group["specification"], tuple(group["history"][:start["step"]]), key)
                row = {"seed": group["seed"], **{k: start[k] for k in ("root", "room", "floor", "formation", "hp", "potions")},
                       "receipt_sha256": receipt}
                labels = {}
                try:
                    if game is None:
                        game = NativeSession(ROOT, Path(tmp) / f"native-{index}", host_path=host, act_list=profile, timeout=50)
                    for name, config in models.items():
                        state = game.restore(fork)
                        if state["context"]["act"] != 2 or state["context"]["room_type"] not in ("Monster","Elite"):
                            raise ValueError("Unexpected fight opening")
                        if not labels:
                            row["features"] = combat_features(state)
                            row["features"]["formation/" + start["formation"]] = 1.0
                        labels[name] = outcome(game, state, EncounterModel(config), RunPolicy(weights))
                    row["outcomes"] = labels
                except (ValueError, RuntimeError, TimeoutError) as exc:
                    row["error"] = str(exc)
                    if game is not None:
                        game.close()
                        game = None
                save_json(output / (key + ".json"), row)
        finally:
            if game is not None:
                game.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for flag in ("host", "bundle", "seed-lock", "plans", "output"):
        p.add_argument("--" + flag, required=True, type=Path)
    p.add_argument("--openings", type=Path, required=True, nargs="+")
    p.add_argument("--formations", nargs="+")
    p.add_argument("--cap", default=60, type=int, help="Maximum independently sampled roots per formation")
    p.add_argument("--workers", default=3, type=int)
    args = p.parse_args()
    if args.cap < 1 or args.workers < 1:
        p.error("Use positive limits")
    args.output.mkdir(parents=True, exist_ok=False)
    _, cfg = load_bundle(args.bundle)
    settings = json.loads(cfg["encounter_model"].read_bytes())
    plans = json.loads(args.plans.read_bytes())
    if plans.get("baseline", False) is not None:
        raise ValueError("A baseline arm with a null plan is required")
    models = {name: settings if plan is None else {**settings, "act2_hallways": {
        "plans": {name: plan}, "by_room": {"Monster": name, "Elite": name}}} for name, plan in plans.items()}
    lock = json.loads(args.seed_lock.read_bytes())["seeds"]
    reserved = set(lock["development"]) | set(lock["test"])
    by_formation = defaultdict(dict)
    for directory in args.openings:
        for path in sorted(directory.glob("*.json.gz")):
            group = read_group(path)
            if group["seed"] in reserved:
                raise ValueError("Reserved native opening in training data")
            for i, start in enumerate(group["starts"]):
                name = start["formation"]
                if args.formations and name not in args.formations:
                    continue
                entry = (start["root"], path, i, group["specification"].get("act_list", "default"))
                cases = by_formation[name]
                if group["seed"] not in cases or entry[0] < cases[group["seed"]][0]:
                    cases[group["seed"]] = entry
    by_profile = defaultdict(list)
    for choices in by_formation.values():
        for key,path,i,profile in sorted(choices.values())[:args.cap]:
            by_profile[profile].append((key,path,i))
    if not by_profile:
        raise ValueError("No matching native openings")
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    receipt = {"bundle_sha256": sha(args.bundle),"base_files": json.loads(args.bundle.read_bytes())["files"],
               "host_sha256": sha(args.host),"seed_lock_sha256": sha(args.seed_lock),"plans": plans,
               "sources": {f.name:sha(f) for f in [Path(__file__), *sorted((ROOT/"src/sts2rl").glob("*.py"))]},
               "roots": sorted(root for cases in by_profile.values() for root,_,_ in cases)}
    save_json(args.output / "receipt.json", receipt)
    checksum = sha(args.output / "receipt.json")
    tasks = []
    for profile, cases in by_profile.items():
        cases.sort()
        for j in range(0,len(cases),4):
            tasks.append(([(path,i) for _,path,i in cases[j:j+4]], args.host.resolve(),models,cfg["weights"],
                          args.output,checksum,profile))
    with ProcessPoolExecutor(args.workers) as pool:
        list(pool.map(shard,tasks))


if __name__ == "__main__":
    main()
