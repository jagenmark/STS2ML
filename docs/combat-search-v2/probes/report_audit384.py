"""Summarize a complete clean solo cohort; accept a collector directory or its receipts ZIP."""

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from math import ceil
from pathlib import Path
from statistics import mean, median
import zipfile

from audit384 import LOCK, LOCK_SHA


def read_rows(source):
    if source.is_dir():
        return [
            json.loads(gzip.decompress(p.read_bytes()))
            for p in sorted(source.glob("AUDIT384_*.json.gz"))
        ]
    with zipfile.ZipFile(source) as z:
        return [
            json.loads(line)
            for line in gzip.decompress(z.read("clean/episodes.jsonl.gz")).splitlines()
        ]


def reason_class(name):
    if name == "covered":
        return "covered"
    if name in (
        "no certified survival",
        "champion continuation unresolved",
        "uncertified root at cap",
        "uncompared root at cap",
        "no no-potion comparison",
        "uncompared root",
        "root exceeds child cap",
    ):
        return "search_certification"
    if name in ("champion knowledge curse", "sandpit deadline"):
        return "champion_or_deadline"
    return "mechanic_or_scope"


def totals(rows):
    result = Counter()
    for counts in rows:
        result.update(counts)
    return result


def categories(counts):
    result = Counter()
    for key, count in counts.items():
        result[reason_class(key)] += count
    return result


def summarize_fights(fights):
    fatal = [f for f in fights if f.get("fatal")]
    survived = [f for f in fights if not f.get("fatal")]

    def hp_fraction(fight):
        return fight["entry_hp"] / fight["max_hp"]

    def entry_profile(subset):
        if not subset:
            return None
        return dict(
            n=len(subset),
            mean_hp=mean(f["entry_hp"] for f in subset),
            mean_hp_fraction=mean(map(hp_fraction, subset)),
            deck={k: mean(f["deck"][k] for f in subset) for k in subset[0]["deck"]},
        )

    groups = Counter()
    for f in fatal:
        c = categories(f["counts"])
        n = sum(c.values())
        majority = next((k for k in c if c[k] * 2 > n), "mixed" if n else "no_choices")
        groups[majority] += 1
    return dict(
        entries=len(fights),
        deaths=len(fatal),
        median_enemy_hp_at_death=median(f["enemy_hp"] for f in fatal) if fatal else None,
        median_death_round=median(f["round"] for f in fatal) if fatal else None,
        mean_entry_hp=mean(f["entry_hp"] for f in fights),
        mean_entry_hp_deaths=mean(f["entry_hp"] for f in fatal) if fatal else None,
        low_entry_deaths=sum(hp_fraction(f) <= 1 / 3 for f in fatal),
        death_hp_source=Counter(f["hp_source"] for f in fatal),
        fatal_fight_majorities=groups,
        fatal_fight_decisions=categories(totals(f["counts"] for f in fatal)),
        failed_boundary_roots=totals(f["failed_boundaries"] for f in fights),
        no_survival_leaf_kinds=totals(f["failed_leaf_kinds"] for f in fights),
        entry_profiles=dict(fatal=entry_profile(fatal), survived=entry_profile(survived)),
    )


