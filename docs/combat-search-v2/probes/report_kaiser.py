"""Recompute the locked Kaiser comparisons and turn evidence from the compact native receipts."""

import argparse
from collections import Counter, defaultdict
import gzip
import itertools
import json
from math import ceil, comb
from pathlib import Path
from statistics import mean, median
import zipfile

import numpy as np

from kaiser import DOC, locked
from report_audit384 import categories, read_rows, reason_class, totals

BOSSES = ("CRUSHER+ROCKET", "KNOWLEDGE_DEMON", "THE_INSATIABLE")


def floor(row):
    return 17 * (row["act"] - 1) + row["floor"]


def summarize(rows):
    coverage, native, times = Counter(), Counter(), Counter()
    exits = defaultdict(list)
    enemy_hp = []
    for row in rows:
        coverage.update(row["coverage"])
        native.update(row["native"])
        times.update({int(k): v for k, v in row["latency"].items()})
        for act, _, room, formation, hp, survived in row["late_fights"]:
            if act == 2 and room == "Boss":
                exits[formation].append(hp)
                assert survived == (hp > 0)
                if not survived and formation == BOSSES[0]:
                    enemy_hp.append(sum(e[1] for e in row["turns"][-1]["enemies"]))
    n = times.total()
    latency = {}
    for q in (50, 95):
        count = 0
        for us in sorted(times):
            count += times[us]
            if count >= ceil(n * q / 100):
                latency[f"p{q}_ms"] = us / 1000
                break
    kaiser = exits[BOSSES[0]]
    return dict(
        n=len(rows),
        mean_floor=mean(floor(r) for r in rows),
        act1_clears=sum(r["a1_clear"] for r in rows),
        act2_entries=sum(any(a == 2 for a, _ in r["boss_fights"]) for r in rows),
        act2_clears=sum(r["a2_clear"] for r in rows),
        act3_entries=sum(any(a == 3 for a, _ in r["boss_fights"]) for r in rows),
        full_wins=sum(r["win"] for r in rows),
        native=dict(native),
        zero_comparable=sum(
            not (r["native"].get("match") or r["native"].get("mismatch")) for r in rows
        ),
        bosses={
            b: dict(clears=sum(hp > 0 for hp in exits[b]), entries=len(exits[b])) for b in BOSSES
        },
        kaiser_covered=coverage["covered"],
        kaiser_eligible=coverage.total(),
        kaiser_coverage_pct=100 * coverage["covered"] / coverage.total(),
        fallback=dict(coverage),
        kaiser_median_enemy_hp_deaths=median(enemy_hp) if enemy_hp else None,
        kaiser_median_exit_hp=median(kaiser),
        kaiser_mean_exit_hp=mean(kaiser),
        kaiser_clear_exit_hp=sorted(hp for hp in kaiser if hp),
        latency_samples=n,
        **latency,
    )


def comparison(control, treatment):
    def by_seed(rows):
        return {r["seed"]: r for r in rows}

    a, b = by_seed(control), by_seed(treatment)
    assert a.keys() == b.keys()
    strata = defaultdict(list)
    by_boss = Counter()
    changes = []
    for seed in sorted(a):
        c, t = a[seed], b[seed]
        assert c["act_list"] == t["act_list"] and c["opening"] == t["opening"]
        delta = floor(t) - floor(c)
        strata[t["act_list"]].append(delta)
        if c["commands"] != t["commands"]:
            changes.append(seed)
            assert c["opening"], (seed, "non-Kaiser commands changed")
        if c["late_fights"] and c["late_fights"][0][3] in BOSSES:
            by_boss[c["late_fights"][0][3]] += c["commands"] != t["commands"]
    diffs = sum(strata.values(), [])
    wins, losses, ties = (sum(v > 0 for v in diffs), sum(v < 0 for v in diffs), diffs.count(0))
    rng = np.random.default_rng(621)
    totals = np.zeros(50000)
    for mode in sorted(strata):
        values = strata[mode]
        for i in range(0, len(totals), 500):
            totals[i : i + 500] += rng.choice(values, (500, len(values))).sum(axis=1)
    return dict(
        n=len(a),
        delta_floor=mean(diffs),
        ci95=np.quantile(totals / len(a), [0.025, 0.975]).tolist(),
        wins=wins,
        losses=losses,
        ties=ties,
        sign_p=min(
            1,
            2
            * sum(comb(wins + losses, k) for k in range(min(wins, losses) + 1))
            / (1 << (wins + losses)),
        ),
        same_openings=sum(bool(r["opening"]) for r in control),
        changed_commands=len(changes),
        changed_by_boss=dict(by_boss),
        paired_floor_changes={
            k: floor(b[k]) - floor(a[k]) for k in a if floor(b[k]) != floor(a[k])
        },
    )


