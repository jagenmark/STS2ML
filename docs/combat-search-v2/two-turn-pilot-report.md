# Two-turn Silent A10 combat search pilot

**Keep the one-turn control.** One extra player turn changed the result of one fight in 100, a Vantom loss that became a win at 4 HP. Mean exit HP moved from 34.62 to 34.79. The paired difference of +0.17 HP had a 95% interval of −1.02 to +1.31. Fourteen openings gained HP, fourteen lost HP and 72 tied.

**The clearest decision-quality bottleneck was the leaf score.** In five of the 76 changed decisions, the original candidate won all four second-turn worlds. The pilot chose a candidate that kept fighting in all four. Both candidates scored 100% survival. Arm 3 values a victory in remaining HP, while a completed nonterminal turn also receives credit for damage and powers. Averaging these values across worlds can reward delaying a kill. Python execution also raises the latency of activated decisions substantially. A faster simulator would reproduce this ranking. These fights do not establish an overall benefit from a longer horizon or measure the benefit of a learned evaluator.

## Matched fights

All 100 opening digests were unique and matched within each pair. Eighty were controlled scenarios with four decks and two HP levels, 70 and 90, with starting HP equal to maximum HP. These scenarios use the Act 2 room-context injection from the v6.2 fight probe, including for species normally found elsewhere. The other 20 were the first 20 saved Waterfall Giant openings in the historical ACT1PATTEST development archive. Each restored on its original full public digest, with its actual deck, relics, HP and map context. Both arms won seven of those 20, and the pilot activated on none of their 203 structurally eligible decisions. The 80 scenarios supplied all observed changes. The cohort includes boss and hallway rooms. It has no separately tagged elite room.

Each fight ran to native combat exit under its assigned policy. A loss contributes zero exit HP. W/L/T counts a pilot-only win, control-only win or equal survival outcome. Intervals are paired percentile bootstraps over openings, 20,000 resamples with a fixed analysis seed. The matched-win interval uses only pairs where both arms cleared. Per-encounter intervals are descriptive, with small samples and related historical openings.

| Encounter | Pairs | Wins 1T→2T | Win W/L/T | Δ HP [95% CI] | Matched wins · Δ HP [95% CI] |
| --- | --- | --- | --- | --- | --- |
| All | 100 | 69→70 | 1/0/99 | +0.17 [-1.02, +1.31] | 69 · +0.19 [-1.52, +1.84] |
| Waterfall Giant | 28 | 15→15 | 0/0/28 | +0.71 [-0.04, +1.86] | 15 · +1.33 [-0.07, +3.40] |
| Ceremonial Beast | 8 | 6→6 | 0/0/8 | -1.50 [-3.50, +0.00] | 6 · -2.00 [-4.33, +0.00] |
| Lagavulin Matriarch | 8 | 7→7 | 0/0/8 | +1.62 [-2.75, +7.12] | 7 · +1.86 [-3.14, +8.00] |
| The Insatiable | 8 | 0→0 | 0/0/8 | +0.00 [+0.00, +0.00] | 0 · — |
| Vantom | 8 | 6→7 | 1/0/7 | +0.62 [-4.25, +5.00] | 6 · +0.17 [-5.83, +6.00] |
| Soul Fysh | 8 | 6→6 | 0/0/8 | +7.25 [+1.75, +13.25] | 6 · +9.67 [+3.17, +16.50] |
| Tunneler | 8 | 8→8 | 0/0/8 | -8.25 [-16.25, -1.75] | 8 · -8.25 [-16.25, -1.75] |
| Slumbering Beetle | 8 | 6→6 | 0/0/8 | +0.00 [+0.00, +0.00] | 6 · +0.00 [+0.00, +0.00] |
| Louse Progenitor | 8 | 7→7 | 0/0/8 | +0.12 [+0.00, +0.38] | 7 · +0.14 [+0.00, +0.43] |
| Shrinker Beetle | 8 | 8→8 | 0/0/8 | -0.25 [-0.75, +0.00] | 8 · -0.25 [-0.75, +0.00] |

