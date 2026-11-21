"""Restore natural runs and export hash-verified combat openings before the act boss."""

import argparse
import gzip
import hashlib
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

from sts2rl.act1 import save_json
from sts2rl.native import NativeError, NativeSession, ReplayFork, digest
from sts2rl.run_evaluation import act_start

ROOT = Path(__file__).resolve().parents[1]


def opening(state, root, step, entry_action):
    alive = [e for e in state["enemies"] if e["hp"] > 0]
    return {
        "root": root,
        "step": step,
        "formation": "+".join(sorted(e["id"].removeprefix("MONSTER.") for e in alive)),
        "floor": state["context"]["floor"],
        "room": state["context"]["room_type"],
        "hp": state["player"]["hp"],
        "potions": len(state["player"]["potions"]),
        "entry_action": entry_action,
        "enemies": [
            {k: e.get(k) for k in ("id", "hp", "intents", "powers")} for e in state["enemies"]
        ],
    }


def act3_hands(trace, map_fork, host, tmp):
    """Restore each first playable hand, including fights reached through intermediate prompts."""
    history = list(map_fork.history)
    starts, errors = [], []
    spec = map_fork.specification
    with trace.open(encoding="utf-8") as stream:
        initial = json.loads(next(stream))["command"]["history"]
        if list(map_fork.history[: len(initial)]) != initial:
            raise ValueError("Physical resume prefix differs from the Act 3 map")
        skip = len(map_fork.history) - len(initial)
        previous, entry_action, pending = map_fork.expected_digest, None, False
        game = None
        try:
            for line in stream:
                r = json.loads(line)
                cmd = r["command"]
                if cmd["cmd"] == "get_map":
                    continue
                if cmd["cmd"] != "action":
                    raise ValueError("Unexpected control command in an Act 3 run")
                if skip:
                    skip -= 1
                    continue
                kind = cmd["action"]
                if kind == "select_map_node":
                    pending = True
                elif pending and kind in ("play_card", "end_turn", "use_potion"):
                    pending = False
                    fork = ReplayFork(spec, tuple(history), previous)
                    if game is None:
                        game = NativeSession(
                            ROOT,
                            tmp / str(len(history)),
                            host_path=host,
                            act_list=spec.get("act_list", "default"),
                            timeout=60,
                        )
                    try:
                        state = game.restore(fork)
                    except NativeError:
                        game.close()
                        game = NativeSession(
                            ROOT,
                            tmp / f"step-{len(history)}",
                            host_path=host,
                            act_list=spec.get("act_list", "default"),
                            timeout=60,
                        )
                        state = game.reset(spec["seed"])
                        for action in history:
                            state = game._request(action)
                        if digest(state) != previous:
                            errors.append({"root": previous, "step": len(history)})
                            state = {}
                    ctx = state.get("context") or {}
                    if (
                        state.get("decision") == "combat_play"
                        and state.get("round") == 1
                        and ctx.get("act") == 3
                        and ctx.get("room_type") in ("Monster", "Elite")
                    ):
                        starts.append(opening(state, previous, len(history), entry_action))
                history.append(cmd)
                previous, entry_action = r["response_digest"], kind
        finally:
            if game is not None:
                game.close()
    return history, starts, errors


def export(task):
    source, output, host, act = task
    result = json.loads((source / "result.json").read_bytes())
    trace = source / "game/rpc.jsonl"
    starts, history = [], []
    error = spec = None
    try:
        fork = act_start(trace, act)
        spec = fork.specification
        if spec["seed"] != result["seed"]:
            raise ValueError("Natural run seed mismatch")
        history = list(fork.history)
        if act == 3:
            with TemporaryDirectory() as tmp:
                history, starts, errors = act3_hands(trace, fork, host, Path(tmp))
                if errors:
                    error = f"Could not restore {len(errors)} individual hands: {errors}"
        else:
            act2_hands(trace, fork, host, history, starts)
    except (ValueError, RuntimeError, TimeoutError) as exc:
        error = str(exc)
    row = {
        "act": act,
        "seed": result["seed"],
        "source": source.parent.name + "/" + source.name,
        "specification": spec,
        "history": history[: max((s["step"] for s in starts), default=0)],
        "starts": starts,
        "error": error,
    }
    if not result["seed"].isalnum():
        raise ValueError("Unexpected seed filename")
    with gzip.open(output / (result["seed"] + ".json.gz"), "wt", encoding="utf-8") as f:
        json.dump(row, f, separators=(",", ":"))
    return len(starts)


