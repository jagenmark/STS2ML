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

## Opt-in and invariance gates

The wrapper runs only at the encounter call site. It maps local actions back
to the native adapter's current stamped choices. Subsequent prompt search
requires a matching public successor from the executed action, including its
known replay queue. Shadow uses the same calculation and emits the champion
choice. The evaluator writes search diagnostics to a separate sidecar.
Bundle switches and config are optional. The config file is hash-validated
when declared in a bundle.

The panel used six `CSV2DEV_DEFAULT_0000`–`0005` lobbies and six
`CSV2DEV_SEEDED_0000`–`0005` lobbies, with their original 0–5 macro indices.
Each lobby ran on the v3 tactics and historical Mecha Knight bundles, for
24 episodes per arm. Every flags-off after receipt and every shadow receipt
matched the pre-edit baseline. Comparisons covered 6,034 decisions, 4,771
combat scorer calls with IEEE-754 score bits, and 6,522 RPC commands and
response digests. They included ordered legal actions, ordered candidates and
bounds for oversized selection prompts, emitted physical evidence, room
results, and canonical run results with elapsed time excluded. The common
`summary.json` SHA-256 is
`61b8d95c53678516d1d744313beda3be056ae22729188be8fcb131cbba61883e`.

The repeat shadow run changed worker count and Python hash seed and also
matched its per-decision search diagnostics with timing excluded. The active
smoke arm completed all 24 episodes. Its champion and historical bundles
changed 33 and 36 decisions respectively. Active results are development
sanity checks. Held evaluation namespaces were never run.

Both bundles loaded their original hash-checked components. A synthetic
version-2 return checkpoint produced from the archived baseline source at
`879e0a9` loaded unchanged with the final source. Its feature-code SHA-256
was `37286ec43b7cc76a963cc5816739e404b63e2a554e2727306422d79906e6735c`.
All release files and all specified legacy provenance modules match the
baseline git tree byte for byte.

### Commands

Run in PowerShell from the worktree. The flags-off baseline was run from
`879e0a9` source with the gate probe placed in this checkout. All output
directories below must be fresh.

```powershell
$base = 'C:/Users/gosee/Documents/codex/2026-10-26/new-chat/STS2ML'
$env:PYTHONPATH = "$PWD/src"
$python = "$base/.venv/cpu/Scripts/python.exe"
$hostPath = "$base/artifacts/a10-conversion-20261121/runtime/src/Sts2Headless/bin/Curriculum/net9.0/Sts2Headless.dll"
$probe = 'docs/combat-search-v2/probes/phase1_gate.py'

& $python $probe --host $hostPath --output artifacts/csv2dev/baseline --workers 6

$env:PYTHONHASHSEED = '19'
& $python $probe --host $hostPath --output artifacts/csv2dev/final-shadow --reference artifacts/csv2dev/baseline --workers 4 --combat-search-v2-shadow
& $python $probe --host $hostPath --output artifacts/csv2dev/final-off --reference artifacts/csv2dev/baseline --workers 6
$env:PYTHONHASHSEED = '71'
& $python $probe --host $hostPath --output artifacts/csv2dev/final-shadow-repeat --reference artifacts/csv2dev/final-shadow --workers 6 --combat-search-v2-shadow
$env:PYTHONHASHSEED = '19'
& $python $probe --host $hostPath --output artifacts/csv2dev/final-act --workers 4 --combat-search-v2

$env:CSV2DEV_HOST = $hostPath
& $python -m pytest -q
```

## Coverage and latency

Coverage means a non-forced combat root returned a certified comparison
without a fallback. Search attempts also include roots where a candidate
failed certification or one stratum could not be compared. Decisions that
search and keep the champion on the merits count as covered. Times are
incremental p50/p95 in milliseconds for native legality enumeration, packing,
and the beam, including fallback dispatch for the all-call column. The
legacy proposal, native execution and offline post-step comparisons are
outside these timings.

