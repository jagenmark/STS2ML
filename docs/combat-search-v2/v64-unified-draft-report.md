# Silent A10 v6.4 unified draft

**Retain the Fan-fixed control for the upcoming release gate.** Arm A lost 2.72 mean floors against control (95% paired CI −3.72 to −1.73), and Arm B lost 2.51 (−3.51 to −1.50). Control cleared Act 2 on 24 of 384 starts, compared with 13 for each treatment. B reached seven Act 3 bosses and recorded the only full win. Its direct advantage over A was 0.22 floors (−0.32 to +0.77), which leaves the size-coefficient choice uncertain. Neither unified arm qualifies for promotion on this development panel.

The draft changes took effect. Control chose Grand Finale in 40/40 reward appearances. A and B each chose it in 0/31. Backflip rose from 64/331 (19.3%) to 190/276 (68.8%) and 181/269 (67.3%). Calculated Gamble went from 0/103 to 94/95 and 98/99. Both treatments took Piercing Wail in more than 96% of its reward appearances, and neither took Skewer. Control cleared Act 1 on 235 starts, A on 175 and B on 180. These comparisons measure the combined valuation change. They cannot identify a single card as the cause of the progression loss.

## Paired progression

| Outcome | Control | A · −1.65 | B · zero |
| --- | --- | --- | --- |
| Natural starts | 384 | 384 | 384 |
| Mean global floor | 24.055 | 21.333 | 21.549 |
| Δ floor vs control [95% paired CI] | — | -2.72 [-3.72, -1.73] | -2.51 [-3.51, -1.50] |
| Floor W/L/T vs control | — | 88/153/143 | 82/151/151 |
| Two-sided exact sign p | — | 3.383e-05 | 7.263e-06 |
| Act 1 clears | 235 | 175 | 180 |
| Act 2 boss entries | 104 | 70 | 68 |
| Act 2 clears | 24 | 13 | 13 |
| CRUSHER+ROCKET clears/entries | 2/32 (6.2%) | 3/23 (13.0%) | 4/27 (14.8%) |
| KNOWLEDGE_DEMON clears/entries | 8/31 (25.8%) | 3/20 (15.0%) | 3/16 (18.8%) |
| THE_INSATIABLE clears/entries | 14/41 (34.1%) | 7/27 (25.9%) | 6/25 (24.0%) |
| Act 3 boss entries | 9 | 3 | 7 |
| Full wins | 0 | 0 | 1 |
| Combat latency p50 / p95, ms | 2.841 / 57.731 | 1.706 / 43.210 | 1.715 / 43.221 |
| Native matches / mismatches / unresolved | 69,255 / 0 / 6,343 | 52,115 / 0 / 7,024 | 51,057 / 0 / 6,886 |

Direct B minus A paired floor difference was +0.22 [-0.32, +0.77]. W/L/T was 53/57/274 with exact p = 0.775.

The floor endpoint is 17 × (act − 1) + floor. The interval resamples paired starts within mode 50,000 times with analysis RNG 621. The sign test excludes ties. Boss rates use the number of entrants in that arm. Latency pools physical combat decisions and includes the read-only logging hook. Native counts span the full run wherever search can project and compare the executed step. An unresolved step crossed a simulator boundary.

## Deck size and skips

| Outcome | Control | A · −1.65 | B · zero |
| --- | --- | --- | --- |
| Act 1 final observed deck size (starts) | 21.46 (384) | 21.58 (384) | 22.10 (384) |
| Act 1 optional rewards skipped | 222/2844 (7.8%) | 137/2728 (5.0%) | 46/2739 (1.7%) |
| Act 2 final observed deck size (starts) | 26.58 (235) | 27.05 (175) | 29.02 (180) |
| Act 2 optional rewards skipped | 82/1045 (7.8%) | 141/757 (18.6%) | 27/759 (3.6%) |
| Act 3 final observed deck size (starts) | 32.12 (24) | 32.38 (13) | 36.85 (13) |
| Act 3 optional rewards skipped | 9/82 (11.0%) | 6/38 (15.8%) | 0/47 (0.0%) |

Each reached act contributes its last publicly observed deck count. Each legal optional card-reward decision contributes once to the skip denominator.

## Card rewards

Cells show picked / offered (pick rate). A dash denotes zero offers.

