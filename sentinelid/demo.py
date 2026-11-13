"""One-minute demo on an invented organisation, in the CERT r4.2 file layout.

Nothing here is CERT data, and the demo model is not the evaluated one. `generate` writes a
self-contained project root (configuration, five activity logs, monthly rosters and an answer
key) for 24 invented people over May-November 2010. Planted incidents imitate the three CERT
scenarios, including an account takeover. `fit` trains a small Random Forest on the root's
June-October rows with the deployed recipe. The real replay, queue, store and dashboard then
run unchanged against that root through `SENTINELID_ROOT`.
"""

import csv
import json
import os
import random
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier

from .ingestion import APP, digest

DEMO_ROOT = APP / "demo"
START, END, SPLIT = date(2010, 5, 1), date(2010, 12, 1), date(2010, 10, 15)
FIT_START, FIT_END = "2010-06-08", "2010-10-15"
DOMAIN = "dtaa.com"
HEADERS = {
    "logon": ["id", "date", "user", "pc", "activity"],
    "device": ["id", "date", "user", "pc", "activity"],
    "file": ["id", "date", "user", "pc", "filename", "content"],
    "email": [
        "id",
        "date",
        "user",
        "pc",
        "to",
        "cc",
        "bcc",
        "from",
        "size",
        "attachments",
        "content",
    ],
    "http": ["id", "date", "user", "pc", "url", "content"],
}
FIRST = "Ada Ben Cleo Dev Eli Fay Gus Hana Ivo Jun Kai Lea Max Nia Oli Pia Quinn Rae Sol Tess Uma Vic Wren Yan".split()
LAST = "Archer Bell Cole Dorsey Ennis Frost Gale Hart Imrie Joyce Keane Lowe Marsh Nolan Orr Pike Quill Reyes Shaw Toft Usher Vance Wilde York".split()
COMMON = [
    f"{name}.example"
    for name in "news weather maps wiki docs shop video forum mail travel sports finance music recipes cloud code".split()
]
JOBS = ["jobs-board.example", "careers-hub.example", "hire-now.example"]
LEAK, KEYLOGGER = "leak-drop.example", "keystroke-tools.example"
# (scenario, actor index, victim index or None, first day, last day); actors 0-8, victims 20-23.
INCIDENTS = [
    ("1", 0, None, "2010-07-19", "2010-07-22"),
    ("2", 1, None, "2010-07-26", "2010-08-20"),
    ("3", 2, 20, "2010-08-16", "2010-08-18"),
    ("1", 3, None, "2010-09-06", "2010-09-09"),
    ("2", 4, None, "2010-08-30", "2010-09-24"),
    ("3", 5, 21, "2010-09-27", "2010-09-29"),
    ("1", 6, None, "2010-11-08", "2010-11-11"),
    ("2", 7, None, "2010-11-01", "2010-11-19"),
    ("3", 8, 22, "2010-11-15", "2010-11-17"),
]


def days(first, last):
    d = date.fromisoformat(first) if isinstance(first, str) else first
    last = date.fromisoformat(last) if isinstance(last, str) else last
    while d <= last:
        yield d
        d += timedelta(days=1)


