# Silent A10 v6.7 · complete single-player card pool

All 86 single-player models in the pinned 91-card Silent pool pass root admission. On 384 paired CSV12DEV lobbies, v6.7 A changed mean progression by +0.354 floors (95% paired interval -0.148 to +0.862). Native matches per 100 combat decisions changed by +4.71. The v6.7 A and B runs recorded zero native mismatches.

## Paired progression, coverage and latency

| Metric | v6.5 A control | v6.7 A treatment | v6.7 B stress |
|---|---:|---:|---:|
| Lobbies | 384 | 384 | 64 |
| Mean global floor | 25.091 | 25.445 | 24.266 |
| Act 1 boss clears / entries | 257 / 347 | 258 / 356 | 37 / 60 |
| Act 2 boss clears / entries | 23 / 118 | 27 / 120 | 3 / 21 |
| CRUSHER+ROCKET clears / entries | 6 / 46 | 6 / 43 | 1 / 6 |
| KNOWLEDGE_DEMON clears / entries | 5 / 33 | 9 / 34 | 2 / 8 |
| THE_INSATIABLE clears / entries | 12 / 39 | 12 / 43 | 0 / 7 |
| Act 3 boss entries | 12 | 15 | 1 |
| Full wins | 0 | 0 | 0 |
| Combat decisions | 100,050 | 101,225 | 17,692 |
| Native matches / mismatches / unresolved | 72,902 / 21 / 6,715 | 78,530 / 0 / 5,906 | 13,129 / 0 / 1,325 |
| Native matches per 100 combat decisions | 72.87 | 77.58 | 74.21 |
| Latency p50 / p95 / p99 (ms) | 3.34 / 67.47 / 97.06 | 5.00 / 90.22 / 116.38 | 5.00 / 90.82 / 119.40 |
| Default mean floor | 24.609 | 25.188 | 24.438 |
| Default matches / 100 decisions | 74.75 | 80.61 | 77.26 |
| Seeded mean floor | 25.573 | 25.703 | 24.094 |
| Seeded matches / 100 decisions | 71.06 | 74.63 | 71.34 |

Arm A finished higher on 55 pairs, lower on 44, and tied on 285. Global floor is 17 × (act − 1) + floor. The confidence interval uses 50,000 mode-stratified paired bootstrap samples. Each A arm ran the same 192 default and 192 seeded lobbies. B used the first 32 pairs of modes, for 64 lobbies. Arm order rotated within lobby. The cohort used 12 workers and one OpenBLAS and OpenMP thread per worker.

The frozen control recorded 21 native mismatches. The first v6.7 implementation also advanced a melted Kunai in CSV12DEV_DEFAULT_0127. Toy Box melts the first remaining wax relic every third combat. The host keeps its physical counter visible while CombatState omits the relic from combat hooks. The corrected projection preserves the displayed relic for comparison and excludes its hooks after a witnessed melt. A permanent fixture replays all 12 originally failing treatment commands, including the Louse Progenitor and Insatiable encounters. The table uses a fresh complete run with the corrected production oracle.

Treatment p95 was 90.22 ms versus 67.47 ms on the same lobbies. The earlier v6.6 A run measured 84.47 ms on CSV11DEV. Expertise checks pile homogeneity at most three times per play. Master Planner scans the pending play queue when a Skill first gains Sly. Mirage sums living enemy stacks once, and Nightmare creates a fixed three copies.

In a fixed-root timing check, increasing the draw pile from 32 to 512 cards changed median Expertise transition time from 119.1 to 251.2 µs. Master Planner setup scoring changed from 9.3 to 76.1 µs. Each median uses seven batches of 256 calls.

The paired floor interval spans zero, so this cohort does not establish a progression gain.

## Card evidence in the two v6.7 arms

Counts are physical plays / directly matched play transitions. An automatic Sly play can occur within another command. Pinned scenarios exercise each base and upgraded form independently of cohort acquisition.

