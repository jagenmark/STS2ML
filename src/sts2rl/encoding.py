"""Explicit player-visible feature projection for macro decision records.

Only the keys read in this module enter the network. In particular, run/decision
IDs, seeds, source, game version, metadata, chosen actions, and outcomes are not
features. Labels are returned separately. Fit a Vocabulary on the training split
only; validation/test entities then map to UNK instead of changing the model.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import torch

from .schema import MAX_CANDIDATES, MAX_ENTITIES

PAD = "<PAD>"
UNK = "<UNK>"
MAX_STATE_TOKENS = MAX_ENTITIES
MAX_ACTIONS = MAX_CANDIDATES
NUMERIC_SCALES = (
    ("ascension", 10.0),
    ("act", 3.0),
    ("floor", 60.0),
    ("hp", 100.0),
    ("max_hp", 100.0),
    ("gold", 1000.0),
)
NUMERIC_DIM = 2 * len(NUMERIC_SCALES) + 3 + 2
STATE_FEATURE_DIM = 2
ACTION_FEATURE_DIM = 4


def _token(namespace: str, value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{namespace} must be a nonempty string")
    return f"{namespace}:{value}"


def _entity_token(entity_id: Any) -> str:
    # The type embedding distinguishes cards, relics and potions; sharing this
    # namespace ties action entities to the identical observed game identifier.
    return _token("entity", entity_id)


def _record_tokens(record: Mapping[str, Any]) -> Iterable[str]:
    observation = record["observation"]
    yield _token("character", observation["character"])
    yield _token("decision", observation["decision_type"])
    for card in observation.get("deck", []):
        yield _entity_token(card["id"])
    for key in ("relics", "potions"):
        for entity_id in observation.get(key, []):
            yield _entity_token(entity_id)
    for action in record["candidates"]:
        yield _token("action_kind", action["kind"])
        if action.get("entity_id") is not None:
            yield _entity_token(action["entity_id"])


@dataclass
class Vocabulary:
    """Stable token vocabulary, serialized as an ordered list with PAD/UNK first."""

    tokens: Sequence[str]
    token_to_id: dict[str, int] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.tokens = tuple(self.tokens)
        if len(self.tokens) < 2 or self.tokens[:2] != (PAD, UNK):
            raise ValueError("Vocabulary must reserve index 0 for PAD and 1 for UNK")
        if any(not isinstance(token, str) for token in self.tokens):
            raise ValueError("Vocabulary tokens must be strings")
        if len(set(self.tokens)) != len(self.tokens):
            raise ValueError("Vocabulary tokens must be unique")
        self.token_to_id = {token: index for index, token in enumerate(self.tokens)}

    @classmethod
    def build(cls, records: Iterable[Mapping[str, Any]]) -> Vocabulary:
        observed = {token for record in records for token in _record_tokens(record)}
        return cls((PAD, UNK, *sorted(observed)))

    def encode(self, token: str) -> int:
        return self.token_to_id.get(token, 1)

    def __len__(self) -> int:
        return len(self.tokens)

    @property
    def size(self) -> int:
        return len(self)

    def to_dict(self) -> dict[str, Any]:
        return {"version": 1, "tokens": list(self.tokens)}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Vocabulary:
        if payload.get("version") != 1:
            raise ValueError("Unsupported vocabulary version")
        return cls(payload["tokens"])


def _number_pair(value: Any, scale: float, name: str) -> list[float]:
    if value is None:
        return [0.0, 0.0]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number or null")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number or null")
    return [float(value) / scale, 1.0]


def _numeric(observation: Mapping[str, Any]) -> list[float]:
    values = [
        feature
        for name, scale in NUMERIC_SCALES
        for feature in _number_pair(observation.get(name), scale, name)
    ]
    values.extend(
        len(observation.get(name, [])) / scale
        for name, scale in (("deck", 50.0), ("relics", 25.0), ("potions", 5.0))
    )
    hp, max_hp = observation.get("hp"), observation.get("max_hp")
    if hp is None or max_hp is None or max_hp <= 0:
        values.extend((0.0, 0.0))
    else:
        values.extend((float(hp) / float(max_hp), 1.0))
    return values


def collate_records(
    records: Sequence[Mapping[str, Any]],
    vocab: Vocabulary,
    device: torch.device | str = "cpu",
    *,
    max_state_tokens: int = MAX_STATE_TOKENS,
    max_actions: int = MAX_ACTIONS,
) -> dict[str, torch.Tensor]:
    """Batch records without truncation or inclusion of non-feature fields.

    ``state_mask`` / ``action_mask`` are True for real entities / legal candidates.
    Actions are candidate-relative, so labels are indices into this batch's padded
    candidate lists, never a global action vocabulary. Missing policy labels use
    target -1 and policy_mask=False. Missing outcome labels use a zero placeholder
    and value_mask=False; they must never be treated as defeats.
    """
    if not records:
        raise ValueError("Cannot collate an empty batch")
    if max_state_tokens < 1 or max_actions < 1:
        raise ValueError("Batch limits must be positive")
    batch_size = len(records)
    state_lengths = [
        sum(len(record["observation"].get(key, [])) for key in ("deck", "relics", "potions"))
        for record in records
    ]
    action_lengths = [len(record["candidates"]) for record in records]
    if max(state_lengths) > max_state_tokens:
        raise ValueError(f"State has more than {max_state_tokens} entities; truncation is disabled")
    if min(action_lengths) < 1 or max(action_lengths) > max_actions:
        raise ValueError(f"Each record needs 1..{max_actions} candidate actions")
    state_size, action_size = max(1, max(state_lengths)), max(action_lengths)
    batch = {
        "state_tokens": torch.zeros((batch_size, state_size), dtype=torch.long),
        "state_types": torch.zeros((batch_size, state_size), dtype=torch.long),
        "state_features": torch.zeros((batch_size, state_size, STATE_FEATURE_DIM)),
        "state_mask": torch.zeros((batch_size, state_size), dtype=torch.bool),
        "context_tokens": torch.zeros((batch_size, 2), dtype=torch.long),
        "numeric": torch.zeros((batch_size, NUMERIC_DIM)),
        "action_tokens": torch.zeros((batch_size, action_size), dtype=torch.long),
        "action_kinds": torch.zeros((batch_size, action_size), dtype=torch.long),
        "action_features": torch.zeros((batch_size, action_size, ACTION_FEATURE_DIM)),
        "action_mask": torch.zeros((batch_size, action_size), dtype=torch.bool),
        "policy_targets": torch.full((batch_size,), -1, dtype=torch.long),
        "policy_mask": torch.zeros(batch_size, dtype=torch.bool),
        "value_targets": torch.zeros(batch_size),
        "value_mask": torch.zeros(batch_size, dtype=torch.bool),
    }
    for row, record in enumerate(records):
        observation = record["observation"]
        batch["context_tokens"][row] = torch.tensor(
            [
                vocab.encode(_token("character", observation["character"])),
                vocab.encode(_token("decision", observation["decision_type"])),
            ]
        )
        batch["numeric"][row] = torch.tensor(_numeric(observation))
        entities = [
            (card["id"], 1, _number_pair(card.get("upgrades"), 3.0, "upgrades"))
            for card in observation.get("deck", [])
        ]
        for key, entity_type in (("relics", 2), ("potions", 3)):
            entities.extend((entity_id, entity_type, [0.0, 0.0]) for entity_id in observation.get(key, []))
        for col, (entity_id, entity_type, features) in enumerate(entities):
            batch["state_tokens"][row, col] = vocab.encode(_entity_token(entity_id))
            batch["state_types"][row, col] = entity_type
            batch["state_features"][row, col] = torch.tensor(features)
            batch["state_mask"][row, col] = True
        action_ids = []
        for col, action in enumerate(record["candidates"]):
            action_id = action["action_id"]
            if not isinstance(action_id, str) or not action_id:
                raise ValueError("Each candidate action_id must be a nonempty string")
            action_ids.append(action_id)
            if action.get("entity_id") is not None:
                batch["action_tokens"][row, col] = vocab.encode(_entity_token(action["entity_id"]))
            batch["action_kinds"][row, col] = vocab.encode(_token("action_kind", action["kind"]))
            batch["action_features"][row, col] = torch.tensor(
                _number_pair(action.get("upgrades"), 3.0, "action.upgrades")
                + _number_pair(action.get("price"), 100.0, "action.price")
            )
            batch["action_mask"][row, col] = True
        if len(set(action_ids)) != len(action_ids):
            raise ValueError("Candidate action IDs must be unique within a decision")
        chosen = record.get("chosen_action_id")
        if chosen is not None:
            if chosen not in action_ids:
                raise ValueError("Chosen action is not among the candidate actions")
            batch["policy_targets"][row] = action_ids.index(chosen)
            batch["policy_mask"][row] = True
        outcome = record.get("outcome")
        if outcome is not None:
            _number_pair(outcome, 1.0, "outcome")
            if not 0.0 <= outcome <= 1.0:
                raise ValueError("Outcome must be in [0, 1] or null")
            batch["value_targets"][row] = float(outcome)
            batch["value_mask"][row] = True
    return {key: tensor.to(device=device) for key, tensor in batch.items()}