def facing(turn):
    """Classify underlying head-on total. Try every rounding/modifier assignment compatible with both previews."""
    es, face = turn["enemies"], turn["facing"]
    if len(es) != 2 or face not in (0, 1):
        return "single_or_unknown"
    classifications = set()
    for weak_factor, vulnerability, intangible in itertools.product(
        (12, 15), (2, 3), (False, True)
    ):
        possible = []
        for slot, (arm, _, _, intents, powers) in enumerate(es):
            attack = [i for i in intents if "damage" in i]
            if not attack:
                possible.append([0])
                continue
            (intent,) = attack
            hits = intent.get("hits", 1)
            bases = ((7,) if hits == 2 else (4, 14)) if arm == "CRUSHER" else (4, 20, 35)
            powers = {p["id"]: p["amount"] for p in powers}
            weak = weak_factor if powers.get("POWER.WEAK_POWER", 0) > 0 else 20
            strength = powers.get("POWER.STRENGTH_POWER", 0)

            def amount(base, behind):
                raw = max(0, base + strength) * weak * vulnerability * (3 if behind else 2) // 80
                return min(1, raw) if intangible else raw

            possible.append(
                [
                    hits * amount(base, False)
                    for base in bases
                    if amount(base, slot != face) == intent["damage"]
                ]
            )
        for pair in itertools.product(*possible):
            front, back = pair[face], pair[1 - face]
            classifications.add(
                "lighter" if front < back else "heavier" if front > back else "equal"
            )
    return classifications.pop() if len(classifications) == 1 else "ambiguous"


def forensics(rows):
    end_turns = defaultdict(list)
    first_kill = defaultdict(Counter)
    alternatives = Counter()
    split = 0
    opening_damage = []
    for row in rows:
        turns = row["turns"]
        targets = set()
        for t in turns:
            if len(t["enemies"]) == 2 and "target_index" in t["action"]["args"]:
                targets.add(t["action"]["args"]["target_index"])
            if t["action"]["action"] == "end_turn":
                end_turns[t["round"]].append(t)
            if t["alternative"] and t["alternative"][0]:
                alternatives[str((t["fallback"] or "covered", t["alternative"][1]))] += 1
        split += len(targets) == 2
        third = next((t for t in turns if t["round"] == 3 and len(t["enemies"]) == 2), None)
        if third:
            opening_damage.append(
                [a[1] - b[1] for a, b in zip(turns[0]["enemies"], third["enemies"], strict=True)]
            )
        arm = next((t["enemies"][0][0] for t in turns if len(t["enemies"]) == 1), None)
        first = {
            "ROCKET": "Crusher first",
            "CRUSHER": "Rocket first",
            None: "both on last public board",
        }[arm]
        first_kill[first]["entries"] += 1
        first_kill[first]["clears"] += row["a2_clear"]
    return dict(
        targeted_both=split,
        first_kill=first_kill,
        kill_candidate_roots=alternatives,
        round3_both_took_damage=sum(min(ds) > 0 for ds in opening_damage),
        round3_median_hp_lost=[median(v) for v in zip(*opening_damage, strict=True)],
        rounds={
            k: dict(
                end_turns=len(ts),
                player_hp_median=median(t["hp"] for t in ts),
                enemy_hp_median=median(sum(e[1] for e in t["enemies"]) for t in ts),
                facing=Counter(map(facing, ts)),
            )
            for k, ts in sorted(end_turns.items())
        },
    )


