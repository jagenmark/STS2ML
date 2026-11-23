"""Validate all paired receipts and reproduce the v5.1 JSON report without a game install."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import gzip
import hashlib
import json
from pathlib import Path
import runpy
from statistics import mean
from tempfile import TemporaryDirectory

import numpy as np

from sts2rl.combat_effects import power
from sts2rl.deck_policy import deck_context
from sts2rl.deployed_controller import DeployedController
from sts2rl.native import NativeSession, canonical_json, digest
from sts2rl.run_evaluation import verified_victory
from sts2rl.run_policy import IDENTITY, _card_id
from sts2rl.strategy import strategy_kind

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence"
PANEL = EVIDENCE / "silent-a10-v51-dev-panel.json"
RECEIPTS = EVIDENCE / "silent-a10-v51-receipts.jsonl.gz"
REPORT = EVIDENCE / "silent-a10-v51-autopsy-fixes.json"
HOST = ROOT / "artifacts/v5-autopsy/native-host/src/Sts2Headless/bin/Curriculum/net9.0/Sts2Headless.dll"
BUNDLE = ROOT / "releases/silent-a10-v2-tactics/challenger/policy.json"
BOSSES = ("KAISER_CRAB_BOSS", "KNOWLEDGE_DEMON_BOSS", "THE_INSATIABLE_BOSS")
MILESTONES = ("a1_clear", "a2_entry", "a2_clear", "a3_entry", "win")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def historical_boss_hand(rec, totals, escape_available, escape_used):
    state = rec["before"]
    ctx = state["context"]
    if state["decision"] != "combat_play" or ctx["act"] != 2 or ctx["room_type"] != "Boss":
        return
    turn = state["round"]
    cmd = rec["action"]
    picked = next((_card_id(c) for c in state["hand"] if c["index"] == cmd["args"].get("card_index")), None)
    if ctx["boss"]["id"] == "THE_INSATIABLE_BOSS":
        if any(_card_id(c) == "FRANTIC_ESCAPE" and c["can_play"] for c in state["hand"]):
            escape_available.add(turn)
        if picked == "FRANTIC_ESCAPE":
            escape_used.add(turn)
        if (rec["next_decision"] == "game_over" and cmd["action"] == "end_turn"
                and any(power(e.get("powers"), "SANDPIT") == 1 for e in state["enemies"])):
            totals["fatal_sandpit_one"] += 1
            totals["escape_legal_in_fatal_turn"] += turn in escape_available
            totals["escape_legal_in_previous_turn"] += turn - 1 in escape_available
            totals["escape_played_in_previous_turn"] += turn - 1 in escape_used
    if ctx["boss"]["id"] == "KNOWLEDGE_DEMON_BOSS" and power(state.get("player_powers"), "SLOTH") and picked:
        totals["sloth_plays"] += 1
        basic = ("STRIKE_SILENT", "DEFEND_SILENT")
        if picked in basic:
            others = [c for c in state["hand"] if c["can_play"] and _card_id(c) not in basic]
            totals["sloth_basic"] += 1
            totals["sloth_basic_other_card_playable"] += bool(others)
            totals["sloth_basic_power_playable"] += any(c["type"] == "Power" for c in others)


def rescore_v5(directory):
    """Replay only stored public reward/event decisions, without starting native lobbies."""
    base, fixed = (DeployedController.from_bundle(BUNDLE) for _ in range(2))
    fixed.policy.v51_draft_fixes = fixed.policy.v51_macro_fixes = True
    cards = {"ACCELERANT", "ACCURACY", "PHANTOM_BLADES", "INFINITE_BLADES"}
    exposed = defaultdict(Counter)
    alternatives = defaultdict(Counter)
    scores = []
    events, fatal = Counter(), Counter()
    example = None
    for i in range(384):
        seed = f"V5DIAG_{i:04d}"
        result = json.loads((directory / seed / "result.json").read_bytes())
        lost_a2 = not result["a2_clear"] and any(act == 2 for act, _ in result["boss_fights"])
        available, used = set(), set()
        with gzip.open(directory / seed / "trace.gz") as stream:
            for rec in map(json.loads, stream):
                if lost_a2:
                    historical_boss_hand(rec, fatal, available, used)
                state = rec["before"]
                kind = strategy_kind(state)
                if kind == "card":
                    by_index = {c["index"]: _card_id(c) for c in state["cards"]}
                    offered = cards.intersection(by_index.values())
                    if not offered:
                        continue
                elif kind != "event" or not any(
                    o.get("text_key", "").endswith(".options.ORNATE") for o in state["options"]
                ):
                    continue
                state["runtime_identity"] = IDENTITY
                trace = {}
                a = base.strategy.choose(state, base.policy, base.offers, explanation=trace)
                if a.command() != rec["action"]:
                    raise ValueError(f"Frozen decision failed to match {seed} step {rec['step']}")
                b = fixed.strategy.choose(state, fixed.policy, fixed.offers)
                if kind == "event":
                    events["offered"] += 1
                    events["changed_to_plain"] += b.command() != a.command()
                    continue
                original = by_index.get(a.args.get("card_index"), "skip")
                changed = by_index.get(b.args.get("card_index"), "skip")
                for cid in offered:
                    exposed[cid]["offers"] += 1
                    exposed[cid]["frozen"] += cid == original
                    exposed[cid]["fixed_same_offer"] += cid == changed
                    if cid == changed:
                        alternatives[cid][original] += 1
                for card, option in zip(state["cards"], trace["options"]):
                    if _card_id(card) != "ACCELERANT":
                        continue
                    scores.append(option["total"])
                    if seed == "V5DIAG_0028" and state["context"]["floor"] == 12:
                        example = {
                            "seed": seed, "act": state["context"]["act"], "floor": 12,
                            "prior": option["prior"], "learned": option["strategy"], "total": option["total"],
                            "shop_grade_same_card_and_deck": base.deck_model.grade(
                                card, state["context"], deck_context(state["player"]["deck"])
                            ),
                        }
    if len(scores) != 132 or events["offered"] != 75 or example is None:
        raise ValueError("Incomplete historical diagnostic traces")
    return {"free_rewards": dict(exposed), "displaced_cards": dict(alternatives),
            "accelerant_frozen_score_range": [min(scores), max(scores)], "example": example,
            "this_or_that": events, "fatal_boss_plays": fatal}


def first_policy_change(job):
    """Compare both controllers on one public prefix and verify the baseline's full trajectory."""
    folder, row, arm = job
    opts = dict(macro_seed=7103 + row["index"])
    baseline = DeployedController.from_bundle(BUNDLE, **opts)
    candidate = DeployedController.from_bundle(folder / arm / "bundle/policy.json", **opts)
    trajectory = hashlib.sha256()
    first = None
    with TemporaryDirectory() as scratch, NativeSession(
        ROOT, Path(scratch) / "episode", host_path=HOST, act_list=row["act_list"]
    ) as game:
        state = game.reset(row["seed"])
        for step in range(row["steps"]):
            if state["decision"] == "game_over":
                break
            a = baseline.choose(state, game)
            if first is None:
                b = candidate.choose(state, game)
                if a.command() != b.command():
                    def choice(action):
                        if action.kind == "play_card":
                            return next(_card_id(c) for c in state["hand"] if c["index"] == action.args["card_index"])
                        if action.kind == "use_potion":
                            return next(p["id"] for p in state["player"]["potions"] if
                                        p["index"] == action.args["potion_index"])
                        if action.kind == "select_map_node":
                            return next(p["type"] for p in state["choices"] if
                                        (p["row"], p["col"]) == (action.args["row"], action.args["col"]))
                        if action.kind == "choose_option":
                            opt = next(o for o in state["options"] if o["index"] == action.args["option_index"])
                            return opt.get("option_id") or opt["text_key"].rsplit(".", 1)[-1]
                        return action.kind

                    first = {"step_zero_based": step, "snapshot": a.snapshot, "act": state["context"]["act"],
                             "floor": state["context"]["floor"], "hp": state["player"]["hp"],
                             "v5": choice(a), arm: choice(b)}
                    if arm == "boss":
                        first.update(boss_id=state["context"]["boss"]["id"], round=state["round"],
                                     sandpit=max(power(e.get("powers"), "SANDPIT") for e in state["enemies"]),
                                     sloth=power(state.get("player_powers"), "SLOTH"),
                                     playable_powers=[_card_id(c) for c in state["hand"]
                                                      if c["can_play"] and c["type"] == "Power"],
                                     search_fallback=candidate.combat_v2.last_fallback)
            trajectory.update(canonical_json([a.snapshot, a.command()]))
            after = game.step(a)
            baseline.observe(state, a, after)
            if first is None:
                candidate.observe(state, a, after)
            state = after
    return {"seed": row["seed"], "mode": row["act_list"], "first": first,
            "replay_matches_base": state["decision"] == "game_over" and state.get("victory") == row["win"]
            and trajectory.hexdigest() == row["trajectory_sha256"]}


