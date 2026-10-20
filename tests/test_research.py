"""Research harness: sealed holdout, truth schema, queue replay and selection rule."""

import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

import numpy as np
from test_pipeline import Q

from sentinelid.research import holdout, replay, summarize
from sentinelid.research_data import truth


class FakeData:
    def __init__(self, keys):
        self.days = np.asarray([d for d, _ in keys])
        self.v = {"identity": np.asarray([u for _, u in keys])}

    def row(self, i, with_events=False):
        day, identity = str(self.days[i]), str(self.v["identity"][i])
        return {
            "day": day,
            "identity_id": identity,
            "score_timestamp": day + "T23:59:59",
            "qualifying_families": {},
            "event_ids": [f"file:{identity}:{day}"] if with_events else [],
        }

    def context(self, identity, day):
        return [f"file:{identity}:{day}"]


def answers(directory):
    path = Path(directory) / "answers.tar.bz2"
    insiders = (
        "dataset,scenario,details,user,start,end\n"
        "4.2,3,r4.2-3-AAA0001.csv,AAA0001,12/02/2010 09:00:00,12/03/2010 10:00:00\n"
        "4.1,1,r4.1-1-BBB0002.csv,BBB0002,12/02/2010 09:00:00,12/03/2010 10:00:00\n"
    )
    records = (
        "logon,{A},11/30/2010 09:00:00,AAA0001,PC-1,Logon\n"
        "email,{B},12/02/2010 09:00:00,CCC0003,PC-2,x@y.com,,,a@dtaa.com,10,0,text\n"
    )
    with tarfile.open(path, "w:bz2") as tar:
        for name, body in [
            ("answers/insiders.csv", insiders),
            ("answers/r4.2-3/r4.2-3-AAA0001.csv", records),
            ("answers/r4.1-1/r4.1-1-BBB0002.csv", records),
        ]:
            data = body.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


