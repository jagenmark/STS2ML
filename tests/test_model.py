from copy import deepcopy

import pytest
import torch

from sts2rl.encoding import NUMERIC_DIM, Vocabulary, collate_records
from sts2rl.model import MacroPolicyValue, ModelConfig, policy_value_loss


def record():
    return {
        "schema_version": 1,
        "run_id": "synthetic-run",
        "decision_id": "1",
        "source": "synthetic",
        "game_version": "synthetic",
        "split_group": "synthetic-group",
        "observation": {
            "character": "IRONCLAD",
            "decision_type": "card_reward",
            "ascension": 10,
            "act": 1,
            "floor": 3,
            "hp": 47,
            "max_hp": 80,
            "gold": 100,
            "deck": [{"id": "STRIKE", "upgrades": 0}, {"id": "BASH", "upgrades": 1}],
            "relics": ["BURNING_BLOOD", "TEST_RELIC"],
            "potions": ["TEST_POTION"],
            "state_quality": "synthetic",
        },
        "candidates": [
            {"action_id": "a", "kind": "take_card", "entity_id": "BASH", "upgrades": 0, "price": None},
            {"action_id": "b", "kind": "take_card", "entity_id": "STRIKE", "upgrades": 1, "price": None},
            {"action_id": "skip", "kind": "skip", "entity_id": None, "upgrades": None, "price": None},
        ],
        "chosen_action_id": "a",
        "outcome": 1.0,
        "metadata": {},
    }


def small_model(vocab):
    torch.manual_seed(7)
    return MacroPolicyValue(ModelConfig(len(vocab), d_model=32, n_heads=4, n_layers=1, ff_multiplier=2))


@pytest.fixture(autouse=True)
def one_cpu_thread():
    old = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


def test_vocabulary_is_stable_and_held_out_entities_are_unknown():
    training = record()
    changed = deepcopy(training)
    changed["observation"]["deck"].reverse()
    changed["candidates"].reverse()
    vocab = Vocabulary.build([training])
    assert vocab.to_dict() == Vocabulary.build([changed]).to_dict()
    assert Vocabulary.from_dict(vocab.to_dict()).to_dict() == vocab.to_dict()
    changed["observation"]["deck"][0]["id"] = "UNSEEN_HELD_OUT"
    batch = collate_records([changed], vocab)
    assert batch["state_tokens"][0, 0].item() == 1
    assert "entity:UNSEEN_HELD_OUT" not in vocab.token_to_id


def test_state_permutation_invariance_and_action_equivariance():
    original = record()
    permuted = deepcopy(original)
    permuted["observation"]["deck"].reverse()
    permuted["observation"]["relics"].reverse()
    permutation = [2, 0, 1]
    permuted["candidates"] = [permuted["candidates"][i] for i in permutation]
    vocab = Vocabulary.build([original])
    model = small_model(vocab).eval()
    with torch.no_grad():
        first = model(collate_records([original], vocab))
        second = model(collate_records([permuted], vocab))
    torch.testing.assert_close(second["value_logits"], first["value_logits"], atol=1e-6, rtol=1e-5)
    torch.testing.assert_close(
        second["policy_logits"], first["policy_logits"][:, permutation], atol=1e-6, rtol=1e-5
    )


def test_padding_masks_actions_and_empty_decks_remain_finite():
    full = record()
    empty = deepcopy(full)
    empty["observation"].update(deck=[], relics=[], potions=[])
    empty["candidates"] = [empty["candidates"][0]]
    vocab = Vocabulary.build([full])
    model = small_model(vocab).eval()
    batch = collate_records([full, empty], vocab)
    outputs = model(batch)
    assert torch.isfinite(outputs["value_logits"]).all()
    assert torch.isfinite(outputs["policy_logits"][batch["action_mask"]]).all()
    assert torch.isneginf(outputs["policy_logits"][~batch["action_mask"]]).all()
    probabilities = outputs["policy_logits"].softmax(-1)
    assert probabilities[1, 0].item() == 1.0
    assert probabilities[1, 1:].sum().item() == 0.0
    alone = model(collate_records([empty], vocab))
    torch.testing.assert_close(alone["value_logits"][0], outputs["value_logits"][1], atol=1e-6, rtol=1e-5)


