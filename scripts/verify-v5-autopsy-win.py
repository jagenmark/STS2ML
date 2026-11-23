"""Re-run the diagnostic victory with and without the sidecar and verify public decisions."""

from contextlib import contextmanager
from dataclasses import asdict
import gzip
import hashlib
import json
import os
from pathlib import Path
import runpy
from tempfile import TemporaryDirectory

from sts2rl.deployed_controller import DeployedController
from sts2rl.native import NativeSession, canonical_json, digest
from sts2rl.run_bundle import load_bundle
from sts2rl.run_evaluation import play_episode
from sts2rl.run_policy import RunWeights


def main():
    collector = runpy.run_path(str(Path(__file__).with_name("collect-v5-autopsy.py")))
    root, work = collector["ROOT"], collector["WORK"]
    role, settings = load_bundle(collector["BUNDLE"])
    wins = []
    for index, seed, mode in collector["panel"]("V5DIAG"):
        original = work / "V5DIAG" / seed
        row = json.loads((original / "result.json").read_bytes())
        if not row["win"]:
            continue
        replay = []
        # Each arm starts a separate native process. The control has no startup hook.
        for instrumented in (False, True):
            with TemporaryDirectory() as temp, gzip.open(original / "trace.gz") as stream:
                rows = iter(map(json.loads, stream))
                current = next(rows, None)

                def check(step, before, action, after, fallback):
                    nonlocal current
                    if current and step == current["step"]:
                        assert action.command() == current["action"]
                        assert all(
                            before[k] == v
                            for k, v in current["before"].items()
                            if k != "combat_state"
                        )
                        assert current["after_player"] == after["player"]
                        current = next(rows, None)

                with collector_env(collector["HOOK"], Path(temp) / "native", instrumented):
                    task = (
                        root,
                        collector["HOST"],
                        Path(temp) / "episode",
                        seed,
                        index,
                        role,
                        asdict(RunWeights.load(settings["weights"])),
                        None,
                        {**settings, "seeded_acts": mode == "seeded", "transition_hook": check},
                    )
                    result = play_episode(task)
                assert current is None and all(
                    result[k] == row[k]
                    for k in ("steps", "status", "win", "act", "floor", "boss_fights")
                )
                rpc = Path(temp) / "episode/game/rpc.jsonl"
                records = [
                    {k: r[k] for k in ("command", "response_digest")}
                    for r in map(json.loads, rpc.read_bytes().splitlines())
                ]
                checksum = hashlib.sha256(canonical_json(records)).hexdigest()
                replay.append(
                    dict(
                        observer=instrumented,
                        rpc_count=len(records),
                        sha256=checksum,
                        terminal_digest=records[-1]["response_digest"],
                    )
                )
                if not instrumented:
                    path = root / "docs/evidence" / f"silent-a10-v5-win-{seed}.jsonl.gz"
                    with gzip.GzipFile(str(path), "wb", mtime=0) as f:
                        for r in records:
                            f.write(canonical_json(r) + b"\n")
        assert replay[0]["sha256"] == replay[1]["sha256"]
        controller = DeployedController.from_bundle(collector["BUNDLE"], macro_seed=7103 + index)
        with (
            TemporaryDirectory() as temp,
            NativeSession(
                root, Path(temp) / "client", act_list=mode, host_path=collector["HOST"]
            ) as game,
        ):
            state = game.reset(seed)
            for command in (r for r in records if r["command"]["cmd"] == "action"):
                action = controller.choose(state, game)
                assert action.command() == command["command"]
                after = game.step(action)
                assert digest(after) == command["response_digest"]
                controller.observe(state, action, after)
                state = after
            assert state["decision"] == "game_over" and state["victory"] is True
        wins.append(
            dict(
                seed=seed,
                boss_fights=row["boss_fights"],
                replay=replay,
                deployed_controller_verified_steps=row["steps"],
            )
        )
    (work / "wins.json").write_bytes(canonical_json(wins))


@contextmanager
def collector_env(hook, receipts, active):
    if os.environ.get("DOTNET_STARTUP_HOOKS"):
        raise ValueError("Expected clean native host environment")
    if active:
        os.environ.update(DOTNET_STARTUP_HOOKS=str(hook), STS2_AUTOPSY_RECEIPTS=str(receipts))
    try:
        yield
    finally:
        if active:
            del os.environ["DOTNET_STARTUP_HOOKS"], os.environ["STS2_AUTOPSY_RECEIPTS"]


if __name__ == "__main__":
    main()
