"""Overnight v7.0 Act 3 Victory & Balanced 547k Model Pipeline (~90 min on Helmer):

Step 1 (~2.5 min): Train `combat_value_v5e_bal.npz` on RX 9070 XT over all 547,532 combined
                   420-dim Schema 5 leaves with balanced weights (`--late-weight 1.6`,
                   `--act3-weight 1.4`, `--kaiser-weight 1.2`) to combine v5c_bal's 73.6% Act 1
                   dominance with v5d's 30.7% Act 2 Boss & Act 3 mastery.
Step 2 (~35 min):  Blind `CSV29DEV` (`N = 512` paired lobbies = 256 default + 256 seeded) comparing:
                   - `v69_v5c_bal_pure` (reigning 27.0+ champion)
                   - `v70_v5e_bal_pure` (new 547k balanced Schema 5)
                   - `v70_v5e_hyb2`     (Control A1 + All Shops + Human-ML A2/A3 Card Rewards)
                   - `v70_v5e_hyb2_lean`(same + leaner A2/A3 skip bias [0.0, 0.45, 0.65] for Act 3 wins!)
Step 3 (~50 min):  High-power `CSV30CONF` (`N = 1,024` paired lobbies = 512 default + 512 seeded)
                   confirming `ctrl_v67` vs `v69_v5c_bal_pure` vs the winning `v70` arm from Step 2!
"""

from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import time

from act3_overnight_v70 import S5_ITER3_DATA, build_v70_bundle
from overnight_v68 import MAIN_REPO, ROCM_PY, make_cohort, run_paired_panel
from overnight_v68_part2 import build_part2_bundle
from report_v64 import paired
from schema5_iter2 import S5_ITER1_DATA
from schema5_kaiser_iter3 import S5_ITER2_DATA
from sts2rl.human_ml_draft import DEFAULT_MODEL_PATH
from sts2rl.run_bundle import freeze_bundle, load_bundle
from v64 import ROOT
from v69_bal_csv26 import SCHEMA5C_BAL_PATH

S5_ITER4_DATA = (
    MAIN_REPO
    / "artifacts"
    / "v70-act3-overnight-20261126"
    / "collect"
    / "schema5_iter4_act3_dataset.npz"
)
SCHEMA5E_BAL_PATH = ROOT / "docs" / "combat-search-v2" / "models" / "combat_value_v5e_bal.npz"


