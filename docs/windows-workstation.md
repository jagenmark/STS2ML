# Continue on the Windows workstation

Use **Silent A10** first; support for every character remains the longer-term
target. Start with the CPU check below. This small offline model does not need a
GPU to validate its data, tests, or training pipeline.

The GPU information was checked against AMD and PyTorch documentation on
**2026-10-29**, and the offline pipeline was executed on this RX 9070 XT desktop
on **2026-10-30**. Game integration remains a separate, unqualified milestone.

## Verified desktop setup and background training

The local environments use Python **3.11.15**, CPU PyTorch **2.14.0+cpu** and
AMD PyTorch **2.14.0+rocm10.1.0** with the `device-gfx1201` extra. Both environment
test runs passed **95 tests**. GPU enumeration selects **RX 9070 XT at cuda:0**;
the integrated Radeon is device 1. Matmul/autograd and a complete synthetic
model training/evaluation run passed. The existing driver **32.0.32015.7029**
worked in these tests; no driver or Windows security setting was changed.
This is a tested local configuration, not a claim about all driver versions.

The installed Steam game identifies as **v0.111.0**, public-beta, build
**24724944**. Local fingerprints and resolved package lists are under
`artifacts/environment/`. Generated data and weights remain Git-ignored.

From the repository root, start one bounded background job:

```powershell
./scripts/start-training.ps1 -Pages 10 -Epochs 30 -Device cuda:0
```

To collect **every available Silent A10 replay**, then automatically train once
on all importable target-patch decisions:

```powershell
./scripts/start-training.ps1 -AllReplays -AllPatches -Epochs 30 -Device cuda:0
```

`-AllReplays` ignores the page-count cap. `-AllPatches` collects every listed
version into `data/replays/silent-a10/raw/`; the training stage still filters
actual journal headers to v0.111.0. Other patches are retained, never silently
mixed into that model. Existing downloads are reused from the earlier raw folder.
Omit `-AllPatches` to collect only the target patch. For an offline fit on the
all-patch cache, use `-CachedOnly -AllPatches`.

The full collector follows pages until an empty page, then reconciles them until
a complete pass discovers no new IDs before its recorded UTC cutoff. Reported
`total` and `total_pages` can be lower bounds and do not stop collection. The
cutoff prevents the job chasing an endless live feed. A restart retains that
same cutoff and inventory. Each completed journal records its checksum; an OS
file lock refuses simultaneous full collectors writing the same directory.

Requests are spaced at least 4.1 seconds apart, use a 90-second timeout, and
retry transient failures up to 12 attempts with backoff. Server `Retry-After`
values are respected, including HTTP dates. A STOP file interrupts backoff.
Listed journals returning 404/410 remain explicitly unavailable; other exhausted
errors stop the job with retained progress. A failed collection cannot produce a
misleading "final full-dataset" model. `collection-summary.json` records coverage.

The 2026-10-30 census reported **at least 2,180** Silent A10 solo standard replays
across patches, and **at least 1,717** listed for v0.111.0. Both responses had
`total_is_lower_bound=true`; these are not exact corpus sizes or usable-run counts.
The full job completed at **19:45 Europe/Stockholm on 2026-10-30**, with artifacts at
`artifacts/v0.111.0/silent-a10/workstation-20261030-172303-775/`.

Two discovery passes covered **2,181 unique listed journals** before the fixed
cutoff. **2,156 files** were available (1,757 new downloads plus 399 reused);
25 listed journals returned unavailable. Import/filtering retained **275 runs /
2,640 v0.111.0 card-reward decisions**. The train/validation/test split was
187/51/37 runs and 1,844/451/345 decisions. Thirty GPU epochs took **86.88 seconds**;
validation again selected epoch 2. The saved checkpoint was reloaded and its
candidate probabilities checked on a held-out decision on RX 9070 XT.

On the **345 held-out decisions from 37 runs**, imitation accuracy was **49.28%**,
versus **47.10%** for the pick-frequency baseline and **25%** for uniform choice.
This small descriptive advantage is not a native game win rate or strong evidence
of playing strength. The held-out dataset differs from the earlier 79-run fit, so
39.3% versus 49.3% is not a controlled same-test comparison. Overfitting remained
strong after the early best epoch. All 167 known retained outcomes were defeats;
108 runs had unknown outcomes, and value training stayed disabled. This job did
not train a combat policy or run RL. See the
[sanitized final evidence](evidence/replay-training-windows-2026-10-30.json).

