"""Run the five frozen arms on the SHA-locked CSV6DEV cohort."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from sts2rl.run_bundle import load_bundle
from sts2rl.run_evaluation import play_episode
from sts2rl.run_policy import RunWeights

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "releases/silent-a10-v2-tactics"
POLICY = RELEASE / "challenger/policy.json"
LOCK = ROOT / "docs/combat-search-v2/v62-dev-lock.json"
ARMS = ("v5", "heuristic", "power", "accelerant_only", "scaling_powers_4")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def configure(output, arm):
    role, settings = load_bundle(POLICY)
    if arm != "v5":
        config = json.loads(settings["combat_search_v2_config"].read_bytes())
        config.update(v61_boss_safe=True, v61_act2_hallways_act3=True)
        if arm != "heuristic":
            config["power_leaf_v62"] = True
        settings.pop("combat_value_v2")
        settings["combat_search_v2_config"] = output / f"{arm}-search.json"
        settings["combat_search_v2_config"].write_bytes(json.dumps(config, sort_keys=True).encode())
    if arm in ("accelerant_only", "scaling_powers_4"):
        strategy = json.loads(settings["strategy_model"].read_bytes())
        strategy["power_draft"] = arm
        settings["strategy_model"] = output / f"{arm}-draft.json"
        settings["strategy_model"].write_bytes(json.dumps(strategy, sort_keys=True).encode())
    return role, settings


def episode(job):
    output, host, arm, role, settings, weights, index, seed, mode = job
    with TemporaryDirectory(dir=output) as tmp:
        row = play_episode((ROOT, host, Path(tmp) / "run", seed, index, role, weights, None,
                            {**settings, "seeded_acts": mode == "seeded", "compact_combat_summary": True,
                             "audit_compact": True, "audit_frozen_right_hand": arm == "v5"}))
    if row["status"] != "complete" or row.get("abandoned") or row["ascension"] != 10:
        raise ValueError((arm, seed, row))
    keys = ("seed", "index", "act_list", "status", "ascension", "steps", "act", "floor", "a1_clear",
            "a2_clear", "boss_fights", "win", "native", "mismatches")
    return dict(arm=arm, **{k: row[k] for k in keys})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=ARMS, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, choices=(12,), default=12)
    args = parser.parse_args()
    host = Path(os.environ["CSV2DEV_HOST"])
    game = ROOT / "artifacts/upstreams/sts2-cli/lib/sts2.dll"
    pins = {host: "7408d040c28416331279a84e299b52ff35086d80b4cb9711aefd0f91168d8f20",
            game: "14b57dbaee1b58cb919625a662831054fd714b3b75b13b7449eac0e95b98a3e4",
            POLICY: "a686db12c8b217bd476ea5c8e60cf6f486b060665536ef9354e8f09c21c81fcb",
            LOCK: "3f166462911e3a53b863cf48bbcae7ee5fae8796abde68bc44ee4993183b4c04"}
    for path, expected in pins.items():
        if sha(path) != expected:
            raise ValueError(f"Checksum mismatch for {path}")
    if any(os.environ.get(k) != "1" for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS")) or os.getenv("DOTNET_STARTUP_HOOKS"):
        raise ValueError("Expected pinned native host and single-threaded BLAS/OpenMP")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    rows = json.loads(LOCK.read_bytes())
    role, settings = configure(output, args.arm)
    weights = asdict(RunWeights.load(settings["weights"]))
    jobs = [(output, host, args.arm, role, settings, weights, *row) for row in rows]
    manifest = dict(arm=args.arm, git=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                    host=sha(host), game=sha(game), policy=sha(POLICY), lock=sha(LOCK), workers=args.workers,
                    model_files={k: sha(v) for k, v in settings.items() if isinstance(v, Path)})
    with (output / (args.arm + ".jsonl.gz")).open("xb") as file, gzip.GzipFile(
            filename="", mode="wb", fileobj=file, mtime=0) as archive, ProcessPoolExecutor(args.workers) as pool:
        (output / (args.arm + "-manifest.json")).write_bytes(json.dumps(manifest, indent=2).encode())
        for i, future in enumerate(as_completed([pool.submit(episode, job) for job in jobs]), 1):
            archive.write((json.dumps(future.result(), separators=(",", ":")) + "\n").encode())
            archive.flush()
            if i % 32 == 0:
                print(args.arm, i, flush=True)


if __name__ == "__main__":
    main()