class World:
    """Invented people, their habits and the event log, built deterministically from a seed."""

    def __init__(self, seed=7):
        self.random = random.Random(seed)
        self.events = defaultdict(list)
        self.labels = defaultdict(list)
        self.serial = 0
        self.people = []
        for i, (first, last) in enumerate(zip(FIRST, LAST, strict=True)):
            role = (
                "ITAdmin"
                if i in (2, 5, 8)
                else "Manager"
                if i >= 20
                else ("Salesman" if i % 4 == 0 else "SoftwareEngineer")
            )
            self.people.append(
                {
                    "id": f"{first[0]}{last[0]}{last[1].upper()}{1000 + i * 37}",
                    "name": f"{first} {last}",
                    "role": role,
                    "team": "Sales" if role == "Salesman" else "Engineering",
                    "pc": f"PC-{4100 + i * 13}",
                    "start": self.random.uniform(7.5, 9.5),
                    "web": self.random.randint(3, 10),
                    "sites": self.random.sample(COMMON, 6),
                    "mail": self.random.randint(2, 6),
                    "usb": self.random.random() < 0.3,
                }
            )
        for i, p in enumerate(self.people):
            p["supervisor"] = self.people[20 + i % 4]["name"] if i < 20 else ""

    def add(self, source, when, person, pc, *fields, incident=None):
        self.serial += 1
        event_id = "{DEMO-%06d}" % self.serial
        self.events[source].append([event_id, when, person["id"], pc, *fields])
        if incident is not None:
            self.labels[incident].append(
                {
                    "event_id": source + ":" + event_id,
                    "timestamp": when.isoformat(),
                    "account": person["id"],
                }
            )

    def at(self, day, hour):
        return datetime.combine(day, datetime.min.time()) + timedelta(hours=hour)

    def message(self, when, sender, recipients, incident=None, size=None, attachments=0):
        self.add(
            "email",
            when,
            sender,
            sender["pc"],
            ";".join(recipients),
            "",
            "",
            f"{sender['name'].replace(' ', '.')}@{DOMAIN}",
            size or self.random.randint(2000, 40000),
            attachments,
            "invented text",
            incident=incident,
        )

    def address(self, person):
        return f"{person['name'].replace(' ', '.')}@{DOMAIN}"

    def ordinary_day(self, day, p):
        r = self.random
        if day.weekday() >= 5 and r.random() > 0.05:
            return
        begin = p["start"] + r.uniform(-0.4, 0.4)
        finish = begin + r.uniform(8, 9.5)
        self.add("logon", self.at(day, begin), p, p["pc"], "Logon")
        for _ in range(r.randint(max(1, p["web"] - 2), p["web"] + 2)):
            site = r.choice(p["sites"]) if r.random() < 0.9 else r.choice(COMMON)
            self.add(
                "http",
                self.at(day, r.uniform(begin, finish)),
                p,
                p["pc"],
                f"http://{site}/page{r.randint(1, 50)}",
                "invented text",
            )
        colleagues = [q for q in self.people if q["team"] == p["team"] and q is not p]
        for _ in range(r.randint(max(0, p["mail"] - 2), p["mail"] + 1)):
            to = [self.address(q) for q in r.sample(colleagues, r.randint(1, 3))]
            if r.random() < 0.1:
                to.append(f"contact{r.randint(1, 9)}@partner.example")
            self.message(self.at(day, r.uniform(begin, finish)), p, to)
        if p["usb"] and r.random() < 0.15:
            t = r.uniform(begin, finish - 1)
            self.add("device", self.at(day, t), p, p["pc"], "Connect")
            for k in range(r.randint(1, 3)):
                self.add(
                    "file",
                    self.at(day, t + 0.1 + k * 0.05),
                    p,
                    p["pc"],
                    f"report{r.randint(1, 99)}.doc",
                    "invented text",
                )
            self.add("device", self.at(day, t + 0.5), p, p["pc"], "Disconnect")
        self.add("logon", self.at(day, finish), p, p["pc"], "Logoff")

    def theft(self, n, p, first, last):
        """Scenario 1 shape: after-hours logons, USB copies, uploads to a leak site."""
        for day in days(first, last):
            t = self.random.uniform(22, 23.5)
            self.add("logon", self.at(day, t), p, p["pc"], "Logon", incident=n)
            self.add("device", self.at(day, t + 0.1), p, p["pc"], "Connect", incident=n)
            for k in range(self.random.randint(6, 12)):
                self.add(
                    "file",
                    self.at(day, t + 0.15 + k * 0.01),
                    p,
                    p["pc"],
                    f"design{k}.pdf",
                    "invented text",
                    incident=n,
                )
            self.add(
                "http",
                self.at(day, t + 0.3),
                p,
                p["pc"],
                f"http://{LEAK}/upload",
                "invented text",
                incident=n,
            )
            self.add("device", self.at(day, t + 0.4), p, p["pc"], "Disconnect", incident=n)
            self.add("logon", self.at(day, t + 0.45), p, p["pc"], "Logoff", incident=n)

    def job_hunt(self, n, p, first, last):
        """Scenario 2 shape: weeks of job-site visits, then copying to USB in the final week."""
        final = date.fromisoformat(last) - timedelta(days=6)
        for day in days(first, last):
            if day.weekday() >= 5:
                continue
            for _ in range(self.random.randint(3, 8)):
                self.add(
                    "http",
                    self.at(day, self.random.uniform(10, 16)),
                    p,
                    p["pc"],
                    f"http://{self.random.choice(JOBS)}/apply",
                    "invented text",
                    incident=n,
                )
            if day >= final:
                self.add("device", self.at(day, 12), p, p["pc"], "Connect", incident=n)
                for k in range(self.random.randint(8, 15)):
                    self.add(
                        "file",
                        self.at(day, 12.1 + k * 0.01),
                        p,
                        p["pc"],
                        f"client{k}.xls",
                        "invented text",
                        incident=n,
                    )
                self.add("device", self.at(day, 12.5), p, p["pc"], "Disconnect", incident=n)

    def takeover(self, n, p, victim, first, _last):
        """Scenario 3 shape: keylogger to USB, planted on the victim's computer, then the
        attacker logs on as the victim after hours and sends alarming mass email."""
        one, two, three = days(first, _last)
        self.add(
            "http",
            self.at(one, 13),
            p,
            p["pc"],
            f"http://{KEYLOGGER}/download",
            "invented text",
            incident=n,
        )
        self.add("device", self.at(one, 13.2), p, p["pc"], "Connect", incident=n)
        self.add("file", self.at(one, 13.25), p, p["pc"], "keylog.exe", "invented", incident=n)
        self.add("device", self.at(one, 13.3), p, p["pc"], "Disconnect", incident=n)
        self.add("logon", self.at(two, 18.5), p, victim["pc"], "Logon", incident=n)
        self.add("device", self.at(two, 18.6), p, victim["pc"], "Connect", incident=n)
        self.add("device", self.at(two, 18.7), p, victim["pc"], "Disconnect", incident=n)
        self.add("logon", self.at(two, 18.8), p, victim["pc"], "Logoff", incident=n)
        self.add("logon", self.at(three, 21), victim, victim["pc"], "Logon", incident=n)
        everyone = [self.address(q) for q in self.people if q is not victim]
        for k in range(3):
            self.message(
                self.at(three, 21.1 + k * 0.05),
                victim,
                everyone,
                incident=n,
                size=60000,
                attachments=1,
            )
        self.add("logon", self.at(three, 21.4), victim, victim["pc"], "Logoff", incident=n)

    def build(self):
        incidents = []
        busy = defaultdict(set)
        for n, (scenario, actor, victim, first, last) in enumerate(INCIDENTS):
            p = self.people[actor]
            v = self.people[victim] if victim is not None else None
            if scenario == "1":
                self.theft(n, p, first, last)
            elif scenario == "2":
                self.job_hunt(n, p, first, last)
            else:
                self.takeover(n, p, v, first, last)
            if scenario == "1":
                busy[actor] |= set(days(first, last))
            incidents.append(
                {
                    "id": f"demo-{n + 1}",
                    "scenario": scenario,
                    "actor": p["id"],
                    "victim": v["id"] if v else None,
                    "start": first,
                    "end": last,
                    "records": self.labels[n],
                }
            )
        for day in days(START, END - timedelta(days=1)):
            for i, p in enumerate(self.people):
                if day not in busy[i]:
                    self.ordinary_day(day, p)
        return incidents


