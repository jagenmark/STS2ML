# Silent A10 v6.5 development ablation

**Advance Arm A as the challenger against Control on FINAL768B.** Its mean was 25.000 floors against 25.029 for Control, a paired difference of −0.03 floors (95% CI −0.32 to +0.26). Both cleared Act 2 on 25/384 starts, reached 11 Act 3 bosses and recorded zero full wins. Arm A eliminated all avoidable blocked acquisitions (55 in Control, zero in A), kept search coverage, and cleared Act 1 on four fewer starts. Its value as a challenger comes from the eligibility improvement with similar observed progression. This development cohort has established neither a floor advantage nor formal noninferiority.

Arm B lost 2.45 floors against Control (95% CI −3.38 to −1.53). It cleared Act 1 on 210 starts against Control’s 257 and converted 8/73 Act 2 bosses against 25/109. Its Act 1 shortfall narrowed from 55 starts in CSV9DEV to 47 in CSV10DEV, while native matches per 100 combat decisions rose from 51.76 for historical v6.4 B to 57.95 for v6.5 B. Current Control reached 72.33. Thus Act 1 survival and search coverage recovered only partially. Historical and current panels use different seeds.

Arm B took Piercing Wail on 87/286 reward offers (30.4%), Calculated Gamble on 59/106 (55.7%), Skewer on 24/95 (25.3%) and Accelerant on 29/84 (34.5%). Skewer recovered from 0/111 and Accelerant improved from 24/86 (27.9%) in historical v6.4 B. Wave fell from 23/27 to 0/29 despite its positive synthetic engine grade. Arm A took Afterimage on 44/44 offers and Well-Laid Plans on 29/31. Neither treatment picked a blocked card on an observed acquisition prompt.

The registered Control oracle produced one mismatch on a forced end turn. A controlled native replay reproduced its two possible HP outcomes from the same public board. The independent audit below accounts for hidden draw order and preserves the registered verdicts and progression.

## Paired CSV10DEV progression

| Outcome | Control | A · trap cleanup | B · role saturation |
| --- | --- | --- | --- |
| Natural starts | 384 | 384 | 384 |
| Mean global floor | 25.029 | 25.000 | 22.578 |
| Difference vs Control [95% paired CI] | — | -0.03 [-0.32, +0.26] | -2.45 [-3.38, -1.53] |
| Floor W/L/T vs Control | — | 30/28/326 | 83/169/132 |
| Two-sided exact sign p | — | 0.89568 | 6.4581e-08 |
| Act 1 clears | 257 | 253 | 210 |
| Act 2 boss entries | 109 | 111 | 73 |
| Act 2 clears | 25 | 25 | 8 |
| CRUSHER+ROCKET clears / entries | 9/43 (20.9%) | 10/44 (22.7%) | 3/29 (10.3%) |
| KNOWLEDGE_DEMON clears / entries | 8/35 (22.9%) | 8/32 (25.0%) | 4/28 (14.3%) |
| THE_INSATIABLE clears / entries | 8/31 (25.8%) | 7/35 (20.0%) | 1/16 (6.2%) |
| Act 3 boss entries | 11 | 11 | 4 |
| Full wins | 0 | 0 | 0 |
| Combat latency p50 / p95 (ms) | 2.998 / 59.382 | 3.028 / 59.383 | 1.994 / 48.724 |
| Registered native matches / mismatches / unresolved | 71,666 / 1 / 6,330 | 72,496 / 0 / 6,335 | 55,951 / 0 / 7,011 |
| Combat decisions | 99,088 | 100,012 | 96,558 |
| Native matches per 100 combat decisions | 72.33 | 72.49 | 57.95 |
| Independent native matches / mismatches / unresolved | 71,662 / 0 / 6,335 | 72,496 / 0 / 6,335 | 55,951 / 0 / 7,011 |

B minus A was -2.42 [-3.36, -1.49] floors, with W/L/T 87/160/137 and exact sign p = 3.9664e-06.

