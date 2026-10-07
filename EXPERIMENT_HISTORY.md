# Experiment history and research progression

Historical results live here as a record of the project's process. They are **outside the corrected optional-module factorial comparison**, its control selection and paired effect calculations. Different periods, units, feature contracts, labels and workloads must not be pooled into a single improvement curve.

## Preserved historical stages

| Stage | Contract / period | Recorded finding | Source |
| --- | --- | --- | --- |
| Rules R versus supervised S2 | Active identity-hours; August 1–14 | Rules: 4 TP, 12 FP, 132 FN; S2: 10 TP, 37 FP, 126 FN. Both missed all 111 scenario-2 positive hours. | [Original classification report](data/experiments/inputs/history/classification-pipeline.md) |
| Daily recovery IX28 | October 1–14 | IX28 reached 9/10 incidents with 60 investigations; rules 2/10 with 12; S2 2/10 with 23. Recovery at matched workload was not established. | [Original recovery report](data/experiments/inputs/history/DETECTION_RECOVERY.md) |
| Frozen November RF / C_IF comparison | Historical v4; November | RF: 31 admissions, 21 current-positive, 23 context-positive, 9/11 timely. IF: 30, 3, 5, 2/11. Formal improvement was not established because RF used one extra admission. | [Original saved results](results.json); [original workload report](data/experiments/inputs/history/IF_WORKLOAD_IMPROVEMENT.md) |
| October 7 read-only investigation | Consumed v4 fitting/calibration/November | Found material three-day magnitude chronology defect; reproduced five score arrays exactly and verified selected admissions. Historical PCA diagnostic is preserved only as provenance. | [Investigation](reports/UNSUPERVISED_INVESTIGATION.md), [measurements](reports/unsupervised-investigation.json) |

The local recovery archive preserves implementations and original reports. The experiment command restores the named historical reports beneath `data/experiments/inputs/history/`. Those links work after local archive restoration; the files are not part of the public source repository.

The durable investigation keeps its findings unchanged, rebases the main measurement link and adds a clearly marked preservation note. Its supporting JSON is byte-identical to the temporary original. Remaining scratch links describe the earlier investigation, not the maintained experiment entry point.

## New corrected research stage

`behavior-experiment-v1` makes the three-day USB/copy magnitude target consecutive: today and the preceding two days. Historical v4 inference is untouched. Fitting/calibration vectors and experimental models are regenerated.

The corrected all-off controls establish the starting point for new RF/IF ablations. The historical baseline reproduction audit belongs to preservation, not the new comparison tables. Correction effects may be described here separately; they are not a claim of independent detection improvement.

The new comparison uses eight configurations per family: temporal persistence/co-occurrence, historical peer measurements and learned relevance priority, independently off/on. Structured outputs retain measurements and evidence. Detector score and priority stay separate through persistence and resume.

See [experiment methodology](EXPERIMENTS.md) and [corrected comparison](reports/EXPERIMENT_COMPARISON.md) for the current milestone. Raw data, models, hashes, chronological blocks and manifests are recorded in its isolated run directory. November remains consumed; deployment is unchanged.

### Correction effects, separate from module effects

For RF, the old 33-input PM contract reported AP 0.78525, 83/97 positive days passing the fitting gate, 31 admissions, 21 current-positive and 9/11 timely reach. The corrected all-off RF control reports AP 0.80220, 84/97 passing, 30 admissions, 17 current-positive and 8/11 timely reach. Correcting semantics slightly improved scoring diagnostics while reducing observed operational reach and yield. Correctness is a prerequisite; it is not itself evidence of operational improvement.

The earlier PM IF baseline at 100 trees / 1,024 samples reported 32 admissions, two current-positive, five context-positive and 2/11 timely reach. Its corrected all-off counterpart reports 31, four, seven and 4/11. This historical comparison belongs here; it is excluded from new factorial effects. It should not be conflated with the historical C_IF magnitude representation or REP_IF's different 200/256 settings.

The correction regenerated 114,895 eligible measurement rows; USB three-day magnitude changed in 18,966 and copy magnitude in 17,846. Exact date tests verify unchanged one/seven-day targets, percentiles and eligibility. Experimental models were refit; the deployed historical model was not altered.

### Optional-module verdict

Completed run: `abcd831c3f4e3171fa84`. All 16 corrected configurations used the frozen protocol, three chronological held-out ranking blocks and identical November scoring dates/drain.

RF with peers and native ordering was the only cell satisfying the declared **observed retrospective cost criterion**: 30 admissions, 21 current-positive (70%) and 9/11 timely reach, compared with the corrected RF control's 30, 17 (56.7%) and 8/11. Temporal and learned-ranking effects were mixed or negative. No IF variant exceeded its corrected control's 4/11 timely reach. The combined temporal/peer/learned variants reached 7/11 for RF and 3/11 for IF.

No independent validation period is available, so validated improvement remains unestablished and deployment remains unchanged. [Measured findings](reports/EXPERIMENT_FINDINGS.md) describe interactions, gate losses and detector/module disagreements. [Preservation evidence](reports/experiment-preservation.json) records unchanged operational artifacts, exact historical reproduction, native queue equivalence and fresh-process checkpoint verification.

An earlier implementation attempt is retained at `data/experiments/394f4f5f36e57f7b32b7/`: its models were fitted, all variants checkpointed, and the first completed queue exposed a NumPy-to-JSON report error. That run has no complete comparison. The error was fixed and tested before the completed versioned run; no failed or partial result was inserted into the final matrix.

## Progression rules

- Preserve historical source/artifact hashes and consumed outcomes.
- Name feature/schema corrections and refit experimental models when input semantics change.
- Compare optional modules with a compatible corrected control in the same family and protocol.
- Keep native IF and supervised-assisted IF distinguishable.
- Record negative effects, workload tradeoffs and unavailable training support.
- Require a separately reserved independent evaluation before a future validated improvement claim or promotion.
