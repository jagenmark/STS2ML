# Silent A10 encounter and draft experiment

The selected policy was **boss-escape** on the fully unlocked standard lobby and pinned v0.111.0 engine. The original release remains the published benchmark. All three arms received the same 192 native opening digests. The source hash and component checksums were locked before reading the separate test results. [Selection](selection.json) · [Locked seeds](seed-lock.json) · [Original benchmark](../../docs/silent-a10-progression.md)

| Policy | Completed | Terminal proof | Entered Act 2 | Entered Act 3 | Full victories |
| --- | ---: | ---: | ---: | ---: | ---: |
| Published challenger at its release commit | 192 | 192 | 60 | 1 | 0 |
| Same weights on the reviewed code | 192 | 192 | 60 | 1 | 0 |
| Selected experiment boss-escape | 192 | 191 | 58 | 2 | 0 |

On 191 paired, terminal-verified seeds against the published release, the new policy alone reached Act 3 on 1 seeds and the release alone on 0 (two-sided exact paired p = 1.000). Against the same-weight code control, 1 favored the candidate and 0 favored the control. The report includes the paired results for all three endpoints and both starting biomes. [Test results](test-report.json) · [Per-game evidence](test-games.jsonl.gz)

On seed A10POOLTEST190068, both policies took the same actions until round four against The Insatiable. The control ended the turn. The candidate played Frantic Escape, survived the boss, and reached floor 11 of Act 3. Across the test suite the candidate reached the Act 2 boss 12 times and the Act 3 boss 0 times. A higher full-game win rate remains unproven. [First changed decisions](paired-first-changes.json)

Candidate seed A10POOLTEST190189 produced an Act 1 loss on both native builds with all 143 legal actions. In the direct retries the last observation had a different digest. Its original 149-request transcript is byte-for-byte identical after removing timing to the separately replay-verified control transcript. The paired statistics use the 191 candidate digests reproduced directly. [Detailed exception](terminal-exceptions.json)

The finalist uses Waterfall Giant = guard, Lagavulin Matriarch = engine, Vantom = engine, Ceremonial Beast = guard. Its public Sandpit escape threshold is 4. Each of the seven model files required to run it is included under the challenger directory and in the downloadable archive. [Portable policy ZIP](policy.zip) · [Model settings and checksums](challenger/policy.json)

## Development and training

The 96 development seeds and the 192 test seeds were reserved before collecting new labels. The primary endpoint was a full victory, followed by entry to Act 3 and entry to Act 2. A policy could enter the final comparison after completing all 96 development games by the recorded cutoff. Only one experimental policy played the final seed set. [Development games](development.json) · [Training studies and conditional results](studies.json)

| Completed development policy | Entered Act 2 | Entered Act 3 | Full victories |
| --- | ---: | ---: | ---: |
| escape | 39 | 5 | 0 |
| boss-escape | 40 | 7 | 0 |
| boss | 40 | 6 | 0 |
| hallway | 37 | 5 | 0 |
| kin-escape | 41 | 6 | 0 |
| hallway-boss | 38 | 6 | 0 |
| late112-boss | 40 | 5 | 0 |
| late48 | 39 | 4 | 0 |
| opening128 | 31 | 1 | 0 |
| pilot | 36 | 3 | 0 |
| pool-route | 37 | 3 | 0 |
| mechanics | 36 | 2 | 0 |
| late-combat | 39 | 4 | 0 |
| control | 39 | 5 | 0 |

The sandpit intervention saved energy to play Frantic Escape during The Insatiable's visible countdown. Threshold four won 4 of 26 matched boss openings, including 1 of 6 reserved archive openings. Threshold zero won 0. One source fight lacked a confirmed completion. The boss-style table used 177 matched openings with five styles. The table and original style each won 20 of 39 reserved fights.

The hallway study restored one area-damage offer per eligible seed, played every card and skip through the next ordinary battle, and compared runs that faced the same enemies. On the archived Dagger Throw versus Dagger Spray decision, Spray left 54 HP and Throw 48 HP under the specified continuation. Across 32 matched roots drawn after the pilot freeze, its small area bonus changed 7 picks and changed total post-fight HP by -2. The confirmed collector follows actual map-room entries and skips event-scripted fights. The archived pilot data and corrected observations are both available. [Inspect the score breakdown](../../docs/silent-a10-draft-scores.md)

## Run on Helmer

Fetch the experiment branch in an existing clone. A separate worktree lets the current checkout keep its local changes. Set the Python interpreter and host paths to the prepared installations on that machine. A new host requires the matching Steam game files and the setup described in the existing guide. [Windows setup and original training archives](../../docs/silent-a10-handoff.md)

```powershell
git fetch origin
git worktree add ..\STS2ML-encounter origin/codex/a10-encounter-draft
cd ..\STS2ML-encounter
$env:PYTHONPATH = (Resolve-Path src).Path
$experiment = "releases/silent-a10-encounter-draft"
# $python and $engine are paths to the existing Python executable and headless DLL.
& $python scripts/verify-silent-encounter-archive.py $experiment
& $python scripts/optimize-silent.py evaluate --host $engine --bundle "$experiment/challenger/policy.json" --roles candidate --seeded-acts --prefix HELMERFRESH01 --seeds 1 --workers 1 --record-strategy --explain-drafts --output artifacts/helmer-fresh01
& $python scripts/show-silent-draft.py artifacts/helmer-fresh01/candidate/run-0000/draft-scores.jsonl.gz
```

The archived finalist produced 1456 card rewards with 5824 legal alternatives. Every chosen action matched the native action history and every option's terms reconstructed its total. The saved score logs can be inspected directly after extraction.

```powershell
Expand-Archive "$experiment/draft-scores.zip" artifacts/test-drafts
& $python scripts/show-silent-draft.py docs/evidence/silent-a10-draft-example.json --step 42 --compare DAGGER_THROW DAGGER_SPRAY
& $python scripts/show-silent-draft.py artifacts/test-drafts/A10POOLTEST190000/draft-scores.jsonl.gz
```

## Resume fitting

The training-state archive contains the new per-action native outcomes, public encounter-pool histories, fitted specialists, teacher recipes, sealed shard checksums and grouped fit reports. The original public decision states and native action histories used to fit the new draft weights come from the November training release. Restore both archives before refitting. The final test games and score logs are reserved for evaluation.

```powershell
& $python scripts/restore-silent-a10.py --check-training
Expand-Archive "$experiment/training-state.zip" artifacts/encounter-training
$state = "artifacts/encounter-training"
$rooms = "artifacts/silent-a10-training-state/rooms"
$baseline = "artifacts/silent-a10-progression-release/challenger/policy.json"
& $python scripts/fit-silent-matchups.py fit --source "$rooms/on-policy" "$rooms/strategy" --labels "$state/late-labels" --receipt "$state/late112-ledger.json" --seed-lock "$state/seed-lock.json" --bundle $baseline --stage late --shared --output artifacts/late-draft-refit
```

For the early-draft fit, use the biomes and progression source directories, `draft-labels`, `opening192-ledger.json`, `--stage opening` and `--contexts "$state/contexts"`. The collecting teacher came from commit `a4be471`. Its source fingerprints, weights and host hashes are preserved in the sealed receipts. To reproduce the boss-style fit from those historical encounter labels, run the current fit script with `PYTHONPATH` pointing to the collecting commit's `src` directory. This preserves the teacher-provenance check.

[All 576 action histories](test-action-histories.jsonl.gz) · [First changed native decision per seed](paired-first-changes.json) · [Independent build verification](cross-host.json) · [Draft log audit](draft-audit.json) · [Artifact checksums](SHA256SUMS)
