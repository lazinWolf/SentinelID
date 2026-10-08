# SentinelID demo guide

How to run the project in its current state and walk through it in about five minutes.

**What you are showing:** a behavioral identity-attack detection pipeline. It processes original CERT r4.2 activity, computes causal history-based features, scores identity-days with a frozen Random Forest, and admits a budgeted number of investigations (one per day) with original evidence and versioned analyst review. Results are preliminary benchmark measurements.

Related docs: [README.md](README.md) (methodology, results, CLI), [ARCHITECTURE.md](ARCHITECTURE.md) (diagrams).

## 1. Prerequisites

The demo uses the **completed saved run** in `data/operations.sqlite`. It needs no downloads and does not re-process the 14 million records.

Check that these exist on the machine:

| Path | Purpose |
| --- | --- |
| `.venv/` | Python environment (joblib, numpy, scikit-learn, scipy) |
| `data/model.joblib` | Frozen REP_RF model |
| `data/raw/` | Original CERT CSV/LDAP files, used for evidence retrieval |
| `data/operations.sqlite` | Completed run: scores, queue trace, 31 cases, reviews |
| `results.json` | Saved RF vs IF benchmark outcomes |

**Fresh clone?** The repository does not include the database. First run, from the project root:

```bash
.venv/bin/python -m sentinelid setup --accept-data-license   # download model + data
.venv/bin/python -m sentinelid verify --sources              # checksum everything
.venv/bin/python -m sentinelid replay                        # full run, long; do this well before presenting
```

