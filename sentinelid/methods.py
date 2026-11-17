"""Methods study (docs/methods-study.md): statistical, distribution, distance, neural, sequence
and graph detectors compared with the project's detectors on the development folds, under the
same gate and queue.

Development only: every row read is before 2010-12-01, and the holdout labels are never loaded.
"""

import json
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from datetime import date
from types import SimpleNamespace

import numpy as np
from sklearn.metrics import roc_auc_score

from . import research
from .adaptive import upward
from .detectors import (
    MAD_FLOOR,
    Copula,
    EdgeScorer,
    Graph,
    Histograms,
    SageScorer,
    causal_edge_scores,
    edge_scores,
    logistic,
    neighbour_scores,
    one_class_svm,
    robust_z,
    standardise,
)
from .detectors import gate as training_gate
from .experiment_io import save_json
from .ingestion import ROOT
from .reporting import write_methods_report
from .research_data import DEVELOPMENT_END, cached_rows, truth

FIT_START = "2010-06-08"
FOLDS = (
    ("2010-08-01", "2010-09-01"),
    ("2010-09-01", "2010-10-01"),
    ("2010-10-01", "2010-11-01"),
    ("2010-11-01", "2010-12-01"),
)
SEEDS = (0, 1, 2)
GATE_QUANTILE = 0.99
POLICY = "max_cooldown"
WINDOW = 14
RECALL_AT = (1, 2, 5, 10)
BASELINE = "rf"
CHANNELS = (
    "usb",
    "copy",
    "logon",
    "after_hours",
    "external_email",
    "message_bytes",
    "attachments",
    "http",
)
REFERENCE_DAYS = 28
REACH_RESAMPLES, AP_RESAMPLES = 2000, 1000


# ---------------------------------------------------------------------------
# Inputs: sequence windows and the identity graph.


def lags(days, identities, window=WINDOW):
    """Row index of each row's identity on each of the `window` days ending today, else -1.

    Column `window - 1` is today; earlier columns look back one calendar day each. Only the
    same or earlier days are ever referenced.
    """
    codes = np.unique(identities, return_inverse=True)[1].astype(np.int64)
    ordinal = np.asarray([date.fromisoformat(str(d)).toordinal() for d in days], dtype=np.int64)
    key = codes * 1_000_000 + ordinal
    order = np.argsort(key, kind="stable")
    ordered = key[order]
    out = np.full((len(key), window), -1, dtype=np.int64)
    for column in range(window):
        wanted = key - (window - 1 - column)
        position = np.minimum(np.searchsorted(ordered, wanted), len(ordered) - 1)
        out[:, column] = np.where(ordered[position] == wanted, order[position], -1)
    return out


def windows(z, lagged):
    """`make(positions)` for rows with `lagged` indices: standardised inputs plus presence."""

    def make(positions):
        index = lagged[positions]
        present = index >= 0
        out = np.zeros((*index.shape, z.shape[1] + 1), dtype=np.float32)
        out[present, : z.shape[1]] = z[index[present]]
        out[..., -1] = present
        return out

    return make


def ledger_edges(root, start, end):
    """{(day, identity): [node]} from the label-free ledger: computers and web domains."""
    path = research.directory(root) / "ledger" / "ledger.sqlite"
    if not path.exists():
        raise FileNotFoundError("Run `python -m sentinelid research ledger` first")
    edges = defaultdict(list)
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as db:
        for table, prefix in (("logon", "pc:"), ("http", "web:")):
            for day, identity, payload in db.execute(
                f"SELECT day,identity,payload FROM {table} WHERE day>=? AND day<?", (start, end)
            ):
                edges[(day, identity)].extend(prefix + node for node in json.loads(payload))
    return edges


# ---------------------------------------------------------------------------
# Fitting and scoring one method on one fold.


