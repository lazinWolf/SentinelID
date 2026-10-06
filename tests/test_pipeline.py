"""Causal features, admissions, persistence and analyst feedback regressions."""

import copy
import json
import pickle
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from sentinelid.features import Day, WorkloadStream, centered_percentile
from sentinelid.ingestion import Record
from sentinelid.pipeline import WorkloadQueue, WorkloadReplay, matrix
from sentinelid.store import WorkloadStore

CFG = {
    "start": "2010-01-01",
    "reference_windows": [28],
    "reference_lag_days": 7,
    "minimum_calendar_history": 41,
    "minimum_active_base_days": 7,
    "retained_history_days": 42,
    "sources": ["logon", "device", "file", "email", "http"],
    "peers": {
        "minimum_active_days_per_user": 7,
        "minimum_users": 10,
        "minimum_total_active_days": 70,
        "features": ["usb", "copy", "external_email"],
    },
}
Q = {"decision_hour": 8, "cooldown_days": 7, "backlog_days": 3, "daily_budget": 1}


def cand(u="a", day="2010-02-01", score=0.8, families=None, ids=None):
    return {
        "detector": "W4",
        "identity_id": u,
        "day": day,
        "available_time": (datetime.fromisoformat(day) + timedelta(days=1)).isoformat(),
        "score": score,
        "trigger_ids": ids or [day + u],
        "evidence_ids": ids or [day + u],
        "qualifying_families": families or {},
    }


def stream():
    s = WorkloadStream(CFG)
    s.day = datetime(2010, 2, 15).date()
    for u in ["target"] + [str(i) for i in range(11)]:
        for j in range(42):
            d = Day(s.day - timedelta(days=j + 1))
            d.sources = {"logon"}
            d.counts["usb"] = 1
            d.peer_group = "team:T"
            s.history[u].appendleft(d)
    c = Day(s.day)
    c.sources = {"logon"}
    c.counts["usb"] = 7
    c.peer_group = "team:T"
    s.buckets["target"] = c
    return s


