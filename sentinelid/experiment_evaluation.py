"""Offline labels and unit-specific retrospective evaluation, never runtime inputs."""

import csv
import io
import tarfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
from sklearn.metrics import average_precision_score, recall_score

from .ingestion import parse_date


def training_truth(archive, start, end):
    events = {}
    with tarfile.open(archive, "r:bz2") as tar:
        incidents = {}
        for row in csv.DictReader(
            io.TextIOWrapper(tar.extractfile("answers/insiders.csv"), encoding="utf-8-sig")
        ):
            if row["dataset"] == "4.2":
                incidents[row["details"]] = row
        for member in tar.getmembers():
            incident = incidents.get(Path(member.name).name)
            if not member.isfile() or not incident:
                continue
            for cells in csv.reader(
                io.TextIOWrapper(tar.extractfile(member), encoding="utf-8-sig")
            ):
                if len(cells) < 5 or cells[0] not in ("device", "logon", "file", "email", "http"):
                    continue
                stamp = parse_date(cells[2]).isoformat()
                if start <= stamp[:10] < end:
                    events[cells[0] + ":" + cells[1]] = {
                        "timestamp": stamp,
                        "day": stamp[:10],
                        "identity": cells[3],
                        "incident": incident["details"],
                    }
    return events


def ranking_diagnostics(keys, scores, y):
    groups = defaultdict(list)
    for i, (day, _) in enumerate(keys):
        groups[day].append(i)
    ranks = []
    totals = Counter()
    for indices in groups.values():
        ordered = sorted(indices, key=lambda i: (-float(scores[i]), keys[i][1]))
        ranks += [j + 1 for j, i in enumerate(ordered) if y[i]]
        for k in (1, 5, 10):
            totals[str(k)] += int(sum(y[i] for i in ordered[:k]))
    return {
        "average_precision": float(average_precision_score(y, scores)) if any(y) else None,
        "positive_day_rank_quantiles": np.quantile(ranks, [0, 0.25, 0.5, 0.75, 1]).tolist()
        if ranks
        else [],
        "forced_daily_top_k_positive_days": dict(totals),
        "semantics": "Eligible day ranking diagnostic; no gate, cooldown or backlog; not operational admissions",
    }


