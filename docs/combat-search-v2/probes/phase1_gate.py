"""Fresh, paired flags-off/shadow receipts. Run directly with PYTHONPATH=src."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import struct
from statistics import median, quantiles

from sts2rl.act1 import is_combat_choice
from sts2rl.encounter import EncounterPolicy
from sts2rl.native import NativeError, digest, legal_actions
from sts2rl.run_bundle import load_bundle
from sts2rl.run_evaluation import play_episode
from sts2rl.run_policy import RunPolicy, RunWeights

ROOT = Path(__file__).resolve().parents[3]
BUNDLES = ("silent-a10-v2-tactics", "silent-a10-mecha-knight")


def episode(job):
    host, output, bundle, mode, index, shadow, act = job
    role, settings = load_bundle(ROOT / "releases" / bundle / "challenger/policy.json")
    if shadow:
        settings["combat_search_v2_shadow"] = True
    elif act:
        settings["combat_search_v2"] = True
    folder = output / bundle / mode / str(index)
    scores = []
    decisions = []
    combat = []

    def record(original):
        def wrapped(actor, state, actions):
            values = original(actor, state, actions)
            scores.append((digest(state), [a.id for a in actions],
                           [struct.pack("!d", float(v)).hex() for v in values]))
            return values
        return wrapped

    def inspect(state, action):
        try:
            legal = [a.command() for a in legal_actions(state)]
        except NativeError as error:
            if state["decision"] != "card_select" or "sequential decoder" not in str(error):
                raise
            legal = {"ordered_candidates": [c["index"] for c in state["cards"]],
                     "min": state["min_select"], "max": state["max_select"]}
        decisions.append((digest(state), legal, action.command()))
        if is_combat_choice(state):
            view = state.get("combat_state", state)
            combat.append({"act": view["context"]["act"], "decision": state["decision"],
                           "formation": [e["id"].split(".", 1)[-1] for e in view.get("enemies", ())],
                           "non_forced": not isinstance(legal, list) or len(legal) > 1})
        return action

    originals = [(cls, cls.combat_scores) for cls in (RunPolicy, EncounterPolicy)]
    for cls, original in originals:
        cls.combat_scores = record(original)
    try:
        result = play_episode(
            (ROOT, host, folder, f"CSV2DEV_{mode.upper()}_{index:04}", index, role,
             asdict(RunWeights.load(settings["weights"])), settings.get("micro"),
             {**settings, "rooms": True, "seeded_acts": mode == "seeded"}), decision_hook=inspect,
        )
    finally:
        for cls, original in originals:
            cls.combat_scores = original
    trace = [json.loads(line) for line in (folder / "game/rpc.jsonl").read_text().splitlines()]
    for entry in trace:
        entry.pop("seconds")
    result.pop("seconds")
    canonical = {"result": result, "rpc": trace, "decisions": decisions, "scores": scores}
    (folder / "gate.json").write_text(json.dumps(canonical, separators=(",", ":")), encoding="utf8")
    (folder / "combat-roots.json").write_text(json.dumps(combat, separators=(",", ":")), encoding="utf8")
    return (bundle, mode, index, result["status"], len(trace), len(scores), digest(canonical))


def diagnostics(folder):
    def key(row):
        return f'{row["act"]}/{" + ".join(row["formation"])}'

    def timing(rows):
        samples = [r["ns"] / 1e6 for r in rows]
        return [median(samples), quantiles(samples, n=100, method="inclusive")[94]] if len(samples) > 1 else samples

    summary = {}
    for bundle in BUNDLES:
        coverage = defaultdict(Counter)
        outcomes = defaultdict(Counter)
        rows = []
        for path in (folder / bundle).rglob("combat-roots.json"):
            for root in json.loads(path.read_text()):
                if root["non_forced"]:
                    coverage[key(root)]["non_forced"] += 1
            sidecar = path.with_name("combat-search-v2.jsonl")
            if sidecar.exists():
                rows.extend(json.loads(line) for line in sidecar.read_text().splitlines()[1:])
        attempted = [row for row in rows if row["attempts"]]
        covered = [row for row in attempted if not row["fallback"]]
        for row in attempted:
            coverage[key(row)]["searched"] += 1
        for row in covered:
            coverage[key(row)]["covered"] += 1
        for row in rows:
            mechanic, outcome, reason = row.get("oracle", ("", "", ""))
            if mechanic:
                outcomes[mechanic][outcome] += 1
                if reason:
                    outcomes[mechanic][f"{outcome}/{reason}"] += 1
        summary[bundle] = {
            "non_forced": sum(entry["non_forced"] for entry in coverage.values()),
            "searched": len(attempted), "covered": len(covered),
            "changed": sum(row["changed"] for row in covered),
            "timing_ms_all": timing(rows), "timing_ms_searched": timing(attempted),
            "fallbacks": Counter(row["fallback"] for row in rows if row["fallback"]),
            "caps": Counter(cap for row in rows for cap in ("child_cap", "depth_cap") if row.get(cap)),
            "leaf_boundaries": sum_counters(row.get("boundaries", {}) for row in rows),
            "formations": coverage, "native": outcomes,
        }
    (folder / "diagnostics.json").write_text(json.dumps(summary, indent=2), encoding="utf8")


def sum_counters(counters):
    total = Counter()
    for counts in counters:
        total.update(counts)
    return total


def compare_search_records(reference, output):
    def records(path):
        for line in path.read_text().splitlines():
            row = json.loads(line)
            row.pop("ns", None)
            yield row

    for before in reference.rglob("combat-search-v2.jsonl"):
        after = output / before.relative_to(reference)
        if list(records(before)) != list(records(after)):
            raise SystemExit(f"Search diagnostics differ for {before.relative_to(reference)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--per-mode", type=int, default=6)
    switches = parser.add_mutually_exclusive_group()
    switches.add_argument("--combat-search-v2-shadow", action="store_true")
    switches.add_argument("--combat-search-v2", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True)
    jobs = [(args.host.resolve(), args.output.resolve(), bundle, mode, i,
             args.combat_search_v2_shadow, args.combat_search_v2)
            for i in range(args.per_mode) for bundle in BUNDLES for mode in ("default", "seeded")]
    with ProcessPoolExecutor(args.workers) as pool:
        rows = list(pool.map(episode, jobs))
    record = {"host": hashlib.sha256(args.host.read_bytes()).hexdigest(), "rows": rows}
    (args.output / "summary.json").write_text(json.dumps(record, indent=2))
    diagnostics(args.output)
    print(json.dumps(record))
    if any(row[3] != "complete" for row in rows):
        raise SystemExit("Incomplete native panel")
    if args.reference and json.loads((args.reference / "summary.json").read_text()) != json.loads(
            json.dumps(record)):
        raise SystemExit("Gate differs from reference")
    if args.reference and (args.combat_search_v2 or args.combat_search_v2_shadow):
        compare_search_records(args.reference, args.output)


if __name__ == "__main__":
    main()