class WorkloadTests(unittest.TestCase):
    def test_zero_ties_signed_direction(self):
        self.assertEqual(centered_percentile(0, [0] * 28), 0)
        self.assertEqual(centered_percentile(1, [0] * 28), 0.5)
        self.assertEqual(centered_percentile(0, [1] * 28), -0.5)

    def test_percentile_multi_duration(self):
        r = stream().close()[0]
        self.assertEqual(r["percentile_reference"]["usb_change_7"]["target"], 13)
        self.assertEqual(r["percentile_reference"]["usb_change_7"]["maximum"], 7)

    def test_peer_self_exclusion_and_freeze(self):
        s = stream()
        r = s.close()[0]
        self.assertEqual(r["peer_reference"]["users"], 11)
        self.assertTrue(r["peer_reference"]["supported"])
        self.assertEqual(r["peer_features"]["peer_usb_percentile"], 0.5)
        s = stream()
        s.buckets["0"] = Day(s.day)
        s.buckets["0"].counts["usb"] = 9999
        s.buckets["0"].peer_group = "team:T"
        r = [r for r in s.close() if r["identity_id"] == "target"][0]
        self.assertEqual(r["peer_features"]["peer_usb_percentile"], 0.5)

    def test_small_group_neutral(self):
        s = stream()
        s.history = {u: h for u, h in s.history.items() if u in ["target", "0"]}
        r = s.close()[0]
        self.assertEqual(r["peer_features"]["peer_supported"], 0)

    def test_missing_extra_context_not_inactivity(self):
        s = stream()
        s.coverage = {
            (s.day - timedelta(days=j)).isoformat(): {k: True for k in CFG["sources"]}
            for j in range(42)
        }
        r = s.close()[0]
        self.assertTrue(r["common_eligible"])
        s = stream()
        s.coverage = {
            (s.day - timedelta(days=j)).isoformat(): {k: True for k in CFG["sources"]}
            for j in range(36)
        }
        r = s.close()[0]
        self.assertFalse(r["common_eligible"])

    def test_pickle_and_future_suffix(self):
        s = stream()
        t = pickle.loads(pickle.dumps(s))
        a = s.close()
        b = t.close()
        self.assertEqual(a, b)
        snapshot = copy.deepcopy(a)
        s.day += timedelta(days=1)
        s.close()
        self.assertEqual(a, snapshot)

    def test_signed_transform_not_clipped(self):
        r = stream().close()[0]
        r["percentiles"]["usb_change_1"] = -0.5
        x, n = matrix([r], "P")
        self.assertEqual(x[0, n.index("percentile:usb_change_1")], -0.5)

    def test_corrected_schema_same_fitting_inference(self):
        s = WorkloadStream(CFG)
        e = Record(
            "email:id",
            datetime(2010, 1, 1),
            "u",
            "pc",
            "email",
            "Send",
            "role",
            "2010-01",
            {"attachments": "3", "size": "42", "to": "a@outside.test"},
            0,
            2,
            "x",
        )
        s.push(e)
        r = s.close()[0]
        self.assertEqual(r["counts"]["attachments"], 3)

    def test_new_family_reopens_repeated_does_not(self):
        q = WorkloadQueue(Q, "max_reopen")
        q.offer(cand(families={"removable_media": ["f1"]}, ids=["f1"]))
        first = q.decide("2010-02-02T08:00:00")[0]
        q.offer(cand(day="2010-02-02", families={"removable_media": ["f2"]}, ids=["f2"]))
        self.assertFalse(q.pending)
        q.offer(cand(day="2010-02-02", families={"external_email": ["e2"]}, ids=["e2"]))
        r = q.decide("2010-02-03T08:00:00")[0]
        self.assertTrue(r["reopening"])
        self.assertEqual(r["preceding_case"], first["case_id"])
        self.assertEqual(first["evidence_ids"], ["f1"])

    def test_generic_score_jitter_no_reopen(self):
        q = WorkloadQueue(Q, "fresh_reopen")
        q.offer(cand())
        q.decide("2010-02-02T08:00:00")
        q.offer(cand(day="2010-02-02", score=0.99))
        self.assertFalse(q.pending)

    def test_budget_and_fresh_priority(self):
        q = WorkloadQueue(Q, "fresh_cooldown")
        q.offer(cand("a", score=0.9))
        q.offer(cand("a", day="2010-02-02", score=0.7))
        q.offer(cand("b", score=0.8))
        self.assertEqual(q.decide("2010-02-03T08:00:00")[0]["identity_id"], "b")
        self.assertEqual(len(q.pending), 1)

    def test_immutable_pending_merge_and_expiry(self):
        q = WorkloadQueue(Q)
        c = cand()
        q.offer(c)
        c["evidence_ids"].append("future")
        self.assertNotIn("future", q.pending["a"]["evidence_ids"])
        q.decide("2010-02-06T08:00:00")
        self.assertEqual(q.decisions[-1]["reason"], "expired")


class WorkloadIntegrationTests(unittest.TestCase):
    def test_percentile_tail_saturation_preserves_magnitude_pair(self):
        s = stream()
        s.buckets["target"].counts["usb"] = 1000
        r = s.close()[0]
        self.assertEqual(r["percentiles"]["usb_change_1"], 0.5)
        x, n = matrix([r], "PM")
        self.assertGreater(x[0, n.index("magnitude:usb_change_1")], 1)

    def test_repeated_ids_cannot_reopen_under_new_family_name(self):
        q = WorkloadQueue(Q, "max_reopen")
        q.offer(cand(ids=["same"]))
        q.decide("2010-02-02T08:00:00")
        q.offer(cand(day="2010-02-02", families={"external_email": ["same"]}, ids=["same"]))
        self.assertFalse(q.pending)

    def test_atomic_cursor_outputs_and_pending_checkpoint(self):
        import sqlite3
        import tempfile
        from pathlib import Path

        from sentinelid.pipeline import WorkloadReplay, WorkloadStore

        with tempfile.TemporaryDirectory() as td:
            r = object.__new__(WorkloadReplay)
            r.store = WorkloadStore(Path(td) / "db.sqlite")
            r.run_id = "unit"
            r.status = "paused"
            r.stream = stream()
            r.queue = WorkloadQueue(Q)
            r.queue.offer(cand())
            r.cursor = 123
            r.last_key = None
            r.pointer_cache = {}
            r.pending_decision = "2010-02-02T08:00:00"
            r.last_closed = r.stream.day - timedelta(days=1)
            with r.store.connection() as db:
                db.execute(
                    "INSERT INTO runs VALUES(?,?,?,?,?,?,?)",
                    ("unit", "paused", 0, 1000, None, "unit", "now"),
                )
            r.commit([], [])
            with r.store.connection() as db:
                state = pickle.loads(db.execute("SELECT checkpoint FROM runs").fetchone()[0])
            self.assertEqual(state["cursor"], 123)
            self.assertTrue(state["queue"].pending)
            self.assertTrue(state["stream"].buckets)
            r.cursor = 124
            row = {"day": "2010-02-01", "identity_id": "a", "score": 0.8}
            with self.assertRaises(sqlite3.IntegrityError):
                r.commit([row, row], [])
            with r.store.connection() as db:
                self.assertEqual(db.execute("SELECT cursor FROM runs").fetchone()[0], 123)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 0)


