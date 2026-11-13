# Identity-attack coverage

How the frozen deployed model's already-reported results split by attack scenario and by whose account the malicious activity was recorded under. Nothing here was used to select or tune anything; the holdout scores are the ones frozen before its labels were read.

## Scenarios in CERT r4.2

| Scenario | Behaviour | Accounts involved |
| --- | --- | --- |
| 1 | Data theft before leaving: after-hours logons, USB use, upload to wikileaks.org | the insider's own |
| 2 | Job hunting, then data theft to a USB drive before leaving | the insider's own |
| 3 | Account takeover: keylogger planted on the supervisor's computer, then mass email sent while logged on as the supervisor | the attacker's own, then the victim's (`hijacked`) |

## November (2010-11-01 to 2010-12-01, exclusive)

31 investigations, 21 current-positive, 9/11 incidents reached in time.

| Scenario | Account | Labelled days over the gate | Incidents reached within 72 h | Median hours, first record to admission |
| --- | --- | ---: | ---: | ---: |
| 1 | own | 4 / 5 | 1 / 3 | 170 |
| 2 | own | 78 / 88 | 7 / 7 | 43 |
| 3 | own | 1 / 2 | 1 / 1 | 47 |
| 3 | hijacked | 0 / 2 | 0 / 1 | never shown |

Where labelled records ended up (event counts): scenario 1: admitted_context 6, cooldown 5, expiry 5, threshold 4; scenario 2: admitted_context 544, cooldown 86, expiry 33, threshold 15; scenario 3: admitted_context 15, threshold 7.

## Holdout (2010-12-01 to 2011-05-17, exclusive)

158 investigations, 68 current-positive, 20/24 incidents reached in time.

| Scenario | Account | Labelled days over the gate | Incidents reached within 72 h | Median hours, first record to admission |
| --- | --- | ---: | ---: | ---: |
| 1 | own | 20 / 21 | 7 / 9 | 32 |
| 2 | own | 264 / 281 | 11 / 13 | 24 |
| 3 | own | 4 / 4 | 2 / 2 | 47 |
| 3 | hijacked | 0 / 4 | 0 / 2 | never shown |

Where labelled records ended up (event counts): scenario 1: admitted_context 48, cooldown 26, expiry 1, threshold 5; scenario 2: admitted_context 1810, cooldown 316, expiry 106, threshold 49; scenario 3: admitted_context 30, cooldown 2, threshold 10.

`admitted_context` means the record was shown in an investigation; `threshold` means its day scored below the gate; `cooldown`, `expiry` and `budget_pending` are queue losses.
