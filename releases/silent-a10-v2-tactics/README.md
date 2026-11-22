# Silent A10 `all_v2_tactics` Challenger

Frozen opt-in challenger built from `releases/silent-a10-mecha-knight/challenger/policy.json` via `scripts/build-batch1-challengers.py --profile all_v2_tactics`. All prior release bundles remain untouched and bit-for-bit invariant.

## What Changed vs Incumbent (`silent-a10-mecha-knight`)
- **Combat (`encounter_model.json`):**
  - Emergency lethal-survival lookahead (`survival_search: true`, `survival_beam: true`) and Silent combat scorer fixes (`scorer_fixes: true`, `v2_burn: true`, `mechanics`/`persistent`/`potion_effects`/`draw_potions` enabled from Act 1).
  - Boss overrides: `THE_KIN_BOSS -> isolate`, `SOUL_FYSH_BOSS -> isolate`.
  - Act 2 boss & hallway tactics (selected on `REP512` counterfactual openings with `+9 / -0` zero-loss wins, validated out-of-sample on 384 disjoint lobbies):
    - `THE_INSATIABLE_BOSS`: `tempo` + `escape="cheap"` Sandpit pacing.
    - `KNOWLEDGE_DEMON_BOSS`: `engine` (`potion=0.30, guard=1.65`) + curse selection.
    - `KAISER_CRAB_BOSS`: `focus="MONSTER.CRUSHER"` + facing tactics.
    - `act2_hallways`: `HUNTER_KILLER` (`engine + tender + beam`), `ENTOMANCER` (`tempo`), `INFESTED_PRISM` (`isolate`), `MYTE+MYTE` (`engine`, `potion=0.30, guard=1.65`).
- **Routing (`room_model.json`, `late_room_model.json`):** Exact probability-Bellman routing (`survival_weighted: true`) with deck-readiness log-odds, fractional potion accumulation, and Bayes-consistent Unknown-room survival splits.
- **Drafting (`strategy_model.json`):** Unified monotone take-vs-skip drafting (`unified_draft: true`, `deck_size_penalty: 0.12`, `offset_scale: 0.0`).
- **Shops & Selections (`deck_model.json`):** Optional selection support (`optional_selections: true`), concave retained gold (`gold_curve: true`), and potion capacity tracking (`potion_capacity: true`), keeping incumbent removal pricing (`marginal_removal: false`, after an 8-way live trace audit isolated `marginal_removal` as the cause of 6/6 lost Act 2 clears in shop ablations).

## Live Native A10 Benchmark Summary ([benchmark.json](benchmark.json))

### 1. Unseen 512-Lobby Replication (`REP512`: 256 `default` + 256 `seeded`, `all_v2_clean` vs Incumbent)

| Metric | Incumbent | `all_v2_clean` | Discordant (`+` / `-`) | Exact `p` / `t` |
|---|---:|---:|---:|---:|
| Act 1 Boss entry | 378 / 512 (73.8%) | **420 / 512 (82.0%)** | +80 / -38 | `p = 0.0001` |
| Act 1 Clear | 172 / 512 (33.6%) | **236 / 512 (46.1%)** | +120 / -56 | `p < 0.0001` |
| Act 2 Boss entry | 43 / 512 (8.4%) | **67 / 512 (13.1%)** | +47 / -23 | `p = 0.0056` |
| Act 2 Clear (Act 3 entry) | 3 / 512 (0.6%) | **12 / 512 (2.3%)** | +12 / -3 | `p = 0.0352` |
| Avg Floor Reached | 18.35 | **20.52 (+2.17)** | 211 W / 127 L | `t = +5.22` |

### 2. Disjoint Held-Out 384-Lobby Validation (`VAL256 + SEEDED128`: `all_v2_tactics` vs Incumbent & `all_v2_clean`)

| Comparison (`n = 384`) | A1 Boss | A1 Clear | A2 Boss | A2 Clear | A3 Boss | Avg Floor (`Δ`, `t`) |
|---|---:|---:|---:|---:|---:|---:|
| **`all_v2_tactics` vs Incumbent** | 289 → **317** (`p=0.0006`) | 143 → **173** (`p=0.0113`) | 33 → **48** (`p=0.0627`) | 9 → 8 | 4 → 4 | 18.83 → **20.61** (`+1.78`, `t=+3.98`) |
| **`all_v2_tactics` vs `all_v2_clean`** | 317 → 317 (`+0/-0`) | 173 → 173 (`+0/-0`) | 46 → **48** (`+2/-0`) | 8 → 8 (`+2/-2`) | 2 → **4** (`+2/-0`) | 20.57 → **20.61** (`+0.04`) |

## Reproduce Frozen Bundle
```bash
.venv/bin/python scripts/build-batch1-challengers.py \
  --base releases/silent-a10-mecha-knight/challenger/policy.json \
  --profile all_v2_tactics \
  --output /tmp/repro-all-v2-tactics
```
