"""Fast paired diagnostic on all 95 Kaiser Crab seeds from CSV24CONF (~6 min on 12 workers):

Tests `kaiser_scaling_v69=True` (concave HP + full early-turn scaling valuation on Kaiser Crab)
on `v68_s5b_pimc` and verifies fixed 2-arm Kaiser `facing` tracking for Schema 5 leaf collection.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, replace
import gzip
import hashlib
import json
import os
from pathlib import Path
import runpy
from tempfile import TemporaryDirectory
import time

import numpy as np

from schema5_iter2 import SCHEMA5B_MODEL_PATH
from sts2rl.combat_search_v2.end_turn import resolve as resolve_eot
from sts2rl.combat_search_v2.features import SCHEMA5_NAMES, extract_leaf_features
from sts2rl.combat_search_v2.state import Unsupported, project
from sts2rl.combat_search_v2.transitions import admission
from sts2rl.run_bundle import freeze_bundle, load_bundle
from sts2rl.run_evaluation import play_episode
from sts2rl.run_policy import RunWeights
from v64 import ROOT


def build_v69_bundle(
    out: Path,
    name: str,
    *,
    model_path: Path | None,
    use_pimc: bool = True,
    value_v68: bool = True,
    kaiser_scaling_v69: bool = False,
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
    if model_path is not None:
        cfg["value_win_weight"] = float(win_weight)
        opts["combat_value_v2"] = model_path
    cfg_path = out / f"{name}_cfg.json"
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8", newline="\n")
    opts["combat_search_v2_config"] = cfg_path
    return freeze_bundle({"args": {**opts, "roles": [role]}}, out / name)


def _project_for_eot_fixed(state, facing=None):
    """Project live combat state with full v6.7 + late/v61/kaiser flags AND tracked Kaiser facing."""
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
        )
        proj = replace(proj, state=st)
    return proj


def _run_one(args):
    arm, bundle, seed, seeded, idx = args
    role, opts = load_bundle(bundle)
    in_fight = False
    facing = None
    kaiser_2arm_leaves = 0
    kaiser_1arm_leaves = 0
    kaiser_rejects = 0
    seen_kaiser = False
    kaiser_exit_hp = 0

    def hook(state, action):
        nonlocal in_fight, facing, kaiser_2arm_leaves, kaiser_1arm_leaves, kaiser_rejects, seen_kaiser, kaiser_exit_hp
        now_combat = bool(state.get("in_combat"))
        if in_fight and not now_combat and seen_kaiser and kaiser_exit_hp == 0:
            kaiser_exit_hp = int((state.get("player") or {}).get("hp", 0))
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

        ctx = state.get("context") or {}
        if now_combat and ctx.get("act") == 2 and ctx.get("room_type") == "Boss":
            enemies = state.get("enemies") or ()
            if any(e["id"].split(".")[-1] in ("CRUSHER", "ROCKET") for e in enemies):
                seen_kaiser = True
                if state.get("decision") == "combat_play" and action.kind == "end_turn":
                    try:
                        proj = _project_for_eot_fixed(state, facing=facing)
                        if not admission(proj):
                            resolved = resolve_eot(proj.state)
                            if resolved.outcome == "completed":
                                feat = extract_leaf_features(resolved, schema=5)
                                if np.isfinite(feat).all():
                                    living = sum(e.hp > 0 for e in resolved.enemies)
                                    if living >= 2:
                                        kaiser_2arm_leaves += 1
                                    else:
                                        kaiser_1arm_leaves += 1
                        else:
                            kaiser_rejects += 1
                    except (Unsupported, KeyError, ValueError, TypeError):
                        kaiser_rejects += 1
        return action

    with TemporaryDirectory() as tmp:
        res = play_episode(
            (
                ROOT,
                os.environ["CSV2DEV_HOST"],
                Path(tmp) / "ep",
                seed,
                idx,
                role,
                asdict(RunWeights.load(opts["weights"])),
                None,
                {**opts, "seeded_acts": seeded},
            ),
            decision_hook=hook,
        )
    act = int(res.get("act", 1))
    fl = int(res.get("floor", 0))
    global_floor = (act - 1) * 17 + fl
    return {
        "arm": arm,
        "seed": seed,
        "act": act,
        "floor": global_floor,
        "a1_clear": bool(res.get("a1_clear")),
        "a2_clear": bool(res.get("a2_clear")),
        "reached_kaiser": seen_kaiser,
        "kaiser_won": bool(seen_kaiser and res.get("a2_clear")),
        "kaiser_exit_hp": kaiser_exit_hp if (seen_kaiser and res.get("a2_clear")) else 0,
        "mm": int((res.get("native") or {}).get("mismatch", 0)),
        "k2_leaves": kaiser_2arm_leaves,
        "k1_leaves": kaiser_1arm_leaves,
        "k_rejects": kaiser_rejects,
    }


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

    # Pull all 95 seeds from CSV24CONF where v68_s5b_pimc reached Kaiser Crab!
    conf_dir = ROOT / "artifacts" / "v68-confirm-csv24conf-768"
    seeds = []
    for p in sorted((conf_dir / "v68_s5b_pimc").glob("*.json.gz")):
        r68 = json.loads(gzip.decompress(p.read_bytes()))
        if any("CRUSHER" in str(b) for b in r68.get("late_fights", [])):
            seed = p.stem.removesuffix(".json")
            seeds.append((seed, "SEEDED" in seed))
    print(f"Loaded {len(seeds)} CSV24CONF v68 Kaiser Crab seeds (identical openings!)", flush=True)

    t0 = time.time()
    out = args.output.resolve()
    b_dir = out / "bundles"
    b_dir.mkdir(parents=True, exist_ok=True)
    bundles = {
        "v68_base": build_v69_bundle(
            b_dir, "v68_base", model_path=SCHEMA5B_MODEL_PATH, use_pimc=True, value_v68=True, kaiser_scaling_v69=False
        ),
        "v68_kscale": build_v69_bundle(
            b_dir, "v68_kscale", model_path=SCHEMA5B_MODEL_PATH, use_pimc=True, value_v68=True, kaiser_scaling_v69=True
        ),
    }

    jobs = [
        (arm, bpath, seed, seeded, i)
        for i, (seed, seeded) in enumerate(seeds)
        for arm, bpath in bundles.items()
    ]
    rows_by_arm: dict[str, list[dict]] = {arm: [] for arm in bundles}
    done = 0
    with ProcessPoolExecutor(args.workers) as pool:
        futs = [pool.submit(_run_one, j) for j in jobs]
        for f in as_completed(futs):
            rec = f.result()
            rows_by_arm[rec["arm"]].append(rec)
            done += 1
            if done % 60 == 0 or done == len(jobs):
                print(f"  [{done}/{len(jobs)}]", flush=True)

    elapsed = round((time.time() - t0) / 60.0, 2)
    print(f"\n=== KAISER CRAB SCALING PROBE ({len(seeds)} seeds, {elapsed} min) ===", flush=True)
    summary = {"n_seeds": len(seeds), "elapsed_min": elapsed, "arms": {}}
    for arm, rows in rows_by_arm.items():
        k_ent = [r for r in rows if r["reached_kaiser"]]
        k_wins = [r for r in k_ent if r["kaiser_won"]]
        k2 = sum(r["k2_leaves"] for r in rows)
        k1 = sum(r["k1_leaves"] for r in rows)
        kr = sum(r["k_rejects"] for r in rows)
        mm = sum(r["mm"] for r in rows)
        mean_fl = sum(r["floor"] for r in rows) / len(rows)
        wr = 100.0 * len(k_wins) / max(1, len(k_ent))
        summary["arms"][arm] = {
            "mean_floor": round(mean_fl, 3),
            "kaiser_wins": len(k_wins),
            "kaiser_entries": len(k_ent),
            "kaiser_wr_pct": round(wr, 2),
            "mm": mm,
            "k2_leaves_collected": k2,
            "k1_leaves_collected": k1,
            "k_rejects": kr,
        }
        print(
            f"  [{arm:12s}] Kaiser={len(k_wins):2d}/{len(k_ent):2d} ({wr:5.1f}%) | "
            f"floor={mean_fl:.2f} | mm={mm} | 2-arm leaves={k2} (1-arm={k1}, rej={kr})",
            flush=True,
        )

    # Check exact seed-by-seed flips between v68_base and v68_kscale
    by_seed = {arm: {r["seed"]: r for r in rows} for arm, rows in rows_by_arm.items()}
    gained = [
        s for s in by_seed["v68_base"]
        if by_seed["v68_kscale"][s]["kaiser_won"] and not by_seed["v68_base"][s]["kaiser_won"]
    ]
    lost = [
        s for s in by_seed["v68_base"]
        if by_seed["v68_base"][s]["kaiser_won"] and not by_seed["v68_kscale"][s]["kaiser_won"]
    ]
    summary["v68_kscale_vs_base"] = {"gained": sorted(gained), "lost": sorted(lost)}
    print(f"  v68_kscale vs v68_base Kaiser flips: +{len(gained)} gained, -{len(lost)} lost", flush=True)
    if gained:
        print(f"    Gained: {gained[:10]}", flush=True)
    if lost:
        print(f"    Lost:   {lost[:10]}", flush=True)

    out_json = ROOT / "docs/combat-search-v2/v69-kaiser-scaling-probe.json"
    out_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Saved {out_json}", flush=True)
    assert len(SCHEMA5_NAMES) == 420


if __name__ == "__main__":
    main()
