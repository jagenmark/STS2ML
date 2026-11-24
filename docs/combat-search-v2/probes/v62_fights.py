"""Matched native fight fixtures. Only the harness knows the scenario seed."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from sts2rl.combat_search_v2 import planner
from sts2rl.combat_search_v2.integration import CombatSearchV2
from sts2rl.deployed_controller import DeployedController
from sts2rl.native import NativeSession, digest
from sts2rl.run_policy import _power
from test_combat_search_v2_native import Oracle

ROOT = Path(__file__).resolve().parents[3]
POLICY = ROOT / "releases/silent-a10-v2-tactics/challenger/policy.json"
SYNERGY = {"ACCELERANT": "DEADLY_POISON", "NOXIOUS_FUMES": "POISONED_STAB", "ACCURACY": "BLADE_DANCE",
           "PHANTOM_BLADES": "LEADING_STRIKE", "INFINITE_BLADES": "CLOAK_AND_DAGGER",
           "AFTERIMAGE": "SLICE", "FOOTWORK": "DEFEND_SILENT"}


def fight(job):
    card, encounter, index, enabled, hp, *deck_kind = job
    escape = card == "FRANTIC_ESCAPE"
    room = "Boss" if encounter.endswith("_BOSS") else "Elite" if encounter.endswith("_ELITE") else "Monster"
    deck = ["STRIKE_SILENT", "DEFEND_SILENT", "DASH"] * 3
    if deck_kind:
        deck = ["LEG_SWEEP", "DAGGER_SPRAY", "DEFLECT", "NEUTRALIZE", "DASH", "SNAKEBITE", "SLICE"]
    if escape:
        deck += ["PREDATOR", "BACKFLIP", "SNAKEBITE", "ADRENALINE"] * 2
    else:
        deck += [card, SYNERGY[card], SYNERGY[card]]
    seed = f"CSV6FIX_{card}_{encounter}_{index}"
    controller = DeployedController.from_bundle(POLICY)
    config = replace(controller.combat_v2.config, v61_boss_safe=True, v61_act2_hallways_act3=True,
                     power_leaf_v62=enabled and not escape, early_escape_v62=enabled and escape)
    mode = controller.combat_v2 = CombatSearchV2(config, record=True)
    counts = Counter()
    beam = planner._Search.beam
    decisions = []

    def observe_beam(search, frontier):
        retained = beam(search, frontier)
        if frontier and len(frontier[0].path) == 1:
            for nodes, label in ((frontier, "beam_enter"), (retained, "beam_keep")):
                counts[label] += sum(n.path[0].kind == "play_card" and hand.get(n.path[0].slot) == card for n in nodes)
        return retained

    def route(raw):
        # enter_room uses the starting map's context. Supply the fixed room
        # metadata just as in the qualified v6.1 differential fixtures.
        if raw.get("in_combat"):
            for view in (raw, raw.get("combat_state", {})):
                if ctx := view.get("context"):
                    ctx.update(act=2, floor=16 if room == "Boss" else 9, room_type=room,
                               boss={"id": encounter} if room == "Boss" else ctx.get("boss"))
        return raw

    with TemporaryDirectory() as tmp, NativeSession(ROOT, Path(tmp) / "game",
            host_path=Path(os.environ["CSV2DEV_HOST"])) as game, patch.object(planner._Search, "beam", observe_beam):
        oracle = Oracle(game)
        oracle.start(card, deck, encounter=encounter, hp=hp, seed=seed)
        before = route(oracle.public)
        opening = digest(before)
        for _ in range(600):
            hand = {c["index"]: c["id"].removeprefix("CARD.") for c in before.get("hand", ())}
            mode.records.clear()
            act = controller.choose(before, game)
            action = hand[act.args["card_index"]] if act.kind == "play_card" else act.kind
            fallback = mode.last_fallback
            if action == card:
                counts["played_fallback" if fallback else "played_search"] += 1
            if escape and before["decision"] == "combat_play":
                enemy = before["enemies"][0]
                timer = _power(enemy.get("powers"), "SANDPIT")
                decisions.append([before["round"], timer, digest(before), action, fallback])
            after = route(oracle.command(**act.command()))
            controller.observe(before, act, after)
            if mode.records and (audit := mode.records[-1].get("oracle")):
                counts[audit[1]] += 1
                if audit[1] == "mismatch":
                    raise ValueError((job, before.get("round"), audit, mode.records[-1]))
            if not after.get("in_combat") or after["decision"] == "game_over":
                return dict(card=card, encounter=encounter, seed=seed, enabled=enabled, opening=opening, entry=hp,
                            deck="developed" if deck_kind else "basic",
                            hp=after["player"]["hp"], counts=counts, decisions=decisions)
            before = after
    raise RuntimeError(f"Fight exceeded fixture cap: {job}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--workers", type=int, choices=(12,), default=12)
    args = parser.parse_args()
    jobs = [(card, encounter, i, enabled, 70) for card in SYNERGY
            for encounter in ("DECIMILLIPEDE_ELITE", "THE_INSATIABLE_BOSS") for i in range(2)
            for enabled in (False, True)]
    jobs.extend(("FRANTIC_ESCAPE", "THE_INSATIABLE_BOSS", i, enabled, 70) for i in range(12) for enabled in (False, True))
    jobs.extend((card, "DECIMILLIPEDE_ELITE", i, enabled, 250) for card in SYNERGY for i in range(2)
                for enabled in (False, True))
    jobs.extend((card, encounter, i, enabled, 70) for card in SYNERGY
                for encounter in ("SLUMBERING_BEETLE_NORMAL", "KNOWLEDGE_DEMON_BOSS")
                for i in range(2) for enabled in (False, True))
    jobs.extend((card, encounter, i, enabled, 70, "developed") for card in SYNERGY
                for encounter in ("SHRINKER_BEETLE_WEAK", "SLUMBERING_BEETLE_NORMAL", "DECIMILLIPEDE_ELITE",
                                  "THE_INSATIABLE_BOSS", "KNOWLEDGE_DEMON_BOSS")
                for i in range(2) for enabled in (False, True))
    with ProcessPoolExecutor(args.workers) as pool:
        results = list(pool.map(fight, jobs))
    assert all(a["opening"] == b["opening"] for a, b in zip(results[::2], results[1::2], strict=True))
    args.output.write_bytes(json.dumps(results, separators=(",", ":")).encode())