def test_unknown_numeric_values_are_distinct_from_observed_zero():
    known = record()
    unknown = deepcopy(known)
    for key in ("ascension", "act", "floor", "hp", "max_hp", "gold"):
        known["observation"][key] = 0
        unknown["observation"][key] = None
    unknown["observation"]["deck"][0]["upgrades"] = None
    vocab = Vocabulary.build([known])
    batch = collate_records([known, unknown], vocab)
    assert batch["numeric"].shape == (2, NUMERIC_DIM)
    assert batch["numeric"][0, 1:12:2].sum().item() == 6
    assert batch["numeric"][1, 1:12:2].sum().item() == 0
    assert batch["state_features"][0, 0, 1].item() == 1
    assert batch["state_features"][1, 0, 1].item() == 0


def test_metadata_seed_and_outcomes_never_change_input_features():
    original = record()
    changed = deepcopy(original)
    for key in ("run_id", "decision_id", "source", "game_version", "split_group"):
        changed[key] = "private-unrelated-data"
    changed["metadata"] = {"draw_order": ["FUTURE_WIN"], "seed": "secret", "final_deck": ["WINNER"]}
    changed["observation"]["seed"] = "also-secret"
    changed["observation"]["draw_order"] = ["UNOBSERVED_CARD"]
    changed["chosen_action_id"] = "skip"
    changed["outcome"] = 0.0
    vocab = Vocabulary.build([original])
    assert Vocabulary.build([changed]).to_dict() == vocab.to_dict()
    first, second = collate_records([original], vocab), collate_records([changed], vocab)
    for key in first.keys() - {"policy_targets", "policy_mask", "value_targets", "value_mask"}:
        assert torch.equal(first[key], second[key]), key


def test_missing_value_labels_are_not_losses_and_missing_policy_labels_are_masked():
    example = record()
    example["outcome"] = None
    vocab = Vocabulary.build([example])
    model = small_model(vocab)
    batch = collate_records([example], vocab)
    assert not batch["value_mask"].item()
    losses = policy_value_loss(model(batch), batch)
    assert losses["value_loss"].item() == 0
    assert losses["policy_loss"].item() > 0
    example["chosen_action_id"] = None
    batch = collate_records([example], vocab)
    losses = policy_value_loss(model(batch), batch)
    assert batch["policy_targets"].item() == -1
    assert losses["loss"].item() == 0
    losses["loss"].backward()


def test_finite_gradients_and_learning_on_synthetic_labels():
    a, b = record(), record()
    b["observation"]["hp"] = 1
    b["observation"]["deck"] = [{"id": "STRIKE", "upgrades": 0}]
    b["chosen_action_id"] = "skip"
    b["outcome"] = 0.0
    vocab = Vocabulary.build([a, b])
    batch = collate_records([a, b], vocab)
    model = small_model(vocab)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.005)
    initial = policy_value_loss(model(batch), batch)["loss"].item()
    for _ in range(30):
        optimizer.zero_grad()
        loss = policy_value_loss(model(batch), batch)["loss"]
        loss.backward()
        assert all(torch.isfinite(p.grad).all() for p in model.parameters() if p.grad is not None)
        optimizer.step()
    final = policy_value_loss(model(batch), batch)["loss"].item()
    assert final < initial * 0.3
    assert model.parameter_count == model.count_parameters()


def test_no_silent_truncation_or_invalid_labels():
    example = record()
    vocab = Vocabulary.build([example])
    with pytest.raises(ValueError, match="truncation"):
        collate_records([example], vocab, max_state_tokens=1)
    with pytest.raises(ValueError, match="candidate actions"):
        collate_records([example], vocab, max_actions=1)
    example["chosen_action_id"] = "not-an-option"
    with pytest.raises(ValueError, match="not among"):
        collate_records([example], vocab)
    example["chosen_action_id"] = "a"
    example["observation"]["gold"] = float("nan")
    with pytest.raises(ValueError, match="finite number"):
        collate_records([example], vocab)


def test_masked_target_and_all_masked_actions_are_rejected():
    example = record()
    vocab = Vocabulary.build([example])
    batch = collate_records([example], vocab)
    model = small_model(vocab)
    batch["action_mask"][0, 0] = False
    outputs = model(batch)
    with pytest.raises(ValueError, match="masked candidate"):
        policy_value_loss(outputs, batch)
    batch["action_mask"][:] = False
    with pytest.raises(ValueError, match="at least one legal"):
        model(batch)
