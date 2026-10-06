"""Reproduce the deployed artifacts without changing experiments or application state."""

import csv
import fcntl
import hashlib
import json
import os
import time
from datetime import datetime
from http.client import IncompleteRead
from urllib.request import Request, urlopen

from .ingestion import ROOT, parse_date


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def matches(path, checksum, size):
    if not path.exists():
        return False
    if path.stat().st_size != size or digest(path) != checksum:
        raise ValueError(
            f"Existing artifact differs from the manifest: {path}; preserve or move it before retrying"
        )
    return True


def download(url, target, checksum, size, span=None, total=None):
    """Resume a bounded transfer; install only after length and checksum verification."""
    if matches(target, checksum, size):
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    for attempt in range(5):
        offset = partial.stat().st_size if partial.exists() else 0
        if offset > size:
            raise ValueError(f"Oversized partial download: {partial}")
        if offset == size:
            break
        start = (span[0] if span else 0) + offset
        end = span[1] if span else size - 1
        ranged = span is not None or offset > 0
        headers = {"Accept-Encoding": "identity", "User-Agent": "SentinelID-setup/1"}
        request_url = url
        if ranged:
            headers["Range"] = f"bytes={start}-{end}"
            request_url += ("&" if "?" in url else "?") + f"sentinel-range={start}-{end}"
        try:
            with urlopen(Request(request_url, headers=headers), timeout=60) as response:
                expected_status = 206 if ranged else 200
                if response.status != expected_status:
                    raise ValueError(f"Server ignored the requested transfer: {url}")
                if (
                    ranged
                    and response.headers.get("Content-Range")
                    != f"bytes {start}-{end}/{total if span else size}"
                ):
                    raise ValueError(f"Unexpected Content-Range: {url}")
                length = response.headers.get("Content-Length")
                if length is not None and int(length) != size - offset:
                    raise ValueError(f"Unexpected Content-Length: {url}")
                with partial.open("ab") as out:
                    while chunk := response.read(min(4 * 1024 * 1024, size - offset + 1)):
                        if offset + len(chunk) > size:
                            raise ValueError(f"Response exceeds requested bytes: {url}")
                        out.write(chunk)
                        offset += len(chunk)
                if offset != size:
                    raise OSError(f"Incomplete download: {url}")
            break
        except (OSError, IncompleteRead):
            if attempt == 4:
                raise
            time.sleep(min(attempt + 1, 3))
    if digest(partial) != checksum:
        raise ValueError(
            f"Download checksum mismatch: {partial}; move this partial file before retrying"
        )
    os.replace(partial, target)


def select_csv(part, target, descriptor, start, end):
    """Match the frozen CSV serialization and reject incomplete date boundaries."""
    temporary = target.with_name(target.name + ".tmp")
    before = after = False
    previous = None
    count = 0
    header = next(csv.reader([descriptor["header"]]))
    try:
        with part.open("rb") as raw, temporary.open("w", encoding="utf-8", newline="") as out:
            raw.readline()  # The range starts within a record.
            writer = csv.writer(out)
            writer.writerow(header)
            while line := raw.readline():
                if not line.endswith(b"\n"):
                    break
                row = next(csv.reader([line.decode("utf-8-sig")]))
                if len(row) != len(header):
                    raise ValueError("Unexpected CSV schema")
                stamp = parse_date(row[1])
                if previous is not None and stamp < previous:
                    raise ValueError("Source dates are out of order")
                previous = stamp
                before |= stamp < start
                after |= stamp >= end
                if start <= stamp < end:
                    writer.writerow(row)
                    count += 1
        if not before or not after or count != descriptor["rows"]:
            raise ValueError(f"Incomplete selection boundaries or row count: {target}")
        if not matches(temporary, descriptor["selected_sha256"], descriptor["selected_bytes"]):
            raise ValueError(f"Missing prepared CSV: {temporary}")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def setup(root=ROOT, sources=None, model_only=False, accept_data_license=False):
    manifest = json.loads((root / "setup-manifest.json").read_text())
    config = json.loads((root / "config.json").read_text())
    if manifest["model_sha256"] != config["deployment"]["sha256"]:
        raise ValueError("Setup manifest and deployment model disagree")
    if (
        manifest["prefix"]["start"] != config["start"]
        or manifest["prefix"]["end_exclusive"] != config["extension_start"]
        or manifest["extension"]["prefix_end"] != config["extension_start"]
        or manifest["extension"]["end"] != config["end"]
    ):
        raise ValueError("Setup manifest and configured date boundaries disagree")
    if not model_only and not accept_data_license:
        raise ValueError(
            "Review the dataset terms at "
            + manifest["license_url"]
            + " then run setup --accept-data-license if you agree"
        )
    data = root / "data"
    data.mkdir(exist_ok=True)
    with (data / ".setup.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("Another setup process is active") from error
        print("Verifying/downloading the pinned deployment model", flush=True)
        download(
            manifest["model_url"],
            root / config["deployment"]["model"],
            manifest["model_sha256"],
            manifest["model_bytes"],
        )
        if model_only:
            return
        selected = set(sources or config["sources"])
        for section, shard in [("prefix", "recovery-v3"), ("extension", "workload-v4")]:
            spec = manifest[section]
            start = datetime.fromisoformat(
                spec["start"] if section == "prefix" else spec["prefix_end"]
            )
            end = datetime.fromisoformat(
                spec["end_exclusive"] if section == "prefix" else spec["end"]
            )
            directory = data / "raw" / shard
            directory.mkdir(parents=True, exist_ok=True)
            for descriptor in spec.get("sources", spec.get("extension_sources", [])):
                source = descriptor["source"]
                if source not in selected:
                    continue
                target = directory / (source + ".csv")
                print(f"{shard}/{source}: verify/download/prepare", flush=True)
                if matches(target, descriptor["selected_sha256"], descriptor["selected_bytes"]):
                    continue
                span = descriptor["byte_range_inclusive"]
                part = data / ".downloads" / (shard + "-" + source)
                download(
                    descriptor["url"],
                    part,
                    descriptor["range_sha256"],
                    span[1] - span[0] + 1,
                    span,
                    descriptor["mirror_full_size"],
                )
                select_csv(part, target, descriptor, start, end)
                part.unlink()
            for item in spec["monthly_metadata"]:
                target = directory / "LDAP" / (item["month"] + ".csv")
                download(
                    manifest["dataset_base"] + "/LDAP/" + target.name,
                    target,
                    item["sha256"],
                    item["bytes"],
                )
        provenance = data / "provenance.json"
        if not provenance.exists():
            temporary = provenance.with_suffix(".tmp")
            temporary.write_text(
                json.dumps({key: manifest[key] for key in ("prefix", "extension")}, indent=2) + "\n"
            )
            os.replace(temporary, provenance)
        print(
            "Setup complete. Full-source setup enables: sentinelid verify --sources; sentinelid replay; sentinelid serve",
            flush=True,
        )