Global floor is 17 × (act − 1) + floor. The 95% intervals use 50,000 paired bootstrap resamples within act-list mode. Exact two-sided sign tests omit tied seeds. Boss conversion uses entrants to that boss as its denominator. Native unresolved counts include simulator boundaries. Latency pools physical combat decisions.

## Deck size and optional reward skips

| Outcome | Control | A · trap cleanup | B · role saturation |
| --- | --- | --- | --- |
| Act 1 final observed deck size | 21.38 (n=384) | 21.39 (n=384) | 22.73 (n=384) |
| Act 1 reward skips | 240/2858 (8.4%) | 226/2856 (7.9%) | 59/2812 (2.1%) |
| Act 2 final observed deck size | 26.55 (n=257) | 26.73 (n=253) | 28.83 (n=210) |
| Act 2 reward skips | 107/1164 (9.2%) | 110/1165 (9.4%) | 87/883 (9.9%) |
| Act 3 final observed deck size | 32.80 (n=25) | 32.20 (n=25) | 36.62 (n=8) |
| Act 3 reward skips | 6/92 (6.5%) | 6/90 (6.7%) | 2/31 (6.5%) |

## Pre-flight scoring

Columns use three max energy, unupgraded offers, and skip = 0. The Act 1 deck has five Strikes, five Defends, Neutralize, Survivor and Ascender’s Bane. Act 2 adds Dash, Predator, Dagger Spray, Poisoned Stab, Skewer, Acrobatics and Backflip. Act 3 also adds Calculated Gamble, Acrobatics, Backflip, Dagger Throw, Adrenaline, Bouncing Flask and Footwork. “Blocked” denotes the hard acquisition score of −1,000,000.

| Card | Act 1 floor 2 | Act 2 floor 8 | Act 3 floor 10 |
| --- | ---: | ---: | ---: |
| Predator | 16.36 | -0.48 | -4.01 |
| Dash | 9.00 | -1.73 | -0.33 |
| Dagger Spray | 17.14 | -1.02 | -1.28 |
| Poisoned Stab | 10.50 | 1.23 | 1.04 |
| Skewer | 11.90 | -3.53 | -3.77 |
| Piercing Wail | 2.19 | 5.20 | 3.53 |
| Calculated Gamble | 5.62 | 3.77 | -7.23 |
| Acrobatics | 6.60 | 1.92 | -7.85 |
| Expose | 4.05 | 7.46 | 5.70 |
| Backflip | 5.00 | 1.74 | -2.87 |
| Afterimage | 11.00 | 19.00 | 11.00 |
| Well-Laid Plans | 7.83 | 7.13 | 7.05 |
| Footwork | 8.46 | 15.60 | 5.07 |
| Accelerant | -27.00 | 22.80 | 46.00 |
| Blur | 2.35 | 10.20 | 5.13 |
| Dodge and Roll | 0.86 | 1.18 | 5.53 |
| Pact's End | -30.00 | -30.00 | 11.46 |
| Corrosive Wave | -14.00 | -3.52 | 10.37 |
| Tools of the Trade | 7.80 | 6.77 | 4.05 |
| Bury | Blocked | Blocked | Blocked |
| Friendship | -7.50 | -7.50 | -7.50 |
| Defragment | Blocked | Blocked | Blocked |
| Zap | 0.00 | 0.00 | 0.00 |
| Ball Lightning | 15.75 | 5.06 | 4.83 |
| Reave | 13.50 | -1.78 | -2.10 |
| Reap | 17.64 | -0.89 | -1.38 |
| High Five | Blocked | Blocked | Blocked |
| Neurosurge | Blocked | Blocked | Blocked |
| Shroud | Blocked | Blocked | Blocked |
| Bulwark | Blocked | Blocked | Blocked |
| Seven Stars | Blocked | Blocked | Blocked |

| Corrosive Wave hand | N including Wave | Affordable sources | P(hit) | E[draw] | Raw score |
| --- | ---: | ---: | ---: | ---: | ---: |
| one source | 20 | 1 | 0.2105 | 0.6316 | -7.60 |
| engine | 28 | 7 | 0.7239 | 2.5185 | 10.37 |

