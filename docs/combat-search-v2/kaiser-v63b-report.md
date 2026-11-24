# Silent A10 Kaiser v63b

**CSV8DEV produced two Kaiser clears in 29 identical openings for each policy (6.9%).** v63b gained one clear and lost another. Each arm cleared Act 2 in 22 of 384 starts. Act 3 boss entries fell from six to five. The paired mean floor difference was −0.031, with a 95% interval from −0.125 to +0.031. On the historical diagnostic, v63b cleared 8/85 against 9/85 for v63. The measurements do not establish a progression gain.

Pre-turning increased on the historical openings, from 7/175 to 29/172 eligible big-hit rounds. In the fresh cohort it fell from 4/61 to 3/61. Rocket’s big attacks were Weakened slightly more often in the fresh cohort, from 25/64 to 26/62. Legacy fallback still directed roughly two-thirds of its targeted attacks at Crusher.

## Paired outcomes

| Metric | Historical v63 | Historical v63b | Fresh v63 | Fresh v63b |
|---|---:|---:|---:|---:|
| Lobbies | 85 | 85 | 384 | 384 |
| Kaiser clears / entries | 9/85 (10.6%) | 8/85 (9.4%) | 2/29 (6.9%) | 2/29 (6.9%) |
| Kaiser covered / eligible decisions | 1116/2223 (50.2%) | 1128/2258 (50.0%) | 410/815 (50.3%) | 409/802 (51.0%) |
| Player exit HP, mean / median (all Kaiser entries) | 1.588 / 0 | 1.494 / 0 | 0.862 / 0 | 1.207 / 0 |
| Median living enemy HP on Kaiser deaths | 266.0 | 253 | 252 | 261 |
| Executed Rocket big attacks faced | 179/184 (97.3%) | 170/175 (97.1%) | 63/64 (98.4%) | 59/62 (95.2%) |
| Already facing Rocket at round opening, both arms alive | 7/175 (4.0%) | 29/172 (16.9%) | 4/61 (6.6%) | 3/61 (4.9%) |
| Rocket big attacks Weakened (including solo) | 87/184 (47.3%) | 82/175 (46.9%) | 25/64 (39.1%) | 26/62 (41.9%) |
| Executed Rocket big attacks, Precision Beam / Laser | 105 / 79 | 97 / 78 | 35 / 29 | 34 / 28 |
| Big attacks on turns beginning with Rocket alone | 9 | 3 | 3 | 1 |
| Legacy fallback attacks, Crusher / Rocket | 292 / 187 (39.0% Rocket) | 292 / 192 (39.7% Rocket) | 107 / 59 (35.5% Rocket) | 107 / 57 (34.8% Rocket) |
| Mean global floor | 34.259 | 34.153 | 24.380 | 24.349 |
| Act 2 boss entries | 85 | 85 | 103 | 103 |
| Act 2 clears | 9 | 8 | 22 | 22 |
| Knowledge Demon clears / entries | — | — | 12/38 (31.6%) | 12/38 (31.6%) |
| The Insatiable clears / entries | — | — | 8/36 (22.2%) | 8/36 (22.2%) |
| Act 3 boss entries | 4 | 4 | 6 | 5 |
| Full wins | 0 | 0 | 0 | 0 |
| Decision latency p50 / p95, ms | 3.138 / 66.774 | 3.105 / 66.063 | 2.918 / 57.608 | 2.915 / 57.767 |
| Native matches / mismatches / unresolved | 19,066 / 0 / 1,850 | 19,020 / 0 / 1,831 | 70,085 / 13 / 6,362 | 70,062 / 13 / 6,319 |
| Kaiser native mismatches | 0 | 0 | 0 | 0 |
| Paired mean floor Δ [95% CI] | — | -0.106 [-0.388, +0.118] | — | -0.031 [-0.125, +0.031] |
| Floor W/L/T, exact sign p | — | 1/2/82, 1 | — | 1/1/382, 1 |

