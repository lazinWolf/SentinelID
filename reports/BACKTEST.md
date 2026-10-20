# Development backtest

Rolling-origin folds inside June-November 2010. Each fold refits on all earlier development days, sets the gate at the fitting-score quantile, and replays one admission per day with cooldown and expiry. Seeds: [0, 1, 2]. Totals are summed over folds and averaged over seeds (min-max in brackets). The sealed December 2010 - May 2011 holdout is not used here.

| Candidate | Features | Model | Queue | Admissions | Current + | Yield | Timely incidents | AP | Gate recall |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| deployed_recipe | v4 | rf | max_cooldown, rank=max | 123.0 | 90.0 | 0.732 | 45.3 [45-46] / 61 | 0.837 | 0.854 |
| corrected | c | rf | max_cooldown, rank=max | 122.0 | 88.7 | 0.727 | 44.3 [44-45] / 61 | 0.832 | 0.848 |
| corrected_peer | c_peer | rf | max_cooldown, rank=max | 123.3 | 88.0 | 0.714 | 41.0 [40-42] / 61 | 0.835 | 0.861 |
| corrected_temporal | c_temporal | rf | max_cooldown, rank=max | 121.7 | 87.3 | 0.718 | 43.0 [42-44] / 61 | 0.832 | 0.847 |
| corrected_temporal_peer | c_temporal_peer | rf | max_cooldown, rank=max | 120.3 | 88.7 | 0.737 | 41.7 [39-43] / 61 | 0.831 | 0.853 |
| corrected_rf500 | c | rf500 | max_cooldown, rank=max | 120.0 | 90.7 | 0.756 | 44.0 [42-45] / 61 | 0.834 | 0.853 |
| corrected_peer_rf500 | c_peer | rf500 | max_cooldown, rank=max | 123.0 | 90.3 | 0.734 | 42.7 [40-45] / 61 | 0.835 | 0.862 |
| corrected_hgb | c | hgb | max_cooldown, rank=max | 124.3 | 91.7 | 0.737 | 45.7 [43-49] / 61 | 0.840 | 0.860 |
| corrected_peer_hgb | c_peer | hgb | max_cooldown, rank=max | 123.3 | 92.3 | 0.749 | 45.3 [44-47] / 61 | 0.848 | 0.875 |
| corrected_peer_reopen | c_peer | rf | max_cooldown_reopen, rank=max | 123.3 | 92.7 | 0.751 | 41.7 [41-42] / 61 | 0.835 | 0.861 |
| corrected_if | c | if | max_cooldown, rank=max | 128.0 | 26.7 | 0.208 | 22.3 [19-26] / 61 | 0.129 | 0.232 |
| rank_sum | v4 | rf | max_cooldown, rank=sum | 123.3 | 86.3 | 0.700 | 40.3 [40-41] / 61 | 0.837 | 0.854 |
| rank_count | v4 | rf | max_cooldown, rank=count | 123.0 | 86.0 | 0.699 | 39.7 [38-42] / 61 | 0.837 | 0.854 |
| cooldown3 | v4 | rf | max_cooldown, rank=max, cooldown_days=3 | 125.7 | 111.7 | 0.889 | 39.7 [37-42] / 61 | 0.837 | 0.854 |
| expiry5 | v4 | rf | max_cooldown, rank=max, backlog_days=5 | 133.7 | 97.0 | 0.726 | 43.7 [43-44] / 61 | 0.837 | 0.854 |
| rank_sum_cooldown3 | v4 | rf | max_cooldown, rank=sum, cooldown_days=3 | 125.3 | 109.7 | 0.875 | 36.7 [35-39] / 61 | 0.837 | 0.854 |
| hgb_rank_sum | c | hgb | max_cooldown, rank=sum | 126.3 | 93.0 | 0.736 | 46.3 [45-47] / 61 | 0.840 | 0.860 |

Baseline: `deployed_recipe`. Selection rule: Highest mean timely incidents summed over folds, among candidates with mean admissions no greater than the baseline and mean current-positive yield no lower; ties broken by yield.

**Selected for the sealed holdout: `deployed_recipe`.**
