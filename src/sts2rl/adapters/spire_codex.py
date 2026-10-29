"""Public Spire Codex downloads and conservative card-reward replay import.

This is an independently written adapter, not a copy of the upstream parser.
The bulk .run export is deliberately not treated as decision-time training data.
"""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
import math
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from sts2rl.schema import SchemaError, validate_record

BASE_URL = "https://spire-codex.com"
SOURCE_REVISION = "2af6543ca7a6c76acfde6be582651c7c05e88e50"
MAX_REPLAY_BYTES = 64 * 1024 * 1024


class RateLimitedError(RuntimeError):
    """A caller should resume later, retaining the same export cursor."""

    def __init__(self, retry_after: str | None):
        self.retry_after = retry_after
        super().__init__(f"Spire Codex rate limit; Retry-After={retry_after!r}")


def _open(url: str, timeout: float):
    request = Request(
        url,
        headers={"User-Agent": "sts2rl-research/0.1", "Accept-Encoding": "identity"},
    )
    try:
        return urlopen(request, timeout=timeout)
    except HTTPError as exc:
        if exc.code == 429:
            raise RateLimitedError(exc.headers.get("Retry-After")) from exc
        raise


def _read_bounded(stream, limit: int) -> bytes:
    chunks = []
    size = 0
    while chunk := stream.read(min(65536, limit - size + 1)):
        size += len(chunk)
        if size > limit:
            raise ValueError(f"Response exceeds the {limit}-byte limit")
        chunks.append(chunk)
    return b"".join(chunks)


def _json_get(url: str, timeout: float = 30) -> dict[str, Any]:
    with _open(url, timeout) as response:
        raw = _read_bounded(response, 8 * 1024 * 1024)
    if raw.startswith(b"\x1f\x8b"):
        import io

        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            raw = _read_bounded(stream, 8 * 1024 * 1024)
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("Expected a JSON object from Spire Codex")
    return result


def get_export_manifest(*, base_url: str = BASE_URL, timeout: float = 30) -> dict:
    """Read snapshot counts/checksums without downloading the corpus."""
    return _json_get(f"{base_url.rstrip('/')}/api/exports/runs/manifest", timeout)


def list_replays(
    *,
    character: str = "IRONCLAD",
    ascension: int = 10,
    page: int = 1,
    limit: int = 20,
    base_url: str = BASE_URL,
    timeout: float = 30,
) -> dict:
    """List public solo, standard replays. The returned replay_url is a UI URL."""
    if not 1 <= limit <= 100 or page < 1 or not 0 <= ascension <= 10:
        raise ValueError("Invalid replay page, limit, or ascension")
    query = urlencode(
        dict(
            character=character,
            ascension=ascension,
            page=page,
            limit=limit,
            players="single",
            game_mode="standard",
        )
    )
    return _json_get(f"{base_url.rstrip('/')}/api/replays?{query}", timeout)


def _download(
    url: str,
    destination: str | Path,
    *,
    timeout: float,
    max_bytes: int,
    overwrite: bool,
) -> dict:
    target = Path(destination)
    if target.exists() and not overwrite:
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with _open(url, timeout) as response:
            digest = hashlib.sha256()
            size = 0
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as out:
                temporary = out.name
                while chunk := response.read(65536):
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError(f"Download exceeds the {max_bytes}-byte limit")
                    out.write(chunk)
                    digest.update(chunk)
            report = {
                "path": str(target),
                "url": response.geturl(),
                "bytes": size,
                "sha256": digest.hexdigest(),
                "next_cursor": response.headers.get("X-Next-Cursor"),
                "etag": response.headers.get("ETag"),
                "content_encoding": response.headers.get("Content-Encoding"),
            }
        if overwrite:
            os.replace(temporary, target)
        else:
            # Exclusive creation also protects against a concurrent downloader.
            os.link(temporary, target)
            os.unlink(temporary)
        temporary = None
        return report
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def download_replay(
    run_id: str,
    destination: str | Path,
    *,
    base_url: str = BASE_URL,
    timeout: float = 30,
    max_bytes: int = MAX_REPLAY_BYTES,
    overwrite: bool = False,
) -> dict:
    """Download original bytes; detect gzip by magic when subsequently importing."""
    if not run_id:
        raise ValueError("run_id cannot be empty")
    url = f"{base_url.rstrip('/')}/api/runs/{quote(run_id, safe='')}/replay"
    return _download(url, destination, timeout=timeout, max_bytes=max_bytes, overwrite=overwrite)


