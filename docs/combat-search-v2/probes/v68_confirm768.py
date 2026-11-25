"""High-power N=768 paired confirmation (CSV24CONF: 384 default + 384 seeded) of
v6.8 Schema 5 Iter 2 + PIMC (`combat_value_v5b.npz`) vs `ctrl_v67`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import time

from overnight_v68 import make_cohort, run_paired_panel
from overnight_v68_part2 import build_part2_bundle
from schema5_iter2 import SCHEMA5B_MODEL_PATH, build_s5_model_bundle
from v64 import ROOT


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--pairs-per-mode", type=int, default=384)
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
        "v68_s5b_pimc": build_s5_model_bundle(
            b_dir,
            "v68_s5b_pimc",
            model_path=SCHEMA5B_MODEL_PATH,
            use_pimc=True,
            value_v68=True,
            win_weight=15.0,
        ),
    }
    rows = make_cohort("CSV24CONF", args.pairs_per_mode)
    print(f"=== CSV24CONF HIGH-POWER CONFIRMATION (N={len(rows)} paired lobbies) ===", flush=True)
    res = run_paired_panel(out, bundles, rows, args.workers)
    res["elapsed_min"] = round((time.time() - t0) / 60.0, 2)
    res["model_sha256"] = hashlib.sha256(SCHEMA5B_MODEL_PATH.read_bytes()).hexdigest()

    print(f"\n=== CSV24CONF RESULTS (N={len(rows)}, {res['elapsed_min']} min) ===", flush=True)
    for arm, s in res["summaries"].items():
        a2_wr = 100.0 * s["a2_clears"] / max(1, s["a2_entries"])
        print(
            f"  [{arm:14s}] floor={s['mean_floor']:.3f} A1={s['a1_clears']}/{s['n']} ({100*s['a1_clears']/s['n']:.1f}%) "
            f"A2={s['a2_clears']}/{s['a2_entries']} ({a2_wr:.1f}%) A3={s['a3_entries']} W={s['wins']} "
            f"mm={s['native'].get('mismatch', 0)} bosses={s['bosses']}",
            flush=True,
        )
    for arm, p in res["paired"].items():
        print(
            f"  Paired {arm:14s} vs ctrl_v67: delta={p['delta']:+.3f} CI95={p['ci95']} "
            f"W/L/T={p['w']}/{p['l']}/{p['t']} p={p['sign_p']:.6f}",
            flush=True,
        )

    out_json = ROOT / "docs/combat-search-v2/v68-confirm-csv24conf-768.json"
    out_json.write_text(json.dumps(res, indent=2), encoding="utf-8")

    # Append confirmation table to overnight report
    st0 = res["summaries"]["ctrl_v67"]
    st1 = res["summaries"]["v68_s5b_pimc"]
    p = res["paired"]["v68_s5b_pimc"]
    lines = [
        "",
        "---",
        "",
        f"# Part 6 · High-Power Confirmation `CSV24CONF` (`N = {len(rows)}` paired lobbies, `{res['elapsed_min']} min`)",
        f"- Model: `combat_value_v5b.npz` (`sha256={res['model_sha256']}`), `draw_pimc_v68=True`, `value_v68=True`, `value_win_weight=15.0`.",
        "",
        "| Arm | Mean Floor | A1 Clears | A2 Boss | A3 Entries | Wins | Mismatches |",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"| `ctrl_v67` | {st0['mean_floor']:.3f} | {st0['a1_clears']}/{st0['n']} | {st0['a2_clears']}/{st0['a2_entries']} | {st0['a3_entries']} | {st0['wins']} | {st0['native'].get('mismatch', 0)} |",
        f"| `v68_s5b_pimc` | **{st1['mean_floor']:.3f}** | **{st1['a1_clears']}/{st1['n']}** | **{st1['a2_clears']}/{st1['a2_entries']}** | **{st1['a3_entries']}** | **{st1['wins']}** | {st1['native'].get('mismatch', 0)} |",
        "",
        f"**Paired delta (`v68_s5b_pimc` vs `ctrl_v67`):** `{p['delta']:+.3f}` floors, 95% CI `[{p['ci95'][0]:+.3f}, {p['ci95'][1]:+.3f}]`, `W/L/T = {p['w']}/{p['l']}/{p['t']}`, sign `p = {p['sign_p']:.6f}`.",
        "",
    ]
    with (ROOT / "docs/combat-search-v2/v68-overnight-report.md").open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(f"Saved {out_json}", flush=True)


if __name__ == "__main__":
    main()
