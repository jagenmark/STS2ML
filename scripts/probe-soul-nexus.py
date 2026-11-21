"""Probe a visible block-versus-scaling decision on training or development Soul Nexus fights."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import gzip
import json
from pathlib import Path
import runpy
from tempfile import TemporaryDirectory

from sts2rl.act1 import save_json
from sts2rl.combat_effects import block_preview, power
from sts2rl.combat_outcome import outcome
from sts2rl.encounter import EncounterModel
from sts2rl.native import NativeSession, ReplayFork, digest, legal_actions
from sts2rl.run_bundle import load_bundle
from sts2rl.run_evaluation import act_start
from sts2rl.run_policy import RunPolicy, RunWeights, _cost
from sts2rl.teacher import incoming

ROOT = Path(__file__).resolve().parents[1]


class ReserveBlock:
    def __init__(self, config, enabled):
        self.actor = EncounterModel(config)
        self.enabled = enabled
        self.changes = []

    def choose(self, state, macro):
        original = self.actor.choose(state, macro)
        if not self.enabled or original.kind != "play_card":
            return original
        enemies = [e for e in state.get("enemies") or [] if e["hp"] > 0]
        if len(enemies) != 1 or enemies[0]["id"] != "MONSTER.SOUL_NEXUS":
            return original
        need = incoming(enemies[0]) - state["player"]["block"]
        if need < max(16, 0.70 * state["player"]["hp"]) or power(
            state.get("player_powers"), "INTANGIBLE"
        ):
            return original
        cards = {c["index"]: c for c in state["hand"]}
        selected = cards[original.args["card_index"]]
        stats = selected.get("stats") or {}
        if (
            _cost(selected) < 2
            or stats.get("damage")
            or stats.get("block")
            or not (selected["type"] == "Power" or stats.get("poisonpower"))
        ):
            return original
        if (
            power(enemies[0].get("powers"), "POISON") + stats.get("poisonpower", 0)
            >= enemies[0]["hp"]
        ):
            return original
        blocks = []
        for action in legal_actions(state):
            if action.kind == "play_card":
                card = cards[action.args["card_index"]]
                block = block_preview(card.get("stats") or {})
                if block > 0 and _cost(card) < _cost(selected):
                    blocks.append((block / max(1, _cost(card)), block, action))
        if not blocks:
            return original
        alt = max(blocks, key=lambda v: v[:2])[2]
        self.changes.append(
            {
                "round": state["round"],
                "root": digest(state),
                "incoming_after_block": need,
                "hp": state["player"]["hp"],
                "original": selected["id"],
                "alternative": cards[alt.args["card_index"]]["id"],
            }
        )
        return alt


def play(task):
    spec, history, root, seed, phase, host, bundle, plan, output = task
    _, settings = load_bundle(bundle)
    base = json.loads(settings["encounter_model"].read_bytes())
    weights = RunWeights.load(settings["weights"])
    pressure = {
        **base,
        "act3_hallways": {"plans": {"pressure": plan}, "by_room": {"Elite": "pressure"}},
    }
    arms = {}
    with (
        TemporaryDirectory() as tmp,
        NativeSession(
            ROOT,
            Path(tmp) / "game",
            host_path=host,
            act_list=spec.get("act_list", "default"),
            timeout=75,
        ) as game,
    ):
        fork = ReplayFork(spec, tuple(history), root)
        for name, config in (("frozen", base), ("pressure", pressure)):
            for reserve in (False, True):
                actor = ReserveBlock(config, reserve)
                result = outcome(game, game.restore(fork), actor, RunPolicy(weights))
                arms[name + ("_reserve" if reserve else "")] = {**result, "changes": actor.changes}
    save_json(
        output / (root + ".json"), {"seed": seed, "root": root, "partition": phase, "arms": arms}
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ("maps", "host", "bundle", "plans", "seed-lock", "output"):
        p.add_argument("--" + arg, type=Path, required=True)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--roots", type=Path, nargs="+")
    group.add_argument("--runs", type=Path, nargs="+")
    p.add_argument("--partition", choices=("train", "development"), required=True)
    p.add_argument("--workers", type=int, default=2)
    a = p.parse_args()
    maps = json.loads((a.maps / "index.json").read_bytes())
    seeds = {r["seed"]: r["map_digest"] for r in maps}
    held = set(json.loads(a.seed_lock.read_bytes())["seeds"]["test"])
    if any(r["partition"] != a.partition for r in maps) or set(seeds) & held:
        raise ValueError("Expected eligible, partitioned training or development maps")
    a.output.mkdir(parents=True, exist_ok=False)
    if a.runs:
        collect = runpy.run_path(str(ROOT / "scripts/collect-act2-fight-openings.py"))["export"]
        groups = []
        for n, source in enumerate(a.runs):
            root = a.output / ("openings-" + str(n))
            root.mkdir()
            groups.append(root)
            for f in sorted(source.glob("*/result.json")):
                row = json.loads(f.read_bytes())
                if (
                    row["seed"] not in seeds
                    or row["status"] != "complete"
                    or row["start_digest"] != seeds[row["seed"]]
                ):
                    raise ValueError("Unrecognized development map")
                if not any(r["icon"] == "Elite" for r in row["rooms"]):
                    continue
                if act_start(f.parent / "game/rpc.jsonl", 3).expected_digest != seeds[row["seed"]]:
                    raise ValueError("Different original map")
                collect((f.parent, root, a.host.resolve(), 3))
    else:
        groups = a.roots
    plan = json.loads(a.plans.read_bytes())["pressure"]
    tasks = {}
    opening_errors = []
    for folder in groups:
        for f in folder.glob("*.json.gz"):
            with gzip.open(f, "rt", encoding="utf-8") as stream:
                group = json.load(stream)
            if group["seed"] not in seeds or group["act"] != 3:
                raise ValueError("Ineligible fight opening")
            if group["error"]:
                opening_errors.append({"seed": group["seed"], "error": group["error"]})
            for start in group["starts"]:
                if start["room"] != "Elite" or start["formation"] != "SOUL_NEXUS":
                    continue
                key = start["root"]
                tasks[key] = (
                    group["specification"],
                    group["history"][: start["step"]],
                    key,
                    group["seed"],
                    a.partition,
                    a.host.resolve(),
                    a.bundle,
                    plan,
                    a.output,
                )
    with ProcessPoolExecutor(a.workers) as pool:
        list(pool.map(play, tasks.values()))
    rows = [json.loads((a.output / (key + ".json")).read_bytes()) for key in sorted(tasks)]
    stats = {}
    for arm in ("frozen", "frozen_reserve", "pressure", "pressure_reserve"):
        selected = [r["arms"][arm] for r in rows]
        stats[arm] = {
            "wins": sum(r["won"] for r in selected),
            "hp": sum(r["hp"] for r in selected),
            "openings_changed": sum(bool(r["changes"]) for r in selected),
        }
    summary = {
        "opening_errors": opening_errors,
        "partition": a.partition,
        "maps": len(maps),
        "roots": len(rows),
        "distinct_seeds": len({r["seed"] for r in rows}),
        "scores": stats,
    }
    save_json(a.output / "report.json", summary)
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
