"""Overnight Act 3 Victory Push on Helmer (~4–5h total, fully automated):

Fixes the remaining Act 3 / Act 2 collector drop bugs (`aeon_plays` for AEONGLASS,
`sloth_plays` for KNOWLEDGE_DEMON, `tender_plays` for TENDER, `facing` for CRUSHER+ROCKET),
then runs a 4-stage overnight pipeline targeting **Act 3 Boss 1 clears & Full A10 Double-Boss Wins**:

Stage A (~65 min): Collect 3,600 fresh full runs (`A3V70_*`) saving EVERY Act 3 opening trace (~350+ traces!)
                   + Kaiser Crab Act 2 openings.
Stage B (~55 min): Fork EVERY Act 3 opening 8x across diverse combat/draft/potion/win_weight policies
                   (generating ~2,800+ Act 3 runs -> ~100k+ Act 3 leaves & ~10k+ Act 3 Boss leaves including AEONGLASS & Floor 16!)
                   + 2x forks on Kaiser Crab openings.
Stage C (~2 min):  Train `combat_value_v5d.npz` on RX 9070 XT GPU over all ~550k+ combined 420-dim leaves
                   (`--schema 5 --late-weight 2.5 --act3-weight 2.5 --kaiser-weight 1.5 --epochs 50`).
Stage D (~25 min): Held-out Act 3 Victory Bakeoff on 160 fresh Act 3 openings (testing `v69_champ`, `v70_v5d`,
                   `v70_v5d_ww35`, `v70_v5d_pot5`, and `v70_v5d_hyb_a3` [Human-ML Act 3 card rewards!])
                   measuring Act 3 Boss 1 clears, Floor 16 entries, and Full A10 Double-Boss Wins!
Stage E (~35 min): Blind full-run paired `CSV28DEV` (`N = 512` paired lobbies = 256 default + 256 seeded)
                   comparing `ctrl_v67` vs `v69_champ` vs winning `v70_best`!
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, replace
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

from overnight_v68 import MAIN_REPO, ROCM_PY, make_cohort, run_paired_panel
from overnight_v68_part2 import build_part2_bundle
from report_v64 import paired
from schema5_iter2 import S5_ITER1_DATA, SCHEMA5B_MODEL_PATH
from schema5_kaiser_iter3 import S5_ITER2_DATA
from sts2rl.combat_search_v2.end_turn import resolve as resolve_eot
from sts2rl.combat_search_v2.features import SCHEMA5_NAMES, extract_leaf_features
from sts2rl.combat_search_v2.state import Unsupported, project
from sts2rl.combat_search_v2.transitions import admission
from sts2rl.human_ml_draft import DEFAULT_MODEL_PATH
from sts2rl.run_bundle import freeze_bundle, load_bundle
from sts2rl.run_evaluation import play_episode
from sts2rl.run_policy import RunWeights
from v64 import ROOT
from v69_bal_csv26 import SCHEMA5C_BAL_PATH

S5_ITER3_DATA = (
    MAIN_REPO
    / "artifacts"
    / "v69-schema5-kaiser-iter3-20261125"
    / "collect"
    / "schema5_iter3_kaiser_dataset.npz"
)
SCHEMA5D_MODEL_PATH = ROOT / "docs" / "combat-search-v2" / "models" / "combat_value_v5d.npz"


def build_v70_bundle(
    out: Path,
    name: str,
    *,
    model_path: Path,
    use_pimc: bool = True,
    value_v68: bool = True,
    kaiser_scaling_v69: bool = False,
    kaiser_pure_neural_v69: bool = False,
    win_weight: float = 15.0,
    potion_reserve: float = 7.0,
    human_ml_min_act: int | None = None,
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
    cfg["potion_reserve"] = float(potion_reserve)
    if use_pimc:
        cfg["draw_pimc_v68"] = True
        cfg["pimc_samples"] = 6
    if value_v68:
        cfg["value_v68"] = True
    if kaiser_scaling_v69:
        cfg["kaiser_scaling_v69"] = True
    if kaiser_pure_neural_v69:
        cfg["kaiser_pure_neural_v69"] = True
    cfg_path = out / f"{name}_cfg.json"
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8", newline="\n")
    opts["combat_search_v2_config"] = cfg_path
    opts["combat_value_v2"] = model_path

    if human_ml_min_act is not None:
        deck = json.loads(opts["deck_model"].read_bytes())
        deck["human_ml_draft_v68"] = True
        deck["human_ml_scope"] = ["card_reward", "bundle_select"]
        deck["human_ml_card_reward_min_act"] = int(human_ml_min_act)
        deck["human_ml_skip_bias"] = 0.0
        deck["human_ml_act_skip_bias"] = [0.0, 0.2, 0.2]
        deck_path = out / f"{name}_deck.json"
        deck_path.write_text(json.dumps(deck, indent=2) + "\n", encoding="utf-8", newline="\n")
        opts["deck_model"] = deck_path
        opts["human_ml_draft_model"] = DEFAULT_MODEL_PATH

    return freeze_bundle({"args": {**opts, "roles": [role]}}, out / name)


def _project_for_eot_v70(state, *, facing=None, plays_this_round=0, aeon_plays=0):
    """Project live combat state with full v6.7 + late/v61/kaiser + tracked facing/sloth/tender/aeon."""
    ctx = state.get("context") or {}
    act = int(ctx.get("act", 1))
    room = ctx.get("room_type", "Monster")
    late = act >= 2
    proj = project(
        state,
        late_prompts=late,
        silent_cards_v66=True,
        silent_cards_v67=True,
    )
    st = proj.state
    if late:
        kaiser = (
            act == 2
            and room == "Boss"
            and bool(st.enemies)
            and all(e.name in ("CRUSHER", "ROCKET") for e in st.enemies)
        )
        side = proj.enemy_indices.index(facing) if facing in proj.enemy_indices else -1
        if len(st.enemies) == 1 and st.enemies[0].name in ("CRUSHER", "ROCKET"):
            side = 0
        st = replace(
            st,
            late=True,
            v61_rules=True,
            kaiser_v63=kaiser,
            facing=side,
            preview_facing=side,
            sloth_plays=plays_this_round,
            tender_plays=plays_this_round,
            aeon_plays=aeon_plays,
        )
        proj = replace(proj, state=st)
    return proj


def _collect_episode_v70(args):
    """Run one episode with complete Act 2/3 tracking, saving Act 3 & Kaiser traces when requested."""
    bundle, row, run_uid, trace_dir, start_trace, start_act = args
    i, seed, mode = row
    role, opts = load_bundle(bundle)

    xs: list[np.ndarray] = []
    yws: list[float] = []
    yhs: list[float] = []
    pending_fight: list[np.ndarray] = []
    in_fight = False
    facing = None
    round_num = -1
    plays_this_round = 0
    aeon_plays = 0
    last_max_hp = 70.0
    saw_kaiser = False

    def hook(state, action):
        nonlocal in_fight, facing, round_num, plays_this_round, aeon_plays, last_max_hp, pending_fight, saw_kaiser
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
        if now_combat and not in_fight:
            facing = next(
                (
                    e["index"]
                    for e in state.get("enemies") or ()
                    if any(
                        p["id"].split(".")[-1].removesuffix("_POWER") == "BACK_ATTACK_RIGHT"
                        for p in e.get("powers") or ()
                    )
                ),
                None,
            )
            round_num = -1
            plays_this_round = 0
            aeon_plays = 0
        in_fight = now_combat

        if now_combat:
            r_cur = int(state.get("round", 0))
            if r_cur != round_num:
                round_num = r_cur
                plays_this_round = 0
            if "target_index" in action.args:
                facing = action.args["target_index"]
            if action.kind == "play_card":
                plays_this_round += 1
                aeon_plays += 1
            ctx = state.get("context") or {}
            if ctx.get("act") == 2 and ctx.get("room_type") == "Boss":
                if any(e["id"].split(".")[-1] in ("CRUSHER", "ROCKET") for e in state.get("enemies") or ()):
                    saw_kaiser = True

        if now_combat and state.get("decision") == "combat_play" and action.kind == "end_turn":
            try:
                proj = _project_for_eot_v70(
                    state,
                    facing=facing,
                    plays_this_round=plays_this_round,
                    aeon_plays=aeon_plays,
                )
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
            if res.get("a2_clear") or saw_kaiser:
                rpc = ep_dir / "game" / "rpc.jsonl"
                if rpc.exists():
                    dst = Path(trace_dir) / f"{seed}_u{run_uid}.jsonl"
                    shutil.copyfile(rpc, dst)
                    saved_trace = (str(dst), row, bool(saw_kaiser), bool(res.get("a2_clear")))

    if pending_fight:
        won = 1.0 if res.get("win") else 0.0
        hp_frac = 0.5 if won else 0.0
        for feat in pending_fight:
            xs.append(feat)
            yws.append(won)
            yhs.append(hp_frac)

    win_flag = bool(res.get("win"))
    if not xs:
        return None, saved_trace, win_flag
    return (
        (
            np.stack(xs, axis=0),
            np.asarray(yws, dtype=np.float32),
            np.asarray(yhs, dtype=np.float32),
            np.full(len(xs), run_uid, dtype=np.int64),
        ),
        saved_trace,
        win_flag,
    )


def _eval_act3_fork(args):
    """Run one Act 3 curriculum evaluation fork and record Act 3 floor, Boss 1 clears, and Full Wins."""
    arm, bundle, trace_path, row = args
    i, seed, mode = row
    role, opts = load_bundle(bundle)
    ep_opts = {
        **opts,
        "seeded_acts": mode == "seeded",
        "start_trace": str(trace_path),
        "curriculum_act": 3,
        "audit_compact": True,
    }
    with TemporaryDirectory() as tmp:
        res = play_episode(
            (
                ROOT,
                os.environ["CSV2DEV_HOST"],
                Path(tmp) / "ep",
                seed,
                i,
                role,
                asdict(RunWeights.load(opts["weights"])),
                None,
                ep_opts,
            )
        )
    a3_bosses = [lf for lf in res.get("late_fights", []) if lf[0] == 3 and lf[2] == "Boss"]
    b1_clear = any(lf[5] for lf in a3_bosses)
    return {
        "arm": arm,
        "seed": seed,
        "a3_floor": int(res.get("floor", 0)),
        "reached_boss": bool(a3_bosses),
        "boss1_clear": b1_clear,
        "win": bool(res.get("win")),
        "mm": int((res.get("native") or {}).get("mismatch", 0)),
        "bosses": [(lf[3], bool(lf[5])) for lf in a3_bosses],
    }


def _stats_v70(X: np.ndarray, yw: np.ndarray) -> dict:
    i_a1, i_a2, i_a3, i_b, i_fl = [SCHEMA5_NAMES.index(k) for k in ("act.1", "act.2", "act.3", "room.Boss", "floor")]
    a3 = X[:, i_a3] > 0.5
    a3b = a3 & (X[:, i_b] > 0.5)
    f16 = a3b & (X[:, i_fl] >= 16)
    return {
        "total": int(len(X)),
        "a1": int((X[:, i_a1] > 0.5).sum()),
        "a2": int((X[:, i_a2] > 0.5).sum()),
        "a3": int(a3.sum()),
        "a3_wins": int(yw[a3].sum()) if a3.any() else 0,
        "a3_boss": int(a3b.sum()),
        "a3_boss_wins": int(yw[a3b].sum()) if a3b.any() else 0,
        "a3_floor16_boss2": int(f16.sum()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--full-per-arm", type=int, default=1800)
    parser.add_argument("--champ", choices=("v5b_kscale", "v5c_bal_pure"), default="v5b_kscale")
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
    c_dir = out / "collect"
    b_dir = c_dir / "bundles"
    tr_dir = c_dir / "traces"
    b_dir.mkdir(parents=True, exist_ok=True)
    tr_dir.mkdir(parents=True, exist_ok=True)

    full_per_arm = 4 if args.smoke else args.full_per_arm
    epochs = 4 if args.smoke else 50
    csv28_pairs = 2 if args.smoke else 256  # N=512 paired lobbies!

    # Build champion & diverse Act 3 explorer bundles
    b_v5b_ks = build_v70_bundle(
        b_dir, "v5b_kscale", model_path=SCHEMA5B_MODEL_PATH, kaiser_scaling_v69=True, win_weight=15.0
    )
    b_v5c_pure = build_v70_bundle(
        b_dir, "v5c_bal_pure", model_path=SCHEMA5C_BAL_PATH, kaiser_pure_neural_v69=True, win_weight=15.0
    )
    b_champ = b_v5b_ks if args.champ == "v5b_kscale" else b_v5c_pure

    champ_model = SCHEMA5B_MODEL_PATH if args.champ == "v5b_kscale" else SCHEMA5C_BAL_PATH
    champ_kscale = args.champ == "v5b_kscale"
    champ_pure = args.champ == "v5c_bal_pure"

    b_ww35 = build_v70_bundle(
        b_dir,
        "champ_ww35",
        model_path=champ_model,
        kaiser_scaling_v69=champ_kscale,
        kaiser_pure_neural_v69=champ_pure,
        win_weight=35.0,
    )
    b_ww60 = build_v70_bundle(
        b_dir,
        "champ_ww60",
        model_path=champ_model,
        kaiser_scaling_v69=champ_kscale,
        kaiser_pure_neural_v69=champ_pure,
        win_weight=60.0,
    )
    b_pot5 = build_v70_bundle(
        b_dir,
        "champ_pot5",
        model_path=champ_model,
        kaiser_scaling_v69=champ_kscale,
        kaiser_pure_neural_v69=champ_pure,
        win_weight=25.0,
        potion_reserve=5.0,
    )
    b_pot9 = build_v70_bundle(
        b_dir,
        "champ_pot9",
        model_path=champ_model,
        kaiser_scaling_v69=champ_kscale,
        kaiser_pure_neural_v69=champ_pure,
        win_weight=15.0,
        potion_reserve=9.0,
    )
    b_hyb3 = build_v70_bundle(
        b_dir,
        "champ_hyb_a3",
        model_path=champ_model,
        kaiser_scaling_v69=champ_kscale,
        kaiser_pure_neural_v69=champ_pure,
        win_weight=25.0,
        human_ml_min_act=3,
    )
    b_hyb2 = build_v70_bundle(
        b_dir,
        "champ_hyb_a2",
        model_path=champ_model,
        kaiser_scaling_v69=champ_kscale,
        kaiser_pure_neural_v69=champ_pure,
        win_weight=25.0,
        human_ml_min_act=2,
    )

    # ---------------- STAGE A: Full runs to harvest ~350-400 Act 3 openings ----------------
    print(f"\n================ STAGE A: {2*full_per_arm} FULL RUNS (harvesting Act 3 openings) ================", flush=True)
    tasks = []
    uid = 0
    for i in range(full_per_arm):
        mode = "default" if i % 2 == 0 else "seeded"
        tasks.append((b_v5b_ks, (i, f"A3V70A_{mode.upper()}_{i:04d}", mode), uid, str(tr_dir), None, 1))
        uid += 1
        tasks.append((b_v5c_pure, (i, f"A3V70B_{mode.upper()}_{i:04d}", mode), uid, str(tr_dir), None, 1))
        uid += 1

    all_x, all_yw, all_yh, all_uid = [], [], [], []
    saved_traces = []
    full_wins = 0
    done = 0
    with ProcessPoolExecutor(args.workers) as pool:
        futs = [pool.submit(_collect_episode_v70, t) for t in tasks]
        for f in as_completed(futs):
            done += 1
            item, tr, wf = f.result()
            if wf:
                full_wins += 1
            if item is not None:
                x, yw, yh, ruid = item
                all_x.append(x)
                all_yw.append(yw)
                all_yh.append(yh)
                all_uid.append(ruid)
            if tr is not None:
                saved_traces.append(tr)
            if done % max(1, len(tasks) // 10) == 0 or done == len(tasks):
                n_a3 = sum(1 for t in saved_traces if t[3])
                n_k = sum(1 for t in saved_traces if t[2])
                print(
                    f"  Full [{done}/{len(tasks)}] -> {sum(len(a) for a in all_yw):,} leaves | "
                    f"A3_openings={n_a3} | Kaiser={n_k} | full_wins={full_wins}",
                    flush=True,
                )

    a3_traces = [tr for tr in saved_traces if tr[3]]
    k_traces = [tr for tr in saved_traces if tr[2] and not tr[3]]

    # Reserve 25% of Act 3 openings (up to 120) as HELD-OUT Act 3 Victory Bakeoff set (NEVER trained on!)
    n_eval_a3 = min(2 if args.smoke else 120, max(1 if args.smoke else 0, len(a3_traces) // 4))
    a3_eval_traces = a3_traces[:n_eval_a3]
    a3_train_traces = a3_traces[n_eval_a3:]
    eval_uids = {int(Path(p).stem.rsplit("_u", 1)[1]) for p, _, _, _ in a3_eval_traces}
    print(
        f"  Split Act 3 openings: train={len(a3_train_traces)}, held-out bakeoff={len(a3_eval_traces)} (strictly excluded from training!)",
        flush=True,
    )

    # ---------------- STAGE B: Heavy 8x Act 3 Curriculum Forks + 2x Kaiser Forks ----------------
    fork_tasks = []
    a3_fork_bundles = (b_v5b_ks, b_v5c_pure, b_ww35, b_ww60, b_pot5, b_pot9, b_hyb3, b_hyb2)
    if args.smoke:
        a3_fork_bundles = (b_v5b_ks, b_v5c_pure)
    for path_s, row, _, _ in a3_train_traces:
        base_uid = int(Path(path_s).stem.rsplit("_u", 1)[1])
        for bnd in a3_fork_bundles:
            fork_tasks.append((bnd, row, base_uid, None, path_s, 3))
    for path_s, row, _, _ in k_traces[: (4 if args.smoke else 300)]:
        base_uid = int(Path(path_s).stem.rsplit("_u", 1)[1])
        for bnd in (b_v5b_ks, b_v5c_pure):
            fork_tasks.append((bnd, row, base_uid, None, path_s, 2))

    print(
        f"\n================ STAGE B: {len(fork_tasks)} CURRICULUM FORKS ({len(a3_train_traces)} A3 x{len(a3_fork_bundles)}) ================",
        flush=True,
    )
    f_done = 0
    f_err = 0
    fork_wins = 0
    with ProcessPoolExecutor(args.workers) as pool:
        futs = [pool.submit(_collect_episode_v70, t) for t in fork_tasks]
        for f in as_completed(futs):
            f_done += 1
            try:
                item, _, wf = f.result()
                if wf:
                    fork_wins += 1
                if item is not None:
                    x, yw, yh, ruid = item
                    all_x.append(x)
                    all_yw.append(yw)
                    all_yh.append(yh)
                    all_uid.append(ruid)
            except Exception:
                f_err += 1
            if f_done % max(1, max(1, len(fork_tasks)) // 8) == 0 or f_done == len(fork_tasks):
                print(
                    f"  Forks [{f_done}/{len(fork_tasks)}] (err={f_err}, fork_wins={fork_wins}) -> "
                    f"{sum(len(a) for a in all_yw):,} new leaves",
                    flush=True,
                )

    X = np.concatenate(all_x, axis=0)
    y_win = np.concatenate(all_yw, axis=0)
    y_hp = np.concatenate(all_yh, axis=0)
    run_id = np.concatenate(all_uid, axis=0)
    if eval_uids and not args.smoke:
        keep = ~np.isin(run_id, list(eval_uids))
        X, y_win, y_hp, run_id = X[keep], y_win[keep], y_hp[keep], run_id[keep]
    data_path = c_dir / "schema5_iter4_act3_dataset.npz"
    np.savez_compressed(data_path, X=X, y_win=y_win, y_hp=y_hp, run_id=run_id)
    new_stats = _stats_v70(X, y_win)
    collect_min = round((time.time() - t0) / 60.0, 2)
    print(f"  Saved {data_path} ({collect_min} min) | new_stats={new_stats} | wins={full_wins}+{fork_wins}", flush=True)

    # ---------------- STAGE C: Train combat_value_v5d.npz on RX 9070 XT GPU ----------------
    print("\n================ STAGE C: GPU TRAINING combat_value_v5d.npz (RX 9070 XT) ================", flush=True)
    t_gpu = time.time()
    data_args = []
    if not args.smoke:
        for prev in (S5_ITER1_DATA, S5_ITER2_DATA, S5_ITER3_DATA):
            if prev.exists():
                data_args.append(str(prev))
    data_args.append(str(data_path))

    out_model = (out / "smoke_v5d.npz") if args.smoke else SCHEMA5D_MODEL_PATH
    train_report_path = c_dir / "schema5_v5d_train_report.json"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    py_exe = str(ROCM_PY) if ROCM_PY.exists() else str(MAIN_REPO / ".venv/cpu/Scripts/python.exe")
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
        "--kaiser-weight",
        "1.5",
        "--act3-weight",
        "2.5",
    ]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
    print(proc.stdout, flush=True)
    if proc.returncode != 0:
        print(proc.stderr, flush=True)
        raise RuntimeError(f"v5d GPU training failed: rc={proc.returncode}")
    train_report = json.loads(train_report_path.read_text(encoding="utf-8"))
    gpu_s = round(time.time() - t_gpu, 1)

    # ---------------- STAGE D: Held-Out Act 3 Victory Bakeoff ----------------
    print(
        f"\n================ STAGE D: HELD-OUT ACT 3 VICTORY BAKEOFF (N={len(a3_eval_traces)} A3 openings) ================",
        flush=True,
    )
    d_dir = out / "act3_bakeoff"
    db_dir = d_dir / "bundles"
    db_dir.mkdir(parents=True, exist_ok=True)
    bakeoff_bundles = {
        "v69_champ": b_champ,
        "v70_v5d_ks": build_v70_bundle(
            db_dir, "v70_v5d_ks", model_path=out_model, kaiser_scaling_v69=True, win_weight=15.0
        ),
        "v70_v5d_pure": build_v70_bundle(
            db_dir, "v70_v5d_pure", model_path=out_model, kaiser_pure_neural_v69=True, win_weight=15.0
        ),
        "v70_v5d_ww35": build_v70_bundle(
            db_dir, "v70_v5d_ww35", model_path=out_model, kaiser_scaling_v69=champ_kscale, kaiser_pure_neural_v69=champ_pure, win_weight=35.0
        ),
        "v70_v5d_pot5": build_v70_bundle(
            db_dir, "v70_v5d_pot5", model_path=out_model, kaiser_scaling_v69=champ_kscale, kaiser_pure_neural_v69=champ_pure, win_weight=25.0, potion_reserve=5.0
        ),
        "v70_v5d_hyb3": build_v70_bundle(
            db_dir, "v70_v5d_hyb3", model_path=out_model, kaiser_scaling_v69=champ_kscale, kaiser_pure_neural_v69=champ_pure, win_weight=25.0, human_ml_min_act=3
        ),
    }

    bakeoff_summary = {}
    best_v70_arm = "v70_v5d_ks"
    if a3_eval_traces:
        jobs = [
            (arm, bnd, path_s, row)
            for path_s, row, _, _ in a3_eval_traces
            for arm, bnd in bakeoff_bundles.items()
        ]
        by_arm: dict[str, list[dict]] = {arm: [] for arm in bakeoff_bundles}
        with ProcessPoolExecutor(args.workers) as pool:
            for rec in pool.map(_eval_act3_fork, jobs):
                by_arm[rec["arm"]].append(rec)
        best_score = -1e9
        for arm, rows_a in by_arm.items():
            n = len(rows_a)
            m_fl = sum(r["a3_floor"] for r in rows_a) / max(1, n)
            n_boss = sum(r["reached_boss"] for r in rows_a)
            n_b1 = sum(r["boss1_clear"] for r in rows_a)
            n_win = sum(r["win"] for r in rows_a)
            mm = sum(r["mm"] for r in rows_a)
            b_counts: dict[str, list[int]] = {}
            for r in rows_a:
                for form, w in r["bosses"]:
                    b_counts.setdefault(form, [0, 0])
                    b_counts[form][1] += 1
                    if w:
                        b_counts[form][0] += 1
            score = m_fl + 3.0 * (n_b1 / max(1, n)) + 10.0 * (n_win / max(1, n))
            bakeoff_summary[arm] = {
                "n": n,
                "mean_a3_floor": round(m_fl, 3),
                "reached_boss": n_boss,
                "boss1_clears": n_b1,
                "full_wins": n_win,
                "mm": mm,
                "bosses": b_counts,
                "score": round(score, 4),
            }
            print(
                f"  [{arm:14s}] A3_fl={m_fl:.2f} | BossEntry={n_boss}/{n} | Boss1Clear={n_b1} | FullWin={n_win} | mm={mm} | {b_counts}",
                flush=True,
            )
            if arm != "v69_champ" and score > best_score:
                best_score = score
                best_v70_arm = arm
    print(f"  -> Selected best v70 Act 3 arm for CSV28DEV: {best_v70_arm}", flush=True)

    # Free raw traces now that bakeoff is done
    shutil.rmtree(tr_dir, ignore_errors=True)

    # ---------------- STAGE E: Blind Full-Run Paired CSV28DEV (N=512 paired lobbies!) ----------------
    print(f"\n================ STAGE E: BLIND CSV28DEV (N={2*csv28_pairs} paired lobbies) ================", flush=True)
    e_dir = out / "csv28dev"
    eb_dir = e_dir / "bundles"
    eb_dir.mkdir(parents=True, exist_ok=True)
    final_bundles = {
        "ctrl_v67": build_part2_bundle(eb_dir, "ctrl_v67"),
        "v69_champ": b_champ,
        best_v70_arm: bakeoff_bundles[best_v70_arm],
    }
    if best_v70_arm != "v70_v5d_ks":
        final_bundles["v70_v5d_ks"] = bakeoff_bundles["v70_v5d_ks"]
    elif "v70_v5d_pure" in bakeoff_bundles:
        final_bundles["v70_v5d_pure"] = bakeoff_bundles["v70_v5d_pure"]

    rows_28 = make_cohort("CSV28DEV", csv28_pairs)
    t_e = time.time()
    ev = run_paired_panel(e_dir, final_bundles, rows_28, args.workers)
    ev["elapsed_min"] = round((time.time() - t_e) / 60.0, 2)

    recs = {
        arm: [
            json.loads(gzip.decompress((e_dir / arm / (seed + ".json.gz")).read_bytes()))
            for _, seed, _ in rows_28
        ]
        for arm in final_bundles
    }
    ev["paired_vs_v69"] = {
        arm: paired(recs["v69_champ"], recs[arm]) for arm in final_bundles if arm not in ("ctrl_v67", "v69_champ")
    }
    a3_b = {}
    for arm, rlist in recs.items():
        c = Counter()
        w = Counter()
        for r in rlist:
            for lf in r.get("late_fights", []):
                if lf[0] == 3 and lf[2] == "Boss":
                    c[lf[3]] += 1
                    if lf[5]:
                        w[lf[3]] += 1
        a3_b[arm] = {k: [w[k], c[k]] for k in sorted(c)}
    ev["act3_bosses"] = a3_b

    for arm, s in ev["summaries"].items():
        print(
            f"  [{arm:14s}] floor={s['mean_floor']:.3f} A1={s['a1_clears']}/{s['n']} "
            f"A2={s['a2_clears']}/{s['a2_entries']} A3={s['a3_entries']} W={s['wins']} "
            f"mm={s['native'].get('mismatch', 0)} | A2b={s['bosses']} | A3b={a3_b[arm]}",
            flush=True,
        )
    for arm, p in ev["paired"].items():
        print(
            f"  vs ctrl_v67 | {arm:14s}: delta={p['delta']:+.3f} CI95={p['ci95']} W/L/T={p['w']}/{p['l']}/{p['t']} p={p['sign_p']:.5f}",
            flush=True,
        )
    for arm, p in ev["paired_vs_v69"].items():
        print(
            f"  vs v69_champ| {arm:14s}: delta={p['delta']:+.3f} CI95={p['ci95']} W/L/T={p['w']}/{p['l']}/{p['t']} p={p['sign_p']:.5f}",
            flush=True,
        )

    summary = {
        "smoke": args.smoke,
        "champ_base": args.champ,
        "best_v70_arm": best_v70_arm,
        "total_elapsed_min": round((time.time() - t0) / 60.0, 2),
        "collect_min": collect_min,
        "gpu_train_s": gpu_s,
        "full_episodes": len(tasks),
        "curriculum_forks": len(fork_tasks),
        "fork_errors": f_err,
        "collection_wins": {"full": full_wins, "forks": fork_wins},
        "new_stats": new_stats,
        "train_report": train_report,
        "act3_bakeoff": bakeoff_summary,
        "csv28dev": ev,
    }
    if not args.smoke:
        (ROOT / "docs/combat-search-v2/v70-act3-overnight-summary.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )
        lines = [
            f"# v7.0 Overnight Act 3 Victory Push (`{summary['total_elapsed_min']:.1f} min`)",
            "",
            f"- **Collection:** `{len(tasks)}` full runs + `{len(fork_tasks)}` Act 3/Kaiser forks (`0`? err=`{f_err}`), collection wins=`{full_wins}+{fork_wins}`.",
            f"- **New Act 3 leaves:** `{new_stats}` -> combined **`{train_report['samples']['total']:,}`** 420-dim leaves.",
            f"- **RX 9070 XT GPU (`{gpu_s}s`):** widths `{train_report['selected']['widths']}`, test `{train_report['selected']['test']}`, `act3={train_report['test_slices'].get('act3')}`, `a3_boss={train_report['test_slices'].get('a3_boss')}`, parity `{train_report['parity_max_diff']:.2e}`.",
            f"- **Model:** `{train_report['path']}` (`sha256={train_report['sha256']}`).",
            "",
            f"## Stage D · Held-Out Act 3 Victory Bakeoff (`N = {len(a3_eval_traces)}` Act 3 openings)",
            "| Arm | Mean A3 Floor | Reached Boss | Boss 1 Clears | Full A10 Wins | Mismatches |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for arm, b in bakeoff_summary.items():
            lines.append(
                f"| `{arm}` | {b['mean_a3_floor']:.3f} | {b['reached_boss']}/{b['n']} | {b['boss1_clears']} | **{b['full_wins']}** | {b['mm']} |"
            )
        lines += [
            "",
            f"## Stage E · Blind Full-Run `CSV28DEV` (`N = {2*csv28_pairs}` paired lobbies)",
            "| Arm | Mean Floor | A1 Clears | A2 Boss | A3 Entries | Full Wins | Mismatches | Delta vs ctrl_v67 | Delta vs v69_champ |",
            "|---|---:|---:|---:|---:|---:|---:|---|---|",
        ]
        for arm, st in ev["summaries"].items():
            p0 = ev["paired"].get(arm)
            p0_s = f"{p0['delta']:+.3f} (p={p0['sign_p']:.4f})" if p0 else "—"
            p69 = ev["paired_vs_v69"].get(arm)
            p69_s = f"{p69['delta']:+.3f} (p={p69['sign_p']:.4f})" if p69 else "—"
            lines.append(
                f"| `{arm}` | {st['mean_floor']:.3f} | {st['a1_clears']}/{st['n']} | {st['a2_clears']}/{st['a2_entries']} | {st['a3_entries']} | **{st['wins']}** | {st['native'].get('mismatch', 0)} | {p0_s} | {p69_s} |"
            )
        lines.append("")
        (ROOT / "docs/combat-search-v2/v70-act3-overnight-report.md").write_text(
            "\n".join(lines), encoding="utf-8"
        )
        print(f"\nACT 3 OVERNIGHT PUSH COMPLETE! ({summary['total_elapsed_min']:.1f} min)", flush=True)
    else:
        print(f"\nACT 3 OVERNIGHT SMOKE PASSED CLEANLY! ({summary['total_elapsed_min']:.2f} min)", flush=True)


if __name__ == "__main__":
    main()
