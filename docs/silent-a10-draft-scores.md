# Inspect a Silent A10 card draft

The challenger can record the calculation it uses to choose a card after combat. For a saved example, run this command in the repository on either machine. The reader uses standard Python.

```sh
python scripts/show-silent-draft.py docs/evidence/silent-a10-draft-example.json --step 42 --compare DAGGER_THROW DAGGER_SPRAY
```

On map row 3 of the Underdocks, Silent had seen Seapunk and Sludge Spinner. Both remaining weak encounters had multiple enemies. The recorded probability of a group in the next **ordinary** fight was 1.0. The published strategy had no weight for that probability. Its total scores on this actual reward were as follows. [Full observation digest, model hashes and scores](evidence/silent-a10-draft-example.json)

| Option | Opening model | Strategy | Card offset | Total |
| --- | ---: | ---: | ---: | ---: |
| Dagger Throw | +0.301 | +0.033 | 0 | **+0.334** |
| Escape Plan | −0.197 | +0.252 | 0 | +0.055 |
| Dagger Spray | +0.200 | −0.383 | 0 | −0.183 |
| Skip | −0.549 | 0 | 0 | −0.549 |

The opening model's learned Dagger Throw coefficient added 1.053 points in the Throw versus Spray comparison. Spray's base damage calculation favored it by 0.600 points. The renderer prints the largest differences for any requested pair. Omit `--compare` to compare the winner with the runner-up. Raise `--terms` to see more contributions. Scores rank the choices available at that step. To measure the consequence of taking another card, restore the same native game state and play each alternative forward.

## Record a new game on Helmer

Use the prepared Python environment and native host from the [machine setup guide](silent-a10-handoff.md). This PowerShell example collects every out-of-combat card reward scored by the bundled strategy. Use a new seed prefix and output directory for a new experiment.

```powershell
$python = ".\.venv\cpu\Scripts\python.exe"
$engine = "artifacts/upstreams/sts2-cli/src/Sts2Headless/bin/Release/net9.0/Sts2Headless.dll"
$policy = "releases/silent-a10-encounter-draft/challenger/policy.json"
& $python scripts/optimize-silent.py evaluate --host $engine --bundle $policy --roles candidate --seeded-acts --prefix HELMERDRAFT01 --seeds 1 --workers 1 --explain-drafts --output artifacts/helmer-draft01
& $python scripts/show-silent-draft.py artifacts/helmer-draft01/candidate/run-0000/draft-scores.jsonl.gz
```

A full game produces one compressed log. Each line contains the seed, native action step, observation digest, scoring-code and weight-file hashes, boss, biome, public group probability, chosen action and the complete list of legal draft alternatives, including skip when available. Add `--step NUMBER` to read a single reward. The trace writes the exact scores the deployed strategy uses in its ranking.

* The base term includes the card's damage, defense, draw and setup values after the energy-cost adjustment, along with duplicate and deck-size penalties and the draft threshold.
* Early Act 1 adds the opening ranker's learned terms to this base. Later rewards use the strategy's ordinary card prior.
* Each learned term records its feature value, weight and signed point contribution. Strategy points include the saved strategy strength. The act-specific card offset completes the total.

The initial weak pool is tracked from the public opening in a fully unlocked v0.111.0 solo lobby. A hallway battle reached from a map selection consumes one draw, including a fight behind a question mark. Shops, elites and event-scripted combats leave the count alone. In a mid-act restore with missing history the model abstains from estimating the remaining pool. The third hallway fight can occur several rows into the map.
