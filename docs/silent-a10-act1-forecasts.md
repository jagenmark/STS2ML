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

## Next experiment

1. Mark the Giant’s ambiguous zero-damage transition as unknown. Count damage-bearing intents during rule verification and rerun the two fixtures whenever the forecast code changes. Freeze the qualified rules, their source hash and the missing-value encoding before fitting.
2. Collect fresh v4 teacher decisions from standard-lobby challenger runs in both starting biomes. Start with Ceremonial Beast. Train matched advisers with the forecast masked or visible, using the same action choices, teacher returns and data split.
3. Compare the unchanged challenger and both advisers on the same previously unseen boss states, preserving starting health, deck, relics, potions and draw state. Measure boss wins first and HP remaining across all starts second. Then test the selected adviser on fresh, locked full-game seeds with the challenger handling the rest of the run. Use Act 3 entries and full victories for promotion. [Published benchmark](silent-a10-progression.md)
