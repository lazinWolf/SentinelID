# Measured findings: corrected optional experiments

The only configuration meeting the predeclared **observed actual-cost criterion** is RF with temporal off, historical peers on and native detector ordering. It admits 30 investigations, of which 21 are current-positive (70%) and 24 contain labelled evidence; timely reach is 9/11. The corrected RF all-off control admits 30, with 17 current-positive (56.7%), 22 context-positive and 8/11 timely reach. This is a retrospective observation in consumed November, not independently validated improvement. The deployed model remains unchanged.

These findings use only the 16 corrected configurations in [the comparison](EXPERIMENT_COMPARISON.md) and [its measurements](experiment-comparison.json). Historical stages and correction effects are separately documented in [research history](../EXPERIMENT_HISTORY.md). No historical configuration contributes to an effect or criterion below.

## What the modules did

- **Temporal:** no consistent benefit. It reduced RF native all-off timely reach from 8 to 7 and current-positive investigations from 17 to 14. With native peers, reach stayed at 9 but actual admissions increased from 30 to 31. For IF, temporal alone reduced reach from 4 to 2; adding learned ordering restored 4, without exceeding the corrected control. The tested persistence/co-occurrence formulation needs further development.
- **Peers:** helped RF with native ordering, even though detector AP fell from 0.8022 to 0.7733 and gate recall stayed at 84/97. Its 36 additional and 20 removed gate-passing identity-days changed queue ordering and retained evidence. It recovered HJB0742's scenario-1 incident and kept all eight control hits. With learned ordering, peers reduced RF timely reach; their effect is conditional on ranking. Native IF peers reduced reach from 4 to 2.
- **Learned relevance ranking:** did not consistently improve either family. RF without extensions gained two current-positive investigations but no timely incident. With peers it lost two timely incidents and six current-positive investigations. It rescued some weak IF representations, but no IF cell exceeded the native corrected control's 4/11 timely reach. These IF variants use supervised assistance.
- **Combining everything:** RF reached 7/11 and IF 3/11. Enabling more modules did not produce better operational outcomes.

The corrected RF control's detector gate rejected 13 of 97 positive identity-days before ranking. IF rejected 80 of 97; its gate recall was 17.5%, versus RF's 86.6%. Across IF representations only 16–18 positive days passed. Ranking cannot repair these gate exclusions. Retained context may later rescue a record from a rejected day, so terminal event-loss counts do not form a monotone funnel.

RF native peers reached scenario counts 1/7/1 for scenarios 1/2/3, compared with the corrected control's 0/7/1. Temporal plus peers also reached nine, but exchanged HJB0742 for GHL0460 and required another admission. Equal incident totals therefore conceal disagreements.

## Interactions

For a module pair A/B, the conditional interaction is `Y11 − Y10 − Y01 + Y00`, keeping the third module fixed. These are descriptive integer differences, not uncertainty-adjusted effect estimates. Third-module 0 means off/native; 1 means on/learned.

| Family | Modules | Third module fixed | Admission interaction | Current-positive interaction | Timely interaction |
| --- | --- | --- | ---: | ---: | ---: |
| rf | temporal + peer | ranking=0 | +1 | +4 | +1 |
| rf | temporal + peer | ranking=1 | +1 | +1 | +0 |
| rf | temporal + ranking | peer=0 | +0 | +1 | +1 |
| rf | temporal + ranking | peer=1 | +0 | -2 | +0 |
| rf | peer + ranking | temporal=0 | -1 | -8 | -2 |
| rf | peer + ranking | temporal=1 | -1 | -11 | -3 |
| if | temporal + peer | ranking=0 | +0 | +0 | +1 |
| if | temporal + peer | ranking=1 | +0 | -3 | -2 |
| if | temporal + ranking | peer=0 | +0 | +2 | +3 |
| if | temporal + ranking | peer=1 | +0 | -1 | +0 |
| if | peer + ranking | temporal=0 | -1 | +3 | +3 |
| if | peer + ranking | temporal=1 | -1 | +0 | +0 |

