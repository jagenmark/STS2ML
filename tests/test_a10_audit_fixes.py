from copy import deepcopy
from dataclasses import asdict, replace
import gzip
import importlib.util
import json
from pathlib import Path
import sys

import pytest
import torch

from sts2rl.aggregation import aggregate_source
from sts2rl.combat_effects import debuff_order, landed_debuffs
from sts2rl.micro import fit_micro
from sts2rl.native import digest, legal_actions
from sts2rl.opening_split import select_openings
from sts2rl.provenance import feature_provenance, label_provenance, mc_provenance, read_encounter_runs
from sts2rl.return_policy import ReturnPolicy
from sts2rl.run_policy import IDENTITY, RunPolicy, RunWeights
from sts2rl.tactical_student import make_network
from sts2rl.teacher import CONTINUATION, heuristic_score
from sts2rl.turn_planning import choose_turn
from test_curriculum import curriculum_row
from test_dagger import source_fixture
from test_teacher_status import hand


def test_public_block_is_final_and_one_stack_blocks_neutralize():
    obs = hand(("CARD.NEUTRALIZE", "AnyEnemy", {"weakpower": 1, "damage": 3}),
               ("CARD.DEFEND_SILENT", "Self", {"block": 3}))
    obs["hand"][0]["type"] = "Attack"
    obs["hand"][1]["cost"] = 1
    obs["player"].update(hp=10, block=0)
    enemy = obs["enemies"][0]
    enemy.update(powers=[{"id": "POWER.ARTIFACT_POWER", "amount": 1}], intents=[{"total_damage": 12}])
    policy = RunPolicy(RunWeights())
    neutralize, defend, _ = legal_actions(obs)
    assert heuristic_score(obs, neutralize) == 3
    assert policy(obs) == choose_turn(obs, policy, depth=1) == defend
    enemy["powers"] = []
    neutralize = legal_actions(obs)[0]
    assert heuristic_score(obs, neutralize) == 6
    assert policy(obs) == choose_turn(obs, policy, depth=1) == neutralize

    obs["hand"] = [obs["hand"][1]]
    obs["hand"][0]["stats"] = {"block": 7}
    obs["player"].update(hp=5, potions=[{"id": "POTION.BLOCK_POTION", "index": 0, "target_type": "Self",
                                        "vars": {"Block": 8}, "can_use": True}])
    for dex in (-2, 0, 2):
        obs["player_powers"] = [{"id": "POWER.DEXTERITY_POWER", "amount": dex}]
        # 7 leaves a lethal 5 incoming. The 8-block potion saves one HP.
        assert policy(obs).kind == choose_turn(obs, policy, depth=1).kind == "use_potion"


def test_artifact_is_consumed_across_cards_and_within_a_card():
    obs = hand(("CARD.NEUTRALIZE", "AnyEnemy", {"weakpower": 1, "damage": 3}),
               ("CARD.DEADLY_POISON", "AnyEnemy", {"poisonpower": 5}))
    obs["hand"][0]["type"] = "Attack"
    obs["hand"][1]["cost"] = 1
    obs["player"].update(hp=10, block=0)
    enemy = obs["enemies"][0]
    enemy.update(powers=[{"id": "POWER.ARTIFACT_POWER", "amount": 1}], intents=[{"total_damage": 12}])
    # Poison first spends Artifact, which allows Neutralize to prevent lethal.
    assert choose_turn(obs, RunPolicy(RunWeights()), depth=2).args["card_index"] == 1
    haze = {"id": "CARD.HAZE", "target_type": "AllEnemies"}
    applications = debuff_order(haze, {"poisonpower": 4, "weakpower": 2}, enemy)
    assert landed_debuffs(haze, applications, 1) == {"weak": 2}
    assert landed_debuffs(haze, applications, 2) == {}
    flask = {"id": "CARD.BOUNCING_FLASK", "target_type": "RandomEnemy"}
    applications = debuff_order(flask, {"poisonpower": 3, "repeat": 3}, enemy)
    assert landed_debuffs(flask, applications, 1) == {"poison": 6}
    assert landed_debuffs(flask, applications, 1, targets=2)["poison"] == pytest.approx(1.875)


