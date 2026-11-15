"""Methods study building blocks on toy inputs; no CERT data is needed."""

import importlib.util
import unittest

import numpy as np
from sklearn.metrics import average_precision_score

from sentinelid import methods

HAS_TORCH = importlib.util.find_spec("torch") is not None


class WindowTests(unittest.TestCase):
    def test_windows_look_back_only_and_mark_missing_days(self):
        days = np.asarray(["2010-06-01", "2010-06-02", "2010-06-04", "2010-06-02", "2010-06-05"])
        who = np.asarray(["A", "A", "A", "B", "A"])
        lagged = methods.lags(days, who, window=4)
        # A on June 4: June 1 (row 0), June 2 (row 1), June 3 missing, June 4 itself (row 2).
        self.assertEqual(lagged[2].tolist(), [0, 1, -1, 2])
        # A on June 5 never sees B's rows or anything later than June 5.
        self.assertEqual(lagged[4].tolist(), [1, -1, 2, 4])
        self.assertEqual(lagged[3].tolist(), [-1, -1, -1, 3])
        z = np.arange(10, dtype=np.float32).reshape(5, 2)
        batch = methods.windows(z, lagged)(np.asarray([2]))
        self.assertEqual(batch.shape, (1, 4, 3))
        self.assertEqual(batch[0, :, -1].tolist(), [1, 1, 0, 1])
        self.assertEqual(batch[0, 2, :2].tolist(), [0, 0])
        self.assertEqual(batch[0, 3, :2].tolist(), [4, 5])


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.edges = {
            ("2010-06-01", "A"): ["pc:1", "web:x.com"],
            ("2010-06-02", "A"): ["pc:1", "web:x.com"],
            ("2010-06-02", "B"): ["pc:2", "web:x.com"],
            ("2010-06-03", "A"): ["pc:2"],
            ("2010-07-01", "A"): ["pc:9"],
        }

    def test_graph_holds_only_history_before_the_fold(self):
        graph = methods.Graph(self.edges, "2010-07-01")
        self.assertEqual(graph.days[("A", "pc:1")], 2)
        self.assertNotIn("pc:9", graph.known)

    def test_rare_edges_are_more_surprising_and_unknown_nodes_get_the_ceiling(self):
        scorer = methods.EdgeScorer(methods.Graph(self.edges, "2010-07-01"))
        self.assertLess(scorer.surprise("A", "pc:1"), scorer.surprise("A", "pc:2"))
        self.assertLess(scorer.surprise("A", "pc:2"), scorer.surprise("B", "pc:1"))
        self.assertEqual(scorer.surprise("A", "pc:9"), scorer.ceiling)
        self.assertEqual(scorer.surprise("Z", "pc:1"), scorer.ceiling)

    def test_identity_day_score_sums_the_largest_surprises(self):
        class Fixed:
            def surprise(self, u, v):
                return {"a": 1.0, "b": 5.0, "c": 3.0, "d": 2.0}[v]

        edges = {("d1", "A"): ["a", "b", "c", "d"], ("d1", "B"): ["a"]}
        days, who = np.asarray(["d1", "d1", "d2"]), np.asarray(["A", "B", "A"])
        self.assertEqual(methods.edge_scores(Fixed(), edges, days, who).tolist(), [10.0, 1.0, 0.0])


class MeasureTests(unittest.TestCase):
    def test_average_precision_matches_scikit_learn_with_ties(self):
        rng = np.random.default_rng(1)
        for _ in range(20):
            y = (rng.random(300) < 0.05).astype(int)
            y[0] = 1
            s = rng.integers(0, 12, 300).astype(float)
            self.assertAlmostEqual(methods.average_precision(y, s), average_precision_score(y, s))

    def test_recall_at_k_ranks_within_each_day(self):
        days = np.asarray(["d1", "d1", "d1", "d2", "d2"])
        who = np.asarray(["A", "B", "C", "A", "B"])
        scores = np.asarray([0.9, 0.1, 0.5, 0.2, 0.3])
        result = methods.ranking(days, who, scores, {("d1", "C"), ("d2", "A")})
        self.assertEqual(result["top_k_positive_days"]["1"], 0)
        self.assertEqual(result["top_k_positive_days"]["2"], 2)
        self.assertEqual(result["positive_days"], 2)


