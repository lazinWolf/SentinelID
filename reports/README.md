# Reports

Every report here is generated from saved results (`sentinelid/reporting.py` and the stage that produced it) and can be regenerated without refitting anything. They answer four questions about identity-based attacks on the synthetic CERT r4.2 benchmark. The strength column says how much each answer can bear.

## 1. Does behavioural profiling catch misuse of an identity's own access?

Yes, for insiders using their own accounts (CERT scenarios 1 and 2).

| Report | What it shows | Strength |
| --- | --- | --- |
| [`../results.json`](../results.json) | Frozen November 2010 evaluation: Random Forest 9/11 incidents with 31 investigations, Isolation Forest 2/11 | Retrospective; the predeclared cost criterion was missed by one investigation |
| [HOLDOUT.md](HOLDOUT.md) | Sealed December 2010 – May 2011 holdout: 20/24 incidents and 16/18 insiders never seen in training, 158 investigations | **Strongest evidence in the project**: every scorer frozen before labels were read |
| [BACKTEST.md](BACKTEST.md) | 17 candidate recipes on rolling development folds; none beat the deployed one (45.3/61 incident-folds). 12 of 15 misses were queue losses | Development; predeclared selection rule |

## 2. Can it start without labels?

Partly. Label-free rarity reaches about half of the supervised result; analyst feedback on its own cases closes most of the gap.

| Report | What it shows | Strength |
| --- | --- | --- |
| [BACKTEST-UNSUPERVISED.md](BACKTEST-UNSUPERVISED.md) | 23 label-free variants; the best, `ecod_up_top5`, 28.0/61 against Isolation Forest 22.3 | Development |
| [HOLDOUT-UNSUPERVISED.md](HOLDOUT-UNSUPERVISED.md) | `ecod_up_top5` on the holdout: 15/24 incidents, 12/18 new insiders | Exploratory holdout reuse |
| [FEEDBACK.md](FEEDBACK.md) | Learning from simulated analyst verdicts: 29 → 40/61; robust to 10–20% wrong verdicts; holdout continuation 16/18 new insiders with half the investigations | Development, simulated analyst; holdout part is an exploratory reuse |
| [ADAPTIVE_APP_CHECK.md](ADAPTIVE_APP_CHECK.md) | The real application in adaptive mode admits the same 23 investigations as the research harness | Engineering verification |

## 3. Does it catch a hijacked account in use?

No. This is the project's main identity finding.

| Report | What it shows | Strength |
| --- | --- | --- |
| [IDENTITY_COVERAGE.md](IDENTITY_COVERAGE.md) | Split by scenario and account: the takeover is reached only through the attacker's own preparation; 0 of 6 hijacked-account days passed the gate | Descriptive re-measurement of published results; small counts |
| [BACKTEST-LEDGER.md](BACKTEST-LEDGER.md), [HOLDOUT-LEDGER.md](HOLDOUT-LEDGER.md) | Takeover-aware population features: a +0.7 development gain that reversed on the holdout | Predeclared; negative |
| [BACKTEST-LEDGER-FIX.md](BACKTEST-LEDGER-FIX.md) | After fixing an exposure-history defect, every candidate ties the control | Development only |
| [BACKTEST-LEDGER-UNSUPERVISED.md](BACKTEST-LEDGER-UNSUPERVISED.md) | The same features lower the label-free detector from 28 to 23 | Development |
| [METHODS_STUDY.md](METHODS_STUDY.md), "Identity reading" | Across 29 detector variants, only graph edge scores and a next-day sequence model reached a hijacked account, each at most once | Exploratory; a lead for linking identities, not a detector |

## 4. Does the choice of detector matter?

Labels and a non-linear model matter more than the model family, and the comparison holds when the implementations are refined.

| Report | What it shows | Strength |
| --- | --- | --- |
| [METHODS_STUDY.md](METHODS_STUDY.md) | 18 methods in rounds 1–2 plus 11 refined round 3 variants, each against the Random Forest with paired bootstrap intervals. MLP matches RF on reach; GRU matches on ranking but reaches incidents later; every label-free and linear method is worse. Specification: [docs/methods-study.md](../docs/methods-study.md) | Exploratory, development only; expectations checked against outcomes |

## History

[history/](history/) keeps the October 2026 reports that the later stages superseded: the corrected factorial experiment ([comparison](history/EXPERIMENT_COMPARISON.md), [findings](history/EXPERIMENT_FINDINGS.md)) and the read-only unsupervised investigation that found the three-day feature defect ([report](history/UNSUPERVISED_INVESTIGATION.md)). [EXPERIMENT_HISTORY.md](../EXPERIMENT_HISTORY.md) tells the whole sequence.

## Units

- **Incident (November, holdout):** reached when one of its labelled records is shown to an analyst within 72 hours of that record.
- **Incident-fold (development):** each monthly fold is scored on its own, so an incident active in two folds counts twice; 61 incident-folds are 43 distinct incidents.
- **New (fresh) insider:** a holdout incident that starts after the holdout begins.
- **Investigation:** one queue admission, standing in for analyst effort, which was not measured.
- **Seeds:** non-integer counts such as 45.3 are means over seeds.