The diagnostic reuses the 45 AUDIT384 and 40 CSV7DEV natural Kaiser entrants. Both policies replayed each lobby from the beginning. CSV8DEV includes all 384 natural starts, including early deaths. Both arms saw identical public boss openings within each panel.

Facing and Weak both use all native Precision Beam and Laser moves actually executed, including solo Rocket. The pre-turn row uses the subset with both arms alive at the start of that round. The replay records orientation before the first player decision. Recording the move on execution excludes preempted attacks. The fallback split counts executed explicitly targeted Attack cards with both arms alive and multiple legal choices when search returned the legacy proposal.

Exit HP includes zero on death. Remaining enemy HP uses the last public board before the fatal action. Coverage counts accepted searches among physical Kaiser decisions with multiple legal actions. Latency pools all physical combat decisions. The 95% percentile interval resamples complete seed pairs within start mode 50,000 times with analysis RNG 621. The two-sided exact sign test drops ties.

## Verified public cycles

| Round in repeating cycle | Crusher | Rocket |
|---|---|---|
| 1 | Thrash 14 | Targeting Reticle 4 |
| 2 | Enlarging Strike 4 | Precision Beam 20 |
| 3 | Bug Sting 7×2 and Debuff | Charge Up, +3 Strength |
| 4 | Adapt, +3 Strength | Laser 35 |
| 5 | Guarded Strike 14 and Defend | Recharge, Sleep |

These are A10 base values before Strength, Weak and facing. The move-state constructors and follow-up edges in the pinned game library agree with the graphs archived at 902623e. A six-round pinned-host fixture covers the cycle wrapping and the Strength-adjusted previews.

## Search changes

Set `kaiser_v63b` to `true` in the Arm 4 search configuration to enable the treatment. The default-off flag applies the v63 mechanics to late Act 2 boss roots containing only Kaiser arms. At a completed leaf the simulated round has advanced once, enemy Weak has ticked and any current-turn Strength gain has resolved. The scorer locates the old move from the public combat round and checks its intent kinds. An unrecognized intent earns no successor credit. Interim beam ranking uses the same successor calculation, accounting for the still-pending tick and buff. The scorer reads neither a future hand nor a future native intent.

Each remaining Weak stack covering an attack earns 25% of its forecast damage, or 40% with an active Paper Krane. The second turn receives half weight. Damage includes per-hit Strength, scheduled buffs, public Vulnerable, and 1.5× rear damage when Surrounded. A turn covered by Intangible receives zero future-defense credit. The fractional estimate follows the specified formula before native per-hit integer rounding.

The rear attacker incurs 75% of its extra half-hit exposure next turn. The discount reflects the option of retargeting next turn, while the existing current-HP term still contributes four points per HP. A width-two search test checks a free turn toward Rocket, an expensive turn that loses current HP, and the turn back toward Crusher before Recharge.

Focus rewards Rocket’s damage and projected poison progress. Crusher earns an extra finishing bonus across its last 30 effective HP when Rocket has more than 45 additional effective HP. The bonus ramps continuously with the HP gap and is capped at 1.5 points per finishing HP before the existing 0.45 focus coefficient. Both arms still receive ordinary damage and poison value.

## Qualification

**Kaiser recorded zero native mismatches on both panels. The all-combat zero-mismatch target failed on CSV8DEV.** Each arm recorded 13 mismatches in the same non-Kaiser lobby, CSV8DEV_DEFAULT_0032. The native Ornamental Fan counter stayed at 1 during attacks and across End Turn. The frozen simulator predicted increments or resets. Four discrepancies occurred in The Obscura fight and nine in Hunter Killer. The checkout at f8e0b00 reproduced all 13 step indices, predictions, observed differences, and before/after hashes on the identical command transcript. Across 140,173 comparable physical steps the two CSV8DEV arms made 140,147 matches and 26 raw mismatches. Two starts per arm had no comparable steps and are included in progression.