def evaluate(rows, scores, priorities, gate, queue, truth, protocol):
    start = protocol["evaluation_start"]
    end = protocol["evaluation_end"]
    current = {e: t for e, t in truth.items() if start <= t["day"] < end}
    positive = {(t["day"], t["observed_account"]) for t in current.values()}
    keys = [(r["day"], r["identity_id"]) for r in rows]
    y = np.asarray([k in positive for k in keys], dtype=int)
    timely = {}
    delays = []
    current_cases = context_cases = 0
    incidents = {t["incident_id"] for t in current.values()}
    presented = defaultdict(list)
    trigger_admissions = defaultdict(list)
    for case in queue.reviews:
        trigger = set(case["trigger_ids"]) & current.keys()
        retained = set(case["evidence_ids"]) & truth.keys()
        current_cases += bool(trigger)
        context_cases += bool(retained)
        for eid in case["evidence_ids"]:
            presented[eid].append(case["case_id"])
        for eid in case["trigger_ids"]:
            trigger_admissions[eid].append(case["case_id"])
        for eid in sorted(retained, key=lambda e: truth[e]["timestamp"]):
            t = truth[eid]
            hours = (
                datetime.fromisoformat(case["decision_time"])
                - datetime.fromisoformat(t["timestamp"])
            ).total_seconds() / 3600
            if hours < 0:
                raise ValueError("Future evidence in an investigation")
            delays.append(hours)
            if hours <= protocol["timely_hours"] and t["incident_id"] in incidents:
                timely.setdefault(
                    t["incident_id"],
                    {
                        "scenario": t["scenario"],
                        "actor": t["actor"],
                        "event_id": eid,
                        "decision_time": case["decision_time"],
                        "event_delay_hours": hours,
                        "official_onset_delay_hours": (
                            datetime.fromisoformat(case["decision_time"])
                            - datetime.fromisoformat(t["official_start"])
                        ).total_seconds()
                        / 3600,
                    },
                )
    causes = defaultdict(list)
    for d in queue.decisions:
        for day in d.get("days", [d.get("day")]):
            causes[(day, d["identity_id"])].append(d["reason"])
    indexed = {k: (r, float(s)) for k, r, s in zip(keys, rows, scores, strict=True)}
    losses = []
    for eid, t in sorted(current.items()):
        row, score = indexed.get((t["day"], t["observed_account"]), (None, None))
        why = causes[(t["day"], t["observed_account"])]
        reason = (
            "admitted_context"
            if presented[eid]
            else "ineligible"
            if row is None
            else "source_omission"
            if eid not in row["event_ids"]
            else "threshold"
            if score < gate
            else "cooldown"
            if "cooldown" in why
            else "expiry"
            if "expired" in why
            else "budget_pending"
            if "budget_wait" in why
            else "unassigned"
        )
        losses.append(
            {
                "event_id": eid,
                "incident_id": t["incident_id"],
                "scenario": t["scenario"],
                "day": t["day"],
                "detector_score": score,
                "gate": gate,
                "terminal": reason,
                "admission_ids": presented[eid],
                "trigger_admission_ids": trigger_admissions[eid],
            }
        )
    scenario_days = {}
    for scenario in sorted({t["scenario"] for t in current.values()}):
        days = {
            (t["day"], t["observed_account"]) for t in current.values() if t["scenario"] == scenario
        }
        scenario_days[scenario] = {
            "positive_days": len(days),
            "gate_positive_days": int(
                sum(k in days and s >= gate for k, s in zip(keys, scores, strict=True))
            ),
            "timely_incidents": sum(t["scenario"] == scenario for t in timely.values()),
        }
    result = {
        "evaluation_status": "consumed-retrospective",
        "gate": float(gate),
        "eligible_days": len(rows),
        "positive_days": int(y.sum()),
        "detector_average_precision": float(average_precision_score(y, scores)),
        "gate_recall": float(recall_score(y, np.asarray(scores) >= gate)),
        "gate_positive_days": int(sum(y & (np.asarray(scores) >= gate))),
        "gate_candidates": int(sum(np.asarray(scores) >= gate)),
        "pre_ranking_excluded_positive_days": int(y.sum() - sum(y & (np.asarray(scores) >= gate))),
        "candidate_keys": [list(k) for k, s in zip(keys, scores, strict=True) if s >= gate],
        "admission_keys": [[c["identity_id"], c["decision_time"]] for c in queue.reviews],
        "admissions": len(queue.reviews),
        "current_positive": int(current_cases),
        "context_positive": int(context_cases),
        "current_positive_yield": current_cases / len(queue.reviews) if queue.reviews else None,
        "context_positive_yield": context_cases / len(queue.reviews) if queue.reviews else None,
        "timely_incidents": len(timely),
        "incidents_available": len(incidents),
        "timely_hits": timely,
        "retained_record_delay_quantiles_hours": np.quantile(
            delays, [0, 0.25, 0.5, 0.75, 1]
        ).tolist()
        if delays
        else [],
        "delay_semantics": "Admission minus retained labelled record timestamp; timely reach is not necessarily incident-onset detection",
        "detector_ranking": ranking_diagnostics(keys, scores, y),
        "priority_ranking": ranking_diagnostics(keys, priorities, y),
        "scenario_breakdown": scenario_days,
        "event_losses": dict(Counter(x["terminal"] for x in losses)),
        "queue_decisions": dict(Counter(x["reason"] for x in queue.decisions)),
        "pending_end": len(queue.pending),
        "cost_semantics": "Actual admissions including drain; not measured analyst labor",
        "loss_semantics": "Terminal retained-evidence assignment; later context can rescue records whose own day fails the gate",
    }
    return result, losses