def download_export_page(
    destination: str | Path,
    *,
    limit: int = 1000,
    cursor: str | None = None,
    start: str | None = None,
    end: str | None = None,
    version: str | None = None,
    base_url: str = BASE_URL,
    timeout: float = 60,
    max_bytes: int = 256 * 1024 * 1024,
    overwrite: bool = False,
) -> dict:
    """Fetch one bounded raw .run page; stop paging only when next_cursor is None.

    Keep start/end/version fixed while passing the opaque cursor to the next call.
    This function does not imply the exported final decks are safe BC features.
    """
    if not 1 <= limit <= 50000:
        raise ValueError("limit must be between 1 and 50000")
    params = {"limit": limit, "cursor": cursor, "start": start, "end": end, "version": version}
    query = urlencode({key: value for key, value in params.items() if value is not None})
    return _download(
        f"{base_url.rstrip('/')}/api/exports/runs?{query}",
        destination,
        timeout=timeout,
        max_bytes=max_bytes,
        overwrite=overwrite,
    )


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if math.isfinite(value) else None
    return None


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _entity(value: Any) -> str | None:
    return value.rsplit(".", 1)[-1].upper() if isinstance(value, str) and value else None


def _deck(cards: Any) -> dict[int, dict] | None:
    if not isinstance(cards, list):
        return None
    result = {}
    for card in cards:
        if not isinstance(card, dict):
            return None
        instance = _integer(card.get("c"))
        entity = _entity(card.get("id"))
        if instance is None or entity is None or instance in result:
            return None
        upgrade = _integer(card.get("up"))
        if upgrade is not None and upgrade < 0:
            return None
        result[instance] = {"id": entity, "upgrades": upgrade}
    return result


