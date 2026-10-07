# SentinelID: read-only unsupervised detection investigation

Investigation date: October 7, 2026. Project inspected: `/home/dividh/Desktop/openai/prj4`.

**Finding:** Isolation Forest has measurable anomaly signal, but its ranking is weak where a small investigation budget needs it. A newly identified three-day feature defect affects both historical experiments and the maintained application. A single exploratory PCA detector performs better than IF on the consumed November cohort, which justifies a future comparison but does not establish recovery.

## Scope and preservation

The maintained application, `PROJECT_SUMMARY.md`, feature implementation, active model and operational database were inspected. Historical code, fitting artifacts, feature cache and consumed outcomes were extracted from the recovery archive into this temporary directory. Analysis used read-only database connections and copied artifacts; new scripts, arrays and reports were written only here.

[Preservation verification](project-preservation.json) records unchanged SHA-256 hashes for 31 checked files, including project source/configuration, the deployed model, provenance and operational database. No new project source files were created. The protected archive was read, not rewritten. This investigation makes **no project changes**, performs no deployment, and does not re-run the complete original-record replay.

November was already consumed. All new performance measurements below are retrospective diagnostics. The scratch PCA configuration was chosen in the context of known IF weaknesses; no independent validation claim is available.

## 1. A concrete feature correctness defect

In [the maintained feature builder](/home/dividh/Desktop/openai/prj4/sentinelid/features.py:141), `last7` is ordered as `[d−1, d−2, d−3, d−4, d−5, d−6, d]`. [The magnitude calculation](/home/dividh/Desktop/openai/prj4/sentinelid/features.py:195) slices `last7[-n:]`.

For `n=3`, the target therefore contains **today plus five and six days ago**, rather than today plus the preceding two days. One-day and seven-day sums are unaffected by this ordering. The percentile implementation independently uses the intended consecutive three days, so the two PM inputs describing the same nominal horizon disagree. This is not the intentional lag of the personal reference period: the defect concerns the target window.

The copied cache verifies the defect in fitting, calibration and November rows. Every recorded three-day magnitude target matches the erroneous date selection; every corresponding percentile target matches the intended selection.

| Phase | Eligible rows | USB three-day target differs | Copy three-day target differs |
| --- | ---: | ---: | ---: |
| Fitting | 85,688 | 16,300 | 16,153 |
| Calibration | 4,711 | 849 | 852 |
| November | 18,772 | 3,373 | 3,369 |
| November positive days | 97 | 85 | 79 |

A target mismatch does not always alter the transformed input, because nonpositive magnitude is clipped. November's transformed USB and copy inputs change on 2,903 and 2,752 rows respectively, including 73 and 67 positive days.

Example: ABC0174 on November 1 has an intended USB target of 1 but a recorded magnitude target of 3; its intended copy target is 1 but the recorded magnitude target is 6. Both percentile targets use 1.

This matters to the models. All 100 C_IF trees and 98/100 deployed RF trees split on at least one affected input. As a diagnostic only, replacing the two inputs in copied November arrays while keeping the old fitted models changes 3,402 IF scores and 3,203 RF scores; 86 and 20 rows change threshold membership. Models still trained on erroneous inputs cannot establish the benefit of a correction. The sensitivity result demonstrates material dependence, not detection recovery.

**Required build action:** create a new feature contract, verify exact 1/3/7-day targets with distinct daily counts, regenerate fitting/calibration inputs and refit affected models. Preserve all existing frozen results. An inference-only patch would mix two feature semantics and is insufficient.

## 2. The saved failures are reproducible

The five archived fitted-model hashes agree with saved metadata. Reconstructed C and PM fitting-vector hashes exactly match their saved hashes. All five November score arrays reproduce with maximum absolute error **0.0**. C_IF, REP_IF and REP_RF investigation identities and decision times also reproduce exactly under the maintained queue implementation.

November contains 18,772 eligible identity-days, of which 97 are positive: **0.517% prevalence**. The main operational comparison uses next-day decisions, maximum pending score, seven-day cooldown, three-day expiry, at most one admission per decision day and three subsequent drain decisions.

| Detector | Day-level average precision | Investigations | Current-positive investigations | Context-positive investigations | Timely incidents / 11 |
| --- | ---: | ---: | ---: | ---: | ---: |
| C_IF, corrected historical fitting baseline | 0.0572 | 30 | 3 | 5 | 2 |
| REP_IF, percentile + magnitude | 0.0606 | 32 | 3 | 6 | 3 |
| Scratch PCA, percentile + magnitude | 0.1869 | 31 | 7 | 11 | 5 |
| Frozen REP_RF, deployed control | 0.7852 | 31 | 21 | 23 | 9 |

