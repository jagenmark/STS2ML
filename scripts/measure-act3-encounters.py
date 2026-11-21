"""Measure a frozen, Act-3-only policy using natural lobbies and independent native replays."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import gzip
import hashlib
import json
from math import comb
from pathlib import Path
from tempfile import TemporaryDirectory

from sts2rl.act1 import save_json
from sts2rl.mecha_knight import phase
from sts2rl.native import NativeError, NativeSession, ReplayFork, digest, legal_actions
from sts2rl.run_evaluation import act_start, verified_victory
from sts2rl.trajectory import natural_specification

ROOT = Path(__file__).resolve().parents[1]


def physical(folder, ascension=10):
    with (folder / "game/rpc.jsonl").open(encoding="utf-8") as f:
        first = json.loads(next(f))
        spec = natural_specification(first["command"], ascension)
        cmds, digests = [], [first["response_digest"]]
        for line in f:
            r = json.loads(line)
            if r["command"]["cmd"] == "get_map":
                continue
            if r["command"]["cmd"] != "action":
                raise ValueError("Invalid command in a natural lobby")
            cmds.append(r["command"])
            digests.append(r["response_digest"])
    return spec, cmds, digests


def read_index(cohort):
    with gzip.open(cohort / "games.jsonl.gz", "rt") as f:
        return [json.loads(line) for line in f]


def prepare(a):
    games = read_index(a.cohort)
    entrants = json.loads((a.cohort / "entries.json").read_bytes())
    salt = b"act3-native-prefix-audit-v1"
    other = sorted(
        (r for r in games if not r["a2_clear"]),
        key=lambda r: hashlib.sha256(salt + r["seed"].encode()).digest(),
    )
    rows = list(entrants)
    rows.extend(
        {k: r[k] for k in ("seed", "index", "act_list")} | {"map_digest": None}
        for r in other[: a.spots]
    )
    save_json(a.output, sorted(rows, key=lambda e: e["index"]))


def metrics(result):
    boss = sorted({floor for act, floor in result["boss_fights"] if act == 3})
    chambers = [r for r in result.get("rooms", []) if r["act"] == 3]
    room_stats = {
        name: {
            "entered": sum(r["icon"] == name for r in chambers),
            "died": sum(r["icon"] == name and r["died"] for r in chambers),
        }
        for name in ("Monster", "Elite", "Unknown")
    }
    if result["win"] and not verified_victory(result["boss_fights"]):
        raise ValueError("Full victory lacks the native double boss")
    return {
        "first": bool(boss),
        "second": len(boss) >= 2,
        "win": bool(result["win"]),
        "floor": result["floor"] if result["a2_clear"] else 0,
        "rooms": room_stats,
    }


def mecha_fights(game, state, commands, hashes):
    """Follow the registered physical path from Act 3 and record actual elite encounters."""
    fights = []
    active = None
    windup = 0
    for i in range(len(commands) + 1):
        ctx = state.get("context") or {}
        enemies = [e for e in state.get("enemies") or [] if e["hp"] > 0]
        knight = (
            state.get("decision") == "combat_play"
            and ctx.get("act") == 3
            and ctx.get("room_type") == "Elite"
            and len(enemies) == 1
            and enemies[0]["id"] == "MONSTER.MECHA_KNIGHT"
        )
        if active and (
            state["decision"] == "game_over"
            or (
                not state.get("in_combat")
                and state["decision"] not in ("card_select", "choose_cards", "choose_card")
            )
        ):
            active["won"] = state["decision"] != "game_over" or state["victory"]
            active["hp_out"] = state["player"]["hp"] if active["won"] else 0
            active["end"] = hashes[i]
            active = None
        if knight:
            if active is None:
                active = {
                    "floor": ctx["floor"],
                    "opening": hashes[i],
                    "hp_in": state["player"]["hp"],
                    "windup_seen": False,
                    "cleave_seen": False,
                    "decisions": [],
                }
                fights.append(active)
                windup = 0
            stage = phase(state, windup)
            if stage == "windup":
                windup = state["round"]
            if stage:
                action = commands[i]
                kind = action["action"]
                item = kind
                if kind in ("play_card", "use_potion"):
                    field, items = (
                        ("card_index", state["hand"])
                        if kind == "play_card"
                        else ("potion_index", state["player"]["potions"])
                    )
                    item = next(it["id"] for it in items if it["index"] == action["args"][field])
                active[stage + "_seen"] = True
                active["decisions"].append(
                    {
                        "round": state["round"],
                        "phase": stage,
                        "item": item,
                        "hp": state["player"]["hp"],
                        "block": state["player"]["block"],
                        "foe_hp": enemies[0]["hp"],
                        "root": hashes[i],
                    }
                )
        if i < len(commands):
            state = game._request(commands[i])
            if digest(state) != hashes[i + 1]:
                raise ValueError("Independent Act 3 action stream diverged")
    if active or state["decision"] != "game_over":
        raise ValueError("Encounter audit did not reach the natural terminal")
    return fights


def check(task):
    base_folder, other_folder, host, entry, scope = task
    seed = entry["seed"]
    results = [json.loads((f / "result.json").read_bytes()) for f in (base_folder, other_folder)]
    if any(
        r["status"] != "complete"
        or r["seed"] != seed
        or r["index"] != entry["index"]
        or r["start_act"] != 1
        for r in results
    ):
        raise ValueError(f"Invalid paired game on {seed}")
    aa, bb = physical(base_folder), physical(other_folder)
    if aa[0] != bb[0] or aa[0].get("act_list") != "seeded":
        raise ValueError("Different natural lobbies")
    if entry["map_digest"] is not None:
        maps = [act_start(f / "game/rpc.jsonl", 3) for f in (base_folder, other_folder)]
        if maps[0] != maps[1] or maps[0].expected_digest != entry["map_digest"]:
            raise ValueError(f"Act 3 physical prefixes disagree on {seed}")
    elif any(r["a2_clear"] for r in results) or aa[1] != bb[1] or aa[2][-1] != bb[2][-1]:
        raise ValueError(f"Act 3 policy changed an earlier run on {seed}")
    pos = next((i for i, (a, b) in enumerate(zip(aa[1], bb[1])) if a != b), None)
    if pos is None and len(aa[1]) != len(bb[1]):
        raise ValueError("Partial physical history")
    with TemporaryDirectory() as tmp:
        serial = 0
        game = None

        def restore(spec, history, expected):
            nonlocal game, serial

            def fresh():
                nonlocal serial
                serial += 1
                return NativeSession(
                    ROOT,
                    Path(tmp) / str(serial),
                    host_path=host,
                    act_list=spec.get("act_list", "default"),
                    timeout=100,
                )

            if game is None or game.closed:
                game = fresh()
            fork = ReplayFork(spec, tuple(history), expected)
            try:
                return game.restore(fork)
            except NativeError:
                game.close()
                game = fresh()
                st = game.reset(spec["seed"])
                for cmd in history:
                    st = game._request(cmd)
                if digest(st) != expected:
                    raise ValueError(f"Independent replay diverged on {seed}")
                return st

        try:
            changed = None
            if pos is not None:
                if aa[2][pos] != bb[2][pos]:
                    raise ValueError("Different public observation before first change")
                st = restore(aa[0], aa[1][:pos], aa[2][pos])
                ctx = st.get("context", {})
                combat = ctx.get("room_type") in ("Monster", "Elite") and st.get("in_combat")
                routed = scope == "route" and st.get("decision") == "map_select"
                if ctx.get("act") != 3 or not (combat or routed):
                    raise ValueError(
                        f"First policy change outside its scope on {seed}: {ctx} {st.get('decision')}"
                    )
                if st["decision"] in ("combat_play", "map_select"):
                    actions = [a.command() for a in legal_actions(st)]
                    if aa[1][pos] not in actions or bb[1][pos] not in actions:
                        raise ValueError("Changed action absent from public action set")
                stage = None
                if scope == "mecha":
                    stage = phase(st)
                    if stage is None and st.get("round", 0) > 1:
                        for k in range(pos - 1, -1, -1):
                            previous = restore(aa[0], aa[1][:k], aa[2][k])
                            if previous.get("decision") != "combat_play":
                                continue
                            if previous["context"] != ctx:
                                break
                            if previous["round"] < st["round"]:
                                if phase(previous) == "windup":
                                    stage = phase(st, previous["round"])
                                break
                    if not stage:
                        raise ValueError(f"First difference outside Mecha Windup/Cleave on {seed}")
                changed = {
                    "mecha_phase": stage,
                    "step": pos,
                    "decision": st["decision"],
                    "room": ctx.get("room_type"),
                    "floor": ctx.get("floor"),
                    "root": aa[2][pos],
                    "incumbent": aa[1][pos],
                    "challenger": bb[1][pos],
                }
            done = {}
            observed = []
            receipts = []
            for (spec, commands, hashes), r in zip((aa, bb), results, strict=True):
                key = digest([spec, commands, hashes[-1]])
                if key not in done:
                    st = restore(spec, commands, hashes[-1])
                    if st["decision"] != "game_over" or st["victory"] is not r["win"]:
                        raise ValueError("Unconfirmed native terminal")
                    fights = []
                    if scope == "mecha" and entry["map_digest"]:
                        offset = hashes.index(entry["map_digest"])
                        state = restore(spec, commands[:offset], hashes[offset])
                        try:
                            fights = mecha_fights(game, state, commands[offset:], hashes[offset:])
                        except (NativeError, ValueError):
                            # Reconstruct hidden state through the original lobby if a compact
                            # restore reproduces the entry digest but a later action diverges.
                            if game and not game.closed:
                                game.close()
                            game = None
                            state = restore(spec, [], hashes[0])
                            for cmd in commands[:offset]:
                                state = game._request(cmd)
                            if digest(state) != hashes[offset]:
                                raise ValueError(f"Independent full lobby diverged on {seed}")
                            fights = mecha_fights(game, state, commands[offset:], hashes[offset:])
                    done[key] = fights
                observed.append(done[key])
                receipts.append({"history": key, "terminal": hashes[-1], "actions": len(commands)})
        finally:
            if game is not None:
                game.close()
    return {
        "seed": seed,
        "index": entry["index"],
        "origin_map": entry["map_digest"],
        "first_difference": changed,
        "terminal_replays": receipts,
        "mecha_fights": dict(zip(("incumbent", "challenger"), observed, strict=True)),
        "incumbent": metrics(results[0]),
        "challenger": metrics(results[1]),
    }


def summarize(games, pairs):
    output = {
        "lobbies": len(games),
        "act2_entries": sum(r["a1_clear"] for r in games),
        "act3_entries": sum(r["a2_clear"] for r in games),
    }
    entrants = [r for r in pairs if r["origin_map"] is not None]
    assert len(entrants) == output["act3_entries"]
    for arm in ("incumbent", "challenger"):
        totals = dict.fromkeys(("first", "second", "win", "floor"), 0)
        totals.update(
            {
                f"{icon}_{metric}": 0
                for icon in ("Monster", "Elite", "Unknown")
                for metric in ("entered", "died")
            }
        )
        for r in entrants:
            v = r[arm]
            for key in ("first", "second", "win", "floor"):
                totals[key] += int(v[key])
            for icon, counts in v["rooms"].items():
                for key, n in counts.items():
                    totals[f"{icon}_{key}"] += n
        fights = [f for r in entrants for f in r.get("mecha_fights", {}).get(arm, [])]
        if fights:
            totals.update(
                mecha_fights=len(fights),
                mecha_seeds=sum(bool(r["mecha_fights"][arm]) for r in entrants),
                mecha_survived=sum(f["won"] for f in fights),
                mecha_windup=sum(f["windup_seen"] for f in fights),
                mecha_cleave=sum(f["cleave_seen"] for f in fights),
            )
        output[arm] = dict(totals)
    won = [r["seed"] for r in entrants if r["challenger"]["first"] and not r["incumbent"]["first"]]
    lost = [r["seed"] for r in entrants if r["incumbent"]["first"] and not r["challenger"]["first"]]
    n = len(won) + len(lost)
    output.update(
        boss_gained=won,
        boss_lost=lost,
        paired_p=min(1, 2 * sum(comb(n, k) for k in range(min(len(won), len(lost)) + 1)) / 2**n),
    )
    return output


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="mode", required=True)
    maker = sub.add_parser("prepare")
    maker.add_argument("--spots", type=int, default=64)
    report = sub.add_parser("report")
    for arg in ("entries", "baseline", "challenger", "host"):
        report.add_argument("--" + arg, type=Path, required=True)
    report.add_argument("--scope", choices=("combat", "route", "mecha"), required=True)
    report.add_argument("--workers", type=int, default=3)
    for parser in (maker, report):
        parser.add_argument("--cohort", type=Path, required=True)
        parser.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.mode == "prepare":
        prepare(a)
        return
    games = read_index(a.cohort)
    entries = json.loads(a.entries.read_bytes())
    expected = {r["seed"] for r in games if r["a2_clear"]}
    if {r["seed"] for r in entries if r["map_digest"]} != expected or len(entries) != len(
        {r["seed"] for r in entries}
    ):
        raise ValueError("Paired lobbies must cover all Act 3 entrants")
    a.output.mkdir(parents=True, exist_ok=False)
    jobs = [
        (
            a.baseline / f"run-{r['index']:04d}",
            a.challenger / r["seed"],
            a.host.resolve(),
            r,
            a.scope,
        )
        for r in entries
    ]
    with ProcessPoolExecutor(a.workers) as pool:
        pairs = list(pool.map(check, jobs))
    halves = {}
    for label, lo, hi in (("first", 0, len(games) // 2), ("second", len(games) // 2, len(games))):
        halves[label] = summarize(
            [r for r in games if lo <= r["index"] < hi], [r for r in pairs if lo <= r["index"] < hi]
        )
    summary = {
        "scope": a.scope,
        "full": summarize(games, pairs),
        "halves": halves,
        "full_paired_lobbies": len(pairs),
        "nonentrant_spot_checks": len(pairs) - len(expected),
        "shared_pre_act3_histories": len(games) - len(expected),
        "independent_host_sha256": hashlib.sha256(a.host.read_bytes()).hexdigest(),
    }
    save_json(a.output / "pairs.json", pairs)
    save_json(a.output / "summary.json", summary)
    print(json.dumps(summary["full"]))


if __name__ == "__main__":
    main()
