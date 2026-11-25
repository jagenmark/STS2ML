# Silent A10 v6.8 Overnight Report (Hillclimb + PIMC + Schema 4 GPU)

Total wall-clock runtime: **83.9 min**.

## Stage 1 · 4-Knob Late-Game-Weighted Hillclimb (`TUNE68`)
- Reference `ctrl_v67`: floor `25.521`, A1 `64`, A2 `7/37`, A3 `2`, wins `0`, obj `28.458`
- Best knobs (`hc_7`): `{'a1_offense_boost': 3.0, 'a1_offense_cap': 5.0, 'skip_a1': -0.2, 'skip_late': 0.3}` -> floor `22.323`, A1 `46`, A2 `4/23`, A3 `2`, wins `0`, obj `24.302`

## Stage 2 · Blind Held-Out Verification (`CSV15DEV`)
| Arm | Mean Floor | A1 Clears | A2 Boss | A3 Entries | Wins | Delta vs ctrl_v67 (95% CI) |
|---|---:|---:|---:|---:|---:|---|
| `ctrl_v67` | 25.715 | 172/256 | 17/86 | 9 | 0 | — |
| `ml_tuned_v67` | 22.699 | 136/256 | 10/58 | 2 | 0 | -3.016 [-4.207, -1.828] (p=0.0000) |
| `ml_tuned_pimc` | 23.234 | 139/256 | 14/60 | 4 | 0 | -2.480 [-3.734, -1.203] (p=0.0003) |

## Stage 3 · Schema 4 Combat Value Training (RX 9070 XT)
- Collected `72,835` completed End-Turn leaves across `2500` episodes in `2159.2s`.
- Trained on **AMD Radeon RX 9070 XT** in `24.0s`: selected widths `[64, 32]`, test `{'n': 7015, 'win_rate': 0.9043, 'bce': 0.1368, 'brier': 0.041, 'win_acc': 0.9445, 'hp_mae': 0.0575}`, NumPy parity `1.79e-07`.
- Exported artifact: `C:\Users\gosee\.t3\worktrees\STS2ML\codex-a10-v68-human-ml--fe7a6f56de75ee4e\docs\combat-search-v2\models\combat_value_v4.npz` (`sha256=ce9a7abaf845f5f70595d6933534443a987c7b9dbfe26f1d900c8a3b7023e8bd`).

## Stage 4 · Blind Held-Out Schema 4 A/B (`CSV16DEV`)
| Arm | Mean Floor | A1 Clears | A2 Boss | A3 Entries | Wins | Delta vs ctrl_v67 (95% CI) |
|---|---:|---:|---:|---:|---:|---|
| `ctrl_v67` | 26.016 | 187/256 | 15/79 | 5 | 0 | — |
| `ctrl_schema4` | 26.375 | 184/256 | 18/88 | 4 | 0 | +0.359 [-0.660, +1.379] (p=0.6232) |
| `best_v68_heur` | 24.074 | 156/256 | 15/67 | 8 | 0 | -1.941 [-3.102, -0.777] (p=0.0003) |
| `best_v68_schema4` | 23.855 | 155/256 | 15/58 | 4 | 0 | -2.160 [-3.379, -0.934] (p=0.0000) |

- Direct paired `best_v68_schema4` vs `best_v68_heur`: **-0.219** floors (95% CI `[-1.242, +0.809]`, W/L/T `70/81/105`, `p=0.4159`).

---

# Part 2 · Act-Hybrid + Schema 4 Iteration 2 (`77.4 min`)

## Stage 5 · Blind `CSV17DEV` (Act-Hybrid + Schema 4 v1)
| Arm | Mean Floor | A1 Clears | A2 Boss | A3 Entries | Wins | Delta vs ctrl_v67 (95% CI) |
|---|---:|---:|---:|---:|---:|---|
| `ctrl_v67` | 24.805 | 160/256 | 14/80 | 7 | 0 | — |
| `ctrl_schema4` | 25.105 | 169/256 | 16/86 | 6 | 0 | +0.301 [-0.719, +1.297] (p=0.3112) |
| `hybrid_heur` | 24.270 | 157/256 | 20/74 | 5 | 0 | -0.535 [-1.586, +0.488] (p=1.0000) |
| `hybrid_schema4` | 24.754 | 166/256 | 16/84 | 4 | 0 | -0.051 [-1.117, +1.008] (p=0.4655) |

