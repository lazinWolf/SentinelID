# Sealed holdout evaluation

Holdout: 2010-12-01 to 2011-05-17 (exclusive), original CERT r4.2 records never used for development. Every scorer was fitted and frozen before holdout labels were read; this evaluation runs once. Refit scorers use June 8 - November 30 development data (labels only for supervised scorers); ranges are over 5 seeds. Queue: one admission per day, 7-day cooldown, 3-day expiry, plus drain.

**Fresh insiders** are incidents whose official start is on or after the holdout start; **timely** means a labelled record was presented within 72 hours of that record.

**Exploratory reuse:** this holdout was already evaluated for holdout-feedback/result.json, holdout-unsupervised/result.json, holdout/result.json. These candidates were developed without its results, but it is no longer untouched.

| Role | Scorer | Admissions | Current + | Yield | Timely incidents | Fresh insiders | AP | Gate recall |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| primary | deployed (frozen, fit Jun-Oct) | 158 | 68 | 0.43-0.43 | 20 / 24 | 16 / 18 | 0.816 | 0.929 |
| primary | corrected | 151-157 | 62-68 | 0.40-0.44 | 18-21 / 24 | 14-16 / 18 | 0.823 | 0.936 |
| primary | ledger_generic | 154-157 | 59-70 | 0.38-0.45 | 16-20 / 24 | 12-15 / 18 | 0.796 | 0.931 |

## Deployed model detail

- Scenario breakdown: {"1": {"positive_days": 21, "gate_positive_days": 20, "timely_incidents": 7}, "2": {"positive_days": 281, "gate_positive_days": 264, "timely_incidents": 11}, "3": {"positive_days": 8, "gate_positive_days": 4, "timely_incidents": 2}}
- Terminal event assignments: {"admitted_context": 1888, "cooldown": 344, "threshold": 64, "expiry": 107}
- Queue decisions: {"admitted": 158, "budget_wait": 2195, "cooldown": 326, "merged": 1224, "expired": 695}
- Median delay from official incident onset to the timely admission: 48.9 hours

## Coverage by scenario and account

Means over seeds. `hijacked` is scenario 3's victim account in use by the attacker.

| Candidate | Scenario | Account | Days over gate | Timely incidents |
| --- | --- | --- | ---: | ---: |
| deployed (frozen, fit Jun-Oct) | 1 | own | 20.0 / 21 | 7.0 / 9 |
| deployed (frozen, fit Jun-Oct) | 2 | own | 264.0 / 281 | 11.0 / 13 |
| deployed (frozen, fit Jun-Oct) | 3 | own | 4.0 / 4 | 2.0 / 2 |
| deployed (frozen, fit Jun-Oct) | 3 | hijacked | 0.0 / 4 | 0.0 / 2 |
| corrected | 1 | own | 19.8 / 21 | 6.2 / 9 |
| corrected | 2 | own | 266.6 / 281 | 11.4 / 13 |
| corrected | 3 | own | 3.4 / 4 | 2.0 / 2 |
| corrected | 3 | hijacked | 0.4 / 4 | 0.4 / 2 |
| ledger_generic | 1 | own | 20.0 / 21 | 5.6 / 9 |
| ledger_generic | 2 | own | 264.8 / 281 | 11.2 / 13 |
| ledger_generic | 3 | own | 3.4 / 4 | 1.2 / 2 |
| ledger_generic | 3 | hijacked | 0.4 / 4 | 0.4 / 2 |
