# Methods study: specification

Written and committed before any result of this study existed. Hyperparameters, metrics and reading rules below are fixed; the results report cites the commit that added this file.

## Question

How do neural, sequence and graph methods compare with the project's existing detectors (Random Forest, Isolation Forest, ECOD top-5), on the same identity-days, folds, gate rule and one-investigation-a-day queue?

This is a descriptive comparison. Nothing in it is promoted to the deployed model or the app, whatever the outcome.

## Data and protocol

- Rows: the prepared research vectors (`data/research/prepared/vectors.npz`), feature set `c` (33 inputs, each relative to the identity's own history).
- Folds: the four development months, 2010-08 to 2010-11. Each model is fitted on rows from 2010-06-08 to the day before the fold starts (an expanding window) and scored on the fold.
- Labels: development labels only. The code refuses any row on or after 2010-12-01, so the sealed holdout is never read.
- Gate: the 0.99 quantile of the method's scores on its own training rows, as for every earlier candidate.
- Queue: the maintained policy (`max_cooldown`, the settings in `config.json`), with incidents reached within 72 hours of a labelled record.
- Seeds: 0, 1 and 2 for methods with randomness; one run for deterministic methods.
- Development labels have been used by every earlier round, so development is not fresh data. The study is exploratory.

## Methods

Inputs to the neural methods are standardised with the training window's mean and standard deviation. No hyperparameter is tuned on any fold; if a method fails to train, the failure is reported, not retuned. Implementation bugs may be fixed, and any rerun is noted in the report.

**References (re-run inside the study so every method has per-row scores):**

| Name | Kind | Definition |
| --- | --- | --- |
| `rf` | supervised | Random Forest as in the research harness: 100 trees, depth 8, leaf 3, balanced class weights. **The comparison baseline.** |
| `if` | unsupervised | Isolation Forest, 100 trees, 1,024 samples. |
| `ecod_top5` | unsupervised | Sum of the 5 strongest upper-tail rarities on upward-only inputs (the project's label-free detector). |

**Tier 1, feed-forward neural networks:**

| Name | Kind | Definition |
| --- | --- | --- |
| `mlp` | supervised | 33 → 64 → 32 → 1, ReLU, dropout 0.1. Binary cross-entropy weighted by the training negative/positive ratio. Adam, learning rate 1e-3, batch 512, 8 epochs. |
| `autoencoder` | unsupervised | 33 → 16 → 8 → 16 → 33, ReLU. Trained on every training row with labels unused, mean squared error, Adam 1e-3, batch 512, 10 epochs. Score: reconstruction error. |

**Tier 2, sequence models over each identity's last 14 calendar days:**

The input for an identity-day is the identity's vectors for that day and the 13 days before it. A day with no row is zeros plus a presence flag of 0. Only past and current rows are read.

| Name | Kind | Definition |
| --- | --- | --- |
| `gru` | supervised | One GRU layer, 32 hidden units, a linear head on the last state. Same loss, optimiser, batch and epochs as `mlp`. |
| `gru_next` | unsupervised | One GRU layer, 32 hidden units, reads the 13 previous days and predicts today's vector. Score: squared prediction error. Mean squared error, Adam 1e-3, batch 512, 8 epochs. |

**Tier 3, graph methods over the identity–computer and identity–web-domain graph:**

The graph's edges are identity→computer logons and identity→domain visits from the label-free ledger, from 2010-05-01 to the day before the fold. It is frozen at the fold start: both graph methods see exactly the same history and differ only in the model. An edge's weight is the number of days on which it occurred.

| Name | Kind | Definition |
| --- | --- | --- |
| `edge` | unsupervised | Smoothed edge probability. P(v given u) = (days(u,v) + 5·q(v)) / (days(u) + 5), where q(v) is v's share of all edge-days of its type, with add-one smoothing. Edge surprise is −log P. |
| `graphsage` | unsupervised | Two GraphSAGE layers (mean aggregation), 32 dimensions. Node inputs: a node-type one-hot and standardised log degree. A dot-product decoder is trained for link prediction: binary cross-entropy against uniform negatives of the same edge type at a 1:1 ratio, full batch, Adam 1e-2, 200 epochs. Edge surprise is −log σ(z_u·z_v). |

For both graph methods, an identity-day's score is the sum of its 3 largest edge surprises today, or of all of them if it has fewer than 3, or 0 if it has none. An edge that touches a node absent from the frozen graph gets the largest edge surprise seen in training.

## Measures

Per method, fold and seed:

- **Ranking quality:**
  - average precision and ROC-AUC over the fold's identity-days;
  - recall at k for k = 1, 2, 5 and 10, meaning the share of malicious identity-days ranked in the top k of their own day.
- **Through the queue:**
  - investigations;
  - current-positive yield;
  - incidents reached within 72 hours, out of 61 incident-folds;
  - coverage by scenario and account role, including the hijacked account in scenario 3.

**Uncertainty:**

- 95% bootstrap intervals with paired resamples, so every method uses the same draws:
  - Incidents reached: resample the 61 incident-folds (2,000 resamples). Each incident-fold counts the share of seeds that reached it.
  - Average precision: resample test days within each fold (1,000 resamples), then average over folds and seeds.
- Every method's difference from `rf` is reported with its interval.

## Reading rules (fixed now)

- A method **matches** `rf` on a measure when the 95% interval of its difference contains 0.
- It is **better** or **worse** when the whole interval lies above or below 0.
- With 8 comparisons, about one interval in 2.5 could miss 0 by chance at the 95% level, so a single "better" or "worse" is read as a lead, not a finding.
- Family-level statements (supervised versus unsupervised, neural versus tree) need every member of the family to agree.

## Expectations, written before running

- `mlp` matches or trails `rf`, since trees usually win on small tabular data.
- `autoencoder` and `gru_next` land near `if` and `ecod_top5`, far below the supervised methods.
- `gru` matches `rf`, because the features already summarise 1-, 3- and 7-day windows.
- The graph methods rank lower overall than the behavioural detectors. They may help scenario 3's attacker, but not the hijacked account, whose edges are its own.

## Outputs

- `data/research/methods/`: per-row scores for every method, fold and seed, plus `results.json`.
- `reports/METHODS_STUDY.md`: the tables, intervals, coverage, and these expectations checked against what happened.
- Figures generated from the saved results.

## Round 2: statistical, distribution, distance and linear methods

Added after round 1 had run and its results had been read, and before any round 2 method had run. Round 1 above is unchanged. The protocol, measures and reading rules are the same; the definitions below are fixed now. The comparison baseline stays `rf`, and with 17 comparisons in total about one interval in 1.7 could miss 0 by chance.

Distance, margin and linear methods standardise inputs with the training window's mean and standard deviation. Deterministic methods run once; methods that draw a subsample run with seeds 0, 1 and 2.

| Name | Kind | Definition |
| --- | --- | --- |
| `zscore` | statistical rule | Raw daily counts in 8 channels (USB, file copies, logons, after-hours logons, external email, message bytes, attachments, web), as log(1 + count). The reference for a channel is the identity's own rows in the previous 28 calendar days. z = (today − median) / max(1.4826 · MAD, 0.1), or 0 with fewer than 7 reference rows. Score: the largest absolute z. This is the only method that does not read feature set `c`. |
| `pct_max` | statistical rule | The largest of the 13 signed-percentile inputs of `c`. |
| `hbos` | distribution | Histogram-based outlier score. Per input, 10 equal-width bins over the training range; a bin's density is its count divided by the largest bin's count, floored at 1 / (training rows + 1); values outside the range use the nearest edge bin. Score: sum of −log density. |
| `copod` | distribution | Copula-based outlier score with tails estimated on the training rows. Per input, the left-tail probability is (training values ≤ x, plus 1) / (n + 1) and the right-tail probability likewise with ≥. Score: the largest of the summed −log left tails, the summed −log right tails, and the sum that takes the left tail where the input's training skewness is negative and the right tail otherwise. |
| `lof` | density | Local Outlier Factor, 20 neighbours, against a 20,000-row random subsample of the training rows. The gate is taken from the subsample's own factors (each row excluded from its own neighbours). |
| `knn` | distance | Mean distance to the 20 nearest rows of the same kind of 20,000-row subsample; gate as for `lof`. |
| `ocsvm` | margin | One-class SVM, RBF kernel, γ = 1 / (inputs × variance), ν = 0.05, fitted on a 10,000-row random subsample of the training rows. Score: the negated decision value. Gate from all training rows. |
| `logreg` | supervised linear | L2 logistic regression, C = 1, balanced class weights. |
| `edge_causal` | graph | The `edge` probability, but with counts that hold only strictly earlier days: each day is scored, then added. q(v) = (days(v) + 1) / (edge-days of its type + nodes of its type + 1), so unseen nodes and identities need no ceiling. |

`edge_causal` is a repair, declared because of a round 1 result: `edge` let 14,011 test identity-days over its gate where about 1% (roughly 800) was intended. Its gate comes from training rows whose edges are already inside the frozen graph, so their surprises are in-sample and too low. `edge_causal` scores training and test rows the same out-of-sample way. `edge` stays in the report as run.

Expectations, written before running round 2:

- `zscore` and `pct_max` land at or below the unsupervised detectors (average precision under 0.2).
- `hbos` and `copod` land near `ecod_top5`, which is the same family.
- `lof` and `knn` land near `if`; `ocsvm` near `autoencoder`.
- `logreg` trails `rf` on average precision; whether it matches on reach is open, since `mlp` did.
- `edge_causal` admits far fewer rows than `edge` and stays well below the behavioural detectors.
