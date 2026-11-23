# Silent A10 combat search v2 — Phase 2

## Recorder and public feature contract

The research recorder loads a read-only .NET startup observer into the pinned
v0.111.0 host. The host executable and the champion bundle retain their original
hashes. The observer writes a separate receipt during the native action and
does not extend the policy observation or issue RPCs. The output also records
fight identity by room sequence, every executed End Turn, and a root admission
census separately from the fight labels. Counts include all visited acts.

The corrected schema 2 has 175 float32 features. It describes the post-enemy board, public
next-turn energy buffs, and the live card multiset by identity, type, and
upgrade. It combines that multiset with the counts at the pre-draw boundary
and the retained subset derived from the pre-End-Turn hand. The observer rejects
any earlier draw before the normal hand draw. The packer requires exact
agreement between the expected retained subset and the pre-draw receipt. It
censors changes to the live multiset, exhaust size, or feature board during
the reveal, and censors intervening prompts. Terminal turns and
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

## Natural collection and blocker census

All 2,048 lobbies completed at 12 workers without retries. The collection
wrote separate census and label files per lobby. The [coverage census](phase2-coverage-census.json)
ranks co-occurring blockers and first-blocker counts using the Phase 1
admission rules. Passing static admission does not certify a search comparison.

| Act | Non-forced roots | Passed admission | Top first blockers |
| --- | ---: | ---: | --- |
| 1 | 295,403 | 27,493 | `kin leader dependency` (15,108) · `plow` (14,352) · `vantom slippery and move hooks` (13,767) · `profile/FLYCONID` (11,012) |
| 2 | 86,033 | 0 | `profile/EXOSKELETON` (10,744) · `profile/TUNNELER` (9,944) · `bowlbug stun source` (9,692) · `profile/THIEVING_HOPPER` (8,608) |
| 3 | 4,653 | 0 | `profile/DEVOTED_SCULPTOR` (682) · `profile/SCROLL_OF_BITING` (632) · `profile/LIVING_SHIELD` (474) · `profile/AEONGLASS` (333) |

### Recorder correction

A train/development receipt audit found that the original observer could
include cards drawn by relics such as Centennial Puzzle and Joss Paper before
the normal hand draw. Its subset check could accept a drawn copy with the same
identity as a pre-End-Turn card. That allowed realized draw information to
enter the retained-hand features. The first model and its ML-test results
were retired. The initial 2,048 trajectories still establish the champion's
actions and encounter census. Across the 1,740 train and development
retraces, all physical actions and terminal results matched. Public digests
matched in 1,735 lobbies. Five differed only in the native event option
`EntrantNumber` field, which also varied between two flags-off replays.
The dedicated 24-lobby receipt gate passed in full.

Schema 2 requires an uninterrupted pre-reveal witness and computes retention
from public pre-End-Turn evidence. The pinned-host Centennial Puzzle fixture
verifies censoring when a native effect draws early. The corrected fit and
calibration use retraced train and development lobbies. The original ML-test
split remains closed after its first opening. The separately approved
[confirmation lock](phase2-confirmation-lock.json) contains 308 new lobbies,
154 per mode, exclusively for the corrected model's final evaluation.

## Coverage qualification

The census pass admitted out-of-combat and combat-opening relics alongside
verified within-turn hooks. Active rules include Paper Krane's Weak modifier,
Ripple Basin and Daughter of the Wind Block, deterministic single-target
Kusarigama damage, the public Pael relic energy transitions, and automatic
single-card discards. Pinned fixtures cover Speed Potion, Gigantification,
temporary dexterity and the added Silent cards.

The supported encounter slices include the Kin, Ceremonial Beast, Flyconid,
Tunneler, Cubex, Vantom, Soul Fysh, Lagavulin Matriarch, Waterfall Giant,
the Rock, Egg and Nectar Bowlbugs, the Insatiable, Entomancer and other
hallways. Tests distinguish encounters with partly qualified moves. Hunter
Killer's Tender follow-up, Kaiser Crab facing, hidden illusion revival,
Bowlbug Silk and Slumbering Beetle, randomly selected actions, and
unobserved multi-phase transitions still use a boundary or champion fallback.

