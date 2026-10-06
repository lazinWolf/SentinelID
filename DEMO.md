# Midterm demonstration guide

## Presentation claim

> We built a behavioral identity-attack detection pipeline that processes original CERT activity, computes causal history-based features, applies a frozen model and creates budgeted investigations with original evidence and analyst feedback. Results are preliminary benchmark measurements.

Use [ARCHITECTURE.md](ARCHITECTURE.md) for diagrams and [README.md](README.md) for methodology and results. The walkthrough uses the completed saved run, not newly computed live evaluation outcomes.

For a fresh checkout, first follow README setup: download the artifacts with `setup --accept-data-license`, verify them, and finish `replay` before presenting. The GitHub repository does not contain a completed application database.

## Preflight

Run from the checkout on the machine containing the prepared local data and model:

```bash
.venv/bin/python -m unittest discover -s tests -q
.venv/bin/python -m sentinelid verify
.venv/bin/python -m sentinelid status
.venv/bin/python -m sentinelid serve
```

Open **http://127.0.0.1:8767/**. If that server is already running, use the existing instance. The prepared demo should show a completed run, 14,143,645 processed records, 30 scored days and 31 cases. Open a case and check original evidence retrieval before presenting. The existing demo needs no downloads.

Run `verify --sources` ahead of time for deeper CSV/LDAP checksum verification. Avoid waiting for a large file scan during the presentation.

Keep the completed run selected. **Do not click New run during the main walkthrough**: it changes the current run and starts history acquisition from May, before November scoring. There is no short replay preset or quick demo reset yet. Pause is checked between committed batches, not after each event.

## Five-minute walkthrough

| Time | Show | Explain |
| --- | --- | --- |
| 0:00–0:45 | Architecture | Original activity becomes causal features, scores, candidates and cases |
| 0:45–1:15 | Saved results and run status | 14.1 million records were processed; records, scores, cases and incidents are different units |
| 1:15–2:45 | Open a case; expand closed-day measurements | Counts, lagged references, signed percentiles, transformed inputs and score gate |
| 2:45–3:45 | Expand original evidence | Source fields, event IDs, timestamps and current versus retained context |
| 3:45–4:15 | Analyst feedback controls | Versioned reviews remain separate from benchmark truth |
| 4:15–5:00 | Comparison and limitations | RF reaches more incidents at slightly greater cost; explain the formal verdict |

An example in the prepared database is **EDB0714**, admitted on November 2 at 08:00, with score approximately **0.9732**, gate **0.4056** and **115 retained records**. Choose its earliest case because the identity appears more than once. Its existing review is an engineering QA note, not attack adjudication.

Show feedback controls without saving to preserve the demonstration state. Saving creates a real local review version; label any demonstration note as presentation feedback rather than a confirmed malicious finding.

## Suggested slides

1. Problem: suspicious activity involving authenticated identities and the need for behavioral context.
2. Dataset: synthetic CERT r4.2, five activity sources and monthly LDAP; scope and date coverage.
3. Related approaches: rules, unsupervised IF and supervised RF; connect choices to archived research.
4. Architecture: ingestion, causal features, scoring, admission, persistence and review.
5. Methodology: chronological development, final fitting, freeze and separate November outcomes.
6. Results: RF 31 investigations / 21 current-positive / 9 of 11 timely incidents; IF 30 / 3 / 2 of 11.
7. Demo: trace one case through measurements and original evidence.
8. Limitations and next steps: admission losses, recurring incidents, source quality and independent evaluation.

## Questions to prepare for

**Why is improvement unestablished when RF detects more incidents?** The primary criterion required no greater investigation cost. RF used 31 admissions versus IF's 30, so it failed that condition despite stronger observed coverage and yield.

**Is 9/11 model accuracy?** No. It is incident coverage under an evidence-timing rule: a relevant retained malicious record must be admitted within 72 hours of that record. Classification and investigation yield use different denominators.

**Does inference use validation labels or future behavior?** Features use lagged historical context. RF was fitted using permitted historical event/day labels. Active inference does not import evaluator truth; saved outcomes in `results.json` are displayed separately.

**Are peer features model inputs?** Not for the selected RF. They are computed for inspection; the PM model uses 33 personal percentile, magnitude and novelty inputs.

**Can replay restart?** SQLite retains unfinished history, pending candidates and the committed cursor. Outputs and checkpoint share a transaction. Unit tests check rollback and checkpoint persistence; a real-source resume check was performed during consolidation. This saved-case walkthrough does not itself demonstrate a fresh live replay.

**Where are training, rules and simulation?** Their implementations and results remain in the verified recovery archive. The active CLI exposes the selected model's operational replay, not training or the complete experiment runner.

**What remains before production?** Independent validation, live connectors, source-quality monitoring, efficient seeking, authentication and deployment work. Analyst feedback records notes and dispositions; it does not retrain the model.
