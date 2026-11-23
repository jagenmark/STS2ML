# Silent A10 v6.1 hallway coverage and boss-safe search

On 256 locked CSV5DEV lobbies, Schema 3 covered **8,938/15,500 (57.7%)** eligible Act 2 hallway and elite decisions, up from **4,916/14,521 (33.9%)** on frozen v5. Regular hallways reached 58.6% coverage and elites reached 48.3%. Across 642 matched regular hallway fights, the hallway arm finished with **1.16 more HP** on average. The four final arms recorded **zero native mismatches**.

Leaving Act 2 bosses on v5 yielded 8 Act 2 clears. Enabling boss-safe Schema 3 yielded 7 and the heuristic yielded 8, versus 7 on frozen v5. All paired floor intervals include zero. No arm won a full run. These development results support wider hallway coverage and leave progression gains uncertain.

## Paired progression

| Arm | Mean floor | Paired Δ floors [95% CI] | Act 1 clear | Act 2 boss | Act 2 clear | Act 3 boss | Full wins | p50 / p95 ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Frozen v5 · Schema 3 | 23.750 | reference | 153 | 58 | 7 | 4 | 0 | 2.246 / 55.669 |
| Hallways + Act 3 · Schema 3 | 23.918 | +0.168 [-0.172, +0.500] | 153 | 59 | 8 | 2 | 0 | 3.074 / 63.830 |
| Boss-safe · Schema 3 | 23.844 | +0.094 [-0.227, +0.398] | 153 | 59 | 7 | 2 | 0 | 3.204 / 64.216 |
| Boss-safe · heuristic | 24.266 | +0.516 [-0.465, +1.508] | 167 | 67 | 8 | 3 | 0 | 2.907 / 53.381 |

The global floor is 17 × (act − 1) + local floor. Each milestone counts unique lobbies. A clear requires entry into the next act and a win requires verified native victory. Intervals use 10,000 paired bootstrap draws within the two 128-lobby act-list strata, with bootstrap seed 561. Latencies pool all physical combat decisions from policy dispatch through action selection, before the native step and audit. The four reported timings were collected one arm at a time. Boss-safe Schema 3 was repeated separately after the native suite finished. All 256 repeat records matched the first run on every field except timing.

Boss-safe Schema 3 minus hallway-only Schema 3 was -0.074 floors (95% CI -0.203 to +0.000). Heuristic minus boss-safe Schema 3 was +0.422 floors (95% CI -0.547 to +1.395). The heuristic uses its leaf in every search-enabled act, so it can change Act 1 outcomes and subsequent fight visits. This development lock also served to reproduce and correct native discrepancies during qualification.

## Coverage and boss survival

| Eligible decisions | Frozen v5 · Schema 3 | Hallways + Act 3 · Schema 3 | Boss-safe · Schema 3 | Boss-safe · heuristic |
| --- | --- | --- | --- | --- |
| Act 1 | 27,617/42,041 (65.7%) | 27,617/42,041 (65.7%) | 27,617/42,041 (65.7%) | 26,776/41,078 (65.2%) |
| Act 2 regular hallways | 4,646/13,172 (35.3%) | 8,271/14,119 (58.6%) | 8,271/14,119 (58.6%) | 8,564/14,627 (58.5%) |
| Act 2 elites | 270/1,349 (20.0%) | 667/1,381 (48.3%) | 667/1,381 (48.3%) | 794/1,677 (47.3%) |
| Act 2 hallways + elites | 4,916/14,521 (33.9%) | 8,938/15,500 (57.7%) | 8,938/15,500 (57.7%) | 9,358/16,304 (57.4%) |
| Act 2 bosses | 106/1,664 (6.4%) | 97/1,649 (5.9%) | 775/1,789 (43.3%) | 861/2,027 (42.5%) |
| Kaiser Crab | 0/535 (0.0%) | 0/544 (0.0%) | 236/581 (40.6%) | 234/631 (37.1%) |
| Knowledge Demon | 0/639 (0.0%) | 0/612 (0.0%) | 285/655 (43.5%) | 352/789 (44.6%) |
| The Insatiable | 106/490 (21.6%) | 97/493 (19.7%) | 254/553 (45.9%) | 275/607 (45.3%) |
| Act 3 | 8/580 (1.4%) | 31/640 (4.8%) | 29/456 (6.4%) | 206/844 (24.4%) |

