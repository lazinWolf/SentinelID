"""Optional modules, chronology, held-out fitting and independent persisted scores."""

import copy
import json
import pickle
import sqlite3
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import joblib
import numpy as np
from sklearn.dummy import DummyClassifier
from test_pipeline import Q, cand, stream

from sentinelid.experiment_evaluation import evaluate
from sentinelid.experiment_features import (
    ModuleOutput,
    corrected,
    measurements,
    ranking_vector,
    vector,
)
from sentinelid.experiment_io import capture_preservation, isolated_path
from sentinelid.experiment_models import configurations, train
from sentinelid.experiment_queue import ExperimentQueue
from sentinelid.experiment_replay import ExperimentReplay
from sentinelid.pipeline import WorkloadQueue, matrix


def fixture():
    s = stream()
    current = s.buckets["target"]
    current.counts["usb"] = 64
    current.counts["copy"] = 640
    for entry in s.history["target"]:
        j = (s.day - entry.date).days
        if j <= 6:
            entry.counts["usb"] = 2 ** (j - 1)
            entry.counts["copy"] = 10 * 2 ** (j - 1)
    daily = {
        (u, x.date.isoformat()): {
            "counts": dict(x.counts),
            "event_ids": ["file:" + x.date.isoformat()],
        }
        for u, history in s.history.items()
        for x in history
    }
    daily[("target", s.day.isoformat())] = {
        "counts": dict(current.counts),
        "event_ids": ["file:today"],
    }
    row = s.close()[0]
    return row, daily


class ModuleTests(unittest.TestCase):
    def test_distinct_exact_horizon_membership_and_control_changes(self):
        row, daily = fixture()
        fixed = corrected(row, daily)
        self.assertEqual(row["references"]["28"]["details"]["usb_change_3"]["target"], 112)
        for n, expected in [(1, 64), (3, 67), (7, 127)]:
            dates = fixed["target_dates"][str(n)]
            target = sum(daily[("target", d)]["counts"]["usb"] for d in dates)
            self.assertEqual(target, expected)
            self.assertEqual(target, row["percentile_reference"][f"usb_change_{n}"]["target"])
        self.assertEqual(fixed["references"]["28"]["details"]["copy_change_3"]["target"], 670)
        old, names = matrix([row], "PM")
        new, _ = matrix([fixed], "PM")
        changed = set(np.flatnonzero(old[0] != new[0]))
        self.assertEqual(
            changed, {names.index("magnitude:usb_change_3"), names.index("magnitude:copy_change_3")}
        )
        self.assertEqual(fixed["eligibility"], row["eligibility"])
        self.assertEqual(fixed["percentiles"], row["percentiles"])

    def test_disabled_adapters_and_immutable_reusable_outputs(self):
        row, daily = fixture()
        fixed = corrected(row, daily)
        t, p = measurements(fixed, daily)
        x, names = vector(fixed, t, p)
        baseline, bn = matrix([fixed], "PM")
        np.testing.assert_array_equal(x, baseline[0])
        self.assertEqual(names, bn)
        self.assertEqual(len(vector(fixed, t, p, True, True)[0]), 40)
        copy_payload = t.as_dict()
        copy_payload["measurements"]["usb_persistence_7"] = 999
        self.assertNotEqual(t.measurements()["usb_persistence_7"], 999)
        with self.assertRaises(FrozenInstanceError):
            t.serialized = "{}"
        self.assertEqual(t, ModuleOutput.create(t.as_dict()))
        self.assertEqual(p.as_dict()["support"]["users"], 11)
        self.assertTrue(p.as_dict()["support"]["self_excluded"])
        rank_values, rank_names = ranking_vector(0.8, x, names, t, p, False, False)
        self.assertEqual(rank_names[0], "detector_score")
        self.assertEqual(rank_values[0], 0.8)
        self.assertFalse(any("peer" in k or "temporal" in k or "identity" in k for k in rank_names))

    def test_temporal_formula_daily_cooccurrence_and_future_isolation(self):
        row, daily = fixture()
        for k in ("usb", "copy"):
            row["references"]["28"]["details"][k + "_change_1"].update(
                reference_mean=0.0, reference_sd=0.0
            )
        for j, count in enumerate([2, 1, 3, 0, 2, 1, 8]):
            day = (datetime.fromisoformat(row["day"]) - timedelta(days=j)).date().isoformat()
            daily[("target", day)]["counts"] = {
                "usb": count,
                "copy": count,
                "after_hours": int(j in (0, 2)),
            }
        t, _ = measurements(row, daily)
        self.assertEqual(t.measurements()["usb_persistence_7"], 4 / 7)
        self.assertEqual(t.measurements()["copy_after_hours_cooccurrence_7"], 2 / 6)
        tomorrow = (datetime.fromisoformat(row["day"]) + timedelta(days=1)).date().isoformat()
        daily[("target", tomorrow)] = {"counts": {"usb": 999}, "event_ids": ["file:future"]}
        self.assertEqual(t, measurements(row, daily)[0])

    def test_unsupported_peer_status_neutral_and_incompatible_flags(self):
        s = stream()
        s.config = copy.deepcopy(s.config)
        s.config["peers"]["minimum_users"] = 20
        row = s.close()[0]
        daily = {("target", row["day"]): {"counts": row["counts"], "event_ids": []}}
        fixed = corrected(
            row,
            {
                **daily,
                **{
                    (
                        "target",
                        (datetime.fromisoformat(row["day"]) - timedelta(days=j)).date().isoformat(),
                    ): {"counts": {"usb": 1}, "event_ids": []}
                    for j in range(1, 7)
                },
            },
        )
        _, p = measurements(fixed, daily)
        self.assertEqual(p.as_dict()["status"], "unsupported")
        self.assertEqual(p.measurements()["peer_supported"], 0)
        config = {
            "detector": "rf",
            "representation_extension": "off",
            "peer_context": "off",
            "ranking": "PCA",
        }
        with self.assertRaises(ValueError):
            configurations(config)


