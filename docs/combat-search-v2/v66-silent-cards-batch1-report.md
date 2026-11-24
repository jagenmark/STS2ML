# Silent A10 v6.6 Batch 1

On 192 paired CSV11DEV lobbies, adding the Silent rules to v6.5 Arm A changed mean progression by +0.28 floors (95% paired interval -0.41 to +0.98). Arm B with the same rules finished -1.83 floors relative to the v6.5 Arm A control. Both v6.6 arms recorded zero native mismatches.

Arm A gained 4.35 native matches per 100 combat decisions. Its floor interval spans zero. Arm B's floor interval was -3.40 to -0.29. Its Act 2 boss clears fell from 15 in control to 5. The p95 combat decision took 84.5 ms in Arm 1 and 82.1 ms in Arm 2, compared with 65.4 ms in control.

## Paired development results

| Metric | Control · v6.5 A | Arm 1 · v6.6 A | Arm 2 · v6.6 B |
|---|---:|---:|---:|
| Starts | 192 | 192 | 192 |
| Mean global floor | 26.021 | 26.302 | 24.188 |
| Act 1 boss clears / entries | 130 / 181 | 131 / 182 | 112 / 185 |
| Act 2 boss clears / entries | 15 / 69 | 17 / 73 | 5 / 57 |
| CRUSHER+ROCKET clears / entries | 1 / 33 | 5 / 35 | 3 / 26 |
| KNOWLEDGE_DEMON clears / entries | 9 / 21 | 8 / 22 | 0 / 14 |
| THE_INSATIABLE clears / entries | 5 / 15 | 4 / 16 | 2 / 17 |
| Act 3 boss entries | 7 | 8 | 1 |
| Full wins | 0 | 0 | 0 |
| Default mean floor | 25.531 | 25.354 | 24.219 |
| Default native matches per 100 | 73.53 | 78.25 | 76.80 |
| Seeded mean floor | 26.510 | 27.250 | 24.156 |
| Seeded native matches per 100 | 69.07 | 73.17 | 70.66 |
| Combat decisions | 51,062 | 51,293 | 51,665 |
| Native match / mismatch / unresolved | 36,381 / 1 / 3,689 | 38,778 / 0 / 3,206 | 38,082 / 0 / 4,046 |
| Native matches per 100 combat decisions | 71.25 | 75.60 | 73.71 |
| Latency p50 / p95 (ms) | 3.158 / 65.445 | 4.488 / 84.467 | 4.523 / 82.133 |

Each arm played 96 default and 96 seeded lobbies. The run used 12 workers, rotating arm order, and one OpenBLAS and OpenMP thread per worker. Global floor is 17 × (act − 1) + floor. The intervals use 50,000 mode-stratified paired bootstrap samples.

| Comparison | Mean floor difference | 95% interval | Floor wins / losses / ties |
|---|---:|---:|---:|
| Arm 1 vs Control | +0.281 | -0.411 to +0.984 | 21 / 14 / 157 |
| Arm 2 vs Control | -1.833 | -3.396 to -0.292 | 60 / 70 / 62 |
| Arm 2 vs Arm 1 | -2.115 | -3.630 to -0.635 | 54 / 66 / 72 |

The frozen v6.5 control recorded 1 mismatch on its own oracle. Pocketwatch resets its counter before hand draw and refreshes its status after the Toasty Mittens prompt. The independent control audit applies that ordering to the same physical actions and compared 36,382 matches, 0 mismatches and 3,689 unresolved transitions. The two v6.6 arms use their production oracle for every verdict in the table.

Historical v6.5 Arm B recorded 57.95 native matches per 100 decisions and a −2.45 floor gap against its CSV10DEV control. CSV11DEV Arm 2 changed those figures by +15.76 matches per 100 and +0.62 floors. The historical comparison uses different seeds and controls. The paired comparison above measures the effect of enabling v6.6 for Arm A. There is no v6.5 B arm on these same seeds.

## Implementation and qualification

Rules commit `1f48b17aed67fceccf5e9394c41f597111ad52c6` descends from `8c27ce5ddf5348f88b1cedb3c3cd5b24bd5c40b1`. Set `silent_cards_v66` in the combat search configuration to enable the rules. The default is false. The two treatment bundles preserve their respective v6.5 acquisition policies.

