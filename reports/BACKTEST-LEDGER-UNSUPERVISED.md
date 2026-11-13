# Development backtest

Rolling-origin folds inside June-November 2010. Each fold refits on all earlier development days, sets the gate at the fitting-score quantile, and replays one admission per day with cooldown and expiry. Seeds: [0, 1, 2]. Totals are summed over folds and averaged over seeds (min-max in brackets). The sealed December 2010 - May 2011 holdout is not used here.

| Candidate | Features | Model | Queue | Admissions | Current + | Yield | Timely incidents | AP | Gate recall |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ecod_up_top5 | c | ecod_top5 | max_cooldown, rank=max | 124.0 | 36.0 | 0.290 | 28.0 [28-28] / 61 | 0.176 | 0.322 |
| ecod_up_top5_generic | c | ecod_top5 | max_cooldown, rank=max | 125.0 | 25.0 | 0.200 | 23.0 [23-23] / 61 | 0.148 | 0.306 |
| ecod_up_top5_all | c | ecod_top5 | max_cooldown, rank=max | 125.0 | 26.0 | 0.208 | 23.0 [23-23] / 61 | 0.152 | 0.306 |

Baseline: `ecod_up_top5`. Selection rule: Highest mean timely incidents summed over folds, among candidates with mean admissions no greater than the ecod_up_top5 control and mean current-positive yield no lower; ties broken by yield.

**Selected for the sealed holdout: `ecod_up_top5`.**

## Coverage by scenario and account

Scenario 1 and 2 insiders act under their own account. Scenario 3 is an account takeover: the attacker logs on to the supervisor's computer as the supervisor, so its records fall under two accounts, `own` (the attacker's preparation) and `hijacked` (the victim's account in use). Days are labelled identity-days; an incident counts once per account role when a record under that role reaches an analyst within 72 hours.

| Candidate | Scenario | Account | Days over gate | Timely incidents |
| --- | --- | --- | ---: | ---: |
| ecod_up_top5 | 1 | own | 38.0 / 45 | 8.0 / 17 |
| ecod_up_top5 | 2 | own | 110.0 / 413 | 18.0 / 39 |
| ecod_up_top5 | 3 | own | 4.0 / 8 | 2.0 / 5 |
| ecod_up_top5 | 3 | hijacked | 0.0 / 8 | 0.0 / 5 |
| ecod_up_top5_generic | 1 | own | 39.0 / 45 | 9.0 / 17 |
| ecod_up_top5_generic | 2 | own | 98.0 / 413 | 10.0 / 39 |
| ecod_up_top5_generic | 3 | own | 5.0 / 8 | 4.0 / 5 |
| ecod_up_top5_generic | 3 | hijacked | 3.0 / 8 | 0.0 / 5 |
| ecod_up_top5_all | 1 | own | 39.0 / 45 | 9.0 / 17 |
| ecod_up_top5_all | 2 | own | 98.0 / 413 | 10.0 / 39 |
| ecod_up_top5_all | 3 | own | 5.0 / 8 | 4.0 / 5 |
| ecod_up_top5_all | 3 | hijacked | 3.0 / 8 | 0.0 / 5 |
