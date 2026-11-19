# Silent A10 progression benchmark

The new policy entered Act 2 on 37 of 128 fresh standard-lobby seeds (28.9%), up from 23 (18.0%) for the previous neural policy. It reached Act 3 twice, up from once. Across both suites it reached the first Act 3 boss once and lost to the Test Subject. Both policies finished with zero full wins in 384 starts each.

A follow-up compared students with optional enemy forecasts and replayed the frozen challenger on their 64 matched openings. [Forecast results and next experiment](silent-a10-act1-forecasts.md)

## Fresh full runs

| Opening configuration | Seeds per policy | Policy | Entered Act 2 | Entered Act 3 | Reached an Act 3 boss | Full wins |
|---|---:|---|---:|---:|---:|---:|
| Fixed biomes | 256 | Previous neural | 40 (15.6%) | 2 | 0 | 0 |
| Fixed biomes | 256 | New policy | **73 (28.5%)** | **4** | **1** | **0** |
| Standard lobby | 128 | Previous neural | 23 (18.0%) | 1 | 0 | 0 |
| Standard lobby | 128 | New policy | **37 (28.9%)** | **2** | 0 | **0** |

All 768 starts produced a native terminal outcome. Of those, 766 reproduced the original terminal digest, covering 165,280 physical actions. On the other two, replaying the individual commands reproduced every observation before the terminal end turn. The resulting game-over state had a different digest. On each seed, two builds independently reproduced the loss on the same floor using both the logged actions and a fresh run of the corresponding frozen policy. The fixed-biome table includes the observed outcomes on these two seeds.

The prespecified paired analysis requires both policies to reproduce their terminal digests. On its 254 fixed-biome pairs, Act 2 entries were 39 → 73, a gain of 13.4 percentage points. The challenger uniquely cleared Act 1 on 50 seeds and the incumbent uniquely cleared it on 16 (two-sided exact McNemar p = 0.000033). All 128 standard-lobby pairs qualified. The challenger gained 25 first-boss clears and gave back 11 (net +10.9 points, p = 0.029). Gains appeared in both standard-lobby opening biomes, from 12 to 19 Act 2 entries on 69 Overgrowth starts and 11 to 18 on 59 Underdocks starts.

Act 3 entries rose from two to four on the 254 fixed-biome pairs (p = 0.625) and from one to two on the 128 standard-lobby pairs (p = 1.00). These counts leave considerable uncertainty about the change in late-game performance. The standard-lobby challenger reached the Act 1 boss on 98 seeds and the Act 2 boss on nine. Two of those nine reached Act 3. With no full wins, the one-sided 95% upper bounds for the win rate are 1.16% in the fixed-biome suite and 2.31% in the standard lobby, treating seeds as independent within each suite. A separately compiled host reproduced all 24 sampled terminal digests across both policies and suites, covering 5,151 actions.

The incumbent is the neural combat student from the previous experiment. The challenger plans card sequences from the visible hand, estimates survival along paths on the visible map and ranks card rewards using matched native continuations. It switches route and combat settings after the first boss and starts using human card-pick statistics in Act 2. Each policy began at Neow with the ordinary Silent deck and health. A win requires a native terminal victory after fights on two distinct Act 3 boss floors. An act entry requires a recorded boss fight in the previous act. [Previous experiment](silent-a10.md)

The fixed-biome suite preserves the historical Overgrowth → Hive → Glory configuration. The standard-lobby suite uses the fully unlocked single-player game's seeded act selection. Both policies received the same seeds, opening biomes and run indices. Before evaluating the fresh seeds, we recorded the selection rule and froze both inference bundles. The evaluator replayed physical commands in fresh engine processes and compared the full public terminal-state digests. It also calls for another autonomous policy run on any winning seed. [Protocol, hashes and paired results](evidence/silent-a10-progression-2026-11-19.json)

## Model selection and training

| Development finalist | Entered Act 2 | Entered Act 3 | Full wins |
|---|---:|---:|---:|
| Revised shop decisions | 75/224 | 4/224 | 0/224 |
| Shop decisions and encounter-specific targeting | 88/224 | 4/224 | 0/224 |
| Later-act routing and card drafting | 75/224 | **7/224** | 0/224 |
| Later-act routing, drafting and encounter-specific targeting | 88/224 | 5/224 | 0/224 |

All four finalists played the same 128 fixed-biome and 96 standard-lobby development seeds. The selection rule prioritized full wins, then Act 3 entries, Act 2 entries and total floor progression. This selected the later-act routing and drafting policy even though two alternatives entered Act 2 more often. The release includes the encounter-targeting alternative and a neural boss-combat student for further work.

The route model estimates the chance of dying in each room and the health and resources of survivors. It scores visible paths through to the boss. The Act 1 fit used 12,191 room transitions from a corpus of 800 seeds. The later-act fit used 19,688 transitions from 1,280 seeds, including standard-lobby and on-policy games. Its boss observations were sparse in later acts, with 840 Act 1, 49 Act 2 and one Act 3 observation. Three unconfirmed episodes were excluded from both fits.

