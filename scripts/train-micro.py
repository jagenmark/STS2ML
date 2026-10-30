"""Collect native Act 1 Monte Carlo labels, then fit/evaluate a micro policy.

One isolated game process and one replay/search process per collection worker.
Create OUTPUT/STOP for a clean stop at the next decision boundary.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import subprocess
import time

from sts2rl.native import NativeSession, SAMPLER, digest, legal_actions
from sts2rl.teacher import combat_result, heuristic, teach_root

ROOT = Path(__file__).resolve().parents[1]


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(path)


def collect_episode(index, output, samples, prefix, exploration):
    seed = f"{prefix}{index:06d}"
    group = digest(seed)
    hp = (15, 25, 40, 70)[index % 4]
    folder = output / "episodes" / f"{index:06d}"
    rng = random.Random(index + 17031)
    started = time.perf_counter()
    records = []
    result = {"index": index, "group": group, "initial_hp": hp, "status": "error"}
    try:
        with NativeSession(ROOT, folder / "game") as game, NativeSession(ROOT, folder / "search") as search:
            state = game.reset(seed, encounter="SHRINKER_BEETLE_WEAK", hp=hp)
            for decision in range(256):
                end = combat_result(state)
                if end is not None:
                    result.update(status="complete", **end)
                    break
                if (output / "STOP").exists():
                    result["status"] = "stopped"
                    break
                actions = legal_actions(state)
                if len(actions) == 1:
                    action = actions[0]
                else:
                    record = teach_root(search, game.fork(), state, samples=samples,
                                        seed=index * 100000 + decision)
                    record.update(group=group, decision_index=decision, initial_hp=hp)
                    records.append(record)
                    action = next(a for a in actions if a.id == record["chosen_action_id"])
                    if rng.random() < exploration:
                        action = rng.choice(actions)
                state = game.step(action)
            else:
                raise RuntimeError("Collection episode truncated")
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    result.update(decisions=len(records), seconds=time.perf_counter() - started,
                  branches=sum(r["branches"] for r in records))
    # Failed/stopped episodes are retained for diagnostics, never silently fitted.
    folder.mkdir(parents=True, exist_ok=True)
    if result["status"] == "complete":
        (folder / "teacher.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    save(folder / "result.json", result)
    return result


def evaluate_policy(output, policy=None, *, episodes=100, prefix="MICROEVAL001"):
    results = []
    with NativeSession(ROOT, output / "native") as game:
        for i in range(episodes):
            hp = (15, 25, 40, 70)[i % 4]
            state = game.reset(f"{prefix}{i:06d}", encounter="SHRINKER_BEETLE_WEAK", hp=hp)
            for step in range(256):
                end = combat_result(state)
                if end is not None:
                    results.append({"index": i, "initial_hp": hp, **end, "steps": step})
                    break
                action = heuristic(state) if policy is None else policy(state)
                state = game.step(action)
            else:
                raise RuntimeError("Evaluation truncated")
    report = {"episodes": episodes, "wins": sum(r["won"] for r in results),
              "mean_hp_loss": sum(r["initial_hp"] - r["hp"] for r in results) / episodes,
              "results": results, "scope": SAMPLER}
    save(output / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--episodes", type=int, default=64)
    parser.add_argument("--samples", type=int, default=8)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--prefix", default="MICROTRAIN001")
    parser.add_argument("--exploration", type=float, default=0.1)
    parser.add_argument("--collect-only", action="store_true")
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--evaluate", type=int, default=100)
    args = parser.parse_args()
    if args.episodes < 1 or args.samples < 2 or args.workers < 1 or not 0 <= args.exploration <= 1:
        parser.error("Invalid experiment budget")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "config.json").exists():
        parser.error("Use a fresh output folder; experiments are immutable")
    save(output / "config.json", {**vars(args), "output": str(output), "sampler": SAMPLER,
        "started": datetime.now(timezone.utc).isoformat(),
        "git_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in (ROOT / "src/sts2rl").glob("*.py")}})
    results = []
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(collect_episode, i, output, args.samples, args.prefix,
                                   args.exploration) for i in range(args.episodes)]
        for future in as_completed(futures):
            results.append(future.result())
            summary = {"stage": "collecting", "completed": len(results), "total": args.episodes,
                       "decisions": sum(r["decisions"] for r in results),
                       "errors": [r for r in results if r["status"] != "complete"],
                       "elapsed_seconds": time.perf_counter() - started}
            save(output / "status.json", summary)
            print(json.dumps(summary), flush=True)
    save(output / "collection.json", sorted(results, key=lambda r: r["index"]))
    if any(r["status"] != "complete" for r in results):
        save(output / "status.json", {**summary, "stage": "collection_incomplete"})
        raise SystemExit("Collection incomplete; no final fit")
    if not args.collect_only:
        from sts2rl.micro import fit_micro, load_micro
        save(output / "status.json", {**summary, "stage": "training"})
        fit_micro(sorted(output.glob("episodes/*/teacher.jsonl")), output / "model",
                  epochs=args.epochs, device=args.device)
        if args.evaluate:
            save(output / "status.json", {**summary, "stage": "evaluating"})
            evaluate_policy(output / "heuristic-evaluation", episodes=args.evaluate)
            evaluate_policy(output / "micro-evaluation",
                            load_micro(output / "model/best.pt", device=args.device), episodes=args.evaluate)
    save(output / "status.json", {**summary, "stage": "complete",
                                  "elapsed_seconds": time.perf_counter() - started})


if __name__ == "__main__":
    main()
