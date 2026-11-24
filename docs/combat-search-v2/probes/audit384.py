"""Solo Arm 4 stress collector with a locked non-evaluation cohort."""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import ExitStack
from dataclasses import asdict
import gzip
import hashlib
import json
import os
from pathlib import Path
import runpy
from tempfile import TemporaryDirectory
from unittest.mock import patch

from sts2rl.combat_search_v2 import episode_summary, planner
from sts2rl.combat_search_v2.integration import CombatSearchV2
from sts2rl.deployed_controller import DeployedController
from sts2rl.native import NativeError, NativeSession, digest, legal_actions
from sts2rl.run_bundle import load_bundle
from sts2rl.run_evaluation import play_episode
from sts2rl.run_policy import RunWeights

from audit_headroom import analyze, prepare_rules

ROOT = Path(__file__).resolve().parents[3]
LOCK = ROOT / "docs/combat-search-v2/v6-audit384-lock.json"
LOCK_SHA = "69e364e20fc73853d65388367711345cc448a9b1d6a094407882cb928a83bdb2"


def group(act, room):
    return "act2_" + str(room).lower() if act == 2 else f"act{act}"


def write_gz(path, data):
    path.write_bytes(gzip.compress(json.dumps(data, separators=(",", ":")).encode(), mtime=0))


