"""2x2 paired CSV14DEV evaluation: (v6.7 vs PIMC+value_v68 combat) x (Control vs Human-ML draft)."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import gzip
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess

from report_v64 import paired, summarize
from sts2rl.human_ml_draft import DEFAULT_MODEL_PATH
from sts2rl.run_bundle import freeze_bundle, load_bundle
from v64 import ROOT, episode

ARMS = ("ctrl_v67", "ctrl_pimc", "ml_v67", "ml_pimc")


def cohort(pairs_per_mode: int = 64):
    return [
        (i, f"CSV14DEV_{mode.upper()}_{i:04d}", mode)
        for i in range(pairs_per_mode)
        for mode in ("default", "seeded")
    ]


def build(out: Path, arm: str) -> Path:
    builder = runpy.run_path(str(ROOT / "scripts/build-batch1-challengers.py"))["build_batch1_bundle"]
    base_policy = builder(
        ROOT / "releases/silent-a10-mecha-knight/challenger/policy.json",
        out / "base",
        profile="trap_cleanup_v65",
    )
    role, opts = load_bundle(base_policy)
    config = json.loads(opts["combat_search_v2_config"].read_bytes())
    config["silent_cards_v67"] = True
    if arm.endswith("_pimc"):
        config["draw_pimc_v68"] = True
        config["value_v68"] = True
        config["pimc_samples"] = 6
    cfg_path = out / f"{arm}_cfg.json"
    cfg_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8", newline="\n")
    opts["combat_search_v2_config"] = cfg_path

    if arm.startswith("ml_"):
        deck = json.loads(opts["deck_model"].read_bytes())
        deck["human_ml_draft_v68"] = True
        deck["human_ml_scope"] = ["card_reward", "bundle_select", "shop"]
        deck["human_ml_skip_bias"] = 0.0
        deck["human_ml_act_skip_bias"] = [0.0, 0.0, 0.0]
        deck["human_ml_shop_scale"] = 4.5
        deck_path = out / f"{arm}_deck.json"
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


def print_report(out: Path, rows, json_out: Path | None = None):
    records = {
        arm: [
            json.loads(gzip.decompress((out / arm / (seed + ".json.gz")).read_bytes()))
            for _, seed, _ in rows
        ]
        for arm in ARMS
    }
    sums = {arm: summarize(records[arm]) for arm in ARMS}
    print(f"\n=== CSV14DEV 2x2 PAIRED BENCHMARK (N = {len(rows)} lobbies per arm) ===\n")
    hdr = f"{'Metric':30s} | {'ctrl_v67':>11s} | {'ctrl_pimc':>11s} | {'ml_v67':>11s} | {'ml_pimc':>11s}"
    print(hdr)
    print("-" * len(hdr))

    def rline(label, fn):
        vals = [fn(sums[a]) for a in ARMS]
        print(f"{label:30s} | {vals[0]:>11s} | {vals[1]:>11s} | {vals[2]:>11s} | {vals[3]:>11s}")

    rline("Mean global floor", lambda s: f"{s['mean_floor']:.3f}")
    rline("Act 1 clears", lambda s: f"{s['a1_clears']}/{s['n']}")
    rline("Act 2 boss clears/entries", lambda s: f"{s['a2_clears']}/{s['a2_entries']}")
    rline("Act 3 boss entries", lambda s: f"{s['a3_entries']}")
    rline("Full wins", lambda s: f"{s['wins']}")
    rline("Matches / 100 combat dec", lambda s: f"{100 * s['native']['match'] / s['latency_n']:.2f}")
    rline("Unresolved / 100 dec", lambda s: f"{100 * s['native']['unresolved'] / s['latency_n']:.2f}")
    rline("Native mismatches", lambda s: f"{s['native'].get('mismatch', 0)}")
    rline("Latency p50 / p95 (ms)", lambda s: f"{s['p50_ms']:.1f}/{s['p95_ms']:.1f}")
    for boss in ("CRUSHER+ROCKET", "KNOWLEDGE_DEMON", "THE_INSATIABLE"):
        rline(
            f"Boss {boss}",
            lambda s, b=boss: f"{s['bosses'][b][0]}/{s['bosses'][b][1]}" if b in s["bosses"] else "0/0",
        )

    print("\n=== PAIRED FLOOR DELTAS ===")
    pairs = {}
    for label, a, b in (
        ("PIMC effect on Control (ctrl_pimc - ctrl_v67)", "ctrl_v67", "ctrl_pimc"),
        ("PIMC effect on Human-ML (ml_pimc - ml_v67)", "ml_v67", "ml_pimc"),
        ("Combined vs Baseline (ml_pimc - ctrl_v67)", "ctrl_v67", "ml_pimc"),
    ):
        p = paired(records[a], records[b])
        pairs[label] = p
        print(
            f"  {label:46s}: {p['delta']:+.3f} | CI95 [{p['ci95'][0]:+.3f}, {p['ci95'][1]:+.3f}] "
            f"| W/L/T {p['w']}/{p['l']}/{p['t']} | p={p['sign_p']:.4f}"
        )

    if json_out is not None:
        json_out.write_text(json.dumps({"summaries": sums, "paired": pairs}, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--pairs-per-mode", type=int, default=64)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--json-out", type=Path, default=None)
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
        cohort=rows,
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

    print_report(out, rows, args.json_out)


if __name__ == "__main__":
    main()
