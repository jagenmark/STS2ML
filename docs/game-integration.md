# Game integration: what exists and what is still unverified

The active target is **v0.111.0 Silent A10**. The [headless comparison](headless-options.md)
recommends qualifying the pinned sts2-cli beta host first. The adapter described
below remains an experimental **stable v0.107.1** binding; it has not been ported
by changing fingerprints. The [beta assessment](divine-beta-assessment.md) also
records the unimplemented full-app ascension request and hard-coded handshake.
Use [the Windows workstation guide](windows-workstation.md) and read-only
`sts2rl doctor` to record the desktop environment before backend work.

The Python learning pipeline can run without Slay the Spire 2. The optional game
adapter below is **experimental and source-inspected**. It has not been run
against a game installation in this project. Its tests use invented protocol
fixtures, not captured game sessions. No native-game win rate is claimed.

## Chosen upstream and version boundary

The optional backend is [favet/divine-sts2](https://github.com/favet/divine-sts2),
inspected at commit `7cb715916fc9abfb0281c0adf4939c74468e05a4`.
That revision documents STS2 **v0.107.1**, product version
`0.1.0+59260271157f76a2896f0eab5bc6ea1245d8b314`.

Before launching a real worker, this adapter verifies the two documented local
game fingerprints:

| File | SHA-256 |
| --- | --- |
| `data_sts2_windows_x86_64/sts2.dll` | `A1F9E653F1E28E4076558FEE1E60D218619CB7E057B887C6417F62C62C6D7A52` |
| `SlayTheSpire2.pck` | `42520EB8B0911C6C0F0BD102D92B33F41ABD4D26B83489817D0A6DBD7DD48587` |

A newer installation may fail that check. Supporting it requires reviewing and
testing the bridge against the new version, not disabling the check or assuming
the old measurements apply. The source revision in a projected record describes
the source we inspected; it does not certify a caller-supplied transport.

Sources: [version compatibility](https://github.com/favet/divine-sts2/blob/7cb715916fc9abfb0281c0adf4939c74468e05a4/docs/version-compatibility.md),
[full-app bridge report](https://github.com/favet/divine-sts2/blob/7cb715916fc9abfb0281c0adf4939c74468e05a4/docs/full-application-control-bridge.md).

## Two upstream backends must remain distinct

| Backend | Actual API | Intended role in this project |
| --- | --- | --- |
| Full application | `FullAppBridgeClient.start_run / observe / legal_actions / step` | Eventual normal whole-run collection and evaluation |
| Reconstructed native | `NativeWorker.reset / step / fork / restore`; `Sts2NativeVectorEnv` | Possible future tactical/search backend after validation |

The full-app backend launches the user's installed game headlessly in an isolated
sandbox. Its snapshot protocol differs from the reconstructed backend. The
upstream `extract_agent_observation` function supports the reconstructed schema;
it must not be applied unchanged to the full-app schema.

The reconstructed Gym wrapper resets individual combat scenarios, uses tactical
HP/damage reward shaping, and returns a single `masks` boolean per environment.
That boolean means "some legal action exists", not a padded per-action mask. It
is not a ready whole-run PPO environment.

The full-app client has **no snapshot/restore method**. Its documented branch
experiments replay the action prefix from a new run. Reconstructed-worker restore
also rebuilds/replays history; it does not deep-copy a live combat. Upstream
throughput figures for these paths are not interchangeable.

Sources: [Gym wrapper](https://github.com/favet/divine-sts2/blob/7cb715916fc9abfb0281c0adf4939c74468e05a4/python/sts2_native_sim/gym.py),
[full-app client](https://github.com/favet/divine-sts2/blob/7cb715916fc9abfb0281c0adf4939c74468e05a4/python/sts2_native_sim/full_app_client.py),
[persistent environment](https://github.com/favet/divine-sts2/blob/7cb715916fc9abfb0281c0adf4939c74468e05a4/docs/persistent-environment.md).

## Implemented policy boundary: card rewards only

`sts2rl.adapters.divine.project_card_reward` accepts schema-2 full-app snapshots
at `phase == "card_reward"`. It copies only explicitly selected state fields and
the offered card/skip candidates. Everything else is rejected or omitted.

Known information gaps at the inspected revision:

- The deck contains bare card IDs, without upgrades, enchantments or evolving
  card state. Unknown upgrades are represented as `null`, never zero.
- Relic counters and useful future-route/boss context are missing.
- The map exposes immediate next branches, not the complete visible graph.
- Event options lack sufficient identity and text for a general event policy.
- Combat hand upgrades default to zero because the upstream tracker does not
  assign them, and draw/discard/exhaust contents are omitted.

Consequently, callers must set `allow_partial=True` to project a card reward.
Records carry `observation.state_quality = "partial_bridge"` and a missing-context
list. This flag must be explicitly handled in training/evaluation. A successful
projection is not evidence that the state is complete enough to train a strong
policy. Routing, events, shops, combat and rest-site projection raise an error.

The seed, state hash, hidden draw order, raw room details, unrecognized metadata,
descriptions and future outcomes do not enter the policy record. Source revision
and inspection status stay in metadata. Chosen action and outcome start as null;
the collector must attach only subsequently observed labels, with truncations
kept distinct from defeats.

Source: [FullAppStateTracker.cs](https://github.com/favet/divine-sts2/blob/7cb715916fc9abfb0281c0adf4939c74468e05a4/src/Sts2.NativeSim.FullAppBridge/FullAppStateTracker.cs).

```python
from sts2rl.adapters.divine import project_card_reward

record = project_card_reward(
    captured_observation,
    captured_legal_actions,
    run_id="opaque-run-id",
    decision_id="reward-04",
    game_version=observed_game_version,
    split_group="opaque-run-group",
    allow_partial=True,
)
```

## Optional local setup

The inspected integration requires **Windows, Python 3.11+, .NET 9**, and the
compatible user-owned game installation. Start from a pinned upstream checkout
and its installation instructions. A wheel alone does not provide the C# build
outputs expected by its repository-relative loader.

```powershell
git clone https://github.com/favet/divine-sts2.git
cd divine-sts2
git checkout 7cb715916fc9abfb0281c0adf4939c74468e05a4
python -m pip install -e .
$env:STS2_GAME_ROOT = "D:\SteamLibrary\steamapps\common\Slay the Spire 2"
dotnet build src/Sts2.NativeSim.FullAppBridge/Sts2.NativeSim.FullAppBridge.csproj -c Release
```

The build requires DLL references from that installation. After establishing
compatibility, a worker can be launched explicitly:

```python
from sts2rl.adapters.divine import DivineFullAppAdapter

adapter = DivineFullAppAdapter(
    game_root=r"D:\SteamLibrary\steamapps\common\Slay the Spire 2",
    sandbox_root=r"D:\STS2Research\sandboxes",
    allow_partial=True,
)
try:
    adapter.launch(character="IRONCLAD")
    raw = adapter.start_run(seed="A1B2C3D4E5", character="IRONCLAD", ascension=10)
    # This is raw simulator output. A new run is usually not a card reward yet.
    # Capture/project card rewards only after another controller reaches one.
finally:
    adapter.close()
```

The wrapper creates a new session sandbox beneath the explicitly supplied root.
It imports the upstream client only when launched. It provides raw observation
access, but its `step` method accepts only currently legal card-reward actions.
There is no automatic combat player in this milestone.

The MIT license covers our code and upstream original code. It does not grant
rights to the game. This repository distributes no executable, game assembly,
resource pack, art, audio, decompiled game code or personal saves. Upstream
[NOTICE.md](https://github.com/favet/divine-sts2/blob/7cb715916fc9abfb0281c0adf4939c74468e05a4/NOTICE.md)
spells out the same boundary.

## Search contract and next integration gate

`sts2rl.search.evaluate_root_actions` implements generic root-sampled Monte Carlo
rollout evaluation. A backend samples hidden worlds conditional on the public
root observation, clones each world per root action, executes chance transitions,
and exposes only public observations to the continuation policy. Root choices are
selected after averaging returns across worlds. Randomness can occur within a
turn when a card draws or generates another card; it is not restricted to
`end_turn`.

Its result includes each action's mean return, standard error and number of
horizon truncations. A single sample has unknown standard error (`null`), not
zero. This estimates the value of the supplied continuation policy, not optimal
play. A finite horizon without a value bootstrap is a finite-horizon objective.
The current tests use a hidden-coin game to check the information boundary.
**No STS2 simulator implements this contract yet.**

To connect it responsibly, first verify a compatible native installation,
capture the same states in the visible game and backend, check legal-action and
transition agreement, add hidden-state resampling that does not consult the real
future draw order, and benchmark fresh-seed combat outcomes. Whole-run evaluation
must follow after the missing macro-state fields have been fixed.
