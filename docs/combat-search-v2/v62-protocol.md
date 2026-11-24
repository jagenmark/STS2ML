# Silent A10 v6.2 paired release protocol

The dev cohort has 192 default and 192 seeded fresh natural lobbies. Every arm uses the same ordered triples of macro index, native seed string and act-list mode. The SHA-256 of the UTF-8 lock file is `3f166462911e3a53b863cf48bbcae7ee5fae8796abde68bc44ee4993183b4c04`. Indices within each stratum run from 0 to 191. Each start uses a fresh v0.111.0 process, ascension 10, macro RNG 7103 plus index, a 12-worker pool and single-threaded OpenBLAS/OpenMP. The observer checks comparable physical steps after execution. Record boundaries and raw mismatches separately. Every release decision uses the raw mismatch count.

| Arm | Search at width 16, depth 10, cap 512 | Free reward change |
| --- | --- | --- |
| 1 | Frozen v5 Schema 3 | None |
| 2 | Frozen v6.1 boss-safe heuristic | None |
| 3 | Arm 2 plus v6.2 power leaf and beam development | None |
| 4 | Arm 3 | First synergistic Accelerant |
| 5 | Arm 3 | First synergistic Accelerant, Accuracy, Phantom Blades, or first Infinite Blades |

The separate early Escape intervention remains off for every arm. Its 12 matched native boss fixtures yielded zero additional exit HP and zero additional clears.

## Decision rule

1. Complete all 1,920 dev starts. Require exactly one complete native result per locked triple per arm, at least one comparable observation per arm and zero raw mismatches across the five arms. Run failures invalidate the gate until a documented infrastructure-only retry completes. Keep the policies frozen throughout.
2. Calculate global floor as 17 × (act − 1) + local floor. Use paired percentile bootstrap intervals with 50,000 draws, resampling within each act-list mode, PCG64 seed 620. All comparisons share the same bootstrap indices. Report two-sided 98.75% intervals for arms 2–5 against v5, with familywise alpha 0.05. Report descriptive 95% intervals for 3−2, 4−3, 5−4, 4−2 and 5−2.
3. Eligibility requires a strictly positive simultaneous lower bound against v5 and zero or positive count differences on Act 1 clear, Act 2 boss entry and Act 2 clear. Count entry once per lobby with a native Act 2 boss fight. Of eligible arms take the largest mean floor, breaking exact ties toward the lower-numbered arm. Advance at most one arm.
4. Only on dev success, commit the winning opt-in builder and a new SHA-256 lock for 256 default and 256 seeded FINAL512 lobbies before opening them. Use the same floor and milestone definitions, 50,000 stratified paired draws with seed 621 and a two-sided 95% interval. Require all 512 pairs, zero native mismatches, strictly positive lower bound, two-sided exact binomial sign-test p < 0.01 on non-tied floor pairs and zero or positive count differences on all three milestones.
5. Only after fresh confirmation passes, run the historical POOLED896 continuity comparison. The historical suite cannot select a policy or rescue a failed gate. On a failed selection or release gate, retain the champion at `efd9877`.

[Locked dev triples](v62-dev-lock.json) · [Collector](../../scripts/ablate-silent-v62.py) · [Analysis](../../scripts/report-silent-v62.py)
