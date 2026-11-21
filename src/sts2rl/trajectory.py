"""Restore logged public decisions from unmodified Silent A10 games."""

import gzip
import hashlib
import json
from pathlib import Path
from random import Random

from .native import ReplayFork, digest


def natural_specification(command):
    """Recover a fresh A10 game specification, including the lobby's act selection."""
    required = {"cmd", "seed", "ascension", "history"}
    if (
        set(command) not in (required, required | {"act_list"})
        or command["cmd"] != "training_restore"
        or command["history"]
        or command["ascension"] != 10
        or command.get("act_list", "default") not in ("default", "seeded")
    ):
        raise ValueError("Expected a natural Silent A10 opening")
    return {k: v for k, v in command.items() if k not in ("cmd", "history")}


def early_draft_contexts(session, directory):
    """Recover the public pre-reward group odds from an archived action history."""
    from .encounter_draft import WeakEncounterPool

    with (Path(directory) / "game/rpc.jsonl").open(encoding="utf-8") as stream:
        first = json.loads(next(stream))
        initial = session.restore(ReplayFork(natural_specification(first["command"]), (),
                                             first["response_digest"]))
        pool = WeakEncounterPool(initial)
        for line in stream:
            if pool.group_probability is None:
                break
            row = json.loads(line)
            command = row["command"]
            if command["cmd"] == "get_map":
                continue
            if command["cmd"] != "action":
                raise ValueError("Unexpected control command in draft history")
            state = session._request(command)
            if digest(state) != row["response_digest"]:
                raise ValueError("Public draft history diverged")
            pool.observe(command["action"], state)
            if state["decision"] == "card_reward" and not state.get("in_combat"):
                yield row["response_digest"], pool.group_probability


def map_combat_openings(directory, minimum_act, limit):
    """Sample natural first hands after a map choice, stratified across early and late floors."""
    with (Path(directory) / "game/rpc.jsonl").open(encoding="utf-8") as stream:
        first = json.loads(next(stream))
        spec = natural_specification(first["command"])
        history, openings = [], []
        act, last_row = 1, -1
        signature = None
        for line in stream:
            row = json.loads(line)
            command = row["command"]
            if command["cmd"] == "get_map":
                continue
            if command["cmd"] != "action":
                raise ValueError("Unexpected control command in a natural game")
            action = command["action"]
            if (
                signature is not None
                and act >= minimum_act
                and action in ("play_card", "use_potion", "end_turn")
            ):
                openings.append((last_row, len(history), signature))
            signature = None
            if action == "select_map_node":
                floor = command["args"]["row"]
                act += int(floor < last_row)
                last_row = floor
                signature = row["response_digest"]
            history.append(command)
    rng = Random(int.from_bytes(hashlib.sha256(spec["seed"].encode()).digest()[:8], "big"))
    rng.shuffle(openings)
    chosen = []
    if limit >= 2:
        for late in (False, True):
            match = next((r for r in openings if (r[0] >= 8) == late), None)
            if match:
                chosen.append(match)
    chosen.extend(r for r in openings if r not in chosen)
    for _, index, digest_value in chosen[:limit]:
        yield None, ReplayFork(spec, tuple(history[:index]), digest_value)


def strategy_roots(directory):
    directory = Path(directory)
    with (directory / "game/rpc.jsonl").open(encoding="utf-8") as stream:
        first = json.loads(next(stream))
        spec = natural_specification(first["command"])
        commands, fingerprints = [], [first["response_digest"]]
        for line in stream:
            row = json.loads(line)
            if row["command"]["cmd"] == "get_map":
                continue
            if row["command"]["cmd"] != "action":
                raise ValueError("Unexpected control command in full run")
            commands.append(row["command"])
            fingerprints.append(row["response_digest"])
    with gzip.open(directory / "strategy.jsonl.gz", "rt", encoding="utf-8") as stream:
        for line in stream:
            entry = json.loads(line)
            step = entry["step"]
            if fingerprints[step] != digest(entry["state"]) or commands[step] != entry["action"]:
                raise ValueError("Logged action or observation differs from the native trace")
            yield entry["state"], ReplayFork(spec, tuple(commands[:step]), fingerprints[step])


def act2_boss_root(directory):
    """Recover the first playable hand at the final Act 2 map node of a natural boss arrival."""
    with (directory / "game/rpc.jsonl").open(encoding="utf-8") as stream:
        first = json.loads(next(stream))
        spec = natural_specification(first["command"])
        previous = first["response_digest"]
        act, last_row = 1, -1
        history, last_fight = [], None
        waiting = False
        for line in stream:
            row = json.loads(line)
            cmd = row["command"]
            if cmd["cmd"] == "get_map":
                continue
            if cmd["cmd"] != "action":
                raise ValueError("Unexpected command in natural history")
            kind = cmd["action"]
            if kind == "select_map_node":
                y = cmd["args"]["row"]
                act += int(y < last_row)
                last_row = y
                if act > 2:
                    break
                waiting = act == 2
                if waiting:
                    last_fight = None
            elif waiting and kind in ("play_card", "end_turn", "use_potion"):
                last_fight = (len(history), previous)
                waiting = False
            history.append(cmd)
            previous = row["response_digest"]
    if not last_fight:
        raise ValueError("No combat action at last Act 2 node")
    index, digest = last_fight
    return ReplayFork(spec, tuple(history[:index]), digest)