| Four-worker arm | Covered / non-forced | Searched | All calls p50 / p95 | Searched p50 / p95 | Child / depth cap hits |
| --- | ---: | ---: | ---: | ---: | ---: |
| v3 shadow | 490 / 2,405 (20.4%) | 521 | 0.307 / 4.771 | 2.029 / 11.238 | 34 / 0 |
| Historical shadow | 491 / 2,141 (22.9%) | 531 | 0.319 / 5.656 | 1.951 / 11.795 | 23 / 0 |
| v3 active | 474 / 2,373 (20.0%) | 507 | 0.306 / 4.869 | 2.059 / 11.540 | 32 / 0 |
| Historical active | 497 / 2,057 (24.2%) | 529 | 0.308 / 5.701 | 1.921 / 10.482 | 18 / 0 |

At six workers, searched p95 on the repeat shadow run was 11.415 ms for v3
and 12.684 ms for the historical bundle. All covered shadow roots were in
Act 1. V3 covered 490/1,854 Act 1 and 0/551 Act 2 roots. The older bundle
covered 491/1,595 Act 1 and 0/546 Act 2 roots. Neither shadow arm reached Act 3.
The largest v3 fallback reasons were Kin leader dependencies (175), Plow
(166), unreconciled prompts (105), Tunneler (95), and Flyconid formations (94).
At searched v3 roots, unresolved draws accounted for 604 leaves. The most
frequent unqualified potion leaves were Colorless (473), Gigantification
(337) and Speed (301).

### Coverage by observed formation

Rows use the ordered living slots visible at each root. A formation can
narrow as enemies die. Counts exclude forced roots. A dash means the bundle
did not visit that signature.

