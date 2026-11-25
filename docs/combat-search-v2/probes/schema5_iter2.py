"""Schema 5 Iteration 2 on Helmer:

1. Collect ~3,600 NEW full runs + Act 2/3 curriculum forks using our best
   Schema 5 policy (with Kaiser Crab fix + optional PIMC selected from CSV22DEV),
   yielding ~160k-180k fresh 420-dim leaves.
2. Combine with Schema 5 Iter 1 (`157,411` leaves) -> ~320k-340k total 420-dim leaves
   with massive Act 2/3 & Boss density, and train `combat_value_v5b.npz` on RX 9070 XT GPU.
3. Quick `value_win_weight` sweep (`15 / 25 / 40`) on N=64 dev seeds.
4. Blind paired `CSV23DEV` (N=256 paired lobbies) comparing:
   - `ctrl_v67` (baseline)
   - `ctrl_s5_it1` (Schema 5 Iter 1 champion from CSV22DEV)
   - `ctrl_s5_it2` (Schema 5 Iter 2)
   - `ctrl_s5_it2_pimc` (Schema 5 Iter 2 + PIMC)
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import gzip
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import time

import numpy as np

from overnight_v68 import (
    MAIN_REPO,
    ROCM_PY,
    eval_single_arm,
    make_cohort,
    run_paired_panel,
)
from overnight_v68_part2 import build_part2_bundle
from report_v64 import paired
from schema5_pipeline import (
    SCHEMA5_MODEL_PATH,
    _act_stats,
    _collect_episode_s5,
)
from sts2rl.run_bundle import freeze_bundle, load_bundle
from v64 import ROOT

S5_ITER1_DATA = MAIN_REPO / "artifacts" / "v68-schema5-20261125" / "collect" / "schema5_dataset.npz"
SCHEMA5B_MODEL_PATH = ROOT / "docs" / "combat-search-v2" / "models" / "combat_value_v5b.npz"


def build_s5_model_bundle(
    out: Path,
    name: str,
    *,
    model_path: Path,
    use_pimc: bool = False,
    value_v68: bool = True,
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
    opts["combat_value_v2"] = model_path
    return freeze_bundle({"args": {**opts, "roles": [role]}}, out / name)


def collect_and_train_it2(
    out: Path,
    full_per_arm: int,
    workers: int,
    epochs: int,
    it1_use_pimc: bool,
    it1_value_v68: bool,
    smoke: bool,
) -> dict:
    t0 = time.time()
    print(
        f"\n================ SCHEMA 5 ITER 2 COLLECT: {2*full_per_arm} FULL RUNS + ACT 2/3 FORKS ================",
        flush=True,
    )
    c_dir = out / "collect"
    b_dir = c_dir / "bundles"
    tr_dir = c_dir / "traces"
    b_dir.mkdir(parents=True, exist_ok=True)
    tr_dir.mkdir(parents=True, exist_ok=True)

    b_a = build_s5_model_bundle(
        b_dir, "s5_a", model_path=SCHEMA5_MODEL_PATH, use_pimc=it1_use_pimc, value_v68=it1_value_v68, win_weight=25.0
    )
    b_b = build_s5_model_bundle(
        b_dir, "s5_b", model_path=SCHEMA5_MODEL_PATH, use_pimc=not it1_use_pimc, value_v68=it1_value_v68, win_weight=25.0
    )
    b_alt = build_s5_model_bundle(
        b_dir, "s5_w40", model_path=SCHEMA5_MODEL_PATH, use_pimc=True, value_v68=it1_value_v68, win_weight=40.0
    )

    tasks = []
    uid = 0
    for i in range(full_per_arm):
        mode = "default" if i % 2 == 0 else "seeded"
        tasks.append((b_a, (i, f"S5I2A_{mode.upper()}_{i:04d}", mode), uid, str(tr_dir), None, 1))
        uid += 1
        tasks.append((b_b, (i, f"S5I2B_{mode.upper()}_{i:04d}", mode), uid, str(tr_dir), None, 1))
        uid += 1

    all_x, all_yw, all_yh, all_uid = [], [], [], []
    saved_traces = []
    done = 0
    total = len(tasks)
    with ProcessPoolExecutor(workers) as pool:
        futs = [pool.submit(_collect_episode_s5, t) for t in tasks]
        for f in as_completed(futs):
            done += 1
            item, tr = f.result()
            if item is not None:
                x, yw, yh, ruid = item
                all_x.append(x)
                all_yw.append(yw)
                all_yh.append(yh)
                all_uid.append(ruid)
            if tr is not None:
                saved_traces.append(tr)
            if done % max(1, total // 10) == 0 or done == total:
                n_rows = sum(len(a) for a in all_yw)
                print(
                    f"  Full [{done}/{total}] -> {n_rows:,} leaves | traces={len(saved_traces)}",
                    flush=True,
                )

    fork_tasks = []
    a2_traces = [tr for tr in saved_traces if tr[2]]
    a3_traces = [tr for tr in saved_traces if tr[3]]
    max_a2 = 4 if smoke else 1200
    a2_cap = a2_traces[:max_a2]
    for path_s, row, _, _ in a2_cap:
        base_uid = int(Path(path_s).stem.rsplit("_u", 1)[1])
        fork_tasks.append((b_b, row, base_uid, None, path_s, 2))
        if not smoke:
            fork_tasks.append((b_alt, row, base_uid, None, path_s, 2))
    for path_s, row, _, _ in a3_traces:
        base_uid = int(Path(path_s).stem.rsplit("_u", 1)[1])
        for bnd in (b_a, b_b, b_alt):
            fork_tasks.append((bnd, row, base_uid, None, path_s, 3))

    print(
        f"  Starting Phase B curriculum forks: {len(fork_tasks)} forks "
        f"(from {len(a2_cap)} A2 openings + {len(a3_traces)} A3 openings)",
        flush=True,
    )
    f_done = 0
    f_err = 0
    with ProcessPoolExecutor(workers) as pool:
        futs = [pool.submit(_collect_episode_s5, t) for t in fork_tasks]
        for f in as_completed(futs):
            f_done += 1
            try:
                item, _ = f.result()
                if item is not None:
                    x, yw, yh, ruid = item
                    all_x.append(x)
                    all_yw.append(yw)
                    all_yh.append(yh)
                    all_uid.append(ruid)
            except Exception:
                f_err += 1
            if f_done % max(1, max(1, len(fork_tasks)) // 8) == 0 or f_done == len(fork_tasks):
                n_rows = sum(len(a) for a in all_yw)
                print(f"  Forks [{f_done}/{len(fork_tasks)}] (err={f_err}) -> {n_rows:,} total new leaves", flush=True)

    shutil.rmtree(tr_dir, ignore_errors=True)

    X = np.concatenate(all_x, axis=0)
    y_win = np.concatenate(all_yw, axis=0)
    y_hp = np.concatenate(all_yh, axis=0)
    run_id = np.concatenate(all_uid, axis=0)
    data_path = c_dir / "schema5_iter2_dataset.npz"
    np.savez_compressed(data_path, X=X, y_win=y_win, y_hp=y_hp, run_id=run_id)
    new_stats = _act_stats(X)
    collect_s = round(time.time() - t0, 1)
    print(f"  Saved {data_path} in {collect_s}s | new_stats={new_stats}", flush=True)

    data_args = []
    if S5_ITER1_DATA.exists() and not smoke:
        data_args.append(str(S5_ITER1_DATA))
    data_args.append(str(data_path))

    t_gpu = time.time()
    train_report_path = c_dir / "schema5_iter2_train_report.json"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    py_exe = str(ROCM_PY) if ROCM_PY.exists() else str(MAIN_REPO / ".venv/cpu/Scripts/python.exe")
    out_model = (out / "smoke_v5b.npz") if smoke else SCHEMA5B_MODEL_PATH
    cmd = [
        py_exe,
        str(ROOT / "scripts/train-schema4-gpu.py"),
        "--schema",
        "5",
        "--data",
        *data_args,
        "--output",
        str(out_model),
        "--report",
        str(train_report_path),
        "--epochs",
        str(epochs),
        "--late-weight",
        "2.5",
    ]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
    print(proc.stdout, flush=True)
    if proc.returncode != 0:
        print(proc.stderr, flush=True)
        raise RuntimeError(f"Schema 5 Iter 2 GPU training failed: rc={proc.returncode}")

    train_report = json.loads(train_report_path.read_text(encoding="utf-8"))
    return {
        "collect_s": collect_s,
        "gpu_train_s": round(time.time() - t_gpu, 1),
        "full_episodes": total,
        "curriculum_forks": len(fork_tasks),
        "fork_errors": f_err,
        "new_stats": new_stats,
        "model_path": str(out_model),
        "train_report": train_report,
    }


def tune_win_weight_it2(
    out: Path, model_path: Path, use_pimc: bool, value_v68: bool, pairs_per_mode: int, workers: int
) -> tuple[float, dict]:
    print(f"\n================ SCHEMA 5 ITER 2 WIN_WEIGHT SWEEP (N={2*pairs_per_mode} dev seeds) ================", flush=True)
    w_dir = out / "win_weight_check"
    b_dir = w_dir / "bundles"
    b_dir.mkdir(parents=True, exist_ok=True)
    rows = make_cohort("WW69S5B", pairs_per_mode)
    scores = {}
    best_w = 25.0
    best_obj = -1e9
    for ww in (15.0, 25.0, 40.0):
        bnd = build_s5_model_bundle(
            b_dir, f"s5b_w{int(ww)}", model_path=model_path, use_pimc=use_pimc, value_v68=value_v68, win_weight=ww
        )
        _, s, obj = eval_single_arm(w_dir / f"w{int(ww)}", bnd, rows, workers)
        scores[str(int(ww))] = {
            "mean_floor": round(s["mean_floor"], 3),
            "a1_clears": s["a1_clears"],
            "a2_clears": s["a2_clears"],
            "a2_entries": s["a2_entries"],
            "a3_entries": s["a3_entries"],
            "wins": s["wins"],
            "obj": obj,
        }
        print(f"  win_weight={ww:4.1f} -> {scores[str(int(ww))]}", flush=True)
        if obj > best_obj:
            best_obj = obj
            best_w = ww
    print(f"  -> Selected win_weight={best_w}", flush=True)
    return best_w, scores


def eval_csv23(
    out: Path,
    model_path: Path,
    best_ww: float,
    it1_use_pimc: bool,
    it1_value_v68: bool,
    pairs_per_mode: int,
    workers: int,
) -> dict:
    t0 = time.time()
    print(
        f"\n================ BLIND CSV23DEV (N={2*pairs_per_mode} paired lobbies, ww={best_ww}) ================",
        flush=True,
    )
    e_dir = out / "csv23dev"
    b_dir = e_dir / "bundles"
    b_dir.mkdir(parents=True, exist_ok=True)
    bundles = {
        "ctrl_v67": build_part2_bundle(b_dir, "ctrl_v67"),
        "s5_it1": build_s5_model_bundle(
            b_dir, "s5_it1", model_path=SCHEMA5_MODEL_PATH, use_pimc=it1_use_pimc, value_v68=it1_value_v68, win_weight=25.0
        ),
        "s5_it2": build_s5_model_bundle(
            b_dir, "s5_it2", model_path=model_path, use_pimc=False, value_v68=it1_value_v68, win_weight=best_ww
        ),
        "s5_it2_pimc": build_s5_model_bundle(
            b_dir, "s5_it2_pimc", model_path=model_path, use_pimc=True, value_v68=it1_value_v68, win_weight=best_ww
        ),
    }
    rows = make_cohort("CSV23DEV", pairs_per_mode)
    res = run_paired_panel(e_dir, bundles, rows, workers)
    res["elapsed_s"] = round(time.time() - t0, 1)

    recs = {
        arm: [
            json.loads(gzip.decompress((e_dir / arm / (seed + ".json.gz")).read_bytes()))
            for _, seed, _ in rows
        ]
        for arm in bundles
    }
    res["paired_vs_it1"] = {
        arm: paired(recs["s5_it1"], recs[arm]) for arm in ("s5_it2", "s5_it2_pimc")
    }

    for arm, s in res["summaries"].items():
        print(
            f"  [{arm:12s}] floor={s['mean_floor']:.3f} A1={s['a1_clears']}/{s['n']} "
            f"A2={s['a2_clears']}/{s['a2_entries']} A3={s['a3_entries']} W={s['wins']} "
            f"mm={s['native'].get('mismatch', 0)} bosses={s['bosses']}",
            flush=True,
        )
    for arm, p in res["paired"].items():
        print(
            f"  vs ctrl_v67 | {arm:12s}: delta={p['delta']:+.3f} CI95={p['ci95']} W/L/T={p['w']}/{p['l']}/{p['t']} p={p['sign_p']:.4f}",
            flush=True,
        )
    for arm, p in res["paired_vs_it1"].items():
        print(
            f"  vs s5_it1   | {arm:12s}: delta={p['delta']:+.3f} CI95={p['ci95']} W/L/T={p['w']}/{p['l']}/{p['t']} p={p['sign_p']:.4f}",
            flush=True,
        )
    return res


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--full-per-arm", type=int, default=1800)
    parser.add_argument("--it1-pimc", action="store_true")
    parser.add_argument("--no-value-v68", action="store_true")
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

    use_v68 = not args.no_value_v68
    full_per_arm = 4 if args.smoke else args.full_per_arm
    epochs = 4 if args.smoke else 45
    ww_pairs = 2 if args.smoke else 32
    csv23_pairs = 2 if args.smoke else 128

    col = collect_and_train_it2(out, full_per_arm, args.workers, epochs, args.it1_pimc, use_v68, smoke=args.smoke)
    model_path = Path(col["model_path"])
    best_ww, ww_scores = tune_win_weight_it2(out, model_path, args.it1_pimc, use_v68, ww_pairs, args.workers)
    ev = eval_csv23(out, model_path, best_ww, args.it1_pimc, use_v68, csv23_pairs, args.workers)

    summary = {
        "smoke": args.smoke,
        "it1_pimc": args.it1_pimc,
        "value_v68": use_v68,
        "total_elapsed_min": round((time.time() - t0) / 60.0, 2),
        "collect_train": col,
        "best_win_weight": best_ww,
        "win_weight_scores": ww_scores,
        "csv23dev": ev,
    }
    if not args.smoke:
        (ROOT / "docs/combat-search-v2/v68-schema5-iter2-summary.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )
        tr = col["train_report"]
        lines = [
            "",
            "---",
            "",
            f"# Part 5 · Schema 5 Iteration 2 (`{tr['samples']['total']:,}` combined 420-dim leaves, `{summary['total_elapsed_min']:.1f} min`)",
            f"- New Iter 2 leaves: `{col['new_stats']}` (`{col['full_episodes']}` full + `{col['curriculum_forks']}` A2/A3 forks, err={col['fork_errors']}).",
            f"- Trained on **{tr['device']}** in `{col['gpu_train_s']}s`: widths `{tr['selected']['widths']}`, test `{tr['selected']['test']}`, slices `{tr['test_slices']}`, parity `{tr['parity_max_diff']:.2e}`.",
            f"- Selected `value_win_weight = {best_ww}` (`{ww_scores}`).",
            f"- Exported: `{tr['path']}` (`sha256={tr['sha256']}`).",
            "",
            "## Blind `CSV23DEV` (`N = 256` paired lobbies)",
            "| Arm | Mean Floor | A1 Clears | A2 Boss | A3 Entries | Wins | Delta vs ctrl_v67 (95% CI) | Delta vs s5_it1 |",
            "|---|---:|---:|---:|---:|---:|---|---|",
        ]
        for arm, st in ev["summaries"].items():
            p = ev["paired"].get(arm)
            p_str = (
                f"{p['delta']:+.3f} [{p['ci95'][0]:+.3f}, {p['ci95'][1]:+.3f}] (p={p['sign_p']:.4f})"
                if p
                else "—"
            )
            p1 = ev["paired_vs_it1"].get(arm)
            p1_str = f"{p1['delta']:+.3f} (p={p1['sign_p']:.4f})" if p1 else "—"
            lines.append(
                f"| `{arm}` | {st['mean_floor']:.3f} | {st['a1_clears']}/{st['n']} | {st['a2_clears']}/{st['a2_entries']} | {st['a3_entries']} | {st['wins']} | {p_str} | {p1_str} |"
            )
        lines.append("")
        with (ROOT / "docs/combat-search-v2/v68-overnight-report.md").open("a", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        print(f"\nSCHEMA 5 ITER 2 COMPLETE! ({summary['total_elapsed_min']:.1f} min)", flush=True)
    else:
        print(f"\nSCHEMA 5 ITER 2 SMOKE PASSED CLEANLY! ({summary['total_elapsed_min']:.2f} min)", flush=True)


if __name__ == "__main__":
    main()
