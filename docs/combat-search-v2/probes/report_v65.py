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
        preflight = json.loads(z.read("qualification/preflight.json"))
        qualification = json.loads(z.read("qualification/qualification.json"))
        qualification["cohort"] = json.loads(z.read("qualification/cohort-proof.json"))
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