def summarize(rows):
    triples = json.loads(LOCK.read_bytes())
    if (
        hashlib.sha256(LOCK.read_bytes()).hexdigest() != LOCK_SHA
        or len(rows) != 384
        or {(r["index"], r["seed"], r["act_list"]) for r in rows} != set(map(tuple, triples))
    ):
        raise ValueError("Incomplete or incorrect cohort")
    hist = Counter()
    native = totals(r["native"] for r in rows)
    if native["match"] <= 0 or any(
        r["status"] != "complete"
        or r["abandoned"]
        or r["error"]
        or r["start_act"] != 1
        or r["ascension"] != 10
        or r["mismatches"]
        or r["native"].get("mismatch")
        for r in rows
    ):
        raise ValueError("Missing clean natural terminal or positive aggregate native audit")
    groups = defaultdict(Counter)
    choices = defaultdict(Counter)
    boss_choices = defaultdict(Counter)
    deaths = defaultdict(list)
    bosses = defaultdict(Counter)
    late = defaultdict(list)
    for r in rows:
        hist.update({int(k): v for k, v in r["latency_us"].items()})
        for k, h in r["coverage"].items():
            groups[k].update(h)
        for k, h in r["headroom"].items():
            if h["covered"] != r["coverage"][k]["covered"]:
                raise ValueError("Covered search denominator mismatch")
            choices[k].update(h)
        for act, _, _, boss, _, cleared in r["late_fights"]:
            if act == 2:
                bosses[boss]["entries"] += 1
                bosses[boss]["clears"] += int(cleared)
                boss_choices["act2_boss/" + boss].update(r["headroom"].get("act2_boss", {}))
        for f in r["encounters"]:
            act = f["key"][0]
            if act >= 2:
                deaths[act, f["formation"]].append(f)
                late[act].append(f)
    h_total = hist.total()

    def quantile(p):
        count = 0
        for us, n in sorted(hist.items()):
            count += n
            if count >= ceil(p * h_total):
                return us / 1000

    def progression(rs):
        return dict(
            n=len(rs),
            mean_floor=mean(17 * (r["act"] - 1) + r["floor"] for r in rs),
            a1_clears=sum(r["a1_clear"] for r in rs),
            a2_clears=sum(r["a2_clear"] for r in rs),
            a2_boss_entries=sum(any(a == 2 for a, _ in r["boss_fights"]) for r in rs),
            a3_boss_entries=sum(any(a == 3 for a, _ in r["boss_fights"]) for r in rs),
            full_wins=sum(r["win"] for r in rs),
        )

    all_trade = totals(choices.values())
    choices["act2_hall_elite"] = totals(choices[k] for k in ("act2_monster", "act2_elite"))
    choices["all"] = all_trade
    choices.update(boss_choices)
    groups["act2"] = totals(groups[s] for s in ("act2_monster", "act2_elite", "act2_boss"))

    def frac(n, d):
        return round(100 * n / d, 3) if d else None

    headroom = {}
    for k, h in choices.items():
        headroom[k] = dict(
            counts=dict(h),
            pct_covered={
                s: frac(h[s], h["covered"]) for s in ("two_completed_roots", "trade5", "trade10")
            },
            pct_trade10={
                s: frac(h[s], h["trade10"])
                for s in (
                    "graph_t1",
                    "verified_table_t1",
                    "t1",
                    "t1_shift",
                    "t2_shape",
                    "t2_attack_switch",
                    "composition",
                    "attack_density",
                    "block_density",
                    "live_attack_density",
                    "live_block_density",
                    "power_location",
                    "reshuffle_possible",
                    "both_lines_reshuffle",
                    "pile",
                )
            },
        )
    entries = {}
    for key in ("act2_boss", "act3"):
        hp = [r["entry"][key] for r in rows if key in r["entry"]]
        entries[key] = dict(n=len(hp), mean_hp=mean(hp), median_hp=median(hp))
    return dict(
        lobbies=progression(rows),
        by_mode={
            mode: progression([r for r in rows if r["act_list"] == mode])
            for mode in ("default", "seeded")
        },
        bosses=bosses,
        entry=entries,
        native=native,
        no_comparable_steps=[r["seed"] for r in rows if not r["native"].get("match")],
        latency=dict(samples=h_total, p50_ms=quantile(0.5), p95_ms=quantile(0.95)),
        coverage={
            k: dict(
                eligible=h.total(),
                covered=h["covered"],
                pct=frac(h["covered"], h.total()),
                classes=categories(h),
                reasons=dict(h.most_common()),
            )
            for k, h in groups.items()
        },
        late_fatal_by_act={a: summarize_fights(fs) for a, fs in late.items()},
        encounters={
            a: {n: summarize_fights(fs) for (act, n), fs in deaths.items() if a == act}
            for a in late
        },
        headroom=headroom,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    args = p.parse_args()
    print(json.dumps(summarize(read_rows(args.source)), indent=2))
