# Whole Act 1 training

The collection target is an ordinary **Silent, v0.111.0 Act 1 run** (A10 by default,
with explicit A7/A8 difficulty support):
start at Neow, make map/event/reward/shop/rest decisions, and stop on death or
entry into Act 2. No encounter, HP, deck or relic is forced in these episodes.
The earlier single-beetle curriculum was a bridge qualification experiment; it
does not provide adequate training diversity for an Act 1 player.

## Run locally

After `scripts/setup-headless.ps1`, use a fresh output folder:

```powershell
& .venv/rocm/Scripts/python.exe scripts/train-act1.py --output artifacts/act1/new-experiment --runs 64 --workers 4 --samples 4 --roots-per-fight 12 --query-probability 0.5 --epochs 20 --evaluate 32 --macro-checkpoint artifacts/v0.111.0/silent-a10/workstation-20261030-172303-775/final/best.pt
```

The macro checkpoint path above is a local example, not a downloaded repository
asset. Omit it to use varied macro choices without the replay model. With it,
85% of card rewards use the replay-trained model and 15% use random exploration.
Map choices favor rests at low HP and avoid low-HP elites when possible. Shops
can buy stocked, affordable relics/cards/potions; the macro currently prefers
relics, then cards. Card removal and potion replacement are not yet supported.

Four workers run eight isolated native processes. CPU processes collect teacher
data; the RX 9070 XT fits the policy afterward. `--collect-only` omits fitting;
`--device cpu` permits CPU fitting. A `STOP` file stops collection at a decision
boundary. Incomplete runs are quarantined and block automatic fitting. Search
branch errors produce no label and are counted separately from actual defeats.

`status.json`, per-run `progress.json`/`result.json`, and `collection.json` record
progress, floors, fights, distinct enemy/card/relic identities and search errors.
`teacher_monsters` records where labels were actually collected. Presence in a
coverage report is not evidence that a mechanic was learned. All traces, raw
observations and weights remain ignored under `artifacts/`.

Short Windows reader/antivirus locks are retried when atomically replacing JSON.
Persistent locks may skip a progress update; they must not terminate a game.
Durable result/configuration writes still report failures. After a failed runner
exits, rerun its exact arguments with `--resume` to reuse complete episodes and
archive/retry incomplete episodes. Worker count can change. Do not resume a
live runner. A `STOP` file remains authoritative. Original and resume source/
runtime manifests are retained. Game-assembly and macro-weight changes are
rejected; an audited presentation-only host fix additionally requires
`--allow-host-update`. `scripts/resume-act1.ps1` can wait for the old runner,
build the fixed host, verify the event effects, and perform this recovery.

## Difficulty curriculum

`--ascension 7` starts the real native game at A7, retaining the entire act and
its normal rewards, events and deck progression. A7 keeps the curse, potion-slot
and economic constraints but removes A8 durability and A9 attack increases.
A10's extra boss is in Act 3, so moving only from A10 to A9 would not help Act 1.
These thresholds are taken from this installed patch's ascension localization,
and native fixtures verify the actual HP/damage changes.

Below A10, the runner automatically selects `silent-act1-ascension-mc-v3` and
checkpoint version 3. Ascension is validated against the native identity, saved
on each episode/teacher record, and passed as a numeric combat input, including
nested card choices. Checkpoints record their trained ascensions and reject
inference at unseen difficulties. Existing A10 v1/v2 checkpoints retain their
original inputs and A10-only runtime guard. The macro still uses the same
A10-replay-trained weights; it receives the actual ascension rather than a false
A10 label. Its transfer to A7 is unproven and held fixed across evaluation arms.

Use `--condition-ascension --ascension 10` to collect A10 data in the same v3
format for a later mixture. Legacy v2 data cannot be silently mixed into v3.
Seed groups remain together across difficulties, and every difficulty must be
represented in train, validation and test. The fitter reports coverage by
difficulty and rejects missing coverage instead of silently evaluating a
different mixture. The first A7 experiment is separate; mixed training is not
yet a measured result.

Example after rebuilding the host:

```powershell
& .venv/rocm/Scripts/python.exe scripts/train-act1.py --output artifacts/act1/new-a7 --ascension 7 --runs 32 --workers 2 --samples 4 --roots-per-fight 12 --query-probability 0.5 --epochs 20 --evaluate 32 --macro-checkpoint artifacts/v0.111.0/silent-a10/workstation-20261030-172303-775/final/best.pt
```

