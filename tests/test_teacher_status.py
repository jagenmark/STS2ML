from types import SimpleNamespace

import pytest

from sts2rl.combat_search import CombatSearch
from sts2rl.native import legal_actions
from sts2rl.run_policy import IDENTITY, RunPolicy, RunWeights
from sts2rl.tactical_student import action_examples
from sts2rl.teacher import LEGACY_CONTINUATION, heuristic, heuristic_score
from test_micro import state


def hand(*cards):
    obs = state()
    obs["runtime_identity"] = IDENTITY
    obs["player"]["potions"] = []
    obs["enemies"][0].update(hp=40, intents=[{"total_damage": 20}])
    obs["hand"] = [
        {**obs["hand"][0], "index": i, "id": name, "type": "Skill", "cost": 0,
         "target_type": target, "stats": stats, "damage_by_target": []}
        for i, (name, target, stats) in enumerate(cards)
    ]
    return obs


def test_native_weak_and_poison_and_frozen_student_features():
    obs = hand(("CARD.NEUTRALIZE", "AnyEnemy", {"damage": 3, "weakpower": 1}),
               ("CARD.DEADLY_POISON", "AnyEnemy", {"poisonpower": 5}))
    weak, poison, _ = legal_actions(obs)
    assert heuristic_score(obs, weak) == 8
    assert heuristic_score(obs, poison) == 10
    assert heuristic(obs) == poison
    assert heuristic_score(obs, weak, version=LEGACY_CONTINUATION) == 3
    assert heuristic_score(obs, poison, version=LEGACY_CONTINUATION) == 0
    _, features = action_examples(obs, RunPolicy(RunWeights()))
    assert [r["x"][-2] for r in features] == [0.2, 0.0, 0.0]


def test_card_reward_uses_native_poison_and_prefers_it_over_the_old_alias():
    obs = {"decision": "card_reward", "can_skip": True, "cards": [
        {"index": 0, "cost": 1, "stats": {"damage": 6}},
        {"index": 1, "cost": 1, "stats": {"poisonpower": 5, "poison": 99}},
        {"index": 2, "cost": 1, "stats": {"poisonpower": 0, "poison": 99}},
        {"index": 3, "cost": 1, "stats": {"poison": 2}},
    ]}
    choices = legal_actions(obs)
    assert [heuristic_score(obs, a) for a in choices] == [5, 9, -1, 3, 0]
    assert heuristic(obs) == choices[1]


def test_native_debuffs_follow_card_target_and_poison_prerequisite():
    obs = hand(("CARD.HAZE", "AllEnemies", {"weakpower": 1, "poisonpower": 4}),
               ("CARD.BOUNCING_FLASK", "RandomEnemy", {"poisonpower": 3, "repeat": 3}),
               ("CARD.BUBBLE_BUBBLE", "AnyEnemy", {"poisonpower": 12}))
    first = obs["enemies"][0]
    first["powers"] = [{"id": "POWER.POISON_POWER", "amount": 2}]
    obs["enemies"] += [
        {**first, "index": 1, "powers": [], "intents": [{"total_damage": 8}]},
        {**first, "index": 2, "hp": 0},
    ]
    assert [heuristic_score(obs, a) for a in legal_actions(obs)] == [23, 18, 24, 0, 0]


def test_combat_search_offers_the_corrected_teacher_candidate(monkeypatch, tmp_path):
    obs = hand(("CARD.STRIKE_SILENT", "AnyEnemy", {"damage": 6}),
               ("CARD.DEFEND_SILENT", "Self", {"block": 5}),
               ("CARD.DEADLY_POISON", "AnyEnemy", {"poisonpower": 5}))
    obs["context"].update(room_type="Boss", floor=17)
    obs["act1_search_support"] = {"supported": True}
    strike, _, poison, _ = legal_actions(obs)
    agent = SimpleNamespace(combat_scores=lambda s, actions: [4, 3, 2, 1])
    search = CombatSearch(tmp_path, None, tmp_path, 0, agent)
    search.worker = SimpleNamespace(closed=False, restore=lambda fork: None, sample=lambda *a, **k: None)
    monkeypatch.setattr(search, "_rollout", lambda action, world: float(action == poison))
    assert search.choose(SimpleNamespace(state=obs, fork=lambda: None), strike, 0) == poison
    assert search.branches == 6


def test_combat_search_positive_poison_skips_an_unneeded_rollout(tmp_path):
    obs = hand(("CARD.DEADLY_POISON", "AnyEnemy", {"poisonpower": 5}))
    obs["context"].update(room_type="Boss", floor=17)
    obs["act1_search_support"] = {"supported": True}
    poison, _ = legal_actions(obs)
    search = CombatSearch(tmp_path, None, tmp_path, 0, RunPolicy(RunWeights()))
    game = SimpleNamespace(state=obs, fork=lambda: pytest.fail("Unexpected simulation"))
    assert search.choose(game, poison, 0) == poison
    assert search.attempts == 0