## Activation and physical move changes

An eligible decision had a certified one-turn recommendation, two surviving roots with distinct completed states, and no certified immediate victory. The pilot activated after both continuations passed the public-state gates and produced scores in all four worlds. The control took 3,891 decisions and the pilot took 3,885. Of 1,914 eligible pilot decisions, 1,275 activated. The 76 physical changes were 6.0% of activations, 4.0% of eligible decisions and 2.0% of all pilot decisions. Slot identity was retained for duplicate cards.

Across the 37 fights with any changed move, wins went from 33 to 34 and mean HP rose by 0.46. Membership in this subgroup depends on pilot behavior. A dash indicates an empty denominator.

| Encounter | Active / eligible | Changed / active | Changed fights | Changed Δ HP [95% CI] | Changed Δ win (pp) |
| --- | --- | --- | --- | --- | --- |
| All | 66.6% | 6.0% | 37 | +0.46 [-2.73, +3.54] | +2.7 |
| Waterfall Giant | 45.8% | 4.7% | 5 | +4.00 [+0.00, +8.80] | +0.0 |
| Ceremonial Beast | 67.2% | 4.3% | 3 | -4.00 [-7.00, +0.00] | +0.0 |
| Lagavulin Matriarch | 92.0% | 5.2% | 5 | +2.60 [-4.40, +10.60] | +0.0 |
| The Insatiable | 0.0% | — | 0 | — | — |
| Vantom | 100.0% | 5.2% | 5 | +1.00 [-7.00, +8.00] | +20.0 |
| Soul Fysh | 100.0% | 6.0% | 8 | +7.25 [+1.75, +13.25] | +0.0 |
| Tunneler | 88.4% | 14.6% | 6 | -11.00 [-20.17, -2.67] | +0.0 |
| Slumbering Beetle | 6.8% | 0.0% | 0 | — | — |
| Louse Progenitor | 100.0% | 2.1% | 2 | +0.50 [+0.00, +1.00] | +0.0 |
| Shrinker Beetle | 100.0% | 9.5% | 3 | -0.67 [-2.00, +0.00] | +0.0 |

The remaining 639 eligible decisions stopped on card support or cost (245), an uncovered living formation member (150), a start trigger (145), an uncertain next intent (77), or an uncertified sampled world (22). The Insatiable's escalating Frantic Escape cost prevented activation in all eight fights. The Slumbering Beetle encounters could activate after their unqualified allies had died. Knowledge Demon, Crusher and Rocket remain outside the ten-species table.

### Decisions that changed

The following examples give the first changed decision in four different fixtures. Scores compare the full candidate lines starting with those cards. The eventual HP difference includes subsequent decisions.

- **Vantom, opening 0, round 4.** Strike and Deadly Poison both left the player at 59 HP before a forecast 10 damage. Strike led the one-turn score 68.48 to 68.13. An extra poison tick reversed the ordering, with second-turn means of 68.55 and 69.60. The pilot won at 4 HP. The control died.
- **Waterfall Giant, opening 2, round 7.** Dash led Leg Sweep 142.59 to 141.09 at the first leaf. Leg Sweep's Weak reduced forecast pressure from 11 to 8 and left 64 player HP against Dash's 62. The next-turn means favored Leg Sweep 151.10 to 149.80. Exit HP went from 47 to 49.
- **Soul Fysh, opening 2, round 8.** Dash won all four next-turn worlds with 37, 37, 43 and 31 HP, a mean of 37. Deflect produced four ongoing fights scored at a mean of 112.92. The pilot chose Deflect. Both policies eventually won, at 31 and 43 HP. This turn exposes the incompatible terminal and nonterminal score scales even though the pilot gained HP in the actual fight.
- **Tunneler, opening 3, round 1.** The Deflect line kept the player at 70 HP and left the enemy at 76. The Deadly Poison line left them at 69 and 71. The next telegraph was a nonattack. One-turn scores favored Deflect 79.58 to 76.95, but the two-turn means favored poison 87.00 to 86.21. Both won, with exit HP falling from 67 to 36.

