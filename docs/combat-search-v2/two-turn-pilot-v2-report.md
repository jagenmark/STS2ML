# Two-turn Silent A10 pilot after the victory-ranking fix

**Keep Arm 3 as the default and pause the C# port.** The fixed Python pilot won 70 of the same 100 fights to Arm 3's 69. Vantom supplied the extra win. The paired gain was **+0.04 exit HP** (95% CI −1.13 to +1.18), down from +0.17. On the 69 paired wins the difference was −0.10 HP. Activated choices took 158.6/432.8 ms p50/p95 on omarchy. A faster implementation would reduce that cost, but the measured fight outcomes give little reason to pay for a port.

The 68 boss openings yielded +1.06 HP (−0.29 to +2.47) and 40→41 wins. This exploratory subset mixes controlled scenarios and 20 inactive restored bosses. A boss-only gate remains a hypothesis for a fresh Python development cohort. The cohort contains zero separately tagged elite rooms and supplies no estimate for an elite gate.

## Paired fight outcomes

We replayed both policies at `b91f56b` and both policies after the fix on omarchy, for 400 native fights. Each run paired the two arms on 100 unique public opening digests, identical across revisions. Eighty openings use the original ten-species, four-deck, two-HP scenarios and their Act 2 routing. Twenty use the first 20 historical ACT1PATTEST Waterfall Giant saves with their native routing. All fights ran to native exit. The control averaged 34.62 HP, the old pilot 34.79 and the fixed pilot 34.66. Relative to Arm 3 the fixed pilot gained HP on 13 openings, lost HP on 12 and tied on 75. Relative to the old pilot it gained on six, lost on six and tied on 88.

W/L/T counts pilot-only clears, control-only clears and ties in survival. HP includes zero for deaths. Intervals use the original paired opening-level percentile bootstrap, 20,000 resamples with seed 64002. Common wins restrict each comparison to openings both arms won. Encounter intervals describe small development samples with related historical openings. Figures are rounded after computing differences.

| Encounter | Pairs | Wins 1T / old / fixed | Old W/L/T | Fixed W/L/T | Old Δ HP [95% CI] | Fixed Δ HP [95% CI] | Fixed − old HP [95% CI] |
| --- | --- | --- | --- | --- | --- | --- | --- |
| All | 100 | 69 / 70 / 70 | 1/0/99 | 1/0/99 | +0.17 [-1.02, +1.31] | +0.04 [-1.13, +1.18] | -0.13 [-0.70, +0.35] |
| Waterfall Giant | 28 | 15 / 15 / 15 | 0/0/28 | 0/0/28 | +0.71 [-0.04, +1.86] | +0.71 [-0.04, +1.86] | +0.00 [+0.00, +0.00] |
| Ceremonial Beast | 8 | 6 / 6 / 6 | 0/0/8 | 0/0/8 | -1.50 [-3.50, +0.00] | -1.50 [-3.50, +0.00] | +0.00 [+0.00, +0.00] |
| Lagavulin Matriarch | 8 | 7 / 7 / 7 | 0/0/8 | 0/0/8 | +1.62 [-2.75, +7.12] | +2.88 [-0.50, +7.62] | +1.25 [+0.00, +3.25] |
| The Insatiable | 8 | 0 / 0 / 0 | 0/0/8 | 0/0/8 | +0.00 [+0.00, +0.00] | +0.00 [+0.00, +0.00] | +0.00 [+0.00, +0.00] |
| Vantom | 8 | 6 / 7 / 7 | 1/0/7 | 1/0/7 | +0.62 [-4.25, +5.00] | +2.00 [-3.25, +6.75] | +1.38 [+0.00, +3.25] |
| Soul Fysh | 8 | 6 / 6 / 6 | 0/0/8 | 0/0/8 | +7.25 [+1.75, +13.25] | +3.12 [-5.12, +11.00] | -4.12 [-9.00, -0.38] |
| Tunneler | 8 | 8 / 8 / 8 | 0/0/8 | 0/0/8 | -8.25 [-16.25, -1.75] | -8.38 [-14.50, -2.88] | -0.12 [-2.25, +2.38] |
| Slumbering Beetle | 8 | 6 / 6 / 6 | 0/0/8 | 0/0/8 | +0.00 [+0.00, +0.00] | -0.25 [-0.75, +0.00] | -0.25 [-0.75, +0.00] |
| Louse Progenitor | 8 | 7 / 7 / 7 | 0/0/8 | 0/0/8 | +0.12 [+0.00, +0.38] | +0.12 [+0.00, +0.38] | +0.00 [+0.00, +0.00] |
| Shrinker Beetle | 8 | 8 / 8 / 8 | 0/0/8 | 0/0/8 | -0.25 [-0.75, +0.00] | +0.00 [+0.00, +0.00] | +0.25 [+0.00, +0.75] |

