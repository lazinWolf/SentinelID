"""Read-only day playback of committed scores and recorded queue decisions."""

import copy
import json
import pickle
import sqlite3
import threading
from collections import Counter, defaultdict
from datetime import datetime, timedelta


def recorded_frames(scores, decisions, cases, config, gate):
    """Project the recorded trace onto days; never make new admission decisions."""
    offers = defaultdict(list)
    counts = Counter()
    offer_actions = defaultdict(list)
    decision_actions = defaultdict(list)
    admitted = defaultdict(list)
    for day, identity, score in scores:
        counts[day] += 1
        if score >= gate:
            offers[day].append({"identity_id": identity, "score": score, "day": day})
    for action in decisions:
        if "decision_time" in action:
            day = (datetime.fromisoformat(action["decision_time"]) - timedelta(days=1)).date()
            decision_actions[day.isoformat()].append(action)
        else:
            offer_actions[action["day"]].append(action)
    for case in cases:
        day = (datetime.fromisoformat(case["decision_time"]) - timedelta(days=1)).date()
        admitted[day.isoformat()].append(case)
    start = datetime.fromisoformat(config["final"]["validation_start"])
    end = datetime.fromisoformat(config["final"]["validation_end"])
    pending = {}
    frames = []
    cumulative = 0
    for index in range((end - start).days + config["queue"]["backlog_days"]):
        day = (start + timedelta(days=index)).date().isoformat()
        reasons = Counter(a["reason"] for a in offer_actions[day] + decision_actions[day])
        suppressed = {
            a["identity_id"] for a in offer_actions[day] if a["reason"] == "cooldown"
        }
        for offer in offers[day]:
            user = offer["identity_id"]
            if user in suppressed:
                continue
            old = pending.get(user)
            if old:
                old["score"] = max(old["score"], offer["score"])
                old["days"].append(day)
            else:
                pending[user] = {**offer, "days": [day]}
        before = sorted(pending.values(), key=lambda c: (-c["score"], c["day"], c["identity_id"]))
        for action in decision_actions[day]:
            if action["reason"] in ("admitted", "expired"):
                pending.pop(action["identity_id"], None)
        cumulative += len(admitted[day])
        frames.append(
            {
                "step": index,
                "day": day,
                "decision_time": (
                    start + timedelta(days=index + 1, hours=config["queue"]["decision_hour"])
                ).isoformat(),
                "drain": day >= end.date().isoformat(),
                "scored": counts[day],
                "gate_passed": len(offers[day]),
                "below_gate": counts[day] - len(offers[day]),
                "offers": sorted(offers[day], key=lambda c: (-c["score"], c["identity_id"])),
                "queue_before_decision": copy.deepcopy(before),
                "pending": copy.deepcopy(
                    sorted(
                        pending.values(),
                        key=lambda c: (-c["score"], c["day"], c["identity_id"]),
                    )
                ),
                "reasons": dict(reasons),
                "actions": offer_actions[day] + decision_actions[day],
                "admissions": admitted[day],
                "cumulative_admissions": cumulative,
            }
        )
    return frames


class RunPresentation:
    def __init__(self, store, config, gate, config_identity):
        self.store = store
        self.config = config
        self.gate = gate
        self.config_identity = config_identity
        self.key = None
        self.frames = []
        self.lock = threading.Lock()

    def snapshot(self, step=0):
        with self.lock:
            run = self.store.run()
            if not run or run["status"] != "completed" or self.gate is None:
                return {
                    "available": False,
                    "reason": "Complete the original-event replay once to enable recorded day playback.",
                }
            if run["experiment_identity"] != self.config_identity:
                raise ValueError("Recorded run uses another configuration; restore it for playback")
            key = (run["id"], run["events_processed"])
            if key != self.key:
                # The model and trace are trusted local artifacts, as in operational resume.
                with sqlite3.connect("file:" + str(self.store.path.resolve()) + "?mode=ro", uri=True) as db:
                    checkpoint = db.execute(
                        "SELECT checkpoint FROM runs WHERE id=?", (run["id"],)
                    ).fetchone()[0]
                    state = pickle.loads(checkpoint)
                    scores = db.execute(
                        "SELECT day,identity,score FROM observations WHERE run=? ORDER BY day,identity",
                        (run["id"],),
                    ).fetchall()
                    cases = []
                    for (payload,) in db.execute(
                        "SELECT payload FROM cases WHERE run=? ORDER BY decision", (run["id"],)
                    ):
                        c = json.loads(payload)
                        cases.append(
                            {
                                k: c[k]
                                for k in ("case_id", "identity_id", "score", "decision_time")
                            }
                            | {"evidence_total": len(c["evidence_pointers"])}
                        )
                self.frames = recorded_frames(
                    scores, state["queue"].decisions, cases, self.config, self.gate
                )
                expected = state["queue"].pending
                actual = {c["identity_id"]: c for c in self.frames[-1]["pending"]}
                if actual.keys() != expected.keys() or any(
                    actual[u]["score"] != expected[u]["score"]
                    or actual[u]["days"] != expected[u]["days"]
                    for u in actual
                ):
                    raise ValueError("Recorded playback does not match the committed queue")
                if self.frames[-1]["cumulative_admissions"] != len(cases):
                    raise ValueError("Recorded playback does not match committed admissions")
                self.key = key
            if not 0 <= step < len(self.frames):
                raise ValueError("Playback day is outside the recorded interval")
            frame = copy.deepcopy(self.frames[step])
            with sqlite3.connect("file:" + str(self.store.path.resolve()) + "?mode=ro", uri=True) as db:
                frame["sample_measurements"] = [
                    json.loads(r[0])
                    for r in db.execute(
                        "SELECT payload FROM observations WHERE run=? AND day=? ORDER BY score DESC,identity LIMIT 3",
                        (run["id"], frame["day"]),
                    )
                ]
            return {
                "available": True,
                "mode": "recorded-run playback",
                "run_id": run["id"],
                "gate": self.gate,
                "queue_policy": copy.deepcopy(self.config["queue"]),
                "steps": len(self.frames),
                "timeline": [
                    {k: f[k] for k in ("day", "scored", "gate_passed", "cumulative_admissions", "drain")}
                    for f in self.frames
                ],
                "frame": frame,
                "writes_application_state": False,
            }