The 24-episode CSV2DEV flags-off and shadow receipts matched the original
Phase 1 summary byte for byte. Corrected native features matched all
460 comparable completed turns within 1e-5. Native diagnostic comparisons
exclude transient off-hand cost and target previews, the post-draw current
energy, and newly revealed positions and telegraphs. Hand costs and legality
at within-turn roots remain compared.

| Shadow bundle | Act 1 | Act 2 | Act 3 | Native mismatches / comparable steps |
| --- | ---: | ---: | ---: | ---: |
| Frozen v3 tactics | 1,195/1,854 (64.5%) | 251/551 (45.6%) | No visits | 0/1,761 |
| Historical Mecha Knight | 809/1,595 (50.7%) | 104/546 (19.0%) | No visits | 0/1,058 |

The v3 shadow panel reached the 45% Act 2 target and fell 0.5 percentage
points short of the 65% Act 1 target. These coverage percentages are
conditional on this development panel's observed non-forced roots. The
held ablation below measures coverage on the larger natural cohort.

## Corrected fit and independent ML test

All 1,740 locked train and development lobbies were retraced. The corrected
training split contains 41,994 usable leaves from 1,432 lobbies.
The observer censored 381 training turns with an earlier native draw.
Each labeled fight has total weight one across its usable turns.
The GPU fit used BCE for win probability and Huber loss for conditional
win HP, with AdamW on the RX 9070 XT and ROCm 7.16.26385.
The 308 development seeds were split into disjoint, mode-balanced groups
of 154 for Platt calibration and 154 for model selection.

| Model | Dev raw Brier | Dev calibrated Brier | Dev log loss | Dev win HP MAE | Dev expected HP MAE | CPU leaf p50 / p95 (ms) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| linear | 0.03565 | 0.03361 | 0.11557 | 4.61 | 4.82 | 0.0261 / 0.0381 |
| mlp32 | 0.03841 | 0.03451 | 0.11894 | 4.83 | 4.95 | 0.0296 / 0.0482 |
| mlp64 | 0.04756 | 0.03952 | 0.13546 | 4.64 | 4.86 | 0.0294 / 0.0337 |

The selected [NumPy artifact](models/combat_value_v2.npz) is the two-head linear fit.
The Platt slope is 1.329956 and the intercept is -0.075492.
Latency uses 7,680 measured calls per candidate with one BLAS thread and
includes public feature packing, float32 forward pass and calibration.
The offline potion-count diagnostic changed selection Brier by +0.000144. The deployed schema excludes potion inventory.

All 308 fresh confirmation lobbies completed. The model and
calibration were frozen before the one-pass evaluation. The sealed cohort
has 8,873 usable leaves from 2,604 weighted fights in 308 lobbies.
Overall Brier was **0.03338**, log loss **0.11867**,
conditional win-HP MAE **4.67 HP** (0.06449 of maximum HP),
and expected exit-HP MAE **4.75 HP** with death at zero.

| Act | Fight weight | Mean P(win) | Observed wins | Brier | Log loss | Win HP MAE | Expected HP MAE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 2100 | 0.918 | 0.924 | 0.0272 | 0.0969 | 4.18 | 4.33 |
| 2 | 483 | 0.802 | 0.830 | 0.0532 | 0.1908 | 6.93 | 6.36 |
| 3 | 21 | 0.717 | 0.714 | 0.1968 | 0.6334 | 7.77 | 9.25 |

| Current HP fraction | Act 1 predicted / observed | Act 2 predicted / observed | Act 3 predicted / observed |
| --- | ---: | ---: | ---: |
| 0–0.25 | 0.631 / 0.577 (162.0) | 0.425 / 0.435 (76.1) | 0.449 / 0.248 (4.8) |
| 0.25–0.5 | 0.817 / 0.829 (298.9) | 0.707 / 0.736 (101.0) | 0.582 / 0.757 (3.6) |
| 0.5–0.75 | 0.955 / 0.972 (865.8) | 0.881 / 0.937 (133.3) | 0.788 / 0.778 (5.2) |
| 0.75–1 | 0.975 / 0.980 (773.3) | 0.963 / 0.977 (172.6) | 0.908 / 0.955 (7.4) |

Parentheses give effective fight weight per bucket. The pooled reliability
table uses 1,000 lobby-bootstrap draws.