The three-way interaction is the difference between the temporal/peer interaction under learned and native ordering: RF has admission/current-positive/timely interactions **0/−3/−1**; IF has **0/−3/−3**. In particular, ranking changes peer effects rather than providing an independent additive gain.

## Module and detector disagreements

Each row compares module-on against module-off, keeping other options fixed. Offers are gate-passing `(day, identity)` pairs; admissions are `(identity, decision timestamp)` pairs. `+ / − / shared` gives on-only/off-only/shared set sizes. Changes in timing count as admission differences. Ranking pairs have zero offer differences, as required, despite later queue differences.

| Family | Switch | On → off IDs | Offers + / − / shared | Admissions + / − / shared | Timely gained / lost |
| --- | --- | --- | --- | --- | --- |
| rf | ranking | db4562540608 → 4489fa7e9d74 | 0 / 0 / 161 | 20 / 20 / 10 | 0 / 0 |
| rf | peer_context | 04c1761b51d9 → 4489fa7e9d74 | 36 / 20 / 141 | 18 / 18 / 12 | 1 / 0 |
| rf | peer_context | 9373cbc8b9a6 → db4562540608 | 36 / 20 / 141 | 21 / 22 / 8 | 0 / 1 |
| rf | ranking | 9373cbc8b9a6 → 04c1761b51d9 | 0 / 0 / 177 | 24 / 25 / 5 | 0 / 2 |
| rf | representation_extension | 07e06ee61673 → 4489fa7e9d74 | 24 / 21 / 140 | 16 / 16 / 14 | 0 / 1 |
| rf | representation_extension | 2d883296899d → db4562540608 | 24 / 21 / 140 | 11 / 11 / 19 | 0 / 0 |
| rf | ranking | 2d883296899d → 07e06ee61673 | 0 / 0 / 164 | 20 / 20 / 10 | 1 / 0 |
| rf | representation_extension | 24b814565ca4 → 04c1761b51d9 | 25 / 27 / 150 | 10 / 9 / 21 | 1 / 1 |
| rf | peer_context | 24b814565ca4 → 07e06ee61673 | 42 / 31 / 133 | 24 / 23 / 7 | 2 / 0 |
| rf | representation_extension | 3a9bf14a9078 → 9373cbc8b9a6 | 25 / 27 / 150 | 22 / 21 / 8 | 0 / 0 |
| rf | peer_context | 3a9bf14a9078 → 2d883296899d | 42 / 31 / 133 | 26 / 26 / 4 | 0 / 1 |
| rf | ranking | 3a9bf14a9078 → 24b814565ca4 | 0 / 0 / 175 | 21 / 22 / 9 | 0 / 2 |
| if | ranking | b51d0c3e6a21 → 95632b1a090a | 0 / 0 / 213 | 24 / 23 / 8 | 0 / 1 |
| if | peer_context | 55cc4d1129dc → 95632b1a090a | 53 / 65 / 148 | 21 / 20 / 11 | 1 / 3 |
| if | peer_context | 9b8edede14cc → b51d0c3e6a21 | 53 / 65 / 148 | 29 / 29 / 3 | 1 / 0 |
| if | ranking | 9b8edede14cc → 55cc4d1129dc | 0 / 0 / 201 | 24 / 24 / 8 | 2 / 0 |
| if | representation_extension | 00017920b220 → 95632b1a090a | 47 / 64 / 149 | 20 / 21 / 10 | 0 / 2 |
| if | representation_extension | 8434f3e36ac2 → b51d0c3e6a21 | 47 / 64 / 149 | 22 / 23 / 9 | 1 / 0 |
| if | ranking | 8434f3e36ac2 → 00017920b220 | 0 / 0 / 196 | 23 / 22 / 8 | 2 / 0 |
| if | representation_extension | 03fbb814af9a → 55cc4d1129dc | 54 / 53 / 148 | 18 / 19 / 13 | 0 / 1 |
| if | peer_context | 03fbb814af9a → 00017920b220 | 58 / 52 / 144 | 21 / 20 / 10 | 0 / 1 |
| if | representation_extension | 6eabfcb5965c → 9b8edede14cc | 54 / 53 / 148 | 19 / 20 / 12 | 0 / 1 |
| if | peer_context | 6eabfcb5965c → 8434f3e36ac2 | 58 / 52 / 144 | 24 / 24 / 7 | 1 / 2 |
| if | ranking | 6eabfcb5965c → 03fbb814af9a | 0 / 0 / 202 | 20 / 20 / 11 | 2 / 0 |

