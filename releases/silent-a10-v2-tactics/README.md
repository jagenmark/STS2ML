# Silent A10 v5 challenger

The frozen challenger is `all_v2_search_v5`, built on `all_v2_p1_v4` with width 16, depth 10, a 512-child budget, a 7.0 HP potion reserve and zero extra win weight. Its Schema 3 NumPy checkpoint has SHA-256 `24debeaaa81c0095cf252807e05e858cf53b8dcbf23ed2e9eb274f267112cb0b`. The policy manifest has SHA-256 `a686db12c8b217bd476ea5c8e60cf6f486b060665536ef9354e8f09c21c81fcb`. [Frozen policy](challenger/policy.json)

All three arms completed 896/896 same-host lobbies with zero retries. On POOLED896, v5 gained 1.138 floors over v4 (95% CI +0.545 to +1.719, exact sign p = 1.77e−6). On unseen REP512 it gained 1.117 floors (+0.295 to +1.930, p = 7.48e−5). Both panels met all three progression gates. The pooled heuristic-minus-Schema 3 interval of −0.367 to +0.624 retained the pre-registered primary. The `v5_release` entry in the benchmark contains all 12 paired comparisons, milestone discordance and encounter diagnostics. [Release report](../../docs/combat-search-v2/v5-release-report.md) · [Benchmark](benchmark.json) · [Episode receipts](v5-receipts.zip)

| Cohort | Arm | Mean floor | A1 boss | A1 clear | A2 boss | A2 clear | A3 boss | Wins |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| VAL256 | v4 | 23.309 | 221 | 158 | 63 | 11 | 4 | 0 |
| VAL256 | Schema 3 | 24.148 | 241 | 164 | 61 | 12 | 4 | 0 |
| VAL256 | Heuristic | 24.672 | 233 | 167 | 75 | 15 | 6 | 0 |
| SEEDED128 | v4 | 22.656 | 114 | 66 | 27 | 5 | 2 | 0 |
| SEEDED128 | Schema 3 | 24.477 | 117 | 81 | 37 | 6 | 4 | 0 |
| SEEDED128 | Heuristic | 23.844 | 117 | 73 | 33 | 5 | 4 | 0 |
| REP512 | v4 | 23.109 | 448 | 309 | 111 | 23 | 11 | 0 |
| REP512 | Schema 3 | 24.227 | 473 | 334 | 136 | 26 | 8 | 0 |
| REP512 | Heuristic | 24.352 | 475 | 330 | 142 | 26 | 7 | 0 |
| POOLED896 | v4 | 23.102 | 783 | 533 | 201 | 39 | 17 | 0 |
| POOLED896 | Schema 3 | 24.240 | 831 | 579 | 234 | 44 | 16 | 0 |
| POOLED896 | Heuristic | 24.371 | 825 | 570 | 250 | 46 | 17 | 0 |

## Reproduce v5

```bash
python scripts/build-batch1-challengers.py --profile all_v2_search_v5 --output /tmp/repro-v5
```

Use `all_v2_search_heur_v5` to reproduce the heuristic comparison arm. The builder also retains `all_v2_p1_v4` for reproducing the prior release.

## Historical v4 challenger

Frozen opt-in challenger built from `releases/silent-a10-mecha-knight/challenger/policy.json` via `scripts/build-batch1-challengers.py --profile all_v2_p1_v4`. All prior release bundles remain untouched and bit-for-bit invariant.