The pinned Tools of the Trade adds one stack at either upgrade level. Its start-of-turn effect increases hand draw by the stack count and then asks for a discard. The normal end-turn transition certifies enemy resolution before that choice. The discard resumes from the public hand. Effects scheduled after the prompt, including Noxious Fumes, are applied after the selection. Mixed unordered I Am Invincible draw piles suspend before enemy resolution. The two native draw orders reproduce different HP outcomes.

Well-Laid Plans retains the whole hand in this build. Its new setup value is 2.2 HP-equivalent units per discounted future turn, capped at four turns. Remaining enemy HP after projected poison determines that horizon. The native card rules and this search heuristic are tested separately.

Helmer ran the CPU Python environment against host SHA-256 `7408d040c28416331279a84e299b52ff35086d80b4cb9711aefd0f91168d8f20` and game SHA-256 `14b57dbaee1b58cb919625a662831054fd714b3b75b13b7449eac0e95b98a3e4`. Native fixtures cover the base and upgraded forms of every Wave 1 and promoted card, hidden-target and draw branches, prompt continuation, and replays of the original failing commands. The JSON fingerprints the decompiled card, power, enchantment and pool models.

Pytest reported **858 passed in 258.55s (0:04:18)**. Ruff reported **All checks passed!** across src and tests. All 19 historical builder outputs, all ten v5 challenger files at efd9877, and 120 CSV2DEV receipts matched their reference bytes. Each of off, active, shadow, frozen v5 and Kaiser contributed 24 receipts. The original v6.5 checkout reproduced all 192 control command transcripts and deterministic outcomes. The compact archive includes the per-lobby verdicts, latency histograms, test output and compatibility hashes.

## Per-card triggers and hits

Each cell gives physical plays / native-matched card executions / attack hits in those executions. Executions include replays and automatic plays. Hits count individual living targets struck, including blocked hits. The JSON also distinguishes per-play native matches, unresolved transitions and mismatches. Corrosive Wave saw no physical play in this cohort. Murder and Storm of Steel had no matched executions in either treatment. Dedicated native fixtures cover all three.

| Card | Control | Arm 1 | Arm 2 |
|---|---:|---:|---:|
| ABRASIVE | 2 / 0 / 0 | 1 / 1 / 0 | 3 / 4 / 0 |
| ACCURACY | 16 / 8 / 0 | 16 / 9 / 0 | 101 / 78 / 0 |
| ASSASSINATE | 129 / 69 / 69 | 140 / 91 / 91 | 55 / 45 / 45 |
| BLADE_OF_INK | 1 / 0 / 0 | 1 / 0 / 0 | 26 / 18 / 0 |
| BOUNCING_FLASK | 48 / 13 / 0 | 33 / 17 / 0 | 56 / 30 / 0 |
| BULLET_TIME | 0 / 0 / 0 | 0 / 0 / 0 | 9 / 8 / 0 |
| CORROSIVE_WAVE | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |
| DODGE_AND_ROLL | 8 / 0 / 0 | 6 / 6 / 0 | 171 / 153 / 0 |
| ECHOING_SLASH | 386 / 104 / 171 | 378 / 309 / 589 | 370 / 318 / 572 |
| ENVENOM | 9 / 0 / 0 | 9 / 6 / 0 | 13 / 11 / 0 |
| ESCAPE_PLAN | 2 / 0 / 0 | 3 / 0 / 0 | 86 / 3 / 0 |
| EXPOSE | 10 / 0 / 0 | 10 / 9 / 0 | 208 / 163 / 0 |
| EXTERMINATE | 35 / 2 / 12 | 28 / 26 / 152 | 33 / 27 / 149 |
| FINISHER | 46 / 0 / 0 | 60 / 51 / 117 | 153 / 134 / 297 |
| HAND_TRICK | 30 / 0 / 0 | 36 / 29 / 0 | 14 / 14 / 0 |
| HIDDEN_DAGGERS | 126 / 43 / 0 | 104 / 82 / 0 | 225 / 167 / 0 |
| INFINITE_BLADES | 41 / 22 / 0 | 38 / 24 / 0 | 134 / 100 / 0 |
| KNIFE_TRAP | 1 / 0 / 0 | 3 / 3 / 0 | 11 / 4 / 0 |
| MEMENTO_MORI | 47 / 0 / 0 | 52 / 39 / 39 | 82 / 61 / 61 |
| MURDER | 1 / 0 / 0 | 1 / 0 / 0 | 1 / 0 / 0 |
| OUTBREAK | 47 / 1 / 0 | 52 / 32 / 0 | 37 / 30 / 0 |
| PHANTOM_BLADES | 35 / 13 / 0 | 32 / 26 / 0 | 122 / 86 / 0 |
| PIERCING_WAIL | 10 / 0 / 0 | 10 / 10 / 0 | 168 / 116 / 0 |
| PINPOINT | 69 / 17 / 17 | 83 / 77 / 77 | 93 / 85 / 85 |
| POUNCE | 119 / 0 / 0 | 177 / 154 / 154 | 183 / 154 / 154 |
| RICOCHET | 64 / 0 / 0 | 75 / 77 / 315 | 110 / 152 / 606 |
| SERPENT_FORM | 1 / 0 / 0 | 2 / 1 / 0 | 9 / 6 / 0 |
| SHADOWMELD | 1 / 0 / 0 | 3 / 3 / 0 | 26 / 25 / 0 |
| SHADOW_STEP | 1 / 0 / 0 | 1 / 0 / 0 | 60 / 45 / 0 |
| SIDESTEP | 22 / 10 / 0 | 20 / 18 / 0 | 0 / 0 / 0 |
| SPEEDSTER | 3 / 0 / 0 | 4 / 2 / 0 | 24 / 21 / 0 |
| STORM_OF_STEEL | 2 / 0 / 0 | 2 / 0 / 0 | 1 / 0 / 0 |
| STRANGLE | 30 / 0 / 0 | 30 / 21 / 21 | 309 / 271 / 271 |
| THE_HUNT | 45 / 28 / 28 | 41 / 25 / 25 | 0 / 0 / 0 |
| TOOLS_OF_THE_TRADE | 5 / 0 / 0 | 6 / 4 / 0 | 36 / 29 / 0 |
| TRACKING | 2 / 0 / 0 | 3 / 3 / 0 | 1 / 1 / 0 |
| UP_MY_SLEEVE | 46 / 0 / 0 | 53 / 45 / 0 | 46 / 37 / 0 |
| WELL_LAID_PLANS | 53 / 50 / 0 | 40 / 36 / 0 | 17 / 16 / 0 |

