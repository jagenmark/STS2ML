"""Bounded replay collection and GPU training, with persistent local status.

Run from the repository root with its installed Python environment. Re-running
with a new output directory reuses downloaded journals. This is offline
imitation learning, not autonomous gameplay or checkpoint-resumed training.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import traceback

from sts2rl.cli import main as cli
from sts2rl.data import audit_records, grouped_split, load_records, write_records
from sts2rl.target import ASCENSION, CHARACTER, GAME_VERSION
from sts2rl.training import TrainConfig, train


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--pages", type=int, default=10)
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--cached-only", action="store_true",
                        help="train once on retained downloads without network requests")
    parser.add_argument("--page-size", type=int, default=50)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--device", default="cuda:0")
    args = parser.parse_args()
    if not 1 <= args.pages <= 100 or not 1 <= args.page_size <= 100 or args.epochs < 1:
        parser.error("pages/page-size must be 1..100 and epochs must be positive")
    if not 1 <= args.start_page <= args.pages:
        parser.error("start-page must be between 1 and pages")
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "status.json").exists():
        parser.error("choose a new output directory; raw downloads will still be reused")
    raw = Path("data") / GAME_VERSION / f"{CHARACTER.lower()}-a{ASCENSION}" / "raw"
    state = {
        "pid": os.getpid(), "started_at": datetime.now(timezone.utc).isoformat(),
        "target": {"game_version": GAME_VERSION, "character": CHARACTER, "ascension": ASCENSION},
        "config": vars(args), "output": str(output), "completed_experiments": [],
    }

    def status(stage: str, **details) -> None:
        state.update(details, stage=stage, updated_at=datetime.now(timezone.utc).isoformat())
        write_json(output / "status.json", state)
        print(f"[{state['updated_at']}] {stage}: {details}", flush=True)

    def stopped() -> bool:
        if (output / "STOP").exists():
            status("stopped", reason="STOP file requested a stop between stages")
            return True
        return False

    try:
        status("starting")
        initial_trained = False
        pages = [None] if args.cached_only else range(args.start_page, args.pages + 1)
        for page in pages:
            if stopped():
                return 0
            if not args.cached_only:
                status("collecting", page=page, pages=args.pages)
                command = ["fetch-replays", "--limit", str(args.page_size), "--page", str(page)]
                if cli(command) != 0:
                    raise RuntimeError(f"replay collection failed on page {page}; files retained")
            if stopped():
                return 0
            last_page = True
            if not args.cached_only:
                manifest = json.loads((raw / f"downloads-page-{page}.json").read_text())
                last_page = page == args.pages or not manifest["listing"].get("runs")
            status("importing", page=page)
            imported = output / "imported.jsonl"
            if cli(["import-replay", str(raw), "--output", str(imported)]) != 0:
                if last_page:
                    raise RuntimeError("no accepted replay decisions; inspect the import report")
                continue
            rows = [
                row for row in load_records(imported)
                if row["game_version"] == GAME_VERSION
                and row["observation"]["character"] == CHARACTER
                and row["observation"]["ascension"] == ASCENSION
            ]
            audit = audit_records(rows)
            partitions, split = grouped_split(rows)
            outcome_counts = Counter(
                {row["run_id"]: row["outcome"] for row in partitions["train"]
                 if row.get("outcome") is not None}.values()
            )
            audit["train_outcomes_by_run"] = {str(k): v for k, v in outcome_counts.items()}
            audit["split_group_counts"] = split["group_counts"]
            write_json(output / "audit.json", audit)
            trainable = all(
                any(row.get("chosen_action_id") is not None for row in part)
                for part in partitions.values()
            )
            status("audited", page=page, accepted_runs=audit["runs"],
                   accepted_decisions=len(rows), split_groups=split["group_counts"])
            if trainable and (not initial_trained or last_page):
                experiment = output / ("final" if last_page else "initial")
                write_records(experiment / "choices.jsonl", rows)
                # A one-class outcome sample cannot learn a useful win predictor.
                value_weight = 0.5 if len(outcome_counts) == 2 else 0.0
                status("training", experiment=str(experiment), value_weight=value_weight)
                report = train(rows, experiment, TrainConfig(
                    epochs=args.epochs, device=args.device, threads=2, value_weight=value_weight,
                ))
                state["completed_experiments"].append({
                    "path": str(experiment), "runs": audit["runs"], "decisions": len(rows),
                    "best_epoch": report["best_epoch"],
                })
                initial_trained = True
                status("trained", experiment=str(experiment))
            if last_page:
                if not trainable:
                    raise RuntimeError("insufficient independent runs for all three partitions")
                break
        status("complete")
        return 0
    except KeyboardInterrupt:
        status("stopped", reason="interrupted")
        return 130
    except Exception as error:
        status("failed", error=f"{type(error).__name__}: {error}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