| Card | Control | A · −1.65 | B · zero |
| --- | --- | --- | --- |
| Grand Finale | 40/40 (100.0%) | 0/31 (0.0%) | 0/31 (0.0%) |
| Bury | 2/2 (100.0%) | 0/1 (0.0%) | 0/1 (0.0%) |
| Neurosurge | 1/1 (100.0%) | 0/2 (0.0%) | 0/2 (0.0%) |
| Friendship | 0/0 (—) | 0/0 (—) | 0/0 (—) |
| Reap | 1/1 (100.0%) | 2/2 (100.0%) | 2/2 (100.0%) |
| Bloodletting | 0/0 (—) | 0/0 (—) | 0/0 (—) |
| Skewer | 119/122 (97.5%) | 0/110 (0.0%) | 0/111 (0.0%) |
| Bubble Bubble | 137/138 (99.3%) | 55/128 (43.0%) | 50/121 (41.3%) |
| Afterimage | 0/35 (0.0%) | 26/31 (83.9%) | 24/29 (82.8%) |
| Well-Laid Plans | 0/42 (0.0%) | 22/35 (62.9%) | 19/32 (59.4%) |
| Tools of the Trade | 0/28 (0.0%) | 19/30 (63.3%) | 20/27 (74.1%) |
| Calculated Gamble | 0/103 (0.0%) | 94/95 (98.9%) | 98/99 (99.0%) |
| Expose | 0/116 (0.0%) | 87/104 (83.7%) | 86/105 (81.9%) |
| Piercing Wail | 0/320 (0.0%) | 277/287 (96.5%) | 270/279 (96.8%) |
| Blur | 1/98 (1.0%) | 5/95 (5.3%) | 6/95 (6.3%) |
| Dodge and Roll | 0/329 (0.0%) | 50/302 (16.6%) | 74/300 (24.7%) |
| Footwork | 34/113 (30.1%) | 55/108 (50.9%) | 62/109 (56.9%) |
| Backflip | 64/331 (19.3%) | 190/276 (68.8%) | 181/269 (67.3%) |
| Accelerant | 45/90 (50.0%) | 25/83 (30.1%) | 24/86 (27.9%) |
| Bouncing Flask | 25/116 (21.6%) | 32/100 (32.0%) | 33/100 (33.0%) |
| Corrosive Wave | 0/43 (0.0%) | 28/32 (87.5%) | 23/27 (85.2%) |
| Pact's End | 2/2 (100.0%) | 1/1 (100.0%) | 1/1 (100.0%) |
| Acrobatics | 0/113 (0.0%) | 93/109 (85.3%) | 94/109 (86.2%) |
| Predator | 190/327 (58.1%) | 190/300 (63.3%) | 192/300 (64.0%) |

## Rewards, shops, and bundles

Cells show picked / offered (pick rate). A dash denotes zero offers.

| Card | Control | A · −1.65 | B · zero |
| --- | --- | --- | --- |
| Grand Finale | 41/56 (73.2%) | 0/45 (0.0%) | 0/43 (0.0%) |
| Bury | 2/2 (100.0%) | 0/1 (0.0%) | 0/1 (0.0%) |
| Neurosurge | 1/1 (100.0%) | 0/2 (0.0%) | 0/2 (0.0%) |
| Friendship | 0/0 (—) | 0/0 (—) | 0/0 (—) |
| Reap | 1/1 (100.0%) | 2/2 (100.0%) | 2/2 (100.0%) |
| Bloodletting | 0/0 (—) | 0/0 (—) | 0/0 (—) |
| Skewer | 122/173 (70.5%) | 1/156 (0.6%) | 1/157 (0.6%) |
| Bubble Bubble | 163/171 (95.3%) | 71/156 (45.5%) | 67/151 (44.4%) |
| Afterimage | 0/40 (0.0%) | 26/35 (74.3%) | 24/33 (72.7%) |
| Well-Laid Plans | 0/45 (0.0%) | 22/36 (61.1%) | 19/33 (57.6%) |
| Tools of the Trade | 0/30 (0.0%) | 19/32 (59.4%) | 20/29 (69.0%) |
| Calculated Gamble | 0/139 (0.0%) | 114/122 (93.4%) | 119/128 (93.0%) |
| Expose | 1/157 (0.6%) | 109/141 (77.3%) | 107/139 (77.0%) |
| Piercing Wail | 1/388 (0.3%) | 335/348 (96.3%) | 330/344 (95.9%) |
| Blur | 1/144 (0.7%) | 5/135 (3.7%) | 7/132 (5.3%) |
| Dodge and Roll | 0/420 (0.0%) | 57/374 (15.2%) | 85/373 (22.8%) |
| Footwork | 35/198 (17.7%) | 64/188 (34.0%) | 82/191 (42.9%) |
| Backflip | 71/414 (17.1%) | 224/341 (65.7%) | 231/343 (67.3%) |
| Accelerant | 80/181 (44.2%) | 38/169 (22.5%) | 46/177 (26.0%) |
| Bouncing Flask | 26/147 (17.7%) | 33/125 (26.4%) | 41/125 (32.8%) |
| Corrosive Wave | 0/51 (0.0%) | 30/37 (81.1%) | 25/32 (78.1%) |
| Pact's End | 2/2 (100.0%) | 1/1 (100.0%) | 1/1 (100.0%) |
| Acrobatics | 0/153 (0.0%) | 110/146 (75.3%) | 115/149 (77.2%) |
| Predator | 195/442 (44.1%) | 243/399 (60.9%) | 260/402 (64.7%) |