“Corrected” in the historical C_IF name concerns an earlier fitting correction; it does **not** mean the three-day target defect is fixed.

Current-positive means an investigation includes exact labelled malicious records among its trigger records. Context-positive includes labelled records retained in the evidence snapshot. Timely incident reach requires admission within 72 hours of a retained labelled event; it is not necessarily 72 hours from the incident's first event. These units must remain separate from day-level classification.

The operating policy is shared, but actual investigation counts differ. This table is descriptive and does not override the original formal matched-cost verdict of “improvement not established.”

## 3. IF's principal limitation is the head of its ranking

C_IF ROC AUC is 0.885, and its average precision exceeds the 0.00517 prevalence reference. The detector is not devoid of signal. However, positive days have a median rank of **59 within their day**; REP_IF's median is **53**, compared with RF's **3**.

A diagnostic that simply takes each day's highest score, removing threshold/backlog/cooldown constraints, finds only 4 positive days in 30 selections for either IF. Even taking ten per day finds only 17/97 positive days for C_IF and 18/97 for REP_IF. These are forced-ranking diagnostics, not deployed queue policies or timely-incident results.

At its fitting gate, C_IF flags 15/97 positive days alongside 158 negative days. REP_IF flags 16/97 alongside 187 negative days. Most attacks therefore fail to enter a useful high-score region before queue effects are considered.

The negative investigation cohort helps explain the mismatch. C_IF has 25/30 investigations without retained labelled attack records. Their merged trigger days have median transformed one-day USB and copy changes of about 1.01 and 1.37, versus 0.66 and 0.38 for positive days. These investigations also include more after-hours activity. Novel web hosts are not the dominant supported explanation: their median novelty is zero in the negative investigation cohort, versus 0.69 for positive days.

This is an observational profile, not causal attribution. It supports the hypothesis that strong changes on negative-labelled removable-media days outrank modest malicious activity. It does not justify declaring every such day harmless, whitelisting high-volume users or suppressing those features without a prospective experiment.

## 4. Calibration and admission add distinct losses

The fitting-gate exceedance rate is about 0.92% for C_IF and 1.08% for REP_IF in November, close to the nominal fitting 1%. A large global alert-rate shift is not supported in this cohort. Conditional changes by user or behavior remain possible.

The separate workload calibration uses only seven days and accepts at most `floor(0.5 × 7) = 3` investigations, including drain. Both principal IF models select the maximum-score quantile from the allowed grid. Their November workload-gated queues then admit only 3 and 2 investigations and reach zero timely incidents. That calibration is meeting a strict cost constraint at the expense of reach; stricter gating cannot repair weak ranking.

Saved policy comparisons provide useful negative evidence. Tested fresh-priority/reopening variants do not improve the primary IF outcomes. Increasing C_IF capacity from one to five admissions per day increases actual investigations from 30 to 95 but timely reach only from 2 to 4 incidents. REP_IF similarly rises from 32 to 111 investigations while timely reach increases from 3 to 4. More capacity is expensive and provides limited recovery.

The original-event loss traces nevertheless identify genuine queue failures. For C_IF, IUB0565 and AKR0057 lose some retained positive events to expiry; FTM0406 is suppressed by cooldown. In contrast, all traced positive events for ABC0174, DRR0162, KRL0501 and MPM0220 are assigned to threshold loss. A queue repair could help some high-scoring cases, while those latter cases need scoring/gating recovery.

Across the 720 positive-event terminal assignments, C_IF has 516 threshold, 59 expiry, 34 cooldown and 111 admitted-context assignments. These are a terminal attribution ledger, not an initial monotone funnel: later evidence context can rescue records whose own day did not pass the gate. Event counts, candidate decisions and investigations cannot be directly equated.

## 5. One complementary unsupervised detector gives a useful lead

A single fixed PCA reconstruction detector was fitted in this temporary directory:

- Same 85,688 chronological fitting rows and 33 PM fields; no fitting labels.
- Training-only standardization.
- PCA retaining 90% of fitting variance, yielding 16 components and 90.606% explained variance.
- Mean squared reconstruction error in standardized input space.
- Fitting residual 99th-percentile gate, followed by the same operational queue.

