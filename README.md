# SentinelID

**Identity attack detection using behavioral analytics, causal event replay and evidence-based investigation.**

SentinelID is an academic and portfolio research prototype built around the CERT r4.2 insider-threat benchmark. It turns activity records into identity-level behavioral measurements, scores them with a saved machine-learning model, and admits a limited number of investigations with inspectable original evidence.

The current application implements operational replay and investigation. Earlier rule-based detection, training, simulations and full evaluations are preserved in a local recovery archive. This is a midterm research prototype, not a production identity-security service.

[Architecture and pipeline diagrams](ARCHITECTURE.md) · [Midterm demonstration guide](DEMO.md)

## Capabilities

- Original-record ingestion from five activity sources with exact-month LDAP identity context.
- Ordered replay, source-order checks and strict email attachment schemas.
- Causal daily features from lagged personal history; fixed Random Forest scoring.
- Budgeted investigation admission with candidate merging, cooldown and expiry.
- Atomic SQLite checkpoints, immutable cases and versioned analyst reviews.
- A local dashboard exposing transformed model inputs, historical references and original source evidence.

```text
CSV + LDAP → ordered records → daily history → features → model score
          → threshold + investigation queue → persistent cases → evidence + review
```

## Quick start

Run from this checkout. The tested environment is **Linux, Python 3.14.3 and scikit-learn 1.9.1**. Replay uses POSIX locking; on Windows, use a Linux environment such as WSL. Use the pinned dependencies for the saved model.

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -q
```

If the project environment already exists, use it directly. Unit tests do not require the large dataset, model or recovery archive.

With local runtime artifacts in place:

```bash
.venv/bin/python -m sentinelid verify
.venv/bin/python -m sentinelid serve
```

Open **http://127.0.0.1:8767/**. The existing project machine has a completed demonstration with 31 cases. A fresh checkout does not include the pretrained model or saved database.

### Local data and model

The official benchmark is available through the [CMU Software Engineering Institute dataset page](https://www.sei.cmu.edu/library/insider-threat-test-dataset/). This project uses two prepared, disjoint date shards:

```text
data/
├── model.joblib                 # Selected model matching config.json's checksum
├── provenance.json             # Acquisition details and CSV/LDAP checksums
├── operations.sqlite           # Optional saved demo; created on runtime use
└── raw/
    ├── recovery-v3/             # May 1–October 14, 2010
    │   ├── device.csv, email.csv, file.csv, http.csv, logon.csv
    │   └── LDAP/                # Monthly CSV snapshots, May–October
    └── workload-v4/             # October 15–November 30, 2010
        ├── device.csv, email.csv, file.csv, http.csv, logon.csv
        └── LDAP/                # October and November snapshots
