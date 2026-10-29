# Public data for Silent A10

Discovery and bounded import probe: **2026-10-29**. Selected target:
**Silent A10, Steam public beta v0.111.0**; later every character, with separate
models and datasets for each patch. The immediate decision is to retain beta
as the first collection candidate. Sufficient clean expert data has not yet
been established.

## Public coverage

| Source | Beta | Stable | Actual grain |
| --- | --- | --- | --- |
| [sts2.fun beta](https://sts2.fun/?patch=beta-v0.111) / [main](https://sts2.fun/?patch=main-v0.107) | 1,873 Silent A10 runs, 501 wins | 2,309 Silent A10 runs, 495 wins | Website statistics for major-patch groups, not an exact-build training set |
| [Spire Codex beta listing](https://spire-codex.com/api/replays?character=SILENT&ascension=10&players=single&game_mode=standard&limit=50&build_id=v0.111.0) / [stable listing](https://spire-codex.com/api/replays?character=SILENT&ascension=10&players=single&game_mode=standard&limit=50&build_id=v0.107.1) | At least 1,716 | At least 448 | Listable solo, standard, Silent A10 replay journals, including incomplete and otherwise unsuitable records |

Both Codex totals carry `total_is_lower_bound=true`. Do not add websites' counts
without deduplication, treat them as independent players/seeds, or equate a
listable journal with an accepted demonstration. Source counts can change.
The [Codex export manifest](https://spire-codex.com/api/exports/runs/manifest)
also listed 328,690 beta and 785,121 stable raw runs across all characters and
ascensions. Those summary records are a different population from replays.

## sts2.fun export

The [FAQ](https://sts2.fun/faq) explicitly offers an anonymized
[SQLite/zstd database](https://sts2.fun/static/sts2_public.db.zst). Its HTTP size
was 759,783,329 bytes and last modification was 2026-10-05 22:36:50 UTC, older
than the current website. Only a 1 MiB HTTP range was downloaded for inspection.

The decompressed prefix established a `runs.raw_json` column and separate
build, branch, major-patch, player, seed, player-count, modifier and validity
fields. Three complete **older v0.98.x Silent examples** contained chosen and
unchosen cards, Ancient choices, per-floor HP/gold, deck mutations and purchases.
These examples do not establish the same schema completeness on v0.111.0.

Floor history does not establish every decision's ordering. One floor contained
22 card-choice entries and two selected cards without a verified offer ID.
Shops also record unbought cards; these cannot all become reward-skip labels.
Final decks and later upgrades must not become decision-time features. The
snapshot is useful for baselines and further schema work, not already a
replacement for the conservative replay importer. Stable player identifiers
could support player-disjoint evaluation. No formal dataset license was found
on the inspected pages; the explicit public export and software license are
distinct facts.

## Actual replay import probe

Sixteen discovered journals were downloaded with pacing and original gzip bytes:
eight listed beta and eight stable, with four listed wins and four non-abandoned
losses per patch. This is a **convenience sample**, not an acceptance-rate estimate.
File hashes and public source URLs are in the
[sanitized evidence record](evidence/public-data-2026-10-29.json).

| Listed patch | Sampled journals | Runs emitting default examples | Card decisions | Decisions with strict timing |
| --- | ---: | ---: | ---: | ---: |
| v0.111.0 | 8 | 2 | 28 | 0 |
| v0.107.1 | 8 | 2 | 45 | 1 |

All emitted examples remain `partial_replay`. Strict timing additionally excludes
an offer if recorded state changes before selection; failing it is not proof
that the entire source is unusable. Default accepted runs supplied one recorded
defeat and one unknown terminal outcome per patch, with no positive outcome labels.

Observed issues include gameplay mods, multiple headers/resumes, console
commands and header/listing disagreement. Some `remap` events are excluded by
the current importer, but a remap alone does not prove cheating or reloading.
Two beta-listed headers say `0.1.0` instead of `v0.111.0`; they were already
excluded for other reasons. Every listed win in this small sample ends with a
`left_run` / `is_game_over=false` journal record. A verified join to the matching
raw run's terminal result needs investigation; do not convert these to losses.

The sample cannot support three substantial held-out partitions or a strong
policy claim. Expand collection, resolve source/outcome/timing boundaries,
and report accepted independent runs, seed groups and players before training.

## Other verified leads

- [AgenticSTS](https://huggingface.co/datasets/AlayaLab/AgenticSTS-trajectories):
  312 LLM-agent run rows, 305 with decision logs. Silent A10 has seven defeats
  and two decision-capped rows, all v0.103.1. Useful protocol examples; not human
  expert data or a current-patch corpus. Its own trajectories/history are CC-BY-4.0;
  competitor captures retain their separate upstream terms.
- [SpireBench](https://www.spirebench.com/blog/trial-v0-results): 25 A0 runs on
  v0.104.0, five per character, with public run files and floor snapshots.
  Useful small import checks, not Silent A10 demonstration coverage.
- [STS2Runs](https://sts2runs.com/faq) advertises monthly dumps, but access to
  its download page was not verified during this audit. No usable counts claimed.

## Collection and learning sequence

Use the patch-filtered commands in the README, preserve listing provenance and
source hashes, and keep raw downloads under ignored `data/`. Select stronger
players through sufficiently large, separate qualification history; retain both
wins and losses. Held-out players and seed families must not choose expert
thresholds, checkpoint selection, or filters. First learn contextual card/skip
choices; aggregate pick/win rates are baselines, not optimal-action labels.

Whole-run RL follows an independently qualified headless backend and a fixed
combat policy. The [headless review](headless-options.md) and
[Windows continuation guide](windows-workstation.md) define that next gate.