| Act / living formation | v3 | Historical |
| --- | ---: | ---: |
| 1 / ASSASSIN_RUBY_RAIDER + AXE_RUBY_RAIDER | — | 0/2 |
| 1 / ASSASSIN_RUBY_RAIDER + AXE_RUBY_RAIDER + CROSSBOW_RUBY_RAIDER | — | 0/8 |
| 1 / AXE_RUBY_RAIDER | — | 0/4 |
| 1 / BRUTE_RUBY_RAIDER + TRACKER_RUBY_RAIDER | — | 0/10 |
| 1 / BYGONE_EFFIGY | 0/20 | 0/18 |
| 1 / BYRDONIS | 0/15 | 0/20 |
| 1 / CALCIFIED_CULTIST + DAMP_CULTIST | 0/9 | 0/17 |
| 1 / CEREMONIAL_BEAST | 0/141 | 0/118 |
| 1 / CORPSE_SLUG | 0/15 | 0/10 |
| 1 / CORPSE_SLUG + CORPSE_SLUG | 0/25 | 0/26 |
| 1 / CROSSBOW_RUBY_RAIDER + BRUTE_RUBY_RAIDER + TRACKER_RUBY_RAIDER | 0/9 | 0/1 |
| 1 / CROSSBOW_RUBY_RAIDER + TRACKER_RUBY_RAIDER | 0/1 | — |
| 1 / CUBEX_CONSTRUCT | 0/68 | 0/60 |
| 1 / DAMP_CULTIST | 0/10 | 0/19 |
| 1 / EYE_WITH_TEETH + FOGMOG | 0/16 | 0/25 |
| 1 / FLYCONID | 0/17 | 0/8 |
| 1 / FOGMOG | 0/19 | 0/61 |
| 1 / FOSSIL_STALKER | 0/15 | 0/10 |
| 1 / FUZZY_WURM_CRAWLER | 126/167 | 123/159 |
| 1 / GAS_BOMB + LIVING_FOG | 0/1 | 0/6 |
| 1 / INKLET | 0/5 | 0/10 |
| 1 / INKLET + INKLET | 0/4 | 0/10 |
| 1 / INKLET + INKLET + INKLET | 0/28 | 0/26 |
| 1 / KIN_FOLLOWER + KIN_FOLLOWER + KIN_PRIEST | 0/64 | 0/39 |
| 1 / KIN_FOLLOWER + KIN_PRIEST | 0/13 | — |
| 1 / KIN_PRIEST | 0/72 | — |
| 1 / LAGAVULIN_MATRIARCH | 0/32 | 0/30 |
| 1 / LEAF_SLIME_M | 14/25 | 16/31 |
| 1 / LEAF_SLIME_M + FLYCONID | 0/27 | — |
| 1 / LEAF_SLIME_M + LEAF_SLIME_S | 23/28 | 27/30 |
| 1 / LEAF_SLIME_M + SLITHERING_STRANGLER | — | 0/15 |
| 1 / LEAF_SLIME_S | 21/23 | 19/23 |
| 1 / LEAF_SLIME_S + LEAF_SLIME_M | 5/6 | 9/14 |
| 1 / LEAF_SLIME_S + LEAF_SLIME_M + TWIG_SLIME_S | 4/8 | 4/7 |
| 1 / LEAF_SLIME_S + LEAF_SLIME_S + SLITHERING_STRANGLER | 0/14 | — |
| 1 / LEAF_SLIME_S + SLITHERING_STRANGLER | 3/7 | 4/6 |
| 1 / LEAF_SLIME_S + TWIG_SLIME_M | 0/2 | 3/3 |
| 1 / LEAF_SLIME_S + TWIG_SLIME_M + TWIG_SLIME_S | 0/3 | 0/1 |
| 1 / LEAF_SLIME_S + TWIG_SLIME_S + SLITHERING_STRANGLER | 0/2 | 0/3 |
| 1 / LIVING_FOG | 0/19 | 0/12 |
| 1 / MAWLER | 31/76 | 8/44 |
| 1 / NIBBIT | 63/136 | 79/115 |
| 1 / NIBBIT + NIBBIT | 20/121 | 24/92 |
| 1 / PHROG_PARASITE | 0/12 | 0/17 |
| 1 / PUNCH_CONSTRUCT | 0/15 | 0/16 |
| 1 / SEAPUNK | 0/15 | 0/20 |
| 1 / SEWER_CLAM | 0/24 | — |
| 1 / SHRINKER_BEETLE | 84/125 | 72/108 |
| 1 / SHRINKER_BEETLE + FUZZY_WURM_CRAWLER | 27/38 | 19/23 |
| 1 / SKULKING_COLONY | 0/26 | — |
| 1 / SLITHERING_STRANGLER | 14/23 | 5/13 |
| 1 / SLUDGE_SPINNER | 0/26 | 0/42 |
| 1 / SNAPPING_JAXFRUIT | 0/3 | 0/2 |
| 1 / SNAPPING_JAXFRUIT + FLYCONID | 0/52 | 0/21 |
| 1 / SNAPPING_JAXFRUIT + SLITHERING_STRANGLER | — | 7/9 |
| 1 / SOUL_FYSH | 0/45 | — |
| 1 / TOADPOLE | 0/7 | 0/7 |
| 1 / TOADPOLE + TOADPOLE | 0/8 | 0/8 |
| 1 / TRACKER_RUBY_RAIDER | 0/13 | 0/3 |
| 1 / TRACKER_RUBY_RAIDER + AXE_RUBY_RAIDER | 0/10 | 0/1 |
| 1 / TRACKER_RUBY_RAIDER + AXE_RUBY_RAIDER + CROSSBOW_RUBY_RAIDER | 0/4 | 0/2 |
| 1 / TWIG_SLIME_M | 4/8 | 1/12 |
| 1 / TWIG_SLIME_M + FLYCONID | — | 0/12 |
| 1 / TWIG_SLIME_M + LEAF_SLIME_S | 23/23 | 22/24 |
| 1 / TWIG_SLIME_S + LEAF_SLIME_M + LEAF_SLIME_S | 3/6 | 3/6 |
| 1 / TWIG_SLIME_S + TWIG_SLIME_M + LEAF_SLIME_S | 4/9 | 3/9 |
| 1 / VANTOM | 0/29 | 0/34 |
| 1 / VINE_SHAMBLER | 0/29 | 0/37 |
| 1 / WRIGGLER | 2/12 | 1/5 |
| 1 / WRIGGLER + WRIGGLER | 7/8 | 7/17 |
| 1 / WRIGGLER + WRIGGLER + WRIGGLER | 6/11 | 14/22 |
| 1 / WRIGGLER + WRIGGLER + WRIGGLER + WRIGGLER | 6/10 | 21/32 |
| 2 / BOWLBUG_EGG | 0/4 | — |
| 2 / BOWLBUG_NECTAR | 0/7 | 0/3 |
| 2 / BOWLBUG_ROCK | 0/11 | — |
| 2 / BOWLBUG_ROCK + BOWLBUG_EGG | 0/13 | — |
| 2 / BOWLBUG_ROCK + BOWLBUG_NECTAR | 0/15 | 0/13 |
| 2 / BOWLBUG_ROCK + BOWLBUG_SILK + SLUMBERING_BEETLE | — | 0/28 |
| 2 / BOWLBUG_SILK | — | 0/8 |
| 2 / BOWLBUG_SILK + SLUMBERING_BEETLE | — | 0/9 |
| 2 / CHOMPER | 0/22 | — |
| 2 / CHOMPER + CHOMPER | 0/26 | — |
| 2 / DECIMILLIPEDE_SEGMENT_FRONT | 0/1 | — |
| 2 / DECIMILLIPEDE_SEGMENT_FRONT + DECIMILLIPEDE_SEGMENT_BACK | 0/9 | 0/6 |
| 2 / DECIMILLIPEDE_SEGMENT_FRONT + DECIMILLIPEDE_SEGMENT_MIDDLE | — | 0/1 |
| 2 / DECIMILLIPEDE_SEGMENT_FRONT + DECIMILLIPEDE_SEGMENT_MIDDLE + DECIMILLIPEDE_SEGMENT_BACK | 0/40 | 0/20 |
| 2 / EXOSKELETON | 0/5 | 0/12 |
| 2 / EXOSKELETON + EXOSKELETON | 0/4 | 0/17 |
| 2 / EXOSKELETON + EXOSKELETON + EXOSKELETON | 0/15 | 0/20 |
| 2 / EXOSKELETON + EXOSKELETON + EXOSKELETON + EXOSKELETON | — | 0/8 |
| 2 / INFESTED_PRISM | 0/45 | 0/28 |
| 2 / KNOWLEDGE_DEMON | — | 0/58 |
| 2 / LOUSE_PROGENITOR | 0/28 | 0/33 |
| 2 / MYTE | 0/12 | 0/34 |
| 2 / MYTE + MYTE | 0/24 | 0/44 |
| 2 / OVICOPTER | 0/12 | 0/26 |
| 2 / PARAFRIGHT + THE_OBSCURA | — | 0/17 |
| 2 / SPINY_TOAD | 0/54 | 0/23 |
| 2 / THE_INSATIABLE | 0/42 | 0/29 |
| 2 / THE_OBSCURA | — | 0/6 |
| 2 / THIEVING_HOPPER | 0/44 | 0/38 |
| 2 / TOUGH_EGG + OVICOPTER | 0/19 | — |
| 2 / TOUGH_EGG + TOUGH_EGG + OVICOPTER | 0/3 | 0/2 |
| 2 / TOUGH_EGG + TOUGH_EGG + TOUGH_EGG + OVICOPTER | 0/10 | 0/16 |
| 2 / TUNNELER | 0/86 | 0/47 |