def replay_victory(job):
    folder, row = job
    arm = row["arm"]
    bundle = BUNDLE if arm == "v5" else folder / arm / "bundle/policy.json"
    actor = DeployedController.from_bundle(bundle, macro_seed=7103 + row["index"])
    trajectory = hashlib.sha256()
    floors = set()
    with TemporaryDirectory() as scratch, NativeSession(
        ROOT, Path(scratch) / "episode", host_path=HOST, act_list=row["act_list"]
    ) as game:
        state = game.reset(row["seed"])
        for _ in range(3000):
            if state["decision"] == "game_over":
                break
            ctx = state["context"]
            if state["decision"] == "combat_play" and ctx["act"] == 3 and ctx["room_type"] == "Boss":
                floors.add(ctx["floor"])
            action = actor.choose(state, game)
            trajectory.update(canonical_json([action.snapshot, action.command()]))
            after = game.step(action)
            actor.observe(state, action, after)
            state = after
    return {"seed": row["seed"], "arm": arm, "act3_boss_floors": sorted(floors),
            "terminal_digest": digest(state), "native_victory": state.get("victory"),
            "matched": trajectory.hexdigest() == row["trajectory_sha256"]
            and state["decision"] == "game_over" and state.get("victory") is True and len(floors) >= 2}


