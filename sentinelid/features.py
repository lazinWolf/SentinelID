"""Causal daily history, signed percentiles and historical peer context."""

import math
import statistics
from collections import Counter, defaultdict, deque
from datetime import datetime, timedelta

from .ingestion import ROOT, host, normalize, recipients, records, rosters

BASE = [
    "usb_change_1",
    "usb_change_3",
    "usb_change_7",
    "copy_change_1",
    "copy_change_3",
    "copy_change_7",
    "usb_active_change_7",
    "logon_change_1",
    "after_hours_change_1",
    "timing_novel_share",
    "new_computer_share",
]


EXTRA = [
    "external_email_change_1",
    "message_bytes_change_1",
    "attachments_change_1",
    "http_change_1",
    "new_recipient_count",
    "new_domain_count",
    "new_host_count",
    "new_recipient_share",
    "new_host_share",
]


COUNTS = [
    "usb",
    "copy",
    "logon",
    "after_hours",
    "external_email",
    "message_bytes",
    "attachments",
    "http",
]


class Day:
    def __init__(self, date):
        self.date = date
        self.counts = Counter()
        self.pointers = []
        self.computers = set()
        self.login_hours = []
        self.recipients = set()
        self.domains = set()
        self.hosts = set()
        self.sources = set()
        self.role = "Unknown role"
        self.month = ""
        self.events = 0

    def push(self, e):
        self.events += 1
        self.pointers.append(e.pointer())
        self.computers.add(e.computer_id)
        self.sources.add(e.source)
        self.role = e.role
        self.month = e.metadata_month
        if e.source == "device" and e.action.lower() == "connect":
            self.counts["usb"] += 1
        if e.source == "file":
            self.counts["copy"] += 1
        if e.source == "logon" and e.action.lower() == "logon":
            self.counts["logon"] += 1
            self.login_hours.append(e.timestamp.hour)
            self.counts["after_hours"] += int(e.timestamp.hour < 7 or e.timestamp.hour >= 19)
        if e.source == "email":
            r = recipients(e.fields)
            external = {x for x in r if "@" in x and x.rsplit("@", 1)[1] != "dtaa.com"}
            self.recipients.update(external)
            self.domains.update((x.rsplit("@", 1)[1] for x in external))
            self.counts["external_email"] += int(bool(external))
            self.counts["message_bytes"] += int(e.fields.get("size") or 0)
            self.counts["attachments"] += int(e.fields.get("attachment_count") or 0)
        if e.source == "http":
            self.counts["http"] += 1
            self.hosts.add(host(e.fields))

    def matched(self):
        return bool(self.sources & {"device", "file", "logon"})


def change(target, reference, n):
    mean = statistics.mean(reference) if reference else 0.0
    sd = statistics.pstdev(reference) if reference else 0.0
    denominator = max(1.0, math.sqrt(n) * sd, math.sqrt(n * max(0.0, mean)))
    return (
        max(0.0, (target - n * mean) / denominator),
        {
            "target": target,
            "reference_calendar_days": len(reference),
            "reference_mean": mean,
            "reference_sd": sd,
            "denominator": denominator,
            "zero_dispersion": sd == 0,
        },
    )