### What Changed vs Incumbent (`silent-a10-mecha-knight`)
- **Combat (`encounter_model.json`):**
  - Emergency lethal-survival lookahead (`survival_search: true`, `survival_beam: true`) and Silent combat scorer fixes (`scorer_fixes: true`, `v2_burn: true`, `mechanics`/`persistent`/`potion_effects`/`draw_potions` enabled from Act 1).
  - **`act2_mechanics: true`** (896-seed verified & adversarially reviewed):
    - Exact `guaranteed_damage` target cutoff in survival search (fixing premature cutoff on blocked/Buffer/Slippery/Hard-to-Kill targets across Acts 1–3).
    - `ILLUSION + MINION` (`PARAFRIGHT + THE_OBSCURA`): recognizes leader kill as immediate encounter clear (canceling minion attacks), down-weights wasted non-lethal chip damage on Parafright, and removes fake permanent kill bonus on reviving illusions.
    - `CURL_UP_POWER` (`LOUSE_PROGENITOR`): models post-attack Block trigger after full multi-hit attack resolution (excluding damage potions), prefers heavy attacks before chip, and preserves Curl Up / Block state in beam deduplication.
    - `KAISER_CRAB_BOSS` (`CRUSHER + ROCKET`): re-enables emergency survival lookahead with `SURROUNDED` per-hit back-attack facing flips, survivor auto-turn on ally death, and immediate `CRAB_RAGE_POWER` (+6 Strength at A10 and +99 Block on ally death).
  - **`enemy_mechanics: true` & `card_potion_mechanics: true`** (896-seed verified & adversarially reviewed):
    - `PLOW_POWER` (`CEREMONIAL_BEAST`): exact 160-HP A10 stun & Strength-wipe modeling (via direct damage or Poison tick, including already-below-threshold Plow), with safe non-lethal multi-card Plow stun overrides that avoid wasting potions when already blocked.
    - `VITAL_SPARK_POWER` (`INFESTED_PRISM`): exact per-Skill attack-boost modeling (including Burst/Duplication replays and pre-Weak arithmetic) in both combat scorer and survival search.
    - `SLIPPERY_POWER` (`VANTOM`) & `BUFFER_POWER`: exact Block → Buffer → Slippery resolution order for both attacks and Poison ticks (including Accelerant and Bouncing Flask), Slippery-aware Shiv strip valuation, and preventing wasted Vulnerable/damage potions into high Slippery.
    - `ADAPTABLE_POWER` (`TEST_SUBJECT`): suppresses false encounter clears while retaining phase-knockout attack cancellation; `SLOW_POWER` (`BYGONE_EFFIGY`) non-attack-before-attack ordering.
    - Force-multiplier potions (`FLEX_POTION`, `DUPLICATOR`, `GIGANTIFICATION_POTION`, `SPEED_POTION`) accurately budgeted & prioritized on `Boss`/`Elite`/lethal turns without hallway potion burning, plus exact beam modeling of consumable Gigantification 3×, Flex/Strength Vulnerable/Weak scaling, and `SHADOWMELD` (`2^amount` owner Block gain on cards, Afterimage, and Block potions).
    - Previously unmodeled Silent cards & combat discards: `KNIFE_TRAP` (with per-Shiv Thorns/Reflect/Curl Up/Afterimage), `STRANGLE`, `PANACHE`, `LETHALITY`, `DEBILITATE` (50% Weak), `SHARED_FATE` (mutual Strength loss), `ENLIGHTENMENT`, `NIGHTMARE`, `FINISHER`/`FLECHETTES`/`PRECISE_CUT` ordering, and `combat_selection` unplayable-card / `GRAND_FINALE` discard handling.
  - **`combat_fixes_v4: true` & `selection_fixes_v4: true`** (896-seed verified & 2× adversarially reviewed):
    - Card-generating potions (`ATTACK_POTION`/`SKILL_POTION`/`POWER_POTION`/`COLORLESS_POTION`) and `DISCOVERY` kept free instead of mistakenly discarded; `Tools of the Trade` start-of-turn discard separated from `Well-Laid Plans` end-of-turn retain.
    - Exact Constrict/Strangler direct-kill vs Poison-tick ordering, native enemy hit order with Buffer, `NO_BLOCK` preserving Afterimage/Fortifier/Plating (`PANIC_BUTTON` dynamic no-block + `SHADOWMELD` scaling), sequential replay/Gigantification/Burst/Thorns/corpse-cutoff simulation, fast-path replay recoil/self-damage accounting, unified Energy Potion/Adrenaline delayed-unlock move building (including X-cost/star-cost/Frantic Escape), `PRECISE_CUT` projected hand-size math, and survival-planner priority over Sandpit `escape_action`.
  - Boss overrides: `THE_KIN_BOSS -> isolate`, `SOUL_FYSH_BOSS -> isolate`.
  - Act 2 boss & hallway tactics:
    - `THE_INSATIABLE_BOSS`: `tempo` + `escape="cheap"` Sandpit pacing.
    - `KNOWLEDGE_DEMON_BOSS`: `engine` (`potion=0.30, guard=1.65`) + curse selection.
    - `KAISER_CRAB_BOSS`: `focus="MONSTER.CRUSHER"` + facing tactics + survival search.
    - `act2_hallways`: `HUNTER_KILLER` (`engine + tender + beam`), `ENTOMANCER` (`tempo`), `INFESTED_PRISM` (`isolate`), `MYTE+MYTE` (`engine`, `potion=0.30, guard=1.65`).
- **Routing (`room_model.json`, `late_room_model.json`):** Exact probability-Bellman routing (`survival_weighted: true`) with deck-readiness log-odds, fractional potion accumulation, and Bayes-consistent Unknown-room survival splits.
- **Drafting (`strategy_model.json`):** Unified monotone take-vs-skip drafting (`unified_draft: true`, `deck_size_penalty: 0.0` [Phase 15B 896-seed verified breakthrough, replacing `0.12`], `offset_scale: 0.0`) and **`event_fixes_v4: true`** (exact event option parsing for `heal to full`/`heal all`, `take N damage`, `obtain N gold`, Abyssal Baths max-HP/damage survival ordering, and explicit `Regret` curse avoidance).
- **Shops & Selections (`deck_model.json`):** Optional selection support (`optional_selections: true`), concave retained gold (`gold_curve: true`), potion capacity tracking (`potion_capacity: true`), keeping incumbent removal pricing (`marginal_removal: false`), plus **`shop_fixes_v4: true`** (`THE_GAMBIT`/`PANIC_BUTTON` shop-trap avoidance, one-time empty-belt potion bonus, and `Quest` / `Spoils Map` protection in both shop removals and transforms).

