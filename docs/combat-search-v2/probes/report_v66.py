"""Package and analyze the pinned CSV11DEV cohort and the decompiled Silent card pool."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re
import zipfile

from report_v64 import paired, summarize
from sts2rl.combat_search_v2.silent_cards import PROMOTED, WAVE
from v64 import DOC
from v66 import ARMS, cohort

REMAINING = {
    "BLADE_SYMPHONY": "Multiplayer. Create two Shivs for each living player teammate. Upgrade reduces cost from 2 to 1.",
    "CONCOCT": "Multiplayer. Give an ally 3/4 Concoct. Its unblocked powered hits apply that much Poison until the end of the opposing side’s turn.",
    "EXPERTISE": "Draw 2/3 cards and give each drawn card Retain for this turn.",
    "FADE": "Multiplayer. Retain. Give an ally 6/9 temporary Dexterity until the end of its side’s turn.",
    "FLANKING": "Multiplayer. Other attackers’ powered hits on the target deal double damage until the end of its side’s turn. Upgrade reduces cost from 2 to 1.",
    "MASTER_PLANNER": "After the owner plays a Skill, permanently give that combat copy Sly. Upgrade reduces cost from 2 to 1.",
    "MIRAGE": "Gain modified Block with base equal to total Poison on living enemies. Exhaust. Upgrade removes Exhaust.",
    "SNEAKY": "Multiplayer. Sly. Gain 1/2 unpowered Block each time another player finishes playing an Attack.",
    "SUPPRESS": "Ancient. Innate. Deal 11/17 damage and apply 3/5 Weak to one enemy for zero energy.",
    "UNTOUCHABLE": "Sly. Gain 6/9 modified Block for two energy.",
    "WRAITH_FORM": "Ancient. Gain 2/3 Intangible and a debuff that removes one Dexterity at each subsequent player-side turn start.",
}
BOUNDARIES = {
    **dict.fromkeys("ACROBATICS ADRENALINE BACKFLIP CALCULATED_GAMBLE DAGGER_THROW PREPARED REFLEX".split(),
                    "Hidden mid-turn draw."),
    "BLADE_OF_INK": "Existing Phantom Blades first-Shiv history can require a witness when playing the generated Shiv.",
    "BOUNCING_FLASK": "Multiple living targets.",
    "BURST": "A repeated Skill can suspend on a draw or selection.",
    "CORROSIVE_WAVE": "Poison after extra draws. A mixed hidden draw suspends the play.",
    "DAGGER_SPRAY": "Multi-hit Curl Up ordering.",
    "ESCAPE_PLAN": "Known Skill draw gains Block. A mixed hidden draw suspends before reveal.",
    "FINISHER": "Use the public calculated hit count, otherwise suspend on unwitnessed attack history.",
    "FLECHETTES": "Multi-hit Curl Up ordering.",
    "HIDDEN_DAGGERS": "Discard selection may auto-play Sly cards with multiple targets.",
    "KNIFE_TRAP": "Replays exhausted Shivs. Mixed exhaust order or a dead replay target can suspend.",
    "MEMENTO_MORI": "Infer discarded-card count from an unambiguous public preview.",
    "MURDER": "Infer combat draw count from an unambiguous public preview.",
    "NIGHTMARE": "Root-admitted legacy play boundary. Batch 2 can model choosing a hand card and creating three copies next turn.",
    "OUTBREAK": "Poison tick can wake an enemy whose new move is hidden.",
    "PHANTOM_BLADES": "Retain applies to existing and future Shivs. First-Shiv bonus needs a witness.",
    "POUNCE": "The final Free Skill stack can conceal the underlying costs of other hand cards.",
    "RICOCHET": "One living target resolves all 4/5 hits. Multiple targets require native RNG.",
    "SERPENT_FORM": "After a subsequent card, deal 4/6 damage to one random enemy. A sole target resolves locally.",
    "SHADOW_STEP": "All-hand discard can auto-play Sly cards with hidden targets.",
    "SKEWER": "Multi-hit Curl Up ordering.",
    "SPEEDSTER": "Extra draws hit each enemy. A mixed hidden draw suspends the play.",
    "STORM_OF_STEEL": "All-hand discard can auto-play Sly cards before Shiv creation.",
    "SURVIVOR": "Discarded Sly attack can require a random target.",
    "THE_HUNT": "A fatal hit can require special monster death eligibility.",
    "TOOLS_OF_THE_TRADE": "Ordinary end turn certifies at next-hand reveal. Interacting start-turn prompts can suspend.",
}


def inventory(decompiled):
    folder = "MegaCrit.Sts2.Core.Models"
    pool = (decompiled / (folder + ".CardPools") / "SilentCardPool.cs").read_text()
    names = re.findall(r"ModelDb\.Card<(\w+)>\(", pool)
    assert len(names) == len(set(names)) == 91
    result = []
    for name in names:
        card = re.sub(r"(?<!^)(?=[A-Z])", "_", name).upper()
        model = (decompiled / (folder + ".Cards") / (name + ".cs")).read_bytes()
        rarity = re.search(rb"CardRarity\.(\w+)", model)[1].decode()
        group = "Multiplayer" if b"MultiplayerOnly" in model else rarity if rarity in ("Basic", "Ancient") else "Reward"
        status = "REMAINING_BATCH2" if card in REMAINING else "SUPPORTED_BOUNDARY" if card in BOUNDARIES else "SUPPORTED_FULL"
        result.append(dict(card=card, group=group, rarity=rarity, status=status, model=name,
                           model_sha256=hashlib.sha256(model).hexdigest(), note=REMAINING.get(card, BOUNDARIES.get(card, ""))))
    assert sum(r["group"] == "Reward" for r in result) == 80
    return sorted(result, key=lambda r: r["card"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("run", "decompiled", "qualification"):
        parser.add_argument(arg, type=Path)
    args = parser.parse_args()
    base = "v66-silent-cards-batch1"
    manifest = json.loads((args.run / "manifest.json").read_bytes())
    assert manifest["cohort"] == [list(t) for t in cohort()]
    records, totals, counts = {}, {}, {}
    for arm in ARMS:
        rows = [json.loads(gzip.decompress((args.run / arm / (seed + ".json.gz")).read_bytes()))
                for _, seed, _ in cohort()]
        assert all(r["seed"] == seed and r["act_list"] == mode for r, (_, seed, mode) in zip(rows, cohort(), strict=True))
        assert arm == "control" or not any(r["mismatches"] for r in rows)
        records[arm] = rows
        details = summarize(rows)
        totals[arm] = {k: details[k] for k in ("n", "mean_floor", "a1_clears", "a2_entries", "a2_clears",
                       "a3_entries", "wins", "bosses", "native", "p50_ms", "p95_ms", "latency_n")}
        totals[arm]["matches_per_100"] = 100 * details["native"]["match"] / details["latency_n"]
        counts[arm] = {}
        for name in sorted(PROMOTED | WAVE | {"TOOLS_OF_THE_TRADE", "WELL_LAID_PLANS"}):
            verdicts = Counter()
            for r in rows:
                verdicts.update(r["card_oracle_counts"].get(name, {}))
            counts[arm][name] = {
                "played": sum(r["played"].get(name, 0) for r in rows),
                "match": verdicts["match"], "unresolved": verdicts["unresolved"], "mismatch": verdicts["mismatch"],
                "bodies": sum(r["matched_card_bodies"].get(name, 0) for r in rows),
                "hits": sum(r["matched_attack_hits"].get(name, 0) for r in rows),
            }
    comparisons = {arm: paired(records["control"], records[arm]) for arm in ARMS[1:]}
    comparisons["arm2_minus_arm1"] = paired(records["arm1"], records["arm2"])
    pool = inventory(args.decompiled)
    qualification = json.loads((args.qualification / "qualification.json").read_bytes())
    assert len(qualification["profiles"]) == 19 and len(qualification["frozen"]) == 10
    assert all(r["exact"] for r in qualification["compat"].values())
    result = dict(manifest=manifest, totals=totals, paired=comparisons, per_card=counts,
                  inventory=pool, qualification=qualification)
    (DOC / (base + ".json")).write_text(json.dumps(result, indent=2) + "\n", newline="\n")
    with zipfile.ZipFile(DOC / (base + "-receipts.zip"), "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(args.run / "manifest.json", "manifest.json")
        for arm, rows in records.items():
            data = b"\n".join(json.dumps(row, separators=(",", ":")).encode() for row in rows) + b"\n"
            archive.writestr(arm + ".jsonl.gz", gzip.compress(data, mtime=0))
        for path in sorted(args.qualification.iterdir()):
            if path.is_file():
                archive.write(path, "qualification/" + path.name)
    report(result, DOC / (base + "-report.md"))


def report(data, path):
    totals, paired = data["totals"], data["paired"]
    a, b = paired["arm1"], paired["arm2"]
    lines = [
        "# Silent A10 v6.6 Batch 1", "",
        f"On 192 paired CSV11DEV lobbies, adding the Silent rules to v6.5 Arm A changed mean progression by "
        f"{a['delta']:+.2f} floors (95% paired interval {a['ci95'][0]:+.2f} to {a['ci95'][1]:+.2f}). "
        f"Arm B with the same rules finished {b['delta']:+.2f} floors relative to the v6.5 Arm A control. "
        "Both v6.6 arms recorded zero native mismatches.", "",
        "## Paired development results", "",
        "| Metric | Control · v6.5 A | Arm 1 · v6.6 A | Arm 2 · v6.6 B |",
        "|---|---:|---:|---:|",
    ]
    def row(label, fn):
        lines.append("| " + " | ".join([label, *(str(fn(totals[arm])) for arm in ARMS)]) + " |")
    row("Starts", lambda r: r["n"])
    row("Mean global floor", lambda r: f"{r['mean_floor']:.3f}")
    row("Act 1 clears", lambda r: r["a1_clears"])
    row("Act 2 boss clears / entries", lambda r: f"{r['a2_clears']} / {r['a2_entries']}")
    for boss in sorted(set().union(*(r["bosses"] for r in totals.values()))):
        row(boss + " clears / entries", lambda r: " / ".join(map(str, r["bosses"].get(boss, (0, 0)))))
    row("Act 3 boss entries", lambda r: r["a3_entries"])
    row("Full wins", lambda r: r["wins"])
    row("Combat decisions", lambda r: f"{r['latency_n']:,}")
    row("Native match / mismatch / unresolved", lambda r: " / ".join(f"{r['native'][k]:,}" for k in ("match", "mismatch", "unresolved")))
    row("Native matches per 100 combat decisions", lambda r: f"{r['matches_per_100']:.2f}")
    row("Latency p50 / p95 (ms)", lambda r: f"{r['p50_ms']:.3f} / {r['p95_ms']:.3f}")
    lines.extend(["", "Each arm played 96 default and 96 seeded lobbies. The run used 12 workers, rotating arm order, "
                  "and one OpenBLAS and OpenMP thread per worker. Global floor is 17 × (act − 1) + floor. "
                  "The intervals use 50,000 mode-stratified paired bootstrap samples.", "",
                  "| Comparison | Mean floor difference | 95% interval | Floor wins / losses / ties |",
                  "|---|---:|---:|---:|"])
    for key, label in (("arm1", "Arm 1 vs Control"), ("arm2", "Arm 2 vs Control"), ("arm2_minus_arm1", "Arm 2 vs Arm 1")):
        r = paired[key]
        lines.append(f"| {label} | {r['delta']:+.3f} | {r['ci95'][0]:+.3f} to {r['ci95'][1]:+.3f} | {r['w']} / {r['l']} / {r['t']} |")
    lines.extend(["", f"Historical v6.5 Arm B recorded 57.95 native matches per 100 decisions and a −2.45 floor gap "
                  f"against its CSV10DEV control. CSV11DEV Arm 2 changed those figures by "
                  f"{totals['arm2']['matches_per_100'] - 57.95:+.2f} matches per 100 and {b['delta'] + 2.45:+.2f} floors. "
                  "The historical comparison uses different seeds and controls. The paired comparison above measures the "
                  "effect of enabling v6.6 for Arm A. There is no v6.5 B arm on these same seeds.", "",
                  "## Per-card triggers and hits", "",
                  "Each cell gives physical plays / native-matched card executions / attack hits in those executions. "
                  "Executions include replays and automatic plays. Hits count individual living targets struck, including blocked hits. "
                  "The JSON also distinguishes per-play native matches, unresolved transitions and mismatches. Zero can mean a card was never acquired.", "",
                  "| Card | Control | Arm 1 | Arm 2 |", "|---|---:|---:|---:|"])
    for name in sorted(data["per_card"]["control"]):
        values = []
        for arm in ARMS:
            c = data["per_card"][arm][name]
            values.append(f"{c['played']} / {c['bodies']} / {c['hits']}")
        lines.append("| " + " | ".join([name, *values]) + " |")
    lines.extend(["", "## Pinned Silent pool and Batch 2", "",
                  "The pinned SilentCardPool.GenerateAllCards() returns 91 distinct models. The ordinary single-player reward pool "
                  "has 80 cards. The other entries are four basics, two Ancient cards and five multiplayer-only cards. "
                  "Exterminate is a separately qualified event card. Shiv is a generated token.", "",
                  "SUPPORTED_FULL records deterministic card mechanics in the qualified kernel. Shared encounter, enchantment and "
                  "relic boundaries still apply. SUPPORTED_BOUNDARY records root admission with a named conditional or legacy play boundary. "
                  "REMAINING_BATCH2 lists every missing model, including multiplayer-only models outside single-player A10.", "",
                  "| Card | Pool | Status | Boundary or remaining native mechanic |", "|---|---|---|---|"])
    for r in data["inventory"]:
        lines.append(f"| {r['card']} | {r['group']} | {r['status']} | {r['note'] or '—'} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
