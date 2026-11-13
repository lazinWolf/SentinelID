"""Activity ledger: single-pass aggregation, causal rarity, computer ownership, references."""

import csv
import math
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from sentinelid.ledger import SERIES, State, build, day_of, features, is_job, names

START = date(2010, 5, 1)


def write(root, source, header, rows):
    folder = root / "data/raw/recovery-v3"
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / (source + ".csv")).open("w", newline="") as f:
        csv.writer(f).writerows([header, *rows])


def stamp(day, hour=9):
    return f"{day.month:02d}/{day.day:02d}/{day.year} {hour:02d}:00:00"


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.addCleanup(self.directory.cleanup)

    def fixture(self, days=50):
        http, email, logon = [], [], []
        n = 0
        for k in range(days):
            day = START + timedelta(days=k)
            for user in ("a", "b", "c", "d"):
                n += 1
                http.append([f"h{n}", stamp(day), user, "pc-" + user, "http://news.com/x", ""])
                logon.append([f"l{n}", stamp(day, 8), user, "pc-" + user, "Logon"])
            email.append(
                [f"e{k}", stamp(day), "a", "pc-a", "x@dtaa.com", "", "", "a@dtaa.com", 1, 0, ""]
            )
        return http, email, logon

    def write(self, http, email, logon):
        write(self.root, "http", ["id", "date", "user", "pc", "url", "content"], http)
        write(
            self.root,
            "email",
            [
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
            email,
        )
        write(self.root, "logon", ["id", "date", "user", "pc", "activity"], logon)

    def compute(self, keys, days=50):
        manifest = build(
            "2010-05-01", (START + timedelta(days=days)).isoformat(), self.root / "l", self.root
        )
        return manifest, features(self.root / "l", keys)

    def test_day_formats(self):
        self.assertEqual(day_of("07/04/2010 13:00:00"), "2010-07-04")
        self.assertEqual(day_of("2010-07-04 13:00:00"), "2010-07-04")
        self.assertEqual(day_of("2010-07-04T13:00:00"), "2010-07-04")
        self.assertTrue(is_job("www.job-hunt.org") and not is_job("news.com"))

    def test_rare_destination_flags_only_the_first_visitors_day(self):
        http, email, logon = self.fixture()
        day = START + timedelta(days=45)
        http.append(["x1", stamp(day, 10), "a", "pc-a", "http://refog.com/page", ""])
        http.sort(key=lambda r: r[1][6:10] + r[1][:2] + r[1][3:5])
        self.write(http, email, logon)
        keys = [((day + timedelta(days=i)).isoformat(), "a") for i in (-1, 0, 1)]
        _, x = self.compute(keys)
        col = names().index("domain_rarity")
        calm, flagged, after = x[:, col]
        self.assertGreater(flagged, calm)
        self.assertAlmostEqual(flagged, math.log(5))  # never seen among 4 known identities
        self.assertEqual(after, 0.0)  # the feature scores only that day's destinations

    def test_references_exclude_the_last_seven_days(self):
        http, email, logon = self.fixture()
        day = START + timedelta(days=45)
        # A spike inside the lag must not shift the reference of a later day.
        for k in range(3):
            http.append(
                [
                    f"s{k}",
                    stamp(day - timedelta(days=3), 10 + k),
                    "a",
                    "pc-a",
                    "http://refog.com/p",
                    "",
                ]
            )
        http.sort(key=lambda r: r[1][6:10] + r[1][:2] + r[1][3:5])
        self.write(http, email, logon)
        keys = [((day - timedelta(days=3)).isoformat(), "a"), (day.isoformat(), "a")]
        _, x = self.compute(keys)
        col = names().index("percentile:ledger_rare_visits")
        spike_day, later = x[:, col]
        self.assertGreater(spike_day, 0.4)  # rare burst against an all-zero baseline
        self.assertEqual(later, 0.0)  # the burst is still inside the lag, not today's reference

    def test_foreign_computer_logons_need_an_established_owner(self):
        http, email, logon = self.fixture()
        day = START + timedelta(days=46)
        logon.append(["f1", stamp(day, 20), "b", "pc-a", "Logon"])
        logon.sort(key=lambda r: r[1][6:10] + r[1][:2] + r[1][3:5])
        self.write(http, email, logon)
        keys = [((day - timedelta(days=1)).isoformat(), "b"), (day.isoformat(), "b")]
        _, x = self.compute(keys)
        col = names().index("percentile:ledger_foreign_logons")
        self.assertEqual(x[0, col], 0.0)
        self.assertGreater(x[1, col], 0.4)
        # Early in the period nobody owns pc-a yet, so the same logon would not count.
        _, early = self.compute([((START + timedelta(days=3)).isoformat(), "b")])
        self.assertEqual(early[0, col], 0.0)

    def test_exposure_links_a_visitor_to_the_computer_owner(self):
        http, email, logon = self.fixture()
        day = START + timedelta(days=45)
        logon.append(["v1", stamp(day, 20), "b", "pc-a", "Logon"])
        logon.sort(key=lambda r: r[1][6:10] + r[1][:2] + r[1][3:5])
        self.write(http, email, logon)
        keys = [((day + timedelta(days=i)).isoformat(), "a") for i in (-1, 0, 2, 3)]
        keys.append((day.isoformat(), "b"))
        _, x = self.compute(keys)
        col = names().index("percentile:ledger_exposure")
        before, same_day, two_later, three_later, visitor = x[:, col]
        self.assertEqual(before, 0.0)  # a later visit never reaches back
        self.assertGreater(same_day, 0.4)
        self.assertGreater(two_later, 0.4)  # still inside the three days to date
        self.assertEqual(three_later, 0.0)
        self.assertEqual(visitor, 0.0)  # the visitor is not the one exposed

    def test_exposure_is_kept_on_days_the_owner_is_silent(self):
        state = State()
        state.logons["pc-a"]["a"] = 20
        state.owner["pc-a"] = "a"
        column = SERIES.index("exposure")
        for ordinal, logon in ((10, {"b": {"pc-a": 2}}), (11, {}), (12, {}), (13, {})):
            exposed = state.visited(ordinal, logon)
            series = {u: state.today(u, ordinal, None, None, logon.get(u)) for u in exposed}
            state.update(ordinal, {}, logon, {u: v for u, (v, _) in series.items()})
        history = state.values["a"]
        self.assertEqual([history[o][column] for o in (10, 11, 12)], [2, 2, 2])
        self.assertNotIn(13, history)  # outside the three days, nothing to record

    def test_mass_email_breadth(self):
        http, email, logon = self.fixture()
        day = START + timedelta(days=47)
        email.append(
            [
                "m",
                stamp(day, 12),
                "a",
                "pc-a",
                ";".join(f"u{i}@dtaa.com" for i in range(40)),
                "",
                "",
                "a@dtaa.com",
                1,
                0,
                "",
            ]
        )
        email.sort(key=lambda r: r[1][6:10] + r[1][:2] + r[1][3:5])
        self.write(http, email, logon)
        _, x = self.compute([(day.isoformat(), "a")])
        self.assertGreater(x[0, names().index("magnitude:ledger_max_recipients")], 2.0)

    def test_source_day_inversion_is_rejected(self):
        http, email, logon = self.fixture(days=5)
        http.reverse()
        self.write(http, email, logon)
        with self.assertRaises(ValueError):
            build("2010-05-01", "2010-06-01", self.root / "l", self.root)

    def test_manifest_counts_identity_days(self):
        http, email, logon = self.fixture(days=5)
        self.write(http, email, logon)
        manifest = build("2010-05-01", "2010-06-01", self.root / "l", self.root)
        self.assertEqual(manifest["identity_days"], {"http": 20, "email": 5, "logon": 20})
        self.assertTrue(np.isfinite(features(self.root / "l", [("2010-05-03", "a")])).all())