| Predicted bin | Leaves | Mean P(win) | Observed wins | 95% seed CI |
| --- | ---: | ---: | ---: | ---: |
| 0.0–0.1 | 271 | 0.032 | 0.076 | [0.036, 0.125] |
| 0.1–0.2 | 156 | 0.147 | 0.172 | [0.092, 0.270] |
| 0.2–0.3 | 133 | 0.243 | 0.176 | [0.081, 0.284] |
| 0.3–0.4 | 137 | 0.350 | 0.228 | [0.136, 0.327] |
| 0.4–0.5 | 173 | 0.451 | 0.368 | [0.264, 0.475] |
| 0.5–0.6 | 172 | 0.555 | 0.498 | [0.379, 0.605] |
| 0.6–0.7 | 267 | 0.650 | 0.592 | [0.496, 0.680] |
| 0.7–0.8 | 371 | 0.754 | 0.746 | [0.675, 0.811] |
| 0.8–0.9 | 608 | 0.858 | 0.916 | [0.883, 0.945] |
| 0.9–1.0 | 6,585 | 0.983 | 0.997 | [0.995, 0.999] |

Artifact SHA-256 `28ad1855c725a39ff1d8b1dc41168011c75cb153dc3b966c04b9ac901324d10a`.

## 2×2 ablation on natural development lobbies

The survival-weight check ran on 52 development lobbies separate from the
256-lobby paired ablation. The comparison used expected exit HP alone
and expected exit HP plus 12 times calibrated P(win).
The mean floors were 20.231 and 20.231, with 21 and 21 Act 1 clears. The selection rule
required a higher mean floor and at least as many Act 1 clears to use 12.
The ablation uses α = 0. Exact victory and death bypass the value model.
A completed surviving turn outranks a boundary with unknown survival.
The same seven-HP reserve price applies once per spent potion.

All five search arms completed 256 paired runs without retries. Each arm
uses the same depth and transitions. Each pair shares the lobby
seed, act list and macro index. The champion results come from the
corrected round of recording. Global floor is 17 × (act − 1) + floor.
The 95% intervals use 10,000 paired bootstrap resamples stratified by
act-list mode. Matched fights share act, floor, room type and opening
formation within a pair. The exit-HP delta includes losses at zero HP.

| Arm | Mean floor | Paired Δ floor [95% CI] | Floor W/L/T | Act 1/2/3 clears | Matched fights | Δ exit HP | Δ HP on matched wins |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Frozen champion | 21.227 | +0.000 [+0.000, +0.000] | 0/0/256 | 126/9/0 | 2,471 | +0.00 | +0.00 |
| Heuristic w8 / c256 | 21.613 | +0.387 [-0.465, +1.203] | 51/34/171 | 135/6/0 | 2,260 | +1.52 | +1.65 |
| Heuristic w16 / c512 | 21.711 | +0.484 [-0.410, +1.328] | 52/32/172 | 135/5/0 | 2,255 | +1.72 | +1.83 |
| Learned w8 / c256 | 21.250 | +0.023 [-0.789, +0.832] | 45/38/173 | 128/5/0 | 2,266 | +1.24 | +1.40 |
| Learned w16 / c512 | 21.324 | +0.098 [-0.695, +0.836] | 48/34/174 | 131/7/0 | 2,280 | +1.31 | +1.38 |
| Heuristic w16 / c256 supplemental | 22.129 | +0.902 [+0.109, +1.664] | 59/29/168 | 141/9/0 | 2,308 | +1.69 | +1.69 |

