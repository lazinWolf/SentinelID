"""Acquisition safety checks without external services or benchmark downloads."""

import hashlib
import io
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sentinelid.setup import download, matches, select_csv


class Response(io.BytesIO):
    def __init__(self, body, status, headers):
        super().__init__(body)
        self.status = status
        self.headers = headers


class SetupTests(unittest.TestCase):
    def test_resume_and_verified_install(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "artifact"
            target.with_name("artifact.part").write_bytes(b"ab")
            checksum = hashlib.sha256(b"abcdef").hexdigest()
            with patch(
                "sentinelid.setup.urlopen",
                return_value=Response(
                    b"cdef", 206, {"Content-Range": "bytes 2-5/6", "Content-Length": "4"}
                ),
            ) as opener:
                download("https://example.org/file", target, checksum, 6)
                self.assertEqual(opener.call_args.args[0].get_header("Range"), "bytes=2-5")
            self.assertEqual(target.read_bytes(), b"abcdef")
            with patch("sentinelid.setup.urlopen") as opener:
                download("https://example.org/file", target, checksum, 6)
                opener.assert_not_called()

    def test_ignored_range_is_never_installed(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "artifact"
            with patch("sentinelid.setup.urlopen", return_value=Response(b"abcdef", 200, {})):
                with self.assertRaises(ValueError):
                    download("https://example.org/file", target, "invalid", 3, (2, 4), 6)
            self.assertFalse(target.exists())

    def test_corrupt_download_and_existing_file_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "artifact"
            with patch("sentinelid.setup.urlopen", return_value=Response(b"bad", 200, {})):
                with self.assertRaises(ValueError):
                    download("https://example.org/file", target, "invalid", 3)
            self.assertFalse(target.exists())
            target.write_bytes(b"old")
            with self.assertRaises(ValueError):
                matches(target, "invalid", 3)
            self.assertEqual(target.read_bytes(), b"old")

    def test_selection_matches_frozen_serialization_and_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            part = Path(directory) / "range"
            target = Path(directory) / "selected.csv"
            part.write_bytes(
                b"partial\nid,04/30/2010 12:00:00,u\nid,05/01/2010 12:00:00,u\nid,05/02/2010 12:00:00,u\npartial"
            )
            expected = b"id,date,user\r\nid,05/01/2010 12:00:00,u\r\n"
            descriptor = {
                "header": "id,date,user",
                "rows": 1,
                "selected_bytes": len(expected),
                "selected_sha256": hashlib.sha256(expected).hexdigest(),
            }
            select_csv(part, target, descriptor, datetime(2010, 5, 1), datetime(2010, 5, 2))
            self.assertEqual(target.read_bytes(), expected)
            descriptor["rows"] = 2
            with self.assertRaises(ValueError):
                select_csv(part, target, descriptor, datetime(2010, 5, 1), datetime(2010, 5, 2))
            self.assertEqual(target.read_bytes(), expected)