The hand model conditions on holding Wave. It counts direct draw sources individually playable after spending one energy on Wave. It excludes delayed draws and triggered powers. The expectation describes cards drawn by eligible handmates before any competition between multiple paid draw plays. Low hit probability incurs a dead-hand penalty and a strictly negative grade below 0.58.

## Eligibility audit

| Acquisition audit | Control | A · trap cleanup | B · role saturation |
| --- | --- | --- | --- |
| Ineligible card appearances | 377 | 380 | 331 |
| Ineligible copies acquired | 55 | 0 | 0 |
| Avoidable ineligible acquisitions | 55 | 0 | 0 |
| Mandatory ineligible acquisitions | 0 | 0 | 0 |

The audit rechecks the actual public energy and channel-source count at each decision. A mandatory choice is avoidable if a legal alternative contains fewer blocked cards. Shop audit counts include repeated visits to stock within the same shop.

## Reward picks per offer

| Card | v6.4 B · CSV9DEV | Control | A · trap cleanup | B · role saturation |
| --- | --- | --- | --- | --- |
| Grand Finale | 0/31 (0.0%) | 39/39 (100.0%) | 0/40 (0.0%) | 0/27 (0.0%) |
| Bury | 0/1 (0.0%) | 0/0 (—) | 1/1 (100.0%) | 0/1 (0.0%) |
| Neurosurge | 0/2 (0.0%) | 1/1 (100.0%) | 0/2 (0.0%) | 0/1 (0.0%) |
| Friendship | 0/0 (—) | 4/4 (100.0%) | 4/4 (100.0%) | 0/3 (0.0%) |
| Reap | 2/2 (100.0%) | 5/7 (71.4%) | 5/7 (71.4%) | 5/6 (83.3%) |
| Bloodletting | 0/0 (—) | 0/0 (—) | 0/0 (—) | 0/0 (—) |
| Skewer | 0/111 (0.0%) | 86/89 (96.6%) | 88/92 (95.7%) | 24/95 (25.3%) |
| Bubble Bubble | 50/121 (41.3%) | 115/115 (100.0%) | 111/111 (100.0%) | 32/93 (34.4%) |
| Afterimage | 24/29 (82.8%) | 0/46 (0.0%) | 44/44 (100.0%) | 28/32 (87.5%) |
| Well-Laid Plans | 19/32 (59.4%) | 0/28 (0.0%) | 29/31 (93.5%) | 13/28 (46.4%) |
| Tools of the Trade | 20/27 (74.1%) | 0/51 (0.0%) | 0/50 (0.0%) | 39/48 (81.2%) |
| Calculated Gamble | 98/99 (99.0%) | 0/112 (0.0%) | 0/113 (0.0%) | 59/106 (55.7%) |
| Expose | 86/105 (81.9%) | 0/103 (0.0%) | 0/104 (0.0%) | 37/83 (44.6%) |
| Piercing Wail | 270/279 (96.8%) | 0/328 (0.0%) | 0/326 (0.0%) | 87/286 (30.4%) |
| Blur | 6/95 (6.3%) | 2/108 (1.9%) | 2/110 (1.8%) | 35/103 (34.0%) |
| Dodge and Roll | 74/300 (24.7%) | 0/355 (0.0%) | 0/360 (0.0%) | 88/338 (26.0%) |
| Footwork | 62/109 (56.9%) | 39/111 (35.1%) | 41/111 (36.9%) | 78/116 (67.2%) |
| Backflip | 181/269 (67.3%) | 78/347 (22.5%) | 78/352 (22.2%) | 167/313 (53.4%) |
| Accelerant | 24/86 (27.9%) | 50/86 (58.1%) | 47/86 (54.7%) | 29/84 (34.5%) |
| Bouncing Flask | 33/100 (33.0%) | 25/124 (20.2%) | 25/126 (19.8%) | 25/114 (21.9%) |
| Corrosive Wave | 23/27 (85.2%) | 0/33 (0.0%) | 0/31 (0.0%) | 0/29 (0.0%) |
| Pact's End | 1/1 (100.0%) | 0/0 (—) | 0/0 (—) | 0/0 (—) |
| Acrobatics | 94/109 (86.2%) | 0/112 (0.0%) | 0/115 (0.0%) | 62/102 (60.8%) |
| Predator | 192/300 (64.0%) | 195/361 (54.0%) | 196/356 (55.1%) | 157/327 (48.0%) |
| Afterlife | 0/0 (—) | 0/8 (0.0%) | 0/8 (0.0%) | 0/8 (0.0%) |
| Astral Pulse | 0/0 (—) | 1/3 (33.3%) | 0/3 (0.0%) | 0/3 (0.0%) |
| Barrage | 0/1 (0.0%) | 0/3 (0.0%) | 0/3 (0.0%) | 1/3 (33.3%) |
| Blight Strike | 0/1 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) | 0/3 (0.0%) |
| Bone Shards | 0/1 (0.0%) | 0/1 (0.0%) | 0/1 (0.0%) | 0/2 (0.0%) |
| Bulwark | 0/1 (0.0%) | 1/1 (100.0%) | 0/1 (0.0%) | 0/1 (0.0%) |
| Calcify | 0/0 (—) | 0/3 (0.0%) | 0/3 (0.0%) | 0/2 (0.0%) |
| Capacitor | 0/1 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) | 0/1 (0.0%) |
| Clash | 0/0 (—) | 0/0 (—) | 0/0 (—) | 0/0 (—) |
| Cleanse | 0/1 (0.0%) | 0/3 (0.0%) | 0/3 (0.0%) | 0/3 (0.0%) |
| Cloak of Stars | 0/2 (0.0%) | 2/3 (66.7%) | 0/3 (0.0%) | 0/3 (0.0%) |
| Compile Driver | 2/3 (66.7%) | 1/2 (50.0%) | 0/2 (0.0%) | 0/2 (0.0%) |
| Countdown | 0/5 (0.0%) | 0/6 (0.0%) | 0/7 (0.0%) | 0/5 (0.0%) |
| Crescent Spear | 0/1 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) |
| Deathbringer | 0/4 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) |
| Death's Door | 0/1 (0.0%) | 0/4 (0.0%) | 0/5 (0.0%) | 0/1 (0.0%) |
| Devour Life | 0/0 (—) | 0/2 (0.0%) | 0/2 (0.0%) | 0/0 (—) |
| Dirge | 0/4 (0.0%) | 0/3 (0.0%) | 0/3 (0.0%) | 0/0 (—) |
| End of Days | 0/0 (—) | 0/2 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) |
| Fetch | 0/1 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) | 0/1 (0.0%) |
| Flatten | 0/3 (0.0%) | 0/4 (0.0%) | 0/5 (0.0%) | 0/4 (0.0%) |
| Focused Strike | 0/0 (—) | 0/2 (0.0%) | 0/1 (0.0%) | 0/0 (—) |
| Furnace | 0/0 (—) | 0/1 (0.0%) | 0/1 (0.0%) | 0/1 (0.0%) |
| Hailstorm | 0/0 (—) | 0/1 (0.0%) | 0/1 (0.0%) | 0/2 (0.0%) |
| High Five | 0/2 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) | 0/0 (—) |
| Hotfix | 0/0 (—) | 0/2 (0.0%) | 0/2 (0.0%) | 0/1 (0.0%) |
| Invoke | 0/5 (0.0%) | 2/3 (66.7%) | 0/3 (0.0%) | 0/3 (0.0%) |
| Loop | 0/0 (—) | 0/1 (0.0%) | 0/0 (—) | 0/0 (—) |
| Necro Mastery | 0/2 (0.0%) | 0/3 (0.0%) | 0/3 (0.0%) | 0/2 (0.0%) |
| Negative Pulse | 0/5 (0.0%) | 0/4 (0.0%) | 0/4 (0.0%) | 0/3 (0.0%) |
| No Escape | 0/2 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) |
| Oblivion | 0/3 (0.0%) | 0/3 (0.0%) | 0/3 (0.0%) | 0/2 (0.0%) |
| Panic Button | 0/0 (—) | 0/0 (—) | 0/0 (—) | 0/0 (—) |
| Particle Wall | 0/1 (0.0%) | 1/1 (100.0%) | 0/1 (0.0%) | 0/0 (—) |
| Poke | 0/3 (0.0%) | 0/6 (0.0%) | 0/6 (0.0%) | 0/7 (0.0%) |
| Pull Aggro | 0/4 (0.0%) | 0/6 (0.0%) | 0/6 (0.0%) | 0/10 (0.0%) |
| Rattle | 0/2 (0.0%) | 0/1 (0.0%) | 0/1 (0.0%) | 0/0 (—) |
| Reanimate | 0/2 (0.0%) | 0/1 (0.0%) | 0/1 (0.0%) | 0/0 (—) |
| Reaper Form | 0/2 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) | 0/1 (0.0%) |
| Refine Blade | 0/1 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) | 0/3 (0.0%) |
| Right Hand Hand | 0/1 (0.0%) | 4/4 (100.0%) | 0/4 (0.0%) | 0/4 (0.0%) |
| Royal Gamble | 0/0 (—) | 0/0 (—) | 0/0 (—) | 0/1 (0.0%) |
| Sacrifice | 0/1 (0.0%) | 0/7 (0.0%) | 0/7 (0.0%) | 0/6 (0.0%) |
| Scourge | 0/4 (0.0%) | 0/7 (0.0%) | 0/7 (0.0%) | 0/3 (0.0%) |
| Seeking Edge | 0/0 (—) | 0/1 (0.0%) | 0/0 (—) | 0/0 (—) |
| Shroud | 0/3 (0.0%) | 1/2 (50.0%) | 0/2 (0.0%) | 0/3 (0.0%) |
| Sic 'Em | 0/0 (—) | 0/5 (0.0%) | 0/6 (0.0%) | 0/5 (0.0%) |
| Snap | 0/3 (0.0%) | 0/3 (0.0%) | 0/3 (0.0%) | 0/4 (0.0%) |
| Spoils of Battle | 0/0 (—) | 0/4 (0.0%) | 0/5 (0.0%) | 0/4 (0.0%) |
| Spur | 0/0 (—) | 0/2 (0.0%) | 0/2 (0.0%) | 0/4 (0.0%) |
| Squeeze | 0/3 (0.0%) | 0/0 (—) | 0/0 (—) | 0/2 (0.0%) |
| Sword Sage | 0/0 (—) | 0/1 (0.0%) | 0/1 (0.0%) | 0/0 (—) |
| Tesla Coil | 0/0 (—) | 0/2 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) |
| The Gambit | 0/0 (—) | 0/0 (—) | 0/0 (—) | 0/0 (—) |
| Thunder | 0/0 (—) | 0/2 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) |
| Time's Up | 0/1 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) | 0/3 (0.0%) |
| Wrought in War | 0/1 (0.0%) | 1/1 (100.0%) | 0/1 (0.0%) | 0/1 (0.0%) |

