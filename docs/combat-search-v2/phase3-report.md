# Silent A10 combat search on all_v2_p1_v4

On the final 256 paired v4 lobbies, Schema 3 c512 gained **1.977 floors** over frozen v4 (95% paired seed CI +0.891 to +3.062). Heuristic c256 independently reproduced the fixed-cap gain with **+1.754 floors** (+0.719 to +2.809). All four arms met the Act 1 and Act 2 coverage targets. The final audit found **0 mismatches in 157,039 comparable steps**. At c512 the learned-minus-heuristic floor difference was +0.410 (−0.539 to +1.340). Act 3 coverage was 1.8–4.4%, and no arm cleared Act 3.

## Experiment

The control was the frozen Silent A10 tactics champion at `93456cd`. Its policy manifest SHA-256 was `8636337a6082264bffffe9a79b50528bdf30ed9096b74ff33fd20a8e844fa51b`. The opt-in search came from `90eebae`. Every rollout used the v0.111.0 host with SHA-256 `7408d040c28416331279a84e299b52ff35086d80b4cb9711aefd0f91168d8f20`. The game assembly SHA-256 was `14b57dbaee1b58cb919625a662831054fd714b3b75b13b7449eac0e95b98a3e4`.

The locked registry contains 2,304 distinct lobby names. Each act-list mode contributes 716 ML training lobbies, 154 development lobbies, 154 sealed test lobbies and 128 separate held policy lobbies. Development was divided equally by mode and by seed into Platt calibration and architecture selection. Each paired arm preserved the seed, act-list mode and macro index. Collection, model fitting, calibration and policy ablation used fresh CSV3 names. The registry SHA-256 is `f6e82973d81a85dc3fc5a427b6f3e59ca8743864a51a061947393e0b548b674b`. [Cohort lock](phase3-seed-lock.json)

## Native qualification

| Formation or hook | Native evidence and resulting rule |
| --- | --- |
| Waterfall Giant | A knockout after Pressurize replaces the ordinary health meter with 999,999,999 HP. The scripted eruption can exit combat. Both the knockout transition and an already post-knockout root stop at a boundary. |
| Infested Prism | Buff/Defend raises Vital Spark and reapplies Tainted to skills in the live zones. The simulator stops before this transition. A skill that changes an already rounded attack preview also stops if the underlying values predict different damage. |
| Thieving Hopper | At Escape Artist 1, a stun can delay departure. The simulator stops before resolving this countdown. A separate fresh fixture exposed Grand Finale dealing 60 base damage, including against the Hopper. |
| Shrinker Beetle and Fuzzy Wurm Crawler | After Ghost in a Jar, the visible attack can be 1 for several different base attacks. Applying Weak with Neutralize can make the new preview ambiguous. The pinned mixed-formation fixture observes the native result and checks that the search stops before guessing it. |
| Exoskeletons | On a fresh run a four-hit zero-damage attack still triggered four three-damage Thorns responses. The simulator now fires Thorns on each hit. |
| Wider coverage | Native fixtures cover the ordinary Corpse Slug, Seapunk, Eye with Teeth/Fogmog, Bowlbug Silk and cultist moves, Accelerant poison ticks, Pendulum, Scroll Boxes and further opening or post-combat relics. Corpse Slug ally-death effects, Fogmog revival, Slumbering Beetle transitions with Plating and uncertain relic triggers have explicit boundaries. |
| Discard after drawing | A suspended play can resume at its public discard prompt after the draw. Reconciliation checks the source, queued operations, selection size, board, visible intents, hand length and aggregate live zones. The search never expands the draw using the eventual cards. |

The pristine v4 flags-off checkout, ported flags-off checkout and shadow runs gave identical 24-episode receipts on CSV2DEV. These receipts include every physical decision, legal action, score bit, RPC digest and terminal result. The panel covered both v4 and the historical Mecha Knight control. All 541 comparable native completed-turn feature vectors agreed exactly (maximum absolute error 0.0). The pinned hidden-draw permutation test produced different realized hands and identical features. Full Python, lint and byte-integrity checks are recorded below.