def test_null_intents_and_nightmare_copy_at_normal_policy_entry_point():
    obs = hand(("CARD.DEFEND_SILENT", "Self", {"block": 5}))
    policy = RunPolicy(RunWeights(), deck_effects=True)
    obs["enemies"][0]["intents"] = None
    scores = policy.combat_scores(obs, legal_actions(obs))
    assert policy(obs) in legal_actions(obs)
    obs["enemies"][0]["intents"] = []
    assert scores == policy.combat_scores(obs, legal_actions(obs))
    choice = {"decision": "card_select", "runtime_identity": IDENTITY, "in_combat": True,
              "player": obs["player"], "min_select": 1, "max_select": 1,
              "selection_source": {"id": "CARD.NIGHTMARE"}, "cards": [
                  {"index": 0, "id": "CARD.ASCENDERS_BANE", "type": "Curse"},
                  {"index": 1, "id": "CARD.DAGGER_THROW", "type": "Attack", "stats": {"damage": 9}}]}
    assert policy(choice).args["indices"] == "1"
    choice["selection_source"] = {"id": "CARD.SURVIVOR"}
    assert policy(choice).args["indices"] == "0"


@pytest.mark.parametrize("deck_effects", [False, True])
def test_strength_loss_counts_only_hits_from_the_chosen_unshielded_target(deck_effects):
    obs = hand(("CARD.DARK_SHACKLES", "AnyEnemy", {"strengthloss": 9}))
    obs["player"].update(hp=50, block=0)
    enemy = obs["enemies"][0]
    enemy.update(intends_attack=True, intents=[{"type": "Attack", "damage": 12}],
                 powers=[{"id": "POWER.ARTIFACT_POWER", "amount": 1}])
    obs["enemies"].append({**enemy, "index": 1, "powers": [],
                           "intents": [{"type": "Attack", "damage": 10, "hits": 3}]})
    weights = RunWeights()
    policy = RunPolicy(weights, deck_effects=deck_effects)
    shielded, unshielded, end = policy.combat_scores(obs, legal_actions(obs))
    assert shielded == end == 0
    assert unshielded == pytest.approx(27 * weights.block * (1 + 42 / 50) + weights.free)


@pytest.mark.parametrize("kind", ["unversioned", "old_version", "changed_code"])
def test_dagger_rejects_stale_source_and_direct_fit_inputs(tmp_path, kind):
    source = tmp_path / "old"
    config, _ = source_fixture(source)
    row = curriculum_row(0)
    if kind == "unversioned":
        del row["teacher_provenance"]
    elif kind == "old_version":
        row["continuation"] = "public-combat-heuristic-v3"
    else:
        row["teacher_provenance"]["code_sha256"] = "different"
    path = source / "run-00000/teacher.jsonl"
    saved = json.loads(path.read_text())
    row["group"] = saved["group"]
    path.write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="provenance|continuation"):
        aggregate_source(source, {**config, "prefix": "NEXT"})
    with pytest.raises(ValueError, match="provenance|continuation"):
        fit_micro([path], tmp_path / "model", epochs=1)
    assert not (tmp_path / "model").exists()
    assert mc_provenance(CONTINUATION) == config["teacher_provenance"]


