"""Blind CSV22DEV (N=256 paired lobbies): test Kaiser Crab value_v68 fallback + PIMC on Schema 5."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import runpy
import time

from overnight_v68 import make_cohort, run_paired_panel
from overnight_v68_part2 import build_part2_bundle
from report_v64 import paired
from schema5_pipeline import SCHEMA5_MODEL_PATH
from sts2rl.run_bundle import freeze_bundle, load_bundle
from v64 import ROOT


def build_s5_variant(
    out: Path,
    name: str,
    *,
    use_pimc: bool = False,
    value_v68: bool = False,
    win_weight: float = 25.0,
) -> Path:
    builder = runpy.run_path(str(ROOT / "scripts/build-batch1-challengers.py"))["build_batch1_bundle"]
    base_policy = builder(
        ROOT / "releases/silent-a10-mecha-knight/challenger/policy.json",
        out / f"{name}_base",
        profile="trap_cleanup_v65",
    )
    role, opts = load_bundle(base_policy)
    cfg = json.loads(opts["combat_search_v2_config"].read_bytes())
    cfg["silent_cards_v67"] = True
    cfg["value_win_weight"] = float(win_weight)
    if use_pimc:
        cfg["draw_pimc_v68"] = True
        cfg["pimc_samples"] = 6
    if value_v68:
        cfg["value_v68"] = True
    cfg_path = out / f"{name}_cfg.json"
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8", newline="\n")
    opts["combat_search_v2_config"] = cfg_path
    opts["combat_value_v2"] = SCHEMA5_MODEL_PATH
    return freeze_bundle({"args": {**opts, "roles": [role]}}, out / name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--pairs-per-mode", type=int, default=128)
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

    t0 = time.time()
    out = args.output.resolve()
    b_dir = out / "bundles"
    b_dir.mkdir(parents=True, exist_ok=True)
    bundles = {
        "ctrl_v67": build_part2_bundle(b_dir, "ctrl_v67"),
        "ctrl_s5": build_s5_variant(b_dir, "ctrl_s5", use_pimc=False, value_v68=False),
        "s5_kfix": build_s5_variant(b_dir, "s5_kfix", use_pimc=False, value_v68=True),
        "s5_pimc_kfix": build_s5_variant(b_dir, "s5_pimc_kfix", use_pimc=True, value_v68=True),
    }
    rows = make_cohort("CSV22DEV", args.pairs_per_mode)
    print(f"=== CSV22DEV SCHEMA 5 KAISER-FIX & PIMC ABLATION (N={len(rows)} paired lobbies) ===", flush=True)
    res = run_paired_panel(out, bundles, rows, args.workers)
    res["elapsed_min"] = round((time.time() - t0) / 60.0, 2)

    recs = {
        arm: [
            json.loads(gzip.decompress((out / arm / (seed + ".json.gz")).read_bytes()))
            for _, seed, _ in rows
        ]
        for arm in bundles
    }
    res["paired_vs_s5"] = {
        arm: paired(recs["ctrl_s5"], recs[arm]) for arm in ("s5_kfix", "s5_pimc_kfix")
    }

    print(f"\n=== CSV22DEV RESULTS ({res['elapsed_min']} min) ===", flush=True)
    for arm, s in res["summaries"].items():
        print(
            f"  [{arm:13s}] floor={s['mean_floor']:.3f} A1={s['a1_clears']}/{s['n']} "
            f"A2={s['a2_clears']}/{s['a2_entries']} A3={s['a3_entries']} W={s['wins']} "
            f"mm={s['native'].get('mismatch', 0)} bosses={s['bosses']}",
            flush=True,
        )
    for arm, p in res["paired"].items():
        print(
            f"  vs ctrl_v67 | {arm:13s}: delta={p['delta']:+.3f} CI95={p['ci95']} W/L/T={p['w']}/{p['l']}/{p['t']} p={p['sign_p']:.4f}",
            flush=True,
        )
    for arm, p in res["paired_vs_s5"].items():
        print(
            f"  vs ctrl_s5  | {arm:13s}: delta={p['delta']:+.3f} CI95={p['ci95']} W/L/T={p['w']}/{p['l']}/{p['t']} p={p['sign_p']:.4f}",
            flush=True,
        )

    out_json = ROOT / "docs/combat-search-v2/v68-s5-kaiser-pimc-csv22dev.json"
    out_json.write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(f"Saved {out_json}", flush=True)


if __name__ == "__main__":
    main()
