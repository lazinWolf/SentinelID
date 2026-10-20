"""Rolling development backtest and a once-only sealed holdout evaluation.

Development uses June-November 2010 labels. The December 2010 - May 2011 holdout
shard is scored only by `holdout`, which loads its labels after every model is
frozen and refuses to run twice.
"""

import json
import sqlite3
import zlib
from collections import defaultdict, deque
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    IsolationForest,
    RandomForestClassifier,
)
from sklearn.metrics import average_precision_score

from .experiment_evaluation import evaluate
from .experiment_features import TEMPORAL, corrected, measurements, vector
from .experiment_io import digest, fingerprint, save_json
from .experiment_queue import ExperimentQueue
from .features import PEER
from .ingestion import ROOT
from .pipeline import matrix
from .research_data import DEVELOPMENT_END, cached_rows, extract, truth

ARCHIVE_ROWS = "data/experiments/inputs/features.sqlite"
ANSWERS = "data/experiments/inputs/answers.tar.bz2"
HOLDOUT_START = "2010-12-01"
HOLDOUT_END = "2011-05-17"
FEATURE_SETS = ("v4", "c", "c_peer", "c_temporal", "c_temporal_peer")


def directory(root=ROOT):
    path = root / "data/research"
    path.mkdir(parents=True, exist_ok=True)
    return path


def day_after(day, n=1):
    return (date.fromisoformat(day) + timedelta(days=n)).isoformat()


# ---------------------------------------------------------------------------
# Preparation: one vector cache for development and holdout rows.


def extract_holdout(root=ROOT):
    """v4 rows for the holdout; 47 warm-up days make December rows fully causal."""
    path = directory(root) / "holdout-rows.sqlite"
    if path.exists():
        return path
    print("Extracting holdout rows from original records", flush=True)
    result = extract(datetime(2010, 10, 15), datetime(2011, 5, 17), path, root=root)
    save_json(path.with_suffix(".json"), {**result, "sha256": digest(path)})
    return path


def check_extraction(root=ROOT, start="2010-11-26"):
    """Rows rebuilt from originals must equal the archived cache once history is warm."""
    archived = {
        (r["day"], r["identity_id"]): r
        for r in cached_rows(root / ARCHIVE_ROWS, start, DEVELOPMENT_END)
    }
    rebuilt = list(cached_rows(directory(root) / "holdout-rows.sqlite", start, DEVELOPMENT_END))
    if len(rebuilt) != len(archived):
        raise ValueError("Extraction row count differs from archive")

    def comparable(row):
        # Both depend on the replay start date, not on behavior; neither is a model input.
        row = json.loads(json.dumps(row))
        row.pop("original_events_through_day", None)
        row.pop("historical_control_eligible", None)
        for value in row["eligibility"].values():
            value.pop("calendar_history", None)
        return row

    for r in rebuilt:
        if comparable(archived[(r["day"], r["identity_id"])]) != comparable(r):
            raise ValueError("Extraction differs from archive: " + r["day"] + "/" + r["identity_id"])
    return len(rebuilt)


