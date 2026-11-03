"""Analyst-feedback learning from a label-free start (Active Anomaly Discovery style).

The detector starts as the label-free `ecod_up_top5` score. Each day's admitted
investigations receive an analyst verdict, simulated from the answer key for
admitted cases only, and the verdicts re-weight the per-input rarity components.
Unadmitted identity-days never contribute labels.
"""

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from scipy.stats import binomtest

from .adaptive import AdaptiveScorer
from .experiment_evaluation import evaluate
from .experiment_io import fingerprint, save_json
from .ingestion import ROOT
from .research import (
    ANSWERS,
    HOLDOUT_END,
    HOLDOUT_START,
    Data,
    ResearchQueue,
    day_after,
    design,
    directory,
    window,
)
from .research_data import truth


class Oracle:
    """Simulated analyst: answers only for admitted cases, optionally with errors.

    `miss` turns true positives into negatives (an overlooked insider); `flip` inverts
    any verdict. Both default to a perfect analyst.
    """

    def __init__(self, events, flip=0.0, miss=0.0, seed=0):
        self.events = events
        self.flip, self.miss = flip, miss
        self.rng = np.random.default_rng(seed)
        self.asked = []
        self.errors = 0

    def verdict(self, case):
        self.asked.append(case["case_id"])
        truth = 1 if set(case["trigger_ids"]) & self.events.keys() else -1
        given = truth
        if truth == 1 and self.rng.random() < self.miss:
            given = -1
        elif self.rng.random() < self.flip:
            given = -truth
        self.errors += given != truth
        return given