## Stage 6 · Schema 4 Iteration 2 (AlphaZero Loop, RX 9070 XT)
- Collected `91,780` new leaves (`3000` episodes) -> combined **`164,615`** leaves (`late_weight=2.0`).
- Trained on **AMD Radeon RX 9070 XT** in `41.9s`: widths `[64, 32]`, test `{'n': 16046, 'win_rate': 0.9127, 'bce': 0.1159, 'brier': 0.0342, 'win_acc': 0.9536, 'hp_mae': 0.0567}`, parity `1.79e-07`.
- Exported: `C:\Users\gosee\.t3\worktrees\STS2ML\codex-a10-v68-human-ml--fe7a6f56de75ee4e\docs\combat-search-v2\models\combat_value_v4b.npz` (`sha256=c2f356846b220aed4f9d4c25a41bcab9322eaf81b08348782b5caaef1ef52ca3`).

## Stage 7 · Final Blind `CSV18DEV` (Schema 4 v2)
| Arm | Mean Floor | A1 Clears | A2 Boss | A3 Entries | Wins | Delta vs ctrl_v67 (95% CI) |
|---|---:|---:|---:|---:|---:|---|
| `ctrl_v67` | 25.172 | 171/256 | 12/79 | 6 | 0 | — |
| `ctrl_schema4b` | 26.352 | 189/256 | 18/87 | 10 | 0 | +1.180 [+0.137, +2.230] (p=0.4944) |
| `ctrl_pimc_s4b` | 26.113 | 180/256 | 22/87 | 10 | 0 | +0.941 [-0.094, +1.980] (p=0.4264) |
| `hybrid_s4b` | 26.145 | 185/256 | 20/83 | 10 | 0 | +0.973 [-0.145, +2.117] (p=1.0000) |

---

# Part 3 · Schema 4 Iteration 3 (`79.9 min`, Fixed Act 2/3 Collector + Curriculum Forks)
- New Iter 3 leaves: `{'total': 94875, 'a1': 53199, 'a2': 35871, 'a3': 5805, 'boss': 15684, 'a2_boss': 3313, 'a3_boss': 349}` -> combined **`259,490`** leaves (`late_weight=2.5`).
- Trained on **AMD Radeon RX 9070 XT** in `59.6s`: widths `[128, 64]`, test `{'n': 25445, 'win_rate': 0.9054, 'bce': 0.1159, 'brier': 0.0352, 'win_acc': 0.9516, 'hp_mae': 0.0586}`, parity `2.98e-07`.
- Selected `value_win_weight = 15.0` (`{'15': {'mean_floor': 26.891, 'a1_clears': 45, 'a2_clears': 8, 'a2_entries': 24, 'a3_entries': 5, 'wins': 0, 'obj': 31.8438}, '25': {'mean_floor': 26.688, 'a1_clears': 45, 'a2_clears': 7, 'a2_entries': 23, 'a3_entries': 4, 'wins': 0, 'obj': 31.0}, '45': {'mean_floor': 26.938, 'a1_clears': 45, 'a2_clears': 7, 'a2_entries': 23, 'a3_entries': 4, 'wins': 0, 'obj': 31.25}}`).
- Exported: `C:\Users\gosee\.t3\worktrees\STS2ML\codex-a10-v68-human-ml--fe7a6f56de75ee4e\docs\combat-search-v2\models\combat_value_v4c.npz` (`sha256=048e602429203d445d333ccec58a9543952e01070fce7b7465ef9dfd1e762a7a`).