def generate(root=DEMO_ROOT, seed=7):
    """Write the invented project root; returns the number of events."""
    root = Path(root)
    world = World(seed)
    incidents = world.build()
    total = 0
    for shard, lo, hi in (("recovery-v3", START, SPLIT), ("workload-v4", SPLIT, END)):
        folder = root / "data/raw" / shard
        (folder / "LDAP").mkdir(parents=True, exist_ok=True)
        for source, header in HEADERS.items():
            rows = sorted(
                (r for r in world.events[source] if lo <= r[1].date() < hi),
                key=lambda r: (r[1], r[0]),
            )
            total += len(rows)
            with (folder / (source + ".csv")).open("w", newline="") as f:
                out = csv.writer(f)
                out.writerow(header)
                for r in rows:
                    out.writerow([r[0], r[1].strftime("%m/%d/%Y %H:%M:%S"), *r[2:]])
        month = date(lo.year, lo.month, 1)
        while month < hi:
            with (folder / "LDAP" / f"{month:%Y-%m}.csv").open("w", newline="") as f:
                out = csv.writer(f)
                out.writerow(
                    [
                        "employee_name",
                        "user_id",
                        "email",
                        "role",
                        "business_unit",
                        "functional_unit",
                        "department",
                        "team",
                        "supervisor",
                    ]
                )
                for p in world.people:
                    out.writerow(
                        [
                            p["name"],
                            p["id"],
                            world.address(p),
                            p["role"],
                            1,
                            "1 - Operations",
                            "1 - " + p["team"],
                            "1 - " + p["team"],
                            p["supervisor"],
                        ]
                    )
            month = (month + timedelta(days=32)).replace(day=1)
    config = json.loads((APP / "config.json").read_text())
    config["events"] = total
    config["frozen_experiment_sha256"] = "demo"
    config["demo"] = "Invented data and a demo model; not the evaluated SentinelID result"
    (root / "config.json").write_text(json.dumps(config, indent=2))
    (root / "configs").mkdir(exist_ok=True)
    (root / "configs/adaptive.json").write_text((APP / "configs/adaptive.json").read_text())
    (root / "answers.json").write_text(json.dumps({"incidents": incidents}, indent=2))
    return total


