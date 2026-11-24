# Silent A10 Arm 4 native stress audit and late-act autopsy

**Arm 4 completed all 384 fresh AUDIT384 lobbies with 71,160 native matches, zero raw mismatches and 6,512 explicit boundaries.** The two clean passes reproduced terminal outcomes, coverage and native counters for every lobby. This was a solo development audit. The released v5 bundle remains at `efd9877`.

**Prioritize Kaiser Crab boss conversion.** Kaiser accounted for 44 of 95 Act 2 boss deaths and cleared once in 45 entries. Most of its eligible decisions fell back. Schema 4 has a measurable opportunity across acts, especially through public pile composition, but a leaf can only rerank lines that Arm 4 reaches and certifies.

## Native qualification and discovery

The pinned v0.111.0 host reproduced the archived forced End Turn at floor 16, round 5 of `FINAL768_DEFAULT_0037`. Rocket died on the third poison tick. Crusher gained 99 rage block before resolving Defend. The simulator assigned 18 block and discarded the existing 99. The opt-in late encounter rule now adds 18. The pinned differential and corrected natural replay both retained Crusher at 12 HP, 117 block, 15 Poison and 9 Strength, with the player at 31 HP on the audited step. The full replay produced 204 matches and 22 boundaries.

The discovery pass produced 71,158 matches, 6,512 boundaries and two differences. Both came from `AUDIT384_SEEDED_0074`. At physical action indices 280 and 323, the public round-two Toasty Mittens prompt showed 3 energy. Selecting a card exhausted it and resumed Candelabra's two-energy grant, leaving 5. The old simulator stayed at 3 in both the Exoskeleton and Spiny Toad fights. The v6.1-rules path now adds the live Candelabra relic's public energy amount after selection on turn two. Each archived command and its before/after digest replayed on the pinned host. The corrected lobby had 286 matches and 18 boundaries.

All seven CSV6DEV lobbies produced 1,781 matches, 207 boundaries and zero differences. All 24 flags-off, 24 active-v5 and 24 shadow CSV2DEV receipts exactly matched their historical full transcript digests and outcomes. Active-v5 produced 2,126 matches and 171 boundaries, shadow 3,534 and 351. All 15 predecessor builder manifest hashes, the Arm 4 manifest and all ten deployed challenger files matched their references. The deployed policy SHA-256 is `a686db12c8b217bd476ea5c8e60cf6f486b060665536ef9354e8f09c21c81fcb`.

One lobby, `AUDIT384_DEFAULT_0107`, had zero comparable steps. It remains in every population denominator. Mismatch totals apply to the physical steps for which the frozen audit emitted a comparison. Unresolved and out-of-scope steps remain visible in the receipts.

## Solo progression

| Starts | Lobbies | Mean floor | A1 clears | A2 boss entries | A2 clears | A3 boss entries | Full wins |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Default | 192 | 25.677 | 128 | 66 | 14 | 5 | 0 |
| Seeded | 192 | 25.401 | 124 | 58 | 15 | 6 | 0 |
| All | 384 | 25.539 | 252 | 124 | 29 | 11 | 0 |

Global floor is `17 × (act − 1) + local floor`. Across 100,425 physical combat decisions the pooled nearest-rank latency was 2.771 ms at p50 and 54.630 ms at p95. The timed path includes copying references to completed leaves. Forecast, pile, deck and death analysis ran after physical selection. Mean HP was 58.0 at first Act 2 boss combat (n=124) and 68.2 at the first public Act 3 state (n=29).

| Act 2 boss | Clears / entries | Mean entry HP on deaths | Median enemy HP at death | Median death round |
| --- | --- | --- | --- | --- |
| Kaiser Crab | 1 / 45 | 56.3 | 263.0 | 4.5 |
| Knowledge Demon | 19 / 42 | 50.7 | 211 | 7 |
| The Insatiable | 9 / 37 | 55.2 | 152.0 | 6.0 |

## Natural coverage and deaths

| Decision group | Covered / non-forced | Coverage |
| --- | --- | --- |
| Act 1 | 39,660 / 60,698 | 65.3% |
| Act 2 hallways | 13,032 / 21,338 | 61.1% |
| Act 2 elites | 1,056 / 2,448 | 43.1% |
| Act 2 bosses | 1,816 / 3,901 | 46.6% |
| Kaiser Crab | 427 / 1,184 | 36.1% |
| Knowledge Demon | 805 / 1,532 | 52.5% |
| The Insatiable | 584 / 1,185 | 49.3% |
| Act 3 | 805 / 2,807 | 28.7% |

A covered root had multiple physical actions and accepted the Arm 4 search result. A champion-equivalent search choice counts as covered. The denominator includes out-of-scope choices. Each boss row is a subset of Act 2 bosses.

