"""Streaming CERT records, schema checks and exact source evidence."""

import csv
import hashlib
import heapq
import itertools
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]


def parse_date(value):
    for fmt in ("%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    raise ValueError(f"Unsupported timestamp: {value!r}. Expected ISO or CERT date format.")


def digest(path):
    checksum = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


SOURCES = ("device", "email", "file", "http", "logon")


@dataclass(frozen=True, slots=True)
class Record:
    event_id: str
    timestamp: object
    identity_id: str
    computer_id: str
    source: str
    action: str
    role: str
    metadata_month: str
    fields: dict
    offset: int
    row_number: int
    source_file: str

    def pointer(self):
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "source_file": self.source_file,
            "offset": self.offset,
            "row_number": self.row_number,
            "metadata_month": self.metadata_month,
            "role": self.role,
        }


def rosters(root):
    result = {}
    for p in sorted((root / "LDAP").glob("*.csv")):
        with p.open(newline="") as f:
            result[p.stem] = {r.get("user_id", r.get("user", "")): r for r in csv.DictReader(f)}
    return result


def records(root, start=None, end=None, sources=SOURCES):
    """CSV line offsets support exact original evidence retrieval without copying content."""
    root = Path(root)
    metadata = rosters(root)

    def source(kind):
        p = root / (kind + ".csv")
        previous = None
        if not p.exists():
            return
        with p.open("rb") as f:
            header = next(csv.reader([f.readline().decode("utf-8-sig")]))
            n = 1
            while True:
                offset = f.tell()
                line = f.readline()
                n += 1
                if not line:
                    break
                cells = next(csv.reader([line.decode("utf-8-sig")]))
                if len(cells) != len(header):
                    raise ValueError(f"{p}:{n}: malformed/multiline record")
                row = dict(zip(header, cells, strict=True))
                t = parse_date(row["date"])
                if previous and t < previous:
                    raise ValueError("Source timestamp inversion")
                previous = t
                if start and t < start:
                    continue
                if end and t >= end:
                    break
                month = t.strftime("%Y-%m")
                person = metadata.get(month, {}).get(row["user"], {})
                yield Record(
                    kind + ":" + row["id"],
                    t,
                    row["user"],
                    row["pc"],
                    kind,
                    row.get(
                        "activity",
                        "Copy to removable media"
                        if kind == "file"
                        else "Send"
                        if kind == "email"
                        else "Visit",
                    ),
                    person.get("role", "Unknown role"),
                    month,
                    row,
                    offset,
                    n,
                    str(p),
                )

    def ordered(kind):
        for _, group in itertools.groupby(source(kind), key=lambda r: r.timestamp):
            yield from sorted(group, key=lambda r: r.event_id)

    yield from heapq.merge(*(ordered(k) for k in sources), key=lambda r: (r.timestamp, r.event_id))


def evidence(pointer):
    p = Path(pointer["source_file"])
    with p.open("rb") as f:
        header = next(csv.reader([f.readline().decode("utf-8-sig")]))
        f.seek(pointer["offset"])
        fields = dict(
            zip(header, next(csv.reader([f.readline().decode("utf-8-sig")])), strict=True)
        )
    if pointer["source"] + ":" + fields["id"] != pointer["event_id"]:
        raise ValueError("Evidence pointer no longer matches source")
    return {
        **pointer,
        "original": fields,
        "schema": "CERT-r4.2-original-record",
        "message_size_semantics": "Message bytes excluding attachments"
        if pointer["source"] == "email"
        else None,
    }


def recipients(fields):
    return {
        a.strip().lower()
        for k in ("to", "cc", "bcc")
        for a in fields.get(k, "").split(";")
        if a.strip()
    }


def host(fields):
    return urlparse(fields.get("url", "")).hostname or ""


def normalize(record):
    if record.source != "email":
        return record
    fields = dict(record.fields)
    aliases = ("attachment_count", "attachments")
    present = [k for k in aliases if k in fields and fields[k] != ""]
    if not present:
        raise ValueError(
            "Email source has no attachment-count column; do not silently substitute zero"
        )
    values = [int(fields[k]) for k in present]
    if min(values) < 0 or len(set(values)) != 1:
        raise ValueError("Invalid/conflicting attachment-count aliases")
    fields["attachment_count"] = values[0]
    fields["attachment_count_original_column"] = present[0]
    return replace(record, fields=fields)