All 355 non-Kaiser pairs matched on every executed command, step count, native outcome, Act/floor and late-fight exit. Of their full raw pre-action board transcripts, 353/355 were byte-identical. The two exceptions had different public entrant numbers in The Trial event on two consecutive prompts each. In CSV8DEV_DEFAULT_0095 the numbers were 980 and 788. In CSV8DEV_SEEDED_0115 they were 860 and 745. Substituting each original number into the same reference boards exactly reproduced each arm’s original SHA-256. The archive includes the reference digest streams and both affected event boards for independent verification. All four raw transcript hashes are retained.

CSV8DEV SHA-256 is `84fe749806766c98e525e695f7f421f01697cfb99024bd8eaff8cfa04f9f969e`. The policy and lock were committed at `fd92ef6d209a41603b49725b3ea7c2a8af793ec2` before the first fresh lobby. The registry audit found zero name or xxHash64 collisions against 65,735 historical or reserved identifiers. Each mode contributed 192 starts. The two arms alternated execution order by index. Both used the pinned v0.111.0 host, 12 workers, and one BLAS and OpenMP thread each.

All ten challenger files matched the efd9877 Git blobs byte-for-byte. Arm 4 rebuilt to `4b5fe32e78a96ca656cca805f316410b19baa9c4f2c227d25b77a6d1306c93a9`. All 85 v63 historical command transcripts, opening hashes, native counters, exits and coverage matched f8e0b00 receipts. The 24 flags-off, 24 active-v5 and 24 shadow CSV2DEV receipts matched the historical full-transcript hashes. The hidden-draw fixture produced different native hands and identical root choices, root scores, fallback decisions and expansion counts.

Pytest reported **621 passed, 1 skipped in 330.56s (0:05:30)**. The guard skipped the archived native fixture that requests FINAL768_DEFAULT_0037. A fresh poison-before-Defend fixture covers its event ordering. Ruff checked 115 Python files under src and tests with zero findings.

## Reproduction

With the pinned CPU interpreter, runtime links, CSV2DEV_HOST, src and the probes directory on PYTHONPATH, run the following from the repository root. Use an empty output directory for each collector.

~~~powershell
python docs/combat-search-v2/probes/kaiser_v63b.py diagnostic artifacts/experiment/diagnostic --workers 12
python docs/combat-search-v2/probes/kaiser_v63b.py dev artifacts/experiment/dev --workers 12
$project = 'docs/combat-search-v2/probes/kaiser_attack_observer/KaiserAttackObserver.csproj'
& ./artifacts/tools/dotnet/dotnet.exe build $project --artifacts-path "$PWD/artifacts/experiment/observer" "-p:GameLib=$PWD/artifacts/upstreams/sts2-cli/lib"
$observer = 'artifacts/experiment/observer/bin/KaiserAttackObserver/debug/KaiserAttackObserver.dll'
python docs/combat-search-v2/probes/kaiser_attack_replay.py diagnostic artifacts/experiment/diagnostic $observer --workers 12
python docs/combat-search-v2/probes/kaiser_attack_replay.py dev artifacts/experiment/dev $observer --workers 12
python docs/combat-search-v2/probes/report_kaiser_v63b.py docs/combat-search-v2/kaiser-v63b-receipts.zip
~~~

The online collector uses the unmodified pinned host. A second command-only replay observes the two executed Rocket move methods, reads current facing and Weak, and verifies the complete command transcript and pre-action public boards against the first run. Where The Trial rerolls its entrant number, the replay reconstructs the original raw hash using the original displayed number. The compact archive includes per-lobby counts and timings, per-hit observations, raw mismatch evidence, fixture guard, compatibility receipts, and registry proof.

[Machine-readable results](kaiser-v63b.json) · [Compact receipts](kaiser-v63b-receipts.zip) · [Cohort lock](csv8dev-lock.json)