def prepare(root=ROOT):
    out = directory(root) / "prepared"
    marker = out / "prepared.json"
    if marker.exists():
        return out
    out.mkdir(exist_ok=True)
    labels = truth(root / ANSWERS, "2010-06-01", DEVELOPMENT_END)
    columns = defaultdict(list)
    names = {}
    events = out / "events.sqlite"
    events.unlink(missing_ok=True)
    with closing(sqlite3.connect(events)) as db:
        db.execute(
            "CREATE TABLE rows(day TEXT,identity TEXT,score_timestamp TEXT,families TEXT,"
            "event_ids BLOB,PRIMARY KEY(identity,day))"
        )

        def source():
            yield from cached_rows(root / ARCHIVE_ROWS, "2010-06-01", DEVELOPMENT_END)
            yield from cached_rows(
                directory(root) / "holdout-rows.sqlite", DEVELOPMENT_END, HOLDOUT_END
            )

        daily = {}
        age = deque()
        for row in source():
            key = (row["identity_id"], row["day"])
            daily[key] = {"counts": row["counts"], "event_ids": row["event_ids"]}
            age.append(key)
            cutoff = day_after(row["day"], -6)
            while age and age[0][1] < cutoff:
                daily.pop(age.popleft(), None)
            db.execute(
                "INSERT INTO rows VALUES(?,?,?,?,?)",
                (
                    row["day"],
                    row["identity_id"],
                    row["score_timestamp"],
                    json.dumps(row["qualifying_families"]),
                    zlib.compress(json.dumps(row["event_ids"]).encode()),
                ),
            )
            if not row["common_eligible"] or row["day"] < "2010-06-08":
                continue
            fixed = corrected(row, daily)
            t, p = measurements(fixed, daily)
            v4, names["v4"] = matrix([row], "PM")
            pm, names["c"] = vector(fixed, t, p)
            columns["day"].append(row["day"])
            columns["identity"].append(row["identity_id"])
            columns["v4"].append(v4[0])
            columns["c"].append(pm)
            columns["temporal"].append([t.measurements()[k] for k in TEMPORAL])
            columns["peer"].append([p.measurements()[k] for k in PEER])
            # Holdout labels stay sealed: -1 until the once-only holdout evaluation.
            columns["label"].append(
                int(any(e in labels for e in row["event_ids"]))
                if row["day"] < DEVELOPMENT_END
                else -1
            )
        db.commit()
    np.savez_compressed(out / "vectors.npz", **{k: np.asarray(v) for k, v in columns.items()})
    save_json(
        marker,
        {
            "rows": len(columns["day"]),
            "development_rows": int(sum(d < DEVELOPMENT_END for d in columns["day"])),
            "holdout_rows": int(sum(d >= DEVELOPMENT_END for d in columns["day"])),
            "names": names,
            "vectors_sha256": digest(out / "vectors.npz"),
            "labels": "Development labels only; holdout rows carry -1",
        },
    )
    return out


class Data:
    def __init__(self, root=ROOT):
        self.path = prepare(root)
        meta = json.loads((self.path / "prepared.json").read_text())
        with np.load(self.path / "vectors.npz") as f:
            self.v = {k: f[k] for k in f.files}
        self.days = self.v["day"]
        self.names = meta["names"]
        self.events = sqlite3.connect(
            "file:" + str((self.path / "events.sqlite").resolve()) + "?mode=ro", uri=True
        )

    def features(self, kind):
        base = "v4" if kind == "v4" else "c"
        parts = [self.v[base]]
        names = list(self.names[base])
        if "temporal" in kind:
            parts.append(self.v["temporal"])
            names += ["temporal:" + k for k in TEMPORAL]
        if "peer" in kind:
            parts.append(self.v["peer"])
            names += PEER
        return np.concatenate(parts, axis=1), names

    def row(self, i, with_events=False):
        day, identity = str(self.days[i]), str(self.v["identity"][i])
        stamp, families, ids = self.events.execute(
            "SELECT score_timestamp,families,event_ids FROM rows WHERE identity=? AND day=?",
            (identity, day),
        ).fetchone()
        return {
            "day": day,
            "identity_id": identity,
            "score_timestamp": stamp,
            "qualifying_families": json.loads(families),
            "event_ids": json.loads(zlib.decompress(ids)) if with_events else [],
        }

    def context(self, identity, day):
        ids = set()
        for (blob,) in self.events.execute(
            "SELECT event_ids FROM rows WHERE identity=? AND day>? AND day<=?",
            (identity, day_after(day, -7), day),
        ):
            ids.update(json.loads(zlib.decompress(blob)))
        return sorted(ids)


# ---------------------------------------------------------------------------
# Models, queue replay and evaluation.


CHANNELS = (
    "usb_active",
    "usb",
    "copy",
    "after_hours",
    "logon",
    "external_email",
    "message_bytes",
    "attachments",
    "http",
    "new_recipient",
    "new_domain",
    "new_host",
    "timing",
    "new_computer",
)


def channel(name):
    """Behavioral channel of an input; horizons and representations of one channel share it."""
    base = name.split(":")[-1]
    prefix = "peer_" if base.startswith("peer_") else ""
    base = base.removeprefix("peer_")
    return prefix + next((k for k in CHANNELS if base.startswith(k)), base)