## Picks across rewards, shops and bundles

| Card | v6.4 B · CSV9DEV | Control | A · trap cleanup | B · role saturation |
| --- | --- | --- | --- | --- |
| Grand Finale | 0/43 (0.0%) | 40/51 (78.4%) | 0/52 (0.0%) | 0/37 (0.0%) |
| Bury | 0/1 (0.0%) | 0/0 (—) | 1/1 (100.0%) | 0/1 (0.0%) |
| Neurosurge | 0/2 (0.0%) | 1/1 (100.0%) | 0/2 (0.0%) | 0/1 (0.0%) |
| Friendship | 0/0 (—) | 4/4 (100.0%) | 4/4 (100.0%) | 0/3 (0.0%) |
| Reap | 2/2 (100.0%) | 5/7 (71.4%) | 5/7 (71.4%) | 5/6 (83.3%) |
| Bloodletting | 0/0 (—) | 0/0 (—) | 0/0 (—) | 0/0 (—) |
| Skewer | 1/157 (0.6%) | 87/145 (60.0%) | 89/149 (59.7%) | 33/148 (22.3%) |
| Bubble Bubble | 67/151 (44.4%) | 145/152 (95.4%) | 144/150 (96.0%) | 49/126 (38.9%) |
| Afterimage | 24/33 (72.7%) | 2/48 (4.2%) | 46/46 (100.0%) | 29/34 (85.3%) |
| Well-Laid Plans | 19/33 (57.6%) | 0/33 (0.0%) | 30/36 (83.3%) | 13/31 (41.9%) |
| Tools of the Trade | 20/29 (69.0%) | 0/54 (0.0%) | 0/53 (0.0%) | 40/49 (81.6%) |
| Calculated Gamble | 119/128 (93.0%) | 2/151 (1.3%) | 2/152 (1.3%) | 80/148 (54.1%) |
| Expose | 107/139 (77.0%) | 3/141 (2.1%) | 3/142 (2.1%) | 46/116 (39.7%) |
| Piercing Wail | 330/344 (95.9%) | 2/431 (0.5%) | 2/431 (0.5%) | 112/377 (29.7%) |
| Blur | 7/132 (5.3%) | 2/151 (1.3%) | 2/153 (1.3%) | 45/137 (32.8%) |
| Dodge and Roll | 85/373 (22.8%) | 0/452 (0.0%) | 0/456 (0.0%) | 111/423 (26.2%) |
| Footwork | 82/191 (42.9%) | 41/225 (18.2%) | 43/222 (19.4%) | 132/223 (59.2%) |
| Backflip | 231/343 (67.3%) | 84/432 (19.4%) | 84/437 (19.2%) | 210/388 (54.1%) |
| Accelerant | 46/177 (26.0%) | 108/205 (52.7%) | 104/205 (50.7%) | 65/191 (34.0%) |
| Bouncing Flask | 41/125 (32.8%) | 26/155 (16.8%) | 26/157 (16.6%) | 31/138 (22.5%) |
| Corrosive Wave | 25/32 (78.1%) | 0/42 (0.0%) | 0/40 (0.0%) | 0/37 (0.0%) |
| Pact's End | 1/1 (100.0%) | 0/0 (—) | 0/0 (—) | 0/0 (—) |
| Acrobatics | 115/149 (77.2%) | 1/142 (0.7%) | 1/147 (0.7%) | 76/129 (58.9%) |
| Predator | 260/402 (64.7%) | 198/465 (42.6%) | 199/461 (43.2%) | 209/422 (49.5%) |
| Afterlife | 0/0 (—) | 0/8 (0.0%) | 0/8 (0.0%) | 0/8 (0.0%) |
| Astral Pulse | 0/0 (—) | 1/3 (33.3%) | 0/3 (0.0%) | 0/3 (0.0%) |
| Barrage | 0/1 (0.0%) | 0/3 (0.0%) | 0/3 (0.0%) | 1/3 (33.3%) |
| Blight Strike | 0/1 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) | 0/3 (0.0%) |
| Bone Shards | 0/1 (0.0%) | 0/1 (0.0%) | 0/1 (0.0%) | 0/2 (0.0%) |
| Bulwark | 0/1 (0.0%) | 1/1 (100.0%) | 0/1 (0.0%) | 0/1 (0.0%) |
| Calcify | 0/0 (—) | 0/3 (0.0%) | 0/3 (0.0%) | 0/2 (0.0%) |
| Capacitor | 0/1 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) | 0/1 (0.0%) |
| Clash | 0/0 (—) | 0/0 (—) | 0/0 (—) | 0/0 (—) |
| Cleanse | 0/1 (0.0%) | 0/3 (0.0%) | 0/3 (0.0%) | 0/3 (0.0%) |
| Cloak of Stars | 0/2 (0.0%) | 2/3 (66.7%) | 0/3 (0.0%) | 0/3 (0.0%) |
| Compile Driver | 2/3 (66.7%) | 1/2 (50.0%) | 0/2 (0.0%) | 0/2 (0.0%) |
| Countdown | 0/5 (0.0%) | 0/6 (0.0%) | 0/7 (0.0%) | 0/5 (0.0%) |
| Crescent Spear | 0/1 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) |
| Deathbringer | 0/4 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) |
| Death's Door | 0/1 (0.0%) | 0/4 (0.0%) | 0/5 (0.0%) | 0/1 (0.0%) |
| Devour Life | 0/0 (—) | 0/2 (0.0%) | 0/2 (0.0%) | 0/0 (—) |
| Dirge | 0/4 (0.0%) | 0/3 (0.0%) | 0/3 (0.0%) | 0/0 (—) |
| End of Days | 0/0 (—) | 0/2 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) |
| Fetch | 0/1 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) | 0/1 (0.0%) |
| Flatten | 0/3 (0.0%) | 0/4 (0.0%) | 0/5 (0.0%) | 0/4 (0.0%) |
| Focused Strike | 0/0 (—) | 0/2 (0.0%) | 0/1 (0.0%) | 0/0 (—) |
| Furnace | 0/0 (—) | 0/1 (0.0%) | 0/1 (0.0%) | 0/1 (0.0%) |
| Hailstorm | 0/0 (—) | 0/1 (0.0%) | 0/1 (0.0%) | 0/2 (0.0%) |
| High Five | 0/2 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) | 0/0 (—) |
| Hotfix | 0/0 (—) | 0/2 (0.0%) | 0/2 (0.0%) | 0/1 (0.0%) |
| Invoke | 0/5 (0.0%) | 2/3 (66.7%) | 0/3 (0.0%) | 0/3 (0.0%) |
| Loop | 0/0 (—) | 0/1 (0.0%) | 0/0 (—) | 0/0 (—) |
| Necro Mastery | 0/2 (0.0%) | 0/3 (0.0%) | 0/3 (0.0%) | 0/2 (0.0%) |
| Negative Pulse | 0/5 (0.0%) | 0/4 (0.0%) | 0/4 (0.0%) | 0/3 (0.0%) |
| No Escape | 0/2 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) |
| Oblivion | 0/3 (0.0%) | 0/3 (0.0%) | 0/3 (0.0%) | 0/2 (0.0%) |
| Panic Button | 0/17 (0.0%) | 0/21 (0.0%) | 0/20 (0.0%) | 0/16 (0.0%) |
| Particle Wall | 0/1 (0.0%) | 1/1 (100.0%) | 0/1 (0.0%) | 0/0 (—) |
| Poke | 0/3 (0.0%) | 0/6 (0.0%) | 0/6 (0.0%) | 0/7 (0.0%) |
| Pull Aggro | 0/4 (0.0%) | 0/6 (0.0%) | 0/6 (0.0%) | 0/10 (0.0%) |
| Rattle | 0/2 (0.0%) | 0/1 (0.0%) | 0/1 (0.0%) | 0/0 (—) |
| Reanimate | 0/2 (0.0%) | 0/1 (0.0%) | 0/1 (0.0%) | 0/0 (—) |
| Reaper Form | 0/2 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) | 0/1 (0.0%) |
| Refine Blade | 0/1 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) | 0/3 (0.0%) |
| Right Hand Hand | 0/1 (0.0%) | 4/4 (100.0%) | 0/4 (0.0%) | 0/4 (0.0%) |
| Royal Gamble | 0/0 (—) | 0/0 (—) | 0/0 (—) | 0/1 (0.0%) |
| Sacrifice | 0/1 (0.0%) | 0/7 (0.0%) | 0/7 (0.0%) | 0/6 (0.0%) |
| Scourge | 0/4 (0.0%) | 0/7 (0.0%) | 0/7 (0.0%) | 0/3 (0.0%) |
| Seeking Edge | 0/0 (—) | 0/1 (0.0%) | 0/0 (—) | 0/0 (—) |
| Shroud | 0/3 (0.0%) | 1/2 (50.0%) | 0/2 (0.0%) | 0/3 (0.0%) |
| Sic 'Em | 0/0 (—) | 0/5 (0.0%) | 0/6 (0.0%) | 0/5 (0.0%) |
| Snap | 0/3 (0.0%) | 0/3 (0.0%) | 0/3 (0.0%) | 0/4 (0.0%) |
| Spoils of Battle | 0/0 (—) | 0/4 (0.0%) | 0/5 (0.0%) | 0/4 (0.0%) |
| Spur | 0/0 (—) | 0/2 (0.0%) | 0/2 (0.0%) | 0/4 (0.0%) |
| Squeeze | 0/3 (0.0%) | 0/0 (—) | 0/0 (—) | 0/2 (0.0%) |
| Sword Sage | 0/0 (—) | 0/1 (0.0%) | 0/1 (0.0%) | 0/0 (—) |
| Tesla Coil | 0/0 (—) | 0/2 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) |
| The Gambit | 0/40 (0.0%) | 0/37 (0.0%) | 0/38 (0.0%) | 0/30 (0.0%) |
| Thunder | 0/0 (—) | 0/2 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) |
| Time's Up | 0/1 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) | 0/3 (0.0%) |
| Wrought in War | 0/1 (0.0%) | 1/1 (100.0%) | 0/1 (0.0%) | 0/1 (0.0%) |

