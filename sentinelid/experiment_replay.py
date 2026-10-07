"""Checkpointed cached-observation replay through the maintained admission policy."""

import fcntl
import json
import pickle
from datetime import datetime, timedelta

from .experiment_data import module_outputs
from .experiment_io import fingerprint, isolated_path
from .experiment_queue import ExperimentQueue
from .store import WorkloadStore


class ExperimentReplay:
    def __init__(
        self,
        root,
        path,
        identity,
        config,
        queue_config,
        rows,
        scores,
        priorities,
        gate,
        context,
        measurement_directory,
        names,
        vectors,
        resume=False,
    ):
        path = isolated_path(root, path)
        self.store = WorkloadStore(path)
        self.lock = path.with_suffix(".lock").open("a+")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise ValueError("Another experiment writer is active") from None
        self.identity = identity
        self.config = config
        self.rows = rows
        self.scores = scores
        self.priorities = priorities
        self.gate = gate
        self.context = context
        self.measurements = measurement_directory
        self.names = names
        self.vectors = vectors
        self.queue_config = queue_config
        self.by_day = {}
        for i, row in enumerate(rows):
            self.by_day.setdefault(row["day"], []).append(i)
        with self.store.connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS experiment_scores(run TEXT,day TEXT,identity TEXT,detector_score REAL,priority_score REAL,PRIMARY KEY(run,day,identity))"
            )
        old = self.store.run()
        if old:
            if not resume:
                self.close()
                raise ValueError("Existing experiment replay requires --resume")
            if old["experiment_identity"] != identity:
                self.close()
                raise ValueError("Experiment checkpoint belongs to a different contract")
            with self.store.connection() as db:
                state = pickle.loads(
                    db.execute("SELECT checkpoint FROM runs WHERE id=?", (old["id"],)).fetchone()[0]
                )
            self.run_id = old["id"]
            self.queue = state["queue"]
            self.day_cursor = state["day_cursor"]
            self.row_cursor = old["events_processed"]
            self.status = old["status"]
        else:
            self.run_id = identity[:32]
            self.queue = ExperimentQueue(queue_config)
            self.day_cursor = self.row_cursor = 0
            self.status = "paused"
            with self.store.connection() as db:
                db.execute(
                    "INSERT INTO runs VALUES(?,?,?,?,?,?,?)",
                    (
                        self.run_id,
                        self.status,
                        0,
                        len(rows),
                        pickle.dumps({"queue": self.queue, "day_cursor": 0}),
                        identity,
                        datetime.now().isoformat(),
                    ),
                )

    def context_ids(self, row):
        day = datetime.fromisoformat(row["day"])
        return sorted(
            {
                e
                for j in range(7)
                for e in self.context.get(
                    (row["identity_id"], (day - timedelta(days=j)).date().isoformat()), []
                )
            }
        )

    def commit(self, observations, cases):
        checkpoint = pickle.dumps({"queue": self.queue, "day_cursor": self.day_cursor})
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            for row in observations:
                db.execute(
                    "INSERT INTO observations VALUES(?,?,?,?,?)",
                    (
                        self.run_id,
                        row["day"],
                        row["identity_id"],
                        row["detector_score"],
                        json.dumps(row, allow_nan=False),
                    ),
                )
                db.execute(
                    "INSERT INTO experiment_scores VALUES(?,?,?,?,?)",
                    (
                        self.run_id,
                        row["day"],
                        row["identity_id"],
                        row["detector_score"],
                        row["priority_score"],
                    ),
                )
            for case in cases:
                db.execute(
                    "INSERT INTO cases VALUES(?,?,?,?,?,?)",
                    (
                        case["case_id"],
                        self.run_id,
                        case["detector"],
                        case["identity_id"],
                        case["decision_time"],
                        json.dumps(case, allow_nan=False),
                    ),
                )
            db.execute(
                "UPDATE runs SET status=?,cursor=?,checkpoint=? WHERE id=?",
                (self.status, self.row_cursor, checkpoint, self.run_id),
            )

    def step(self, evaluation_start, evaluation_end):
        if self.status == "completed":
            return
        previous = (pickle.dumps(self.queue), self.day_cursor, self.row_cursor, self.status)
        observations = []
        start = datetime.fromisoformat(evaluation_start)
        end = datetime.fromisoformat(evaluation_end)
        days = (end - start).days
        try:
            if self.day_cursor < days:
                day = (start + timedelta(days=self.day_cursor)).date().isoformat()
                for i in self.by_day.get(day, []):
                    row = self.rows[i]
                    score = float(self.scores[i])
                    priority = float(self.priorities[i])
                    temporal, peer, audit = module_outputs(
                        self.measurements, day, row["identity_id"]
                    )
                    modules = {}
                    if self.config["representation_extension"] != "off":
                        modules["temporal"] = temporal.as_dict()
                    if self.config["peer_context"] != "off":
                        modules["peer"] = peer.as_dict()
                    observation = {
                        "day": day,
                        "identity_id": row["identity_id"],
                        "detector_score": score,
                        "priority_score": priority,
                        "model_inputs": dict(
                            zip(self.names, self.vectors[i].tolist(), strict=True)
                        ),
                        "feature_contract": "behavior-experiment-v1",
                        "horizon_audit": audit,
                        "module_outputs": modules,
                        "gate": self.gate,
                        "role": row["role"],
                        "counts": row["counts"],
                    }
                    observations.append(observation)
                    if score >= self.gate:
                        self.queue.offer(
                            {
                                "detector": self.identity,
                                "identity_id": row["identity_id"],
                                "day": day,
                                "available_time": row["score_timestamp"],
                                "score": score,
                                "detector_score": score,
                                "priority_score": priority,
                                "trigger_ids": row["event_ids"],
                                "evidence_ids": self.context_ids(row),
                                "qualifying_families": row["qualifying_families"],
                            }
                        )
                when = start + timedelta(
                    days=self.day_cursor + 1, hours=self.queue_config["decision_hour"]
                )
            else:
                when = end + timedelta(
                    days=self.day_cursor - days + 1, hours=self.queue_config["decision_hour"]
                )
            cases = self.queue.decide(when.isoformat())
            for case in cases:
                case.update(
                    feature_contract="behavior-experiment-v1",
                    threshold=self.gate,
                    experiment_identity=self.identity,
                    ranking=self.config["ranking"],
                    evidence_semantics="Current and rolling context, not exact detector-event attribution",
                )
            self.row_cursor += len(observations)
            self.day_cursor += 1
            self.status = (
                "completed"
                if self.day_cursor == days + self.queue_config["backlog_days"]
                else "paused"
            )
            self.commit(observations, cases)
        except BaseException:
            self.queue = pickle.loads(previous[0])
            self.day_cursor, self.row_cursor, self.status = previous[1:]
            raise

    def offers_hash(self):
        return fingerprint(
            [
                (r["day"], r["identity_id"], float(s), self.gate)
                for r, s in zip(self.rows, self.scores, strict=True)
                if s >= self.gate
            ]
        )

    def close(self):
        if getattr(self, "lock", None) and not self.lock.closed:
            fcntl.flock(self.lock, fcntl.LOCK_UN)
            self.lock.close()
