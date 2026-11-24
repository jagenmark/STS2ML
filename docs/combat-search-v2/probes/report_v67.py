"""Validate, summarize and archive the complete CSV12DEV paired development run."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from math import ceil
from pathlib import Path
import re
import zipfile

from report_v64 import paired, summarize
from report_v66 import inventory
from sts2rl.combat_search_v2.silent_cards import BATCH2
from sts2rl.combat_search_v2.state import Variant
from sts2rl.combat_search_v2.transitions import card_supported
from sts2rl.unified_draft import catalog
from v64 import DOC
from v67 import ARMS, BASE, cohort

STEM = "v67-silent-pool-complete"
NOTES = {
    "EXPERTISE": "Draw 2/3 and retain the drawn copies this turn. A mixed hidden pile suspends before spending energy.",
    "MASTER_PLANNER": "After a Skill finishes playing, that combat copy gains permanent Sly, including before a replay.",
    "MIRAGE": "Modified Block from total Poison on living enemies. Only the base version Exhausts.",
    "SUPPRESS": "Innate. Deal 11/17 damage, then apply 3/5 Weak.",
    "UNTOUCHABLE": "Sly. Gain 6/9 modified Block on manual play or automatic discard play.",
    "WRAITH_FORM": "Gain 2/3 Intangible. The separate debuff applies negative Dexterity after player-side turn start.",
    "NIGHTMARE": "Witness the selected copy and create three before hand draw. Multiple instances, modified clones, overflow or competing generation can suspend.",
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def stats(rows):
    all_stats = summarize(rows)
    result = {k: all_stats[k] for k in ("n", "mean_floor", "a1_clears", "a2_entries", "a2_clears",
              "a3_entries", "wins", "bosses", "native", "p50_ms", "p95_ms", "latency_n")}
    result["a1_entries"] = sum(any(act == 1 for act, _ in r["boss_fights"]) for r in rows)
    result["matches_per_100"] = 100 * result["native"]["match"] / result["latency_n"]
    hist = Counter()
    for r in rows:
        hist.update({int(k): v for k, v in r["latency_us"].items()})
    cumulative = 0
    for us, n in sorted(hist.items()):
        cumulative += n
        if cumulative >= ceil(hist.total() * 0.99):
            result["p99_ms"] = us / 1000
            break
    return result


def pool_inventory(decompiled):
    rows = inventory(decompiled)
    for r in rows:
        if r["group"] == "Multiplayer":
            r.update(status="EXCLUDED_MULTIPLAYER")
        if r["card"] in NOTES:
            boundary = r["card"] in ("EXPERTISE", "NIGHTMARE")
            r.update(status="SUPPORTED_BOUNDARY" if boundary else "SUPPORTED_FULL", note=NOTES[r["card"]])
        r["root_admission"] = []
        for up, model in enumerate(catalog()[r["card"]]["variants"]):
            card = Variant(r["card"], model["card_type"], model["cost"], model["target_type"], up,
                           tuple(model["keywords"]), ("costs_x",) if model["costs_x"] else ())
            admitted = card_supported(card, silent_cards_v67=True)
            assert admitted == (r["group"] != "Multiplayer"), (card, r)
            r["root_admission"].append(admitted)
        assert len(r["root_admission"]) == 2
    assert Counter(r["group"] for r in rows) == {"Reward": 80, "Basic": 4, "Ancient": 2, "Multiplayer": 5}
    assert sum(r["status"].startswith("SUPPORTED_") for r in rows) == 86
    return rows


def report(result):
    totals = result["arms"]
    a, t, stress = (totals[arm] for arm in ARMS)
    pair = result["paired"]
    delta = t["matches_per_100"] - a["matches_per_100"]
    lines = [
        "# Silent A10 v6.7 · complete single-player card pool",
        "",
        f"All 86 single-player models in the pinned 91-card Silent pool pass root admission. On 384 paired "
        f"CSV12DEV lobbies, v6.7 A changed mean progression by {pair['delta']:+.3f} floors "
        f"(95% paired interval {pair['ci95'][0]:+.3f} to {pair['ci95'][1]:+.3f}). "
        f"Native matches per 100 combat decisions changed by {delta:+.2f}. "
        f"The v6.7 A and B runs recorded zero native mismatches.",
        "",
        "## Paired progression, coverage and latency",
        "",
        "| Metric | v6.5 A control | v6.7 A treatment | v6.7 B stress |",
        "|---|---:|---:|---:|",
    ]

    def row(label, fn):
        lines.append("| " + label + " | " + " | ".join(str(fn(x)) for x in (a, t, stress)) + " |")

    row("Lobbies", lambda x: x["n"])
    row("Mean global floor", lambda x: f"{x['mean_floor']:.3f}")
    for act in (1, 2):
        row(f"Act {act} boss clears / entries", lambda x: f"{x[f'a{act}_clears']} / {x[f'a{act}_entries']}")
    for boss in sorted(set().union(*(x["bosses"] for x in totals.values()))):
        row(boss + " clears / entries", lambda x: " / ".join(map(str, x["bosses"].get(boss, (0, 0)))))
    row("Act 3 boss entries", lambda x: x["a3_entries"])
    row("Full wins", lambda x: x["wins"])
    row("Combat decisions", lambda x: f"{x['latency_n']:,}")
    row("Native matches / mismatches / unresolved", lambda x: " / ".join(f"{x['native'][k]:,}"
        for k in ("match", "mismatch", "unresolved")))
    row("Native matches per 100 combat decisions", lambda x: f"{x['matches_per_100']:.2f}")
    row("Latency p50 / p95 / p99 (ms)", lambda x: " / ".join(f"{x[k]:.2f}" for k in ("p50_ms", "p95_ms", "p99_ms")))
    for mode in ("default", "seeded"):
        row(mode.title() + " mean floor", lambda x: f"{x['modes'][mode]['mean_floor']:.3f}")
        row(mode.title() + " matches / 100 decisions", lambda x: f"{x['modes'][mode]['matches_per_100']:.2f}")
    lines += ["", f"Arm A finished higher on {pair['w']} pairs, lower on {pair['l']}, and tied on {pair['t']}. "
              "Global floor is 17 × (act − 1) + floor. The confidence interval uses 50,000 mode-stratified "
              "paired bootstrap samples. Each A arm ran the same 192 default and 192 seeded lobbies. "
              "B used the first 32 pairs of modes, for 64 lobbies. Arm order rotated within lobby. "
              "The cohort used 12 workers and one OpenBLAS and OpenMP thread per worker.",
              "", f"The frozen control recorded {a['native']['mismatch']} native mismatches. The first v6.7 "
              "implementation also advanced a melted Kunai in CSV12DEV_DEFAULT_0127. Toy Box melts the "
              "first remaining wax relic every third combat. The host keeps its physical counter visible while "
              "CombatState omits the relic from combat hooks. The corrected projection preserves the displayed "
              "relic for comparison and excludes its hooks after a witnessed melt. A permanent fixture replays "
              "all 12 originally failing treatment commands, including the Louse Progenitor and Insatiable "
              "encounters. The table uses a fresh complete run with the corrected production oracle."]
    prior = json.loads((DOC / "v66-silent-cards-batch1.json").read_bytes())["totals"]["arm1"]
    lines += ["", f"Treatment p95 was {t['p95_ms']:.2f} ms versus {a['p95_ms']:.2f} ms on the same lobbies. "
              f"The earlier v6.6 A run measured {prior['p95_ms']:.2f} ms on CSV11DEV. "
              "Expertise checks pile homogeneity at most three times per play. Master Planner scans the pending "
              "play queue when a Skill first gains Sly. Mirage sums living enemy stacks once, and Nightmare creates "
              "a fixed three copies."]
    if scaling := result["qualification"].get("scaling"):
        times = scaling["pile_sizes"]
        lines += ["", "In a fixed-root timing check, increasing the draw pile from 32 to 512 cards changed "
                  f"median Expertise transition time from {times['32']['expertise']:.1f} to "
                  f"{times['512']['expertise']:.1f} µs. Master Planner setup scoring changed from "
                  f"{times['32']['planner_value']:.1f} to {times['512']['planner_value']:.1f} µs. "
                  "Each median uses seven batches of 256 calls."]
    if pair["ci95"][0] <= 0 <= pair["ci95"][1]:
        lines += ["", "The paired floor interval spans zero, so this cohort does not establish a progression gain."]
    lines += ["", "## Card evidence in the two v6.7 arms", "",
              "Counts are physical plays / directly matched play transitions. An automatic Sly play can occur within "
              "another command. Pinned scenarios exercise each base and upgraded form independently of cohort acquisition.",
              "", "| Card | v6.7 A | v6.7 B |", "|---|---:|---:|"]
    for name in sorted(NOTES):
        cells = [result["cards"][arm][name] for arm in ("treatment", "stress")]
        lines.append(f"| {name} | " + " | ".join(f"{c['plays']} / {c['match']}" for c in cells) + " |")
    q = result["qualification"]
    lines += ["", "## Rules and qualification", "",
              "Set `silent_cards_v67` to true to enable Batch 2 and the v6.6 rules. The flag defaults to false. "
              "Arm A uses the v6.5 trap-cleanup acquisition profile. Arm B uses the v6.5 unified draft profile.",
              "", "The native host grants Master Planner’s keyword after a Skill, before a replay. A second copy of the power "
              "increments the observable stack counter and the Skill still gains one keyword. Expertise’s temporary "
              "Retain follows the physical card into discard and clears during end-turn cleanup. Mirage counts each living "
              "enemy before the ordinary Dexterity and Frail modifiers. Suppress resolves its hit and Envenom before Weak.",
              "", "Wraith Form applies Intangible first. Player Artifact can consume the debuff at play time. "
              "Artifact acquired afterward can block a subsequent Dexterity loss. Intangible caps individual damage "
              "instances at one and decrements after the enemy side ends. The start-turn loss waits for a pending "
              "Tools of the Trade or Toasty Mittens choice. The Artifact fixture applies the native scenario power then "
              "plays through the pinned RunSimulator. The benchmark uses the original headless process.",
              "", "Nightmare snapshots the selected hand copy and creates three copies before hand draw. The public power "
              "exposes its count but omits the card identity. A witnessed ordinary choice certifies enemy resolution, the "
              "generated hand positions and pile conservation at the next draw. An unwitnessed or unsupported clone "
              "uses a named boundary. Pocketwatch resets its counter before hand draw, then refreshes its status after "
              "Toasty Mittens. The native regression crosses the fourth play and checks both sides of the prompt.",
              "", "The Master Planner heuristic values available discard effects and eligible Skills over the remaining "
              "fight horizon. Wraith Form values protected turns and charges for future Dexterity loss. These values "
              "affect search ranking. The differential tests compare physical game outcomes.",
              "", f"Helmer ran CPU Python on rules commit `{result['manifest']['commit']}`. "
              f"Pytest reported **{q['pytest']}**. Ruff reported **{q['ruff']}**. "
              f"All {len(q['profiles'])} historical builder profiles reproduced their output bytes, all ten frozen "
              "challenger files matched efd9877, and all 120 CSV2DEV receipts matched their archived bytes. "
              f"Both v6.6 CSV11DEV arms reproduced all {len(q['v66_replays'])} deterministic episode records "
              "with v6.7 disabled, including command hashes, card counts and native verdicts. Wall-clock timings "
              "were excluded from the v6.6 replay comparison.",
              "", f"Pinned host SHA-256 `{result['manifest']['host']}`. Game SHA-256 `{result['manifest']['game']}`. "
              "The receipt archive contains the manifest, per-lobby results and latency histograms, source fingerprints, "
              "compatibility receipts and qualification logs.",
              "", "## Pinned Silent inventory", "",
              "The 86 solo cards comprise 80 rewards, four basics and two Ancient cards. SUPPORTED_BOUNDARY admits "
              "the card at the root and can suspend on a hidden draw, selection, history or other named condition. "
              "Common encounter and relic boundaries apply throughout. The five multiplayer-only models are excluded.",
              "", "| Card | Pool | Status | Rule or conditional boundary |", "|---|---|---|---|"]
    for r in result["inventory"]:
        lines.append(f"| {r['card']} | {r['group']} | {r['status']} | {r['note'] or '—'} |")
    return "\n".join(lines) + "\n"


def main(run, qualification, decompiled):
    manifest = json.loads((run / "manifest.json").read_bytes())
    rows = cohort()
    assert manifest["base"] == BASE and manifest["cohort"] == [list(t) for t in rows]
    assert manifest["stress"] == manifest["cohort"][:64] and len(set(r[1] for r in rows)) == 384
    records, arms, cards = {}, {}, {}
    for arm in ARMS:
        expected = rows[:64] if arm == "stress" else rows
        records[arm] = [json.loads(gzip.decompress((run / arm / (seed + ".json.gz")).read_bytes()))
                        for _, seed, mode in expected]
        assert all((r["seed"], r["act_list"]) == (seed, mode) for r, (_, seed, mode) in
                   zip(records[arm], expected, strict=True))
        arms[arm] = stats(records[arm])
        assert arm == "control" or arms[arm]["native"]["mismatch"] == 0
        arms[arm]["modes"] = {mode: stats([r for r in records[arm] if r["act_list"] == mode])
                              for mode in ("default", "seeded")}
        cards[arm] = {}
        for name in sorted(BATCH2 | {"NIGHTMARE"}):
            verdicts = Counter()
            for r in records[arm]:
                verdicts.update(r["card_oracle_counts"].get(name, {}))
            cards[arm][name] = dict(plays=sum(r["played"].get(name, 0) for r in records[arm]),
                                    **{k: verdicts[k] for k in ("match", "mismatch", "unresolved")})
    q = json.loads((qualification / "compatibility.json").read_bytes())
    if (qualification / "scaling.json").is_file():
        q["scaling"] = json.loads((qualification / "scaling.json").read_bytes())
    q["pytest"] = (qualification / "pytest.log").read_text().strip().splitlines()[-1]
    q["ruff"] = (qualification / "ruff.log").read_text().strip()
    assert re.fullmatch(r"\d+ passed in .+", q["pytest"]) and q["ruff"] == "All checks passed!"
    pool = pool_inventory(decompiled)
    groups = {"Cards": [r["model"] for r in pool if r["card"] in NOTES],
              "Powers": ["NightmarePower", "MasterPlannerPower", "WraithFormPower", "IntangiblePower",
                         "ArtifactPower", "DexterityPower", "EnvenomPower", "AfterimagePower"],
              "Relics": ["Pocketwatch", "ToastyMittens", "Kunai", "ToyBox"], "CardPools": ["SilentCardPool"]}
    fingerprints = {group + "/" + name: digest((decompiled / ("MegaCrit.Sts2.Core.Models." + group) /
                    (name + ".cs")).read_bytes()) for group, names in groups.items() for name in names}
    for group, name in [("Combat", "CombatState"), ("Combat", "CombatManager"),
                        ("Commands", "CardPileCmd"), ("Commands", "PowerCmd"), ("Models", "CardModel")]:
        fingerprints[group + "/" + name] = digest((decompiled / ("MegaCrit.Sts2.Core." + group) /
                                                   (name + ".cs")).read_bytes())
    result = dict(manifest=manifest, arms=arms, paired=paired(records["control"], records["treatment"]),
                  stress_paired_subset=paired(records["control"][:64], records["stress"]),
                  cards=cards, inventory=pool, qualification=q, decompiled_models=fingerprints)
    (DOC / (STEM + ".json")).write_text(json.dumps(result, indent=2) + "\n", newline="\n")
    (DOC / (STEM + "-report.md")).write_text(report(result), encoding="utf-8", newline="\n")
    with zipfile.ZipFile(DOC / (STEM + "-receipts.zip"), "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(run / "manifest.json", "manifest.json")
        archive.writestr("decompiled-models.json", json.dumps(fingerprints, indent=2))
        for arm in ARMS:
            raw = b"".join(json.dumps(r, separators=(",", ":")).encode() + b"\n" for r in records[arm])
            archive.writestr(arm + ".jsonl.gz", gzip.compress(raw, mtime=0))
        for path in sorted(qualification.iterdir()):
            if path.is_file():
                archive.write(path, "qualification/" + path.name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("run", "qualification", "decompiled"):
        parser.add_argument(key, type=Path)
    args = parser.parse_args()
    main(args.run, args.qualification, args.decompiled)
