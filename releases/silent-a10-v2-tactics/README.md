# Silent A10 `all_v2_mech` Challenger (`silent-a10-v2-tactics`)

Frozen opt-in challenger built from `releases/silent-a10-mecha-knight/challenger/policy.json` via `scripts/build-batch1-challengers.py --profile all_v2_mech`. All prior release bundles remain untouched and bit-for-bit invariant.

## What Changed vs Incumbent (`silent-a10-mecha-knight`)
- **Combat (`encounter_model.json`):**
  - Emergency lethal-survival lookahead (`survival_search: true`, `survival_beam: true`) and Silent combat scorer fixes (`scorer_fixes: true`, `v2_burn: true`, `mechanics`/`persistent`/`potion_effects`/`draw_potions` enabled from Act 1).
  - **`act2_mechanics: true`** (896-seed verified & adversarially reviewed):
    - Exact `guaranteed_damage` target cutoff in survival search (fixing premature cutoff on blocked/Buffer/Slippery/Hard-to-Kill targets across Acts 1–3).
    - `ILLUSION + MINION` (`PARAFRIGHT + THE_OBSCURA`): recognizes leader kill as immediate encounter clear (canceling minion attacks), down-weights wasted non-lethal chip damage on Parafright, and removes fake permanent kill bonus on reviving illusions.
    - `CURL_UP_POWER` (`LOUSE_PROGENITOR`): models post-attack Block trigger after full multi-hit attack resolution (excluding damage potions), prefers heavy attacks before chip, and preserves Curl Up / Block state in beam deduplication.
    - `KAISER_CRAB_BOSS` (`CRUSHER + ROCKET`): re-enables emergency survival lookahead with `SURROUNDED` per-hit back-attack facing flips, survivor auto-turn on ally death, and immediate `CRAB_RAGE_POWER` (+6 Strength at A10 and +99 Block on ally death).
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
| **`all_v2_mech` vs Incumbent** | 667 → **736** (`p<0.0001`) | 315 → **416** (`p<0.0001`, +32%) | 76 → **125** (`p<0.0001`, +64%) | 12 → **25** (`p=0.0351`, 2.08×) | 5 → **9** (+80%) | 18.55 → **20.78** (**+2.23**, `t=+7.22`, `384`W/`210`L) |
| **`all_v2_mech` vs `all_v2_clean`** | 737 → 736 | 409 → **416** (+7) | 113 → **125** (`p=0.0290`) | 20 → **25** (`+9/-4`) | 4 → **9** (`+6/-1`, 2.25×) | 20.54 → **20.78** (**+0.24**, `t=+2.56`, `67`W/`40`L) |

### 2. Cohort Breakdown (`Held-Out 384` and `REP512`)

| Cohort | Comparison | A1 Clear | A2 Boss | A2 Clear | A3 Boss | Avg Floor (`Δ`, `t`) |
|---|---|---:|---:|---:|---:|---:|
| **Held-Out 384** (`VAL256 + SEEDED128`) | vs Incumbent | 143 → **179** (`p=0.0022`) | 33 → **51** (`p=0.0198`) | 9 → **10** | 4 → 4 | 18.83 → **20.83** (`+2.00`, `t=+4.48`) |
| **Held-Out 384** (`VAL256 + SEEDED128`) | vs `all_v2_tactics` | 173 → **179** (`+9/-3`) | 48 → **51** (`+5/-2`) | 8 → **10** (`+2/-0`) | 4 → 4 | 20.61 → **20.83** (`+0.22`, `t=+1.71`, `24`W/`11`L) |
| **Unseen `REP512`** (`256` default + `256` seeded) | vs Incumbent | 172 → **237** (`p<0.0001`) | 43 → **74** (`p=0.0003`) | 3 → **15** (`p=0.0042`, 5×) | 1 → **5** (`+4/-0`) | 18.35 → **20.74** (`+2.39`, `t=+5.65`) |
| **Unseen `REP512`** (`256` default + `256` seeded) | vs `all_v2_clean` | 236 → **237** | 67 → **74** (`+12/-5`) | 12 → **15** (`+5/-2`) | 2 → **5** (`+4/-1`) | 20.52 → **20.74** (`+0.22`, `t=+1.90`, `34`W/`23`L) |

## Reproduce Frozen Bundle
```bash
.venv/bin/python scripts/build-batch1-challengers.py \
  --base releases/silent-a10-mecha-knight/challenger/policy.json \
  --profile all_v2_mech \
  --output /tmp/repro-all-v2-mech
```
