"""Run paired CSV12DEV A lobbies and stress Arm B on the first 64 paired seeds."""
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

BASE = "a584f1b79b944ce2d46ee32c0cd378e54b380ef6"
ARMS = ("control", "treatment", "stress")


def cohort():
    return [(i, f"CSV12DEV_{mode.upper()}_{i:04d}", mode) for i in range(192) for mode in ("default", "seeded")]


def build(out, arm):
    builder = runpy.run_path(str(ROOT / "scripts/build-batch1-challengers.py"))["build_batch1_bundle"]
    profile = "unified_draft_v65" if arm == "stress" else "trap_cleanup_v65"
    path = builder(ROOT / "releases/silent-a10-mecha-knight/challenger/policy.json", out, profile=profile)
    if arm == "control":
        return path
    role, opts = load_bundle(path)
    config = json.loads(opts["combat_search_v2_config"].read_bytes())
    config["silent_cards_v67"] = True
    path = out / "v67.json"
    path.write_text(json.dumps(config, indent=2) + "\n", newline="\n")
    opts["combat_search_v2_config"] = path
    return freeze_bundle({"args": {**opts, "roles": [role]}}, out / "v67")


def lobby(out, bundles, row):
    arms = list(bundles)
    shift = (2 * row[0] + int(row[2] == "seeded")) % len(arms)
    for arm in arms[shift:] + arms[:shift]:
        if arm != "stress" or row[0] < 32:
            episode(out / arm, bundles[arm], row, card_counts=True)
    return row[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    pins = runpy.run_path(str(ROOT / "scripts/verify-silent-v6.py"))
    assert all(os.environ[k] == "1" for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS"))
    assert not os.getenv("DOTNET_STARTUP_HOOKS")
    for path, name in [(Path(os.environ["CSV2DEV_HOST"]), "HOST_SHA"),
                       (ROOT / "artifacts/upstreams/sts2-cli/lib/sts2.dll", "GAME_SHA")]:
        assert hashlib.sha256(path.read_bytes()).hexdigest() == pins[name]
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    bundles = {arm: build(out / arm, arm) for arm in ARMS}
    rows = cohort()
    manifest = dict(commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                    base=BASE, host=pins["HOST_SHA"], game=pins["GAME_SHA"], workers=12,
                    openblas_threads=1, omp_threads=1, cohort=rows, stress=rows[:64],
                    bundles={arm: hashlib.sha256(p.read_bytes()).hexdigest() for arm, p in bundles.items()})
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    with ProcessPoolExecutor(12) as pool:
        jobs = [pool.submit(lobby, out, bundles, row) for row in rows]
        for job in as_completed(jobs):
            print(job.result(), flush=True)


if __name__ == "__main__":
    main()
