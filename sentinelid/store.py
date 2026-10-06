"""Atomic state, immutable cases and append-only review history."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .ingestion import ROOT, evidence


class WorkloadStore:
    def __init__(self, path=None):
        self.path = Path(path or ROOT / "data/operations.sqlite")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript(
                "\n                CREATE TABLE IF NOT EXISTS runs (\n                    id TEXT PRIMARY KEY, status TEXT, cursor INTEGER,\n                    events INTEGER, checkpoint BLOB, identity TEXT, created TEXT\n                );\n                CREATE TABLE IF NOT EXISTS observations (\n                    run TEXT, day TEXT, identity TEXT, score REAL, payload TEXT,\n                    PRIMARY KEY(run, day, identity)\n                );\n                CREATE TABLE IF NOT EXISTS cases (\n                    id TEXT PRIMARY KEY, run TEXT, detector TEXT, identity TEXT,\n                    decision TEXT, payload TEXT\n                );\n                CREATE TABLE IF NOT EXISTS reviews (\n                    case_id TEXT, version INTEGER, status TEXT, disposition TEXT,\n                    note TEXT, actor TEXT, created TEXT,\n                    PRIMARY KEY(case_id, version)\n                );\n            "
            )

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def run(self, run_id=None):
        with self.connection() as db:
            r = db.execute(
                "SELECT id,status,cursor,events,identity,created FROM runs "
                + ("WHERE id=?" if run_id else "ORDER BY rowid DESC LIMIT 1"),
                (run_id,) if run_id else (),
            ).fetchone()
        return (
            dict(
                zip(
                    (
                        "id",
                        "status",
                        "events_processed",
                        "events_total",
                        "experiment_identity",
                        "created",
                    ),
                    r,
                    strict=True,
                )
            )
            if r
            else None
        )

    def summary(self):
        result = {"run": self.run(), "runs": [], "case_count": 0, "detector": None}
        with self.connection() as db:
            result["runs"] = [
                dict(zip(("id", "status", "cursor"), r, strict=True))
                for r in db.execute("SELECT id,status,cursor FROM runs ORDER BY rowid DESC")
            ]
            if result["run"]:
                rid = result["run"]["id"]
                result["case_count"] = db.execute(
                    "SELECT count(*) FROM cases WHERE run=?", (rid,)
                ).fetchone()[0]
                r = db.execute("SELECT detector FROM cases WHERE run=? LIMIT 1", (rid,)).fetchone()
                result["detector"] = r[0] if r else None
                result["closed_days"] = db.execute(
                    "SELECT count(DISTINCT day) FROM observations WHERE run=?", (rid,)
                ).fetchone()[0]
        return result

    def queue(self, run_id=None, detector=None, status="all", search="", offset=0, limit=20):
        run = self.run(run_id)
        if not run:
            return {"rows": [], "total": 0}
        if status not in ("all", "new", "in_review", "resolved", "dismissed"):
            raise ValueError("Invalid review status")
        with self.connection() as db:
            rows = []
            for cid, payload in db.execute(
                "SELECT id,payload FROM cases WHERE run=? AND identity LIKE ? ORDER BY decision,id",
                (run["id"], "%" + search + "%"),
            ):
                case = json.loads(payload)
                if detector and detector != case["detector"]:
                    continue
                review = self.latest_review(db, cid)
                if status != "all" and review["status"] != status:
                    continue
                rows.append(
                    {
                        **{
                            k: v
                            for k, v in case.items()
                            if k not in ("evidence_pointers", "evidence_ids", "trigger_ids")
                        },
                        "evidence_total": len(case["evidence_pointers"]),
                        "review": review,
                    }
                )
        return {"run": run["id"], "total": len(rows), "rows": rows[offset : offset + limit]}

    def latest_review(self, db, cid):
        row = db.execute(
            "SELECT version,status,disposition,note,actor,created FROM reviews WHERE case_id=? ORDER BY version DESC LIMIT 1",
            (cid,),
        ).fetchone()
        return (
            dict(
                zip(
                    ("version", "status", "disposition", "note", "actor", "created"),
                    row,
                    strict=True,
                )
            )
            if row
            else {"version": 0, "status": "new", "disposition": "unreviewed", "note": ""}
        )

    def detail(self, cid, offset=0, limit=50):
        with self.connection() as db:
            record = db.execute("SELECT payload,run FROM cases WHERE id=?", (cid,)).fetchone()
            if not record:
                raise ValueError("Unknown case")
            case = json.loads(record[0])
            observations = [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT payload FROM observations WHERE run=? AND identity=? ORDER BY day",
                    (record[1], case.get("identity_id", "")),
                )
                if json.loads(r[0])["day"] in case.get("days", [])
            ]
            review = self.latest_review(db, cid)
            history = [
                dict(
                    zip(
                        ("version", "status", "disposition", "note", "actor", "created"),
                        r,
                        strict=True,
                    )
                )
                for r in db.execute(
                    "SELECT version,status,disposition,note,actor,created FROM reviews WHERE case_id=? ORDER BY version",
                    (cid,),
                )
            ]
        return {
            "case": {
                k: v
                for k, v in case.items()
                if k not in ("evidence_pointers", "evidence_ids", "trigger_ids")
            },
            "review": review,
            "review_history": history,
            "observations": observations,
            "evidence_total": len(case["evidence_pointers"]),
            "evidence_offset": offset,
            "events": [
                evidence(p)
                for p in sorted(
                    case["evidence_pointers"], key=lambda p: (p["timestamp"], p["event_id"])
                )[offset : offset + min(100, limit)]
            ],
            "policy": "Aggregate daily measurements and seven-day original context. Exact model-event attribution is not computed. No ground-truth labels in inference.",
        }

    def review(self, cid, version, status, disposition, note="", actor="local analyst"):
        if status not in ("new", "in_review", "resolved", "dismissed") or disposition not in (
            "unreviewed",
            "benign",
            "suspicious",
            "confirmed",
            "needs_context",
        ):
            raise ValueError("Invalid analyst review")
        if not isinstance(note, str) or len(note) > 4000:
            raise ValueError("Invalid note")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM cases WHERE id=?", (cid,)).fetchone():
                raise ValueError("Unknown case")
            if self.latest_review(db, cid)["version"] != version:
                raise ValueError("Review changed; refresh before editing")
            db.execute(
                "INSERT INTO reviews VALUES(?,?,?,?,?,?,?)",
                (cid, version + 1, status, disposition, note, actor, datetime.now().isoformat()),
            )
        return self.detail(cid)
