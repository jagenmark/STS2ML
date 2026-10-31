"""Collect ordinary Silent Act 1 runs, audit coverage, fit and evaluate micro."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time

from sts2rl.act1 import act1_profile, existing_act1_results, run_act1, save_json
from sts2rl.act1_evaluation import evaluate_three_way
from sts2rl.aggregation import aggregate_source
from sts2rl.native import CURRICULUM_ASCENSIONS

ROOT = Path(__file__).resolve().parents[1]


def summary(results):
    counts = {}
    for field in ("monsters", "teacher_monsters", "cards", "relics", "floors", "skipped_roots"):
        counter = Counter()
        for r in results:
            counter.update(r.get(field, {}))
        counts[field] = dict(counter)
    return {"completed": len(results), "successful_runs": sum(r["status"] == "complete" for r in results),
        "act1_clears": sum(r.get("cleared_act1", False) for r in results),
        "decisions": sum(r["decisions"] for r in results), "branches": sum(r["branches"] for r in results),
        "fights": sum(r["fights"] for r in results), "max_floor": max((r["max_floor"] for r in results), default=0),
        "teacher_overrides": sum(r.get("teacher_overrides", 0) for r in results),
        "teacher_disagreements": sum(r.get("teacher_disagreements", 0) for r in results),
        "queried_actor_positive_regret": sum(r.get("queried_actor_positive_regret", 0) for r in results),
        "queried_actor_regret_sum": sum(r.get("queried_actor_regret_sum", 0) for r in results),
        "run_errors": [r for r in results if r["status"] not in ("complete", "running")],
        "search_errors": sum(len(r.get("search_errors", [])) for r in results), **counts}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--runs", type=int, default=64)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--samples", type=int, default=4)
    p.add_argument("--roots-per-fight", type=int, default=12)
    p.add_argument("--query-probability", type=float, default=.35)
    p.add_argument("--prefix", default="ACT1TRAIN001")
    p.add_argument("--macro-checkpoint", type=Path)
    p.add_argument("--student-checkpoint", type=Path, help="Collect labels on this frozen student's own trajectories; teacher suggestions never control the real game")
    p.add_argument("--aggregate-from", type=Path, help="Completed source experiment to retain, preserving its train/validation/test assignments")
    p.add_argument("--ascension", type=int, choices=CURRICULUM_ASCENSIONS, default=10)
    p.add_argument("--condition-ascension", action="store_true", help="Use the v3 difficulty-conditioned profile (automatic below A10)")
    p.add_argument("--host-path", type=Path, help="An isolated qualified host DLL; default is the Release host")
    p.add_argument("--collect-only", action="store_true")
    p.add_argument("--epochs", type=int, default=20)
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--evaluate", type=int, default=32)
    p.add_argument("--resume", action="store_true", help="After a failed runner exits, keep complete runs and retry archived incomplete runs")
    p.add_argument("--allow-host-update", action="store_true", help="During resume, permit an audited headless-host fix; game assembly and macro weights must match")
    args = p.parse_args()
    args.condition_ascension |= args.ascension != 10
    args.host_path = str(args.host_path.resolve()) if args.host_path else None
    args.student_checkpoint = str(args.student_checkpoint.resolve()) if args.student_checkpoint else None
    args.aggregate_from = str(args.aggregate_from.resolve()) if args.aggregate_from else None
    if args.student_checkpoint and not args.aggregate_from:
        p.error("Student-state collection requires --aggregate-from to retain prior teacher data")
    if args.host_path and not Path(args.host_path).is_relative_to(ROOT):
        p.error("Host DLL must be inside this repository's isolated artifacts")
    if args.allow_host_update and not args.resume:
        p.error("Host updates only apply to an explicitly resumed experiment")
    if min(args.runs, args.workers, args.roots_per_fight, args.epochs) < 1 or args.samples < 2 or args.evaluate < 0 or not 0 <= args.query_probability <= 1:
        p.error("Invalid run/search budget")
    if not args.collect_only and args.runs < 10:
        p.error("Fitting requires at least ten independent run seeds")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    previous = None
    if args.resume:
        if not (output / "config.json").exists() or not (output / "status.json").exists():
            p.error("Resume requires an existing configuration and terminal status")
        if (output / "STOP").exists():
            p.error("STOP is present; resume must not override a requested stop")
        previous = json.loads((output / "config.json").read_text(encoding="utf-8"))
        previous_status = json.loads((output / "status.json").read_text(encoding="utf-8"))
        if previous_status.get("stage") != "failed":
            p.error("Resume only after a failed runner has exited; do not run concurrently")
        for key in ("runs", "samples", "roots_per_fight", "query_probability", "prefix", "collect_only", "epochs", "evaluate"):
            if previous[key] != getattr(args, key):
                p.error("Resume configuration mismatch: " + key)
        for key, default in (("ascension", 10), ("condition_ascension", False), ("host_path", None), ("student_checkpoint", None), ("aggregate_from", None)):
            if previous.get(key, default) != getattr(args, key):
                p.error("Resume configuration mismatch: " + key)
        old_macro = previous.get("macro_checkpoint")
        if (Path(old_macro).resolve() if old_macro else None) != (args.macro_checkpoint.resolve() if args.macro_checkpoint else None):
            p.error("Resume macro checkpoint mismatch")
    elif (output / "config.json").exists():
        p.error("Use a fresh experiment folder")
    config = {**vars(args), "output": str(output), "macro_checkpoint": str(args.macro_checkpoint) if args.macro_checkpoint else None,
              "sampler": act1_profile(args.ascension, args.condition_ascension), "started": datetime.now(timezone.utc).isoformat(),
              "git_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "source_hashes": {str(f.relative_to(ROOT)): hashlib.sha256(f.read_bytes()).hexdigest()
                                for f in [*ROOT.glob("src/sts2rl/*.py"), Path(__file__),
                                    *ROOT.glob("scripts/headless/*.cs"), *ROOT.glob("scripts/headless-*.patch")]},
              "runtime_sha256": {str(f.relative_to(ROOT)): hashlib.sha256(f.read_bytes()).hexdigest()
                  for f in [ROOT / "artifacts/upstreams/sts2-cli/lib/sts2.dll",
                            Path(args.host_path) if args.host_path else ROOT / "artifacts/upstreams/sts2-cli/src/Sts2Headless/bin/Release/net9.0/Sts2Headless.dll",
                            Path(args.host_path).with_name("GodotSharp.dll") if args.host_path else ROOT / "artifacts/upstreams/sts2-cli/src/Sts2Headless/bin/Release/net9.0/GodotSharp.dll"]},
              "macro_sha256": hashlib.sha256(args.macro_checkpoint.read_bytes()).hexdigest() if args.macro_checkpoint else None}
    config.update(collection_actor="student" if args.student_checkpoint else "teacher_assisted",
                  student_sha256=hashlib.sha256(Path(args.student_checkpoint).read_bytes()).hexdigest() if args.student_checkpoint else None,
                  student_collection_device="cpu" if args.student_checkpoint else None)
    aggregate_paths, inherited_split, aggregation = aggregate_source(args.aggregate_from, config) if args.aggregate_from else ([], None, None)
    config["aggregation"] = aggregation
    if previous:
        old_runtime = {k.replace("\\", "/"): v for k, v in previous["runtime_sha256"].items()}
        new_runtime = {k.replace("\\", "/"): v for k, v in config["runtime_sha256"].items()}
        game_key = "artifacts/upstreams/sts2-cli/lib/sts2.dll"
        if old_runtime[game_key] != new_runtime[game_key] or previous["macro_sha256"] != config["macro_sha256"]:
            p.error("Resume cannot mix native builds or macro weights")
        if previous.get("student_sha256") != config["student_sha256"] or previous.get("aggregation") != aggregation:
            p.error("Resume cannot change the frozen student or aggregate dataset/split")
        if old_runtime != new_runtime and not args.allow_host_update:
            p.error("Headless host changed; audit the fix before using --allow-host-update")
        save_json(output / f"resume-config-{time.time_ns()}.json", config)
    else:
        save_json(output / "config.json", config)
    if args.macro_checkpoint:
        import torch
        torch.set_num_threads(1)
    started = time.perf_counter()
    native_args = {"ascension": args.ascension, "condition_ascension": args.condition_ascension, "host_path": args.host_path}
    results, pending = existing_act1_results(output, args.runs, args.prefix,
        ascension=args.ascension, condition_ascension=args.condition_ascension) if args.resume else ([], range(args.runs))
    status = {"stage": "collecting", "total": args.runs, **summary(results), "seconds": 0}
    save_json(output / "status.json", status)
    try:
        student = None
        if args.student_checkpoint:
            from sts2rl.micro import load_micro
            student = load_micro(args.student_checkpoint, device="cpu")
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = [executor.submit(run_act1, ROOT, output, i, prefix=args.prefix,
                samples=args.samples, roots_per_fight=args.roots_per_fight,
                query_probability=args.query_probability, macro_checkpoint=args.macro_checkpoint,
                micro_policy=student, execute_teacher=student is None, **native_args) for i in pending]
            for future in as_completed(futures):
                results.append(future.result())
                status = {"stage": "collecting", "total": args.runs, **summary(results),
                          "seconds": time.perf_counter() - started}
                save_json(output / "status.json", status, best_effort=True)
                print(json.dumps({k: status[k] for k in ("completed", "total", "decisions", "fights", "max_floor", "act1_clears", "search_errors")}), flush=True)
        save_json(output / "collection.json", results)
        if status["run_errors"]:
            raise RuntimeError("Incomplete/error runs quarantined; inspect coverage before fitting")
        if args.student_checkpoint and any(r.get("teacher_overrides") != 0 or r.get("collection_actor") != "student" for r in results):
            raise RuntimeError("Student-state collection violated the no-teacher-override contract")
        if not args.collect_only:
            from sts2rl.micro import fit_micro, load_micro
            save_json(output / "status.json", {**status, "stage": "training"})
            model = output / "model"
            if model.exists() and (pending or not (model / "report.json").exists()):
                if not model.resolve().is_relative_to(output):
                    raise ValueError("Model folder resolves outside the experiment")
                model.rename(output / f"incomplete-model-{time.time_ns()}")
            if not (model / "report.json").exists():
                if args.aggregate_from:
                    _, _, latest = aggregate_source(args.aggregate_from, config)
                    if latest != aggregation:
                        raise RuntimeError("Aggregate dataset changed during collection")
                fit_micro([*aggregate_paths, *sorted(output.glob("run-*/teacher.jsonl"))], model,
                          epochs=args.epochs, device=args.device, inherited_split=inherited_split)
            if args.evaluate:
                save_json(output / "status.json", {**status, "stage": "evaluating"})
                comparison = evaluate_three_way(ROOT, output, episodes=args.evaluate,
                    prefix=args.prefix + "EVAL", macro_checkpoint=args.macro_checkpoint,
                    micro_policy=load_micro(model / "best.pt", device=args.device), samples=args.samples,
                    previous_policy=load_micro(args.student_checkpoint, device=args.device) if args.student_checkpoint else None,
                    roots_per_fight=args.roots_per_fight, query_probability=args.query_probability,
                    workers=args.workers, **native_args, protocol={
                        "macro_sha256": config["macro_sha256"], "runtime_sha256": config["runtime_sha256"],
                        "source_hashes": config["source_hashes"],
                        "previous_micro_sha256": config["student_sha256"],
                        "micro_sha256": hashlib.sha256((model / "best.pt").read_bytes()).hexdigest()})
                if any(r["run_errors"] for r in comparison["policies"].values()):
                    raise RuntimeError("Incomplete live evaluation; inspect policy-comparison.json; errors are not defeats")
        save_json(output / "status.json", {**status, "stage": "complete", "seconds": time.perf_counter() - started})
    except BaseException as exc:
        save_json(output / "status.json", {"stage": "failed", **summary(results), "error": f"{type(exc).__name__}: {exc}"})
        raise


if __name__ == "__main__":
    main()