| Card | v6.7 A | v6.7 B |
|---|---:|---:|
| EXPERTISE | 0 / 0 | 4 / 0 |
| MASTER_PLANNER | 1 / 0 | 4 / 4 |
| MIRAGE | 1 / 1 | 5 / 3 |
| NIGHTMARE | 0 / 0 | 2 / 2 |
| SUPPRESS | 0 / 0 | 0 / 0 |
| UNTOUCHABLE | 7 / 5 | 2 / 0 |
| WRAITH_FORM | 0 / 0 | 0 / 0 |

## Rules and qualification

Set `silent_cards_v67` to true to enable Batch 2 and the v6.6 rules. The flag defaults to false. Arm A uses the v6.5 trap-cleanup acquisition profile. Arm B uses the v6.5 unified draft profile.

The native host grants Master Planner’s keyword after a Skill, before a replay. A second copy of the power increments the observable stack counter and the Skill still gains one keyword. Expertise’s temporary Retain follows the physical card into discard and clears during end-turn cleanup. Mirage counts each living enemy before the ordinary Dexterity and Frail modifiers. Suppress resolves its hit and Envenom before Weak.

Wraith Form applies Intangible first. Player Artifact can consume the debuff at play time. Artifact acquired afterward can block a subsequent Dexterity loss. Intangible caps individual damage instances at one and decrements after the enemy side ends. The start-turn loss waits for a pending Tools of the Trade or Toasty Mittens choice. The Artifact fixture applies the native scenario power then plays through the pinned RunSimulator. The benchmark uses the original headless process.

Nightmare snapshots the selected hand copy and creates three copies before hand draw. The public power exposes its count but omits the card identity. A witnessed ordinary choice certifies enemy resolution, the generated hand positions and pile conservation at the next draw. An unwitnessed or unsupported clone uses a named boundary. Pocketwatch resets its counter before hand draw, then refreshes its status after Toasty Mittens. The native regression crosses the fourth play and checks both sides of the prompt.

The Master Planner heuristic values available discard effects and eligible Skills over the remaining fight horizon. Wraith Form values protected turns and charges for future Dexterity loss. These values affect search ranking. The differential tests compare physical game outcomes.

Helmer ran CPU Python on rules commit `decf295baa57d5f0d9ba80e0c60f682e38d29603`. Pytest reported **898 passed in 120.38s (0:02:00)**. Ruff reported **All checks passed!**. All 21 historical builder profiles reproduced their output bytes, all ten frozen challenger files matched efd9877, and all 120 CSV2DEV receipts matched their archived bytes. Both v6.6 CSV11DEV arms reproduced all 384 deterministic episode records with v6.7 disabled, including command hashes, card counts and native verdicts. Wall-clock timings were excluded from the v6.6 replay comparison.

Pinned host SHA-256 `7408d040c28416331279a84e299b52ff35086d80b4cb9711aefd0f91168d8f20`. Game SHA-256 `14b57dbaee1b58cb919625a662831054fd714b3b75b13b7449eac0e95b98a3e4`. The receipt archive contains the manifest, per-lobby results and latency histograms, source fingerprints, compatibility receipts and qualification logs.

## Pinned Silent inventory

The 86 solo cards comprise 80 rewards, four basics and two Ancient cards. SUPPORTED_BOUNDARY admits the card at the root and can suspend on a hidden draw, selection, history or other named condition. Common encounter and relic boundaries apply throughout. The five multiplayer-only models are excluded.

