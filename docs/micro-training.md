# Native micro training: first Act 1 curriculum

The native combat adapter and Monte Carlo teacher run on the pinned Windows
v0.111.0 engine. The first admitted training distribution is **Silent A10,
starter deck and Ring of the Snake, no potions, Shrinker Beetle Weak**. Initial
HP varies between 15, 25, 40 and 70. These are isolated native Act 1 encounter
scenarios, not full Act 1 runs. Scenario controls never enter the action space.

## Running an experiment

After `scripts/setup-headless.ps1`, use the GPU Python environment:

```powershell
& .venv/rocm/Scripts/python.exe scripts/train-micro.py --output artifacts/micro/new-experiment --episodes 64 --samples 8 --workers 4 --epochs 20 --evaluate 100
```

Use a fresh output folder. Each collection worker owns two isolated native
processes: the real episode and a reusable search process. Four workers use
eight native processes. The runner writes `status.json`, per-episode results
and teacher records, then `model/best.pt` and `model/report.json`. `STOP` in the
experiment directory stops collection at a decision boundary. Failed or stopped
episodes prevent the final fit. All labels, traces and checkpoints stay ignored
under `artifacts/`; no game assemblies or raw game content are published.

`--collect-only` stops after data generation. `--device cpu` supports CPU fitting.
The configuration records the fixed native sampler profile. Training and test
seeds are separated by episode group, with vocabulary fitted only on training
groups. Validation cross-entropy selects the checkpoint; the test partition is
evaluated once after selection. Live evaluation uses another fixed seed family.

## Adapter and information boundary

`sts2rl.native.NativeSession` exposes reset, step, fork and restore. A fork stores
the seed, public action history and expected observation hash in runner-only
metadata. Restore rebuilds the native run and replays the history; a mismatching
hash, timeout or engine error invalidates the session. This is replay-based
branching, not a serialized active-combat snapshot. Reusing a process required
fixing selector-scope disposal and combat event subscriptions in the host.

Combat actions include playable cards with explicit targets, usable potions,
end-turn and bounded card-selection combinations. Unsupported target types,
unknown phases and selection sets above 1,024 fail explicitly. Map/event/rest/
reward/bundle choices are represented for integration; shopping currently only
supports leaving. This is not a claim of complete game-action coverage. Actions
are bound to an observation hash; stale and forged actions are rejected locally.
Potion actions are exposed but are outside the qualified teacher curriculum.
For this single-player host, `AnyPlayer` targets resolve to the owner. Potion
execution failures are surfaced as errors instead of silently discarding the
potion and reporting success.

The network consumes hand, unordered draw/discard/exhaust/play piles, deck,
relic counters, visible enemy intents/powers, player state and selection context.
Actions bind to their source card/potion/selection and enemy target embeddings.
Descriptions are not language-understood. Seeds, native internals, future
outcomes and actual hidden draw order are not neural inputs.

## Monte Carlo labels

Each candidate is replayed into the same independently sampled worlds. The
sampler sorts the public draw multiset before shuffling it and resets native
run/player RNG objects, so candidate scores cannot depend on the actual hidden
draw permutation or future RNG stream. The admitted starter cards cannot reveal
or manipulate draw order; the inspected beetle move cycle is deterministic.
Other decks, relics, potions and monsters are rejected by this sampler until
their hidden-state semantics have been qualified. This is intentionally not a
general claim that resetting RNGs samples every possible game's belief state.

Continuations use a public heuristic based on damage, lethal attacks, incoming
damage, useful block and Survivor discards. A completed fight returns `100 + HP`
for survival and `0` for defeat. Truncations/errors do not produce labels. These
are values under that continuation policy, not optimal values or MCTS results.
Identical hand cards share rollout estimates. The real collection policy uses
the teacher with 10% random-action exploration to broaden visited states.

The micro network distills soft action targets (temperature 2 HP points), with
probability divided between identical physical card copies. Its auxiliary value
head predicts expected **local fight return / 170**, not whole-run victory.
Offline metrics include agreement with any tied best action and estimated
regret. Live evaluation reports fight wins and HP loss against the heuristic
on the same unseen seeds and starting HP. It must show actual improvement before
claiming the learned policy is stronger.

At inference, probabilities of interchangeable card copies are **summed before
choosing the action effect**. Taking the highest-probability physical copy would
favor a unique end-turn over several good attack copies. A regression test
covers this distinction; the first evaluation exposed the inconsistency and a
new seed family was used after correcting inference.

## First measured fit, 2026-10-30

The [sanitized evidence](evidence/micro-training-windows-2026-10-30.json) records
64 collected scenario episodes, **1,372 decisions and 36,112 rollout branches**,
with no collection errors. Collection took 16.2 minutes with four workers.
The RX 9070 XT fit took 51.4 seconds for 20 epochs; validation selected epoch 20.
The split is 52/6/6 independent seed groups, with 1,105/137/130 decisions.

On 16 separate paired validation scenarios, both the Monte Carlo teacher and
heuristic won every fight. The teacher lost **2.00 HP** on average versus
**4.75 HP** for the heuristic: better on 11 seeds and tied on five. This is a
small, narrow encounter comparison, not general game-playing strength.

After the inference correction, a **fresh 100-seed** evaluation gave:

| Policy | Fight wins | Mean HP lost |
| --- | ---: | ---: |
| Heuristic | 100/100 | 4.82 |
| Learned micro | 99/100 | 4.98 |

The student is close to the heuristic here and **has not demonstrated superiority**.
The original inference result (93/100, 10.18 HP lost on an earlier seed family)
is retained in the evidence; it is not directly comparable to the new seed set.
Weights were unchanged by the inference fix. The archived offline test metrics
also retain their original physical-copy selection interpretation.

Both policies were additionally executed through **32 ordinary Act 1 starts**
on identical seeds with fixed noncombat choices. Both cleared **0/32**, with
**zero engine errors** after the target-handling fix. The micro policy encounters
untrained enemies/cards/relics there. This confirms that the first encounter
curriculum does not yet produce an Act 1 player; broader teacher coverage and
macro integration are required.

## Qualification and next expansion

```powershell
& .venv/cpu/Scripts/python.exe scripts/verify-micro-native.py --output artifacts/micro/new-qualification
& .venv/cpu/Scripts/python.exe -m pytest -q
```

The first native probe executed all eight root actions, checked pending-discard
replay, rejected a stale action, preserved sibling isolation, and verified that
the same sampled world produces identical full trajectories after deliberately
changing the actual hidden draw order. Different sample seeds produced different
trajectories. Fifty alternating restores with a subsequent action passed.

For a paired teacher/heuristic comparison on a separate validation seed family:

```powershell
& .venv/cpu/Scripts/python.exe scripts/evaluate-micro.py --output artifacts/micro/teacher-validation --policy teacher --episodes 16 --workers 2 --samples 8
& .venv/cpu/Scripts/python.exe scripts/evaluate-micro.py --output artifacts/micro/heuristic-validation --policy heuristic --episodes 16 --workers 2
```

The same evaluator accepts `--scope act1` for heuristic or checkpoint policies.
It fixes noncombat decisions (first available choice, heal at rests), ends on
death or entry into Act 2, and reports errors separately from defeats. These
runs test integration/generalization outside the starter training distribution;
the qualified teacher itself cannot yet search arbitrary Act 1 states.

Expansion requires more audited Act 1 encounters and decks, tests for remembered
visible draw order, and native-vs-rendered transition comparisons. Whole-Act-1
clear rate, broad combat parity, shops, macro integration and full-run RL remain
separate milestones. Existing replay-trained macro checkpoints are unchanged.
