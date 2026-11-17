"""Plain-language case signals, the dashboard findings file and the demo story."""

import json
import unittest
from pathlib import Path

from sentinelid import demo
from sentinelid.signals import signals

ROOT = Path(__file__).resolve().parents[1]


def observation(**features):
    """One identity-day: every change is zero unless given; references default to a usual 2."""
    names = [
        f"{c}_change_{n}"
        for c in ("usb", "copy", "logon", "after_hours", "http", "external_email")
        for n in (1, 3, 7)
    ]
    base = dict.fromkeys(names, 0.0)
    base.update(features.pop("changes", {}))
    details = {k: {"target": 2, "reference_mean": 2.0} for k in names}
    details.update(features.pop("details", {}))
    return {
        "features": {**base, **features},
        "percentiles": {k: 0.5 if base[k] else 0.0 for k in names},
        "reference": {"details": details},
    }


class SignalTests(unittest.TestCase):
    def test_quiet_day_has_no_signals(self):
        self.assertEqual(signals(observation()), [])

    def test_first_use_is_named_with_its_technique(self):
        o = observation(
            changes={"usb_change_1": 4.0},
            details={"usb_change_1": {"target": 6, "reference_mean": 0}},
        )
        [s] = signals(o)
        self.assertEqual(s["title"], "First USB use in the reference period")
        self.assertEqual(s["technique"], "T1052.001")
        self.assertEqual(s["strength"], "strong")
        self.assertIn("6 connections today", s["detail"])

    def test_small_changes_and_low_percentiles_are_ignored(self):
        o = observation(changes={"http_change_1": 0.5})  # log1p(0.5) < notable
        self.assertEqual(signals(o), [])
        o = observation(changes={"http_change_1": 5.0})
        o["percentiles"]["http_change_1"] = 0.1  # ordinary for this identity
        self.assertEqual(signals(o), [])

    def test_one_signal_per_channel_and_strongest_first(self):
        o = observation(
            changes={"copy_change_1": 1.0, "copy_change_7": 9.0, "logon_change_1": 1.0},
            new_computer_share=0.5,
        )
        found = signals(o)
        keys = [s["key"] for s in found]
        self.assertEqual(keys.count("copy_change_7") + keys.count("copy_change_1"), 1)
        self.assertEqual(keys[0], "copy_change_7")
        self.assertIn("new_computer_share", keys)

    def test_signals_never_read_labels(self):
        o = observation(changes={"usb_change_1": 4.0})
        o["label"] = 1
        o["incident_id"] = "secret"
        self.assertNotIn("secret", json.dumps(signals(o)))


class FindingsTests(unittest.TestCase):
    def test_committed_findings_answer_the_four_identity_questions(self):
        data = json.loads((ROOT / "dashboard/findings.json").read_text())
        self.assertEqual(
            [q["id"] for q in data["questions"]], ["own", "labels", "stolen", "methods"]
        )
        for q in data["questions"]:
            self.assertTrue(q["bars"] and q["sources"])
            for bar in q["bars"]:
                self.assertLessEqual(bar["value"], bar["total"])
            for source in q["sources"]:
                self.assertTrue((ROOT / source).exists(), source)
        stolen = next(q for q in data["questions"] if q["id"] == "stolen")
        hijacked = next(b for b in stolen["bars"] if b["label"].startswith("Hijacked"))
        self.assertEqual(hijacked["value"], 0)


class DemoStoryTests(unittest.TestCase):
    def test_story_names_the_blind_spot_when_the_hijacked_account_is_missed(self):
        result = {
            "reviews": 8,
            "current_positive_reviews": 3,
            "incidents": [
                {"scenario": "1", "accounts": [{"identity": "A", "role": "own", "reached": True}]},
                {
                    "scenario": "3",
                    "accounts": [
                        {"identity": "B", "role": "own", "reached": True},
                        {"identity": "C", "role": "hijacked", "reached": False},
                    ],
                },
            ],
        }
        text = demo.tell(result, 8767)
        self.assertIn("B (attacker's own account) reached within 72 h", text)
        self.assertIn("C (hijacked account) not reached", text)
        self.assertIn("blind spot", text)
        self.assertIn("http://127.0.0.1:8767/", text)


if __name__ == "__main__":
    unittest.main()
