"""Run only the closed, fresh lategame panels with passive transition telemetry."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import gzip
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from sts2rl.deployed_controller import DeployedController
from sts2rl.native import canonical_json
from sts2rl.run_bundle import load_bundle
from sts2rl.run_evaluation import play_episode
from sts2rl.run_policy import RunWeights

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "releases/silent-a10-v2-tactics/challenger/policy.json"
WORK = ROOT / "artifacts/v5-autopsy"
HOST = WORK / "native-host/src/Sts2Headless/bin/Curriculum/net9.0/Sts2Headless.dll"
HOOK = ROOT / "scripts/headless/lategame-observer/bin/Debug/net9.0/LategameObserver.dll"


def panel(name):
    return [
        [i, f"{name}_{i:04d}", "seeded" if i % 2 else "default"]
        for i in range({"V5DIAG": 384, "V5DEV": 256}[name])
    ]


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def job(args):
    folder, (index, seed, mode), observe, fix = args
    role, options = load_bundle(BUNDLE)
    trajectory = hashlib.sha256()
    macro_choices = []

    def dev_step(step, before, action, after, fallback):
        trajectory.update(canonical_json([action.snapshot, action.command()]))
        if before["decision"] in ("rest_site", "event_choice"):
            chosen = next(
                (o for o in before["options"] if o["index"] == action.args.get("option_index")), {}
            )
            macro_choices.append(
                [step, action.snapshot, chosen.get("option_id") or chosen.get("text_key")]
            )

    def write_step(step, before, action, after, fallback):
        view = before.get("combat_state", before)
        ctx = view.get("context") or {}
        late = ctx.get("act") == 3 or (ctx.get("act") == 2 and ctx.get("room_type") == "Boss")
        if before.get("in_combat") and not late:
            return
        if before["decision"] == "map_select":
            return
        trim = {
            "public_combat_history",
            "act1_search_support",
            "runtime_identity",
            "combat_state",
            "draw_pile_cards",
            "discard_pile_cards",
            "exhaust_pile_cards",
        }
        record = {k: v for k, v in before.items() if k not in trim}
        if view is not before:
            record["combat_state"] = {k: v for k, v in view.items() if k not in trim}
        payload = dict(
            step=step,
            before=record,
            action=action.command(),
            fallback=fallback,
            after_player=after.get("player", {}),
            next_decision=after["decision"],
        )
        stream.write(json.dumps(payload, separators=(",", ":")) + "\n")

    path = folder / seed
    path.mkdir()
    with (
        TemporaryDirectory(dir=path) as temp,
        gzip.open(path / "trace.gz", "wt", compresslevel=1) as stream,
    ):
        if observe:
            os.environ.update(
                DOTNET_STARTUP_HOOKS=str(HOOK), STS2_AUTOPSY_RECEIPTS=str(path / "native.jsonl")
            )
        task = (
            ROOT,
            HOST,
            Path(temp) / "episode",
            seed,
            index,
            role,
            asdict(RunWeights.load(options["weights"])),
            None,
            {
                **options,
                "seeded_acts": mode == "seeded",
                "compact_combat_summary": True,
                "v6_lategame_fixes": fix,
                "transition_hook": write_step if observe else dev_step,
            },
        )
        row = play_episode(task)
    if not observe:
        row.update(trajectory_sha256=trajectory.hexdigest(), macro_choices=macro_choices)
    (path / "result.json").write_bytes(canonical_json(row))
    if row["status"] != "complete" or row.get("abandoned"):
        raise RuntimeError(f"{seed}: {row.get('error', row['status'])}")
    return seed


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--panel", choices=("V5DIAG", "V5DEV"), required=True)
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--fix", action="store_true")
    p.add_argument("--resume", action="store_true")
    args = p.parse_args()
    if args.fix and args.panel != "V5DEV":
        p.error("Prototypes require V5DEV")
    if os.environ.get("DOTNET_STARTUP_HOOKS") or any(
        os.environ.get(k) != "1" for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS")
    ):
        p.error("Expected single-thread BLAS/OMP and a clean parent host environment")
    DeployedController.from_bundle(BUNDLE)
    order = panel(args.panel)
    panel_hash = hashlib.sha256(canonical_json(order)).hexdigest()
    if (
        panel_hash
        != {
            "V5DIAG": "88993f46d0d41700e6014af5cf0079754dbb7ae2794e34c8ca63b0e0b5e2a51e",
            "V5DEV": "bbd4a073745a3b0a3c37ba3c36b81cea6647c6c47ffde6a871cbd2f572c72916",
        }[args.panel]
    ):
        raise ValueError("Panel lock mismatch")
    manifest = dict(
        panel=order,
        panel_sha256=panel_hash,
        bundle=checksum(BUNDLE),
        host=checksum(HOST),
        game=checksum(ROOT / "artifacts/upstreams/sts2-cli/lib/sts2.dll"),
        observer=checksum(HOOK) if args.panel == "V5DIAG" else None,
        fix=args.fix,
    )
    if args.panel == "V5DEV":
        manifest["source_sha256"] = {
            p.name: checksum(p)
            for p in (
                ROOT / "src/sts2rl" / n
                for n in (
                    "run_policy.py",
                    "deck_policy.py",
                    "strategy.py",
                    "run_evaluation.py",
                    "deployed_controller.py",
                )
            )
        }
    if manifest["bundle"] != "a686db12c8b217bd476ea5c8e60cf6f486b060665536ef9354e8f09c21c81fcb":
        raise ValueError("Frozen v5 manifest mismatch")
    folder = WORK / (args.panel + ("-fix" if args.fix else ""))
    folder.mkdir(exist_ok=args.resume)
    lock = folder / "lock.json"
    if lock.exists():
        if json.loads(lock.read_bytes()) != manifest:
            raise ValueError("Different locked experiment")
    else:
        with lock.open("xb") as f:
            f.write(canonical_json(manifest))
    print(panel_hash, len(order), flush=True)
    jobs = []
    for row in order:
        path = folder / row[1]
        if args.resume and (path / "result.json").exists():
            old = json.loads((path / "result.json").read_bytes())
            if old["status"] == "complete" and not old.get("abandoned"):
                continue
        if path.exists():
            path.rename(
                folder / f"{row[1]}.attempt-{len(list(folder.glob(row[1] + '.attempt-*'))) + 1}"
            )
        jobs.append((folder, row, args.panel == "V5DIAG", args.fix))
    with ProcessPoolExecutor(args.workers) as pool:
        for i, seed in enumerate(pool.map(job, jobs), 1):
            if i % 16 == 0:
                print(i, seed, flush=True)


if __name__ == "__main__":
    main()
