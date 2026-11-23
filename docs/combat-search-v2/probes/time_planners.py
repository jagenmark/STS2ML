"""Small, offline timing probe. Run from the checkout root with PYTHONPATH=src."""

from __future__ import annotations

import json
import runpy
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from time import perf_counter_ns

from sts2rl.encounter import EncounterModel
from sts2rl.native import legal_actions
from sts2rl.run_policy import RunPolicy, RunWeights
from sts2rl.turn_planning import _search_survival_lines, choose_turn, choose_turn_survival


ROOT = Path(__file__).resolve().parents[3]
CHAMPION = ROOT / "releases/silent-a10-v2-tactics/challenger"
ARCHIVE = Path("/tmp/sts2-eval-20261121/final_v2_mech_v3_896")
REPEATS = 80

helpers = runpy.run_path(str(ROOT / "tests/test_combat_mechanics_v3.py"))
combat_state = helpers["_combat_state"]
card = helpers["_card"]
enemy = helpers["_enemy"]


def defend(index, block):
    return card(index, "DEFEND_SILENT", "Skill", 1, {"block": block}, target="Self")


def attack(index, amount):
    return enemy(index, "SHRINKER_BEETLE", 38, 38, [{"type": "Attack", "damage": amount}])


def fixtures():
    yield "Energy Potion", combat_state(
        hp=4, energy=0, hand=[{**defend(0, 8), "can_play": False}], enemies=[attack(0, 10)],
        potions=[{"index": 0, "id": "POTION.ENERGY_POTION", "target_type": "Self", "vars": {"Energy": 2}}],
    )
    yield "Burst", combat_state(
        hp=3, energy=2, hand=[card(0, "BURST", "Skill", 1, {}, target="Self"), defend(1, 8)],
        enemies=[attack(0, 16)],
    )
    yield "Survivor", combat_state(
        hp=3, energy=2, enemies=[attack(0, 15)], hand=[
            card(0, "SURVIVOR", "Skill", 1, {"block": 8, "discard": 1}, target="Self"),
            defend(1, 5),
            {**card(2, "BURN", "Status", 0, {"damage": 2}, target="None"), "can_play": False},
        ],
    )
    yield "7 cards / 3 enemies", combat_state(
        hp=9, energy=3, enemies=[attack(0, 8), attack(1, 11), attack(2, 7)], hand=[
            defend(0, 5), defend(1, 8),
            card(2, "NEUTRALIZE", "Attack", 0, {"damage": 3, "weakpower": 1}),
            card(3, "STRIKE_SILENT", "Attack", 1, {"damage": 6}),
            card(4, "DASH", "Attack", 2, {"damage": 10, "block": 10}),
            card(5, "PRECISE_CUT", "Attack", 0, {"damage": 8}),
            card(6, "KNIFE_TRAP", "Skill", 1, {"calculatedshivs": 3}),
        ],
        potions=[{"index": 0, "id": "POTION.ENERGY_POTION", "target_type": "Self", "vars": {"Energy": 2}}],
    )


def p95(samples):
    return statistics.quantiles(samples, n=100, method="inclusive")[94]


def timing(call):
    call()
    durations = []
    for _ in range(REPEATS):
        start = perf_counter_ns()
        call()
        durations.append((perf_counter_ns() - start) / 1e6)
    return statistics.median(durations), p95(durations)


def count_evaluated_children(call):
    counts = Counter()

    def observe(frame, event, _arg):
        if event == "call" and frame.f_code.co_filename.endswith("turn_planning.py"):
            counts[frame.f_code.co_name] += 1

    sys.setprofile(observe)
    try:
        call()
    finally:
        sys.setprofile(None)
    return counts["line_quality_and_meta"] - 1  # excludes the initial End Turn


def trace_sample():
    actions = defaultdict(list)
    game_seconds, combat_calls, trace_actions = [], [], []
    for suite in ("val256", "seeded128", "rep512"):
        for index in (0, 16, 32, 48):
            trace = ARCHIVE / suite / f"run-{index:04d}/game/rpc.jsonl"
            records = [json.loads(line) for line in trace.read_text().splitlines()]
            game_seconds.append(sum(row["seconds"] for row in records))
            counts = Counter()
            for row in records:
                command = row["command"]
                if command["cmd"] == "action":
                    kind = command["action"]
                    actions[kind].append(row["seconds"] * 1000)
                    counts[kind] += 1
            combat_calls.append(sum(counts[k] for k in ("play_card", "use_potion", "end_turn")))
            trace_actions.append(sum(counts.values()))
    for kind in ("play_card", "use_potion", "end_turn"):
        values = actions[kind]
        print(f"RPC {kind}: n={len(values)} p50={statistics.median(values):.2f} p95={p95(values):.2f} ms")
    for name, values in (
        ("RPC seconds per game", game_seconds), ("combat action proxy per game", combat_calls),
        ("all physical actions per game", trace_actions),
    ):
        print(f"{name}: mean={statistics.mean(values):.2f}, median={statistics.median(values):.2f}")


def main():
    policy = RunPolicy(RunWeights.load(CHAMPION / "weights.json"))
    print(sys.version.split()[0], f"{REPEATS} repetitions per fixture/mode")
    for name, state in fixtures():
        encounter = EncounterModel.load(CHAMPION / "encounter_model.json")
        encounter.prepare(state, policy)
        actor = encounter.actor
        actions = legal_actions(state)
        proposed = actor.combat(state, actions)
        print(f"{name} ({len(actions)} legal root actions)")
        cases = (
            ("classic choose_turn w6 d5", lambda: choose_turn(state, actor), False),
            ("survival override w8 d5", lambda: choose_turn_survival(state, actor, proposed), False),
            ("survival kernel w8 d5", lambda: _search_survival_lines(state, actor, actions), True),
            ("survival kernel w16 d5", lambda: _search_survival_lines(state, actor, actions, width=16), True),
        )
        for label, call, count in cases:
            median, tail = timing(call)
            children = count_evaluated_children(call) if count else 0
            work = f", {children} scored children, {median * 1000 / children:.1f} us/child incl. fixed costs" if children else ""
            print(f"  {label}: p50={median:.3f} p95={tail:.3f} ms{work}")
        actual = encounter.choose(state, policy)
        print("  deployed", actual.kind, actual.args)
    if ARCHIVE.is_dir():
        trace_sample()


if __name__ == "__main__":
    main()
