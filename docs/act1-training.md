# Whole Act 1 training

The current collection target is an ordinary **Silent A10, v0.111.0 Act 1 run**:
start at Neow, make map/event/reward/shop/rest decisions, and stop on death or
entry into Act 2. No encounter, HP, deck or relic is forced in these episodes.
The earlier single-beetle curriculum was a bridge qualification experiment; it
does not provide adequate training diversity for an Act 1 player.

## Run locally

After `scripts/setup-headless.ps1`, use a fresh output folder:

```powershell
& .venv/rocm/Scripts/python.exe scripts/train-act1.py --output artifacts/act1/new-experiment --runs 64 --workers 4 --samples 4 --roots-per-fight 12 --query-probability 0.5 --epochs 20 --evaluate 32 --macro-checkpoint artifacts/v0.111.0/silent-a10/workstation-20261030-172303-775/final/best.pt
```

The macro checkpoint path above is a local example, not a downloaded repository
asset. Omit it to use varied macro choices without the replay model. With it,
85% of card rewards use the replay-trained model and 15% use random exploration.
Map choices favor rests at low HP and avoid low-HP elites when possible. Shops
can buy stocked, affordable relics/cards/potions; the macro currently prefers
relics, then cards. Card removal and potion replacement are not yet supported.

Four workers run eight isolated native processes. CPU processes collect teacher
data; the RX 9070 XT fits the policy afterward. `--collect-only` omits fitting;
`--device cpu` permits CPU fitting. A `STOP` file stops collection at a decision
boundary. Incomplete runs are quarantined and block automatic fitting. Search
branch errors produce no label and are counted separately from actual defeats.

`status.json`, per-run `progress.json`/`result.json`, and `collection.json` record
progress, floors, fights, distinct enemy/card/relic identities and search errors.
`teacher_monsters` records where labels were actually collected. Presence in a
coverage report is not evidence that a mechanic was learned. All traces, raw
observations and weights remain ignored under `artifacts/`.

## Search and information boundary

Monte Carlo still searches **to the end of the current fight**, using a public
heuristic continuation. It does not search the whole act's decision tree. The
collector obtains those fight states throughout real Act 1 runs, with changing
HP, decks, upgrades, relics, potions, enemies and current intents. At most two
roots per turn and the configured budget per fight are queried. Unsampled
decisions use the combat heuristic; queried decisions execute the teacher choice.

Every branch starts by replaying the original seed and full action history in
another isolated process and matching the public-state hash. Map save/reload
was tested and rejected as an optimization: a matching map observation did not
guarantee the same subsequent unknown room. Full replay is slower but preserves
that history; it is not active-combat snapshot cloning.

The experimental sampler `silent-a10-act1-mc-v2` canonicalizes then shuffles the
hidden draw multiset and resets run, player, monster-local, encounter and chaotic
RNG streams. It preserves current visible intents and native monster history.
Known effects that can reveal or establish draw order conservatively exclude
the affected fight from labels until a public belief tracker supports them.
The run itself continues. Roots with oversized branch budgets are also skipped
and counted. The original starter-only sampler remains a separate profile.

**This is not proof of an exact belief sampler for every Act 1 mechanic.**
Cached hidden monster state and unexported per-card state still need broader
audits and rendered-game parity checks. Only audited stateless starter cards
share estimates between identical physical copies; other copies are searched
separately. Finite regression fixtures verify hidden draw-order invariance and
chance variation across six encounters, including an elite, with a varied deck
and a potion. They do not establish complete game coverage.

The neural input includes hand, unordered draw/discard/exhaust/play piles, deck,
upgrades/modifiers, visible relic counters, enemy intents/powers, player powers,
potions, selection origin and public enemy turn history. Generated combat card
rewards and bundles are action-bound as well. Seeds, private engine state and
future outcomes are excluded. Descriptive text is not language-understood;
there is no pretrained wiki comprehension claim.

## Fitting and evaluation

Completed fights return `100 + 100 * HP / max_HP`, minus 3 per used potion;
death returns zero. Smoke Bomb escape receives no fight-win bonus. The auxiliary
value head predicts this **local fight return / 200**, not the chance of clearing
the act. Search truncations and engine errors never become loss labels.

Soft action targets use temperature 2 return points. Entire seed groups stay in
one train/validation/test partition; vocabulary is fitted only on training runs.
The broad model uses 0.1 dropout and weight decay. Validation cross-entropy selects
the checkpoint. Reports include coverage per split, offline agreement and regret.
Old starter data cannot be silently mixed with the broad return scale.

Final evaluation runs the student and heuristic on the same new seed family,
with the same macro model/configuration. It reports actual Act 1 clears, floors,
coverage and errors separately. Their trajectories can diverge because combat
outcomes change later choices. Offline imitation accuracy is not an Act 1 win rate.

## Initial broad pilot, 2026-10-30

After fixing native shop logging and missing Godot JIT signatures for Rolling
Boulder, the collection pilot completed **12/12 runs without engine or search
errors**: **61 fights, 237 teacher decisions, 2,524 branches**, in 179.3 seconds
with four workers. Labels covered **21 enemy identities**; encountered decks and
relic sets included 42 card identities and 18 relic identities. The furthest run
reached floor 15. **0/12 cleared Act 1**, so boss coverage and clear rate still
need improvement. This pilot validates the broader pipeline, not a strong agent.

Qualification commands:

```powershell
& .venv/cpu/Scripts/python.exe scripts/verify-act1-native.py --output artifacts/act1/new-qualification
& .venv/cpu/Scripts/python.exe scripts/verify-micro-native.py --output artifacts/act1/new-starter-regression
& .venv/cpu/Scripts/python.exe -m pytest -q
```

The native fixtures additionally verify actual Rolling Boulder damage, relic/
potion/card purchase effects, low-HP resting and rejection of unsupported draw
knowledge. The starter regression verifies deterministic forks, pending
selections, fifty repeated restores, potion effects and sibling isolation.
