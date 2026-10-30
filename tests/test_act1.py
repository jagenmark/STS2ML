from copy import deepcopy
import json
from pathlib import Path

import pytest
import torch

from sts2rl.act1 import MacroPolicy, act1_result, existing_act1_results, is_combat_choice, macro_record, save_json
from sts2rl.combat import combat_entities
from sts2rl.micro import collate_micro, micro_vocabulary, teacher_targets
from sts2rl.native import ACT1_SAMPLER, digest, legal_actions
from sts2rl.schema import validate_record
from sts2rl.teacher import combat_result, equivalent_groups
from test_micro import record, state


def test_act1_finishes_at_act2_and_does_not_count_fights_as_clears():
    obs = state()
    assert act1_result(obs) is None
    obs.update(decision="card_reward", in_combat=False)
    assert act1_result(obs) is None
    obs["context"]["act"] = 2
    assert act1_result(obs) == {"cleared_act1": True, "hp": 50}
    obs["context"]["act"] = 1
    obs.update(decision="game_over", victory=False)
    obs["player"]["hp"] = 0
    assert act1_result(obs) == {"cleared_act1": False, "hp": 0}


def test_macro_reward_projection_matches_replay_entity_ids():
    obs = state()
    obs["runtime_identity"] = {"ascension": 7}
    obs.update(decision="card_reward", cards=obs["hand"], can_skip=True)
    projected = validate_record(macro_record(obs))
    assert projected["candidates"][0]["entity_id"] == "STRIKE_SILENT"
    assert projected["observation"]["ascension"] == 7
    assert projected["observation"]["relics"] == ["NUNCHAKU"]
    assert projected["observation"]["deck"][0]["id"] == "STRIKE_SILENT"
    assert [c["action_id"] for c in projected["candidates"]] == [a.id for a in legal_actions(obs)]


def test_shop_respects_stock_gold_and_slot_limit():
    obs = state()
    obs.update(decision="shop", cards=[{"index": 0, "cost": 80, "is_stocked": True}],
               relics=[{"index": 0, "cost": 101, "is_stocked": True},
                       {"index": 1, "cost": 30, "is_stocked": False}],
               potions=[{"index": 0, "cost": 50, "is_stocked": True}])
    assert {a.kind for a in legal_actions(obs)} == {"buy_card", "buy_potion", "leave_room"}
    obs["player"]["potions"] = [{}, {}]
    assert all(a.kind != "buy_potion" for a in legal_actions(obs))
    assert MacroPolicy(4)(obs).kind == "buy_card"


def test_generated_combat_rewards_bind_card_and_selection_origin():
    combat = state()
    obs = {"decision": "card_reward", "player": combat["player"], "combat_state": combat,
           "cards": combat["hand"], "can_skip": True,
           "selection_source": {"kind": "use_potion", "id": "POTION.ATTACK_POTION"}}
    assert is_combat_choice(obs)
    assert not is_combat_choice({k: v for k, v in obs.items() if k != "combat_state"})
    entities = combat_entities(obs)
    assert any(e.identity == "POTION.ATTACK_POTION" for e in entities)
    vocab = micro_vocabulary([obs])
    batch = collate_micro([obs], vocab)
    assert batch["source"].sum(-1)[0].tolist() == [1, 0]
    obs.update(decision="bundle_select", bundles=[{"cards": combat["hand"] * 2}])
    # A bundle binds every card in the bundle, not just its first item.
    batch = collate_micro([obs], micro_vocabulary([obs]))
    assert batch["source"].sum().item() == 2


def test_public_enemy_history_changes_input_but_private_future_does_not():
    obs = state()
    obs["public_combat_history"] = [{"round": 1, "enemies": deepcopy(obs["enemies"])}]
    other = deepcopy(obs)
    other["public_combat_history"][0]["enemies"][0]["next_move"] = "SECRET"
    vocab = micro_vocabulary([obs])
    first, second = collate_micro([obs], vocab), collate_micro([other], vocab)
    for key in first:
        torch.testing.assert_close(first[key], second[key])
    other["public_combat_history"][0]["enemies"][0]["intents"][0]["total_damage"] = 11
    assert not torch.equal(first["numbers"], collate_micro([other], vocab)["numbers"])


def test_broad_return_normalization_and_terminal_labels():
    obs = state()
    obs.update(decision="map_select", in_combat=False)
    obs["player"].update(hp=70, max_hp=70)
    assert combat_result(obs, profile=ACT1_SAMPLER)["return"] == 200
    row = record(state())
    row["sampler"] = ACT1_SAMPLER
    for estimate in row["estimates"].values():
        estimate["mean_return"] = 200
    _, value = teacher_targets([row])
    assert value.item() == pytest.approx(1)
    row["sampler"] = "silent-a10-starter-beetle-v1"
    with pytest.raises(ValueError, match="Invalid curriculum"):
        teacher_targets([row])


def test_unaudited_duplicate_cards_are_not_assumed_interchangeable():
    obs = state()
    obs["hand"][0]["id"] = "CARD.UNKNOWN_STATEFUL_CARD"
    obs["hand"].append({**obs["hand"][0], "index": 1})
    assert [len(g) for g in equivalent_groups(obs, legal_actions(obs))] == [1, 1, 1]


def test_atomic_status_retries_windows_reader_lock(tmp_path, monkeypatch):
    path = tmp_path / "progress.json"
    save_json(path, {"old": True})
    original = Path.replace
    calls = []

    def locked_once(source, destination):
        calls.append(source)
        if len(calls) == 1:
            assert json.loads(path.read_text()) == {"old": True}
            raise PermissionError("Windows reader has not shared delete access")
        return original(source, destination)

    monkeypatch.setattr(Path, "replace", locked_once)
    monkeypatch.setattr("sts2rl.act1.time.sleep", lambda _: None)
    assert save_json(path, {"new": True})
    assert len(calls) == 2
    assert json.loads(path.read_text()) == {"new": True}


def test_locked_telemetry_preserves_old_file_without_aborting_run(tmp_path, monkeypatch):
    path = tmp_path / "progress.json"
    save_json(path, {"old": True})

    def locked(*args):
        raise PermissionError("Still locked")

    monkeypatch.setattr(Path, "replace", locked)
    monkeypatch.setattr("sts2rl.act1.time.sleep", lambda _: None)
    assert save_json(path, {"new": True}, best_effort=True) is False
    assert json.loads(path.read_text()) == {"old": True}
    with pytest.raises(PermissionError):
        save_json(path, {"durable_result": True})


def test_resume_keeps_complete_seed_and_archives_partial_labels(tmp_path):
    for index, status in enumerate(("complete", "error")):
        folder = tmp_path / f"run-{index:05d}"
        folder.mkdir()
        save_json(folder / "result.json", {"index": index, "status": status, "group": digest(f"PREFIX{index:06d}")})
        (folder / "teacher.jsonl").write_text("fixture", encoding="utf-8")
    complete, pending = existing_act1_results(tmp_path, 3, "PREFIX")
    assert [r["index"] for r in complete] == [0]
    assert pending == [1, 2]
    assert (tmp_path / "run-00000/teacher.jsonl").read_text() == "fixture"
    assert not (tmp_path / "run-00001").exists()
    assert len(list(tmp_path.glob("previous-attempts/*/run-00001/teacher.jsonl"))) == 1
    with pytest.raises(ValueError, match="another seed"):
        existing_act1_results(tmp_path, 3, "WRONG_PREFIX")
