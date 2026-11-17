"""Markdown reports written from saved research results.

Every writer reads only what a stage saved, so any report can be regenerated without refitting.
"""

import json
from collections import Counter, defaultdict

import numpy as np

from .ingestion import ROOT
from .research_data import directory

COUNTS = ("identity_days", "gate_days", "incidents", "timely_incidents")


def combine_coverage(runs):
    """Role coverage summed over folds, then averaged over seeds."""
    seeds = defaultdict(lambda: defaultdict(lambda: defaultdict(Counter)))
    for r in runs:
        for scenario, roles in r.get("role_coverage", {}).items():
            for kind, values in roles.items():
                seeds[r.get("seed", 0)][scenario][kind].update({k: values[k] for k in COUNTS})
    result = {}
    for per_seed in seeds.values():
        for scenario, roles in per_seed.items():
            for kind, values in roles.items():
                target = result.setdefault(scenario, {}).setdefault(kind, dict.fromkeys(COUNTS, 0))
                for k in COUNTS:
                    target[k] += values[k] / len(seeds)
    return result


def coverage_lines(table):
    """Markdown rows: candidate, scenario, role, gate days and timely incidents."""
    lines = [
        "| Candidate | Scenario | Account | Days over gate | Timely incidents |",
        "| --- | --- | --- | ---: | ---: |",
    ]
    for name, t in table.items():
        for scenario, roles in sorted(t["role_coverage"].items()):
            for kind, v in sorted(roles.items(), reverse=True):
                lines.append(
                    f"| {name} | {scenario} | {kind} | {v['gate_days']:.1f} / "
                    f"{v['identity_days']:.0f} | {v['timely_incidents']:.1f} / {v['incidents']:.0f} |"
                )
    return lines


def policy_label(candidate):
    parts = [candidate["policy"], "rank=" + candidate.get("rank", "max")]
    parts += [f"{k}={v}" for k, v in candidate.get("queue", {}).items()]
    return ", ".join(parts)


# Text a report cannot derive from its results: a title and a verdict written after review.
REPORT_TEXT = {
    "backtest-ledger-fix": {
        "title": "Development backtest: ledger exposure fix check",
        "verdict": "**No candidate beats the control; every one ties it at 44.3.** This is a "
        "development-only check after the exposure fix (`configs/research-ledger-fix.json`); the "
        "holdout is not used, and the round 3 holdout verdict stands as recorded.",
    }
}


