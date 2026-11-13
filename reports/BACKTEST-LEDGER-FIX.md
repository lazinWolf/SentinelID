# Development backtest: ledger exposure fix check

Rolling-origin folds inside June-November 2010. Each fold refits on all earlier development days, sets the gate at the fitting-score quantile, and replays one admission per day with cooldown and expiry. Seeds: [0, 1, 2]. Totals are summed over folds and averaged over seeds (min-max in brackets). The sealed December 2010 - May 2011 holdout is not used here.

| Candidate | Features | Model | Queue | Admissions | Current + | Yield | Timely incidents | AP | Gate recall |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| corrected | c | rf | max_cooldown, rank=max | 122.0 | 88.7 | 0.727 | 44.3 [44-45] / 61 | 0.832 | 0.848 |
| ledger_exposure | c | rf | max_cooldown, rank=max | 123.0 | 89.3 | 0.726 | 44.3 [43-45] / 61 | 0.824 | 0.842 |
| ledger_generic | c | rf | max_cooldown, rank=max | 122.3 | 90.0 | 0.736 | 44.3 [44-45] / 61 | 0.834 | 0.842 |
| ledger_all | c | rf | max_cooldown, rank=max | 123.3 | 93.0 | 0.754 | 44.3 [43-45] / 61 | 0.838 | 0.842 |

Baseline: `corrected`. Selection rule: Highest mean timely incidents summed over folds, among candidates with mean admissions no greater than the corrected control and mean current-positive yield no lower; ties broken by yield.

**No candidate beats the control; every one ties it at 44.3.** This is a development-only check after the exposure fix (`configs/research-ledger-fix.json`); the holdout is not used, and the round 3 holdout verdict stands as recorded.

## Coverage by scenario and account

Scenario 1 and 2 insiders act under their own account. Scenario 3 is an account takeover: the attacker logs on to the supervisor's computer as the supervisor, so its records fall under two accounts, `own` (the attacker's preparation) and `hijacked` (the victim's account in use). Days are labelled identity-days; an incident counts once per account role when a record under that role reaches an analyst within 72 hours.

| Candidate | Scenario | Account | Days over gate | Timely incidents |
| --- | --- | --- | ---: | ---: |
| corrected | 1 | own | 38.0 / 45 | 11.3 / 17 |
| corrected | 2 | own | 356.3 / 413 | 30.0 / 39 |
| corrected | 3 | own | 4.3 / 8 | 3.0 / 5 |
| corrected | 3 | hijacked | 0.0 / 8 | 0.0 / 5 |
| ledger_exposure | 1 | own | 37.7 / 45 | 11.3 / 17 |
| ledger_exposure | 2 | own | 354.0 / 413 | 30.3 / 39 |
| ledger_exposure | 3 | own | 4.0 / 8 | 2.7 / 5 |
| ledger_exposure | 3 | hijacked | 0.0 / 8 | 0.0 / 5 |
| ledger_generic | 1 | own | 36.7 / 45 | 11.0 / 17 |
| ledger_generic | 2 | own | 355.3 / 413 | 31.3 / 39 |
| ledger_generic | 3 | own | 4.0 / 8 | 2.0 / 5 |
| ledger_generic | 3 | hijacked | 1.0 / 8 | 0.0 / 5 |
| ledger_all | 1 | own | 36.7 / 45 | 11.7 / 17 |
| ledger_all | 2 | own | 355.3 / 413 | 30.7 / 39 |
| ledger_all | 3 | own | 4.7 / 8 | 2.0 / 5 |
| ledger_all | 3 | hijacked | 0.0 / 8 | 0.0 / 5 |