The bounded-page mode collects at most ten pages of 50 listed replays with request pacing, imports
conservatively, and filters the actual replay header to Silent/A10/v0.111.0.
Existing journals are reused and hashed. Each completed download updates its
provenance manifest, so an interruption preserves the listing and hashes.
A request failure stops the bounded-page job; inspect the log before restarting. Use
`-StartPage 9` to resume collection at page 9, or `-CachedOnly` to import and
train once on already downloaded files without any network calls:

```powershell
./scripts/start-training.ps1 -CachedOnly -Epochs 30 -Device cuda:0
```

The 2026-10-30 collection reached 399 replay files before read timeouts. A retry
of page 9 also timed out, so a cached-only GPU fit completed on **79 accepted
runs / 774 card-reward decisions**. The split contained 50 training, 13 validation
and 16 test groups. Validation selected epoch 2 of 30; test pick accuracy was
39.3%, versus 42.6% for the pick-frequency baseline. This is not yet a strong
card-choice policy or a game win-rate result. All known training outcomes were
defeats, so outcome training remained disabled. The completed local experiment is
`artifacts/v0.111.0/silent-a10/workstation-20261030-165649-028/final/`.

The first dataset with imitation labels in all three run/seed-grouped partitions
triggers an initial model. After collection, a final model is trained on the
expanded dataset. Both use 30 epochs with validation-selected checkpoints.
These are separate fits from initialization, not optimizer-resumed training.
The outcome head is disabled when the training partition has fewer than two
outcome classes; unknown terminal results are never relabeled as losses.
Early results may contain very few independent runs and are pipeline checks.

The launcher prints its unique experiment directory. Inside it, `status.json`
records the process ID, stage and completed models; `pipeline.log` records
collection/import stages; `training.log` records download and epoch progress.
Recovered transient errors are kept under `last_retry`, rather than appearing as
an active error on a successful completion.
Each model's `progress.json`, `best.pt`, `choices.jsonl`, `split.json` and
`report.json` preserve its progress, checkpoint, exact data and evaluation.

```powershell
$Sts2Run = Get-ChildItem artifacts/v0.111.0/silent-a10/workstation-* -Directory |
    Sort-Object Name -Descending | Select-Object -First 1
Get-Content (Join-Path $Sts2Run.FullName 'status.json')
Get-Content (Join-Path $Sts2Run.FullName 'training.log') -Tail 20 -Wait
# Request a stop after the current page or training stage:
New-Item (Join-Path $Sts2Run.FullName 'STOP') -ItemType File
```

The background process survives closing this terminal, but not shutdown or
sign-out. Re-running the launcher creates a new experiment and reuses raw data.
Avoid starting overlapping jobs against the same raw-data directory.

## Get the code and verify the CPU path

Prerequisites: Git and 64-bit CPython 3.12 installed with the `py` launcher. Run
these commands in PowerShell. Explicit Python paths avoid activation-policy
changes. Both environments below live inside the Git-ignored `.venv/` directory.

```powershell
git clone https://github.com/jagenmark/STS2ML.git
Set-Location STS2ML
py -3.12 -m venv .venv/cpu
$Sts2Python = ".\.venv\cpu\Scripts\python.exe"
& $Sts2Python -m pip install --upgrade pip
& $Sts2Python -m pip install "torch==2.14.0" --index-url https://download.pytorch.org/whl/cpu
& $Sts2Python -m pip install -e ".[dev]"
& $Sts2Python -m pip check
& $Sts2Python -m pytest -q
& $Sts2Python -m sts2rl doctor --device cpu --output artifacts/environment/doctor-cpu.json
& $Sts2Python -m sts2rl inspect-model
& $Sts2Python -m sts2rl demo --output artifacts/demo-cpu
& $Sts2Python -m sts2rl predict artifacts/demo-cpu/best.pt artifacts/demo-cpu/decision.json --device cpu
```