def write_backtest_report(path, config, summary):
    text = REPORT_TEXT.get(config.get("output", "backtest"), {})
    lines = [
        "# " + text.get("title", "Development backtest"),
        "",
        "Rolling-origin folds inside June-November 2010. Each fold refits on all earlier development days, "
        "sets the gate at the fitting-score quantile, and replays one admission per day with cooldown and expiry. "
        f"Seeds: {config['seeds']}. Totals are summed over folds and averaged over seeds (min-max in brackets). "
        "The sealed December 2010 - May 2011 holdout is not used here.",
        "",
        "| Candidate | Features | Model | Queue | Admissions | Current + | Yield | Timely incidents | AP | Gate recall |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for t in summary["candidates"].values():
        ti = t["timely_incidents"]
        lines.append(
            f"| {t['name']} | {t['features']} | {t['model']} | {policy_label(t)} | "
            f"{t['admissions']['mean']:.1f} | {t['current_positive']['mean']:.1f} | "
            f"{t['current_positive_yield']:.3f} | {ti['mean']:.1f} [{ti['min']:.0f}-{ti['max']:.0f}] / "
            f"{t['incidents_available']:.0f} | {t['detector_average_precision']:.3f} | {t['gate_recall']:.3f} |"
        )
    lines += [
        "",
        f"Baseline: `{config['baseline']}`. Selection rule: {config['selection_rule']}",
        "",
        text.get("verdict", f"**Selected for the sealed holdout: `{summary['selected']}`.**"),
        "",
    ]
    if any(t.get("role_coverage") for t in summary["candidates"].values()):
        lines += [
            "## Coverage by scenario and account",
            "",
            "Scenario 1 and 2 insiders act under their own account. Scenario 3 is an account "
            "takeover: the attacker logs on to the supervisor's computer as the supervisor, so "
            "its records fall under two accounts, `own` (the attacker's preparation) and "
            "`hijacked` (the victim's account in use). Days are labelled identity-days; an "
            "incident counts once per account role when a record under that role reaches an "
            "analyst within 72 hours.",
            "",
            *coverage_lines(summary["candidates"]),
            "",
        ]
    path.parent.mkdir(exist_ok=True)
    path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Sealed holdout.


def write_holdout_report(root=ROOT, stage="holdout"):
    result = json.loads((directory(root) / stage / "result.json").read_text())
    groups = defaultdict(list)
    for run in result["runs"]:
        groups[(run["role"], run["name"])].append(run)

    def span(runs, key):
        values = [r[key] for r in runs]
        low, high = min(values), max(values)
        return f"{low}" if low == high else f"{low}-{high}"

    lines = [
        "# Sealed holdout evaluation",
        "",
        f"Holdout: {result['holdout'][0]} to {result['holdout'][1]} (exclusive), original CERT r4.2 records "
        "never used for development. Every scorer was fitted and frozen before holdout labels were read; "
        "this evaluation runs once. Refit scorers use June 8 - November 30 development data (labels only for supervised scorers); ranges are over 5 seeds. "
        "Queue: one admission per day, 7-day cooldown, 3-day expiry, plus drain.",
        "",
        "**Fresh insiders** are incidents whose official start is on or after the holdout start; "
        "**timely** means a labelled record was presented within 72 hours of that record.",
        "",
    ]
    if result.get("previous_holdout_uses"):
        lines += [
            "**Exploratory reuse:** this holdout was already evaluated for "
            + ", ".join(result["previous_holdout_uses"])
            + ". These candidates were developed without its results, but it is no longer untouched.",
            "",
        ]
    lines += [
        "| Role | Scorer | Admissions | Current + | Yield | Timely incidents | Fresh insiders | AP | Gate recall |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for (role, name), runs in groups.items():
        first = runs[0]
        yields = [r["current_positive_yield"] for r in runs]
        lines.append(
            f"| {role} | {name} | {span(runs, 'admissions')} | {span(runs, 'current_positive')} | "
            f"{min(yields):.2f}-{max(yields):.2f} | {span(runs, 'timely_incidents')} / {first['incidents_available']} | "
            f"{span(runs, 'timely_fresh_incidents')} / {first['fresh_incidents_available']} | "
            f"{np.mean([r['detector_average_precision'] for r in runs]):.3f} | "
            f"{np.mean([r['gate_recall'] for r in runs]):.3f} |"
        )
    deployed = groups[("primary", "deployed (frozen, fit Jun-Oct)")][0]
    lines += [
        "",
        "## Deployed model detail",
        "",
        f"- Scenario breakdown: {json.dumps(deployed['scenario_breakdown'])}",
        f"- Terminal event assignments: {json.dumps(deployed['event_losses'])}",
        f"- Queue decisions: {json.dumps(deployed['queue_decisions'])}",
        "- Median delay from official incident onset to the timely admission: "
        f"{np.median([h['official_onset_delay_hours'] for h in deployed['timely_hits'].values()]):.1f} hours",
        "",
    ]
    if all("role_coverage" in r for r in result["runs"]):
        table = {
            name: {"role_coverage": combine_coverage(runs)} for (_, name), runs in groups.items()
        }
        lines += [
            "## Coverage by scenario and account",
            "",
            "Means over seeds. `hijacked` is scenario 3's victim account in use by the attacker.",
            "",
            *coverage_lines(table),
            "",
        ]
    suffix = stage.removeprefix("holdout").upper()
    (root / f"reports/HOLDOUT{suffix}.md").write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Identity-attack coverage of the deployed model.

SCENARIOS = {
    "1": "Data theft before leaving: after-hours logons, USB use, upload to wikileaks.org",
    "2": "Job hunting, then data theft to a USB drive before leaving",
    "3": "Account takeover: keylogger planted on the supervisor's computer, then mass email "
    "sent while logged on as the supervisor",
}


def write_coverage_report(root, result):
    lines = [
        "# Identity-attack coverage",
        "",
        "How the frozen deployed model's already-reported results split by attack scenario and by "
        "whose account the malicious activity was recorded under. Nothing here was used to select "
        "or tune anything; the holdout scores are the ones frozen before its labels were read.",
        "",
        "## Scenarios in CERT r4.2",
        "",
        "| Scenario | Behaviour | Accounts involved |",
        "| --- | --- | --- |",
        f"| 1 | {SCENARIOS['1']} | the insider's own |",
        f"| 2 | {SCENARIOS['2']} | the insider's own |",
        f"| 3 | {SCENARIOS['3']} | the attacker's own, then the victim's (`hijacked`) |",
        "",
    ]
    for name, p in result["periods"].items():
        lines += [
            f"## {name.capitalize()} ({p['span'][0]} to {p['span'][1]}, exclusive)",
            "",
            f"{p['admissions']} investigations, {p['current_positive']} current-positive, "
            f"{p['timely_incidents']}/{p['incidents_available']} incidents reached in time.",
            "",
            "| Scenario | Account | Labelled days over the gate | Incidents reached within 72 h "
            "| Median hours, first record to admission |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
        for scenario, roles in sorted(p["role_coverage"].items()):
            for kind, v in sorted(roles.items(), reverse=True):
                delays = v["first_record_to_admission_hours"]
                median = f"{np.median(delays):.0f}" if delays else "never shown"
                lines.append(
                    f"| {scenario} | {kind} | {v['gate_days']} / {v['identity_days']} | "
                    f"{v['timely_incidents']} / {v['incidents']} | {median} |"
                )
        lines += [
            "",
            "Where labelled records ended up (event counts): "
            + "; ".join(
                f"scenario {sc}: " + ", ".join(f"{k} {n}" for k, n in sorted(c.items()))
                for sc, c in p["losses_by_scenario"].items()
            )
            + ".",
            "",
        ]
    lines += [
        "`admitted_context` means the record was shown in an investigation; `threshold` means its "
        "day scored below the gate; `cooldown`, `expiry` and `budget_pending` are queue losses.",
        "",
    ]
    (root / "reports/IDENTITY_COVERAGE.md").write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Methods study.


def write_methods_report(path, result):
    t = result["methods"]
    baseline = result.get("baseline", "rf")
    f = lambda v: f"{v:.3f}"  # noqa: E731
    lines = [
        "# Methods study: detection methods compared",
        "",
        "Development folds August to November 2010 (expanding training window from 2010-06-08), "
        "feature set `c`, gate at the 0.99 quantile of each method's training scores, the maintained "
        "one-a-day queue. Specification, fixed before any result: "
        "[docs/methods-study.md](../docs/methods-study.md). The holdout is not used. Intervals are "
        "95% paired bootstrap intervals (incident-folds for reach, test days for average precision); "
        f"the baseline is `{baseline}`.",
        "",
        f"## Ranking and reach ({result['incident_folds']} incident-folds)",
        "",
        "| Method | Family | Avg. precision [95%] | vs RF [95%] | ROC-AUC | Incidents reached [95%] | vs RF [95%] |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for m, r in t.items():
        lo, hi = r["average_precision_interval"]
        dlo, dhi = r["ap_difference_interval"]
        rlo, rhi = r["incidents_reached_interval"]
        qlo, qhi = r["reached_difference_interval"]
        lines.append(
            f"| `{m}` | {r['family']} | {f(r['average_precision'])} [{f(lo)}, {f(hi)}] | "
            + (
                "—"
                if m == baseline
                else f"{r['ap_difference']:+.3f} [{dlo:+.3f}, {dhi:+.3f}] {r['ap_reading']}"
            )
            + f" | {f(r['roc_auc'])} | {r['incidents_reached']:.1f} [{rlo:.1f}, {rhi:.1f}] | "
            + (
                "—"
                if m == baseline
                else f"{r['reached_difference']:+.1f} [{qlo:+.1f}, {qhi:+.1f}] {r['reached_reading']}"
            )
            + " |"
        )
    lines += [
        "",
        "## Budget curves and queue cost",
        "",
        "Recall at k is the share of malicious identity-days ranked in the top k of their own day "
        "(before the gate and queue). Investigations and current-positive yield are through the queue.",
        "",
        "| Method | Recall@1 | Recall@2 | Recall@5 | Recall@10 | Over gate | Investigations | Yield |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for m, r in t.items():
        a = r["recall_at"]
        lines.append(
            f"| `{m}` | {a['1']:.3f} | {a['2']:.3f} | {a['5']:.3f} | {a['10']:.3f} | "
            f"{r['gate_candidates']:.0f} | {r['admissions']:.1f} | "
            f"{r['current_positive'] / r['admissions']:.0%} |"
        )
    lines += [
        "",
        "## Reach by scenario",
        "",
        "Mean incident-folds reached within 72 hours per scenario; for the takeover (scenario 3), "
        "split by the attacker's own account and the hijacked account.",
        "",
        "| Method | Scenario 1 | Scenario 2 | Scenario 3 | Takeover: attacker | Takeover: hijacked |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for m, r in t.items():
        s = r["scenario_reached"]
        lines.append(
            f"| `{m}` | {s.get('1', 0):.1f} | {s.get('2', 0):.1f} | {s.get('3', 0):.1f} | "
            f"{r['takeover_attacker_reached']:.1f} | {r['takeover_hijacked_reached']:.1f} |"
        )
    lines += [
        "",
        "## Timeliness",
        "",
        "Hours from an incident's first labelled record (own account) to the first investigation "
        "showing one, pooled over folds and seeds; incidents never shown are left out. Ranking "
        "measures reward a malicious day ranked high on any day of an incident; reach needs it "
        "early.",
        "",
        "| Method | Scenario 1: shown, median h, after 72 h | Scenario 2 | Scenario 3 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for m, r in t.items():
        cells = []
        for scenario in ("1", "2", "3"):
            c = r["timeliness"][scenario]
            cells.append(
                f"{c['shown']}/{c['incidents']}, {c['median_hours']:.0f} h, "
                f"{c['share_after_72_hours']:.0%}"
                if c["shown"]
                else f"0/{c['incidents']}"
            )
        lines.append(f"| `{m}` | " + " | ".join(cells) + " |")
    lines += [
        "",
        "Reading rule (fixed in the specification): a method matches the baseline when the interval "
        "of its difference contains 0, and is better or worse when the whole interval is above or "
        f"below 0. With {len(t) - 1} comparisons a single better or worse is a lead, not a "
        "finding.",
        "",
    ]
    path.write_text("\n".join(lines))