class Inputs:
    """Shared inputs, built once: features, upward-only features, windows and edges."""

    def __init__(self, data, root):
        self.data = data
        self.root = root
        self.x, self.names = data.features("c")
        self._lags = self._edges = self._causal = None
        self._zscore = {}

    @property
    def lagged(self):
        if self._lags is None:
            self._lags = lags(self.data.days, self.data.v["identity"])
        return self._lags

    @property
    def edges(self):
        if self._edges is None:
            self._edges = ledger_edges(self.root, research.LEDGER_START, DEVELOPMENT_END)
        return self._edges

    def development(self):
        return np.flatnonzero(self.data.days < DEVELOPMENT_END)

    def zscores(self, upward=False, floor=MAD_FLOOR):
        """Robust z-score per development row (NaN elsewhere), from raw daily counts."""
        key = (upward, floor)
        if key not in self._zscore:
            rows = self.development()
            days, identities = self.data.days[rows], self.data.v["identity"][rows]
            counts = raw_counts(self.root, days, identities)
            scores = np.full(len(self.data.days), np.nan)
            scores[rows] = robust_z(
                np.log1p(counts),
                lags(days, identities, window=REFERENCE_DAYS + 1),
                upward=upward,
                floor=floor,
            )
            self._zscore[key] = scores
        return self._zscore[key]

    @property
    def zscore(self):
        return self.zscores()

    @property
    def zscore_r3(self):
        return self.zscores(upward=True, floor=0.5)

    @property
    def causal(self):
        """Causal edge score per development row (NaN elsewhere)."""
        if self._causal is None:
            by_key = causal_edge_scores(self.edges)
            scores = np.full(len(self.data.days), np.nan)
            for i in self.development():
                key = (str(self.data.days[i]), str(self.data.v["identity"][i]))
                scores[i] = by_key.get(key, 0.0)
            self._causal = scores
        return self._causal


def raw_counts(root, days, identities):
    """Raw daily counts per channel for the given development rows, cached after one pass."""
    path = output(root) / "counts.npz"
    if path.exists():
        with np.load(path) as f:
            if np.array_equal(f["day"], days) and np.array_equal(f["identity"], identities):
                return f["counts"]
    wanted = {(str(d), str(i)): k for k, (d, i) in enumerate(zip(days, identities, strict=True))}
    counts = np.zeros((len(days), len(CHANNELS)))
    found = 0
    for row in cached_rows(root / research.ARCHIVE_ROWS, str(min(days)), DEVELOPMENT_END):
        k = wanted.get((row["day"], row["identity_id"]))
        if k is not None:
            counts[k] = [row["counts"].get(c, 0) for c in CHANNELS]
            found += 1
    if found != len(days):
        raise ValueError("Raw counts are missing for some development rows")
    np.savez_compressed(path, counts=counts, day=days, identity=identities)
    return counts


def _project(kind, upward_inputs=False, supervised=False):
    def run(f):
        x = upward(f.x, f.inputs.names) if upward_inputs else f.x
        model = research.fit(kind, x[f.train], f.y if supervised else None, f.seed, f.inputs.names)
        return research.score(model, x[f.train]), research.score(model, x[f.test])

    return run


def _graph(f, refined=False):
    graph = Graph(f.inputs.edges, f.start)
    if f.method == "edge":
        scorer = EdgeScorer(graph)
    else:
        scorer = SageScorer(graph, f.seed, refined=refined)
    days, identities = f.inputs.data.days, f.inputs.data.v["identity"]
    return (
        edge_scores(scorer, f.inputs.edges, days[f.train], identities[f.train]),
        edge_scores(scorer, f.inputs.edges, days[f.test], identities[f.test]),
    )


def _precomputed(name):
    def run(f):
        scores = getattr(f.inputs, name)
        return scores[f.train], scores[f.test]

    return run


def _pct_max(f):
    columns = [j for j, n in enumerate(f.inputs.names) if n.startswith("percentile:")]
    return f.x[f.train][:, columns].max(axis=1), f.x[f.test][:, columns].max(axis=1)


def _pct_max_r3(f):
    """Largest signed percentile, ties broken by the largest change magnitude."""
    names = f.inputs.names
    pct = [j for j, n in enumerate(names) if n.startswith("percentile:")]
    mag = [j for j, n in enumerate(names) if n.startswith("magnitude:")]

    def score(x):
        return 1000.0 * x[:, pct].max(axis=1) + x[:, mag].max(axis=1)

    return score(f.x[f.train]), score(f.x[f.test])