The CPU package index contains a CPython 3.12 Windows x64 wheel for this pinned
version. [PyTorch CPU wheel index](https://download.pytorch.org/whl/cpu/torch/).
The demo measures an invented rule; it is not an STS2 win-rate result. Both
`train` and `predict` default to `--device cpu`. The first doctor check works
offline without a game installation; omit `--game-root` and leave
`STS2_GAME_ROOT` unset for that check. `train` defaults to **SILENT / A10 /
v0.111.0**, so other datasets need explicit filter overrides.

For an existing checkout, save or commit local edits, then update without an
automatic merge:

```powershell
git status --short
git pull --ff-only
& $Sts2Python -m pip install -e ".[dev]"
```

## Optional native Windows GPU profile

AMD currently lists the RX 9070 XT as **gfx1201**, including native Windows
support. The ROCm **10.1.0** matrix specifies **Windows 11 25H2**, PyTorch
**2.14.0**, and Python **3.11–3.14**; use **3.12** here. Its matching Adrenalin
driver is **26.10.41.05** (Windows Driver Store **32.0.31041.5005**).
[AMD compatibility matrix](https://rocm.docs.amd.com/en/latest/compatibility/compatibility-matrix.html),
[AMD driver release and download](https://www.amd.com/en/resources/support-articles/release-notes/RN-RAD-ROCM-10-01.html).

First review and complete AMD's
[Windows prerequisites](https://rocm.docs.amd.com/en/latest/install/rocm.html#prerequisites),
including its existing-HIP-SDK/conflicting-software and Windows security-setting
requirements, and install the matched driver. Those system changes are manual;
the CPU profile needs none of them. The older Radeon documentation stops at
ROCm 7.2.1; do not combine its wheels or driver recipe with this profile.

Create a separate environment from the repository root. The architecture extra
selects gfx1201 kernels. STS2ML needs `torch`; AMD's broader recipe also installs
vision/audio packages, which this project does not use.
[AMD PyTorch installation](https://rocm.docs.amd.com/projects/ai-ecosystem/en/latest/frameworks/pytorch/install.html).

```powershell
py -3.12 -m venv .venv/rocm
$Sts2Python = ".\.venv\rocm\Scripts\python.exe"
& $Sts2Python -m pip install --upgrade pip
& $Sts2Python -m pip install --index-url https://stable.repo.amd.com/rocm/whl-next/ "torch[device-gfx1201]==2.14.0+rocm10.1.0"
& $Sts2Python -m pip install -e ".[dev]"
& $Sts2Python -m pip check
& $Sts2Python -c "import torch; print('torch:', torch.__version__, 'HIP:', torch.version.hip); assert torch.version.hip and torch.cuda.is_available(); print('GPU:', torch.cuda.get_device_name(0)); x=torch.randn(32,32,device='cuda:0',requires_grad=True); loss=(x@x).square().mean(); loss.backward(); torch.cuda.synchronize(); print('forward/backward:', loss.item())"
& $Sts2Python -m sts2rl doctor --device cuda:0 --output artifacts/environment/doctor-gpu.json
& $Sts2Python -m pytest -q
```

Verify the printed device is the RX 9070 XT. If an integrated GPU takes index 0,
inspect `torch.cuda.get_device_name(i)` for each index before choosing the device.
PyTorch deliberately uses `torch.cuda` and device **`cuda:0`** for HIP/ROCm too;
`hip:0` is not the device spelling. [PyTorch HIP semantics](https://docs.pytorch.org/docs/2.14/notes/hip.html).

An optional project-level GPU check uses only the synthetic dataset created by
the CPU demo:

```powershell
& $Sts2Python -m sts2rl train artifacts/demo-cpu/synthetic.jsonl --character DEMO --game-version synthetic-not-game-data --device cuda:0 --epochs 1 --d-model 64 --n-layers 2 --output artifacts/demo-rocm
```

A successful tensor check alone does not validate the entire training pipeline.
If this profile fails on another setup, select the existing CPU environment and continue with
`--device cpu`; no GPU troubleshooting is required to make data-pipeline progress.

## Native Windows and WSL2 are separate installations

The commands above install **Windows x64** packages. A WSL2 environment needs its
own Linux Python environment and Linux packages; do not share a virtual
environment between Windows and WSL2. AMD's ROCm 10.1.0 WSL2 route includes this
GPU, but is explicitly a **Technical Preview**, with Ubuntu **22.04.5, 24.04.5,
or 26.04.1**, and no GPU debugging/KFD-dependent tooling or profiling support.
Use AMD's selector for RX 9070 XT + WSL2 before choosing that route.
[AMD WSL2 installation and limitations](https://rocm.docs.amd.com/en/latest/install/rocm.html).
For this milestone, native Windows CPU first and optional native GPU keep the
handoff smaller.

## Optional installed-game diagnostics

Set the actual Steam library path on this desktop. For example, if the game is
under `D:\SteamLibrary\steamapps\common\Slay the Spire 2`:

```powershell
$env:STS2_GAME_ROOT = "D:\SteamLibrary\steamapps\common\Slay the Spire 2"
& .\.venv\cpu\Scripts\python.exe -m sts2rl doctor --device cpu --game-root $env:STS2_GAME_ROOT --output artifacts/environment/doctor-cpu.json
# Run this second command only after installing the optional GPU profile.
& .\.venv\rocm\Scripts\python.exe -m sts2rl doctor --device cuda:0 --game-root $env:STS2_GAME_ROOT --output artifacts/environment/doctor-gpu.json
```

Doctor saves device and game-fingerprint diagnostics. A successful report does
not certify beta compatibility or a working game bridge; that requires the
separate checks in [game integration](game-integration.md).

## Native headless setup and qualification on Windows

The PowerShell wrapper installs a checksum-verified local .NET 9.0.320 SDK,
pins the sts2-cli checkout, validates the installed game hash, copies/patches
only local ignored libraries, and builds Release. Git Bash is not required.

```powershell
./scripts/setup-headless.ps1
& .venv/cpu/Scripts/python.exe scripts/benchmark-headless.py --output artifacts/headless/new-check --runs 8 --workers 1 4
& artifacts/tools/dotnet/dotnet.exe run --project tests/native/Observations.csproj -c Release -- (Get-Location).Path
```

Use `-GameRoot` when Steam is installed elsewhere. Both runners isolate save
paths and retain their logs under `artifacts/headless/`. The
[headless evidence](headless-options.md) records Silent A10 early-loss episodes,
deterministic observations, and explicit relic counter / pile transitions.
The CPU suite now passes 122 tests, and the new combat-state encoder also passed
a forward/backward check on RX 9070 XT with real native observations.

The [first micro curriculum](micro-training.md) now adds combat actions, verified
replay forks, hidden-state sampling and Monte Carlo distillation for starter
Silent A10 against Shrinker Beetle. Whole-run parity and broader hidden-state
qualification remain open. Debug/scenario controls are experiment infrastructure,
never policy actions.

## Data and artifact handoff

Git transfers code, configuration, and documentation. Raw player data,
checkpoints, virtual environments, and game binaries are excluded from Git and
are not published with this repository. Obtain the game through Steam. Follow
[the data documentation](data.md) for public sources and import limitations, and
[game integration](game-integration.md) for the separate bridge work.

Transfer any existing local datasets/checkpoints separately, preserving the
source and exact patch in their directory names, for example:

```text
data/v0.111.0/silent-a10/raw/
data/v0.111.0/silent-a10/choices.jsonl
artifacts/v0.111.0/silent-a10/<experiment>/
```

Keep other patches in other directories. Audit imported data before training;
use its exact `game_version`, not a filename or website patch-group label. Keep
the import report, training report, split manifest, checkpoint, and source
metadata together. Record the checkout and resolved environment locally:

```powershell
New-Item -ItemType Directory -Force artifacts/environment | Out-Null
git rev-parse HEAD | Set-Content artifacts/environment/git-revision.txt
& $Sts2Python -m pip freeze | Set-Content artifacts/environment/packages.txt
& $Sts2Python -m torch.utils.collect_env | Set-Content artifacts/environment/torch-environment.txt
```

The Torch versions above are pinned profiles, not a complete dependency lock.
Keep these environment files with a result when comparing machines or devices.
On the Windows checkout, use `git pull --ff-only` before resuming work to get the
latest committed handoff.