Coverage is certified whole-turn choices divided by eligible combat decisions, including fallbacks and selection prompts. A combat-play root with neither a playable card nor a usable potion is excluded. The deadline override and champion curse handoff count as fallback dispositions. Each arm contributes its own naturally reached fights.

| Act 2 boss cleared / entered | Frozen v5 · Schema 3 | Hallways + Act 3 · Schema 3 | Boss-safe · Schema 3 | Boss-safe · heuristic |
| --- | --- | --- | --- | --- |
| Kaiser Crab | 1/22 (4.5%) | 2/23 (8.7%) | 2/23 (8.7%) | 1/24 (4.2%) |
| Knowledge Demon | 6/18 (33.3%) | 6/18 (33.3%) | 5/18 (27.8%) | 5/21 (23.8%) |
| The Insatiable | 0/18 (0.0%) | 0/18 (0.0%) | 0/18 (0.0%) | 2/22 (9.1%) |

On the hallways arm, Kaiser Crab and Knowledge Demon used the frozen boss behavior, alongside v5's existing partial Insatiable coverage. Both experimental boss-safe arms searched regular card roots and handed the actual curse offers to the champion. On the same 18 Schema 3 Knowledge Demon entries, enabling boss-safe search changed clears from 6 to 5. The heuristic recorded 2 Insatiable clears in 22 entries.

## Hallway damage and boss entry HP

| Arm | Matched regular fights | Exit HP | V5 exit HP on same fights | Paired Δ exit HP | Paired Δ net HP lost per fight | Boss entry HP, all entrants | Paired Δ boss entry HP (bosses) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Frozen v5 · Schema 3 | 660 | 38.55 | 38.55 | +0.00 | +0.00 | 56.72 | +0.00 (58) |
| Hallways + Act 3 · Schema 3 | 642 | 40.43 | 39.27 | +1.16 | -0.51 | 57.71 | +1.72 (50) |
| Boss-safe · Schema 3 | 642 | 40.43 | 39.27 | +1.16 | -0.51 | 57.71 | +1.72 (50) |
| Boss-safe · heuristic | 502 | 40.85 | 40.74 | +0.11 | -0.38 | 56.30 | -0.89 (36) |

Fights pair within lobby on act, local floor, room type and opening formation. Entry is the first public combat HP and exit is the first post-combat HP, with zero on death. Net HP lost is entry minus exit. A matched exit difference includes HP carried into the fight. The net-loss column measures damage taken after accounting for that starting difference.

Across **50 paired boss entrants**, cumulative net HP lost in regular hallways was **56.78** with the Schema 3 hallway arm versus **59.48** for their v5 controls, a change of **-2.70 HP per run**. The heuristic changed the corresponding loss by +1.25 HP across 36 paired entrants. The historical 22.2 HP figure compared eventual boss clears with deaths. These paired measurements estimate the policy difference on CSV5 and use a different population.

In Act 3, matched exit HP changed by +0.86 (21 fights) for the hallway arm, +0.86 (21) for boss-safe Schema 3, and -1.82 (17) for the heuristic. The earlier v6 heuristic gained 7.00 HP across 26 matched Act 3 fights on its development panel. Both estimates come from few late fights. Whispering Earring was the most frequent Act 3 fallback on the new Schema 3 arms. [v6 Act 2 boss and Act 3 report](v6-act2boss-act3-report.md)

## Public mechanics and native qualification

| 128-lobby census | Regular hallway | Elite | Combined | Raw mismatches, all acts |
| --- | --- | --- | --- | --- |
| Frozen v5 | 2,193/5,778 (38.0%) | 180/667 (27.0%) | 2,373/6,445 (36.8%) | 1 |
| Historical v6 | 2,193/5,778 (38.0%) | 180/667 (27.0%) | 2,373/6,445 (36.8%) | 9 |
| Existing v6 rules routed into Act 2 hallways and elites | 3,130/5,898 (53.1%) | 258/631 (40.9%) | 3,388/6,529 (51.9%) | 1 |
| Qualified v6.1 boss-safe | 3,575/6,025 (59.3%) | 274/637 (43.0%) | 3,849/6,662 (57.8%) | 0 |