| Encounter | Old common wins · Δ HP [95% CI] | Fixed common wins · Δ HP [95% CI] |
| --- | --- | --- |
| All | 69 · +0.19 [-1.52, +1.84] | 69 · -0.10 [-1.75, +1.51] |
| Waterfall Giant | 15 · +1.33 [-0.07, +3.40] | 15 · +1.33 [-0.07, +3.40] |
| Ceremonial Beast | 6 · -2.00 [-4.33, +0.00] | 6 · -2.00 [-4.33, +0.00] |
| Lagavulin Matriarch | 7 · +1.86 [-3.14, +8.00] | 7 · +3.29 [-0.57, +8.71] |
| The Insatiable | 0 · — | 0 · — |
| Vantom | 6 · +0.17 [-5.83, +6.00] | 6 · +0.83 [-5.17, +6.33] |
| Soul Fysh | 6 · +9.67 [+3.17, +16.50] | 6 · +4.17 [-6.83, +14.67] |
| Tunneler | 8 · -8.25 [-16.25, -1.75] | 8 · -8.38 [-14.50, -2.88] |
| Slumbering Beetle | 6 · +0.00 [+0.00, +0.00] | 6 · -0.33 [-1.00, +0.00] |
| Louse Progenitor | 7 · +0.14 [+0.00, +0.43] | 7 · +0.14 [+0.00, +0.43] |
| Shrinker Beetle | 8 · -0.25 [-0.75, +0.00] | 8 · +0.00 [+0.00, +0.00] |

## How the ranking changed

Each candidate still receives the same four public-state CRN draws as its competitor. Among all four worlds, compare the fraction alive (including victories), then the fraction victorious, then mean Arm 3 leaf utility. A strict improvement changes the physical root. An exact tie retains the control. An extra sampled death has priority over any gain in victories. At equal survival each additional victory outranks any progress, power or block bonus. The numeric tie-breaker therefore compares candidates with equal counts of each certified outcome. No change to the leaf evaluator, search budgets or sampling was needed.

Re-scoring the 76 archived changed decisions on their original roots reverses 25 rankings, including all five previously reported 4/4-versus-0/4 cases. All 57 new changed decisions respect the new order. Four victories in this table mean four certified sampled continuations. Native draws and subsequent policy decisions determine exit HP. The two Soul Fysh decisions belong to the same fight and the fixed policy can leave the old trajectory before a recorded root.

| Encounter / opening / round | 4-win control root | Old 0-win choice | Old mean, control / alternative | Native exit HP, 1T / old / fixed |
| --- | --- | --- | --- | --- |
| Lagavulin Matriarch / 1 / 6 | DASH@3 | DEFLECT@2 | 53 / 121.06 | 53 / 45 / 53 |
| Soul Fysh / 2 / 8 | DASH@2 | DEFLECT@5 | 37 / 112.92 | 31 / 43 / 31 |
| Soul Fysh / 2 / 8 | DEADLY_POISON@2 | end_turn | 34 / 110.445 | 31 / 43 / 31 |
| Tunneler / 7 / 4 | POISONED_STAB@4 | BLUR@2 | 77 / 110.3475 | 77 / 77 / 71 |
| Shrinker Beetle / 3 / 1 | POISONED_STAB@2 | AFTERIMAGE@1 | 70 / 85.62 | 70 / 70 / 70 |

