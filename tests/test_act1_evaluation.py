import json

import pytest

from sts2rl.act1_evaluation import compare_act1, evaluate_three_way


def row(index, *, status="complete", clear=False, floor=4, seconds=1):
    return {"index": index, "group": f"seed-{index}", "status": status,
            "cleared_act1": clear, "max_floor": floor, "seconds": seconds,
            "search_errors": []}


def test_paired_comparison_excludes_errors_in_any_arm_instead_of_counting_losses():
    arms = {"heuristic": [row(0), row(1, status="error", floor=99)],
            "micro": [row(0, floor=5, seconds=2), row(1, clear=True, floor=17)],
            "teacher": [row(0, clear=True, floor=17, seconds=100), row(1)]}
    report = compare_act1(arms)
    assert report["complete_paired_seed_groups"] == 1
    assert report["excluded_pair_indices"] == [1]
    assert report["policies"]["heuristic"]["completed"] == 1
    assert report["policies"]["heuristic"]["mean_max_floor"] == 4
    comparison = report["comparisons"]["heuristic_vs_teacher"]
    assert comparison["right_only_clears"] == 1
    assert comparison["mean_floor_difference_left_minus_right"] == -13
    assert comparison["mean_seconds_difference_left_minus_right"] == -99
    assert report["comparisons"]["heuristic_vs_micro"]["neither_clears"] == 1


def test_evaluation_refuses_different_seeds_duplicate_indices_and_missing_attempts():
    with pytest.raises(ValueError, match="seed groups differ"):
        compare_act1({"a": [row(0)], "b": [{**row(0), "group": "different"}]})
    with pytest.raises(ValueError, match="duplicate"):
        compare_act1({"a": [row(0), row(0)], "b": [row(0)]})
    with pytest.raises(ValueError, match="same evaluation seeds"):
        compare_act1({"a": [row(0), row(1)], "b": [row(0)]})


def test_three_way_protocol_pairs_seeds_budgets_macro_and_reuses_only_matching_results(tmp_path, monkeypatch):
    calls = []
    def student(state):
        return state  # Never invoked by the fake native runner.

    def fake_run(root, folder, index, **kwargs):
        calls.append((folder.name, index, kwargs))
        (folder / f"run-{index:05d}").mkdir(parents=True)
        return row(index, clear=kwargs["teacher"], seconds=5 if kwargs["teacher"] else 1)

    monkeypatch.setattr("sts2rl.act1_evaluation.run_act1", fake_run)
    args = dict(episodes=2, prefix="FRESH_EVAL", macro_checkpoint="fixed-macro.pt",
                micro_policy=student, samples=4, roots_per_fight=12, query_probability=.5,
                workers=2, protocol={"micro_sha256": "first"})
    report = evaluate_three_way(tmp_path, tmp_path / "evaluation", **args)
    assert len(calls) == 6
    assert report["complete_paired_seed_groups"] == 2
    for name, index, kwargs in calls:
        assert kwargs["prefix"] == "FRESH_EVAL"
        assert kwargs["macro_checkpoint"] == "fixed-macro.pt"
        assert (kwargs["samples"], kwargs["roots_per_fight"], kwargs["query_probability"]) == (4, 12, .5)
        assert kwargs["teacher"] == (name == "evaluation-teacher")
        assert (kwargs["micro_policy"] is student) == (name == "evaluation-micro")
        assert kwargs["stop_file"] == tmp_path / "evaluation/STOP"
    saved = json.loads((tmp_path / "evaluation/policy-comparison.json").read_text())
    assert saved == report
    assert evaluate_three_way(tmp_path, tmp_path / "evaluation", **args) == report
    assert len(calls) == 6
    args["protocol"] = {"micro_sha256": "changed-model"}
    evaluate_three_way(tmp_path, tmp_path / "evaluation", **args)
    assert len(calls) == 12
    assert len(list((tmp_path / "evaluation").glob("incomplete-evaluation-*"))) == 3


def test_one_errored_policy_does_not_prevent_other_policies_being_measured(tmp_path, monkeypatch):
    def fake_run(root, folder, index, **kwargs):
        return row(index, status="error" if folder.name == "evaluation-heuristic" else "complete")

    monkeypatch.setattr("sts2rl.act1_evaluation.run_act1", fake_run)
    report = evaluate_three_way(tmp_path, tmp_path, episodes=1, prefix="NEW", macro_checkpoint=None,
        micro_policy=lambda _: None, samples=4, roots_per_fight=12, query_probability=.5, workers=1, protocol={})
    assert set(report["policies"]) == {"heuristic", "micro", "teacher"}
    assert report["complete_paired_seed_groups"] == 0
    assert report["comparisons"]["micro_vs_teacher"]["mean_floor_difference_left_minus_right"] is None


def test_previous_student_is_evaluated_on_same_new_seeds_without_teacher_assistance(tmp_path, monkeypatch):
    old, new = object(), object()
    calls = []
    def fake_run(root, folder, index, **kwargs):
        calls.append((folder.name, index, kwargs))
        return row(index)
    monkeypatch.setattr("sts2rl.act1_evaluation.run_act1", fake_run)
    report = evaluate_three_way(tmp_path, tmp_path, episodes=2, prefix="NEW", macro_checkpoint=None,
        micro_policy=new, previous_policy=old, samples=4, roots_per_fight=12,
        query_probability=.5, workers=1, protocol={"previous_micro_sha256": "frozen"})
    assert len(calls) == 8
    assert report["comparisons"]["previous_micro_vs_micro"]["paired_runs"] == 2
    for name, index, args in calls:
        if name == "evaluation-previous_micro":
            assert args["micro_policy"] is old and not args["teacher"]
        assert args["prefix"] == "NEW"
