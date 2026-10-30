# Headless options for Silent A10 on v0.111.0

Source review: 2026-10-29. Target: installed Steam public beta `v0.111.0`,
game commit `41cef1ea`, initially Silent A10 and later all five characters.
The original review inspected public source and documentation. On 2026-10-30,
the pinned sts2-cli host was built and benchmarked on Windows as described below.
These bounded episodes do not certify full-game or cross-platform parity.

## Windows measurements, 2026-10-30

Hardware: Ryzen 7 9800X3D (8 cores / 16 threads), 32 GB RAM, Windows 11 25H2.
The managed engine uses CPU; the RX 9070 XT was not used by this benchmark.
The profile pins .NET SDK 9.0.320 and upstream revision `fec723a` above.
A diagnostic-only patch reports **actual RunState ascension, character, and
loaded assembly informational version** on every response. Each episode checked
Silent/A10 and `0.1.0+41cef1ea4657c524aa50e870df009e56337e8c32`.

Sixteen identical seeds were run twice at each concurrency, in forward then
reverse concurrency order: **128 normal terminal episodes, zero infrastructure
errors, identical per-seed observation sequences**. Every episode was a defeat
in Act 1, floors 4–12. The policy plays the first playable card, takes the first
reward, prefers healing, skips shops, and uses seeded random routing.

| Processes | Mean episode incl. startup | Extrapolated terminal episodes/hour | Peak sum of worker RSS |
| --- | ---: | ---: | ---: |
| 1 | 1.115 s | 3,220 | 144 MiB |
| 2 | 1.114 s | 6,220 | 285 MiB |
| 4 | 1.149 s | 11,601 | 549 MiB |
| 8 | 1.309 s | 19,726 | 1,093 MiB |

These are **early-loss episode** measurements, not timings for three acts,
winning runs, a learned combat policy, or Monte Carlo search. The short batches
do not establish sustained hourly throughput. Eight processes gave 6.1x the
single-process throughput; higher concurrency was not tested. New-process
startup plus run reset averaged 0.70 s at one worker. Persistent resets could
reduce that cost, but reset isolation has not been qualified.

The [sanitized evidence](evidence/headless-windows-2026-10-30.json) records hashes,
method and limitations. Full traces remain local under `artifacts/headless/`.
The replay downloader remained running during the measurement.

```powershell
./scripts/setup-headless.ps1
uv pip install --python .venv/cpu/Scripts/python.exe -e '.[dev,benchmark]'
& .venv/cpu/Scripts/python.exe scripts/benchmark-headless.py --output artifacts/headless/new-benchmark --runs 16 --workers 1 2 4 8 --repeats 2
```

Setup copies and patches only ignored local game-library copies. Each worker
gets its own working directory and application-data paths. Episode wall time
includes process start, reset, JSON, trace logging and shutdown. Timeouts,
identity mismatches and engine errors remain errors, never defeat labels.
This runner is a measurement harness, not yet the STS2ML training environment.

## Public combat observations v2

The additive `headless-public-observation.patch` and
`scripts/headless/ObservationExport.cs` extend the pinned host. Setup applies
both patches idempotently; the original benchmark above used only the identity
patch, so its timing does not include the larger v2 observations.

Every owned relic exports its stable ID, actual UI `show_counter` / `counter`,
status, used-up flag, stack count, description template and numeric variables.
No counter is invented when the game does not show one. Explicit counter rules
are currently qualified for **Nunchaku**, **Happy Flower**, and **Pen Nib** only.
For example Nunchaku at nine attacks has `counter=9`, `threshold=10`,
`remaining=1`, `unit=attack_played`, `effect=gain_energy`, `effect_amount=1`.
Other relics retain their real counter/description/variables and a null rule.
This does not infer mechanics by reflecting arbitrary private or saved fields.

Combat observations include every card in hand, draw, discard, exhaust and play
piles, including duplicates, upgrade levels, current costs, X-cost flags,
temporary retain/exhaust/Sly flags, enchantments and afflictions. Non-hand piles
are sorted by the complete exported representation, so even differently upgraded
copies cannot leak draw order. Their stats are explicitly base values; existing
hand damage previews remain target-sensitive. Enemy and power IDs are stable.

