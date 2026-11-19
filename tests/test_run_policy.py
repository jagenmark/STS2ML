from dataclasses import replace
import json

import pytest

from sts2rl.native import NativeError, NativeSession, digest, legal_actions, selected_cards
from sts2rl.offer_policy import OfferModel
from sts2rl.routing import RoomModel
from sts2rl.run_evaluation import act2_start, verified_victory
from sts2rl.run_policy import IDENTITY, RunPolicy, RunWeights
from sts2rl.tactical_student import action_examples
from sts2rl.turn_planning import choose_turn
from test_micro import state


def test_large_selection_validates_one_bound_subset_in_public_order():
    obs = {"decision": "card_select", "cards": [{"index": i} for i in range(19)],
           "min_select": 4, "max_select": 4}
    session = NativeSession.__new__(NativeSession)
    session.state, session.history = obs, []
    session._request = lambda command: {"decision": "map_select"}
    with pytest.raises(NativeError, match="1024|sequential"):
        legal_actions(obs)
    action = selected_cards(obs, [9, 4, 2, 0])
    assert action.args == {"indices": "0,2,4,9"}
    for bad in ([0, 0, 1, 2], [0, 1, 2, 20], [1, 2]):
        with pytest.raises(NativeError):
            selected_cards(obs, bad)
    with pytest.raises(NativeError, match="current public"):
        session.step(replace(action, args={"indices": "0,2,4,8"}))
    assert session.step(action) == {"decision": "map_select"}
    assert session.history == [action.command()]


def test_visible_hand_plans_two_card_lethal_under_lethal_intent():
    obs = state()
    obs.update(runtime_identity=IDENTITY, energy=2, context={"act": 1, "floor": 3, "room_type": "Monster"})
    obs["player"].update(hp=8, block=0)
    obs["enemies"][0].update(hp=12, max_hp=12, intents=[{"type": "Attack", "total_damage": 15}])
    strike = obs["hand"][0]
    defend = {**strike, "index": 2, "id": "CARD.DEFEND_SILENT", "type": "Skill",
              "stats": {"block": 6}, "target_type": "Self"}
    obs["hand"] = [strike, {**strike, "index": 1}, defend]
    policy = RunPolicy(RunWeights())
    assert choose_turn(obs, policy).args == {"card_index": 0, "target_index": 0}
    groups, examples = action_examples(obs, policy)
    assert sorted(len(g) for g in groups) == [1, 1, 2]
    assert len(examples) == 3
    obs["draw_pile"] = list(reversed(obs["draw_pile"])) + [defend]
    assert choose_turn(obs, policy).args["card_index"] == 0
    assert action_examples(obs, policy)[1] == examples


def test_map_planning_follows_the_values_of_visible_children():
    model = RoomModel({"RestSite": [20, 160, 0, 0, 0], "Monster": [20, -160, 0, 0, 2]})
    choices = [{"col": 0, "row": 1, "type": "Unknown"}, {"col": 1, "row": 1, "type": "Unknown"}]
    obs = {"decision": "map_select", "choices": choices, "runtime_identity": IDENTITY, "context": {"act": 2},
           "player": {"hp": 20, "max_hp": 60, "gold": 40}}
    graph = [[{**n, "children": [{"col": n["col"], "row": 2}]} for n in choices],
             [{"col": 0, "row": 2, "type": "Monster"}, {"col": 1, "row": 2, "type": "RestSite"}]]
    action = model.choose(obs, graph)
    assert action in legal_actions(obs) and action.args["col"] == 1


def test_offer_fit_ignores_seed_difficulty_shared_by_all_options():
    def root(base):
        return {"arms": [{"prior": 0., "features": {"a": 1.}, "return": base},
                         {"prior": 0., "features": {"b": 1.}, "return": base + 2}]}
    first = OfferModel.fit([root(0), root(2)])
    second = OfferModel.fit([root(100), root(-40)])
    assert first.weights == pytest.approx(second.weights)
    assert first.weights["b"] > first.weights["a"]


def test_curriculum_uses_natural_map_boundary_and_full_game_requires_two_bosses(tmp_path):
    first = {"cmd": "training_restore", "history": [], "seed": "TRAIN", "ascension": 10}
    cmds = [first, {"cmd": "action", "action": "select_map_node", "args": {"row": 16}},
            {"cmd": "action", "action": "skip_card_reward", "args": {}}, {"cmd": "get_map"},
            {"cmd": "action", "action": "select_map_node", "args": {"row": 0}}]
    path = tmp_path / "rpc.jsonl"
    path.write_text("\n".join(json.dumps({"command": c, "response_digest": digest(i)}) for i, c in enumerate(cmds)))
    fork = act2_start(path)
    assert fork.specification == {"seed": "TRAIN", "ascension": 10}
    assert fork.history == tuple(cmds[1:3]) and fork.expected_digest == digest(2)
    assert not verified_victory([[1, 16], [2, 15], [3, 15], [3, 15]])
    assert verified_victory([[3, 15], [3, 16]])


def test_bundle_rejects_damaged_weights(tmp_path):
    import hashlib
    from sts2rl.run_bundle import load_bundle

    weights = tmp_path / "weights.json"
    weights.write_text(json.dumps(RunWeights().checkpoint()))
    bundle = tmp_path / "policy.json"
    bundle.write_text(json.dumps({"version": 1, "runtime_identity": IDENTITY, "actor": "candidate",
                                  "turn_search": True, "files": {"weights": {"name": weights.name,
                                  "sha256": hashlib.sha256(weights.read_bytes()).hexdigest()}}}))
    role, settings = load_bundle(bundle)
    assert role == "candidate" and settings["turn_search"] and settings["weights"] == weights
    weights.write_text("{}")
    with pytest.raises(ValueError, match="checksum"):
        load_bundle(bundle)


def test_persistent_card_value_uses_only_observed_deck_synergies():
    policy = RunPolicy(RunWeights(), deck_effects=True)
    accuracy = {"id": "CARD.ACCURACY", "type": "Power", "cost": 1, "stats": {"accuracypower": 3}}
    shivs = {"id": "CARD.BLADE_DANCE", "stats": {"cards": 3}}
    assert policy.card_value(accuracy, deck=[shivs]) > policy.card_value(accuracy, deck=[])
    original = RunPolicy(RunWeights())
    assert original.card_value(accuracy, deck=[shivs]) == original.card_value(accuracy, deck=[])


def test_single_smith_option_remembers_the_upgrade_selection():
    policy = RunPolicy(RunWeights())
    player = {"hp": 40, "max_hp": 40, "deck": []}
    rest = {"decision": "rest_site", "runtime_identity": IDENTITY, "player": player,
            "options": [{"index": 3, "option_id": "SMITH"}]}
    assert policy(rest).args == {"option_index": 3}
    cards = [{"id": "CARD.STRIKE_SILENT", "index": 0, "type": "Attack", "stats": {"damage": 6},
              "after_upgrade": {"stats": {"damage": 9}}},
             {"id": "CARD.SLICE", "index": 1, "type": "Attack", "stats": {"damage": 5},
              "after_upgrade": {"stats": {"damage": 7}}}]
    selection = {"decision": "card_select", "runtime_identity": IDENTITY, "player": player,
                 "min_select": 1, "max_select": 1, "cards": cards}
    assert policy(selection).args == {"indices": "0"}
