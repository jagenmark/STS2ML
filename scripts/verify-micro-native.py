"""Opt-in integration qualification using the locally installed pinned game."""
from pathlib import Path
import argparse
import json
import time

from sts2rl.native import NativeSession, NativeError, digest, legal_actions, SAMPLER
from sts2rl.teacher import combat_result, heuristic


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    folder = args.output.resolve()
    with NativeSession(root, folder / "game") as game, NativeSession(root, folder / "branch") as worker:
        state = game.reset("MICROQUALIFY001", encounter="SHRINKER_BEETLE_WEAK", hp=25)
        fork = game.fork()
        before = digest(game.state)
        actions = legal_actions(state)
        for action in actions:
            worker.restore(fork)
            worker.step(next(a for a in legal_actions(worker.state) if a.id == action.id))
        traces = []
        for sample in (17, 17, 91):
            worker.restore(fork)
            if len(traces) == 1:
                # Deliberately alter hidden order, then use the same chance sample.
                worker._request({"cmd": "set_draw_order", "cards": [
                    c["id"].split(".", 1)[1] for c in reversed(state["draw_pile"])]})
            worker.sample(sample)
            trace = []
            for _ in range(256):
                trace.append(digest(worker.state))
                if combat_result(worker.state) is not None:
                    break
                worker.step(heuristic(worker.state))
            else:
                raise AssertionError("Sampled trajectory truncated")
            traces.append(digest(trace))
        assert traces[0] == traces[1], "Teacher depends on actual hidden draw permutation"
        assert traces[0] != traces[2], "Different chance samples did not vary trajectories"
        assert digest(game.state) == before, "Sibling search mutated the real episode"
        # A genuine non-root replay fork, including a pending Survivor discard.
        survivor = next(a for a in actions if a.kind == "play_card" and
            next(c for c in state["hand"] if c["index"] == a.args["card_index"])["id"] == "CARD.SURVIVOR")
        game.step(survivor)
        assert game.state["decision"] == "card_select"
        pending = game.fork()
        worker.restore(pending)
        worker.sample(4)
        worker.step(heuristic(worker.state))
        # Alternating seeds and completed action histories must reset cleanly.
        started = time.perf_counter()
        for i in range(50):
            worker.restore(pending if i % 2 else fork)
            worker.step(heuristic(worker.state))
        restore_seconds = time.perf_counter() - started
        stale = legal_actions(game.state)[0]
        game.step(stale)
        try:
            game.step(stale)
            raise AssertionError("Stale action accepted")
        except NativeError as exc:
            assert "Stale" in str(exc)
        # Test-only fixture: AnyPlayer must resolve to this solo player and the
        # native effect must actually happen before consumption is accepted.
        fixture = game._request({"cmd": "set_player", "potions": ["BLOCK_POTION"]})
        game.state["player"] = fixture["player"]
        block = game.state["player"]["block"]
        potion = next(a for a in legal_actions(game.state) if a.kind == "use_potion")
        game.step(potion)
        assert game.state["player"]["block"] == block + 12
        assert not game.state["player"]["potions"]
        worker._request({"cmd": "set_player", "potions": ["BLOCK_POTION"]})
        try:
            worker._request({"cmd": "training_sample", "sample_seed": 10})
            raise AssertionError("Unqualified potion root admitted to teacher")
        except NativeError as exc:
            assert "outside qualified" in str(exc)
    report = {"passed": True, "sampler": SAMPLER, "root_actions_executed": len(actions),
              "hidden_order_invariance": True, "chance_variation": True,
              "sibling_isolation": True, "pending_selection_replay": True,
              "repeated_restores": 50, "restore_and_step_seconds": restore_seconds,
              "stale_action_rejected": True, "any_player_potion_effect_verified": True,
              "unqualified_teacher_root_rejected": True, "trace_hashes": traces}
    (folder / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