`sts2rl.combat` projects an explicit field allowlist into neural tensors and a
set-attention state encoder. Relic counters, threshold, distance to trigger and
effect amount are numeric features with missing-value indicators. Pile membership,
modified duplicates, enemy intents, player powers, potions and the permanent deck
are represented. Unknown categorical entities map to UNK in a train-only vocabulary.
The existing replay macro model/checkpoints are unchanged. **There is no trained
combat action head, MC teacher integration or combat RL job yet.** The state
encoder can read the information; strategic use requires training.

Local native tests execute actual game code from the pinned assembly:

* Nunchaku at 9 wraps to 0 and refunds one energy after a one-energy attack.
* Pen Nib at 9 doubles a Strike's damage from 6 to 12 and wraps to 0.
* Happy Flower at 2 grants one extra energy at the next turn and wraps to 0.
* Playing a card moves it to discard; Ascender's Bane moves to exhaust on turn end.
* Pile counts conserve the starter cards. Re-reading observations has no visible
  side effects; reversing the true draw pile including modified duplicates leaves
  the entire public observation unchanged.

```powershell
./scripts/setup-headless.ps1
& artifacts/tools/dotnet/dotnet.exe run --project tests/native/Observations.csproj -c Release -- (Get-Location).Path
& .venv/cpu/Scripts/python.exe -m pytest tests/test_combat.py -q
```

Tests inject counter fixtures only inside a separate test executable and isolated
save directory. They add no privileged policy commands. Native observations also
passed an RX 9070 XT encoder forward/backward check with nonzero gradients through
the counter inputs. Sanitized results are in
[observation evidence](evidence/observations-windows-2026-10-30.json); full local
observations stay under `artifacts/headless/observation-tests/`.

Remaining information limits: description templates are not a pretrained wiki;
the encoder does not understand arbitrary description text. Enemy intents are the
current visible intents, not a guaranteed future sequence. Special effects that
reveal or fix upcoming draws still need an explicit public-history representation;
the unordered pile intentionally cannot preserve those known ordering facts yet.
Selection prompts, other relic trigger rules and several character-specific
mechanics still need qualification. These probes are native-engine tests, not a
side-by-side comparison with the rendered game.

## Decision

There are credible existing native-engine headless projects. Start by
qualifying **wuhao21/sts2-cli**, rather than writing a second rules engine.
It has explicit v0.111.0 evidence, all-character execution, JSON control, and
Linux/Windows setup paths. Its adapter still needs local compatibility,
full-run, information-boundary, and branching checks before training.

**rsgcsg/STS2-headless** is the strongest reference for a strict player-visible
contract and exact build admission. Its supported runtime is macOS ARM64;
Windows has bounded experimental evidence and Linux remains unqualified.
**divine-sts2** offers useful Windows worker/search architecture but its pinned
game build is stable v0.107.1. No reviewed candidate establishes a ready-made,
validated Silent A10 v0.111.0 training environment on both our machines.

## What “headless” means here

- **Shipped-process headless:** the actual Godot executable runs without a
  display; game rules, resources, SceneTree, and normal run lifecycle remain.
- **Managed native-engine host:** a separate .NET process loads the installed
  `sts2.dll`, suppresses/replaces presentation, and adapts choices. This avoids
  reimplementing cards, but adapter patches can still change behavior.
- **Reimplemented simulator:** another engine implements the rules. Catalog
  counts and passing unit tests do not establish parity with a new patch.
- **Live-game bridge/MCP:** structured observations/actions over a running game
  do not by themselves provide headless execution, cheap reset, or branching.

## Compared candidates

All revisions below are exact source pins, not moving default branches.

