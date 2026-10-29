# STS2ML

A compact policy/value learning baseline for **Slay the Spire 2**. The intended
system learns macro decisions from player observations and later improves through
whole-run reinforcement learning, with search handling tactical combat.

**Current milestone:** a working, game-independent offline training pipeline for
card-reward choices, conservative replay import, a small attention model, and
tested contracts for future game integration. There is no autonomous STS2 player
or measured native win rate yet.

**Active target:** Steam public beta **v0.111.0**, **Silent A10**. All five
characters remain the longer-term goal. Each patch has its own data, vocabulary,
checkpoints and evaluation results; training and inference enforce that boundary.
Start on the desktop with the [Windows / RX 9070 XT guide](docs/windows-workstation.md).

## What works now

| Component | Implemented behavior |
| --- | --- |
| Replay import | Spire Codex recorder v5–v7 → pre-choice card-reward observations, human choice labels, and terminal outcomes when known |
| Model | Position-free set attention over deck/relics/potions, candidate-to-state attention, masked action policy, outcome value head |
| Training | Imitation cross-entropy + masked outcome BCE, CPU or a supported PyTorch device, validation-selected checkpoints |
| Evaluation | Connected run/seed grouped train/validation/test splits; train-only vocabulary; uniform and pick-frequency baselines |
| Prediction | Load a checkpoint and rank the legal candidates in one canonical JSON observation |
| Diagnostics | Read-only game/Steam fingerprints and an explicit CPU or GPU forward/backward check |
| Monte Carlo | Backend-independent root-sampled rollout evaluator with a player-visible continuation-policy boundary |
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
Neither is installed or launched by this repository. Windows Silent A10 and
complete-run parity still need verification.

The existing experimental `divine-sts2` adapter targets **v0.107.1**; this
does not establish compatibility with the beta. Its
full-app observations omit important details, and its reconstructed combat Gym
is a different backend. Our adapter refuses an unverified game fingerprint and
does not claim a working full-run controller.

See [game integration](docs/game-integration.md) for exact pinned revisions,
fingerprints, setup and missing fields, and the [divine beta assessment](docs/divine-beta-assessment.md)
for its concrete blockers. `sts2rl doctor --game-root "<Steam game directory>"`
only reads identity and hashes; it never starts the game or certifies a backend.
CPU is enough for the offline milestone. The Windows guide contains a separately
verified vendor GPU profile; desktop execution and performance remain untested.

## Next milestones

1. Grow and audit a clean **v0.111.0 Silent A10** replay collection. Add held-out
   player evaluation and measure against simple card-frequency baselines.
2. Qualify the pinned beta headless candidate on Windows: actual Silent/A10,
   legal transitions, full-run lifecycle and player-visible observations. Expand
   the observation bridge with upgrades/enchantments, relic state and route context.
3. Implement and validate the tactical simulator adapter with hidden-state
   sampling; check transitions against the real game on fixed seeds.
4. Run paired, unseen-seed whole-run evaluations with an unchanged combat policy.
5. Add macro reinforcement learning with explicit semi-Markov decision boundaries,
   correct terminal/truncation handling and the win objective.
6. Expand to every character, preserving separate patch models and per-character
   evaluation. Prefer imitation of reliable players before whole-run RL; retain
   both wins and losses from those players.

## Sources, data and license

Project code: MIT. Spire Codex and divine-sts2 retain their own licenses; no
upstream source, third-party replay fixture, raw player dataset, game binaries,
game artwork or decompiled game code is vendored. Downloaded data and generated
weights are not committed. Source revisions and API terms are linked in the docs.

This is independent research software, unaffiliated with Mega Crit.