def _upward(run):
    """Round 3: the same detector on upward-only inputs, as `ecod_top5` reads them."""

    def wrapped(f):
        f.x = upward(f.x, f.inputs.names)
        return run(f)

    return wrapped


def _distribution(model):
    def run(f):
        fitted = model().fit(f.x[f.train])
        return fitted.score(f.x[f.train]), fitted.score(f.x[f.test])

    return run


def _neural(f, early_stop=False):
    from . import neural

    z = neural.Standardizer(f.x[f.train])(f.x)
    if f.method in ("gru", "gru_next"):

        def maker(rows):
            return windows(z, f.inputs.lagged[rows])

    else:

        def maker(rows):
            return lambda positions: z[rows[positions]]

    n = len(f.train)
    if f.method in ("mlp", "gru") and early_stop:
        # Hold out the last 14 calendar days of the training window, in time order.
        cut = research.day_after(f.start, -14)
        days = f.inputs.data.days[f.train]
        fit, held = f.train[days < cut], f.train[days >= cut]
        scorer = neural.classifier(
            f.method,
            maker(fit),
            f.inputs.data.v["label"][fit],
            f.seed,
            validation=(maker(held), f.inputs.data.v["label"][held]),
        )
    elif f.method in ("mlp", "gru"):
        scorer = neural.classifier(f.method, maker(f.train), f.y, f.seed)
    elif f.method == "autoencoder":
        scorer = neural.reconstruction(maker(f.train), n, f.seed)
    else:
        scorer = neural.next_day(maker(f.train), n, f.x.shape[1], f.seed)
    return scorer(maker(f.train), n), scorer(maker(f.test), len(f.test))


# name -> (family, deterministic, fit and score one fold). Order is the report's order.
REGISTRY = {
    "rf": ("supervised tree", False, _project("rf", supervised=True)),
    "if": ("unsupervised isolation", False, _project("if")),
    "ecod_top5": ("unsupervised tail rarity", True, _project("ecod_top5", upward_inputs=True)),
    "mlp": ("supervised neural", False, _neural),
    "autoencoder": ("unsupervised neural", False, _neural),
    "gru": ("supervised sequence", False, _neural),
    "gru_next": ("unsupervised sequence", False, _neural),
    "edge": ("unsupervised graph", True, _graph),
    "graphsage": ("unsupervised graph", False, _graph),
    # Round 2.
    "zscore": ("statistical rule", True, _precomputed("zscore")),
    "pct_max": ("statistical rule", True, _pct_max),
    "hbos": ("unsupervised distribution", True, _distribution(Histograms)),
    "copod": ("unsupervised distribution", True, _distribution(Copula)),
    "lof": (
        "unsupervised density",
        False,
        lambda f: neighbour_scores("lof", standardise(f.x, f.train), f.train, f.test, f.seed),
    ),
    "knn": (
        "unsupervised distance",
        False,
        lambda f: neighbour_scores("knn", standardise(f.x, f.train), f.train, f.test, f.seed),
    ),
    "ocsvm": (
        "unsupervised margin",
        False,
        lambda f: one_class_svm(standardise(f.x, f.train), f.train, f.test, f.seed),
    ),
    "logreg": (
        "supervised linear",
        True,
        lambda f: logistic(standardise(f.x, f.train), f.y, f.train, f.test),
    ),
    "edge_causal": ("unsupervised graph", True, _precomputed("causal")),
    # Round 3: refined implementations (docs/methods-study.md).
    "zscore_r3": ("statistical rule", True, _precomputed("zscore_r3")),
    "pct_max_r3": ("statistical rule", True, _pct_max_r3),
    "hbos_r3": ("unsupervised distribution", True, _upward(_distribution(Histograms))),
    "copod_r3": ("unsupervised distribution", True, _upward(_distribution(Copula))),
    "lof_r3": (
        "unsupervised density",
        False,
        _upward(
            lambda f: neighbour_scores("lof", standardise(f.x, f.train), f.train, f.test, f.seed)
        ),
    ),
    "knn_r3": (
        "unsupervised distance",
        False,
        _upward(
            lambda f: neighbour_scores("knn", standardise(f.x, f.train), f.train, f.test, f.seed)
        ),
    ),
    "ocsvm_r3": (
        "unsupervised margin",
        False,
        _upward(lambda f: one_class_svm(standardise(f.x, f.train), f.train, f.test, f.seed)),
    ),
    "autoencoder_r3": ("unsupervised neural", False, _upward(_neural)),
    "mlp_r3": ("supervised neural", False, lambda f: _neural(f, early_stop=True)),
    "gru_r3": ("supervised sequence", False, lambda f: _neural(f, early_stop=True)),
    "graphsage_r3": ("unsupervised graph", False, lambda f: _graph(f, refined=True)),
}
ROUND3 = {name for name in REGISTRY if name.endswith("_r3")}
METHODS = tuple(REGISTRY)
FAMILY = {name: family for name, (family, _, _) in REGISTRY.items()}
DETERMINISTIC = {name for name, (_, fixed, _) in REGISTRY.items() if fixed}