**Tunneler's HP loss persists.** Both pilots still selected Deadly Poison over Deflect in round 1 of opening 3. All eight leaves were ongoing fights and the mean utilities were 87.00 and 86.21, respectively. That opening ended at 67 / 36 / 43 HP. In opening 5 both pilots opened with Slice over Noxious Fumes and finished at 67 HP against Arm 3's 86. In opening 7 the fixed policy made a different round-4 decision, preferring Snakebite's 3/4 victories over Deflect's 2/4, with eventual exit HP falling from 77 to 71. The loss across Tunneler openings consequently moved from −8.25 to −8.38 HP. Soul Fysh's benefit shrank from +7.25 to +3.12 HP. On Vantom opening 0 the extra win improved from 4 to 11 exit HP.

## Activation and changed physical moves

The control took 3,891 decisions in each run. The pilot totals were 3,885 before and 3,838 after. Among fixed-pilot decisions, 57 changes represent 4.6% of activations, 3.1% of eligible decisions and 1.5% of all decisions. Changed-fight means use the fights in which that pilot actually made a different physical move from its local one-turn recommendation. Membership can differ between revisions.

| Encounter | Old active / eligible | Fixed active / eligible | Old changes (% active) | Fixed changes (% active) |
| --- | --- | --- | --- | --- |
| All | 1275/1914 (66.6%) | 1238/1867 (66.3%) | 76 (6.0%) | 57 (4.6%) |
| Waterfall Giant | 190/415 (45.8%) | 190/415 (45.8%) | 9 (4.7%) | 9 (4.7%) |
| Ceremonial Beast | 92/137 (67.2%) | 92/137 (67.2%) | 4 (4.3%) | 4 (4.3%) |
| Lagavulin Matriarch | 173/188 (92.0%) | 167/182 (91.8%) | 9 (5.2%) | 5 (3.0%) |
| The Insatiable | 0/187 (0.0%) | 0/187 (0.0%) | 0 (—) | 0 (—) |
| Vantom | 210/210 (100.0%) | 209/209 (100.0%) | 11 (5.2%) | 7 (3.3%) |
| Soul Fysh | 285/285 (100.0%) | 265/265 (100.0%) | 17 (6.0%) | 17 (6.4%) |
| Tunneler | 130/147 (88.4%) | 130/137 (94.9%) | 19 (14.6%) | 10 (7.7%) |
| Slumbering Beetle | 11/161 (6.8%) | 8/158 (5.1%) | 0 (0.0%) | 1 (12.5%) |
| Louse Progenitor | 142/142 (100.0%) | 142/142 (100.0%) | 3 (2.1%) | 3 (2.1%) |
| Shrinker Beetle | 42/42 (100.0%) | 35/35 (100.0%) | 4 (9.5%) | 1 (2.9%) |

| Encounter | Old changed fights · Δ HP [95% CI] | Fixed changed fights · Δ HP [95% CI] |
| --- | --- | --- |
| All | 37 · +0.46 [-2.73, +3.54] | 33 · +0.12 [-3.39, +3.52] |
| Waterfall Giant | 5 · +4.00 [+0.00, +8.80] | 5 · +4.00 [+0.00, +8.80] |
| Ceremonial Beast | 3 · -4.00 [-7.00, +0.00] | 3 · -4.00 [-7.00, +0.00] |
| Lagavulin Matriarch | 5 · +2.60 [-4.40, +10.60] | 3 · +7.67 [-2.00, +18.00] |
| The Insatiable | 0 · — | 0 · — |
| Vantom | 5 · +1.00 [-7.00, +8.00] | 5 · +3.20 [-5.60, +10.00] |
| Soul Fysh | 8 · +7.25 [+1.75, +13.25] | 7 · +3.57 [-5.71, +12.57] |
| Tunneler | 6 · -11.00 [-20.17, -2.67] | 6 · -11.17 [-18.00, -4.83] |
| Slumbering Beetle | 0 · — | 1 · -2.00 [-2.00, -2.00] |
| Louse Progenitor | 2 · +0.50 [+0.00, +1.00] | 2 · +0.50 [+0.00, +1.00] |
| Shrinker Beetle | 3 · -0.67 [-2.00, +0.00] | 1 · +0.00 [+0.00, +0.00] |

## Native fidelity and latency on omarchy

Timings are wall-clock p50/p95 milliseconds for the full deployed choice. Host execution and post-choice auditing are outside the timer. Both local benchmark runs used 12 workers and one OpenBLAS/OpenMP thread per worker. These timings include machine load and the effect of reaching different roots.