def test_return_fit_and_runtime_reject_different_weights_or_code(tmp_path, monkeypatch):
    script = Path(__file__).resolve().parents[1] / "scripts/train-silent-returns.py"
    spec = importlib.util.spec_from_file_location("return_training", script)
    trainer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trainer)
    source = tmp_path / "labels/run-0000"
    source.mkdir(parents=True)
    prior = RunWeights()
    stamp = label_provenance(prior, script)
    (source / "result.json").write_text(json.dumps({"label_provenance": stamp}))
    path = source / "decisions.jsonl.gz"
    def write_row(provenance):
        with gzip.open(path, "wt") as stream:
            stream.write(json.dumps({"label_provenance": provenance}) + "\n")
    write_row(stamp)
    weights = tmp_path / "weights.json"
    weights.write_text(json.dumps(replace(prior, block=5).checkpoint()))
    out = tmp_path / "fit"
    monkeypatch.setattr(sys, "argv", [str(script), "fit", "--weights", str(weights),
                                      "--source", str(source.parent), "--output", str(out)])
    with pytest.raises(ValueError, match="label_provenance"):
        trainer.main()
    assert not out.exists()
    weights.write_text(json.dumps(prior.checkpoint()))
    write_row({**stamp, "teacher_sha256": "old"})
    with pytest.raises(ValueError, match="label_provenance"):
        trainer.main()

    data = {"version": 2, "runtime_identity": IDENTITY, "vocab": {}, "weights": asdict(prior),
            "feature_provenance": feature_provenance(prior), "width": 8, "inputs": 4, "margin": 0.4,
            "state_dict": make_network(8, 4, 1).state_dict()}
    model = tmp_path / "returns.pt"
    torch.save(data, model)
    assert ReturnPolicy(model).prior.weights == prior
    data["weights"]["block"] = 5
    torch.save(data, model)
    with pytest.raises(ValueError, match="feature_provenance"):
        ReturnPolicy(model)


def test_distillation_requires_compatible_encounter_outcomes(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts/train-silent-encounters.py"
    original = RunWeights()
    different = replace(original, block=5)
    for i, weights in enumerate([original, different]):
        source = tmp_path / f"run-{i:04d}"
        source.mkdir()
        stamp = label_provenance(weights, script)
        (source / "labels.json").write_text(json.dumps({
            "policy_weights": weights.checkpoint()["weights"], "label_provenance": stamp,
            "roots": [{"label_provenance": stamp, "seed": str(i)}],
        }))
    with pytest.raises(ValueError, match="label_provenance"):
        list(read_encounter_runs([tmp_path], script))
    with pytest.raises(ValueError, match="label_provenance"):
        list(read_encounter_runs([tmp_path], script, different))
    (tmp_path / "run-0001/labels.json").unlink()
    assert next(read_encounter_runs([tmp_path], script, original))[1][0]["seed"] == "0"
    (tmp_path / "run-0000/labels.json").write_text(json.dumps({"roots": []}))
    with pytest.raises(ValueError, match="Missing encounter outcome weights"):
        list(read_encounter_runs([tmp_path], script, original))


def test_opening_split_is_disjoint_portable_and_rejects_a_changed_lock(tmp_path):
    pool = tmp_path / "pool"
    for i in range(90):
        run = pool / f"run-{i:03d}"
        (run / "game").mkdir(parents=True)
        seed = f"ARCHIVE{i}"
        (run / "result.json").write_text(json.dumps({"seed": seed, "status": "complete",
                                                     "ascension": 10, "a1_clear": True}))
        cmds = [{"cmd": "training_restore", "seed": seed, "ascension": 10, "history": []},
                {"cmd": "action", "action": "select_map_node", "args": {"row": 16}},
                {"cmd": "action", "action": "select_map_node", "args": {"row": 0}}]
        (run / "game/rpc.jsonl").write_text("\n".join(json.dumps({"command": c, "response_digest": digest([seed, n])})
                                                     for n, c in enumerate(cmds)))
    train, split = select_openings([pool], 2, "default", "train", 15)
    lock = tmp_path / "opening-split.json"
    lock.write_text(json.dumps(split))
    test, checked = select_openings([pool], 2, "default", "test", 15, lock)
    assert split == checked and len(train) == len(test) == 15
    assert not {s for s, _ in train} & {s for s, _ in test}
    assert len(split["train"]) + len(split["test"]) == 90
    moved = pool.rename(tmp_path / "copied")
    assert [s for s, _ in select_openings([moved], 2, "default", "test", 15, lock)[0]] == [s for s, _ in test]
    bad = deepcopy(split)
    bad["train"].append(bad["test"][0])
    lock.write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="locked"):
        select_openings([moved], 2, "default", "test", 15, lock)
    with pytest.raises(ValueError, match="fixed split"):
        select_openings([moved], 2, "default", "test", 90)
