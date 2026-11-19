# Enemy forecasts in Silent A10

Keep the released challenger as the full-run policy. Give a boss-combat adviser the verified next-turn hit count and base damage as optional inputs, with an explicit indicator for unknown forecasts. The most informative next comparison is whether that adviser can improve the challenger from identical boss openings.

## Full Act 1 comparison

The student experiment held the action scorer, teacher labels, model initialization, optimizer, and minibatch order fixed within each pair. Six input features gave the forecast arm enemy and target-specific information. The control received zeros in those columns. All arms played the same 64 standard-lobby seeds. A separate native run of the released challenger matched **all 64 starting-state digests**. The students shared a route model and macro scorer with each other. The released challenger used its complete published bundle. [Per-seed outcomes and verification counts](evidence/silent-a10-act1-forecasts.json)

| Act 1 clears | Forecast masked | Forecast visible |
|---|---:|---:|
| Student initialization 174 | 3/64 | 6/64 |
| Student initialization 175 | 2/64 | 8/64 |
| Student initialization 176 | 2/64 | 2/64 |

The students gained **4.7 percentage points**, from 7/192 to 16/192. Pairing by the 64 seeds and holding the three trained model pairs fixed gave a 95% bootstrap interval of **+1.0 to +8.9 points**. The released challenger cleared Act 1 on **21/64** (32.8%), entered Act 3 twice, and finished with zero full wins. These seeds are now development evidence.

All 654 training decisions came from 48 Overgrowth runs with the v2 teacher. A forecast applied on 224 decisions. The forecast students reached fewer Act 1 bosses (96 versus 104) and beat more of them (16 versus seven). Ceremonial Beast accounted for six forecast clears in 27 arrivals and two control clears in 29. The two arms arrived with different decks and health, so isolate this fight before attributing the gain to boss play. The solo beetle comparison had already won every fight in both arms and showed no measurable HP gain.

## Two missed DeathBlows

The original qualification used 48 separate seeds and retained 31 rules across 18 enemies. Replaying all checkable forecast transitions recovered 850/851 exact damage predictions without the tracked damage modifiers. The original hit counter searched for `Attack` in the intent name. The native host also exports damage for `DeathBlow`. Counting damage-bearing attack intents corrected the hit result from 1,181/1,181 to **1,179/1,181**. Both misses came from the Waterfall Giant rule that predicted zero hits and zero damage after an attack and buff.

| Game seed | Next round | Forecast damage | Native DeathBlow |
|---|---:|---:|---:|
| `ACT1PATTEST0061` | 9 | 0 | 38 |
| `ACT1PATTEST0030` | 14 | 0 | 53 |

The 38-damage case had a tracked modifier and therefore fell outside the original base-damage accuracy calculation. Both before-and-after public states reproduced on an independently built host. The compressed file contains the initial game specifications, physical actions, action counts and native digests for replay with `NativeSession.restore`. [Two native replay fixtures](evidence/silent-a10-waterfall-forecasts.json.gz)

The static pilot file excludes the three Waterfall Giant rows. Its 28 rules for 17 other enemies matched 1,117/1,117 checkable hit counts and 826/826 clean damage checks on the inspected data. Waterfall Giant now has a separate rule that reads its current public state. [Pilot rule file](evidence/silent-a10-forecast-pilot-rules.json)

## How the Giant's explosion works

On the pinned A10 build, Steam Eruption displays the base damage of the final attack. The first knockout cancels the Giant's current move, shows Stun and replaces its HP bar with infinite HP. On the next player turn it announces one DeathBlow. The Giant explodes at the end of that turn and the fight ends if the player survives. The final intent includes the current damage modifiers. [Versioned game text](https://github.com/ptrlrd/spire-codex/blob/main/data-beta/v0.111.0/eng/powers.json#L2202-L2205)

