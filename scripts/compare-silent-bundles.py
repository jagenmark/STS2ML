"""Compare two frozen Silent A10 bundles on paired natural starts and replay the terminal outcomes."""

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import hashlib
import json
from math import comb
from pathlib import Path

from sts2rl.act1 import save_json
from sts2rl.native import NativeSession, ReplayFork, digest
from sts2rl.run_bundle import load_bundle
from sts2rl.run_evaluation import play_episode, verified_victory
from sts2rl.run_policy import RunWeights
from sts2rl.trajectory import natural_specification

ROOT = Path(__file__).resolve().parents[1]
MEASURES = ("win", "a2_clear", "a1_clear")
ARMS = ("incumbent", "challenger")


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_result(folder):
    return json.loads((folder / "result.json").read_text(encoding="utf-8"))


def attest(shard):
    """Replay logged physical actions in new native sandboxes with no policy in the loop."""
    host, out, profile, index, folders = shard
    game, rows = None, []
    try:
        for folder in folders:
            result = read_result(folder)
            entry = {"seed": result["seed"], "arm": folder.parent.name, "profile": profile}
            try:
                with (folder / "game/rpc.jsonl").open(encoding="utf-8") as f:
                    first = json.loads(next(f))
                    spec = natural_specification(first["command"])
                    commands = []
                    expected = first["response_digest"]
                    for line in f:
                        record = json.loads(line)
                        if record["command"]["cmd"] == "get_map":
                            continue
                        if record["command"]["cmd"] != "action":
                            raise ValueError("Control command in a full-game trace")
                        commands.append(record["command"])
                        expected = record["response_digest"]
                if spec["seed"] != entry["seed"] or spec.get("act_list", "default") != profile:
                    raise ValueError("Replay identity mismatch")
                if game is None:
                    game = NativeSession(
                        ROOT,
                        out / f"{profile}-{index}-{len(rows)}",
                        host_path=host,
                        timeout=60,
                        act_list=profile,
                    )
                terminal = game.restore(ReplayFork(spec, tuple(commands), expected))
                if terminal["decision"] != "game_over" or terminal["victory"] is not result["win"]:
                    raise ValueError("Native terminal outcome mismatch")
                if result["win"] and not verified_victory(result["boss_fights"]):
                    raise ValueError("Winner lacks two distinct Act 3 boss floors")
                entry.update(verified=True, actions=len(commands), terminal=digest(terminal))
            except Exception as exc:
                entry.update(verified=False, error=f"{type(exc).__name__}: {exc}")
                if game is not None:
                    game.close()
                    game = None
            rows.append(entry)
    finally:
        if game is not None:
            game.close()
    return rows