```

These artifacts and the recovery archive are excluded from Git. Restore prepared local artifacts or recover the historical acquisition/training code below. The active CLI does not download, prepare or train them; downloading the full benchmark alone does not recreate this artifact contract.

Keep source CSV bytes unchanged because evidence uses original IDs and byte offsets. Saved database pointers contain absolute paths, so moving the demo to another machine requires rebasing those pointers. `verify --sources` hashes CSV and LDAP files against local provenance; it does not certify equality to a complete official archive. Model/checkpoint files use Python serialization and should come from a trusted project source.

## Commands

Prefix each command with `.venv/bin/python -m sentinelid`:

| Command | Purpose |
| --- | --- |
| `status` | Show the latest persisted run, selected model and case count |
| `verify` | Check the model checksum and required source-file presence |
| `verify --sources` | Also verify all original CSV and LDAP checksums |
| `serve --port 8767` | Start the local investigation dashboard |
| `replay --new --events 100000` | Create a separate run and process a bounded batch |
| `replay --events 100000` | Resume the latest run for another bounded batch |
| `replay` | Resume until completion |
| `replay --checkpoint-on-pending` | Stop at a day boundary with candidates awaiting a decision |

`--new` retains earlier runs but makes the new run current in the dashboard. New runs build history from May; scoring starts in November, so initial progress does not immediately produce alerts. For a midterm, use the saved completed demonstration. Pause takes effect between committed batches.

One writer owns a database at a time. Resume requires the same configuration identity. Changing `config.json` requires a separate run; it does not validate a new experiment. These commands neither retrain models nor recompute benchmark outcomes.

## Methodology

The scoring unit is an **eligible identity-day**. Targets span 1, 3 and 7 calendar days. Personal references use 28 lagged historical endpoints with a seven-day lag and extra context for multi-day aggregates. Signed percentiles retain direction; magnitude features preserve information beyond percentile saturation.

The selected Random Forest uses **33 inputs**, 100 trees, maximum depth 8, minimum leaf size 3, balanced subsample weights and seed 42. Inputs combine personal percentiles, magnitude and novelty. Historical peer measurements are computed for inspection, but **are not inputs to the selected model**.

| Research phase | CERT calendar interval |
| --- | --- |
| Model/policy selection | Two earlier chronological development blocks; full protocol archived |
| Final fitting | June 8–October 14, 2010; 85,688 eligible rows |
| Label-free workload-gate calibration | October 15–21, 2010 |
| Frozen validation scoring | November 1–30, 2010, followed by the declared queue drain |

Deployment uses the development-selected **fitting-score gate**, approximately **0.405628**, maximum pending-score priority, one admission per decision day, seven-day cooldown and three-day backlog limit. The workload-calibrated gate is an evaluated alternative, not the deployed gate. Decisions occur at 08:00 after each scoring day, with three extra daily decisions to drain the backlog.

## Measured results

Frozen November results from [results.json](results.json):

| System | Investigations | Current-positive investigations | Context-positive investigations | Timely incidents |
| --- | --- | --- | --- | --- |
| Selected Random Forest | 31 | 21 | 23 | 9/11 |
| Corrected Isolation Forest | 30 | 3 | 5 | 2/11 |

An investigation is one queue admission, not measured analyst labor. Current-positive means a labelled malicious record appears in the trigger period; context-positive includes retained evidence. A timely incident requires relevant retained malicious evidence admitted within 72 hours of that record. This is not necessarily detection within 72 hours of incident onset, nor is incident coverage classification accuracy.

**Formal matched-cost improvement remains unestablished:** RF used one extra investigation and failed the predeclared non-greater-cost condition. RF uses fitting labels; IF does not. Two validation incidents recur in fitting. CERT is synthetic, so these results do not establish production or unseen-identity performance. Evidence presence does not identify exactly which event caused a forest prediction.

The saved replay processed **14,143,645 original records**, produced **18,772 scores** and admitted **31 cases**. Consolidation checks preserved all saved scores and queue decisions, matched 907 reconstructed real-day feature rows, and retained cases and reviews. These are historical regression measurements; unit tests alone do not reproduce the frozen evaluation.

## Project structure

```text
sentinelid/                # Ingestion, features, scoring/queue/replay, store, server and CLI
dashboard/                # HTML, JavaScript and CSS investigation interface
tests/test_pipeline.py    # Feature, queue, checkpoint and review regressions
.github/workflows/ci.yml  # Dataset-free unit test workflow
config.json               # Runtime settings and selected model identity
results.json              # Saved comparison and measured verdict
ARCHITECTURE.md            # Pipeline, research boundary and recovery diagrams
DEMO.md                    # Midterm walkthrough and discussion notes
requirements.txt          # Exact dependency versions for the saved model
pyproject.toml            # Project metadata and lint configuration
data/                     # Local only: originals, model and application state
archive/                  # Local only: recoverable historical work
```

Source, configuration, saved result summaries and documentation belong in Git. Data, model binaries, databases, archives, credentials and caches remain local. The CI workflow runs tests without downloading benchmark data; hosted execution is separate from local verification.

## Scope and next steps

Implemented: original-record replay, causal features, fixed-model scoring, admission, durable state, evidence inspection and analyst feedback. Training, rule comparisons, simulations and full outcome evaluation are recoverable historical work.

Next steps: a short checkpoint-based live demo, admission/evidence-refresh improvements, source-quality monitoring, efficient replay seeking and independent evaluation intervals/identities. The current server has no production authentication or live identity-provider integration. Feedback is stored; it does not automatically retrain the model.

## Recover historical work

The local `archive/research-history.tar.zst` contains 1,313 members plus `RECOVERY_MANIFEST.json`, including 155 protected artifacts. Its verified SHA-256 is:

```text
05de10fcec9ed156e8c7a50e2975f031b69c567ffff5031b943403d24069684f
```

With `tar` and `zstd` available, extract into a separate directory:

```bash
mkdir -p /tmp/sentinelid-history
tar --zstd -xf archive/research-history.tar.zst -C /tmp/sentinelid-history
```

The archive preserves earlier compatibility links, implementations and experiments. Historical replay also needs the two retained raw shards under the extracted `data/raw/` directory. An external presentation dependency link does not bundle dependencies. Duplicate range-download scratch was removed; selected originals remain. Preserve consumed outcomes and frozen artifacts when beginning new experiments.

## Dataset attribution

The synthetic CERT Insider Threat Test Dataset is published by the CMU Software Engineering Institute. See the [official description](https://www.sei.cmu.edu/library/insider-threat-test-dataset/) and [dataset record](https://doi.org/10.1184/R1/12841247.v1). Local acquisition and mirror receipts are in `data/provenance.json`; benchmark terms and attribution are separate from this project's code.
