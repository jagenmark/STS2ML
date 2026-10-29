"""Contract fixtures are invented inputs, not recordings from a running game."""

import copy
import json

import pytest

from sts2rl.adapters.divine import (
    INSPECTED_REVISION,
    BridgeContractError,
    DivineFullAppAdapter,
    PartialStateError,
    UnsupportedDecisionError,
    project_card_reward,
)
from sts2rl.schema import validate_record


@pytest.fixture
def observation():
    return {
        "schema_version": 2,
        "phase": "card_reward",
        "is_terminal": False,
        "is_victory": False,
        "character": "IRONCLAD",
        "ascension": 10,
        "act": 1,
        "floor": 4,
        "gold": 99,
        "player_hp": 62,
        "player_max_hp": 80,
        "deck_cards": ["STRIKE_IRONCLAD", "BASH", "STRIKE_IRONCLAD"],
        "relics": ["BURNING_BLOOD"],
        "potions": [],
        "seed": "SECRET_SEED",
        "state_hash": "SECRET_HASH",
        "rng_counters": {"SECRET_RNG": 42},
        "draw_pile": ["SECRET_ORDER"],
        "future_outcome": "SECRET_OUTCOME",
        "room": {"details": {"SECRET_ROOM_INFO": 42}},
    }


@pytest.fixture
def actions():
    return [
        {
            "action_id": "choose_card:0:BASH",
            "action_type": "choose_card",
            "description": "SECRET_DESCRIPTION",
            "metadata": {"card_index": 0, "card_id": "BASH", "upgrades": 1,
                         "hidden": "SECRET_METADATA"},
        },
        {"action_id": "skip_card", "action_type": "skip_card", "metadata": None},
    ]


def project(observation, actions, **kwargs):
    return project_card_reward(
        observation, actions, run_id="run-01", decision_id="reward-04",
        game_version="fixture-build", **kwargs
    )


def test_projection_preserves_unknown_upgrades_and_blocks_unlisted_data(observation, actions):
    before = copy.deepcopy((observation, actions))
    record = project(observation, actions, allow_partial=True)
    assert validate_record(record) is record
    assert "SECRET" not in json.dumps(record)
    assert record["observation"]["deck"] == [
        {"id": "BASH", "upgrades": None},
        {"id": "STRIKE_IRONCLAD", "upgrades": None},
        {"id": "STRIKE_IRONCLAD", "upgrades": None},
    ]
    assert record["observation"]["state_quality"] == "partial_bridge"
    assert record["candidates"][0]["upgrades"] == 1
    assert record["candidates"][1]["kind"] == "skip"
    assert record["metadata"]["inspected_source_revision"] == INSPECTED_REVISION
    assert record["outcome"] is None
    assert record["chosen_action_id"] is None
    assert record["split_group"] == "run-01"
    assert (observation, actions) == before


def test_partial_state_requires_explicit_opt_in(observation, actions):
    with pytest.raises(PartialStateError, match="allow_partial"):
        project(observation, actions)


@pytest.mark.parametrize("phase", ["combat", "map", "event", "shop", "rest_site"])
def test_unsupported_decision_is_rejected(observation, actions, phase):
    observation["phase"] = phase
    with pytest.raises(UnsupportedDecisionError):
        project(observation, actions, allow_partial=True)


def test_mismatched_card_identity_is_rejected(observation, actions):
    actions[0]["metadata"]["card_id"] = "DEFEND_IRONCLAD"
    with pytest.raises(BridgeContractError, match="disagree"):
        project(observation, actions, allow_partial=True)


def test_duplicate_action_and_absent_skip_are_rejected(observation, actions):
    with pytest.raises(BridgeContractError, match="Duplicate"):
        project(observation, actions + [actions[0]], allow_partial=True)
    with pytest.raises(BridgeContractError, match="skip"):
        project(observation, actions[:1], allow_partial=True)


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), -1, True, "80"])
def test_invalid_numerics_do_not_become_model_features(observation, actions, bad_value):
    observation["player_hp"] = bad_value
    with pytest.raises(BridgeContractError):
        project(observation, actions, allow_partial=True)


def test_unknown_schema_is_rejected(observation, actions):
    observation["schema_version"] = 3
    with pytest.raises(BridgeContractError, match="schema"):
        project(observation, actions, allow_partial=True)


class StubTransport:
    def __init__(self, observation, actions):
        self.observation, self.actions = observation, actions
        self.launched = False
        self.closed = False
        self.executed = []

    def launch(self, requested_character="IRONCLAD"):
        self.launched = True

    def start_run(self, seed, character, ascension):
        return {"observation": self.observation}

    def observe(self):
        return self.observation

    def legal_actions(self):
        return self.actions

    def step(self, action_id):
        self.executed.append(action_id)
        return {"observation": {"phase": "map"}}

    def close(self):
        self.closed = True


def test_optional_transport_and_legal_action_boundary(observation, actions):
    transport = StubTransport(observation, actions)
    adapter = DivineFullAppAdapter(transport=transport, allow_partial=True)
    assert not transport.launched
    with pytest.raises(RuntimeError, match="Launch"):
        adapter.observe()
    adapter.launch()
    record = adapter.card_reward_record(run_id="r", decision_id="d")
    assert record["observation"]["hp"] == 62.0
    with pytest.raises(BridgeContractError, match="legal"):
        adapter.step("choose_card:99:UNKNOWN")
    assert transport.executed == []
    assert adapter.step("skip_card")["observation"]["phase"] == "map"
    assert transport.executed == ["skip_card"]
    adapter.close()
    assert transport.closed
    with pytest.raises(RuntimeError, match="Launch"):
        adapter.observe()


def test_default_adapter_construction_does_not_import_or_launch_upstream(monkeypatch):
    def forbidden_import(*args, **kwargs):
        raise AssertionError("upstream import must be lazy")

    monkeypatch.setattr("sts2rl.adapters.divine.importlib.import_module", forbidden_import)
    adapter = DivineFullAppAdapter()
    adapter.close()


def test_transport_cannot_step_unsupported_phase(observation, actions):
    transport = StubTransport(observation, actions)
    adapter = DivineFullAppAdapter(transport=transport, allow_partial=True)
    adapter.launch()
    observation["phase"] = "combat"
    with pytest.raises(UnsupportedDecisionError):
        adapter.step("end_turn")
    assert transport.executed == []
    adapter.close()
