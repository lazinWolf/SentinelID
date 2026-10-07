"""Verified local research inputs and atomically installed experiment artifacts."""

import hashlib
import json
import os
import subprocess
import tarfile
from pathlib import Path

from .experiment_features import canonical

ARCHIVE_SHA = "05de10fcec9ed156e8c7a50e2975f031b69c567ffff5031b943403d24069684f"


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    os.replace(temporary, path)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def restore_inputs(root):
    destination = root / "data/experiments/inputs"
    destination.mkdir(parents=True, exist_ok=True)
    manifest = destination / "manifest.json"
    if manifest.exists():
        data = json.loads(manifest.read_text())
        if data["archive_sha256"] != ARCHIVE_SHA:
            raise ValueError("Unexpected research archive identity")
        for name, checksum in data["files"].items():
            if digest(destination / name) != checksum:
                raise ValueError("Cached input changed: " + name)
        if all(
            (destination / (k + "-fit-max_cooldown-1-reviews.json")).exists()
            for k in ("C_IF", "REP_IF", "REP_RF")
        ):
            return destination, data
    archive = root / "archive/research-history.tar.zst"
    if not archive.exists():
        raise FileNotFoundError(
            "Experiments require the local research archive (not included in a public clone); see EXPERIMENTS.md"
        )
    if digest(archive) != ARCHIVE_SHA:
        raise ValueError("Research archive checksum mismatch")
    filenames = [
        "features.sqlite",
        "features-manifest.json",
        "final-models.json",
        "validation-scores.json",
        "validation-truth.json",
    ]
    filenames += [k + "-fit-max_cooldown-1-reviews.json" for k in ("C_IF", "REP_IF", "REP_RF")]
    filenames += [k + ".joblib" for k in ("C_IF", "C_MATCH_IF", "REP_BASE_IF", "REP_IF", "REP_RF")]
    wanted = {"data/processed/workload-v4/" + name: name for name in filenames}
    wanted["data/raw/answers.tar.bz2"] = "answers.tar.bz2"
    for name in (
        "classification-pipeline.md",
        "DETECTION_RECOVERY.md",
        "IF_WORKLOAD_IMPROVEMENT.md",
    ):
        wanted["archive/research/reports/" + name] = "history/" + name
    found = {}
    process = subprocess.Popen(["zstd", "-dc", str(archive)], stdout=subprocess.PIPE)
    try:
        with tarfile.open(fileobj=process.stdout, mode="r|") as stream:
            for member in stream:
                if member.name not in wanted:
                    continue
                target = destination / wanted[member.name]
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(target.name + ".tmp")
                with stream.extractfile(member) as source, temporary.open("wb") as out:
                    while block := source.read(4 * 1024 * 1024):
                        out.write(block)
                checksum = digest(temporary)
                if target.exists():
                    if digest(target) != checksum:
                        raise ValueError("Existing research input differs: " + str(target))
                    temporary.unlink()
                else:
                    os.replace(temporary, target)
                found[wanted[member.name]] = checksum
    finally:
        process.stdout.close()
        code = process.wait()
    if code or set(found) != set(wanted.values()):
        raise ValueError("Research archive is incomplete or extraction failed")
    data = {"archive_sha256": ARCHIVE_SHA, "files": found}
    save_json(manifest, data)
    return destination, data


def isolated_path(root, path):
    base = (root / "data/experiments").resolve()
    target = Path(path).resolve()
    if target == base or base not in target.parents:
        raise ValueError("Experiment output must be inside data/experiments")
    if target == (root / "data/operations.sqlite").resolve():
        raise ValueError("Experiments cannot use the active database")
    return target


def capture_preservation(root):
    path = root / "data/experiments/preservation-before.json"
    if path.exists():
        return
    files = [
        root / name
        for name in (
            "config.json",
            "results.json",
            "data/model.joblib",
            "data/operations.sqlite",
            "data/provenance.json",
            "archive/research-history.tar.zst",
        )
    ]
    files += list((root / "sentinelid").glob("*.py"))
    files += list((root / "dashboard").glob("*"))
    files += list((root / "data/raw").rglob("*.csv"))
    save_json(path, {str(p.relative_to(root)): digest(p) for p in files if p.is_file()})