def collect(job):
    out, bundle, triple, telemetry = job
    index, seed, mode = triple
    role, opts = load_bundle(bundle)
    decisions = hashlib.sha256()
    headroom = defaultdict(Counter)
    coverage = defaultdict(Counter)
    encounters = []
    fixtures = []
    commands = []
    entry = {}
    pending = None
    terminal_kinds = None
    last_digest = None
    physical = NativeSession.step
    observer = CombatSearchV2.observe

    class ObservedSearch(planner._Search):
        def run(self, state):
            nonlocal pending, terminal_kinds
            completed = []
            kinds = set()
            make_line = planner.Line

            def record_line(board, path, score, root):
                line = make_line(board, path, score, root)
                if board.outcome == "completed":
                    completed.append(line)
                kinds.add(board.outcome or "unresolved")
                return line

            with patch.object(planner, "Line", record_line):
                result = super().run(state)
            pending = state, result, completed
            terminal_kinds = kinds
            return result

    def step(host, action):
        nonlocal last_digest
        last_digest = action.snapshot
        command = action.command()
        commands.append(command)
        decisions.update(
            json.dumps([last_digest, command], sort_keys=True, separators=(",", ":")).encode()
            + b"\n"
        )
        return physical(host, action)

    def audit(controller, action, after, enumerate_actions):
        context = controller._decision
        observer(controller, action, after, enumerate_actions)
        if (
            context
            and controller.records
            and controller.records[-1].get("oracle", [None, None])[1] == "mismatch"
        ):
            state = context[0].state
            fields = (
                "late",
                "v61_rules",
                "right_hand_return",
                "facing",
                "preview_facing",
                "sloth_plays",
                "aeon_plays",
                "bound_used",
                "tender_plays",
                "remnant_floor",
                "curse_number",
            )
            fixtures.append(
                dict(
                    index=len(commands) - 1,
                    before=last_digest,
                    after=digest(after),
                    witness={k: getattr(state, k) for k in fields},
                    record=controller.records[-1],
                )
            )

    class Summary(episode_summary.EpisodeSummary):
        def observe(self, before, after, fallback):
            nonlocal pending, terminal_kinds
            super().observe(before, after, fallback)
            view = before.get("combat_state", before)
            ctx = view.get("context", {})
            act, room = ctx.get("act"), ctx.get("room_type")
            if act == 3 and "act3" not in entry and "player" in view:
                entry["act3"] = view["player"]["hp"]
            if before.get("in_combat") and "enemies" in view:
                tag = group(act, room)
                key = [act, ctx.get("floor"), room]
                if not encounters or key != encounters[-1]["key"]:
                    deck = view["player"]["deck"]
                    encounters.append(
                        dict(
                            key=key,
                            formation=self.formation,
                            entry_hp=view["player"]["hp"],
                            max_hp=view["player"]["max_hp"],
                            deck=dict(
                                cards=len(deck),
                                powers=sum(c["type"] == "Power" for c in deck),
                                attacks=sum(c["type"] == "Attack" for c in deck),
                                block_cards=sum(
                                    (c.get("stats") or {}).get("block", 0) > 0 for c in deck
                                ),
                                upgraded=sum(bool(c["upgrades"]) for c in deck),
                            ),
                            counts=Counter(),
                            failed_boundaries=Counter(),
                            failed_leaf_kinds=Counter(),
                        )
                    )
                fight = encounters[-1]
                if act == 2 and room == "Boss":
                    entry.setdefault("act2_boss", fight["entry_hp"])
                try:
                    eligible = len(legal_actions(before)) > 1
                except NativeError:
                    eligible = (
                        before["decision"] == "card_select" and len(before.get("cards", ())) > 1
                    )
                if eligible:
                    reason = fallback if fallback is not None else "outside encounter scope"
                    key = reason or "covered"
                    coverage[tag][key] += 1
                    if tag == "act2_boss":
                        coverage[tag + "/" + self.formation][key] += 1
                    fight["counts"][key] += 1
                    if key == "covered" and telemetry:
                        if pending is None:
                            raise ValueError("Missing beam for covered root")
                        headroom[tag].update(analyze(*pending, out / "rules", view))
                    elif pending:
                        result = pending[1]
                        # Count each boundary once per failed physical root.
                        fight["failed_boundaries"].update(
                            reason for reason, _ in result.boundary_counts
                        )
                        if key == "no certified survival":
                            fight["failed_leaf_kinds"][
                                "+".join(sorted(terminal_kinds)) or "none"
                            ] += 1
                if self.death and after["decision"] == "game_over":
                    final_enemies = after.get("combat_state", after).get("enemies")
                    fight.update(
                        fatal=True,
                        enemy_hp=sum(
                            max(e["hp"], 0)
                            for e in (final_enemies if final_enemies else view["enemies"])
                        ),
                        hp_source="terminal" if final_enemies else "last_public",
                        round=view["round"],
                        hp_before=view["player"]["hp"],
                    )
            pending = None
            terminal_kinds = None

    with TemporaryDirectory(dir=out) as tmp, ExitStack() as stack:
        stack.enter_context(patch.object(NativeSession, "step", step))
        stack.enter_context(patch.object(CombatSearchV2, "observe", audit))
        if telemetry:
            stack.enter_context(patch.object(planner, "_Search", ObservedSearch))
            stack.enter_context(patch.object(episode_summary, "EpisodeSummary", Summary))
        folder = Path(tmp) / "run"
        row = play_episode(
            (
                ROOT,
                os.environ["CSV2DEV_HOST"],
                folder,
                seed,
                index,
                role,
                asdict(RunWeights.load(opts["weights"])),
                None,
                {
                    **opts,
                    "seeded_acts": mode == "seeded",
                    "compact_combat_summary": True,
                    "time_combat_decisions": True,
                    "audit_compact": True,
                },
            )
        )
        times = json.loads((folder / "combat-decision-ns.json").read_bytes())
    receipt = {
        k: row.get(k)
        for k in (
            "seed",
            "index",
            "act_list",
            "status",
            "error",
            "abandoned",
            "act",
            "floor",
            "start_act",
            "ascension",
            "boss_fights",
            "a1_clear",
            "a2_clear",
            "win",
            "native",
            "mismatches",
            "steps",
            "death",
            "late_fights",
        )
    }
    receipt.update(
        digest=decisions.hexdigest(),
        headroom=headroom,
        coverage=coverage,
        entry=entry,
        encounters=encounters,
        latency_us=Counter((n + 500) // 1000 for n in times),
    )
    suffix = "" if telemetry else "-plain"
    write_gz(out / f"{seed}{suffix}.json.gz", receipt)
    if fixtures:
        write_gz(
            out / f"fixture-{seed}.json.gz",
            dict(
                seed=seed, mode=mode, steps=fixtures, history=commands[: fixtures[-1]["index"] + 1]
            ),
        )
    return seed, row["status"], row.get("error"), row["native"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, choices=[12], required=True)
    parser.add_argument("--sanity", action="store_true")
    parser.add_argument("--only", nargs="+")
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if hashlib.sha256(LOCK.read_bytes()).hexdigest() != LOCK_SHA:
        raise ValueError("Cohort lock changed")
    triples = json.loads(LOCK.read_bytes())
    if args.sanity:
        triples = [
            t
            for t in triples
            if t[0] == 0 or t[1] in ("AUDIT384_DEFAULT_0025", "AUDIT384_SEEDED_0074")
        ]
    if args.only:
        subset = set(args.only)
        triples = [t for t in triples if t[1] in subset]
        if {t[1] for t in triples} != subset:
            raise ValueError("Only locked non-eval seeds are allowed")
    protocol = runpy.run_path(str(ROOT / "scripts/verify-silent-v6.py"))
    if (
        protocol["sha"](Path(os.environ["CSV2DEV_HOST"]).read_bytes()) != protocol["HOST_SHA"]
        or protocol["sha"]((ROOT / "artifacts/upstreams/sts2-cli/lib/sts2.dll").read_bytes())
        != protocol["GAME_SHA"]
        or os.getenv("DOTNET_STARTUP_HOOKS")
        or any(os.getenv(k) != "1" for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS"))
    ):
        raise ValueError("Runtime differs from the pinned protocol")
    (out / "rules").mkdir(exist_ok=True)
    prepare_rules(out / "rules")
    build = runpy.run_path(str(ROOT / "scripts/build-batch1-challengers.py"))["build_batch1_bundle"]
    bundle = build(
        ROOT / "releases/silent-a10-mecha-knight/challenger/policy.json",
        out / "arm4",
        profile="all_v2_search_v6",
    )
    if protocol["sha"](bundle.read_bytes()) != protocol["PINS"]["v6"]:
        raise ValueError("Arm 4 manifest changed")
    DeployedController.from_bundle(bundle)
    jobs = [
        (out, bundle, triple, t)
        for triple in triples
        for t in ((True, False) if args.sanity else (True,))
    ]
    with ProcessPoolExecutor(args.workers) as pool:
        for f in as_completed([pool.submit(collect, job) for job in jobs]):
            print(*f.result(), flush=True)


if __name__ == "__main__":
    main()
