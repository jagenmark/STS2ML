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
actions and encounter census.

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