## Pinned Silent pool and Batch 2

The pinned SilentCardPool.GenerateAllCards() returns 91 distinct models. The ordinary single-player reward pool has 80 cards. The other entries are four basics, two Ancient cards and five multiplayer-only cards. Exterminate is a separately qualified event card. Shiv is a generated token.

Of the 91 models, 48 are SUPPORTED_FULL, 32 are SUPPORTED_BOUNDARY, and 11 remain for Batch 2. The four missing ordinary single-player rewards are Expertise, Master Planner, Mirage and Untouchable.

SUPPORTED_FULL records deterministic card mechanics in the qualified kernel. Shared encounter, enchantment and relic boundaries still apply. SUPPORTED_BOUNDARY records root admission with a named conditional or legacy play boundary. REMAINING_BATCH2 lists every missing model, including multiplayer-only models outside single-player A10.

| Card | Pool | Status | Boundary or remaining native mechanic |
|---|---|---|---|
| ABRASIVE | Reward | SUPPORTED_FULL | — |
| ACCELERANT | Reward | SUPPORTED_FULL | — |
| ACCURACY | Reward | SUPPORTED_FULL | — |
| ACROBATICS | Reward | SUPPORTED_BOUNDARY | Hidden mid-turn draw. |
| ADRENALINE | Reward | SUPPORTED_BOUNDARY | Hidden mid-turn draw. |
| AFTERIMAGE | Reward | SUPPORTED_FULL | — |
| ANTICIPATE | Reward | SUPPORTED_FULL | — |
| ASSASSINATE | Reward | SUPPORTED_FULL | — |
| BACKFLIP | Reward | SUPPORTED_BOUNDARY | Hidden mid-turn draw. |
| BACKSTAB | Reward | SUPPORTED_FULL | — |
| BLADE_DANCE | Reward | SUPPORTED_FULL | — |
| BLADE_OF_INK | Reward | SUPPORTED_BOUNDARY | Existing Phantom Blades first-Shiv history can require a witness when playing the generated Shiv. |
| BLADE_SYMPHONY | Multiplayer | REMAINING_BATCH2 | Multiplayer. Create two Shivs for each living player teammate. Upgrade reduces cost from 2 to 1. |
| BLUR | Reward | SUPPORTED_FULL | — |
| BOUNCING_FLASK | Reward | SUPPORTED_BOUNDARY | Multiple living targets. |
| BUBBLE_BUBBLE | Reward | SUPPORTED_FULL | — |
| BULLET_TIME | Reward | SUPPORTED_FULL | — |
| BURST | Reward | SUPPORTED_BOUNDARY | A repeated Skill can suspend on a draw or selection. |
| CALCULATED_GAMBLE | Reward | SUPPORTED_BOUNDARY | Hidden mid-turn draw. |
| CLOAK_AND_DAGGER | Reward | SUPPORTED_FULL | — |
| CONCOCT | Multiplayer | REMAINING_BATCH2 | Multiplayer. Give an ally 3/4 Concoct. Its unblocked powered hits apply that much Poison until the end of the opposing side’s turn. |
| CORROSIVE_WAVE | Reward | SUPPORTED_BOUNDARY | Poison after extra draws. A mixed hidden draw suspends the play. |
| DAGGER_SPRAY | Reward | SUPPORTED_BOUNDARY | Multi-hit Curl Up ordering. |
| DAGGER_THROW | Reward | SUPPORTED_BOUNDARY | Hidden mid-turn draw. |
| DASH | Reward | SUPPORTED_FULL | — |
| DEADLY_POISON | Reward | SUPPORTED_FULL | — |
| DEFEND_SILENT | Basic | SUPPORTED_FULL | — |
| DEFLECT | Reward | SUPPORTED_FULL | — |
| DODGE_AND_ROLL | Reward | SUPPORTED_FULL | — |
| ECHOING_SLASH | Reward | SUPPORTED_FULL | — |
| ENVENOM | Reward | SUPPORTED_FULL | — |
| ESCAPE_PLAN | Reward | SUPPORTED_BOUNDARY | Known Skill draw gains Block. A mixed hidden draw suspends before reveal. |
| EXPERTISE | Reward | REMAINING_BATCH2 | Draw 2/3 cards and give each drawn card Retain for this turn. |
| EXPOSE | Reward | SUPPORTED_FULL | — |
| FADE | Multiplayer | REMAINING_BATCH2 | Multiplayer. Retain. Give an ally 6/9 temporary Dexterity until the end of its side’s turn. |
| FAN_OF_KNIVES | Reward | SUPPORTED_FULL | — |
| FINISHER | Reward | SUPPORTED_BOUNDARY | Use the public calculated hit count, otherwise suspend on unwitnessed attack history. |
| FLANKING | Multiplayer | REMAINING_BATCH2 | Multiplayer. Other attackers’ powered hits on the target deal double damage until the end of its side’s turn. Upgrade reduces cost from 2 to 1. |
| FLECHETTES | Reward | SUPPORTED_BOUNDARY | Multi-hit Curl Up ordering. |
| FLICK_FLACK | Reward | SUPPORTED_FULL | — |
| FOOTWORK | Reward | SUPPORTED_FULL | — |
| GRAND_FINALE | Reward | SUPPORTED_FULL | — |
| HAND_TRICK | Reward | SUPPORTED_FULL | — |
| HAZE | Reward | SUPPORTED_FULL | — |
| HIDDEN_DAGGERS | Reward | SUPPORTED_BOUNDARY | Discard selection may auto-play Sly cards with multiple targets. |
| INFINITE_BLADES | Reward | SUPPORTED_FULL | — |
| KNIFE_TRAP | Reward | SUPPORTED_BOUNDARY | Replays exhausted Shivs. Mixed exhaust order or a dead replay target can suspend. |
| LEADING_STRIKE | Reward | SUPPORTED_FULL | — |
| LEG_SWEEP | Reward | SUPPORTED_FULL | — |
| MALAISE | Reward | SUPPORTED_FULL | — |
| MASTER_PLANNER | Reward | REMAINING_BATCH2 | After the owner plays a Skill, permanently give that combat copy Sly. Upgrade reduces cost from 2 to 1. |
| MEMENTO_MORI | Reward | SUPPORTED_BOUNDARY | Infer discarded-card count from an unambiguous public preview. |
| MIRAGE | Reward | REMAINING_BATCH2 | Gain modified Block with base equal to total Poison on living enemies. Exhaust. Upgrade removes Exhaust. |
| MURDER | Reward | SUPPORTED_BOUNDARY | Infer combat draw count from an unambiguous public preview. |
| NEUTRALIZE | Basic | SUPPORTED_FULL | — |
| NIGHTMARE | Reward | SUPPORTED_BOUNDARY | Root-admitted legacy play boundary. Batch 2 can model choosing a hand card and creating three copies next turn. |
| NOXIOUS_FUMES | Reward | SUPPORTED_FULL | — |
| OUTBREAK | Reward | SUPPORTED_BOUNDARY | Poison tick can wake an enemy whose new move is hidden. |
| PHANTOM_BLADES | Reward | SUPPORTED_BOUNDARY | Retain applies to existing and future Shivs. First-Shiv bonus needs a witness. |
| PIERCING_WAIL | Reward | SUPPORTED_FULL | — |
| PINPOINT | Reward | SUPPORTED_FULL | — |
| POISONED_STAB | Reward | SUPPORTED_FULL | — |
| POUNCE | Reward | SUPPORTED_BOUNDARY | The final Free Skill stack can conceal the underlying costs of other hand cards. |
| PRECISE_CUT | Reward | SUPPORTED_FULL | — |
| PREDATOR | Reward | SUPPORTED_FULL | — |
| PREPARED | Reward | SUPPORTED_BOUNDARY | Hidden mid-turn draw. |
| REFLEX | Reward | SUPPORTED_BOUNDARY | Hidden mid-turn draw. |
| RICOCHET | Reward | SUPPORTED_BOUNDARY | One living target resolves all 4/5 hits. Multiple targets require native RNG. |
| SERPENT_FORM | Reward | SUPPORTED_BOUNDARY | After a subsequent card, deal 4/6 damage to one random enemy. A sole target resolves locally. |
| SHADOWMELD | Reward | SUPPORTED_FULL | — |
| SHADOW_STEP | Reward | SUPPORTED_BOUNDARY | All-hand discard can auto-play Sly cards with hidden targets. |
| SIDESTEP | Reward | SUPPORTED_FULL | — |
| SKEWER | Reward | SUPPORTED_BOUNDARY | Multi-hit Curl Up ordering. |
| SLICE | Reward | SUPPORTED_FULL | — |
| SNAKEBITE | Reward | SUPPORTED_FULL | — |
| SNEAKY | Multiplayer | REMAINING_BATCH2 | Multiplayer. Sly. Gain 1/2 unpowered Block each time another player finishes playing an Attack. |
| SPEEDSTER | Reward | SUPPORTED_BOUNDARY | Extra draws hit each enemy. A mixed hidden draw suspends the play. |
| STORM_OF_STEEL | Reward | SUPPORTED_BOUNDARY | All-hand discard can auto-play Sly cards before Shiv creation. |
| STRANGLE | Reward | SUPPORTED_FULL | — |
| STRIKE_SILENT | Basic | SUPPORTED_FULL | — |
| SUCKER_PUNCH | Reward | SUPPORTED_FULL | — |
| SUPPRESS | Ancient | REMAINING_BATCH2 | Ancient. Innate. Deal 11/17 damage and apply 3/5 Weak to one enemy for zero energy. |
| SURVIVOR | Basic | SUPPORTED_BOUNDARY | Discarded Sly attack can require a random target. |
| TACTICIAN | Reward | SUPPORTED_FULL | — |
| THE_HUNT | Reward | SUPPORTED_BOUNDARY | A fatal hit can require special monster death eligibility. |
| TOOLS_OF_THE_TRADE | Reward | SUPPORTED_BOUNDARY | Ordinary end turn certifies at next-hand reveal. Interacting start-turn prompts can suspend. |
| TRACKING | Reward | SUPPORTED_FULL | — |
| UNTOUCHABLE | Reward | REMAINING_BATCH2 | Sly. Gain 6/9 modified Block for two energy. |
| UP_MY_SLEEVE | Reward | SUPPORTED_FULL | — |
| WELL_LAID_PLANS | Reward | SUPPORTED_FULL | — |
| WRAITH_FORM | Ancient | REMAINING_BATCH2 | Ancient. Gain 2/3 Intangible and a debuff that removes one Dexterity at each subsequent player-side turn start. |
