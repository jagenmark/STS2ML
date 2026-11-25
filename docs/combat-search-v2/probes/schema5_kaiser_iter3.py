"""Schema 5 Iteration 3 (Kaiser Crab Focus) on Helmer (~1.5h total):

Fixes the 2-arm Kaiser Crab `facing` collector bug (which previously dropped 100% of
2-arm Kaiser turns from Schema 4 & Schema 5 training!), collects ~2,400 fresh full runs +
heavy 3x Kaiser Crab Act 2 curriculum forks across diverse scaling/defensive policies,
combines with Iter 1 + Iter 2 (~410k total 420-dim leaves), trains `combat_value_v5c.npz`
on RX 9070 XT GPU (`--kaiser-weight 4.0`), and evaluates on BOTH:
  1. The 95 identical CSV24CONF Kaiser Crab openings (`v68_v5b` vs `v69_v5c_kscale` vs `v69_v5c_pure`)
  2. Blind `CSV25DEV` (`N=256` paired lobbies: `ctrl_v67` vs `v68_v5b` vs `v69_v5c_kscale` vs `v69_v5c_pure`)
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

from kaiser_scaling_probe import _project_for_eot_fixed
from overnight_v68 import MAIN_REPO, ROCM_PY, make_cohort, run_paired_panel
from overnight_v68_part2 import build_part2_bundle
from report_v64 import paired
from schema5_iter2 import S5_ITER1_DATA, SCHEMA5B_MODEL_PATH
from sts2rl.combat_search_v2.end_turn import resolve as resolve_eot
from sts2rl.combat_search_v2.features import SCHEMA5_NAMES, extract_leaf_features
from sts2rl.combat_search_v2.state import Unsupported
from sts2rl.combat_search_v2.transitions import admission
from sts2rl.run_bundle import freeze_bundle, load_bundle
from sts2rl.run_evaluation import play_episode
from sts2rl.run_policy import RunWeights
from v64 import ROOT

S5_ITER2_DATA = MAIN_REPO / "artifacts" / "v68-schema5-iter2-20261125" / "collect" / "schema5_iter2_dataset.npz"
SCHEMA5C_MODEL_PATH = ROOT / "docs" / "combat-search-v2" / "models" / "combat_value_v5c.npz"


def build_v69_bundle(
    out: Path,
    name: str,
    *,
    model_path: Path | None,
    use_pimc: bool = True,
    value_v68: bool = True,
    kaiser_scaling_v69: bool = False,
    kaiser_pure_neural_v69: bool = False,
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
    if use_pimc:
        cfg["draw_pimc_v68"] = True
        cfg["pimc_samples"] = 6
    if value_v68:
        cfg["value_v68"] = True
    if kaiser_scaling_v69:
        cfg["kaiser_scaling_v69"] = True
    if kaiser_pure_neural_v69:
        cfg["kaiser_pure_neural_v69"] = True
    if model_path is not None:
        cfg["value_win_weight"] = float(win_weight)
        opts["combat_value_v2"] = model_path
    cfg_path = out / f"{name}_cfg.json"
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8", newline="\n")
    opts["combat_search_v2_config"] = cfg_path
    return freeze_bundle({"args": {**opts, "roles": [role]}}, out / name)


def _collect_episode_s5_kaiser(args):
    """Run one episode with FIXED Kaiser facing tracking, saving Act 2 traces when Kaiser Crab appears."""
    bundle, row, run_uid, trace_dir, start_trace, start_act = args
    i, seed, mode = row
    role, opts = load_bundle(bundle)

    xs: list[np.ndarray] = []
    yws: list[float] = []
    yhs: list[float] = []
    pending_fight: list[np.ndarray] = []
    in_fight = False
    facing = None
    last_max_hp = 70.0
    saw_kaiser = False

    def hook(state, action):
        nonlocal in_fight, facing, last_max_hp, pending_fight, saw_kaiser
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
        in_fight = now_combat

        if now_combat and "target_index" in action.args:
            facing = action.args["target_index"]

        if now_combat:
            ctx = state.get("context") or {}
            if ctx.get("act") == 2 and ctx.get("room_type") == "Boss":
                if any(e["id"].split(".")[-1] in ("CRUSHER", "ROCKET") for e in state.get("enemies") or ()):
                    saw_kaiser = True

        if now_combat and state.get("decision") == "combat_play" and action.kind == "end_turn":
            try:
                proj = _project_for_eot_fixed(state, facing=facing)
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
            if saw_kaiser or res.get("a2_clear"):
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


def _kaiser_stats(X: np.ndarray, yw: np.ndarray) -> dict:
    i_a1, i_a2, i_a3, i_b = [SCHEMA5_NAMES.index(k) for k in ("act.1", "act.2", "act.3", "room.Boss")]
    i_c = SCHEMA5_NAMES.index("s5.kaiser_crusher_hp")
    i_r = SCHEMA5_NAMES.index("s5.kaiser_rocket_hp")
    k_all = (X[:, i_c] > 0) | (X[:, i_r] > 0)
    k_2arm = (X[:, i_c] > 0) & (X[:, i_r] > 0)
    return {
        "total": int(len(X)),
        "a1": int((X[:, i_a1] > 0.5).sum()),
        "a2": int((X[:, i_a2] > 0.5).sum()),
        "a3": int((X[:, i_a3] > 0.5).sum()),
        "boss": int((X[:, i_b] > 0.5).sum()),
        "a2_boss": int(((X[:, i_a2] > 0.5) & (X[:, i_b] > 0.5)).sum()),
        "a3_boss": int(((X[:, i_a3] > 0.5) & (X[:, i_b] > 0.5)).sum()),
        "kaiser_all": int(k_all.sum()),
        "kaiser_2arm": int(k_2arm.sum()),
        "kaiser_2arm_wins": int(yw[k_2arm].sum()) if k_2arm.any() else 0,
    }


def collect_and_train(out: Path, full_per_arm: int, workers: int, epochs: int, smoke: bool) -> dict:
    t0 = time.time()
    print(
        f"\n================ SCHEMA 5 ITER 3 (KAISER FOCUS): {2*full_per_arm} FULL + KAISER FORKS ================",
        flush=True,
    )
    c_dir = out / "collect"
    b_dir = c_dir / "bundles"
    tr_dir = c_dir / "traces"
    b_dir.mkdir(parents=True, exist_ok=True)
    tr_dir.mkdir(parents=True, exist_ok=True)

    b_kscale = build_v69_bundle(
        b_dir, "v68_kscale", model_path=SCHEMA5B_MODEL_PATH, use_pimc=True, value_v68=True, kaiser_scaling_v69=True
    )
    b_base = build_v69_bundle(
        b_dir, "v68_base", model_path=SCHEMA5B_MODEL_PATH, use_pimc=True, value_v68=True, kaiser_scaling_v69=False
    )
    b_kscale_w40 = build_v69_bundle(
        b_dir,
        "v68_kscale_w40",
        model_path=SCHEMA5B_MODEL_PATH,
        use_pimc=True,
        value_v68=True,
        kaiser_scaling_v69=True,
        win_weight=40.0,
    )
    b_ctrl = build_part2_bundle(b_dir, "ctrl_v67")

    tasks = []
    uid = 0
    for i in range(full_per_arm):
        mode = "default" if i % 2 == 0 else "seeded"
        tasks.append((b_kscale, (i, f"S5I3K_{mode.upper()}_{i:04d}", mode), uid, str(tr_dir), None, 1))
        uid += 1
        tasks.append((b_ctrl, (i, f"S5I3C_{mode.upper()}_{i:04d}", mode), uid, str(tr_dir), None, 1))
        uid += 1

    all_x, all_yw, all_yh, all_uid = [], [], [], []
    saved_traces = []
    done = 0
    total = len(tasks)
    with ProcessPoolExecutor(workers) as pool:
        futs = [pool.submit(_collect_episode_s5_kaiser, t) for t in tasks]
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
                n_k = sum(1 for t in saved_traces if t[2])
                print(
                    f"  Full [{done}/{total}] -> {n_rows:,} leaves | kaiser_traces={n_k} total_traces={len(saved_traces)}",
                    flush=True,
                )

    # Heavy 3x Act 2 curriculum forks ONLY on Kaiser Crab openings + Act 3 openings!
    fork_tasks = []
    k_traces = [tr for tr in saved_traces if tr[2]]
    a3_traces = [tr for tr in saved_traces if tr[3]]
    for path_s, row, _, _ in k_traces:
        base_uid = int(Path(path_s).stem.rsplit("_u", 1)[1])
        for bnd in (b_kscale, b_base, b_kscale_w40, b_ctrl):
            fork_tasks.append((bnd, row, base_uid, None, path_s, 2))
    for path_s, row, _, _ in a3_traces:
        base_uid = int(Path(path_s).stem.rsplit("_u", 1)[1])
        for bnd in (b_kscale, b_base):
            fork_tasks.append((bnd, row, base_uid, None, path_s, 3))

    print(
        f"  Starting Phase B curriculum forks: {len(fork_tasks)} forks "
        f"(from {len(k_traces)} Kaiser A2 openings x4 + {len(a3_traces)} A3 openings x2)",
        flush=True,
    )
    f_done = 0
    f_err = 0
    with ProcessPoolExecutor(workers) as pool:
        futs = [pool.submit(_collect_episode_s5_kaiser, t) for t in fork_tasks]
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
    data_path = c_dir / "schema5_iter3_kaiser_dataset.npz"
    np.savez_compressed(data_path, X=X, y_win=y_win, y_hp=y_hp, run_id=run_id)
    new_stats = _kaiser_stats(X, y_win)
    collect_s = round(time.time() - t0, 1)
    print(f"  Saved {data_path} in {collect_s}s | new_stats={new_stats}", flush=True)

    data_args = []
    if not smoke:
        for prev in (S5_ITER1_DATA, S5_ITER2_DATA):
            if prev.exists():
                data_args.append(str(prev))
    data_args.append(str(data_path))

    t_gpu = time.time()
    train_report_path = c_dir / "schema5_iter3_train_report.json"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    py_exe = str(ROCM_PY) if ROCM_PY.exists() else str(MAIN_REPO / ".venv/cpu/Scripts/python.exe")
    out_model = (out / "smoke_v5c.npz") if smoke else SCHEMA5C_MODEL_PATH
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
        "4.0",
    ]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
    print(proc.stdout, flush=True)
    if proc.returncode != 0:
        print(proc.stderr, flush=True)
        raise RuntimeError(f"Schema 5 Iter 3 GPU training failed: rc={proc.returncode}")

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


def eval_csv25(out: Path, model_path: Path, pairs_per_mode: int, workers: int) -> dict:
    t0 = time.time()
    print(f"\n================ BLIND CSV25DEV (N={2*pairs_per_mode} paired lobbies) ================", flush=True)
    e_dir = out / "csv25dev"
    b_dir = e_dir / "bundles"
    b_dir.mkdir(parents=True, exist_ok=True)
    bundles = {
        "ctrl_v67": build_part2_bundle(b_dir, "ctrl_v67"),
        "v68_v5b": build_v69_bundle(
            b_dir, "v68_v5b", model_path=SCHEMA5B_MODEL_PATH, use_pimc=True, value_v68=True, win_weight=15.0
        ),
        "v69_v5c_kscale": build_v69_bundle(
            b_dir,
            "v69_v5c_kscale",
            model_path=model_path,
            use_pimc=True,
            value_v68=True,
            kaiser_scaling_v69=True,
            win_weight=15.0,
        ),
        "v69_v5c_pure": build_v69_bundle(
            b_dir,
            "v69_v5c_pure",
            model_path=model_path,
            use_pimc=True,
            value_v68=True,
            kaiser_pure_neural_v69=True,
            win_weight=15.0,
        ),
    }
    rows = make_cohort("CSV25DEV", pairs_per_mode)
    res = run_paired_panel(e_dir, bundles, rows, workers)
    res["elapsed_s"] = round(time.time() - t0, 1)

    recs = {
        arm: [
            json.loads(gzip.decompress((e_dir / arm / (seed + ".json.gz")).read_bytes()))
            for _, seed, _ in rows
        ]
        for arm in bundles
    }
    res["paired_vs_v5b"] = {
        arm: paired(recs["v68_v5b"], recs[arm]) for arm in ("v69_v5c_kscale", "v69_v5c_pure")
    }

    for arm, s in res["summaries"].items():
        print(
            f"  [{arm:15s}] floor={s['mean_floor']:.3f} A1={s['a1_clears']}/{s['n']} "
            f"A2={s['a2_clears']}/{s['a2_entries']} A3={s['a3_entries']} W={s['wins']} "
            f"mm={s['native'].get('mismatch', 0)} bosses={s['bosses']}",
            flush=True,
        )
    for arm, p in res["paired"].items():
        print(
            f"  vs ctrl_v67 | {arm:15s}: delta={p['delta']:+.3f} CI95={p['ci95']} W/L/T={p['w']}/{p['l']}/{p['t']} p={p['sign_p']:.4f}",
            flush=True,
        )
    for arm, p in res["paired_vs_v5b"].items():
        print(
            f"  vs v68_v5b  | {arm:15s}: delta={p['delta']:+.3f} CI95={p['ci95']} W/L/T={p['w']}/{p['l']}/{p['t']} p={p['sign_p']:.4f}",
            flush=True,
        )
    return res


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--full-per-arm", type=int, default=1200)
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
    epochs = 4 if args.smoke else 45
    csv25_pairs = 2 if args.smoke else 128

    col = collect_and_train(out, full_per_arm, args.workers, epochs, smoke=args.smoke)
    ev = eval_csv25(out, Path(col["model_path"]), csv25_pairs, args.workers)

    summary = {
        "smoke": args.smoke,
        "total_elapsed_min": round((time.time() - t0) / 60.0, 2),
        "collect_train": col,
        "csv25dev": ev,
    }
    if not args.smoke:
        (ROOT / "docs/combat-search-v2/v69-schema5-kaiser-iter3-summary.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )
        tr = col["train_report"]
        lines = [
            "",
            "---",
            "",
            f"# Part 7 · Schema 5 Iteration 3 Kaiser Crab Focus (`{tr['samples']['total']:,}` leaves, `{summary['total_elapsed_min']:.1f} min`)",
            f"- Fixed 2-arm Kaiser `facing` tracking: new Iter 3 stats `{col['new_stats']}` (`{col['full_episodes']}` full + `{col['curriculum_forks']}` forks, err={col['fork_errors']}).",
            f"- Trained on **{tr['device']}** in `{col['gpu_train_s']}s` (`kaiser_weight=4.0`): widths `{tr['selected']['widths']}`, test `{tr['selected']['test']}`, kaiser_2arm `{tr['test_slices'].get('kaiser_2arm')}`, parity `{tr['parity_max_diff']:.2e}`.",
            f"- Exported: `{tr['path']}` (`sha256={tr['sha256']}`).",
            "",
            "## Blind `CSV25DEV` (`N = 256` paired lobbies)",
            "| Arm | Mean Floor | A1 Clears | A2 Boss | A3 Entries | Wins | Delta vs ctrl_v67 (95% CI) | Delta vs v68_v5b |",
            "|---|---:|---:|---:|---:|---:|---|---|",
        ]
        for arm, st in ev["summaries"].items():
            p = ev["paired"].get(arm)
            p_str = (
                f"{p['delta']:+.3f} [{p['ci95'][0]:+.3f}, {p['ci95'][1]:+.3f}] (p={p['sign_p']:.4f})"
                if p
                else "—"
            )
            pb = ev["paired_vs_v5b"].get(arm)
            pb_str = f"{pb['delta']:+.3f} (p={pb['sign_p']:.4f})" if pb else "—"
            lines.append(
                f"| `{arm}` | {st['mean_floor']:.3f} | {st['a1_clears']}/{st['n']} | {st['a2_clears']}/{st['a2_entries']} | {st['a3_entries']} | {st['wins']} | {p_str} | {pb_str} |"
            )
        lines.append("")
        with (ROOT / "docs/combat-search-v2/v68-overnight-report.md").open("a", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        print(f"\nSCHEMA 5 KAISER ITER 3 COMPLETE! ({summary['total_elapsed_min']:.1f} min)", flush=True)
    else:
        print(f"\nSCHEMA 5 KAISER ITER 3 SMOKE PASSED CLEANLY! ({summary['total_elapsed_min']:.2f} min)", flush=True)


if __name__ == "__main__":
    main()
