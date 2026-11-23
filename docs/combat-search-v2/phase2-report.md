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
