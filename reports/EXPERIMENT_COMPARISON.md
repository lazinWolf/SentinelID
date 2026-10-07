# Corrected optional-module experiment

All results are retrospective on consumed November. Historical results are excluded from these tables and module effects. No independent validation or deployment change.

## RF

| Temporal | Peer | Ranking | Detector AP | Gate recall | Admissions | Current + | Context + | Timely / 11 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| off | off | detector_score | 0.8022 | 0.866 | 30 | 17 | 22 | 8/11 |
| off | off | relevance_v1 | 0.8022 | 0.866 | 30 | 19 | 23 | 8/11 |
| off | historical_v1 | detector_score | 0.7733 | 0.866 | 30 | 21 | 24 | 9/11 |
| off | historical_v1 | relevance_v1 | 0.7733 | 0.866 | 29 | 15 | 19 | 7/11 |
| temporal_v1 | off | detector_score | 0.7580 | 0.825 | 30 | 14 | 21 | 7/11 |
| temporal_v1 | off | relevance_v1 | 0.7580 | 0.825 | 30 | 17 | 20 | 8/11 |
| temporal_v1 | historical_v1 | detector_score | 0.7894 | 0.825 | 31 | 22 | 26 | 9/11 |
| temporal_v1 | historical_v1 | relevance_v1 | 0.7894 | 0.825 | 30 | 14 | 19 | 7/11 |

## IF

| Temporal | Peer | Ranking | Detector AP | Gate recall | Admissions | Current + | Context + | Timely / 11 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| off | off | detector_score | 0.0772 | 0.175 | 31 | 4 | 7 | 4/11 |
| off | off | relevance_v1 | 0.0772 | 0.175 | 32 | 4 | 6 | 3/11 |
| off | historical_v1 | detector_score | 0.0738 | 0.186 | 32 | 2 | 6 | 2/11 |
| off | historical_v1 | relevance_v1 | 0.0738 | 0.186 | 32 | 5 | 8 | 4/11 |
| temporal_v1 | off | detector_score | 0.0701 | 0.165 | 30 | 3 | 7 | 2/11 |
| temporal_v1 | off | relevance_v1 | 0.0701 | 0.165 | 31 | 5 | 7 | 4/11 |
| temporal_v1 | historical_v1 | detector_score | 0.0629 | 0.186 | 31 | 1 | 4 | 1/11 |
| temporal_v1 | historical_v1 | relevance_v1 | 0.0629 | 0.186 | 31 | 3 | 7 | 3/11 |

## Paired module effects

Each on/off pair holds the other switches fixed. Interactions are visible when a switch changes outcomes differently under the other enabled modules.

| Family | Switch | On configuration | Off configuration | Admission Δ | Current-positive Δ | Timely Δ |
| --- | --- | --- | --- | ---: | ---: | ---: |
| rf | ranking | db4562540608 | 4489fa7e9d74 | +0 | +2 | +0 |
| rf | peer_context | 04c1761b51d9 | 4489fa7e9d74 | +0 | +4 | +1 |
| rf | peer_context | 9373cbc8b9a6 | db4562540608 | -1 | -4 | -1 |
| rf | ranking | 9373cbc8b9a6 | 04c1761b51d9 | -1 | -6 | -2 |
| rf | representation_extension | 07e06ee61673 | 4489fa7e9d74 | +0 | -3 | -1 |
| rf | representation_extension | 2d883296899d | db4562540608 | +0 | -2 | +0 |
| rf | ranking | 2d883296899d | 07e06ee61673 | +0 | +3 | +1 |
| rf | representation_extension | 24b814565ca4 | 04c1761b51d9 | +1 | +1 | +0 |
| rf | peer_context | 24b814565ca4 | 07e06ee61673 | +1 | +8 | +2 |
| rf | representation_extension | 3a9bf14a9078 | 9373cbc8b9a6 | +1 | -1 | +0 |
| rf | peer_context | 3a9bf14a9078 | 2d883296899d | +0 | -3 | -1 |
| rf | ranking | 3a9bf14a9078 | 24b814565ca4 | -1 | -8 | -2 |
| if | ranking | b51d0c3e6a21 | 95632b1a090a | +1 | +0 | -1 |
| if | peer_context | 55cc4d1129dc | 95632b1a090a | +1 | -2 | -2 |
| if | peer_context | 9b8edede14cc | b51d0c3e6a21 | +0 | +1 | +1 |
| if | ranking | 9b8edede14cc | 55cc4d1129dc | +0 | +3 | +2 |
| if | representation_extension | 00017920b220 | 95632b1a090a | -1 | -1 | -2 |
| if | representation_extension | 8434f3e36ac2 | b51d0c3e6a21 | -1 | +1 | +1 |
| if | ranking | 8434f3e36ac2 | 00017920b220 | +1 | +2 | +2 |
| if | representation_extension | 03fbb814af9a | 55cc4d1129dc | -1 | -1 | -1 |
| if | peer_context | 03fbb814af9a | 00017920b220 | +1 | -2 | -1 |
| if | representation_extension | 6eabfcb5965c | 9b8edede14cc | -1 | -2 | -1 |
| if | peer_context | 6eabfcb5965c | 8434f3e36ac2 | +0 | -2 | -1 |
| if | ranking | 6eabfcb5965c | 03fbb814af9a | +0 | +2 | +2 |

## Interpretation

A shared daily cap does not match actual admissions. The recorded criterion requires no greater admissions, higher timely reach and nonlower current-positive yield relative to the corrected family control. Any satisfaction is an observed retrospective result, not independently validated improvement.

IF with relevance ranking uses supervised training labels. Native IF fitting remains label-free. Priority AP and forced daily rankings are diagnostics; the detector alone controls the gate. Event loss counts are terminal evidence assignments, not a monotone funnel.

Full per-configuration delays, scenario breakdowns, ranking diagnostics and losses are in the JSON comparison and isolated experiment outputs. Cases retain original evidence, not exact forest-event attribution.


RF representation_extension: timely reach increased in 0/4 paired settings, decreased in 1/4, and was unchanged in 3/4. Admission deltas ranged from +0 to +1.

RF peer_context: timely reach increased in 2/4 paired settings, decreased in 2/4, and was unchanged in 0/4. Admission deltas ranged from -1 to +1.

RF ranking: timely reach increased in 1/4 paired settings, decreased in 2/4, and was unchanged in 1/4. Admission deltas ranged from -1 to +0.

IF representation_extension: timely reach increased in 1/4 paired settings, decreased in 3/4, and was unchanged in 0/4. Admission deltas ranged from -1 to -1.

IF peer_context: timely reach increased in 1/4 paired settings, decreased in 3/4, and was unchanged in 0/4. Admission deltas ranged from +0 to +1.

IF ranking: timely reach increased in 3/4 paired settings, decreased in 1/4, and was unchanged in 0/4. Admission deltas ranged from +0 to +1.