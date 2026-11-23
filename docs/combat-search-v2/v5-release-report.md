# Silent A10 v5 release verification

**Promoted `all_v2_search_v5` with the frozen Schema 3 value model.** On POOLED896 it gained 1.138 floors over v4 (95% CI +0.545 to +1.719). On unseen REP512 it gained 1.117 floors (+0.295 to +1.930). Act 1 clears, Act 2 boss entries and Act 2 clears all increased on both panels. The heuristic gained 0.131 floors over Schema 3 on POOLED896 (−0.367 to +0.624). Its interval includes zero, so the pre-registered rule selects the primary.

All three arms finished the same 896 lobbies, giving 2,688 unique terminal results on the first attempt with zero retries, incompletes or abandoned runs. The v4 rerun exactly reproduced the historical pooled and REP512 mean floors and all six milestone counts. Code, profiles, model and promotion rule were committed at `5d20083b065c96479280987c10d131348658d922` before the first held rollout. [Protocol](v5-protocol.md)

## Outcomes

Boss counts are lobbies entering boss combat, and clears count lobbies reaching the next act. A win requires native victory with both Act 3 boss floors verified. VAL256's Schema 3 floor interval crosses zero and its Act 2 boss count fell by two. The pre-registered replication panel was REP512.

| Cohort | Arm | Mean floor | A1 boss | A1 clear | A2 boss | A2 clear | A3 boss | Wins |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| VAL256 | v4 | 23.309 | 221 | 158 | 63 | 11 | 4 | 0 |
| VAL256 | Schema 3 | 24.148 | 241 | 164 | 61 | 12 | 4 | 0 |
| VAL256 | Heuristic | 24.672 | 233 | 167 | 75 | 15 | 6 | 0 |
| SEEDED128 | v4 | 22.656 | 114 | 66 | 27 | 5 | 2 | 0 |
| SEEDED128 | Schema 3 | 24.477 | 117 | 81 | 37 | 6 | 4 | 0 |
| SEEDED128 | Heuristic | 23.844 | 117 | 73 | 33 | 5 | 4 | 0 |
| REP512 | v4 | 23.109 | 448 | 309 | 111 | 23 | 11 | 0 |
| REP512 | Schema 3 | 24.227 | 473 | 334 | 136 | 26 | 8 | 0 |
| REP512 | Heuristic | 24.352 | 475 | 330 | 142 | 26 | 7 | 0 |
| POOLED896 | v4 | 23.102 | 783 | 533 | 201 | 39 | 17 | 0 |
| POOLED896 | Schema 3 | 24.240 | 831 | 579 | 234 | 44 | 16 | 0 |
| POOLED896 | Heuristic | 24.371 | 825 | 570 | 250 | 46 | 17 | 0 |

## Paired global-floor results

Each 95% interval resamples paired lobbies within suite and act-list mode. The promotion p-value is the two-sided exact floor sign test. W/L/T compares the first arm in the contrast with the second.

| Cohort | Floor contrast | Δ | 95% CI | Paired t | Sign p | Paired t p | W/L/T |
| --- | --- | --- | --- | --- | --- | --- | --- |
| VAL256 | Schema 3 − v4 | +0.840 | [-0.207, +1.855] | +1.573 | 0.168 | 0.117 | 85/67/104 |
| VAL256 | Heuristic − v4 | +1.363 | [+0.469, +2.305] | +2.923 | 0.026 | 0.00378 | 82/55/119 |
| VAL256 | Heuristic − Schema 3 | +0.523 | [-0.414, +1.484] | +1.086 | 0.661 | 0.279 | 68/62/126 |
| SEEDED128 | Schema 3 − v4 | +1.820 | [+0.414, +3.258] | +2.491 | 0.00921 | 0.014 | 44/22/62 |
| SEEDED128 | Heuristic − v4 | +1.188 | [-0.125, +2.547] | +1.725 | 0.0769 | 0.0869 | 39/24/65 |
| SEEDED128 | Heuristic − Schema 3 | -0.633 | [-2.008, +0.812] | -0.880 | 0.382 | 0.381 | 28/36/64 |
| REP512 | Schema 3 − v4 | +1.117 | [+0.295, +1.930] | +2.658 | 7.48e-05 | 0.0081 | 188/118/206 |
| REP512 | Heuristic − v4 | +1.242 | [+0.422, +2.059] | +2.968 | 0.00108 | 0.00314 | 176/119/217 |
| REP512 | Heuristic − Schema 3 | +0.125 | [-0.514, +0.764] | +0.378 | 0.703 | 0.706 | 120/127/265 |
| POOLED896 | Schema 3 − v4 | +1.138 | [+0.545, +1.719] | +3.758 | 1.77e-06 | 0.000182 | 317/207/372 |
| POOLED896 | Heuristic − v4 | +1.269 | [+0.705, +1.834] | +4.366 | 9.93e-06 | 1.41e-05 | 297/198/401 |
| POOLED896 | Heuristic − Schema 3 | +0.131 | [-0.367, +0.624] | +0.511 | 0.703 | 0.609 | 216/225/455 |

