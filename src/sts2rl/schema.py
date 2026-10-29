"""Versioned, deliberately small player-observable macro decision contract.

Run IDs, split groups, labels, provenance and metadata are never model inputs.
Unknown observation fields fail closed so hidden simulator fields cannot silently
become training features. This v1 contract is a card-reward baseline, not a claim
that upgrades alone describe every card or that the complete map is represented.
"""

from __future__ import annotations

import math
from typing import Any

SCHEMA_VERSION = 1
MAX_ENTITIES = 512
MAX_CANDIDATES = 128
OBSERVATION_FIELDS = {
    "character",
    "ascension",
    "decision_type",
    "act",
    "floor",
    "hp",
    "max_hp",
    "gold",
    "deck",
    "relics",
    "potions",
    "state_quality",
}
CANDIDATE_FIELDS = {"action_id", "kind", "entity_id", "upgrades", "price"}


class SchemaError(ValueError):
    """The decision cannot be safely represented by schema v1."""


def _text(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise SchemaError(f"{name} must be a nonempty string of at most 512 characters")


def _number(value: Any, name: str, *, nullable: bool = True, integer: bool = False) -> None:
    if value is None and nullable:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchemaError(f"{name} must be a finite nonnegative number or null")
    if not math.isfinite(value) or value < 0 or value > 1e12 or (integer and int(value) != value):
        raise SchemaError(f"{name} is out of range")


def validate_record(record: dict) -> dict:
    """Validate without mutation; missing numeric values are represented by null."""
    if not isinstance(record, dict) or record.get("schema_version") != SCHEMA_VERSION:
        raise SchemaError("expected a decision object with schema_version=1")
    for name in ("run_id", "decision_id", "source", "game_version", "split_group"):
        _text(record.get(name), name)
    observation = record.get("observation")
    if not isinstance(observation, dict):
        raise SchemaError("observation must be an object")
    unknown = set(observation) - OBSERVATION_FIELDS
    if unknown:
        raise SchemaError(f"unrecognized observation fields: {sorted(unknown)}")
    for name in ("character", "decision_type", "state_quality"):
        _text(observation.get(name), f"observation.{name}")
    for name in ("ascension", "act", "floor", "hp", "max_hp", "gold"):
        if name not in observation:
            raise SchemaError(f"observation.{name} must be explicit, using null if unknown")
        _number(observation[name], name, integer=name in {"ascension", "act", "floor"})
    if observation["max_hp"] is not None and observation["max_hp"] <= 0:
        raise SchemaError("known max_hp must be positive")
    if observation["hp"] is not None and observation["max_hp"] is not None:
        if observation["hp"] > observation["max_hp"]:
            raise SchemaError("hp exceeds max_hp")
    total = 0
    for name in ("deck", "relics", "potions"):
        entities = observation.get(name)
        if not isinstance(entities, list):
            raise SchemaError(f"{name} must be a list")
        total += len(entities)
        for entry in entities:
            if name == "deck":
                if not isinstance(entry, dict) or set(entry) != {"id", "upgrades"}:
                    raise SchemaError("deck entries must contain exactly id and upgrades")
                _text(entry["id"], "card id")
                _number(entry["upgrades"], "upgrades", integer=True)
            else:
                _text(entry, name)
    if total > MAX_ENTITIES:
        raise SchemaError(f"more than {MAX_ENTITIES} entities; no silent truncation")
    candidates = record.get("candidates")
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= MAX_CANDIDATES:
        raise SchemaError(f"expected 1..{MAX_CANDIDATES} legal candidates")
    action_ids = []
    for candidate in candidates:
        if not isinstance(candidate, dict) or set(candidate) - CANDIDATE_FIELDS:
            raise SchemaError("unrecognized candidate fields")
        for name in ("action_id", "kind"):
            _text(candidate.get(name), name)
        if candidate.get("entity_id") is not None:
            _text(candidate["entity_id"], "entity_id")
        _number(candidate.get("upgrades"), "candidate.upgrades", integer=True)
        _number(candidate.get("price"), "price")
        action_ids.append(candidate["action_id"])
    if len(set(action_ids)) != len(action_ids):
        raise SchemaError("duplicate candidate action_id")
    if record.get("chosen_action_id") is not None and record["chosen_action_id"] not in action_ids:
        raise SchemaError("chosen_action_id is not a legal candidate")
    outcome = record.get("outcome")
    if outcome is not None and (isinstance(outcome, bool) or outcome not in (0, 1)):
        raise SchemaError("outcome must be 0, 1 or null; abandonment is not defeat")
    if not isinstance(record.get("metadata", {}), dict):
        raise SchemaError("metadata must be an object")
    return record
