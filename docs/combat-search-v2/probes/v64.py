"""Run only the pre-registered CSV9DEV triples and retain compact per-lobby receipts."""

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
import gzip
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
from tempfile import TemporaryDirectory

from sts2rl.run_bundle import load_bundle
from sts2rl.run_evaluation import play_episode
from sts2rl.run_policy import RunWeights
from sts2rl.unified_draft import identity, normalize

ROOT = Path(__file__).resolve().parents[3]
DOC = ROOT / "docs/combat-search-v2"
ARMS = ("v64_control", "unified_size_165", "unified_size_0")
LOCK_SHA = "afe45cafa3e320e120f5bea8752e3fb89122f8aa7c98fcb7032e05153cd5d777"


def cohort():
    data = (DOC / "csv9dev-lock.json").read_bytes()
    assert hashlib.sha256(data).hexdigest() == LOCK_SHA
    rows = json.loads(data)
    assert rows == [
        [i, f"CSV9DEV_{m.upper()}_{i:04d}", m] for i in range(192) for m in ("default", "seeded")
    ]
    return rows


def episode(folder, bundle, triple):
    i, seed, mode = triple
    role, opts = load_bundle(bundle)
    events, deck_size = [], {}
    commands = hashlib.sha256()
    history = []

    def log(state, action):
        ctx = state["context"]
        act, floor = ctx["act"], ctx["floor"]
        deck = state.get("player", {}).get("deck")
        if deck is not None:
            deck_size[act] = len(deck)
        history.append(action.command())
        commands.update(json.dumps(history[-1], sort_keys=True).encode() + b"\n")
        kind = state["decision"]
        if kind in ("card_reward", "shop", "bundle_select"):

            def offer(c):
                return [
                    identity(c),
                    normalize(c)["upgraded"],
                    c.get("index"),
                    c.get("cost") if kind == "shop" else None,
                ]

            cards = (
                [[offer(c) for c in b["cards"]] for b in state["bundles"]]
                if kind == "bundle_select"
                else [offer(c) for c in state["cards"] if c.get("is_stocked", True)]
            )
            events.append(
                [act, floor, kind, cards, action.kind, action.args, bool(state.get("can_skip"))]
            )
        return action

    with TemporaryDirectory(dir=folder) as tmp:
        run = Path(tmp) / "episode"
        row = play_episode(
            (
                ROOT,
                os.environ["CSV2DEV_HOST"],
                run,
                seed,
                i,
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
            ),
            decision_hook=log,
        )
        timings = json.loads((run / "combat-decision-ns.json").read_bytes())
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
        offers=events,
        deck_size=deck_size,
        commands=commands.hexdigest(),
        latency_us=Counter((ns + 500) // 1000 for ns in timings),
    )
    if receipt["mismatches"]:
        receipt["history"] = history
    path = folder / (seed + ".json.gz")
    path.write_bytes(gzip.compress(json.dumps(receipt, separators=(",", ":")).encode(), mtime=0))
    if row["status"] != "complete" or row.get("error") or row.get("abandoned"):
        raise RuntimeError((seed, row.get("status"), row.get("error")))


def run_triple(job):
    out, bundles, triple = job
    shift = (2 * triple[0] + int(triple[2] == "seeded")) % 3
    for arm in ARMS[shift:] + ARMS[:shift]:
        episode(out / arm, bundles[arm], triple)
    return triple[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path)
    parser.add_argument("--workers", type=int, choices=[12], required=True)
    args = parser.parse_args()
    protocol = runpy.run_path(str(ROOT / "scripts/verify-silent-v6.py"))
    for filename, checksum in (
        (Path(os.environ["CSV2DEV_HOST"]), protocol["HOST_SHA"]),
        (ROOT / "artifacts/upstreams/sts2-cli/lib/sts2.dll", protocol["GAME_SHA"]),
    ):
        assert hashlib.sha256(filename.read_bytes()).hexdigest() == checksum
    assert all(os.getenv(k) == "1" for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS"))
    assert not os.getenv("DOTNET_STARTUP_HOOKS")
    assert not subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT).strip()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    build = runpy.run_path(str(ROOT / "scripts/build-batch1-challengers.py"))["build_batch1_bundle"]
    bundles = {}
    for arm in ARMS:
        bundles[arm] = build(
            ROOT / "releases/silent-a10-mecha-knight/challenger/policy.json", out / arm, profile=arm
        )
    manifest = dict(
        commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        lock=LOCK_SHA,
        bundles={k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in bundles.items()},
        host=protocol["HOST_SHA"],
        game=protocol["GAME_SHA"],
        workers=args.workers,
    )
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    with ProcessPoolExecutor(args.workers) as pool:
        futures = [pool.submit(run_triple, (out, bundles, triple)) for triple in cohort()]
        for f in as_completed(futures):
            print(f.result(), flush=True)


if __name__ == "__main__":
    main()