The formations below had the most frozen-v5 fallback decisions in each room type. Coverage uses each arm's own visits.

| Room | Opening formation | v5 fallback decisions | v5 covered | v6.1 covered |
| --- | --- | --- | --- | --- |
| Regular | Myte + Myte | 341 | 222/563 (39.4%) | 308/558 (55.2%) |
| Regular | Tunneler | 327 | 477/804 (59.3%) | 688/835 (82.4%) |
| Regular | Exoskeleton + Exoskeleton + Exoskeleton | 317 | 290/607 (47.8%) | 411/604 (68.0%) |
| Elite | Decimillipede Segment Front + Decimillipede Segment Middle + Decimillipede Segment Back | 245 | 21/266 (7.9%) | 66/249 (26.5%) |
| Elite | Infested Prism | 144 | 94/238 (39.5%) | 112/239 (46.9%) |

Frozen v5's regular-hallway first blockers included 204 Tender decisions, 131 Intimidating Helmet, 122 Meat on the Bone, 121 Pandora's Box, and 120 Beating Remnant. Segment reattachment blocked 108 elite decisions. The leading card-specific first blockers were `SURVIVOR` (74), `PINPOINT` (60), `BOUNCING_FLASK` (56) on v5 and `METAMORPHOSIS` (53), `SCULPTING_STRIKE` (25), `RESTLESSNESS` (23) on v6.1. The routing-only diagnostic used a working copy on top of `0a96622`. Reusing the already-qualified v6 card, relic and prompt rules supplied most of the increase. Native fixtures additionally exercised the following mechanics.

- Hunter Killer applies Tender. Each witnessed play loses one Strength and Dexterity, restored at turn end. An unwitnessed count or ambiguous Artifact interaction stops the line.
- Slumbering Beetle loses a Slumber stack on HP loss or its sleep move. Its visible Plating supplies block until waking. A damage-triggered wake that could change the move is a boundary.
- A Decimillipede segment alive at the public turn opening can be knocked out before its next move. The resolver stops before an older knockout may reattach. The last segment's knockout ends combat.
- Beating Remnant caps HP loss at 20 on a witnessed turn. Missing damage history, regeneration ordering and start-turn poison stop the line. Dolly's Mirror completes its effect before combat. Burning Sticks stops at the first qualifying skill exhaust that generates a copy.
- With boss-safe search, the Knowledge Demon beam evaluates only the frozen champion's configured preference at a deterministic hypothetical offer. At a real offer the champion's stamped selection is returned, including when the preceding projection stopped. A retained one-cost card with a possible base Enlightenment discount creates a boundary at the offer. Sloth prices remaining play slots and high-impact cards in the projected hand. The native third-offer alternative is Waste Away. Demise is a power on the enemy.
- Both boss-safe leaf evaluators price Sandpit at one tick by the player's max HP plus 20, at two ticks by 12 HP and at three by 4 HP. At one or two ticks the live controller takes an affordable Frantic Escape unless it certifies an immediate victory. After a crab limb dies, the leaf and beam also charge for the surviving arm's remaining HP and rage block. Pinned plays witness 99 Block and six Strength.
- Other differential fixtures cover The Hunt's fatal-hit power, Nimble Relax, spent Toy Box relics and delayed Toasty Mittens triggers. Hidden-draw swaps produce different actual hands with identical pre-reveal hallway features and boss values. Search inputs contain current public observations, unordered piles and witnessed actions. Post-step comparisons are used for auditing and subsequent real decisions.

| Final dev arm | Matches | Mismatches | Explicit boundaries |
| --- | --- | --- | --- |
| Frozen v5 · Schema 3 | 40,474 | 0 | 3,557 |
| Hallways + Act 3 · Schema 3 | 46,076 | 0 | 4,094 |
| Boss-safe · Schema 3 | 47,196 | 0 | 4,245 |
| Boss-safe · heuristic | 47,534 | 0 | 4,590 |