def build_hyb_bundle(
    out: Path,
    name: str,
    *,
    model_path: Path,
    act_skip_bias: list[float],
    win_weight: float = 15.0,
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
    cfg["draw_pimc_v68"] = True
    cfg["pimc_samples"] = 6
    cfg["value_v68"] = True
    cfg["kaiser_pure_neural_v69"] = True
    cfg["value_win_weight"] = float(win_weight)
    cfg_path = out / f"{name}_cfg.json"
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8", newline="\n")
    opts["combat_search_v2_config"] = cfg_path
    opts["combat_value_v2"] = model_path

    deck = json.loads(opts["deck_model"].read_bytes())
    deck["human_ml_draft_v68"] = True
    deck["human_ml_scope"] = ["card_reward", "bundle_select"]
    deck["human_ml_card_reward_min_act"] = 2
    deck["human_ml_skip_bias"] = 0.0
    deck["human_ml_act_skip_bias"] = list(act_skip_bias)
    deck_path = out / f"{name}_deck.json"
    deck_path.write_text(json.dumps(deck, indent=2) + "\n", encoding="utf-8", newline="\n")
    opts["deck_model"] = deck_path
    opts["human_ml_draft_model"] = DEFAULT_MODEL_PATH
    return freeze_bundle({"args": {**opts, "roles": [role]}}, out / name)


def _act3_boss_tally(run_dir: Path, arm: str, rows) -> tuple[dict, float]:
    c = Counter()
    w = Counter()
    d3 = []
    for _, seed, _ in rows:
        r = json.loads(gzip.decompress((run_dir / arm / (seed + ".json.gz")).read_bytes()))
        ds = r.get("deck_size") or {}
        if "3" in ds:
            d3.append(ds["3"])
        for lf in r.get("late_fights", []):
            if lf[0] == 3 and lf[2] == "Boss":
                c[lf[3]] += 1
                if lf[5]:
                    w[lf[3]] += 1
    avg_d3 = round(sum(d3) / len(d3), 1) if d3 else 0.0
    return {k: [w[k], c[k]] for k in sorted(c)}, avg_d3


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
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
    out.mkdir(parents=True, exist_ok=True)

    # ---------------- STEP 1: Train balanced 547k combat_value_v5e_bal.npz on RX 9070 XT ----------------
    print("\n================ STEP 1: GPU TRAINING combat_value_v5e_bal.npz (547k balanced) ================", flush=True)
    t_gpu = time.time()
    train_report_path = out / "v5e_bal_train_report.json"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    py_exe = str(ROCM_PY) if ROCM_PY.exists() else str(MAIN_REPO / ".venv/cpu/Scripts/python.exe")
    data_files = [str(p) for p in (S5_ITER1_DATA, S5_ITER2_DATA, S5_ITER3_DATA, S5_ITER4_DATA) if p.exists()]
    cmd = [
        py_exe,
        str(ROOT / "scripts/train-schema4-gpu.py"),
        "--schema",
        "5",
        "--data",
        *data_files,
        "--output",
        str(SCHEMA5E_BAL_PATH),
        "--report",
        str(train_report_path),
        "--epochs",
        "50",
        "--late-weight",
        "1.6",
        "--kaiser-weight",
        "1.2",
        "--act3-weight",
        "1.4",
    ]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
    print(proc.stdout, flush=True)
    if proc.returncode != 0:
        print(proc.stderr, flush=True)
        raise RuntimeError(f"v5e_bal GPU training failed: rc={proc.returncode}")
    train_report = json.loads(train_report_path.read_text(encoding="utf-8"))
    gpu_s = round(time.time() - t_gpu, 1)

    # ---------------- STEP 2: Blind CSV29DEV (N=512 paired lobbies, 4 arms) ----------------
    print("\n================ STEP 2: BLIND CSV29DEV (N=512 paired lobbies) ================", flush=True)
    d29 = out / "csv29dev"
    b29 = d29 / "bundles"
    b29.mkdir(parents=True, exist_ok=True)
    bundles_29 = {
        "v69_v5c_bal_pure": build_v70_bundle(
            b29, "v69_v5c_bal_pure", model_path=SCHEMA5C_BAL_PATH, kaiser_pure_neural_v69=True, win_weight=15.0
        ),
        "v70_v5e_bal_pure": build_v70_bundle(
            b29, "v70_v5e_bal_pure", model_path=SCHEMA5E_BAL_PATH, kaiser_pure_neural_v69=True, win_weight=15.0
        ),
        "v70_v5e_hyb2": build_hyb_bundle(
            b29, "v70_v5e_hyb2", model_path=SCHEMA5E_BAL_PATH, act_skip_bias=[0.0, 0.2, 0.2], win_weight=15.0
        ),
        "v70_v5e_hyb2_lean": build_hyb_bundle(
            b29, "v70_v5e_hyb2_lean", model_path=SCHEMA5E_BAL_PATH, act_skip_bias=[0.0, 0.45, 0.65], win_weight=15.0
        ),
    }
    rows_29 = make_cohort("CSV29DEV", 256)
    t29 = time.time()
    ev29 = run_paired_panel(d29, bundles_29, rows_29, args.workers)
    ev29["elapsed_min"] = round((time.time() - t29) / 60.0, 2)

    recs_29 = {
        arm: [json.loads(gzip.decompress((d29 / arm / (seed + ".json.gz")).read_bytes())) for _, seed, _ in rows_29]
        for arm in bundles_29
    }
    ev29["paired_vs_v69"] = {
        arm: paired(recs_29["v69_v5c_bal_pure"], recs_29[arm]) for arm in bundles_29 if arm != "v69_v5c_bal_pure"
    }
    ev29["act3_bosses"] = {}
    ev29["avg_a3_deck"] = {}
    best_v70 = "v70_v5e_bal_pure"
    best_obj = -1e9
    for arm, s in ev29["summaries"].items():
        a3b, avg_d3 = _act3_boss_tally(d29, arm, rows_29)
        ev29["act3_bosses"][arm] = a3b
        ev29["avg_a3_deck"][arm] = avg_d3
        b1_wins = sum(v[0] for v in a3b.values())
        obj = s["mean_floor"] + 0.08 * s["a2_clears"] + 0.15 * s["a3_entries"] + 0.5 * b1_wins + 2.0 * s["wins"]
        print(
            f"  [{arm:18s}] floor={s['mean_floor']:.3f} A1={s['a1_clears']}/{s['n']} "
            f"A2={s['a2_clears']}/{s['a2_entries']} A3={s['a3_entries']} A3B1={b1_wins} W={s['wins']} "
            f"d3={avg_d3} mm={s['native'].get('mismatch', 0)} | A2b={s['bosses']} | A3b={a3b}",
            flush=True,
        )
        if arm != "v69_v5c_bal_pure" and obj > best_obj:
            best_obj = obj
            best_v70 = arm
    for arm, p in ev29["paired_vs_v69"].items():
        print(
            f"  vs v69_v5c_bal_pure | {arm:18s}: delta={p['delta']:+.3f} CI95={p['ci95']} W/L/T={p['w']}/{p['l']}/{p['t']} p={p['sign_p']:.5f}",
            flush=True,
        )
    print(f"  -> Selected best v70 arm for N=1024 CSV30CONF: {best_v70}", flush=True)

    # ---------------- STEP 3: Mega Confirmation CSV30CONF (N=1,024 paired lobbies!) ----------------
    print(f"\n================ STEP 3: MEGA CONFIRMATION CSV30CONF (N=1024 paired lobbies, winner={best_v70}) ================", flush=True)
    d30 = out / "csv30conf"
    b30 = d30 / "bundles"
    b30.mkdir(parents=True, exist_ok=True)
    bundles_30 = {
        "ctrl_v67": build_part2_bundle(b30, "ctrl_v67"),
        "v69_v5c_bal_pure": bundles_29["v69_v5c_bal_pure"],
        best_v70: bundles_29[best_v70],
    }
    rows_30 = make_cohort("CSV30CONF", 512)
    t30 = time.time()
    ev30 = run_paired_panel(d30, bundles_30, rows_30, args.workers)
    ev30["elapsed_min"] = round((time.time() - t30) / 60.0, 2)

    recs_30 = {
        arm: [json.loads(gzip.decompress((d30 / arm / (seed + ".json.gz")).read_bytes())) for _, seed, _ in rows_30]
        for arm in bundles_30
    }
    ev30["paired_v70_vs_v69"] = paired(recs_30["v69_v5c_bal_pure"], recs_30[best_v70])
    ev30["act3_bosses"] = {}
    ev30["avg_a3_deck"] = {}
    for arm, s in ev30["summaries"].items():
        a3b, avg_d3 = _act3_boss_tally(d30, arm, rows_30)
        ev30["act3_bosses"][arm] = a3b
        ev30["avg_a3_deck"][arm] = avg_d3
        b1_wins = sum(v[0] for v in a3b.values())
        print(
            f"  [{arm:18s}] floor={s['mean_floor']:.3f} A1={s['a1_clears']}/{s['n']} "
            f"A2={s['a2_clears']}/{s['a2_entries']} A3={s['a3_entries']} A3B1={b1_wins} W={s['wins']} "
            f"d3={avg_d3} mm={s['native'].get('mismatch', 0)} | A2b={s['bosses']} | A3b={a3b}",
            flush=True,
        )
    for arm, p in ev30["paired"].items():
        print(
            f"  vs ctrl_v67        | {arm:18s}: delta={p['delta']:+.3f} CI95={p['ci95']} W/L/T={p['w']}/{p['l']}/{p['t']} p={p['sign_p']:.6f}",
            flush=True,
        )
    p_h = ev30["paired_v70_vs_v69"]
    print(
        f"  {best_v70} vs v69: delta={p_h['delta']:+.3f} CI95={p_h['ci95']} W/L/T={p_h['w']}/{p_h['l']}/{p_h['t']} p={p_h['sign_p']:.6f}",
        flush=True,
    )

    summary = {
        "total_elapsed_min": round((time.time() - t0) / 60.0, 2),
        "gpu_train_s": gpu_s,
        "train_report": train_report,
        "best_v70": best_v70,
        "csv29dev": ev29,
        "csv30conf": ev30,
    }
    (ROOT / "docs/combat-search-v2/v70-act3-wins-summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    lines = [
        f"# v7.0 Overnight Wave 2 · Balanced 547k Schema 5 + Lean Act 2/3 Human-ML (`{summary['total_elapsed_min']:.1f} min`)",
        "",
        f"- **Model:** `combat_value_v5e_bal.npz` (`{train_report['samples']['total']:,}` leaves, RX 9070 XT `{gpu_s}s`, widths `{train_report['selected']['widths']}`, test `{train_report['selected']['test']}`, `act3={train_report['test_slices'].get('act3')}`, `a3_boss={train_report['test_slices'].get('a3_boss')}`, `kaiser_2arm={train_report['test_slices'].get('kaiser_2arm')}`, parity `{train_report['parity_max_diff']:.2e}`).",
        "",
        "## Step 2 · Blind `CSV29DEV` (`N = 512` paired lobbies)",
        "| Arm | Mean Floor | A1 Clears | A2 Boss | A3 Entries | A3 Boss1 Clears | Full Wins | Avg A3 Deck | Delta vs v69 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for arm, s in ev29["summaries"].items():
        b1 = sum(v[0] for v in ev29["act3_bosses"][arm].values())
        pv = ev29["paired_vs_v69"].get(arm)
        pv_s = f"{pv['delta']:+.3f} (p={pv['sign_p']:.4f})" if pv else "—"
        lines.append(
            f"| `{arm}` | {s['mean_floor']:.3f} | {s['a1_clears']}/{s['n']} | {s['a2_clears']}/{s['a2_entries']} | {s['a3_entries']} | {b1} | **{s['wins']}** | {ev29['avg_a3_deck'][arm]} | {pv_s} |"
        )
    lines += [
        "",
        f"## Step 3 · Mega Confirmation `CSV30CONF` (`N = 1,024` paired lobbies, winner=`{best_v70}`)",
        "| Arm | Mean Floor | A1 Clears | A2 Boss | A3 Entries | A3 Boss1 Clears | Full Wins | Avg A3 Deck | Delta vs ctrl_v67 (95% CI, p) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for arm, s in ev30["summaries"].items():
        b1 = sum(v[0] for v in ev30["act3_bosses"][arm].values())
        pv = ev30["paired"].get(arm)
        pv_s = f"{pv['delta']:+.3f} [{pv['ci95'][0]:+.3f}, {pv['ci95'][1]:+.3f}] (p={pv['sign_p']:.6f})" if pv else "—"
        lines.append(
            f"| `{arm}` | {s['mean_floor']:.3f} | {s['a1_clears']}/{s['n']} | {s['a2_clears']}/{s['a2_entries']} | {s['a3_entries']} | {b1} | **{s['wins']}** | {ev30['avg_a3_deck'][arm]} | {pv_s} |"
        )
    lines.append("")
    lines.append(
        f"Head-to-head `{best_v70}` vs `v69_v5c_bal_pure`: `{p_h['delta']:+.3f}` floors, 95% CI `[{p_h['ci95'][0]:+.3f}, {p_h['ci95'][1]:+.3f}]`, `W/L/T = {p_h['w']}/{p_h['l']}/{p_h['t']}`, `p = {p_h['sign_p']:.6f}`."
    )
    lines.append("")
    (ROOT / "docs/combat-search-v2/v70-act3-wins-report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\nOVERNIGHT WAVE 2 COMPLETE! ({summary['total_elapsed_min']:.1f} min)", flush=True)


if __name__ == "__main__":
    main()
