from copy import deepcopy
from dataclasses import replace
import json

import pytest
import torch

from sts2rl.combat import combat_entities
from sts2rl.micro import MicroPolicy, choose_micro_action, collate_micro, load_micro, micro_vocabulary, partition_records, teacher_targets
from sts2rl.native import ASSEMBLY_VERSION, SAMPLER, NativeError, NativeSession, digest, legal_actions
from sts2rl.teacher import equivalent_groups, heuristic, teach_root
from test_combat import observation


def state():
    result = observation()
    result["in_combat"] = True
    result["hand"][0]["target_type"] = "AnyEnemy"
    return result


def record(obs):
    actions = legal_actions(obs)
    return {"observation": obs,
            "actions": [{"id": a.id, "kind": a.kind, "args": a.args} for a in actions],
            "estimates": {a.id: {"mean_return": 140 if a.kind == "play_card" else 110} for a in actions}}


def test_native_targets_cost_checks_and_potions():
    obs = state()
    obs["enemies"].append({**obs["enemies"][0], "index": 1})
    obs["hand"].append({**obs["hand"][0], "index": 1, "can_play": False})
    obs["player"]["potions"] = [{"index": 0, "target_type": "AnyPlayer", "can_use": False},
                                 {"index": 1, "target_type": "AnyEnemy", "can_use": True}]
    actions = legal_actions(obs)
    assert len(actions) == 5
    assert [a.args["target_index"] for a in actions if a.kind == "play_card"] == [0, 1]
    assert all(a.args.get("potion_index", 1) == 1 for a in actions)
    obs["player"]["potions"][0]["can_use"] = True
    assert next(a for a in legal_actions(obs) if a.args.get("potion_index") == 0).args == {"potion_index": 0}


def test_native_rejects_stale_and_forged_actions_before_sending():
    session = NativeSession.__new__(NativeSession)
    session.state = state()
    action = legal_actions(session.state)[0]
    session.state["energy"] -= 1
    with pytest.raises(NativeError, match="Stale"):
        session.step(action)
    action = legal_actions(session.state)[0]
    with pytest.raises(NativeError, match="current public"):
        session.step(replace(action, kind="set_player"))


def test_selection_combinations_and_public_combat_context():
    combat = state()
    obs = {"decision": "card_select", "combat_state": combat, "player": combat["player"],
           "prompt": "Discard", "min_select": 0, "max_select": 2,
           "cards": [{**combat["hand"][0], "index": i} for i in range(3)]}
    assert len(legal_actions(obs)) == 7  # empty + singles + pairs
    assert len([e for e in combat_entities(obs) if e.zone == "selection_card"]) == 3
    vocab = micro_vocabulary([obs])
    batch = collate_micro([obs], vocab)
    assert sorted(batch["source"].sum(-1)[0].tolist()) == [0, 1, 1, 1, 2, 2, 2]
    obs["cards"] = [{**combat["hand"][0], "index": i} for i in range(50)]
    with pytest.raises(NativeError, match="sequential decoder"):
        legal_actions(obs)


def test_duplicates_share_targets_without_probability_inflation():
    single = state()
    double = deepcopy(single)
    double["hand"].append({**double["hand"][0], "index": 1})
    assert sorted(map(len, equivalent_groups(double, legal_actions(double)))) == [1, 2]
    first, _ = teacher_targets([record(single)])
    second, _ = teacher_targets([record(double)])
    torch.testing.assert_close(first[0, 0], second[0, :2].sum())
    torch.testing.assert_close(first[0, 1], second[0, 2])


def test_inference_aggregates_duplicate_mass_before_choosing_action():
    obs = state()
    obs["hand"].append({**obs["hand"][0], "index": 1})
    # Neither physical copy beats end_turn alone; their shared effect does.
    action = choose_micro_action(obs, torch.tensor([0.3, 0.3, 0.4]).log())
    assert action.kind == "play_card"
    assert choose_micro_action(obs, torch.tensor([0.1, 0.1, 0.8]).log()).kind == "end_turn"