| CSV2DEV shadow | Act 1 covered / eligible | Act 2 | Act 3 | Mismatches / comparable steps |
| --- | ---: | ---: | ---: | ---: |
| all_v2_p1_v4 | 1,353 / 1,915 | 398 / 877 | 12 / 78 | 0 / 2,232 |
| Mecha Knight | 938 / 1,595 | 145 / 546 | No visits | 0 / 1,302 |

A separate 12-lobby CSV3 qualification replay of previously failing cases gave 2,226 matches, zero mismatches and 203 explicit boundaries. These lobbies were outside the held policy comparison.

## Sentinel diagnosis and model

The pre-draw training receipts contained **84 Waterfall Giant witnesses with 999,999,999 maximum HP in 84 fresh training lobbies**. Schema 2 treated this as ordinary HP. The old weighted means were 517,590 for enemy slot 0 and 517,599 for total living HP. Both inverse standard deviations were 4.3970e-8.

Schema 3 packs 187 float32 values. It caps each enemy at 2,000 HP before forming slot and aggregate features, marks oversized enemies, and adds log HP, slot HP fractions, fraction of maximum HP missing among ordinary living enemies, and capped first-tick poison pressure. Oversized enemies are excluded from both progress fractions. The recorder and planner share the packer. Retained cards come from pre-End-Turn evidence. An uninterrupted pre-draw witness must agree on the board and card multiset. A missing witness, an earlier draw, a reveal-sensitive change or an intervening prompt censors a training example. The feature names exclude current post-draw energy, future telegraphs, card order, RNG state, lobby and seed. Historical Schema 2 artifacts retain their original inference path.

| Coordinate | Schema 2 HP-head slope per raw HP | Schema 3 HP-head slope | Schema 3 win-logit slope before Platt | Median increase in expected exit HP for a one-unit decrease |
| --- | ---: | ---: | ---: | ---: |
| enemy.0.hp | −4.40e-9 | −0.007356 | −0.002786 | +0.04629 |
| living_hp | −5.13e-9 | −0.006951 | −0.003830 | +0.05106 |

The coordinate checks vary each input independently. Removing one actual HP from enemy 0 and repacking the complete state gave **+0.19437 predicted exit HP** at the median of 24 fixtures. The selected linear model still assigns a positive conditional HP-logit slope to living count (+0.04933). That coefficient reflects an on-policy association. The one-HP intervention measures damage while the enemy remains alive.

The 1,432 training lobbies supplied 43,033 usable leaves from 12,527 fights. Each fight contributed total weight one. The RX 9070 XT trained a regularized linear model, two ReLU MLPs (32×16 and 64×32), and a linear residual around a fixed monotone HP/block/damage heuristic. The residual kept the progress coefficients fixed while fitting contextual corrections. All four models used win BCE, conditional exit-HP Huber loss and positive-slope Platt calibration. The 154 calibration lobbies supplied 4,765 leaves and the separate 154 selection lobbies supplied 4,570. Selection minimized calibrated Brier among candidates passing the CPU p95 and damage-sensitivity gates. PyTorch/NumPy prediction agreement was checked on the selection rows at absolute tolerance 1e-6.

The selected pure NumPy float32 linear checkpoint has SHA-256 `24debeaaa81c0095cf252807e05e858cf53b8dcbf23ed2e9eb274f267112cb0b`. Its Platt slope was 1.497085 and its intercept was +0.248651. With one BLAS thread, each candidate was timed on 7,680 warm calls including public state packing, inference and calibration.

## Development and sealed calibration

| Candidate | Raw dev Brier | Calibrated Brier | Log loss | Win HP MAE | Expected HP MAE | CPU p50 / p95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| linear | 0.03320 | 0.03152 | 0.10639 | 4.03 | 4.10 | 0.0288 / 0.0535 |
| mlp32 | 0.03793 | 0.03379 | 0.11460 | 4.25 | 4.26 | 0.0322 / 0.0651 |
| mlp64 | 0.04204 | 0.03503 | 0.11779 | 3.94 | 3.99 | 0.0326 / 0.0635 |
| residual | 0.03310 | 0.03157 | 0.10843 | 4.82 | 4.81 | 0.0289 / 0.0550 |

