"""Ensure advisory MC labels cannot alter the frozen student's actual trajectory."""
import argparse
import json
from pathlib import Path

from sts2rl.act1 import run_act1, save_json
from sts2rl.micro import load_micro


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--student-checkpoint", type=Path, required=True)
    p.add_argument("--macro-checkpoint", type=Path, required=True)
    p.add_argument("--host-path", type=Path, required=True)
    args = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    policy = load_micro(args.student_checkpoint, device="cpu")
    common = dict(prefix="DAGGERQUALIFY001", ascension=7, host_path=args.host_path,
                  macro_checkpoint=args.macro_checkpoint, micro_policy=policy,
                  samples=2, roots_per_fight=1, query_probability=0)
    plain = run_act1(root, output / "plain", 0, teacher=False, **common)
    labeled = run_act1(root, output / "labeled", 0, execute_teacher=False, **common)
    for result in (plain, labeled):
        assert result["status"] == "complete", result
        assert not result["search_errors"], result
    def trajectory(name):
        return [{k: r[k] for k in ("command", "response_digest")} for r in
                map(json.loads, (output / name / "run-00000/game/rpc.jsonl").read_text(encoding="utf-8").splitlines())]
    assert trajectory("plain") == trajectory("labeled"), "Advisory teacher changed the student's native trajectory"
    rows = [json.loads(line) for line in (output / "labeled/run-00000/teacher.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows and all(not r["teacher_executed"] and r["actor_action_id"] == r["executed_action_id"] for r in rows)
    assert labeled["teacher_overrides"] == 0
    report = {"passed": True, "identical_native_commands_and_observations": True,
              "teacher_labels": len(rows), "teacher_action_disagreements": labeled["teacher_disagreements"],
              "teacher_overrides": 0, "purpose": "Integration qualification only; these rows never enter training/evaluation"}
    save_json(output / "report.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
