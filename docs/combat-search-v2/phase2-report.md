# Silent A10 combat search v2 — Phase 2

## Recorder and public feature contract

The research recorder loads a read-only .NET startup observer into the pinned
v0.111.0 host. The host executable and the champion bundle retain their original
hashes. The observer writes a separate receipt during the native action and
does not extend the policy observation or issue RPCs. The output also records
fight identity by room sequence, every executed End Turn, and a root admission
census separately from the fight labels. Counts include all visited acts.

Schema 1 has 175 float32 features. It describes the post-enemy board, public
next-turn energy buffs, and the live card multiset by identity, type, and
upgrade. It combines that multiset with the counts at the pre-draw boundary
and the retained subset of the pre-End-Turn hand. A row is censored if the
reveal changes the live multiset, exhaust size, or feature board, or if cards
in the retained subset lack evidence in the earlier hand. Terminal turns and
unobserved boundaries still produce recorder rows. Potion count is a separate
diagnostic field. The feature packer omits potion inventory, draw order,
post-draw energy, next intents, and lobby and RNG identifiers.

The 24-episode CSV2DEV recording gate matched the Phase 1 flags-off receipts
at every decision, score bit, and RPC digest. All 258 qualified completed-turn
features matched the simulator within 1e-5. The native hidden-draw permutation
fixture produced different next hands and identical feature vectors. The
native Ceremonial Beast fixture preserved the kill HP through the later Act 2
heal. The pinned registry rejected `POTION.SMOKE_BOMB` and
`CARD.ENDLESS_AGONY` as missing models. Smoke Bomb continuation and escape
classification and draw-created live-deck size changes have synthetic
coverage, with a real pinned draw receipt for the latter.

The natural cohort lock contains 2,048 unique lobby names and explicit
per-mode macro indices, with 716 train, 154 development, and 154 sealed test
lobbies in each mode. The SHA-256 commits to all canonical registry rows.
Neither the recorder nor model receives the index or the seed as input.

### Reproducing the recording gate

```powershell
$base = 'C:/Users/gosee/Documents/codex/2026-10-26/new-chat/STS2ML'
$env:PYTHONPATH = "$PWD/src"
$python = "$base/.venv/cpu/Scripts/python.exe"
$hostPath = "$base/artifacts/a10-conversion-20261121/runtime/src/Sts2Headless/bin/Curriculum/net9.0/Sts2Headless.dll"
& ./artifacts/tools/dotnet/dotnet.exe build scripts/headless/combat-v2-observer/CombatV2Observer.csproj @(
  '--artifacts-path', 'artifacts/combat-search-v2/observer',
  "-p:GameLib=$PWD/artifacts/upstreams/sts2-cli/lib"
)
$env:CSV2DEV_HOST = $hostPath
$env:CSV2DEV_OBSERVER = "$PWD/artifacts/combat-search-v2/observer/bin/CombatV2Observer/debug/CombatV2Observer.dll"
& $python docs/combat-search-v2/probes/phase1_gate.py --host $hostPath --output artifacts/combat-search-v2/recording-parity --workers 12 --record-combat-v2 --reference artifacts/csv2dev/baseline
& $python -m pytest -q
```

## Collection and value model

All 2,048 lobbies completed at 12 workers without retries. The collection
wrote separate census and label files per lobby. The [coverage census](phase2-coverage-census.json)
ranks co-occurring blockers and first-blocker counts using the Phase 1
admission rules. Passing static admission does not certify a search comparison.

| Act | Non-forced roots | Passed admission | Top first blockers |
| --- | ---: | ---: | --- |
| 1 | 295,403 | 27,493 | `kin leader dependency` (15,108); `plow` (14,352); `vantom slippery and move hooks` (13,767); `profile/FLYCONID` (11,012) |
| 2 | 86,033 | 0 | `profile/EXOSKELETON` (10,744); `profile/TUNNELER` (9,944); `bowlbug stun source` (9,692); `profile/THIEVING_HOPPER` (8,608) |
| 3 | 4,653 | 0 | `profile/DEVOTED_SCULPTOR` (682); `profile/SCROLL_OF_BITING` (632); `profile/LIVING_SHIELD` (474); `profile/AEONGLASS` (333) |

The regularized linear and two MLP candidates were fit with AdamW on
the RX 9070 XT using ROCm 7.16.26385. Each fight contributes total weight
one across its labeled turns. The win head uses BCE and the conditional
win-HP head uses Huber loss. There were 42,329 training leaves from
1,432 lobbies. The calibration and model-selection groups each had 154
disjoint development lobbies. Platt scaling uses the calibration group only.