def fit_and_score(method, inputs, train, test, seed, start):
    """(scores on training rows, scores on test rows); higher is more suspicious."""
    if method not in REGISTRY:
        raise ValueError("Unknown method: " + method)
    y = inputs.data.v["label"][train]
    if (y < 0).any():
        raise ValueError("Sealed label in development training")
    fold = SimpleNamespace(
        method=method.removesuffix("_r3"),
        inputs=inputs,
        x=inputs.x,
        train=train,
        test=test,
        seed=seed,
        start=start,
        y=y,
    )
    return REGISTRY[method][2](fold)


# ---------------------------------------------------------------------------
# Measures.


def average_precision(y, s):
    """Step-wise average precision over distinct thresholds (equal to scikit-learn's)."""
    order = np.argsort(-s, kind="mergesort")
    s, y = s[order], y[order]
    last = np.r_[np.flatnonzero(np.diff(s)), len(s) - 1]
    hits = np.cumsum(y)[last]
    if hits[-1] == 0:
        return float("nan")
    precision = hits / (last + 1)
    recall = hits / hits[-1]
    return float(np.sum(np.diff(np.r_[0.0, recall]) * precision))


def positives(events, start, end):
    return {(t["day"], t["observed_account"]) for t in events.values() if start <= t["day"] < end}


def ranking(days, identities, scores, positive):
    y = np.asarray([(str(d), str(i)) in positive for d, i in zip(days, identities, strict=True)])
    by_day = defaultdict(list)
    for k, d in enumerate(days):
        by_day[str(d)].append(k)
    caught = Counter()
    for rows in by_day.values():
        ordered = sorted(rows, key=lambda k: (-float(scores[k]), str(identities[k])))
        for k in RECALL_AT:
            caught[k] += int(y[ordered[:k]].sum())
    return {
        "positive_days": int(y.sum()),
        "average_precision": average_precision(y.astype(int), np.asarray(scores, dtype=float)),
        "roc_auc": float(roc_auc_score(y, scores)),
        "top_k_positive_days": {str(k): caught[k] for k in RECALL_AT},
    }


# ---------------------------------------------------------------------------
# The study.


def output(root=ROOT):
    path = research.directory(root) / "methods"
    path.mkdir(exist_ok=True)
    return path


