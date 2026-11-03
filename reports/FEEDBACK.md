# Analyst-feedback learning

Starts with no labels: the detector is the label-free `ecod_up_top5` score. After each daily decision, the simulated analyst labels only the admitted investigation (positive if its trigger records contain a labelled malicious record), and the per-input rarity weights are refit with an L2 pull toward the label-free prior. One continuous queue runs August-November 2010 with one admission per day. `none` is the same harness without learning.

Timely incidents per month (incidents with a labelled record presented within 72 hours):

| Variant | 2010-08-01 | 2010-09-01 | 2010-10-01 | 2010-11-01 | Total | Admissions | Current + | Yield | Labels (positive) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| none | 7/17 | 8/17 | 11/16 | 3/11 | 29/61 | 120 | 33 | 0.28 | 149 (34) |
| lambda_3 | 9/17 | 7/17 | 10/16 | 8/11 | 34/61 | 87 | 68 | 0.78 | 105 (68) |
| lambda_0.3 | 10/17 | 9/17 | 13/16 | 8/11 | 40/61 | 102 | 70 | 0.69 | 127 (71) |
| reference: label-free ecod_up_top5 (fold backtest) | 7.0 | 9.0 | 9.0 | 3.0 | 28.0 | | | | |
| reference: supervised RF (fold backtest, 3-seed mean) | 11.7 | 13.7 | 11.7 | 8.3 | 45.3 | | | | |

Reference rows come from the fold backtests, which reset the queue each month and refit on earlier folds; they indicate scale, while the `none` row is the like-for-like control.

## What feedback learned (largest final weights)

- lambda_3: percentile:http_change_1 1.18, new_host_count 0.26, magnitude:http_change_1 0.19, percentile:message_bytes_change_1 0.12, magnitude:message_bytes_change_1 0.11, percentile:attachments_change_1 0.07, magnitude:external_email_change_1 0.04, percentile:usb_change_1 0.00
- lambda_0.3: percentile:http_change_1 1.68, new_domain_count 0.33, magnitude:message_bytes_change_1 0.25, new_host_count 0.22, percentile:usb_change_1 0.08, magnitude:attachments_change_1 0.05, percentile:usb_change_3 0.00, percentile:usb_change_7 0.00

## Statistical check

Paired by incident-month against the no-learning control: incidents reached by only one system, with an exact two-sided sign test. Yield intervals are 95% Wilson intervals. Two lambda values were tried, so a single p near 0.05 is weak evidence.

| Variant | Only this variant | Only control | Sign-test p | Yield [95% CI] |
| --- | ---: | ---: | ---: | --- |
| none | | | | 0.28 [0.20, 0.36] |
| lambda_3 | 16 | 11 | 0.442 | 0.78 [0.68, 0.86] |
| lambda_0.3 | 17 | 6 | 0.035 | 0.69 [0.59, 0.77] |

## Imperfect analyst

lambda = 0.3 with 10 seeds per analyst. `flip` inverts any verdict with that probability; `miss` labels a true positive negative. Evaluation still uses the answer key. Values are mean (min-max) over seeds; the no-learning control reached 29/61 with yield 0.28.

| Analyst | Wrong verdicts | Timely incidents | Admissions | Yield | Seeds beating control |
| --- | ---: | ---: | ---: | ---: | ---: |
| flip_10 | 9.3 (5-13) | 38.2 (35-42) | 98.5 (92-105) | 0.70 | 10/10 |
| flip_20 | 18.0 (15-23) | 34.7 (23-41) | 101.3 (89-123) | 0.60 | 9/10 |
| miss_30 | 14.9 (7-21) | 32.8 (23-41) | 106.4 (88-124) | 0.52 | 7/10 |

## Exploratory holdout continuation

The same online learner continues from August 2010 through 2011-05-16; metrics cover December-May only. Holdout labels enter only as verdicts on admitted cases, as an analyst would provide them. **Exploratory reuse:** the holdout was already evaluated for holdout-unsupervised/result.json, holdout/result.json.

| Variant | Admissions | Current + | Yield | Timely incidents | Fresh insiders |
| --- | ---: | ---: | ---: | ---: | ---: |
| none | 164 | 17 | 0.10 | 13/24 | 11/18 |
| lambda_3 | 82 | 46 | 0.56 | 19/24 | 16/18 |
| lambda_0.3 | 83 | 46 | 0.55 | 19/24 | 16/18 |
| reference: deployed supervised RF (sealed holdout) | 158 | 68 | 0.43 | 20/24 | 16/18 |
| reference: label-free ecod_up_top5 (exploratory holdout) | 163 | 18 | 0.11 | 15/24 | 12/18 |

Paired against the deployed RF on the same holdout incidents; RF yield 0.43 [0.36, 0.51]:

| Variant | Only this variant | Only RF | Sign-test p | Yield [95% CI] |
| --- | ---: | ---: | ---: | --- |
| none | 0 | 7 | 0.016 | 0.10 [0.07, 0.16] |
| lambda_3 | 1 | 2 | 1.000 | 0.56 [0.45, 0.66] |
| lambda_0.3 | 1 | 2 | 1.000 | 0.55 [0.45, 0.66] |
