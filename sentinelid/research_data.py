"""Shard-spanning original replay, feature extraction and offline truth for research."""

import csv
import io
import json
import os
import sqlite3
import tarfile
import zlib
from contextlib import closing
from datetime import datetime
from pathlib import Path

from .features import WorkloadStream
from .ingestion import ROOT, normalize, parse_date, records, rosters

# Contiguous original shards; holdout-v5 is the sealed research period.
SHARDS = [
    ("recovery-v3", datetime(2010, 5, 1), datetime(2010, 10, 15)),
    ("workload-v4", datetime(2010, 10, 15), datetime(2010, 12, 1)),
    ("holdout-v5", datetime(2010, 12, 1), datetime(2011, 5, 17)),
]
DEVELOPMENT_END = "2010-12-01"


def shard_records(start, end, root=ROOT):
    for shard, lo, hi in SHARDS:
        lo, hi = max(lo, start), min(hi, end)
        if lo < hi:
            for e in records(root / "data/raw" / shard, start=lo, end=hi):
                yield normalize(e)


def extract(start, end, path, config=None, root=ROOT):
    """Replay originals through the deployed v4 feature builder into a row cache."""
    config = dict(config or json.loads((root / "config.json").read_text()))
    config["start"] = start.isoformat()
    stream = WorkloadStream(config)
    for shard, _, _ in SHARDS:
        directory = root / "data/raw" / shard
        if directory.exists():
            stream.metadata.update(rosters(directory))
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.unlink(missing_ok=True)
    count = events = 0
    with closing(sqlite3.connect(temporary)) as db:
        db.execute(
            "CREATE TABLE rows(day TEXT,identity TEXT,payload BLOB,PRIMARY KEY(day,identity))"
        )

        def write(rows):
            nonlocal count
            for r in rows:
                for k in ("current_pointers", "context_pointers"):
                    r.pop(k, None)
                db.execute(
                    "INSERT INTO rows VALUES(?,?,?)",
                    (r["day"], r["identity_id"], zlib.compress(json.dumps(r).encode())),
                )
                count += 1

        for e in shard_records(start, end, root):
            events += 1
            write(stream.push(e))
            if events % 1_000_000 == 0:
                db.commit()
                print("Extracted events:", events, "day:", stream.day, flush=True)
        write(stream.finish(end))
        db.commit()
    os.replace(temporary, path)
    return {"events": events, "identity_days": count, "start": start.isoformat()}


def cached_rows(path, start=None, end=None):
    with closing(
        sqlite3.connect("file:" + str(Path(path).resolve()) + "?mode=ro&immutable=1", uri=True)
    ) as db:
        statement = "SELECT payload FROM rows"
        parameters = []
        if start:
            statement += " WHERE day>=? AND day<?"
            parameters = [start, end]
        for (payload,) in db.execute(statement + " ORDER BY day,identity", parameters):
            yield json.loads(zlib.decompress(payload))


def truth(archive, start, end):
    """Labelled malicious records with day in [start, end), in validation-truth schema."""
    events = {}
    with tarfile.open(archive, "r:bz2") as tar:
        incidents = {}
        for row in csv.DictReader(
            io.TextIOWrapper(tar.extractfile("answers/insiders.csv"), encoding="utf-8-sig")
        ):
            if row["dataset"] == "4.2":
                incidents[row["details"]] = row
        for member in tar.getmembers():
            incident = incidents.get(Path(member.name).name)
            if not member.isfile() or not incident:
                continue
            for cells in csv.reader(
                io.TextIOWrapper(tar.extractfile(member), encoding="utf-8-sig")
            ):
                if len(cells) < 5 or cells[0] not in ("device", "logon", "file", "email", "http"):
                    continue
                stamp = parse_date(cells[2]).isoformat()
                if start <= stamp[:10] < end:
                    events[cells[0] + ":" + cells[1]] = {
                        "event_id": cells[0] + ":" + cells[1],
                        "source": cells[0],
                        "timestamp": stamp,
                        "day": stamp[:10],
                        "observed_account": cells[3],
                        "incident_id": incident["details"],
                        "actor": incident["user"],
                        "scenario": incident["scenario"],
                        "official_start": parse_date(incident["start"]).isoformat(),
                        "official_end": parse_date(incident["end"]).isoformat(),
                    }
    return events
