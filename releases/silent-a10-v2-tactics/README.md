# Silent A10 `all_v2_mech_v3` Challenger (`silent-a10-v2-tactics`)

Frozen opt-in challenger built from `releases/silent-a10-mecha-knight/challenger/policy.json` via `scripts/build-batch1-challengers.py --profile all_v2_mech_v3`. All prior release bundles remain untouched and bit-for-bit invariant.

## What Changed vs Incumbent (`silent-a10-mecha-knight`)
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
  - Boss overrides: `THE_KIN_BOSS -> isolate`, `SOUL_FYSH_BOSS -> isolate`.
  - Act 2 boss & hallway tactics:
    - `THE_INSATIABLE_BOSS`: `tempo` + `escape="cheap"` Sandpit pacing.
    - `KNOWLEDGE_DEMON_BOSS`: `engine` (`potion=0.30, guard=1.65`) + curse selection.
    - `KAISER_CRAB_BOSS`: `focus="MONSTER.CRUSHER"` + facing tactics + survival search.
    - `act2_hallways`: `HUNTER_KILLER` (`engine + tender + beam`), `ENTOMANCER` (`tempo`), `INFESTED_PRISM` (`isolate`), `MYTE+MYTE` (`engine`, `potion=0.30, guard=1.65`).
- **Routing (`room_model.json`, `late_room_model.json`):** Exact probability-Bellman routing (`survival_weighted: true`) with deck-readiness log-odds, fractional potion accumulation, and Bayes-consistent Unknown-room survival splits.
- **Drafting (`strategy_model.json`):** Unified monotone take-vs-skip drafting (`unified_draft: true`, `deck_size_penalty: 0.12`, `offset_scale: 0.0`).
- **Shops & Selections (`deck_model.json`):** Optional selection support (`optional_selections: true`), concave retained gold (`gold_curve: true`), and potion capacity tracking (`potion_capacity: true`), keeping incumbent removal pricing (`marginal_removal: false`).

## Live Native A10 Benchmark Summary ([benchmark.json](benchmark.json))

### 1. Pooled 896-Lobby Verification (`VAL256 + SEEDED128 + REP512`: 1,792 paired games)

| Comparison (`n = 896`) | A1 Boss | A1 Clear | A2 Boss | A2 Clear (Act 3) | A3 Boss | Avg Floor (`Δ`, `t`) |
|---|---:|---:|---:|---:|---:|---:|
| **`all_v2_mech_v3` vs Incumbent** | 667 → **745** (`p=6.8e-9`) | 315 → **440** (`p=1.0e-12`, +39.7%) | 76 → **128** (`p=3.4e-6`, +68.4%) | 12 → **27** (`p=0.0167`, 2.25×) | 5 → **10** (2.0×) | 18.55 → **21.13** (**+2.58**, `t=+8.51`, `402`W/`202`L) |
| **`all_v2_mech_v3` vs `all_v2_mech`** | 736 → **745** (`p=0.0225`) | 416 → **440** (`p=0.0012`, `+38/-14`) | 125 → **128** (`+24/-21`) | 25 → **27** (`+8/-6`) | 9 → **10** (`+4/-3`) | 20.78 → **21.13** (**+0.36**, `t=+2.86`, `88`W/`51`L) |

### 2. Cohort Breakdown (`Held-Out 384` and `REP512`)

| Cohort | Comparison | A1 Clear | A2 Boss | A2 Clear | A3 Boss | Avg Floor (`Δ`, `t`) |
|---|---|---:|---:|---:|---:|---:|
| **Held-Out 384** (`VAL256 + SEEDED128`) | vs Incumbent | 143 → **193** (`p=1.4e-5`) | 33 → **57** (`p=0.0018`) | 9 → **10** | 4 → 3 | 18.83 → **21.26** (`+2.44`, `t=+5.64`) |
| **Held-Out 384** (`VAL256 + SEEDED128`) | vs `all_v2_mech` | 179 → **193** (`p=0.0094`, `+20/-6`) | 51 → **57** (`+12/-6`) | 10 → 10 | 4 → 3 | 20.83 → **21.26** (`+0.43`, `t=+2.28`, `46`W/`22`L) |
| **Unseen `REP512`** (`256` default + `256` seeded) | vs Incumbent | 172 → **247** (`p=2.4e-8`) | 43 → **71** (`p=0.0009`) | 3 → **17** (`p=0.0013`, 5.67×) | 1 → **7** (`p=0.031`, 7×) | 18.35 → **21.04** (`+2.69`, `t=+6.39`) |
| **Unseen `REP512`** (`256` default + `256` seeded) | vs `all_v2_mech` | 237 → **247** (`p=0.0755`, `+18/-8`) | 74 → 71 | 15 → **17** (`+5/-3`) | 5 → **7** (`+3/-1`) | 20.74 → **21.04** (`+0.30`, `t=+1.81`, `42`W/`29`L) |

## Reproduce Frozen Bundle
```bash
.venv/bin/python scripts/build-batch1-challengers.py \
  --base releases/silent-a10-mecha-knight/challenger/policy.json \
  --profile all_v2_mech_v3 \
  --output /tmp/repro-all-v2-mech-v3
```
