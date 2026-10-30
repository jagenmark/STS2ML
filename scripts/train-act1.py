"""Collect ordinary Silent A10 Act 1 runs, audit coverage, fit and evaluate micro."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time

from sts2rl.act1 import run_act1, save_json
from sts2rl.native import ACT1_SAMPLER

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
    p.add_argument("--collect-only", action="store_true")
    p.add_argument("--epochs", type=int, default=20)
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--evaluate", type=int, default=32)
    args = p.parse_args()
    if min(args.runs, args.workers, args.roots_per_fight, args.epochs) < 1 or args.samples < 2 or args.evaluate < 0 or not 0 <= args.query_probability <= 1:
        p.error("Invalid run/search budget")
    if not args.collect_only and args.runs < 10:
        p.error("Fitting requires at least ten independent run seeds")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "config.json").exists():
        p.error("Use a fresh experiment folder")
    config = {**vars(args), "output": str(output), "macro_checkpoint": str(args.macro_checkpoint) if args.macro_checkpoint else None,
              "sampler": ACT1_SAMPLER, "started": datetime.now(timezone.utc).isoformat(),
              "git_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "source_hashes": {str(f.relative_to(ROOT)): hashlib.sha256(f.read_bytes()).hexdigest()
                                for f in [*ROOT.glob("src/sts2rl/*.py"), Path(__file__),
                                    *ROOT.glob("scripts/headless/*.cs"), *ROOT.glob("scripts/headless-*.patch")]},
              "runtime_sha256": {str(f.relative_to(ROOT)): hashlib.sha256(f.read_bytes()).hexdigest()
                  for f in [ROOT / "artifacts/upstreams/sts2-cli/lib/sts2.dll",
                            ROOT / "artifacts/upstreams/sts2-cli/src/Sts2Headless/bin/Release/net9.0/Sts2Headless.dll",
                            ROOT / "artifacts/upstreams/sts2-cli/src/Sts2Headless/bin/Release/net9.0/GodotSharp.dll"]},
              "macro_sha256": hashlib.sha256(args.macro_checkpoint.read_bytes()).hexdigest() if args.macro_checkpoint else None}
    save_json(output / "config.json", config)
    if args.macro_checkpoint:
        import torch
        torch.set_num_threads(1)
    started, results = time.perf_counter(), []
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = [executor.submit(run_act1, ROOT, output, i, prefix=args.prefix,
                samples=args.samples, roots_per_fight=args.roots_per_fight,
                query_probability=args.query_probability, macro_checkpoint=args.macro_checkpoint) for i in range(args.runs)]
            for future in as_completed(futures):
                results.append(future.result())
                status = {"stage": "collecting", "total": args.runs, **summary(results),
                          "seconds": time.perf_counter() - started}
                save_json(output / "status.json", status)
                print(json.dumps({k: status[k] for k in ("completed", "total", "decisions", "fights", "max_floor", "act1_clears", "search_errors")}), flush=True)
        save_json(output / "collection.json", results)
        if status["run_errors"]:
            raise RuntimeError("Incomplete/error runs quarantined; inspect coverage before fitting")
        if not args.collect_only:
            from sts2rl.micro import fit_micro, load_micro
            save_json(output / "status.json", {**status, "stage": "training"})
            fit_micro(sorted(output.glob("run-*/teacher.jsonl")), output / "model", epochs=args.epochs, device=args.device)
            if args.evaluate:
                save_json(output / "status.json", {**status, "stage": "evaluating"})
                policies = {"heuristic": None, "micro": load_micro(output / "model/best.pt", device=args.device)}
                for name, policy in policies.items():
                    evaluation = [run_act1(ROOT, output / ("evaluation-" + name), i,
                        prefix=args.prefix + "EVAL", teacher=False, micro_policy=policy,
                        macro_checkpoint=args.macro_checkpoint) for i in range(args.evaluate)]
                    save_json(output / (name + "-evaluation.json"), {"summary": summary(evaluation), "runs": evaluation})
                    if any(r["status"] != "complete" for r in evaluation):
                        raise RuntimeError("Incomplete live evaluation; engine errors are not defeats")
        save_json(output / "status.json", {**status, "stage": "complete", "seconds": time.perf_counter() - started})
    except BaseException as exc:
        save_json(output / "status.json", {"stage": "failed", **summary(results), "error": f"{type(exc).__name__}: {exc}"})
        raise


if __name__ == "__main__":
    main()
