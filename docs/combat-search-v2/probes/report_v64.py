"""Analyze the compact three-arm CSV9DEV archive, with seed-paired inference."""

import argparse
from collections import Counter, defaultdict
import gzip
import json
from math import ceil, comb
from pathlib import Path
from statistics import mean
import zipfile

import numpy as np

from sts2rl.unified_draft import FORCE_SKIP, catalog
from v64 import ARMS, cohort

CARDS = """GRAND_FINALE BURY NEUROSURGE FRIENDSHIP REAP BLOODLETTING SKEWER BUBBLE_BUBBLE
AFTERIMAGE WELL_LAID_PLANS TOOLS_OF_THE_TRADE CALCULATED_GAMBLE EXPOSE PIERCING_WAIL BLUR
DODGE_AND_ROLL FOOTWORK BACKFLIP ACCELERANT BOUNCING_FLASK CORROSIVE_WAVE PACTS_END ACROBATICS PREDATOR""".split()


def global_floor(r):
    return 17 * (r["act"] - 1) + r["floor"]


def paired(control, arm):
    delta = {mode: [] for mode in ("default", "seeded")}
    for c, r in zip(control, arm, strict=True):
        assert c["seed"] == r["seed"] and c["act_list"] == r["act_list"]
        delta[r["act_list"]].append(global_floor(r) - global_floor(c))
    diffs = sum(delta.values(), [])
    wins, losses = sum(d > 0 for d in diffs), sum(d < 0 for d in diffs)
    rng = np.random.default_rng(621)
    boot = np.zeros(50000)
    for values in delta.values():
        for i in range(0, len(boot), 500):
            boot[i : i + 500] += rng.choice(values, (500, len(values))).sum(axis=1)
    return dict(
        delta=mean(diffs),
        ci95=np.quantile(boot / len(diffs), [0.025, 0.975]).tolist(),
        w=wins,
        l=losses,
        t=len(diffs) - wins - losses,
        sign_p=min(
            1,
            2
            * sum(comb(wins + losses, k) for k in range(min(wins, losses) + 1))
            / (1 << (wins + losses)),
        ),
    )


