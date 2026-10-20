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
from scipy.optimize import minimize
from scipy.special import expit

from .experiment_evaluation import evaluate
from .experiment_io import fingerprint, save_json
from .ingestion import ROOT
from .research import (
    ANSWERS,
    HOLDOUT_END,
    HOLDOUT_START,
    Data,
    ResearchQueue,
    TailScorer,
    day_after,
    design,
    directory,
    window,
)
from .research_data import truth

TOP = 5


def components(scorer, x):
    """34 non-negative components: 33 rarities plus the top-5 rarity sum (the prior)."""
    rarity = scorer.rarity(x)
    return np.column_stack([rarity, np.sort(rarity, axis=1)[:, -TOP:].sum(axis=1)])


def prior(width):
    w = np.zeros(width)
    w[-1] = 1.0
    return w


class FeedbackModel:
    """Non-negative weights anchored to the label-free prior; lam=None disables learning."""

    def __init__(self, width, lam):
        self.w0 = prior(width)
        self.w = self.w0.copy()
        self.b = 0.0
        self.lam = lam

    def score(self, z):
        return z @ self.w

    def update(self, z, y):
        if self.lam is None or not len(y):
            return
        y = np.asarray(y, dtype=float)

        def objective(theta):
            w, b = theta[:-1], theta[-1]
            margin = y * (z @ w - b)
            loss = np.logaddexp(0.0, -margin).sum() + self.lam * np.sum((w - self.w0) ** 2)
            g = -y * expit(-margin)
            grad_w = z.T @ g + 2 * self.lam * (w - self.w0)
            return loss, np.append(grad_w, -g.sum())

        start = np.append(self.w, self.b)
        bounds = [(0.0, None)] * len(self.w) + [(None, None)]
        result = minimize(objective, start, jac=True, method="L-BFGS-B", bounds=bounds)
        self.w, self.b = result.x[:-1], float(result.x[-1])


class Oracle:
    """Simulated analyst: answers only for cases that were actually admitted."""

    def __init__(self, events):
        self.events = events
        self.asked = []

    def verdict(self, case):
        self.asked.append(case["case_id"])
        return 1 if set(case["trigger_ids"]) & self.events.keys() else -1


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
    keys = {(str(data.days[i]), str(data.v["identity"][i])): i for i in run}
    labelled, verdicts = [], []
    model = None
    trace = []
    days = (date.fromisoformat(end) - date.fromisoformat(start)).days
    for n in range(days + queue_config["backlog_days"]):
        day = day_after(start, n)
        if day < end and (model is None or day[8:] == "01"):
            # Monthly label-free reference refit on all prior rows.
            reference = window(data, reference_start, day)
            scorer = TailScorer().fit(x[reference])
            z_reference = components(scorer, x[reference])
            if model is None:
                model = FeedbackModel(z_reference.shape[1], lam)
            if labelled:
                model.update(components(scorer, x[labelled]), verdicts)
        gate = float(np.quantile(model.score(z_reference), gate_quantile))
        if day < end:
            today = run[data.days[run] == day]
            scores = model.score(components(scorer, x[today])) if len(today) else []
            for i, s in zip(today, scores, strict=True):
                margins[position[i]] = s - gate
                if s < gate:
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
        cases = queue.decide(day_after(day) + "T%02d:00:00" % queue_config["decision_hour"])
        for case in cases:
            y = oracle.verdict(case)
            for case_day in case["days"]:
                i = keys.get((case_day, case["identity_id"]))
                if i is not None:
                    labelled.append(i)
                    verdicts.append(y)
        if cases and labelled:
            model.update(components(scorer, x[labelled]), verdicts)
        trace.append({"day": day, "gate": gate, "labels": len(verdicts)})
    return queue, run, margins, model, trace


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
    }


DEFAULT_CONFIG = "configs/research-feedback.json"


def simulate(data, x, config, end, events, variant, queue_config):
    """One online run with a fresh analyst; verdicts must stay limited to admitted cases."""
    oracle = Oracle(events)
    queue, rows, margins, model, trace = online(
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
    return queue, rows, margins, model, trace


def setting(config_path, root):
    config = json.loads(Path(config_path).read_text())
    data = Data(root)
    x, names = design(data, {"features": "c", "transform": "up"})
    queue_config = json.loads((root / "config.json").read_text())["queue"]
    return config, data, x, names, queue_config


def run(config_path=DEFAULT_CONFIG, root=ROOT):
    config, data, x, names, queue_config = setting(config_path, root)
    start, end = config["start"], config["end"]
    events = truth(root / ANSWERS, day_after(start, -7), end)
    results = {}
    for variant in config["variants"]:
        queue, rows, margins, model, trace = simulate(
            data, x, config, end, events, variant, queue_config
        )
        per_month = {
            m: monthly(data, rows, margins, queue, events, m, e, end) for m, e in months(start, end)
        }
        totals = {
            k: sum(m[k] for m in per_month.values())
            for k in ("admissions", "current_positive", "timely_incidents", "incidents_available")
        }
        weights = sorted(
            zip(names + ["top5_sum"], model.w.tolist(), strict=True), key=lambda t: -t[1]
        )
        results[variant["name"]] = {
            "lambda": variant["lambda"],
            "months": per_month,
            "totals": totals,
            "labels": trace[-1]["labels"],
            "positive_labels": sum(
                1 for c in queue.reviews if set(c["trigger_ids"]) & events.keys()
            ),
            "top_weights": weights[:8],
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
    previous = sorted(
        str(p.relative_to(directory(root))) for p in directory(root).glob("holdout*/result.json")
    )
    config, data, x, _, queue_config = setting(config_path, root)
    events = truth(root / ANSWERS, day_after(config["start"], -7), HOLDOUT_END)
    fresh = {t["incident_id"] for t in events.values() if t["official_start"] >= HOLDOUT_START}
    results = {}
    for variant in config["variants"]:
        queue, rows, margins, _, _ = simulate(
            data, x, config, HOLDOUT_END, events, variant, queue_config
        )
        m = monthly(data, rows, margins, queue, events, HOLDOUT_START, HOLDOUT_END, HOLDOUT_END)
        m["timely_fresh_incidents"] = len(set(m["timely_ids"]) & fresh)
        m["fresh_incidents_available"] = len(fresh)
        results[variant["name"]] = m
        print(variant["name"], {k: v for k, v in m.items() if k != "timely_ids"}, flush=True)
    out.mkdir(exist_ok=True)
    save_json(
        out / "result.json",
        {"variants": results, "previous_holdout_uses": previous, "config": config},
    )
    write_report(root)
    return results


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
    lines.append("")
    (root / "reports/FEEDBACK.md").write_text("\n".join(lines))
