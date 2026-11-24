"""Matched diagnostic fights. Only this harness knows seeds, histories and native results."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
import gzip
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter_ns

from sts2rl.combat_search_v2.integration import CombatSearchV2
from sts2rl.combat_search_v2.next_intent import next_intent
from sts2rl.combat_search_v2.state import END_TURN, project
from sts2rl.combat_search_v2.transitions import advance
from sts2rl.combat_search_v2.two_turn import prepare
from sts2rl.deployed_controller import DeployedController
from sts2rl.native import NativeSession, ReplayFork, digest
from test_combat_search_v2_native import Oracle, ROOT
from test_two_turn_native import ENCOUNTERS

POLICY = ROOT / "releases/silent-a10-v2-tactics/challenger/policy.json"
ARCHIVE = ROOT / "docs/evidence/silent-a10-waterfall-openings.json.gz"
DECKS = (
    ["STRIKE_SILENT", "DEFEND_SILENT", "DASH"] * 3 + ["DEADLY_POISON", "FOOTWORK"],
    ["LEG_SWEEP", "DAGGER_SPRAY", "DEFLECT", "NEUTRALIZE", "DASH", "SNAKEBITE", "SLICE",
     "NOXIOUS_FUMES", "POISONED_STAB", "POISONED_STAB"],
    ["DASH", "LEG_SWEEP", "DEADLY_POISON", "SNAKEBITE", "DEFLECT", "SLICE"] * 2,
    ["DASH", "DEFLECT", "DEADLY_POISON", "SNAKEBITE", "AFTERIMAGE", "SLICE", "BLUR", "NEUTRALIZE",
     "DEFEND_SILENT", "POISONED_STAB", "DAGGER_SPRAY", "DASH"],
)


def route(public, encounter):
    # Match the v6.2 controlled-fixture routing. Historical openings keep their own context.
    if public.get("in_combat"):
        room = "Boss" if encounter.endswith("_BOSS") else "Monster"
        for view in (public, public.get("combat_state", {})):
            if ctx := view.get("context"):
                ctx.update(act=2, floor=16 if room == "Boss" else 9, room_type=room,
                           boss={"id": encounter} if room == "Boss" else ctx.get("boss"))
    return public


def label(state, kind, slot):
    if kind == "play_card":
        return state["hand"][slot]["id"].split(".")[-1] + f"@{slot}"
    return f"{kind}@{slot}" if slot >= 0 else kind


def fight(job):
    encounter, index, archive, pilot = job
    controller = DeployedController.from_bundle(POLICY)
    config = replace(controller.combat_v2.config, v61_boss_safe=True, v61_act2_hallways_act3=True,
                     power_leaf_v62=True, two_turn_pilot=pilot)
    assert (config.width, config.depth, config.children) == (16, 10, 512)
    mode = controller.combat_v2 = CombatSearchV2(config, record=True)
    counts = Counter()
    examples, latency, errors = [], [], []
    with TemporaryDirectory() as tmp, NativeSession(ROOT, Path(tmp) / "game", host_path=Path(os.environ["CSV2DEV_HOST"]),
            act_list="seeded" if archive else "default") as game:
        oracle = Oracle(game)
        if archive:
            with gzip.open(ARCHIVE) as stream:
                row = json.load(stream)[index]
            assert row["seed"].startswith("ACT1PATTEST")
            before = game.restore(ReplayFork(row["specification"], tuple(row["history"]), row["opening"]))
        else:
            deck = DECKS[index % len(DECKS)]
            hp = 70 if index < 4 else 90
            game.reset(f"CSV2TURN_FIGHT_{encounter}_{index}")
            oracle.command(cmd="set_player", hp=hp, max_hp=hp, deck=deck, potions=[])
            before = route(oracle.command(cmd="enter_room", type="monster", encounter=encounter), encounter)
        opening = digest(before)
        entry = before["player"]["hp"]
        for _ in range(600):
            mode.records.clear()
            start = perf_counter_ns()
            action = controller.choose(before, game)
            elapsed = perf_counter_ns() - start
            rec = mode.records[-1] if mode.records else {}
            diag = rec.get("pilot", {})
            active = diag.get("active", False)
            latency.append([elapsed, int(active), diag.get("pilot_ns", 0), diag.get("world_search_ns", 0)])
            counts["eligible"] += bool(diag)
            counts["active"] += active
            counts["changed"] += diag.get("changed", False)
            if diag.get("reason"):
                counts["gate/" + diag["reason"]] += 1
            if diag.get("changed") and len(examples) < 5:
                ctrl = diag["control"]
                examples.append(dict(round=before["round"], root_hp=before["player"]["hp"],
                    control=label(before, ctrl["kind"], ctrl["slot"]),
                    pilot=label(before, action.kind, action.args.get("card_index", -1)),
                    candidates=diag["candidates"]))
            forecasts = []
            ready = None
            if action.kind == "end_turn" and mode._decision:
                state = mode._decision[0].state
                leaf = advance(state, END_TURN)
                forecasts = [(e.name, next_intent(leaf, e)) for e in leaf.enemies if e.hp]
                ready, _ = prepare(leaf)
            after = oracle.command(**action.command())
            if not archive:
                after = route(after, encounter)
            controller.observe(before, action, after)
            if audit := rec.get("oracle"):
                counts[audit[1]] += 1
                if audit[1] == "mismatch":
                    errors.append([before.get("round"), audit, rec.get("difference")])
            if any(pred is not None for _, pred in forecasts):
                observed = project(after).state if after["decision"] == "combat_play" else None
                actual = {e.name: e.intents for e in observed.enemies} if observed else {}
                for name, pred in forecasts:
                    if pred is not None:
                        counts["intent"] += 1
                        if pred != actual.get(name):
                            counts["intent_mismatch"] += 1
                            errors.append([before["round"], name, repr(pred), repr(actual.get(name))])
                if ready:
                    counts["start"] += 1
                    if not observed or (ready.energy, ready.block, ready.boundary.count + len(ready.hand)) != (
                            observed.energy, observed.block, len(observed.hand)):
                        counts["start_mismatch"] += 1
                        errors.append([before["round"], "start energy/block/hand count"])
            if not after.get("in_combat") or after["decision"] == "game_over":
                assert after["player"]["hp"] >= 0
                return dict(encounter=encounter, index=index, archive=archive, pilot=pilot, opening=opening,
                            entry=entry, hp=after["player"]["hp"], win=after["player"]["hp"] > 0,
                            counts=counts, latency=latency, examples=examples, errors=errors)
            before = after
    raise RuntimeError(job)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--workers", type=int, choices=(12,), default=12)
    args = parser.parse_args()
    jobs = [(enc, i, False, arm) for enc in ENCOUNTERS for i in range(8) for arm in (False, True)]
    jobs += [("WATERFALL_GIANT_BOSS", i, True, arm) for i in range(20) for arm in (False, True)]
    with ProcessPoolExecutor(args.workers) as pool, gzip.open(args.output, "wt", encoding="utf-8") as stream:
        for row in pool.map(fight, jobs):
            stream.write(json.dumps(row, separators=(",", ":")) + "\n")
            stream.flush()


if __name__ == "__main__":
    main()
