"""Daily activity ledger and the causal behavior features computed from it.

The frozen feature builder ignores most raw fields and profiles each identity alone. The
ledger keeps per identity-day aggregates of three fields, built in one pass over the original
CSVs: HTTP destination counts, email recipient totals and logon computers. Its features add
population context (who else visits a destination, whose computer a logon lands on, who else
used one's own computer). A day's values use that day and earlier ones only; references follow
the frozen pipeline's convention (28 calendar days, lagged 7 days).
"""

import csv
import json
import math
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import numpy as np

from .features import centered_percentile, change
from .ingestion import ROOT, parse_date, recipients
from .research_data import SHARDS

COLUMNS = {
    "http": ("date", "user", "url"),
    "email": ("date", "user", "to", "cc", "bcc"),
    "logon": ("date", "user", "pc", "activity"),
}

SERIES = (
    "rare_visits",
    "job_visits",
    "recipients",
    "max_recipients",
    "foreign_logons",
    "exposure",
)
# Feature groups; each series contributes a personal percentile and a magnitude.
GROUPS = {
    "rarity": ("rare_visits", "domain_rarity"),
    "job": ("job_visits",),
    "email": ("recipients", "max_recipients"),
    "pc": ("foreign_logons",),
    "exposure": ("exposure",),
}
# A destination is population-rare when this few distinct identities visited it before today.
RARE_VISITORS = 3
# A computer has an owner after this many logons, when one identity holds this share of them.
OWNER_LOGONS, OWNER_SHARE = 10, 0.6
# Exposure counts other identities' logons on one's own computers over this many days to date.
EXPOSURE_DAYS = 3
JOB_WORDS = (
    "job",
    "career",
    "hire",
    "recruit",
    "resume",
    "employ",
    "monster",
    "indeed",
    "glassdoor",
    "linkedin",
)
LAG, WINDOW = 7, 28
# Bump when a feature's meaning changes, so cached feature matrices are rebuilt.
# 2: exposure is stored on days the exposed owner is silent too (it was recorded as 0).
VERSION = 2


def day_of(text):
    """ISO day of a CERT (MM/DD/YYYY) or ISO timestamp without a full parse."""
    if len(text) == 19 and text[2] == "/" and text[5] == "/":
        return f"{text[6:10]}-{text[:2]}-{text[3:5]}"
    if len(text) == 19 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return parse_date(text).date().isoformat()


def rows(path, columns):
    with open(path, newline="", encoding="utf-8-sig") as stream:
        reader = csv.reader(stream)
        header = next(reader)
        index = [header.index(c) for c in columns]
        for n, cells in enumerate(reader, start=2):
            if len(cells) != len(header):
                raise ValueError(f"{path}:{n}: malformed/multiline record")
            yield [cells[i] for i in index]


def aggregate(source, root, start, end):
    """Yield (day, {identity: payload}) in day order from one source across all shards."""
    current, bucket = None, {}
    for shard, _, _ in SHARDS:
        path = root / "data/raw" / shard / (source + ".csv")
        if not path.exists():
            continue
        for cells in rows(path, COLUMNS[source]):
            day = day_of(cells[0])
            if day < start or day >= end:
                continue
            if current and day < current:
                raise ValueError(f"{path}: source day inversion at {day}")
            if day != current:
                if current:
                    yield current, bucket
                current, bucket = day, {}
            user = cells[1]
            if source == "http":
                payload = bucket.setdefault(user, Counter())
                payload[urlparse(cells[2]).hostname or ""] += 1
            elif source == "email":
                payload = bucket.setdefault(user, {"emails": 0, "recipients": 0, "max": 0})
                n = len(recipients(dict(zip(("to", "cc", "bcc"), cells[2:], strict=True))))
                payload["emails"] += 1
                payload["recipients"] += n
                payload["max"] = max(payload["max"], n)
            elif cells[3].lower() == "logon":
                bucket.setdefault(user, Counter())[cells[2]] += 1
    if current:
        yield current, bucket