| Candidate and source revision | Execution and version evidence | Platform and license | Assessment |
| --- | --- | --- | --- |
| [wuhao21/sts2-cli](https://github.com/wuhao21/sts2-cli/tree/fec723a21741a1a33a4f54dc9b28c50df31d6e45), `fec723a21741a1a33a4f54dc9b28c50df31d6e45` | IL-patched installed engine with Godot stubs. Explicit v0.111.0 / `41cef1ea`, Steam build `24724944` compatibility report. | Tested macOS ARM64; setup handles Linux and Windows Bash/MSYS paths, which is not cross-platform runtime proof. MIT. | First execution candidate. Strongest direct version fit with accessible setup. |
| [rsgcsg/STS2-headless](https://github.com/rsgcsg/STS2-headless/tree/1deb5b7b3125e2308df7e8e44cb3b213e46e7f64), `1deb5b7b3125e2308df7e8e44cb3b213e46e7f64` | Shipped Godot reference host plus a managed candidate based on a pinned older sts2-cli revision. Exact v0.111.0 assembly/host/Connector hashes. | Supported tuple: macOS ARM64. Separate Windows x64 experimental tuple; Linux pending. MIT. | Contract/reference candidate; not an already-qualified Linux/Windows training farm. |
| [favet/divine-sts2](https://github.com/favet/divine-sts2/tree/7cb715916fc9abfb0281c0adf4939c74468e05a4), `7cb715916fc9abfb0281c0adf4939c74468e05a4` | Shipped-process headless bridge plus native reconstructed scenarios. Compatibility targets v0.107.1 / `59260271`, not v0.111.0. | Windows 10/11 x64; Python, PowerShell, .NET tooling. MIT. | Useful search/worker design; beta port and new evidence needed. |
| [yizhang-dream/sts2-simulator](https://github.com/yizhang-dream/sts2-simulator/tree/83fcca63912e81c6e608de705b18a35dbbed0fd9), `83fcca63912e81c6e608de705b18a35dbbed0fd9` | Pure Python reimplementation with Gymnasium. Public snapshot is from May 2026; its later v0.111.0 numeric override layer is explicitly absent. | Python >=3.11; no simulator OS restriction documented. No license file or project license field found at this revision. | Not a reproducible v0.111.0 rules source; do not adopt as authoritative training environment. |

### sts2-cli: direct beta candidate, with adapter work remaining

The [compatibility report](https://github.com/wuhao21/sts2-cli/blob/fec723a21741a1a33a4f54dc9b28c50df31d6e45/docs/compatibility-v0.111.0.md)
records five terminal runs per character. All five Silent runs died in Act 1
(floors 5–17); the batch runner omits ascension, so these use the default A0.
This is execution evidence, **not** A10 evidence or a traversal of every act.

[Program.cs](https://github.com/wuhao21/sts2-cli/blob/fec723a21741a1a33a4f54dc9b28c50df31d6e45/src/Sts2Headless/Program.cs)
exposes `start_run(character, seed, ascension)`, ordinary `action` commands,
`load_save`, and `write_continue_save`. It also exposes privileged scenario
commands (`set_player`, `enter_room`, `set_draw_order`); these must never enter
the policy action space. Each worker owns native singleton state, so isolate
workers in separate processes until repeated-reset behavior is verified.

[RunSimulator.cs](https://github.com/wuhao21/sts2-cli/blob/fec723a21741a1a33a4f54dc9b28c50df31d6e45/src/Sts2Headless/RunSimulator.cs)
returns hand, current enemy intents, player/deck/relic/potion information and
pile counts. It does not yet offer the complete, explicitly audited
player-visible projection and finite action contract we need. Runtime card
identity, piles, selections, and action legality require checks and an adapter.

There is **no general active-combat fork/restore API** in the inspected
protocol. `SaveCheckpoint` saves a map checkpoint, or rolls a non-map state
back to a pre-room checkpoint. Native save/load therefore must not be treated
as a clone of the current combat. Initial branching can replay from a seeded
reset plus action history; exact hashes and timeout handling must be added.
The adapter also contains manual lifecycle repairs (for example between-act
healing), so executing native card code alone does not prove complete parity.

The [setup script](https://github.com/wuhao21/sts2-cli/blob/fec723a21741a1a33a4f54dc9b28c50df31d6e45/setup.sh)
recognizes Darwin, Linux, and MINGW/MSYS/CYGWIN and accepts a game-directory
argument. A Windows-native setup wrapper and explicit custom-library handling
would make the continuation on the desktop easier to reproduce.

### STS2-headless: stronger boundaries, narrower admitted runtime

Its [compatibility table](https://github.com/rsgcsg/STS2-headless/blob/1deb5b7b3125e2308df7e8e44cb3b213e46e7f64/docs/COMPATIBILITY.md)
pins more than the display version: game assembly, executable, GodotSharp,
managed patch/host, Connector, and modset. A Windows-specific v0.111.0 tuple
exists, but is explicitly experimental. The [status record](https://github.com/rsgcsg/STS2-headless/blob/1deb5b7b3125e2308df7e8e44cb3b213e46e7f64/docs/STATUS.md)
reports one Windows probe with 64 actions and 122 reads; it explicitly leaves
semantic qualification unevaluated. This is not full-run Silent A10 proof.

The [Python consumer](https://github.com/rsgcsg/STS2-headless/blob/1deb5b7b3125e2308df7e8e44cb3b213e46e7f64/consumers/python/sts2_headless/client.py)
provides `reset/observe/read/step` and vector orchestration. Actions are bound
to the current snapshot, stale actions are refused, and receipts separate
delivery from completion. No public cheap state-fork method appears there.
Its [managed projection](https://github.com/rsgcsg/STS2-headless/blob/1deb5b7b3125e2308df7e8e44cb3b213e46e7f64/src/managed-player-environment.mjs)
explicitly hides RNG, true draw order, future enemy moves and future rewards,
and exposes inspectable deck/pile reads. These boundaries are worth preserving.

### divine-sts2: useful branching design, wrong current patch

The [version contract](https://github.com/favet/divine-sts2/blob/7cb715916fc9abfb0281c0adf4939c74468e05a4/docs/version-compatibility.md)
pins v0.107.1. Its [persistent environment documentation](https://github.com/favet/divine-sts2/blob/7cb715916fc9abfb0281c0adf4939c74468e05a4/docs/persistent-environment.md)
distinguishes full-application execution from reconstructed scenarios. The
JSON host exposes reset/observe/step/fork/restore and Python Gym/worker tools.
Fork handles store reset input, action history and expected hash; restoration
reconstructs and replays, rather than copying an arbitrary live combat object.

Its [observation filter](https://github.com/favet/divine-sts2/blob/7cb715916fc9abfb0281c0adf4939c74468e05a4/python/sts2_native_sim/observations.py)
separates privileged canonical state from policy observations, masks seeds/RNG,
and makes the draw pile unordered. Full-run controls are described, but the
inspected concrete long-route evidence is principally Act 1; the
[status guide](https://github.com/favet/divine-sts2/blob/7cb715916fc9abfb0281c0adf4939c74468e05a4/docs/project-status-and-review-guide.md)
warns that some development evidence is private. Public benchmarks are
upstream claims, not measurements of our beta installation.

### Python simulator: convenient API does not fix missing beta provenance

The [README](https://github.com/yizhang-dream/sts2-simulator/blob/83fcca63912e81c6e608de705b18a35dbbed0fd9/README.md)
explicitly excludes the extraction pipeline and
`v01110_card_overrides.json`. The public full-run
[Gym environment](https://github.com/yizhang-dream/sts2-simulator/blob/83fcca63912e81c6e608de705b18a35dbbed0fd9/sts2_env/gym_env/run_env.py)
has seeded `reset`, `step`, masks, character and ascension parameters. This
supports experiments on that simulator, not a claim that its Silent mechanics,
run generation, or A10 outcomes match installed v0.111.0. No documented exact
native-state fork contract was identified.

## Smallest next verification and what STS2ML must add

1. Record the local Steam build, `sts2.dll` product version and SHA-256; build
   the pinned sts2-cli in an isolated directory using local game files. Repeat
   on Windows and keep each platform's identity separate.
2. Run bounded Silent A0 and **A10** seeded terminal smoke episodes, retaining
   stderr and action/state logs outside the upstream seven-day log cleanup.
   Death is a normal terminal result; stalls/crashes are infrastructure errors.
3. Compare selected transitions against the same build's real-game evidence:
   Poison/Weak/Retain/Sly, Outbreak, Mirage, Well-Laid Plans, Expertise,
   potions, card selections, shops, act transitions and A10's double boss.
   Passing Act 1 losses alone cannot clear the last two boundaries.
4. Add a versioned STS2ML reset/step adapter, legal-action IDs/masks,
   player-visible observations, terminal/error distinction, process isolation
   and reproducible logs. Keep scenario/debug controls and hidden state outside
   the policy interface.
5. Implement and verify seeded action replay for branching before MCTS; then
   measure restoration cost separately from resident steps. An optimization to
   native snapshots needs its own parity evidence.

These additions are integration and qualification work. A new card-by-card
simulator is not currently justified. GPU training backend selection for the
Windows RX 9070 XT is a separate check: none of these headless execution
evidence reports establishes AMD training support or performance.