Reward denominators count card appearances. The combined table counts stocked slots once per shop visit, including unaffordable stock, and counts every card in each bundle. Routes and survival change which offers each policy reaches. The JSON includes counts by individual offer source.

## Native hidden-order differential

On CSV10DEV_DEFAULT_0147 at Act 2 floor 3, round 1 against two Exoskeletons, ending the turn was forced. The player had 49 HP, zero block, and I Am Invincible in a 16-card unordered draw pile. The frozen observer predicted 43 HP. When I Am Invincible was on top, it played automatically and the host returned 49 HP. Putting it last produced the predicted 43 HP. Both experiments replayed the same command prefix and public root hash before setting the test-only hidden permutation.

At audit commit `777516c8af3daded5043fcab0fd6ef54ebb81a9b`, a second observer identified mixed draw piles containing the autoplay card before requesting the successor. It labeled relevant end turns unresolved for either outcome. Across the 1,152 repeat starts, every executed command digest, offer, deck count, terminal outcome and frozen native verdict matched the registered run. The archive carries both complete passes. The published latency is from the registered pass.

| Pre-step boundary reclassification | Control | A · trap cleanup | B · role saturation |
| --- | --- | --- | --- |
| Previously matching end turns | 4 | 0 | 0 |
| Previously mismatching end turns | 1 | 0 | 0 |
| Previously unresolved end turns | 0 | 0 | 0 |