class OptionalQueueTests(unittest.TestCase):
    def test_native_ordering_matches_existing_policy(self):
        native = WorkloadQueue(Q)
        experimental = ExperimentQueue(Q)
        for c in [
            cand("a", score=0.8),
            cand("b", score=0.7),
            cand("a", day="2010-02-02", score=0.9),
        ]:
            native.offer(c)
            experimental.offer({**c, "detector_score": c["score"], "priority_score": c["score"]})
        left = native.decide("2010-02-03T08:00:00")
        right = experimental.decide("2010-02-03T08:00:00")
        for original, optional in zip(left, right, strict=True):
            for key in original:
                self.assertEqual(original[key], optional[key])

    def test_priority_order_and_independent_merge_maxima(self):
        q = ExperimentQueue(Q)
        q.offer({**cand("a", score=0.9), "detector_score": 0.9, "priority_score": 0.2})
        q.offer(
            {
                **cand("a", day="2010-02-02", score=0.5),
                "detector_score": 0.5,
                "priority_score": 0.95,
            }
        )
        q.offer({**cand("b", score=0.95), "detector_score": 0.95, "priority_score": 0.7})
        restored = pickle.loads(pickle.dumps(q))
        chosen = restored.decide("2010-02-03T08:00:00")[0]
        self.assertEqual(chosen["identity_id"], "a")
        self.assertEqual(chosen["score"], 0.9)
        self.assertEqual(chosen["detector_score"], 0.9)
        self.assertEqual(chosen["priority_score"], 0.95)
        self.assertEqual(chosen["detector_day"], "2010-02-01")
        self.assertEqual(chosen["priority_day"], "2010-02-02")
        self.assertEqual(len(chosen["detector_history"]), 2)


class RankingTrainingTests(unittest.TestCase):
    def test_held_out_predictions_and_training_only_scaler(self):
        config = json.loads((Path(__file__).resolve().parents[1] / "experiments.json").read_text())
        protocol = config["protocol"]
        row, daily = fixture()
        fixed = corrected(row, daily)
        _, names = matrix([fixed], "PM")
        dates = [
            "2010-06-08",
            "2010-06-09",
            "2010-07-15",
            "2010-07-16",
            "2010-08-15",
            "2010-08-16",
            "2010-09-15",
            "2010-09-16",
            "2010-10-15",
            "2010-11-01",
        ]
        x = np.zeros((len(dates), 33))
        x[:, 0] = np.arange(len(dates))
        x[:, 2] = np.arange(len(dates))
        data = {
            "keys": [(d, "u") for d in dates],
            "pm": x,
            "temporal": np.zeros((len(dates), 3)),
            "peer": np.zeros((len(dates), 4)),
            "label": np.asarray([0, 1] * 4 + [-1, -1]),
            "relevance": np.asarray([0, 1] * 4 + [-1, -1]),
        }
        calls = []

        def dummy_fit(values, labels, family, p):
            calls.append(values[:, 0].tolist())
            return DummyClassifier(strategy="prior").fit(values, labels)

        c = {
            "detector": "rf",
            "representation_extension": "off",
            "peer_context": "off",
            "ranking": "relevance_v1",
        }
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch("sentinelid.experiment_models.fit_detector", side_effect=dummy_fit),
        ):
            m = train(data, names, c, protocol, Path(temporary))
            self.assertEqual(
                calls,
                [
                    [0.0, 1.0],
                    [0.0, 1.0, 2.0, 3.0],
                    [0.0, 1.0, 2.0, 3.0, 4.0, 5.0],
                    list(np.arange(8, dtype=float)),
                ],
            )
            self.assertEqual(m["ranking_rows"], 6)
            bundle = joblib.load(Path(temporary) / "models/rf-t0p0/ranker.joblib")
            self.assertEqual(bundle["names"][0], "detector_score")
            scaler = bundle["model"].named_steps["standardscaler"]
            self.assertAlmostEqual(scaler.mean_[1], 4.5)
            self.assertNotIn("identity_id", bundle["names"])


