"""Small isolated factorial runner: cached measurements, fixed models and case replay."""

import fcntl
import gzip
import json
import os
import sqlite3
import sys
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

import joblib
import numpy as np
import sklearn

from .experiment_data import arrays, prepare, source_rows
from .experiment_evaluation import evaluate
from .experiment_io import capture_preservation, digest, fingerprint, restore_inputs, save_json
from .experiment_models import configurations, feature_matrix, model_key, train
from .experiment_replay import ExperimentReplay
from .features import Day, original_records
from .ingestion import ROOT
from .pipeline import WorkloadQueue, predict


def baseline(inputs, root):
    """Reproduce old artifacts separately; none are corrected factorial controls."""
    saved = json.loads((inputs / "validation-scores.json").read_text())
    meta = json.loads((inputs / "final-models.json").read_text())
    all_rows = list(source_rows(inputs / "features.sqlite", "2010-10-26", "2010-12-01"))
    rows = [r for r in all_rows if r["day"] >= "2010-11-01" and r["common_eligible"]]
    if [(r["day"], r["identity_id"]) for r in rows] != [tuple(k) for k in saved["keys"]]:
        raise ValueError("Historical row ordering differs")
    context = {(r["identity_id"], r["day"]): r["event_ids"] for r in all_rows}
    cfg = json.loads((root / "config.json").read_text())
    result = {
        "scope": "Historical preservation only; excluded from corrected factorial results",
        "models": {},
        "admissions": {},
    }
    for key in ("C_IF", "C_MATCH_IF", "REP_BASE_IF", "REP_IF", "REP_RF"):
        checksum = digest(inputs / (key + ".joblib"))
        if checksum != meta["models"][key]["sha256"]:
            raise ValueError("Historical model changed: " + key)
        bundle = joblib.load(inputs / (key + ".joblib"))
        scores = predict(rows, bundle)
        error = float(np.max(np.abs(scores - np.asarray(saved["scores"][key]))))
        if error != 0:
            raise ValueError("Historical score reproduction failed: " + key)
        result["models"][key] = {"sha256": checksum, "maximum_score_error": error}
        if key not in ("C_IF", "REP_IF", "REP_RF"):
            continue
        queue = WorkloadQueue(cfg["queue"])
        by_day = defaultdict(list)
        for row, score in zip(rows, scores, strict=True):
            if score >= saved["gates"][key]["fit"]:
                by_day[row["day"]].append((row, float(score)))
        start = datetime(2010, 11, 1)
        for i in range(33):
            day = (start + timedelta(days=i)).date().isoformat()
            for row, score in by_day[day]:
                ids = sorted(
                    {
                        e
                        for j in range(7)
                        for e in context.get(
                            (
                                row["identity_id"],
                                (datetime.fromisoformat(day) - timedelta(days=j))
                                .date()
                                .isoformat(),
                            ),
                            [],
                        )
                    }
                )
                queue.offer(
                    {
                        "detector": key,
                        "identity_id": row["identity_id"],
                        "day": day,
                        "available_time": row["score_timestamp"],
                        "score": score,
                        "trigger_ids": row["event_ids"],
                        "evidence_ids": ids,
                        "qualifying_families": row["qualifying_families"],
                    }
                )
            queue.decide((start + timedelta(days=i + 1, hours=8)).isoformat())
        old = json.loads((inputs / (key + "-fit-max_cooldown-1-reviews.json")).read_text())
        fields = ("case_id", "identity_id", "decision_time", "score", "trigger_ids", "evidence_ids")
        if [{k: c[k] for k in fields} for c in queue.reviews] != [
            {k: c[k] for k in fields} for c in old
        ]:
            raise ValueError("Historical admission reproduction failed: " + key)
        result["admissions"][key] = {"count": len(old), "cases_scores_evidence_equal": True}
        if key == "REP_RF" and (root / "data/operations.sqlite").exists():
            with closing(
                sqlite3.connect(
                    "file:" + str((root / "data/operations.sqlite").resolve()) + "?mode=ro",
                    uri=True,
                )
            ) as db:
                latest = db.execute("SELECT id FROM runs ORDER BY rowid DESC LIMIT 1").fetchone()
                active = [
                    json.loads(r[0])
                    for r in db.execute("SELECT payload FROM cases WHERE run=?", latest)
                ]
            frozen = {c["case_id"]: c for c in old}
            if len(active) != len(old) or any(
                c["batch_case_id"] not in frozen
                or any(c[k] != frozen[c["batch_case_id"]][k] for k in fields if k != "case_id")
                for c in active
            ):
                raise ValueError("Active application cases differ from historical RF")
            result["active_rf_cases_equal"] = True
    return result, rows, context