def months(start, end):
    result = []
    day = date.fromisoformat(start)
    while day.isoformat() < end:
        following = date(day.year + day.month // 12, day.month % 12 + 1, 1)
        result.append((day.isoformat(), min(following.isoformat(), end)))
        day = following
    return result


def online(data, x, start, end, reference_start, lam, oracle, queue_config, gate_quantile):
    """Day-by-day scoring, admission, verdicts and re-weighting with a continuous queue."""
    queue = ResearchQueue(queue_config, "max_cooldown")
    run = window(data, start, end)
    position = {i: k for k, i in enumerate(run)}
    margins = np.full(len(run), np.nan)
    scorer = AdaptiveScorer(reference_start, lam, gate_quantile)
    for i in window(data, reference_start, start):
        scorer.observe(str(data.days[i]), str(data.v["identity"][i]), x[i])
    verdicts, trace = [], []
    days = (date.fromisoformat(end) - date.fromisoformat(start)).days
    for n in range(days + queue_config["backlog_days"]):
        day = day_after(start, n)
        if day < end:
            scorer.prepare(day, verdicts)
            today = run[data.days[run] == day]
            scores = scorer.score(x[today]) if len(today) else []
            for i, s in zip(today, scores, strict=True):
                margins[position[i]] = s - scorer.gate
                if s < scorer.gate:
                    continue
                row = data.row(i, with_events=True)
                queue.offer(
                    {
                        "detector": "feedback",
                        "identity_id": row["identity_id"],
                        "day": day,
                        "available_time": row["score_timestamp"],
                        "score": float(s),
                        "detector_score": float(s),
                        "priority_score": float(s),
                        "trigger_ids": row["event_ids"],
                        "evidence_ids": data.context(row["identity_id"], day),
                        "qualifying_families": row["qualifying_families"],
                    }
                )
            for i in today:
                scorer.observe(day, str(data.v["identity"][i]), x[i])
        cases = queue.decide(day_after(day) + "T%02d:00:00" % queue_config["decision_hour"])
        for case in cases:
            y = oracle.verdict(case)
            verdicts.append((y, [(d, case["identity_id"]) for d in case["days"]]))
        if cases:
            scorer.learn(verdicts)
        trace.append({"day": day, "gate": scorer.gate, "labels": scorer.labels})
    return queue, run, margins, scorer, trace


def monthly(data, run, margins, queue, events, start, end, last_end):
    """Evaluate one month's rows against admissions decided for that month (drain in the last)."""
    keep = (data.days[run] >= start) & (data.days[run] < end)
    rows_idx, scores = run[keep], margins[keep]
    upper = day_after(end, 3 if end == last_end else 0) + "T23:59:59"
    view = SimpleNamespace(
        reviews=[c for c in queue.reviews if day_after(start) <= c["decision_time"] <= upper],
        decisions=queue.decisions,
        pending=queue.pending,
    )
    month_events = {k: t for k, t in events.items() if day_after(start, -7) <= t["day"] < end}
    available = {t["incident_id"] for t in month_events.values() if start <= t["day"] < end}
    positives = {(t["day"], t["observed_account"]) for t in month_events.values()}
    rows = [
        data.row(i, with_events=(str(data.days[i]), str(data.v["identity"][i])) in positives)
        for i in rows_idx
    ]
    protocol = {"evaluation_start": start, "evaluation_end": end, "timely_hours": 72}
    result, _ = evaluate(rows, scores, scores, 0.0, view, month_events, protocol)
    return {
        **{
            k: result[k]
            for k in (
                "admissions",
                "current_positive",
                "timely_incidents",
                "incidents_available",
                "detector_average_precision",
                "gate_recall",
            )
        },
        "timely_ids": sorted(result["timely_hits"]),
        "available_ids": sorted(available),
    }


DEFAULT_CONFIG = "configs/research-feedback.json"


def simulate(data, x, config, end, events, variant, queue_config, analyst=None, seed=0):
    """One online run with a fresh analyst; verdicts must stay limited to admitted cases."""
    analyst = analyst or {}
    oracle = Oracle(events, analyst.get("flip", 0.0), analyst.get("miss", 0.0), seed)
    queue, rows, margins, scorer, trace = online(
        data,
        x,
        config["start"],
        end,
        config["reference_start"],
        variant["lambda"],
        oracle,
        queue_config,
        config["gate_quantile"],
    )
    if oracle.asked != [c["case_id"] for c in queue.reviews]:
        raise ValueError("Analyst verdicts requested for non-admitted cases")
    return queue, rows, margins, scorer, trace, oracle


def setting(config_path, root):
    config = json.loads(Path(config_path).read_text())
    data = Data(root)
    x, names = design(data, {"features": "c", "transform": "up"})
    queue_config = json.loads((root / "config.json").read_text())["queue"]
    return config, data, x, names, queue_config


def development(data, x, config, events, variant, queue_config, analyst=None, seed=0):
    """Online run over the development period, evaluated month by month."""
    start, end = config["start"], config["end"]
    queue, rows, margins, scorer, trace, oracle = simulate(
        data, x, config, end, events, variant, queue_config, analyst, seed
    )
    per_month = {
        m: monthly(data, rows, margins, queue, events, m, e, end) for m, e in months(start, end)
    }
    totals = {
        k: sum(m[k] for m in per_month.values())
        for k in ("admissions", "current_positive", "timely_incidents", "incidents_available")
    }
    return per_month, totals, queue, scorer, trace, oracle


def continuation(data, x, config, events, fresh, variant, queue_config, analyst=None, seed=0):
    """Online run from the development start through the holdout; metrics cover the holdout."""
    queue, rows, margins, _, _, oracle = simulate(
        data, x, config, HOLDOUT_END, events, variant, queue_config, analyst, seed
    )
    m = monthly(data, rows, margins, queue, events, HOLDOUT_START, HOLDOUT_END, HOLDOUT_END)
    m["timely_fresh_incidents"] = len(set(m["timely_ids"]) & fresh)
    m["fresh_incidents_available"] = len(fresh)
    return m, oracle


def holdout_events(config, root):
    events = truth(root / ANSWERS, day_after(config["start"], -7), HOLDOUT_END)
    fresh = {t["incident_id"] for t in events.values() if t["official_start"] >= HOLDOUT_START}
    return events, fresh


def previous_holdout_uses(root):
    return sorted(
        str(p.relative_to(directory(root))) for p in directory(root).glob("holdout*/result.json")
    )


def run(config_path=DEFAULT_CONFIG, root=ROOT):
    config, data, x, names, queue_config = setting(config_path, root)
    events = truth(root / ANSWERS, day_after(config["start"], -7), config["end"])
    results = {}
    for variant in config["variants"]:
        per_month, totals, queue, scorer, trace, _ = development(
            data, x, config, events, variant, queue_config
        )
        results[variant["name"]] = {
            "lambda": variant["lambda"],
            "months": per_month,
            "totals": totals,
            "labels": trace[-1]["labels"],
            "positive_labels": sum(
                1 for c in queue.reviews if set(c["trigger_ids"]) & events.keys()
            ),
            "top_weights": scorer.weights(names),
        }
        print(variant["name"], json.dumps(totals), flush=True)
    out = directory(root) / "feedback"
    out.mkdir(exist_ok=True)
    save_json(
        out / "results.json",
        {"config": config, "config_sha256": fingerprint(config), "variants": results},
    )
    write_report(root)
    return results


def holdout(config_path=DEFAULT_CONFIG, root=ROOT):
    """Exploratory reuse: keep learning online from August through the holdout months."""
    out = directory(root) / "holdout-feedback"
    if (out / "result.json").exists():
        raise ValueError("Feedback holdout already evaluated: " + str(out / "result.json"))
    previous = previous_holdout_uses(root)
    config, data, x, _, queue_config = setting(config_path, root)
    events, fresh = holdout_events(config, root)
    results = {}
    for variant in config["variants"]:
        m, _ = continuation(data, x, config, events, fresh, variant, queue_config)
        results[variant["name"]] = m
        print(variant["name"], {k: v for k, v in m.items() if k != "timely_ids"}, flush=True)
    out.mkdir(exist_ok=True)
    save_json(
        out / "result.json",
        {"variants": results, "previous_holdout_uses": previous, "config": config},
    )
    write_report(root)
    return results


def robustness(config_path=DEFAULT_CONFIG, root=ROOT, with_holdout=False):
    """Repeat the selected learner with imperfect analysts over several seeds.

    with_holdout continues each run through the holdout (exploratory reuse, once only).
    """
    config, data, x, _, queue_config = setting(config_path, root)
    settings = config["robustness"]
    variant = {"lambda": settings["lambda"]}
    if with_holdout:
        out = directory(root) / "holdout-feedback-robustness"
        if (out / "result.json").exists():
            raise ValueError("Robustness holdout already evaluated: " + str(out / "result.json"))
        previous = previous_holdout_uses(root)
        events, fresh = holdout_events(config, root)
    else:
        events = truth(root / ANSWERS, day_after(config["start"], -7), config["end"])
    results = {}
    for analyst in settings["analysts"]:
        runs = []
        for seed in settings["seeds"]:
            if with_holdout:
                m, oracle = continuation(
                    data, x, config, events, fresh, variant, queue_config, analyst, seed
                )
                m = {k: v for k, v in m.items() if k != "available_ids"}
            else:
                per_month, m, _, _, _, oracle = development(
                    data, x, config, events, variant, queue_config, analyst, seed
                )
                m["timely_ids"] = month_ids(per_month, "timely_ids")
            runs.append({"seed": seed, "verdict_errors": oracle.errors, **m})
            print(analyst["name"], seed, m["timely_incidents"], m["admissions"], flush=True)
        results[analyst["name"]] = runs
    saved = {"config": config, "config_sha256": fingerprint(config), "analysts": results}
    if with_holdout:
        out.mkdir(exist_ok=True)
        save_json(out / "result.json", {**saved, "previous_holdout_uses": previous})
    else:
        out = directory(root) / "feedback-robustness"
        out.mkdir(exist_ok=True)
        save_json(out / "results.json", saved)
    write_report(root)
    return results


def month_ids(per_month, key):
    """Incident ids qualified by month, the unit counted in development totals."""
    return [m + ":" + i for m, r in per_month.items() for i in r[key]]


def paired(a, b):
    """Incidents reached by only one of two systems and an exact two-sided sign test."""
    a, b = set(a), set(b)
    only_a, only_b = len(a - b), len(b - a)
    p = binomtest(only_a, only_a + only_b).pvalue if only_a + only_b else 1.0
    return only_a, only_b, p


def wilson(k, n):
    interval = binomtest(k, n).proportion_ci(method="wilson")
    return f"{k / n:.2f} [{interval.low:.2f}, {interval.high:.2f}]"


def spread(values):
    return f"{np.mean(values):.1f} ({min(values)}-{max(values)})"


def fold_reference(root, output, candidate):
    """Per-fold timely incidents of a backtest candidate, averaged over seeds."""
    per = {}
    for r in json.loads((directory(root) / output / "results.json").read_text())["runs"]:
        if r["candidate"] == candidate:
            per.setdefault(r["fold"], []).append(r["timely_incidents"])
    return {fold: float(np.mean(v)) for fold, v in per.items()}


def holdout_reference(root, stage, scorer):
    runs = json.loads((directory(root) / stage / "result.json").read_text())["runs"]
    r = next(r for r in runs if r["name"] == scorer)
    return {
        "admissions": r["admissions"],
        "current_positive": r["current_positive"],
        "timely_incidents": r["timely_incidents"],
        "incidents_available": r["incidents_available"],
        "timely_fresh_incidents": r["timely_fresh_incidents"],
        "fresh_incidents_available": r["fresh_incidents_available"],
        "timely_ids": sorted(r["timely_hits"]),
    }


def holdout_row(label, m):
    return (
        f"| {label} | {m['admissions']} | {m['current_positive']} | "
        f"{m['current_positive'] / m['admissions']:.2f} | "
        f"{m['timely_incidents']}/{m['incidents_available']} | "
        f"{m['timely_fresh_incidents']}/{m['fresh_incidents_available']} |"
    )


def write_report(root=ROOT):
    saved = json.loads((directory(root) / "feedback/results.json").read_text())
    config, results = saved["config"], saved["variants"]
    month_list = [m for m, _ in months(config["start"], config["end"])]
    lines = [
        "# Analyst-feedback learning",
        "",
        "Starts with no labels: the detector is the label-free `ecod_up_top5` score. After each daily "
        "decision, the simulated analyst labels only the admitted investigation (positive if its trigger "
        "records contain a labelled malicious record), and the per-input rarity weights are refit with an "
        "L2 pull toward the label-free prior. One continuous queue runs August-November 2010 with one "
        "admission per day. `none` is the same harness without learning.",
        "",
        "Timely incidents per month (incidents with a labelled record presented within 72 hours):",
        "",
        "| Variant | "
        + " | ".join(month_list)
        + " | Total | Admissions | Current + | Yield | Labels (positive) |",
        "| --- | "
        + " | ".join("---:" for _ in month_list)
        + " | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, r in results.items():
        t = r["totals"]
        lines.append(
            f"| {name} | "
            + " | ".join(
                f"{r['months'][m]['timely_incidents']}/{r['months'][m]['incidents_available']}"
                for m in month_list
            )
            + f" | {t['timely_incidents']}/{t['incidents_available']} | {t['admissions']} | "
            f"{t['current_positive']} | {t['current_positive'] / t['admissions']:.2f} | "
            f"{r['labels']} ({r['positive_labels']}) |"
        )
    for label, ref in [
        (
            "reference: label-free ecod_up_top5 (fold backtest)",
            fold_reference(root, "backtest-unsupervised", "ecod_up_top5"),
        ),
        (
            "reference: supervised RF (fold backtest, 3-seed mean)",
            fold_reference(root, "backtest", "deployed_recipe"),
        ),
    ]:
        lines.append(
            f"| {label} | "
            + " | ".join(f"{ref.get(m, float('nan')):.1f}" for m in month_list)
            + f" | {sum(ref.values()):.1f} | | | | |"
        )
    lines += [
        "",
        "Reference rows come from the fold backtests, which reset the queue each month and refit on "
        "earlier folds; they indicate scale, while the `none` row is the like-for-like control.",
        "",
        "## What feedback learned (largest final weights)",
        "",
    ]
    for name, r in results.items():
        if r["lambda"] is not None:
            top = ", ".join(f"{k} {w:.2f}" for k, w in r["top_weights"])
            lines.append(f"- {name}: {top}")
    control = results["none"]
    lines += [
        "",
        "## Statistical check",
        "",
        "Paired by incident-month against the no-learning control: incidents reached by only one "
        "system, with an exact two-sided sign test. Yield intervals are 95% Wilson intervals. "
        "Two lambda values were tried, so a single p near 0.05 is weak evidence.",
        "",
        "| Variant | Only this variant | Only control | Sign-test p | Yield [95% CI] |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for name, r in results.items():
        t = r["totals"]
        if r["lambda"] is None:
            only = "| | |"
        else:
            a, b, p = paired(
                month_ids(r["months"], "timely_ids"), month_ids(control["months"], "timely_ids")
            )
            only = f"{a} | {b} | {p:.3f} |"
        lines.append(f"| {name} | {only} {wilson(t['current_positive'], t['admissions'])} |")
    noisy = directory(root) / "feedback-robustness/results.json"
    if noisy.exists():
        lines += robustness_section(json.loads(noisy.read_text()), control)
    continuation = directory(root) / "holdout-feedback/result.json"
    if continuation.exists():
        held = json.loads(continuation.read_text())
        lines += [
            "",
            "## Exploratory holdout continuation",
            "",
            "The same online learner continues from August 2010 through 2011-05-16; metrics cover "
            "December-May only. Holdout labels enter only as verdicts on admitted cases, as an analyst "
            "would provide them. **Exploratory reuse:** the holdout was already evaluated for "
            + ", ".join(held["previous_holdout_uses"])
            + ".",
            "",
            "| Variant | Admissions | Current + | Yield | Timely incidents | Fresh insiders |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        lines += [holdout_row(name, m) for name, m in held["variants"].items()]
        lines += [
            holdout_row(
                "reference: deployed supervised RF (sealed holdout)",
                holdout_reference(root, "holdout", "deployed (frozen, fit Jun-Oct)"),
            ),
            holdout_row(
                "reference: label-free ecod_up_top5 (exploratory holdout)",
                holdout_reference(root, "holdout-unsupervised", "ecod_up_top5"),
            ),
        ]
        rf = holdout_reference(root, "holdout", "deployed (frozen, fit Jun-Oct)")
        lines += [
            "",
            "Paired against the deployed RF on the same holdout incidents; RF yield "
            f"{wilson(rf['current_positive'], rf['admissions'])}:",
            "",
            "| Variant | Only this variant | Only RF | Sign-test p | Yield [95% CI] |",
            "| --- | ---: | ---: | ---: | --- |",
        ]
        for name, m in held["variants"].items():
            a, b, p = paired(m["timely_ids"], rf["timely_ids"])
            lines.append(
                f"| {name} | {a} | {b} | {p:.3f} | "
                f"{wilson(m['current_positive'], m['admissions'])} |"
            )
        noisy = directory(root) / "holdout-feedback-robustness/result.json"
        if noisy.exists():
            lines += robustness_holdout_section(json.loads(noisy.read_text()), rf)
    lines.append("")
    (root / "reports/FEEDBACK.md").write_text("\n".join(lines))


def robustness_section(saved, control):
    settings = saved["config"]["robustness"]
    c = control["totals"]
    lines = [
        "",
        "## Imperfect analyst",
        "",
        f"lambda = {settings['lambda']} with {len(settings['seeds'])} seeds per analyst. `flip` "
        "inverts any verdict with that probability; `miss` labels a true positive negative. "
        "Evaluation still uses the answer key. Values are mean (min-max) over seeds; the "
        f"no-learning control reached {c['timely_incidents']}/{c['incidents_available']} with "
        f"yield {c['current_positive'] / c['admissions']:.2f}.",
        "",
        "| Analyst | Wrong verdicts | Timely incidents | Admissions | Yield | "
        "Seeds beating control |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, runs in saved["analysts"].items():
        yields = [r["current_positive"] / r["admissions"] for r in runs]
        beats = sum(
            r["timely_incidents"] > c["timely_incidents"]
            and r["current_positive"] / r["admissions"] >= c["current_positive"] / c["admissions"]
            for r in runs
        )
        lines.append(
            f"| {name} | {spread([r['verdict_errors'] for r in runs])} | "
            f"{spread([r['timely_incidents'] for r in runs])} | "
            f"{spread([r['admissions'] for r in runs])} | {np.mean(yields):.2f} | "
            f"{beats}/{len(runs)} |"
        )
    return lines


def robustness_holdout_section(saved, rf):
    lines = [
        "",
        "Imperfect analysts over the holdout continuation (exploratory reuse; previously used for "
        + ", ".join(saved["previous_holdout_uses"])
        + f"). The deployed RF reached {rf['timely_incidents']}/{rf['incidents_available']} "
        f"incidents and {rf['timely_fresh_incidents']}/{rf['fresh_incidents_available']} fresh "
        f"insiders with {rf['admissions']} investigations.",
        "",
        "| Analyst | Timely incidents | Fresh insiders | Admissions | Yield |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, runs in saved["analysts"].items():
        lines.append(
            f"| {name} | {spread([r['timely_incidents'] for r in runs])} | "
            f"{spread([r['timely_fresh_incidents'] for r in runs])} | "
            f"{spread([r['admissions'] for r in runs])} | "
            f"{np.mean([r['current_positive'] / r['admissions'] for r in runs]):.2f} |"
        )
    return lines
