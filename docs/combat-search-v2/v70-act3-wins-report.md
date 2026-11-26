# v7.0 Overnight Wave 2 · Balanced 547k Schema 5 + Lean Act 2/3 Human-ML (`83.8 min`)

- **Model:** `combat_value_v5e_bal.npz` (`547,532` leaves, RX 9070 XT `135.1s`, widths `[128, 64]`, test `{'n': 55149, 'win_rate': 0.8959, 'bce': 0.1, 'brier': 0.0309, 'win_acc': 0.9565, 'hp_mae': 0.0568}`, `act3={'n': 3841, 'win_rate': 0.8188, 'bce': 0.2172, 'brier': 0.0674, 'win_acc': 0.9107, 'hp_mae': 0.0793}`, `a3_boss={'n': 319, 'win_rate': 0.1191, 'bce': 0.5803, 'brier': 0.1793, 'win_acc': 0.7712, 'hp_mae': 0.0895}`, `kaiser_2arm={'n': 660, 'win_rate': 0.1394, 'bce': 0.2196, 'brier': 0.0706, 'win_acc': 0.8985, 'hp_mae': 0.0801}`, parity `1.79e-07`).

## Step 2 · Blind `CSV29DEV` (`N = 512` paired lobbies)
| Arm | Mean Floor | A1 Clears | A2 Boss | A3 Entries | A3 Boss1 Clears | Full Wins | Avg A3 Deck | Delta vs v69 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `v69_v5c_bal_pure` | 26.125 | 352/512 | 50/170 | 19 | 1 | **0** | 33.6 | — |
| `v70_v5e_bal_pure` | 26.842 | 372/512 | 58/184 | 21 | 0 | **0** | 32.9 | +0.717 (p=0.0979) |
| `v70_v5e_hyb2` | 26.531 | 373/512 | 42/186 | 9 | 0 | **0** | 29.7 | +0.406 (p=0.1027) |
| `v70_v5e_hyb2_lean` | 26.365 | 373/512 | 39/178 | 10 | 0 | **0** | 28.8 | +0.240 (p=0.3026) |

## Step 3 · Mega Confirmation `CSV30CONF` (`N = 1,024` paired lobbies, winner=`v70_v5e_bal_pure`)
| Arm | Mean Floor | A1 Clears | A2 Boss | A3 Entries | A3 Boss1 Clears | Full Wins | Avg A3 Deck | Delta vs ctrl_v67 (95% CI, p) |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `ctrl_v67` | 25.943 | 685/1024 | 92/355 | 35 | 2 | **0** | 32.6 | — |
| `v69_v5c_bal_pure` | 27.130 | 738/1024 | 118/379 | 52 | 2 | **0** | 33.2 | +1.187 [+0.646, +1.731] (p=0.000486) |
| `v70_v5e_bal_pure` | 27.137 | 738/1024 | 113/398 | 44 | 2 | **0** | 33.1 | +1.193 [+0.632, +1.765] (p=0.000343) |

Head-to-head `v70_v5e_bal_pure` vs `v69_v5c_bal_pure`: `+0.007` floors, 95% CI `[-0.496, +0.508]`, `W/L/T = 252/270/502`, `p = 0.456867`.
