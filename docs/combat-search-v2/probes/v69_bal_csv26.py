"""Compare v5c (kaiser_weight=4.0) vs v5c_bal (kaiser_weight=1.5) in both pure-neural
and kaiser_scaling_v69 modes on a blind N=256 panel (CSV26DEV) + the 95 CSV24CONF Kaiser seeds.
"""

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
from schema5_iter2 import SCHEMA5B_MODEL_PATH
from schema5_kaiser_iter3 import SCHEMA5C_MODEL_PATH, build_v69_bundle
from v64 import ROOT

SCHEMA5C_BAL_PATH = ROOT / "docs" / "combat-search-v2" / "models" / "combat_value_v5c_bal.npz"


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
        "v68_v5b": build_v69_bundle(
            b_dir, "v68_v5b", model_path=SCHEMA5B_MODEL_PATH, use_pimc=True, value_v68=True, win_weight=15.0
        ),
        "v69_v5b_kscale": build_v69_bundle(
            b_dir,
            "v69_v5b_kscale",
            model_path=SCHEMA5B_MODEL_PATH,
            use_pimc=True,
            value_v68=True,
            kaiser_scaling_v69=True,
            win_weight=15.0,
        ),
        "v69_v5c_bal_pure": build_v69_bundle(
            b_dir,
            "v69_v5c_bal_pure",
            model_path=SCHEMA5C_BAL_PATH,
            use_pimc=True,
            value_v68=True,
            kaiser_pure_neural_v69=True,
            win_weight=15.0,
        ),
    }
    rows = make_cohort("CSV26DEV", args.pairs_per_mode)
    print(f"=== CSV26DEV BALANCED V5C & V5B+KSCALE (N={len(rows)} paired lobbies) ===", flush=True)
    res = run_paired_panel(out, bundles, rows, args.workers)
    res["elapsed_min"] = round((time.time() - t0) / 60.0, 2)

    recs = {
        arm: [
            json.loads(gzip.decompress((out / arm / (seed + ".json.gz")).read_bytes()))
            for _, seed, _ in rows
        ]
        for arm in bundles
    }
    res["paired_vs_v5b"] = {
        arm: paired(recs["v68_v5b"], recs[arm]) for arm in ("v69_v5b_kscale", "v69_v5c_bal_pure")
    }

    print(f"\n=== CSV26DEV RESULTS ({res['elapsed_min']} min) ===", flush=True)
    for arm, s in res["summaries"].items():
        print(
            f"  [{arm:17s}] floor={s['mean_floor']:.3f} A1={s['a1_clears']}/{s['n']} "
            f"A2={s['a2_clears']}/{s['a2_entries']} A3={s['a3_entries']} W={s['wins']} "
            f"mm={s['native'].get('mismatch', 0)} bosses={s['bosses']}",
            flush=True,
        )
    for arm, p in res["paired"].items():
        print(
            f"  vs ctrl_v67 | {arm:17s}: delta={p['delta']:+.3f} CI95={p['ci95']} W/L/T={p['w']}/{p['l']}/{p['t']} p={p['sign_p']:.4f}",
            flush=True,
        )
    for arm, p in res["paired_vs_v5b"].items():
        print(
            f"  vs v68_v5b  | {arm:17s}: delta={p['delta']:+.3f} CI95={p['ci95']} W/L/T={p['w']}/{p['l']}/{p['t']} p={p['sign_p']:.4f}",
            flush=True,
        )

    out_json = ROOT / "docs/combat-search-v2/v69-balanced-v5c-csv26dev.json"
    out_json.write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(f"Saved {out_json}", flush=True)
    assert SCHEMA5C_MODEL_PATH.exists()


if __name__ == "__main__":
    main()
