"""Paired CSV11DEV triples on the pinned host, with per-card native evidence."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
import gzip
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
from unittest.mock import patch

from sts2rl.combat_search_v2 import transitions
from sts2rl.combat_search_v2.integration import CombatSearchV2, _difference
from sts2rl.combat_search_v2.state import project, root_move
from sts2rl.run_bundle import freeze_bundle, load_bundle
from v64 import ROOT, episode

ARMS = ("control", "arm1", "arm2")
BASE = "8c27ce5ddf5348f88b1cedb3c3cd5b24bd5c40b1"


def cohort():
    return [(i, f"CSV11DEV_{mode.upper()}_{i:04d}", mode) for i in range(96) for mode in ("default", "seeded")]


def build(out):
    profiles = ("trap_cleanup_v65", "trap_cleanup_v65", "unified_draft_v65")
    builder = runpy.run_path(str(ROOT / "scripts/build-batch1-challengers.py"))["build_batch1_bundle"]
    bundles = {}
    for arm, profile in zip(ARMS, profiles, strict=True):
        dest = out / arm
        ref = builder(ROOT / "releases/silent-a10-mecha-knight/challenger/policy.json", dest, profile=profile)
        if arm != "control":
            role, opts = load_bundle(ref)
            config = json.loads(opts["combat_search_v2_config"].read_bytes())
            config["silent_cards_v66"] = True
            path = dest / "v66.json"
            path.write_text(json.dumps(config, indent=2) + "\n", newline="\n")
            opts["combat_search_v2_config"] = path
            ref = freeze_bundle({"args": {**opts, "roles": [role]}}, dest / "v66")
        bundles[arm] = ref
    return bundles


def triple(out, bundles, row):
    shift = (2 * row[0] + int(row[2] == "seeded")) % 3
    for arm in ARMS[shift:] + ARMS[:shift]:
        run_arm(out / arm, bundles[arm], row)
    return row[1]


def run_arm(folder, bundle, row):
    """Count card bodies and individual target hits only on native-matched transitions."""
    original_observe = CombatSearchV2.observe
    original_effect, original_damage = transitions._card_effect, transitions._damage
    bodies, hits = Counter(), Counter()
    independent = Counter()
    pocketwatch_checks = []

    def observe(mode, action, after, enumerate_actions):
        executions, strikes = Counter(), Counter()
        source = None

        def damage(state, slot, amount, **kwargs):
            if source and state.enemies[slot].hp > 0 and kwargs.get("attacker_powers") is not None:
                strikes[source] += 1
            return original_damage(state, slot, amount, **kwargs)

        def effect(state, play):
            nonlocal source
            source = play.card.variant.name
            executions[source] += 1
            result = original_effect(state, play)
            source = None
            return result

        context = mode._decision
        with patch.object(transitions, "_card_effect", effect), patch.object(transitions, "_damage", damage):
            original_observe(mode, action, after, enumerate_actions)
        oracle = mode.records[-1].get("oracle") if mode.records else None
        if oracle and oracle[1] == "match":
            bodies.update(executions)
            hits.update(strikes)
        if folder.name == "control" and oracle:
            verdict = oracle[1]
            if context and action.kind == "end_turn" and verdict in ("match", "mismatch"):
                prior = context[0].state
                watch = next((r for r in prior.relics if r.name == "POCKETWATCH"), None)
                if prior.late and watch and any(r.name == "TOASTY_MITTENS" for r in prior.relics):
                    # The original observer refreshes status inside the paused Mittens
                    # prompt. The pinned Pocketwatch model refreshes after that prompt.
                    fixed = transitions.advance(prior, root_move(context[0], action.kind, action.args))
                    if fixed.outcome == "completed" and after.get("decision") == "card_select":
                        actual = project(after, late_prompts=True).state
                        if actual.prompt.operation == "TOASTY_MITTENS":
                            fixed = replace(fixed, relics=tuple(replace(r, status=watch.status)
                                            if r.name == "POCKETWATCH" else r for r in fixed.relics))
                            verdict = "mismatch" if _difference(fixed, actual) else "match"
                            pocketwatch_checks.append([prior.act, prior.floor, prior.round, oracle[1], verdict])
            independent[verdict] += 1

    with patch.object(CombatSearchV2, "observe", observe):
        episode(folder, bundle, row, card_counts=True)
    path = folder / (row[1] + ".json.gz")
    data = json.loads(gzip.decompress(path.read_bytes()))
    data.update(matched_card_bodies=bodies, matched_attack_hits=hits)
    if folder.name == "control":
        data.update(independent_native=independent, pocketwatch_checks=pocketwatch_checks)
    path.write_bytes(gzip.compress(json.dumps(data, separators=(",", ":")).encode(), mtime=0))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    assert all(os.environ[k] == "1" for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS"))
    assert not os.getenv("DOTNET_STARTUP_HOOKS")
    pins = runpy.run_path(str(ROOT / "scripts/verify-silent-v6.py"))
    for path, name in [(Path(os.environ["CSV2DEV_HOST"]), "HOST_SHA"),
                       (ROOT / "artifacts/upstreams/sts2-cli/lib/sts2.dll", "GAME_SHA")]:
        assert hashlib.sha256(path.read_bytes()).hexdigest() == pins[name]
    assert not subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT).strip()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    bundles = build(out)
    rows = cohort()
    manifest = dict(commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                    base=BASE, host=pins["HOST_SHA"], game=pins["GAME_SHA"], workers=12,
                    cohort=rows, bundles={arm: hashlib.sha256(p.read_bytes()).hexdigest() for arm, p in bundles.items()})
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    with ProcessPoolExecutor(12) as pool:
        jobs = [pool.submit(triple, out, bundles, row) for row in rows]
        for job in as_completed(jobs):
            print(job.result(), flush=True)


if __name__ == "__main__":
    main()
