"""Experimental card-reward adapter for the inspected divine-sts2 full-app bridge.

Importing this module does not import divine-sts2, launch a game, or require game
files. The upstream bridge currently omits information that a full macro policy
needs. Projection therefore requires an explicit ``allow_partial=True`` and never
turns unknown deck upgrades into zero upgrades.
"""

from __future__ import annotations

import hashlib
import importlib
import math
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from ..schema import validate_record

UPSTREAM_REPOSITORY = "https://github.com/favet/divine-sts2"
INSPECTED_REVISION = "7cb715916fc9abfb0281c0adf4939c74468e05a4"
SUPPORTED_GAME_VERSION = "0.1.0+59260271157f76a2896f0eab5bc6ea1245d8b314"
SUPPORTED_ASSEMBLY_SHA256 = (
    "a1f9e653f1e28e4076558fee1e60d218619cb7e057b887c6417f62c62c6d7a52"
)
SUPPORTED_PCK_SHA256 = (
    "42520eb8b0911c6c0f0bd102d92b33f41abd4d26b83489817d0a6dbd7dd48587"
)


class BridgeContractError(ValueError):
    """The observed bridge payload is unsupported or internally inconsistent."""


class PartialStateError(BridgeContractError):
    """A caller has not explicitly accepted the bridge's incomplete state."""


class UnsupportedDecisionError(BridgeContractError):
    """Only card-reward decisions have an implemented policy projection."""


class FullAppTransport(Protocol):
    """Minimal inspected upstream interface; injected transports enable offline tests."""

    def launch(self, requested_character: str = "IRONCLAD") -> None: ...
    def start_run(self, seed: str, character: str, ascension: int) -> dict[str, Any]: ...
    def observe(self) -> dict[str, Any]: ...
    def legal_actions(self) -> list[dict[str, Any]]: ...
    def step(self, action_id: str) -> dict[str, Any]: ...
    def close(self) -> None: ...


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BridgeContractError(f"{field} must be a nonempty string")
    return value


def _integer(value: Any, field: str, *, optional: bool = False) -> int | None:
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BridgeContractError(f"{field} must be a nonnegative integer")
    return value


