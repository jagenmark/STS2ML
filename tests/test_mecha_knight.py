import pytest

from sts2rl import run_evaluation
from sts2rl.mecha_knight import MechaTactics, burn_damage, item_features
from sts2rl.native import legal_actions, runtime_identity
from sts2rl.run_policy import INFERENCE_IDENTITY
from sts2rl.trajectory import natural_specification
from test_micro import state


def knight():
    s = state()
    s["context"].update(act=3, room_type="Elite")
    s["enemies"][0].update(
        id="MONSTER.MECHA_KNIGHT", intents=[{"type": "Defend"}, {"type": "Buff"}]
    )
    s["round"] = 3
    return s


def test_only_the_knight_and_the_attack_immediately_after_windup_are_scored():
    s = knight()
    enemy = s["enemies"][0]
    t = MechaTactics({})
    s["context"]["act"] = 2
    assert t.observe(s) is None
    s["context"]["act"] = 3
    enemy["id"] = "MONSTER.OTHER"
    assert t.observe(s) is None
    enemy["id"] = "MONSTER.MECHA_KNIGHT"
    assert t.observe(s) == "windup"
    enemy["intents"] = [{"type": "Attack", "total_damage": 45}]
    s["round"] = 4
    assert t.observe(s) == "cleave"
    assert MechaTactics({}).observe(s) is None
    s["round"] = 5
    assert t.observe(s) is None


def test_burn_uses_the_block_preview_and_ghost_is_saved_for_the_real_hit():
    s = knight()
    s["player"].update(
        block=2,
        potions=[
            {
                "id": "POTION.GHOST_IN_A_JAR",
                "index": 0,
                "can_use": True,
                "target_type": "Self",
                "vars": {},
            }
        ],
    )
    base = s["hand"][0]
    s["hand"] = [
        {
            **base,
            "id": "CARD.DEFEND_SILENT",
            "type": "Skill",
            "target_type": "Self",
            "stats": {"calculatedblock": 7},
        },
        *[
            {
                **base,
                "id": "CARD.BURN",
                "type": "Status",
                "index": i,
                "can_play": False,
                "stats": {"damage": 2},
            }
            for i in range(1, 5)
        ],
    ]
    assert burn_damage(s["hand"]) == 8
    actions = legal_actions(s)
    wind = dict(zip((a.kind for a in actions), item_features(s, actions, "windup"), strict=True))
    assert wind["play_card"]["burn"] == 6
    assert wind["use_potion"]["potions"] < 0
    s["enemies"][0]["intents"] = [{"type": "Attack", "total_damage": 45}]
    heavy = dict(zip((a.kind for a in actions), item_features(s, actions, "cleave"), strict=True))
    assert heavy["use_potion"]["potions"] > 0


def test_transfer_uses_the_requested_identity_and_restores_the_default_on_failure(monkeypatch):
    def fail(task, ascension, decision_hook):
        assert ascension == 7 and INFERENCE_IDENTITY.get() == runtime_identity(7)
        raise RuntimeError("interrupted")

    monkeypatch.setattr(run_evaluation, "_play_episode", fail)
    with pytest.raises(RuntimeError, match="interrupted"):
        run_evaluation.play_episode(({"ascension": 7},))
    assert INFERENCE_IDENTITY.get() == runtime_identity(10)
    native = {
        "cmd": "training_restore",
        "history": [],
        "ascension": 7,
        "act_list": "seeded",
        "seed": "TEST",
    }
    assert natural_specification(native, ascension=7)["ascension"] == 7
    with pytest.raises(ValueError):
        natural_specification(native)
    assert run_evaluation.verified_victory([(3, 15)], 7)
    assert not run_evaluation.verified_victory([(3, 15), (3, 15)], 10)
    assert run_evaluation.verified_victory([(3, 15), (3, 16)], 10)


def test_paid_relic_is_hidden_only_if_the_policy_attempts_the_stale_offer():
    from types import SimpleNamespace
    from sts2rl.merchant import PendingRelicPurchase

    guard = PendingRelicPurchase()
    raw = {
        "decision": "shop",
        "player": {"gold": 494, "relics": []},
        "relics": [{"index": 2, "name": "Kifuda", "cost": 180, "is_stocked": True}],
    }
    buy = SimpleNamespace(kind="buy_relic", args={"relic_index": 2})
    assert guard.corrected_view(raw, buy) is None
    guard.observe(
        raw,
        buy,
        {"decision": "card_select", "player": {"gold": 314, "relics": [{"id": "RELIC.KIFUDA"}]}},
    )
    assert guard.corrected_view(raw, buy)["relics"][0]["is_stocked"] is False
    assert raw["relics"][0]["is_stocked"] is True
    assert (
        guard.corrected_view({**raw, "relics": [{**raw["relics"][0], "name": "Shovel"}]}, buy)
        is None
    )
    guard.observe({"decision": "map_select"}, SimpleNamespace(kind="select_map_node"), {})
    assert guard.corrected_view(raw, buy) is None
