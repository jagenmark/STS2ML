"""Schema 5 Full Pipeline on Helmer:

1. Collect ~2,800 full runs (50% ctrl_s4c + 50% calibrated hybrid_s4c) PLUS
   ~2,000 Act 2 & Act 3 curriculum forks via `act_start()`, extracting rich
   420-dim Schema 5 features (relics & counters, next-turn energy/draw/shuffle,
   per-enemy powers & last-turn intents, 3-turn poison horizon, boss mechanics,
   analytical next-K draw mix, retained-hand roles) with full v6.7 + late/v61/kaiser flags.
2. Train `combat_value_v5.npz` on RX 9070 XT GPU (`--schema 5`, `--late-weight 2.5`,
   sweeping `(128, 64)`, `(128, 64, 32)`, `(256, 128, 64)`) with NumPy parity check.
3. Quick `value_win_weight` sweep (`15 / 25 / 40`) on `N=64` dev seeds.
4. Blind paired `CSV21DEV` (`N=256` paired lobbies) comparing:
   - `ctrl_v67` (baseline)
   - `ctrl_s4c` (Schema 4 Iter 3 champion)
   - `ctrl_s5`  (Schema 5 on Control draft)
   - `hyb_s5`   (Schema 5 on calibrated Act-Hybrid draft + PIMC)
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
import gzip
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
from tempfile import TemporaryDirectory
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
from schema4_iter3 import SCHEMA4C_MODEL_PATH, _project_for_eot
from sts2rl.combat_search_v2.end_turn import resolve as resolve_eot
from sts2rl.combat_search_v2.features import SCHEMA5_NAMES, extract_leaf_features
from sts2rl.combat_search_v2.state import Unsupported
from sts2rl.combat_search_v2.transitions import admission
from sts2rl.human_ml_draft import DEFAULT_MODEL_PATH
from sts2rl.run_bundle import freeze_bundle, load_bundle
from sts2rl.run_evaluation import play_episode
from sts2rl.run_policy import RunWeights
from v64 import ROOT

SCHEMA5_MODEL_PATH = ROOT / "docs" / "combat-search-v2" / "models" / "combat_value_v5.npz"


def build_hybrid_bundle(
    out: Path,
    name: str,
    *,
    value_path: Path,
    shop_scale: float,
    win_weight: float = 15.0,
    use_pimc: bool = True,
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
    cfg["value_win_weight"] = float(win_weight)
    cfg_path = out / f"{name}_cfg.json"
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8", newline="\n")
    opts["combat_search_v2_config"] = cfg_path
    opts["combat_value_v2"] = value_path

    deck = json.loads(opts["deck_model"].read_bytes())
    deck["human_ml_draft_v68"] = True
    deck["human_ml_scope"] = ["card_reward", "bundle_select"]
    deck["human_ml_card_reward_min_act"] = 2
    deck["human_ml_skip_bias"] = 0.0
    deck["human_ml_act_skip_bias"] = [0.0, 0.2, 0.2]
    deck["human_ml_shop_scale"] = float(shop_scale)
    deck_path = out / f"{name}_deck.json"
    deck_path.write_text(json.dumps(deck, indent=2) + "\n", encoding="utf-8", newline="\n")
    opts["deck_model"] = deck_path
    opts["human_ml_draft_model"] = DEFAULT_MODEL_PATH
    return freeze_bundle({"args": {**opts, "roles": [role]}}, out / name)


def _collect_episode_s5(args):
    """Run one episode (full or Act 2/3 curriculum fork), collecting 420-dim Schema 5 leaves."""
    bundle, row, run_uid, trace_dir, start_trace, start_act = args
    i, seed, mode = row
    role, opts = load_bundle(bundle)

    xs: list[np.ndarray] = []
    yws: list[float] = []
    yhs: list[float] = []
    pending_fight: list[np.ndarray] = []
    in_fight = False
    last_max_hp = 70.0

    def hook(state, action):
        nonlocal in_fight, last_max_hp, pending_fight
        player = state.get("player") or {}
        if player.get("max_hp"):
            last_max_hp = float(player["max_hp"])
        now_combat = bool(state.get("in_combat"))
        if in_fight and not now_combat and pending_fight:
            hp_frac = min(1.0, max(0.0, float(player.get("hp", 0)) / max(1.0, last_max_hp)))
            for feat in pending_fight:
                xs.append(feat)
                yws.append(1.0)
                yhs.append(hp_frac)
            pending_fight = []
        in_fight = now_combat

        if now_combat and state.get("decision") == "combat_play" and action.kind == "end_turn":
            try:
                proj = _project_for_eot(state)
                if not admission(proj):
                    resolved = resolve_eot(proj.state)
                    if resolved.outcome == "completed":
                        feat = extract_leaf_features(resolved, schema=5)
                        if np.isfinite(feat).all():
                            pending_fight.append(feat)
            except (Unsupported, KeyError, ValueError, TypeError):
                pass
        return action

    ep_opts = {**opts, "seeded_acts": mode == "seeded"}
    if start_trace is not None:
        ep_opts["start_trace"] = str(start_trace)
        ep_opts["curriculum_act"] = int(start_act)

    saved_trace = None
    with TemporaryDirectory() as tmp:
        ep_dir = Path(tmp) / "ep"
        res = play_episode(
            (
                ROOT,
                os.environ["CSV2DEV_HOST"],
                ep_dir,
                seed,
                i,
                role,
                asdict(RunWeights.load(opts["weights"])),
                None,
                ep_opts,
            ),
            decision_hook=hook,
        )
        if trace_dir is not None and start_trace is None and res.get("status") == "complete":
            if res.get("a1_clear") or res.get("a2_clear"):
                rpc = ep_dir / "game" / "rpc.jsonl"
                if rpc.exists():
                    dst = Path(trace_dir) / f"{seed}_u{run_uid}.jsonl"
                    shutil.copyfile(rpc, dst)
                    saved_trace = (str(dst), row, bool(res.get("a1_clear")), bool(res.get("a2_clear")))

    if pending_fight:
        won = 1.0 if res.get("win") else 0.0
        hp_frac = 0.5 if won else 0.0
        for feat in pending_fight:
            xs.append(feat)
            yws.append(won)
            yhs.append(hp_frac)

    if not xs:
        return None, saved_trace
    return (
        (
            np.stack(xs, axis=0),
            np.asarray(yws, dtype=np.float32),
            np.asarray(yhs, dtype=np.float32),
            np.full(len(xs), run_uid, dtype=np.int64),
        ),
        saved_trace,
    )


def _act_stats(X: np.ndarray) -> dict:
    i_a1, i_a2, i_a3, i_b = [SCHEMA5_NAMES.index(k) for k in ("act.1", "act.2", "act.3", "room.Boss")]
    return {
        "total": int(len(X)),
        "a1": int((X[:, i_a1] > 0.5).sum()),
        "a2": int((X[:, i_a2] > 0.5).sum()),
        "a3": int((X[:, i_a3] > 0.5).sum()),
        "boss": int((X[:, i_b] > 0.5).sum()),
        "a2_boss": int(((X[:, i_a2] > 0.5) & (X[:, i_b] > 0.5)).sum()),
        "a3_boss": int(((X[:, i_a3] > 0.5) & (X[:, i_b] > 0.5)).sum()),
    }


def collect_and_train_s5(
    out: Path,
    full_per_arm: int,
    shop_scale: float,
    workers: int,
    epochs: int,
    smoke: bool,
) -> dict:
    t0 = time.time()
    print(
        f"\n================ SCHEMA 5 COLLECT: {2*full_per_arm} FULL RUNS + ACT 2/3 FORKS (shop_scale={shop_scale}) ================",
        flush=True,
    )
    c_dir = out / "collect"
    b_dir = c_dir / "bundles"
    tr_dir = c_dir / "traces"
    b_dir.mkdir(parents=True, exist_ok=True)
    tr_dir.mkdir(parents=True, exist_ok=True)

    b_ctrl = build_part2_bundle(b_dir, "ctrl_s4c", schema4_path=SCHEMA4C_MODEL_PATH, win_weight=15.0)
    b_hyb = build_hybrid_bundle(
        b_dir, "hyb_s4c", value_path=SCHEMA4C_MODEL_PATH, shop_scale=shop_scale, win_weight=15.0
    )
    b_alt = build_part2_bundle(b_dir, "ctrl_s4c_w40", use_pimc=True, schema4_path=SCHEMA4C_MODEL_PATH, win_weight=40.0)

    tasks = []
    uid = 0
    for i in range(full_per_arm):
        mode = "default" if i % 2 == 0 else "seeded"
        tasks.append((b_ctrl, (i, f"S5C_{mode.upper()}_{i:04d}", mode), uid, str(tr_dir), None, 1))
        uid += 1
        tasks.append((b_hyb, (i, f"S5H_{mode.upper()}_{i:04d}", mode), uid, str(tr_dir), None, 1))
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

    # Curriculum forks directly from Act 2 & Act 3 openings (preserving base_uid per seed-root!)
    fork_tasks = []
    a2_traces = [tr for tr in saved_traces if tr[2]]
    a3_traces = [tr for tr in saved_traces if tr[3]]
    max_a2 = 4 if smoke else 1200
    a2_cap = a2_traces[:max_a2]
    for path_s, row, _, _ in a2_cap:
        base_uid = int(Path(path_s).stem.rsplit("_u", 1)[1])
        fork_tasks.append((b_hyb, row, base_uid, None, path_s, 2))
        if not smoke:
            fork_tasks.append((b_alt, row, base_uid, None, path_s, 2))
    for path_s, row, _, _ in a3_traces:
        base_uid = int(Path(path_s).stem.rsplit("_u", 1)[1])
        for bnd in (b_ctrl, b_hyb, b_alt):
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
                print(f"  Forks [{f_done}/{len(fork_tasks)}] (err={f_err}) -> {n_rows:,} total leaves", flush=True)

    shutil.rmtree(tr_dir, ignore_errors=True)

    X = np.concatenate(all_x, axis=0)
    y_win = np.concatenate(all_yw, axis=0)
    y_hp = np.concatenate(all_yh, axis=0)
    run_id = np.concatenate(all_uid, axis=0)
    data_path = c_dir / "schema5_dataset.npz"
    np.savez_compressed(data_path, X=X, y_win=y_win, y_hp=y_hp, run_id=run_id)
    stats = _act_stats(X)
    collect_s = round(time.time() - t0, 1)
    print(f"  Saved {data_path} in {collect_s}s | stats={stats}", flush=True)

    # Train Schema 5 on RX 9070 XT GPU!
    t_gpu = time.time()
    train_report_path = c_dir / "schema5_train_report.json"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    py_exe = str(ROCM_PY) if ROCM_PY.exists() else str(MAIN_REPO / ".venv/cpu/Scripts/python.exe")
    out_model = (out / "smoke_v5.npz") if smoke else SCHEMA5_MODEL_PATH
    cmd = [
        py_exe,
        str(ROOT / "scripts/train-schema4-gpu.py"),
        "--schema",
        "5",
        "--data",
        str(data_path),
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
        raise RuntimeError(f"Schema 5 GPU training failed: rc={proc.returncode}")

    train_report = json.loads(train_report_path.read_text(encoding="utf-8"))
    return {
        "collect_s": collect_s,
        "gpu_train_s": round(time.time() - t_gpu, 1),
        "full_episodes": total,
        "curriculum_forks": len(fork_tasks),
        "fork_errors": f_err,
        "stats": stats,
        "model_path": str(out_model),
        "train_report": train_report,
    }


def tune_win_weight_s5(out: Path, model_path: Path, pairs_per_mode: int, workers: int) -> tuple[float, dict]:
    print(f"\n================ SCHEMA 5 WIN_WEIGHT SWEEP (N={2*pairs_per_mode} dev seeds) ================", flush=True)
    w_dir = out / "win_weight_check"
    b_dir = w_dir / "bundles"
    b_dir.mkdir(parents=True, exist_ok=True)
    rows = make_cohort("WW69S5", pairs_per_mode)
    scores = {}
    best_w = 25.0
    best_obj = -1e9
    for ww in (15.0, 25.0, 40.0):
        bnd = build_part2_bundle(b_dir, f"s5_w{int(ww)}", schema4_path=model_path, win_weight=ww)
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


def eval_csv21(
    out: Path,
    model_path: Path,
    best_ww: float,
    shop_scale: float,
    pairs_per_mode: int,
    workers: int,
) -> dict:
    t0 = time.time()
    print(
        f"\n================ BLIND CSV21DEV (N={2*pairs_per_mode} paired lobbies, ww={best_ww}, shop={shop_scale}) ================",
        flush=True,
    )
    e_dir = out / "csv21dev"
    b_dir = e_dir / "bundles"
    b_dir.mkdir(parents=True, exist_ok=True)
    bundles = {
        "ctrl_v67": build_part2_bundle(b_dir, "ctrl_v67"),
        "ctrl_s4c": build_part2_bundle(b_dir, "ctrl_s4c", schema4_path=SCHEMA4C_MODEL_PATH, win_weight=15.0),
        "ctrl_s5": build_part2_bundle(b_dir, "ctrl_s5", schema4_path=model_path, win_weight=best_ww),
        "hyb_s5": build_hybrid_bundle(
            b_dir, "hyb_s5", value_path=model_path, shop_scale=shop_scale, win_weight=best_ww
        ),
    }
    rows = make_cohort("CSV21DEV", pairs_per_mode)
    res = run_paired_panel(e_dir, bundles, rows, workers)
    res["elapsed_s"] = round(time.time() - t0, 1)

    recs = {
        arm: [
            json.loads(gzip.decompress((e_dir / arm / (seed + ".json.gz")).read_bytes()))
            for _, seed, _ in rows
        ]
        for arm in bundles
    }
    res["paired_vs_s4c"] = {
        arm: paired(recs["ctrl_s4c"], recs[arm]) for arm in ("ctrl_s5", "hyb_s5")
    }

    for arm, s in res["summaries"].items():
        print(
            f"  [{arm:10s}] floor={s['mean_floor']:.3f} A1={s['a1_clears']}/{s['n']} "
            f"A2={s['a2_clears']}/{s['a2_entries']} A3={s['a3_entries']} W={s['wins']} "
            f"mm={s['native'].get('mismatch', 0)} bosses={s['bosses']}",
            flush=True,
        )
    for arm, p in res["paired"].items():
        print(
            f"  vs ctrl_v67 | {arm:10s}: delta={p['delta']:+.3f} CI95={p['ci95']} W/L/T={p['w']}/{p['l']}/{p['t']} p={p['sign_p']:.4f}",
            flush=True,
        )
    for arm, p in res["paired_vs_s4c"].items():
        print(
            f"  vs ctrl_s4c | {arm:10s}: delta={p['delta']:+.3f} CI95={p['ci95']} W/L/T={p['w']}/{p['l']}/{p['t']} p={p['sign_p']:.4f}",
            flush=True,
        )
    return res


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--shop-scale", type=float, default=2.0)
    parser.add_argument("--full-per-arm", type=int, default=1400)
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

    full_per_arm = 4 if args.smoke else args.full_per_arm
    s5_epochs = 4 if args.smoke else 45
    ww_pairs = 2 if args.smoke else 32
    csv21_pairs = 2 if args.smoke else 128

    col = collect_and_train_s5(out, full_per_arm, args.shop_scale, args.workers, s5_epochs, smoke=args.smoke)
    model_path = Path(col["model_path"])
    best_ww, ww_scores = tune_win_weight_s5(out, model_path, ww_pairs, args.workers)
    ev = eval_csv21(out, model_path, best_ww, args.shop_scale, csv21_pairs, args.workers)

    summary = {
        "smoke": args.smoke,
        "shop_scale": args.shop_scale,
        "total_elapsed_min": round((time.time() - t0) / 60.0, 2),
        "collect_train": col,
        "best_win_weight": best_ww,
        "win_weight_scores": ww_scores,
        "csv21dev": ev,
    }
    if not args.smoke:
        (ROOT / "docs/combat-search-v2/v68-schema5-summary.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )
        tr = col["train_report"]
        lines = [
            "",
            "---",
            "",
            f"# Part 4 · Schema 5 (`{tr['features']}` features, `{summary['total_elapsed_min']:.1f} min`, `shop_scale={args.shop_scale}`)",
            f"- Collected Schema 5 dataset: `{col['stats']}` (`{col['full_episodes']}` full + `{col['curriculum_forks']}` A2/A3 forks, err={col['fork_errors']}).",
            f"- Trained on **{tr['device']}** in `{col['gpu_train_s']}s`: widths `{tr['selected']['widths']}`, test `{tr['selected']['test']}`, slices `{tr['test_slices']}`, parity `{tr['parity_max_diff']:.2e}`.",
            f"- Selected `value_win_weight = {best_ww}` (`{ww_scores}`).",
            f"- Exported: `{tr['path']}` (`sha256={tr['sha256']}`).",
            "",
            "## Blind `CSV21DEV` (`N = 256` paired lobbies)",
            "| Arm | Mean Floor | A1 Clears | A2 Boss | A3 Entries | Wins | Delta vs ctrl_v67 (95% CI) | Delta vs ctrl_s4c |",
            "|---|---:|---:|---:|---:|---:|---|---|",
        ]
        for arm, st in ev["summaries"].items():
            p = ev["paired"].get(arm)
            p_str = (
                f"{p['delta']:+.3f} [{p['ci95'][0]:+.3f}, {p['ci95'][1]:+.3f}] (p={p['sign_p']:.4f})"
                if p
                else "—"
            )
            p4 = ev["paired_vs_s4c"].get(arm)
            p4_str = f"{p4['delta']:+.3f} (p={p4['sign_p']:.4f})" if p4 else "—"
            lines.append(
                f"| `{arm}` | {st['mean_floor']:.3f} | {st['a1_clears']}/{st['n']} | {st['a2_clears']}/{st['a2_entries']} | {st['a3_entries']} | {st['wins']} | {p_str} | {p4_str} |"
            )
        lines.append("")
        with (ROOT / "docs/combat-search-v2/v68-overnight-report.md").open("a", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        print(f"\nSCHEMA 5 PIPELINE COMPLETE! ({summary['total_elapsed_min']:.1f} min)", flush=True)
    else:
        print(f"\nSCHEMA 5 SMOKE PASSED CLEANLY! ({summary['total_elapsed_min']:.2f} min)", flush=True)


if __name__ == "__main__":
    main()
