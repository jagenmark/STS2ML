# Silent A10 v6.2 scaling powers and paired release gate

**Retain frozen v5.** All five arms completed the same 384 lobbies. None achieved a strictly positive Bonferroni-adjusted lower bound against the champion. Independently, 73 raw native mismatches violated the pre-registered audit gate. No candidate advanced. FINAL512 and POOLED896 were never run, and the release directory remains byte-identical to `efd9877`. Its policy manifest SHA-256 is `a686db12c8b217bd476ea5c8e60cf6f486b060665536ef9354e8f09c21c81fcb`.

## Paired progression on CSV6DEV

Each arm completed 192 default and 192 seeded natural A10 lobbies. The interval against v5 is the two-sided 98.75% stratified paired bootstrap interval. W/L/T counts higher, lower and equal global floors on the same lobby. Milestones are lobby counts out of 384. All arms recorded zero full-run wins.

| Arm | Mean floor | Paired Δ vs v5 [98.75% CI] | W/L/T | Act 1 clears | Act 2 boss entries | Act 2 clears | Native matches / mismatches / boundaries |
| --- | ---: | --- | --- | ---: | ---: | ---: | --- |
| 1 · Frozen v5 | 24.555 | Reference | 0/0/384 | 256 | 108 | 14 | 61,742 / 1 / 5,287 |
| 2 · v6.1 heuristic | 24.745 | +0.190 [−0.780, +1.135] | 109/84/191 | 255 | 121 | 12 | 70,785 / 17 / 6,498 |
| 3 · Power leaf + beam | 25.057 | +0.503 [−0.479, +1.464] | 119/87/178 | 256 | 124 | 17 | 70,994 / 17 / 6,495 |
| 4 · Arm 3 + Accelerant draft | 25.219 | +0.664 [−0.370, +1.693] | 125/88/171 | 256 | 123 | 21 | 70,511 / 19 / 6,483 |
| 5 · Arm 3 + four-power draft | 25.109 | +0.555 [−0.510, +1.646] | 125/99/160 | 254 | 121 | 22 | 66,912 / 19 / 6,621 |

Arm 3 added five Act 2 clears over the unchanged heuristic. The Accelerant-only draft added four more and had the highest mean floor. Adding the other three draft changes yielded one additional Act 2 clear, two fewer Act 1 clears and a lower mean floor. Arms 3 and 4 met the three milestone requirements against v5. Neither met the floor or audit requirement.

| Direct paired floor contrast | Mean Δ | Descriptive 95% CI | W/L/T |
| --- | ---: | --- | --- |
| 3 − 2 · Power scoring | +0.313 | [−0.052, +0.693] | 34/25/325 |
| 4 − 3 · Accelerant draft | +0.161 | [−0.167, +0.505] | 19/11/354 |
| 5 − 4 · Other three draft changes | −0.109 | [−0.570, +0.336] | 33/41/310 |
| 4 − 2 · Power scoring and Accelerant draft | +0.474 | [0.000, +0.966] | 50/32/302 |
| 5 − 2 · Power scoring and four-power draft | +0.365 | [−0.286, +1.021] | 66/59/259 |

### Native audit

Across 341,017 comparable steps, the simulator matched 340,944 and disagreed on 73. Another 31,384 steps reached explicit boundaries. The discrepancies occurred on seven distinct seeds. Seventy concerned end-turn state, comprising 44 relic comparisons, 22 power comparisons and four HP comparisons. The remaining three concerned Skewer card zones in frozen v5, a Dagger Throw discard's legal actions in Arm 2 and enemy state after Precise Cut in Arm 5. Some discrepancies recur on the same physical situation across arms. The gate counts each raw mismatch. No arm was revised or rerun using these outcomes.

The independent Right Hand Hand observer matched the frozen Skewer step. The raw v5 discrepancy remains in the table. The dev receipt archive is 78,496 bytes, with SHA-256 `4c8359553fb5c3ffded9ad986e4f9328705bb7648a7808259a9749c891ef6abb`.

[All 1,920 terminal receipts, mismatch diagnostics, manifests and analysis](v62-dev-receipts.zip)

## Native fight diagnostics

The v6.2 heuristic finished 140 paired power fixtures with 1,768 total exit HP against 1,639 for the v6.1 boss-safe heuristic. Mean exit HP rose from 11.71 to 12.63, a gain of **0.92 HP per fixture**. Fourteen pairs gained HP, eight lost HP and 118 tied. Clears rose from 38 to 42. Each pair started at the same public-state digest. These are diagnostic configurations with repeated seeds across deck variants. They do not estimate a natural-lobby win rate.

| Power in deck | Pairs | Certified power plays, v6.1 → v6.2 | First beam retained / entered, v6.2 | Paired total Δ exit HP |
| --- | ---: | ---: | ---: | ---: |
| Accelerant | 20 | 12 → 19 | 26/26 | −5 |
| Noxious Fumes | 20 | 6 → 18 | 25/25 | +74 |
| Accuracy | 20 | 7 → 19 | 29/29 | +41 |
| Phantom Blades | 20 | 0 → 16 | 21/21 | +24 |
| Infinite Blades | 20 | 6 → 15 | 68/68 | −7 |
| Afterimage | 20 | 19 → 19 | 35/35 | +7 |
| Footwork | 20 | 16 → 18 | 37/37 | −5 |