| Encounter | 1T before | 1T after | Old 2T | Fixed 2T | Old active | Fixed active |
| --- | --- | --- | --- | --- | --- | --- |
| All | 3.3/45.4 | 3.2/47.6 | 6.2/318.2 | 5.6/300.9 | 172.6/450.2 | 158.6/432.8 |
| Waterfall Giant | 2.2/28.6 | 2.1/32.3 | 2.3/219.9 | 2.2/220.4 | 174.1/454.0 | 175.6/489.5 |
| Ceremonial Beast | 4.0/41.5 | 3.6/43.3 | 7.6/288.4 | 6.6/309.6 | 156.2/448.4 | 160.7/436.6 |
| Lagavulin Matriarch | 4.2/36.4 | 4.1/34.7 | 68.8/368.7 | 69.2/319.1 | 189.6/463.1 | 168.0/388.1 |
| The Insatiable | 4.7/40.3 | 4.0/35.7 | 4.5/47.2 | 4.1/41.0 | — | — |
| Vantom | 4.1/49.1 | 3.2/41.7 | 61.8/345.8 | 61.0/381.6 | 116.9/374.9 | 94.0/452.9 |
| Soul Fysh | 5.1/45.0 | 5.8/62.5 | 135.8/451.9 | 136.4/375.6 | 206.2/528.0 | 183.5/432.3 |
| Tunneler | 4.7/59.2 | 4.1/43.2 | 80.9/307.0 | 88.8/264.0 | 142.1/345.3 | 133.9/302.0 |
| Slumbering Beetle | 7.3/142.8 | 7.6/171.8 | 8.7/228.2 | 7.2/190.4 | 416.4/890.1 | 274.3/463.7 |
| Louse Progenitor | 3.7/33.6 | 4.7/40.6 | 82.0/374.8 | 91.6/349.4 | 181.4/394.4 | 147.9/447.9 |
| Shrinker Beetle | 3.7/33.9 | 3.3/39.7 | 22.6/356.4 | 11.0/227.6 | 172.8/411.0 | 95.1/354.7 |

| Encounter | Old steps / intents / starts / errors | Fixed steps / intents / starts / errors |
| --- | --- | --- |
| All | 6075/1221/901/0 | 6028/1209/889/0 |
| Waterfall Giant | 1214/292/140/0 | 1214/292/140/0 |
| Ceremonial Beast | 528/68/68/0 | 528/68/68/0 |
| Lagavulin Matriarch | 645/129/129/0 | 642/127/127/0 |
| The Insatiable | 584/88/0/0 | 584/88/0/0 |
| Vantom | 632/152/152/0 | 630/150/150/0 |
| Soul Fysh | 838/184/184/0 | 815/179/179/0 |
| Tunneler | 445/86/86/0 | 434/86/86/0 |
| Slumbering Beetle | 528/90/10/0 | 525/89/9/0 |
| Louse Progenitor | 490/106/106/0 | 490/106/106/0 |
| Shrinker Beetle | 171/26/26/0 | 166/24/24/0 |

The fixed run recorded 3,043 exact steps, 610 intents and 450 qualified starts for Arm 3, and 2,985 steps, 599 intents and 439 starts for the pilot, with zero native mismatches. The respective 49 and 50 unresolved step boundaries are outside the exact-match counts. The private-RNG/draw-permutation native test also passed. It keeps the public digest fixed, observes different real hands, and checks identical eight sampled hands, world scores, aggregates and physical choice.

## Why all 20 restored openings stayed with Arm 3

Both arms won seven of the 20. The fixed pilot made 1,064 decisions here. Twelve openings had zero eligible decisions. On the other eight, the first failing extension gate accounted for all 203 eligible decisions. Booming Conch accounted for 94 and Strike Dummy for 51 because neither relic is qualified for the pilot's turn start. The card gate accounted for 58. Among those 58, the first rejected card was Memento Mori 16 times, Strike 12, Omnislice 11, Skewer 10 and Ascender's Bane nine. All three restored decks contain a Sharp (2) Strike alongside ordinary Strikes. The modified copy fails card support. Skewer costs X, Omnislice lacks card support, and Ascender's Bane and Memento Mori are outside the fixed-cost sampling list.

