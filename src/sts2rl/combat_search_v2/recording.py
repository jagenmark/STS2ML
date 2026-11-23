"""Opt-in collection from executed public actions and native boundary receipts."""
from collections import Counter, defaultdict
from contextlib import contextmanager
import gzip
import json
import os
from pathlib import Path

from .encounters import encounter_reason
from .features import FEATURE_NAMES, VERSION, extract_post_eot_features
from .state import Unsupported, entry, project
from .transitions import POTIONS, admission_reasons

DEFAULT_OBSERVER = Path(
    "artifacts/combat-search-v2/observer/bin/CombatV2Observer/debug/CombatV2Observer.dll"
)


def observer_path(root, path=None):
    return Path(path or Path(root) / DEFAULT_OBSERVER).resolve(strict=True)


@contextmanager
def observer_environment(observer, receipts):
    if observer is None:
        yield
        return
    hook = str(observer)
    previous_hook = os.environ.get("DOTNET_STARTUP_HOOKS")
    if previous_hook:
        hook = previous_hook + os.pathsep + hook
    environment = {"DOTNET_STARTUP_HOOKS": hook, "STS2_COMBAT_V2_RECEIPTS": str(receipts.resolve())}
    previous = {key: os.environ.get(key) for key in environment}
    os.environ.update(environment)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _view(state):
    return state.get("combat_state", state)


def _formation(view):
    return tuple(entry(e["id"]) for e in view.get("enemies", ()) if e["hp"] > 0)


def _was_smoke_bomb(before, action):
    return action.kind == "use_potion" and any(
        potion["index"] == action.args.get("potion_index") and entry(potion["id"]) == "SMOKE_BOMB"
        for potion in _view(before)["player"].get("potions", ())
    )


def terminal_label(before, action, after, witness):
    if not before.get("in_combat") or after.get("in_combat") is not False:
        return None
    if after.get("decision") == "game_over" and after.get("victory") is False:
        if after.get("player", {}).get("hp") == 0:
            return {"outcome": "dead", "exit_hp": 0, "exit_max_hp": after["player"]["max_hp"]}
        return {"outcome": "censored", "reason": "unverified death"}
    if witness is None:
        return {"outcome": "censored", "reason": "missing pre-reward exit witness"}
    outcome = "escape" if witness["escaped"] or _was_smoke_bomb(before, action) else "victory"
    return {"outcome": outcome, "exit_hp": witness["hp"], "exit_max_hp": witness["max_hp"]}