Shop denominators count each stocked slot once per shop visit, including unaffordable cards. Bundles count every card on every offer, including every card in the mandatory chosen bundle. The archive retains each public prompt, option index, upgrade flag, price where applicable, and the actual action. Different routes and survival change which offers an arm reaches.

## Qualification and reproduction

The policies and cohort were committed at `38e224b18099df8e4e0405ddbcbe27407dcc2029` before the first CSV9DEV start. All three used the unmodified v0.111.0 host, 12 workers, and one OpenBLAS and OpenMP thread each. The lock digest was `afe45cafa3e320e120f5bea8752e3fb89122f8aa7c98fcb7032e05153cd5d777`. No seed name or xxHash64 collided with the 67,785 historical or reserved names checked. No reserved lobby was run.

The Fan discrepancy came from a wax Ornamental Fan awarded by Toy Box. It triggered normally until the third combat ended. After the wax melted, the host still displayed the final counter (1) and Normal status, but stopped triggering the relic. The opt-in search follows the publicly observed wax batch and Toy Box counter resets. On the historical CSV8DEV_DEFAULT_0032 command stream, the frozen model reproduced all 13 mismatches at the same public before/after hashes. The fixed predictor matched every one of those boards. A fresh policy-controlled replay reached the Act 2 boss with 59 native matches, zero mismatches and 15 unresolved transitions. The fixture covers the original 13 steps even where the corrected search chose different actions on the fresh replay.

The static exporter read 596 base card models and their 557 first upgrades from the pinned game library. The sanity sweep covered all 1,153 variants, including 23 distinct Star-cost cards, 37 multiplayer-only cards and ten energy-X cards. It checked finite scores and rejection of the defined traps. Energy, current card stats, keywords, upgrade level, and price come from public fields when supplied. Static English titles resolve merchant offers without an ID. Actual upgrade keyword sets supply the Retain addition on Calculated Gamble+. No native host modification is required. The Python package includes the catalog. Its gzip SHA-256 is `04dbff028826ec9a97726fc2ba19e62c67e7da7f90c8475638639f096a7de30d`. The standalone C# exporter in `probes/card_catalog` references the pinned binaries read-only and enumerates canonical models offline.

All ten released v5 challenger files matched the efd9877 blobs. All 16 historical builders reproduced every output bundle byte against f8e0b00. The historical CSV2DEV off, active and shadow receipts matched on all 24 episodes per mode. The full pinned-host suite returned **624 passed, 1 skipped** in 293.86 seconds. The guard skipped the archived FINAL768 fixture. Ruff checked 115 Python files in src and tests with zero findings.

Independent CSV2DEV replays used the released v5 checkpoint from efd9877 and the Arm 4 + Kaiser v63 configuration from f8e0b00, with both v6.4 flags off. All 24 full physical transcripts per policy matched their respective checkout, including public boards, executed commands, legal actions, floating-point score bytes and terminal outcomes.

After the locked run, a code review added conditional estimates for Right Hand Hand with summon support, Multi-Cast with orb sources, and Heavenly Drill at its four-energy threshold. The implementation changes raw scores only for those three cards. Across the 768 unified starts, only CSV9DEV_DEFAULT_0005 offered one of them (Right Hand Hand, once per arm). Both affected starts replayed with identical commands, offers, deck counts, native counters and progression. The published latency distribution is from the pre-registered run.

Run the collector with the pinned CPU interpreter, local runtime links, CSV2DEV_HOST set to the pinned host, both thread limits set to one, and src on PYTHONPATH. The analysis takes the compact receipt archive as input.

~~~powershell
python docs/combat-search-v2/probes/v64.py artifacts/v64/dev --workers 12
python docs/combat-search-v2/probes/report_v64.py docs/combat-search-v2/v64-unified-draft-receipts.zip docs/combat-search-v2/v64-unified-draft.json
~~~

[Protocol](v64-protocol.md) · [Cohort lock](csv9dev-lock.json) · [Machine-readable results](v64-unified-draft.json) · [Compact receipts](v64-unified-draft-receipts.zip)