def labelled(root):
    incidents = json.loads((Path(root) / "answers.json").read_text())["incidents"]
    return {(r["timestamp"][:10], r["account"]) for i in incidents for r in i["records"]}


def fit(root):
    """Train the demo model on June 8 - October 14 rows; run with SENTINELID_ROOT=root."""
    from .features import WorkloadStream, original_records
    from .pipeline import matrix

    config = json.loads((Path(root) / "config.json").read_text())
    stream, rows = WorkloadStream(config), []
    for e in original_records(config):
        previous = stream.day
        out = stream.push(e)
        if stream.day != previous:
            rows += out
    rows += stream.finish(datetime.fromisoformat(config["end"]))
    rows = [r for r in rows if FIT_START <= r["day"] < FIT_END and r["common_eligible"]]
    x, names = matrix(rows, config["deployment"]["representation"])
    positive = labelled(root)
    y = np.asarray([(r["day"], r["identity_id"]) in positive for r in rows], dtype=int)
    model = RandomForestClassifier(
        n_estimators=100,
        max_depth=8,
        min_samples_leaf=3,
        class_weight="balanced_subsample",
        random_state=42,
        n_jobs=-1,
    ).fit(x, y)
    # Parallel prediction sums tree votes in thread order, which changes the last bit of a
    # score between runs; the deployed model predicts single-threaded, and so does this one.
    model.n_jobs = 1
    gate = 0.5
    bundle = {
        "representation": config["deployment"]["representation"],
        "kind": "rf",
        "names": names,
        "model": model,
        "fit_gate": gate,
        "trees": 100,
        "samples": len(rows),
        "seed": 42,
        "fit_rows": len(rows),
        "score_semantics": "Demo model on invented data; probability of a planted-incident day",
        "gates": {"fit": gate, "workload": gate, "calibration_options": []},
        "labels_used": True,
    }
    path = Path(root) / config["deployment"]["model"]
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, path)
    config["deployment"]["sha256"] = digest(path)
    (Path(root) / "config.json").write_text(json.dumps(config, indent=2))
    return {"rows": len(rows), "positive_rows": int(y.sum())}


