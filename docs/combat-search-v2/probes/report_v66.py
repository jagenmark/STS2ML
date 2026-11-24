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


def model_hashes(root):
    cards = PROMOTED | WAVE | {"TOOLS_OF_THE_TRADE", "WELL_LAID_PLANS", "I_AM_INVINCIBLE", "SHIV"}
    powers = """Accuracy BlockNextTurn CorrosiveWave DoubleDamage Envenom FreeSkill InfiniteBlades NoDraw
                PhantomBlades PiercingWail RetainHand SerpentForm Shadowmeld ShadowStep Speedster Strangle
                TheHunt Thorns ToolsOfTheTrade Tracking WellLaidPlans Weak Vulnerable Artifact Dexterity Strength""".split()
    models = {
        "CardPools": ["SilentCardPool"],
        "Cards": ["".join(w.title() for w in name.split("_")) for name in sorted(cards)],
        "Powers": [name + "Power" for name in powers],
        "Enchantments": ["Inky"],
    }
    return {f"{group}/{name}": hashlib.sha256(
        (root / ("MegaCrit.Sts2.Core.Models." + group) / (name + ".cs")).read_bytes()).hexdigest()
        for group, names in models.items() for name in names}


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
        totals[arm]["a1_entries"] = sum(any(act == 1 for act, _ in r["boss_fights"]) for r in rows)
        totals[arm]["modes"] = {}
        for mode in ("default", "seeded"):
            subset = summarize([r for r in rows if r["act_list"] == mode])
            totals[arm]["modes"][mode] = dict(starts=subset["n"], mean_floor=subset["mean_floor"],
                matches_per_100=100 * subset["native"]["match"] / subset["latency_n"])
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
    qualification["decompiled_model_hashes"] = model_hashes(args.decompiled)
    qualification["tests"] = (args.qualification / "pytest.log").read_text(encoding="utf-8").strip().splitlines()[-1]
    qualification["ruff"] = (args.qualification / "ruff.log").read_text(encoding="utf-8").strip()
    qualification["base_control_transcripts"] = len(json.loads((args.qualification / "control-replay.json").read_bytes()))
    assert qualification["base_control_transcripts"] == len(cohort())
    assert re.fullmatch(r"\d+ passed in .+", qualification["tests"])
    assert qualification["ruff"] == "All checks passed!"
    quality = Counter()
    pocketwatch = []
    for row in records["control"]:
        quality.update(row["independent_native"])
        pocketwatch.extend([row["seed"], *check] for check in row["pocketwatch_checks"])
    assert quality["mismatch"] == 0
    qualification.update(control_independent_native=quality, control_pocketwatch=pocketwatch)
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
        f"Arm A gained {totals['arm1']['matches_per_100'] - totals['control']['matches_per_100']:.2f} native matches "
        f"per 100 combat decisions. Its floor interval spans zero. Arm B's floor interval was "
        f"{b['ci95'][0]:+.2f} to {b['ci95'][1]:+.2f}. Its Act 2 boss clears fell from "
        f"{totals['control']['a2_clears']} in control to {totals['arm2']['a2_clears']}. "
        f"The p95 combat decision took {totals['arm1']['p95_ms']:.1f} ms in Arm 1 and {totals['arm2']['p95_ms']:.1f} ms "
        f"in Arm 2, compared with {totals['control']['p95_ms']:.1f} ms in control.", "",
        "## Paired development results", "",
        "| Metric | Control · v6.5 A | Arm 1 · v6.6 A | Arm 2 · v6.6 B |",
        "|---|---:|---:|---:|",
    ]
    def row(label, fn):
        lines.append("| " + " | ".join([label, *(str(fn(totals[arm])) for arm in ARMS)]) + " |")
    row("Starts", lambda r: r["n"])
    row("Mean global floor", lambda r: f"{r['mean_floor']:.3f}")
    row("Act 1 boss clears / entries", lambda r: f"{r['a1_clears']} / {r['a1_entries']}")
    row("Act 2 boss clears / entries", lambda r: f"{r['a2_clears']} / {r['a2_entries']}")
    for boss in sorted(set().union(*(r["bosses"] for r in totals.values()))):
        row(boss + " clears / entries", lambda r: " / ".join(map(str, r["bosses"].get(boss, (0, 0)))))
    row("Act 3 boss entries", lambda r: r["a3_entries"])
    row("Full wins", lambda r: r["wins"])
    for mode in ("default", "seeded"):
        row(mode.capitalize() + " mean floor", lambda r: f"{r['modes'][mode]['mean_floor']:.3f}")
        row(mode.capitalize() + " native matches per 100", lambda r: f"{r['modes'][mode]['matches_per_100']:.2f}")
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
    q = data["qualification"]
    fix = q["control_independent_native"]
    lines.extend(["", f"The frozen v6.5 control recorded {totals['control']['native']['mismatch']} mismatch on its own oracle. "
                  "Pocketwatch resets its counter before hand draw and refreshes its status after the Toasty Mittens prompt. "
                  f"The independent control audit applies that ordering to the same physical actions and compared "
                  f"{fix['match']:,} matches, {fix.get('mismatch', 0)} mismatches and {fix['unresolved']:,} unresolved transitions. "
                  "The two v6.6 arms use their production oracle for every verdict in the table."])
    lines.extend(["", f"Historical v6.5 Arm B recorded 57.95 native matches per 100 decisions and a −2.45 floor gap "
                  f"against its CSV10DEV control. CSV11DEV Arm 2 changed those figures by "
                  f"{totals['arm2']['matches_per_100'] - 57.95:+.2f} matches per 100 and {b['delta'] + 2.45:+.2f} floors. "
                  "The historical comparison uses different seeds and controls. The paired comparison above measures the "
                  "effect of enabling v6.6 for Arm A. There is no v6.5 B arm on these same seeds.", "",
                  "## Implementation and qualification", "",
                  f"Rules commit `{data['manifest']['commit']}` descends from `{data['manifest']['base']}`. "
                  "Set `silent_cards_v66` in the combat search configuration to enable the rules. The default is false. "
                  "The two treatment bundles preserve their respective v6.5 acquisition policies.", "",
                  "The pinned Tools of the Trade adds one stack at either upgrade level. Its start-of-turn effect "
                  "increases hand draw by the stack count and then asks for a discard. The normal end-turn transition "
                  "certifies enemy resolution before that choice. The discard resumes from the public hand. Effects scheduled "
                  "after the prompt, including Noxious Fumes, are applied after the selection. Mixed unordered I Am Invincible "
                  "draw piles suspend before enemy resolution. The two native draw orders reproduce different HP outcomes.", "",
                  "Well-Laid Plans retains the whole hand in this build. Its new setup value is 2.2 HP-equivalent units per "
                  "discounted future turn, capped at four turns. Remaining enemy HP after projected poison determines that horizon. "
                  "The native card rules and this search heuristic are tested separately.", "",
                  f"Helmer ran the CPU Python environment against host SHA-256 `{data['manifest']['host']}` and game "
                  f"SHA-256 `{data['manifest']['game']}`. Native fixtures cover the base and upgraded forms of every Wave 1 and promoted card, "
                  "hidden-target and draw branches, prompt continuation, and replays of the original failing commands. "
                  "The JSON fingerprints the decompiled card, power, enchantment and pool models.", "",
                  f"Pytest reported **{q['tests']}**. Ruff reported **{q['ruff']}** across src and tests. "
                  "All 19 historical builder outputs, all ten v5 challenger files at efd9877, and 120 CSV2DEV receipts "
                  "matched their reference bytes. Each of off, active, shadow, frozen v5 and Kaiser contributed 24 receipts. "
                  f"The original v6.5 checkout reproduced all {q['base_control_transcripts']} control command transcripts and deterministic outcomes. "
                  "The compact archive includes the per-lobby verdicts, latency histograms, test output and compatibility hashes.", "",
                  "## Per-card triggers and hits", "",
                  "Each cell gives physical plays / native-matched card executions / attack hits in those executions. "
                  "Executions include replays and automatic plays. Hits count individual living targets struck, including blocked hits. "
                  "The JSON also distinguishes per-play native matches, unresolved transitions and mismatches. Corrosive Wave saw no physical play in this cohort. Murder and Storm of Steel had no matched executions in either treatment. Dedicated native fixtures cover all three.", "",
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
                  f"Of the 91 models, {sum(r['status'] == 'SUPPORTED_FULL' for r in data['inventory'])} are SUPPORTED_FULL, "
                  f"{sum(r['status'] == 'SUPPORTED_BOUNDARY' for r in data['inventory'])} are SUPPORTED_BOUNDARY, "
                  "and 11 remain for Batch 2. The four missing ordinary single-player rewards are Expertise, Master Planner, "
                  "Mirage and Untouchable.", "",
                  "SUPPORTED_FULL records deterministic card mechanics in the qualified kernel. Shared encounter, enchantment and "
                  "relic boundaries still apply. SUPPORTED_BOUNDARY records root admission with a named conditional or legacy play boundary. "
                  "REMAINING_BATCH2 lists every missing model, including multiplayer-only models outside single-player A10.", "",
                  "| Card | Pool | Status | Boundary or remaining native mechanic |", "|---|---|---|---|"])
    for r in data["inventory"]:
        lines.append(f"| {r['card']} | {r['group']} | {r['status']} | {r['note'] or '—'} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
