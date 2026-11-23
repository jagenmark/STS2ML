# Silent A10 v5 promotion protocol

Registered before the first official rollout. Every arm uses the ordered triples from the tactics benchmark at `93456cd`. VAL256 has 256 default lobbies, SEEDED128 has 128 seeded lobbies, and REP512 has 256 default and 256 seeded lobbies. Each triple supplies its explicit index to the historical episode runner (macro RNG seed 7103 + index). All three arms use fresh native sessions on the pinned Phase 3 host and game assembly, 12 CPU workers, and one OpenBLAS and OMP thread. Each arm–lobby pair gets one attempt. No tuning or policy changes follow opening.

| Profile | Policy manifest SHA-256 |
| --- | --- |
| all_v2_p1_v4 | `8636337a6082264bffffe9a79b50528bdf30ed9096b74ff33fd20a8e844fa51b` |
| all_v2_search_v5 | `a686db12c8b217bd476ea5c8e60cf6f486b060665536ef9354e8f09c21c81fcb` |
| all_v2_search_heur_v5 | `85de8c968e2b973a2928719bedab2697ddd305e0c55c2654064fcf5f9ebd93c4` |

Both candidates enable combat search with width 16, depth 10, a 512-child cap, a 7.0 HP potion reserve and zero extra win weight. The primary uses the Phase 3 Schema 3 model with SHA-256 `24debeaaa81c0095cf252807e05e858cf53b8dcbf23ed2e9eb274f267112cb0b`. The comparison arm uses the heuristic leaf.

## Decision

Require 896 complete, unique, same-host pairs per arm, zero retries and zero incompletes. For **both POOLED896 and REP512**, the primary against v4 must have a strictly positive lower bound on its 95% paired mean-floor interval and p < 0.01. Act 1 clears, Act 2 boss entries and Act 2 clears must each equal or exceed v4's count on each of these panels. If the primary passes, promote the heuristic instead only when its pooled paired mean-floor interval against the primary lies strictly above zero. Otherwise promote the primary. If the primary gate fails, retain v4.

Global floor is 17 × (act − 1) + local floor. Bootstrap paired lobbies 10,000 times with replacement within each suite and act-list stratum, preserving stratum size, using NumPy default_rng(20261123) and the 2.5th/97.5th percentiles. Report the paired t statistic and two-sided Student t p-value. The promotion p-value uses the historical benchmark's exact two-sided sign test on floor wins and losses, excluding ties. For milestone discordance use the two-sided exact matched binomial test. Results are reported per official suite and pooled for all three contrasts.

Search coverage counts eligible in-combat public decisions in Act 2 boss rooms and throughout Act 3. A combat-play root with no playable card or usable potion is forced and excluded, matching the Phase 3 census. A covered root has no search fallback. Deaths use the fatal action's room and opening formation, with boss identity from the public context. Retain only compact episode receipts and aggregate counts.