def pack(folder, spec, historical):
    lock = json.loads((folder / "lock.json").read_bytes())
    if lock["prereg_sha256"] != sha(PANEL):
        raise ValueError("Experiment protocol mismatch")
    failures = sorted(str(p.relative_to(folder)) for p in folder.glob("*/*.failed-*.json"))
    header = {"lock": lock, "failed_attempts": failures, "v5_diagnostic_rescore": rescore_v5(historical)}
    raw = []
    changes = {"macro": [], "boss": []}
    victories = []
    for index, seed, mode in spec["panel"]:
        lobby = {}
        for arm in spec["arms"]:
            raw.append((folder / arm / (seed + ".json")).read_bytes())
            row = lobby[arm] = json.loads(raw[-1])
            validate_row((index, seed, mode, arm), row)
            if row["win"]:
                victories.append((folder, row))
        for arm, jobs in changes.items():
            if lobby["v5"]["trajectory_sha256"] != lobby[arm]["trajectory_sha256"]:
                jobs.append((folder, lobby["v5"], arm))
    with ProcessPoolExecutor(4) as pool:
        for arm, jobs in changes.items():
            header[arm + "_first_changes"] = list(pool.map(first_policy_change, jobs))
        header["victory_replays"] = list(pool.map(replay_victory, victories))
    raw.insert(0, canonical_json(header))
    return gzip.compress(b"\n".join(raw) + b"\n", compresslevel=9, mtime=0)


