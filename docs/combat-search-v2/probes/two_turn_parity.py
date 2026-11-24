"""Compare off-switch action, board and audit transcripts under two source PYTHONPATHs."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from hashlib import sha256
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from sts2rl.combat_search_v2.integration import CombatSearchV2
from sts2rl.deployed_controller import DeployedController
from sts2rl.native import NativeSession, canonical_json, digest
from test_combat_search_v2_native import Oracle, ROOT


def fixture(job):
    arm, encounter = job
    transcript = sha256()
    controller = DeployedController.from_bundle(ROOT / "releases/silent-a10-v2-tactics/challenger/policy.json")
    config = replace(controller.combat_v2.config, v61_boss_safe=arm != "v5", v61_act2_hallways_act3=arm != "v5",
                     power_leaf_v62=arm == "v62")
    mode = controller.combat_v2 = CombatSearchV2(config, record=True)
    with TemporaryDirectory() as tmp, NativeSession(ROOT, Path(tmp) / "game",
                                                   host_path=Path(os.environ["CSV2DEV_HOST"])) as game:
        oracle = Oracle(game)
        oracle.start("PARITY_" + encounter, ["DASH", "DEFLECT", "DEADLY_POISON", "SNAKEBITE",
                     "AFTERIMAGE", "SLICE", "BLUR", "NEUTRALIZE", "DEFEND_SILENT"], encounter=encounter)
        state = oracle.public
        for step in range(1, 601):
            for view in (state, state.get("combat_state", {})):
                if ctx := view.get("context"):
                    boss = encounter.endswith("_BOSS")
                    ctx.update(act=2, room_type="Boss" if boss else "Monster", floor=16 if boss else 9)
                    if boss:
                        ctx["boss"] = {"id": encounter}
            mode.records.clear()
            action = controller.choose(state, game)
            after = oracle.command(**action.command())
            controller.observe(state, action, after)
            rec = mode.records[-1].copy() if mode.records else {}
            for field in ("ns", "leaf_ns"):
                rec.pop(field, None)
            transcript.update(canonical_json([digest(state), action.command(), rec, digest(after)]))
            if not after.get("in_combat") or after["decision"] == "game_over":
                mode.write(tmp)
                metadata = (Path(tmp) / "combat-search-v2.jsonl").read_bytes().splitlines()[0]
                return [arm, encounter, step, transcript.hexdigest(), sha256(metadata).hexdigest()]
            state = after
    raise RuntimeError(job)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--workers", choices=(12,), type=int, default=12)
    args = parser.parse_args()
    jobs = [(arm, enc) for arm in ("v5", "v61", "v62") for enc in
            ("WATERFALL_GIANT_BOSS", "LAGAVULIN_MATRIARCH_BOSS", "SHRINKER_BEETLE_WEAK")]
    with ProcessPoolExecutor(args.workers) as pool:
        args.output.write_bytes(canonical_json(list(pool.map(fixture, jobs))))
