"""Native Silent A10 episodes for policy search and paired evaluation."""
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import gzip
import json
from pathlib import Path
from time import monotonic

from .act1 import MacroPolicy, is_combat_choice, save_json
from .encounter_draft import WeakEncounterPool
from .boss_search import BossSearch
from .combat_search import CombatSearch
from .encounter import EncounterModel
from .deck_policy import DeckPolicy
from .native import NativeSession, ReplayFork, digest
from .offer_policy import OfferModel, offer_type
from .run_policy import RunPolicy, RunWeights
from .routing import RoomModel
from .teacher import heuristic
from .strategy import StrategyModel, strategy_kind
from .turn_planning import choose_turn

_micro_cache = {}
_student_cache = {}
_return_cache = {}


def inventory(state):
    player = state["player"]
    deck = player["deck"]
    return {"hp": player["hp"], "max_hp": player["max_hp"], "gold": player["gold"],
            "relics": len(player["relics"]), "potions": len(player["potions"]),
            "cards": sum(c.get("rarity") != "Basic" and c.get("type") not in ("Status", "Curse", "Quest") for c in deck),
            "upgrades": sum(c.get("upgrades", int(c.get("upgraded", False))) for c in deck)}


def verified_victory(boss_fights):
    return len({floor for act, floor in boss_fights if act == 3}) >= 2


def act_start(trace, target_act=2):
    """Recover the map before the first choice of a naturally reached later act."""
    if target_act not in (2, 3):
        raise ValueError("Expected an Act 2 or Act 3 curriculum opening")
    with Path(trace).open(encoding="utf-8") as stream:
        first = json.loads(next(stream))
        spec = first["command"]
        required = {"cmd", "history", "seed", "ascension"}
        if spec.get("cmd") != "training_restore" or set(spec) not in (required, required | {"act_list"}):
            raise ValueError("A curriculum start requires an unmodified full run")
        if target_act == 2 and spec["history"]:
            raise ValueError("An Act 2 start requires an unmodified full run")
        game_spec = {k: v for k, v in spec.items() if k not in ("cmd", "history")}
        commands = list(spec["history"])
        previous = first["response_digest"]
        act, last_row = 1, -1
        for command in commands:
            if command.get("cmd") != "action":
                raise ValueError("Unexpected control command in the curriculum history")
            if command.get("action") == "select_map_node":
                row = command["args"]["row"]
                act += int(row < last_row)
                last_row = row
        for line in stream:
            record = json.loads(line)
            command = record["command"]
            if command["cmd"] == "get_map":
                continue
            if command["cmd"] != "action":
                raise ValueError("Unexpected control command in a full-game training trace")
            if command["action"] == "select_map_node":
                row = command["args"]["row"]
                if row < last_row:
                    act += 1
                    if act == target_act:
                        return ReplayFork(game_spec, tuple(commands), previous)
                last_row = row
            commands.append(command)
            previous = record["response_digest"]
    raise ValueError(f"Trace contains no Act {target_act} map")


def act2_start(trace):
    return act_start(trace, 2)


