"""Paired native runs. Only the harness sees the lock, history, and post-action telemetry."""

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import ExitStack
from dataclasses import asdict, replace
import gzip
import hashlib
import json
import os
from pathlib import Path
import runpy
from tempfile import TemporaryDirectory
from unittest.mock import patch
import zipfile

from sts2rl.combat_search_v2 import planner, episode_summary, value, end_turn
from sts2rl.combat_search_v2.integration import CombatSearchV2
from sts2rl.native import NativeSession, NativeError, digest, legal_actions
from sts2rl.run_bundle import load_bundle
from sts2rl.run_evaluation import play_episode
from sts2rl.run_policy import RunWeights

ROOT = Path(__file__).resolve().parents[3]
DOC = ROOT / "docs/combat-search-v2"
CRABS = {"MONSTER.CRUSHER", "MONSTER.ROCKET"}
AUDIT_SHA = "69e364e20fc73853d65388367711345cc448a9b1d6a094407882cb928a83bdb2"
DEV_SHA = "3647cc5d3327c94feb6cd7d4704205c7975c60872438ad556cfccc88ee8eafe5"


def locked(panel):
    audit = panel == "audit"
    path = DOC / ("v6-audit384-lock.json" if audit else "csv7dev-lock.json")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (AUDIT_SHA if audit else DEV_SHA)
    rows = json.loads(path.read_bytes())
    if audit:
        with zipfile.ZipFile(DOC / "v6-audit-autopsy-receipts.zip") as archive:
            raw = gzip.decompress(archive.read("clean/episodes.jsonl.gz")).splitlines()
        entries = {
            r["seed"]
            for r in map(json.loads, raw)
            if any(f["formation"] == "CRUSHER+ROCKET" for f in r["encounters"])
        }
        rows = [r for r in rows if r[1] in entries]
        assert len(rows) == 45
    return rows