def boundaries(control, forensic):
    expected = {r["seed"]: r for r in control}
    assert len(forensic) == len(expected)
    for r in forensic:
        partner = expected[r["seed"]]
        assert (r["commands"], r["native"], r["opening"]) == (
            partner["commands"],
            partner["native"],
            partner["opening"],
        )
    turns = [t for r in forensic for t in r["turns"] if t["eligible"] and t["fallback"]]
    no_survival = [t for t in turns if t["fallback"] == "no certified survival"]
    ambiguous = [t for t in turns if "ambiguous attack preview" in t["failed_boundaries"]]
    archive = read_rows(DOC / "v6-audit-autopsy-receipts.zip")
    fights = [
        f
        for r in archive
        if r["seed"] in expected
        for f in r["encounters"]
        if f["formation"] == BOSSES[0]
    ]
    majorities = Counter()
    mechanic = Counter()
    for fight in fights:
        if not fight.get("fatal"):
            continue
        counts = categories(fight["counts"])
        group = next((g for g, n in counts.items() if n * 2 > sum(counts.values())), "mixed")
        majorities[group] += 1
        if group == "mechanic_or_scope":
            mechanic.update({r: n for r, n in fight["counts"].items() if reason_class(r) == group})
    return dict(
        fatal_majorities=majorities,
        majority_mechanic_reasons=mechanic,
        no_survival_leaf_kinds=totals(f["failed_leaf_kinds"] for f in fights),
        all_failed_boundaries=Counter(k for t in turns for k in t["failed_boundaries"]),
        no_survival_boundaries=Counter(k for t in no_survival for k in t["failed_boundaries"]),
        ambiguous_roots=len(ambiguous),
        ambiguous_trials=totals(t["preview_trials"] for t in ambiguous),
        all_ambiguous_trials_resolved_roots=sum(
            bool(t["preview_trials"].get("resolved"))
            and not t["preview_trials"].get("still_ambiguous")
            for t in ambiguous
        ),
    )


def analyze(path):
    result = {}
    with zipfile.ZipFile(path) as z:
        for panel in ("audit", "dev"):
            names = {s for _, s, _ in locked(panel)}
            data = {}
            for arm in ("control", "treatment", *(("rage-ablation",) if panel == "audit" else ())):
                raw = gzip.decompress(z.read(f"{panel}/{arm}.jsonl.gz"))
                rows = list(map(json.loads, raw.splitlines()))
                assert len(rows) == len(names) and {r["seed"] for r in rows} == names
                assert all(
                    r["status"] == "complete"
                    and not r["abandoned"]
                    and not r["error"]
                    and len(r["mismatches"]) == r["native"].get("mismatch", 0)
                    for r in rows
                )
                data[arm] = rows
            result[panel] = {arm: summarize(rows) for arm, rows in data.items()}
            result[panel]["paired"] = comparison(data["control"], data["treatment"])
            if panel == "audit":
                result[panel]["rage_paired"] = comparison(data["control"], data["rage-ablation"])
                result[panel]["control_turn_evidence"] = forensics(data["control"])
                preview = gzip.decompress(z.read("audit/preview-audit.jsonl.gz"))
                result[panel]["forensic_boundaries"] = boundaries(
                    data["control"], list(map(json.loads, preview.splitlines()))
                )
        for key in ("cohort-proof", "qualification", "discovery"):
            result[key] = json.loads(z.read(key + ".json"))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip", type=Path)
    args = parser.parse_args()
    print(json.dumps(analyze(args.zip), indent=2))
