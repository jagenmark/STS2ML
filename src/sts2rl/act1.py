"""Whole-Act-1 episodes, varied macro choices, coverage and sparse MC teaching."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import random
import time

from .native import ACT1_SAMPLER, CURRICULUM_SAMPLER, NativeError, NativeSession, digest, legal_actions, runtime_identity
from .teacher import equivalent_groups, heuristic, teach_root


def is_combat_choice(state):
    return state.get("decision") == "combat_play" or "combat_state" in state


def act1_profile(ascension=10, condition_ascension=False):
    runtime_identity(ascension)
    return CURRICULUM_SAMPLER if condition_ascension or ascension != 10 else ACT1_SAMPLER


def act1_result(state):
    act = state.get("context", {}).get("act", state.get("act", 1))
    if act > 1:
        return {"cleared_act1": True, "hp": state["player"]["hp"]}
    if state.get("decision") == "game_over":
        return {"cleared_act1": bool(state.get("victory")), "hp": state["player"]["hp"]}
    return None


def macro_record(state):
    """Project native rewards to the replay model's existing partial schema."""
    player, context = state["player"], state.get("context", {})
    def strip(s):
        return s.split(".", 1)[-1]
    candidates = []
    for action in legal_actions(state):
        card = next((c for c in state["cards"] if c["index"] == action.args.get("card_index")), None)
        candidates.append({"action_id": action.id, "kind": "pick_card" if card else "skip",
            "entity_id": strip(card["id"]) if card else None,
            "upgrades": card.get("upgrades", int(card.get("upgraded", False))) if card else None,
            "price": None})
    return {"schema_version": 1, "run_id": "native", "decision_id": digest(state),
        "source": "native", "game_version": "v0.111.0", "split_group": "native",
        "observation": {"character": "SILENT", "ascension": state["runtime_identity"]["ascension"], "decision_type": "card_reward",
            "act": context.get("act"), "floor": context.get("floor"),
            **{k: player.get(k) for k in ("hp", "max_hp", "gold")},
            "deck": [{"id": strip(c["id"]), "upgrades": c.get("upgrades", int(c.get("upgraded", False)))} for c in player["deck"]],
            "relics": [strip(r["id"]) for r in player["relics"]],
            "potions": [strip(p["id"]) for p in player["potions"]], "state_quality": "partial_native"},
        "candidates": candidates, "chosen_action_id": None, "outcome": None}


class MacroPolicy:
    def __init__(self, seed, checkpoint=None):
        self.rng = random.Random(seed)
        self.model = None
        if checkpoint:
            from .training import load_checkpoint
            self.model, self.vocab, meta = load_checkpoint(checkpoint, device="cpu")
            if meta["game_version"] != "v0.111.0":
                raise ValueError("Macro checkpoint patch mismatch")
        self.selection = None

    def __call__(self, state):
        actions = legal_actions(state)
        decision = state["decision"]
        player = state["player"]
        if decision == "card_reward" and self.model is not None:
            import torch
            from .encoding import collate_records
            from .schema import validate_record
            record = validate_record(macro_record(state))
            with torch.inference_mode():
                logits = self.model(collate_records([record], self.vocab))["policy_logits"][0]
                # Mostly learned reward choices, with some variation across runs.
                if self.rng.random() >= .15:
                    return actions[int(logits.argmax())]
        if decision == "map_select":
            hp = player["hp"] / player["max_hp"]
            def score(action):
                point = next(p for p in state["choices"] if p["col"] == action.args["col"] and p["row"] == action.args["row"])
                weights = {"RestSite": 9 if hp < .7 else 5, "Monster": 5, "Elite": 1 if hp < .8 else 4,
                           "Unknown": 4, "Shop": 5 if player["gold"] >= 100 else 1, "Treasure": 9}
                return weights.get(point["type"], 5) + self.rng.uniform(-2, 2)
            return max(actions, key=score)
        if decision == "rest_site":
            options = {o["index"]: o for o in state["options"]}
            heal = [a for a in actions if options.get(a.args.get("option_index"), {}).get("option_id") == "HEAL"]
            if heal and player["hp"] / player["max_hp"] < .75:
                return heal[0]
            others = [a for a in actions if a not in heal]
            self.selection = "upgrade"
            return others[0] if others else actions[0]
        if decision == "shop":
            relics = [a for a in actions if a.kind == "buy_relic"]
            if relics:
                return self.rng.choice(relics)
            cards = [a for a in actions if a.kind == "buy_card"]
            if cards and len(player["deck"]) < 24:
                return self.rng.choice(cards)
            return next(a for a in actions if a.kind == "leave_room")
        if decision == "card_select" and self.selection == "upgrade":
            self.selection = None
            neutralize = next((c for c in state["cards"] if c["id"] == "CARD.NEUTRALIZE"), None)
            if neutralize:
                best = next((a for a in actions if a.args.get("indices") == str(neutralize["index"])), None)
                if best:
                    return best
        return self.rng.choice(actions)


