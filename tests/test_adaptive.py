"""Adaptive replay scoring: causal reference, verdict learning and stored analyst verdicts."""

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from sentinelid.adaptive import AdaptiveScorer, TailScorer, upward
from sentinelid.store import WorkloadStore


class AdaptiveScorerTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(0)
        self.scorer = AdaptiveScorer("2010-06-08", 0.3, 0.9)
        self.scorer.observe("2010-06-01", "early", np.full(4, 99.0))  # before reference start
        for d in range(8, 30):
            for u in range(10):
                self.scorer.observe(f"2010-06-{d:02d}", f"u{u}", rng.exponential(size=4))

    def test_reference_is_causal_and_cold_start_is_label_free_top5(self):
        self.scorer.prepare("2010-06-20", [])
        reference = np.asarray(self.scorer.rows)[np.asarray(self.scorer.days) < "2010-06-20"]
        self.assertEqual(len(self.scorer.tail.columns), len(reference))
        x = np.random.default_rng(1).exponential(size=(5, 4))
        np.testing.assert_allclose(
            self.scorer.score(x), -TailScorer(top=5).fit(reference).score_samples(x)
        )
        self.assertAlmostEqual(
            np.mean(self.scorer.score(reference) >= self.scorer.gate), 0.1, delta=0.01
        )

    def test_verdicts_reweight_once_and_ignore_unknown_identity_days(self):
        self.scorer.prepare("2010-06-20", [])
        before = self.scorer.model.w.copy()
        verdicts = [
            (1, [("2010-06-10", "u1"), ("2010-06-11", "missing")]),
            (-1, [("2010-06-12", "u2")]),
        ]
        self.scorer.prepare("2010-06-21", verdicts)
        self.assertEqual(self.scorer.labels, 2)
        self.assertFalse(np.array_equal(before, self.scorer.model.w))
        learned = self.scorer.model.w.copy()
        self.scorer.prepare("2010-06-22", verdicts)  # unchanged verdicts: no refit
        np.testing.assert_array_equal(learned, self.scorer.model.w)

    def test_upward_clips_only_percentiles(self):
        x = upward(
            np.asarray([[-0.5, -2.0, -0.3]]), ["percentile:a", "magnitude:a", "peer_x_percentile"]
        )
        np.testing.assert_array_equal(x, [[0.0, -2.0, 0.0]])


class StoredVerdictTests(unittest.TestCase):
    def test_latest_disposition_maps_to_verdicts_in_admission_order(self):
        with tempfile.TemporaryDirectory() as directory:
            store = WorkloadStore(Path(directory) / "state.sqlite")
            for cid, when, days in [
                ("b", "2010-11-03T08:00:00", ["2010-11-02"]),
                ("a", "2010-11-02T08:00:00", ["2010-11-01"]),
                ("c", "2010-11-04T08:00:00", ["2010-11-03"]),
            ]:
                case = {
                    "case_id": cid,
                    "identity_id": "u" + cid,
                    "days": days,
                    "evidence_pointers": [],
                }
                with store.connection() as db:
                    db.execute(
                        "INSERT INTO cases VALUES(?,?,?,?,?,?)",
                        (cid, "run", "adaptive_feedback", "u" + cid, when, json.dumps(case)),
                    )
            store.review("a", 0, "in_review", "suspicious")
            store.review("a", 1, "resolved", "benign")  # the latest version counts
            store.review("b", 0, "resolved", "confirmed")
            store.review("c", 0, "in_review", "needs_context")  # no verdict
            self.assertEqual(
                store.verdicts("run"),
                [(-1, [("2010-11-01", "ua")]), (1, [("2010-11-02", "ub")])],
            )