class TailScorer:
    """Label-free ECOD-style score from the upper-tail rarity of each input.

    `top` keeps only the strongest rarities. With `names`, each behavioral channel
    contributes its single strongest rarity, so one behavior is not counted per horizon.
    """

    def __init__(self, top=None, names=None):
        self.top = top
        self.channels = None
        if names is not None:
            labels = [channel(n) for n in names]
            self.channels = [
                [j for j, c in enumerate(labels) if c == k] for k in dict.fromkeys(labels)
            ]

    def fit(self, x):
        self.columns = np.sort(x, axis=0)
        return self

    def score_samples(self, x):
        n = len(self.columns)
        rarity = np.column_stack(
            [
                -np.log((n - np.searchsorted(c, x[:, j], side="left") + 1) / (n + 1))
                for j, c in enumerate(self.columns.T)
            ]
        )
        if self.channels:
            rarity = np.column_stack([rarity[:, group].max(axis=1) for group in self.channels])
        if self.top:
            rarity = np.sort(rarity, axis=1)[:, -self.top :]
        return -rarity.sum(axis=1)


class ByDayType:
    """Separate label-free references for weekend and weekday identity-days."""

    def __init__(self, build, x, weekend):
        self.models = {flag: build().fit(x[weekend == flag]) for flag in (False, True)}

    def score_samples(self, x, weekend):
        result = np.empty(len(x))
        for flag, model in self.models.items():
            result[weekend == flag] = model.score_samples(x[weekend == flag])
        return result


def weekends(days):
    return np.asarray([date.fromisoformat(str(d)).weekday() >= 5 for d in days])


# Data-movement channels; email content-volume inputs are excluded by channel, not by score.
MOVEMENT = ("usb", "copy", "logon", "after_hours", "http", "timing_novel", "new_computer", "new_host")


def design(data, candidate):
    """Candidate inputs: optional upward-only percentiles and channel subset."""
    x, names = data.features(candidate["features"])
    if candidate.get("transform") == "up":
        x = x.copy()
        for j, name in enumerate(names):
            if name.startswith("percentile:") or name.startswith("peer_") and "percentile" in name:
                x[:, j] = np.maximum(0.0, x[:, j])
    if candidate.get("subset") == "movement":
        keep = [
            j
            for j, name in enumerate(names)
            if name == "peer_supported"
            or any(k in name for k in MOVEMENT)
            or name.startswith("temporal:")
            or name in ("peer_usb_percentile", "peer_copy_percentile")
        ]
        x, names = x[:, keep], [names[j] for j in keep]
    return x, names


def detector(kind, seed, names=None):
    """Unfitted label-free detector: if[256|200], ecod, ecod_top<k>, ecodc[<k>]."""
    if kind.startswith("if"):
        return IsolationForest(
            n_estimators=200 if kind.endswith("200") else 100,
            max_samples=256 if "256" in kind else 1024,
            random_state=seed,
            n_jobs=-1,
        )
    if kind.startswith("ecodc"):
        return TailScorer(int(kind[5:]) if kind[5:] else None, names)
    if kind.startswith("ecod"):
        return TailScorer(int(kind[8:]) if kind.startswith("ecod_top") else None)
    raise ValueError("Unknown model: " + kind)


def fit(kind, x, y, seed, names=None, weekend=None):
    if kind.endswith("_wk"):
        base = kind.removesuffix("_wk")
        return ByDayType(lambda: detector(base, seed, names), x, weekend)
    if kind.startswith("rf"):
        trees = int(kind[2:] or 100)
        return RandomForestClassifier(
            n_estimators=trees,
            max_depth=8,
            min_samples_leaf=3,
            class_weight="balanced_subsample",
            random_state=seed,
            n_jobs=-1,
        ).fit(x, y)
    if kind == "hgb":
        return HistGradientBoostingClassifier(
            max_depth=4,
            learning_rate=0.05,
            max_iter=300,
            min_samples_leaf=20,
            l2_regularization=1.0,
            class_weight="balanced",
            random_state=seed,
        ).fit(x, y)
    return detector(kind, seed, names).fit(x)


def score(model, x, weekend=None):
    if isinstance(model, ByDayType):
        return -model.score_samples(x, weekend)
    if isinstance(model, IsolationForest | TailScorer):
        return -model.score_samples(x)
    return model.predict_proba(x)[:, 1]


class ResearchQueue(ExperimentQueue):
    """Maintained admission policy with an optional persistence-aware ordering."""

    def __init__(self, config, variant, rank="max"):
        super().__init__(config, variant)
        if rank not in ("max", "sum", "count"):
            raise ValueError("Unknown ranking: " + rank)
        self.rank = rank

    def rank_key(self, candidate):
        scores = [h["score"] for h in candidate["score_history"]]
        primary = {"max": max(scores), "sum": sum(scores), "count": len(scores)}[self.rank]
        return (-primary, -max(scores), candidate["available_time"], candidate["identity_id"])


