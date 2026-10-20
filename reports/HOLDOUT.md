# Sealed holdout evaluation

Holdout: 2010-12-01 to 2011-05-17 (exclusive), original CERT r4.2 records never used for development. Every scorer was fitted and frozen before holdout labels were read; this evaluation runs once. Refit scorers use June 8 - November 30 development data (labels only for supervised scorers); ranges are over 5 seeds. Queue: one admission per day, 7-day cooldown, 3-day expiry, plus drain.

**Fresh insiders** are incidents whose official start is on or after the holdout start; **timely** means a labelled record was presented within 72 hours of that record.

| Role | Scorer | Admissions | Current + | Yield | Timely incidents | Fresh insiders | AP | Gate recall |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| primary | deployed (frozen, fit Jun-Oct) | 158 | 68 | 0.43-0.43 | 20 / 24 | 16 / 18 | 0.816 | 0.929 |
| primary | deployed_recipe | 150-155 | 64-67 | 0.42-0.44 | 18-20 / 24 | 14-16 / 18 | 0.823 | 0.936 |
| secondary | corrected_hgb | 151-156 | 60-66 | 0.39-0.43 | 17-18 / 24 | 13-14 / 18 | 0.595 | 0.954 |
| secondary | hgb_rank_sum | 150-157 | 55-62 | 0.36-0.40 | 15-17 / 24 | 11-13 / 18 | 0.595 | 0.954 |

## Deployed model detail

- Scenario breakdown: {"1": {"positive_days": 21, "gate_positive_days": 20, "timely_incidents": 7}, "2": {"positive_days": 281, "gate_positive_days": 264, "timely_incidents": 11}, "3": {"positive_days": 8, "gate_positive_days": 4, "timely_incidents": 2}}
- Terminal event assignments: {"admitted_context": 1888, "cooldown": 344, "threshold": 64, "expiry": 107}
- Queue decisions: {"admitted": 158, "budget_wait": 2195, "cooldown": 326, "merged": 1224, "expired": 695}
- Median delay from official incident onset to the timely admission: 48.9 hours