def play_episode(task, *, decision_hook=None):
    """Run the deployed policy; an optional research hook can intervene at a public decision."""
    root, host, folder, seed, index, role, weights, checkpoint, options = task
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    row = {"act_list": "seeded" if options.get("seeded_acts") else "default", "act_names": [], "seed": seed, "index": index, "role": role, "status": "error", "ascension": 10,
           "start_act": options.get("curriculum_act", 2) if options.get("start_trace") else 1,
           "act": 0, "floor": 0, "a1_clear": False, "a2_clear": False, "win": False,
           "steps": 0, "boss_fights": [], "last_enemies": [], "boss_hp_fraction": None}
    started = monotonic()
    macro = MacroPolicy(7103 + index)
    policy = RunPolicy(RunWeights(**weights), macro_seed=7103 + index,
                       deck_effects=options.get("deck_effects", False) and role not in ("baseline", "prior"))
    late = (RunWeights.load(options["late_weights"]) if options.get("late_weights")
            and role not in ("baseline", "prior", "no-late") else None)
    micro = None
    samples = []
    strategy_samples = []
    draft_explanations = []
    feature_policy = RunPolicy(RunWeights(**weights)) if options.get("label_turns") else None
    if options.get("opening_partition"):
        row["opening_partition"] = options["opening_partition"]
    if feature_policy:
        from .provenance import planner_provenance
        row["feature_weights"] = weights
        row["late_teacher_weights"] = late.checkpoint()["weights"] if late else None
        row["teacher_deck_effects"] = policy.deck_effects
        row["label_provenance"] = planner_provenance(feature_policy.weights, late, policy.deck_effects)
    search = boss_search = None
    rooms = []
    try:
        student = None
        return_model = None
        if options.get("return_model") and role not in ("baseline", "prior", "original-combat"):
            import torch
            from .return_policy import ReturnPolicy
            torch.set_num_threads(1)
            path = options["return_model"]
            if path not in _return_cache:
                _return_cache[path] = ReturnPolicy(path)
            return_model = _return_cache[path]
        if role in ("student", "hybrid"):
            import torch
            from .tactical_student import TacticalStudent
            torch.set_num_threads(1)
            path = options["tactical_student"]
            if path not in _student_cache:
                _student_cache[path] = TacticalStudent(path)
            student = _student_cache[path]
        router = RoomModel.load(options["room_model"]) if options.get("room_model") and role not in (
            "baseline", "prior", "original-macro", "no-route") else None
        late_router = RoomModel.load(options["late_room_model"]) if options.get("late_room_model") and role not in (
            "baseline", "prior", "original-macro", "no-route") else None
        offers = OfferModel.load(options["offer_model"]) if options.get("offer_model") and role not in (
            "baseline", "prior", "original-macro", "no-offer") else None
        strategy = StrategyModel.load(options["strategy_model"]) if options.get("strategy_model") and role not in (
            "baseline", "prior", "original-macro") else None
        deck_model = DeckPolicy.load(options["deck_model"]) if options.get("deck_model") and role not in (
            "baseline", "prior", "original-macro") else None
        encounter = EncounterModel.load(options["encounter_model"]) if options.get("encounter_model") and role not in (
            "baseline", "prior", "original-combat") else None
        turn_search = options.get("turn_search") and role not in ("baseline", "prior", "original-combat", "no-turn")
        if options.get("combat_search") and role == "candidate":
            search = CombatSearch(Path(root), host, folder / "search", index, policy)
        if checkpoint:
            import torch
            from .micro import load_micro
            if checkpoint not in _micro_cache:
                _micro_cache[checkpoint] = load_micro(checkpoint, device="cpu")
                torch.set_num_threads(1)
            micro = _micro_cache[checkpoint]
        if options.get("boss_search") and role not in ("baseline", "prior", "original-combat"):
            boss_search = BossSearch(options["boss_search"], root, host, folder / "boss-search")
        repeated = Counter()
        room = None
        with NativeSession(Path(root), folder / "game", ascension=10, host_path=host, timeout=45, act_list=row["act_list"]) as game:
            if options.get("start_trace"):
                fork = act_start(options["start_trace"], row["start_act"])
                if fork.specification["seed"] != seed or fork.specification["ascension"] != 10:
                    raise ValueError("Curriculum start identity mismatch")
                state = game.restore(fork)
                if state.get("context", {}).get("act") != row["start_act"] or state["decision"] != "map_select":
                    raise ValueError("Replay did not restore the requested native act opening")
                row["start_digest"] = fork.expected_digest
            else:
                state = game.reset(seed)
            track_pool = (strategy and strategy.uses_matchups) or getattr(router, "act1_context", None)
            pool = WeakEncounterPool(state) if track_pool or options.get("explain_drafts") else None
            for step in range(3000):
                if monotonic() - started > 180:
                    raise TimeoutError("Episode exceeded 180 seconds")
                ctx = state.get("context", {})
                act, floor = ctx.get("act", row["act"]), ctx.get("floor", row["floor"])
                if act != row["act"]:
                    previous = row["act"]
                    row["act_names"].append(ctx.get("act_name"))
                    if previous and (act != previous + 1 or not any(b[0] == previous for b in row["boss_fights"])):
                        raise ValueError("Act transition lacks a recorded boss combat in the previous act")
                    row["floor"] = 0
                    if act >= 2 and late is not None:
                        policy.weights = late
                    if act >= 2 and late_router is not None:
                        router = late_router
                row.update(act=act, floor=max(floor, row["floor"]), steps=step)
                row["a1_clear"] |= act >= 2
                row["a2_clear"] |= act >= 3
                if room is not None and state["decision"] in ("game_over", "map_select"):
                    after = inventory(state)
                    died = state["decision"] == "game_over" and state.get("victory") is False
                    if died:
                        after["hp"] = 0
                    rooms.append({**room, "after": after, "died": died})
                    room = None
                if state.get("decision") == "game_over":
                    if type(state.get("victory")) is not bool:
                        raise ValueError("Missing native terminal result")
                    if state["victory"] and not verified_victory(row["boss_fights"]):
                        row["status"] = "unverified_victory"
                    else:
                        row.update(status="complete", win=state["victory"])
                        if state.get("abandoned"):
                            row["abandoned"] = True
                    break
                if state.get("decision") == "combat_play":
                    enemies = [e for e in state["enemies"] if e["hp"] > 0]
                    row["last_enemies"] = [e["id"] for e in enemies]
                    if ctx.get("room_type") == "Boss":
                        key = [act, floor]
                        if key not in row["boss_fights"]:
                            row["boss_fights"].append(key)
                        if enemies:
                            row["boss_hp_fraction"] = sum(e["hp"] for e in enemies) / max(1, sum(e["max_hp"] for e in enemies))
                fingerprint = digest(state)
                repeated[fingerprint] += 1
                if repeated[fingerprint] > 3:
                    raise RuntimeError("Repeated decision without progress")
                combat = is_combat_choice(state)
                use_student = student is not None and (role == "student" or act >= 2)
                teaching = options.get("label_turns") and state["decision"] == "combat_play"
                turn_action = choose_turn(state, policy) if teaching or (
                    turn_search and state["decision"] == "combat_play" and not use_student and micro is None
                    and not (encounter and encounter.applies(state))) else None
                if state["decision"] == "map_select" and router is not None:
                    if pool is not None and getattr(router, "act1_context", None):
                        action = router.choose(state, game.public_map(), normal_count=pool.normal_count)
                    else:
                        action = router.choose(state, game.public_map())
                elif encounter is not None and encounter.applies(state) and combat:
                    action = encounter.choose(state, policy)
                elif deck_model is not None and not combat and (state["decision"] in deck_model.scope or
                        (state["decision"] == "card_select" and (deck_model.to_upgrade or deck_model.prompt))):
                    action = deck_model.choose(state, policy)
                elif strategy is not None and strategy_kind(state) in strategy.kinds:
                    trace = {} if options.get("explain_drafts") and state["decision"] == "card_reward" else None
                    action = strategy.choose(state, policy, offers,
                                             group_probability=pool.group_probability if pool else None,
                                             explanation=trace)
                    if trace:
                        draft_explanations.append({"version": 1, "seed": seed, "step": step,
                                                   "state_digest": fingerprint,
                                                   "scorer_sha256": options.get("draft_scorer_sha256"),
                                                   "model_sha256": options.get("draft_model_hashes", {}), **trace})
                    if state["decision"] == "rest_site":
                        policy.selection = "upgrade" if any(o["index"] == action.args.get("option_index")
                            and o.get("option_id") == "SMITH" for o in state["options"]) else None
                elif use_student and state["decision"] == "combat_play":
                    action = student(state)
                elif combat and micro is not None:
                    action = micro(state)
                elif turn_search and state["decision"] == "combat_play":
                    action = turn_action
                elif offers is not None and offer_type(state):
                    action = offers.choose(state, policy)
                elif role == "baseline" or (role == "original-macro" and not combat) or (role == "original-combat" and combat):
                    action = heuristic(state) if combat else macro(state)
                else:
                    action = policy(state)
                if boss_search is not None and combat:
                    action = boss_search.choose(game, action, policy)
                if return_model is not None and state["decision"] == "combat_play":
                    evaluated = return_model.choose(state, action)
                    row["return_changes"] = row.get("return_changes", 0) + (evaluated.id != action.id)
                    action = evaluated
                if search is not None and state["decision"] == "combat_play":
                    action = search.choose(game, action, step)
                if decision_hook is not None:
                    action = decision_hook(state, action)
                if options.get("record_strategy") and (not combat or
                        (state["decision"] == "combat_play" and ctx.get("room_type") == "Boss"
                         and (not strategy_samples or strategy_samples[-1]["state"].get("context") != ctx))):
                    strategy_samples.append({"step": step, "state": state, "action": action.command()})
                if teaching:
                    from .tactical_student import action_examples
                    groups, examples = action_examples(state, feature_policy)
                    if len(groups) > 1:
                        labels = {a.id: i for i, group in enumerate(groups) for a in group}
                        samples.append({"choices": examples, "label": labels[turn_action.id],
                                        "act": act, "label_provenance": row["label_provenance"],
                                        "executed": labels[action.id]})
                if state["decision"] == "map_select" and options.get("rooms"):
                    point = next(p for p in state["choices"] if (p["col"], p["row"]) ==
                                 (action.args["col"], action.args["row"]))
                    room = {"act": act, "row": point["row"], "icon": point["type"], "before": inventory(state)}
                if deck_model is not None:
                    deck_model.observe(state, action)
                state = game.step(action)
                if pool is not None:
                    pool.observe(action.kind, state)
            else:
                raise RuntimeError("Episode exceeded action budget")
    except Exception as exc:
        row.update(status="error", error=f"{type(exc).__name__}: {exc}")
    finally:
        if boss_search is not None:
            boss_search.close()
            row["boss_search"] = boss_search.metrics
        if search is not None:
            search.close()
            row["search"] = {"roots": search.attempts, "branches": search.branches,
                             "changes": search.changes, "errors": search.errors}
    row["seconds"] = monotonic() - started
    if options.get("explain_drafts"):
        with gzip.open(folder / "draft-scores.jsonl.gz", "wt", encoding="utf-8") as stream:
            for trace in draft_explanations:
                stream.write(json.dumps(trace, separators=(",", ":")) + "\n")
    if options.get("record_strategy"):
        with gzip.open(folder / "strategy.jsonl.gz", "wt", encoding="utf-8", compresslevel=2) as stream:
            for sample in strategy_samples:
                stream.write(json.dumps(sample, separators=(",", ":")) + "\n")
    if options.get("label_turns"):
        with gzip.open(folder / "actions.jsonl.gz", "wt", encoding="utf-8", compresslevel=2) as stream:
            for sample in samples:
                stream.write(json.dumps(sample, separators=(",", ":")) + "\n")
        row["labeled_decisions"] = len(samples)
    if options.get("rooms"):
        row["rooms"] = rooms
    save_json(folder / "result.json", row)
    return row


def run_batch(pool: ProcessPoolExecutor, root, host, folder, specs, prefix, count, options=None, starts=None):
    tasks = []
    for i in range(count):
        seed = starts[i][0] if starts else f"{prefix}{i:04d}"
        episode_options = {**(options or {}), "start_trace": starts[i][1] if starts else None}
        for role, weights, checkpoint in specs:
            tasks.append((str(root), str(host), str(folder / role / f"run-{i:04d}"), seed, i,
                          role, weights, str(checkpoint) if checkpoint else None, episode_options))
    return list(pool.map(play_episode, tasks, chunksize=1))
