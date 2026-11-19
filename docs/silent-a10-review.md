# Silent A10 review of ed722b6

This investigation used the November 19 release, the policy code at `ed722b6` and the v0.111.0 native host. The benchmark and training archives retain their original bytes. [Release](https://github.com/jagenmark/STS2ML/releases/tag/silent-a10-2026-11-19)

## Combat decisions

| Case | Observation |
|---|---|
| Dexterity | In a controlled native fight, Silent drank a Dexterity Potion for +2. Defend showed 7 block and granted 7. The base policy and turn planner both valued the play at 9 block. In a restored training fight, Defend with +1 Dexterity showed and granted 6. |
| Neutralize against Artifact | In the synthetic case with 10 HP, 12 incoming damage and one Artifact stack, the planner projected a loss of 9 HP after Neutralize. The base policy credited 3 mitigation. In a separate native continuation against Aeonglass, the last Artifact stack was consumed, Weak stayed at zero and the intended damage stayed at 24. |
| Nightmare | From the same restored training hand, the base policy selected Ascender’s Bane. The encounter policy and released challenger selected Dagger Throw. The next hands contained three copies of Ascender’s Bane or four Dagger Throws respectively, including the ordinary draw. |
| Empty intents | With a synthetic living enemy exposing `intents: null`, the ordinary episode runner recorded a `TypeError` with `deck_effects` enabled. The control episode completed with the option off. The native exporter can emit null for an empty intent list. Both frozen benchmark bundles have this option off. |

The Dexterity and Nightmare training opening was action 216 of `H2A10BIOMETRAIN0011`. The Artifact check continued from action 656 of `H2A10NEXTTRAIN0185`. These branches measure individual actions. The frozen challenger routes combat through its encounter policy, with hand search disabled in that policy. The named turn planner also supplies labels to other experiments. [Base scorer](https://github.com/jagenmark/STS2ML/blob/ed722b6/src/sts2rl/run_policy.py#L165) · [Turn planner](https://github.com/jagenmark/STS2ML/blob/ed722b6/src/sts2rl/turn_planning.py#L108) · [Episode routing](https://github.com/jagenmark/STS2ML/blob/ed722b6/src/sts2rl/run_evaluation.py#L212) · [Native intent exporter](https://github.com/wuhao21/sts2-cli/blob/fec723a21741a1a33a4f54dc9b28c50df31d6e45/src/Sts2Headless/RunSimulator.cs#L2175)

## Return-model feature weights

All **1,374 archived return-training decisions from 229 seeds** restored to their expected native state hashes. On each decision we regenerated the shortlist and compared every ordered action token and feature value with the saved input.

| Feature weights | Exact matches with the saved input |
|---|---:|
| `incumbent/weights.json` | **1,374 / 1,374** |
| Weights embedded in the experimental `checkpoints/returns/returns.pt` | **103 / 1,374** |

The embedded weights equal `challenger/weights.json`. In 1,271 decisions the input differed, and in ten the ordered list of action tokens also differed. The fit command accepted the data with a deliberately different weight file through model construction. The two frozen benchmark policies omit this experimental return adviser. [Collector and fit](https://github.com/jagenmark/STS2ML/blob/ed722b6/scripts/train-silent-returns.py#L85) · [Inference](https://github.com/jagenmark/STS2ML/blob/ed722b6/src/sts2rl/return_policy.py#L98)

For a historical refit on the release tag, the matching feature weights are `artifacts/silent-a10-progression-release/incumbent/weights.json` (SHA-256 `33bd1adb134e681f2b5a9bb217d02be195ad57ff1d4b387072148d72adf438e5`).

## Label versions and seed selection

DAgger accepted ten synthetic episodes labeled with the v2 continuation alongside ten new episodes labeled v3. They passed aggregation, seed-split checks and fit input validation. The probe stopped before parameter updates. DAgger checks the sampler, ascension, macro weights, game assembly and dataset integrity. These checks allow different teacher continuations to coexist. [Aggregation checks](https://github.com/jagenmark/STS2ML/blob/ed722b6/src/sts2rl/aggregation.py#L41) · [Fit input checks](https://github.com/jagenmark/STS2ML/blob/ed722b6/src/sts2rl/micro.py#L173)

Using the released `development-openings/act-2` pool, training and `check-late` scheduled the same **15 of 15 seed and action-history pairs** with different prefixes. Conditional scheduling sorts archived seeds and takes the requested count. In a separate check, the **384 distinct full-run benchmark seeds and 1,536 archived room-training seeds shared zero IDs**. [Conditional selection](https://github.com/jagenmark/STS2ML/blob/ed722b6/scripts/optimize-silent.py#L98) · [Full-run benchmark protocol](silent-a10-progression.md)

## Corrections on the development branch

The base policy and turn planner use the native block preview. Both estimated 7 block for a Defend that granted 7 with +2 Dexterity. With 10 HP, 12 incoming and one Artifact stack, Neutralize leaves 12 incoming. The planner tracks each enemy’s remaining Artifact across plays. These corrections shipped in MC continuation v4. Nightmare copied Dagger Throw on the restored training hand, and the optional deck-effects policy accepted an enemy with null intents. The subsequent v5 continuation also handles the Waterfall Giant's delayed explosion. [Native Giant checks](silent-a10-act1-forecasts.md#how-the-giants-explosion-works)

New MC, planner and return labels carry their teacher and feature identities as applicable. Aggregation and fitting check the recorded code and weights. A fresh v4 native collection produced five decisions. A separate return collection produced 64 roots on 32 seeds and completed a one-epoch fit and three native games. Changing the feature weights or supplying the unversioned archived labels failed before training.

Conditional training and evaluation now save disjoint seed lists with native opening digests. The 82 fixed-biome Act 2 openings split into 58 training and 24 test seeds. Native collection and evaluation each completed 15 continuations using the same lock, with zero shared seeds. These are previously explored development openings. Fresh full games still supply the independent benchmark.

The current loader recognizes the original experimental return checkpoint by its SHA-256 and reconstructs its historical inputs with the incumbent feature weights. A standalone checkpoint also carries those weights for use on the release tag. For **both** files, the ordered action tokens and feature vectors matched **1,374/1,374** restored decisions on **229 seeds**. [Cross-machine instructions and checkpoint](silent-a10-handoff.md#experimental-return-adviser)
