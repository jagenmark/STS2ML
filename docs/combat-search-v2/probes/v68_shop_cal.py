"""Blind CSV20DEV (N=256) test of calibrated human_ml_shop_scale (2.5 & 2.0) on hybrid_s4c."""

from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import runpy
import time

from overnight_v68 import make_cohort, run_paired_panel
from overnight_v68_part2 import build_part2_bundle
from schema4_iter3 import SCHEMA4C_MODEL_PATH
from sts2rl.human_ml_draft import DEFAULT_MODEL_PATH
from sts2rl.run_bundle import freeze_bundle, load_bundle
from v64 import ROOT


def build_hybrid_scaled(out: Path, name: str, *, shop_scale: float, win_weight: float = 15.0) -> Path:
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
    cfg["value_v68"] = True
    cfg["pimc_samples"] = 6
    cfg["value_win_weight"] = float(win_weight)
    cfg_path = out / f"{name}_cfg.json"
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8", newline="\n")
    opts["combat_search_v2_config"] = cfg_path
    opts["combat_value_v2"] = SCHEMA4C_MODEL_PATH

    deck = json.loads(opts["deck_model"].read_bytes())
    deck["human_ml_draft_v68"] = True
    deck["human_ml_scope"] = ["card_reward", "bundle_select", "shop"]
    deck["human_ml_card_reward_min_act"] = 2
    deck["human_ml_skip_bias"] = 0.0
    deck["human_ml_act_skip_bias"] = [0.0, 0.2, 0.2]
    deck["human_ml_shop_scale"] = float(shop_scale)
    deck_path = out / f"{name}_deck.json"
    deck_path.write_text(json.dumps(deck, indent=2) + "\n", encoding="utf-8", newline="\n")
    opts["deck_model"] = deck_path
    opts["human_ml_draft_model"] = DEFAULT_MODEL_PATH
    return freeze_bundle({"args": {**opts, "roles": [role]}}, out / name)


def shop_audit(run_dir: Path, arm: str, rows) -> dict:
    a1 = Counter()
    a2 = Counter()
    for _, seed, _ in rows:
        r = json.loads(gzip.decompress((run_dir / arm / (seed + ".json.gz")).read_bytes()))
        for act, _fl, kind, _cards, action, _args, _ in r["offers"]:
            if kind == "shop":
                if act == 1:
                    a1[action] += 1
                elif act == 2:
                    a2[action] += 1
    return {
        "a1": {k: a1[k] for k in ("buy_card", "buy_potion", "buy_relic", "remove_card")},
        "a2": {k: a2[k] for k in ("buy_card", "buy_potion", "buy_relic", "remove_card")},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--pairs-per-mode", type=int, default=128)
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
        "ctrl_s4c": build_part2_bundle(b_dir, "ctrl_s4c", schema4_path=SCHEMA4C_MODEL_PATH, win_weight=15.0),
        "hyb_s25": build_hybrid_scaled(b_dir, "hyb_s25", shop_scale=2.5, win_weight=15.0),
        "hyb_s20": build_hybrid_scaled(b_dir, "hyb_s20", shop_scale=2.0, win_weight=15.0),
    }
    rows = make_cohort("CSV20DEV", args.pairs_per_mode)
    print(f"=== CSV20DEV SHOP-SCALE CALIBRATION (N={len(rows)} paired lobbies) ===", flush=True)
    res = run_paired_panel(out, bundles, rows, args.workers)
    res["elapsed_min"] = round((time.time() - t0) / 60.0, 2)
    res["shop_audit"] = {arm: shop_audit(out, arm, rows) for arm in bundles}

    # Also compute paired deltas directly vs ctrl_s4c
    from report_v64 import paired

    recs = {
        arm: [
            json.loads(gzip.decompress((out / arm / (seed + ".json.gz")).read_bytes()))
            for _, seed, _ in rows
        ]
        for arm in bundles
    }
    res["paired_vs_s4c"] = {
        arm: paired(recs["ctrl_s4c"], recs[arm]) for arm in ("hyb_s25", "hyb_s20")
    }

    print(f"\n=== CSV20DEV RESULTS ({res['elapsed_min']} min) ===", flush=True)
    for arm, s in res["summaries"].items():
        sh = res["shop_audit"][arm]["a1"]
        print(
            f"  [{arm:10s}] floor={s['mean_floor']:.3f} A1={s['a1_clears']}/{s['n']} "
            f"A2={s['a2_clears']}/{s['a2_entries']} A3={s['a3_entries']} W={s['wins']} "
            f"mm={s['native'].get('mismatch', 0)} | A1shop={sh} | bosses={s['bosses']}",
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

    out_json = ROOT / "docs/combat-search-v2/v68-shop-cal-csv20dev.json"
    out_json.write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(f"Saved {out_json}", flush=True)


if __name__ == "__main__":
    main()
