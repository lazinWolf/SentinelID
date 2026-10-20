"""Analyst-feedback learning: label-free start, bounded updates and no label leakage."""

import unittest

import numpy as np
from test_pipeline import Q
from test_research import FakeData

from sentinelid.feedback import FeedbackModel, Oracle, components, online
from sentinelid.research import TailScorer


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(0)
        self.reference = rng.exponential(size=(200, 8))
        self.scorer = TailScorer().fit(self.reference)

    def test_cold_start_ranks_like_label_free_top5(self):
        x = np.random.default_rng(1).exponential(size=(50, 8))
        model = FeedbackModel(9, lam=1.0)
        np.testing.assert_allclose(
            model.score(components(self.scorer, x)),
            -TailScorer(top=5).fit(self.reference).score_samples(x),
        )

    def test_update_learns_positive_component_and_stays_non_negative(self):
        z = np.zeros((40, 9))
        y = np.asarray([1] * 20 + [-1] * 20)
        z[:20, 2] = 5.0  # positives are rare on component 2
        z[:, -1] = np.random.default_rng(2).exponential(size=40)  # prior carries no signal
        model = FeedbackModel(9, lam=0.3)
        model.update(z, y)
        self.assertGreater(model.w[2], 0.1)
        self.assertTrue((model.w >= 0).all())

    def test_no_learning_without_lambda(self):
        model = FeedbackModel(9, lam=None)
        model.update(np.ones((3, 9)), [1, -1, 1])
        np.testing.assert_array_equal(model.w, model.w0)

    def test_oracle_only_sees_admitted_cases(self):
        days = ["2010-11-%02d" % d for d in range(20, 31)] + ["2010-12-01", "2010-12-02"]
        keys = [(d, u) for d in days for u in ("a", "b", "c")]
        data = FakeData(keys)
        x = np.random.default_rng(3).exponential(size=(len(keys), 8))
        x[-6:, 0] += 50.0  # December rows are extreme, so they pass the gate
        oracle = Oracle({"file:a:2010-12-01": {}})
        queue, _, margins, model, trace = online(
            data, x, "2010-12-01", "2010-12-03", "2010-11-20", 1.0, oracle, Q, 0.9
        )
        self.assertEqual(oracle.asked, [c["case_id"] for c in queue.reviews])
        self.assertTrue(np.isfinite(margins).all())
        # Each admitted case labels exactly its own scored identity-days, nothing else.
        self.assertEqual(trace[-1]["labels"], sum(len(c["days"]) for c in queue.reviews))
