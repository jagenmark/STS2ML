# Silent A10 full-run experiments

The target is a solo Silent victory on the v0.111.0 native headless game. Each evaluation starts at Neow with the normal starter deck. A full win requires a native victory and observations from two distinct Act 3 boss rooms. An Act 2 or Act 3 entry requires a recorded boss fight in the preceding act. Engine failures retain their last confirmed milestone and are reported separately.

## Results on unseen seeds

| Policy | Completed / attempted | Reached Act 2 | Reached Act 3 | Full wins |
|---|---:|---:|---:|---:|
| Repository heuristic | 128/128 | 0 | 0 | 0 |
| Hand planner | 128/128 | 21 | 1 | 0 |
| Neural combat student | 128/128 | 26 | 1 | 0 |

### Late-game specialist on 192 fresh seeds

| Policy | Completed / attempted | Reached Act 2 | Reached Act 3 | Full wins |
|---|---:|---:|---:|---:|
| Same hand planner | 191/192 | 38 | 1 | 0 |
| Planner in Act 1, neural specialist thereafter | 191/192 | 38 | 2 | 0 |

The three main policies faced the same 128 seeds. The planner reached the Act 1 boss on 79 seeds and defeated it on 21. The neural student reached the boss on 84 and defeated it on 26. These encounters provide a frequent training target with a measurable effect on later-act coverage.

The second experiment held the Act 1 actor fixed across 192 fresh seeds. The Trial event failed on the same seed for both policies. It remains unresolved. The reports count confirmed milestones across all attempts and compare terminal outcomes on completed pairs.

The weights were frozen before each suite. An early headless build advanced some runs to Act 3 when an Act 2 fight failed to initialize. Both suites were evaluated again with the game's combat-completion flag required before rewards. Three runs interrupted by Kaiser Crab death audio were retried after a narrow presentation fix. Each retry matched every earlier public decision. All 384 main-suite trajectories reproduced their full terminal-state digest on the audio-fixed host. Of 382 completed follow-up trajectories, 380 reproduced their exact terminal digest. The two exceptions shared a seed. Fresh games under both policies reproduced the observed loss on Act 2 floor 4, with a different final public state. [Machine-readable evidence](evidence/silent-a10-linux-2026-11-19.json)

## Models

- The planner estimates the value of legal combat actions from the current hand, native damage previews, block, enemy intents and statuses. A bounded search scores affordable sequences and plays the first action. The game resolves each action before the planner chooses again. Two rounds of weight search used 400 and 256 full-game attempts with common seeds across candidates.
- The room model used by the planner was fitted on 2,967 observed transitions from 228 complete training games. It estimates health, gold, other rewards and death risk by room type and player condition, then scores paths on the visible map. A separate model ranks Neow's offers and early card rewards. Its labels came from 981 alternative continuations of 281 training decisions. Each alternative began from the same public observation as the others in that offer.
- The frozen neural student ranks legal combat effects with 11,281 parameters. It learned from 8,372 decisions across 62 completed planner games, with 7,194 decisions used for fitting. It matched the planner on 547 of 577 held-out decisions. It uses an earlier room model fitted on 1,027 transitions and the same offer ranker. Its gameplay results appear separately above.
- A second student trained on an additional 64 games collected under the first student's decisions. A late-game specialist trained on 44 completed continuations from naturally reached Act 2 openings. Replaying a curriculum start requires the exact public-state digest at the original map. The late-game specialist switches on after the Act 1 boss. Its conditional check and its full-run evaluation used separate seeds.

The older Monte Carlo combat network trained on 686 labeled decisions from 11,055 simulated branches. It reached Act 2 twice in 48 development runs, compared with ten entries for the hand planner on the same seeds. The Monte Carlo collection used the worker's structured observations with localization keys in its text fields. The full-game evaluations used the extracted localization tables. Development and training results in the evidence file retain the host used at the time.

## Run a saved policy

The local release is `artifacts/a10-hour/silent-a10-release.zip`. It includes the frozen model files, per-file checksums, the two evaluation protocols and the measured runtime hashes. Generated weights and game assets stay outside Git. On Linux with the prepared game assets and .NET SDK, use a fresh build and output folder.

```bash
.venv/bin/python scripts/build-silent-host.py --output artifacts/silent-a10-host
unzip artifacts/a10-hour/silent-a10-release.zip -d artifacts/silent-a10-release
export STS2_SELECTOR_FIX_LOCAL_TASK=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
.venv/bin/python scripts/optimize-silent.py evaluate \
  --host artifacts/silent-a10-host/src/Sts2Headless/bin/Curriculum/net9.0/Sts2Headless.dll \
  --bundle artifacts/silent-a10-release/neural/policy.json \
  --output artifacts/silent-a10-evaluation --prefix MYFRESHSEEDS --seeds 128 --workers 4
```

The default comparison includes the repository heuristic and the saved actor. Use `planner/policy.json` for hand planning or `late-student/policy.json` for the specialist. Each output includes a per-seed terminal result and an RPC trace. The Windows workstation uses its existing native setup and the host DLL from that build. The reported benchmark used Linux. [Windows setup](../scripts/setup-headless.ps1)

## Continue training

Use new seed prefixes for new data and distinct prefixes for model selection and the final evaluation. The working collection has a fitted room model under `artifacts/a10-hour/rooms-next-audited.json`. Its 5,912 transitions come from training games. The fitter excluded three earlier runs where combat stopped before native completion. This is a research checkpoint for the next route comparison.

- Run `scripts/optimize-silent.py train` for the cross-entropy weight search. Add `--act2-starts` with training role directories to optimize from ordinary Act 2 openings. The trainer uses different seeds in each generation and compares candidates only on common completed seeds.
- Use `--record-rooms` during collection and pass the resulting role directories to `scripts/fit-room-model.py`. Use `scripts/train-silent-offers.py` to generate counterfactual opening and reward labels and fit an offer model.
- Collect a planner's choices with `--turn-search --label-turns`. Pass the role directory to `scripts/train-tactical-student.py`. For student-state aggregation, collect separate seeds with `--roles student --tactical-student PATH --label-turns`, then train on both directories. For a late-game student, use `collect-late --act2-starts DIRECTORIES --turn-search --label-turns`.
