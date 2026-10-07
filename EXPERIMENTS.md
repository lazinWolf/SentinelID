# Optional experiment layer

The deployed application remains the historical baseline. `experiment` is a separate research command; it does not modify `config.json`, the deployed model, active database, cases, reviews or dashboard. PCA is excluded.

## Reproduction

This milestone needs the **local research archive**, prepared original data and pinned project environment. A public clone alone does not include the archive or archived labels/feature cache. Follow README runtime setup first. Archive SHA-256 is recorded in the project summary and verified before extraction.

```bash
.venv/bin/python -m unittest discover -s tests -q
.venv/bin/python -m sentinelid experiment --config experiments.json
```

An interrupted experiment resumes with:

```bash
.venv/bin/python -m sentinelid experiment --config experiments.json --resume
```

For a bounded checkpoint demonstration, append `--stop-after-days 1`, then resume without that limit. The limit counts additional scoring/decision days per configuration, including drain. Experiments replay cached eligible identity-days through the maintained queue; they do not re-ingest the full dataset for every combination. A shared source pass resolves evidence pointers and verifies representative original daily counts.

The default configuration creates **eight RF and eight IF combinations**. Each of the four switches accepts a supported scalar value or a list of values. Input names and dependencies are resolved centrally. Use all-off temporal/peer options and native ranking as each family's corrected control. Never compare a single modified configuration against an incompatible historical representation as though it were a factorial control.

## Output and isolation

`data/experiments/inputs/` contains checksum-verified copies of selected archived inputs. Each experiment has a deterministic directory derived from configuration, protocol, input and code identities. It contains:

- Frozen protocol, corrected reusable measurement cache and its checksum.
- Four detector representations per family, chronological held-out models, rankers, score arrays and model manifests.
- One isolated SQLite database per switch combination, with checkpoints and explicit `detector_score` and `priority_score` columns in `experiment_scores`.
- Case payloads, observations with structured module outputs, queue decisions, event-loss records and metrics.
- Original evidence-pointer index, source compatibility checks and preservation audit.

A process lock prevents competing writers. Batches atomically commit observations, separate scores, cases and checkpoints. Existing incompatible artifacts fail verification. Results never write into `data/operations.sqlite`. Configuration and model identity must match on resume.

The compact corrected results are exported to [EXPERIMENT_COMPARISON.md](reports/EXPERIMENT_COMPARISON.md) and `reports/experiment-comparison.json`. The completed milestone's [measured findings](reports/EXPERIMENT_FINDINGS.md) add numerical interactions and set disagreements; its [preservation evidence](reports/experiment-preservation.json) records full checks. [EXPERIMENT_HISTORY.md](EXPERIMENT_HISTORY.md) keeps historical stages separate. Historical results are excluded from corrected tables, paired effects and configuration selection.

The recorded run is `abcd831c3f4e3171fa84`; all 16 configurations completed 30 scoring days and three drain decisions after a separate-process resume. The 33-test suite, source verification, lint and compilation passed. All eight native variants matched the maintained queue's cases/decisions exactly. A shared evidence pass resolved 77,482 original pointers and checked 63 real identity-day count reconstructions.

## Feature contracts and reusable measurements

Historical `behavior-workload-v4` keeps the known three-day magnitude target defect. It uses today plus five/six days ago while its percentile target uses today plus one/two days ago. The preserved model and scores must keep that contract.

Experimental `behavior-experiment-v1` corrects only those USB/copy magnitude targets and refits models. Personal references, eligibility, novelty, peer semantics and the queue policy remain unchanged. Exact target dates are retained in the observation audit.

Temporal and peer modules return immutable, serializable structured outputs. They retain measurements, definitions, availability, target/reference dates, coverage/support and supporting event IDs. Model-vector adapters consume those values; inspection and evidence reuse the structured outputs directly. Metadata such as identity and group names never becomes a model input.

Temporal measurements use the trailing seven calendar days. Missing user activity on a covered date contributes zero counts; missing source coverage makes the row ineligible under the existing common requirements. Personal references use the existing eligibility/support checks and the scoring day's lagged statistics:

- USB/copy persistence: share of days with magnitude at least 1 and below 3 against the scoring day's lagged personal daily reference.
- Copy/after-hours co-occurrence: copy-active days containing an after-hours logon divided by copy-active days, with zero for no copy activity. This is daily co-occurrence, not within-session association.

Peer outputs reuse existing supported, historical, self-excluding team/role comparisons. Unsupported groups remain explicit with neutral values and support=0. Target source-context IDs are retained; they are not exact peer-event attribution. Modules do not alter the common eligible population.

## Scoring and priority

RF uses the saved family settings: 100 trees, depth 8, minimum leaf size 3, balanced subsample weights, seed 42. IF uses 100 trees, 1,024 samples and seed 42. All representations use a 99th-percentile fitting-score gate.

Detector scores alone decide whether an offer passes the gate. Native priority equals detector score, but remains separately stored. Learned priority comes from standardized L2 logistic regression (`C=1`, balanced weights, seed 42), predicting whether seven-day evidence available at candidate creation contains an exact labelled malicious record.

Ranker training uses detector predictions from expanding historical fits before July 15, August 15 and September 15. Corresponding held-out predictions run through the next cutoff, ending October 14. Scaling and logistic fitting use these held-out training rows only. Engineering reviews and November labels are excluded. If both target classes are unavailable, the learned variant is reported unavailable instead of silently replaced.

Inputs are detector score, selected personal evidence measurements and enabled module values. Disabled temporal/peer modules contribute no priority or detector inputs. IF plus learned ranking is supervised-assisted; it is not a purely unsupervised system.

Ranking pairs share identical pre-queue offers and gates. Changing ordering can alter later cooldown/expiry state. Merging independently retains maximum detector score and maximum offered priority, with separate histories and originating days. Priority is not refreshed between offers. One daily admission, 08:00 decisions, seven-day cooldown, three-day expiry and the declared drain remain fixed.

## Interpretation

Fitting is June 8–October 14; calibration diagnostics cover October 15–21. November is **consumed retrospective evidence**. No new independent validation period is established, and no configuration is deployed automatically.

Reports distinguish detector AP/recall, priority ranking, admitted investigations, current/context evidence, timely incidents, delays and terminal event losses. Actual admissions—not the shared daily cap—measure the declared workload proxy. An observed cost criterion requires no greater admissions, greater timely reach and nonlower current-positive yield than the corrected family control. Satisfaction would remain retrospective, not validated superiority.

Higher priority cannot rescue an attack whose day fails the detector gate, although later retained context can present a record from such a day. Terminal event assignments therefore are not a monotone funnel. Original evidence does not establish exact forest attribution or measured analyst effort.