def run(root=ROOT, only=None):
    """Fit, score and replay each method; results merge into any earlier run of other methods."""
    methods = list(only or METHODS)
    unknown = set(methods) - set(METHODS)
    if unknown:
        raise ValueError("Unknown methods: " + ", ".join(sorted(unknown)))
    out = output(root)
    data = research.Data(root)
    inputs = Inputs(data, root)
    queue_config = json.loads((root / "config.json").read_text())["queue"]
    truths = {s: truth(root / research.ANSWERS, research.day_after(s, -7), e) for s, e in FOLDS}
    if any(t["day"] >= DEVELOPMENT_END for events in truths.values() for t in events.values()):
        raise ValueError("The study must stay inside development")
    path = out / "results.json"
    saved = json.loads(path.read_text()) if path.exists() else {"runs": []}
    for method in methods:
        runs, scores = [], {}
        for seed in SEEDS[:1] if method in DETERMINISTIC else SEEDS:
            for start, end in FOLDS:
                train = research.window(data, FIT_START, start)
                test = research.window(data, start, end)
                if max(data.days[test]) >= DEVELOPMENT_END:
                    raise ValueError("Holdout row in a development fold")
                fitted, s = fit_and_score(method, inputs, train, test, seed, start)
                if not (np.isfinite(fitted).all() and np.isfinite(s).all()):
                    raise ValueError(f"{method} produced non-finite scores")
                gate, guarded = training_gate(fitted, GATE_QUANTILE, guard=method in ROUND3)
                queue = research.replay(data, test, s, gate, start, end, POLICY, queue_config)
                metrics, _ = research.measure(data, test, s, gate, queue, truths[start], start, end)
                events = truths[start]
                runs.append(
                    {
                        "method": method,
                        "seed": seed,
                        "fold": start,
                        "gate": gate,
                        **({"gate_guard": guarded} if method in ROUND3 else {}),
                        "gate_candidates": metrics["gate_candidates"],
                        "gate_recall": metrics["gate_recall"],
                        "admissions": metrics["admissions"],
                        "current_positive": metrics["current_positive"],
                        "timely": sorted(metrics["timely_hits"]),
                        "available": sorted(
                            {t["incident_id"] for t in events.values() if start <= t["day"] < end}
                        ),
                        "role_coverage": metrics["role_coverage"],
                        **ranking(
                            data.days[test],
                            data.v["identity"][test],
                            s,
                            positives(events, start, end),
                        ),
                    }
                )
                scores[f"{seed}:{start}"] = s.astype(np.float32)
                r = runs[-1]
                print(
                    method,
                    seed,
                    start,
                    f"AP {r['average_precision']:.3f} AUC {r['roc_auc']:.3f}",
                    f"adm {r['admissions']} timely {len(r['timely'])}/{len(r['available'])}",
                    flush=True,
                )
        np.savez_compressed(out / f"scores-{method}.npz", **scores)
        saved["runs"] = [r for r in saved["runs"] if r["method"] != method] + runs
        save_json(path, saved)
    return saved


# ---------------------------------------------------------------------------
# Paired bootstrap and the report.


def interval(values):
    return [float(np.quantile(values, 0.025)), float(np.quantile(values, 0.975))]