def save_json(path, data, *, best_effort=False):
    """Atomically replace JSON, tolerating short Windows reader/AV file locks.

    Telemetry can skip a write; durable results/configuration must still fail
    explicitly if the lock persists. Never truncate the last readable result.
    """
    path = Path(path)
    temporary = path.with_suffix(".tmp")
    payload = json.dumps(data, indent=2, allow_nan=False) + "\n"
    for attempt in range(8):
        try:
            temporary.write_text(payload, encoding="utf-8")
            temporary.replace(path)
            return True
        except PermissionError:
            if attempt == 7:
                if best_effort:
                    return False
                raise
            time.sleep(.01 * 2 ** attempt)


def existing_act1_results(output, runs, prefix, *, ascension=10, condition_ascension=False):
    """Reuse complete episodes; archive incomplete attempts before retrying.

    Call only after the previous runner exits. Archives stay inside this
    experiment; no partial teacher rows are mixed with their replacement run.
    """
    output = Path(output).resolve()
    complete, pending = [], []
    archive = output / "previous-attempts" / str(time.time_ns())
    for index in range(runs):
        folder = output / f"run-{index:05d}"
        if folder.exists():
            if not folder.resolve().is_relative_to(output):
                raise ValueError("Run folder resolves outside the experiment")
            result_file = folder / "result.json"
            result = json.loads(result_file.read_text(encoding="utf-8")) if result_file.exists() else {}
            if result.get("status") == "complete" and (folder / "teacher.jsonl").exists():
                if result.get("group") != digest(f"{prefix}{index:06d}") or result.get("index") != index:
                    raise ValueError("Existing run belongs to another seed/index")
                if result.get("ascension", 10) != ascension or result.get("sampler", ACT1_SAMPLER) != act1_profile(ascension, condition_ascension):
                    raise ValueError("Existing run belongs to another ascension/profile")
                complete.append(result)
                continue
            archive.mkdir(parents=True, exist_ok=True)
            folder.rename(archive / folder.name)
        pending.append(index)
    return complete, pending