class FrozenBoundaryCompatibilityTests(unittest.TestCase):
    def test_novelty_matches_frozen_post_score_pruning(self):
        s = stream()
        s.buckets["target"].hosts = {"rare-host"}
        for d in s.history["target"]:
            if d.date == s.day - timedelta(days=36):
                d.hosts = {"rare-host"}
        r = s.close()[0]
        self.assertEqual(r["features"]["28"]["new_host_count"], 0)


class ApplicationStoreTests(unittest.TestCase):
    def test_failed_commit_preserves_unfinished_state_and_cursor(self):
        with tempfile.TemporaryDirectory() as directory:
            worker = object.__new__(WorkloadReplay)
            worker.store = WorkloadStore(Path(directory) / "state.sqlite")
            worker.run_id = "application-test"
            worker.status = "paused"
            worker.cursor = 1
            worker.stream = {"unfinished_day": "2010-11-02", "records": ["first-record"]}
            worker.queue = {"pending": ["identity"]}
            worker.last_key = None
            worker.pointer_cache = {}
            worker.pending_decision = "2010-11-02T08:00:00"
            worker.last_closed = None
            with worker.store.connection() as db:
                db.execute(
                    "INSERT INTO runs VALUES(?,?,?,?,?,?,?)",
                    (worker.run_id, "paused", 0, 2, None, "active-contract", "now"),
                )
            worker.commit([], [])
            worker.cursor = 2
            row = {"day": "2010-11-01", "identity_id": "identity", "score": 0.5}
            with self.assertRaises(sqlite3.IntegrityError):
                worker.commit([row, row], [])
            with worker.store.connection() as db:
                cursor, payload = db.execute("SELECT cursor,checkpoint FROM runs").fetchone()
                self.assertEqual(db.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 0)
            state = pickle.loads(payload)
            self.assertEqual(cursor, 1)
            self.assertEqual(state["stream"]["records"], ["first-record"])
            self.assertEqual(state["queue"]["pending"], ["identity"])

    def test_versioned_feedback_survives_reopen_without_mutating_case(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite"
            store = WorkloadStore(path)
            case = {
                "case_id": "case",
                "detector": "REP_RF",
                "identity_id": "identity",
                "decision_time": "2010-11-02T08:00:00",
                "evidence_pointers": [],
                "evidence_ids": [],
                "trigger_ids": [],
                "days": ["2010-11-01"],
            }
            with store.connection() as db:
                db.execute(
                    "INSERT INTO cases VALUES(?,?,?,?,?,?)",
                    ("case", "run", "REP_RF", "identity", case["decision_time"], json.dumps(case)),
                )
            store.review("case", 0, "in_review", "unreviewed", "Engineering note")
            reopened = WorkloadStore(path)
            self.assertEqual(reopened.detail("case")["review"]["version"], 1)
            with self.assertRaises(ValueError):
                reopened.review("case", 0, "dismissed", "benign")
            with reopened.connection() as db:
                self.assertEqual(
                    json.loads(db.execute("SELECT payload FROM cases").fetchone()[0]), case
                )