| Model | Dev raw Brier | Dev calibrated Brier | Dev log loss | Dev win HP MAE | Dev expected HP MAE | CPU p50 / p95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| linear | 0.03516 | 0.03284 | 0.11041 | 4.61 | 4.72 | 0.0259 / 0.0303 |
| mlp32 | 0.04731 | 0.03972 | 0.13398 | 5.02 | 5.17 | 0.0292 / 0.0334 |
| mlp64 | 0.05013 | 0.04201 | 0.14640 | 4.48 | 4.83 | 0.0296 / 0.0338 |

The selected [two-head linear NumPy model](models/combat_value_v2.npz) uses
`sigmoid(1.596761 × logit -0.294142)` for its win head. The held development
potion-count diagnostic changed Brier by -0.000038. Potion inventory stays
outside the feature schema. CPU timing used one BLAS thread, 7,680 measured
calls per model, and included state packing, float32 inference, and calibration.

The selection receipt was frozen before the single ML-test pass. Test
yielded 9,232 usable leaves from 2,631 fights in 307 of 308 complete lobbies.
Overall Brier was **0.03924**, log loss **0.13244**, conditional win-HP MAE
**4.56 HP** (0.06249 of maximum HP), and expected exit-HP MAE **4.74 HP**.
The latter codes death as zero. There were no natural escapes.

| Act | Fight weight | Mean P(win) | Observed wins | Brier | Log loss | Win HP MAE | Expected HP MAE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 2067 | 0.919 | 0.928 | 0.0334 | 0.1129 | 4.13 | 4.37 |
| 2 | 532 | 0.780 | 0.806 | 0.0601 | 0.2030 | 6.40 | 6.06 |
| 3 | 32 | 0.701 | 0.750 | 0.0678 | 0.2246 | 6.32 | 6.79 |

| Current HP fraction | Act 1 predicted / observed | Act 2 predicted / observed | Act 3 predicted / observed |
| --- | ---: | ---: | ---: |
| 0–0.25 | 0.582 / 0.597 (153.8) | 0.377 / 0.378 (86.1) | 0.165 / 0.254 (3.9) |
| 0.25–0.5 | 0.822 / 0.842 (293.2) | 0.641 / 0.720 (101.7) | 0.558 / 0.644 (10.3) |
| 0.5–0.75 | 0.959 / 0.971 (882.9) | 0.868 / 0.908 (147.9) | 0.831 / 0.853 (9.6) |
| 0.75–1 | 0.982 / 0.981 (737.1) | 0.964 / 0.962 (196.2) | 0.984 / 1.000 (8.2) |

Parentheses give effective fight weight per bucket. Act 3 calibration
has 32 test fights. The pooled reliability table uses 1,000 lobby-bootstrap draws.

| Predicted bin | Leaves | Mean P(win) | Observed wins | 95% seed CI |
| --- | ---: | ---: | ---: | ---: |
| 0.0–0.1 | 429 | 0.033 | 0.079 | [0.046, 0.114] |
| 0.1–0.2 | 179 | 0.145 | 0.240 | [0.171, 0.316] |
| 0.2–0.3 | 189 | 0.247 | 0.354 | [0.263, 0.448] |
| 0.3–0.4 | 174 | 0.353 | 0.571 | [0.459, 0.671] |
| 0.4–0.5 | 169 | 0.456 | 0.551 | [0.438, 0.652] |
| 0.5–0.6 | 214 | 0.546 | 0.555 | [0.456, 0.651] |
| 0.6–0.7 | 254 | 0.653 | 0.659 | [0.580, 0.742] |
| 0.7–0.8 | 329 | 0.753 | 0.796 | [0.723, 0.863] |
| 0.8–0.9 | 469 | 0.856 | 0.856 | [0.803, 0.900] |
| 0.9–1.0 | 6,826 | 0.989 | 0.993 | [0.990, 0.995] |

### Reproducing the collection and sealed evaluation

```powershell
$gpu = "$base/.venv/rocm/Scripts/python.exe"
$data = "artifacts/combat-search-v2/data"
$models = "artifacts/combat-search-v2/models"
& $python scripts/collect-combat-v2.py --host $hostPath --output $data --workers 12
& $gpu scripts/train-combat-v2.py fit --data $data --output $models
& $python scripts/time-combat-v2-value.py --models $models
& $python scripts/train-combat-v2.py finalize --data $data --output $models
```
