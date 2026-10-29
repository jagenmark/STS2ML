"""Original synthetic journals exercise the observed public recorder schema."""

import copy
import gzip
import io
import json
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import pytest

from sts2rl.adapters.spire_codex import (
    RateLimitedError,
    download_export_page,
    download_replay,
    import_replay,
)


def header():
    return {
        "t": "header",
        "replay_version": 7,
        "build_id": "v0.test",
        "character": "IRONCLAD",
        "ascension": 10,
        "player_count": 1,
        "game_mode": "standard",
        "modifiers": [],
        "reloads": 0,
        "seed": "synthetic-seed-a",
        "starting_max_hp": 80,
        "starting_deck": [{"c": 1, "id": "CARD.STRIKE_IRONCLAD", "up": 0}],
        "starting_relics": ["BURNING_BLOOD"],
        "potions": [],
    }


def offer(did=1, **extra):
    return {
        "t": "decision",
        "decision_id": did,
        "decision_type": "card_reward",
        "source": "reward",
        "floor": 2,
        "act": 1,
        "offer_generation": 0,
        "n_presented": 2,
        "n_selectable": 2,
        "decline_available": True,
        "can_reroll": False,
        "options": [
            {
                "option_index": 0,
                "option_kind": "card",
                "option_id": "BASH",
                "instance_id": 10,
                "up": 0,
                "presented": True,
                "selectable": True,
            },
            {
                "option_index": 1,
                "option_kind": "card",
                "option_id": "ANGER",
                "instance_id": 11,
                "up": 1,
                "presented": True,
                "selectable": True,
            },
        ],
        **extra,
    }


def ending(reason="death", **extra):
    return {
        "t": "end",
        "terminal_reason": reason,
        "is_game_over": True,
        "capture_status": "complete",
        **extra,
    }


def journal(tmp_path, *events, compressed=False):
    events = copy.deepcopy(list(events))
    for index, event in enumerate(events):
        event.setdefault("s", index)
        event.setdefault("ms", index * 100)
    data = ("\n".join(json.dumps(event) for event in events) + "\n").encode()
    path = tmp_path / "test.jsonl"
    path.write_bytes(gzip.compress(data) if compressed else data)
    return path


def acquire(**extra):
    return {
        "t": "acquire",
        "decision_id": 1,
        "c": 11,
        "id": "ANGER",
        "option_index": 1,
        "source": "reward",
        **extra,
    }


def test_deck_snapshot_precedes_acquisition_and_later_reward_contains_card(tmp_path):
    path = journal(
        tmp_path,
        header(),
        {"t": "hp", "hp": 65},
        offer(),
        acquire(),
        offer(2),
        {"t": "outcome", "decision_id": 2, "outcome": "skip"},
        ending(),
    )
    examples, report = import_replay(path, run_id="human-run")
    assert report["emitted_examples"] == 2
    assert examples[0]["observation"]["deck"] == [{"id": "STRIKE_IRONCLAD", "upgrades": 0}]
    assert examples[1]["observation"]["deck"][-1] == {"id": "ANGER", "upgrades": 1}
    assert examples[0]["chosen_action_id"] == "card:1"
    assert examples[1]["chosen_action_id"] == "skip"
    assert examples[0]["outcome"] == 0.0
    assert examples[0]["observation"]["gold"] is None
    assert examples[0]["observation"]["state_quality"] == "partial_replay"


def test_only_explicit_legal_skip_is_a_label(tmp_path):
    path = journal(
        tmp_path,
        header(),
        offer(),
        {"t": "resolve", "reward_kind": "CardReward"},
        offer(2, decline_available=False),
        {"t": "outcome", "decision_id": 2, "outcome": "skip"},
        ending(),
    )
    examples, report = import_replay(path)
    assert examples == []
    assert report["rejection_reasons"] == {"ambiguous_resolution": 1, "unresolved_decision": 1}


@pytest.mark.parametrize(
    "end_event, expected",
    [
        (ending("victory"), 1.0),
        (ending("death"), 0.0),
        (ending("left_run", is_game_over=False), None),
        (ending("death", is_game_over=False), None),
        (ending("victory", capture_status="truncated"), None),
        (None, None),
    ],
)
def test_terminal_labels_are_never_invented(tmp_path, end_event, expected):
    events = [header(), offer(), acquire()]
    if end_event is not None:
        events.append(end_event)
    examples, _ = import_replay(journal(tmp_path, *events))
    assert examples[0]["outcome"] == expected