The reward model learned from 3,548 alternative continuations of 1,025 decisions. Each alternative restored the same native state and changed the chosen action. The fit used 824 decision groups from 209 seeds and reserved 201 groups from 53 seeds for validation. The separate card-pick prior used 154 base or upgraded card entries. Its source gives separate statistics for A10+ and for each act across the beta v0.111 patch group. A strong prior from the start of the run hurt development performance. The selected policy delays its use until Act 2. [Public Silent card statistics](https://sts2.fun/cards?character=SILENT&patch=beta-v0.111)

On 82 identical, naturally reached Act 2 openings, the previous policy entered Act 3 twice and a later-act combat specialist did so seven times. From 16 identical Act 3 openings, the previous policy reached the first final boss three times and a specialist reached it four times. Neither completed both bosses on these starts. These are conditional experiments and each start has a separate public-state digest.

Targeting a follower early in the Kin fight won 24 of 73 alternative fights from identical openings, compared with 14 for the balanced scorer. It gained 11 fights and lost one that the balanced scorer had won. On the 15 held-out openings, the counts were four and two. The boss neural student trained on 7,020 decisions from 206 seeds, and agreed with 559 of 631 held-out teacher choices. The public combat scorer agreed on 564. Neither the targeting variant nor the neural student displaced the selected full-run policy.

## Endgame experiments

The first continuation comparison used 82 Act 2 and 16 Act 3 openings. Each comes from an actual run and has a matching opening digest on a separately compiled engine. A further experiment optimized combat and drafting weights directly on 12 of the Act 3 starts. Three generations of eight policies produced 96 completed continuations. On 15 different Act 3 development seeds, both the frozen and newly fitted weights reached the first final boss once and lost. The fitted weights are included as a development checkpoint.

Ten combat styles then played from 17 different openings against the first Act 3 boss, drawn from seven development seeds. The collection included the Test Subject, Queen and Aeonglass. The median starting health was 66. All 170 fights ended in losses. An offline search then tried 456 alternative action sequences on four of the more promising openings from distinct seeds. It could replay future draws during training. Its best Test Subject trajectory brought the last observed boss health down from 26.4% to 8.0% before the player died. All four best trajectories reproduced on the independent host.

After the benchmark, the frozen challenger collected 256 additional standard-lobby training games. It reached Act 2 on 79, Act 3 on seven, and won none. The release includes all 79 Act 2 and seven Act 3 openings from this additional cohort. Together the two collections provide 161 Act 2 and 23 Act 3 openings with independently verified native state digests. The new trajectories raised the route-training corpus to 24,197 room transitions from 1,536 seeds. The expanded fit contains 1,028 Act 1, 77 Act 2 and three Act 3 boss observations. On the same 82 Act 2 development openings, this refit reached the Act 2 boss 30 times, up from 28 for the frozen challenger. Both entered Act 3 four times. The release preserves this refit separately and the paired benchmark still refers to the original frozen policy.

## Reproduce the benchmark

The GitHub release includes the frozen policies, source Git bundle, selection record, per-game results, physical action histories and terminal replay receipts. All 17 archived development boss openings restored on the independently compiled engine. The archive includes their legal action histories. On a prepared Linux checkout with the pinned game assets and local .NET SDK, run these commands from the repository root. Each benchmark uses a new output directory. [Release downloads](https://github.com/jagenmark/STS2ML/releases/tag/silent-a10-2026-11-19) · [Cross-machine setup and training data](silent-a10-handoff.md)

```bash
.venv/bin/python scripts/restore-silent-a10.py --models-only
.venv/bin/python scripts/build-silent-host.py --output artifacts/silent-a10-progression-host
export STS2_SELECTOR_FIX_LOCAL_TASK=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
SILENT_HOST=artifacts/silent-a10-progression-host/src/Sts2Headless/bin/Curriculum/net9.0/Sts2Headless.dll
SILENT_RELEASE=artifacts/silent-a10-progression-release
.venv/bin/python scripts/compare-silent-bundles.py \
  --host "$SILENT_HOST" --incumbent "$SILENT_RELEASE/incumbent/policy.json" \
  --challenger "$SILENT_RELEASE/challenger/policy.json" \
  --suite default H2A10FINAL 256 --suite seeded H2A10MIXED 128 \
  --workers 8 --output artifacts/silent-a10-paired-reproduction
```

For a new ordinary standard-lobby run or for conditional training on the archived late-game openings, use the same host and release variables. The `development-openings` directories are suitable for model development. Use `--seeded-acts` with `act-2-standard` or `act-3-standard` for the newly collected standard-lobby starts. Use new seed prefixes for future full-run evaluations.

```bash
.venv/bin/python scripts/optimize-silent.py evaluate --host "$SILENT_HOST" \
  --bundle "$SILENT_RELEASE/challenger/policy.json" --roles candidate --seeded-acts \
  --prefix MYNEWLOBBY --seeds 32 --workers 4 --output artifacts/silent-a10-new-games
.venv/bin/python scripts/optimize-silent.py check-late --host "$SILENT_HOST" \
  --bundle "$SILENT_RELEASE/challenger/policy.json" --roles candidate \
  --act2-starts "$SILENT_RELEASE/development-openings/act-3" --curriculum-act 3 \
  --seeds 5 --workers 4 --output artifacts/silent-a10-act3-continuations
```

The development branch assigns the 16 fixed-biome Act 3 openings to 11 training and five test seeds. The 82 fixed-biome Act 2 openings supply 58 training and 24 test seeds. Pass a previous run’s `opening-split.json` with `--opening-split` to verify the same seed lists and opening hashes on another machine. To reproduce the historical all-opening comparisons, use the release tag.

The independent build and all evaluation games use the v0.111.0 game assembly. The headless host handles the Trial's verdict and abandonment, same-card redraws from Unceasing Top, shop procurement and removal, and native combat completion before rewards appear. The Underdocks checks cover Punch Off, Phantasmal Gardeners and the Soul Nexus death animation. All 17 previously interrupted decisions produced a confirmed native outcome with the revised host. The controlled native fixture also checks both final bosses. [Native host setup](headless-options.md)
