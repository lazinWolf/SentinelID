"""Frozen RF scoring, budgeted admissions and durable original-event replay."""

import copy
import fcntl
import hashlib
import json
import math
import pickle
import uuid
from datetime import datetime, timedelta

import joblib
import numpy as np

from .features import BASE, CHANGE, EXTRA, NOVEL, PEER, WorkloadStream, original_records
from .ingestion import ROOT, digest
from .store import WorkloadStore


def matrix(rows, representation):
    names = (
        BASE + EXTRA
        if representation.split("_")[0] == "C"
        else ["percentile:" + k for k in CHANGE]
        + NOVEL
        + (["magnitude:" + k for k in CHANGE] if representation.startswith("PM") else [])
    )
    if representation.endswith("PEER"):
        names += PEER

    def value(r, k):
        if k.startswith("percentile:"):
            return r["percentiles"][k.split(":", 1)[1]]
        if k in PEER:
            return r["peer_features"][k]
        raw = r["features"]["28"][k.split(":", 1)[1] if k.startswith("magnitude:") else k]
        return math.log1p(max(0.0, raw))

    return (np.asarray([[value(r, k) for k in names] for r in rows], dtype=float), names)


def predict(rows, b):
    if not rows:
        return np.asarray([])
    x, n = matrix(rows, b["representation"])
    assert n == b["names"]
    return -b["model"].score_samples(x) if b["kind"] == "if" else b["model"].predict_proba(x)[:, 1]


class WorkloadQueue:
    def __init__(self, config, variant="max_cooldown"):
        self.config = config
        self.variant = variant
        self.pending = {}
        self.last_admission = {}
        self.reviews = []
        self.decisions = []

    def offer(self, c):
        c = copy.deepcopy(c)
        u = c["identity_id"]
        prior = self.last_admission.get(u)
        families = c.get("qualifying_families", {})
        when = datetime.fromisoformat(c["available_time"]).replace(
            hour=self.config["decision_hour"]
        )
        within = prior and when < datetime.fromisoformat(prior["decision_time"]) + timedelta(
            days=self.config["cooldown_days"]
        )
        unseen = {
            k: sorted(set(v) - set((prior or {}).get("evidence_ids", [])))
            for k, v in families.items()
            if not prior or k not in prior.get("presented_families", [])
        }
        unseen = {k: v for k, v in unseen.items() if v}
        if within and ("reopen" not in self.variant or not unseen):
            self.decisions.append(
                {
                    "identity_id": u,
                    "day": c["day"],
                    "reason": "cooldown",
                    "preceding_case": prior["case_id"],
                    "qualifying_new_families": unseen,
                }
            )
            return
        c["reopening"] = bool(within)
        c["preceding_case"] = prior["case_id"] if within else None
        c["new_qualifying_ids"] = unseen
        c["reopening_reason"] = "unseen_supported_family_and_new_records" if within else None
        old = self.pending.get(u)
        if old:
            for k in ["evidence_ids", "trigger_ids"]:
                old[k] = sorted(set(old[k]) | set(c[k]))
            old["days"] = sorted(set(old["days"]) | {c["day"]})
            old["score_history"].append({"day": c["day"], "score": c["score"]})
            if "fresh" in self.variant or c["score"] > old["score"]:
                old["score"] = c["score"]
                old["priority_day"] = c["day"]
            for k, v in families.items():
                old["qualifying_families"][k] = sorted(
                    set(old["qualifying_families"].get(k, [])) | set(v)
                )
            self.decisions.append(
                {
                    "identity_id": u,
                    "day": c["day"],
                    "reason": "merged",
                    "pending_first_day": old["day"],
                    "priority_day": old["priority_day"],
                }
            )
        else:
            self.pending[u] = {
                **c,
                "days": [c["day"]],
                "priority_day": c["day"],
                "score_history": [{"day": c["day"], "score": c["score"]}],
            }

    def rank_key(self, candidate):
        return (-candidate["score"], candidate["available_time"], candidate["identity_id"])

    def decide(self, when):
        for u, c in list(self.pending.items()):
            if datetime.fromisoformat(when) > datetime.fromisoformat(
                c["available_time"]
            ) + timedelta(days=self.config["backlog_days"]):
                self.decisions.append(
                    {
                        "identity_id": u,
                        "days": c["days"],
                        "reason": "expired",
                        "decision_time": when,
                    }
                )
                del self.pending[u]
        candidates = sorted(
            (c for c in self.pending.values() if c["available_time"] <= when),
            key=self.rank_key,
        )
        chosen = candidates[: self.config["daily_budget"]]
        results = []
        for c in chosen:
            case = copy.deepcopy(c)
            case["decision_time"] = when
            case["case_id"] = hashlib.sha256(
                (
                    c["detector"]
                    + ":"
                    + self.variant
                    + ":"
                    + str(self.config["daily_budget"])
                    + ":"
                    + c["identity_id"]
                    + ":"
                    + when
                ).encode()
            ).hexdigest()[:24]
            prior = self.last_admission.get(c["identity_id"])
            shown = (
                set(prior.get("presented_families", [])) if case["reopening"] and prior else set()
            )
            case["presented_families"] = sorted(shown | set(c["qualifying_families"]))
            self.reviews.append(case)
            results.append(case)
            self.last_admission[c["identity_id"]] = copy.deepcopy(case)
            del self.pending[c["identity_id"]]
            self.decisions.append(
                {
                    "identity_id": c["identity_id"],
                    "days": c["days"],
                    "case_id": case["case_id"],
                    "reason": "admitted",
                    "decision_time": when,
                    "reopening": case["reopening"],
                }
            )
        for c in candidates[len(chosen) :]:
            self.decisions.append(
                {
                    "identity_id": c["identity_id"],
                    "days": c["days"],
                    "reason": "budget_wait",
                    "decision_time": when,
                }
            )
        return results

    def state(self):
        return copy.deepcopy(self.__dict__)