## Native differential evidence

The pinned host replayed fixture lines and the stamped active-arm choices.
The oracle compared observable HP, Block, energy, powers, slots, and legal
action order at stable within-turn successors, as well as eligible prompts.
Completed-turn comparisons count the visible board and conserved card
multisets across the reveal. They exclude the specific cards revealed,
new enemy telegraphs and newly resolved costs of unqualified cards. The
recorded class is unresolved where a mid-turn boundary prevents comparison.

Earlier passes caught upgraded Flick-Flack damage, generated Slimed's target,
cost changes on a next-turn Pinpoint reveal, and a Dagger Spray hit ordering
error when the first wave killed the Shrink source. The final sample had
**0/1,129** mismatches in shadow and **0/1,108** in the active arm. These rates
are conditional on the comparable steps. A dash means there were no
comparable observations for that mechanic in that arm.

| Observed mechanic | Shadow mismatches / compared | Active mismatches / compared | Unresolved shadow / active |
| --- | ---: | ---: | ---: |
| AMBERGRIS | — | — | 2 / 2 |
| BLADE_DANCE | 0/5 | 0/2 | 0 / 0 |
| CLOAK_AND_DAGGER | 0/1 | — | 0 / 0 |
| DAGGER_SPRAY | 0/12 | 0/13 | 0 / 0 |
| DAGGER_THROW | 0/2 | 0/1 | 11 / 9 |
| DASH | 0/4 | 0/6 | 0 / 0 |
| DEADLY_POISON | 0/12 | 0/14 | 0 / 0 |
| DEFEND_SILENT | 0/172 | 0/162 | 0 / 0 |
| EXPLOSIVE_AMPOULE | 0/1 | — | 0 / 0 |
| FIRE_POTION | 0/1 | 0/2 | 0 / 0 |
| FLICK_FLACK | 0/1 | 0/2 | 0 / 0 |
| FYSH_OIL | — | — | 2 / 0 |
| NEUTRALIZE | 0/93 | 0/100 | 0 / 0 |
| POISONED_STAB | 0/7 | 0/7 | 0 / 0 |
| POISON_POTION | 0/2 | 0/2 | 0 / 0 |
| POWDERED_DEMISE | — | — | 0 / 1 |
| SHIV | 0/40 | 0/34 | 0 / 0 |
| SLICE | 0/6 | 0/6 | 0 / 0 |
| SLIMED | — | — | 21 / 17 |
| SPEED_POTION | — | — | 1 / 2 |
| STRIKE_SILENT | 0/376 | 0/389 | 0 / 0 |
| SUCKER_PUNCH | 0/1 | 0/1 | 0 / 0 |
| SURVIVOR | 0/64 | 0/60 | 0 / 0 |
| SURVIVOR/discard | 0/64 | 0/60 | 0 / 0 |
| SWIFT_POTION | — | — | 1 / 1 |
| VULNERABLE_POTION | — | 0/2 | 0 / 0 |
| end_turn | 0/265 | 0/245 | 0 / 0 |