## Blind `CSV19DEV` (`N = 256` paired lobbies)
| Arm | Mean Floor | A1 Clears | A2 Boss | A3 Entries | Wins | Delta vs ctrl_v67 (95% CI) |
|---|---:|---:|---:|---:|---:|---|
| `ctrl_v67` | 25.359 | 170/256 | 13/88 | 5 | 0 | — |
| `ctrl_s4b` | 26.363 | 184/256 | 19/97 | 6 | 0 | +1.004 [-0.008, +2.031] (p=0.0106) |
| `ctrl_s4c` | 26.434 | 186/256 | 17/99 | 7 | 0 | +1.074 [-0.012, +2.180] (p=0.0429) |
| `hybrid_s4c` | 25.734 | 178/256 | 21/85 | 4 | 0 | +0.375 [-0.723, +1.492] (p=0.8078) |

---

# Part 4 · Schema 5 (`420` features, `122.6 min`, `shop_scale=2.0`)
- Collected Schema 5 dataset: `{'total': 157411, 'a1': 86047, 'a2': 62335, 'a3': 9029, 'boss': 25722, 'a2_boss': 5889, 'a3_boss': 503}` (`3600` full + `3450` A2/A3 forks, err=0).
- Trained on **AMD Radeon RX 9070 XT** in `46.4s`: widths `[128, 64]`, test `{'n': 15375, 'win_rate': 0.8985, 'bce': 0.1139, 'brier': 0.0341, 'win_acc': 0.9541, 'hp_mae': 0.0621}`, slices `{'all': {'n': 15375, 'win_rate': 0.8985, 'bce': 0.1139, 'brier': 0.0341, 'win_acc': 0.9541, 'hp_mae': 0.0621}, 'act1': {'n': 8389, 'win_rate': 0.9247, 'bce': 0.0785, 'brier': 0.0236, 'win_acc': 0.9694, 'hp_mae': 0.0506}, 'act2': {'n': 5994, 'win_rate': 0.8704, 'bce': 0.1493, 'brier': 0.0443, 'win_acc': 0.9399, 'hp_mae': 0.0731}, 'act3': {'n': 992, 'win_rate': 0.8468, 'bce': 0.1988, 'brier': 0.062, 'win_acc': 0.9103, 'hp_mae': 0.1001}, 'boss': {'n': 2497, 'win_rate': 0.5983, 'bce': 0.3216, 'brier': 0.1003, 'win_acc': 0.8682, 'hp_mae': 0.0999}, 'a2_boss': {'n': 574, 'win_rate': 0.3868, 'bce': 0.3909, 'brier': 0.1242, 'win_acc': 0.8293, 'hp_mae': 0.1222}}`, parity `1.19e-07`.
- Selected `value_win_weight = 25.0` (`{'15': {'mean_floor': 26.609, 'a1_clears': 45, 'a2_clears': 6, 'a2_entries': 26, 'a3_entries': 2, 'wins': 0, 'obj': 30.1406}, '25': {'mean_floor': 27.266, 'a1_clears': 46, 'a2_clears': 7, 'a2_entries': 27, 'a3_entries': 3, 'wins': 0, 'obj': 31.4375}, '40': {'mean_floor': 26.75, 'a1_clears': 44, 'a2_clears': 7, 'a2_entries': 28, 'a3_entries': 2, 'wins': 0, 'obj': 30.5938}}`).
- Exported: `C:\Users\gosee\.t3\worktrees\STS2ML\codex-a10-v68-human-ml--fe7a6f56de75ee4e\docs\combat-search-v2\models\combat_value_v5.npz` (`sha256=7959317e3de9c6b185e85b33e8736a8eb946d49dc2f4eb625f447ea5c7307b35`).