def run_act1(root, output, index, *, prefix, samples=4, roots_per_fight=12, macro_checkpoint=None,
             micro_policy=None, teacher=True, query_probability=.35, max_branches=96, stop_file=None,
             ascension=10, condition_ascension=False, host_path=None, execute_teacher=True):
    if not execute_teacher and (micro_policy is None or not teacher):
        raise ValueError("Student-state labeling requires a student and teacher queries")
    profile = act1_profile(ascension, condition_ascension)
    folder = output / f"run-{index:05d}"
    folder.mkdir(parents=True, exist_ok=False)
    seed, group = f"{prefix}{index:06d}", digest(f"{prefix}{index:06d}")
    rng = random.Random(1931 + index)
    macro = MacroPolicy(7103 + index, macro_checkpoint)
    started = time.perf_counter()
    result = {"index": index, "group": group, "status": "running", "cleared_act1": False,
              "ascension": ascension, "sampler": profile,
              "collection_actor": "student" if not execute_teacher else "teacher_assisted" if teacher else "micro" if micro_policy else "heuristic",
              "teacher_overrides": 0, "teacher_disagreements": 0,
              "queried_actor_regret_sum": 0.0, "queried_actor_positive_regret": 0,
              "steps": 0, "decisions": 0, "branches": 0, "fights": 0, "max_floor": 0,
              "skipped_roots": {}, "search_errors": []}
    monsters, cards, relics, floors, taught = Counter(), Counter(), Counter(), Counter(), Counter()
    records = []
    game, search = None, None
    fight_key, fight_roots, turn_roots, search_number = None, 0, Counter(), 0
    try:
        native_args = {"ascension": ascension, "host_path": host_path}
        game = NativeSession(root, folder / "game", **native_args)
        if teacher:
            search = NativeSession(root, folder / "search-0", **native_args)
        state = game.reset(seed)
        repeated = Counter()
        for step in range(2048):
            result["steps"] = step
            result["max_floor"] = max(result["max_floor"], state.get("context", {}).get("floor", 0))
            end = act1_result(state)
            if end is not None:
                result.update(status="complete", **end)
                break
            if Path(stop_file or output / "STOP").exists():
                result["status"] = "stopped"
                break
            repeated[digest(state)] += 1
            if repeated[digest(state)] > 3:
                raise NativeError("Repeated state without progress")
            combat_choice = is_combat_choice(state)
            if combat_choice:
                view = state if state["decision"] == "combat_play" else state["combat_state"]
                key = (state.get("context", {}).get("floor"), tuple(e["id"] for e in view["enemies"]))
                # Floor is stable through deaths/spawns; do not reset label budget then.
                if fight_key is None or key[0] != fight_key[0]:
                    fight_key, fight_roots, turn_roots = key, 0, Counter()
                    result["fights"] += 1
                    monsters.update(e["id"] for e in view["enemies"])
                    cards.update(c["id"] for c in state["player"]["deck"])
                    relics.update(r["id"] for r in state["player"]["relics"])
                    floors[str(key[0])] += 1
                actions = legal_actions(state)
                action = micro_policy(state) if micro_policy else heuristic(state)
                support = state.get("act1_search_support", {})
                turn = view["round"]
                eligible = teacher and len(actions) > 1 and fight_roots < roots_per_fight and turn_roots[turn] < 2
                if eligible and (fight_roots == 0 or rng.random() < query_probability):
                    reason = None
                    if not support.get("supported"):
                        reason = "draw_knowledge_or_history"
                    elif len(equivalent_groups(state, actions)) * samples > max_branches:
                        reason = "branch_budget"
                    if reason:
                        result["skipped_roots"][reason] = result["skipped_roots"].get(reason, 0) + 1
                    else:
                        if search is None or search.closed:
                            search_number += 1
                            search = NativeSession(root, folder / f"search-{search_number}", **native_args)
                        try:
                            record = teach_root(search, game.fork(), state, samples=samples,
                                seed=81000000 + index * 10000 + step, profile=profile)
                            record.update(group=group, ascension=ascension, decision_index=step, floor=key[0],
                                          monster_ids=[e["id"] for e in view["enemies"]],
                                          actor_action_id=action.id, teacher_executed=execute_teacher)
                            result["teacher_disagreements"] += action.id != record["chosen_action_id"]
                            regret = record["estimates"][record["chosen_action_id"]]["mean_return"] - record["estimates"][action.id]["mean_return"]
                            record["actor_estimated_regret"] = regret
                            result["queried_actor_regret_sum"] += regret
                            result["queried_actor_positive_regret"] += regret > 1e-6
                            if execute_teacher:
                                action = next(a for a in actions if a.id == record["chosen_action_id"])
                                result["teacher_overrides"] += action.id != record["actor_action_id"]
                            record["executed_action_id"] = action.id
                            records.append(record)
                            fight_roots += 1
                            turn_roots[turn] += 1
                            taught.update(e["id"] for e in view["enemies"])
                            result["decisions"] += 1
                            result["branches"] += record["branches"]
                        except (NativeError, TimeoutError) as exc:
                            # Quarantine this root. An engine error is never an outcome label.
                            result["search_errors"].append({"step": step, "error": str(exc)})
                            search.close()
            else:
                fight_key = None
                action = macro(state)
            state = game.step(action)
            if step % 5 == 0 or (combat_choice and fight_roots):
                if not save_json(folder / "progress.json", {**result, "seconds": time.perf_counter() - started}, best_effort=True):
                    result["progress_write_failures"] = result.get("progress_write_failures", 0) + 1
        else:
            result["status"] = "truncated"
    except Exception as exc:
        result.update(status="error", error=f"{type(exc).__name__}: {exc}")
    finally:
        if game:
            game.close()
        if search:
            search.close()
    result.update(seconds=time.perf_counter() - started, monsters=dict(monsters), cards=dict(cards),
                  relics=dict(relics), floors=dict(floors), teacher_monsters=dict(taught))
    filename = "teacher.jsonl" if result["status"] == "complete" else "quarantined.jsonl"
    (folder / filename).write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    save_json(folder / "result.json", result)
    return result
