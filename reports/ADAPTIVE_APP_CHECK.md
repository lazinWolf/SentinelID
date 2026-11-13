# Adaptive app against the research harness

November 2010 from a cold start (λ = 0.3). The harness scores cached research vectors; the app recomputes every feature from the 14.1M original records during replay. A simulated perfect analyst reviews each admitted case: in the harness the verdict goes straight to the learner, in the app it is saved as a versioned review that the replay reads before the next scored day.

| | Harness | App |
| --- | ---: | ---: |
| Investigations | 23 | 23 |
| Scored identity-days | 18772 | 18772 |

- Identical admissions (identity and decision time, in order): **yes**.
- Identity-days scored by both: 18772; largest difference in score minus day gate: 0.0628.

## Where the score differences come from

All 33 inputs agree on every one of the 18,772 scored November identity-days, and scores already differ on November 1, before any verdict exists. The difference is therefore in the label-free reference (June 8 – October 31): 820 of its 96,123 rows differ, only in novelty inputs (new hosts, recipients and domains), always with the live replay counting more (by one in 462 of 481 host differences). They fall on the first working day after a break: 16 Mondays from June 14 to October 11 (31 to 59 identities each), the Tuesdays after the July 5 and September 6 holidays (43 and 45), and 6 rows on five Sundays. November matches. The live feature builder and the builder of the archived development cache evidently bound novelty history across non-working days differently before November. The cause was not traced further, and it changed no admission.
