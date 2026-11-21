# Silent A10 Act 3 encounters

This study follows Silent from the normal seeded lobby to the first and second Act 3 bosses and the native victory screen on the pinned public beta v0.111.0, game revision `41cef1ea`. It compares the previous boss-conversion checkpoint with two policies whose decisions first change in Act 3.

| Bundle in the archive | What changes in a run |
| --- | --- |
| `models/incumbent/policy.json` | Previous boss-conversion policy |
| `models/combat/policy.json` | Chooses a combat plan from the visible enemies, HP, potions and opening combat features in ordinary and elite fights |
| `models/route/policy.json` | Uses game-observed survival and resource changes in Act 3 map decisions |

## How the policies were selected

Training used 21 natural Act 3 maps. Alternative routes on those maps supplied additional elite fights. The combat fit used a signed inventory of matched native fight outcomes. Model development used 14 separate Act 3 maps, including eight arrivals from a newly registered batch of 1,024 standard lobbies. The route model learned from 225 ordinary map rooms, 37 elite rooms and 194 question-mark rooms. Multiple room visits can come from the same seed. [Selection and checkpoint hashes](selection.json) · [All screened candidates](screening.json)

The main test registered 4,096 previously unused starting seeds. A separate 2,048-seed test compared both challengers with the incumbent. Every incumbent game started in the native lobby. Each challenger replayed every Act 3 arrival from the original lobby and 64 additional earlier losses per cohort. All other earlier losses share the incumbent trajectory because the changed policy first acts in Act 3. The paired reports check identical Act 3 entry histories, the first changed action and native terminal results on a second build. [Main protocol](protocol.json) · [Main seed registry](seed-lock.json) · [Routing seed registry](route-seed-lock.json)

The native Glory act draws two weak encounters before switching to its regular pool. It counts actual normal draws, including ordinary fights behind a question mark. Elites draw separately. A pool-aware router and a forecast of the next enemy attack were also tested on training and development maps. The measured room-cost policy and formation-dependent combat policy were selected for the natural tests. A training-only search found a reproducible Soul Nexus win from 66 HP with 8 HP remaining. The archive contains the opening and the complete action sequence. [Training findings](training-findings.json)

## Restore and continue on Helmer

Check out the release tag to use the matching feature, inference and trainer code. Run the following from the repository root in an existing Python 3.11+ project environment. The archive carries the three complete model bundles, physical training and development maps, native labels, route observations and the two benchmark cohorts. Each file has a SHA-256 entry in the manifest.

```powershell
git fetch origin --tags
git switch --detach silent-a10-act3-encounters-20261121
gh release download silent-a10-act3-encounters-20261121 --repo jagenmark/STS2ML --pattern silent-a10-act3-encounters.zip
$env:PYTHONPATH = (Resolve-Path src).Path
python scripts/archive-act3-encounters.py verify --archive silent-a10-act3-encounters.zip --refit
python -m zipfile -e silent-a10-act3-encounters.zip artifacts/act3-training-state
```

Use a local Steam installation of the pinned game and the corrected headless host to simulate fights. The Helmer study uses the previously built `artifacts/a10-conversion-20261121/runtime/src/Sts2Headless/bin/Curriculum/net9.0/Sts2Headless.dll` under the main project and the CPU Python environment in `artifacts/act2-hallways-20261120/venv`. On a prepared Linux checkout, `python scripts/build-silent-host.py --output artifacts/act3-host` builds the compatible host. [Workstation setup](../../docs/silent-a10-handoff.md) · [Corrected native host](../silent-a10-boss-conversion/README.md)

To compare a new policy across the 21 training maps, set `$gameHost` to the DLL on your machine. Choose a new output directory per experiment.

```powershell
$state = "artifacts/act3-training-state"
python scripts/study-act2-preparation.py --act 3 --openings "$state/training/train-maps" --bundles "$state/models/incumbent/policy.json" "$state/models/combat/policy.json" --host $gameHost --workers 4 --output artifacts/new-act3-training
```

For a fresh natural A10 batch, supply a new seed prefix and the complete bundle you want to evaluate.

```powershell
python scripts/optimize-silent.py evaluate --bundle "$state/models/combat/policy.json" --host $gameHost --roles candidate --seeded-acts --prefix MY_NEW_ACT3_ --seeds 64 --workers 4 --record-rooms --output artifacts/new-act3-lobbies
```

Training-only inputs are under `training` and `room-observations`. The paired test fights, original natural histories and independent replay receipts are under `evaluation`. Reserve both published test registries when fitting future policies. [Download](https://github.com/jagenmark/STS2ML/releases/tag/silent-a10-act3-encounters-20261121)
