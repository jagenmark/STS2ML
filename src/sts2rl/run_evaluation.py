"""Native Silent A10 episodes for policy search and paired evaluation."""
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import gzip
import json
from pathlib import Path
from time import monotonic

from .act1 import MacroPolicy, is_combat_choice, save_json
from .combat_search import CombatSearch
from .native import NativeSession, ReplayFork, digest
from .offer_policy import OfferModel, offer_type
from .run_policy import RunPolicy, RunWeights
from .routing import RoomModel
from .teacher import heuristic
from .turn_planning import choose_turn

_micro_cache = {}
_student_cache = {}


def inventory(state):
    player = state["player"]
    deck = player["deck"]
    return {"hp": player["hp"], "max_hp": player["max_hp"], "gold": player["gold"],
            "relics": len(player["relics"]), "potions": len(player["potions"]),
            "cards": sum(c.get("rarity") != "Basic" and c.get("type") not in ("Status", "Curse", "Quest") for c in deck),
            "upgrades": sum(c.get("upgrades", int(c.get("upgraded", False))) for c in deck)}


def verified_victory(boss_fights):
    return len({floor for act, floor in boss_fights if act == 3}) >= 2


def act2_start(trace):
    """Recover the first Act 2 map from a naturally played training episode."""
    with Path(trace).open(encoding="utf-8") as stream:
        spec = json.loads(next(stream))["command"]
        if spec.get("cmd") != "training_restore" or spec.get("history") or set(spec) != {"cmd", "history", "seed", "ascension"}:
            raise ValueError("A curriculum start requires an unmodified full run")
        commands, previous, last_row = [], None, -1
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
                    return ReplayFork({"seed": spec["seed"], "ascension": spec["ascension"]}, tuple(commands), previous)
                last_row = row
            commands.append(command)
            previous = record["response_digest"]
    raise ValueError("Trace contains no second-act map")


def play_episode(task):
    root, host, folder, seed, index, role, weights, checkpoint, options = task
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    row = {"seed": seed, "index": index, "role": role, "status": "error", "ascension": 10,
           "start_act": 2 if options.get("start_trace") else 1,
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
    feature_policy = RunPolicy(RunWeights(**weights)) if options.get("label_turns") else None
    search = None
    rooms = []
    try:
        student = None
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
        repeated = Counter()
        room = None
        with NativeSession(Path(root), folder / "game", ascension=10, host_path=host, timeout=15) as game:
            if options.get("start_trace"):
                fork = act2_start(options["start_trace"])
                if fork.specification["seed"] != seed or fork.specification["ascension"] != 10:
                    raise ValueError("Curriculum start identity mismatch")
                state = game.restore(fork)
                if state.get("context", {}).get("act") != 2 or state["decision"] != "map_select":
                    raise ValueError("Replay did not restore a native Act 2 opening")
                row["start_digest"] = fork.expected_digest
            else:
                state = game.reset(seed)
            for step in range(3000):
                if monotonic() - started > 180:
                    raise TimeoutError("Episode exceeded 180 seconds")
                ctx = state.get("context", {})
                act, floor = ctx.get("act", row["act"]), ctx.get("floor", row["floor"])
                if act != row["act"]:
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
                    turn_search and state["decision"] == "combat_play" and not use_student and micro is None) else None
                if state["decision"] == "map_select" and router is not None:
                    action = router.choose(state, game.public_map())
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
                if search is not None and state["decision"] == "combat_play":
                    action = search.choose(game, action, step)
                if teaching:
                    from .tactical_student import action_examples
                    groups, examples = action_examples(state, feature_policy)
                    if len(groups) > 1:
                        labels = {a.id: i for i, group in enumerate(groups) for a in group}
                        samples.append({"choices": examples, "label": labels[turn_action.id],
                                        "executed": labels[action.id]})
                if state["decision"] == "map_select" and options.get("rooms"):
                    point = next(p for p in state["choices"] if (p["col"], p["row"]) ==
                                 (action.args["col"], action.args["row"]))
                    room = {"act": act, "row": point["row"], "icon": point["type"], "before": inventory(state)}
                state = game.step(action)
            else:
                raise RuntimeError("Episode exceeded action budget")
    except Exception as exc:
        row.update(status="error", error=f"{type(exc).__name__}: {exc}")
    finally:
        if search is not None:
            search.close()
            row["search"] = {"roots": search.attempts, "branches": search.branches,
                             "changes": search.changes, "errors": search.errors}
    row["seconds"] = monotonic() - started
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