## Blind `CSV21DEV` (`N = 256` paired lobbies)
| Arm | Mean Floor | A1 Clears | A2 Boss | A3 Entries | Wins | Delta vs ctrl_v67 (95% CI) | Delta vs ctrl_s4c |
|---|---:|---:|---:|---:|---:|---|---|
| `ctrl_v67` | 25.988 | 182/256 | 18/85 | 5 | 0 | — | — |
| `ctrl_s4c` | 26.254 | 184/256 | 16/91 | 5 | 0 | +0.266 [-0.719, +1.262] (p=0.8624) | — |
| `ctrl_s5` | 26.586 | 187/256 | 22/89 | 9 | 0 | +0.598 [-0.414, +1.629] (p=0.8682) | +0.332 (p=0.4370) |
| `hyb_s5` | 26.418 | 183/256 | 22/87 | 7 | 0 | +0.430 [-0.559, +1.426] (p=0.7433) | +0.164 (p=1.0000) |

---

# Part 5 · Schema 5 Iteration 2 (`310,062` combined 420-dim leaves, `117.5 min`)
- New Iter 2 leaves: `{'total': 152651, 'a1': 85954, 'a2': 58590, 'a3': 8107, 'boss': 24888, 'a2_boss': 5380, 'a3_boss': 469}` (`3600` full + `3285` A2/A3 forks, err=0).
- Trained on **AMD Radeon RX 9070 XT** in `71.4s`: widths `[128, 64]`, test `{'n': 30463, 'win_rate': 0.8939, 'bce': 0.1115, 'brier': 0.0337, 'win_acc': 0.9536, 'hp_mae': 0.059}`, slices `{'all': {'n': 30463, 'win_rate': 0.8939, 'bce': 0.1115, 'brier': 0.0337, 'win_acc': 0.9536, 'hp_mae': 0.059}, 'act1': {'n': 17079, 'win_rate': 0.9269, 'bce': 0.074, 'brier': 0.0227, 'win_acc': 0.9672, 'hp_mae': 0.05}, 'act2': {'n': 11624, 'win_rate': 0.8576, 'bce': 0.1311, 'brier': 0.0407, 'win_acc': 0.9427, 'hp_mae': 0.0681}, 'act3': {'n': 1760, 'win_rate': 0.8136, 'bce': 0.3461, 'brier': 0.094, 'win_acc': 0.8938, 'hp_mae': 0.0948}, 'boss': {'n': 4991, 'win_rate': 0.6031, 'bce': 0.312, 'brier': 0.0974, 'win_acc': 0.8587, 'hp_mae': 0.0986}, 'a2_boss': {'n': 1083, 'win_rate': 0.3527, 'bce': 0.3378, 'brier': 0.1085, 'win_acc': 0.8421, 'hp_mae': 0.1137}}`, parity `1.79e-07`.
- Selected `value_win_weight = 15.0` (`{'15': {'mean_floor': 25.953, 'a1_clears': 47, 'a2_clears': 8, 'a2_entries': 18, 'a3_entries': 2, 'wins': 0, 'obj': 29.3594}, '25': {'mean_floor': 25.797, 'a1_clears': 46, 'a2_clears': 7, 'a2_entries': 17, 'a3_entries': 2, 'wins': 0, 'obj': 28.9531}, '40': {'mean_floor': 26.094, 'a1_clears': 47, 'a2_clears': 7, 'a2_entries': 18, 'a3_entries': 2, 'wins': 0, 'obj': 29.3125}}`).
- Exported: `C:\Users\gosee\.t3\worktrees\STS2ML\codex-a10-v68-human-ml--fe7a6f56de75ee4e\docs\combat-search-v2\models\combat_value_v5b.npz` (`sha256=b5a184f413b51ecf4482438e6e326d994be1cfb36a3ec9ed7ebb2649e24958df`).

