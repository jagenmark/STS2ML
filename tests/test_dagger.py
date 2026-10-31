from copy import deepcopy
import json

import pytest

from sts2rl.act1 import run_act1, save_json
from sts2rl.aggregation import aggregate_source
from sts2rl.micro import partition_records
from sts2rl.native import CURRICULUM_SAMPLER, digest, legal_actions
from test_curriculum import curriculum_row, conditioned_state


@pytest.mark.parametrize("execute_teacher", [False, True])
def test_student_states_keep_actor_actions_despite_disagreeing_teacher(tmp_path, monkeypatch, execute_teacher):
    executed = []
    initial = conditioned_state()
    initial["act1_search_support"] = {"supported": True}
    class Game:
        def __init__(self, *args, **kwargs):
            self.closed = False
        def reset(self, seed):
            self.state = deepcopy(initial)
            return self.state
        def fork(self):
            return "fixture"
        def step(self, action):
            executed.append(action.kind)
            self.state = deepcopy(self.state)
            self.state["round"] += 1
            if len(executed) == 3:
                self.state.update(decision="game_over", victory=False)
                self.state["player"]["hp"] = 0
            return self.state
        def close(self):
            self.closed = True
    def student(state):
        return next(a for a in legal_actions(state) if a.kind == "end_turn")
    def teacher(worker, fork, state, **kwargs):
        actions = legal_actions(state)
        return {"chosen_action_id": next(a.id for a in actions if a.kind == "play_card"), "branches": 4,
                "estimates": {a.id: {"mean_return": 160 if a.kind == "play_card" else 120} for a in actions}}
    monkeypatch.setattr("sts2rl.act1.NativeSession", Game)
    monkeypatch.setattr("sts2rl.act1.teach_root", teacher)
    result = run_act1(tmp_path, tmp_path / "runs", 0, prefix="NEW", ascension=7,
                      micro_policy=student, execute_teacher=execute_teacher, query_probability=1)
    assert result["status"] == "complete"
    assert executed == ["play_card" if execute_teacher else "end_turn"] * 3
    assert result["teacher_overrides"] == (3 if execute_teacher else 0)
    assert result["teacher_disagreements"] == result["queried_actor_positive_regret"] == 3
    rows = [json.loads(line) for line in (tmp_path / "runs/run-00000/teacher.jsonl").read_text().splitlines()]
    assert all(r["teacher_executed"] == execute_teacher for r in rows)
    assert all(r["executed_action_id"] == r["chosen_action_id" if execute_teacher else "actor_action_id"] for r in rows)


def test_aggregate_split_never_moves_prior_validation_or_test_into_training():
    old = [curriculum_row(i) for i in range(20)]
    _, original = partition_records(old)
    new = [curriculum_row(i) for i in range(20, 40)]
    parts, combined = partition_records(old + new, inherited_split=original)
    assert all(combined[g] == split for g, split in original.items())
    assert {k: len(v) for k, v in parts.items()} == {"train": 32, "validation": 4, "test": 4}
    with pytest.raises(ValueError, match="missing groups"):
        partition_records(new, inherited_split=original)


def source_fixture(folder):
    folder.mkdir()
    config = {"runs": 10, "evaluate": 3, "prefix": "SOURCE", "sampler": CURRICULUM_SAMPLER,
              "ascension": 7, "macro_sha256": "macro", "runtime_sha256": {"artifacts/upstreams/sts2-cli/lib/sts2.dll": "game"}}
    save_json(folder / "config.json", config)
    save_json(folder / "status.json", {"stage": "complete"})
    rows = []
    for i in range(10):
        row = curriculum_row(i)
        row["group"] = digest(f"SOURCE{i:06d}")
        rows.append(row)
        run = folder / f"run-{i:05d}"
        run.mkdir()
        save_json(run / "result.json", {"index": i, "status": "complete", "group": row["group"]})
        (run / "teacher.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    _, split = partition_records(rows)
    (folder / "model").mkdir()
    save_json(folder / "model/report.json", {"dataset_sha256": digest(rows), "split": split})
    # If aggregation recursed into evaluation folders this would corrupt it.
    evaluation = folder / "evaluation-teacher/run-00000"
    evaluation.mkdir(parents=True)
    save_json(evaluation / "teacher.jsonl", {"forbidden": True})
    return config, split


def test_aggregation_excludes_evaluation_and_checks_fitted_source_integrity(tmp_path):
    config, split = source_fixture(tmp_path / "old")
    new = {**config, "prefix": "NEW"}
    paths, inherited, manifest = aggregate_source(tmp_path / "old", new)
    assert len(paths) == 10 and inherited == split
    assert manifest["decisions"] == 10
    with pytest.raises(ValueError, match="overlap"):
        aggregate_source(tmp_path / "old", {**new, "prefix": "SOURCEEVAL"})
    with pytest.raises(ValueError, match="ascension"):
        aggregate_source(tmp_path / "old", {**new, "ascension": 10})
    path = paths[0]
    row = json.loads(path.read_text())
    row["observation"]["energy"] += 1
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="differs from its fitted dataset"):
        aggregate_source(tmp_path / "old", new)
