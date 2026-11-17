"""Plain-language reasons behind a case, read from the stored measurements of one identity-day.

A signal names a departure from the identity's own 28-day reference ("USB use well above
usual", "logged on to a computer not used before") and the ATT&CK technique the threat model
maps it to (REPORT.md section 3.2). Signals use only the measurements the model saw, never
labels. They explain which behaviour changed, not which input drove the forest's score.
"""

import math

# channel -> (label, unit, ATT&CK technique, attack stage)
CHANNELS = {
    "usb": ("USB use", "connections", "T1052.001", "Exfiltration over USB"),
    "copy": ("Copying to removable media", "file copies", "T1005", "Collection"),
    "after_hours": ("After-hours logons", "logons", "T1078", "Use of valid credentials"),
    "logon": ("Logons", "logons", "T1078", "Use of valid credentials"),
    "external_email": ("External email", "messages", "T1534", "Email from the account"),
    "attachments": ("Email attachments", "attachments", "T1534", "Email from the account"),
    "message_bytes": ("Email volume", "bytes", "T1534", "Email from the account"),
    "http": ("Web activity", "visits", "T1567", "Web exfiltration or tool download"),
}
# A change counts when log1p(magnitude) reaches NOTABLE (about the top 3% of development
# identity-days) and the signed percentile is in the upper quarter of the identity's history.
NOTABLE, STRONG, PERCENTILE = 0.6, 1.0, 0.25
SINGULAR = {
    "connections": "connection",
    "file copies": "file copy",
    "logons": "logon",
    "messages": "message",
    "attachments": "attachment",
    "bytes": "byte",
    "visits": "visit",
}
LIMIT = 5


def strength(value):
    return "strong" if value >= STRONG else "notable"


def change_signals(observation):
    features = observation.get("features", {})
    percentiles = observation.get("percentiles", {})
    details = observation.get("reference", {}).get("details", {})
    found = {}
    for channel, (label, unit, technique, stage) in CHANNELS.items():
        for n in (1, 3, 7):
            key = f"{channel}_change_{n}"
            if key not in features or key not in details:
                continue
            size = math.log1p(max(0.0, features[key]))
            if size < NOTABLE or percentiles.get(key, 0.0) < PERCENTILE:
                continue
            if channel in found and found[channel]["size"] >= size:
                continue
            d = details[key]
            count = f"{d['target']:,} {unit if d['target'] != 1 else SINGULAR[unit]}"
            usual = n * d["reference_mean"]
            period = "today" if n == 1 else f"in the last {n} days"
            if usual == 0:
                lower = label if label.startswith("USB") else label[0].lower() + label[1:]
                title = f"First {lower} in the reference period"
                detail = f"{count} {period}; none in the 28-day reference"
            else:
                title = f"{label} well above this identity's usual"
                detail = f"{count} {period} against a usual {usual:,.1f}"
            found[channel] = {
                "key": key,
                "title": title,
                "detail": detail,
                "technique": technique,
                "stage": stage,
                "strength": strength(size),
                "size": size,
            }
    return list(found.values())


def novelty_signals(observation):
    f = observation.get("features", {})
    out = []
    if f.get("new_computer_share", 0) > 0:
        out.append(
            {
                "key": "new_computer_share",
                "title": "Logged on to a computer not used before",
                "detail": f"{f['new_computer_share']:.0%} of today's computers are new to this "
                "identity. In an account takeover this is the attacker's own account on the "
                "victim's machine.",
                "technique": "T1570",
                "stage": "Lateral tool transfer",
                "strength": "strong",
                "size": 1.0 + f["new_computer_share"],
            }
        )
    if f.get("timing_novel_share", 0) > 0:
        out.append(
            {
                "key": "timing_novel_share",
                "title": "Logons at hours never seen before",
                "detail": f"{f['timing_novel_share']:.0%} of today's logons fall more than an "
                "hour from any logon hour in the reference",
                "technique": "T1078",
                "stage": "Use of valid credentials",
                "strength": "strong" if f["timing_novel_share"] >= 0.5 else "notable",
                "size": 0.6 + f["timing_novel_share"],
            }
        )
    if f.get("new_domain_count", 0) >= 1:
        n = int(f["new_domain_count"])
        out.append(
            {
                "key": "new_domain_count",
                "title": f"{n} web domain{'s' if n > 1 else ''} never visited before",
                "detail": "New destinations can mean an upload site or a tool download",
                "technique": "T1567 / T1105",
                "stage": "Web exfiltration or tool download",
                "strength": "notable",
                "size": 0.6 + 0.1 * min(n, 4),
            }
        )
    if f.get("new_recipient_count", 0) >= 5:
        n = int(f["new_recipient_count"])
        out.append(
            {
                "key": "new_recipient_count",
                "title": f"Email to {n} recipients not written to before",
                "detail": "A sudden widening of who this identity writes to",
                "technique": "T1534",
                "stage": "Email from the account",
                "strength": "notable",
                "size": 0.6,
            }
        )
    return out


def signals(observation, limit=LIMIT):
    """The day's strongest departures from the identity's own history, strongest first."""
    found = change_signals(observation) + novelty_signals(observation)
    found.sort(key=lambda s: (-s["size"], s["key"]))
    return [{k: v for k, v in s.items() if k != "size"} for s in found[:limit]]
