# Silent A10 v6 late combat search

On the locked 256-lobby development panel, Schema 3 covered **1,342/2,408 (55.7%)** of eligible Act 2 boss decisions and **274/539 (50.8%)** in Act 3. Frozen v5 covered 100/2,332 (4.3%) and 25/1,257 (2.0%) respectively. Both v6 arms recorded zero native mismatches.

**Wider search reduced progression for Schema 3.** Act 2 clears fell from 15 to 6 and Act 3 boss entries from 7 to 2. The paired mean floor difference was -0.395 (95% CI -0.688 to -0.152). Knowledge Demon accounted for seven of the nine lost clears, falling from 10/33 to 3/33 on the same boss entries. The heuristic cleared Act 2 in 10 lobbies and reached an Act 3 boss in 7.

## Paired outcomes

| Arm | Mean floor | Paired Δ [95% CI] | A1 clear | A2 boss | A2 clear | A3 boss | Full wins | p50 / p95 (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Frozen v5 Schema 3 | 23.953 | reference | 150 | 76 | 15 | 7 | 0 | 2.216 / 55.669 |
| v6 Schema 3 | 23.559 | -0.395 [-0.688, -0.152] | 150 | 76 | 6 | 2 | 0 | 2.589 / 58.418 |
| v6 heuristic | 23.844 | -0.109 [-1.203, +1.008] | 155 | 67 | 10 | 7 | 0 | 2.259 / 46.336 |

All milestone columns count lobbies out of 256. A clear means entry into the next act. Act 3 boss entry counts each lobby once. A full win requires native victory. The global floor is 17 × (act − 1) + local floor, as in v5. Floor intervals use 10,000 paired bootstrap samples, separately resampling the 128 lobbies in each act-list mode. The bootstrap RNG seed is 406. Latencies cover every combat decision from policy dispatch to physical selection, before the native step and audit. Native regression tests overlapped parts of the panel, so these wall-clock percentiles include machine contention.

The heuristic-minus-Schema-3 difference was **+0.285 floors** (95% paired CI -0.797 to +1.363). The heuristic uses its leaf in all search-eligible acts. Its head-to-head comparison includes earlier routing and different late-fight visits. Estimating its marginal gain from late coverage alone would require a fourth arm with the heuristic leaf and v6 disabled. The panel was reused during native qualification. These intervals describe development outcomes. The frozen champion is still the release policy.

## Coverage and survival

| Eligible decisions | Frozen v5 Schema 3 | v6 Schema 3 | v6 heuristic |
| --- | --- | --- | --- |
| Act 2 bosses | 100/2,332 (4.3%) | 1,342/2,408 (55.7%) | 1,451/2,266 (64.0%) |
| Kaiser Crab | 0/587 (0.0%) | 340/669 (50.8%) | 265/483 (54.9%) |
| Knowledge Demon | 0/1,188 (0.0%) | 697/1,201 (58.0%) | 920/1,317 (69.9%) |
| The Insatiable | 100/557 (18.0%) | 305/538 (56.7%) | 266/466 (57.1%) |
| Act 3 | 25/1,257 (2.0%) | 274/539 (50.8%) | 459/1,192 (38.5%) |

The denominator follows the v5 release census. It counts eligible in-combat choices with a recorded search disposition, including fallbacks, and excludes combat-play states with neither a playable card nor a usable potion. A covered choice required a certified search decision. Each arm follows its selected actions, so its encounter visits and decision counts can differ.

| Act 2 boss cleared / entered | Frozen v5 Schema 3 | v6 Schema 3 | v6 heuristic |
| --- | --- | --- | --- |
| Kaiser Crab | 2/25 (8.0%) | 1/25 (4.0%) | 1/18 (5.6%) |
| Knowledge Demon | 10/33 (30.3%) | 3/33 (9.1%) | 9/34 (26.5%) |
| The Insatiable | 3/18 (16.7%) | 2/18 (11.1%) | 0/15 (0.0%) |

| Arm | Act 2 boss exit HP (paired Δ, fights) | Act 3 exit HP (paired Δ, fights) |
| --- | --- | --- |
| Frozen v5 Schema 3 | 3.09 (+0.00, n=76) | 35.03 (+0.00, n=63) |
| v6 Schema 3 | 1.08 (-2.01, n=76) | 38.36 (-1.84, n=25) |
| v6 heuristic | 3.35 (-0.20, n=46) | 44.23 (+7.00, n=26) |

HP comparisons pair by lobby, act, local floor, room type and opening formation. Death contributes zero exit HP. Each v6 row uses the frozen-v5 value for those same matched fights. An arm's independently reached fights still count toward coverage and survival.

### Act 3 fallbacks and deaths

| Act 3 fallback | v6 Schema 3 | v6 heuristic |
| --- | --- | --- |
| no certified survival | 97 | 208 |
| champion continuation unresolved | 39 | 63 |
| profile/SOUL_NEXUS | 27 | 32 |
| uncertified root at cap | 18 | 24 |
| profile/BATTLE_FRIEND_V3 | 16 | 16 |
| profile/STABBOT | 14 | 12 |
| card/ASSASSINATE | 11 | 4 |
| selection operation | 8 | 6 |
| relic/BEATING_REMNANT | 0 | 86 |
| relic/WHISPERING_EARRING | 0 | 52 |
| unwitnessed wither count | 0 | 50 |
| profile/GUARDBOT | 0 | 34 |

| Fatal Act 3 formation | Frozen v5 Schema 3 | v6 Schema 3 | v6 heuristic |
| --- | --- | --- | --- |
| Test Subject | 4 | 2 | 2 |
| Punch Construct + Cubex Construct ×2 | 0 | 2 | 1 |
| Axebot | 1 | 1 | 2 |
| Slimed Berserker | 2 | 1 | 0 |
| Aeonglass | 3 | 0 | 4 |
| Devoted Sculptor | 2 | 0 | 0 |
| Fabricator | 2 | 0 | 0 |
| Owl Magistrate | 1 | 0 | 0 |
| Torch Head Amalgam + Queen | 0 | 0 | 1 |

## Native qualification

| Arm | Native matches | Native mismatches | Boundaries |
| --- | --- | --- | --- |
| Frozen v5 Schema 3 | 39489 | 4 | 3268 |
| v6 Schema 3 | 41753 | 0 | 3598 |
| v6 heuristic | 41655 | 0 | 3688 |

The frozen controller produced four zone mismatches on one lobby, `CSV4DEV_DEFAULT_0061`. Playing Dash twice, Predator once and Snakebite once returned Right Hand Hand from discard in the native host. Frozen v5 left it in discard. An independent observer applied the v6 return rule to the **same physical v5 actions** before comparing them with the pinned host. It recorded 39,493 matches, 0 mismatches and 3,268 boundaries. The two frozen-control passes also reproduced every terminal result, coverage count, late-fight exit and raw audit disposition across 256 lobbies. Both readings are retained in the receipts. The v6 flag also enables this rule in earlier rooms containing that card.

| Checked search revision / stage | Arm | Lobbies | Raw mismatches | Finding |
| --- | --- | --- | --- | --- |
| Initial implementation | Schema 3 | 256 | 6 | Ultimate Strike with Strike Dummy, Rampart after start-turn damage, Survivor before Enrage |
| fb32e53 | Schema 3 / heuristic | 256 each | 13 / 7 | Toasty Mittens and Plating, Meat on the Bone, curse-prompt relic timing, disabled wax relics and crab rage after poison |
| f3d85e8 | Schema 3 / heuristic | 256 each | 4 / 5 | Retain Hand countdown and Phantom Blades applying Retain to existing Shivs |
| 5c0bc7f | Schema 3 | 73 | 458 | Stopped when the pre-action projection exposed a new Stable Serum stat outside late rooms and the post-action projection used the frozen stat set. All recorded differences were potion metadata. |
| ab9725e | Schema 3 / heuristic | 256 each | 0 / 0 | Passed the native audit. A separate Confused × Frantic Escape fixture exposed a reveal-sensitive cost. |
| 7c2e4d5 | Schema 3 / heuristic | 256 each | 0 / 0 | Final public rules, including the Confused boundary and six pinned Razor Tooth upgrades. |

- **Kaiser Crab.** The search reads the champion's already-observed facing and the displayed intent. It turns toward the selected limb, accounts for back attacks, and stops when rounding leaves more than one possible adjusted hit. Poison and direct kills check the surviving arm's 99 Block and six Strength. Ambiguous multi-target hit order and phase transitions stop the line.
- **Knowledge Demon.** Prior, publicly observed Debuff intents identify the ordinal of the deterministic two-option curse offer. Both choices consume beam budget. At the actual prompt the controller checks the visible options, values, zones and board. Sloth counts witnessed plays and stops when automatic plays make that count uncertain. Native fixtures exercise both choices at all three offers, Disintegration, Mind Rot, Sloth, Waste Away, Demise and relic ordering.
- **The Insatiable.** The frozen Sandpit countdown, Frantic Escape and Devour transitions remain in use. V6 can reconcile Hidden Daggers discards and a witnessed Toasty Mittens prompt. A Confused draw that might randomize Frantic Escape's cost stops at the reveal boundary.
- **Act 3.** Pinned fixtures cover the Scrolls' Paper Cuts, Living Shield with Turret Operator, Slimed Berserker, Punch and Cubex Constructs, Axebot, Owl Magistrate, Lost and Forgotten, the three Knights, Globe Head, Mecha Knight, Devoted Sculptor, Fabricator and Frog Knight. Deterministic portions of Queen with Torch Head Amalgam, Test Subject, and Aeonglass qualify. The resolver stops at unmodeled summon, revival, reattachment, transformation and random-target transitions. Subsequent observed states can qualify again.
- **Hidden draws.** For each Act 2 boss the host fixture changes the hidden draw order, realizes different hands, and compares identical pre-reveal vectors. Current-hand costs, visible targets and past public intents are admissible. New-turn hands, intents and energy are excluded from leaf inputs. The host's post-action observation is used for auditing and for the next public decision.

## Integrity and reproduction

The new setting is `combat_search_v2_config.v6_late_coverage`, default `false`. The 10 challenger files are byte-identical to Git blobs at `efd98778688eac038cc946693cadd4389cb30d4d`. The policy manifest SHA-256 is `a686db12c8b217bd476ea5c8e60cf6f486b060665536ef9354e8f09c21c81fcb`. The protected legacy modules have no diff against that revision.

The pristine and current active-v5 receipts match byte for byte on all 24 CSV2DEV episodes. Flags-off receipts also match byte for byte. The v5 and v6 shadow runs each reproduce the flags-off physical digest, including actions, legal choices, score bits, RPCs and terminal outcome. V5 shadow recorded 3,534 matches and 351 explicit boundaries. V6 shadow recorded 3,681 matches and 369 boundaries. Both had zero native mismatches.

The paired arms used one search implementation commit, `7c2e4d5d0642ac58ed5777b4c6d69229056a80fc`, width 16 and a 512-child budget. Each used 12 CPU workers with OpenBLAS and OpenMP set to one thread. The pinned v0.111.0 host SHA-256 is `7408d040c28416331279a84e299b52ff35086d80b4cb9711aefd0f91168d8f20`. The game assembly SHA-256 is `14b57dbaee1b58cb919625a662831054fd714b3b75b13b7449eac0e95b98a3e4`. The fresh CSV4DEV lock SHA-256 is `96d62dae6b90dd1086b387a64e721c35a47ae2aab17a5f2420fb6a7a2ca63964`. No reserved evaluation lobby was run.

With the pinned host in `CSV2DEV_HOST`, run `scripts/ablate-silent-v6.py --arm ARM --workers 12 --output DIRECTORY` for each arm (`v5`, `schema3`, `heuristic`). Run `scripts/report-silent-v6.py RECEIPTS.jsonl.gz --pack DIRECTORY` to pack and summarize. The flags-off and shadow driver is `probes/v6_gate.py`. The full native suite used the pinned observer in `CSV2DEV_OBSERVER` and the `v6_fixture_seeds` pytest plugin on the probes import path, which maps historical scenario fixtures onto fresh CSV4FIX names. Pytest reported **554 passed in 277.36s (0:04:37)**. Ruff checked 108 Python files under `src/` and `tests/` with zero findings.

[Locked lobbies](v6-dev-lock.json) · [Compact episode receipts](v6-dev-receipts.jsonl.gz) · [File hashes, three arm manifests, discovery counts and CSV2DEV receipts](v6-verification.json) · [Pinned native fixtures](../../tests/test_combat_search_v6_native.py)
