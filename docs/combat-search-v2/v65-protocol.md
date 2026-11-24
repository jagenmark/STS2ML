# Silent A10 v6.5 development protocol

The 384 CSV10DEV lobbies pair three policies on each natural start, with 192 default and 192 seeded act lists. The registered lock SHA-256 is `6b30bfddc5f1a9883b3cfbd63351b8c55d3c23de6217d84e480cf46caf20164f`. Name and xxHash64 comparisons against 69,835 historical and reserved names found zero collisions. The collector requires a clean commit, the v0.111.0 binary and game-library hashes, 12 workers, and one OpenBLAS and OpenMP thread each. Each triple rotates arm order. Reserved panels are excluded.

Control is the Fan-fixed Arm 4 + Kaiser v6.3 profile from 37afd57. A retains the Control reward strategy, merchant and bundle pricing with a targeted eligibility adjustment and diminishing uplift for Afterimage and Well-Laid Plans. B routes all three acquisition prompts through the same role-sensitive raw grade. Its size coefficient is zero. Both apply the solo off-class gates. Forced choices select among legal alternatives. Public state and the pinned static catalog supply all draft inputs.

The primary comparison uses paired global floor, 17 × (act − 1) + floor. Report mode-stratified 50,000-sample paired bootstrap intervals, exact two-sided sign tests excluding ties, all three pairwise contrasts, boss entries and clears, wins, deck size, optional reward skips, physical combat latency and native matches/mismatches/unresolved. Compare offer-conditioned pick rates and interpret differences from CSV9DEV descriptively across distinct cohorts. The primary recommendation considers paired progression together with Act 1 survival, late conversion and the zero-mismatch requirement.

## Synthetic scores before CSV10DEV

Columns use three max energy, unupgraded offers, and skip = 0. The Act 1 deck has five Strikes, five Defends, Neutralize, Survivor and Ascender’s Bane. Act 2 adds Dash, Predator, Dagger Spray, Poisoned Stab, Skewer, Acrobatics and Backflip. Act 3 also adds Calculated Gamble, Acrobatics, Backflip, Dagger Throw, Adrenaline, Bouncing Flask and Footwork. “Blocked” denotes the hard acquisition score of −1,000,000.

| Card | Act 1 floor 2 | Act 2 floor 8 | Act 3 floor 10 |
| --- | ---: | ---: | ---: |
| Predator | 16.36 | -0.48 | -4.01 |
| Dash | 9.00 | -1.73 | -0.33 |
| Dagger Spray | 17.14 | -1.02 | -1.28 |
| Poisoned Stab | 10.50 | 1.23 | 1.04 |
| Skewer | 11.90 | -3.53 | -3.77 |
| Piercing Wail | 2.19 | 5.20 | 3.53 |
| Calculated Gamble | 5.62 | 3.77 | -7.23 |
| Acrobatics | 6.60 | 1.92 | -7.85 |
| Expose | 4.05 | 7.46 | 5.70 |
| Backflip | 5.00 | 1.74 | -2.87 |
| Afterimage | 11.00 | 19.00 | 11.00 |
| Well-Laid Plans | 7.83 | 7.13 | 7.05 |
| Footwork | 8.46 | 15.60 | 5.07 |
| Accelerant | -27.00 | 22.80 | 46.00 |
| Blur | 2.35 | 10.20 | 5.13 |
| Dodge and Roll | 0.86 | 1.18 | 5.53 |
| Pact's End | -30.00 | -30.00 | 11.46 |
| Corrosive Wave | -14.00 | -3.52 | 10.37 |
| Tools of the Trade | 7.80 | 6.77 | 4.05 |
| Bury | Blocked | Blocked | Blocked |
| Friendship | -7.50 | -7.50 | -7.50 |
| Defragment | Blocked | Blocked | Blocked |
| Zap | 0.00 | 0.00 | 0.00 |
| Ball Lightning | 15.75 | 5.06 | 4.83 |
| Reave | 13.50 | -1.78 | -2.10 |
| Reap | 17.64 | -0.89 | -1.38 |
| High Five | Blocked | Blocked | Blocked |
| Neurosurge | Blocked | Blocked | Blocked |
| Shroud | Blocked | Blocked | Blocked |
| Bulwark | Blocked | Blocked | Blocked |
| Seven Stars | Blocked | Blocked | Blocked |

| Corrosive Wave hand | N including Wave | Affordable sources | P(hit) | E[draw] | Raw score |
| --- | ---: | ---: | ---: | ---: | ---: |
| one source | 20 | 1 | 0.2105 | 0.6316 | -7.60 |
| engine | 28 | 7 | 0.7239 | 2.5185 | 10.37 |

The hand model conditions on holding Wave. It counts direct draw sources individually playable after spending one energy on Wave. It excludes delayed draws and triggered powers. The expectation describes cards drawn by eligible handmates before any competition between multiple paid draw plays. Low hit probability incurs a dead-hand penalty and a strictly negative grade below 0.58.

[Cohort lock](csv10dev-lock.json)