## Act 2 boss and Act 3 diagnostics

Schema 3 reached 234 Act 2 bosses and cleared 44. Kaiser Crab killed 69 runs, Knowledge Demon 62 and The Insatiable 59. Search covered 625 of 7,093 eligible boss decisions (8.8%). All 625 were against The Insatiable (625/2,426). Kaiser Crab had 0/2,029 covered and Knowledge Demon had 0/2,638. The most frequent fallback reasons were `knowledge demon prompt/sloth` (2,326), `kaiser facing` (1,867), `selection operation` (286) and `unreconciled prompt` (282).

All 44 Schema 3 Act 3 entries ended in death. The Queen killed seven, Test Subject six and Aeonglass three. Among the other 28 deaths, the Punch Construct with two Cubex Constructs killed four. Search covered 54/3,860 eligible Act 3 decisions (1.4%). Missing profiles for Scroll of Biting (471), Living Shield (376) and Slimed Berserker (311) were the most frequent fallback reasons. Pooled Act 3 boss entries went from 17 with v4 to 16 with Schema 3. Every arm recorded zero full wins.

| Fatal opening formation in Act 3 | Schema 3 deaths |
| --- | --- |
| TORCH_HEAD_AMALGAM+QUEEN | 7 |
| TEST_SUBJECT | 6 |
| PUNCH_CONSTRUCT+CUBEX_CONSTRUCT+CUBEX_CONSTRUCT | 4 |
| AEONGLASS | 3 |
| AXEBOT | 3 |
| FLAIL_KNIGHT+SPECTRAL_KNIGHT+MAGI_KNIGHT | 3 |
| OWL_MAGISTRATE | 3 |
| SLIMED_BERSERKER | 3 |
| THE_LOST+THE_FORGOTTEN | 3 |
| GLOBE_HEAD | 2 |
| MECHA_KNIGHT | 2 |
| DEVOTED_SCULPTOR | 1 |
| FABRICATOR | 1 |
| FROG_KNIGHT | 1 |
| SCROLL_OF_BITING+SCROLL_OF_BITING+SCROLL_OF_BITING | 1 |
| SCROLL_OF_BITING+SCROLL_OF_BITING+SCROLL_OF_BITING+SCROLL_OF_BITING | 1 |

The JSON includes eligible-root counts and all fallback reasons for both search arms by encounter. The compact receipts preserve both the public boss context and the actual opening enemies. On the second Act 3 boss floor the public context can still name the first boss. The formation breakdown uses the observed enemies on the fatal floor. [Benchmark](../../releases/silent-a10-v2-tactics/benchmark.json) · [Episode receipts and run manifest](../../releases/silent-a10-v2-tactics/v5-receipts.zip)

## Reproduction

The full pinned-host suite passed 467 tests and Ruff reported zero findings across `src/` and `tests/`. All 13 pre-existing builder profiles reproduced their original bundle bytes. The eight v4 files also matched the release at `93456cd`. The promoted directory matches the evaluated primary byte-for-byte and loads through `DeployedController`. Reanalysis from the 109,627-byte receipt archive reproduced every paired comparison and the promotion decision.

Use the pinned CPU interpreter, `PYTHONPATH=src`, and `OPENBLAS_NUM_THREADS=1` and `OMP_NUM_THREADS=1`. The runner verifies the official seed registry, bundle manifests, host and game SHA-256 before opening a lobby. It runs the normal A10 episode evaluator with 12 workers and writes compact terminal results. To recompute statistics alone, extract the receipt archive into a directory and pass that directory to the reporting script using Python with NumPy and SciPy.

```powershell
& $cpu scripts/verify-silent-v5.py --host $pinnedHost --workers 12 --output artifacts/v5-reproduction
py scripts/report-silent-v5.py artifacts/v5-reproduction
```

The release manifest SHA-256 is `a686db12c8b217bd476ea5c8e60cf6f486b060665536ef9354e8f09c21c81fcb`. The bundled Schema 3 checkpoint SHA-256 is `24debeaaa81c0095cf252807e05e858cf53b8dcbf23ed2e9eb274f267112cb0b`. The v5 bundle adds the active search switch, its configuration and the checkpoint to the v4 components. [Frozen policy](../../releases/silent-a10-v2-tactics/challenger/policy.json)