| Card | Pool | Status | Rule or conditional boundary |
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
| BLADE_SYMPHONY | Multiplayer | EXCLUDED_MULTIPLAYER | Multiplayer. Create two Shivs for each living player teammate. Upgrade reduces cost from 2 to 1. |
| BLUR | Reward | SUPPORTED_FULL | — |
| BOUNCING_FLASK | Reward | SUPPORTED_BOUNDARY | Multiple living targets. |
| BUBBLE_BUBBLE | Reward | SUPPORTED_FULL | — |
| BULLET_TIME | Reward | SUPPORTED_FULL | — |
| BURST | Reward | SUPPORTED_BOUNDARY | A repeated Skill can suspend on a draw or selection. |
| CALCULATED_GAMBLE | Reward | SUPPORTED_BOUNDARY | Hidden mid-turn draw. |
| CLOAK_AND_DAGGER | Reward | SUPPORTED_FULL | — |
| CONCOCT | Multiplayer | EXCLUDED_MULTIPLAYER | Multiplayer. Give an ally 3/4 Concoct. Its unblocked powered hits apply that much Poison until the end of the opposing side’s turn. |
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
| EXPERTISE | Reward | SUPPORTED_BOUNDARY | Draw 2/3 and retain the drawn copies this turn. A mixed hidden pile suspends before spending energy. |
| EXPOSE | Reward | SUPPORTED_FULL | — |
| FADE | Multiplayer | EXCLUDED_MULTIPLAYER | Multiplayer. Retain. Give an ally 6/9 temporary Dexterity until the end of its side’s turn. |
| FAN_OF_KNIVES | Reward | SUPPORTED_FULL | — |
| FINISHER | Reward | SUPPORTED_BOUNDARY | Use the public calculated hit count, otherwise suspend on unwitnessed attack history. |
| FLANKING | Multiplayer | EXCLUDED_MULTIPLAYER | Multiplayer. Other attackers’ powered hits on the target deal double damage until the end of its side’s turn. Upgrade reduces cost from 2 to 1. |
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
| MASTER_PLANNER | Reward | SUPPORTED_FULL | After a Skill finishes playing, that combat copy gains permanent Sly, including before a replay. |
| MEMENTO_MORI | Reward | SUPPORTED_BOUNDARY | Infer discarded-card count from an unambiguous public preview. |
| MIRAGE | Reward | SUPPORTED_FULL | Modified Block from total Poison on living enemies. Only the base version Exhausts. |
| MURDER | Reward | SUPPORTED_BOUNDARY | Infer combat draw count from an unambiguous public preview. |
| NEUTRALIZE | Basic | SUPPORTED_FULL | — |
| NIGHTMARE | Reward | SUPPORTED_BOUNDARY | Witness the selected copy and create three before hand draw. Multiple instances, modified clones, overflow or competing generation can suspend. |
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
| SNEAKY | Multiplayer | EXCLUDED_MULTIPLAYER | Multiplayer. Sly. Gain 1/2 unpowered Block each time another player finishes playing an Attack. |
| SPEEDSTER | Reward | SUPPORTED_BOUNDARY | Extra draws hit each enemy. A mixed hidden draw suspends the play. |
| STORM_OF_STEEL | Reward | SUPPORTED_BOUNDARY | All-hand discard can auto-play Sly cards before Shiv creation. |
| STRANGLE | Reward | SUPPORTED_FULL | — |
| STRIKE_SILENT | Basic | SUPPORTED_FULL | — |
| SUCKER_PUNCH | Reward | SUPPORTED_FULL | — |
| SUPPRESS | Ancient | SUPPORTED_FULL | Innate. Deal 11/17 damage, then apply 3/5 Weak. |
| SURVIVOR | Basic | SUPPORTED_BOUNDARY | Discarded Sly attack can require a random target. |
| TACTICIAN | Reward | SUPPORTED_FULL | — |
| THE_HUNT | Reward | SUPPORTED_BOUNDARY | A fatal hit can require special monster death eligibility. |
| TOOLS_OF_THE_TRADE | Reward | SUPPORTED_BOUNDARY | Ordinary end turn certifies at next-hand reveal. Interacting start-turn prompts can suspend. |
| TRACKING | Reward | SUPPORTED_FULL | — |
| UNTOUCHABLE | Reward | SUPPORTED_FULL | Sly. Gain 6/9 modified Block on manual play or automatic discard play. |
| UP_MY_SLEEVE | Reward | SUPPORTED_FULL | — |
| WELL_LAID_PLANS | Reward | SUPPORTED_FULL | — |
| WRAITH_FORM | Ancient | SUPPORTED_FULL | Gain 2/3 Intangible. The separate debuff applies negative Dexterity after player-side turn start. |