class RoundTwoTests(unittest.TestCase):
    def test_causal_edges_are_scored_before_they_are_counted(self):
        edges = {
            # A warm-up day: on an empty graph the first edge has probability 1 by definition.
            ("2010-05-31", "C"): ["pc:7", "pc:8", "pc:9"],
            ("2010-06-01", "A"): ["pc:1"],
            ("2010-06-01", "B"): ["pc:1"],
            ("2010-06-02", "A"): ["pc:1"],
            ("2010-06-03", "A"): ["pc:1", "pc:2"],
        }
        scores = methods.causal_edge_scores(edges)
        # Same-day edges do not inform each other: A and B both meet pc:1 as unseen.
        self.assertEqual(scores[("2010-06-01", "A")], scores[("2010-06-01", "B")])
        # A repeated edge is less surprising than its first appearance.
        self.assertLess(scores[("2010-06-02", "A")], scores[("2010-06-01", "A")])
        # A new computer on day 3 outweighs the now-familiar one.
        self.assertGreater(scores[("2010-06-03", "A")], 2 * scores[("2010-06-02", "A")])
        # Later days never change an earlier score.
        self.assertEqual(
            methods.causal_edge_scores({k: v for k, v in edges.items() if k[0] < "2010-06-03"})[
                ("2010-06-02", "A")
            ],
            scores[("2010-06-02", "A")],
        )

    def test_robust_z_uses_only_the_identitys_earlier_rows(self):
        days = np.asarray([f"2010-06-{d:02d}" for d in range(1, 11)] * 2)
        who = np.asarray(["A"] * 10 + ["B"] * 10)
        values = np.ones((20, 2))
        values[9] = [1.0, 6.0]  # A's last day spikes in one channel
        values[10:] = 50.0  # B is steady at a different level
        lagged = methods.lags(days, who, window=methods.REFERENCE_DAYS + 1)
        z = methods.robust_z(values, lagged)
        self.assertEqual(z[:7].tolist(), [0.0] * 7)  # fewer than 7 reference rows
        self.assertEqual(z[8], 0.0)
        self.assertAlmostEqual(z[9], 5.0 / methods.MAD_FLOOR)
        self.assertEqual(z[19], 0.0)  # B is never compared with A

    def test_distribution_scores_rise_in_the_tails(self):
        rng = np.random.default_rng(0)
        x = rng.normal(size=(5000, 4))
        probe = np.asarray([[0.0] * 4, [4.0, 0.0, 0.0, 0.0], [99.0] * 4])
        for model in (methods.Histograms().fit(x), methods.Copula().fit(x)):
            scores = model.score(probe)
            self.assertTrue(np.isfinite(scores).all())
            self.assertLess(scores[0], scores[1])
            self.assertLess(scores[1], scores[2])

    def test_every_tabular_method_returns_finite_scores(self):
        class Data:
            days = np.asarray(["2010-07-01"] * 300 + ["2010-08-01"] * 60)
            v = {"label": (np.arange(360) % 30 == 0).astype(int), "identity": np.arange(360)}

        class Inputs:
            data = Data()
            x = np.random.default_rng(0).normal(size=(360, 5))
            names = ["percentile:a", "percentile:b", "c", "d", "e"]

        Inputs.x[Data.v["label"] == 1] += 3
        train, test = np.arange(300), np.arange(300, 360)
        for method in ("pct_max", "hbos", "copod", "lof", "knn", "ocsvm", "logreg"):
            fitted, scores = methods.fit_and_score(method, Inputs, train, test, 0, "2010-08-01")
            self.assertEqual(scores.shape, (60,), method)
            self.assertTrue(np.isfinite(fitted).all() and np.isfinite(scores).all(), method)
            self.assertGreater(
                scores[Data.v["label"][test] == 1].mean(),
                scores[Data.v["label"][test] == 0].mean(),
                method,
            )


@unittest.skipUnless(HAS_TORCH, "PyTorch is optional")
class NeuralTests(unittest.TestCase):
    def setUp(self):
        from sentinelid import neural

        self.neural = neural
        rng = np.random.default_rng(0)
        self.x = rng.normal(size=(2000, 6)).astype(np.float32)
        self.y = (self.x[:, 0] > 1.5).astype(int)

    def test_classifier_learns_a_separable_rule(self):
        make = lambda p: self.x[p]  # noqa: E731
        scorer = self.neural.classifier("mlp", make, self.y, seed=0)
        scores = scorer(make, len(self.x))
        self.assertGreater(average_precision_score(self.y, scores), 0.9)

    def test_unsupervised_scores_rank_outliers_higher(self):
        x = self.x.copy()
        x[:20] *= 6
        make = lambda p: x[p]  # noqa: E731
        scores = self.neural.reconstruction(make, len(x), seed=0)(make, len(x))
        self.assertGreater(scores[:20].mean(), scores[20:].mean())

    def test_sequence_models_return_one_finite_score_per_row(self):
        lagged = methods.lags(
            np.asarray([f"2010-06-{d:02d}" for d in range(1, 21)] * 2),
            np.asarray(["A"] * 20 + ["B"] * 20),
            window=5,
        )
        z = np.random.default_rng(0).normal(size=(40, 3)).astype(np.float32)
        make = methods.windows(z, lagged)
        y = np.zeros(40, dtype=int)
        y[[5, 25]] = 1
        for scorer in (
            self.neural.classifier("gru", make, y, seed=0),
            self.neural.next_day(make, 40, 3, seed=0),
        ):
            scores = scorer(make, 40)
            self.assertEqual(scores.shape, (40,))
            self.assertTrue(np.isfinite(scores).all())

    def test_graphsage_embeds_every_node(self):
        edges = {("2010-06-01", u): [f"pc:{u}", "web:a.com"] for u in ("A", "B", "C")} | {
            ("2010-06-02", "A"): ["pc:B"]
        }
        scorer = methods.SageScorer(methods.Graph(edges, "2010-07-01"), seed=0)
        self.assertEqual(scorer.z.shape[0], 3 + 4)
        self.assertTrue(np.isfinite(scorer.surprise("A", "pc:A")))
        self.assertEqual(scorer.surprise("A", "pc:unknown"), scorer.ceiling)


if __name__ == "__main__":
    unittest.main()
