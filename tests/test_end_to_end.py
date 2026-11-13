"""End to end on the invented demo organisation: real ingestion, features, model, queue, store.

The only CI test of the full pipeline. It needs no CERT data; it takes about a minute.
"""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from sentinelid.demo import generate
from sentinelid.ingestion import APP, evidence, records


def replay(root, *args):
    env = {**os.environ, "SENTINELID_ROOT": str(root)}
    subprocess.run(
        [sys.executable, "-m", "sentinelid", "replay", *args],
        env=env,
        check=True,
        cwd=APP,
        capture_output=True,
    )


class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.directory.name)
        generate(cls.root)
        env = {**os.environ, "SENTINELID_ROOT": str(cls.root)}
        subprocess.run(
            [sys.executable, "-m", "sentinelid.demo", "fit"],
            env=env,
            check=True,
            cwd=APP,
            capture_output=True,
        )
        replay(cls.root)  # uninterrupted run
        replay(cls.root, "--new", "--events", "20000")  # interrupted run ...
        replay(cls.root)  # ... resumed from its checkpoint
        with sqlite3.connect(cls.root / "data/operations.sqlite") as db:
            cls.runs = [r for (r,) in db.execute("SELECT id FROM runs ORDER BY rowid")]
            cls.cases = {
                run: [
                    json.loads(p)
                    for (p,) in db.execute(
                        "SELECT payload FROM cases WHERE run=? ORDER BY decision,identity", (run,)
                    )
                ]
                for run in cls.runs
            }
            cls.scores = {
                run: db.execute(
                    "SELECT day,identity,score FROM observations WHERE run=? ORDER BY day,identity",
                    (run,),
                ).fetchall()
                for run in cls.runs
            }
        cls.incidents = json.loads((cls.root / "answers.json").read_text())["incidents"]

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_sources_merge_in_time_order_and_reject_inversions(self):
        shard = self.root / "data/raw/recovery-v3"
        keys = [(r.timestamp, r.event_id) for r in records(shard)]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(
            {k.split(":")[0] for _, k in keys}, {"device", "email", "file", "http", "logon"}
        )
        broken = self.root / "broken"
        (broken / "LDAP").mkdir(parents=True)
        lines = (shard / "logon.csv").read_text().splitlines()
        lines[1], lines[2] = lines[2], lines[1]
        (broken / "logon.csv").write_text("\n".join(lines) + "\n")
        with self.assertRaises(ValueError):
            list(records(broken))

    def test_planted_november_incidents_reach_an_analyst(self):
        cases = self.cases[self.runs[0]]
        shown = {e for c in cases for e in c["evidence_ids"]}
        for incident in self.incidents:
            if incident["start"] < "2010-11-01":
                continue
            ids = {r["event_id"] for r in incident["records"]}
            self.assertTrue(ids & shown, incident["id"])
            if incident["victim"]:
                # As in CERT, the takeover is caught through the attacker's own account.
                accounts = {r["account"] for r in incident["records"] if r["event_id"] in shown}
                self.assertIn(incident["actor"], accounts)

    def test_evidence_resolves_to_the_original_lines(self):
        pointers = [p for c in self.cases[self.runs[0]] for p in c["evidence_pointers"]]
        self.assertTrue(pointers)
        for p in pointers[:200]:
            record = evidence(p)
            self.assertEqual(p["source"] + ":" + record["original"]["id"], p["event_id"])

    def test_interrupted_and_resumed_run_matches_uninterrupted(self):
        first, resumed = self.runs
        self.assertEqual(self.scores[first], self.scores[resumed])
        self.assertEqual(
            [(c["identity_id"], c["decision_time"], c["evidence_ids"]) for c in self.cases[first]],
            [
                (c["identity_id"], c["decision_time"], c["evidence_ids"])
                for c in self.cases[resumed]
            ],
        )


if __name__ == "__main__":
    unittest.main()