def test_hidden_draw_order_and_final_deck_cannot_change_observation(tmp_path):
    events = [
        header(),
        {"t": "draw_order", "order_deck_c": [1, 999]},
        offer(),
        acquire(),
        ending(final_deck=[{"id": "UNSEEN_FUTURE_CARD"}]),
    ]
    first, _ = import_replay(journal(tmp_path, *events), run_id="same")
    events[1]["order_deck_c"] = [666, 1]
    events[-1]["final_deck"] = [{"id": "DIFFERENT_FUTURE_CARD"}]
    events[-1]["terminal_reason"] = "victory"
    second, _ = import_replay(journal(tmp_path, *events), run_id="same")
    assert first[0]["observation"] == second[0]["observation"]
    assert first[0]["candidates"] == second[0]["candidates"]
    assert first[0]["outcome"] != second[0]["outcome"]
    assert "seed" not in first[0]["observation"]


@pytest.mark.parametrize(
    "changes, reason",
    [
        ({"mods": [{"id": "cheat", "affects_gameplay": True}]}, "gameplay_or_unknown_mod"),
        ({"mods": [{"id": "unknown"}]}, "gameplay_or_unknown_mod"),
        ({"reloads": 1}, "reloaded_run"),
        ({"player_count": 2}, "not_single_player"),
        ({"game_mode": "daily"}, "not_standard_unmodified_run"),
        ({"replay_version": 99}, "unsupported_replay_version"),
    ],
)
def test_run_quality_filters(tmp_path, changes, reason):
    start = header() | changes
    examples, report = import_replay(journal(tmp_path, start, offer(), acquire(), ending()))
    assert not examples and reason in report["excluded_run_reasons"]


def test_sequence_gap_rejects_run(tmp_path):
    examples, report = import_replay(journal(tmp_path, header(), offer(s=4), acquire()))
    assert not examples
    assert "noncontiguous_sequence" in report["excluded_run_reasons"]


def test_console_event_rejects_even_when_header_says_disabled(tmp_path):
    start = header() | {"full_console": False}
    path = journal(
        tmp_path, start, offer(), acquire(), {"t": "console", "command": "win"}, ending("victory")
    )
    examples, report = import_replay(path)
    assert not examples
    assert report["excluded_run_reasons"] == ["console_command_used"]


def test_offer_timing_is_explicit_and_strict_mode_excludes_intervening_rewards(tmp_path):
    path = journal(
        tmp_path,
        header(),
        {"t": "gold", "gold": 100},
        offer(),
        {"t": "gold", "gold": 120},
        {"t": "potion_got", "id": "BLOOD_POTION"},
        {"t": "relic", "id": "POTION_BELT"},
        acquire(),
        ending(),
    )
    examples, report = import_replay(path)
    assert len(examples) == 1 and report["state_changed_before_resolution"] == 1
    example = examples[0]
    assert example["observation"]["gold"] == 100
    assert example["observation"]["potions"] == []
    assert "POTION_BELT" not in example["observation"]["relics"]
    assert example["metadata"]["observation_timing"] == "offer_created"
    assert example["metadata"]["fields_changed_before_resolution"] == ["gold", "potions", "relics"]
    strict, report = import_replay(path, strict_timing=True)
    assert strict == []
    assert report["rejection_reasons"] == {"state_changed_after_offer": 1}


def test_now_observed_offer_resolves_its_own_prior_upgrade_without_lookahead(tmp_path):
    path = journal(tmp_path, header(), {"t": "upgrade", "c": 11, "id": "ANGER"}, offer(), acquire())
    examples, _ = import_replay(path)
    assert len(examples) == 1
    assert examples[0]["observation"]["deck"] == [{"id": "STRIKE_IRONCLAD", "upgrades": 0}]
    assert examples[0]["candidates"][1]["upgrades"] == 1


def test_unknown_upgrade_is_not_retroactively_explained_by_future_offer(tmp_path):
    first = offer()
    first["options"][1]["instance_id"] = 99
    path = journal(
        tmp_path,
        header(),
        {"t": "upgrade", "c": 11, "id": "ANGER"},
        first,
        {"t": "outcome", "decision_id": 1, "outcome": "skip"},
        offer(2),
        {"t": "outcome", "decision_id": 2, "outcome": "skip"},
    )
    examples, report = import_replay(path)
    assert len(examples) == 1 and examples[0]["decision_id"] == "2"
    assert report["rejection_reasons"] == {"unknown_deck_after_mutation": 1}


