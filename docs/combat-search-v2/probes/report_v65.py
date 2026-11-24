"""Analyze the locked CSV10DEV compact receipts and audit public acquisition eligibility."""

import argparse
from collections import Counter
from functools import cache
import gzip
import json
from pathlib import Path
import zipfile

from report_v64 import paired, summarize
from sts2rl.draft_v65 import generator, prohibited
from sts2rl.unified_draft import normalize
from v65 import ARMS, LOCK_SHA, cohort
from v64 import DOC


@cache
def card(name, upgraded):
    return normalize({"id": name, "upgrades": upgraded})


def audit(rows, arm):
    """A mandatory acquisition is avoidable if a clean legal alternative existed."""
    counts = Counter()
    picked = Counter()
    for row in rows:
        for prompt, context in zip(row["offers"], row["acquisition_context"], strict=True):
            _, _, kind, cards, action, args, legal_skip = prompt
            energy, generators = context
            if kind == "bundle_select":
                bundles = []
                for bundle in cards:
                    sources = generators
                    blocked = []
                    for name, up, _, _ in bundle:
                        c = card(name, up)
                        if prohibited(c, energy, sources):
                            blocked.append(name)
                        if arm == "unified_draft_v65":
                            sources += generator(c)
                    bundles.append(blocked)
                counts["offered"] += sum(map(len, bundles))
                chosen = bundles[args["bundle_index"]]
                picked.update(chosen)
                counts["unavoidable"] += min(map(len, bundles))
                counts["avoidable"] += len(chosen) - min(map(len, bundles))
            else:
                blocked = {
                    slot: name
                    for name, up, slot, _ in cards
                    if prohibited(card(name, up), energy, generators)
                }
                counts["offered"] += len(blocked)
                if action in ("select_card_reward", "buy_card") and args["card_index"] in blocked:
                    picked[blocked[args["card_index"]]] += 1
                    forced = kind == "card_reward" and not legal_skip and len(blocked) == len(cards)
                    counts["unavoidable" if forced else "avoidable"] += 1
    return {
        **{k: counts[k] for k in ("offered", "avoidable", "unavoidable")},
        "picked": picked.total(),
        "by_card": dict(picked),
    }


def replay_audit(original, replay):
    totals, reclassified = Counter(), Counter()
    differing_steps = []
    for first, second in zip(original, replay, strict=True):
        # Both physical runs use the frozen acting policy and its original oracle.
        # Timing and the second observer's annotations are the only new information.
        def deterministic(row):
            data = {
                k: v
                for k, v in row.items()
                if k not in ("latency_us", "independent_native", "draw_order_boundaries")
            }
            data["mismatches"] = [
                {k: v for k, v in m.items() if k not in ("ns", "independent_oracle")}
                for m in row["mismatches"]
            ]
            return data

        assert deterministic(first) == deterministic(second), first["seed"]
        expected = Counter(first["native"])
        for step, before, after in second["draw_order_boundaries"]:
            assert before[0] == after[0] == "end_turn" and after[1] == "unresolved"
            expected[before[1]] -= 1
            expected[after[1]] += 1
            reclassified[before[1]] += 1
            differing_steps.append([first["seed"], step, before, after])
        assert expected == Counter(second["independent_native"]), first["seed"]
        totals.update(expected)
    return dict(
        native={k: totals[k] for k in ("match", "mismatch", "unresolved")},
        deterministic_receipts=len(original),
        boundaries=dict(reclassified),
        steps=differing_steps,
    )


def analyze(archive):
    with zipfile.ZipFile(archive) as z:
        manifest = json.loads(z.read("manifest.json"))
        assert manifest["lock"] == LOCK_SHA
        expected = [(seed, mode) for _, seed, mode in cohort()]
        rows = {}
        for arm in ARMS:
            rows[arm] = list(
                map(json.loads, gzip.decompress(z.read(arm + ".jsonl.gz")).splitlines())
            )
            assert [(r["seed"], r["act_list"]) for r in rows[arm]] == expected
        replay = {}
        if "reaudit/manifest.json" in z.namelist():
            replay_manifest = json.loads(z.read("reaudit/manifest.json"))
            for key in ("bundles", "lock", "workers", "host", "game"):
                assert replay_manifest[key] == manifest[key]
            assert replay_manifest["audit_draw_order_v65"]
            for arm in ARMS:
                repeat = list(
                    map(
                        json.loads,
                        gzip.decompress(z.read("reaudit/" + arm + ".jsonl.gz")).splitlines(),
                    )
                )
                replay[arm] = replay_audit(rows[arm], repeat)
        preflight = json.loads(z.read("qualification/preflight.json"))
        qualification = json.loads(z.read("qualification/qualification.json"))
        qualification["cohort"] = json.loads(z.read("qualification/cohort-proof.json"))
        qualification["registered_pytest"] = (
            z.read("qualification/registered-tests.log").decode().splitlines()[-1]
        )
        if replay:
            qualification["final_pytest"] = (
                z.read("qualification/final-tests.log").decode().splitlines()[-1]
            )
            qualification["final_ruff"] = z.read("qualification/final-ruff.log").decode().strip()
    results = {}
    for arm, episodes in rows.items():
        result = summarize(episodes)
        result["hard_skip_audit"] = audit(episodes, arm)
        result["combat_steps"] = result["latency_n"]
        result["native_matches_per_100_combat_decisions"] = (
            100 * result["native"]["match"] / result["combat_steps"]
        )
        results[arm] = result
    previous = json.loads((DOC / "v64-unified-draft.json").read_bytes())["arms"]["unified_size_0"]
    return dict(
        independent_audit=replay,
        audit_manifest=replay_manifest if replay else None,
        historical_csv9dev_b=previous,
        manifest=manifest,
        qualification=qualification,
        preflight=preflight,
        arms=results,
        paired={arm: paired(rows[ARMS[0]], rows[arm]) for arm in ARMS[1:]},
        b_vs_a=paired(rows[ARMS[1]], rows[ARMS[2]]),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(analyze(args.archive), indent=2, sort_keys=True) + "\n", encoding="utf8"
    )