## Latency and native fidelity

Latency is p50/p95 wall-clock milliseconds inside the deployed controller's whole choice, including the legacy proposal, projection, search, safety overrides and decision recording. Native execution, replay restoration and post-choice audits are outside the timer. The benchmark ran 12 workers on Helmer, with both BLAS thread limits at one. Per-encounter audit counts combine the two arms.

| Encounter | 1T all (ms) | 2T all (ms) | 2T active (ms) | Steps / intents / starts / mismatches |
| --- | --- | --- | --- | --- |
| All | 1.7/24.7 | 3.0/116.3 | 86.2/129.9 | 6075/1221/901/0 |
| Waterfall Giant | 1.2/15.5 | 1.2/98.2 | 87.4/130.1 | 1214/292/140/0 |
| Ceremonial Beast | 2.1/21.6 | 3.9/116.3 | 84.9/130.9 | 528/68/68/0 |
| Lagavulin Matriarch | 2.1/20.2 | 42.4/115.6 | 84.5/121.7 | 645/129/129/0 |
| The Insatiable | 2.7/23.5 | 2.7/23.5 | — | 584/88/0/0 |
| Vantom | 2.0/20.2 | 33.6/123.7 | 54.8/127.1 | 632/152/152/0 |
| Soul Fysh | 2.7/24.1 | 83.1/130.9 | 99.3/134.1 | 838/184/184/0 |
| Tunneler | 2.1/22.6 | 46.7/112.7 | 73.6/115.7 | 445/86/86/0 |
| Slumbering Beetle | 4.7/75.2 | 5.2/84.7 | 101.6/117.8 | 528/90/10/0 |
| Louse Progenitor | 2.4/22.0 | 46.3/121.0 | 88.2/133.5 | 490/106/106/0 |
| Shrinker Beetle | 2.4/23.6 | 15.5/103.3 | 62.5/108.8 | 171/26/26/0 |

On activated decisions, the eight second-turn searches consumed 89.5% of total choice time. The full pilot extension consumed 90.5%. Subtracting the extension on those same roots leaves a p50/p95 of 4.5/26.7 ms. The second-turn searches alone took 77.6/116.2 ms. A separate deterministic cProfile run on Lagavulin opening 2 covered 18 activations. Of 2.77 seconds in the profiled planner, advancing 12,888 child states used 2.08 s, beam selection used 0.33 s, 6,476 leaf evaluations used 0.13 s and 144 sampled hands used 0.012 s. These instrumented cumulative timings describe that fight's cost distribution.

Control and pilot had 3,043 and 3,032 exact native step matches, respectively, and 49 and 50 explicit unresolved boundaries. The final run had zero raw step mismatches. Predictions agreed on all 610 control and 611 pilot executed next-intent comparisons, including type order, per-hit damage and hit count. Public energy, block and total hand size matched on all 901 qualified native starts. Sampled hands are hypothetical worlds. A separate controlled fixture prescribed a sampled draw on the host and verified the exact hand, board, intents, legality and the researched second-turn line.

During qualification, an early Insatiable rule produced 22 mismatches in a diagnostic run. Its later consecutive multiattacks share a telegraph. The table now abstains on that transition after the unambiguous opening. The final benchmark reran both policies on every opening. It measures a development pilot, with no independent holdout claim.

## Search boundary and verification

The first search uses Arm 3's heuristic, width 16, child cap 512 and depth 10. The second search uses the same leaf, width 6, cap 96 and depth 8. The pilot compares the best certified line from each of two different surviving physical roots with different completed states. Each candidate uses all four worlds. It ranks the fraction of worlds with survival or victory first and their mean numeric leaf value second. An exact tie retains the control. The controller still applies Arm 3's physical-action safeguards.