### Live Native A10 Benchmark Summary ([benchmark.json](benchmark.json))

#### 1. Pooled 896-Lobby Verification (`VAL256 + SEEDED128 + REP512`: 1,792 paired games per comparison)

| Comparison (`n = 896`) | A1 Boss | A1 Clear | A2 Boss | A2 Clear (Act 3) | A3 Boss | Avg Floor (`Δ`, `t`) |
|---|---:|---:|---:|---:|---:|---:|
| **`all_v2_p1_v4` vs Incumbent** | 667 → **783** (`p=7.6e-17`) | 315 → **533** (`p=1.6e-32`, +69.2%) | 76 → **201** (`p=9.2e-21`, 2.64×) | 12 → **39** (`p=6.6e-5`, 3.25×) | 5 → **17** (`p=0.0075`, 3.40×) | 18.55 → **23.10** (**+4.55**, `t=+13.63`, `488`W/`155`L) |
| **`all_v2_p1_v4` vs `all_v2_mech_v3`** | 745 → **783** (`p=3.2e-5`) | 440 → **533** (`p=7.8e-11`, +21.1%) | 128 → **201** (`p=9.7e-9`, +57.0%) | 27 → **39** (`p=0.073`, `+25/-13`) | 10 → **17** (`p=0.092`, `+10/-3`) | 21.13 → **23.10** (**+1.97**, `t=+8.01`, `336`W/`154`L) |
| **`all_v2_p1_v4` vs `dsp_000`** | 746 → **783** (`p=2.0e-6`) | 460 → **533** (`p=7.4e-10`, `+108/-35`) | 160 → **201** (`p=0.00014`, `+77/-36`) | 28 → **39** (`p=0.080`, `+22/-11`) | 10 → **17** (`p=0.118`, `+11/-4`) | 21.61 → **23.10** (**+1.50**, `t=+6.90`, `245`W/`93`L) |

#### 2. Cohort Breakdown (`Held-Out 384` and `REP512`)

| Cohort | Comparison | A1 Clear | A2 Boss | A2 Clear | A3 Boss | Avg Floor (`Δ`, `t`) |
|---|---|---:|---:|---:|---:|---:|
| **Held-Out 384** (`VAL256 + SEEDED128`) | vs Incumbent | 143 → **224** (`p=3.4e-11`) | 33 → **90** (`p=4.3e-10`) | 9 → **16** | 4 → **6** | 18.83 → **23.09** (`+4.26`, `t=+8.63`, `214`W/`68`L) |
| **Held-Out 384** (`VAL256 + SEEDED128`) | vs `all_v2_mech_v3` | 193 → **224** (`p=0.0019`, `+63/-32`) | 57 → **90** (`p=0.00014`, `+53/-20`) | 10 → **16** (`+12/-6`) | 3 → **6** (`+5/-2`) | 21.26 → **23.09** (`+1.83`, `t=+4.70`, `136`W/`71`L) |
| **Held-Out 384** (`VAL256 + SEEDED128`) | vs `dsp_000` | 192 → **224** (`p=0.00010`, `+49/-17`) | 72 → **90** (`p=0.011`, `+32/-14`) | 13 → **16** (`+8/-5`) | 3 → **6** (`+5/-2`) | 21.73 → **23.09** (`+1.36`, `t=+3.98`, `104`W/`43`L) |
| **Unseen `REP512`** (`256` default + `256` seeded) | vs Incumbent | 172 → **309** (`p=3.6e-23`) | 43 → **111** (`p=8.2e-12`) | 3 → **23** (`p=3.6e-5`, 7.67×) | 1 → **11** (`p=0.0020`, 11×) | 18.35 → **23.11** (`+4.76`, `t=+10.55`, `274`W/`87`L) |
| **Unseen `REP512`** (`256` default + `256` seeded) | vs `all_v2_mech_v3` | 247 → **309** (`p=3.2e-9`, `+87/-25`) | 71 → **111** (`p=3.0e-5`, `+65/-25`) | 17 → **23** (`+13/-7`) | 7 → **11** (`+5/-1`) | 21.04 → **23.11** (`+2.07`, `t=+6.55`, `200`W/`83`L) |
| **Unseen `REP512`** (`256` default + `256` seeded) | vs `dsp_000` | 268 → **309** (`p=3.1e-6`, `+59/-18`) | 88 → **111** (`p=0.0067`, `+45/-22`) | 15 → **23** (`+14/-6`) | 7 → **11** (`+6/-2`) | 21.51 → **23.11** (`+1.60`, `t=+5.70`, `141`W/`50`L) |

### Reproduce the v4 bundle
```bash
.venv/bin/python scripts/build-batch1-challengers.py \
  --base releases/silent-a10-mecha-knight/challenger/policy.json \
  --profile all_v2_p1_v4 \
  --output /tmp/repro-all-v2-p1-v4
```
