# Human data and observation boundaries

## What this milestone imports

The implemented adapter imports **solo, standard, unmodified card-reward decisions
from Spire Codex replay journals, recorder versions 5–7**. It does not reconstruct
complete game state from end-of-run summaries. All resulting observations carry
`state_quality: partial_replay`.

The first available offer is snapshotted when its `decision` record appears. An
explicit, matching `acquire` or `outcome` event supplies the action label later.
The selected card therefore cannot enter its own pre-choice deck. Gold, potions,
and other rewards collected between the initial offer and the eventual selection
may be absent from this snapshot; this is a documented limitation of the first
adapter. It learns the human selection from the initially observed offer.
Metadata explicitly records `observation_timing: offer_created` and
`fields_changed_before_resolution`. A caller can use
`import_replay(path, strict_timing=True)` to exclude examples with observed
intervening HP, gold, deck, relic or potion changes. The default retains these
examples as a partial-observation baseline. Metadata is not a model feature.
The adapter deliberately does not replace the snapshot with the state just
before an acquisition hook: the game can emit consequences of choosing a card
before that hook, so doing so could leak the chosen action.

Canonical examples contain:

- Observation: character, ascension, act/floor, HP/max HP/gold when known, deck
  card identities and recorded upgrade levels, relics, potions, and quality.
- Candidates: each selectable card and, only when explicitly legal, skip.
- Targets: the recorded human action; a win/loss target only for a complete
  journal whose final `end` says `victory` or `death` and does not say
  `is_game_over: false`.
- Metadata: source/game/recorder version, run ID and a hashed seed group for
  reproducibility and leakage-resistant splitting. These are not policy inputs.

Missing numeric observations and unrecorded upgrade levels are `null`, not zero.
The model's presence indicators distinguish unknown state from actual zero. A
missing terminal record or `left_run` is not converted to a loss. Missing a
choice is not converted to skip.

## Why the large run export is not enough by itself

Spire Codex's documented bulk export is a valuable raw dataset. However, its raw
`.run` objects are summaries. `players[].deck` is the **final deck**, with
`floor_added_to_deck` and the final `current_upgrade_level`.
`map_point_history[act][floor].player_stats` contains floor aggregates, including
`card_choices`, `cards_removed`, `upgraded_cards`, HP/gold and relic choices.
These arrays do not by themselves establish every within-floor operation's
ordering or delimit every separate offer.

Filtering the final deck by acquisition floor would still lose subsequently
removed cards and leak later upgrades. Using final HP, final relics, future
encounters, or the final deck as decision-time inputs would make misleading
offline scores. Consequently this project includes a bounded bulk downloader,
but deliberately does not turn that data into full-state imitation examples.
Aggregate pick/win rates can later supply explicitly documented priors or
baselines; they are not optimal-action labels.

## Public endpoints

Base URL: <https://spire-codex.com>.

| Endpoint | Purpose |
| --- | --- |
| `/api/exports/runs/manifest` | Dump timestamp, counts, byte lengths, SHA-256 and per-version exports |
| `/api/exports/runs?limit=1000` | A bounded page of raw `.run` objects, gzipped JSONL |
| `/api/replays?character=IRONCLAD&ascension=10&players=single&game_mode=standard` | Discover actual public replay hashes |
| `/api/runs/{run_hash}/replay` | A public replay journal; gzip bytes with `Content-Encoding: gzip` |

`list_replays()` returns the service's listing. Its `replay_url` field is a
**website URL**; `download_replay()` constructs the documented API path instead.
Do not enumerate guessed run hashes.

```python
from sts2rl.adapters.spire_codex import (
    download_replay, import_replay, list_replays,
)

listing = list_replays(character="IRONCLAD", ascension=10, limit=10)
run_id = listing["runs"][0]["run_hash"]
download_replay(run_id, "data/raw/replay.jsonl.gz")
examples, report = import_replay("data/raw/replay.jsonl.gz", run_id=run_id)
print(report)  # Inspect exclusions and accepted decisions before training.
```

The API may have no matching replays. Check `listing["runs"]` before selecting a
row in production. Live dataset sizes are not assumed from earlier discussions.

### Bulk pagination

`download_export_page()` downloads one bounded page and returns `next_cursor`
from **`X-Next-Cursor`**, plus its SHA-256 and size. Pass that opaque cursor to
the next call, retaining the same `start`, `end` and `version`. Stop only when the
header is absent: missing/bad server records can produce a short page that still
has a continuation. Date bounds refer to submission time, with `[start, end)`
semantics, not the run's play time.

