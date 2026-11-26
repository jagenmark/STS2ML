# v7.0 Overnight Act 3 Victory Push (`133.7 min`)

- **Collection:** `3600` full runs + `2856` Act 3/Kaiser forks (`0`? err=`0`), collection wins=`0+0`.
- **New Act 3 leaves:** `{'total': 139467, 'a1': 83708, 'a2': 42437, 'a3': 13322, 'a3_wins': 10806, 'a3_boss': 943, 'a3_boss_wins': 102, 'a3_floor16_boss2': 93}` -> combined **`547,532`** 420-dim leaves.
- **RX 9070 XT GPU (`130.8s`):** widths `[128, 64]`, test `{'n': 55149, 'win_rate': 0.8959, 'bce': 0.1006, 'brier': 0.031, 'win_acc': 0.957, 'hp_mae': 0.0576}`, `act3={'n': 3841, 'win_rate': 0.8188, 'bce': 0.2194, 'brier': 0.0664, 'win_acc': 0.9143, 'hp_mae': 0.0829}`, `a3_boss={'n': 319, 'win_rate': 0.1191, 'bce': 0.3731, 'brier': 0.1107, 'win_acc': 0.8339, 'hp_mae': 0.0548}`, parity `4.77e-07`.
- **Model:** `C:\Users\gosee\.t3\worktrees\STS2ML\codex-a10-v68-human-ml--fe7a6f56de75ee4e\docs\combat-search-v2\models\combat_value_v5d.npz` (`sha256=786debb674b9ad76adf803850a197a612aa0519295c160a82d686d4dbcbd81fe`).

## Stage D · Held-Out Act 3 Victory Bakeoff (`N = 94` Act 3 openings)
| Arm | Mean A3 Floor | Reached Boss | Boss 1 Clears | Full A10 Wins | Mismatches |
|---|---:|---:|---:|---:|---:|
| `v69_champ` | 10.160 | 0/94 | 0 | **0** | 0 |
| `v70_v5d_ks` | 10.372 | 0/94 | 0 | **0** | 0 |
| `v70_v5d_pure` | 10.372 | 0/94 | 0 | **0** | 0 |
| `v70_v5d_ww35` | 10.351 | 0/94 | 0 | **0** | 0 |
| `v70_v5d_pot5` | 10.351 | 0/94 | 0 | **0** | 0 |
| `v70_v5d_hyb3` | 10.521 | 0/94 | 0 | **0** | 0 |

## Stage E · Blind Full-Run `CSV28DEV` (`N = 512` paired lobbies)
| Arm | Mean Floor | A1 Clears | A2 Boss | A3 Entries | Full Wins | Mismatches | Delta vs ctrl_v67 | Delta vs v69_champ |
|---|---:|---:|---:|---:|---:|---:|---|---|
| `ctrl_v67` | 26.518 | 357/512 | 41/214 | 18 | **0** | 6 | — | — |
| `v69_champ` | 27.184 | 374/512 | 50/215 | 19 | **0** | 3 | +0.666 (p=0.0286) | — |
| `v70_v5d_hyb3` | 26.547 | 363/512 | 55/188 | 17 | **0** | 2 | +0.029 (p=0.3483) | -0.637 (p=0.1372) |
| `v70_v5d_ks` | 26.525 | 357/512 | 58/189 | 21 | **0** | 3 | +0.008 (p=0.4053) | -0.658 (p=0.1327) |