class DailyStream:
    def __init__(self, config, coverage=None):
        self.config = config
        self.start = datetime.fromisoformat(config["start"]).date()
        self.day = self.start
        self.buckets = {}
        self.history = defaultdict(deque)
        self.coverage = coverage

    def available(self, d, k):
        return self.coverage is None or self.coverage.get(d.isoformat(), {}).get(k, False)

    def push(self, e):
        rows = []
        while self.day < e.timestamp.date():
            rows.extend(self.close())
            self.day += timedelta(days=1)
        if e.timestamp.date() != self.day:
            raise ValueError("Late event: ordered replay contract requires nondecreasing days")
        self.buckets.setdefault(e.identity_id, Day(self.day)).push(e)
        return rows

    def close(self):
        rows = []
        d = self.day
        cfg = self.config
        for user, current in sorted(self.buckets.items()):
            history = {x.date: x for x in self.history[user]}
            last7 = [
                history.get(d - timedelta(days=j), Day(d - timedelta(days=j))) for j in range(1, 7)
            ] + [current]
            newrec = (
                current.recipients - set().union(*(x.recipients for x in history.values()))
                if history
                else current.recipients
            )
            newdomains = (
                current.domains - set().union(*(x.domains for x in history.values()))
                if history
                else current.domains
            )
            newhosts = (
                current.hosts - set().union(*(x.hosts for x in history.values()))
                if history
                else current.hosts
            )
            inputs = {}
            refs = {}
            eligibility = {}
            for window in cfg["reference_windows"]:
                end = d - timedelta(days=cfg["reference_lag_days"])
                dates = [end - timedelta(days=j + 1) for j in range(window)]
                reference = [history.get(t, Day(t)) for t in dates]
                required_dates = dates + [d - timedelta(days=j) for j in range(7)]
                base_missing = [
                    (t.isoformat(), k)
                    for t in required_dates
                    for k in ("logon", "device", "file")
                    if not self.available(t, k)
                ]
                expanded_missing = [
                    (t.isoformat(), k)
                    for t in required_dates
                    for k in ("email", "http")
                    if not self.available(t, k)
                ]
                active = sum((x.matched() for x in reference))
                calendar = (d - self.start).days
                eligibility[str(window)] = {
                    "base": calendar >= cfg["minimum_calendar_history"]
                    and active >= cfg["minimum_active_base_days"]
                    and (not base_missing),
                    "expanded": not expanded_missing,
                    "calendar_history": calendar,
                    "active_base_reference_days": active,
                    "missing_base_source_days": base_missing,
                    "missing_expanded_source_days": expanded_missing,
                }
                features = {}
                details = {}
                for k in COUNTS:
                    for n in [1, 3, 7] if k in ("usb", "copy") else [1]:
                        targets = last7[-n:]
                        score, detail = change(
                            sum((x.counts[k] for x in targets)), [x.counts[k] for x in reference], n
                        )
                        name = k + "_change_" + str(n)
                        features[name] = score
                        details[name] = detail
                features["usb_active_change_7"], details["usb_active_change_7"] = change(
                    sum((x.counts["usb"] > 0 for x in last7)),
                    [int(x.counts["usb"] > 0) for x in reference],
                    7,
                )
                known = set().union(*(x.computers for x in reference))
                hours = {h for x in reference for h in x.login_hours}
                features["new_computer_share"] = len(current.computers - known) / max(
                    1, len(current.computers)
                )
                features["timing_novel_share"] = (
                    sum(
                        (not any((abs(h - old) <= 1 for old in hours)) for h in current.login_hours)
                    )
                    / max(1, len(current.login_hours))
                    if hours
                    else 0.0
                )
                features.update(
                    new_recipient_count=len(newrec),
                    new_domain_count=len(newdomains),
                    new_host_count=len(newhosts),
                    new_recipient_share=len(newrec) / max(1, len(current.recipients)),
                    new_host_share=len(newhosts) / max(1, len(current.hosts)),
                )
                inputs[str(window)] = features
                refs[str(window)] = {
                    "start": min(dates).isoformat(),
                    "end_exclusive": end.isoformat(),
                    "details": details,
                    "modality_states": {
                        k: "missing_source"
                        if any(
                            (
                                not self.available(
                                    t, {"usb": "device", "copy": "file", "logon": "logon"}[k]
                                )
                                for t in required_dates
                            )
                        )
                        else "no_action"
                        if not current.counts[k]
                        else "no_history"
                        if not any((x.counts[k] for x in reference))
                        else "observed"
                        for k in ("usb", "copy", "logon")
                    },
                }
            context = [p for x in last7 for p in x.pointers]
            rows.append(
                {
                    "schema": "calendar-behavior-v3",
                    "identity_id": user,
                    "day": d.isoformat(),
                    "score_timestamp": datetime.combine(
                        d + timedelta(days=1), datetime.min.time()
                    ).isoformat(),
                    "matched_existing_population": current.matched(),
                    "role": current.role,
                    "metadata_month": current.month,
                    "counts": dict(current.counts),
                    "event_ids": [p["event_id"] for p in current.pointers],
                    "current_pointers": current.pointers,
                    "context_pointers": context,
                    "features": inputs,
                    "references": refs,
                    "eligibility": eligibility,
                }
            )
        for user, current in self.buckets.items():
            h = self.history[user]
            h.append(current)
            while h and h[0].date < d - timedelta(days=35):
                h.popleft()
            for prior in h:
                if prior.date < d - timedelta(days=5):
                    prior.pointers = []
        self.buckets = {}
        return rows

    def finish(self, end):
        rows = []
        end = end.date() if isinstance(end, datetime) else end
        while self.day < end:
            rows.extend(self.close())
            self.day += timedelta(days=1)
        return rows