def test_inconsistent_observation_cannot_escape_schema_validation(tmp_path):
    path = journal(tmp_path, header(), {"t": "hp", "hp": 9000}, offer(), acquire())
    examples, report = import_replay(path)
    assert not examples
    assert report["rejection_reasons"] == {"canonical_schema_violation": 1}


def test_rerolls_and_conflicting_choices_rejected(tmp_path):
    path = journal(
        tmp_path,
        header(),
        offer(can_reroll=True),
        acquire(),
        offer(2),
        {"t": "outcome", "decision_id": 2, "outcome": "skip"},
        acquire(decision_id=2),
        ending(),
    )
    examples, report = import_replay(path)
    assert not examples
    assert "reroll_not_supported" in report["rejection_reasons"]
    assert "conflicting_resolution" in report["rejection_reasons"]


def test_ambiguous_mutation_invalidates_until_authoritative_snapshot(tmp_path):
    events = [
        header(),
        {"t": "remove", "c": 999, "id": "UNKNOWN"},
        offer(),
        acquire(),
        {"t": "deck", "cards": [{"c": 1, "id": "BASH", "up": 1}]},
        offer(2),
        {"t": "outcome", "decision_id": 2, "outcome": "skip"},
    ]
    examples, report = import_replay(journal(tmp_path, *events))
    assert len(examples) == 1
    assert report["rejection_reasons"]["unknown_deck_after_mutation"] == 1
    assert examples[0]["observation"]["deck"] == [{"id": "BASH", "upgrades": 1}]


def test_gzip_magic_and_seed_groups_are_stable(tmp_path):
    first, _ = import_replay(journal(tmp_path, header(), offer(), acquire(), compressed=True), "a")
    other_header = header() | {"build_id": "v0.other"}
    second, _ = import_replay(journal(tmp_path, other_header, offer(), acquire()), "b")
    assert first[0]["split_group"] == second[0]["split_group"]
    assert first[0]["split_group"] != header()["seed"]


def test_damage_is_not_double_counted_with_absolute_hp(tmp_path):
    events = [
        header(),
        {"t": "hp", "hp": 60, "d": -5, "ms": 100},
        {"t": "hit", "dst": "player", "dmg": 5, "ms": 100},
        {"t": "hit", "dst": "player", "dmg": 3, "ms": 200},
        offer(),
        acquire(),
    ]
    examples, _ = import_replay(journal(tmp_path, *events))
    assert examples[0]["observation"]["hp"] == 57


class FakeResponse(io.BytesIO):
    def __init__(self, raw, headers=None):
        super().__init__(raw)
        self.headers = headers or {}

    def geturl(self):
        return "https://spire-codex.com/observed-response"


def test_pagination_uses_header_even_when_page_is_short(tmp_path):
    payload = gzip.compress(b'{"run_hash":"sample"}\n')
    with patch(
        "sts2rl.adapters.spire_codex.urlopen",
        return_value=FakeResponse(payload, {"X-Next-Cursor": "opaque+cursor/="}),
    ) as mock:
        report = download_export_page(
            tmp_path / "page.gz", limit=1000, start="2026-01-01T00:00:00Z", cursor="last+cursor/="
        )
    assert report["next_cursor"] == "opaque+cursor/="
    assert "cursor=last%2Bcursor%2F%3D" in mock.call_args.args[0].full_url
    assert (tmp_path / "page.gz").read_bytes() == payload


def test_download_does_not_overwrite_and_cleans_partial_file(tmp_path):
    existing = tmp_path / "exists.gz"
    existing.write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        download_replay("sample", existing)
    assert existing.read_bytes() == b"keep"
    with patch("sts2rl.adapters.spire_codex.urlopen", return_value=FakeResponse(b"too big")):
        with pytest.raises(ValueError, match="limit"):
            download_replay("sample", tmp_path / "new.gz", max_bytes=2)
    assert list(tmp_path.iterdir()) == [existing]


def test_rate_limit_reports_retry_after_without_retry_storm(tmp_path):
    error = HTTPError("https://example.invalid", 429, "limited", {"Retry-After": "45"}, None)
    with patch("sts2rl.adapters.spire_codex.urlopen", side_effect=error) as mock:
        with pytest.raises(RateLimitedError) as caught:
            download_replay("sample", tmp_path / "new.gz")
    assert caught.value.retry_after == "45"
    assert mock.call_count == 1
    assert not list(Path(tmp_path).iterdir())
