# Silent A10 Kaiser Crab conversion

**On 384 fresh paired starts, the Kaiser treatment cleared 6 of 40 identical boss openings (15%), compared with 4 of 40 (10%) for Arm 4.** It converted three control deaths and lost one control clear. Search coverage rose by 10.8 percentage points. Act 2 clears increased from 27 to 29 and Act 3 boss entries from 12 to 13. Every one of the 344 runs outside Kaiser had an identical command transcript across arms, including all encounters with the other two Act 2 bosses. Neither arm won a run.

The mean floor gain was +0.060, with a paired 95% interval of −0.023 to +0.177 and exact sign p = 0.625. There is evidence of higher coverage and two additional observed clears. The small number of changed outcomes leaves the progression effect uncertain. Both arms recorded zero native mismatches over 139,432 comparable physical steps in total. One seed in each arm, CSV7DEV_SEEDED_0048, had no comparable step and remains in the progression denominator.

On the 45 in-sample openings, the treatment increased Kaiser clears from one to three and mean exit HP from 0.333 to 0.444. Both additional survivors finished with low HP (2 and 3). The all-entry median exit HP stayed at zero in both cohorts. Median enemy HP on deaths increased in both cohorts; those medians describe different sets of losing runs.

## Paired results

| Outcome | AUDIT384 Arm 4 | AUDIT384 + Kaiser | CSV7DEV Arm 4 | CSV7DEV + Kaiser |
| --- | ---: | ---: | ---: | ---: |
| Lobbies | 45 | 45 | 384 | 384 |
| Kaiser Crab clears / entries | 1/45 (2.2%) | 3/45 (6.7%) | 4/40 (10.0%) | 6/40 (15.0%) |
| Knowledge Demon clears / entries | — | — | 10/35 (28.6%) | 10/35 (28.6%) |
| The Insatiable clears / entries | — | — | 13/37 (35.1%) | 13/37 (35.1%) |
| Kaiser covered / eligible | 427/1184 (36.1%) | 574/1177 (48.8%) | 426/1038 (41.0%) | 542/1046 (51.8%) |
| Kaiser median enemy HP on deaths | 263 | 276 | 232 | 240.5 |
| Kaiser median player exit HP, all entries | 0 | 0 | 0 | 0 |
| Kaiser mean player exit HP, all entries | 0.333 | 0.444 | 1.650 | 2.875 |
| Kaiser median player exit HP among clears | 15 | 3 | 7.5 | 7 |
| Mean global floor | 33.244 | 33.756 | 24.581 | 24.641 |
| Act 1 clears | 45 | 45 | 235 | 235 |
| Act 2 boss entries | 45 | 45 | 112 | 112 |
| Act 2 clears | 1 | 3 | 27 | 29 |
| Act 3 boss entries | 0 | 1 | 12 | 13 |
| Full wins | 0 | 0 | 0 | 0 |
| Decision p50 / p95 (ms) | 2.901 / 59.452 | 2.890 / 63.142 | 2.886 / 57.330 | 2.896 / 57.090 |
| Native matches / explicit boundaries | 9,524 / 985 | 9,722 / 994 | 69,632 / 6,151 | 69,800 / 6,120 |
| Raw native mismatches | 0 | 0 | 0 | 0 |
| Paired floor Δ [95% CI] | — | +0.511 [0.000, 1.378] | — | +0.060 [-0.023, 0.177] |
| Paired floor W/L/T · exact sign p | — | 2/0/43 · 0.5 | — | 3/1/380 · 0.625 |

The diagnostic population consists of the 45 natural Kaiser entrants selected from AUDIT384. Each arm started from the beginning of each lobby. The fresh population includes every one of 384 locked starts, including runs that died before Act 2. Kaiser coverage counts accepted searches among physical decisions with more than one legal action. A clear has the player's native HP at fight exit. A death has exit HP zero. Remaining enemy HP on deaths sums living arms on the last public board before the fatal physical action. The host omits the enemy board at game over.

The floor difference is treatment minus control. The percentile interval resamples complete seed pairs within each start mode with 50,000 replicates and RNG seed 621. The two-sided exact sign test excludes ties. Latency is the pooled nearest-rank physical decision time across all combat, in milliseconds. Native matches and explicit boundaries are physical steps for which the oracle produced a record.

## Why the control cleared once