def validate_row(key, row):
    if (tuple(row[k] for k in ("index", "seed", "act_list", "arm")) != key
            or row["status"] != "complete" or row.get("abandoned") or row["ascension"] != 10
            or row["start_act"] != 1 or row["role"] != "candidate"):
        raise ValueError(f"Invalid lobby or pair identity at {key}")
    entry = any(a == 2 for a, _ in row["boss_fights"])
    a3_entry = any(a == 3 for a, _ in row["boss_fights"])
    if (entry != (row["a2_boss"] is not None) or (entry and row["a2_boss"] not in BOSSES)
            or (entry and not row["a1_clear"])
            or (row["a2_clear"] and not entry) or (a3_entry and not row["a2_clear"])
            or (row["win"] and not verified_victory(row["boss_fights"]))):
        raise ValueError(f"Invalid boss evidence at {key}")
    row.update(a2_entry=entry, a3_entry=a3_entry, global_floor=(row["act"] - 1) * 17 + row["floor"])


def read_verified(data, spec):
    header, *rows = map(json.loads, gzip.decompress(data).splitlines())
    if (header["lock"]["prereg_sha256"] != sha(PANEL)
            or header["lock"]["panel_sha256"] != digest(spec["panel"])
            or header["lock"]["bundles"]["v5"] != spec["baseline_manifest_sha256"]):
        raise ValueError("Receipt manifest differs from the frozen panel")
    expected = [(i, s, m, a) for i, s, m in spec["panel"] for a in spec["arms"]]
    if len(rows) != 1280 or len(expected) != len(rows):
        raise ValueError("Incomplete five-arm panel")
    for key, row in zip(expected, rows, strict=True):
        validate_row(key, row)
    wins = {(r["arm"], r["seed"]) for r in rows if r["win"]}
    replays = header["victory_replays"]
    if (len(replays) != len(wins) or {(r["arm"], r["seed"]) for r in replays} != wins
            or not all(r["matched"] for r in replays)):
        raise ValueError("Missing or unverified native two-boss victory replay")
    baseline_hashes = {r["seed"]: r["trajectory_sha256"] for r in rows if r["arm"] == "v5"}
    for arm in ("boss", "macro"):
        changed = {r["seed"] for r in rows if r["arm"] == arm and r["trajectory_sha256"] != baseline_hashes[r["seed"]]}
        controls = header[arm + "_first_changes"]
        if len(controls) != len(changed) or {r["seed"] for r in controls} != changed:
            raise ValueError(f"Missing paired first-decision audit for {arm}")
    return header, rows


def binary_pairs(base, arm, predicate):
    x = [bool(predicate(r)) for r in base]
    y = [bool(predicate(r)) for r in arm]
    return {"gain": sum(b and not a for a, b in zip(x, y, strict=True)),
            "loss": sum(a and not b for a, b in zip(x, y, strict=True)),
            "both": sum(a and b for a, b in zip(x, y, strict=True))}


