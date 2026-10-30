from copy import deepcopy

import pytest
import torch

from sts2rl.combat import CombatStateEncoder, collate_combat, combat_entities, combat_vocabulary


def observation():
    card = {"id": "CARD.STRIKE_SILENT", "type": "Attack", "cost": 1, "upgrades": 0,
            "stats": {"damage": 6}, "keywords": []}
    return {
        "decision": "combat_play", "observation_version": 2, "round": 2, "energy": 3,
        "max_energy": 3, "context": {"act": 1, "floor": 4, "room_type": "Monster"},
        "hand": [{**card, "index": 0, "can_play": True}],
        "draw_pile": [card, {**card, "upgrades": 1, "stats": {"damage": 9}}],
        "discard_pile": [], "exhaust_pile": [], "play_pile": [],
        "enemies": [{"id": "MONSTER.TEST", "index": 0, "hp": 20, "max_hp": 40,
                     "block": 0, "intents": [{"type": "Attack", "damage": 3,
                                              "hits": 2, "total_damage": 6}]}],
        "player": {"hp": 50, "max_hp": 70, "block": 3, "gold": 100, "potions": [],
                   "deck": [card], "relics": [{
                       "id": "RELIC.NUNCHAKU", "show_counter": True, "counter": 9,
                       "status": "Active", "is_used_up": False, "stack_count": 1,
                       "vars": {"Cards": 10, "Energy": 1}, "counter_rule": {
                           "unit": "attack_played", "threshold": 10, "remaining": 1,
                           "effect": "gain_energy", "effect_amount": 1,
                       },
                   }]},
    }


def test_live_relic_counter_reaches_neural_input_and_gradients():
    torch.manual_seed(42)
    nine, zero = observation(), observation()
    zero["player"]["relics"][0]["counter"] = 0
    zero["player"]["relics"][0]["counter_rule"]["remaining"] = 10
    vocab = combat_vocabulary([nine])
    batch = collate_combat([nine, zero], vocab)
    encoder = CombatStateEncoder(len(vocab), width=16)
    # Numeric input, not just a different textual observation.
    assert not torch.equal(batch["numbers"][0], batch["numbers"][1])
    batch["numbers"].requires_grad_()
    pooled, _ = encoder(batch)
    assert not torch.allclose(pooled[0], pooled[1])
    pooled[0, 0].backward()
    counter = batch["fields"] == vocab.encode("field:counter")
    assert batch["numbers"].grad[counter].abs().sum() > 0


def test_missing_counter_is_not_zero_and_unknown_rule_is_not_fabricated():
    known, unknown = observation(), observation()
    known["player"]["relics"][0]["counter"] = 0
    unknown["player"]["relics"][0].update(counter=None, counter_rule=None, show_counter=False)
    vocab = combat_vocabulary([known, unknown])
    batch = collate_combat([known, unknown], vocab)
    position = (batch["fields"] == vocab.encode("field:counter")).nonzero()
    assert [batch["numbers"][b, e, a, 1].item() for b, e, a in position] == [1, 0]
    relic = next(e for e in combat_entities(unknown) if e.zone == "relic")
    assert relic.attributes["rule.remaining"] is None
    assert relic.attributes["rule_known"] is False


def test_hidden_metadata_and_descriptions_cannot_enter_network():
    clean = observation()
    hostile = deepcopy(clean)
    hostile.update(seed="hidden-seed", rng={"future": 91}, runtime_identity={"seed": "private"})
    hostile["player"]["relics"][0].update(private_counter=123, description="secret token")
    hostile["draw_pile"][0]["underlying_index"] = 7
    hostile["enemies"][0]["future_moves"] = ["hidden move"]
    vocab = combat_vocabulary([clean])
    assert vocab.tokens == combat_vocabulary([hostile]).tokens
    for key, tensor in collate_combat([clean], vocab).items():
        assert torch.equal(tensor, collate_combat([hostile], vocab)[key])


def test_unordered_piles_preserve_modified_duplicates_and_zone():
    torch.manual_seed(7)
    clean, reversed_pile, changed, moved = (observation() for _ in range(4))
    reversed_pile["draw_pile"].reverse()
    changed["draw_pile"][1]["upgrades"] = 0
    moved["exhaust_pile"].append(moved["draw_pile"].pop())
    vocab = combat_vocabulary([clean, moved])
    encoder = CombatStateEncoder(len(vocab), width=16).eval()
    pooled, _ = encoder(collate_combat([clean, reversed_pile, changed, moved], vocab))
    torch.testing.assert_close(pooled[0], pooled[1], atol=1e-6, rtol=1e-5)
    assert not torch.allclose(pooled[0], pooled[2])
    assert not torch.allclose(pooled[0], pooled[3])
    assert len([e for e in combat_entities(clean) if e.zone == "draw_pile"]) == 2


def test_padding_does_not_change_prediction_and_unseen_ids_remain_unknown():
    short, long = observation(), observation()
    long["draw_pile"].extend(deepcopy(long["draw_pile"]) * 3)
    vocab = combat_vocabulary([short])
    encoder = CombatStateEncoder(len(vocab), width=16).eval()
    alone, _ = encoder(collate_combat([short], vocab))
    batched, _ = encoder(collate_combat([short, long], vocab))
    torch.testing.assert_close(alone[0], batched[0], atol=1e-6, rtol=1e-5)
    long["player"]["relics"][0]["id"] = "RELIC.UNSEEN"
    batch = collate_combat([long], vocab)
    assert (batch["entities"] == 1).any()
    assert "entity:RELIC.UNSEEN" not in vocab.tokens


@pytest.mark.parametrize("kind", ["version", "pile", "relic", "nan", "oversize"])
def test_incomplete_or_invalid_observations_fail_closed(kind):
    state = observation()
    vocab = combat_vocabulary([state])
    if kind == "version":
        state["observation_version"] = 1
    elif kind == "pile":
        del state["exhaust_pile"]
    elif kind == "relic":
        del state["player"]["relics"][0]["counter"]
    elif kind == "nan":
        state["player"]["relics"][0]["counter"] = float("nan")
    else:
        state["draw_pile"] *= 1024
    with pytest.raises(ValueError):
        collate_combat([state], vocab)