When an older experiment has the Release DLL open, build a separate host with
`dotnet build .../Sts2Headless.csproj -c Curriculum -p:Optimize=true` and pass
`--host-path artifacts/upstreams/sts2-cli/src/Sts2Headless/bin/Curriculum/net9.0/Sts2Headless.dll`.
The runtime manifest fingerprints that host and its Godot stub. Do not replace
the host of a live experiment. `verify-curriculum-native.py --output <fresh>
--host-path <dll>` checks A7/A8/A10 replay/sampling and difficulty effects;
`verify-act1-native.py --ascension 7 --output <fresh> --host-path <dll>` checks
the broad fixtures at A7. Both are regression checks, not playing-strength data.

## Measured runtime and concurrency

With four collection workers on this Ryzen 9800X3D, early-loss teacher episodes
took roughly **67–117 seconds** in the larger four-sample experiment. One run
that reached floor 15 took **768 seconds**. The first actual **Act 1 clear by
the MC-assisted collection policy** took **862 seconds (14m22s)**, with 58
teacher roots and 1,368 rollout branches. These are examples, not a stable
estimate for every run. Later roots repeatedly replay longer action histories.

Without search, the earlier paired evaluation averaged **1.57 seconds** for the
heuristic and **3.58 seconds** for the student, including process startup. Most
of those runs died early; these are not times for successful full-Act-1 clears.

Each collection worker owns two native processes; its real game waits while
the search process evaluates branches sequentially. Different runs already
execute in parallel. Independent sampled branches could also be parallelized,
but that is not implemented yet. More workers are configurable. Earlier simple
headless tests measured 8-process throughput at 1.7 times 4-process throughput;
that does not establish the scaling of this heavier MC workload. Measure valid
teacher decisions per minute and memory use before increasing concurrency.

## Search and information boundary

Monte Carlo still searches **to the end of the current fight**, using a public
heuristic continuation. It does not search the whole act's decision tree. The
collector obtains those fight states throughout real Act 1 runs, with changing
HP, decks, upgrades, relics, potions, enemies and current intents. At most two
roots per turn and the configured budget per fight are queried. Unsampled
decisions use the combat heuristic; queried decisions execute the teacher choice.

Every branch starts by replaying the original seed and full action history in
another isolated process and matching the public-state hash. Map save/reload
was tested and rejected as an optimization: a matching map observation did not
guarantee the same subsequent unknown room. Full replay is slower but preserves
that history; it is not active-combat snapshot cloning.

The experimental sampler `silent-a10-act1-mc-v2` canonicalizes then shuffles the
hidden draw multiset and resets run, player, monster-local, encounter and chaotic
RNG streams. It preserves current visible intents and native monster history.
Known effects that can reveal or establish draw order conservatively exclude
the affected fight from labels until a public belief tracker supports them.
The run itself continues. Roots with oversized branch budgets are also skipped
and counted. The original starter-only sampler remains a separate profile.

**This is not proof of an exact belief sampler for every Act 1 mechanic.**
Cached hidden monster state and unexported per-card state still need broader
audits and rendered-game parity checks. Only audited stateless starter cards
share estimates between identical physical copies; other copies are searched
separately. Finite regression fixtures verify hidden draw-order invariance and
chance variation across six encounters, including an elite, with a varied deck
and a potion. They do not establish complete game coverage.

The neural input includes hand, unordered draw/discard/exhaust/play piles, deck,
upgrades/modifiers, visible relic counters, enemy intents/powers, player powers,
potions, selection origin and public enemy turn history. Generated combat card
rewards and bundles are action-bound as well. Seeds, private engine state and
future outcomes are excluded. Descriptive text is not language-understood;
there is no pretrained wiki comprehension claim.

## Fitting and evaluation

Completed fights return `100 + 100 * HP / max_HP`, minus 3 per used potion;
death returns zero. Smoke Bomb escape receives no fight-win bonus. The auxiliary
value head predicts this **local fight return / 200**, not the chance of clearing
the act. Search truncations and engine errors never become loss labels.

Soft action targets use temperature 2 return points. Entire seed groups stay in
one train/validation/test partition; vocabulary is fitted only on training runs.
The broad model uses 0.1 dropout and weight decay. Validation cross-entropy selects
the checkpoint. Reports include coverage per split, offline agreement and regret.
Old starter data cannot be silently mixed with the broad return scale.

Final evaluation now runs **heuristic, student and MC-assisted teacher** on the
same new seed family, with the same macro checkpoint, exploration settings and
per-seed macro RNG. The teacher uses the collection's chance-sample/root/query
budgets and heuristic continuation. Its assistance is sparse, not a claim of
full search at every decision. Evaluation uses the configured worker count.