## Priority diagnostic on its declared target

The main comparison reports priority AP against **current-positive eligible identity-days**, alongside detector AP. The following additional diagnostic evaluates the ranker's declared seven-day record-relevance target **among gate-passing offers only**. The cohort and target differ, so these AP values must not be compared directly with the main detector AP. They measure labelled evidence relevance, not analyst usefulness. No threshold or configuration was tuned using this diagnostic.

| Family / temporal / peer / ranking | Offers | Context-positive offers | Detector context AP | Priority context AP |
| --- | ---: | ---: | ---: | ---: |
| rf / off / off / detector_score | 161 | 101 | 0.9513 | 0.9513 |
| rf / off / off / relevance_v1 | 161 | 101 | 0.9513 | 0.8193 |
| rf / off / historical_v1 / detector_score | 177 | 103 | 0.9346 | 0.9346 |
| rf / off / historical_v1 / relevance_v1 | 177 | 103 | 0.9346 | 0.7887 |
| rf / temporal_v1 / off / detector_score | 164 | 95 | 0.9450 | 0.9450 |
| rf / temporal_v1 / off / relevance_v1 | 164 | 95 | 0.9450 | 0.8220 |
| rf / temporal_v1 / historical_v1 / detector_score | 175 | 102 | 0.9601 | 0.9601 |
| rf / temporal_v1 / historical_v1 / relevance_v1 | 175 | 102 | 0.9601 | 0.8304 |
| if / off / off / detector_score | 213 | 27 | 0.3757 | 0.3757 |
| if / off / off / relevance_v1 | 213 | 27 | 0.3757 | 0.2467 |
| if / off / historical_v1 / detector_score | 201 | 31 | 0.3822 | 0.3822 |
| if / off / historical_v1 / relevance_v1 | 201 | 31 | 0.3822 | 0.4734 |
| if / temporal_v1 / off / detector_score | 196 | 26 | 0.3644 | 0.3644 |
| if / temporal_v1 / off / relevance_v1 | 196 | 26 | 0.3644 | 0.2426 |
| if / temporal_v1 / historical_v1 / detector_score | 202 | 32 | 0.3018 | 0.3018 |
| if / temporal_v1 / historical_v1 / relevance_v1 | 202 | 32 | 0.3018 | 0.3354 |

## Verification and scope

- 33 dataset-free tests passed; lint and compilation passed.
- Five historical score arrays reproduced with maximum absolute error zero. Saved historical admissions and active RF cases reproduced without rewriting their artifacts.
- All eight native corrected configurations reproduced the maintained queue's cases and decisions exactly. All 16 persisted score arrays and independent case maxima/origin days matched their saved models and checkpoints.
- All eight ranker scalers matched only their chronological held-out training rows: 62,889 rows with 679 positive-context labels. Final detector fitting used 85,688 rows with 512 positive days. Evaluation labels are absent from the experimental training cache.
- A shared pass checked 2,236,607 source records, resolved all 77,482 required evidence pointers and reproduced counts for 63 representative real identity-days.
- 33 of 35 captured files remained byte-identical; the two declared source changes add the experiment CLI and queue sorting extension point. Active database, deployed model, frozen results, configuration, original sources, dashboard and recovery archive are unchanged.

Run identity: `abcd831c3f4e3171fa84`. Exact manifests, models, case evidence, per-event losses, scenarios, delays, set disagreements and preservation audits are under `data/experiments/abcd831c3f4e3171fa84/`. Its `effect-diagnostics.json` contains the set and interaction calculations above. See [reproduction commands](../EXPERIMENTS.md).

The result supports keeping optional experiments modular and treating peers as a promising conditional RF addition. It does not support deploying all modules, broad algorithm search or a validated improvement claim. No independent period is available in this corpus; deployment remains unchanged.