def _load_events(path: str | Path) -> tuple[list[dict], str]:
    path = Path(path)
    with path.open("rb") as source:
        raw = _read_bounded(source, MAX_REPLAY_BYTES)
    digest = hashlib.sha256(raw).hexdigest()
    if raw.startswith(b"\x1f\x8b"):
        import io

        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            raw = _read_bounded(stream, MAX_REPLAY_BYTES)
    events = []
    for line_number, line in enumerate(raw.decode("utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid replay JSON at line {line_number}") from exc
        if not isinstance(event, dict):
            raise ValueError(f"Replay line {line_number} must be a JSON object")
        events.append(event)
    return events, digest


def import_replay(
    path: str | Path, run_id: str | None = None, *, strict_timing: bool = False
) -> tuple[list[dict], dict]:
    """Import v5-v7 solo card-reward decisions with conservative quality gates.

    State is snapshotted when the offer is recorded, before any selected card is
    acquired. Later events supply labels only. Missing fields remain unknown.
    Exact game state is not claimed: every example is marked partial_replay.
    strict_timing excludes offers whose recorded state changes before resolution.
    """
    events, digest = _load_events(path)
    run_id = run_id or f"replay:{digest}"
    report: dict[str, Any] = {
        "run_id": run_id,
        "events": len(events),
        "offered_decisions": 0,
        "emitted_examples": 0,
        "rejected_decisions": 0,
        "rejection_reasons": {},
        "excluded_run_reasons": [],
        "outcome": None,
        "strict_timing": strict_timing,
    }
    if not events or events[0].get("t") != "header":
        report["excluded_run_reasons"].append("missing_initial_header")
        return [], report
    header = events[0]
    version = _integer(header.get("replay_version"))
    excluded = report["excluded_run_reasons"]
    if version not in (5, 6, 7):
        excluded.append("unsupported_replay_version")
    if _integer(header.get("player_count")) != 1:
        excluded.append("not_single_player")
    if header.get("game_mode") != "standard" or header.get("modifiers"):
        excluded.append("not_standard_unmodified_run")
    mods = header.get("mods", [])
    if not isinstance(mods, list) or any(
        not isinstance(mod, dict) or mod.get("affects_gameplay") is not False for mod in mods
    ):
        excluded.append("gameplay_or_unknown_mod")
    if header.get("full_console") is True:
        excluded.append("console_enabled")
    if any(event.get("t") == "console" for event in events):
        excluded.append("console_command_used")
    if header.get("reloads", 0) != 0 or any(
        event.get("t") in {"resume", "reload", "remap"} for event in events
    ):
        excluded.append("reloaded_run")
    if any(_integer(event.get("s")) != index for index, event in enumerate(events)):
        excluded.append("noncontiguous_sequence")
    if sum(event.get("t") == "header" for event in events) != 1:
        excluded.append("multiple_headers")
    character = _entity(header.get("character"))
    ascension = _integer(header.get("ascension"))
    if character not in {"IRONCLAD", "SILENT", "DEFECT", "NECROBINDER", "REGENT"}:
        excluded.append("unknown_character")
    if ascension is None or not 0 <= ascension <= 10:
        excluded.append("unsupported_ascension")
    if not isinstance(header.get("build_id"), str) or not header["build_id"]:
        excluded.append("missing_game_version")
    deck = _deck(header.get("starting_deck"))
    if deck is None or not deck:
        excluded.append("missing_or_invalid_starting_deck")
    if not isinstance(header.get("starting_relics"), list):
        excluded.append("missing_starting_relics")
    if excluded:
        return [], report
    assert deck is not None
    relics = [_entity(item) for item in header["starting_relics"]]
    if any(item is None for item in relics):
        excluded.append("invalid_starting_relics")
        return [], report
    potions = [
        _entity(item.get("id"))
        for item in (header.get("potions") or [])
        if isinstance(item, dict) and item.get("id")
    ]
    hp, max_hp, gold = (None, _number(header.get("starting_max_hp")), None)
    last_hp: dict | None = None
    seed = header.get("seed")
    group_input = f"seed:{str(seed).upper()}" if seed else f"run:{run_id}"
    split_group = hashlib.sha256(group_input.encode()).hexdigest()
    pending: dict[str, dict] = {}
    invalid: dict[str, str] = {}
    deck_known = True
    unclassified_upgrades: dict[int, str] = {}
    end_events = [event for event in events if event.get("t") == "end"]
    if len(end_events) == 1:
        ending = end_events[0]
        if (
            ending is events[-1]
            and ending.get("capture_status") == "complete"
            and ending.get("is_game_over") is not False
        ):
            report["outcome"] = {"victory": 1.0, "death": 0.0}.get(ending.get("terminal_reason"))

    def label(decision_id: str, action: str | None) -> None:
        if decision_id not in pending:
            return
        if action is None:
            invalid[decision_id] = "ambiguous_resolution"
            return
        entry = pending[decision_id]
        old = entry["example"]["chosen_action_id"]
        if old is None:
            # Record the mismatch; do not retrofit pre-acquire state. Hooks may
            # emit selection effects before acquire, which would leak the label.
            initial = entry["example"]["observation"]
            current = {
                "hp": hp,
                "max_hp": max_hp,
                "gold": gold,
                "deck": list(deck.values()),
                "relics": relics,
                "potions": potions,
            }
            changed = sorted(key for key, value in current.items() if initial[key] != value)
            entry["example"]["metadata"]["fields_changed_before_resolution"] = changed
            if strict_timing and changed:
                invalid[decision_id] = "state_changed_after_offer"
        if old is not None and old != action:
            invalid[decision_id] = "conflicting_resolution"
        entry["example"]["chosen_action_id"] = action

    for event in events[1:]:
        kind = event.get("t")
        did = str(event["decision_id"]) if "decision_id" in event else None
        if kind == "decision" and event.get("decision_type") == "card_reward":
            report["offered_decisions"] += 1
            if did is None:
                did = f"missing:{event['s']}"
                invalid[did] = "missing_decision_id"
                continue
            if did in pending or did in invalid:
                invalid[did] = "repeated_or_rerolled_decision"
                continue
            if event.get("can_reroll") is not False or event.get("offer_generation", 0) != 0:
                invalid[did] = "reroll_not_supported"
                continue
            if not deck_known:
                invalid[did] = "unknown_deck_after_mutation"
                continue
            if not isinstance(event.get("decline_available"), bool):
                invalid[did] = "unknown_skip_legality"
                continue
            options = event.get("options")
            if not isinstance(options, list) or not options:
                invalid[did] = "empty_or_invalid_options"
                continue
            candidates = []
            indexes: dict[int, dict] = {}
            malformed = False
            for option in options:
                if not isinstance(option, dict):
                    malformed = True
                    break
                if option.get("presented") is not True or option.get("selectable") is not True:
                    continue
                index = _integer(option.get("option_index"))
                entity = _entity(option.get("option_id"))
                if (
                    index is None
                    or index < 0
                    or index in indexes
                    or not entity
                    or option.get("option_kind") != "card"
                ):
                    malformed = True
                    break
                candidate = {
                    "action_id": f"card:{index}",
                    "kind": "pick_card",
                    "entity_id": entity,
                    "upgrades": _integer(option.get("up")),
                    "price": None,
                }
                candidates.append(candidate)
                indexes[index] = {"candidate": candidate, "instance": option.get("instance_id")}
            if (
                malformed
                or not candidates
                or event.get("n_selectable", len(indexes)) != len(indexes)
            ):
                invalid[did] = "invalid_candidate_set"
                continue
            # Reward generation can upgrade an offered card before logging the
            # offer. Resolve that event only when this now-observed offer names
            # the exact instance and entity. Never inspect a later event.
            for entry in indexes.values():
                instance = _integer(entry["instance"])
                if unclassified_upgrades.get(instance) == entry["candidate"]["entity_id"]:
                    del unclassified_upgrades[instance]
            if unclassified_upgrades:
                invalid[did] = "unknown_deck_after_mutation"
                continue
            if event["decline_available"]:
                candidates.append(
                    {
                        "action_id": "skip",
                        "kind": "skip",
                        "entity_id": None,
                        "upgrades": None,
                        "price": None,
                    }
                )
            observation = {
                "character": character,
                "ascension": ascension,
                "decision_type": "card_reward",
                "act": _integer(event.get("act")),
                "floor": _integer(event.get("floor")),
                "hp": hp,
                "max_hp": max_hp,
                "gold": gold,
                "deck": copy.deepcopy(list(deck.values())),
                "relics": list(relics),
                "potions": list(potions),
                "state_quality": "partial_replay",
            }
            pending[did] = {
                "indexes": indexes,
                "example": {
                    "schema_version": 1,
                    "run_id": run_id,
                    "decision_id": did,
                    "source": "spire_codex_replay",
                    "game_version": header["build_id"],
                    "split_group": split_group,
                    "observation": observation,
                    "candidates": candidates,
                    "chosen_action_id": None,
                    "outcome": report["outcome"],
                    "metadata": {
                        "replay_version": version,
                        "offer_sequence": event["s"],
                        "observation_timing": "offer_created",
                        "fields_changed_before_resolution": [],
                        "unknown_scalars": [
                            name for name in ("hp", "max_hp", "gold") if observation[name] is None
                        ],
                        "grouping": "seed" if seed else "run",
                        "source_revision": SOURCE_REVISION,
                    },
                },
            }
        elif kind == "outcome" and did in pending:
            if event.get("outcome") == "skip":
                legal = any(c["kind"] == "skip" for c in pending[did]["example"]["candidates"])
                label(did, "skip" if legal else None)
            elif event.get("outcome") in {"chosen", "select"}:
                index = _integer(event.get("option_index"))
                entry = pending[did]["indexes"].get(index)
                label(did, entry["candidate"]["action_id"] if entry else None)
        elif kind == "acquire":
            entity = _entity(event.get("id"))
            instance = _integer(event.get("c"))
            selected = None
            if did in pending:
                choices = pending[did]["indexes"]
                index = _integer(event.get("option_index"))
                if index is not None:
                    selected = choices.get(index)
                else:
                    matching = [
                        item
                        for item in choices.values()
                        if item["instance"] == instance and instance is not None
                    ]
                    if len(matching) == 1:
                        selected = matching[0]
                if selected and selected["candidate"]["entity_id"] == entity:
                    label(did, selected["candidate"]["action_id"])
                else:
                    label(did, None)
            if entity is None or instance is None or instance in deck:
                deck_known = False
            else:
                upgrade = (
                    selected["candidate"]["upgrades"] if selected else _integer(event.get("up"))
                )
                deck[instance] = {"id": entity, "upgrades": upgrade}
                if unclassified_upgrades.get(instance) == entity:
                    del unclassified_upgrades[instance]
        elif kind == "deck":
            snapshot = _deck(event.get("cards"))
            if snapshot is None:
                deck_known = False
            else:
                deck, deck_known = snapshot, True
                unclassified_upgrades.clear()
        elif kind in {"remove", "upgrade"}:
            instance = _integer(event.get("c"))
            if instance not in deck:
                entity = _entity(event.get("id"))
                if kind == "upgrade" and instance is not None and entity is not None:
                    unclassified_upgrades[instance] = entity
                else:
                    deck_known = False
            elif kind == "remove":
                del deck[instance]
            else:
                # Some replay versions log no resulting upgrade level.
                deck[instance]["upgrades"] = _integer(event.get("up"))
        elif kind == "transform":
            old, new = _integer(event.get("from_c")), _integer(event.get("to_c"))
            entity = _entity(event.get("to_id"))
            if old not in deck or new is None or new in deck or entity is None:
                deck_known = False
            else:
                del deck[old]
                deck[new] = {"id": entity, "upgrades": _integer(event.get("up"))}
        elif kind == "hp" and event.get("dst", "player") in {"player", character}:
            if event.get("mine") is not False:
                hp = _number(event.get("hp"))
                last_hp = event
        elif kind == "hit" and event.get("dst") in {"player", character}:
            damage = _number(event.get("dmg"))
            # Older journals write absolute hp immediately before the same hit;
            # newer journals record the damage alone. Do not count both.
            already_recorded = (
                bool(
                    last_hp
                    and last_hp.get("s") == event["s"] - 1
                    and last_hp.get("ms") == event.get("ms")
                    and _number(last_hp.get("d")) == -damage
                )
                if damage is not None
                else False
            )
            if not already_recorded:
                hp = max(0.0, hp - damage) if hp is not None and damage is not None else None
        elif kind == "max_hp" and event.get("dst", "player") in {"player", character}:
            max_hp = _number(event.get("max_hp"))
            if "hp" in event:
                hp = _number(event["hp"])
        elif kind == "gold":
            gold = _number(event.get("gold"))
        elif kind == "shop":
            gold = _number(event.get("gold"))
        elif kind == "buy":
            # gold_on_hand has changed timing across recorder versions.
            gold = None
        elif kind in {"relic", "relic_lost", "potion_got", "potion_used", "potion_dropped"}:
            entity = _entity(event.get("id"))
            if entity:
                collection = relics if kind.startswith("relic") else potions
                if kind in {"relic", "potion_got"}:
                    collection.append(entity)
                elif entity in collection:
                    collection.remove(entity)

    examples = []
    for decision_id, entry in pending.items():
        if decision_id not in invalid and entry["example"]["chosen_action_id"] is None:
            invalid[decision_id] = "unresolved_decision"
        if decision_id not in invalid:
            try:
                validate_record(entry["example"])
            except SchemaError:
                invalid[decision_id] = "canonical_schema_violation"
            else:
                examples.append(entry["example"])
    report["emitted_examples"] = len(examples)
    report["state_changed_before_resolution"] = sum(
        bool(entry["example"]["metadata"]["fields_changed_before_resolution"])
        for entry in pending.values()
    )
    report["rejected_decisions"] = len(invalid)
    report["rejection_reasons"] = dict(sorted(Counter(invalid.values()).items()))
    return examples, report
