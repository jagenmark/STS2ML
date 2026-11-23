# Silent A10 combat search v2 — Phase 1

## Runtime and scope

The work started at Phase 0 commit `879e0a9`, above champion commit `08bbd71`.
The Windows CPU interpreter and the pinned v0.111.0 host are from the root
checkout. Host SHA-256 is
`7408d040c28416331279a84e299b52ff35086d80b4cb9711aefd0f91168d8f20`.
The worktree uses ignored junctions for the SDK and upstream game libraries.
All native episodes and fixtures use `CSV2DEV_`.

## Projection and transitions

Schema 1 allows indexed hand and enemy slots, sorted public pile variants,
public intents and powers, potion slots, relic counters, and explicitly
recognized combat prompts. The online kernel accepts immutable values and
local move coordinates. Native action IDs and snapshot stamps stay outside it.
Tests exercise guarded observation mappings, swapped public pile permutations,
duplicate variants and unexplained native playability. Known effects use
pinned base parameters, with draws represented as unresolved prefixes.

The flags-off baseline was captured before source edits. The first recorder
attempt raised the legacy 1,024-combination guard on four oversized prompts.
The corrected recorder captures the ordered candidates and bounds for that
sequential API. Gate commands and matching receipts follow below.

## Ordered resolver

Native fixture runs exposed three ordering details. Afterimage does not
trigger on its own initial power application. With Burst and Duplication
stacked, Survivor opens a separate prompt for each of its three actual plays.
When Blade Dance fills the hand, overflow Shivs enter discard. Tainted is
tracked as an attack delta from each actual Skill and resets after the enemy
turn. Its native power display belongs to the player.

The fixture suite exercised Cloak Clasp through a native shop purchase because
the host's generic relic injection omits the owner. It also checked
Constrict, Burn, Wither, Ethereal, Blur, ordered Buffer consumption, Wriggler
status additions and Sandpit/Escape. Phase bosses with unobserved state have
explicit fallback reasons. The next-intent reveal and ambiguous recalculation
of rounded previews are explicit boundaries.

## Fixed-work search

The frozen search uses width 8, depth 10, a 256-child limit, and a
seven-unit reserve charge per spent potion. It trials each root and compares
completed continuations by survival category and the same HP-equivalent
utility. Beam slots reserve the champion prefix and the no-potion stratum.
Unknown draws and pending unqualified actions lack a survival certificate.
An unresolved champion continuation keeps the champion action.

A repeated local probe hit all 256 attempts. The seven-card, three-enemy
fixture measured 11.15 / 11.68 ms (p50 / p95) for projection and search. The
ten-card, three-enemy stress case measured 11.77 / 13.62 ms in the same
50-call probe. The native panel below measures the full opt-in path.
