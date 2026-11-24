# Silent A10 Arm 4 release protocol

The only candidate is `all_v2_search_v6`, with manifest SHA-256 `4b5fe32e78a96ca656cca805f316410b19baa9c4f2c227d25b77a6d1306c93a9`. It uses the v6.1 hallway and boss-safe scopes, v6.2 power heuristic, Accelerant-only reward adjustment, width 16, depth 10, cap 512 and potion reserve 7. Its comparator is released v5 with manifest SHA-256 `a686db12c8b217bd476ea5c8e60cf6f486b060665536ef9354e8f09c21c81fcb`. Freeze the builder, transition fixes, collector, analysis, decision rule and lock together before opening any held lobby.

## Population and execution

The 768 ordered triples interleave 384 default and 384 seeded natural Silent A10 starts. Each pair shares its seed, act-list mode and macro index. The UTF-8 lock SHA-256 is `0afc2bac154b2bf564c41b36cf54ca3337b4d8cd6231a411e3d7567093735aa0`. Before this freeze, the fetched Git refs had no occurrence of the FINAL768 namespace. The 768 names and their UTF-8 xxHash64 values were unique and disjoint from 76,963 historical identifiers and reserved names. The check scanned tracked scripts, locks, documents and compressed receipts, reconstructed the CSV2 and CSV3 registries, and expanded 75 historical or reserved prefixes through index 1023. This includes all 896 official triples.

Use fresh pinned v0.111.0 processes on Helmer, 12 workers, single-threaded BLAS/OpenMP and zero retries. Host SHA-256 is `7408d040c28416331279a84e299b52ff35086d80b4cb9711aefd0f91168d8f20`. Game SHA-256 is `14b57dbaee1b58cb919625a662831054fd714b3b75b13b7449eac0e95b98a3e4`. Each worker runs v5 then v6 on one triple. Submit batches of 12 pairs. Retain terminal receipts, raw native differences and pooled physical combat-decision latency histograms rounded to the nearest microsecond. Report empirical nearest-rank p50 and p95. Temporary RPC records contain command and response digests and expire with each episode. The observer receives the physical outcome after the decision.

## Promotion

1. Require 768 complete pairs, 0 retries and 0 raw candidate mismatches on comparable steps, with positive audit coverage. On a candidate mismatch or incomplete start, finish only the already-dispatched batch and stop. Preserve all results and skip POOLED896. On early termination report statistics for completed pairs as descriptive, with the denominator.
2. Compute global floor as 17 × (act − 1) + local floor. Bootstrap the paired v6 minus v5 floor differences within each act-list stratum at its original size, 50,000 draws, NumPy PCG64 seed 621, default then seeded, in chunks of 500 per stratum. Require the 2.5th percentile to exceed zero. Use the 97.5th percentile as the upper limit. Require a two-sided exact binomial sign test on non-ties with p < 0.01.
3. Require v6 counts at least equal to v5 on each of Act 1 clears, Act 2 boss entries and Act 2 clears. Count boss entries once per lobby. A full win requires native victory and both Act 3 boss floors.
4. Only after all criteria pass, run the official VAL256 + SEEDED128 + REP512 continuity panel and freeze the evaluated candidate. Report both panels and the historical lineage. Otherwise retain the release at `efd9877`. There is one candidate, one opening, and no post-opening policy changes or reselection.

Run the collector with the CPU interpreter, `PYTHONPATH=src`, `CSV2DEV_HOST` set to the pinned Curriculum DLL and both thread limits set to 1. The first invocation is `python scripts/verify-silent-v6.py --panel final768 --workers 12 --output artifacts/release-v6`. The continuity invocation uses the same output root and `--panel pooled896`. Each panel requires a fresh subdirectory. After extraction of the receipts, `python scripts/report-silent-v6-release.py <panel-directory>` recomputes the result without opening a lobby.

[Locked triples](v6-final768-lock.json) · [Collector](../../scripts/verify-silent-v6.py) · [Analysis](../../scripts/report-silent-v6-release.py)