def comparison(base, arm, spec):
    # Both arrays are aligned by the verified (index, literal seed, mode) keys.
    delta = np.array([r["global_floor"] - b["global_floor"] for b, r in zip(base, arm, strict=True)])
    rng = np.random.default_rng(spec["analysis"]["bootstrap_seed"])
    sums = np.zeros(10000)
    for mode in spec["analysis"]["strata"]:
        d = delta[[r["act_list"] == mode for r in base]]
        if len(d):
            sums += rng.choice(d, size=(len(sums), len(d))).sum(axis=1)
    boss_rows = {}
    for boss in BOSSES:
        entered = [r for r in arm if r["a2_boss"] == boss]
        common = [(a, b) for a, b in zip(base, arm, strict=True) if a["a2_boss"] == b["a2_boss"] == boss]
        boss_rows[boss] = {
            "entries": len(entered), "clears": sum(r["a2_clear"] for r in entered),
            "entry_hp_mean": mean(r["a2_hp"] for r in entered) if entered else None,
            "paired_entries": binary_pairs(base, arm, lambda r: r["a2_boss"] == boss),
            "paired_clears": binary_pairs(base, arm, lambda r: r["a2_boss"] == boss and r["a2_clear"]),
            "common_entries": len(common),
            "clear_gain_loss_among_common_entries": [
                sum(y["a2_clear"] and not x["a2_clear"] for x, y in common),
                sum(x["a2_clear"] and not y["a2_clear"] for x, y in common),
            ],
        }
    by_decision = Counter()
    fatal = Counter()
    for r in arm:
        by_decision.update(r["counts"])
        if r["a2_entry"] and not r["a2_clear"] and r["death"] and r["death"]["room"] == "Boss":
            fatal.update({k: v for k, v in r["counts"].items()
                          if k.startswith(("sandpit_", "escape_", "sloth_"))})
    return {
        "n": len(arm), "mean_floor": mean(r["global_floor"] for r in arm),
        "delta_floor": float(delta.mean()),
        "paired_floor_ci95": np.percentile(sums / len(arm), [2.5, 97.5]).tolist(),
        "floor_wlt": [int((delta > 0).sum()), int((delta < 0).sum()), int((delta == 0).sum())],
        "milestones": {k: sum(r[k] for r in arm) for k in MILESTONES},
        "paired_milestones": {k: binary_pairs(base, arm, lambda r: r[k]) for k in MILESTONES},
        "bosses": boss_rows,
        "decisions": dict(sorted(by_decision.items())),
        "decisions_in_fatal_a2_boss_fights": dict(sorted(fatal.items())),
        "identical_public_decision_hashes": sum(
            x["trajectory_sha256"] == y["trajectory_sha256"] for x, y in zip(base, arm, strict=True)
        ),
        "victories": [{k: r[k] for k in ("index", "seed", "act_list", "steps", "boss_fights", "trajectory_sha256")}
                      for r in arm if r["win"]],
    }


def macro_attribution(replays, rows):
    lookup = {(r["arm"], r["seed"]): r for r in rows}
    groups = defaultdict(list)
    for replay in replays:
        first = replay["first"]
        name = (f"{first['v5']} -> {first['macro']}" if first and replay["replay_matches_base"]
                else "unresolved public trajectory")
        base, macro = (lookup[a, replay["seed"]] for a in ("v5", "macro"))
        groups[name].append((base, macro))
    return {name: {"pairs": len(pairs),
                   "sum_floor_change": sum(y["global_floor"] - x["global_floor"] for x, y in pairs),
                   "floor_wlt": [sum(y["global_floor"] > x["global_floor"] for x, y in pairs),
                                 sum(y["global_floor"] < x["global_floor"] for x, y in pairs),
                                 sum(y["global_floor"] == x["global_floor"] for x, y in pairs)],
                   "a2_clear_change": sum(int(y["a2_clear"]) - int(x["a2_clear"]) for x, y in pairs)}
            for name, pairs in groups.items()}


