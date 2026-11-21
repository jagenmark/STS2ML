# Silent A10 Mecha Knight and A7 transfer

Across 9,216 locked A10 lobbies, 113 reached Act 3. The previous policy reached the first Act 3 boss 28 times and the frozen Mecha Knight challenger reached it 28 times. Both policies played the same seeds, and their first action could differ only at Mecha Knight’s visible Windup or the following Heavy Cleave. [Benchmark and paired outcomes](benchmark.json)

| Natural A10 lobbies | Act 3 entries | First boss, previous → challenger | Second boss | Full wins | Mecha fights won |
|---|---:|---:|---:|---:|---:|
| 6,144 | 78 | 20 → 20 | 0 → 0 | 0 → 0 | 0/4 → 0/4 |
| 3,072 | 35 | 8 → 8 | 0 → 0 | 0 → 0 | No encounters |

All four naturally encountered Mecha Knights reached Windup and Heavy Cleave. Silent entered those fights at 31, 32, 35 and 48 HP. The challenger changed an action in each fight and both policies lost all four. The previously published combat policy remains the default and the new checkpoint is an experimental alternative.

On matched A10 seeds, the challenger gained 0 first-boss arrivals and lost 0. The pooled two-sided exact paired p-value was 1. The two cohorts kept their separate registries. All Act 3 entrants and 32 additional earlier losses per cohort were played again from the original lobby. An independently built host checked the recorded endings, Mecha decisions and first action differences.

One registered lobby stopped when its shop still displayed Kifuda after payment and the relic’s card prompt. Both models used the same sold-item correction. The simulator then completed this lobby with its original seed and index. All previously completed incumbent games were retained. [Native shop replay](native-shop-repair.json)

## Cards and potions

Flamethrower can leave four Burns in hand for Windup. On A10, Windup grants five Strength and Heavy Cleave has 40 base damage. The challenger can block or exhaust Burns, draw or redraw while energy is available, account for carried block or debuffs through Artifact, and save a short defensive effect for the incoming hit. It uses only the public state.

On the 60 development fights with carried inventories, the selected policy won 22 and the incumbent won 18. Both won four of nine naturally encountered fights. The remaining 51 were deliberately placed on development maps. In 14 separate potion-replacement scenarios, the counts were three and one. A policy fitted from 391 native counterfactual continuations across 66 decision states won 18 of 60. The fixed plan won the development comparison before either A10 test was opened. [Selection](selection.json) · [Development results](development-panel.json)

The held main practice panel deliberately placed Mecha Knight on 32 new Act 3 entry maps with carried decks and potions. Complete matched fights numbered 32, with 3 incumbent wins and 4 challenger wins.
The held replication practice panel deliberately placed Mecha Knight on 32 new Act 3 entry maps with carried decks and potions. Complete matched fights numbered 32, with 4 incumbent wins and 4 challenger wins.

Across the same 64 held practice openings, net HP lost during the first Windup fell from 299 to 125 in total. The challenger survived the first Heavy Cleave on 62 maps, compared with 54 for the previous model. Full-fight wins rose from seven to eight. In the four natural fights, both survived the first Cleave once. The supplemental archive includes the eight complete natural fight traces, which match the actual lobby action sequences and terminal digests. [First-cycle results](windup-outcomes.json) · [Supplemental traces](https://github.com/jagenmark/STS2ML/releases/download/silent-a10-mecha-knight-20261121/mecha-windup-diagnostics.zip)

## Natural A7 benchmark

The published A10 combat policy transferred directly to A7. It won 0/256 in the first registered series and 2/512 in the fixed follow-up. The selected Mecha challenger won 0/256 and 2/512 on the same lobbies. Every incumbent terminal was independently replayed. Winning policies were also rerun from the lobby with the original index. [Winning seeds and replay receipts](a7-victories.json)

On the identical 256 seeds with the same weights, A7 reached Acts 2 and 3 in 167 and 22 games, respectively, and the final boss in 8. The corresponding A10 totals were 89, 2 and 1. Playing the three historical A10 first-final-boss clears on A7 produced two full wins. The two selected A7 winner seeds both ended at the Act 1 boss when played at A10. Those five cases were selected by outcome. [Same-seed replay results](difficulty-crossover.json)

## Reproduce the study on Helmer

The tag contains the matching policy and training code. The archive contains the previous model, the frozen challenger, the native training cases and counterfactual labels, development fights, test seed lists, per-seed results and replayable commands. Each model file and archive member has a SHA-256 checksum.

From a prepared checkout with the project Python environment active, use a separate worktree for the tagged code. Set `$gameHost` to the path of the corrected native host for the pinned game installation. On Helmer, the host lives under `artifacts/a10-conversion-20261121/runtime/src/Sts2Headless/bin/Curriculum/net9.0/Sts2Headless.dll` in the main project. The Python and native prerequisites are documented in the workstation handoff. [Workstation setup](../../docs/silent-a10-handoff.md)

```powershell
git fetch origin --tags
git worktree add --detach ../sts2-mecha-release silent-a10-mecha-knight-20261121
$project = (Get-Location).Path
$gameHost = "$project/artifacts/a10-conversion-20261121/runtime/src/Sts2Headless/bin/Curriculum/net9.0/Sts2Headless.dll"
Set-Location ../sts2-mecha-release
New-Item -ItemType Directory -Force artifacts | Out-Null
foreach ($part in @("upstreams","tools")) {
    if (!(Test-Path "artifacts/$part")) {
        New-Item -ItemType Junction -Path "artifacts/$part" -Target "$project/artifacts/$part" | Out-Null
    }
}
$env:PYTHONPATH = (Resolve-Path src).Path
gh release download silent-a10-mecha-knight-20261121 --repo jagenmark/STS2ML --pattern silent-a10-mecha-knight.zip
python scripts/archive-mecha-knight.py verify --archive silent-a10-mecha-knight.zip --refit --host $gameHost
python -m zipfile -e silent-a10-mecha-knight.zip artifacts/mecha-state
```

To fit the experimental action ranker again using its native continuation labels, run the command below. Each label binds the teacher bundle, source fingerprints, native host and training case registry. Reserve all published development and test seeds when training the next model.

```powershell
$state = "artifacts/mecha-state"
python scripts/train-mecha-actions.py fit --cases "$state/training/screen-cases" --labels "$state/training/action-labels" --bundle "$state/models/incumbent/policy.json" --output artifacts/mecha-refit
```

To evaluate another set of full games, supply a fresh seed registry and choose the ascension recorded in that registry. For a quick replay of the published primary A7 experiment, use the archived A7 registry and incumbent bundle.

```powershell
python scripts/evaluate-silent-seed-list.py --ascension 7 --seed-lock "$state/a7-seed-lock.json" --partition test --bundle "$state/models/incumbent/policy.json" --host $gameHost --workers 4 --output artifacts/mecha-a7-replay
```
