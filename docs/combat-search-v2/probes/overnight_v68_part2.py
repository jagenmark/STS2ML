"""Overnight Part 2 on Helmer:

Stage 5: Blind CSV17DEV (N=256) testing Act-Hybrid (Control A1 + Human-ML A2/3 & Shop) + Schema 4 v1
Stage 6: AlphaZero Iteration 2 of Schema 4 (3,000 new episodes + Stage 3 = ~165k leaves) on RX 9070 XT
Stage 7: Final Blind CSV18DEV (N=256) testing Schema 4 v2 (combat_value_v4b.npz) across Control & Act-Hybrid
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import time

import numpy as np

from overnight_v68 import (
    MAIN_REPO,
    ROCM_PY,
    SCHEMA4_MODEL_PATH,
    _collect_one_episode,
    make_cohort,
    run_paired_panel,
)
from sts2rl.combat_search_v2.features import SCHEMA4_NAMES
from sts2rl.human_ml_draft import DEFAULT_MODEL_PATH
from sts2rl.run_bundle import freeze_bundle, load_bundle
from v64 import ROOT

SCHEMA4B_MODEL_PATH = ROOT / "docs" / "combat-search-v2" / "models" / "combat_value_v4b.npz"
STAGE3_DATA = MAIN_REPO / "artifacts" / "v68-overnight-20261124" / "stage3_schema4" / "schema4_dataset.npz"


def build_part2_bundle(
    out: Path,
    name: str,
    *,
    hybrid_ml: bool = False,
    use_pimc: bool = False,
    schema4_path: Path | None = None,
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
    if use_pimc:
        cfg["draw_pimc_v68"] = True
        cfg["value_v68"] = True
        cfg["pimc_samples"] = 6
    if schema4_path is not None:
        cfg["value_win_weight"] = float(win_weight)
        opts["combat_value_v2"] = schema4_path
    cfg_path = out / f"{name}_cfg.json"
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8", newline="\n")
    opts["combat_search_v2_config"] = cfg_path

    if hybrid_ml:
        deck = json.loads(opts["deck_model"].read_bytes())
        deck["human_ml_draft_v68"] = True
        deck["human_ml_scope"] = ["card_reward", "bundle_select", "shop"]
        deck["human_ml_card_reward_min_act"] = 2
        deck["human_ml_skip_bias"] = 0.0
        deck["human_ml_act_skip_bias"] = [0.0, 0.2, 0.2]
        deck["human_ml_shop_scale"] = 4.5
        deck_path = out / f"{name}_deck.json"
        deck_path.write_text(json.dumps(deck, indent=2) + "\n", encoding="utf-8", newline="\n")
        opts["deck_model"] = deck_path
        opts["human_ml_draft_model"] = DEFAULT_MODEL_PATH

    return freeze_bundle({"args": {**opts, "roles": [role]}}, out / name)


def stage5_csv17(out: Path, pairs_per_mode: int, workers: int) -> dict:
    t0 = time.time()
    print(f"\n================ STAGE 5: BLIND CSV17DEV ACT-HYBRID + SCHEMA 4 v1 (N={2*pairs_per_mode}) ================", flush=True)
    s5_dir = out / "stage5_csv17dev"
    b_dir = s5_dir / "bundles"
    b_dir.mkdir(parents=True, exist_ok=True)
    bundles = {
        "ctrl_v67": build_part2_bundle(b_dir, "ctrl_v67"),
        "ctrl_schema4": build_part2_bundle(b_dir, "ctrl_schema4", schema4_path=SCHEMA4_MODEL_PATH),
        "hybrid_heur": build_part2_bundle(b_dir, "hybrid_heur", hybrid_ml=True, use_pimc=True),
        "hybrid_schema4": build_part2_bundle(
            b_dir, "hybrid_schema4", hybrid_ml=True, use_pimc=True, schema4_path=SCHEMA4_MODEL_PATH
        ),
    }
    rows = make_cohort("CSV17DEV", pairs_per_mode)
    res = run_paired_panel(s5_dir, bundles, rows, workers)
    res["elapsed_s"] = round(time.time() - t0, 1)
    for arm, s in res["summaries"].items():
        print(
            f"  [{arm:15s}] floor={s['mean_floor']:.3f} A1={s['a1_clears']}/{s['n']} "
            f"A2={s['a2_clears']}/{s['a2_entries']} A3={s['a3_entries']} W={s['wins']} "
            f"mm={s['native'].get('mismatch', 0)} bosses={s['bosses']}",
            flush=True,
        )
    for arm, p in res["paired"].items():
        print(
            f"  Paired {arm:15s} vs ctrl_v67: delta={p['delta']:+.3f} CI95={p['ci95']} W/L/T={p['w']}/{p['l']}/{p['t']} p={p['sign_p']:.4f}",
            flush=True,
        )
    (s5_dir / "stage5_summary.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    return res


def stage6_schema4_iter2(out: Path, episodes_per_arm: int, workers: int, epochs: int) -> dict:
    t0 = time.time()
    print(f"\n================ STAGE 6: SCHEMA 4 ITERATION 2 ({2*episodes_per_arm} NEW RUNS + RX 9070 XT) ================", flush=True)
    s6_dir = out / "stage6_schema4_it2"
    b_dir = s6_dir / "bundles"
    b_dir.mkdir(parents=True, exist_ok=True)
    b_ctrl = build_part2_bundle(b_dir, "ctrl_schema4", schema4_path=SCHEMA4_MODEL_PATH)
    b_hyb = build_part2_bundle(b_dir, "hybrid_schema4", hybrid_ml=True, use_pimc=True, schema4_path=SCHEMA4_MODEL_PATH)

    tasks = []
    uid = 0
    for i in range(episodes_per_arm):
        mode = "default" if i % 2 == 0 else "seeded"
        tasks.append((b_ctrl, (i, f"S4IT2C_{mode.upper()}_{i:04d}", mode), uid))
        uid += 1
        tasks.append((b_hyb, (i, f"S4IT2H_{mode.upper()}_{i:04d}", mode), uid))
        uid += 1

    all_x, all_yw, all_yh, all_uid = [], [], [], []
    done = 0
    total = len(tasks)
    with ProcessPoolExecutor(workers) as pool:
        futs = [pool.submit(_collect_one_episode, t) for t in tasks]
        for f in as_completed(futs):
            done += 1
            item = f.result()
            if item is not None:
                x, yw, yh, ruid, _ = item
                all_x.append(x)
                all_yw.append(yw)
                all_yh.append(yh)
                all_uid.append(ruid)
            if done % max(1, total // 10) == 0 or done == total:
                n_rows = sum(len(a) for a in all_yw)
                print(f"  Collected [{done}/{total}] episodes -> {n_rows:,} new End-Turn leaves", flush=True)

    X = np.concatenate(all_x, axis=0)
    y_win = np.concatenate(all_yw, axis=0)
    y_hp = np.concatenate(all_yh, axis=0)
    run_id = np.concatenate(all_uid, axis=0)
    data_path = s6_dir / "schema4_iter2_dataset.npz"
    np.savez_compressed(data_path, X=X, y_win=y_win, y_hp=y_hp, run_id=run_id)
    collect_s = round(time.time() - t0, 1)
    print(f"  Saved {data_path} ({len(X):,} new leaves in {collect_s}s)", flush=True)

    # Combine Stage 3 + Stage 6 datasets for Iteration 2 GPU training
    data_args = [str(data_path)]
    if STAGE3_DATA.exists():
        data_args.insert(0, str(STAGE3_DATA))
    t_gpu = time.time()
    train_report_path = s6_dir / "schema4_iter2_train_report.json"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    py_exe = str(ROCM_PY) if ROCM_PY.exists() else str(MAIN_REPO / ".venv/cpu/Scripts/python.exe")
    cmd = [
        py_exe,
        str(ROOT / "scripts/train-schema4-gpu.py"),
        "--data",
        *data_args,
        "--output",
        str(SCHEMA4B_MODEL_PATH),
        "--report",
        str(train_report_path),
        "--epochs",
        str(epochs),
        "--late-weight",
        "2.0",
    ]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
    print(proc.stdout, flush=True)
    if proc.returncode != 0:
        print(proc.stderr, flush=True)
        raise RuntimeError(f"Schema 4 Iter 2 GPU training failed with exit code {proc.returncode}")

    train_report = json.loads(train_report_path.read_text(encoding="utf-8"))
    result = {
        "collect_s": collect_s,
        "gpu_train_s": round(time.time() - t_gpu, 1),
        "new_episodes": total,
        "new_leaves": int(len(X)),
        "total_leaves": train_report["samples"]["total"],
        "features": len(SCHEMA4_NAMES),
        "train_report": train_report,
    }
    (s6_dir / "stage6_summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def stage7_csv18(out: Path, pairs_per_mode: int, workers: int) -> dict:
    t0 = time.time()
    print(f"\n================ STAGE 7: FINAL BLIND CSV18DEV SCHEMA 4 v2 (N={2*pairs_per_mode}) ================", flush=True)
    s7_dir = out / "stage7_csv18dev"
    b_dir = s7_dir / "bundles"
    b_dir.mkdir(parents=True, exist_ok=True)
    bundles = {
        "ctrl_v67": build_part2_bundle(b_dir, "ctrl_v67"),
        "ctrl_schema4b": build_part2_bundle(b_dir, "ctrl_schema4b", schema4_path=SCHEMA4B_MODEL_PATH),
        "ctrl_pimc_s4b": build_part2_bundle(b_dir, "ctrl_pimc_s4b", use_pimc=True, schema4_path=SCHEMA4B_MODEL_PATH),
        "hybrid_s4b": build_part2_bundle(
            b_dir, "hybrid_s4b", hybrid_ml=True, use_pimc=True, schema4_path=SCHEMA4B_MODEL_PATH
        ),
    }
    rows = make_cohort("CSV18DEV", pairs_per_mode)
    res = run_paired_panel(s7_dir, bundles, rows, workers)
    res["elapsed_s"] = round(time.time() - t0, 1)
    for arm, s in res["summaries"].items():
        print(
            f"  [{arm:15s}] floor={s['mean_floor']:.3f} A1={s['a1_clears']}/{s['n']} "
            f"A2={s['a2_clears']}/{s['a2_entries']} A3={s['a3_entries']} W={s['wins']} "
            f"mm={s['native'].get('mismatch', 0)} bosses={s['bosses']}",
            flush=True,
        )
    for arm, p in res["paired"].items():
        print(
            f"  Paired {arm:15s} vs ctrl_v67: delta={p['delta']:+.3f} CI95={p['ci95']} W/L/T={p['w']}/{p['l']}/{p['t']} p={p['sign_p']:.4f}",
            flush=True,
        )
    (s7_dir / "stage7_summary.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    return res


def append_morning_report(report_path: Path, summary: dict) -> None:
    s5, s6, s7 = summary["stage5"], summary["stage6"], summary["stage7"]
    tr = s6["train_report"]
    lines = [
        "",
        "---",
        "",
        f"# Part 2 · Act-Hybrid + Schema 4 Iteration 2 (`{summary['total_elapsed_min']:.1f} min`)",
        "",
        "## Stage 5 · Blind `CSV17DEV` (Act-Hybrid + Schema 4 v1)",
        "| Arm | Mean Floor | A1 Clears | A2 Boss | A3 Entries | Wins | Delta vs ctrl_v67 (95% CI) |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for arm, st in s5["summaries"].items():
        p = s5["paired"].get(arm)
        p_str = (
            f"{p['delta']:+.3f} [{p['ci95'][0]:+.3f}, {p['ci95'][1]:+.3f}] (p={p['sign_p']:.4f})"
            if p
            else "—"
        )
        lines.append(
            f"| `{arm}` | {st['mean_floor']:.3f} | {st['a1_clears']}/{st['n']} | {st['a2_clears']}/{st['a2_entries']} | {st['a3_entries']} | {st['wins']} | {p_str} |"
        )
    lines += [
        "",
        "## Stage 6 · Schema 4 Iteration 2 (AlphaZero Loop, RX 9070 XT)",
        f"- Collected `{s6['new_leaves']:,}` new leaves (`{s6['new_episodes']}` episodes) -> combined **`{s6['total_leaves']:,}`** leaves (`late_weight=2.0`).",
        f"- Trained on **{tr['device']}** in `{s6['gpu_train_s']}s`: widths `{tr['selected']['widths']}`, test `{tr['selected']['test']}`, parity `{tr['parity_max_diff']:.2e}`.",
        f"- Exported: `{tr['path']}` (`sha256={tr['sha256']}`).",
        "",
        "## Stage 7 · Final Blind `CSV18DEV` (Schema 4 v2)",
        "| Arm | Mean Floor | A1 Clears | A2 Boss | A3 Entries | Wins | Delta vs ctrl_v67 (95% CI) |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for arm, st in s7["summaries"].items():
        p = s7["paired"].get(arm)
        p_str = (
            f"{p['delta']:+.3f} [{p['ci95'][0]:+.3f}, {p['ci95'][1]:+.3f}] (p={p['sign_p']:.4f})"
            if p
            else "—"
        )
        lines.append(
            f"| `{arm}` | {st['mean_floor']:.3f} | {st['a1_clears']}/{st['n']} | {st['a2_clears']}/{st['a2_entries']} | {st['a3_entries']} | {st['wins']} | {p_str} |"
        )
    lines.append("")
    with report_path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--smoke", action="store_true")
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

    csv17_pairs = 2 if args.smoke else 128
    s6_ep_per_arm = 4 if args.smoke else 1500
    s6_epochs = 4 if args.smoke else 40
    csv18_pairs = 2 if args.smoke else 128

    s5 = stage5_csv17(out, csv17_pairs, args.workers)
    s6 = stage6_schema4_iter2(out, s6_ep_per_arm, args.workers, s6_epochs)
    s7 = stage7_csv18(out, csv18_pairs, args.workers)

    summary = {
        "smoke": args.smoke,
        "total_elapsed_min": round((time.time() - t0) / 60.0, 2),
        "stage5": s5,
        "stage6": s6,
        "stage7": s7,
    }
    if not args.smoke:
        (ROOT / "docs/combat-search-v2/v68-overnight-part2-summary.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )
        append_morning_report(ROOT / "docs/combat-search-v2/v68-overnight-report.md", summary)
        print(f"\nALL PART 2 STAGES COMPLETE! ({summary['total_elapsed_min']:.1f} min)", flush=True)
    else:
        print(f"\nPART 2 SMOKE PASSED CLEANLY! ({summary['total_elapsed_min']:.2f} min)", flush=True)


if __name__ == "__main__":
    main()
