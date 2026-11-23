"""Opt-in bridge from stamped public choices to the pure beam."""
from collections import Counter
from copy import copy, deepcopy
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
from time import perf_counter_ns

from ..native import NativeError, runtime_identity
from .encounters import encounter_reason
from .end_turn import attack_amount
from .planner import Config, search
from .state import SCHEMA, Unsupported, entry, project, root_move
from .transitions import CARDS, admission, advance, legal


def _variant_key(variant, after_reveal=False):
    cost = None if after_reveal and variant.name not in CARDS else variant.cost
    return (variant.name, variant.kind, cost, variant.target, variant.upgrade,
            variant.keywords, variant.modifier)


def _zone(cards, after_reveal=False):
    return Counter(_variant_key(card, after_reveal) for card in cards)


def _board(state):
    return (state.hp, state.max_hp, state.block, state.energy, state.max_energy,
            state.round, state.powers, state.relics,
            tuple((e.name, e.hp, e.max_hp, e.block, e.powers) for e in state.enemies if e.hp > 0),
            tuple((p.name, p.target, p.usable, p.stats) for p in state.potions))


def _positions(state):
    return (tuple(_variant_key(c.variant) for c in state.hand), _zone(state.draw),
            _zone(state.discard), _zone(state.exhaust), _zone(state.play))


def _intents(state):
    return tuple(tuple((i.kind, i.hits, attack_amount(state, e, i) if i.damage is not None else None)
                       for i in e.intents) for e in state.enemies if e.hp > 0)


def _prompt_signature(state):
    if state.prompt is None:
        return None
    prompt = state.prompt
    positions = {c.slot: i for i, c in enumerate(state.hand)}
    return (prompt.operation, tuple(positions[i] for i in prompt.candidates),
            prompt.minimum, prompt.maximum)


def _normalized_legal(state):
    hand = {c.slot: i for i, c in enumerate(state.hand)}
    enemies = {e.slot: i for i, e in enumerate(e for e in state.enemies if e.hp > 0)}
    potions = {p.slot: i for i, p in enumerate(state.potions)}
    return tuple((m.kind, hand[m.slot] if m.kind == "play_card" else potions.get(m.slot, -1)
                  if m.kind == "use_potion" else -1, enemies.get(m.target, -1),
                  tuple(hand[i] for i in m.selection)) for m in legal(state))


def _native_legal(projected, actions):
    return tuple(root_move(projected, action.kind, action.args) for action in actions)


def _completed_zones(state):
    return (_zone((*state.draw, *state.discard, *(c.variant for c in state.hand)), after_reveal=True),
            _zone(state.exhaust, after_reveal=True), _zone(state.play, after_reveal=True))


def _difference(predicted, actual):
    """Compare deterministic attributes. Completed turns cross the native reveal."""
    for name, expected, observed in zip(
        ("hp", "max_hp", "block", "energy", "max_energy", "round", "powers", "relics", "enemies", "potions"),
        _board(predicted), _board(actual),
    ):
        if expected != observed:
            return f"board/{name}"
    if predicted.outcome == "completed":
        if _completed_zones(predicted) != _completed_zones(actual):
            return "completed zones"
        return ""
    if _positions(predicted) != _positions(actual):
        return "zones"
    if _intents(predicted) != _intents(actual):
        return "intent"
    if _prompt_signature(predicted) != _prompt_signature(actual):
        return "prompt"
    return ""


