# Silent A10 Arm 4 release verification

**Retain frozen v5.** One raw native mismatch stopped FINAL768 after 84 of 768 paired lobbies, with zero retries. The remaining 684 pairs stayed unopened and POOLED896 was skipped. All ten files in the deployed challenger match `efd9877`. Its policy manifest SHA-256 is `a686db12c8b217bd476ea5c8e60cf6f486b060665536ef9354e8f09c21c81fcb`.

## Paired FINAL768 outcomes

Each arm completed 42 default and 42 seeded natural starts. The table describes those 84 pairs. Milestone counts are lobbies. Latency covers physical combat decisions.

| Measure | Frozen v5 | Arm 4 v6 |
| --- | ---: | ---: |
| Mean global floor | 25.274 | 25.286 |
| Act 1 clears | 52 | 54 |
| Act 2 boss entries | 32 | 26 |
| Act 2 clears | 3 | 5 |
| Act 3 boss entries | 2 | 3 |
| Full wins | 0 | 0 |
| Combat decisions timed | 21,689 | 21,840 |
| Decision p50 / p95, ms | 2.038 / 50.909 | 2.845 / 51.171 |
| Native matches / mismatches / boundaries | 13,365 / 0 / 899 | 16,255 / 1 / 1,266 |

Arm 4 averaged 0.012 floors higher on the completed pairs (two-sided stratified paired 95% bootstrap CI [−1.702, +1.726]). It finished higher on 22 lobbies, lower on 21 and tied on 41. The two-sided exact sign-test p-value was 1.000.

| Act 2 boss | v5 clears / entries | v6 clears / entries |
| --- | ---: | ---: |
| Kaiser Crab | 1 / 11 | 1 / 7 |
| Knowledge Demon | 2 / 12 | 2 / 11 |
| The Insatiable | 0 / 9 | 2 / 8 |

## Decision and native audit

| Pre-registered criterion | Result |
| --- | --- |
| 768/768 complete pairs | Fail |
| Zero raw candidate mismatches with positive coverage | Fail |
| Lower floor CI above zero | Fail |
| Exact sign p < 0.01 | Fail |
| Act 1 clears at least v5 | Pass |
| Act 2 boss entries at least v5 | Fail |
| Act 2 clears at least v5 | Pass |

The floor, sign-test and milestone rows describe only the completed pairs. The audit failure decided the gate.

**v6 raw differences**

| Lobby | Act / local floor / round | Formation | Action | First difference |
| --- | --- | --- | --- | --- |
| `FINAL768_DEFAULT_0037` | 2 / 16 / 5 | CRUSHER+ROCKET | end_turn | board/enemies |

End turn was the sole legal action. Rocket died. Both the simulator and the host recorded 12 HP, 15 Poison and 9 Strength for Crusher. The simulator predicted 18 block for Crusher and the host reported 117. The player finished at 31 HP in both. The collector finished the six default and six seeded pairs already dispatched in that batch, then stopped. The frozen candidate received no post-opening changes.

## Development qualification

Each of the seven lobbies was replayed in an arm that produced an archived difference. The compact differential fixtures retain only physical commands, state digests, and public action-count witnesses. They restore the same native decisions regardless of whether the corrected policy still chooses the original line. A second natural replay evaluated the released v5 configuration and the frozen Arm 4 configuration on all seven lobbies.

| CSV6DEV lobby | Archived difference and correction | Arm 4 matches | Arm 4 boundaries |
| --- | --- | ---: | ---: |
| DEFAULT_0007 | Toasty Mittens pauses before extra draw or Blur expires. End-turn search stops at that unresolved start trigger. | 193 | 23 |
| DEFAULT_0034 | Skewer spends enough energy to return Right Hand Hand from discard. Arm 4 applies the public return rule wherever its search is eligible. The raw frozen-v5 mismatch is retained in the qualification receipts. | 161 | 10 |
| DEFAULT_0121 | Aeonglass increases Wither damage separately from the normal card upgrade and increases its Strength gain on later Increasing Intensity moves. The heuristic stops at an in-hand Wither or that scaling move. | 343 | 73 |
| SEEDED_0080 | Precise Cut subtracts its per-card penalty before Strength. Clamping base damage early predicted one point against Tunneler's block. The corrected calculation clamps after Strength. | 124 | 32 |
| SEEDED_0148 | Dagger Throw drew Flick Flack. Its Sly discard auto-play consumed the last Sloth allowance. Search stops at the automatic discard play, and count-dependent continuations wait for a witnessed reset. | 388 | 32 |
| SEEDED_0160 | The Mittens prompt exposed Draw Cards Next Turn before its trigger completed. The same start-turn boundary applies across encounters. | 280 | 13 |
| SEEDED_0186 | The Letter Opener counter remained live during the Mittens prompt. Search stops when the pending counter reset or extra draw would change the compared board. | 292 | 24 |

Across the original five-arm archive the seven lobbies accounted for 44 relic, 22 power, four HP, one legality, one enemy-state and one card-zone difference. The Arm 4 qualification replay had **1,781 matches, 207 explicit boundaries and zero raw mismatches**. Completed-turn audits retain their existing comparison rules. The simulator makes boundary decisions from the current public board. The physical observer runs after action selection.

All 15 prior builder manifests reproduced their archived SHA-256 values. All ten released files separately matched the Git blobs at `efd9877`. The v6 candidate loaded through `DeployedController` with the heuristic leaf and no checkpoint. Each of the 24 flags-off, 24 active-v5 and 24 shadow CSV2DEV transcripts matched the archived digest and outcome. Active-v5 had 2,126 matches and 171 boundaries, shadow had 3,534 matches and 351 boundaries. Flags-off ran without search. All three modes recorded zero mismatches. [Development receipts](v6-release-qualification.zip)

## Reproduction

Commit `98bd1e7965723f95d9f0e6710bf0b2f76b5509a3` froze the code, policies and ordered triples before the first held start. FINAL768 lock SHA-256 is `0afc2bac154b2bf564c41b36cf54ca3337b4d8cd6231a411e3d7567093735aa0`. The candidate manifest SHA-256 is `4b5fe32e78a96ca656cca805f316410b19baa9c4f2c227d25b77a6d1306c93a9`. Both arms used the same pinned v0.111.0 host on Helmer and 12 workers, with single-threaded BLAS and OpenMP. [Decision rule and commands](v6-release-protocol.md)

The archive contains 168 terminal receipts, raw diagnostics, aggregate latency histograms, the run manifest and analysis. Archive SHA-256 is `cdf76e9e99f7f3a8d419b62f8889f75e3f43c55f57599643c31e7a47b9605643`. [FINAL768 receipts](v6-final768-receipts.zip)

The full suite passed all 604 tests before opening the gate and again after closure (267.50 seconds on the final run). Both runs used the pinned host, observer and `pytest -q -p v6_fixture_seeds`. Ruff checked 112 files under `src/` and `tests/` with zero findings. Reanalysis from the extracted archive reproduced the reported results. The retained release loaded its Schema 3 checkpoint through `DeployedController`. After cleanup, this worktree owned 73,334 bytes under `artifacts/`, excluding junctions to the shared pinned dependencies.