class FightRecorder:
    def __init__(self, folder, *, verify_parity=False):
        self.folder = Path(folder)
        self.receipts = self.folder / "native-combat-v2.jsonl"
        self.offset = 0
        self.fights = []
        self.turns = []
        self.census = defaultdict(Counter)
        self.pending = None
        self.verify_parity = verify_parity

    def _receipt(self, step):
        found = {}
        with self.receipts.open(encoding="utf-8") as stream:
            stream.seek(self.offset)
            while line := stream.readline():
                receipt = json.loads(line)
                if receipt.get("step", -1) > step:
                    raise ValueError("Native combat recorder is ahead of the action stream")
                if receipt.get("step") == step:
                    found = receipt
            self.offset = stream.tell()
        return found

    def _open_fight(self, view, step):
        ctx = view["context"]
        self.fights.append({
            "id": len(self.fights), "step": step, "act": ctx["act"], "floor": ctx["floor"],
            "room_type": ctx["room_type"], "formation": _formation(view), "entry_hp": view["player"]["hp"],
            "rounds": [], "outcome": "censored", "reason": "truncated combat",
        })

    def _root(self, public, view):
        act = view["context"]["act"]
        counts = self.census[act]
        if public["decision"] != "combat_play":
            source = public.get("selection_source") or {}
            counts[f"prompt seen/{public['decision']}/{entry(source.get('id', 'unknown'))}"] += 1
        elif not (any(c["can_play"] for c in view["hand"])
                  or any(p["can_use"] for p in view["player"].get("potions", ()))):
            counts["forced"] += 1
            return
        counts["roots"] += 1
        counts["formation seen/" + "+".join(_formation(view))] += 1
        try:
            projected = project(public)
        except (Unsupported, KeyError, TypeError, ValueError) as error:
            counts[f"first blocker/{error}"] += 1
            return
        formation = encounter_reason(projected.state)
        reasons = tuple(admission_reasons(projected))
        first = formation or (reasons[0] if reasons else None)
        counts[f"first blocker/{first}" if first else "admission passed"] += 1
        for reason in set(reasons):
            counts[f"blocker/{reason}"] += 1
        if formation:
            counts[f"blocker/formation/{formation}"] += 1
        if projected.state.prompt:
            counts["blocker/prompt/reconciliation required"] += 1
        for potion in projected.state.potions:
            if potion.usable and potion.name not in POTIONS:
                counts[f"boundary/potion/{potion.name}"] += 1

    def observe(self, before, action, after, step, native_step=None):
        view = _view(before)
        if before.get("in_combat") and (not self.fights or self.fights[-1].get("end_step") is not None):
            self._open_fight(view, step)
        receipt = {}
        if before.get("in_combat"):
            fight = self.fights[-1]
            if view.get("round") and (not fight["rounds"] or view["round"] != fight["rounds"][-1][0]):
                fight["rounds"].append([view["round"], step])
            self._root(before, view)
            if action.kind == "end_turn":
                if self.pending is not None:
                    self.pending[0]["censor"] = "previous turn boundary missing"
                row = {"fight": fight["id"], "step": step, "round": view["round"],
                       "potion_count": len(view["player"].get("potions", ()))}
                self.turns.append(row)
                self.pending = row, before
            if self.pending is not None or after.get("in_combat") is False:
                receipt = self._receipt(step if native_step is None else native_step)

            terminal = terminal_label(before, action, after, receipt.get("exit"))
            if terminal is not None:
                fight.pop("reason", None)
                fight.update(terminal, end_step=step)
            if self.pending is not None:
                row, pre = self.pending
                next_view = _view(after)
                if terminal is not None:
                    row["censor"] = "combat ended at turn boundary"
                elif next_view.get("round", 0) > row["round"] and next_view.get("decision") == "combat_play":
                    try:
                        if receipt.get("draw") is None:
                            raise Unsupported("missing pre-draw witness")
                        values = extract_post_eot_features(pre, after, witness=receipt["draw"])
                    except (Unsupported, KeyError, TypeError, ValueError) as error:
                        row["censor"] = str(error)
                    else:
                        row["x"] = values.tolist()
                        if self.verify_parity:
                            self._parity(pre, values)
                if "x" in row or "censor" in row:
                    self.pending = None
        if after.get("in_combat") and not before.get("in_combat"):
            self._open_fight(_view(after), step + 1)

    def _parity(self, pre, values):
        import numpy as np
        from .end_turn import resolve
        from .features import extract_leaf_features
        from .transitions import admission

        try:
            projected = project(pre)
            if admission(projected):
                return
            leaf = resolve(projected.state)
            if leaf.outcome != "completed":
                return
        except Unsupported:
            return
        counts = self.census[leaf.act]
        counts["parity tested"] += 1
        different = np.flatnonzero(np.abs(values - extract_leaf_features(leaf)) > 1e-5)
        if len(different):
            counts["parity mismatch"] += 1
            for i in different:
                counts[f"parity feature/{FEATURE_NAMES[i]}"] += 1

    def write(self):
        if self.pending is not None:
            self.pending[0]["censor"] = "episode ended before next actionable turn"
        with gzip.open(self.folder / "combat-v2-recording.json.gz", "wt", encoding="utf-8", compresslevel=2) as stream:
            json.dump({"schema": VERSION, "feature_names": FEATURE_NAMES, "turns": self.turns,
                       "fights": self.fights}, stream, separators=(",", ":"))
        (self.folder / "combat-v2-census.json").write_text(
            json.dumps(self.census, sort_keys=True, separators=(",", ":")), encoding="utf-8")
