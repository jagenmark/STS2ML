"""Pinned native bridge, snapshot-bound public actions, and verified replay forks.

Scenario/restore/sampling controls belong to the experiment runner, never to a
policy. Native processes have isolated save directories and bounded RPC waits.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import itertools
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
from typing import Any

ASSEMBLY_VERSION = "0.1.0+41cef1ea4657c524aa50e870df009e56337e8c32"
SAMPLER = "silent-a10-starter-beetle-v1"
ACT1_SAMPLER = "silent-a10-act1-mc-v2"


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


class NativeError(RuntimeError):
    pass


@dataclass(frozen=True)
class Action:
    id: str
    kind: str
    args: dict
    snapshot: str

    def command(self) -> dict:
        return {"cmd": "action", "action": self.kind, "args": deepcopy(self.args)}


def legal_actions(state: dict) -> list[Action]:
    """Finite public choice contract. Unknown phases/types fail explicitly.

    can_play/can_use are native checks. Target/selection enumeration is a public
    adapter contract; unsupported target modes and oversized selections fail.
    """
    fingerprint = digest(state)
    actions = []

    def add(kind, **args):
        actions.append(Action(digest([kind, args])[:20], kind, args, fingerprint))

    def targeted(kind, item, index_name):
        args = {index_name: item["index"]}
        target = item.get("target_type")
        if target == "AnyEnemy":
            for enemy in state["enemies"]:
                if enemy["hp"] > 0:
                    add(kind, **args, target_index=enemy["index"])
        elif target in ("Self", "AnyPlayer", "None", "All", "AllEnemies", "RandomEnemy", "TargetedNoCreature"):
            add(kind, **args)
        else:
            raise NativeError(f"Unsupported target type: {target}")

    decision = state.get("decision")
    if decision == "combat_play":
        if state.get("observation_version") != 2:
            raise NativeError("Native observation v2 required")
        for card in state["hand"]:
            if card["can_play"]:
                targeted("play_card", card, "card_index")
        for potion in state["player"]["potions"]:
            if "can_use" not in potion:
                raise NativeError("Rebuild host: potion usability missing")
            if potion["can_use"]:
                targeted("use_potion", potion, "potion_index")
        add("end_turn")
    elif decision == "card_select":
        indices = [c["index"] for c in state["cards"]]
        lo, hi = state["min_select"], min(state["max_select"], len(indices))
        if not 0 <= lo <= hi:
            raise NativeError("Invalid selection bounds")
        for n in range(lo, hi + 1):
            for selected in itertools.combinations(indices, n):
                if not selected:
                    add("skip_select")
                else:
                    add("select_cards", indices=",".join(map(str, selected)))
                if len(actions) > 1024:
                    raise NativeError("Selection requires a sequential decoder; no truncation")
    elif decision == "map_select":
        for choice in state["choices"]:
            add("select_map_node", col=choice["col"], row=choice["row"])
    elif decision in ("event_choice", "rest_site"):
        for option in state["options"]:
            if not option.get("is_locked") and option.get("is_enabled", True):
                add("choose_option", option_index=option["index"])
        if not actions:
            add("leave_room")
    elif decision == "card_reward":
        for card in state["cards"]:
            add("select_card_reward", card_index=card["index"])
        if state.get("can_skip"):
            add("skip_card_reward")
    elif decision == "bundle_select":
        for i, _ in enumerate(state["bundles"]):
            add("select_bundle", bundle_index=i)
    elif decision == "shop":
        gold = state["player"]["gold"]
        for category, kind, index in (("cards", "buy_card", "card_index"),
                                      ("relics", "buy_relic", "relic_index"),
                                      ("potions", "buy_potion", "potion_index")):
            if category == "potions" and len(state["player"]["potions"]) >= 2:
                continue
            for item in state.get(category, []):
                if item.get("is_stocked") and item.get("cost", gold + 1) <= gold:
                    add(kind, **{index: item["index"]})
        add("leave_room")
    elif decision == "game_over":
        return []
    else:
        raise NativeError(f"Unsupported native decision: {decision}")
    if not actions or len({a.id for a in actions}) != len(actions):
        raise NativeError("Empty/duplicate native action set")
    return actions


@dataclass(frozen=True)
class ReplayFork:
    specification: dict
    history: tuple[dict, ...]
    expected_digest: str


class NativeSession:
    def __init__(self, root: Path, folder: Path, *, timeout: float = 30):
        self.root, self.folder = root.resolve(), folder.resolve()
        self.folder.mkdir(parents=True, exist_ok=False)
        dotnet = self.root / "artifacts/tools/dotnet/dotnet.exe"
        upstream = self.root / "artifacts/upstreams/sts2-cli"
        host = upstream / "src/Sts2Headless/bin/Release/net9.0/Sts2Headless.dll"
        env = os.environ.copy()
        env.update(DOTNET_ROOT=str(dotnet.parent), STS2_LIB=str(upstream / "lib"),
                   STS2_GAME_DIR=str(upstream / "lib"), STS2_TRAINING="1",
                   DOTNET_CLI_TELEMETRY_OPTOUT="1")
        for name in ("APPDATA", "LOCALAPPDATA"):
            path = self.folder / name.lower()
            path.mkdir()
            env[name] = str(path)
        self.errors = (self.folder / "engine.log").open("w", encoding="utf-8")
        self.trace = (self.folder / "rpc.jsonl").open("w", encoding="utf-8")
        self.timeout, self.closed = timeout, False
        self.state, self.history, self.specification = {}, [], {}
        self.sampled = False
        try:
            self.process = subprocess.Popen([str(dotnet), str(host)], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=self.errors, text=True, encoding="utf-8",
                bufsize=1, cwd=self.folder, env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            self.responses = queue.Queue()

            def reader():
                try:
                    for line in self.process.stdout:
                        if line.startswith("{"):
                            self.responses.put(line)
                finally:
                    self.responses.put(None)

            self.reader = threading.Thread(target=reader, daemon=True)
            self.reader.start()
            if self._read().get("type") != "ready":
                raise NativeError("Unexpected native handshake")
        except BaseException:
            self.close()
            raise

    def _read(self):
        try:
            line = self.responses.get(timeout=self.timeout)
        except queue.Empty:
            raise TimeoutError("Native RPC deadline exceeded") from None
        if line is None:
            raise NativeError("Native stdout closed")
        return json.loads(line)

    def _request(self, command):
        if self.closed:
            raise NativeError("Closed native session")
        started = time.perf_counter()
        try:
            self.process.stdin.write(json.dumps(command) + "\n")
            self.process.stdin.flush()
            result = self._read()
            self.trace.write(json.dumps({"command": command, "response_digest": digest(result),
                                        "seconds": time.perf_counter() - started}) + "\n")
            self.trace.flush()
            if result.get("type") in ("error", "save_error"):
                self.errors.write("\n[RPC ERROR] " + json.dumps(result) + "\n")
                self.errors.flush()
                raise NativeError(result.get("message", str(result)))
            if result.get("runtime_identity") != {"character": "SILENT", "ascension": 10,
                                                   "assembly_version": ASSEMBLY_VERSION}:
                raise NativeError("Native runtime identity mismatch")
            return result
        except BaseException:
            # Errors/timeouts invalidate a possibly half-applied action stream.
            self.close()
            raise

    def reset(self, seed: str, *, encounter: str | None = None, hp: int = 70):
        spec = {"seed": seed}
        if encounter is not None:
            spec.update(encounter=encounter, hp=hp)
        self.state = self._request({"cmd": "training_restore", **spec, "history": []})
        self.specification, self.history, self.sampled = spec, [], False
        return deepcopy(self.state)

    def step(self, action: Action):
        if action.snapshot != digest(self.state):
            raise NativeError("Stale action: observation changed")
        allowed = {a.id: a for a in legal_actions(self.state)}
        if allowed.get(action.id) != action:
            raise NativeError("Action is not in the current public action set")
        command = action.command()
        self.state = self._request(command)
        self.history.append(command)
        return deepcopy(self.state)

    def fork(self):
        if self.sampled:
            raise NativeError("Cannot replay-fork a sampled world without its chance history")
        return ReplayFork(deepcopy(self.specification), tuple(deepcopy(self.history)), digest(self.state))

    def restore(self, fork: ReplayFork):
        state = self._request({"cmd": "training_restore", **fork.specification,
                               "history": list(fork.history)})
        if digest(state) != fork.expected_digest:
            self.close()
            raise NativeError("Replay diverged from expected public state")
        self.state, self.specification = state, deepcopy(fork.specification)
        self.history, self.sampled = list(deepcopy(fork.history)), False
        return deepcopy(state)

    def sample(self, seed: int, *, profile: str = SAMPLER):
        before = digest(self.state)
        state = self._request({"cmd": "training_sample", "sample_seed": seed, "profile": profile})
        if digest(state) != before:
            self.close()
            raise NativeError("Chance sampling changed the public root")
        self.state, self.sampled = state, True
        return deepcopy(state)

    def close(self):
        if self.closed:
            return
        self.closed = True
        if hasattr(self, "process"):
            if self.process.poll() is None:
                self.process.kill()
            self.process.wait(timeout=5)
            if hasattr(self, "reader"):
                self.reader.join(timeout=2)
            self.process.stdin.close()
            self.process.stdout.close()
        self.errors.close()
        self.trace.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
