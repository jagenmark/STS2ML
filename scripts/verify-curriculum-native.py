"""Verify real difficulty changes, replay identity and sampler scope locally."""
import argparse
import json
from pathlib import Path

from sts2rl.act1 import MacroPolicy
from sts2rl.native import CURRICULUM_ASCENSIONS, CURRICULUM_SAMPLER, NativeError, NativeSession, digest, legal_actions, runtime_identity
from sts2rl.teacher import heuristic, incoming


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--host-path", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    results = {}
    for ascension in CURRICULUM_ASCENSIONS:
        opts = {"ascension": ascension, "host_path": args.host_path}
        with NativeSession(root, output / f"a{ascension}-game", **opts) as game, NativeSession(root, output / f"a{ascension}-fork", **opts) as worker:
            state = game.reset("ASCENSIONQUALIFY001")
            macro = MacroPolicy(22)
            for _ in range(64):
                if state["decision"] == "combat_play":
                    break
                state = game.step(macro(state))
            else:
                raise AssertionError("No natural first combat")
            assert state["runtime_identity"] == runtime_identity(ascension)
            assert any(c["id"] == "CARD.ASCENDERS_BANE" for c in state["player"]["deck"])
            fork = game.fork()
            assert fork.specification["ascension"] == ascension
            traces = []
            for _ in range(2):
                restored = worker.restore(fork)
                assert digest(restored) == digest(state)
                worker.sample(17, profile=CURRICULUM_SAMPLER)
                assert digest(worker.state) == digest(state)
                trace = []
                for _ in range(8):
                    if worker.state.get("in_combat") is False or not legal_actions(worker.state):
                        break
                    trace.append(digest(worker.step(heuristic(worker.state))))
                traces.append(trace)
            assert traces[0] == traces[1]
            # The natural first enemy may telegraph a debuff. Use an explicit
            # attacking fixture to check native HP and damage thresholds.
            game.reset("ASCENSIONSTATS001")
            stats = game._request({"cmd": "enter_room", "type": "monster", "encounter": "NIBBITS_WEAK"})
            results[str(ascension)] = {
                "identity": state["runtime_identity"], "replay_and_sampling": True,
                "stat_fixture": "NIBBITS_WEAK",
                "enemies": [{"id": e["id"], "hp": e["max_hp"], "damage": incoming(e)} for e in stats["enemies"]]}
        if ascension != 10:
            with NativeSession(root, output / f"a{ascension}-reject", **opts) as worker:
                worker.restore(fork)
                try:
                    worker.sample(1)
                except NativeError as exc:
                    assert "ascension 10" in str(exc)
                else:
                    raise AssertionError("Legacy A10 sampler accepted lower ascension")
    enemies = [results[str(a)]["enemies"] for a in CURRICULUM_ASCENSIONS]
    assert [e["id"] for e in enemies[0]] == [e["id"] for e in enemies[1]] == [e["id"] for e in enemies[2]]
    assert sum(e["hp"] for e in enemies[1]) > sum(e["hp"] for e in enemies[0]), "A8 durability must actually change"
    assert sum(e["damage"] for e in enemies[2]) > sum(e["damage"] for e in enemies[1]), "A9 attack modifier must actually change"
    report = {"passed": True, "profile": CURRICULUM_SAMPLER, "ascensions": results}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