def queue_settings(candidate, queue_config):
    return {**queue_config, **candidate.get("queue", {})}, candidate.get("rank", "max")


def replay(data, indices, scores, gate, start, end, policy, queue_config, rank="max"):
    """Admissions through the maintained queue, plus the declared drain."""
    queue = ResearchQueue(queue_config, policy, rank)
    by_day = defaultdict(list)
    for i, s in zip(indices, scores, strict=True):
        if s >= gate:
            by_day[str(data.days[i])].append((i, float(s)))
    days = (date.fromisoformat(end) - date.fromisoformat(start)).days
    for n in range(days + queue_config["backlog_days"]):
        day = day_after(start, n)
        for i, s in by_day.get(day, []):
            row = data.row(i, with_events=True)
            queue.offer(
                {
                    "detector": "research",
                    "identity_id": row["identity_id"],
                    "day": day,
                    "available_time": row["score_timestamp"],
                    "score": s,
                    "detector_score": s,
                    "priority_score": s,
                    "trigger_ids": row["event_ids"],
                    "evidence_ids": data.context(row["identity_id"], day),
                    "qualifying_families": row["qualifying_families"],
                }
            )
        queue.decide(day_after(day) + "T%02d:00:00" % queue_config["decision_hour"])
    return queue


def measure(data, indices, scores, gate, queue, events, start, end):
    positives = {(t["day"], t["observed_account"]) for t in events.values()}
    rows = [
        data.row(i, with_events=(str(data.days[i]), str(data.v["identity"][i])) in positives)
        for i in indices
    ]
    protocol = {"evaluation_start": start, "evaluation_end": end, "timely_hours": 72}
    result, losses = evaluate(rows, scores, scores, gate, queue, events, protocol)
    for k in ("candidate_keys", "admission_keys", "priority_ranking", "detector_ranking"):
        result.pop(k)
    return result, losses


def self_calibrate(data, indices, raw, statistic, days=28):
    """Subtract each identity's own recent score level (prior days only, label-free)."""
    level = {"user_median": 0.5, "user_q90": 0.9}[statistic]
    history = defaultdict(deque)
    adjusted = np.empty(len(indices))
    for k in np.argsort(data.days[indices], kind="stable"):
        i = indices[k]
        day, identity = str(data.days[i]), str(data.v["identity"][i])
        past = history[identity]
        while past and past[0][0] < day_after(day, -days):
            past.popleft()
        adjusted[k] = raw[k] - (np.quantile([v for _, v in past], level) if past else 0.0)
        past.append((day, raw[k]))
    return adjusted


def window(data, start, end):
    return np.flatnonzero((data.days >= start) & (data.days < end))


# ---------------------------------------------------------------------------
# Development backtest.