def json_lines(path, rows):
    temporary = path.with_name(path.name + ".tmp")
    with gzip.open(temporary, "wt") as stream:
        for row in rows:
            stream.write(json.dumps(row, allow_nan=False) + "\n")
    os.replace(temporary, path)


def resolve_evidence(root, directory, rows, configurations_run):
    """One source pass resolves only needed original pointers and checks real daily counts."""
    needed = set()
    for output in configurations_run:
        with closing(sqlite3.connect(output / "operations.sqlite")) as db:
            for (payload,) in db.execute("SELECT payload FROM cases"):
                needed.update(json.loads(payload)["evidence_ids"])
    pointers = {}
    counts = {}
    selected = {"ABC0174", "EDB0714", "GHL0460"}
    cfg = json.loads((root / "config.json").read_text())
    observed = 0
    for event in original_records(cfg, datetime(2010, 10, 26)):
        observed += 1
        if event.event_id in needed:
            pointers[event.event_id] = event.pointer()
        if event.identity_id in selected:
            key = (event.timestamp.date().isoformat(), event.identity_id)
            counts.setdefault(key, Day(event.timestamp.date())).push(event)
            counts[key].pointers = []
        if observed % 500000 == 0:
            print("Verified source records in evidence pass:", observed, flush=True)
    if needed != pointers.keys():
        raise ValueError(
            "Missing original evidence pointers: " + str(len(needed - pointers.keys()))
        )
    matched = 0
    for row in rows:
        key = (row["day"], row["identity_id"])
        if row["identity_id"] in selected:
            if dict(counts[key].counts) != row["counts"]:
                raise ValueError(
                    "Original daily counts disagree with measurement cache: " + str(key)
                )
            matched += 1
    if not matched:
        raise ValueError("No original-day compatibility rows checked")
    json_lines(directory / "original-pointers.jsonl.gz", pointers.values())
    for output in configurations_run:
        with closing(sqlite3.connect(output / "operations.sqlite")) as db:
            with db:
                for cid, payload in db.execute("SELECT id,payload FROM cases").fetchall():
                    case = json.loads(payload)
                    case["evidence_pointers"] = [
                        {
                            **pointers[e],
                            "relationship": "current scoring period"
                            if e in case["trigger_ids"]
                            else "prior rolling context",
                        }
                        for e in case["evidence_ids"]
                    ]
                    db.execute("UPDATE cases SET payload=? WHERE id=?", (json.dumps(case), cid))
    return {
        "resolved_original_pointers": len(pointers),
        "original_day_counts_equal": matched,
        "source_pass_records": observed,
    }


def preservation(root):
    before = json.loads((root / "data/experiments/preservation-before.json").read_text())
    after = {name: digest(root / name) for name in before}
    expected = {"sentinelid/__main__.py", "sentinelid/pipeline.py"}
    unexpected = [name for name in before if before[name] != after[name] and name not in expected]
    if unexpected:
        raise ValueError("Protected artifacts changed: " + ", ".join(unexpected))
    return {
        "before": before,
        "after": after,
        "protected_unchanged": sum(before[name] == after[name] for name in before),
        "expected_source_extension_points": sorted(expected),
        "unexpected_changes": unexpected,
        "active_database_model_configuration_results_sources_archive_unchanged": True,
    }


