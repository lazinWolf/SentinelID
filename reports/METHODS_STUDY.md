# Methods study: neural, sequence and graph detectors

Development folds August to November 2010 (expanding training window from 2010-06-08), feature set `c`, gate at the 0.99 quantile of each method's training scores, the maintained one-a-day queue. Specification, fixed before any result: [docs/methods-study.md](../docs/methods-study.md). The holdout is not used. Intervals are 95% paired bootstrap intervals (incident-folds for reach, test days for average precision); the baseline is `rf`.

## Ranking and reach (61 incident-folds)

| Method | Family | Avg. precision [95%] | vs RF [95%] | ROC-AUC | Incidents reached [95%] | vs RF [95%] |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `rf` | supervised tree | 0.832 [0.799, 0.862] | — | 0.990 | 44.3 [38.3, 50.0] | — |
| `if` | unsupervised | 0.129 [0.107, 0.163] | -0.703 [-0.734, -0.659] worse | 0.937 | 22.3 [15.7, 29.3] | -22.0 [-30.3, -13.0] worse |
| `ecod_top5` | unsupervised | 0.176 [0.149, 0.219] | -0.656 [-0.687, -0.610] worse | 0.953 | 28.0 [21.0, 35.0] | -16.3 [-25.7, -7.7] worse |
| `mlp` | supervised neural | 0.770 [0.732, 0.804] | -0.062 [-0.082, -0.043] worse | 0.970 | 44.7 [38.3, 50.7] | +0.3 [-4.7, +5.7] matches |
| `autoencoder` | unsupervised neural | 0.181 [0.159, 0.218] | -0.650 [-0.682, -0.608] worse | 0.957 | 21.3 [15.3, 28.0] | -23.0 [-30.3, -15.0] worse |
| `gru` | supervised sequence | 0.840 [0.812, 0.866] | +0.008 [-0.023, +0.041] matches | 0.992 | 35.3 [28.7, 42.0] | -9.0 [-15.0, -3.7] worse |
| `gru_next` | unsupervised sequence | 0.097 [0.083, 0.122] | -0.734 [-0.764, -0.695] worse | 0.942 | 19.0 [12.3, 26.7] | -25.3 [-34.0, -16.3] worse |
| `edge` | unsupervised graph | 0.044 [0.034, 0.059] | -0.787 [-0.821, -0.748] worse | 0.728 | 9.0 [4.0, 15.0] | -35.3 [-43.0, -27.3] worse |
| `graphsage` | unsupervised graph | 0.023 [0.016, 0.035] | -0.808 [-0.840, -0.773] worse | 0.550 | 7.3 [3.7, 12.0] | -37.0 [-43.7, -29.7] worse |

## Budget curves and queue cost

Recall at k is the share of malicious identity-days ranked in the top k of their own day (before the gate and queue). Investigations and current-positive yield are through the queue.

| Method | Recall@1 | Recall@2 | Recall@5 | Recall@10 | Over gate | Investigations | Yield |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `rf` | 0.190 | 0.361 | 0.726 | 0.850 | 791 | 122.0 | 73% |
| `if` | 0.075 | 0.116 | 0.180 | 0.258 | 807 | 128.0 | 21% |
| `ecod_top5` | 0.068 | 0.120 | 0.243 | 0.354 | 790 | 124.0 | 29% |
| `mlp` | 0.180 | 0.345 | 0.691 | 0.805 | 715 | 124.3 | 69% |
| `autoencoder` | 0.078 | 0.134 | 0.241 | 0.383 | 895 | 128.7 | 23% |
| `gru` | 0.184 | 0.352 | 0.714 | 0.911 | 848 | 116.0 | 72% |
| `gru_next` | 0.061 | 0.093 | 0.148 | 0.217 | 862 | 128.7 | 17% |
| `edge` | 0.015 | 0.036 | 0.063 | 0.129 | 14011 | 130.0 | 8% |
| `graphsage` | 0.015 | 0.027 | 0.049 | 0.077 | 837 | 126.0 | 6% |

## Reach by scenario

Mean incident-folds reached within 72 hours per scenario; for the takeover (scenario 3), split by the attacker's own account and the hijacked account.

| Method | Scenario 1 | Scenario 2 | Scenario 3 | Takeover: attacker | Takeover: hijacked |
| --- | ---: | ---: | ---: | ---: | ---: |
| `rf` | 11.3 | 30.0 | 3.0 | 3.0 | 0.0 |
| `if` | 9.0 | 10.7 | 2.7 | 2.7 | 0.0 |
| `ecod_top5` | 8.0 | 18.0 | 2.0 | 2.0 | 0.0 |
| `mlp` | 13.3 | 27.3 | 4.0 | 4.0 | 0.0 |
| `autoencoder` | 11.3 | 10.0 | 0.0 | 0.0 | 0.0 |
| `gru` | 6.3 | 28.0 | 1.0 | 1.0 | 0.0 |
| `gru_next` | 9.7 | 6.7 | 2.7 | 2.0 | 0.7 |
| `edge` | 3.0 | 2.0 | 4.0 | 4.0 | 1.0 |
| `graphsage` | 4.0 | 0.0 | 3.3 | 3.3 | 0.0 |

Reading rule (fixed in the specification): a method matches the baseline when the interval of its difference contains 0, and is better or worse when the whole interval is above or below 0. With eight comparisons a single better or worse is a lead, not a finding.
