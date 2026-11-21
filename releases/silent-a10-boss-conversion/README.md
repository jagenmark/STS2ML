# Silent A10 boss conversion

The frozen challenger reached Act 3 on **15 of 2,048 new seeds (0.73%)**. The preceding boss-escape policy reached it on **8 of 2,048 (0.39%)** under the same corrected rules. Seven matched seeds gained an Act 3 entry, and none lost one. Both policies reached the first Act 3 boss four times and recorded zero full A10 victories. Six of the seven extra entries came against Knowledge Demon and one came against Kaiser Crab. [Per-cohort results and individual gains](benchmark.json)

| Natural Silent A10 games | Paired seeds | Entered Act 2, both | Reached Act 2 boss, both | Act 3, incumbent | Act 3, challenger | Full wins, both |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Initial held-out batch | 1,024 | 329 | 71 | 5 | 9 | 0 |
| Independent Helmer replication | 1,024 | 338 | 88 | 3 | 6 | 0 |
| Combined | 2,048 | 667 | 159 | 8 | 15 | 0 |

Each pair started in the same fully unlocked native lobby with the same seed, act selection and original macro-policy index. The first batch ran the incumbent on Linux and the challenger on Linux and Helmer. The replication ran both arms on Helmer. Its seeds were registered before examination of the first held-out results. All 2,048 pairs had identical Act 1 actions. An independent native build reproduced all 2,151 distinct physical histories covering 4,096 scored games. The two-sided exact paired p-value for Act 3 entry is 0.125 in the first batch, 0.25 in the replication and 0.015625 pooled. [Frozen selection](selection.json) · [First seed registry](seed-lock.json) · [Replication registry](replication-seed-lock.json)

| Act 2 boss | Identical first hands | Incumbent wins | Challenger wins |
| --- | ---: | ---: | ---: |
| Knowledge Demon | 54 | 1 | 7 |
| Kaiser Crab | 50 | 1 | 2 |
| The Insatiable | 55 | 6 | 6 |

## Native rules and model selection

The pinned v0.111.0 game calls Knowledge Demon's choice screen with `canSkip=false`. Its test-selector path passes bounds of 0–1 to the headless adapter. The host patch restores the minimum of one for the three curse pairs and checks selection bounds before resolving a prompt. Choosing either card applied its named power in a native fight. Linux and Helmer reproduced the same observations and the server rejected a direct skip. On 33 historical training openings the preceding policy won 18 under the permissive adapter and one under the corrected rule. Those are paired replay results for this boss. [Native observations](native-mechanics.json) · [Training diagnostics](diagnostics.json)

Both benchmark arms use that correction. The challenger takes Mind Rot, Sloth and Waste Away when offered against Disintegration. Against Kaiser Crab it scores the change in incoming damage when a targeted card or potion turns Silent and gives Rocket a target preference. At one native opening the same Strike aimed at Crusher left Silent at 9 HP. Aiming it at Rocket left her at 4 HP. The incumbent Sandpit rule won the model-selection comparison for The Insatiable.

The fit compared full native fights from 89 of 90 historical training arrivals and 28 development arrivals. One older physical history failed replay. The Knowledge Demon policy won 6 of 33 training fights and 4 of 11 development fights. The corrected incumbent won 1 and 2 respectively. The selected crab plan won 1 of 18 training fights versus 0 for the incumbent. Both went 0 of 9 during development. On a separate set of 21 natural boss openings collected from 256 new training lobbies after freezing, the challenger won 3 and the incumbent 2. [Selection rule](selection-rule.json) · [Per-boss fit](fit.json)

Changing one Bowlbug card choice on 29 matched runs produced 13 boss arrivals versus 10, and the same four seeds reached Act 3. Two boss-aware draft alternatives were tested from 48 training maps and 48 separate development maps. The leaner draft gained four boss arrivals in training and two in development, with equal Act 3 entries in both comparisons. Six HP thresholds at the final campfire were also tested. All 117 paired campfires could be completed after handling prompts that open before the first boss hand. The incumbent threshold tied the best survival count in both sets. The frozen model uses the incumbent draft and campfire weights. [Draft results](draft-experiment.json) · [Single-action and campfire results](diagnostics.json)

## Run the checkpoint

The inference manifest is `challenger/policy.json`. It verifies the hashes of all seven model files. Each policy decision uses the public observation and prior targeted actions. The corrected headless adapter is part of this Git branch. The pinned game assets, localized lookup tables and .NET SDK come from a prepared local installation. [Workstation setup](../../docs/silent-a10-handoff.md)

On a prepared Linux checkout, run the following from the repository root. Choose an unused output directory for a new batch.

```bash
export PYTHONPATH="$PWD/src"
python scripts/build-silent-host.py --output artifacts/boss-conversion-host
HOST_DLL="$PWD/artifacts/boss-conversion-host/src/Sts2Headless/bin/Curriculum/net9.0/Sts2Headless.dll"
python scripts/optimize-silent.py evaluate --host "$HOST_DLL" \
  --bundle releases/silent-a10-boss-conversion/challenger/policy.json \
  --roles candidate --seeded-acts --prefix MY_A10_BATCH_ --seeds 64 --workers 4 \
  --record-rooms --output artifacts/my-a10-batch
```

