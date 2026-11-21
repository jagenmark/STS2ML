"""Replay each distinct physical history from two natural Silent A10 evaluation arms."""

import argparse
import hashlib
import json
import tempfile
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path

from sts2rl.act1 import save_json
from sts2rl.native import NativeSession, ReplayFork, digest
from sts2rl.run_evaluation import verified_victory
from sts2rl.trajectory import natural_specification

ROOT = Path(__file__).resolve().parents[1]
session = None
temporary = None
serial = 0


def history(folder):
    result = json.loads((folder / "result.json").read_bytes())
    if (
        result["status"] != "complete"
        or result["ascension"] != 10
        or result["start_act"] != 1
        or (result["win"] and not verified_victory(result["boss_fights"]))
    ):
        raise ValueError("Unfinished or nonstandard natural run")
    with (folder / "game/rpc.jsonl").open() as stream:
        first = json.loads(next(stream))
        specification = natural_specification(first["command"])
        if specification["seed"] != result["seed"] or specification.get("act_list") != "seeded":
            raise ValueError("Unexpected natural starting state")
        commands, terminal = [], first["response_digest"]
        for line in stream:
            row = json.loads(line)
            cmd = row["command"]
            if cmd["cmd"] == "get_map":
                continue
            if cmd["cmd"] != "action":
                raise ValueError("Unexpected simulation control in a live run")
            commands.append(cmd)
            terminal = row["response_digest"]
    return result, specification, commands, terminal


def verify(task):
    global session, temporary, serial
    host, folder = task
    result, spec, commands, terminal = history(folder)
    errors = []
    for mode in ("bulk", "bulk-retry", "per-command"):
        try:
            if session is None:
                if temporary is None:
                    temporary = tempfile.TemporaryDirectory()
                session = NativeSession(
                    ROOT,
                    Path(temporary.name) / str(serial),
                    host_path=host,
                    act_list="seeded",
                    timeout=90,
                )
                serial += 1
            if mode == "per-command":
                with (folder / "game/rpc.jsonl").open() as stream:
                    for line in stream:
                        row = json.loads(line)
                        state = session._request(row["command"])
                        if digest(state) != row["response_digest"]:
                            raise ValueError("Divergent intermediate observation")
            else:
                state = session.restore(ReplayFork(spec, tuple(commands), terminal))
            if (
                state["decision"] != "game_over"
                or state["victory"] != result["win"]
                or digest(state) != terminal
            ):
                raise ValueError("Divergent terminal result")
            return {"verified": True, "proof": mode, "terminal": terminal, "actions": len(commands)}
        except (RuntimeError, ValueError, TimeoutError) as exc:
            errors.append(str(exc))
            if session:
                session.close()
            session = None
    return {"verified": False, "errors": errors, "terminal": terminal, "actions": len(commands)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("baseline", "challenger", "host", "seed-lock", "output"):
        p.add_argument("--" + key, required=True, type=Path)
    p.add_argument("--workers", type=int, default=3)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    expected = json.loads(a.seed_lock.read_bytes())["seeds"]["test"]
    sources = {"baseline": a.baseline, "challenger": a.challenger}
    keys = {name: {} for name in sources}
    observed = set()
    origins, pending, proofs = {}, {}, {}
    next_scan = 0
    with ProcessPoolExecutor(a.workers) as pool:
        while True:
            if time.monotonic() >= next_scan:
                for arm, source in sources.items():
                    for file in sorted((source / "candidate").glob("run-*/result.json")):
                        if file in observed:
                            continue
                        row, spec, commands, end = history(file.parent)
                        seed = row["seed"]
                        if expected[row["index"]] != seed or seed in keys[arm]:
                            raise ValueError("Unexpected original index or repeated seed")
                        key = digest([spec, commands, end, row["win"]])
                        keys[arm][seed] = key
                        observed.add(file)
                        if key not in origins:
                            origins[key] = arm
                            pending[pool.submit(verify, (a.host.resolve(), file.parent))] = key
                save_json(
                    a.output / "progress.json",
                    {"episodes": len(observed), "unique": len(origins), "checked": len(proofs)},
                )
                next_scan = time.monotonic() + 5
            if pending:
                done, _ = wait(pending, timeout=1, return_when=FIRST_COMPLETED)
                for f in done:
                    proofs[pending.pop(f)] = f.result()
            elif all(set(keys[n]) == set(expected) for n in sources):
                break
            else:
                time.sleep(1)
    for arm in sources:
        rows = [
            {
                "seed": s,
                "arm": arm,
                "physical_history_sha256": k,
                "direct_source_arm": origins[k],
                **proofs[k],
            }
            for s, k in sorted(keys[arm].items())
        ]
        save_json(a.output / (arm + ".json"), rows)
    save_json(
        a.output / "summary.json",
        {
            "episodes": len(observed),
            "unique": len(proofs),
            "verified_unique": sum(r["verified"] for r in proofs.values()),
            "host_sha256": hashlib.sha256(a.host.read_bytes()).hexdigest(),
        },
    )


if __name__ == "__main__":
    main()