def summarize(root):
    """Score the demo replay against its own answer key and write the dashboard results."""
    import sqlite3

    root = Path(root)
    incidents = json.loads((root / "answers.json").read_text())["incidents"]
    records = {r["event_id"]: (i, r) for i in incidents for r in i["records"]}
    with sqlite3.connect(root / "data/operations.sqlite") as db:
        cases = [json.loads(p) for (p,) in db.execute("SELECT payload FROM cases")]
    current = timely = 0
    reached = set()
    for c in cases:
        triggers = set(c.get("trigger_ids", []))
        evidence = {p["event_id"] for p in c.get("evidence_pointers", [])} | triggers
        current += bool(triggers & records.keys())
        decided = datetime.fromisoformat(c["decision_time"])
        for eid in evidence & records.keys():
            i, r = records[eid]
            if (decided - datetime.fromisoformat(r["timestamp"])).total_seconds() <= 72 * 3600:
                reached.add(i["id"])
    november = [i for i in incidents if i["start"] >= "2010-11-01"]
    timely = sum(i["id"] in reached for i in november)
    config = json.loads((root / "config.json").read_text())
    results = {
        "selection": config["deployment"],
        "validation": {
            "frontier": [
                {
                    "system": "DEMO_RF/fit/max_cooldown/1",
                    "capacity": 1,
                    "reviews": len(cases),
                    "current_positive_reviews": current,
                    "context_positive_reviews": current,
                    "timely_incidents": timely,
                    "incidents_available": len(november),
                    "official_incidents": timely,
                    "selected": True,
                }
            ]
        },
        "verdict": {
            "verdict": "demo only - invented data, not an evaluation",
            "scope": "Invented 24-person organisation; demo model trained on its June-October",
            "selected": "DEMO_RF/fit/max_cooldown/1",
            "selected_reviews": len(cases),
            "selected_timely": timely,
        },
    }
    (root / "results.json").write_text(json.dumps(results, indent=2))
    return results["validation"]["frontier"][0]


def run(port=8767, fresh=False, serve=True):
    """Generate, fit, replay and serve the demo; each stage runs against the demo root."""
    root = DEMO_ROOT
    if fresh or not (root / "answers.json").exists():
        for p in (root / "data/operations.sqlite", root / "data/operations.lock"):
            p.unlink(missing_ok=True)
        print("Generating invented organisation:", generate(root), "events", flush=True)
    env = {**os.environ, "SENTINELID_ROOT": str(root)}

    def stage(*args):
        subprocess.run([sys.executable, "-m", *args], env=env, check=True, cwd=APP)

    if not (root / "data/model.joblib").exists():
        stage("sentinelid.demo", "fit")
    if not (root / "data/operations.sqlite").exists():
        stage("sentinelid", "replay")
    stage("sentinelid.demo", "summarize")
    if serve:
        print(f"Dashboard: http://127.0.0.1:{port}/  (Ctrl+C to stop)", flush=True)
        stage("sentinelid", "serve", "--port", str(port))


if __name__ == "__main__":
    target = Path(os.environ.get("SENTINELID_ROOT", DEMO_ROOT))
    if sys.argv[1:] == ["fit"]:
        print("Demo model:", json.dumps(fit(target)), flush=True)
    elif sys.argv[1:] == ["summarize"]:
        print("Demo result:", json.dumps(summarize(target)), flush=True)
    else:
        raise SystemExit("usage: python -m sentinelid.demo fit|summarize")