An armed Giant can still take its ordinary move. At 38 Steam, a surviving Giant finished Ram and showed Siphon next, for zero damage. At the same 38 Steam, the archived Giant had 7 HP and 13 Poison. Ending the turn immediately or knocking it out with Dash led to the same 38-damage DeathBlow. At 53 Steam, the other Giant had 9 HP and 20 Poison. Both the original card sequence and passing immediately produced a 53-damage DeathBlow.

The forecaster exposes the ordinary next move and the damage stored for a knockout. It commits to the eruption when public damage or the upcoming Poison tick guarantees it, and reevaluates after each card. The combat scorers and turn planner remove the canceled attack from current danger and stop rewarding the first knockout as a win. A one-turn Ghost in a Jar can be saved for the DeathBlow. The v5 Monte Carlo teacher uses the same phase in its continuation. New student runs require matching teacher labels and record the forecast inputs and weights they used.

### Native checks

| Archived seed | Restored decision | Winning line | HP after the explosion |
|---|---|---|---:|
| `ACT1PATTEST0061` | Round 5, 46 HP | Triggered at 35 Steam a round earlier. Dash and Defend gave 17 block on the final turn. | 13 |
| `ACT1PATTEST0030` | Round 10, 41 HP | Reached the 53-damage DeathBlow with 26 HP. Leg Sweep weakened it to 39, then Defend brought block to 16. | 3 |

Both paths reach the native card reward from the original deck, HP and draw state. Replaying the same balanced encounter scorer at the same earlier openings on the previous revision also won, with 8 and 3 HP, respectively. The first comparison used turn planning and the second used the direct scorer. These two examples establish that the positions were winnable. [Winning actions and opening digests](evidence/silent-a10-waterfall-survivals.json)

Three controlled encounters also matched all 87 ordinary transitions and announced final hits of 92, 107 and 113. In the last fight the encounter policy held Ghost in a Jar during the wind-up, drank it on the final turn, and lost 1 HP. A replay of the historical students' 31 Giant fights across six seeds produced 295 distinct checkable transitions. Hit counts matched on all 295, including nine DeathBlows, and all 106 checks without tracked damage modifiers matched the predicted damage.

### Same-opening challenger comparison

Those 31 arrivals gave 30 distinct boss openings. Replaying the released challenger's encounter weights from each opening, the scorer at `8522a7d` won 7/30, and the corrected scorer won 8/30. All seven earlier wins were retained. The one extra win had 26 player HP facing a 35-damage DeathBlow. The old policy spent energy on Bubble Bubble and Deadly Poison and blocked once. The corrected policy played two Defends, blocked 10 and survived with 1 HP. The other 22 openings still ended in defeat. These six previously explored seeds measure performance on this development set. [Native openings, action histories and paired ending HP](evidence/silent-a10-waterfall-openings.json.gz)

Run the regression on a machine with the pinned game and a training-enabled host.

```sh
python scripts/verify-waterfall-giant.py --host /path/to/Sts2Headless.dll
```

Pass `--bundle /path/to/challenger/policy.json` to replay all 30 openings with the restored release weights and compare each outcome.

## Next experiment

1. Use the pilot rule file and the Giant's public phase. Count damage-bearing intents during rule verification and rerun the native regression whenever the forecast changes.
2. Collect fresh v5 teacher decisions from standard-lobby challenger runs in both starting biomes. Train matched advisers with the forecast masked or visible, using the same action choices, teacher returns and data split. The Act 1 study accepts the versioned collection via `--teachers`, a restored challenger directory via `--bundle`, and a distinct evaluation seed namespace via `--prefix`. [Study entry point](../scripts/act1-pattern-students.py)
3. Compare the unchanged challenger and both advisers on the same previously unseen boss states, preserving starting health, deck, relics, potions and draw state. Measure boss wins first and HP remaining across all starts second. Then test the selected adviser on fresh, locked full-game seeds with the challenger handling the rest of the run. Use Act 3 entries and full victories for promotion. [Published benchmark](silent-a10-progression.md)