def reports(root, directory, configs, results, manifests):
    by_id = {r["configuration_id"]: r for r in results}
    effects = []
    for config, result in zip(configs, results, strict=True):
        control = next(
            (
                r
                for c, r in zip(configs, results, strict=True)
                if c["detector"] == config["detector"]
                and c["representation_extension"] == "off"
                and c["peer_context"] == "off"
                and c["ranking"] == "detector_score"
            ),
            None,
        )
        if result.get("status") == "unavailable" or not control:
            result["observed_cost_criterion"] = None
            continue
        result["delta_vs_corrected_control"] = {
            k: result[k] - control[k]
            for k in (
                "admissions",
                "current_positive",
                "context_positive",
                "timely_incidents",
                "detector_average_precision",
            )
        }
        result["observed_cost_criterion"] = bool(
            result["admissions"] <= control["admissions"]
            and result["timely_incidents"] > control["timely_incidents"]
            and result["current_positive_yield"] is not None
            and control["current_positive_yield"] is not None
            and result["current_positive_yield"] >= control["current_positive_yield"]
        )
        for switch in ("representation_extension", "peer_context", "ranking"):
            if config[switch] == "off" or config[switch] == "detector_score":
                continue
            off = dict(config)
            off[switch] = "detector_score" if switch == "ranking" else "off"
            other = by_id.get(fingerprint(off)[:12])
            if not other or other.get("status") == "unavailable":
                continue
            effects.append(
                {
                    "family": config["detector"],
                    "switch": switch,
                    "on": result["configuration_id"],
                    "off": other["configuration_id"],
                    "admission_delta": result["admissions"] - other["admissions"],
                    "timely_delta": result["timely_incidents"] - other["timely_incidents"],
                    "current_positive_delta": result["current_positive"]
                    - other["current_positive"],
                }
            )
            if (
                switch == "ranking"
                and result["candidate_stream_sha256"] != other["candidate_stream_sha256"]
            ):
                raise ValueError("Ranking pairs have different gate-passing offers")
    text = [
        "# Corrected optional-module experiment",
        "",
        "All results are retrospective on consumed November. Historical results are excluded from these tables and module effects. No independent validation or deployment change.",
        "",
    ]
    for family in ("rf", "if"):
        text += [
            f"## {family.upper()}",
            "",
            "| Temporal | Peer | Ranking | Detector AP | Gate recall | Admissions | Current + | Context + | Timely / 11 |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for c, r in zip(configs, results, strict=True):
            if c["detector"] != family:
                continue
            if r.get("status") == "unavailable":
                text.append(
                    f"| {c['representation_extension']} | {c['peer_context']} | relevance unavailable | — | — | — | — | — | — |"
                )
            else:
                text.append(
                    f"| {c['representation_extension']} | {c['peer_context']} | {c['ranking']} | {r['detector_average_precision']:.4f} | {r['gate_recall']:.3f} | {r['admissions']} | {r['current_positive']} | {r['context_positive']} | {r['timely_incidents']}/11 |"
                )
        text.append("")
    text += [
        "## Paired module effects",
        "",
        "Each on/off pair holds the other switches fixed. Interactions are visible when a switch changes outcomes differently under the other enabled modules.",
        "",
        "| Family | Switch | On configuration | Off configuration | Admission Δ | Current-positive Δ | Timely Δ |",
        "| --- | --- | --- | --- | ---: | ---: | ---: |",
    ]
    text += [
        f"| {e['family']} | {e['switch']} | {e['on']} | {e['off']} | {e['admission_delta']:+d} | {e['current_positive_delta']:+d} | {e['timely_delta']:+d} |"
        for e in effects
    ]
    text += [
        "",
        "## Interpretation",
        "",
        "A shared daily cap does not match actual admissions. The recorded criterion requires no greater admissions, higher timely reach and nonlower current-positive yield relative to the corrected family control. Any satisfaction is an observed retrospective result, not independently validated improvement.",
        "",
        "IF with relevance ranking uses supervised training labels. Native IF fitting remains label-free. Priority AP and forced daily rankings are diagnostics; the detector alone controls the gate. Event loss counts are terminal evidence assignments, not a monotone funnel.",
        "",
        "Full per-configuration delays, scenario breakdowns, ranking diagnostics and losses are in the JSON comparison and isolated experiment outputs. Cases retain original evidence, not exact forest-event attribution.",
        "",
    ]
    for family in ("rf", "if"):
        for switch in ("representation_extension", "peer_context", "ranking"):
            pairs = [e for e in effects if e["family"] == family and e["switch"] == switch]
            if pairs:
                text += [
                    "",
                    f"{family.upper()} {switch}: timely reach increased in {sum(e['timely_delta'] > 0 for e in pairs)}/{len(pairs)} paired settings, decreased in {sum(e['timely_delta'] < 0 for e in pairs)}/{len(pairs)}, and was unchanged in {sum(e['timely_delta'] == 0 for e in pairs)}/{len(pairs)}. Admission deltas ranged from {min(e['admission_delta'] for e in pairs):+d} to {max(e['admission_delta'] for e in pairs):+d}.",
                ]
    summary = {
        "feature_contract": "behavior-experiment-v1",
        "evaluation_status": "consumed-retrospective",
        "historical_results_included": False,
        "deployment_changed": False,
        "run_directory": str(directory.relative_to(root)),
        "results": results,
        "paired_effects": effects,
        "models": manifests,
        "independent_validation": "unavailable",
    }
    save_json(directory / "comparison.json", summary)
    save_json(root / "reports/experiment-comparison.json", summary)
    (root / "reports/EXPERIMENT_COMPARISON.md").write_text("\n".join(text))


def run(config_path, resume=False, stop_after_days=None, root=ROOT):
    config = json.loads(Path(config_path).read_text())
    if (
        config.get("schema") != "sentinelid-factorial-v1"
        or config.get("feature_contract") != "behavior-experiment-v1"
    ):
        raise ValueError("Unsupported experiment configuration or feature contract")
    configs = configurations(config)
    p = config["protocol"]
    if (
        p["evaluation_status"] != "consumed-retrospective"
        or p["fit_end"] > p["calibration_start"]
        or p["calibration_end"] > p["evaluation_start"]
    ):
        raise ValueError("Invalid chronological experiment protocol")
    if (
        not p["fit_start"]
        < p["oof_cutoffs"][0]
        < p["oof_cutoffs"][1]
        < p["oof_cutoffs"][2]
        < p["fit_end"]
    ):
        raise ValueError("Held-out blocks must follow their fitting data")
    capture_preservation(root)
    inputs, input_manifest = restore_inputs(root)
    code = {path.name: digest(path) for path in sorted((root / "sentinelid").glob("*.py"))}
    declaration = {
        "config": config,
        "runtime": {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
            "joblib": joblib.__version__,
        },
        "code": code,
        "inputs": input_manifest,
        "application_configuration_sha256": digest(root / "config.json"),
        "experimental_label_use": "Historical fitting labels only; November truth used after model freeze",
    }
    identity = fingerprint(declaration)
    directory = root / "data/experiments" / identity[:20]
    directory.mkdir(parents=True, exist_ok=True)
    lock = (directory / ".lock").open("a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise ValueError("Experiment runner already active") from None
    try:
        declaration_path = directory / "protocol.json"
        if declaration_path.exists() and not resume:
            raise ValueError("Experiment exists; use --resume")
        if not declaration_path.exists():
            save_json(declaration_path, declaration)
        print("Experiment:", directory, flush=True)
        old, rows, context = baseline(inputs, root)
        save_json(directory / "historical-preservation.json", old)
        print("Historical scores, admissions and active RF cases reproduced", flush=True)
        prepared = prepare(inputs, directory, p)
        data = arrays(directory)
        manifests = {}
        unique = {}
        for c in configs:
            unique.setdefault(model_key(c), c)
        for key, c in unique.items():
            print("Fitting/verifying:", key, flush=True)
            manifests[key] = train(data, prepared["names"], c, p, directory)
        save_json(
            directory / "model-freeze.json",
            {
                "protocol_sha256": digest(declaration_path),
                "models": manifests,
                "historical_results_excluded": True,
            },
        )
        # Evaluation truth is opened only after all detector and ranking artifacts are frozen.
        truth = json.loads((inputs / "validation-truth.json").read_text())["events"]
        days = np.asarray([k[0] for k in data["keys"]])
        test = (days >= p["evaluation_start"]) & (days < p["evaluation_end"])
        if [data["keys"][i] for i in np.flatnonzero(test)] != [
            (r["day"], r["identity_id"]) for r in rows
        ]:
            raise ValueError("Corrected evaluation eligibility/order changed")
        queue_cfg = json.loads((root / "config.json").read_text())["queue"]
        results = []
        outputs = []
        complete = True
        for c in configs:
            cid = fingerprint(c)[:12]
            key = model_key(c)
            m = manifests[key]
            output = directory / cid
            output.mkdir(exist_ok=True)
            child_identity = fingerprint({"parent": identity, "config": c, "models": m})
            save_json(
                output / "manifest.json",
                {
                    "identity": child_identity,
                    "config": c,
                    "model_manifest": m,
                    "queue_policy": queue_cfg,
                    "queue_variant": "max_cooldown",
                },
            )
            if c["ranking"] == "relevance_v1" and m["ranking_status"] == "unavailable":
                results.append(
                    {
                        "configuration_id": cid,
                        "status": "unavailable",
                        "reason": "Ranking historical support lacks both classes",
                    }
                )
                continue
            with np.load(directory / "models" / key / "scores.npz") as scores_file:
                scores = scores_file["detector"][test]
                priorities = (
                    scores_file["priority"][test]
                    if c["ranking"] == "relevance_v1"
                    else scores.copy()
                )
            vectors, names = feature_matrix(data, prepared["names"], c)
            worker = ExperimentReplay(
                root,
                output / "operations.sqlite",
                child_identity,
                c,
                queue_cfg,
                rows,
                scores,
                priorities,
                m["gate"],
                context,
                directory,
                names,
                vectors[test],
                resume,
            )
            try:
                advanced = 0
                while worker.status != "completed" and (
                    stop_after_days is None or advanced < stop_after_days
                ):
                    worker.step(p["evaluation_start"], p["evaluation_end"])
                    advanced += 1
                if worker.status != "completed":
                    complete = False
                    print("Paused:", cid, worker.day_cursor, flush=True)
                    continue
                result, losses = evaluate(
                    rows, scores, priorities, m["gate"], worker.queue, truth, p
                )
                result.update(
                    configuration_id=cid,
                    config=c,
                    candidate_stream_sha256=worker.offers_hash(),
                    detector_model_sha256=m["files"]["detector.joblib"],
                    ranking_model_sha256=m["files"].get("ranker.joblib")
                    if c["ranking"] == "relevance_v1"
                    else None,
                )
                save_json(output / "metrics.json", result)
                json_lines(output / "event-losses.jsonl.gz", losses)
                json_lines(output / "queue-decisions.jsonl.gz", worker.queue.decisions)
                results.append(result)
                outputs.append(output)
                print(
                    cid,
                    c["detector"],
                    c["representation_extension"],
                    c["peer_context"],
                    c["ranking"],
                    "admissions",
                    result["admissions"],
                    "current",
                    result["current_positive"],
                    "timely",
                    result["timely_incidents"],
                    flush=True,
                )
            finally:
                worker.close()
        if not complete:
            save_json(
                directory / "progress.json",
                {
                    "status": "paused",
                    "resume_command": f"python -m sentinelid experiment --config {config_path} --resume",
                },
            )
            return directory
        evidence = resolve_evidence(root, directory, rows, outputs)
        save_json(directory / "evidence-verification.json", evidence)
        audit = preservation(root)
        save_json(directory / "preservation.json", audit)
        reports(root, directory, configs, results, manifests)
        save_json(
            directory / "progress.json",
            {"status": "completed", "configurations": len(results), "preservation_passed": True},
        )
        print(
            "Completed corrected comparison:", root / "reports/EXPERIMENT_COMPARISON.md", flush=True
        )
        return directory
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