def configuration():
    return json.loads((ROOT / "config.json").read_text())


def verify_model(originals=False):
    """Check the deployed model contract; historical artifacts are not runtime dependencies."""
    cfg = configuration()
    if digest(ROOT / cfg["deployment"]["model"]) != cfg["deployment"]["sha256"]:
        raise ValueError("Deployed model checksum changed")
    for shard in ("recovery-v3", "workload-v4"):
        for source in cfg["sources"]:
            if not (ROOT / "data/raw" / shard / (source + ".csv")).is_file():
                raise ValueError("Missing original source: " + shard + "/" + source)
        if not list((ROOT / "data/raw" / shard / "LDAP").glob("*.csv")):
            raise ValueError("Missing monthly identity metadata: " + shard)
    if originals:
        provenance = json.loads((ROOT / "data/provenance.json").read_text())
        for section, shard, key in (
            ("prefix", "recovery-v3", "sources"),
            ("extension", "workload-v4", "extension_sources"),
        ):
            source_root = ROOT / "data/raw" / shard
            for source in provenance[section][key]:
                path = source_root / (source["source"] + ".csv")
                if digest(path) != source["selected_sha256"]:
                    raise ValueError("Original source checksum changed: " + str(path))
            for month in provenance[section]["monthly_metadata"]:
                path = source_root / "LDAP" / (month["month"] + ".csv")
                if digest(path) != month["sha256"]:
                    raise ValueError("Identity metadata checksum changed: " + str(path))
    return cfg