| Stage | Cohort and arm | Lobbies | Raw mismatches | Finding |
| --- | --- | --- | --- | --- |
| Frozen reference | Census · v5 | 128 | 1 | Dash returned Right Hand Hand from discard. The independent v6 observer matched the same physical action. |
| Historical v6 | Census · v6 | 128 | 9 | Nimble Relax block and expired Toy Box wax relics. |
| v6 rules in hallways | Census · hallways | 128 | 1 | A wax Pendulum failed to tick after Toy Box expired. |
| f13c575 | Census · boss-safe | 128 | 8 | Nimble Relax and wax Letter Opener outside the initial hallway guard. |
| f9fe589 | Dev · hallways | 256 | 8 | The Hunt fatal power with surviving allies and start-turn triggers suspended by Toasty Mittens. |
| c926f68 | Dev · boss-safe | 256 | 1 | Base Enlightenment expired on retained Snakebite before a Knowledge Demon curse offer. |
| c926f68 | Dev · hallways / heuristic | 256 | 0 / 0 | Both arms completed before the final curse qualification. |
| a6c4868 | Dev · all four arms | 256 | 0 / 0 / 0 / 0 | Each arm ran the full lock on the same revision. |

## Integrity and reproduction

The 128 census lobbies and 256 dev lobbies use disjoint CSV5CENSUS and CSV5DEV names. Each panel has equal default and seeded halves. Commit `0a96622` locked both before the first episode. The lock SHA-256 is `c49e77b83a761acbc68f3e5f6e8e07ec076ce65493acabe8790e7b0b79a3e11d`. The final four arms used search revision `a6c4868761cc1226f84ee8a7c326ba060e9b1afe`, width 16, depth 10, 512 children and 12 CPU workers. Each arm used one OpenBLAS and one OpenMP thread per worker. The public host SHA-256 is `7408d040c28416331279a84e299b52ff35086d80b4cb9711aefd0f91168d8f20` and game assembly SHA-256 is `14b57dbaee1b58cb919625a662831054fd714b3b75b13b7449eac0e95b98a3e4`.

The two new config booleans default to false. `v61_act2_hallways_act3` enables Act 2 Monster and Elite rooms and v6 Act 3 search. `v61_boss_safe` includes those rooms and enables the qualified Act 2 boss policy. The 10 release files match Git revision `efd9877` byte for byte, including manifest SHA-256 `a686db12c8b217bd476ea5c8e60cf6f486b060665536ef9354e8f09c21c81fcb`. All protected legacy modules match that revision. On 12 fresh census lobbies, frozen and current active-v5 action digests, RPC transcripts and terminal outcomes matched byte for byte. Both audited v5 dev passes reproduced all 256 terminal, fight, coverage and native-audit records.

Use the CPU interpreter with `PYTHONPATH=src` and `CSV2DEV_HOST` pointing at the pinned v0.111.0 Curriculum DLL. Set `OPENBLAS_NUM_THREADS` and `OMP_NUM_THREADS` to `1`. The worktree's `artifacts/tools/dotnet` and `artifacts/upstreams/sts2-cli/lib` must resolve to the pinned SDK and game library. Run the ablation script once for each arm, then combine and analyze the receipts.

```powershell
foreach ($arm in 'v5','hallways','boss-safe','heuristic') {
    & $cpu scripts/ablate-silent-v61.py --arm $arm --cohort DEV --workers 12 --output artifacts/v61-reproduce
}
& $cpu scripts/report-silent-v61.py artifacts/v61-reproduce/receipts.jsonl.gz --pack artifacts/v61-reproduce
```

For the full native suite, add `docs/combat-search-v2/probes` to `PYTHONPATH`, set `CSV2DEV_OBSERVER` to the built pinned observer, and run `pytest -q -p v6_fixture_seeds`. The fixture mapper keeps historical regression scenarios off reserved lobby namespaces. Pytest reported **593 passed in 317.96s (0:05:17)**. Ruff checked **110 Python files** under `src/` and `tests/` with zero findings.

To recompute the tables from the published 1,024 terminal receipts, run `python scripts/report-silent-v61.py docs/combat-search-v2/v61-dev-receipts.jsonl.gz`. The receipt archive SHA-256 is `9756e535b1e1d5b87ae1bb559a6d87142e7586659590ed9878c779e2f18d4a72`.

[Locked lobbies](v61-cohorts.json) · [Paired dev receipts](v61-dev-receipts.jsonl.gz) · [Manifests, census, discovery records, physical parity and full metrics](v61-verification.json) · [Native fixtures](../../tests/test_combat_search_v61_native.py)