def summarize(rows):
    native, hist, boss_entries, boss_clears = Counter(), Counter(), Counter(), Counter()
    offered, picked = defaultdict(Counter), defaultdict(Counter)
    skips, optional, decisions, deck = Counter(), Counter(), Counter(), defaultdict(list)
    force_mandatory = Counter()
    for r in rows:
        assert r["status"] == "complete" and not r["error"] and not r["abandoned"]
        native.update(r["native"])
        assert len(r["mismatches"]) == r["native"].get("mismatch", 0)
        hist.update({int(k): v for k, v in r["latency_us"].items()})
        for act, _, room, formation, _, cleared in r["late_fights"]:
            if act == 2 and room == "Boss":
                boss_entries[formation] += 1
                boss_clears[formation] += cleared
        for act, n in r["deck_size"].items():
            deck[act].append(n)
        shops = set()
        for act, floor, kind, cards, action, args, legal_skip in r["offers"]:
            decisions[kind] += 1
            if kind == "card_reward":
                optional[act] += legal_skip
                skips[act] += action == "skip_card_reward"
                offered[kind].update(c[0] for c in cards)
                if action == "select_card_reward":
                    name = next(c[0] for c in cards if c[2] == args["card_index"])
                    picked[kind][name] += 1
                    if not legal_skip:
                        force_mandatory[name] += 1
            elif kind == "bundle_select":
                offered[kind].update(c[0] for b in cards for c in b)
                picked[kind].update(c[0] for c in cards[args["bundle_index"]])
                force_mandatory.update(c[0] for c in cards[args["bundle_index"]])
            else:
                for name, up, slot, price in cards:
                    key = (act, floor, slot, name, up)
                    if key not in shops:
                        offered[kind][name] += 1
                        shops.add(key)
                    if action == "buy_card" and args["card_index"] == slot:
                        picked[kind][name] += 1

    def quantile(q):
        target = ceil(hist.total() * q)
        acc = 0
        for t, v in sorted(hist.items()):
            acc += v
            if acc >= target:
                return t / 1000

    offered["all"] = sum(offered.values(), Counter())
    picked["all"] = sum(picked.values(), Counter())
    hard_skips = FORCE_SKIP | {
        name
        for name, card in catalog().items()
        if any(
            v["multiplayer_only"] or v["stars_x"] or v["star_cost"] > 0 for v in card["variants"]
        )
    }
    hard_offered = sum(offered["all"][name] for name in hard_skips)
    hard_picked = sum(picked["all"][name] for name in hard_skips)
    hard_mandatory = sum(force_mandatory[name] for name in hard_skips)
    return dict(
        hard_skip_audit=dict(
            offered=hard_offered,
            picked=hard_picked,
            forced=hard_mandatory,
            voluntary=hard_picked - hard_mandatory,
        ),
        n=len(rows),
        mean_floor=mean(global_floor(r) for r in rows),
        a1_clears=sum(r["a1_clear"] for r in rows),
        a2_entries=sum(any(act == 2 for act, _ in r["boss_fights"]) for r in rows),
        a2_clears=sum(r["a2_clear"] for r in rows),
        a3_entries=sum(any(act == 3 for act, _ in r["boss_fights"]) for r in rows),
        wins=sum(r["win"] for r in rows),
        bosses={k: [boss_clears[k], boss_entries[k]] for k in boss_entries},
        native={k: native[k] for k in ("match", "mismatch", "unresolved")},
        p50_ms=quantile(0.5),
        p95_ms=quantile(0.95),
        latency_n=hist.total(),
        deck_size={a: dict(mean=mean(vals), n=len(vals)) for a, vals in deck.items()},
        reward_skip={a: dict(skips=skips[a], optional=optional[a]) for a in optional},
        prompts=dict(decisions),
        mandatory_picks=dict(force_mandatory),
        cards={
            k: {
                n: dict(picked=picked[k][n], offered=offered[k][n])
                for n in set(offered[k]) | set(CARDS)
            }
            for k in offered
        },
    )


def analyze(path):
    starts = [s for _, s, _ in cohort()]
    with zipfile.ZipFile(path) as z:
        rows = {
            arm: list(map(json.loads, gzip.decompress(z.read(arm + ".jsonl.gz")).splitlines()))
            for arm in ARMS
        }
        manifest = json.loads(z.read("manifest.json"))

        def receipt(name):
            return json.loads(z.read("qualification/" + name + ".json"))

        fan = receipt("fan-proof")
        baseline = receipt("baseline-proof")
        qualification = dict(
            cohort=receipt("cohort-proof"),
            catalog=receipt("catalog-proof"),
            reproduced_fan=fan["reproduced"],
            fixed_fan=fan["fixed"],
            frozen_files=len(baseline["frozen_files"]),
            prior_profiles=len(baseline) - 2,
            historical_csv2dev=baseline["compat"],
            offclass_replay=receipt("offclass-proof"),
            explicit_frozen_starts={
                arm: len(receipt(arm + "-reference")) for arm in ("v5", "kaiser")
            },
            pytest=z.read("qualification/tests.log").decode("utf8").strip().splitlines()[-1],
        )
        for arm in ("v5", "kaiser"):
            assert receipt(arm + "-reference") == receipt(arm + "-candidate")
    assert all([r["seed"] for r in rs] == starts for rs in rows.values())
    return dict(
        manifest=manifest,
        qualification=qualification,
        arms={k: summarize(rs) for k, rs in rows.items()},
        paired={k: paired(rows[ARMS[0]], rows[k]) for k in ARMS[1:]},
        b_vs_a=paired(rows[ARMS[1]], rows[ARMS[2]]),
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    a.output.write_text(
        json.dumps(analyze(a.archive), indent=2, sort_keys=True) + "\n", encoding="utf8"
    )