The sealed checkpoint was opened once after selection. All 308 sealed lobbies completed. One lobby had no eligible leaf, leaving 8,998 scored leaves from 307 lobbies and 2,695 fight weights.

| Sealed split | Weighted fights | Mean P(win) | Observed win rate | Brier | Log loss | Win HP MAE | Expected HP MAE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| All | 2695 | 0.9082 | 0.9091 | 0.03333 | 0.11430 | 4.27 | 4.35 |
| Act 1 | 2088 | 0.9360 | 0.9353 | 0.02492 | 0.08613 | 3.79 | 3.94 |
| Act 2 | 566 | 0.8185 | 0.8216 | 0.05689 | 0.18933 | 5.89 | 5.45 |
| Act 3 | 41 | 0.7293 | 0.7805 | 0.13609 | 0.51318 | 10.27 | 10.53 |

| Player HP fraction | Act 1 predicted / observed | Act 2 predicted / observed | Act 3 predicted / observed |
| --- | ---: | ---: | ---: |
| 0–0.25 | 0.637 / 0.580 (127.9) | 0.475 / 0.389 (91.0) | 0.524 / 0.602 (9.8) |
| 0.25–0.5 | 0.854 / 0.865 (277.1) | 0.753 / 0.781 (116.9) | 0.679 / 0.860 (13.7) |
| 0.5–0.75 | 0.963 / 0.968 (894.7) | 0.886 / 0.906 (167.9) | 0.887 / 0.780 (6.8) |
| 0.75–1 | 0.983 / 0.980 (788.3) | 0.963 / 0.979 (190.1) | 0.881 / 0.844 (10.7) |

Parentheses show effective fight weight. The pooled reliability table uses 1,000 lobby-bootstrap resamples per prediction bin.

| P(win) bin | Leaves | Predicted | Observed | Observed 95% seed CI |
| --- | ---: | ---: | ---: | ---: |
| 0.0–0.1 | 265 | 0.032 | 0.128 | [0.070, 0.197] |
| 0.1–0.2 | 154 | 0.149 | 0.178 | [0.106, 0.257] |
| 0.2–0.3 | 153 | 0.249 | 0.169 | [0.100, 0.245] |
| 0.3–0.4 | 148 | 0.353 | 0.248 | [0.153, 0.350] |
| 0.4–0.5 | 165 | 0.453 | 0.233 | [0.159, 0.315] |
| 0.5–0.6 | 180 | 0.549 | 0.480 | [0.373, 0.587] |
| 0.6–0.7 | 216 | 0.648 | 0.660 | [0.560, 0.739] |
| 0.7–0.8 | 257 | 0.753 | 0.727 | [0.646, 0.800] |
| 0.8–0.9 | 469 | 0.855 | 0.897 | [0.858, 0.929] |
| 0.9–1.0 | 6,991 | 0.990 | 0.993 | [0.990, 0.996] |

## First held policy comparison

All five arms used the same 256 held lobbies, split evenly between the default and seeded act lists. Every search arm used width 16, depth 10, a seven-HP potion reserve and the indicated child cap. Learned leaves used calibrated expected exit HP with zero extra win bonus. Global floor was 17 × (act − 1) + floor. Intervals use 10,000 paired lobby bootstrap samples stratified by act-list mode. A matched fight shares the act, floor, room type and opening formation. A death contributes zero exit HP.

