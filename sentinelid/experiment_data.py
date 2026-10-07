"""One corrected reusable measurement cache, separate from historical observations."""

import json
import os
import sqlite3
import zlib
from collections import deque
from contextlib import closing
from datetime import date, timedelta

import numpy as np

from .experiment_evaluation import training_truth
from .experiment_features import TEMPORAL, ModuleOutput, corrected, measurements, vector
from .experiment_io import digest, save_json


def unpack(value):
    return json.loads(zlib.decompress(value))


def source_rows(path, start=None, end=None):
    with closing(
        sqlite3.connect("file:" + str(path.resolve()) + "?mode=ro&immutable=1", uri=True)
    ) as db:
        statement = "SELECT payload FROM rows"
        parameters = []
        if start:
            statement += " WHERE day>=? AND day<?"
            parameters = [start, end]
        statement += " ORDER BY day,identity"
        for (payload,) in db.execute(statement, parameters):
            yield unpack(payload)


def prepare(inputs, directory, protocol):
    path = directory / "measurements.sqlite"
    marker = directory / "measurements.json"
    if marker.exists():
        saved = json.loads(marker.read_text())
        if digest(path) != saved["sha256"]:
            raise ValueError("Prepared experimental measurements changed")
        return saved
    labels = training_truth(
        inputs / "answers.tar.bz2", protocol["history_start"], protocol["fit_end"]
    )
    temporary = path.with_suffix(".tmp")
    temporary.unlink(missing_ok=True)
    daily = {}
    age = deque()
    count = 0
    changes = {"usb": 0, "copy": 0}
    with closing(sqlite3.connect(temporary)) as db:
        db.execute(
            "CREATE TABLE samples(day TEXT,identity TEXT,pm BLOB,tvalues BLOB,pvalues BLOB,temporal BLOB,peer BLOB,label INTEGER,relevance INTEGER,audit BLOB,PRIMARY KEY(day,identity))"
        )
        for row in source_rows(inputs / "features.sqlite"):
            key = (row["identity_id"], row["day"])
            daily[key] = {"counts": row["counts"], "event_ids": row["event_ids"]}
            age.append(key)
            cutoff = (date.fromisoformat(row["day"]) - timedelta(days=6)).isoformat()
            while age and age[0][1] < cutoff:
                daily.pop(age.popleft(), None)
            if not row["common_eligible"] or row["day"] < protocol["fit_start"]:
                continue
            fixed = corrected(row, daily)
            t, p = measurements(fixed, daily)
            values, names = vector(fixed, t, p)
            label = relevance = None
            if row["day"] < protocol["fit_end"]:
                label = int(any(e in labels for e in row["event_ids"]))
                relevance = int(
                    any(
                        e in labels
                        for d in fixed["target_dates"]["7"]
                        for e in daily.get((row["identity_id"], d), {}).get("event_ids", [])
                    )
                )
            audit = {
                "target_dates": fixed["target_dates"],
                "details": {
                    k: fixed["references"]["28"]["details"][k]
                    for k in ("usb_change_3", "copy_change_3")
                },
            }
            for kind in changes:
                changes[kind] += (
                    row["features"]["28"][kind + "_change_3"]
                    != fixed["features"]["28"][kind + "_change_3"]
                )
            db.execute(
                "INSERT INTO samples VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    row["day"],
                    row["identity_id"],
                    values.tobytes(),
                    np.asarray([t.measurements()[k] for k in TEMPORAL], dtype=float).tobytes(),
                    np.asarray(
                        [
                            p.measurements()[k]
                            for k in (
                                "peer_usb_percentile",
                                "peer_copy_percentile",
                                "peer_external_email_percentile",
                                "peer_supported",
                            )
                        ],
                        dtype=float,
                    ).tobytes(),
                    zlib.compress(t.serialized.encode()),
                    zlib.compress(p.serialized.encode()),
                    label,
                    relevance,
                    zlib.compress(json.dumps(audit).encode()),
                ),
            )
            count += 1
            if count % 20000 == 0:
                db.commit()
                print("Prepared corrected rows:", count, flush=True)
        db.commit()
    os.replace(temporary, path)
    result = {
        "feature_contract": "behavior-experiment-v1",
        "rows": count,
        "names": names,
        "sha256": digest(path),
        "source_cache_sha256": digest(inputs / "features.sqlite"),
        "magnitude_changes": changes,
        "labels": "Training through October14 only; calibration/evaluation labels absent",
    }
    save_json(marker, result)
    return result


def arrays(directory):
    result = {key: [] for key in ("keys", "pm", "temporal", "peer", "label", "relevance")}
    with closing(
        sqlite3.connect(
            "file:" + str((directory / "measurements.sqlite").resolve()) + "?mode=ro&immutable=1",
            uri=True,
        )
    ) as db:
        for day, identity, pm, tv, pv, label, relevance in db.execute(
            "SELECT day,identity,pm,tvalues,pvalues,label,relevance FROM samples ORDER BY day,identity"
        ):
            result["keys"].append((day, identity))
            for key, blob in [("pm", pm), ("temporal", tv), ("peer", pv)]:
                result[key].append(np.frombuffer(blob, dtype=float))
            result["label"].append(-1 if label is None else label)
            result["relevance"].append(-1 if relevance is None else relevance)
    for key in result:
        if key != "keys":
            result[key] = np.asarray(result[key])
    return result


def module_outputs(directory, day, identity):
    with closing(
        sqlite3.connect(
            "file:" + str((directory / "measurements.sqlite").resolve()) + "?mode=ro&immutable=1",
            uri=True,
        )
    ) as db:
        row = db.execute(
            "SELECT temporal,peer,audit FROM samples WHERE day=? AND identity=?", (day, identity)
        ).fetchone()
    return (
        ModuleOutput(zlib.decompress(row[0]).decode()),
        ModuleOutput(zlib.decompress(row[1]).decode()),
        unpack(row[2]),
    )