| Act | Leading fatal encounters | Deaths | Median remaining enemy HP | Median round | Mean entry HP on deaths |
| --- | --- | --- | --- | --- | --- |
| 2 | Kaiser Crab | 44 | 263.0 | 4.5 | 56.3 |
| 2 | The Insatiable | 28 | 152.0 | 6.0 | 55.2 |
| 2 | Knowledge Demon | 23 | 211 | 7 | 50.7 |
| 2 | Bowlbug Rock, Bowlbug Silk and Slumbering Beetle | 17 | 69 | 4 | 32.8 |
| 2 | Decimillipede | 16 | 69.0 | 4.5 | 48.4 |
| 2 | Infested Prism | 15 | 84 | 3 | 32.5 |
| 2 | Hunter Killer | 11 | 60 | 3 | 22.5 |
| 3 | Axebot | 5 | 53 | 7 | 27.6 |
| 3 | Test Subject | 5 | 102 | 5 | 57.8 |
| 3 | Flail Knight + Spectral Knight + Magi Knight | 4 | 150.0 | 3.5 | 48.5 |
| 3 | Aeonglass | 3 | 300 | 5 | 73 |
| 3 | Soul Nexus | 3 | 48 | 5 | 91.7 |
| 3 | Queen and Torch Head | 3 | 421 | 5 | 69.7 |
| 3 | Globe Head | 2 | 24.5 | 3.5 | 16.5 |

Remaining enemy HP sums living enemies. The pinned host omits the enemy board at game over, so these are the final public pre-action HP totals. They can exceed exact terminal HP when the fatal action also damages an enemy. The death round comes from that same board. The JSON includes every observed formation.

| Act | Eligible choices | Search certification fallbacks | Mechanic/scope fallbacks | Champion/deadline | Most frequent fallback reasons |
| --- | --- | --- | --- | --- | --- |
| 2 | 27,687 | 6,946 | 4,695 | 142 | no certified survival (3,969), champion continuation unresolved (1,900), uncertified root at cap (1,073), selection operation (338), unreconciled prompt (328) |
| 3 | 2,807 | 492 | 1,510 | 0 | no certified survival (289), relic/WHISPERING_EARRING (137), champion continuation unresolved (133), unwitnessed wither count (116), relic/SAI (105) |

| Fatal fights | Deaths | Majority covered | Majority mechanic/scope | Majority certification | Other or mixed | Entered at ≤⅓ max HP |
| --- | --- | --- | --- | --- | --- | --- |
| 2 | 223 | 83 | 32 | 61 | 47 | 60 |
| 3 | 29 | 2 | 16 | 6 | 5 | 7 |

Each majority is strictly above half of eligible physical choices in that fight. Low HP is an independent flag and can overlap every column. A mostly covered loss is a candidate for tactical review. Entry HP, deck size and deck composition describe the resources available to the policy. A single-policy trajectory cannot separate the effects of draft, route and combat choices.

## Schema 4 opportunity

For each non-forced covered root we inspected the same one-turn beam the policy used. We compared surviving completed lines from different root moves. Both had to score within 5 or 10 HP-equivalent utility of the best completed line. One had to finish with at least one more point of combined HP and block, and the other needed at least three more points of damage plus surviving poison credit, or one more initially in-hand Power played. Poison credit is capped at each enemy's remaining HP. A certified victory outranks all ordinary leaves and contributes zero trade-offs. Among qualifying lines the highest-ranked qualifying pair in the narrower available band supplies the forecast witnesses.

| Roots | Covered | Trade-off ≤5 | Trade-off ≤10 | Deterministic t+1 | Material t+1 shift | Deterministic t+2 shape | t+2 attack switch | Distinct piles |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Act 1 | 39,660 | 35.1% | 39.2% | 80.2% | 38.0% | 60.1% | 28.9% | 39.6% |
| Act 2 hallways + elites | 14,088 | 25.1% | 31.4% | 72.8% | 33.9% | 51.4% | 26.2% | 55.3% |
| Act 2 bosses | 1,816 | 24.7% | 33.9% | 49.2% | 38.1% | 36.4% | 22.2% | 59.4% |
| Act 3 | 805 | 27.9% | 34.8% | 72.1% | 44.3% | 49.6% | 16.4% | 71.1% |
| All | 56,369 | 32.2% | 37.0% | 77.6% | 37.2% | 57.4% | 27.9% | 43.9% |

The two trade-off percentages use all covered roots. The five rightmost percentages use the ≤10 trade-off roots in the same row. For intent measures both witness lines must qualify. The t+1 predictor reconstructs each line's pre-End-Turn state, then applies the pinned static graph and public move history to its pre-draw completed state. A unique forecast or a verified table transition qualifies. A material t+1 change switches between zero and positive attack pressure or changes the displayed total by at least eight. The t+2 test requires every compatible move node to lead directly to the same ordinary intent shape for each living enemy. It reports attack kinds and hit counts, conditional on no intervening kill, stun or transformation. It makes no second-turn damage or hand prediction.