class ResearchTests(unittest.TestCase):
    def test_truth_filters_dates_and_keeps_observed_account(self):
        with tempfile.TemporaryDirectory() as directory:
            events = truth(answers(directory), "2010-12-01", "2011-05-17")
        self.assertEqual(list(events), ["email:{B}"])
        event = events["email:{B}"]
        self.assertEqual(event["observed_account"], "CCC0003")
        self.assertEqual(event["actor"], "AAA0001")
        self.assertEqual(event["official_start"], "2010-12-02T09:00:00")

    def test_replay_admits_budget_per_day_and_drains(self):
        keys = [("2010-12-01", "a"), ("2010-12-01", "b"), ("2010-12-02", "c")]
        data = FakeData(keys)
        queue = replay(
            data, [0, 1, 2], [0.9, 0.8, 0.1], 0.5, "2010-12-01", "2010-12-03", "max_cooldown", Q
        )
        self.assertEqual(
            [(c["identity_id"], c["decision_time"]) for c in queue.reviews],
            [("a", "2010-12-02T08:00:00"), ("b", "2010-12-03T08:00:00")],
        )
        self.assertEqual(queue.reviews[0]["evidence_ids"], ["file:a:2010-12-01"])

    def test_selection_respects_cost_and_yield_constraints(self):
        def run(name, admissions, current, timely):
            return {
                "candidate": name,
                "seed": 0,
                "admissions": admissions,
                "current_positive": current,
                "timely_incidents": timely,
                "incidents_available": 10,
                "detector_average_precision": 0.5,
                "gate_recall": 0.5,
            }

        config = {
            "baseline": "base",
            "candidates": [
                {"name": n, "features": "c", "model": "rf", "policy": "max_cooldown"}
                for n in ("base", "costly", "noisy", "better")
            ],
        }
        summary = summarize(
            config,
            [
                run("base", 30, 15, 6),
                run("costly", 31, 20, 9),
                run("noisy", 30, 10, 9),
                run("better", 30, 16, 7),
            ],
        )
        self.assertEqual(summary["selected"], "better")

    def test_sealed_holdout_runs_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = root / "data/research/holdout/result.json"
            result.parent.mkdir(parents=True)
            result.write_text(json.dumps({"runs": []}))
            with self.assertRaisesRegex(ValueError, "already evaluated"):
                holdout(root)

    def test_persistence_ranking_prefers_repeated_offers(self):
        keys = [("2010-12-01", "a"), ("2010-12-01", "x"), ("2010-12-02", "a"), ("2010-12-02", "b")]
        data = FakeData(keys)
        for rank, second in [("max", "b"), ("sum", "a"), ("count", "a")]:
            queue = replay(
                data,
                [0, 1, 2, 3],
                [0.6, 0.95, 0.6, 0.9],
                0.5,
                "2010-12-01",
                "2010-12-03",
                "max_cooldown",
                Q,
                rank,
            )
            self.assertEqual([c["identity_id"] for c in queue.reviews][:2], ["x", second])

    def test_tail_scorer_is_label_free_and_upper_tail_only(self):
        from sentinelid.research import TailScorer, design

        model = TailScorer().fit(np.asarray([[0.0, 5.0], [0.0, 1.0], [1.0, 3.0], [2.0, 0.0]]))
        rarity = -model.score_samples(np.asarray([[0.0, 0.0], [2.0, 5.0], [9.0, 9.0]]))
        self.assertEqual(rarity[0], 0.0)
        self.assertTrue(rarity[0] < rarity[1] < rarity[2])

        class Vectors:
            def features(self, kind):
                names = ["percentile:usb_change_1", "magnitude:external_email_change_1"]
                return np.asarray([[-0.4, 0.3], [0.2, 0.1]]), names

        x, names = design(Vectors(), {"features": "c", "transform": "up", "subset": "movement"})
        self.assertEqual(names, ["percentile:usb_change_1"])
        np.testing.assert_array_equal(x[:, 0], [0.0, 0.2])

    def test_channel_tail_scorer_counts_each_behavior_once(self):
        from sentinelid.research import TailScorer, channel

        names = ["percentile:usb_change_1", "magnitude:usb_change_7", "percentile:http_change_1"]
        self.assertEqual([channel(n) for n in names], ["usb", "usb", "http"])
        self.assertEqual(channel("peer_usb_percentile"), "peer_usb")
        train = np.zeros((9, 3))
        model = TailScorer(names=names).fit(train)
        usb_only, usb_and_http = -model.score_samples(np.asarray([[1.0, 1.0, 0.0], [1.0, 0.0, 1.0]]))
        self.assertLess(usb_only, usb_and_http)

    def test_self_calibration_uses_only_prior_days_of_same_identity(self):
        from sentinelid.research import self_calibrate

        keys = [("2010-12-03", "a"), ("2010-12-01", "a"), ("2010-12-02", "a"), ("2010-12-02", "b")]
        data = FakeData(keys)
        adjusted = self_calibrate(
            data, np.arange(4), np.asarray([9.0, 1.0, 3.0, 5.0]), "user_median"
        )
        # a: Dec1 has no history; Dec2 minus median(1); Dec3 minus median(1, 3). b: no history.
        np.testing.assert_array_equal(adjusted, [7.0, 1.0, 2.0, 5.0])

    def test_holdout_report_is_named_after_its_stage(self):
        from sentinelid.research import write_holdout_report

        def run(name, role):
            return {
                "name": name,
                "role": role,
                "admissions": 3,
                "current_positive": 1,
                "current_positive_yield": 1 / 3,
                "timely_incidents": 1,
                "incidents_available": 2,
                "timely_fresh_incidents": 1,
                "fresh_incidents_available": 1,
                "detector_average_precision": 0.5,
                "gate_recall": 0.5,
                "scenario_breakdown": {},
                "event_losses": {},
                "queue_decisions": {},
                "timely_hits": {"x": {"official_onset_delay_hours": 2.0}},
            }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage = root / "data/research/holdout-unsupervised"
            stage.mkdir(parents=True)
            (root / "reports").mkdir()
            runs = [run("deployed (frozen, fit Jun-Oct)", "primary"), run("zzz_last", "primary")]
            (stage / "result.json").write_text(
                json.dumps(
                    {
                        "runs": runs,
                        "holdout": ["2010-12-01", "2011-05-17"],
                        "previous_holdout_uses": ["holdout/result.json"],
                    }
                )
            )
            write_holdout_report(root, "holdout-unsupervised")
            self.assertEqual(
                [p.name for p in (root / "reports").iterdir()], ["HOLDOUT-UNSUPERVISED.md"]
            )
            self.assertIn("Exploratory reuse", (root / "reports/HOLDOUT-UNSUPERVISED.md").read_text())