The documented export budget is 120 credits/hour; bounded pages cost one credit,
unbounded pulls 60. Space sustained page downloads approximately 30 seconds
apart. Limits can change at runtime: consult `/api/rate-limits` and the live
developer page before collecting. At project setup the live developer page
listed a general anonymous limit of 15 requests/minute. The pinned replay route
also has a 120/minute endpoint cap; that does not override a lower general limit.
Use at least 4.1 seconds between replay requests and respect whichever limit is
lower. The helpers expose `RateLimitedError.retry_after` on HTTP 429; they do
not automatically pace or retry requests. The collection CLI supplies pacing.
Defaults are bounded and downloads are atomic,
do not overwrite an existing destination, and clean failed temporary files.

The response bytes are retained exactly, including gzip. Import detects gzip by
its magic bytes, so a server's filename or content type cannot silently turn a
compressed journal into plain-text input. Imports cap both compressed and
expanded input at 64 MiB.

## Conservative exclusions and remaining gaps

The importer rejects multiplayer, nonstandard/modifier runs, known or unknown
gameplay mods, console-enabled journals or any recorded console command,
reloads/resumes, noncontiguous event
sequences, unsupported recorder versions, and missing initial deck information.
It rejects reroll-enabled offers because this first action space has no reroll
action, repeated decision IDs, malformed candidate sets, illegal skips,
ambiguous/conflicting choices and unresolved decisions. Every exclusion is
counted in the report.

Deck mutations use instance IDs internally. When a mutation cannot be resolved,
later decisions are excluded until an authoritative `deck` snapshot repairs the
state. Unknown upgrade levels stay unknown. Absolute HP records and damage
records are reconciled so older journals that log both for one hit are not
double-counted. Purchase gold is marked unknown until another absolute gold/shop
snapshot because `gold_on_hand` timing differs across recorder versions.
An upgrade of an unknown card instance remains unresolved until an authoritative
deck snapshot or a currently observed reward offer identifies that exact
instance and card ID as an offered card. This handles cards upgraded during
reward generation without adding them to the deck or looking ahead. An earlier
rejected decision is never retrospectively rescued by a future offer.

This adapter does not yet encode enchantments, every per-card counter, relic
counters, map topology, future reachable paths, event context, or all character
resources. Relic/potion arrays can be incomplete in older recordings. These are
reasons to keep the quality tag and to collect explicit live observations for
the eventual strong policy. A passing import is not proof of simulator fidelity.

Hidden `draw_order` records, final decks/relics, future encounters and RNG state
are not imported as observations. Seed is used only to group train/evaluation
splits. All decisions sharing a seed belong to the same split, even across
patches. A later evaluation should additionally report player-disjoint and
patch-disjoint results; the replay itself does not always carry a player token.

Imitation accuracy measures agreement with recorded players. Win-label training
estimates outcomes under the historical players' policy, not the causal value
of every candidate action. Neither is a substitute for paired, unseen-seed
full-run evaluation once the game engine is available.

## Provenance and terms

The schema was checked against the author's public repository at commit
`2af6543ca7a6c76acfde6be582651c7c05e88e50`:

- [Developer API documentation](https://spire-codex.com/developers)
- [API terms](https://github.com/ptrlrd/spire-codex/blob/2af6543ca7a6c76acfde6be582651c7c05e88e50/API_TERMS.md)
- [Service terms](https://spire-codex.com/terms)
- [Export route and cursor contract](https://github.com/ptrlrd/spire-codex/blob/2af6543ca7a6c76acfde6be582651c7c05e88e50/backend/app/routers/exports.py)
- [Replay retrieval route](https://github.com/ptrlrd/spire-codex/blob/2af6543ca7a6c76acfde6be582651c7c05e88e50/backend/app/routers/replays.py)
- [Public recorder fixtures](https://github.com/ptrlrd/spire-codex/tree/2af6543ca7a6c76acfde6be582651c7c05e88e50/backend/tests/fixtures)

The hosted API is documented as free for community use within its rate limits.
The upstream software has a separate PolyForm Noncommercial license; no upstream
implementation or fixture is vendored here. Tests in this repository are
original synthetic examples of the observed interface. The project's own code
license does not relicense downloaded data or game assets. Game content belongs
to Mega Crit. Raw downloads and checkpoints stay outside version control.