def historical_audit():
    prior = json.loads((EVIDENCE / "silent-a10-v5-lategame-autopsy.json").read_bytes())["macros_all"]
    names = ("ACCELERANT", "ACCURACY", "PHANTOM_BLADES", "INFINITE_BLADES", "AFTERIMAGE",
             "WELL_LAID_PLANS", "TOOLS_OF_THE_TRADE", "SPEEDSTER", "CALCULATED_GAMBLE", "NOXIOUS_FUMES",
             "FOOTWORK", "CORROSIVE_WAVE", "MIRAGE", "SERPENT_FORM", "ENVENOM", "OUTBREAK", "ACROBATICS", "BACKFLIP")
    purchases = {k.upper().replace(" ", "_"): v for k, v in prior["items"]["buy_card"].items()}
    return {
        "source": "silent-a10-v5-lategame-autopsy.json", "free_and_paid": {
            name: {**prior["card_rewards"][name], "shop_buys": purchases.get(name, 0)} for name in names
        },
        "accelerant": {
            "free_dispatch": "StrategyModel unified draft, RunPolicy.card_value with deck_effects=false",
            "free_features": "generic Power setup; take:poison and take:poison-deck both zero",
            "free_first_cost_one_raw": 3.69012320825935,
            "free_first_cost_one_prior": -1.3011453483694146,
            "skip": 0, "shop_dispatch": "DeckPolicy.terms -> grade -> merchant_choice",
            "shop_scaling_before_act_and_cost": "accelerant * min(29, 1.45 * poison + 5 * noxious)",
        },
        "ornate": {"taken": 75, "removals": 32, "removal_gold": 3200, "plain_hp_cost": 6,
                   "plain_gold_observed_range": [41, 68]},
        "queen": {"queen_targets": 33, "torch_head_targets": 12,
                  "observed_power_on_torch_head": "POWER.MINION_POWER", "targeting_change": False},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-run", type=Path, help="Pack a complete collection in canonical seed/arm order")
    parser.add_argument("--v5-traces", type=Path, default=ROOT / "artifacts/v5-autopsy/V5DIAG",
                        help="Original historical traces for the same-offer audit when packing")
    args = parser.parse_args()
    spec = runpy.run_path(str(Path(__file__).with_name("collect-v51-autopsy.py")))["locked_experiment"]()
    data = pack(args.from_run, spec, args.v5_traces) if args.from_run else RECEIPTS.read_bytes()
    header, rows = read_verified(data, spec)
    tables = {}
    for name in ("all", *spec["analysis"]["strata"]):
        groups = {arm: [r for r in rows if r["arm"] == arm and (name == "all" or r["act_list"] == name)]
                  for arm in spec["arms"]}
        tables[name] = {arm: comparison(groups["v5"], group, spec) for arm, group in groups.items()}
    result = {
        "schema": 1, "collection": {k: header[k] for k in ("lock", "failed_attempts", "victory_replays")},
        "complete_episodes": len(rows), "host_sha256": spec["host_sha256"], "game_sha256": spec["game_sha256"],
        "preregistration": PANEL.name, "arms": spec["arms"], "analysis": spec["analysis"],
        "receipt_file": RECEIPTS.name, "receipt_sha256": hashlib.sha256(data).hexdigest(),
        "macro_first_divergence": macro_attribution(header["macro_first_changes"], rows),
        "boss_first_changes": header["boss_first_changes"],
        "historical_audit": {**historical_audit(), "same_state": header["v5_diagnostic_rescore"]}, "results": tables,
    }
    # This is an interpretation of the published experiment. A new collection needs its own review.
    if result["receipt_sha256"] == "a05f7fb1a2f58f9ba84f437d754eff525f229a4e9f303c4231390b2dd2f969fc":
        result["v6_recommendation"] = {
            "v51_boss_tactics": {
                "decision": "advance as v6 candidate",
                "basis": "Two paired Insatiable clear gains, no floor losses. Sloth basics increased and Demon clears were flat.",
            },
            "v51_draft_fixes": {
                "decision": "keep experimental and isolate Accelerant before promotion",
                "basis": "Free picks and Act 2 clears increased, while entries fell and the paired floor interval crosses zero.",
            },
            "v51_macro_fixes": {
                "decision": "keep off",
                "basis": "Clumsy removal spend fell by 500 gold with one lost Kaiser clear. Kindle tied on floors and all baseline Ancients were visited.",
            },
            "combined": "keep off given an uncertain floor gain and zero full victories across all arms",
        }
    if args.from_run:
        RECEIPTS.write_bytes(data)
    REPORT.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
