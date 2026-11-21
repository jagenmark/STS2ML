"""Replay one changed Bowlbug card choice, then use the same policy through the rest of the run."""

import argparse
import gzip
import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from sts2rl.act1 import save_json
from sts2rl.act2_hallways import formation_key
from sts2rl.encounter import EncounterModel
from sts2rl.native import digest, legal_actions
from sts2rl.run_bundle import load_bundle
from sts2rl.run_evaluation import play_episode
from sts2rl.run_policy import RunPolicy, RunWeights

ROOT = Path(__file__).resolve().parents[1]
FORMATION = "BOWLBUG_EGG+BOWLBUG_ROCK"


def measure(task):
    source, original, alternative, host, out, example = task
    expected = json.loads(source.read_bytes())
    seed, index = expected["seed"], expected["index"]
    role, opts = load_bundle(original)
    _, alt = load_bundle(alternative)
    result = {"seed": seed, "historical_example": bool(example), "arms": {}}
    for name in ("control", "one_action"):
        challenger = EncounterModel.load(alt["encounter_model"])
        weights = RunWeights.load(opts["weights"])
        macro = RunPolicy(weights, macro_seed=7103 + index)
        note = {}
        boss = {}
        active = None
        eligible = False

        def choose(state, action):
            nonlocal active, eligible
            ctx = state.get("context") or {}
            if state["decision"] != "combat_play" or ctx.get("act") != 2:
                return action
            if ctx["room_type"] == "Boss":
                if not boss:
                    boss.update(
                        hp=state["player"]["hp"],
                        potions=len(state["player"]["potions"]),
                        name=(ctx.get("boss") or {}).get("id"),
                    )
                return action
            key = (ctx["floor"], ctx["room_type"])
            if key != active:
                active = key
                eligible = ctx["room_type"] == "Monster" and formation_key(state) == FORMATION
            if not eligible or note:
                return action
            if example:
                if digest(state) != example["root"]:
                    return action
                if action.command() != example["baseline"]["command"]:
                    raise ValueError("Historical policy failed to reproduce its original action")
                other = next(
                    a
                    for a in legal_actions(state)
                    if a.command() == example["challenger"]["command"]
                )
            else:
                other = challenger.choose(state, macro)
            if other != action:
                note.update(
                    root=digest(state),
                    floor=ctx["floor"],
                    round=state["round"],
                    control=action.command(),
                    alternative=other.command(),
                )
                if name == "one_action":
                    return other
            return action

        folder = out / "runs" / seed / name
        row = play_episode(
            (
                ROOT,
                host,
                folder,
                seed,
                index,
                role,
                asdict(weights),
                opts.get("micro"),
                {**opts, "seeded_acts": True, "rooms": True},
            ),
            decision_hook=choose,
        )
        result["arms"][name] = {
            k: row.get(k)
            for k in ("status", "error", "act", "floor", "a2_clear", "win", "boss_fights")
        }
        result["arms"][name].update(intervention=note, boss2=boss)
        if row["status"] == "complete":
            with (folder / "game/rpc.jsonl").open() as stream:
                last = next(reversed(stream.readlines()))
            result["arms"][name]["terminal"] = json.loads(last)["response_digest"]
    ctrl = result["arms"]["control"]
    with (source.parent / "game/rpc.jsonl").open() as stream:
        result["matched_original_terminal"] = (
            ctrl.get("terminal")
            == json.loads(next(reversed(stream.readlines())))["response_digest"]
        )
    result["same_decision"] = ctrl["intervention"] == result["arms"]["one_action"]["intervention"]
    save_json(out / (seed + ".json"), result)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for k in (
        "source",
        "openings",
        "examples",
        "baseline",
        "alternative",
        "host",
        "output",
        "seed-lock",
    ):
        p.add_argument("--" + k, required=True, type=Path)
    p.add_argument("--sample", type=int, default=28)
    p.add_argument("--workers", type=int, default=2)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    reserved = set().union(*json.loads(a.seed_lock.read_bytes())["seeds"].values())
    examples = {
        r["seed"]: r for r in json.loads(a.examples.read_bytes()) if r.get("formation") == FORMATION
    }
    cases = {}
    for f in a.openings.glob("*.json.gz"):
        with gzip.open(f, "rt") as s:
            grp = json.load(s)
        if any(t["formation"] == FORMATION for t in grp["starts"]):
            cases[grp["seed"]] = grp["seed"]
    others = sorted(
        set(cases) - examples.keys(),
        key=lambda s: sha256(("bowlbug-transfer-v1" + s).encode()).digest(),
    )
    selected = [*sorted(examples), *others[: a.sample]]
    if set(selected) & reserved:
        raise ValueError("Historical intervention overlaps new evaluation seeds")
    sources = {
        r["seed"]: f for f in a.source.glob("*/result.json") if (r := json.loads(f.read_bytes()))
    }
    save_json(
        a.output / "design.json",
        {
            "examples": sorted(examples),
            "additional": others[: a.sample],
            "source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
            "baseline": sha256(a.baseline.read_bytes()).hexdigest(),
            "alternative": sha256(a.alternative.read_bytes()).hexdigest(),
        },
    )
    tasks = [
        (sources[s], a.baseline, a.alternative, a.host.resolve(), a.output, examples.get(s))
        for s in selected
    ]
    with ProcessPoolExecutor(a.workers) as pool:
        list(pool.map(measure, tasks))


if __name__ == "__main__":
    main()