Of 20,860 trade-off roots, the static graph gave a unique t+1 preview on 16,157, and the independently verified smaller table applied on 3,588, with overlap. The supplied 89/110 deterministic-monster count describes a catalogue population. The local `902623e` census separately covered 89 playable encounters and 120 concrete graph classes including utility monsters. Neither denominator substitutes for the observed root frequencies. The pilot-rules file contains empirical move-family summaries, including repeated keys with different successors. Only public graph or verified-table transitions contributed to deterministic counts.

Pile metrics use unordered current-root multisets. With at least five cards in draw and a nonempty discard, composition qualified for a ≥25 percentage-point attack or printed-block density gap between draw and discard, a ≥15-point gap between draw and the combined live deck (draw, discard and hand), or a Power identity present in just one pile. Draw/discard attack density qualified on 30.8%, block density on 29.6%, and distinct Power location on 10.0%. A short draw pile with available discards occurred on 26.0%. Including this signal put pile leverage at 69.9%. Both completed witness lines explicitly required reshuffling on 26.4%. Signals overlap.

## Ranked decision

1. **Kaiser Crab coverage and conversion.** Search covered 427 of 1,184 non-forced choices. Of 44 deaths, 13 were majority mechanic/scope fallbacks and 16 majority covered. Of its 255 no-certified-survival roots, 126 produced only unresolved leaves, 70 produced only deaths and 59 produced both. The most frequent explicit boundaries on failed beam roots were centennial puzzle draw (69), draw (61), ambiguous attack preview (38), potion/GAMBLERS_BREW (25). Prioritize public facing and attack-preview ambiguity on these fights. For draw-dependent lines, test whether survival can be certified across possible draws without observing their order. The 263 median enemy HP remaining at death also warrants review of early target choice in covered lines. Kaiser offered 258 competitive trade-off roots, of which 0 qualified for a material t+1 shift. A Schema 4 leaf has limited access to this specific loss population.
2. **Schema 4 one-turn leaf, trained on Arm 4 trajectories.** Across all acts, 20,860 of 56,369 covered roots had a measured competitive trade-off. 7,758 had material t+1 shifts and 9,158 had distinct pile composition. Retain separate unordered draw and discard features and mask abstaining graph forecasts. Test realized conversion separately on development data. An outcome trial would be needed to estimate the win-rate effect.
3. **Macro/deck and Act 3 targeting.** Only 2 of the 44 Kaiser losses started at or below one-third HP. Their mean entry was 56.3 HP, with 28.0 cards, 1.1 Powers and 5.5 upgraded cards on average. A single Kaiser clear gives a poor comparison group for deck quality. Act 3 saw only 29 entrants, 11 boss entries and 0 full wins. Its coverage gaps deserve follow-up as more trajectories reach it. The current evidence supports a targeted Act 2 test before a broad draft or route change.

## Reproduction and evidence

The cohort lock SHA-256 is `69e364e20fc73853d65388367711345cc448a9b1d6a094407882cb928a83bdb2`. The two modes each contain 192 natural Silent A10 starts. All 384 names and xxHash64s were distinct and disjoint from 32,960 scanned or reconstructed historical identifiers, including the complete official 896. The collector accepts locked AUDIT384 names only. The earlier FINAL768 failure was replayed solely as the named regression.

All stress runs used the pinned host on Helmer with 12 workers and both BLAS and OpenMP set to one. The decision hook only records physical command/digest pairs. Diagnostic code consumes public current state, unordered piles and immutable simulated leaves. Native outcomes go to the post-action differential or outcome counters. The final detailed pass and the preceding clean pass matched full snapshot-and-command digests on 380/384 lobbies. Four sanity starts spanning both modes, Act 3 and the discovered failing lobby matched full telemetry-on/off digests and native counters. On the four cross-pass exceptions, further on/off runs matched every physical command (1,965 actions total). Independent pinned hosts receiving identical commands differed only in the event option display field `EntrantNumber` on two observations per lobby. The receipts preserve the original unequal hashes and the supplemental command hashes. The production planner, frozen release and protected legacy modules are byte-identical to the branch base.

`python docs/combat-search-v2/probes/audit384.py --workers 12 --output <fresh-directory>` reproduces the solo pass with the release protocol's pinned host, dependencies and environment. Add `--sanity` in a separate directory for the four on/off comparisons. The graph probe needs the locally fetched `902623e` and `9092ea4` Git objects. `python docs/combat-search-v2/probes/report_audit384.py docs/combat-search-v2/v6-audit-autopsy-receipts.zip` recomputes the complete analysis offline.

The pinned suite passed 606 tests with `pytest -q -p v6_fixture_seeds`. Ruff checked 112 files under `src/` and `tests/` with zero findings. The receipt archive is 597,597 bytes, SHA-256 `ee2a0eb5cf1de5bccb1913701bc8889ecd0aedcf599764ea7e2ee9ea6c5158ff`. It contains the original differences, per-lobby compressed receipts and latency bins, sanity digests, baseline hashes and qualification results. [Machine-readable report](v6-audit-autopsy.json) · [Compact receipts](v6-audit-autopsy-receipts.zip) · [Locked starts](v6-audit384-lock.json)
