"""Fresh, paired flags-off/shadow receipts. Run directly with PYTHONPATH=src."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import struct

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
    return (bundle, mode, index, result["status"], len(trace), len(scores), digest(canonical))


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
    print(json.dumps(record))
    if any(row[3] != "complete" for row in rows):
        raise SystemExit("Incomplete native panel")
    if args.reference and json.loads((args.reference / "summary.json").read_text()) != json.loads(
            json.dumps(record)):
        raise SystemExit("Gate differs from reference")


if __name__ == "__main__":
    main()