class WorkloadReplay:
    def __init__(self, path=None, new=False):
        self.cfg = verify_model()
        self.selection = self.cfg["deployment"]
        self.key = self.selection["scorer"]
        self.bundle = joblib.load(ROOT / self.selection["model"])
        self.gate = self.bundle["gates"][self.selection["gate"]]
        if self.bundle["representation"] != self.selection["representation"]:
            raise ValueError("Deployed model representation changed")
        self.store = WorkloadStore(path)
        self.lock = self.store.path.with_suffix(".lock").open("a+")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise ValueError("Another pipeline writer owns this run") from None
        self.identity = digest(ROOT / "config.json")
        old = self.store.run()
        self.checkpoint_requested = False
        if new or not old:
            self.run_id = uuid.uuid4().hex
            self.stream = WorkloadStream(self.cfg)
            self.queue = WorkloadQueue(self.cfg["queue"], self.selection["queue_variant"])
            self.cursor = 0
            self.last_key = None
            self.pointer_cache = {}
            self.pending_decision = None
            self.status = "paused"
            self.last_closed = self.stream.day - timedelta(days=1)
            n = self.cfg["events"]
            with self.store.connection() as db:
                db.execute(
                    "INSERT INTO runs VALUES(?,?,?,?,?,?,?)",
                    (self.run_id, "paused", 0, n, None, self.identity, datetime.now().isoformat()),
                )
            self.commit([], [])
        else:
            if old["experiment_identity"] != self.identity:
                raise ValueError("Preserve incompatible run and create a new run")
            self.run_id = old["id"]
            self.status = old["status"]
            with self.store.connection() as db:
                state = pickle.loads(
                    db.execute("SELECT checkpoint FROM runs WHERE id=?", (self.run_id,)).fetchone()[
                        0
                    ]
                )
            for k, v in state.items():
                setattr(self, k, v)
        start = self.last_key[0] if self.last_key else None
        self.iterator = (
            e
            for e in original_records(self.cfg, start)
            if self.last_key is None or (e.timestamp, e.event_id) > self.last_key
        )

    def case(self, c):

        def uid(x):
            return hashlib.sha256((self.run_id + ":" + x).encode()).hexdigest()[:24]

        return {
            **c,
            "case_id": uid(c["case_id"]),
            "batch_case_id": c["case_id"],
            "preceding_batch_case": c["preceding_case"],
            "preceding_case": uid(c["preceding_case"]) if c["preceding_case"] else None,
            "phase": "validation",
            "evidence_pointers": [
                {
                    **self.pointer_cache[e],
                    "relationship": "current scoring period"
                    if e in c["trigger_ids"]
                    else "prior rolling context",
                }
                for e in c["evidence_ids"]
            ],
            "threshold": self.gate,
            "feature_contract": "behavior-workload-v4",
            "model_version": self.key + " / " + self.bundle["representation"],
            "queue_version": self.selection["queue_variant"],
            "calibration_version": self.selection["gate"],
            "evidence_semantics": "Aggregate context; exact forest attribution not computed",
        }

    def decide(self):
        if not self.pending_decision:
            return []
        result = [self.case(c) for c in self.queue.decide(self.pending_decision)]
        self.pending_decision = None
        needed = {e for c in self.queue.pending.values() for e in c["evidence_ids"]}
        self.pointer_cache = {e: p for e, p in self.pointer_cache.items() if e in needed}
        return result

    def closed(self, rr):
        output = []
        ready = [
            r
            for r in rr
            if self.cfg["final"]["validation_start"]
            <= r["day"]
            < self.cfg["final"]["validation_end"]
            and r["common_eligible"]
        ]
        scored = iter(predict(ready, self.bundle)) if ready else iter(())
        for r in rr:
            self.last_closed = datetime.fromisoformat(r["day"]).date()
            f = self.cfg["final"]
            if (
                not f["validation_start"] <= r["day"] < f["validation_end"]
                or not r["common_eligible"]
            ):
                continue
            score = float(next(scored))
            output.append(
                {
                    "day": r["day"],
                    "identity_id": r["identity_id"],
                    "score": score,
                    "features": r["features"]["28"],
                    "percentiles": r["percentiles"],
                    "peer_features": r["peer_features"],
                    "reference": r["references"]["28"],
                    "percentile_reference": r["percentile_reference"],
                    "peer_reference": r["peer_reference"],
                    "counts": r["counts"],
                    "role": r["role"],
                    "metadata_month": r["metadata_month"],
                    "transformed_inputs": dict(
                        zip(
                            self.bundle["names"],
                            matrix([r], self.bundle["representation"])[0][0].tolist(),
                            strict=True,
                        )
                    ),
                    "contract": "behavior-workload-v4",
                    "model_version": self.key + " / " + self.bundle["representation"],
                }
            )
            if score >= self.gate:
                pointers = r["context_pointers"]
                self.pointer_cache.update({p["event_id"]: p for p in pointers})
                self.queue.offer(
                    {
                        "detector": self.key,
                        "identity_id": r["identity_id"],
                        "day": r["day"],
                        "available_time": r["score_timestamp"],
                        "score": score,
                        "trigger_ids": r["event_ids"],
                        "evidence_ids": sorted({p["event_id"] for p in pointers}),
                        "qualifying_families": r["qualifying_families"],
                    }
                )
        return output

    def commit(self, rows, cases):
        state = {
            k: getattr(self, k)
            for k in [
                "stream",
                "queue",
                "cursor",
                "last_key",
                "pointer_cache",
                "pending_decision",
                "last_closed",
            ]
        }
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            for r in rows:
                db.execute(
                    "INSERT INTO observations VALUES(?,?,?,?,?)",
                    (
                        self.run_id,
                        r["day"],
                        r["identity_id"],
                        r["score"],
                        json.dumps(r, separators=(",", ":")),
                    ),
                )
            for c in cases:
                db.execute(
                    "INSERT INTO cases VALUES(?,?,?,?,?,?)",
                    (
                        c["case_id"],
                        self.run_id,
                        c["detector"],
                        c["identity_id"],
                        c["decision_time"],
                        json.dumps(c, separators=(",", ":")),
                    ),
                )
            db.execute(
                "UPDATE runs SET status=?,cursor=?,checkpoint=? WHERE id=?",
                (self.status, self.cursor, pickle.dumps(state, protocol=5), self.run_id),
            )

    def step(self, count=100000, checkpoint_on_pending=False):
        out = []
        cases = []
        self.checkpoint_requested = False
        try:
            cases.extend(self.decide())
            for _ in range(count):
                try:
                    e = next(self.iterator)
                except StopIteration:
                    rr = self.stream.finish(datetime.fromisoformat(self.cfg["end"]))
                    out.extend(self.closed(rr))
                    if rr:
                        self.pending_decision = (
                            datetime.fromisoformat(self.cfg["end"])
                            + timedelta(hours=self.cfg["queue"]["decision_hour"])
                        ).isoformat()
                        cases.extend(self.decide())
                    for j in range(1, self.cfg["queue"]["backlog_days"] + 1):
                        self.pending_decision = (
                            datetime.fromisoformat(self.cfg["end"])
                            + timedelta(days=j, hours=self.cfg["queue"]["decision_hour"])
                        ).isoformat()
                        cases.extend(self.decide())
                    self.status = "completed"
                    break
                previous = self.stream.day
                rr = self.stream.push(e)
                self.cursor += 1
                self.last_key = (e.timestamp, e.event_id)
                if self.stream.day != previous:
                    out.extend(self.closed(rr))
                    day = previous
                    while day < self.stream.day:
                        if (
                            self.cfg["final"]["validation_start"]
                            <= day.isoformat()
                            < self.cfg["final"]["validation_end"]
                        ):
                            self.pending_decision = (
                                datetime.combine(day + timedelta(days=1), datetime.min.time())
                                + timedelta(hours=self.cfg["queue"]["decision_hour"])
                            ).isoformat()
                            if checkpoint_on_pending and self.queue.pending:
                                self.checkpoint_requested = True
                                break
                            cases.extend(self.decide())
                        day += timedelta(days=1)
                    if self.checkpoint_requested:
                        break
            self.commit(out, cases)
        except Exception:
            self.close()
            raise
        return self.store.summary()

    def close(self):
        if not self.lock.closed:
            fcntl.flock(self.lock, fcntl.LOCK_UN)
            self.lock.close()