CHANGE = [k for k in BASE + EXTRA if "_change_" in k]


NOVEL = [k for k in BASE + EXTRA if k not in CHANGE]


PEER = [
    "peer_usb_percentile",
    "peer_copy_percentile",
    "peer_external_email_percentile",
    "peer_supported",
]


def centered_percentile(value, history):
    if not history:
        raise ValueError("Percentile requires explicit historical coverage")
    return (sum((x < value for x in history)) + 0.5 * sum((x == value for x in history))) / len(
        history
    ) - 0.5


def original_records(config, start=None):
    split = datetime.fromisoformat(config["extension_start"])
    end = datetime.fromisoformat(config["end"])
    begin = start or datetime.fromisoformat(config["start"])
    for root, lo, hi in [
        (ROOT / "data/raw/recovery-v3", begin, min(end, split)),
        (ROOT / "data/raw/workload-v4", max(begin, split), end),
    ]:
        if lo < hi:
            for e in records(root, start=lo, end=hi):
                yield normalize(e)


class WorkloadStream(DailyStream):
    def __init__(self, config, coverage=None):
        super().__init__(config, coverage)
        self.metadata = {}
        self.legacy_active = defaultdict(set)
        for root in [ROOT / "data/raw/recovery-v3", ROOT / "data/raw/workload-v4"]:
            for month, users in rosters(root).items():
                self.metadata[month] = users

    def push(self, e):
        e = normalize(e)
        if "2010-05-25" <= e.timestamp.date().isoformat() < "2010-06-08" and e.source in (
            "logon",
            "file",
            "device",
        ):
            self.legacy_active[e.identity_id].add(e.timestamp.date())
        result = super().push(e)
        person = self.metadata.get(e.metadata_month, {}).get(e.identity_id, {})
        group = (
            "team:" + person["team"]
            if person.get("team")
            else "role:" + person["role"]
            if person.get("role")
            else None
        )
        self.buckets[e.identity_id].peer_group = group
        if e.source == "email" and any(
            ("@" in a and a.rsplit("@", 1)[1] != "dtaa.com" for a in recipients(e.fields))
        ):
            bucket = self.buckets[e.identity_id]
            bucket.external_ids = getattr(bucket, "external_ids", []) + [e.event_id]
        return result

    def close(self):
        d = self.day
        before = {u: deque(h) for u, h in self.history.items()}
        current = dict(self.buckets)
        end = d - timedelta(days=7)
        dates = [end - timedelta(days=j + 1) for j in range(28)]
        extra_dates = [min(dates) - timedelta(days=j + 1) for j in range(6)]
        peers = defaultdict(dict)
        for user, h in before.items():
            groups = defaultdict(list)
            for x in h:
                if min(dates) <= x.date < end and x.matched() and getattr(x, "peer_group", None):
                    groups[x.peer_group].append(x)
            for group, days in groups.items():
                if len(days) >= self.config["peers"]["minimum_active_days_per_user"]:
                    peers[group][user] = (
                        [
                            sum((x.counts[k] for x in days)) / 28
                            for k in self.config["peers"]["features"]
                        ],
                        len(days),
                    )
        self.history = defaultdict(
            deque,
            {
                u: deque((x for x in h if x.date >= d - timedelta(days=36)))
                for u, h in before.items()
            },
        )
        rows = super().close()
        for r in rows:
            user = r["identity_id"]
            today = current[user]
            hist = {x.date: x for x in before.get(user, [])}
            f = r["features"]["28"]
            perc = {}
            audit = {}
            for name in CHANGE:
                key, n = name.rsplit("_change_", 1)
                n = int(n)

                def value(x, key=key):
                    return int(x.counts["usb"] > 0) if key == "usb_active" else x.counts[key]

                target = sum(
                    (
                        value(
                            today
                            if j == 0
                            else hist.get(d - timedelta(days=j), Day(d - timedelta(days=j)))
                        )
                        for j in range(n)
                    )
                )
                history = [
                    sum(
                        (
                            value(hist.get(t - timedelta(days=j), Day(t - timedelta(days=j))))
                            for j in range(n)
                        )
                    )
                    for t in dates
                ]
                perc[name] = centered_percentile(target, history)
                audit[name] = {
                    "target": target,
                    "n": n,
                    "observations": len(history),
                    "ties": sum((x == target for x in history)),
                    "maximum": max(history),
                    "minimum": min(history),
                    "zero_history": not any(history),
                }
            group = getattr(today, "peer_group", None)
            others = {u: v for u, v in peers.get(group, {}).items() if u != user}
            support = (
                len(others) >= self.config["peers"]["minimum_users"]
                and sum((v[1] for v in others.values()))
                >= self.config["peers"]["minimum_total_active_days"]
            )
            peer_values = {}
            peer_targets = {}
            for i, k in enumerate(self.config["peers"]["features"]):
                v = (
                    today.counts[k]
                    + sum(
                        (
                            hist.get(d - timedelta(days=j), Day(d - timedelta(days=j))).counts[k]
                            for j in range(1, 7)
                        )
                    )
                ) / 7
                peer_targets[k] = v
                peer_values["peer_" + k + "_percentile"] = (
                    centered_percentile(v, [x[0][i] for x in others.values()]) if support else 0.0
                )
            peer_values["peer_supported"] = int(support)
            complete = all(
                (self.available(t, k) for t in extra_dates for k in self.config["sources"])
            )
            r["common_eligible"] = (
                r["matched_existing_population"]
                and r["eligibility"]["28"]["base"]
                and r["eligibility"]["28"]["expanded"]
                and complete
            )
            r["historical_control_eligible"] = len(self.legacy_active[user]) >= 7
            r.update(
                schema="behavior-workload-v4",
                percentiles=perc,
                percentile_reference=audit,
                peer_features=peer_values,
                peer_reference={
                    "group": group,
                    "users": len(others),
                    "active_days": sum((v[1] for v in others.values())),
                    "supported": support,
                    "self_excluded": True,
                    "start": min(dates).isoformat(),
                    "end_exclusive": end.isoformat(),
                    "targets": peer_targets,
                },
                qualifying_families={},
            )
            for family, k, count in [
                ("removable_media", "copy_change_1", today.counts["copy"]),
                ("external_email", "external_email_change_1", today.counts["external_email"]),
            ]:
                if f[k] >= 3 and count >= 2:
                    sources = {"file", "device"} if family == "removable_media" else {"email"}
                    r["qualifying_families"][family] = (
                        getattr(today, "external_ids", [])
                        if family == "external_email"
                        else [p["event_id"] for p in today.pointers if p["source"] in sources]
                    )
            r["references"]["28"]["percentile_extra_source_coverage"] = complete
        for user, h in before.items():
            if user in current:
                h.append(current[user])
            while h and h[0].date < d - timedelta(days=self.config["retained_history_days"]):
                h.popleft()
            for x in h:
                if x.date < d - timedelta(days=5):
                    x.pointers = []
            self.history[user] = h
        for user, today in current.items():
            if user not in before:
                self.history[user] = deque([today])
        return rows
