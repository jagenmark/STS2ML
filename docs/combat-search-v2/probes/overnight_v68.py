"""Overnight 4-stage pipeline on Helmer:

Stage 1: 4-knob late-game-weighted hillclimb on Human-ML Draft + PIMC (TUNE96)
Stage 2: Blind held-out paired verification on CSV15DEV (N = 256)
Stage 3: Schema 4 leaf dataset collection (2,000 runs) + RX 9070 XT GPU training
Stage 4: Blind held-out paired A/B test of Schema 4 on CSV16DEV (N = 256) + Morning Report
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
import subprocess
from tempfile import TemporaryDirectory
import time

import numpy as np

from report_v64 import global_floor, paired, summarize
from sts2rl.combat_search_v2.end_turn import resolve as resolve_eot
from sts2rl.combat_search_v2.features import SCHEMA4_NAMES, extract_leaf_features
from sts2rl.combat_search_v2.state import Unsupported, project
from sts2rl.combat_search_v2.transitions import admission
from sts2rl.human_ml_draft import DEFAULT_MODEL_PATH
from sts2rl.run_bundle import freeze_bundle, load_bundle
from sts2rl.run_evaluation import play_episode
from sts2rl.run_policy import RunWeights
from v64 import ROOT, episode

MAIN_REPO = Path(r"C:\Users\gosee\Documents\codex\2026-10-26\new-chat\STS2ML")
ROCM_PY = MAIN_REPO / ".venv" / "rocm" / "Scripts" / "python.exe"
SCHEMA4_MODEL_PATH = ROOT / "docs" / "combat-search-v2" / "models" / "combat_value_v4.npz"


def make_cohort(prefix: str, pairs_per_mode: int):
    return [
        (i, f"{prefix}_{mode.upper()}_{i:04d}", mode)
        for i in range(pairs_per_mode)
        for mode in ("default", "seeded")
    ]


def build_bundle(
    out: Path,
    name: str,
    *,
    use_ml: bool = False,
    knobs: dict | None = None,
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

    if use_ml:
        k = knobs or {}
        deck = json.loads(opts["deck_model"].read_bytes())
        deck["human_ml_draft_v68"] = True
        deck["human_ml_scope"] = ["card_reward", "bundle_select", "shop"]
        deck["human_ml_skip_bias"] = 0.0
        deck["human_ml_act_skip_bias"] = [
            float(k.get("skip_a1", 0.0)),
            float(k.get("skip_late", 0.0)),
            float(k.get("skip_late", 0.0)),
        ]
        deck["human_ml_shop_scale"] = float(k.get("shop_scale", 4.5))
        deck["human_ml_a1_offense_boost"] = float(k.get("a1_offense_boost", 0.0))
        deck["human_ml_a1_offense_cap"] = float(k.get("a1_offense_cap", 4.0))
        deck_path = out / f"{name}_deck.json"
        deck_path.write_text(json.dumps(deck, indent=2) + "\n", encoding="utf-8", newline="\n")
        opts["deck_model"] = deck_path
        opts["human_ml_draft_model"] = DEFAULT_MODEL_PATH

    return freeze_bundle({"args": {**opts, "roles": [role]}}, out / name)


def _run_arm_episode(args):
    folder, bundle, row = args
    episode(folder, bundle, row, card_counts=False)
    return row[1]


def eval_single_arm(run_dir: Path, bundle: Path, rows, workers: int) -> tuple[list[dict], dict, float]:
    run_dir.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(workers) as pool:
        futs = [pool.submit(_run_arm_episode, (run_dir, bundle, row)) for row in rows]
        for f in as_completed(futs):
            f.result()
    recs = [
        json.loads(gzip.decompress((run_dir / (seed + ".json.gz")).read_bytes()))
        for _, seed, _ in rows
    ]
    s = summarize(recs)
    n = max(1, s["n"])
    # Late-game-weighted objective: prevents Act 1 attack-bloat overfitting
    obj = (
        s["mean_floor"]
        + 4.0 * (s["a2_entries"] / n)
        + 12.0 * (s["a2_clears"] / n)
        + 25.0 * ((s["a3_entries"] + s["wins"]) / n)
    )
    return recs, s, round(obj, 4)


def _lobby_multi(args):
    out, bundles, row = args
    arms = list(bundles)
    shift = (2 * row[0] + int(row[2] == "seeded")) % len(arms)
    for arm in arms[shift:] + arms[:shift]:
        episode(out / arm, bundles[arm], row, card_counts=False)
    return row[1]


def run_paired_panel(out: Path, bundles: dict[str, Path], rows, workers: int) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    for arm in bundles:
        (out / arm).mkdir(parents=True, exist_ok=True)
    done = 0
    total = len(rows)
    with ProcessPoolExecutor(workers) as pool:
        jobs = [pool.submit(_lobby_multi, (out, bundles, row)) for row in rows]
        for job in as_completed(jobs):
            done += 1
            seed = job.result()
            if done % max(1, total // 8) == 0 or done == total:
                print(f"  [{done}/{total}] {seed}", flush=True)
    records = {
        arm: [
            json.loads(gzip.decompress((out / arm / (seed + ".json.gz")).read_bytes()))
            for _, seed, _ in rows
        ]
        for arm in bundles
    }
    summaries = {arm: summarize(records[arm]) for arm in bundles}
    arm_names = list(bundles)
    base_arm = arm_names[0]
    paired_vs_base = {
        arm: paired(records[base_arm], records[arm]) for arm in arm_names[1:]
    }
    return {"summaries": summaries, "paired": paired_vs_base}


def _collect_one_episode(args):
    bundle, row, run_uid = args
    i, seed, mode = row
    role, opts = load_bundle(bundle)
    # Track completed End Turn Schema 4 features per combat, labeled at combat end
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
            # Survived and exited combat!
            hp_frac = min(1.0, max(0.0, float(player.get("hp", 0)) / max(1.0, last_max_hp)))
            for feat in pending_fight:
                xs.append(feat)
                yws.append(1.0)
                yhs.append(hp_frac)
            pending_fight = []
        in_fight = now_combat

        if now_combat and state.get("decision") == "combat_play" and action.kind == "end_turn":
            try:
                ctx = state.get("context") or {}
                act = int(ctx.get("act", 1))
                late = act >= 2
                proj = project(
                    state,
                    late_prompts=late,
                    silent_cards_v66=True,
                    silent_cards_v67=True,
                )
                if not admission(proj):
                    resolved = resolve_eot(proj.state)
                    if resolved.outcome == "completed":
                        feat = extract_leaf_features(resolved, schema=4)
                        if np.isfinite(feat).all():
                            pending_fight.append(feat)
            except (Unsupported, KeyError, ValueError, TypeError):
                pass
        return action

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
                {**opts, "seeded_acts": mode == "seeded"},
            ),
            decision_hook=hook,
        )
    # Any pending_fight left at episode end: won if episode won, else died in that fight
    if pending_fight:
        won = 1.0 if res.get("win") else 0.0
        hp_frac = 0.5 if won else 0.0
        for feat in pending_fight:
            xs.append(feat)
            yws.append(won)
            yhs.append(hp_frac)

    if not xs:
        return None
    return (
        np.stack(xs, axis=0),
        np.asarray(yws, dtype=np.float32),
        np.asarray(yhs, dtype=np.float32),
        np.full(len(xs), run_uid, dtype=np.int64),
        global_floor(res),
    )


def stage1_hillclimb(out: Path, tune_pairs: int, workers: int, smoke: bool) -> dict:
    t0 = time.time()
    print(f"\n================ STAGE 1: 4-KNOB HILLCLIMB (N={2*tune_pairs} seeds) ================", flush=True)
    rows = make_cohort("TUNE68", tune_pairs)
    s1_dir = out / "stage1_hillclimb"
    b_dir = s1_dir / "bundles"
    b_dir.mkdir(parents=True, exist_ok=True)

    # Reference baseline on TUNE68
    ctrl_b = build_bundle(b_dir, "ctrl_v67", use_ml=False, use_pimc=False)
    _, ctrl_s, ctrl_obj = eval_single_arm(s1_dir / "ctrl_v67", ctrl_b, rows, workers)
    print(
        f"  [REF ctrl_v67] floor={ctrl_s['mean_floor']:.3f} A1={ctrl_s['a1_clears']}/{ctrl_s['n']} "
        f"A2={ctrl_s['a2_clears']}/{ctrl_s['a2_entries']} A3={ctrl_s['a3_entries']} W={ctrl_s['wins']} obj={ctrl_obj:.3f}",
        flush=True,
    )

    # Initial structured grid covering Act 1 offense boost, cap, and skip balance
    if smoke:
        anchors = [
            {"a1_offense_boost": 1.6, "a1_offense_cap": 3.5, "skip_a1": 0.0, "skip_late": 0.0},
            {"a1_offense_boost": 2.4, "a1_offense_cap": 4.5, "skip_a1": -0.2, "skip_late": 0.0},
        ]
    else:
        anchors = [
            {"a1_offense_boost": 1.2, "a1_offense_cap": 3.5, "skip_a1": 0.0, "skip_late": 0.0},
            {"a1_offense_boost": 1.8, "a1_offense_cap": 4.0, "skip_a1": 0.0, "skip_late": 0.0},
            {"a1_offense_boost": 2.4, "a1_offense_cap": 4.5, "skip_a1": 0.0, "skip_late": 0.0},
            {"a1_offense_boost": 3.0, "a1_offense_cap": 5.0, "skip_a1": -0.2, "skip_late": 0.0},
            {"a1_offense_boost": 2.2, "a1_offense_cap": 3.5, "skip_a1": -0.3, "skip_late": 0.2},
            {"a1_offense_boost": 2.6, "a1_offense_cap": 4.0, "skip_a1": 0.2, "skip_late": -0.2},
        ]

    history = []
    seen = set()

    def key_of(k: dict):
        return (
            round(k["a1_offense_boost"], 2),
            round(k["a1_offense_cap"], 2),
            round(k["skip_a1"], 2),
            round(k["skip_late"], 2),
        )

    def evaluate_knobs(tag: str, k: dict):
        kk = key_of(k)
        if kk in seen:
            return None
        seen.add(kk)
        bnd = build_bundle(b_dir, tag, use_ml=True, knobs=k, use_pimc=True)
        _, s, obj = eval_single_arm(s1_dir / tag, bnd, rows, workers)
        rec = {
            "tag": tag,
            "knobs": dict(k),
            "obj": obj,
            "mean_floor": round(s["mean_floor"], 3),
            "a1_clears": s["a1_clears"],
            "a2_entries": s["a2_entries"],
            "a2_clears": s["a2_clears"],
            "a3_entries": s["a3_entries"],
            "wins": s["wins"],
            "mismatches": s["native"].get("mismatch", 0),
        }
        history.append(rec)
        print(
            f"  [{tag:12s}] knobs={kk} -> floor={rec['mean_floor']:.3f} A1={rec['a1_clears']}/{s['n']} "
            f"A2={rec['a2_clears']}/{rec['a2_entries']} A3={rec['a3_entries']} W={rec['wins']} obj={obj:.3f}",
            flush=True,
        )
        return rec

    for idx, k in enumerate(anchors):
        evaluate_knobs(f"init_{idx}", k)

    best = max(history, key=lambda r: r["obj"])

    # Coordinate hillclimb around best anchor (1 pass for smoke, 2 passes for full)
    steps_schedule = (
        [("a1_offense_boost", 0.5)]
        if smoke
        else [
            ("a1_offense_boost", 0.5),
            ("a1_offense_cap", 0.75),
            ("skip_a1", 0.3),
            ("skip_late", 0.3),
        ]
    )
    step_idx = 0
    for param, delta in steps_schedule:
        improved = False
        for sign in (+1.0, -1.0):
            cand = dict(best["knobs"])
            val = round(cand[param] + sign * delta, 2)
            if param == "a1_offense_boost":
                val = max(0.0, min(4.5, val))
            elif param == "a1_offense_cap":
                val = max(1.5, min(7.0, val))
            else:
                val = max(-1.0, min(1.0, val))
            cand[param] = val
            step_idx += 1
            rec = evaluate_knobs(f"hc_{step_idx}", cand)
            if rec is not None and rec["obj"] > best["obj"]:
                best = rec
                improved = True
                break
        if improved:
            print(f"  -> New best after {param}: {best['tag']} obj={best['obj']:.3f}", flush=True)

    result = {
        "elapsed_s": round(time.time() - t0, 1),
        "ref_ctrl_v67": {
            "mean_floor": round(ctrl_s["mean_floor"], 3),
            "a1_clears": ctrl_s["a1_clears"],
            "a2_entries": ctrl_s["a2_entries"],
            "a2_clears": ctrl_s["a2_clears"],
            "a3_entries": ctrl_s["a3_entries"],
            "wins": ctrl_s["wins"],
            "obj": ctrl_obj,
        },
        "best": best,
        "history": history,
    }
    (s1_dir / "stage1_summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def stage2_csv15(out: Path, best_knobs: dict, pairs_per_mode: int, workers: int) -> dict:
    t0 = time.time()
    print(f"\n================ STAGE 2: BLIND CSV15DEV (N={2*pairs_per_mode} paired lobbies) ================", flush=True)
    s2_dir = out / "stage2_csv15dev"
    b_dir = s2_dir / "bundles"
    b_dir.mkdir(parents=True, exist_ok=True)
    bundles = {
        "ctrl_v67": build_bundle(b_dir, "ctrl_v67", use_ml=False, use_pimc=False),
        "ml_tuned_v67": build_bundle(b_dir, "ml_tuned_v67", use_ml=True, knobs=best_knobs, use_pimc=False),
        "ml_tuned_pimc": build_bundle(b_dir, "ml_tuned_pimc", use_ml=True, knobs=best_knobs, use_pimc=True),
    }
    rows = make_cohort("CSV15DEV", pairs_per_mode)
    res = run_paired_panel(s2_dir, bundles, rows, workers)
    res["elapsed_s"] = round(time.time() - t0, 1)
    for arm, s in res["summaries"].items():
        print(
            f"  [{arm:14s}] floor={s['mean_floor']:.3f} A1={s['a1_clears']}/{s['n']} "
            f"A2={s['a2_clears']}/{s['a2_entries']} A3={s['a3_entries']} W={s['wins']} "
            f"mm={s['native'].get('mismatch', 0)}",
            flush=True,
        )
    for arm, p in res["paired"].items():
        print(
            f"  Paired {arm} vs ctrl_v67: delta={p['delta']:+.3f} CI95={p['ci95']} W/L/T={p['w']}/{p['l']}/{p['t']} p={p['sign_p']:.4f}",
            flush=True,
        )
    (s2_dir / "stage2_summary.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    return res


def stage3_schema4(out: Path, best_knobs: dict, episodes_per_arm: int, workers: int, epochs: int) -> dict:
    t0 = time.time()
    print(f"\n================ STAGE 3: SCHEMA 4 DATA ({2*episodes_per_arm} runs) + RX 9070 XT TRAIN ================", flush=True)
    s3_dir = out / "stage3_schema4"
    b_dir = s3_dir / "bundles"
    b_dir.mkdir(parents=True, exist_ok=True)
    b_ctrl = build_bundle(b_dir, "ctrl_v67", use_ml=False, use_pimc=False)
    b_ml = build_bundle(b_dir, "ml_tuned_pimc", use_ml=True, knobs=best_knobs, use_pimc=True)

    tasks = []
    uid = 0
    for i in range(episodes_per_arm):
        mode = "default" if i % 2 == 0 else "seeded"
        tasks.append((b_ctrl, (i, f"S4CTRL_{mode.upper()}_{i:04d}", mode), uid))
        uid += 1
        tasks.append((b_ml, (i, f"S4ML_{mode.upper()}_{i:04d}", mode), uid))
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
                print(f"  Collected [{done}/{total}] episodes -> {n_rows:,} End-Turn leaves", flush=True)

    X = np.concatenate(all_x, axis=0)
    y_win = np.concatenate(all_yw, axis=0)
    y_hp = np.concatenate(all_yh, axis=0)
    run_id = np.concatenate(all_uid, axis=0)
    data_path = s3_dir / "schema4_dataset.npz"
    np.savez_compressed(data_path, X=X, y_win=y_win, y_hp=y_hp, run_id=run_id)
    collect_s = round(time.time() - t0, 1)
    print(f"  Saved {data_path} ({len(X):,} leaves x {X.shape[1]} feats in {collect_s}s)", flush=True)

    # Train on RX 9070 XT GPU via ROCm venv
    t_gpu = time.time()
    train_report_path = s3_dir / "schema4_train_report.json"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    py_exe = str(ROCM_PY) if ROCM_PY.exists() else str(MAIN_REPO / ".venv/cpu/Scripts/python.exe")
    cmd = [
        py_exe,
        str(ROOT / "scripts/train-schema4-gpu.py"),
        "--data",
        str(data_path),
        "--output",
        str(SCHEMA4_MODEL_PATH),
        "--report",
        str(train_report_path),
        "--epochs",
        str(epochs),
    ]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
    print(proc.stdout, flush=True)
    if proc.returncode != 0:
        print(proc.stderr, flush=True)
        raise RuntimeError(f"Schema 4 GPU training failed with exit code {proc.returncode}")

    train_report = json.loads(train_report_path.read_text(encoding="utf-8"))
    result = {
        "collect_s": collect_s,
        "gpu_train_s": round(time.time() - t_gpu, 1),
        "episodes": total,
        "leaves": int(len(X)),
        "features": len(SCHEMA4_NAMES),
        "train_report": train_report,
    }
    (s3_dir / "stage3_summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def stage4_csv16(
    out: Path,
    best_knobs: dict,
    winner_cfg: dict,
    pairs_per_mode: int,
    workers: int,
) -> dict:
    t0 = time.time()
    print(f"\n================ STAGE 4: BLIND CSV16DEV SCHEMA 4 A/B (N={2*pairs_per_mode} paired lobbies) ================", flush=True)
    s4_dir = out / "stage4_csv16dev"
    b_dir = s4_dir / "bundles"
    b_dir.mkdir(parents=True, exist_ok=True)
    bundles = {
        "ctrl_v67": build_bundle(b_dir, "ctrl_v67", use_ml=False, use_pimc=False),
        "ctrl_schema4": build_bundle(
            b_dir, "ctrl_schema4", use_ml=False, use_pimc=False, schema4_path=SCHEMA4_MODEL_PATH, win_weight=25.0
        ),
        "best_v68_heur": build_bundle(
            b_dir,
            "best_v68_heur",
            use_ml=winner_cfg["use_ml"],
            knobs=best_knobs,
            use_pimc=winner_cfg["use_pimc"],
        ),
        "best_v68_schema4": build_bundle(
            b_dir,
            "best_v68_schema4",
            use_ml=winner_cfg["use_ml"],
            knobs=best_knobs,
            use_pimc=winner_cfg["use_pimc"],
            schema4_path=SCHEMA4_MODEL_PATH,
            win_weight=25.0,
        ),
    }
    rows = make_cohort("CSV16DEV", pairs_per_mode)
    res = run_paired_panel(s4_dir, bundles, rows, workers)
    # Also compute paired delta best_v68_schema4 vs best_v68_heur
    recs_h = [
        json.loads(gzip.decompress((s4_dir / "best_v68_heur" / (s + ".json.gz")).read_bytes()))
        for _, s, _ in rows
    ]
    recs_s4 = [
        json.loads(gzip.decompress((s4_dir / "best_v68_schema4" / (s + ".json.gz")).read_bytes()))
        for _, s, _ in rows
    ]
    res["paired_schema4_vs_heur"] = paired(recs_h, recs_s4)
    res["elapsed_s"] = round(time.time() - t0, 1)
    for arm, s in res["summaries"].items():
        print(
            f"  [{arm:16s}] floor={s['mean_floor']:.3f} A1={s['a1_clears']}/{s['n']} "
            f"A2={s['a2_clears']}/{s['a2_entries']} A3={s['a3_entries']} W={s['wins']} "
            f"mm={s['native'].get('mismatch', 0)}",
            flush=True,
        )
    print(f"  Schema4 vs Heur (on best_v68): {res['paired_schema4_vs_heur']}", flush=True)
    (s4_dir / "stage4_summary.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    return res


def write_morning_report(report_path: Path, summary: dict) -> None:
    s1, s2, s3, s4 = summary["stage1"], summary["stage2"], summary["stage3"], summary["stage4"]
    lines = [
        "# Silent A10 v6.8 Overnight Report (Hillclimb + PIMC + Schema 4 GPU)",
        "",
        f"Total wall-clock runtime: **{summary['total_elapsed_min']:.1f} min**.",
        "",
        "## Stage 1 · 4-Knob Late-Game-Weighted Hillclimb (`TUNE68`)",
        f"- Reference `ctrl_v67`: floor `{s1['ref_ctrl_v67']['mean_floor']:.3f}`, A1 `{s1['ref_ctrl_v67']['a1_clears']}`, A2 `{s1['ref_ctrl_v67']['a2_clears']}/{s1['ref_ctrl_v67']['a2_entries']}`, A3 `{s1['ref_ctrl_v67']['a3_entries']}`, wins `{s1['ref_ctrl_v67']['wins']}`, obj `{s1['ref_ctrl_v67']['obj']:.3f}`",
        f"- Best knobs (`{s1['best']['tag']}`): `{s1['best']['knobs']}` -> floor `{s1['best']['mean_floor']:.3f}`, A1 `{s1['best']['a1_clears']}`, A2 `{s1['best']['a2_clears']}/{s1['best']['a2_entries']}`, A3 `{s1['best']['a3_entries']}`, wins `{s1['best']['wins']}`, obj `{s1['best']['obj']:.3f}`",
        "",
        "## Stage 2 · Blind Held-Out Verification (`CSV15DEV`)",
        "| Arm | Mean Floor | A1 Clears | A2 Boss | A3 Entries | Wins | Delta vs ctrl_v67 (95% CI) |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for arm, st in s2["summaries"].items():
        p = s2["paired"].get(arm)
        p_str = (
            f"{p['delta']:+.3f} [{p['ci95'][0]:+.3f}, {p['ci95'][1]:+.3f}] (p={p['sign_p']:.4f})"
            if p
            else "—"
        )
        lines.append(
            f"| `{arm}` | {st['mean_floor']:.3f} | {st['a1_clears']}/{st['n']} | {st['a2_clears']}/{st['a2_entries']} | {st['a3_entries']} | {st['wins']} | {p_str} |"
        )
    tr = s3["train_report"]
    lines += [
        "",
        "## Stage 3 · Schema 4 Combat Value Training (RX 9070 XT)",
        f"- Collected `{s3['leaves']:,}` completed End-Turn leaves across `{s3['episodes']}` episodes in `{s3['collect_s']}s`.",
        f"- Trained on **{tr['device']}** in `{s3['gpu_train_s']}s`: selected widths `{tr['selected']['widths']}`, test `{tr['selected']['test']}`, NumPy parity `{tr['parity_max_diff']:.2e}`.",
        f"- Exported artifact: `{tr['path']}` (`sha256={tr['sha256']}`).",
        "",
        "## Stage 4 · Blind Held-Out Schema 4 A/B (`CSV16DEV`)",
        "| Arm | Mean Floor | A1 Clears | A2 Boss | A3 Entries | Wins | Delta vs ctrl_v67 (95% CI) |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for arm, st in s4["summaries"].items():
        p = s4["paired"].get(arm)
        p_str = (
            f"{p['delta']:+.3f} [{p['ci95'][0]:+.3f}, {p['ci95'][1]:+.3f}] (p={p['sign_p']:.4f})"
            if p
            else "—"
        )
        lines.append(
            f"| `{arm}` | {st['mean_floor']:.3f} | {st['a1_clears']}/{st['n']} | {st['a2_clears']}/{st['a2_entries']} | {st['a3_entries']} | {st['wins']} | {p_str} |"
        )
    p4 = s4["paired_schema4_vs_heur"]
    lines += [
        "",
        f"- Direct paired `best_v68_schema4` vs `best_v68_heur`: **{p4['delta']:+.3f}** floors (95% CI `[{p4['ci95'][0]:+.3f}, {p4['ci95'][1]:+.3f}]`, W/L/T `{p4['w']}/{p4['l']}/{p4['t']}`, `p={p4['sign_p']:.4f}`).",
        "",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")


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

    t_start = time.time()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)

    tune_pairs = 2 if args.smoke else 48
    csv15_pairs = 2 if args.smoke else 128
    s4_ep_per_arm = 4 if args.smoke else 1250
    s4_epochs = 5 if args.smoke else 40
    csv16_pairs = 2 if args.smoke else 128

    s1 = stage1_hillclimb(out, tune_pairs, args.workers, smoke=args.smoke)
    best_knobs = s1["best"]["knobs"]

    s2 = stage2_csv15(out, best_knobs, csv15_pairs, args.workers)
    # Pick better of ml_tuned_pimc vs ml_tuned_v67 to carry into Stage 4 alongside ctrl_v67
    use_pimc_win = s2["summaries"]["ml_tuned_pimc"]["mean_floor"] >= s2["summaries"]["ml_tuned_v67"]["mean_floor"]
    winner_cfg = {"use_ml": True, "use_pimc": use_pimc_win}

    s3 = stage3_schema4(out, best_knobs, s4_ep_per_arm, args.workers, s4_epochs)
    s4 = stage4_csv16(out, best_knobs, winner_cfg, csv16_pairs, args.workers)

    summary = {
        "smoke": args.smoke,
        "total_elapsed_min": round((time.time() - t_start) / 60.0, 2),
        "stage1": s1,
        "stage2": s2,
        "stage3": s3,
        "stage4": s4,
    }
    if not args.smoke:
        sum_path = ROOT / "docs/combat-search-v2/v68-overnight-summary.json"
        rep_path = ROOT / "docs/combat-search-v2/v68-overnight-report.md"
        sum_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        write_morning_report(rep_path, summary)
        print(f"\nALL 4 STAGES COMPLETE! Morning report written to {rep_path}", flush=True)
    else:
        rep_path = out / "smoke_report.md"
        write_morning_report(rep_path, summary)
        print(f"\nALL 4 SMOKE STAGES PASSED CLEANLY! ({summary['total_elapsed_min']:.2f} min)", flush=True)


if __name__ == "__main__":
    main()
