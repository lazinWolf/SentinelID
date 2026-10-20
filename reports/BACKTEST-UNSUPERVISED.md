# Development backtest

Rolling-origin folds inside June-November 2010. Each fold refits on all earlier development days, sets the gate at the fitting-score quantile, and replays one admission per day with cooldown and expiry. Seeds: [0, 1, 2]. Totals are summed over folds and averaged over seeds (min-max in brackets). The sealed December 2010 - May 2011 holdout is not used here.

| Candidate | Features | Model | Queue | Admissions | Current + | Yield | Timely incidents | AP | Gate recall |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| if | c | if | max_cooldown, rank=max | 128.0 | 26.7 | 0.208 | 22.3 [19-26] / 61 | 0.129 | 0.232 |
| if256 | c | if256 | max_cooldown, rank=max | 126.3 | 27.7 | 0.219 | 23.0 [19-26] / 61 | 0.115 | 0.231 |
| if_up | c | if | max_cooldown, rank=max | 126.3 | 28.7 | 0.227 | 24.0 [23-25] / 61 | 0.123 | 0.224 |
| if_up_movement | c | if | max_cooldown, rank=max | 126.3 | 26.7 | 0.211 | 21.3 [19-25] / 61 | 0.121 | 0.233 |
| ecod | c | ecod | max_cooldown, rank=max | 125.0 | 27.0 | 0.216 | 23.0 [23-23] / 61 | 0.123 | 0.228 |
| ecod_up | c | ecod | max_cooldown, rank=max | 125.0 | 26.0 | 0.208 | 23.0 [23-23] / 61 | 0.122 | 0.226 |
| ecod_up_top5 | c | ecod_top5 | max_cooldown, rank=max | 124.0 | 36.0 | 0.290 | 28.0 [28-28] / 61 | 0.176 | 0.322 |
| ecod_up_movement | c | ecod | max_cooldown, rank=max | 124.0 | 24.0 | 0.194 | 21.0 [21-21] / 61 | 0.127 | 0.242 |
| ecod_up_movement_top5 | c | ecod_top5 | max_cooldown, rank=max | 123.0 | 31.0 | 0.252 | 26.0 [26-26] / 61 | 0.159 | 0.294 |
| ecod_up_peer | c_peer | ecod | max_cooldown, rank=max | 123.0 | 23.0 | 0.187 | 20.0 [20-20] / 61 | 0.109 | 0.192 |
| ecod_up_temporal_peer_movement | c_temporal_peer | ecod | max_cooldown, rank=max | 125.0 | 22.0 | 0.176 | 19.0 [19-19] / 61 | 0.110 | 0.218 |
| if_up_peer_movement | c_peer | if | max_cooldown, rank=max | 125.7 | 33.3 | 0.265 | 26.7 [22-30] / 61 | 0.152 | 0.295 |
| ecodc_up | c | ecodc | max_cooldown, rank=max | 126.0 | 24.0 | 0.190 | 19.0 [19-19] / 61 | 0.134 | 0.201 |
| ecodc2_up | c | ecodc2 | max_cooldown, rank=max | 126.0 | 28.0 | 0.222 | 24.0 [24-24] / 61 | 0.172 | 0.321 |
| ecodc3_up | c | ecodc3 | max_cooldown, rank=max | 126.0 | 27.0 | 0.214 | 23.0 [23-23] / 61 | 0.150 | 0.268 |
| ecod_up_top5_wk | c | ecod_top5_wk | max_cooldown, rank=max | 124.0 | 33.0 | 0.266 | 26.0 [26-26] / 61 | 0.173 | 0.321 |
| ecodc2_up_wk | c | ecodc2_wk | max_cooldown, rank=max | 126.0 | 28.0 | 0.222 | 24.0 [24-24] / 61 | 0.173 | 0.324 |
| ecodc3_up_wk | c | ecodc3_wk | max_cooldown, rank=max | 126.0 | 28.0 | 0.222 | 23.0 [23-23] / 61 | 0.149 | 0.270 |
| if_up_wk | c | if_wk | max_cooldown, rank=max | 124.7 | 27.7 | 0.222 | 22.7 [19-26] / 61 | 0.124 | 0.237 |
| ecodc3_up_peer_wk | c_peer | ecodc3_wk | max_cooldown, rank=max | 127.0 | 29.0 | 0.228 | 23.0 [23-23] / 61 | 0.151 | 0.274 |
| ecod_up_top5_selfmed | c | ecod_top5 | max_cooldown, rank=max | 120.0 | 17.0 | 0.142 | 13.0 [13-13] / 61 | 0.052 | 0.111 |
| ecod_up_top5_selfq90 | c | ecod_top5 | max_cooldown, rank=max | 90.0 | 7.0 | 0.078 | 7.0 [7-7] / 61 | 0.037 | 0.044 |
| if_up_selfmed | c | if | max_cooldown, rank=max | 22.7 | 10.0 | 0.440 | 8.0 [7-9] / 61 | 0.069 | 0.049 |

Baseline: `if`. Selection rule: Highest mean timely incidents summed over folds, among candidates with mean admissions no greater than the baseline and mean current-positive yield no lower; ties broken by yield.

**Selected for the sealed holdout: `ecod_up_top5`.**