def analyse(root=ROOT, rng_seed=0):
    out = output(root)
    runs = json.loads((out / "results.json").read_text())["runs"]
    methods = [m for m in METHODS if any(r["method"] == m for r in runs)]
    if BASELINE not in methods:
        raise ValueError("The baseline has not been run")
    data = research.Data(root)
    rng = np.random.default_rng(rng_seed)

    # Reach: one entry per incident-fold, the share of a method's seeds that reached it.
    units = sorted(
        {(r["fold"], i) for r in runs if r["method"] == BASELINE for i in r["available"]}
    )
    reach = {}
    for m in methods:
        mine = [r for r in runs if r["method"] == m]
        seeds = sorted({r["seed"] for r in mine})
        hit = Counter((r["fold"], i) for r in mine for i in r["timely"])
        reach[m] = np.asarray([hit[u] / len(seeds) for u in units])
    draws = rng.integers(len(units), size=(REACH_RESAMPLES, len(units)))

    # Average precision: resample test days within each fold, same draws for every method.
    truths = {s: truth(root / research.ANSWERS, research.day_after(s, -7), e) for s, e in FOLDS}
    folds = []
    for start, end in FOLDS:
        test = research.window(data, start, end)
        days = data.days[test]
        positive = positives(truths[start], start, end)
        y = np.asarray(
            [
                (str(d), str(i)) in positive
                for d, i in zip(days, data.v["identity"][test], strict=True)
            ],
            dtype=int,
        )
        groups = [np.flatnonzero(days == d) for d in np.unique(days)]
        picks = [rng.integers(len(groups), size=len(groups)) for _ in range(AP_RESAMPLES)]
        folds.append((start, y, groups, picks))
    scores = {m: np.load(out / f"scores-{m}.npz") for m in methods}
    ap_draws = {}
    for m in methods:
        keys = [k for k in scores[m].files]
        values = np.zeros(AP_RESAMPLES)
        for start, y, groups, picks in folds:
            fold_keys = [k for k in keys if k.endswith(":" + start)]
            for b, pick in enumerate(picks):
                rows = np.concatenate([groups[g] for g in pick])
                values[b] += np.mean(
                    [average_precision(y[rows], scores[m][k][rows]) for k in fold_keys]
                ) / len(folds)
        ap_draws[m] = values

    table = {}
    for m in methods:
        mine = [r for r in runs if r["method"] == m]
        seeds = sorted({r["seed"] for r in mine})
        total_positive_days = sum(r["positive_days"] for r in mine)
        hijacked = sum(
            r["role_coverage"].get("3", {}).get("hijacked", {}).get("timely_incidents", 0)
            for r in mine
        )
        own3 = sum(
            r["role_coverage"].get("3", {}).get("own", {}).get("timely_incidents", 0) for r in mine
        )
        by_scenario = Counter()
        for r in mine:
            for i in r["timely"]:
                by_scenario[i.split("-")[1]] += 1
        reached = float(reach[m].sum())
        diff_reach = (reach[m] - reach[BASELINE])[draws].sum(axis=1)
        ap = float(np.mean([r["average_precision"] for r in mine]))
        table[m] = {
            "family": FAMILY[m],
            "seeds": len(seeds),
            "incidents_reached": reached,
            "incidents_reached_interval": interval(reach[m][draws].sum(axis=1)),
            "reached_difference": float(reach[m].sum() - reach[BASELINE].sum()),
            "reached_difference_interval": interval(diff_reach),
            "average_precision": ap,
            "average_precision_interval": interval(ap_draws[m]),
            "ap_difference": ap
            - float(np.mean([r["average_precision"] for r in runs if r["method"] == BASELINE])),
            "ap_difference_interval": interval(ap_draws[m] - ap_draws[BASELINE]),
            "roc_auc": float(np.mean([r["roc_auc"] for r in mine])),
            "recall_at": {
                str(k): sum(r["top_k_positive_days"][str(k)] for r in mine) / total_positive_days
                for k in RECALL_AT
            },
            "admissions": sum(r["admissions"] for r in mine) / len(seeds),
            "current_positive": sum(r["current_positive"] for r in mine) / len(seeds),
            "gate_candidates": sum(r["gate_candidates"] for r in mine) / len(seeds),
            "scenario_reached": {k: v / len(seeds) for k, v in sorted(by_scenario.items())},
            "takeover_attacker_reached": own3 / len(seeds),
            "takeover_hijacked_reached": hijacked / len(seeds),
            "timeliness": timeliness(mine),
            "gate_guard_runs": sum(bool(r.get("gate_guard")) for r in mine),
            "runs": len(mine),
        }
        for measure in ("reached", "ap"):
            low, high = table[m][f"{measure}_difference_interval"]
            table[m][f"{measure}_reading"] = (
                "baseline"
                if m == BASELINE
                else "better"
                if low > 0
                else "worse"
                if high < 0
                else "matches"
            )
    result = {"incident_folds": len(units), "baseline": BASELINE, "methods": table}
    save_json(out / "analysis.json", result)
    write_methods_report(root / "reports/METHODS_STUDY.md", result)
    return result


def timeliness(runs):
    """Per scenario (own account): hours from an incident's first labelled record to the first
    admission showing one, pooled over folds and seeds, and the share later than 72 hours."""
    out = {}
    for scenario in ("1", "2", "3"):
        hours = [
            h
            for r in runs
            for h in r["role_coverage"]
            .get(scenario, {})
            .get("own", {})
            .get("first_record_to_admission_hours", [])
        ]
        incidents = sum(
            r["role_coverage"].get(scenario, {}).get("own", {}).get("incidents", 0) for r in runs
        )
        out[scenario] = {
            "shown": len(hours),
            "incidents": incidents,
            "median_hours": float(np.median(hours)) if hours else None,
            "share_after_72_hours": float(np.mean(np.asarray(hours) > 72)) if hours else None,
        }
    return out