def _number(value: Any, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BridgeContractError(f"{field} must be numeric or null")
    if not math.isfinite(value) or value < 0:
        raise BridgeContractError(f"{field} must be finite and nonnegative")
    return float(value)


def _ids(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise BridgeContractError(f"{field} must be an array of identifiers")
    return [_text(item, field) for item in value]


def project_card_reward(
    observation: Mapping[str, Any],
    legal_actions: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    decision_id: str,
    game_version: str,
    split_group: str | None = None,
    allow_partial: bool = False,
) -> dict[str, Any]:
    """Build one canonical inference record using an explicit feature allowlist.

    The seed, state hash, raw room details, descriptions, hidden piles, terminal
    outcome and unrecognized metadata never enter this record. ``game_version``
    is supplied by the caller; projection alone does not verify installed files.
    IDs should be opaque run/decision IDs, not game seeds.
    """
    if not isinstance(observation, Mapping):
        raise BridgeContractError("observation must be an object")
    if observation.get("schema_version") != 2 or isinstance(
        observation.get("schema_version"), bool
    ):
        raise BridgeContractError("Only full-app bridge observation schema 2 is supported")
    if observation.get("phase") != "card_reward":
        raise UnsupportedDecisionError("Only card_reward has an implemented projection")
    if observation.get("is_terminal") is not False:
        raise BridgeContractError("Expected an explicitly nonterminal card-reward state")
    if not allow_partial:
        raise PartialStateError(
            "The bridge omits deck upgrades, enchantments and other macro context; "
            "set allow_partial=True to accept an experimental partial record"
        )
    run_id = _text(run_id, "run_id")
    decision_id = _text(decision_id, "decision_id")
    game_version = _text(game_version, "game_version")
    group = _text(split_group if split_group is not None else run_id, "split_group")
    if not isinstance(legal_actions, (list, tuple)) or not legal_actions:
        raise BridgeContractError("card_reward must have a nonempty legal action list")

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    skips = 0
    for action in legal_actions:
        if not isinstance(action, Mapping):
            raise BridgeContractError("Every legal action must be an object")
        action_id = _text(action.get("action_id"), "action_id")
        if action_id in seen:
            raise BridgeContractError(f"Duplicate action_id: {action_id}")
        seen.add(action_id)
        action_type = action.get("action_type")
        if action_type == "choose_card":
            metadata = action.get("metadata")
            if not isinstance(metadata, Mapping):
                raise BridgeContractError("choose_card requires card metadata")
            entity_id = _text(metadata.get("card_id"), "metadata.card_id")
            index = _integer(metadata.get("card_index"), "metadata.card_index")
            if action_id != f"choose_card:{index}:{entity_id}":
                raise BridgeContractError("Action ID and card metadata disagree")
            upgrades = _integer(metadata.get("upgrades"), "metadata.upgrades", optional=True)
            kind = "pick_card"
        elif action_type == "skip_card":
            if action_id != "skip_card":
                raise BridgeContractError("Unrecognized skip_card action identifier")
            kind, entity_id, upgrades = "skip", None, None
            skips += 1
        else:
            raise UnsupportedDecisionError(f"Unsupported card-reward action: {action_type!r}")
        candidates.append(
            {
                "action_id": action_id,
                "kind": kind,
                "entity_id": entity_id,
                "upgrades": upgrades,
                "price": None,
            }
        )
    if skips != 1 or len(candidates) < 2:
        raise BridgeContractError("Expected offered cards and exactly one skip candidate")

    hp = _number(observation.get("player_hp"), "player_hp")
    max_hp = _number(observation.get("player_max_hp"), "player_max_hp")
    if hp is not None and max_hp is not None and (max_hp <= 0 or hp > max_hp):
        raise BridgeContractError("Invalid HP / max HP relationship")
    record = {
        "schema_version": 1,
        "run_id": run_id,
        "decision_id": decision_id,
        "source": "divine_full_app",
        "game_version": game_version,
        "split_group": group,
        "observation": {
            "character": _text(observation.get("character"), "character"),
            "ascension": _integer(observation.get("ascension"), "ascension"),
            "decision_type": "card_reward",
            "act": _integer(observation.get("act"), "act", optional=True),
            "floor": _integer(observation.get("floor"), "floor", optional=True),
            "hp": hp,
            "max_hp": max_hp,
            "gold": _number(observation.get("gold"), "gold"),
            "deck": [
                {"id": card, "upgrades": None}
                for card in sorted(_ids(observation.get("deck_cards"), "deck_cards"))
            ],
            "relics": _ids(observation.get("relics"), "relics"),
            "potions": _ids(observation.get("potions"), "potions"),
            "state_quality": "partial_bridge",
        },
        "candidates": candidates,
        "chosen_action_id": None,
        "outcome": None,
        "metadata": {
            "upstream_repository": UPSTREAM_REPOSITORY,
            "inspected_source_revision": INSPECTED_REVISION,
            "bridge_schema_version": 2,
            "integration_status": "experimental_source_inspected",
            "missing_context": [
                "deck_upgrades",
                "deck_enchantments",
                "dynamic_card_state",
                "relic_counters",
                "complete_visible_map",
                "upcoming_boss",
            ],
        },
    }
    return validate_record(record)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class DivineFullAppAdapter:
    """Optional lazy client with a card-reward-only policy boundary.

    A supplied ``transport`` is an explicit caller-managed backend used for tests
    or experiments. Otherwise ``launch`` loads the optional upstream package,
    checks the supported installed build, and creates a fresh isolated sandbox.
    Raw methods return simulator data; only ``card_reward_record`` is model input.
    """

    def __init__(
        self,
        *,
        game_root: str | Path | None = None,
        sandbox_root: str | Path | None = None,
        game_version: str = SUPPORTED_GAME_VERSION,
        allow_partial: bool = False,
        transport: FullAppTransport | None = None,
    ) -> None:
        self.game_root = Path(game_root).expanduser().resolve() if game_root is not None else None
        self.sandbox_root = (
            Path(sandbox_root).expanduser().resolve() if sandbox_root is not None else None
        )
        self.game_version = _text(game_version, "game_version")
        self.allow_partial = allow_partial
        self._transport = transport
        self._launched = False
        self._closed = False

    def launch(self, *, character: str = "IRONCLAD") -> None:
        if self._closed or self._launched:
            raise RuntimeError("Create a fresh adapter for each launch")
        character = _text(character, "character")
        if self._transport is None:
            if os.name != "nt":
                raise RuntimeError("The inspected full-app integration requires Windows")
            if self.game_root is None or self.sandbox_root is None:
                raise ValueError("Explicit game_root and sandbox_root are required")
            if self.sandbox_root == self.game_root or self.game_root in self.sandbox_root.parents:
                raise ValueError("sandbox_root must be outside the game installation")
            if self.game_version != SUPPORTED_GAME_VERSION:
                raise BridgeContractError("Only the inspected game build can be launched")
            expected = {
                self.game_root / "data_sts2_windows_x86_64" / "sts2.dll": SUPPORTED_ASSEMBLY_SHA256,
                self.game_root / "SlayTheSpire2.pck": SUPPORTED_PCK_SHA256,
            }
            for path, fingerprint in expected.items():
                if not path.is_file() or _file_sha256(path) != fingerprint:
                    raise BridgeContractError(f"Installed game build does not match the inspected build: {path}")
            try:
                upstream = importlib.import_module("sts2_native_sim.full_app_client")
            except ImportError as exc:
                raise RuntimeError(
                    f"Install the optional divine-sts2 checkout at {INSPECTED_REVISION}; "
                    "see docs/game-integration.md"
                ) from exc
            config = upstream.FullAppClientConfig(
                game_root=str(self.game_root),
                sandbox_root=str(self.sandbox_root / f"sts2rl-{uuid4().hex}"),
                worker_id=0,
            )
            self._transport = upstream.FullAppBridgeClient(config)
        try:
            self._transport.launch(requested_character=character)
        except Exception:
            self.close()
            raise
        self._launched = True

    def _client(self) -> FullAppTransport:
        if self._closed or not self._launched or self._transport is None:
            raise RuntimeError("Launch the adapter before interacting with the bridge")
        return self._transport

    def start_run(self, *, seed: str, character: str = "IRONCLAD", ascension: int = 10) -> dict[str, Any]:
        """Start a run and return raw simulator data, not policy features."""
        return self._client().start_run(
            seed=_text(seed, "seed"),
            character=_text(character, "character"),
            ascension=_integer(ascension, "ascension"),
        )

    def observe(self) -> dict[str, Any]:
        """Read raw simulator data; use card_reward_record for the policy boundary."""
        return self._client().observe()

    def card_reward_record(
        self, *, run_id: str, decision_id: str, split_group: str | None = None
    ) -> dict[str, Any]:
        client = self._client()
        return project_card_reward(
            client.observe(),
            client.legal_actions(),
            run_id=run_id,
            decision_id=decision_id,
            game_version=self.game_version,
            split_group=split_group,
            allow_partial=self.allow_partial,
        )

    def step(self, action_id: str) -> dict[str, Any]:
        """Execute a currently legal card-reward action; reject all other phases."""
        record = self.card_reward_record(run_id="validation", decision_id="validation")
        if action_id not in {action["action_id"] for action in record["candidates"]}:
            raise BridgeContractError("Requested action is not currently legal")
        return self._client().step(action_id)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._launched = False
            if self._transport is not None:
                self._transport.close()

    def __enter__(self) -> DivineFullAppAdapter:
        self.launch()
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
