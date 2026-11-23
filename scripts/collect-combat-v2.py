"""Collect the locked natural champion cohort for combat search v2."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from sts2rl.combat_search_v2.recording import observer_path
from sts2rl.combat_search_v2.seed_registry import (
    load_confirmation_registry, load_phase3_registry, load_registry, registry_sha256,
)
from sts2rl.run_bundle import load_bundle
from sts2rl.run_evaluation import play_episode
from sts2rl.run_policy import RunWeights

ROOT = Path(__file__).resolve().parents[1]
CHAMPION = ROOT / "releases/silent-a10-v2-tactics/challenger/policy.json"
PINNED_HOST_SHA256 = "7408d040c28416331279a84e299b52ff35086d80b4cb9711aefd0f91168d8f20"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def attempt_folders(data, lobby):
    return sorted((data / lobby.split / lobby.seed).glob("attempt-*"))


def complete_attempt(data, lobby):
    for folder in attempt_folders(data, lobby):
        result = folder / "result.json"
        if result.exists():
            row = json.loads(result.read_bytes())
            identity = row["seed"], row["index"], row["act_list"]
            if identity != (lobby.seed, lobby.index, lobby.mode):
                raise ValueError(f"Unexpected lobby identity in {result}")
            if row["status"] == "complete" and (folder / "combat-v2-census.json").is_file() and (
                    folder / "combat-v2-recording.json.gz").is_file():
                return folder
    return None


def collection_task(data, lobby, host, role, settings, weights):
    folder = data / lobby.split / lobby.seed / f"attempt-{len(attempt_folders(data, lobby)):02}"
    return (ROOT, host, folder, lobby.seed, lobby.index, role, weights, None,
            {**settings, "seeded_acts": lobby.mode == "seeded", "record_combat_v2": True})


def run_collection(data, rows, host, role, settings, weights, workers):
    pending = [lobby for lobby in rows if complete_attempt(data, lobby) is None]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for _ in range(3):
            if not pending:
                break
            jobs = {pool.submit(play_episode, collection_task(data, lobby, host, role, settings, weights)): lobby
                    for lobby in pending}
            pending = []
            for i, job in enumerate(as_completed(jobs), 1):
                row = job.result()
                if row["status"] != "complete":
                    pending.append(jobs[job])
                    print(jobs[job].seed, row.get("error", row["status"]), flush=True)
                if i % 32 == 0 or i == len(jobs):
                    print(f"{i}/{len(jobs)} completed in this pass, {len(pending)} retries pending", flush=True)
    return pending


def coverage_census(data, rows):
    counts = defaultdict(Counter)
    for lobby in rows:
        folder = complete_attempt(data, lobby)
        census = json.loads((folder / "combat-v2-census.json").read_bytes())
        for act, reasons in census.items():
            counts[act].update(reasons)
    return {act: dict(sorted(counts[act].items(), key=lambda entry: (-entry[1], entry[0])))
            for act in sorted(counts)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--observer", type=Path)
    cohorts = parser.add_mutually_exclusive_group()
    cohorts.add_argument("--phase3", choices=("fit", "test", "held"))
    cohorts.add_argument("--fit-only", action="store_true", help="Rebuild train and development data with the test split closed")
    cohorts.add_argument("--confirmation-only", action="store_true", help="Collect the separately locked test-only lobbies")
    args = parser.parse_args()
    host = args.host.resolve(strict=True)
    observer = observer_path(ROOT, args.observer)
    if sha(host) != PINNED_HOST_SHA256:
        parser.error("The collection requires the pinned v0.111.0 headless host")
    if args.phase3:
        registry = load_phase3_registry()
        splits = ("train", "dev") if args.phase3 == "fit" else (args.phase3,)
        rows = [row for row in registry if row.split in splits]
        if sha(CHAMPION) != "8636337a6082264bffffe9a79b50528bdf30ed9096b74ff33fd20a8e844fa51b":
            parser.error("Phase 3 requires all_v2_p1_v4")
    else:
        registry = load_confirmation_registry() if args.confirmation_only else load_registry()
        rows = [lobby for lobby in registry if not args.fit_only or lobby.split != "test"]
    role, settings = load_bundle(CHAMPION)
    settings["combat_v2_observer"] = str(observer)
    weights = asdict(RunWeights.load(settings["weights"]))
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = {"version": 1, "registry_sha256": registry_sha256(registry), "count": len(rows), "actor": role,
                **({"phase3": args.phase3} if args.phase3 else {}),
                **({"fit_only": True} if args.fit_only else {}),
                **({"confirmation_only": True} if args.confirmation_only else {}),
                "champion_sha256": sha(CHAMPION), "host_sha256": sha(host), "observer_sha256": sha(observer),
                "game_sha256": sha(ROOT / "artifacts/upstreams/sts2-cli/lib/sts2.dll"), "workers": args.workers,
                "feature_source_sha256": sha(ROOT / "src/sts2rl/combat_search_v2/features.py"),
                "recorder_source_sha256": sha(ROOT / "src/sts2rl/combat_search_v2/recording.py")}
    manifest_path = args.output / "collection.json"
    if manifest_path.exists() and json.loads(manifest_path.read_bytes()) != manifest:
        raise SystemExit("Existing collection manifest differs")
    save(manifest_path, manifest)
    pending = run_collection(args.output, rows, host, role, settings, weights, args.workers)
    if pending:
        raise SystemExit(f"Collection incomplete: {len(pending)} lobbies failed")
    save(args.output / "coverage-census.json", {"runs": len(rows), "by_act": coverage_census(args.output, rows)})


if __name__ == "__main__":
    main()