PCA requires explicit consideration of input scales; the implementation follows the documented behavior of [PCA](https://scikit-learn.org/stable/modules/generated/sklearn.decomposition.PCA.html) and [StandardScaler](https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.StandardScaler.html). Reconstruction-error scoring is this investigation's diagnostic construction, not a reproduced CERT paper result.

No parameter sweep was performed. The comparison deliberately retains the existing window defect in both IF and PCA inputs to isolate an algorithm change within the current representation. This makes it a useful lead, not the final corrected experiment.

PCA finds 44/97 positive days at its fitting gate, versus C_IF's 15/97. Its positive-day median rank is 13. Through the queue it yields 7 current-positive investigations, 11 context-positive investigations and 5 timely incidents in 31 investigations. Its timely IDs are HJB0742, ABC0174, DRR0162, IUB0565 and KRL0501; several differ from IF's timely detections.

However, 24/31 investigations are not current-positive and six incidents remain untimely/unreached. PCA remains substantially weaker than the supervised control. November outcomes are consumed, the representation has prior label-informed development, and the small incident cohort provides limited certainty. Do not deploy PCA or claim validated superiority based on this diagnostic.

## 6. Recommended next build milestone

1. **Repair and version feature semantics first.** Add a meaningful chronology fixture and explicit horizon provenance. Regenerate inputs and refit IF, RF and the proposed PCA control using the corrected contract. Preserve old models, outcomes and report terminology.
2. **Predeclare one focused comparison.** Compare corrected C_IF/PM_IF with fixed standardized PCA reconstruction under identical causal features and queue policy. Reserve a genuinely unexamined future period before inspecting its labels. If no such period exists, report retrospective development and seek another dataset/cohort for independent validation.
3. **Evaluate the score-to-case chain.** Report day-level average precision and recall, daily ranking diagnostics, actual admissions, current/context evidence precision, timely incident reach, and threshold/expiry/cooldown losses. Establish an actual-cost comparison in advance rather than interpreting a shared daily cap as matched workload.
4. **Calibrate workload over longer chronological development blocks.** Predefine acceptable investigation cost, minimum useful reach and underfill behavior. Inspect block variability. Do not tune thresholds on consumed November; label-free calibration alone does not ensure attack coverage.
5. **Test one queue hypothesis separately.** Investigate expiry and cooldown using retained original records and evidence freshness. Keep scoring changes and admission changes separable so an improvement can be attributed to its stage.

Do not start with a broad neural-model search, more indiscriminate features, or relaxed thresholds alone. IF's weakness does not establish that every unsupervised approach must fail. The present evidence supports correcting the feature contract and testing one complementary notion of anomaly under a declared operational protocol.

Unresolved hypotheses include adaptation of references to long-running attacks, representation saturation, conditional drift and actor dependence across chronological periods. This audit has not established their causal effects. Do not remove labelled attack history from an unsupervised fitting/reference pipeline as though those labels would be available operationally.

## Reproduction and evidence

- [Main measurements and reproduction assertions](unsupervised-investigation.json)
- [Event losses by incident](incident-loss-breakdown.json)
- [Feature-window initial diagnostic](three-day-window-diagnostic.json)
- [Main scratch analysis script](investigate.py)
- [Frozen-model input sensitivity script](window_sensitivity.py)
- [PCA investigation records](exploratory-pca-reviews.json)
- [Before hashes](project-before.json) and [preservation check](project-preservation.json)
- [Copied historical report](archive/research/reports/IF_WORKLOAD_IMPROVEMENT.md)

Scripts require the extracted artifacts retained beside them and the project's pinned environment. From the project directory, `.venv/bin/python -B /tmp/sentinelid-unsupervised-audit-z4jbt3dr/investigate.py` reconstructs the main scratch outputs. `window_sensitivity.py` adds the copied-input sensitivity and positive transformed-window checks. These commands write only inside the scratch directory, but overwrite its diagnostic outputs; they do not create a new untouched evaluation.

This report is stored outside the project in a temporary directory. Copy or attach it to the build discussion if it needs permanent retention.

## Durable preservation note

Copied from the October 7 read-only investigation. Other scratch links and script instructions refer to the original temporary workspace and are not public reproduction instructions. Use the experiment guide for the maintained reproduction path. The historical PCA diagnostic is retained as provenance only and is excluded from the corrected factorial experiment.