def backtest(config_path, root=ROOT):
    config = json.loads(Path(config_path).read_text())
    data = Data(root)
    queue_config = json.loads((root / "config.json").read_text())["queue"]
    folds = config["folds"]
    truths = {
        f["start"]: truth(root / ANSWERS, day_after(f["start"], -7), f["end"]) for f in folds
    }
    for events in truths.values():
        if any(t["day"] >= DEVELOPMENT_END for t in events.values()):
            raise ValueError("Backtest folds must stay inside development")
    results = []
    for candidate in config["candidates"]:
        x, names = design(data, candidate)
        weekend = weekends(data.days)
        unsupervised = candidate["model"].startswith(("if", "ecod"))
        # The tail scorer is deterministic; one seed suffices.
        seeds = config["seeds"][:1] if candidate["model"].startswith("ecod") else config["seeds"]
        for seed in seeds:
            for f in folds:
                train = window(data, config["fit_start"], f["start"])
                test = window(data, f["start"], f["end"])
                y = data.v["label"][train]
                if (y < 0).any():
                    raise ValueError("Sealed label in development training")
                model = fit(
                    candidate["model"],
                    x[train],
                    None if unsupervised else y,
                    seed,
                    names,
                    weekend[train],
                )
                if candidate.get("calibrate"):
                    seen = np.concatenate([train, test])
                    both = self_calibrate(
                        data, seen, score(model, x[seen], weekend[seen]), candidate["calibrate"]
                    )
                    fitted, s = both[: len(train)], both[len(train) :]
                else:
                    fitted, s = score(model, x[train], weekend[train]), score(
                        model, x[test], weekend[test]
                    )
                gate = float(np.quantile(fitted, config["gate_quantile"]))
                settings, rank = queue_settings(candidate, queue_config)
                queue = replay(
                    data, test, s, gate, f["start"], f["end"], candidate["policy"], settings, rank
                )
                metrics, _ = measure(
                    data, test, s, gate, queue, truths[f["start"]], f["start"], f["end"]
                )
                results.append(
                    {"candidate": candidate["name"], "seed": seed, "fold": f["start"], **metrics}
                )
                print(
                    candidate["name"],
                    seed,
                    f["start"],
                    "adm",
                    metrics["admissions"],
                    "cur+",
                    metrics["current_positive"],
                    "timely",
                    f"{metrics['timely_incidents']}/{metrics['incidents_available']}",
                    flush=True,
                )
    summary = summarize(config, results)
    out = directory(root) / config.get("output", "backtest")
    out.mkdir(exist_ok=True)
    save_json(out / "results.json", {"config": config, "runs": results, "summary": summary})
    save_json(
        out / "selection.json",
        {
            "selected": summary["selected"],
            "baseline": config["baseline"],
            "rule": config["selection_rule"],
            "config_sha256": fingerprint(config),
            "vectors_sha256": json.loads((data.path / "prepared.json").read_text())[
                "vectors_sha256"
            ],
        },
    )
    write_report(root / config.get("report", "reports/BACKTEST.md"), config, summary)
    return summary


def summarize(config, results):
    table = {}
    for candidate in config["candidates"]:
        runs = [r for r in results if r["candidate"] == candidate["name"]]
        per_seed = defaultdict(lambda: defaultdict(float))
        for r in runs:
            for k in ("admissions", "current_positive", "timely_incidents", "incidents_available"):
                per_seed[r["seed"]][k] += r[k]
        seeds = list(per_seed.values())

        def stat(k, seeds=seeds):
            values = [s[k] for s in seeds]
            return {"mean": float(np.mean(values)), "min": min(values), "max": max(values)}

        table[candidate["name"]] = {
            **candidate,
            "admissions": stat("admissions"),
            "current_positive": stat("current_positive"),
            "timely_incidents": stat("timely_incidents"),
            "incidents_available": seeds[0]["incidents_available"],
            "current_positive_yield": float(
                np.mean([s["current_positive"] / s["admissions"] for s in seeds])
            ),
            "detector_average_precision": float(
                np.mean([r["detector_average_precision"] for r in runs])
            ),
            "gate_recall": float(np.mean([r["gate_recall"] for r in runs])),
        }
    base = table[config["baseline"]]
    eligible = [
        t
        for t in table.values()
        if t["admissions"]["mean"] <= base["admissions"]["mean"]
        and t["current_positive_yield"] >= base["current_positive_yield"]
    ]
    best = max(
        eligible,
        key=lambda t: (t["timely_incidents"]["mean"], t["current_positive_yield"]),
    )
    return {"candidates": table, "selected": best["name"]}


def policy_label(candidate):
    parts = [candidate["policy"], "rank=" + candidate.get("rank", "max")]
    parts += [f"{k}={v}" for k, v in candidate.get("queue", {}).items()]
    return ", ".join(parts)


def write_report(path, config, summary):
    lines = [
        "# Development backtest",
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
        f"**Selected for the sealed holdout: `{summary['selected']}`.**",
        "",
    ]
    path.parent.mkdir(exist_ok=True)
    path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Once-only sealed holdout.


