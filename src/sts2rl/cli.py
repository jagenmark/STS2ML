"""Small, scriptable entry points for the first offline research milestone."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import re
import sys
import time

from .data import audit_records, deduplicate_records, load_records, validate_dataset, write_records
from .target import ASCENSION, CHARACTER, GAME_VERSION


def _print(value: object) -> None:
    print(json.dumps(value, indent=2, allow_nan=False))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sts2rl", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="read game fingerprints and check the Python device")
    doctor.add_argument("--game-root")
    doctor.add_argument("--device", default="cpu")
    doctor.add_argument("--skip-torch", action="store_true")
    doctor.add_argument("--output", help="save the JSON report for desktop handoff")
    demo = commands.add_parser("demo", help="run a synthetic end-to-end learning check")
    demo.add_argument("--output", default="artifacts/demo")
    demo.add_argument("--runs", type=int, default=96)
    demo.add_argument("--epochs", type=int, default=8)
    audit = commands.add_parser("audit", help="validate canonical JSONL decisions")
    audit.add_argument("data")
    imp = commands.add_parser(
        "import-replay", help="import Spire Codex journals as partial-state card choices"
    )
    imp.add_argument("inputs", nargs="+")
    imp.add_argument("--output", required=True)
    imp.add_argument("--report")
    imp.add_argument(
        "--strict-timing",
        action="store_true",
        help="exclude offers with state changes before resolution",
    )
    fetch = commands.add_parser(
        "fetch-replays", help="download one bounded page of public replay journals"
    )
    fetch.add_argument("--character", default=CHARACTER)
    fetch.add_argument("--ascension", type=int, default=ASCENSION)
    fetch.add_argument("--game-version", default=GAME_VERSION)
    fetch.add_argument("--limit", type=int, default=20)
    fetch.add_argument("--page", type=int, default=1)
    fetch.add_argument("--output", help="defaults to data/<patch>/<character>-a<ascension>/raw")
    inspect = commands.add_parser("inspect-model", help="measure model size without training")
    inspect.add_argument("--vocab-size", type=int, default=1024)
    train = commands.add_parser(
        "train", help="train imitation/outcome heads with grouped held-out splits"
    )
    train.add_argument("data")
    train.add_argument("--output", default="artifacts/train")
    train.add_argument("--character", default=CHARACTER)
    train.add_argument("--ascension", type=int, default=ASCENSION)
    train.add_argument("--game-version", default=GAME_VERSION)
    train.add_argument("--epochs", type=int, default=10)
    train.add_argument("--batch-size", type=int, default=32)
    train.add_argument("--learning-rate", type=float, default=3e-4)
    train.add_argument("--value-weight", type=float, default=0.5)
    train.add_argument("--seed", type=int, default=42)
    train.add_argument("--d-model", type=int, default=128)
    train.add_argument("--n-layers", type=int, default=3)
    train.add_argument("--threads", type=int, default=2)
    train.add_argument("--device", default="cpu")
    infer = commands.add_parser("predict", help="rank candidates in one canonical JSON decision")
    infer.add_argument("checkpoint")
    infer.add_argument("decision")
    infer.add_argument("--device", default="cpu")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _run(args)
    except (ValueError, OSError, RuntimeError) as error:
        print(f"sts2rl: {error}", file=sys.stderr)
        return 2


def _run(args: argparse.Namespace) -> int:
    if args.command == "doctor":
        from .diagnostics import inspect_environment

        report = inspect_environment(
            args.game_root, device=args.device, check_torch=not args.skip_torch
        )
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        _print(report)
        if (
            report["runtime"]["smoke_test"]["status"] == "failed"
            or report["game"]["status"] == "invalid"
            or (
                report["game"]["status"] == "not_found"
                and report["game"].get("path_source", "discovered") != "discovered"
            )
        ):
            return 2
    elif args.command == "audit":
        rows = load_records(args.data)
        validate_dataset(rows)
        _print(audit_records(rows))
    elif args.command == "inspect-model":
        from .model import MacroPolicyValue, ModelConfig

        config = ModelConfig(args.vocab_size)
        model = MacroPolicyValue(config)
        _print(
            {
                "config": asdict(config),
                "parameters": model.parameter_count,
                "fp32_weight_bytes": model.parameter_count * 4,
            }
        )
    elif args.command == "import-replay":
        from .adapters.spire_codex import import_replay

        rows, reports = [], []
        # Expand directories ourselves so the documented command also works in PowerShell.
        inputs = []
        for value in args.inputs:
            path = Path(value)
            inputs.extend(sorted(path.glob("*.jsonl*")) if path.is_dir() else [path])
        for path in inputs:
            imported, report = import_replay(path, strict_timing=args.strict_timing)
            rows.extend(imported)
            reports.append({"path": str(path), **report})
        # Validate the complete dataset before publishing any output bytes.
        if rows:
            rows = deduplicate_records(rows)
            validate_dataset(rows)
            write_records(args.output, rows)
        summary = {"files": len(reports), "decisions": len(rows), "reports": reports}
        report_path = Path(args.report or str(args.output) + ".import.json")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        _print({"files": len(reports), "decisions": len(rows), "report": str(report_path)})
        if not rows:
            print(
                "No accepted choices; inspect the exclusion report. No new training file was written.",
                file=sys.stderr,
            )
            return 2
    elif args.command == "fetch-replays":
        from .adapters.spire_codex import download_replay, list_replays

        listing = list_replays(
            character=args.character.upper(),
            ascension=args.ascension,
            game_version=args.game_version,
            limit=args.limit,
            page=args.page,
        )
        if any(row.get("build_id") != args.game_version for row in listing.get("runs", [])):
            raise ValueError("replay listing returned a different game version; no files downloaded")
        if not args.output and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", args.game_version):
            raise ValueError("use an explicit --output for a game version containing path characters")
        folder = Path(args.output) if args.output else (
            Path("data") / args.game_version / f"{args.character.lower()}-a{args.ascension}" / "raw"
        )
        folder.mkdir(parents=True, exist_ok=True)
        downloads = []
        for row in listing.get("runs", []):
            run_id = row["run_hash"]
            path = folder / f"{run_id}.jsonl.gz"
            if path.exists():
                downloads.append({"run_id": run_id, "status": "existing", "path": str(path)})
                continue
            downloads.append({"run_id": run_id, **download_replay(run_id, path)})
            # Respect the general anonymous 15/minute tier as well as route caps.
            time.sleep(4.1)
        (folder / f"downloads-page-{args.page}.json").write_text(
            json.dumps(
                {
                    "character": args.character.upper(),
                    "ascension": args.ascension,
                    "game_version": args.game_version,
                    "page": args.page,
                    "listing": listing,
                    "downloads": downloads,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        _print(
            {
                "listed": len(listing.get("runs", [])),
                "downloads": len(downloads),
                "directory": str(folder),
            }
        )
    elif args.command == "demo":
        from .demo import make_demo_records
        from .training import TrainConfig, predict, train

        folder = Path(args.output)
        rows = make_demo_records(args.runs)
        write_records(folder / "synthetic.jsonl", rows)
        report = train(rows, folder, TrainConfig(epochs=args.epochs, d_model=64, n_layers=2))
        query = {**rows[0], "chosen_action_id": None, "outcome": None}
        (folder / "decision.json").write_text(json.dumps(query, indent=2) + "\n", encoding="utf-8")
        _print(
            {
                "data": "SYNTHETIC; not game-playing results",
                "parameters": report["parameter_count"],
                "test": report["test"],
                "prediction": predict(folder / "best.pt", query),
                "report": str(folder / "report.json"),
            }
        )
    elif args.command == "train":
        from .training import TrainConfig, train

        rows = load_records(args.data)
        # Validate before filtering: a contradictory run cannot be repaired by
        # hiding its other patch/character/ascension behind a target filter.
        validate_dataset(rows)
        rows = [
            r
            for r in rows
            if (args.character is None or r["observation"]["character"] == args.character.upper())
            and (args.ascension is None or r["observation"]["ascension"] == args.ascension)
            and (args.game_version is None or r["game_version"] == args.game_version)
        ]
        if not rows:
            raise ValueError("no records match the requested character, ascension and game version")
        config = TrainConfig(
            epochs=args.epochs,
            batch_size=args.batch_size,
            learning_rate=args.learning_rate,
            value_weight=args.value_weight,
            seed=args.seed,
            d_model=args.d_model,
            n_layers=args.n_layers,
            device=args.device,
            threads=args.threads,
        )
        report = train(rows, args.output, config)
        _print(
            {
                "parameters": report["parameter_count"],
                "split": report["split"]["labelled_counts"],
                "best_epoch": report["best_epoch"],
                "test": report["test"],
                "report": str(Path(args.output) / "report.json"),
            }
        )
    elif args.command == "predict":
        from .training import predict

        record = json.loads(Path(args.decision).read_text(encoding="utf-8"))
        _print(predict(args.checkpoint, record, device=args.device))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
