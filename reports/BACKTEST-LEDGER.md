# Development backtest

Rolling-origin folds inside June-November 2010. Each fold refits on all earlier development days, sets the gate at the fitting-score quantile, and replays one admission per day with cooldown and expiry. Seeds: [0, 1, 2]. Totals are summed over folds and averaged over seeds (min-max in brackets). The sealed December 2010 - May 2011 holdout is not used here.

| Candidate | Features | Model | Queue | Admissions | Current + | Yield | Timely incidents | AP | Gate recall |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| deployed_recipe | v4 | rf | max_cooldown, rank=max | 123.0 | 90.0 | 0.732 | 45.3 [45-46] / 61 | 0.837 | 0.854 |
| corrected | c | rf | max_cooldown, rank=max | 122.0 | 88.7 | 0.727 | 44.3 [44-45] / 61 | 0.832 | 0.848 |
| ledger_rarity | c | rf | max_cooldown, rank=max | 122.7 | 94.0 | 0.766 | 45.0 [43-47] / 61 | 0.842 | 0.855 |
| ledger_email | c | rf | max_cooldown, rank=max | 125.0 | 94.0 | 0.752 | 45.0 [43-47] / 61 | 0.838 | 0.849 |
| ledger_pc | c | rf | max_cooldown, rank=max | 121.3 | 90.7 | 0.747 | 44.0 [42-46] / 61 | 0.823 | 0.847 |
| ledger_job | c | rf | max_cooldown, rank=max | 122.3 | 89.3 | 0.730 | 43.0 [42-44] / 61 | 0.835 | 0.853 |
| ledger_exposure | c | rf | max_cooldown, rank=max | 122.7 | 89.7 | 0.731 | 43.3 [43-44] / 61 | 0.826 | 0.844 |
| ledger_generic | c | rf | max_cooldown, rank=max | 121.3 | 91.0 | 0.750 | 45.0 [44-46] / 61 | 0.833 | 0.844 |
| ledger_all | c | rf | max_cooldown, rank=max | 122.7 | 89.3 | 0.729 | 41.7 [41-42] / 61 | 0.839 | 0.849 |

Baseline: `corrected`. Selection rule: Highest mean timely incidents summed over folds, among candidates with mean admissions no greater than the corrected control and mean current-positive yield no lower; ties broken by yield. The deployed recipe is shown for reference only.

**Selected for the sealed holdout: `ledger_generic`.**

## Coverage by scenario and account

Scenario 1 and 2 insiders act under their own account. Scenario 3 is an account takeover: the attacker logs on to the supervisor's computer as the supervisor, so its records fall under two accounts, `own` (the attacker's preparation) and `hijacked` (the victim's account in use). Days are labelled identity-days; an incident counts once per account role when a record under that role reaches an analyst within 72 hours.

| Candidate | Scenario | Account | Days over gate | Timely incidents |
| --- | --- | --- | ---: | ---: |
| deployed_recipe | 1 | own | 38.3 / 45 | 12.0 / 17 |
| deployed_recipe | 2 | own | 359.0 / 413 | 30.7 / 39 |
| deployed_recipe | 3 | own | 4.0 / 8 | 2.7 / 5 |
| deployed_recipe | 3 | hijacked | 0.0 / 8 | 0.0 / 5 |
| corrected | 1 | own | 38.0 / 45 | 11.3 / 17 |
| corrected | 2 | own | 356.3 / 413 | 30.0 / 39 |
| corrected | 3 | own | 4.3 / 8 | 3.0 / 5 |
| corrected | 3 | hijacked | 0.0 / 8 | 0.0 / 5 |
| ledger_rarity | 1 | own | 38.0 / 45 | 12.3 / 17 |
| ledger_rarity | 2 | own | 360.0 / 413 | 29.3 / 39 |
| ledger_rarity | 3 | own | 4.0 / 8 | 3.3 / 5 |
| ledger_rarity | 3 | hijacked | 0.0 / 8 | 0.0 / 5 |
| ledger_email | 1 | own | 36.7 / 45 | 11.3 / 17 |
| ledger_email | 2 | own | 359.0 / 413 | 30.7 / 39 |
| ledger_email | 3 | own | 4.0 / 8 | 3.0 / 5 |
| ledger_email | 3 | hijacked | 0.0 / 8 | 0.0 / 5 |
| ledger_pc | 1 | own | 38.3 / 45 | 12.3 / 17 |
| ledger_pc | 2 | own | 355.7 / 413 | 29.7 / 39 |
| ledger_pc | 3 | own | 4.0 / 8 | 2.0 / 5 |
| ledger_pc | 3 | hijacked | 0.0 / 8 | 0.0 / 5 |
| ledger_job | 1 | own | 37.7 / 45 | 11.3 / 17 |
| ledger_job | 2 | own | 358.7 / 413 | 31.0 / 39 |
| ledger_job | 3 | own | 4.7 / 8 | 0.7 / 5 |
| ledger_job | 3 | hijacked | 0.0 / 8 | 0.0 / 5 |
| ledger_exposure | 1 | own | 38.0 / 45 | 11.0 / 17 |
| ledger_exposure | 2 | own | 354.3 / 413 | 30.0 / 39 |
| ledger_exposure | 3 | own | 4.0 / 8 | 2.3 / 5 |
| ledger_exposure | 3 | hijacked | 0.0 / 8 | 0.0 / 5 |
| ledger_generic | 1 | own | 36.7 / 45 | 12.0 / 17 |
| ledger_generic | 2 | own | 356.0 / 413 | 30.0 / 39 |
| ledger_generic | 3 | own | 4.3 / 8 | 3.0 / 5 |
| ledger_generic | 3 | hijacked | 1.0 / 8 | 0.0 / 5 |
| ledger_all | 1 | own | 37.7 / 45 | 9.7 / 17 |
| ledger_all | 2 | own | 357.0 / 413 | 30.3 / 39 |
| ledger_all | 3 | own | 4.7 / 8 | 1.7 / 5 |
| ledger_all | 3 | hijacked | 0.3 / 8 | 0.0 / 5 |