def holdout(root=ROOT, seeds=(0, 1, 2, 3, 4), output="backtest"):
    """Once per backtest configuration; any configuration after the first is a reuse."""
    stage = "holdout" + output.removeprefix("backtest")
    out = directory(root) / stage
    result_path = out / "result.json"
    if result_path.exists():
        raise ValueError("The sealed holdout was already evaluated: " + str(result_path))
    selection = json.loads((directory(root) / output / "selection.json").read_text())
    config = json.loads((directory(root) / output / "results.json").read_text())["config"]
    previous = sorted(
        str(p.relative_to(directory(root)))
        for p in directory(root).glob("holdout*/result.json")
    )
    if fingerprint(config) != selection["config_sha256"]:
        raise ValueError("Backtest configuration changed after selection")
    data = Data(root)
    queue_config = json.loads((root / "config.json").read_text())["queue"]
    candidates = {c["name"]: c for c in config["candidates"]}
    train = window(data, config["fit_start"], DEVELOPMENT_END)
    test = window(data, HOLDOUT_START, HOLDOUT_END)
    # Fit and freeze every scorer before any holdout label is read.
    frozen = []
    deployed = joblib.load(root / "data/model.joblib")
    x4, names = data.features("v4")
    if names != deployed["names"]:
        raise ValueError("Deployed model inputs differ from the v4 vectors")
    frozen.append(
        {
            "name": "deployed (frozen, fit Jun-Oct)",
            "role": "primary",
            "policy": "max_cooldown",
            "queue": queue_config,
            "rank": "max",
            "gate": float(deployed["gates"]["fit"]),
            "scores": deployed["model"].predict_proba(x4[test])[:, 1],
        }
    )
    roles = {selection["baseline"]: "primary", selection["selected"]: "primary"}
    for name in config.get("holdout_secondary", []):
        roles.setdefault(name, "secondary")
    for name, role in roles.items():
        c = candidates[name]
        x, names = design(data, c)
        weekend = weekends(data.days)
        for seed in seeds:
            model = fit(
                c["model"], x[train], data.v["label"][train], seed, names, weekend[train]
            )
            if c.get("calibrate"):
                seen = np.concatenate([train, test])
                both = self_calibrate(
                    data, seen, score(model, x[seen], weekend[seen]), c["calibrate"]
                )
                fitted, held = both[: len(train)], both[len(train) :]
            else:
                fitted, held = score(model, x[train], weekend[train]), score(
                    model, x[test], weekend[test]
                )
            frozen.append(
                {
                    "name": name,
                    "role": role,
                    "seed": seed,
                    "policy": c["policy"],
                    "queue": queue_settings(c, queue_config)[0],
                    "rank": c.get("rank", "max"),
                    "gate": float(np.quantile(fitted, config["gate_quantile"])),
                    "scores": held,
                }
            )
    out.mkdir(exist_ok=True)
    np.savez_compressed(out / "frozen-scores.npz", *[f["scores"] for f in frozen])
    save_json(
        out / "freeze.json",
        {
            "selection": selection,
            "scorers": [{k: v for k, v in f.items() if k != "scores"} for f in frozen],
            "scores_sha256": digest(out / "frozen-scores.npz"),
            "frozen_at": datetime.now().isoformat(),
        },
    )
    events = truth(root / ANSWERS, day_after(HOLDOUT_START, -7), HOLDOUT_END)
    fresh = {
        t["incident_id"] for t in events.values() if t["official_start"] >= HOLDOUT_START
    }
    runs = []
    for f in frozen:
        queue = replay(
            data,
            test,
            f["scores"],
            f["gate"],
            HOLDOUT_START,
            HOLDOUT_END,
            f["policy"],
            f["queue"],
            f["rank"],
        )
        metrics, _ = measure(
            data, test, f["scores"], f["gate"], queue, events, HOLDOUT_START, HOLDOUT_END
        )
        metrics["timely_fresh_incidents"] = sum(k in fresh for k in metrics["timely_hits"])
        metrics["fresh_incidents_available"] = len(fresh)
        runs.append({k: v for k, v in f.items() if k != "scores"} | metrics)
        print(
            f["name"],
            f.get("seed", ""),
            "adm",
            metrics["admissions"],
            "cur+",
            metrics["current_positive"],
            "timely",
            f"{metrics['timely_incidents']}/{metrics['incidents_available']}",
            "fresh",
            f"{metrics['timely_fresh_incidents']}/{len(fresh)}",
            flush=True,
        )
    save_json(
        result_path,
        {
            "runs": runs,
            "holdout": [HOLDOUT_START, HOLDOUT_END],
            "backtest": output,
            "previous_holdout_uses": previous,
        },
    )
    write_holdout_report(root, stage)
    return runs


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
    suffix = stage.removeprefix("holdout").upper()
    (root / f"reports/HOLDOUT{suffix}.md").write_text("\n".join(lines))
