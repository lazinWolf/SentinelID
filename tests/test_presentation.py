"""Recorded playback must preserve actual queue decisions and operational state."""

import copy
import hashlib
import json
import pickle
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from sentinelid.pipeline import WorkloadQueue
from sentinelid.presentation import RunPresentation, recorded_frames
from sentinelid.store import WorkloadStore

Q = {"decision_hour": 8, "cooldown_days": 7, "backlog_days": 3, "daily_budget": 1}
CFG = {"final": {"validation_start": "2010-11-01", "validation_end": "2010-11-06"}, "queue": Q}


def trace():
    scores = [
        ("2010-11-01", u, s)
        for u, s in [("a", .99), ("b", .97), ("c", .96), ("d", .7), ("e", .6), ("low", .3)]
    ] + [
        ("2010-11-02", "a", 1.0),
        ("2010-11-02", "b", .98),
        ("2010-11-02", "f", .95),
        ("2010-11-03", "c", .9),
        ("2010-11-03", "g", .94),
    ]
    queue = WorkloadQueue(Q)
    states = []
    start = datetime(2010, 11, 1)
    for i in range(8):
        day = (start + timedelta(days=i)).date().isoformat()
        for d, user, score in scores:
            if day != d or score < .5:
                continue
            queue.offer({
                "detector": "RF", "identity_id": user, "day": day, "score": score,
                "available_time": (start + timedelta(days=i + 1)).isoformat(),
                "evidence_ids": [d + user], "trigger_ids": [d + user], "qualifying_families": {},
            })
        queue.decide((start + timedelta(days=i + 1, hours=8)).isoformat())
        states.append(copy.deepcopy(queue.pending))
    cases = [
        {k: c[k] for k in ("case_id", "identity_id", "score", "decision_time")}
        | {"evidence_total": len(c["evidence_ids"])}
        for c in queue.reviews
    ]
    return scores, queue, states, cases


class RecordedPlaybackTests(unittest.TestCase):
    def test_every_day_matches_maintained_queue_with_merge_cooldown_and_expiry(self):
        scores, queue, states, cases = trace()
        frames = recorded_frames(scores, queue.decisions, cases, CFG, .5)
        for f, expected in zip(frames, states, strict=True):
            actual = {c["identity_id"]: c for c in f["pending"]}
            self.assertEqual(actual.keys(), expected.keys())
            for user in actual:
                self.assertEqual(actual[user]["score"], expected[user]["score"])
                self.assertEqual(actual[user]["days"], expected[user]["days"])
        self.assertEqual(frames[0]["below_gate"], 1)
        self.assertEqual(frames[1]["reasons"]["cooldown"], 1)
        self.assertEqual(frames[1]["reasons"]["merged"], 1)
        self.assertEqual(frames[3]["reasons"]["expired"], 2)
        self.assertEqual(frames[-1]["cumulative_admissions"], len(queue.reviews))
        self.assertTrue(frames[-1]["drain"])
        self.assertEqual(frames[-1]["scored"], 0)

    def test_snapshot_is_read_only_deterministic_and_isolated_from_caller_mutation(self):
        scores, queue, _, _ = trace()
        with tempfile.TemporaryDirectory() as td:
            store = WorkloadStore(Path(td) / "operations.sqlite")
            with store.connection() as db:
                db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", ("saved", "completed", 100, 100, pickle.dumps({"queue": queue}), "same", "now"))
                for day, user, score in scores:
                    payload = {"day": day, "identity_id": user, "score": score}
                    db.execute("INSERT INTO observations VALUES(?,?,?,?,?)", ("saved", day, user, score, json.dumps(payload)))
                for c in queue.reviews:
                    payload = {**c, "evidence_pointers": [{"event_id": e} for e in c["evidence_ids"]]}
                    db.execute("INSERT INTO cases VALUES(?,?,?,?,?,?)", (c["case_id"], "saved", "RF", c["identity_id"], c["decision_time"], json.dumps(payload)))
            before = hashlib.sha256(store.path.read_bytes()).hexdigest()
            playback = RunPresentation(store, CFG, .5, "same")
            first = playback.snapshot(0)
            self.assertFalse(first["writes_application_state"])
            first["frame"]["pending"].clear()
            self.assertTrue(playback.snapshot(0)["frame"]["pending"])
            self.assertEqual(playback.snapshot(7), playback.snapshot(7))
            with self.assertRaises(ValueError):
                playback.snapshot(8)
            self.assertEqual(before, hashlib.sha256(store.path.read_bytes()).hexdigest())
            with self.assertRaises(ValueError):
                RunPresentation(store, CFG, .5, "changed").snapshot()

    def test_empty_run_does_not_fabricate_a_demo(self):
        with tempfile.TemporaryDirectory() as td:
            store = WorkloadStore(Path(td) / "operations.sqlite")
            result = RunPresentation(store, CFG, None, "same").snapshot()
            self.assertFalse(result["available"])
            self.assertNotIn("frame", result)