## Blind `CSV23DEV` (`N = 256` paired lobbies)
| Arm | Mean Floor | A1 Clears | A2 Boss | A3 Entries | Wins | Delta vs ctrl_v67 (95% CI) | Delta vs s5_it1 |
|---|---:|---:|---:|---:|---:|---|---|
| `ctrl_v67` | 26.426 | 181/256 | 21/96 | 8 | 0 | — | — |
| `s5_it1` | 26.258 | 175/256 | 25/88 | 11 | 0 | -0.168 [-1.340, +1.012] (p=0.8699) | — |
| `s5_it2` | 26.910 | 185/256 | 24/102 | 11 | 0 | +0.484 [-0.586, +1.547] (p=0.0140) | +0.652 (p=0.3122) |
| `s5_it2_pimc` | 27.203 | 183/256 | 32/105 | 13 | 0 | +0.777 [-0.332, +1.883] (p=0.0532) | +0.945 (p=0.1651) |

---

# Part 6 · High-Power Confirmation `CSV24CONF` (`N = 768` paired lobbies, `22.93 min`)
- Model: `combat_value_v5b.npz` (`sha256=b5a184f413b51ecf4482438e6e326d994be1cfb36a3ec9ed7ebb2649e24958df`), `draw_pimc_v68=True`, `value_v68=True`, `value_win_weight=15.0`.

| Arm | Mean Floor | A1 Clears | A2 Boss | A3 Entries | Wins | Mismatches |
|---|---:|---:|---:|---:|---:|---:|
| `ctrl_v67` | 25.297 | 507/768 | 50/250 | 19 | 0 | 2 |
| `v68_s5b_pimc` | **26.319** | **532/768** | **71/268** | **25** | **0** | 5 |

**Paired delta (`v68_s5b_pimc` vs `ctrl_v67`):** `+1.022` floors, 95% CI `[+0.350, +1.694]`, `W/L/T = 256/187/325`, sign `p = 0.001210`.

---

# Part 7 · Schema 5 Iteration 3 Kaiser Crab Focus (`408,065` leaves, `75.0 min`)
- Fixed 2-arm Kaiser `facing` tracking: new Iter 3 stats `{'total': 98003, 'a1': 56372, 'a2': 37494, 'a3': 4137, 'boss': 19816, 'a2_boss': 6412, 'a3_boss': 284, 'kaiser_all': 4548, 'kaiser_2arm': 4169, 'kaiser_2arm_wins': 451}` (`2400` full + `1578` forks, err=0).
- Trained on **AMD Radeon RX 9070 XT** in `94.8s` (`kaiser_weight=4.0`): widths `[128, 64]`, test `{'n': 41145, 'win_rate': 0.8929, 'bce': 0.1117, 'brier': 0.0343, 'win_acc': 0.9522, 'hp_mae': 0.059}`, kaiser_2arm `{'n': 457, 'win_rate': 0.1838, 'bce': 0.2613, 'brier': 0.0843, 'win_acc': 0.8775, 'hp_mae': 0.0928}`, parity `2.09e-07`.
- Exported: `C:\Users\gosee\.t3\worktrees\STS2ML\codex-a10-v68-human-ml--fe7a6f56de75ee4e\docs\combat-search-v2\models\combat_value_v5c.npz` (`sha256=eb5a2f13731bf8758339f6cbf746bdf281c81ba3da8cd152b6d95594f329bdaa`).

## Blind `CSV25DEV` (`N = 256` paired lobbies)
| Arm | Mean Floor | A1 Clears | A2 Boss | A3 Entries | Wins | Delta vs ctrl_v67 (95% CI) | Delta vs v68_v5b |
|---|---:|---:|---:|---:|---:|---|---|
| `ctrl_v67` | 24.785 | 162/256 | 18/80 | 8 | 0 | — | — |
| `v68_v5b` | 26.551 | 180/256 | 30/100 | 9 | 0 | +1.766 [+0.672, +2.891] (p=0.0416) | — |
| `v69_v5c_kscale` | 26.383 | 181/256 | 26/95 | 7 | 0 | +1.598 [+0.344, +2.883] (p=0.0750) | -0.168 (p=0.9312) |
| `v69_v5c_pure` | 26.387 | 181/256 | 26/95 | 6 | 0 | +1.602 [+0.387, +2.848] (p=0.0861) | -0.164 (p=0.8624) |