| Arm | Mean floor | Paired Δ floor [95% CI] | Floor W/L/T | Act 1/2/3 clears | Act 2 boss entries | Matched fights | Δ exit HP | Δ HP on matched wins |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Frozen v4 | 22.359 | +0.000 [+0.000, +0.000] | 0/0/256 | 138/8/0 | 51 | 2,586 | +0.00 | +0.00 |
| Heuristic c256 | 24.074 | +1.715 [+0.824, +2.605] | 80/44/132 | 164/9/0 | 76 | 2,320 | +2.83 | +2.91 |
| Heuristic c512 | 24.453 | +2.094 [+1.105, +3.105] | 88/46/122 | 164/13/0 | 80 | 2,297 | +3.10 | +3.16 |
| Schema 3 c256 | 23.590 | +1.230 [+0.102, +2.336] | 89/55/112 | 154/9/0 | 69 | 2,242 | +3.43 | +3.55 |
| Schema 3 c512 | 24.059 | +1.699 [+0.504, +2.879] | 89/54/113 | 153/15/0 | 73 | 2,239 | +3.65 | +3.84 |

Natural coverage counts roots at which the search produced a comparison and a certified choice. Denominators come from the recorder census of eligible combat roots on that arm’s actual trajectory. Comparable native steps are matches plus mismatches. A boundary stops a modeled branch before unknown effects. It is reported separately.

| Arm | Act 1 covered / eligible | Act 2 | Act 3 | Mismatches / comparable | Unresolved transitions |
| --- | ---: | ---: | ---: | ---: | ---: |
| Frozen v4 | Search off | Search off | Search off | — | — |
| Heuristic c256 | 22,619/39,775 (56.9%) | 3,885/17,068 (22.8%) | 17/791 (2.1%) | 3/34,314 (0.0087%) | 2,588 |
| Heuristic c512 | 24,052/40,140 (59.9%) | 4,119/17,222 (23.9%) | 18/1,263 (1.4%) | 5/34,563 (0.0145%) | 2,545 |
| Schema 3 c256 | 23,377/40,598 (57.6%) | 3,662/16,027 (22.8%) | 17/646 (2.6%) | 9/34,739 (0.0259%) | 2,573 |
| Schema 3 c512 | 24,962/41,095 (60.7%) | 3,963/15,995 (24.8%) | 25/1,372 (1.8%) | 7/35,049 (0.0200%) | 2,571 |

Times below are p50 / p95 in milliseconds. Full decision time includes champion action selection and optional search on combat choices. Search time covers the opt-in bridge through action selection. Searched time restricts that measure to roots with attempted children. First-leaf time covers the first completed leaf at a root under rollout load. The warm single-thread NumPy benchmark is reported above.

| Arm | Full combat decision | All search calls | Searched calls | First completed leaf |
| --- | ---: | ---: | ---: | ---: |
| Frozen v4 | 0.8790 / 3.2231 | — | — | — |
| Heuristic c256 | 2.1894 / 25.8399 | 0.8398 / 23.9852 | 4.8723 / 27.8525 | 0.0082 / 0.0131 |
| Heuristic c512 | 2.1869 / 41.2016 | 0.8373 / 39.4097 | 5.0476 / 48.4856 | 0.0082 / 0.0131 |
| Schema 3 c256 | 2.3868 / 34.2813 | 0.9969 / 32.5158 | 6.4042 / 36.9869 | 0.1012 / 0.1886 |
| Schema 3 c512 | 2.4284 / 55.0740 | 0.9997 / 53.1960 | 6.6836 / 64.4414 | 0.1017 / 0.1931 |

| Within-search paired contrast | Δ floor [95% seed CI] |
| --- | ---: |
| Schema 3 c256 minus Heuristic c256 | -0.484 [-1.461, +0.488] |
| Schema 3 c512 minus Heuristic c512 | -0.395 [-1.488, +0.668] |
| Heuristic c512 minus Heuristic c256 | +0.379 [-0.355, +1.117] |
| Schema 3 c512 minus Schema 3 c256 | +0.469 [-0.301, +1.258] |


## Independent held confirmation