class ExperimentPersistenceTests(unittest.TestCase):
    def make_worker(self, root, resume=False, gate=0.5):
        rows = []
        for user in ("a", "b"):
            rows.append(
                {
                    "day": "2010-11-01",
                    "identity_id": user,
                    "role": "role",
                    "counts": {},
                    "event_ids": ["file:" + user],
                    "score_timestamp": "2010-11-02T00:00:00",
                    "qualifying_families": {},
                }
            )
        return ExperimentReplay(
            root,
            root / "data/experiments/test/operations.sqlite",
            "fixture-run",
            {"representation_extension": "off", "peer_context": "off", "ranking": "relevance_v1"},
            Q,
            rows,
            [0.7, 0.8],
            [0.9, 0.1],
            gate,
            {(r["identity_id"], r["day"]): r["event_ids"] for r in rows},
            root,
            ["input"],
            np.zeros((2, 1)),
            resume,
        )

    def test_isolation_separate_sql_values_restart_and_gate(self):
        output = ModuleOutput.create({"measurements": {}})
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch("sentinelid.experiment_replay.module_outputs", return_value=(output, output, {})),
        ):
            root = Path(temporary)
            worker = self.make_worker(root)
            worker.step("2010-11-01", "2010-11-03")
            self.assertEqual(worker.queue.pending["b"]["detector_score"], 0.8)
            self.assertEqual(worker.queue.pending["b"]["priority_score"], 0.1)
            worker.close()
            worker = self.make_worker(root, True)
            worker.step("2010-11-01", "2010-11-03")
            with worker.store.connection() as db:
                values = db.execute(
                    "SELECT detector_score,priority_score FROM experiment_scores ORDER BY identity"
                ).fetchall()
                self.assertEqual(values, [(0.7, 0.9), (0.8, 0.1)])
                cases = [
                    json.loads(x[0])
                    for x in db.execute("SELECT payload FROM cases ORDER BY decision")
                ]
            self.assertEqual(cases[0]["detector_score"], 0.7)
            self.assertEqual(cases[0]["priority_score"], 0.9)
            self.assertEqual(cases[1]["detector_score"], 0.8)
            self.assertEqual(cases[1]["priority_score"], 0.1)
            worker.close()
            self.assertFalse((root / "data/operations.sqlite").exists())
            with self.assertRaises(ValueError):
                isolated_path(root, root / "data/operations.sqlite")
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch("sentinelid.experiment_replay.module_outputs", return_value=(output, output, {})),
        ):
            worker = self.make_worker(Path(temporary), gate=0.95)
            worker.step("2010-11-01", "2010-11-03")
            self.assertEqual(worker.queue.reviews, [])
            self.assertEqual(worker.queue.pending, {})
            worker.close()

    def test_failed_transaction_rolls_back_outputs_cursor_and_queue(self):
        output = ModuleOutput.create({"measurements": {}})
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch("sentinelid.experiment_replay.module_outputs", return_value=(output, output, {})),
        ):
            worker = self.make_worker(Path(temporary))
            with worker.store.connection() as db:
                db.execute(
                    "CREATE TRIGGER fail_score BEFORE INSERT ON experiment_scores BEGIN SELECT RAISE(ABORT,'forced'); END"
                )
            with self.assertRaises(sqlite3.IntegrityError):
                worker.step("2010-11-01", "2010-11-03")
            self.assertEqual(worker.day_cursor, 0)
            self.assertEqual(worker.queue.pending, {})
            with worker.store.connection() as db:
                self.assertEqual(db.execute("SELECT count(*) FROM observations").fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT cursor FROM runs").fetchone()[0], 0)
            worker.close()


class ReportSafetyTests(unittest.TestCase):
    def test_scenario_counts_are_json_serializable_and_gate_exclusions_explicit(self):
        row = {"day": "2010-11-01", "identity_id": "u", "event_ids": ["file:x"]}
        truth = {
            "file:x": {
                "day": row["day"],
                "observed_account": "u",
                "timestamp": "2010-11-01T12:00:00",
                "incident_id": "i",
                "scenario": "1",
            }
        }
        protocol = {
            "evaluation_start": "2010-11-01",
            "evaluation_end": "2010-12-01",
            "timely_hours": 72,
        }
        result, _ = evaluate(
            [row], np.asarray([0.1]), np.asarray([0.99]), 0.5, ExperimentQueue(Q), truth, protocol
        )
        json.dumps(result, allow_nan=False)
        self.assertEqual(result["pre_ranking_excluded_positive_days"], 1)
        self.assertEqual(result["candidate_keys"], [])

    def test_first_run_preservation_capture_is_non_overwriting(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "config.json").write_text("original")
            capture_preservation(root)
            marker = root / "data/experiments/preservation-before.json"
            old = marker.read_bytes()
            (root / "config.json").write_text("changed")
            capture_preservation(root)
            self.assertEqual(marker.read_bytes(), old)