**The isolated rage penalty had little influence on these 45 trajectories.** Removing exactly the surviving-arm penalty and rerunning the control changed the command sequence in one lobby, the existing clear, which still exited at 15 HP. The other 44 command transcripts were identical. At 15 roots at least one root's best certified completion included an arm kill. The selected line included that kill at nine accepted roots and one fallback root. Two accepted roots and three fallback roots selected another line. These counts describe the beam's best certified completion per root move. The isolated replay also tests whether the penalty changed earlier pruning.

**Both arms remained alive late into the fight.** On the last public board of 41 deaths both arms were alive. Crusher died first in three observed fights with one clear. Rocket died first in one with no clear. Four observed first kills are too few to establish a kill-order advantage. All 45 runs explicitly targeted both arms. All 43 fights reaching a two-arm round-three opening had already dealt HP damage to both, with a median 55 HP lost by Crusher and 27 by Rocket. Those HP totals include poison and area attacks. In the 44 deaths, mean entry HP was 56.3, only two runs entered at or below one-third HP, and the median death round was 4.5.

| Control round | Physical End Turns | Median player HP | Median total enemy HP | Facing lighter arm / two-arm End Turns |
| --- | ---: | ---: | ---: | ---: |
| 1 | 45 | 58 | 385 | 0 / 45 |
| 2 | 45 | 47 | 362 | 3 / 45 |
| 3 | 43 | 30 | 325 | 1 / 43 |
| 4 | 42 | 27 | 291.5 | 1 / 42 |
| 5 | 23 | 14 | 228 | 0 / 21 |
| 6 | 17 | 8 | 185 | 0 / 15 |
| 7 | 8 | 6.5 | 142 | 0 / 6 |
| 8 | 2 | 7.5 | 105.5 | 0 / 1 |

Facing refers to the public last targeted card or potion, initialized to the right-hand arm. For each End Turn the offline check removed the rear bonus, considered compatible base attacks, hit counts, Weak, Paper Krane, Vulnerable and Intangible, and classified the two head-on totals only when every compatible assignment agreed. Among 218 two-arm End Turns, 212 faced the heavier arm, five faced the lighter arm and one had equal totals. Seven more End Turns had a single arm. These counts describe displayed threats. Block and poison kills can change the damage actually taken. AUDIT384_DEFAULT_0089 faced the heavier attacker for seven consecutive rounds. At round four it had 58 HP against arms at 133 and 159. It reached round eight at 12 HP facing Crusher alone at 56 HP, then died. On the sole control clear, AUDIT384_DEFAULT_0161, the player faced the heavier attacker on each of the first four End Turns. Crusher fell before round five and the player finished at 15 HP.

**Certification and unsupported mechanics both mattered.** Of 44 deaths, 16 were majority covered, 13 majority mechanic/scope fallback, eight majority search-certification fallback and seven mixed. The 255 no-certified-survival decisions across all 45 fights comprised 126 unresolved-only, 70 death-only and 59 with both kinds of leaf. The 69 Centennial Puzzle, 61 ordinary draw, 38 ambiguous attack preview and 25 Gambler's Brew counts in the original report were overlapping counts across *all failed beam roots*. A failed root can encounter several of these boundaries.

A second instrumented control replay preserved every command and native counter. Of the 255 no-certified-survival roots specifically, 65 encountered Puzzle draw, 40 ordinary draw, 18 ambiguous preview and 21 Gambler's Brew. Across all 38 failed roots with ambiguous previews, the pinned attack bases resolved **all 1,191 ambiguous amount evaluations** on the old control frontier. Each original decision still received the old boundary in this measurement. Resolving one boundary cannot certify a leaf that also encounters an independent boundary or dies.

In the 13 majority mechanic/scope deaths, the largest reasons were disabled wax relic (35 decisions), Ghost Seed (33), Beating Remnant (32), Cauldron (21), Tracking (20), Neurosurge (17), unreconciled prompt (16), player Doom (16) and The Abacus (16). Across all Kaiser openings the treatment reduced no-certified-survival fallbacks from 255 to 234 and champion-continuation-unresolved fallbacks from 75 to 73. Different physical trajectories change these denominators.

## Opt-in rules and qualification

