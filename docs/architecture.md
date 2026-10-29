# Architecture and evaluation decisions

## Scope of milestone 0.1

The eventual agent combines a learned macro policy/value model with tactical
search. This milestone provides the learning and observation boundary first.
Only card rewards are imported/projected by the supplied adapters. The schema
can carry other decision types, but that does not make unimplemented shops,
events, routes or rest sites supported.

Choosing an approximately 0.9M-parameter model keeps experiments cheap while
retaining interactions between candidate cards, the deck and relics. Increase
capacity only after clean held-out results show that capacity, rather than
observation completeness, data coverage or training quality, is the limitation.

## Canonical decision schema

Each JSONL line has schema_version=1 and these fields:

| Field | Meaning | Enters network? |
| --- | --- | --- |
| `run_id`, `decision_id` | Deduplication and provenance | No |
| `split_group` | Hashed seed family; combined transitively with run ID | No |
| `source`, `game_version` | Audit/filtering; mixed patches rejected by default | No |
| `observation.character`, `decision_type` | Categorical context | Yes |
| `ascension`, `act`, `floor`, `hp`, `max_hp`, `gold` | Numeric context + knownness indicators | Yes |
| `deck` | Multiset of `{id, upgrades}`; null upgrade means unknown | Yes |
| `relics`, `potions` | Entity lists | Yes |
| `state_quality` | Observed/partial/synthetic provenance | Audit only |
| `candidates` | Legal actions; kind, entity, upgrade, price | Yes, except opaque action IDs |
| `chosen_action_id` | Recorded action mapped to a candidate index | Target only |
| `outcome` | 1 victory, 0 defeat, null unresolved | Target only |
| `metadata` | Adapter revision, omissions and provenance | No |

The encoder reads an explicit allowlist. Schema validation rejects extra fields
inside observations/candidates, duplicate action IDs, out-of-range numbers,
illegal targets, and states exceeding 512 entities or 128 actions. There is no
silent truncation. Raw game snapshots stay behind the adapter boundary.

Cards and actions share entity embeddings. Type embeddings separate deck cards,
relics and potions. The state sequence includes a context token; candidate queries
cross-attend to it and all encoded entities. A separate scalar head estimates the
observational outcome. Empty decks still have a valid context token.

## Offline experiment protocol

1. Validate every record and reject inconsistent outcomes or character/patch/
   ascension within one run.
2. Build connected components using both run IDs and seed groups. Unlabelled
   observations still establish grouping links.
3. Assign each component by a seeded SHA-256 hash to approximately 70% training,
   15% validation and 15% test. Fractions are approximate at group level.
4. Remove unlabelled records within their already assigned partitions. Fit the
   token vocabulary and simple offer-conditioned frequency baseline on training
   records only.
5. Train on human choice CE plus terminal-outcome BCE. Sort records before seeded
   shuffling. Select checkpoints using validation policy cross-entropy only.
6. Evaluate the selected checkpoint on test once. Report agreement, cross-entropy,
   uniform and frequency baselines, run-mean agreement, outcome BCE/Brier score,
   and the number of decisions/runs.

The loss is decision-weighted, so longer runs contribute more examples. Run-mean
accuracy makes that weighting visible but does not eliminate all selection bias.
Player-disjoint and later-patch evaluations are not implemented yet. A test set
with only a few runs is an integration check, not a credible skill estimate.
Any comparison after repeated inspection of test data needs a fresh held-out set.

## Artifacts and reproducibility

`best.pt` stores model weights, architecture, vocabulary, training configuration,
training audit, split manifest and fitted baselines. Loading uses PyTorch's
`weights_only=True` deserializer. `report.json` records every epoch's training and
validation metrics, final test metrics and limitations. `split.json` stores the
dataset digest and component assignments. No test labels determine vocabulary
or checkpoint selection.

The digest is canonicalized over sorted complete records. Reordering input rows
does not change grouping or training order. Retain raw source hashes and the
exact Python/PyTorch environment with any published result; exact cross-device
bitwise reproducibility is not promised. A source dataset change can legitimately
merge components and alter a split, so retain the original split artifact.

## Tactical search boundary

The generic Monte Carlo evaluator estimates each legal root action's return
under a chosen continuation policy. Each sampled world represents uncertainty
consistent with the public information. The continuation policy receives only
public observations. Scores are averaged across worlds before choosing the root
action. The hidden-coin test checks the important distinction between sampling
uncertainty and allowing a planner to know the sampled answer.

This interface still needs a faithful STS2 backend. It is not an implemented
combat solver, MCTS tree, or rollout-throughput claim. Draws and random card
generation can occur within a turn, so determinization must cover more than the
initial hand or enemy move.

## Path to whole-run RL

Macro actions occur at irregular intervals. A future collector should bundle all
combat/micro steps between macro decisions into one transition, record elapsed
steps when discounting is used, distinguish real defeat from timeout/worker error,
and train against terminal victory with any shaping separately justified.

Before PPO or other online optimization, freeze and evaluate a combat policy.
Otherwise a macro win-rate difference can reflect a changed tactical controller.
Evaluate policies on identical unseen seed sets with confidence intervals over
runs, and report completion rates, invalid actions, timeouts and game build.
Neither the upstream reconstructed-combat reward nor a card's raw win rate is
automatically the right full-run objective.
