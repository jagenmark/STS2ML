"""Run paired CSV13DEV lobbies: v6.7 A control vs v6.8 Human-ML Draft (reward-only and full)."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess

from sts2rl.human_ml_draft import DEFAULT_MODEL_PATH
from sts2rl.run_bundle import freeze_bundle, load_bundle
from v64 import ROOT, episode

BASE = "8883d9f514935a83e7f94d10fca88f7"
ARMS = ("control", "ml_reward", "ml_full")


def cohort(pairs_per_mode: int = 96):
    return [
        (i, f"CSV13DEV_{mode.upper()}_{i:04d}", mode)
        for i in range(pairs_per_mode)
        for mode in ("default", "seeded")
    ]


def check_names(rows):
    names = {seed for _, seed, _ in rows}
    assert len(names) == len(rows)
    reserved = ("FINAL768", "POOLED896", "VAL256", "SEEDED128", "TRUE_SEEDED", "REP512")
    assert not any(seed.startswith(reserved) for seed in names)
    doc = ROOT / "docs/combat-search-v2"
    for stem in (
        "csv7dev-lock",
        "csv9dev-lock",
        "csv10dev-lock",
        "v6-dev-lock",
        "v6-audit384-lock",
        "v62-dev-lock",
    ):
        assert not names.intersection(r[1] for r in json.loads((doc / (stem + ".json")).read_bytes()))
    from v66 import cohort as csv11
    from v67 import cohort as csv12

    assert not names.intersection(r[1] for r in csv11())
    assert not names.intersection(r[1] for r in csv12())
    return dict(namespace="CSV13DEV_", lobbies=len(rows), overlaps=0)


def build(out: Path, arm: str) -> Path:
    builder = runpy.run_path(str(ROOT / "scripts/build-batch1-challengers.py"))["build_batch1_bundle"]
    base_policy = builder(
        ROOT / "releases/silent-a10-mecha-knight/challenger/policy.json",
        out / "base",
        profile="trap_cleanup_v65",
    )
    role, opts = load_bundle(base_policy)
    # Enable v6.7 complete solo Silent combat search across all arms
    config = json.loads(opts["combat_search_v2_config"].read_bytes())
    config["silent_cards_v67"] = True
    cfg_path = out / "v67.json"
    cfg_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8", newline="\n")
    opts["combat_search_v2_config"] = cfg_path

    if arm in ("ml_reward", "ml_full"):
        deck = json.loads(opts["deck_model"].read_bytes())
        deck["human_ml_draft_v68"] = True
        deck["human_ml_scope"] = (
            ["card_reward", "bundle_select"]
            if arm == "ml_reward"
            else ["card_reward", "bundle_select", "shop"]
        )
        deck["human_ml_skip_bias"] = 0.0
        deck["human_ml_act_skip_bias"] = [0.0, 0.0, 0.0]
        deck["human_ml_shop_scale"] = 4.5
        deck_path = out / "deck_model_v68.json"
        deck_path.write_text(json.dumps(deck, indent=2) + "\n", encoding="utf-8", newline="\n")
        opts["deck_model"] = deck_path
        opts["human_ml_draft_model"] = DEFAULT_MODEL_PATH

    return freeze_bundle({"args": {**opts, "roles": [role]}}, out / arm)


def lobby(out: Path, bundles: dict[str, Path], row):
    arms = list(bundles)
    shift = (2 * row[0] + int(row[2] == "seeded")) % len(arms)
    for arm in arms[shift:] + arms[:shift]:
        episode(out / arm, bundles[arm], row, card_counts=True)
    return row[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--pairs-per-mode", type=int, default=96)
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()

    pins = runpy.run_path(str(ROOT / "scripts/verify-silent-v6.py"))
    assert all(os.environ.get(k) == "1" for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS"))
    assert not os.getenv("DOTNET_STARTUP_HOOKS")
    for path, name in [
        (Path(os.environ["CSV2DEV_HOST"]), "HOST_SHA"),
        (ROOT / "artifacts/upstreams/sts2-cli/lib/sts2.dll", "GAME_SHA"),
    ]:
        assert hashlib.sha256(path.read_bytes()).hexdigest() == pins[name], name

    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    bundles = {arm: build(out / "bundles" / arm, arm) for arm in ARMS}
    for arm in ARMS:
        (out / arm).mkdir(parents=True, exist_ok=True)
    rows = cohort(args.pairs_per_mode)
    manifest = dict(
        commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        host=pins["HOST_SHA"],
        game=pins["GAME_SHA"],
        model_sha256=hashlib.sha256(DEFAULT_MODEL_PATH.read_bytes()).hexdigest(),
        workers=args.workers,
        cohort=rows,
        name_check=check_names(rows),
        bundles={arm: hashlib.sha256(p.read_bytes()).hexdigest() for arm, p in bundles.items()},
    )
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    done = 0
    total = len(rows)
    with ProcessPoolExecutor(args.workers) as pool:
        jobs = [pool.submit(lobby, out, bundles, row) for row in rows]
        for job in as_completed(jobs):
            done += 1
            seed = job.result()
            if done % 16 == 0 or done == total:
                print(f"[{done}/{total}] {seed}", flush=True)


if __name__ == "__main__":
    main()
