"""High-power N=768 paired confirmation (CSV27CONF: 384 default + 384 seeded) comparing:
  - `ctrl_v67` (baseline)
  - `v69_v5b_kscale` (combat_value_v5b.npz + PIMC + kaiser_scaling_v69)
  - `v69_v5c_bal_pure` (combat_value_v5c_bal.npz + PIMC + kaiser_pure_neural_v69)
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
from schema5_kaiser_iter3 import build_v69_bundle
from v64 import ROOT
from v69_bal_csv26 import SCHEMA5C_BAL_PATH


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
    rows = make_cohort("CSV27CONF", args.pairs_per_mode)
    print(f"=== CSV27CONF HIGH-POWER CONFIRMATION (N={len(rows)} paired lobbies, 3 arms) ===", flush=True)
    res = run_paired_panel(out, bundles, rows, args.workers)
    res["elapsed_min"] = round((time.time() - t0) / 60.0, 2)
    res["model_sha256"] = {
        "v5b": hashlib.sha256(SCHEMA5B_MODEL_PATH.read_bytes()).hexdigest(),
        "v5c_bal": hashlib.sha256(SCHEMA5C_BAL_PATH.read_bytes()).hexdigest(),
    }

    recs = {
        arm: [
            json.loads(gzip.decompress((out / arm / (seed + ".json.gz")).read_bytes()))
            for _, seed, _ in rows
        ]
        for arm in bundles
    }
    res["paired_v5c_vs_v5b"] = paired(recs["v69_v5b_kscale"], recs["v69_v5c_bal_pure"])

    # Also tally Act 3 boss 1st-clear counts!
    a3_boss_stats = {}
    for arm, rlist in recs.items():
        b_wins: dict[str, list[int]] = {}
        for r in rlist:
            for lf in r.get("late_fights", []):
                if lf[0] == 3 and lf[2] == "Boss":
                    form = lf[3]
                    if form not in b_wins:
                        b_wins[form] = [0, 0]
                    b_wins[form][1] += 1
                    if lf[5]:
                        b_wins[form][0] += 1
        a3_boss_stats[arm] = b_wins
    res["act3_bosses"] = a3_boss_stats

    print(f"\n=== CSV27CONF RESULTS (N={len(rows)}, {res['elapsed_min']} min) ===", flush=True)
    for arm, s in res["summaries"].items():
        a2_wr = 100.0 * s["a2_clears"] / max(1, s["a2_entries"])
        print(
            f"  [{arm:17s}] floor={s['mean_floor']:.3f} A1={s['a1_clears']}/{s['n']} ({100*s['a1_clears']/s['n']:.1f}%) "
            f"A2={s['a2_clears']}/{s['a2_entries']} ({a2_wr:.1f}%) A3={s['a3_entries']} W={s['wins']} "
            f"mm={s['native'].get('mismatch', 0)} | A2b={s['bosses']} | A3b={a3_boss_stats[arm]}",
            flush=True,
        )
    for arm, p in res["paired"].items():
        print(
            f"  vs ctrl_v67    | {arm:17s}: delta={p['delta']:+.3f} CI95={p['ci95']} W/L/T={p['w']}/{p['l']}/{p['t']} p={p['sign_p']:.6f}",
            flush=True,
        )
    p_h2h = res["paired_v5c_vs_v5b"]
    print(
        f"  v5c_bal vs v5b | delta={p_h2h['delta']:+.3f} CI95={p_h2h['ci95']} W/L/T={p_h2h['w']}/{p_h2h['l']}/{p_h2h['t']} p={p_h2h['sign_p']:.6f}",
        flush=True,
    )

    out_json = ROOT / "docs/combat-search-v2/v69-confirm-csv27conf-768.json"
    out_json.write_text(json.dumps(res, indent=2), encoding="utf-8")

    # Append to report
    lines = [
        "",
        "---",
        "",
        f"# Part 8 · High-Power Confirmation `CSV27CONF` (`N = {len(rows)}` paired lobbies, `{res['elapsed_min']} min`)",
        "",
        "| Arm | Mean Floor | A1 Clears | A2 Boss | A3 Entries | Full Wins | Mismatches | Delta vs ctrl_v67 (95% CI, p) |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for arm, st in res["summaries"].items():
        p = res["paired"].get(arm)
        p_str = (
            f"{p['delta']:+.3f} [{p['ci95'][0]:+.3f}, {p['ci95'][1]:+.3f}] (p={p['sign_p']:.6f})"
            if p
            else "—"
        )
        lines.append(
            f"| `{arm}` | {st['mean_floor']:.3f} | {st['a1_clears']}/{st['n']} | {st['a2_clears']}/{st['a2_entries']} | {st['a3_entries']} | {st['wins']} | {st['native'].get('mismatch', 0)} | {p_str} |"
        )
    lines.append("")
    lines.append(
        f"Head-to-head `v69_v5c_bal_pure` vs `v69_v5b_kscale`: `{p_h2h['delta']:+.3f}` floors, 95% CI `[{p_h2h['ci95'][0]:+.3f}, {p_h2h['ci95'][1]:+.3f}]`, `W/L/T = {p_h2h['w']}/{p_h2h['l']}/{p_h2h['t']}`, `p = {p_h2h['sign_p']:.6f}`."
    )
    lines.append("")
    with (ROOT / "docs/combat-search-v2/v68-overnight-report.md").open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(f"Saved {out_json}", flush=True)


if __name__ == "__main__":
    main()