def act2_hands(trace, fork, host, history, starts):
    act, spec = 2, fork.specification
    with (
        TemporaryDirectory() as tmp,
        NativeSession(
            ROOT, Path(tmp) / "game", host_path=host, act_list=spec.get("act_list", "default")
        ) as game,
        trace.open(encoding="utf-8") as stream,
    ):
        state = game.restore(fork)
        if state["decision"] != "map_select" or state["context"]["act"] != act:
            raise ValueError(f"Expected the map at the start of Act {act}")
        initial = json.loads(next(stream))["command"]["history"]
        if list(fork.history[: len(initial)]) != initial:
            raise ValueError("Resume trace and physical prefix disagree")
        offset = len(initial)
        active = False
        for line in stream:
            row = json.loads(line)
            cmd = row["command"]
            if cmd["cmd"] == "get_map":
                continue
            if cmd["cmd"] != "action":
                raise ValueError("Unexpected command in natural run")
            if offset < len(fork.history):
                offset += 1
                continue
            state = game._request(cmd)
            if digest(state) != row["response_digest"]:
                raise ValueError(f"Public state diverged at action {len(history) + 1}")
            history.append(cmd)
            ctx = state.get("context") or {}
            if (
                ctx.get("act") != act
                or ctx.get("room_type") == "Boss"
                or state["decision"] == "game_over"
            ):
                break
            if not state.get("in_combat"):
                active = False
            if state["decision"] != "combat_play" or active:
                continue
            active = True
            if ctx["room_type"] not in ("Monster", "Elite") or state["round"] != 1:
                continue
            starts.append(opening(state, row["response_digest"], len(history), cmd["action"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, nargs="+")
    for flag in ("output", "host", "seed-lock"):
        parser.add_argument("--" + flag, required=True, type=Path)
    parser.add_argument(
        "--diagnostic-selection",
        type=Path,
        help="Analyze the locked test cohort after freezing a challenger",
    )
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--act", type=int, choices=(2, 3), default=2)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    lock = json.loads(args.seed_lock.read_bytes())["seeds"]
    protected = set(lock["test"]) | set(lock["development"])
    cases = []
    seeds = set()
    test = set(lock["test"])
    observed = set()
    if args.diagnostic_selection:
        selection = json.loads(args.diagnostic_selection.read_bytes())
        if selection["seed_lock_sha256"] != hashlib.sha256(args.seed_lock.read_bytes()).hexdigest():
            raise ValueError("The frozen selection uses a different seed lock")
    for folder in args.source:
        for path in sorted(folder.glob("*/result.json" if args.act == 3 else "run-*/result.json")):
            row = json.loads(path.read_bytes())
            if args.diagnostic_selection and (row["seed"] not in test or row["seed"] in observed):
                raise ValueError("Unexpected or repeated seed in post-selection diagnostics")
            observed.add(row["seed"])
            if (
                row["status"] != "complete"
                or not row["a2_clear" if args.act == 3 else "a1_clear"]
                or row.get("opening_partition") == "test"
            ):
                continue
            if (not args.diagnostic_selection and row["seed"] in protected) or row["seed"] in seeds:
                raise ValueError("Duplicate or reserved training seed")
            seeds.add(row["seed"])
            cases.append(
                (
                    "MONSTER.HUNTER_KILLER" not in (row.get("last_enemies") or []),
                    row["seed"],
                    path.parent,
                )
            )
    if args.diagnostic_selection and observed != test:
        raise ValueError("Post-selection diagnostics require the complete test cohort")
    tasks = [(source, args.output, args.host.resolve(), args.act) for _, _, source in sorted(cases)]
    with ProcessPoolExecutor(args.workers) as pool:
        counts = list(pool.map(export, tasks))
    save_json(
        args.output / "manifest.json",
        {
            "seeds": sorted(seeds),
            "starts": sum(counts),
            "purpose": "test-diagnostic" if args.diagnostic_selection else "train",
            "selection_sha256": hashlib.sha256(args.diagnostic_selection.read_bytes()).hexdigest()
            if args.diagnostic_selection
            else None,
            "host_sha256": hashlib.sha256(args.host.read_bytes()).hexdigest(),
            "seed_lock_sha256": hashlib.sha256(args.seed_lock.read_bytes()).hexdigest(),
        },
    )


if __name__ == "__main__":
    main()