Helmer has a localized runtime and a worktree for this experiment. With PowerShell in the experiment's `source` directory, the following starts a batch using that installation.

```powershell
$study = Split-Path -Parent (Get-Location).Path
$project = Split-Path -Parent (Split-Path -Parent $study)
$py = Join-Path $project 'artifacts/act2-hallways-20261120/venv/Scripts/python.exe'
$gameHost = Join-Path $study 'runtime/src/Sts2Headless/bin/Curriculum/net9.0/Sts2Headless.dll'
$env:PYTHONPATH = (Resolve-Path src).Path
& $py scripts/optimize-silent.py evaluate --host $gameHost --bundle releases/silent-a10-boss-conversion/challenger/policy.json --roles candidate --seeded-acts --prefix MY_HELMER_A10_ --seeds 64 --workers 4 --record-rooms --output artifacts/my-helmer-batch
```

## Continue training

The release archive contains both complete model bundles, natural boss openings with their physical action prefixes, paired training labels, the candidate plans and selection rule, the development and test registries, both machines' native mechanics checks, and per-game actions and independent replay receipts. Its manifest hashes every payload. The fit can be repeated using the archived labels on a machine with the Python project installed. [Download the archive](https://github.com/jagenmark/STS2ML/releases/tag/silent-a10-boss-conversion-20261121)

```bash
gh release download silent-a10-boss-conversion-20261121 --repo jagenmark/STS2ML --pattern 'silent-a10-boss-conversion.zip'
PYTHONPATH=src python scripts/archive-boss-conversion.py verify --archive silent-a10-boss-conversion.zip --refit
```

The verifier checks both seed cohorts, recomputes each physical history fingerprint, totals the results from the individual games, and refits the frozen policy. For new comparisons, extract the archive and run `scripts/study-act2-bosses.py compare` on `roots/training` or a new training collection. The scripts record the actor source, weights, collector and native host. Historical labels retain their original identities. Reserve both published test registries when constructing future training sets.

Helmer downloaded the published archive, verified all 631 entries and refitted the same model bytes as Linux. The extracted weights and training maps are ready in `artifacts/a10-conversion-20261121/training-state` in the Helmer project. Playing all 17 maps on Windows with those weights reproduced each Linux terminal state. [Cross-machine verification](helmer-verification.json)

## Act 3 training maps

A check of 29 archived training prefixes found 25 whose physical history contained the old Knowledge Demon skip. The exact rejected command and the offered native curse pair were recovered for all 25. From 110 training boss arrivals we identified 17 fights the frozen model won. Replaying their historical prefixes and then playing the boss under the corrected rules produced 17 new Act 3 map openings. An independent build restored all 17. Resuming the incumbent Act 3 combat style from those maps reproduced all 17 terminal states of the continuous training runs. [Act 3 map checks and conditional results](act3-training.json)

The main gains still end before the first Act 3 boss. The seven additional held-out runs died on Act 3 floors 3–13. On the separate 17 rebuilt training maps, the deployed style reached the first boss six times. The alternative guard and tempo styles also finished without a full victory. To investigate these losses, extract `experiments/act3-training-maps.zip` from the release archive and point the matched runner at its `maps` directory. It retains the original seed index, lobby configuration, full physical prefix and public map digest.

```bash
PYTHONPATH=src python scripts/study-act2-preparation.py --act 3 \
  --openings artifacts/act3-training/maps --bundles artifacts/act3-training/bundles/engine/policy.json \
  --host "$HOST_DLL" --workers 3 --output artifacts/act3-training-continued
```

In the Helmer PowerShell session above, the equivalent command uses the extracted release.

```powershell
$state = Join-Path $study 'training-state'
& $py scripts/study-act2-preparation.py --act 3 --openings "$state/act3-training/maps" --bundles "$state/models/challenger/policy.json" --host $gameHost --workers 4 --output "$study/next-act3-batch"
```

### Opening decisions in fatal rooms

On the 11 training runs that died before the Act 3 boss, all 11 controls reproduced the original terminal state. Ten fatal rooms offered a first combat action or a card selection. We played all 101 alternative choices to the end of the game. Two encounters could be survived by changing the opening move. Against three Scrolls of Biting, opening with Piercing Wail left Silent at 5 HP after the fight. Against Fabricator, Survivor left her at 19 HP and a Swift Potion left her at 17 HP. The deployed policy opened both fights with Noxious Fumes. Every alternative run still ended before the Act 3 boss. [Training results and replay archive checksum](act3-opening-actions.json)

Simply delaying Noxious Fumes in these two encounters and playing the next highest-scoring action led the model to select Panic Button or Backflip. Both runs still died on floor 4. Across all 17 training maps this follow-up still reached the boss six times and won zero games. An independent engine reproduced all 112 terminal states in the opening-action comparison. The supplement includes the public choices, full native action traces and the follow-up results. [Download the training experiment](https://github.com/jagenmark/STS2ML/releases/download/silent-a10-boss-conversion-20261121/silent-a10-act3-opening-actions.zip)

From the Helmer session above, this reruns the comparison on the archived training maps.

```powershell
& $py scripts/study-act3-opening-actions.py --data "$state/act3-training" --bundle "$state/models/challenger/policy.json" --host $gameHost --workers 4 --output "$study/next-act3-opening-test"
```