| Arm | Act 1 coverage | Act 2 coverage | Act 3 coverage | Native mismatches / comparable | All decision p50 / p95 ms | Searched decision p50 / p95 ms | First completed leaf p50 / p95 ms | Child cap hits |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Heuristic w8 / c256 | 36.1% (13,891/38,479) | 9.0% (1,013/11,300) | 0.0% (0/321) | 7/17,642 (0.040%) | 0.436 / 12.848 | 3.562 / 18.903 | 0.007 / 0.010 | 1,780 |
| Heuristic w16 / c512 | 36.6% (14,206/38,819) | 8.5% (963/11,341) | 0.0% (0/274) | 12/17,737 (0.068%) | 0.437 / 19.358 | 3.585 / 34.449 | 0.007 / 0.010 | 1,211 |
| Learned w8 / c256 | 36.0% (13,782/38,238) | 9.4% (1,053/11,174) | 0.0% (0/409) | 11/17,544 (0.063%) | 0.440 / 16.503 | 4.516 / 24.899 | 0.082 / 0.114 | 1,676 |
| Learned w16 / c512 | 36.9% (14,337/38,832) | 11.0% (1,222/11,107) | 0.0% (0/525) | 8/18,117 (0.044%) | 0.439 / 25.600 | 4.589 / 45.846 | 0.082 / 0.114 | 1,256 |
| Heuristic w16 / c256 supplemental | 34.6% (13,315/38,514) | 9.8% (1,173/12,002) | 0.0% (0/493) | 9/17,734 (0.051%) | 0.430 / 14.634 | 3.523 / 19.530 | 0.007 / 0.010 | 3,262 |

| Factorial contrast | Δ floor [95% seed CI] |
| --- | ---: |
| Width increase with heuristic leaf | +0.098 [-0.352, +0.539] |
| Width increase with learned leaf | +0.074 [-0.332, +0.480] |
| Learned leaf at width 8 | -0.363 [-1.137, +0.438] |
| Learned leaf at width 16 | -0.387 [-1.121, +0.363] |
| Width × learned interaction | -0.023 [-0.562, +0.543] |

The most frequent held mismatches were `end_turn/board/enemies` (16), `end_turn/decision` (10), `SURVIVOR/discard/intent` (5), `DEFEND_SILENT/intent` (5), `end_turn/completed zones` (5).
Repeated steps across arms contribute separately to these diagnostic counts.

The four primary floor intervals include zero. At width 8 the learned leaf
changed mean floor by −0.363 versus the heuristic. At width 16 the paired
difference was −0.387. Both intervals include zero. The supplemental
fixed-work control had the highest observed mean floor, +0.902 versus the
champion [0.109, 1.664], with nine Act 2 clears. Its floor contrast is
exploratory because the control was added on observed child-cap use.

Coverage on the held lobbies was below the Act 1 and Act 2 targets for every
arm. The held panel also surfaced native differences after the zero-mismatch
shadow and 52-lobby tuning gates. The most frequent formations among
those differences were `WATERFALL_GIANT` (20), `INFESTED_PRISM` (17), `THIEVING_HOPPER` (5), `SHRINKER_BEETLE + FUZZY_WURM_CRAWLER` (4), `EXOSKELETON + EXOSKELETON + EXOSKELETON` (1). These counts include
repeat observations across arms. Active-run first-leaf timing includes scheduling and call overhead under 12 workers. The single
BLAS thread microbenchmark measures warm standalone leaf latency.

All 414 Python tests passed with the pinned-host fixtures enabled. The
two-lobby CLI learned-shadow gate matched the flags-off physical/RPC and
terminal records. The mandated legacy modules and frozen champion files
match the Phase 1 commit byte for byte.

## Reproducing the corrected study

Use the pinned variables and observer build from the recording gate. The
initial census belongs to the Phase 2 commit that predates the recorder
correction. The following commands reproduce the corrected fit and paired
ablations with fresh output directories.

```powershell
$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '1'
$gpu = "$base/.venv/rocm/Scripts/python.exe"
$data = "artifacts/combat-search-v2/data-certified"
$models = "artifacts/combat-search-v2/models-certified"
$confirmation = "artifacts/combat-search-v2/confirmation"
$ablation = "artifacts/combat-search-v2/ablation-certified"
& $python scripts/collect-combat-v2.py --host $hostPath --output $data --workers 12 --fit-only
& $gpu scripts/train-combat-v2.py fit --data $data --output $models
& $python scripts/time-combat-v2-value.py --models $models
& $python scripts/train-combat-v2.py select --data $data --output $models
& $python scripts/collect-combat-v2.py --host $hostPath --output $confirmation --workers 12 --confirmation-only
& $python scripts/train-combat-v2.py confirm --data $confirmation --output $models
& $python scripts/ablate-combat-v2.py tune --host $hostPath --data $data --model "$models/combat_value_v2.npz" --output $ablation --workers 12
& $python scripts/ablate-combat-v2.py ablate --host $hostPath --data $data --model "$models/combat_value_v2.npz" --output $ablation --workers 12
```
