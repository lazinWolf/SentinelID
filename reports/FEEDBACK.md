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

## Exploratory holdout continuation

The same online learner continues from August 2010 through 2011-05-16; metrics cover December-May only. Holdout labels enter only as verdicts on admitted cases, as an analyst would provide them. **Exploratory reuse:** the holdout was already evaluated for holdout-unsupervised/result.json, holdout/result.json.

| Variant | Admissions | Current + | Yield | Timely incidents | Fresh insiders |
| --- | ---: | ---: | ---: | ---: | ---: |
| none | 164 | 17 | 0.10 | 13/24 | 11/18 |
| lambda_3 | 82 | 46 | 0.56 | 19/24 | 16/18 |
| lambda_0.3 | 83 | 46 | 0.55 | 19/24 | 16/18 |
| reference: deployed supervised RF (sealed holdout) | 158 | 68 | 0.43 | 20/24 | 16/18 |
| reference: label-free ecod_up_top5 (exploratory holdout) | 163 | 18 | 0.11 | 15/24 | 12/18 |