- A rounded attack preview can match several integer base values. The base tables come from the A10 Crusher and Rocket move graphs archived at 902623e. The Kaiser path checks the pinned arm's finite attack bases against the public preview, recorded facing and current modifiers. It accepts an amount only when the compatible bases agree on the new damage. Otherwise the original ambiguity check still applies.
- Centennial Puzzle's public relic row looks unused even after its once-per-fight draw. A witnessed net HP decrease in the same Kaiser fight supplies evidence that the trigger has fired. Later damage can then be simulated without repeatedly expecting another Puzzle draw. A first unresolved draw, an ordinary hidden draw or a Gambler's Brew selection stays at an explicit boundary. The search can use an independently completed surviving continuation at cap when another move remains uncertified, subject to the incumbent and comparison checks. It never assigns an HP guarantee to unknown drawn cards.
- Ghost Seed exposes Ethereal in the existing public card keywords. Cauldron's potion generation happens at pickup. Beating Remnant reuses the existing witnessed turn-start HP cap. An unknown cap continues to block admission. Both levels of Exterminate, Envenom and nonlethal Outbreak gained differentials. Outbreak with Accelerant or a lethal poison tick remains unresolved.
- The Kaiser leaf and beam reward HP, persistent mitigation, near-term poison damage and progress toward eliminating an arm, with a small Rocket preference. A surviving arm keeps its actual rage Strength and block in the simulator. The evaluator prices that Strength directly. The score is a tactical estimate; native qualification verifies transitions and leaves, while the paired runs measure the decisions those estimates produce.

All treatment code is under the default-off Kaiser switch on late Act 2 boss roots with exclusively Crusher/Rocket enemies. The nine pinned-host tests used for qualification include both card levels, a facing flip with an ambiguous Weak preview, the once-per-combat Puzzle witness, a witnessed Remnant cap, and a real native hidden-draw permutation. The two native draw orders gave different hands and identical chosen root, root scores, fallback and search attempts. A tenth fresh fixture separately reproduces Rocket dying from poison before Crusher's Defend and verifies 117 block on the survivor.

## In-sample treatment selection

Five iterations used the same 45 openings before the cohort lock. The initial focus-heavy leaf cleared once (458/1,080 decisions covered). Increasing the value of HP and persistent defense cleared twice (524/1,161). An experiment that let a surviving line bypass an unresolved champion more often raised coverage to 604/1,168 but cleared once. Restoring the incumbent comparison and increasing mitigation weights recovered two clears (534/1,160). Qualifying the poison and area cards produced the selected three-clear policy (574/1,177). Every iteration recorded zero comparable-step native mismatches. These are repeated development measurements on the same fights.

## Protocol and receipts

The policy and cohort were committed at 5f5e9b15e06a489e58c551a01fb79ccbf3acf535 before the first CSV7DEV lobby. The 192 default and 192 seeded natural starts have SHA-256 3647cc5d3327c94feb6cd7d4704205c7975c60872438ad556cfccc88ee8eafe5. The lock had zero name or xxHash64 collisions against 63,682 historical or conservatively reserved identifiers. Paired arms ran on the pinned v0.111.0 host with 12 workers, one BLAS thread and one OpenMP thread. Arm order alternated by index within each start mode.

All 45 diagnostic controls reproduced the archived lobby's outcome, step count, native counters, late-fight exits and Kaiser coverage. All ten challenger files matched the efd9877 Git blobs byte-for-byte. The active Arm 4 builder reproduced manifest SHA-256 4b5fe32e78a96ca656cca805f316410b19baa9c4f2c227d25b77a6d1306c93a9. The 24 flags-off, 24 active-v5 and 24 shadow CSV2DEV receipts matched the historical full-transcript records. Active-v5 recorded 2,126 matches and 171 boundaries. Shadow recorded 3,534 and 351.

The full pytest invocation reported **615 passed, 1 skipped in 290.46s (0:04:50)**. The panel guard skipped only the archived case whose setup resets FINAL768_DEFAULT_0037. The fresh CSV7FIX poison-before-Defend differential exercised the same event ordering on the pinned host. Ruff reported zero findings across 113 files in src/ and tests/. No reserved lobby ran.

Reproduce the experiment with the pinned CPU Python, PYTHONPATH including src and docs/combat-search-v2/probes, CSV2DEV_HOST pointing at the qualified assembly, and the native runtime paths available under artifacts/. Run the collector as `python docs/combat-search-v2/probes/kaiser.py dev paired <fresh-directory> --workers 12`. For the diagnostics use `audit control`, `audit treatment`, `audit rage-ablation` or `audit preview-audit` in place of `dev paired`. The offline report script takes the receipt ZIP as its only argument.

The receipt archive includes the control, treatment, rage-ablation and preview-audit diagnostic replay sets, both locked development arms, per-lobby timing bins, the registry proof, all 72 compatibility receipts and the tested in-sample iterations. [Machine-readable results](kaiser-conversion.json) · [Native receipts](kaiser-conversion-receipts.zip) · [CSV7DEV lock](csv7dev-lock.json) · [Offline report script](probes/report_kaiser.py)
