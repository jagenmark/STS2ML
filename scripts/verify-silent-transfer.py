"""Independently replay a registered natural Silent benchmark at its actual ascension."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import gzip
import hashlib
import json
from pathlib import Path
import runpy
from tempfile import TemporaryDirectory

from sts2rl.act1 import save_json
from sts2rl.native import NativeError, NativeSession, ReplayFork, digest
from sts2rl.run_bundle import load_bundle
from sts2rl.run_evaluation import play_episode, verified_victory
from sts2rl.run_policy import RunWeights

ROOT = Path(__file__).resolve().parents[1]
physical = runpy.run_path(str(ROOT / "scripts/measure-act3-encounters.py"))["physical"]


def confirm(task):
    folder, index, seed, ascension, host, bundle = task
    row = json.loads((folder / "result.json").read_bytes())
    if (row["seed"], row["index"], row["ascension"], row["status"], row["start_act"]) != (
        seed,
        index,
        ascension,
        "complete",
        1,
    ):
        raise ValueError(f"Invalid benchmark result for {seed}")
    spec, commands, hashes = physical(folder, ascension)
    if spec != {"seed": seed, "ascension": ascension, "act_list": "seeded"}:
        raise ValueError(f"Wrong lobby for {seed}")
    with TemporaryDirectory() as tmp:
        for stream in (False, True):
            try:
                with NativeSession(
                    ROOT,
                    Path(tmp) / str(stream),
                    host_path=host,
                    ascension=ascension,
                    act_list="seeded",
                    timeout=90,
                ) as session:
                    if stream:
                        state = session.reset(seed)
                        if digest(state) != hashes[0]:
                            raise ValueError("Opening digest diverged")
                        for cmd in commands:
                            state = session._request(cmd)
                    else:
                        state = session.restore(ReplayFork(spec, tuple(commands), hashes[-1]))
                    if (
                        digest(state) != hashes[-1]
                        or state["decision"] != "game_over"
                        or state["victory"] is not row["win"]
                    ):
                        raise ValueError(f"Native terminal diverged on {seed}")
                    break
            except NativeError:
                if stream:
                    raise
    intermediate_differences = []
    if row["win"]:
        if not verified_victory(row["boss_fights"], ascension):
            raise ValueError(f"Missing final boss for {seed}")
        with TemporaryDirectory() as tmp:
            role, opts = load_bundle(bundle)
            folder = Path(tmp) / seed
            played = play_episode(
                (
                    ROOT,
                    host,
                    folder,
                    seed,
                    index,
                    role,
                    asdict(RunWeights.load(opts["weights"])),
                    opts.get("micro"),
                    {**opts, "ascension": ascension, "seeded_acts": True, "rooms": True},
                )
            )
            again_spec, again_commands, again_hashes = physical(folder, ascension)
            if (
                played["status"] != "complete"
                or not played["win"]
                or (again_spec, again_commands, again_hashes[0], again_hashes[-1])
                != (spec, commands, hashes[0], hashes[-1])
            ):
                raise ValueError(f"The frozen policy did not reproduce victory on {seed}")
            intermediate_differences = [
                i for i, (a, b) in enumerate(zip(hashes, again_hashes, strict=True)) if a != b
            ]
    metrics = {
        k: row[k]
        for k in (
            "index",
            "seed",
            "ascension",
            "act",
            "floor",
            "a1_clear",
            "a2_clear",
            "boss_fights",
            "last_enemies",
            "win",
        )
    }
    if row["win"]:
        metrics["winning_policy_replay"] = {
            "identical_actions": len(commands),
            "intermediate_digest_differences": intermediate_differences,
        }
    return metrics | {"opening": hashes[0], "terminal": hashes[-1]}, {
        "spec": spec,
        "history": commands,
        "expected_digest": hashes[-1],
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for k in ("source", "seed-lock", "bundle", "host", "output"):
        p.add_argument("--" + k, type=Path, required=True)
    p.add_argument("--workers", type=int, default=3)
    a = p.parse_args()
    reg = json.loads(a.seed_lock.read_bytes())
    seeds, ascension = reg["seeds"]["test"], reg["ascension"]

    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    if reg["policy_sha256"] != sha(a.bundle) or len(set(seeds)) != len(seeds):
        raise ValueError("Registered policy or seed list mismatch")
    run = json.loads((a.source.parent / "config.json").read_bytes())
    if (
        run["seed_lock"],
        run["bundle"],
        run["partition"],
        run["ascension"],
        run["start"],
        run["stop"],
    ) != (sha(a.seed_lock), sha(a.bundle), "test", ascension, 0, len(seeds)):
        raise ValueError("Native run configuration differs from the registered benchmark")
    a.output.mkdir(parents=True, exist_ok=False)
    tasks = [
        (a.source / f"run-{i:04d}", i, seed, ascension, a.host.resolve(), a.bundle)
        for i, seed in enumerate(seeds)
    ]
    rows = []
    with (
        ProcessPoolExecutor(a.workers) as pool,
        gzip.open(a.output / "histories.jsonl.gz", "wt", encoding="utf-8") as out,
    ):
        for row, hist in pool.map(confirm, tasks):
            out.write(json.dumps(hist, separators=(",", ":")) + "\n")
            rows.append(row)
    summary = {
        "ascension": ascension,
        "lobbies": len(rows),
        "native_terminal_replays": len(rows),
        "act2_entries": sum(r["a1_clear"] for r in rows),
        "act3_entries": sum(r["a2_clear"] for r in rows),
        "act3_bosses_reached": sum(any(a == 3 for a, f in r["boss_fights"]) for r in rows),
        "wins": sum(r["win"] for r in rows),
        "win_seeds": [r["seed"] for r in rows if r["win"]],
        "policy_sha256": sha(a.bundle),
        "registry_sha256": sha(a.seed_lock),
        "independent_host_sha256": sha(a.host),
    }
    save_json(a.output / "games.json", rows)
    save_json(a.output / "summary.json", summary)
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