def test_model_binds_targets_masks_padding_and_backpropagates():
    torch.manual_seed(3)
    a, b = state(), state()
    b["enemies"].append({**b["enemies"][0], "index": 1, "hp": 1})
    vocab = micro_vocabulary([a, b])
    model = MicroPolicy(len(vocab), width=16)
    batch = collate_micro([a, b], vocab)
    logits, value = model(batch)
    assert logits.shape == (2, 3) and logits[0, 2] < -1e8
    assert not torch.allclose(logits[1, :1], logits[1, 1:2])
    target, values = teacher_targets([record(a), record(b)])
    loss = -(target * logits.log_softmax(-1)).sum() + (value - values).square().sum()
    loss.backward()
    assert model.encoder.number.weight.grad.abs().sum() > 0
    assert model.scorer[0].weight.grad.abs().sum() > 0


def test_micro_cannot_read_seed_future_or_hidden_pile_order():
    clean, hostile = state(), state()
    hostile.update(seed="secret", future_reward=999, rng={"actual_order": [7, 4]})
    hostile["enemies"][0]["next_move_after_this_turn"] = "secret"
    hostile["draw_pile"][0]["actual_index"] = 9
    vocab = micro_vocabulary([clean])
    assert micro_vocabulary([hostile]).tokens == vocab.tokens
    first, second = collate_micro([clean], vocab), collate_micro([hostile], vocab)
    for key in first:
        torch.testing.assert_close(first[key], second[key])


def test_split_keeps_all_decisions_of_one_seed_together():
    rows = [{"group": f"seed-{i}"} for i in range(20) for _ in range(5)]
    parts, split = partition_records(rows)
    assert {s: len(r) for s, r in parts.items()} == {"train": 80, "validation": 10, "test": 10}
    assert len(split) == 20
    for name, items in parts.items():
        assert all(split[r["group"]] == name for r in items)


def test_truncated_teacher_must_not_emit_labels(monkeypatch):
    obs = state()
    class Worker:
        state = obs
        def restore(self, fork):
            pass
        def sample(self, seed):
            pass
    from sts2rl.native import ReplayFork
    fork = ReplayFork({}, (), digest(obs))
    def fail(*args, **kwargs):
        raise NativeError("Rollout truncated")
    monkeypatch.setattr("sts2rl.teacher.rollout", fail)
    with pytest.raises(NativeError, match="truncated"):
        teach_root(Worker(), fork, obs, samples=2)


def test_heuristic_uses_current_intent_and_surplus_block():
    obs = state()
    obs["hand"][0].update(id="CARD.DEFEND_SILENT", target_type="Self", type="Skill", stats={"block": 5})
    obs["player"]["block"] = 0
    assert heuristic(obs).kind == "play_card"
    obs["player"]["block"] = 20
    assert heuristic(obs).kind == "end_turn"


def test_teacher_records_round_trip_without_native_secrets():
    row = record(state())
    assert teacher_targets([json.loads(json.dumps(row))])[0].sum().item() == pytest.approx(1)


def test_saved_micro_requires_runtime_match_and_returns_bound_action(tmp_path):
    obs = state()
    vocab = micro_vocabulary([obs])
    model = MicroPolicy(len(vocab), width=16)
    path = tmp_path / "policy.pt"
    torch.save({"micro_version": 1, "sampler": SAMPLER, "assembly_version": ASSEMBLY_VERSION,
                "vocabulary": vocab.to_dict(), "width": 16, "state_dict": model.state_dict()}, path)
    policy = load_micro(path)
    with pytest.raises(ValueError, match="runtime identity"):
        policy(obs)
    obs["runtime_identity"] = {"character": "SILENT", "ascension": 10, "assembly_version": ASSEMBLY_VERSION}
    assert policy(obs) in legal_actions(obs)