Each row accounts for every native choice. The eligible column lists the first rejected public item on the evaluated line. The final column gives the one-turn fallbacks or structural skips on the other choices. “Forced” means fewer than two legal roots. “Distinct lines” means fewer than two distinct completed surviving continuations. “Eruption” is Waterfall Giant's post-knockout phase. The raw receipts retain the original reason strings and full opening digests.

| Archive index · digest prefix | Choices | Eligible · first pilot gate | Other choices · one-turn reason |
| --- | --- | --- | --- |
| 0 · `877421cf330a` | 63 | 0 | relic/MERCURY_HOURGLASS ×52, unreconciled prompt ×5, eruption ×6 |
| 1 · `668913936aa3` | 68 | 26 · ASCENDERS_BANE (cost 0) ×3, MEMENTO_MORI (cost 1) ×8, OMNISLICE (cost 0) ×5, SKEWER (cost 0) ×6, STRIKE_SILENT (cost 1) ×4 | card/OMNISLICE ×13, card/STRIKE_SILENT ×6, champion continuation unresolved ×5, distinct lines ×3, forced ×10, no certified survival ×1, unreconciled prompt ×1, eruption ×3 |
| 2 · `99ab49e5c3db` | 48 | 0 | relic/RAINBOW_RING ×43, unreconciled prompt ×3, eruption ×2 |
| 3 · `cf2fb5751f5b` | 37 | 0 | relic/RAINBOW_RING ×33, unreconciled prompt ×1, eruption ×3 |
| 4 · `b48fb538e363` | 59 | 30 · relic BOOMING_CONCH ×30 | card/DEFEND_SILENT ×13, champion continuation unresolved ×1, forced ×9, no certified survival ×1, unreconciled prompt ×1, eruption ×4 |
| 5 · `f62bfe04c71b` | 82 | 37 · relic BOOMING_CONCH ×37 | card/DEFEND_SILENT ×20, champion continuation unresolved ×1, distinct lines ×2, forced ×14, unreconciled prompt ×2, eruption ×6 |
| 6 · `6be1778b08fc` | 62 | 0 | player power/RETAIN_HAND ×6, relic/TOUGH_BANDAGES ×48, unreconciled prompt ×5, eruption ×3 |
| 7 · `d9df61eb749b` | 64 | 0 | player power/RETAIN_HAND ×4, relic/TOUGH_BANDAGES ×53, unreconciled prompt ×4, eruption ×3 |
| 8 · `cc0be376ba37` | 34 | 0 | relic/FRESNEL_LENS ×30, unreconciled prompt ×1, eruption ×3 |
| 9 · `af5774d8c823` | 51 | 16 · ASCENDERS_BANE (cost 0) ×3, MEMENTO_MORI (cost 1) ×4, OMNISLICE (cost 0) ×3, SKEWER (cost 0) ×2, STRIKE_SILENT (cost 1) ×4 | card/OMNISLICE ×5, card/STRIKE_SILENT ×11, champion continuation unresolved ×4, distinct lines ×5, forced ×8, unreconciled prompt ×2 |
| 10 · `d5f494e80cba` | 51 | 16 · ASCENDERS_BANE (cost 0) ×3, MEMENTO_MORI (cost 1) ×4, OMNISLICE (cost 0) ×3, SKEWER (cost 0) ×2, STRIKE_SILENT (cost 1) ×4 | card/OMNISLICE ×5, card/STRIKE_SILENT ×11, champion continuation unresolved ×4, distinct lines ×5, forced ×8, unreconciled prompt ×2 |
| 11 · `5909483d410a` | 34 | 0 | relic/RAINBOW_RING ×32, unreconciled prompt ×1, eruption ×1 |
| 12 · `edb17a0fea36` | 59 | 0 | relic/RAINBOW_RING ×51, selection operation ×1, unreconciled prompt ×4, eruption ×3 |
| 13 · `4fc437b3c57b` | 67 | 27 · relic BOOMING_CONCH ×27 | card/DEFEND_SILENT ×24, champion continuation unresolved ×1, distinct lines ×1, forced ×6, unreconciled prompt ×3, eruption ×5 |
| 14 · `e648f3d91aac` | 44 | 24 · relic STRIKE_DUMMY ×24 | card/PROWESS ×2, champion continuation unresolved ×2, distinct lines ×3, forced ×8, no certified survival ×2, uncertified root at cap ×1, unreconciled prompt ×2 |
| 15 · `a22ea44ab9ff` | 48 | 27 · relic STRIKE_DUMMY ×27 | card/PROWESS ×6, champion continuation unresolved ×3, distinct lines ×1, forced ×5, no certified survival ×1, uncertified root at cap ×1, unreconciled prompt ×1, eruption ×3 |
| 16 · `7dc9cfa810ec` | 64 | 0 | player power/RETAIN_HAND ×5, relic/TOUGH_BANDAGES ×51, unreconciled prompt ×4, eruption ×4 |
| 17 · `1309c0bb4832` | 63 | 0 | player power/RETAIN_HAND ×6, relic/TOUGH_BANDAGES ×52, unreconciled prompt ×3, eruption ×2 |
| 18 · `2be1e8c226e9` | 37 | 0 | relic/FRESNEL_LENS ×30, unreconciled prompt ×3, eruption ×4 |
| 19 · `5994c9f03ba5` | 29 | 0 | relic/FRESNEL_LENS ×25, eruption ×4 |