## Qualification and reproduction

The pre-registered policy and cohort commit was `d5bcad6d02a9636f9a4c63609205d4e3480b4f1b`. All 384 names and seed hashes were disjoint from 69,835 historical or reserved names. The collector checked both pinned runtime hashes and used twelve workers with one thread each for OpenBLAS and OpenMP.

All 19 previous builders reproduced every policy file byte for byte. The 10 released challenger files matched the Git blobs at efd9877. The 24 off, 24 active and 24 shadow CSV2DEV receipts were exact. Another 24 frozen-v5 and 24 Kaiser CSV2DEV transcripts matched their historical references. Four archived CSV9DEV starts per profile also matched Control and both v6.4 configurations on every deterministic receipt field.

Before the registered run, the full pinned-host suite passed 636 tests. After adding the hidden-order differential, it passed 639 tests. Each run skipped the reserved-lobby fixture. Ruff checked 117 files in src and tests with zero findings. The compact archive includes the raw test output, all per-seed receipts, the seed-collision evidence and historical compatibility proofs. The reserved evaluation panels remained unopened.

The collector and analysis can be rerun with the pinned environment.

```powershell
python docs/combat-search-v2/probes/v65.py artifacts/v65/dev --workers 12
python docs/combat-search-v2/probes/v65.py artifacts/v65/reaudit --workers 12 --audit-draw-order
python docs/combat-search-v2/probes/report_v65.py docs/combat-search-v2/v65-role-saturated-draft-receipts.zip docs/combat-search-v2/v65-role-saturated-draft.json
```

[Protocol and synthetic scores](v65-protocol.md) · [Seed lock](csv10dev-lock.json) · [Machine-readable results](v65-role-saturated-draft.json) · [Receipts](v65-role-saturated-draft-receipts.zip)