The first panel produced 24 mismatches in 138,665 comparable steps across four search arms. The failures came from five mechanisms. Native Neutralize left Akabeko's Vigor active. Dash granted block before Thorns hit. Louse Progenitor triggered Curl Up on an attack absorbed by block. Plating absorbed Infection damage and could raise block enough to activate Parrying Shield. Each mechanism has a pinned-host regression. The resolver now models Dash and Curl Up, and stops ambiguous Vigor, Plating and Shield branches. The diagnostic and original observations remain above.

Before running a second panel, commit `e79cdc7` locked 128 new lobbies per mode, disjoint from the 2,304 original lobbies. The SHA-256 of the new registry is `319cda5852952670f0e312992819045d1fe2702fc8cc20da2ed8091bca3ecd62`. The frozen champion, selected model, macro settings and four search budgets stayed fixed. New native fixtures also cover the three Decimillipede segments, Knowledge Demon with public Disintegration, opening relics, and combinations of public energy and card-count relics. Explicit boundaries cover unsupported moves, counters and death phases. [Confirmation cohort lock](phase3-held-confirmation-lock.json)

A preflight identified a train–inference parity issue when newly modeled public relic bonuses entered the simulated energy total. The recorder had always excluded those bonuses from the energy-buff coordinate. The partial launch was stopped after the first progress checkpoint, before reviewing outcomes. The reported panel starts from a separate empty output directory and uses the corrected encoder for every arm. It preserves both the modeled physical energy and the frozen training feature definition. No test-set labels were reopened.

### Confirmation results

| Arm | Mean floor | Paired Δ floor [95% CI] | Floor W/L/T | Act 1/2/3 clears | Act 2 boss entries | Matched fights | Δ exit HP | Δ HP on matched wins |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Frozen v4 | 22.578 | +0.000 [+0.000, +0.000] | 0/0/256 | 135/13/0 | 53 | 2,602 | +0.00 | +0.00 |
| Heuristic c256 | 24.320 | +1.742 [+0.707, +2.797] | 94/47/115 | 166/13/0 | 68 | 2,242 | +3.37 | +3.30 |
| Heuristic c512 | 24.125 | +1.547 [+0.508, +2.617] | 81/45/130 | 156/13/0 | 68 | 2,239 | +3.46 | +3.43 |
| Schema 3 c256 | 23.988 | +1.410 [+0.398, +2.410] | 85/56/115 | 158/10/0 | 66 | 2,230 | +3.21 | +3.33 |
| Schema 3 c512 | 24.578 | +2.000 [+0.910, +3.090] | 96/57/103 | 167/13/0 | 67 | 2,234 | +3.80 | +3.84 |

| Arm | Act 1 covered / eligible | Act 2 | Act 3 | Mismatches / comparable | Unresolved transitions |
| --- | ---: | ---: | ---: | ---: | ---: |
| Frozen v4 | Search off | Search off | Search off | — | — |
| Heuristic c256 | 24,490/39,930 (61.3%) | 5,376/16,964 (31.7%) | 25/1,280 (2.0%) | 9/39,105 (0.0230%) | 3,295 |
| Heuristic c512 | 25,706/39,818 (64.6%) | 5,365/16,316 (32.9%) | 58/1,306 (4.4%) | 9/38,680 (0.0233%) | 3,289 |
| Schema 3 c256 | 25,333/40,557 (62.5%) | 5,047/16,543 (30.5%) | 29/1,028 (2.8%) | 14/39,419 (0.0355%) | 3,238 |
| Schema 3 c512 | 26,919/41,055 (65.6%) | 5,781/17,380 (33.3%) | 22/1,245 (1.8%) | 15/40,296 (0.0372%) | 3,305 |

| Arm | Full combat decision | All search calls | Searched calls | First completed leaf |
| --- | ---: | ---: | ---: | ---: |
| Frozen v4 | 0.8784 / 2.8830 | — | — | — |
| Heuristic c256 | 2.5153 / 28.6329 | 1.1891 / 26.7101 | 5.1174 / 29.9581 | 0.0082 / 0.0131 |
| Heuristic c512 | 2.5275 / 46.1999 | 1.2052 / 44.1779 | 5.1472 / 51.9664 | 0.0082 / 0.0130 |
| Schema 3 c256 | 2.8236 / 36.7092 | 1.4650 / 34.8755 | 6.6365 / 38.5903 | 0.1025 / 0.1850 |
| Schema 3 c512 | 2.8162 / 59.7880 | 1.4516 / 57.9244 | 6.6697 / 67.3450 | 0.1027 / 0.1858 |