class CombatSearchV2:
    def __init__(self, config=Config(), *, shadow=False, record=False):
        self.config = config
        self.shadow = shadow
        self.records = [] if record else None
        self._prompt = None
        self._decision = None

    def clone(self):
        clone = copy(self)
        clone.records = deepcopy(self.records)
        return clone

    @classmethod
    def from_options(cls, options, *, record=False):
        act = options.get("combat_search_v2", False)
        shadow = options.get("combat_search_v2_shadow", False)
        if act and shadow:
            raise ValueError("Choose either active or shadow combat search v2")
        path = options.get("combat_search_v2_config")
        config = Config(**json.loads(Path(path).read_bytes())) if path else Config()
        return cls(config, shadow=shadow, record=record)

    def _record(self, record):
        if self.records is not None:
            self.records.append(record)

    def write(self, folder):
        if self.records is None:
            return
        config = asdict(self.config)
        canonical = json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
        metadata = {"schema": SCHEMA, "config": config, "config_sha256": hashlib.sha256(canonical).hexdigest(),
                    "mode": "shadow" if self.shadow else "act"}
        with (Path(folder) / "combat-search-v2.jsonl").open("w", encoding="utf-8") as stream:
            stream.write(json.dumps(metadata, separators=(",", ":")) + "\n")
            for row in self.records:
                stream.write(json.dumps(row, separators=(",", ":")) + "\n")

    def choose(self, public, champion, enumerate_actions):
        started = perf_counter_ns() if self.records is not None else 0
        projected = None
        previous_prompt, self._prompt = self._prompt, None
        self._decision = None
        result = None
        fallback = ""
        changed = False
        actual = champion
        try:
            if public.get("runtime_identity") != runtime_identity(10):
                raise Unsupported("runtime")
            projected = project(public)
            if projected.state.prompt:
                if previous_prompt is None or _difference(previous_prompt, projected.state):
                    raise Unsupported("unreconciled prompt")
                projected = replace(projected, state=replace(previous_prompt, spent=0))
            actions = enumerate_actions(public)
            moves = _native_legal(projected, actions)
            primary = root_move(projected, champion.kind, champion.args)
            result = search(projected, moves, primary, self.config)
            fallback = result.fallback
            changed = result.choice != primary
            if changed and not self.shadow and not fallback:
                actual = actions[moves.index(result.choice)]
            if (result.attempts or result.fallback == "forced") and primary in moves:
                self._decision = projected, moves
        except (Unsupported, NativeError, KeyError, TypeError, ValueError) as error:
            fallback = str(error) if isinstance(error, Unsupported) else f"projection/{type(error).__name__}"
        if self.records is not None:
            view = public.get("combat_state", public)
            formation = [entry(e["id"]) for e in view.get("enemies", ())]
            row = {
                "act": (view.get("context") or {}).get("act"), "formation": formation,
                "decision": public.get("decision"), "fallback": fallback, "changed": changed,
                "ns": perf_counter_ns() - started, "attempts": result.attempts if result else 0,
            }
            if result is not None:
                row.update(roots=result.root_count, covered_roots=result.covered_roots,
                           child_cap=result.child_cap, depth_cap=result.depth_cap,
                           depth=result.reached_depth, dedup=result.duplicates,
                           width_pruned=result.width_pruned, boundaries=dict(result.boundary_counts),
                           no_potion=result.no_potion.score if result.no_potion else None,
                           with_potion=result.with_potion.score if result.with_potion else None)
            self._record(row)
        return actual

    def observe(self, action, after, enumerate_actions):
        context, self._decision = self._decision, None
        self._prompt = None
        if context is None:
            return
        projected, moves = context
        state = projected.state
        if encounter_reason(state) or admission(projected):
            return
        try:
            move = root_move(projected, action.kind, action.args)
            if move not in moves:
                return
            predicted = advance(state, move)
        except (Unsupported, ValueError, KeyError):
            return
        evidence = ""
        reason = ""
        if predicted.boundary and not predicted.outcome:
            evidence = "unresolved"
            reason = predicted.boundary.reason
        elif predicted.outcome in ("victory", "dead"):
            matches = (after.get("decision") == "game_over" and after["player"]["hp"] == 0
                       if predicted.outcome == "dead" else not after.get("in_combat"))
            evidence = "match" if matches else "mismatch"
            reason = "" if matches else "outcome"
        elif self.records is not None or predicted.prompt:
            try:
                actual = project(after)
                reason = _difference(predicted, actual.state)
                if not reason and not predicted.outcome:
                    expected = _normalized_legal(predicted)
                    native = _native_legal(actual, enumerate_actions(after))
                    if native != legal(actual.state) or expected != _normalized_legal(actual.state):
                        reason = "legality"
                evidence = "mismatch" if reason else "match"
                if predicted.prompt and not reason:
                    self._prompt = predicted
            except (Unsupported, NativeError, KeyError, ValueError, TypeError) as error:
                evidence, reason = "mismatch", str(error)
        if self.records is not None and evidence:
            mechanic = move.kind
            if move.kind == "play_card":
                mechanic = next(c.variant.name for c in state.hand if c.slot == move.slot)
            elif move.kind == "use_potion":
                mechanic = next(p.name for p in state.potions if p.slot == move.slot)
            elif move.kind == "select_cards":
                mechanic = state.prompt.operation + "/discard"
            self.records[-1]["oracle"] = [mechanic, evidence, reason]


def choose_encounter(mode, encounter, public, policy, enumerate_actions):
    """Preserve the legacy boss observer if the opt-in arm changes its proposal."""
    if public["decision"] == "combat_play" and not mode.shadow:
        encounter.prepare(public, policy)
    tactics = encounter.boss_tactics
    original_facing = tactics.facing if tactics is not None else None
    champion = encounter.choose(public, policy)
    action = mode.choose(public, champion, enumerate_actions)
    if tactics is not None and action is not champion:
        tactics.facing = original_facing
        tactics.observe(action)
    return action
