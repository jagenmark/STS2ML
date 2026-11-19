# Use the Silent A10 checkpoints on another machine

The November 19 release contains four loadable policy bundles, 768 benchmark outcomes, the original inference source, 161 Act 2 openings and 23 Act 3 openings. A second download contains the data and intermediate checkpoints from the completed training runs. The model called `challenger` is the policy that reached Act 2 on 37 of 128 standard-lobby seeds. [GitHub release](https://github.com/jagenmark/STS2ML/releases/tag/silent-a10-2026-11-19) · [Benchmark and seed protocol](silent-a10-progression.md)

## Restore on Helmer

From an existing STS2ML checkout, fetch the release. A new checkout can be created with `git clone https://github.com/jagenmark/STS2ML.git`.

```powershell
git fetch origin --tags
git switch --detach silent-a10-2026-11-19
$python = ".\.venv\cpu\Scripts\python.exe"
```

Reuse the workstation's existing CPU Python environment. On a fresh checkout, create it once.

```powershell
py -3.11 -m venv .venv/cpu
& $python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
& $python -m pip install -e '.[dev]'
```

Download both archives, verify their SHA-256 inventories, and check the restored data.

```powershell
& $python scripts/restore-silent-a10.py --check-training
```

The check loads the policy bundles, runs a native training observation through the neural checkpoint, and reproduces the route fit on 24,197 transitions. It works offline after installation. Use `--models-only` for inference, or `--archives PATH` to install previously downloaded ZIPs. On Linux use the same restore command with `.venv/bin/python`.

| Restored directory under `artifacts/` | Contents |
|---|---|
| `silent-a10-progression-release/` | Frozen challenger and incumbent, two development policies, native opening histories, benchmark protocols, results, replay receipts and source Git bundle |
| `silent-a10-training-state/rooms/` | 1,536 training episodes with seed, result and physical command history |
| `silent-a10-training-state/labels/` and `imitation/` | Original teacher decisions, branch outcomes and the action features used in the completed fits |
| `silent-a10-training-state/checkpoints/` and `weight-search/` | Experimental fits, intermediate neural weights, search populations, centers, spreads and outcomes |

## Play a new seed with the released weights

Native games require a local Steam installation of Slay the Spire 2 public beta **v0.111.0, commit 41cef1ea**. The Windows setup script checks the game assembly, prepares the pinned .NET SDK and builds the patched host. A non-default Steam library can be passed with `-GameRoot`. [Windows host setup](../scripts/setup-headless.ps1)

```powershell
.\scripts\setup-headless.ps1
$env:STS2_SELECTOR_FIX_LOCAL_TASK = "1"
$engine = "artifacts/upstreams/sts2-cli/src/Sts2Headless/bin/Release/net9.0/Sts2Headless.dll"
$models = "artifacts/silent-a10-progression-release"
& $python scripts/optimize-silent.py evaluate --host $engine --bundle "$models/challenger/policy.json" --roles candidate --seeded-acts --prefix HELMERNEW01 --seeds 2 --workers 2 --output artifacts/helmer-new01
```

Use a fresh output directory for each run. Change the prefix to obtain new **full-game** seeds. Conditional runs replay the seed and history stored in each opening, so reserve separate opening seeds for training and evaluation. The prefixes `H2A10FINAL` and `H2A10MIXED` belong to the published benchmark. On a prepared Linux machine the isolated build and paired evaluation commands are in the [benchmark guide](silent-a10-progression.md#reproduce-the-benchmark).

## Continue model development

The release tag pins the inference and feature code that produced the benchmark. For new development, switch to the working branch and keep generated runs in new output directories. The restored archives remain available across checkouts.

```powershell
git switch codex/continue-a7-training
git pull --ff-only
```

To reproduce a completed strategic fit with the archived returns, use the **release tag** and run the following from the repository root.

```powershell
& $python scripts/train-silent-strategy.py fit --source artifacts/silent-a10-training-state/labels/strategy --output artifacts/helmer-strategy-refit
```

For a new experiment, record the code revision, teacher and feature weights, and seed lists alongside the data. Collect fresh labels when the labeling policy changes. The archived trajectories can also be replayed from their seed and physical commands. Save a new evaluation's policy as a portable bundle with `scripts/freeze-silent-bundle.py --run PATH/TO/config.json --output PATH/TO/new-bundle`. Transfer that entire directory together with the matching code revision, newly collected training data and experiment configuration. The released snapshot was taken between completed fits.