| Within-search paired contrast | Δ floor [95% seed CI] |
| --- | ---: |
| Schema 3 c256 minus Heuristic c256 | -0.332 [-1.274, +0.590] |
| Schema 3 c512 minus Heuristic c512 | +0.453 [-0.504, +1.387] |
| Heuristic c512 minus Heuristic c256 | -0.195 [-0.867, +0.504] |
| Schema 3 c512 minus Schema 3 c256 | +0.590 [-0.215, +1.391] |

### Diagnosis on the confirmation lobbies

All four arms met both coverage thresholds on this pass. The 47 remaining native discrepancies occurred at End Turn in four lobbies. Twenty-eight involved a Frost orb obtained through cross-class cards. Seventeen involved a living Osty, which absorbed incoming damage. Two involved both Ripple Basin and Orichalcum activating from zero block. The original projection omitted the orb and summon fields, and relic acquisition order gave the wrong block total when both relics triggered.

Pinned-host fixtures create the relevant public board with Ice Lance and Pull Aggro, and reproduce the relic interaction with both relics equipped. The final resolver stops on active orbs, living Osty and the simultaneous block interaction. These gates use the current public observation. The following verification reruns all five arms on the same 256 confirmation lobbies after the correction. Its native agreement measures the corrected implementation. The independent panel's pre-correction results above preserve the discovery record.

### Final paired verification

| Arm | Mean floor | Paired Δ floor [95% CI] | Floor W/L/T | Act 1/2/3 clears | Act 2 boss entries | Matched fights | Δ exit HP | Δ HP on matched wins |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Frozen v4 | 22.578 | +0.000 [+0.000, +0.000] | 0/0/256 | 135/13/0 | 53 | 2,602 | +0.00 | +0.00 |
| Heuristic c256 | 24.332 | +1.754 [+0.719, +2.809] | 94/46/116 | 166/13/0 | 68 | 2,244 | +3.38 | +3.30 |
| Heuristic c512 | 24.145 | +1.566 [+0.527, +2.633] | 81/45/130 | 157/13/0 | 67 | 2,239 | +3.47 | +3.43 |
| Schema 3 c256 | 23.969 | +1.391 [+0.391, +2.387] | 84/56/116 | 157/10/0 | 66 | 2,230 | +3.19 | +3.31 |
| Schema 3 c512 | 24.555 | +1.977 [+0.891, +3.062] | 95/56/105 | 166/13/0 | 67 | 2,235 | +3.77 | +3.80 |

| Arm | Act 1 covered / eligible | Act 2 | Act 3 | Mismatches / comparable | Unresolved transitions |
| --- | ---: | ---: | ---: | ---: | ---: |
| Frozen v4 | Search off | Search off | Search off | — | — |
| Heuristic c256 | 24,443/39,934 (61.2%) | 5,361/17,008 (31.5%) | 25/1,280 (2.0%) | 0/39,023 (0.0000%) | 3,290 |
| Heuristic c512 | 25,656/39,825 (64.4%) | 5,385/16,375 (32.9%) | 58/1,306 (4.4%) | 0/38,625 (0.0000%) | 3,286 |
| Schema 3 c256 | 25,245/40,526 (62.3%) | 5,014/16,475 (30.4%) | 29/1,028 (2.8%) | 0/39,268 (0.0000%) | 3,237 |
| Schema 3 c512 | 26,815/41,025 (65.4%) | 5,739/17,297 (33.2%) | 22/1,245 (1.8%) | 0/40,123 (0.0000%) | 3,300 |