If `.venv` is missing: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`.

## 2. Preflight (5 minutes before)

Run from the project root. All of these were checked on the current files.

```bash
.venv/bin/python -m unittest discover -s tests -q   # expect: Ran 25 tests ... OK
.venv/bin/python -m sentinelid verify               # expect: model_checksum "verified", sources "present"
.venv/bin/python -m sentinelid status               # expect the numbers below
```

`status` should show:

- run status `completed`, 14,143,645 / 14,143,645 events processed
- 30 closed days, 18,772 scored identity-days, last scored day 2010-11-30
- 31 cases, detector `REP_RF`

Optional, ahead of time only (slow): `verify --sources` hashes every CSV/LDAP file.

## 3. Start the dashboard

```bash
.venv/bin/python -m sentinelid serve
```

Open **http://127.0.0.1:8767/** (`--host` / `--port` are available). Leave the terminal open. If port 8767 is already in use, a server is probably already running; just use it.

The first load of **Day replay** reads the checkpoint and takes a few seconds (about 4 s measured); open that tab once before presenting so it is cached.

Before the audience arrives:

1. Open a case (e.g. EDB0714) and expand an original record to confirm evidence retrieval works.
2. Click Day replay → **Reset** so you start at November 1.
3. Press **P** (outside a text field) or use **Presentation mode** in the header for larger text on a projector.

The dashboard has four tabs: **Pipeline**, **Day replay**, **Investigations**, **Benchmark results**.

## 4. Safety rules during the demo

- **Do not create a new operational run.** That control is under *Advanced* on the Pipeline tab. It changes the current run and rebuilds history from May.
- **Reset is safe.** It only changes the displayed playback day; it creates no run and deletes no cases.
- **Don't save feedback** unless you want a real review version written to the local database. If you do save, label it "presentation feedback", not a confirmed malicious finding.
- Stop the server with Ctrl+C in its terminal when finished.

## 5. Walkthrough (about 5 minutes)

| Time | Show | Say |
| --- | --- | --- |
| 0:00–0:45 | **Pipeline** tab | Original activity → causal features → score → candidates → cases. Point at the counters: 14,143,645 records, 18,772 scored identity-days, 31 investigations. These are different units; budget is one admission per day. |
| 0:45–1:45 | **Day replay**, Nov 1–4 | Step through. Nov 1: 918 eligible identity-days, six above the gate, one admitted (EDB0714), five pending. Nov 2: EDB0714's higher score is suppressed by cooldown, TNM0961/ABC0174 merge into existing candidates, IUB0565 admitted, ten waiting. Nov 4 shows pending expiry. Use Play briefly, then Pause; demonstrate scrubbing. |
| 1:45–3:00 | **EDB0714** (Pipeline shortcut or Nov 1 admitted-case button): *Decision* and *Measurements* | Counts, lagged reference windows, signed percentiles, transformed inputs, and the score vs gate. |
| 3:00–4:00 | *Original records* and *Review history* | Expand a record: CSV fields, event ID, byte offset. Current vs retained context. Reviews are versioned and separate from benchmark truth. |
| 4:00–5:00 | **Benchmark results** | RF 31 investigations / 21 current-positive / 9 of 11 timely incidents; IF 30 / 3 / 2 of 11. RF covers more incidents but at one more admission, so the formal "no greater cost" criterion is not met. |

EDB0714 facts: admitted Nov 2 at 08:00, score about 0.9732, gate 0.4056, 115 retained records. Choose its earliest case since the identity appears more than once. Its existing review is an engineering QA note, not attack adjudication.

## 6. What Day replay is (and isn't)

It is a **recorded-run simulation for presentation**. It reads committed scores and queue decisions from the completed database and projects them onto 30 scoring days plus 3 queue-drain steps, verifying the end state against the stored queue.

It does **not** re-ingest CSVs, recompute features, run the model, change policy, inject attacks, recompute evaluation outcomes, or write application state. Say this out loud so the audience does not think it is a live detection run.

## 7. If something goes wrong

| Symptom | Fix |
| --- | --- |
| `Address already in use` | A server is already running on 8767; use it, or `serve --port 8768`. |
| Day replay says unavailable / empty | The completed run is missing (fresh clone). Run `replay` to completion. |
| Day replay slow first time | Expected (a few seconds); later navigation is cached. |
| Evidence won't expand | Check `data/raw/` exists; run `verify`. |
| Wrong run or odd state shown | `status` should show one completed run with 31 cases; if you created a new run, select the completed one `bc676ca5…` again. |
| Tests fail | Stop and fix before presenting; they cover rollback and checkpoint persistence. |

## 8. Suggested slides

1. Problem: suspicious activity by authenticated identities; need for behavioral context.
2. Dataset: synthetic CERT r4.2, five activity sources plus monthly LDAP; scope and date coverage.
3. Related approaches: rules, unsupervised IF, supervised RF (see [literature_review.md](literature_review.md)).
4. Architecture: ingestion, causal features, scoring, admission, persistence, review.
5. Methodology: chronological development, final fitting, freeze, separate November outcomes.
6. Results: RF 31 / 21 / 9 of 11; IF 30 / 3 / 2 of 11.
7. Live demo: trace one case from measurements to original evidence.
8. Limitations and next steps: admission losses, recurring incidents, source quality, independent evaluation.

Fuller speaker material is in [present.md](present.md) and [present-script.md](present-script.md).

## 9. Questions to prepare for

**Why is improvement unestablished when RF detects more incidents?** The primary criterion required no greater investigation cost. RF used 31 admissions versus IF's 30, so it failed that condition despite stronger coverage and yield.

**Is 9/11 model accuracy?** No. It is incident coverage under an evidence-timing rule: a relevant retained malicious record must be admitted within 72 hours of that record. Classification and investigation yield use different denominators.

**Does inference use validation labels or future behavior?** No. Features use lagged historical context. RF was fitted on permitted historical labels. Saved outcomes in `results.json` are displayed separately.

**Are peer features model inputs?** Not for the selected RF. They are computed for inspection; the PM model uses 33 personal percentile, magnitude and novelty inputs.

**Can replay restart?** Yes. SQLite keeps unfinished history, pending candidates and the committed cursor; outputs and checkpoint share a transaction. Unit tests check rollback and persistence. This walkthrough itself does not run a fresh live replay.

**Where are training, rules and simulation?** Earlier implementations are in the verified `archive/` recovery tarball. The app adds only read-only recorded-day playback, not a delivery-fault or attack-injection simulator. Corrected experiments live on the separate `experimental` branch; this demo uses the frozen deployed baseline.

**Why are the three-day magnitude targets unusual?** The frozen feature contract has a documented chronology defect: USB/copy magnitude uses today plus five/six days ago, while the percentile uses consecutive days. The saved model keeps it for reproducibility; corrected experiments were refit separately and not deployed.

**What remains before production?** Independent validation, live connectors, source-quality monitoring, efficient seeking, authentication and deployment. Feedback records notes and dispositions; it does not retrain the model.
