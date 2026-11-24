"""Paired CSV11DEV triples on the pinned host, with per-card native evidence."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess

from sts2rl.run_bundle import freeze_bundle, load_bundle
from v64 import ROOT, episode

ARMS = ("control", "arm1", "arm2")
BASE = "8c27ce5ddf5348f88b1cedb3c3cd5b24bd5c40b1"


def cohort():
    return [(i, f"CSV11DEV_{mode.upper()}_{i:04d}", mode) for i in range(96) for mode in ("default", "seeded")]


def build(out):
    profiles = ("trap_cleanup_v65", "trap_cleanup_v65", "unified_draft_v65")
    builder = runpy.run_path(str(ROOT / "scripts/build-batch1-challengers.py"))["build_batch1_bundle"]
    bundles = {}
    for arm, profile in zip(ARMS, profiles, strict=True):
        dest = out / arm
        ref = builder(ROOT / "releases/silent-a10-mecha-knight/challenger/policy.json", dest, profile=profile)
        if arm != "control":
            role, opts = load_bundle(ref)
            config = json.loads(opts["combat_search_v2_config"].read_bytes())
            config["silent_cards_v66"] = True
            path = dest / "v66.json"
            path.write_text(json.dumps(config, indent=2) + "\n", newline="\n")
            opts["combat_search_v2_config"] = path
            ref = freeze_bundle({"args": {**opts, "roles": [role]}}, dest / "v66")
        bundles[arm] = ref
    return bundles


def triple(out, bundles, row):
    shift = (2 * row[0] + int(row[2] == "seeded")) % 3
    for arm in ARMS[shift:] + ARMS[:shift]:
        episode(out / arm, bundles[arm], row, card_counts=True)
    return row[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    assert all(os.environ[k] == "1" for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS"))
    assert not os.getenv("DOTNET_STARTUP_HOOKS")
    pins = runpy.run_path(str(ROOT / "scripts/verify-silent-v6.py"))
    for path, name in [(Path(os.environ["CSV2DEV_HOST"]), "HOST_SHA"),
                       (ROOT / "artifacts/upstreams/sts2-cli/lib/sts2.dll", "GAME_SHA")]:
        assert hashlib.sha256(path.read_bytes()).hexdigest() == pins[name]
    assert not subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT).strip()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    bundles = build(out)
    rows = cohort()
    manifest = dict(commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                    base=BASE, host=pins["HOST_SHA"], game=pins["GAME_SHA"], workers=12,
                    cohort=rows, bundles={arm: hashlib.sha256(p.read_bytes()).hexdigest() for arm, p in bundles.items()})
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    with ProcessPoolExecutor(12) as pool:
        jobs = [pool.submit(triple, out, bundles, row) for row in rows]
        for job in as_completed(jobs):
            print(job.result(), flush=True)


if __name__ == "__main__":
    main()