| Arm | Full combat decision | All search calls | Searched calls | First completed leaf |
| --- | ---: | ---: | ---: | ---: |
| Frozen v4 | 0.8822 / 3.2721 | — | — | — |
| Heuristic c256 | 2.5239 / 29.5655 | 1.1807 / 27.5040 | 5.1710 / 30.8818 | 0.0081 / 0.0130 |
| Heuristic c512 | 2.5451 / 47.0675 | 1.2110 / 45.0054 | 5.1819 / 53.3386 | 0.0081 / 0.0133 |
| Schema 3 c256 | 2.8392 / 37.7019 | 1.4791 / 35.7639 | 6.7593 / 39.9967 | 0.1034 / 0.1983 |
| Schema 3 c512 | 2.8435 / 60.2341 | 1.4682 / 58.0565 | 6.7931 / 68.6670 | 0.1037 / 0.2009 |

| Within-search paired contrast | Δ floor [95% seed CI] |
| --- | ---: |
| Schema 3 c256 minus Heuristic c256 | -0.363 [-1.305, +0.551] |
| Schema 3 c512 minus Heuristic c512 | +0.410 [-0.539, +1.340] |
| Heuristic c512 minus Heuristic c256 | -0.188 [-0.863, +0.516] |
| Schema 3 c512 minus Schema 3 c256 | +0.586 [-0.219, +1.391] |

## Verification and reproduction

The final planner source digest was `d2aec01b9f06f2ef25a41305e2d9f489af1fc1402aac2ff2b75e25619bc007f9`. All five arms used 12 rollout workers. A disk-full error interrupted receipt writing. The first pass retained 831 complete recordings, each of which passed gzip validation. The resumed pass completed the remaining 449 arm–lobby pairs with the same planner, host, model, registry and configuration hashes. The five-arm summary includes one successful result per arm and lobby. The repeated timed champion matched the independently collected flags-off control in every terminal result and fight record.

The pinned full suite passed **466 tests**, and Ruff reported **zero findings**. All 44 protected file comparisons matched the bytes at `93456cd`, including the eight champion files, 16 legacy modules and applicable macro scripts and models. The three 24-episode gate receipts share SHA-256 `4eea5074c263a82b7bc252574b19598980c7e87073c2373ae843da0501917d99`. Native versus simulated completed-leaf features agreed on all 541 comparisons with maximum absolute error 0.0. The isolated learned-leaf CPU p95 was 0.0535 ms. The measured first-leaf p95 under concurrent rollout load was 0.1983–0.2009 ms.

The frozen model, both cohort collections, native comparison receipts, timing samples and paired results live under the worktree's ignored artifact directory. The report records all three panels so that the effects of qualification and reuse of the confirmation lobbies are visible. [Frozen NumPy model](../../artifacts/combat-search-v3/models/combat_value_v2.npz) · [Selection freeze](../../artifacts/combat-search-v3/models/selection-freeze.json) · [Sealed metrics](../../artifacts/combat-search-v3/models/sealed-test.json) · [Final manifest](../../artifacts/combat-search-v3/final-ablation/manifest.json) · [Final five-arm metrics](../../artifacts/combat-search-v3/final-ablation/phase3.json)

To reproduce the pairing from the locked local recordings on Helmer, use the pinned CPU interpreter, host and read-only observer described above. Run from the repository root, with the observer and host paths set in the environment.

```powershell
$env:PYTHONPATH = "$PWD/src"
$env:OPENBLAS_NUM_THREADS = "1"
$env:OMP_NUM_THREADS = "1"
$cpu = "C:/Users/gosee/Documents/codex/2026-10-26/new-chat/STS2ML/.venv/cpu/Scripts/python.exe"
$v = "artifacts/combat-search-v3"
& $cpu scripts/ablate-combat-v2.py phase3 --held-confirmation --workers 12 `
  --host $env:CSV2DEV_HOST --observer $env:CSV2DEV_OBSERVER `
  --data "$v/confirm-control" --model "$v/models/combat_value_v2.npz" --output "$v/final-ablation"
```
