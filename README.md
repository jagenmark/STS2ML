# STS2ML

A compact policy/value learning baseline for **Slay the Spire 2**. The intended
system learns macro decisions from player observations and later improves through
whole-run reinforcement learning, with search handling tactical combat.

**Current milestone:** replay-trained card-reward choices plus a native combat
adapter, verified replay branching and Monte Carlo distillation for a first
Act 1 encounter curriculum. Whole-run play and win rate remain unqualified.

**Active target:** Steam public beta **v0.111.0**, **Silent A10**. All five
characters remain the longer-term goal. Each patch has its own data, vocabulary,
checkpoints and evaluation results; training and inference enforce that boundary.
Start on the desktop with the [Windows / RX 9070 XT guide](docs/windows-workstation.md).

**Windows continuation (2026-10-30):** CPU and RX 9070 XT offline training now
execute locally. The pinned native-engine headless host also completed a
[1/2/4/8-process benchmark](docs/headless-options.md#windows-measurements-2026-10-30):
128 deterministic Silent A10 episodes, all early Act 1 losses with a weak fixed
policy. This validates a bounded execution path, not a winning agent or full-game parity.
The local observation extension now exports visible relic counters and full
unordered combat piles. A separate combat encoder and action/value heads consume
them in the [first micro curriculum](docs/micro-training.md). See the
[native counter and pile checks](docs/headless-options.md#public-combat-observations-v2).
Use `./scripts/start-training.ps1 -AllReplays -AllPatches` for complete replay
collection followed by a target-patch GPU fit. It resumes downloads, retries
transient failures, and follows the listing beyond lower-bound page counts.
The completed 2026-10-30 collection obtained 2,156 journals from 2,181 listed IDs;
the filtered dataset contains 275 runs and 2,640 card-reward decisions. Held-out
imitation accuracy is **49.3%**, versus **47.1%** for the frequency baseline on
37 test runs. This is not a measured game win rate.
[Final result and limitations](docs/windows-workstation.md#verified-desktop-setup-and-background-training).

## What works now

| Component | Implemented behavior |
| --- | --- |
| Replay import | Spire Codex recorder v5–v7 → pre-choice card-reward observations, human choice labels, and terminal outcomes when known |
| Model | Position-free set attention over deck/relics/potions, candidate-to-state attention, masked action policy, outcome value head |
| Training | Imitation cross-entropy + masked outcome BCE, CPU or a supported PyTorch device, validation-selected checkpoints |
| Evaluation | Connected run/seed grouped train/validation/test splits; train-only vocabulary; uniform and pick-frequency baselines |
| Prediction | Load a checkpoint and rank the legal candidates in one canonical JSON observation |
| Diagnostics | Read-only game/Steam fingerprints and an explicit CPU or GPU forward/backward check |
| Monte Carlo | Generic evaluator plus native, sampled rollouts for a qualified Silent A10 starter encounter |
| Micro training | Snapshot-bound combat actions, replay forks, soft teacher distillation, local fight-value head and paired live evaluation |
| Combat inputs | Native relic counters/status, three qualified counter rules, full hand/draw/discard/exhaust/play piles, modifier state, and a tested set-attention state encoder |
| Optional bridge | Source-inspected, explicitly partial card-reward adapter to a pinned `divine-sts2` full-app interface |
| Checks | Unit/integration tests, a synthetic learnability demo, GitHub Actions for Linux/Windows on Python 3.11 and 3.12 |

The default network is **894,850 parameters with a 1,024-entry vocabulary**:
128-dimensional embeddings, three Transformer layers and four attention heads.
Float32 weights alone occupy approximately **3.58 MB**. Vocabulary size changes
that count. Training memory includes optimizer states and activations.

## Quick start without the game

Python 3.11+ is required. These commands install CPU PyTorch so the first smoke
test does not depend on CUDA or ROCm. No API key or paid LLM service is needed.

```bash
git clone https://github.com/jagenmark/STS2ML.git
cd STS2ML
python -m venv .venv
```

Activate the environment:

```powershell
# Windows PowerShell
.venv\Scripts\Activate.ps1
```

```bash
# Linux / macOS
source .venv/bin/activate
```

Then:

```bash
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
python -m pip install -e ".[dev]"
pytest -q
sts2rl doctor --output artifacts/environment/doctor.json
sts2rl inspect-model
sts2rl demo --output artifacts/demo
sts2rl predict artifacts/demo/best.pt artifacts/demo/decision.json
```

The demo learns an **invented two-color rule**, with permuted offers and separate
run groups. Its accuracy is a plumbing/optimization check, **not an STS2 result**.
It creates a checkpoint, split manifest, JSON report and an inference example in
`artifacts/demo/`. That directory is excluded from Git.

## Work with player replays

The default collection and training target is **Silent A10, v0.111.0**. Download
a small patch-filtered page before considering a large collection:

```bash
sts2rl fetch-replays --limit 20
sts2rl import-replay data/v0.111.0/silent-a10/raw --output data/v0.111.0/silent-a10/choices.jsonl
sts2rl audit data/v0.111.0/silent-a10/choices.jsonl
```

Use the audit's exact `game_version` value when training:

```bash
sts2rl train data/v0.111.0/silent-a10/choices.jsonl --epochs 10 --output artifacts/v0.111.0/silent-a10/bc-01
```

The listing filter does not certify a replay header. Verify the audit's exact
`game_version`; `train` filters Silent/A10/v0.111.0 by default. Other targets can
be selected explicitly with `--character`, `--ascension` and `--game-version`.
Mixed-patch training has no override. Prediction rejects a mismatched patch, and
an output folder cannot overwrite another patch's checkpoint or training report.
The importer is intentionally conservative. Some journals contain reloads,
mods, co-op players, incomplete initial states, or unresolved choices and will be
excluded with reasons. If a small collection leaves a split empty, collect more
independent runs. Do not weaken the split to divide one run's decisions between
training and test. The CLI accepts a directory on Windows as well as Unix, so it
does not depend on shell glob expansion.

Read [the data contract and source limitations](docs/data.md) before treating
an offline metric as evidence. In particular, imported state is explicitly
`partial_replay`: enchantments, relic counters and complete route context are
not represented in this milestone.

The initial real-data probe found that rewards can change state between offer
creation and selection. The importer retains the earlier snapshot and records
these changes in metadata. Use `import-replay --strict-timing` to exclude such
examples entirely. See [the initial verification report](docs/verification.md)
for the exact tests and the small real-data sample's limitations.
The [Silent A10 public-data audit](docs/public-data-audit.md) compares beta and
stable source coverage and records the bounded import probe.

## Architecture and training objective

The model reads card identities and upgrades, relic/potion identities, and
numeric state including HP, gold, floor and ascension. Every optional numeric
field has an indicator distinguishing “unknown” from an observed zero. Entity
counts preserve multiplicity. Entity sets have no positional encoding: reordering
the deck serialization does not change the decision, while reordering candidate
actions reorders their corresponding probabilities.

Candidate actions attend to the encoded state and receive individual scores;
softmax normalizes over **the actual legal candidates**. Padded actions are masked.
The candidate list may include an explicit skip, which is learned as an action.
The value head predicts a recorded run's terminal result from its observed state.

Training minimizes:

```text
loss = cross_entropy(recorded human choice, policy)
     + value_weight * binary_cross_entropy(recorded terminal result, value)
```

Missing human choices and missing terminal outcomes have independent masks.
Abandonment or an unfinished replay is not silently labeled a loss. A checkpoint
whose value head was not trained reports no outcome probability at inference.
This is observational pretraining: agreement with a human choice and historical
outcome prediction do not establish the causal benefit of taking a card.

The vocabulary is built from the training partition only. Run identifiers,
seeds, future draw order, final decks, player identifiers and result labels never
enter the feature encoder. Seeds are used only for split grouping. A connected
component of run IDs and seed groups stays in one partition, even if an
unlabelled record links the component. Contradictory run outcomes are rejected.

See [architecture and evaluation decisions](docs/architecture.md) for the schema,
checkpoint contents and RL roadmap.

## What needs the desktop

The actual game integration requires the user's installed game and a verified
compatible bridge. The [headless source review](docs/headless-options.md) selects
the pinned **sts2-cli** beta host as the first qualification candidate, with
**STS2-headless** as a reference for observation and compatibility boundaries.
The Windows setup script now builds and launches the pinned sts2-cli using local
game files. Bounded Silent A10 episodes and selected counter/pile transitions
are verified; complete-run parity still needs verification.

The existing experimental `divine-sts2` adapter targets **v0.107.1**; this
does not establish compatibility with the beta. Its
full-app observations omit important details, and its reconstructed combat Gym
is a different backend. Our adapter refuses an unverified game fingerprint and
does not claim a working full-run controller.

See [game integration](docs/game-integration.md) for exact pinned revisions,
fingerprints, setup and missing fields, and the [divine beta assessment](docs/divine-beta-assessment.md)
for its concrete blockers. `sts2rl doctor --game-root "<Steam game directory>"`
only reads identity and hashes; it never starts the game or certifies a backend.
CPU is enough for the offline milestone. Offline training and the new combat
encoder's forward/backward pass have also run on the desktop RX 9070 XT.

## Next milestones

1. Grow and audit a clean **v0.111.0 Silent A10** replay collection. Add held-out
   player evaluation and measure against simple card-frequency baselines.
2. Continue native qualification: legal transitions, selections, route context,
   remaining relic mechanics, and full-run lifecycle. Counter/pile checks are a
   bounded subset, not proof that every visible mechanic is represented.
3. Implement and validate tactical branching with hidden-state sampling. Generate
   Monte Carlo action-value targets, then imitate the search teacher with a micro
   policy using the new combat encoder; improve rollouts through expert iteration.
4. Start with an **Act 1 curriculum**, logging unique fight/act completions and
   held-out seed success separately. Increase the horizon as measured success
   improves; a completed Act 1 is not a full-run win.
5. Add macro reinforcement learning with fight/act rewards, explicit semi-Markov
   boundaries, correct terminal/truncation handling, and paired unseen-seed
   evaluation of the ultimate whole-run win objective.
6. Expand to every character, preserving separate patch models and per-character
   evaluation. Prefer imitation of reliable players before whole-run RL; retain
   both wins and losses from those players.

## Sources, data and license

Project code: MIT. Spire Codex and divine-sts2 retain their own licenses; no
upstream source, third-party replay fixture, raw player dataset, game binaries,
game artwork or decompiled game code is vendored. Downloaded data and generated
weights are not committed. Source revisions and API terms are linked in the docs.

This is independent research software, unaffiliated with Mega Crit.
## Native micro training

The [Act 1 micro curriculum](docs/micro-training.md) now connects native combat
actions, verified replay branching, sampled Monte Carlo teacher labels and a
trainable combat policy/value head. The first admitted scope is Silent A10 with
the starter deck against Shrinker Beetle; this is not yet whole-Act-1 play.

The first GPU fit used 1,372 decisions from 36,112 native rollout branches.
On 100 fresh encounter seeds the micro won 99 fights with 4.98 mean HP loss,
versus 100 wins and 4.82 HP loss for the heuristic. The separate MC teacher
comparison saved HP on 11 of 16 paired seeds and tied on five. Ordinary Act 1
evaluation remains 0/32 clears for both learned and heuristic policies.
[Measured results and scope](docs/micro-training.md#first-measured-fit-2026-10-30).