def episode(job, *, kaiser_metrics=None):
    bundle, out, triple, audit, arm = job
    index, seed, mode = triple
    role, opts = load_bundle(bundle)
    if arm == "treatment":
        opts["combat_search_v2_config"] = str(out / "kaiser_config.json")
    native_step, choose, original_result = (
        NativeSession.step,
        CombatSearchV2.choose,
        planner._Search.result,
    )
    transcript = hashlib.sha256()
    public_boards = hashlib.sha256()
    metrics = Counter()
    history, turns, errors = [], [], []
    opening = facing = current = alternative = None
    coverage = Counter()
    preview_trials = Counter()
    failed_boundaries = ()
    original_amount = end_turn.attack_amount

    def diagnose_amount(state, enemy, intent):
        amount = original_amount(state, enemy, intent)
        if amount is None and enemy.name in ("CRUSHER", "ROCKET"):
            exact = original_amount(replace(state, kaiser_v63=True), enemy, intent)
            preview_trials["still_ambiguous" if exact is None else "resolved"] += 1
        return amount

    def step(host, action):
        nonlocal current
        current = action
        if kaiser_metrics:
            public_boards.update(action.snapshot.encode())
        history.append(action.command())
        transcript.update(json.dumps(action.command(), sort_keys=True).encode() + b"\n")
        return native_step(host, action)

    observe = CombatSearchV2.observe

    def observe_native(search, action, after, enumerate_actions):
        context = search._decision
        observe(search, action, after, enumerate_actions)
        if (
            context
            and search.records
            and (search.records[-1].get("oracle") or [None, None])[1] == "mismatch"
        ):
            state = context[0].state
            fields = (
                "late",
                "v61_rules",
                "kaiser_v63",
                "puzzle_triggered",
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
            search.records[-1]["replay"] = dict(
                before=action.snapshot,
                after=digest(after),
                witness={k: getattr(state, k) for k in fields},
            )

    def choose_facing(search, public, champion, enumerate_actions, **kwargs):
        nonlocal facing, failed_boundaries
        preview_trials.clear()
        failed_boundaries = ()
        facing = kwargs.get("facing")
        return choose(search, public, champion, enumerate_actions, **kwargs)

    def compare(search):
        nonlocal alternative, failed_boundaries
        result = original_result(search)
        failed_boundaries = tuple(k for k, _ in result.boundary_counts)
        if (
            audit
            and result.line
            and any(e.name in ("ROCKET", "CRUSHER") for e in result.line.state.enemies)
        ):
            candidates = [
                line for line in search.certified if line and line.state.outcome == "completed"
            ]
            killed = [
                line
                for line in candidates
                if len(line.state.enemies) == 2 and sum(e.hp > 0 for e in line.state.enemies) == 1
            ]
            alternative = [len(killed), bool(result.line in killed)]
        return result

    class Summary(episode_summary.EpisodeSummary):
        def observe(self, before, after, fallback):
            nonlocal opening, alternative, facing
            super().observe(before, after, fallback)
            view = before.get("combat_state", before)
            enemies = view.get("enemies", [])
            if before.get("in_combat") and any(e["id"] in CRABS for e in enemies):
                opening = opening or digest(before)
                try:
                    eligible = len(legal_actions(before)) > 1
                except NativeError:
                    eligible = (
                        before["decision"] == "card_select" and len(before.get("cards", [])) > 1
                    )
                if eligible:
                    coverage[fallback or "covered"] += 1
                if kaiser_metrics:
                    kaiser_metrics(view, current, facing, eligible, fallback, metrics)
                if audit or after["decision"] == "game_over":
                    turns.append(
                        dict(
                            round=view["round"],
                            hp=view["player"]["hp"],
                            block=view["player"]["block"],
                            enemies=[
                                [
                                    e["id"][8:],
                                    e["hp"],
                                    e["block"],
                                    e.get("intents"),
                                    e.get("powers"),
                                ]
                                for e in enemies
                            ],
                            facing=facing,
                            card=next(
                                (
                                    c["id"][5:]
                                    for c in view["hand"]
                                    if current.kind == "play_card"
                                    and c["index"] == current.args["card_index"]
                                ),
                                None,
                            ),
                            action=current.command(),
                            fallback=fallback,
                            eligible=eligible,
                            alternative=alternative,
                            failed_boundaries=failed_boundaries,
                            preview_trials=dict(preview_trials),
                        )
                    )
            alternative = facing = None

        def audit(self, record, second_audit=None):
            super().audit(record, second_audit)
            if (record.get("oracle") or [None, None])[1] == "mismatch":
                errors.append([len(history) - 1, record])

    with TemporaryDirectory(dir=None if kaiser_metrics else out) as tmp, ExitStack() as stack:
        stack.enter_context(patch.object(episode_summary, "EpisodeSummary", Summary))
        stack.enter_context(patch.object(NativeSession, "step", step))
        stack.enter_context(patch.object(CombatSearchV2, "observe", observe_native))
        if arm == "rage-ablation":
            original = value._boss_adjustment

            def no_rage(state):
                if all(e.name in ("CRUSHER", "ROCKET") for e in state.enemies):
                    return 0
                return original(state)

            stack.enter_context(patch.object(value, "_boss_adjustment", no_rage))
        if arm == "preview-audit":
            stack.enter_context(patch.object(end_turn, "attack_amount", diagnose_amount))
        if audit or kaiser_metrics:
            stack.enter_context(patch.object(CombatSearchV2, "choose", choose_facing))
        if audit:
            stack.enter_context(patch.object(planner._Search, "result", compare))
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
        latency = Counter(
            (ns + 500) // 1000
            for ns in json.loads((folder / "combat-decision-ns.json").read_bytes())
        )
    keys = (
        "seed",
        "act_list",
        "status",
        "error",
        "abandoned",
        "act",
        "floor",
        "a1_clear",
        "a2_clear",
        "boss_fights",
        "win",
        "late_fights",
        "steps",
        "native",
        "mismatches",
    )
    receipt = {k: row.get(k) for k in keys}
    receipt.update(
        opening=opening,
        turns=turns,
        coverage=coverage,
        latency=latency,
        commands=transcript.hexdigest(),
    )
    if kaiser_metrics:
        receipt.update(kaiser_metrics=metrics, public_boards=public_boards.hexdigest())
        if opening:
            receipt["kaiser_replay"] = history
    if errors:
        receipt.update(errors=errors, history=history[: errors[-1][0] + 1])
    (out / (seed + ".json.gz")).write_bytes(
        gzip.compress(json.dumps(receipt, separators=(",", ":")).encode(), mtime=0)
    )
    return seed, row["status"], row.get("error"), row["native"]


def run_pair(job):
    bundle, out, triple = job
    # Balance execution order within each start mode.
    arms = ("control", "treatment") if triple[0] % 2 == 0 else ("treatment", "control")
    return [episode((bundle, out / arm, triple, False, arm)) for arm in arms]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("panel", choices=("audit", "dev"))
    p.add_argument(
        "arm", choices=("control", "treatment", "rage-ablation", "preview-audit", "paired")
    )
    p.add_argument("out", type=Path)
    p.add_argument("--workers", required=True, type=int, choices=[12])
    args = p.parse_args()
    if (args.panel == "dev") != (args.arm == "paired"):
        p.error("The development cohort requires a paired run")
    triples = locked(args.panel)
    protocol = runpy.run_path(str(ROOT / "scripts/verify-silent-v6.py"))
    assert protocol["sha"](Path(os.environ["CSV2DEV_HOST"]).read_bytes()) == protocol["HOST_SHA"]
    assert (
        protocol["sha"]((ROOT / "artifacts/upstreams/sts2-cli/lib/sts2.dll").read_bytes())
        == protocol["GAME_SHA"]
    )
    assert not os.getenv("DOTNET_STARTUP_HOOKS") and all(
        os.getenv(k) == "1" for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS")
    )
    args.out.mkdir(parents=True, exist_ok=False)
    build = runpy.run_path(str(ROOT / "scripts/build-batch1-challengers.py"))["build_batch1_bundle"]
    bundle = build(
        ROOT / "releases/silent-a10-mecha-knight/challenger/policy.json",
        args.out.resolve() / "arm4",
        profile="all_v2_search_v6",
    )
    assert protocol["sha"](bundle.read_bytes()) == protocol["PINS"]["v6"]
    if args.arm == "paired":
        for arm in ("control", "treatment"):
            (args.out / arm).mkdir()
    if args.arm in ("treatment", "paired"):
        config = Path(load_bundle(bundle)[1]["combat_search_v2_config"])

        # Keep the builder's integrity-checked bundle intact. Override only the run option.
        override = (
            args.out / "treatment" if args.arm == "paired" else args.out
        ) / "kaiser_config.json"
        override.write_text(json.dumps({**json.loads(config.read_bytes()), "kaiser_v63": True}))
    with ProcessPoolExecutor(args.workers) as pool:
        if args.arm == "paired":
            futures = [pool.submit(run_pair, (bundle, args.out.resolve(), t)) for t in triples]
        else:
            futures = [
                pool.submit(
                    episode, (bundle, args.out.resolve(), t, args.panel == "audit", args.arm)
                )
                for t in triples
            ]
        for f in as_completed(futures):
            print(*f.result(), flush=True)


if __name__ == "__main__":
    main()
