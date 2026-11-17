"""SentinelID: identity-based attack detection using behavioural analytics.

Module map

Application (replay original records, score each identity-day, admit one investigation a day):
    ingestion      CERT records, schema checks, evidence pointers to the original lines
    features       causal daily history per identity: signed percentiles, magnitudes, novelty
    pipeline       frozen-model or adaptive scoring, the budgeted queue, resumable replay
    adaptive       label-free tail scorer re-weighted by analyst verdicts
    store          atomic SQLite state, immutable cases, versioned reviews
    server         local dashboard API; presentation: read-only day playback; signals: case reasons
    demo, setup    invented demo organisation; checksum-pinned CERT acquisition

Research (development backtest, sealed holdout, label-free and feedback studies):
    research_data  shard replay, cached rows, offline truth
    research       backtest, holdout and its use ledger, identity coverage
    detectors      every compared detector; neural: the PyTorch ones
    feedback       analyst-feedback learning; ledger: population-context features
    methods        the predeclared methods study (docs/methods-study.md)
    reporting      markdown reports regenerated from saved results

October corrected factorial study (kept for its report; shared helpers are reused above):
    experiments, experiment_data, experiment_features, experiment_models,
    experiment_queue, experiment_replay, experiment_evaluation, experiment_io
"""