def compare(profile_rows, verified):
    by_seed = {arm: {r["seed"]: r for r in rows} for arm, rows in profile_rows.items()}
    matched = sorted(
        set.intersection(
            *[
                {s for s, r in rows.items() if r["status"] == "complete" and (arm, s) in verified}
                for arm, rows in by_seed.items()
            ]
        )
    )
    result = {"paired_verified": len(matched), "arms": {}, "discordance": {}, "paired_exact_p": {}}
    for arm, rows in by_seed.items():
        eligible = [
            r for s, r in rows.items() if r["status"] == "complete" and (arm, s) in verified
        ]
        result["arms"][arm] = {
            "attempted": len(rows),
            "completed": sum(r["status"] == "complete" for r in rows.values()),
            "replayed": len(eligible),
            "unresolved": [s for s in rows if (arm, s) not in verified],
            "all_verified": {m: sum(r[m] for r in eligible) for m in MEASURES},
            "paired": {m: sum(rows[s][m] for s in matched) for m in MEASURES},
            "paired_act1_boss_entries": sum(
                any(a == 1 for a, _ in rows[s]["boss_fights"]) for s in matched
            ),
            "paired_act2_boss_entries": sum(
                any(a == 2 for a, _ in rows[s]["boss_fights"]) for s in matched
            ),
            "paired_act3_boss_entries": sum(
                any(a == 3 for a, _ in rows[s]["boss_fights"]) for s in matched
            ),
            "paired_first_acts": dict(Counter(rows[s]["act_names"][0] for s in matched)),
            "winning_seeds": [r["seed"] for r in eligible if r["win"]],
        }
        by_biome = {}
        for seed in matched:
            row = rows[seed]
            biome = row["act_names"][0]
            if biome != by_seed[ARMS[0]][seed]["act_names"][0]:
                raise ValueError("Paired policies did not receive the same opening act")
            counts = by_biome.setdefault(biome, {"pairs": 0, **dict.fromkeys(MEASURES, 0)})
            counts["pairs"] += 1
            for m in MEASURES:
                counts[m] += row[m]
        result["arms"][arm]["paired_by_first_act"] = by_biome
    for field in MEASURES:
        result["discordance"][field] = {
            arm: sum(by_seed[arm][s][field] and not by_seed[other][s][field] for s in matched)
            for arm, other in (ARMS, ARMS[::-1])
        }
        only = result["discordance"][field].values()
        discordant = sum(only)
        result["paired_exact_p"][field] = min(
            1.0, 2 * sum(comb(discordant, k) for k in range(min(only) + 1)) / 2**discordant
        )
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", type=Path, required=True)
    p.add_argument("--incumbent", type=Path, required=True)
    p.add_argument("--challenger", type=Path, required=True)
    p.add_argument(
        "--suite", nargs=3, action="append", required=True, metavar=("ACT_LIST", "PREFIX", "COUNT")
    )
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--workers", type=int, default=6)
    args = p.parse_args()
    suites = [(mode, prefix, int(count)) for mode, prefix, count in args.suite]
    if (
        args.workers < 1
        or any(mode not in ("default", "seeded") or n < 1 for mode, _, n in suites)
        or len({s[0] for s in suites}) != len(suites)
        or len({s[1] for s in suites}) != len(suites)
    ):
        p.error("Specify one unique prefix per act list and positive counts")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    host = args.host.resolve()
    arms, files = {}, {}
    for arm in ARMS:
        path = getattr(args, arm).resolve()
        role, settings = load_bundle(path)
        weights = asdict(RunWeights.load(settings["weights"]))
        arms[arm] = role, weights, settings.pop("micro", None), settings
        files[arm] = {
            "bundle": str(path),
            "sha256": checksum(path),
            "files": json.loads(path.read_text())["files"],
        }
    save_json(
        out / "freeze.json", {"suites": suites, "host_sha256": checksum(host), "policies": files}
    )
    tasks = {}
    for index in range(max(n for _, _, n in suites)):
        for mode, prefix, count in suites:
            if index >= count:
                continue
            for arm in ARMS:
                role, w, micro, settings = arms[arm]
                folder = out / "games" / mode / arm / f"run-{index:04d}"
                tasks[(mode, arm, index)] = (
                    ROOT,
                    host,
                    folder,
                    f"{prefix}{index:04d}",
                    index,
                    role,
                    w,
                    micro,
                    {**settings, "rooms": True, "seeded_acts": mode == "seeded"},
                )
    with ProcessPoolExecutor(args.workers) as pool:
        rows = dict(zip(tasks, pool.map(play_episode, tasks.values()), strict=True))
        folders = {k: v[2] for k, v in tasks.items()}
        retries = {}
        for key, row in rows.items():
            if row["status"] != "complete":
                mode, arm, i = key
                task = list(tasks[key])
                task[2] = out / "retries" / mode / arm / f"run-{i:04d}"
                retries[key] = tuple(task)
        for key, row in zip(retries, pool.map(play_episode, retries.values()), strict=True):
            rows[key] = row
            folders[key] = retries[key][2]
        shards = []
        for mode, _, _ in suites:
            complete = [
                f for k, f in folders.items() if k[0] == mode and rows[k]["status"] == "complete"
            ]
            for i in range(min(len(complete), args.workers)):
                shards.append((host, out / "replay", mode, i, complete[i :: args.workers]))
        receipts = [r for part in pool.map(attest, shards) for r in part]
        # A fresh process distinguishes a transient restore failure from a reproducibility failure.
        failed = {(r["profile"], r["arm"], r["seed"]) for r in receipts if not r["verified"]}
        repeat = [
            (host, out / "replay-retry" / arm, mode, i, [folders[(mode, arm, i)]])
            for (mode, arm, i), r in rows.items()
            if (mode, arm, r["seed"]) in failed
        ]
        if failed:
            save_json(
                out / "first-replay-failures.json", [r for r in receipts if not r["verified"]]
            )
            receipts = [r for r in receipts if r["verified"]]
            receipts.extend(r for part in pool.map(attest, repeat) for r in part)
        winning = {}
        for key, row in rows.items():
            if row["status"] == "complete" and row["win"]:
                mode, arm, i = key
                task = list(tasks[key])
                task[2] = out / "winning-reruns" / mode / arm / f"run-{i:04d}"
                winning[key] = tuple(task)
        independent = []
        for key, rerun in zip(winning, pool.map(play_episode, winning.values()), strict=True):
            old = rows[key]
            confirmed = (
                rerun["status"] == "complete"
                and rerun["win"]
                and rerun["boss_fights"] == old["boss_fights"]
            )
            independent.append(
                {"profile": key[0], "arm": key[1], "seed": old["seed"], "confirmed": confirmed}
            )
            if not confirmed:
                receipt = next(
                    r
                    for r in receipts
                    if (r["profile"], r["arm"], r["seed"]) == (key[0], key[1], old["seed"])
                )
                receipt.update(verified=False, error="Independent full-policy victory failed")
    receipts.sort(key=lambda r: (r["profile"], r["arm"], r["seed"]))
    save_json(out / "terminal-receipts.json", receipts)
    report = {
        "policy_retries": len(retries),
        "first_replay_failures": len(failed),
        "winning_reruns": independent,
        "verified_actions": sum(r.get("actions", 0) for r in receipts if r["verified"]),
        "receipt_sha256": checksum(out / "terminal-receipts.json"),
        "suites": {},
    }
    for mode, _, _ in suites:
        profile_rows = {
            a: [r for (m, arm, _), r in rows.items() if m == mode and arm == a] for a in ARMS
        }
        confirmed = {
            (r["arm"], r["seed"]) for r in receipts if r["profile"] == mode and r["verified"]
        }
        report["suites"][mode] = compare(profile_rows, confirmed)
    save_json(out / "report.json", report)
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