The public completed leaf already resolves enemy actions, power ticks, start energy, retained cards and Blur. The extension forecasts each living enemy's next telegraph, re-anchors damage previews to the new public modifiers, and deals up to the certified draw count. Among fixed-cost supported cards, identity/copy priorities depend on the canonical public root and sample number. Candidates share priorities. A short draw pile empties first, then only the discard pile shuffles. Remaining shuffled cards become the new draw pile. Turn 1 potion spend carries through every world. Unqualified start triggers, Barricade, Confused, unsupported cards and variable costs leave the choice with Arm 3.

All ten covered monsters passed pinned-host transition fixtures before enabling reranking. Inspection of the pinned game assembly confirmed that none of their move-state-machine builders constructs a RandomBranchState. Lagavulin Matriarch and Slumbering Beetle use conditional branches. Waterfall Giant uses the existing public Steam Eruption forecast. The pinned host SHA-256 is `7408d040c28416331279a84e299b52ff35086d80b4cb9711aefd0f91168d8f20` and the game DLL SHA-256 is `14b57dbaee1b58cb919625a662831054fd714b3b75b13b7449eac0e95b98a3e4`.

The native leakage fixture reseeded private RNGs and permuted the hidden draw pile while preserving the full public digest. The actual revealed hands differed. All eight hypothetical hands, individual world scores, candidate means and the physical first move were identical. The kernel's inputs are the public root and the local search frontier. The future native observation first enters the differential harness after the decision. Unit tests also cover shuffled input order, copy coupling, exact reshuffle, unsupported cards, preview reset, potion accounting and the victory and single-root skips.

All ten challenger files matched the raw Git blobs at `efd9877` byte for byte. Separate Python source paths for the original `a0a7fb1` and pilot checkout reproduced all nine flags-off transcripts across v5, v6.1 and v6.2, covering 369 physical decisions per checkout. Stable decision records, oracle outcomes, board digests and serialized config metadata matched. The combined parity receipt SHA-256 is `9916973a980937d5abe29c5ad4ffa9f152a920cdc3902b438fd18ac181a6dff7`.

The full pinned-host suite passed 613 tests, including the leakage and intent fixtures. Ruff checked 115 Python files under `src/` and `tests/` with zero findings. A second complete benchmark reproduced the recorded results, audits, examples and activation sequence for all 200 arm-fights.

## Reproduction

Use the pinned CPU environment, put `src`, `tests` and `docs/combat-search-v2/probes` on `PYTHONPATH`, point `CSV2DEV_HOST` at the pinned Curriculum host, and set `OPENBLAS_NUM_THREADS=1` and `OMP_NUM_THREADS=1`. The fixture runner configures Arm 3 explicitly and enables `two_turn_pilot` only on the experimental arm. The ordinary configuration defaults to false. Run the suite with the pinned observer in `CSV2DEV_OBSERVER` and the existing fixture namespace mapper.

```text
python -m pytest -q -p v6_fixture_seeds
python -m ruff check src/ tests/
python docs/combat-search-v2/probes/two_turn_fights.py receipts.jsonl.gz --workers 12
python docs/combat-search-v2/probes/two_turn_report.py receipts.jsonl.gz
```

The archived 200 fight receipts occupy 61,865 bytes (SHA-256 `376608c17ec078f0afbde988500ea3f260b339c25092112db0cbf91bad4ab0f4`) and include opening digests, outcomes, counters, per-choice timings and every changed decision in this run. [Native fight receipts](two-turn-pilot-receipts.jsonl.gz) · [Pairing and audits](probes/two_turn_fights.py) · [Bootstrap and tables](probes/two_turn_report.py) · [Off-switch transcript probe](probes/two_turn_parity.py)