def build(start, end, directory, root=ROOT):
    """Write the three ledger tables and a manifest; replaces any earlier ledger."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "ledger.sqlite"
    temporary = path.with_name(path.name + ".tmp")
    temporary.unlink(missing_ok=True)
    counts = {}
    with closing(sqlite3.connect(temporary)) as db:
        for source in COLUMNS:
            db.execute(
                f"CREATE TABLE {source}(day TEXT,identity TEXT,payload TEXT,"
                "PRIMARY KEY(day,identity)) WITHOUT ROWID"
            )
            counts[source] = 0
            for day, bucket in aggregate(source, root, start, end):
                db.executemany(
                    f"INSERT INTO {source} VALUES(?,?,?)",
                    [(day, u, json.dumps(p, separators=(",", ":"))) for u, p in bucket.items()],
                )
                counts[source] += len(bucket)
            db.commit()
            print("Ledger", source, counts[source], "identity-days", flush=True)
    temporary.replace(path)
    manifest = {
        "start": start,
        "end": end,
        "identity_days": counts,
        "sources": {
            f"{shard}/{source}.csv": (root / "data/raw" / shard / (source + ".csv")).stat().st_size
            for shard, _, _ in SHARDS
            for source in COLUMNS
            if (root / "data/raw" / shard / (source + ".csv")).exists()
        },
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest


def is_job(domain):
    return any(word in domain for word in JOB_WORDS)


def table(db, source, day):
    return {
        u: json.loads(p)
        for u, p in db.execute(f"SELECT identity,payload FROM {source} WHERE day=?", (day,))
    }


def names(groups=None):
    """Column names for the requested groups (all by default), in storage order."""
    wanted = {s for g in (groups or GROUPS) for s in GROUPS[g]}
    result = []
    for s in (*SERIES, "domain_rarity"):
        if s in wanted:
            result += (
                [s] if s == "domain_rarity" else ["percentile:ledger_" + s, "magnitude:ledger_" + s]
            )
    return result


class State:
    """Causal ledger state: who visited what, who owns which computer, recent daily values."""

    def __init__(self):
        self.visitors = defaultdict(set)
        self.known = set()
        self.logons = defaultdict(Counter)
        self.owner = {}
        self.visits = defaultdict(dict)
        self.values = defaultdict(dict)

    def popularity(self, domain):
        return len(self.visitors[domain])

    def rarity(self, domain):
        return -math.log((self.popularity(domain) + 1) / (len(self.known) + 1))

    def visited(self, ordinal, logon):
        """Record today's visits; return every owner exposed within the window to date.

        An owner can be silent today and still exposed by a visit one or two days ago; that
        value belongs in their history, or later references would read it as zero.
        """
        for user, pcs in logon.items():
            for pc, n in pcs.items():
                owner = self.owner.get(pc)
                if owner not in (None, user):
                    days = self.visits[owner]
                    days[ordinal] = days.get(ordinal, 0) + n
        return [owner for owner in self.visits if self.exposure(owner, ordinal)]

    def exposure(self, user, ordinal):
        days = self.visits.get(user, {})
        return sum(days.get(o, 0) for o in range(ordinal - EXPOSURE_DAYS + 1, ordinal + 1))

    def today(self, user, ordinal, http, email, logon):
        """Series values and the rarest-destination score from state before today."""
        rare = job = 0
        top = 0.0
        for domain, n in (http or {}).items():
            top = max(top, self.rarity(domain))
            rare += n if self.popularity(domain) <= RARE_VISITORS else 0
            job += n if is_job(domain) else 0
        foreign = sum(
            n for pc, n in (logon or {}).items() if self.owner.get(pc) not in (None, user)
        )
        mail = email or {}
        return (
            rare,
            job,
            mail.get("recipients", 0),
            mail.get("max", 0),
            foreign,
            self.exposure(user, ordinal),
        ), top

    def reference(self, user, ordinal, index):
        history = self.values[user]
        return [
            history[o][index] if o in history else 0.0
            for o in range(ordinal - LAG - WINDOW, ordinal - LAG)
        ]

    def update(self, ordinal, http, logon, series):
        for user, domains in http.items():
            self.known.add(user)
            for domain in domains:
                self.visitors[domain].add(user)
        for user, pcs in logon.items():
            for pc, n in pcs.items():
                self.logons[pc][user] += n
                user_, total = self.logons[pc].most_common(1)[0]
                every = sum(self.logons[pc].values())
                self.owner[pc] = (
                    user_ if every >= OWNER_LOGONS and total / every >= OWNER_SHARE else None
                )
        for user, values in series.items():
            history = self.values[user]
            history[ordinal] = values
            history.pop(ordinal - LAG - WINDOW - 1, None)
        for days in self.visits.values():
            for old in [o for o in days if o <= ordinal - EXPOSURE_DAYS + 1]:
                del days[old]


def features(directory, keys):
    """Feature matrix for (day, identity) keys in day order; columns follow names()."""
    state = State()
    wanted = defaultdict(list)
    for position, (day, identity) in enumerate(keys):
        wanted[day].append((position, identity))
    matrix = np.zeros((len(keys), len(names())))
    layout = {c: j for j, c in enumerate(names())}
    with closing(sqlite3.connect(Path(directory) / "ledger.sqlite")) as db:
        recorded = db.execute(
            "SELECT day FROM http UNION SELECT day FROM email UNION SELECT day FROM logon"
        )
        days = sorted({d for (d,) in recorded} | set(wanted))
        for day in days:
            ordinal = date.fromisoformat(day).toordinal()
            http, email, logon = (table(db, s, day) for s in ("http", "email", "logon"))
            exposed = state.visited(ordinal, logon)
            series = {}
            for user in http.keys() | email.keys() | logon.keys() | set(exposed):
                series[user] = state.today(
                    user, ordinal, http.get(user), email.get(user), logon.get(user)
                )
            for position, user in wanted.get(day, ()):
                values, top = series.get(user) or state.today(user, ordinal, None, None, None)
                if user in http:
                    matrix[position, layout["domain_rarity"]] = top
                for index, s in enumerate(SERIES):
                    reference = state.reference(user, ordinal, index)
                    matrix[position, layout["percentile:ledger_" + s]] = centered_percentile(
                        values[index], reference
                    )
                    matrix[position, layout["magnitude:ledger_" + s]] = math.log1p(
                        change(values[index], reference, 1)[0]
                    )
            state.update(ordinal, http, logon, {u: v for u, (v, _) in series.items()})
    return matrix