`evaluation-protocol.json` records seed prefix, budgets and model/runtime/source
fingerprints. `policy-comparison.json` reports clears, mean furthest floor and
mean/median runtime per policy, plus paired differences. A pair is excluded if
any arm has a run error; errors are not counted as defeats. Search failures and
fallbacks remain visible in the per-run results. All three arms are attempted
before evaluation errors are reported. Matching completed arms may be reused on
resume; a changed protocol archives and reruns them. A root `STOP` file applies
to all evaluation arms. Held-out teacher rows are stored under evaluation folders
and are excluded from the training glob.

Trajectories can diverge because combat outcomes change later macro choices;
the policy is fixed, not the entire sequence of choices. Offline imitation
accuracy and collection clears are not evidence of the student's Act 1 strength.

## Next decisions after the paired comparison

Overfitting is a hypothesis, not an established explanation of the current gap.
Four chance samples can leave action rankings noisy; heuristic continuations
can also make values systematically misleading. Even a low-noise estimate can
be an accurate estimate of a poor continuation policy.

1. If MC assistance consistently improves held-out outcomes but the student
   does not, investigate coverage, optimization and action binding. Then collect
   teacher labels from the student's own visited states, including its mistakes.
   This follows the iterative data-collection principle of
   [DAgger](https://proceedings.mlr.press/v15/ross11a.html).
2. If MC assistance does not improve outcomes, first test a larger search budget
   and a better continuation policy on a separate diagnostic seed set. Measure
   action-ranking stability across independent chance samples as well as live
   outcomes. More epochs on unchanged labels will not repair a weak teacher.
3. Test a difficulty curriculum with the same comparison protocol. In this
   installed patch A8 increases enemy durability, A9 makes attacks deadlier,
   and A10 adds the second Act 3 boss. A7 is therefore a useful proposed Act 1
   step down while retaining the curse, potion-slot and economic restrictions.
   A7/A8 support now has explicit native identity checks, data metadata and
   neural ascension inputs. Evaluate its separate pilot before mixing difficulties.
4. Keep some A10 data and separate A10 evaluation while progressing A7 → A8 →
   A10. Keep the macro policy fixed during each micro comparison. Diagnostic
   results used to choose an approach must not be presented as an untouched
   final test; reserve fresh seeds for later confirmation.

## Initial broad pilot, 2026-10-30

After fixing native shop logging and missing Godot JIT signatures for Rolling
Boulder, the collection pilot completed **12/12 runs without engine or search
errors**: **61 fights, 237 teacher decisions, 2,524 branches**, in 179.3 seconds
with four workers. Labels covered **21 enemy identities**; encountered decks and
relic sets included 42 card identities and 18 relic identities. The furthest run
reached floor 15. **0/12 cleared Act 1**, so boss coverage and clear rate still
need improvement. This pilot validates the broader pipeline, not a strong agent.

The pilot GPU fit took 18.9 seconds for 20 epochs; validation selected epoch 7.
Ten/one/one run groups produced 205/16/16 train/validation/test decisions. The
test split agreed with a tied teacher-best action on 68.75% of its 16 decisions;
that very small test is only a pipeline check. On **32 fresh paired Act 1 seeds**,
both the student and heuristic cleared **0/32**, with zero engine errors. Mean
furthest floor was **6.56 for the student vs 7.59 for the heuristic**. Both reached
floor 17 in at least one run. The student has not demonstrated improvement.

The larger A10 collection completed **64/64 valid runs**, **403 fights**,
**3,090 teacher decisions**, and **61,848 rollout branches**, after retrying
the quarantined engine failures. It had no search errors and **3 Act 1 clears
by the MC-assisted collection policy**. GPU fitting and a new 32-seed three-way
evaluation follow automatically. Collection clears are not student results.
See the [sanitized evidence](evidence/act1-training-windows-2026-10-30.json).

Qualification commands:

```powershell
& .venv/cpu/Scripts/python.exe scripts/verify-act1-native.py --output artifacts/act1/new-qualification
& .venv/cpu/Scripts/python.exe scripts/verify-micro-native.py --output artifacts/act1/new-starter-regression
& .venv/cpu/Scripts/python.exe -m pytest -q
```

The native fixtures additionally verify actual Rolling Boulder damage, relic/
potion/card purchase effects, low-HP resting and rejection of unsupported draw
knowledge. The starter regression verifies deterministic forks, pending
selections, fifty repeated restores, potion effects and sibling isolation.

The larger collection exposed unguarded presentation calls in Jungle Maze's
Join Forces option and Dense Vegetation's Rest option. `PresentationFix.cs`
removes only inspected audio/screen-shake calls; native gold, HP, event completion
and subsequent combat remain intact. The native event probe verifies both Jungle
Maze options' exact gold/HP effects and Dense Vegetation's healing followed by
its mandatory fight. The transpiler rejects unexpected call counts. Deployment
and qualification use the rebuilt host after its previous runner exits.
Invalid episodes remain quarantined until their rerun succeeds.