### Fixture qualification

The CPU suite finished with **355 passing tests**, including 36 new pure
fixtures and 26 pinned-host differential fixtures. The fixtures include
Energy Potion and a replayed Malaise at resolved X, Malaise against Artifact,
Adrenaline and Sly, three Survivor prompts on a stacked replay, Blade Dance
overflow, and Afterimage and Vital Spark on actual plays. End-turn witnesses
cover Burn and Wither, a native shop-acquired Cloak Clasp, Constrict before
lethal Poison, Buffer across slots and repeated hits, Ethereal and Blur
under Well-Laid Plans, Sandpit lethality and replayed Escape cost. The
potion fixtures cover direct and AoE damage, Block, Strength, Dexterity,
Weak, Vulnerable, Intangible, Poison, energy, and Duplication.

The test that replays the planner's Energy Potion save executes the full
selected line against the host. The draw and discard fixtures assert the
known prefixes of Acrobatics, Prepared, and Calculated Gamble. Native
continuations provide the fresh observation after a reveal. The two-turn
Sandpit fixture supplies the following turn as an explicit public root to
check the value of carrying a cheap Escape.

## Gaps before Phase 2 collection

- Add qualified rules for priority formations. Kin, Plow, Tunneler, and
  Flyconid dominate the v3 exclusions. Act 2 coverage was zero on both
  development arms. Reattach, Waterfall, bowlbug stun, Entomancer Dazed,
  Knowledge Demon prompts and Sloth, Kaiser facing, Vantom, and Axebot
  Stock require more phase or hook evidence. The current panel warrants
  revisiting the Phase 0 coverage threshold before a broad collection.
- Qualify more card modifiers, relic combinations and potion effects.
  The planner stops at an unknown draw and requires a reconciled public
  prefix for multi-action prompts. Examples awaiting witnesses include
  Nightmare copies, Tools of the Trade, Inky Shivs, and next-turn draw
  or temporary cost effects. Random targets and generated choices need
  their own belief or boundary rules.
- Obtain a public pre-reveal witness for the Phase 2 leaf labels, or keep
  the labels on deterministic prefixes with an explicit boundary and
  censoring contract. The current RPC observes the next revealed view.
  Pre-reward terminal HP and Act 3 support also need targeted witnesses
  before those outcomes are used as training targets.