## Verification and reproduction

The host SHA-256 was `7408d040c28416331279a84e299b52ff35086d80b4cb9711aefd0f91168d8f20`. The local Linux game DLL was `f4da33f492d29236cde918c0458f6ec72a757b621c688820a77f441aca29a70b`. The original Helmer report records `14b57dbaee1b58cb919625a662831054fd714b3b75b13b7449eac0e95b98a3e4`. We checked the local pre-fix run against all 200 archived receipts. Opening digests, exit outcomes, audit and gate counts, per-choice activation, changed physical moves and individual world scores all matched. Seventeen logged four-world means differed by at most 2.85 × 10⁻¹⁴. The local controls also matched across revisions on every non-timing receipt field and all 3,891 activation flags. A separate replay of all 100 control fights hashed each pre-action board digest, physical command, stable decision record (omitting only the two timing fields) and post-action board digest. All 3,891 decisions gave byte-identical per-fight transcripts across revisions. The combined transcript digest list has SHA-256 `ed8f2da9d657f4a72f252745a30414f9f61cda794fedf12932c4cf81be987094`.

The separate flags-off probe ran against an archive of the original `b91f56b` Python sources and the fixed sources. All nine v5/v6.1/v6.2 transcripts matched byte for byte across 369 physical decisions per checkout, including actions, board digests, stable decision records and config metadata. The combined SHA-256 reproduced the original `9916973a980937d5abe29c5ad4ffa9f152a920cdc3902b438fd18ac181a6dff7`. All ten protected challenger files matched the raw Git blobs at `efd9877`.

The full Python suite passed all 619 tests in 457.68 s with the native host, observer and fixture namespace mapper enabled. The five receipt-backed regression cases exercise the reranker with the recorded world scores. A separate rerun of the two-turn unit tests and native leakage fixture passed all 11 cases. Ruff reported zero findings under `src/` and `tests/`.

With the repository-local .NET SDK and Linux game library available, set `CSV2DEV_HOST` to the Curriculum DLL above and `CSV2DEV_OBSERVER` to the compiled CombatV2Observer. The following commands reproduce the fixed run and summarize either set of receipts. For the local baseline, run the benchmark from the parent revision using the same environment. No evaluation panel is part of the benchmark.

```sh
export PYTHONPATH="src:tests:docs/combat-search-v2/probes"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
PYTEST_ADDOPTS="-p v6_fixture_seeds" .venv/bin/pytest -q
.venv/bin/ruff check src/ tests/
.venv/bin/python docs/combat-search-v2/probes/two_turn_fights.py fixed.jsonl.gz --workers 12
.venv/bin/python docs/combat-search-v2/probes/two_turn_report.py fixed.jsonl.gz
.venv/bin/python docs/combat-search-v2/probes/two_turn_parity.py off.json
```

[Omarchy pre-fix native receipts](two-turn-pilot-v2-baseline.jsonl.gz) · [Omarchy fixed native receipts](two-turn-pilot-v2-receipts.jsonl.gz) · [Original pilot report and receipts](two-turn-pilot-report.md)
