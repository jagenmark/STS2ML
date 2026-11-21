"""Learn next-turn enemy attack estimates from native Act 3 training trajectories."""

import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
import gzip
import hashlib
import json
from pathlib import Path
from statistics import fmean
from tempfile import TemporaryDirectory

from sts2rl.act1 import save_json
from sts2rl.act3_combat import forecast_keys
from sts2rl.combat_outcome import outcome
from sts2rl.encounter import EncounterModel
from sts2rl.native import NativeSession, ReplayFork
from sts2rl.run_bundle import load_bundle
from sts2rl.run_policy import RunPolicy, RunWeights
from sts2rl.teacher import incoming

ROOT = Path(__file__).resolve().parents[1]


class RecordTurns:
    def __init__(self, actor):
        self.actor = actor
        self.turns = {}

    def choose(self, state, macro):
        if state["decision"] == "combat_play" and state["round"] not in self.turns:
            self.turns[state["round"]] = {
                (e["index"], e["id"]): (forecast_keys(e, state["round"]), incoming(e))
                for e in state["enemies"]
                if e["hp"] > 0
            }
        return self.actor.choose(state, macro)


def collect(task):
    path, idx, host, bundle = task
    with gzip.open(path, "rt") as f:
        data = json.load(f)
    entry = data["starts"][idx]
    fork = ReplayFork(data["specification"], tuple(data["history"][: entry["step"]]), entry["root"])
    _, opts = load_bundle(bundle)
    actor = RecordTurns(EncounterModel.load(opts["encounter_model"]))
    macro = RunPolicy(RunWeights.load(opts["weights"]))
    with (
        TemporaryDirectory() as tmp,
        NativeSession(
            ROOT,
            Path(tmp) / "game",
            host_path=host,
            act_list=fork.specification.get("act_list", "default"),
            timeout=60,
        ) as game,
    ):
        state = game.restore(fork)
        if state["context"]["act"] != 3 or state["context"]["room_type"] not in (
            "Monster",
            "Elite",
        ):
            raise ValueError("Forbidden forecasting root")
        outcome(game, state, actor, macro)
    labels = []
    for turn, before in actor.turns.items():
        after = actor.turns.get(turn + 1, {})
        for monster in before.keys() & after.keys():
            keys, visible = before[monster]
            labels.append(
                {
                    "seed": data["seed"],
                    "root": entry["root"],
                    "round": turn,
                    "keys": keys,
                    "current_damage": visible,
                    "next_damage": after[monster][1],
                }
            )
    return labels


def fit(rows):
    cells = defaultdict(lambda: defaultdict(list))
    for r in rows:
        for key in r["keys"]:
            cells[key][r["seed"]].append(r["next_damage"])
    return {
        key: fmean(fmean(observations) for observations in seeds.values())
        for key, seeds in sorted(cells.items())
        if len(seeds) >= 2
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for k in ("host", "bundle", "seed-lock", "output"):
        p.add_argument("--" + k, required=True, type=Path)
    p.add_argument("--openings", type=Path, required=True, nargs="+")
    p.add_argument("--workers", type=int, default=2)
    a = p.parse_args()
    partitions = json.loads(a.seed_lock.read_bytes())["seeds"]
    reserved = set(partitions["development"] + partitions["test"])
    roots = {}
    for folder in a.openings:
        for path in sorted(folder.glob("*.json.gz")):
            with gzip.open(path, "rt") as f:
                record = json.load(f)
            if record.get("act") != 3 or record["seed"] in reserved:
                raise ValueError("Only Act 3 training openings may fit enemy forecasts")
            for i, s in enumerate(record["starts"]):
                roots.setdefault(s["root"], (path, i, a.host.resolve(), a.bundle))
    a.output.mkdir(parents=True, exist_ok=False)
    with ProcessPoolExecutor(a.workers) as pool:
        labels = [r for group in pool.map(collect, roots.values()) for r in group]
    seeds = {r["seed"] for r in labels}
    errors, repeated = [], []
    for seed in sorted(seeds):
        table = fit([r for r in labels if r["seed"] != seed])
        for r in labels:
            if r["seed"] == seed:
                pred = next((table[k] for k in r["keys"] if k in table), r["current_damage"])
                errors.append(abs(pred - r["next_damage"]))
                repeated.append(abs(r["current_damage"] - r["next_damage"]))
    save_json(a.output / "table.json", fit(labels))
    with gzip.open(a.output / "transitions.json.gz", "wt", encoding="utf-8") as f:
        json.dump(labels, f, separators=(",", ":"))
    save_json(
        a.output / "fit.json",
        {
            "seeds": sorted(seeds),
            "roots": sorted(roots),
            "observed_transitions": len(labels),
            "leave_one_seed_out_mae": fmean(errors),
            "repeat_current_intent_mae": fmean(repeated),
            "bundle_sha256": hashlib.sha256(a.bundle.read_bytes()).hexdigest(),
            "host_sha256": hashlib.sha256(a.host.read_bytes()).hexdigest(),
            "seed_lock_sha256": hashlib.sha256(a.seed_lock.read_bytes()).hexdigest(),
            "sources": {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in [Path(__file__), *sorted((ROOT / "src/sts2rl").glob("*.py"))]
            },
        },
    )
    print(len(labels), "transitions", fmean(errors), fmean(repeated))


if __name__ == "__main__":
    main()
