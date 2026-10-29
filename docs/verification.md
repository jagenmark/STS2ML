# Initial verification — 2026-10-29

This document distinguishes code verification from game-playing evaluation.

## Beta and Windows handoff update — 2026-10-29

The follow-up implementation selects v0.111.0 / Silent / A10, adds a read-only
`doctor`, exact-patch collection defaults, and mandatory patch boundaries for
training, checkpoint loading, output-directory reuse, and inference. A whole
dataset's run consistency is checked before CLI target filtering. Linux/Windows
CI jobs now cover Python 3.11 and 3.12; their hosted results must be checked in
Actions rather than inferred from the workflow definition.

Local verification used Python **3.12.16**, PyTorch **2.15.0+cpu**, pytest **9.2.0**,
and Ruff **0.17.3**:

```bash
ruff check src tests
pytest -q
sts2rl demo --output artifacts/verification-beta-handoff/demo --runs 64 --epochs 2
sts2rl doctor --game-root "<local Steam game directory>" --output artifacts/environment/doctor-linux-beta.json
```

**94 tests passed**, lint passed, and the synthetic demo completed training,
checkpoint selection and prediction. PyTorch emitted an optional missing-NumPy
warning; these checks did not use NumPy. This short demo's metric is not a game
result or the earlier eight-epoch synthetic experiment below.

The local doctor identified v0.111.0 / commit `41cef1ea`, Steam build `24724944`,
branch `public-beta`, and the [recorded Linux game hashes](divine-beta-assessment.md).
Its CPU matmul/backward check passed. It correctly reported that the existing
stable divine adapter does not admit these files. This operation read game
metadata/files without launching the game, bridge, or headless candidate.

The [public-data audit](public-data-audit.md), [headless comparison](headless-options.md)
and [Windows guide](windows-workstation.md) preserve the research and next steps.
No headless backend, beta A10 game transition, Windows GPU installation, complete
native run, or RL playing-strength improvement has been executed here.

## Environment and commands

The initial implementation was checked on Linux with Python 3.12.14,
PyTorch 2.15.0+cpu, pytest 9.2.0 and Ruff 0.17.3.

```bash
python -m pip install -e ".[dev]"
ruff check src tests
pytest -q
sts2rl demo --output artifacts/demo --epochs 8
sts2rl inspect-model --vocab-size 1024
```

**79 tests passed** in the final local test suite before upload. Tests cover:

- Schema validation, unknown/hidden fields, candidate legality and finite limits.
- Train-only vocabulary and exclusion of labels/IDs/metadata from model features.
- Set permutation invariance, candidate permutation equivariance, empty decks,
  legal-action masking and finite gradients.
- Save/load/inference and missing value supervision with actual PyTorch checkpoints.
- Run/seed split integrity, including transitive links through unlabelled records,
  contradictory outcomes and duplicate records.
- Replay mutation tracking, pre-acquisition snapshots, unknown offered-card
  upgrades, console/reload exclusions and timing annotations.
- Full-app adapter contract and fail-closed compatibility checks using synthetic
  protocol fixtures.
- Root-sampled Monte Carlo behavior on synthetic chance environments, including
  a hidden-coin case that cannot be solved by observing the hidden answer.

GitHub Actions repeats lint, tests and a short synthetic demo on Python 3.11 and
3.12. The workflow uses pinned action commits and read-only repository permissions.
The existence of that workflow alone does not establish a passing hosted run;
check the repository's Actions tab for its current status.

## Synthetic learning experiment

The demo creates 96 invented runs / 288 decisions, splits by run/seed, and learns
an invented red/blue preference rule. The smaller demo model has 144,002
parameters (64 dimensions, two layers); it is distinct from the default research
model.

In the recorded eight-epoch run, the selected checkpoint obtained 66/66 correct
choices over 22 held-out synthetic runs, with policy cross-entropy approximately
0.00467. Uniform choice would average one-third accuracy. This demonstrates
working encoding, optimization, checkpoint selection and inference on a known
learnable rule. **It says nothing about STS2 strategy or native win rate.**

The default model was measured separately at 894,850 parameters for a vocabulary
of 1,024 tokens, corresponding to 3,579,400 bytes of float32 weights.

## Real replay ingestion probe

A bounded convenience sample downloaded 29 journals discovered through the public
Spire Codex replay listing, targeting solo Ironclad A10. Raw logs and generated
datasets are ignored by Git and are not published with this source tree.

One v0.111.0 run, public hash `4d185274cc6cfbee`, passed the initial journal gates.
Its 2,085 events yielded 15 canonical card-reward examples. The run ended in
death; all 15 outcome labels are therefore zero. Rejected logs commonly contained
resumes/multiple headers, gameplay mods or unsupported recorder versions. One
contained recorded console commands despite a false header console flag.

All 15 accepted examples showed recorded changes between offer creation and
selection. The default import labels them `partial_replay`, records
`observation_timing: offer_created` and lists changed fields. Strict timing import
rejects all 15. We retain the initial snapshot instead of copying potentially
action-dependent state from just before the acquisition hook.

This probe validates real journal parsing and the honest representation of data
limitations. **One run cannot support run-disjoint training and evaluation**, and
the current command correctly requires enough independent groups. No human-data
playing-strength result or pretrained STS2 policy is claimed.

Sources: [Spire Codex developer API](https://spire-codex.com/developers),
[inspected replay schema fixtures](https://github.com/ptrlrd/spire-codex/tree/2af6543ca7a6c76acfde6be582651c7c05e88e50/backend/tests/fixtures).

## Not established by these tests

- Compatibility with the user's installed game patch.
- A faithful native tactical simulator or useful combat search speed.
- Complete macro observations, native full-run control, or online RL.
- Whether the model beats simple strategies or strong human players.
- GPU training compatibility on the user's RX 9070 XT installation.

The next meaningful evidence is a verified game/recorder observation boundary,
followed by a substantially larger clean dataset and paired unseen-seed native
evaluations. Enlarging the network does not solve missing or mistimed state.
