"""Versioned experimental measurements; the deployed feature builder stays frozen."""

import copy
import json
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from .features import PEER
from .pipeline import matrix

CONTRACT = "behavior-experiment-v1"
TEMPORAL = ["usb_persistence_7", "copy_persistence_7", "copy_after_hours_cooccurrence_7"]
DEFINITIONS = {
    "usb_persistence_7": "Share of seven calendar days with 1 <= USB change magnitude < 3, using scoring-day lagged reference",
    "copy_persistence_7": "Share of seven calendar days with 1 <= copy change magnitude < 3, using scoring-day lagged reference",
    "copy_after_hours_cooccurrence_7": "Copy-active calendar days also containing an after-hours logon / copy-active days; daily co-occurrence, not session association",
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True)
class ModuleOutput:
    """Immutable JSON value; each consumer receives its own structured copy."""

    serialized: str

    @classmethod
    def create(cls, value):
        return cls(canonical(value))

    def as_dict(self):
        return json.loads(self.serialized)

    def measurements(self):
        return self.as_dict()["measurements"]


def trailing(row, daily, n=7):
    day = date.fromisoformat(row["day"])
    return [(day - timedelta(days=j)).isoformat() for j in range(n)]


def corrected(row, daily):
    """Correct only the two three-day magnitude inputs and retain horizon provenance."""
    result = copy.deepcopy(row)
    horizons = {str(n): trailing(row, daily, n) for n in (1, 3, 7)}
    for source in ("usb", "copy"):
        target = sum(
            daily.get((row["identity_id"], d), {}).get("counts", {}).get(source, 0)
            for d in horizons["3"]
        )
        name = source + "_change_3"
        if target != row["percentile_reference"][name]["target"]:
            raise ValueError(
                f"Cached percentile target disagrees with consecutive dates: {row['day']}/{row['identity_id']}/{source}"
            )
        detail = result["references"]["28"]["details"][name]
        result["features"]["28"][name] = max(
            0.0, (target - 3 * detail["reference_mean"]) / detail["denominator"]
        )
        detail["target"] = target
    result["schema"] = CONTRACT
    result["target_dates"] = horizons
    return result


def measurements(row, daily):
    dates = trailing(row, daily)
    values = [daily.get((row["identity_id"], d), {"counts": {}, "event_ids": []}) for d in dates]
    reference = row["references"]["28"]
    support = row["eligibility"]["28"]
    base = {
        "schema": "behavior-module-output-v1",
        "identity_id": row["identity_id"],
        "day": row["day"],
        "available_time": row["score_timestamp"],
        "target_dates": dates,
        "reference": {"start": reference["start"], "end_exclusive": reference["end_exclusive"]},
        "status": "ready" if row["common_eligible"] else "unsupported",
        "support": {"eligible": row["common_eligible"], "coverage": support},
    }
    per_day = []
    for day, value in zip(dates, values, strict=True):
        entry = {"day": day, "counts": value["counts"], "magnitudes": {}}
        for kind in ("usb", "copy"):
            ref = reference["details"][kind + "_change_1"]
            # The same frozen scoring-day daily reference is used on all seven targets.
            sd = ref["reference_sd"]
            mean = ref["reference_mean"]
            denominator = max(1.0, sd, mean**0.5)
            entry["magnitudes"][kind] = max(
                0.0, (value["counts"].get(kind, 0) - mean) / denominator
            )
        per_day.append(entry)
    temporal = {
        kind + "_persistence_7": sum(1 <= x["magnitudes"][kind] < 3 for x in per_day) / 7
        for kind in ("usb", "copy")
    }
    copy_days = sum(x["counts"].get("copy", 0) > 0 for x in per_day)
    temporal["copy_after_hours_cooccurrence_7"] = sum(
        x["counts"].get("copy", 0) > 0 and x["counts"].get("after_hours", 0) > 0 for x in per_day
    ) / max(1, copy_days)
    evidence = sorted(
        {
            e
            for x in values
            for e in x["event_ids"]
            if e.split(":", 1)[0] in ("device", "file", "logon")
        }
    )
    t = ModuleOutput.create(
        {
            **base,
            "module": "temporal_v1",
            "version": 1,
            "measurements": temporal,
            "definitions": DEFINITIONS,
            "daily_breakdown": per_day,
            "evidence_ids": evidence,
            "reference_statistics": {
                k: reference["details"][k + "_change_1"] for k in ("usb", "copy")
            },
        }
    )
    peer = row["peer_reference"]
    p = ModuleOutput.create(
        {
            **base,
            "module": "historical_v1",
            "version": 1,
            "status": "ready" if peer["supported"] else "unsupported",
            "measurements": row["peer_features"],
            "definitions": {
                k: "Existing historical leave-one-identity-out peer measurement" for k in PEER
            },
            "reference": peer,
            "support": {
                "supported": peer["supported"],
                "users": peer["users"],
                "active_days": peer["active_days"],
                "self_excluded": peer["self_excluded"],
            },
            "evidence_ids": sorted(
                {
                    e
                    for x in values
                    for e in x["event_ids"]
                    if e.split(":", 1)[0] in ("device", "file", "email")
                }
            ),
            "evidence_semantics": "Target seven-day source context; no claim of exact peer-event attribution",
        }
    )
    return t, p


def vector(row, temporal, peer, temporal_on=False, peer_on=False):
    x, names = matrix([row], "PM")
    values = x[0].tolist()
    if temporal_on:
        names += ["temporal:" + k for k in TEMPORAL]
        values += [temporal.measurements()[k] for k in TEMPORAL]
    if peer_on:
        names += PEER
        values += [peer.measurements()[k] for k in PEER]
    return np.asarray(values, dtype=float), names


def ranking_vector(detector_score, values, names, temporal, peer, temporal_on, peer_on):
    fields = [
        "percentile:usb_change_7",
        "percentile:copy_change_7",
        "magnitude:usb_change_7",
        "magnitude:copy_change_7",
        "magnitude:after_hours_change_1",
        "magnitude:external_email_change_1",
        "timing_novel_share",
    ]
    result = [float(detector_score)] + [float(values[names.index(k)]) for k in fields]
    rank_names = ["detector_score"] + fields
    if temporal_on:
        result += [temporal.measurements()[k] for k in TEMPORAL]
        rank_names += ["temporal:" + k for k in TEMPORAL]
    if peer_on:
        result += [peer.measurements()[k] for k in PEER]
        rank_names += PEER
    return result, rank_names