The search retained the power continuation at 241/241 first-beam opportunities with v6.2 and 629/633 with v6.1. Earlier plays remove the card from future hands, so the denominators differ. Certified power plays rose from 66 to 124. Legacy fallback contributed another 35 and four plays, respectively. Unit fixtures with one energy chose Strike for lethal and Defend to survive an otherwise fatal attack. The new score uses the existing development quota in the beam. The safety ranking and certified survival categories retain their existing priority.

The initial 28 pairs against The Insatiable and the Decimillipede ended in death for both arms. Fourteen additional Decimillipede pairs at a diagnostic 250 starting HP and 28 basic-deck Slumbering Beetle and Knowledge Demon pairs also tied at zero. The 70 developed-deck pairs used Leg Sweep, Dagger Spray, Deflect, Neutralize, Dash, Snakebite and Slice alongside the test card and its support. On 14 pairs per encounter, total exit HP changed by +84 against the Decimillipede, +45 against Slumbering Beetle, +1 against The Insatiable, 0 against Knowledge Demon and −1 against Shrinker Beetle. The harness injects encounter routing metadata for the scenario, with native combat fields and physical actions. Across both power arms, 9,748 comparable steps matched native execution and 702 reached explicit boundaries. Raw mismatches were zero.

### Public scoring and free rewards

The new leaf prices effects over up to four discounted turns, using living enemy HP after projected poison damage. It assigns zero future setup value at 14 or less remaining effective HP. The next poison-start estimate accounts for the sequence of decreasing ticks under Accelerant and public damage caps. Persistent values use public hand and unordered draw/discard piles for poison supply, attack density and Shiv generation. The computation uses no revealed future hand, future intent, future energy, RNG, lobby identifier or label. Completed learned leaves retain their frozen estimator. The tested power arms use the heuristic.

Native normalized identifiers include `ENVENOM`, `THORNS` for Caltrops, `A_THOUSAND_CUTS`, `SERPENT_FORM`, `AFTERIMAGE` and `DEXTERITY` for Footwork. Valuation preserves the simulator's existing coverage boundaries, including Tools of the Trade's start-turn reveal and some Phantom Blades/Shiv interactions. The draft arms reuse the shop's scaling term only for first copies in free rewards. Accelerant requires a source that can start poison, while Accuracy and Phantom Blades require a Shiv source. Infinite Blades supplies its own Shivs.

### The Insatiable

On 12 separate matched Insatiable pairs, both policies lost all 12 fights. The first changed action was Backflip → Frantic Escape at Sandpit 4 in two pairs. Both were unresolved champion continuations. At Sandpit 3, search played Escape 25 times under v6.1 and 23 under the experiment, with zero fallback Escapes in either arm. At Sandpit 4, search plays moved from 22 to 23 and fallback plays from zero to three. Both arms also played one fallback Escape at Sandpit 2. Across timers, total Escape plays moved from 48 to 50 and fallback Escape plays from one to four. There were 526 comparable matches, 88 explicit boundaries and zero mismatches. With zero exit-HP or clear gain, the dev arms keep earlier Escape disabled. The Sloth policy was outside this experiment.

## Qualification and reproducibility

Commit `87bf119fbabce1cc742ddc48c5677989765ba8bd` froze the five policy configurations, collector, decision rule and ordered dev triples before the first CSV6DEV lobby. The lock SHA-256 is `3f166462911e3a53b863cf48bbcae7ee5fae8796abde68bc44ee4993183b4c04`. The 384 names and UTF-8 xxHash64 values were unique and disjoint from 29,138 historical or reserved names checked, including the 896 official names. Git history on the fetched refs had no prior use of the CSV6DEV namespace. The release manifest and all nine payloads matched the ten hashes at `efd9877`. All 15 existing builders reproduced their frozen reference manifest hashes. CSV2DEV flags-off, shadow and active-v5 reproduced the expected complete transcript digest in each of 24 cases per mode.

The pinned v0.111.0 headless host SHA-256 is `7408d040c28416331279a84e299b52ff35086d80b4cb9711aefd0f91168d8f20`. The game DLL SHA-256 is `14b57dbaee1b58cb919625a662831054fd714b3b75b13b7449eac0e95b98a3e4`. Both controls use the same protected release assets. Arm 2 changes the search scope to v6.1 boss-safe and uses its heuristic. Arms 3–5 retain those choices. Each arm uses width 16, depth 10 and a 512-child cap.

The pre-dev suite passed 597 tests. Final verification passed all 597 tests in 242.68 seconds with the pinned host and observer enabled (`pytest -q -p v6_fixture_seeds`). Ruff checked 111 Python files under `src/` and `tests/` with zero findings. The frozen controller loaded its Schema 3 checkpoint. The local worktree's owned `artifacts/` files occupied 247,618 bytes after cleanup, excluding junctions to the pre-existing native dependencies.

[Pre-registered gate](v62-protocol.md) · [Cohort](v62-dev-lock.json) · [Compact native qualification receipts](v62-qualification.json.gz) · [Fight probe](probes/v62_fights.py)

To reproduce the tables without starting any lobbies, extract the dev receipt archive to a directory and run `python scripts/report-silent-v62.py <directory>` with the CPU interpreter. The analysis reproduces the archived `result.json`. For native reproduction, use the v6.1 pinned runtime layout, set `CSV2DEV_HOST` to the Curriculum host and both `OPENBLAS_NUM_THREADS` and `OMP_NUM_THREADS` to 1. Run `scripts/ablate-silent-v62.py --arm <arm> --workers 12 --output <directory>` once per arm, using `v5`, `heuristic`, `power`, `accelerant_only` and `scaling_powers_4`. The fixture probe also needs `tests` on `PYTHONPATH` alongside `src`.
