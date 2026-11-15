"""Methods study (docs/methods-study.md): statistical, distribution, distance, neural, sequence
and graph detectors compared with the project's detectors on the development folds, under the
same gate and queue.

Development only: every row read is before 2010-12-01, and the holdout labels are never loaded.
"""

import heapq
import json
import math
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from datetime import date

import numpy as np
from scipy.stats import skew
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.neighbors import LocalOutlierFactor, NearestNeighbors
from sklearn.svm import OneClassSVM

from . import research
from .adaptive import upward
from .experiment_io import save_json
from .ingestion import ROOT
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
TOP_EDGES = 3
SMOOTHING = 5.0
RECALL_AT = (1, 2, 5, 10)
BASELINE = "rf"
METHODS = (
    "rf",
    "if",
    "ecod_top5",
    "mlp",
    "autoencoder",
    "gru",
    "gru_next",
    "edge",
    "graphsage",
    # Round 2.
    "zscore",
    "pct_max",
    "hbos",
    "copod",
    "lof",
    "knn",
    "ocsvm",
    "logreg",
    "edge_causal",
)
DETERMINISTIC = {"ecod_top5", "edge", "zscore", "pct_max", "hbos", "copod", "logreg", "edge_causal"}
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
REFERENCE_DAYS, MIN_REFERENCE, MAD_FLOOR = 28, 7, 0.1
NEIGHBOURS, NEIGHBOUR_ROWS, SVM_ROWS, SVM_NU, BINS = 20, 20_000, 10_000, 0.05, 10
FAMILY = {
    "rf": "supervised tree",
    "if": "unsupervised",
    "ecod_top5": "unsupervised",
    "mlp": "supervised neural",
    "autoencoder": "unsupervised neural",
    "gru": "supervised sequence",
    "gru_next": "unsupervised sequence",
    "edge": "unsupervised graph",
    "graphsage": "unsupervised graph",
    "zscore": "statistical rule",
    "pct_max": "statistical rule",
    "hbos": "unsupervised distribution",
    "copod": "unsupervised distribution",
    "lof": "unsupervised density",
    "knn": "unsupervised distance",
    "ocsvm": "unsupervised margin",
    "logreg": "supervised linear",
    "edge_causal": "unsupervised graph",
}
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


class Graph:
    """Identity-to-node edges weighted by the number of days they occurred, before `before`."""

    def __init__(self, edges, before):
        self.days = Counter()
        for (day, identity), nodes in edges.items():
            if day < before:
                for node in nodes:
                    self.days[(identity, node)] += 1
        self.identities = sorted({u for u, _ in self.days})
        self.nodes = sorted({v for _, v in self.days})
        self.known = set(self.identities) | set(self.nodes)


def kind(node):
    return node.split(":", 1)[0]


class EdgeScorer:
    """Smoothed P(node | identity) per node type; surprise is -log P."""

    def __init__(self, graph):
        self.graph = graph
        self.identity_days = Counter()
        node_days = Counter()
        for (u, v), n in graph.days.items():
            self.identity_days[(u, kind(v))] += n
            node_days[v] += n
        totals, counts = Counter(), Counter()
        for v, n in node_days.items():
            totals[kind(v)] += n
            counts[kind(v)] += 1
        self.share = {
            v: (n + 1) / (totals[kind(v)] + counts[kind(v)]) for v, n in node_days.items()
        }
        self.ceiling = max(self.raw(u, v) for u, v in graph.days)

    def raw(self, u, v):
        days = self.graph.days.get((u, v), 0)
        return -math.log(
            (days + SMOOTHING * self.share[v]) / (self.identity_days[(u, kind(v))] + SMOOTHING)
        )

    def surprise(self, u, v):
        if u not in self.graph.known or v not in self.graph.known:
            return self.ceiling
        return self.raw(u, v)


class SageScorer:
    """GraphSAGE link-prediction embeddings; surprise is -log sigmoid(z_u . z_v)."""

    def __init__(self, graph, seed):
        from . import neural

        index = {name: i for i, name in enumerate(graph.identities + graph.nodes)}
        types = ["identity"] * len(graph.identities) + [kind(v) for v in graph.nodes]
        pairs = list(graph.days)
        sources = np.asarray([index[u] for u, _ in pairs])
        targets = np.asarray([index[v] for _, v in pairs])
        degree = np.bincount(np.concatenate([sources, targets]), minlength=len(index))
        log_degree = np.log1p(degree)
        log_degree = (log_degree - log_degree.mean()) / (log_degree.std() or 1.0)
        names = ("identity", "pc", "web")
        features = np.column_stack(
            [np.asarray([t == k for t in types], dtype=float) for k in names] + [log_degree]
        )
        kinds = np.asarray([0 if kind(v) == "pc" else 1 for _, v in pairs])
        pools = [
            [index[v] for v in graph.nodes if kind(v) == "pc"],
            [index[v] for v in graph.nodes if kind(v) == "web"],
        ]
        z = neural.graphsage(features, sources, targets, kinds, pools, seed)
        self.index, self.z = index, z
        logits = (z[sources] * z[targets]).sum(axis=1)
        self.ceiling = float(np.max(np.logaddexp(0, -logits)))

    def surprise(self, u, v):
        if u not in self.index or v not in self.index:
            return self.ceiling
        return float(np.logaddexp(0, -float(self.z[self.index[u]] @ self.z[self.index[v]])))


def edge_scores(scorer, edges, days, identities, top=TOP_EDGES):
    """Sum of each identity-day's `top` largest edge surprises; 0 without edges."""
    out = np.zeros(len(days))
    for k, (day, identity) in enumerate(zip(days, identities, strict=True)):
        nodes = edges.get((str(day), str(identity)))
        if nodes:
            out[k] = sum(heapq.nlargest(top, (scorer.surprise(str(identity), v) for v in nodes)))
    return out


def causal_edge_scores(edges, top=TOP_EDGES):
    """{(day, identity): score} where each day is scored on strictly earlier days, then added."""
    by_day = defaultdict(list)
    for (day, identity), nodes in edges.items():
        by_day[day].append((identity, nodes))
    pair, identity_days, node_days = Counter(), Counter(), Counter()
    totals, kinds = Counter(), Counter()
    out = {}
    for day in sorted(by_day):
        for identity, nodes in by_day[day]:
            surprises = []
            for v in nodes:
                k = kind(v)
                share = (node_days[v] + 1) / (totals[k] + kinds[k] + 1)
                surprises.append(
                    -math.log(
                        (pair[(identity, v)] + SMOOTHING * share)
                        / (identity_days[(identity, k)] + SMOOTHING)
                    )
                )
            out[(day, identity)] = sum(heapq.nlargest(top, surprises))
        for identity, nodes in by_day[day]:
            for v in nodes:
                k = kind(v)
                kinds[k] += node_days[v] == 0
                pair[(identity, v)] += 1
                identity_days[(identity, k)] += 1
                node_days[v] += 1
                totals[k] += 1
    return out


def robust_z(values, lagged):
    """Largest absolute robust z-score per row against the identity's own earlier rows.

    `lagged[:, :-1]` indexes the reference rows (-1 where the identity has no row that day);
    the last column is the row itself and is not part of its own reference.
    """
    reference = np.where(
        (lagged[:, :-1] >= 0)[..., None], values[lagged[:, :-1]], np.nan
    )  # rows x days x channels
    enough = (lagged[:, :-1] >= 0).sum(axis=1) >= MIN_REFERENCE
    out = np.zeros(len(values))
    with np.errstate(all="ignore"):
        median = np.nanmedian(reference[enough], axis=1)
        mad = np.nanmedian(np.abs(reference[enough] - median[:, None, :]), axis=1)
    z = (values[enough] - median) / np.maximum(1.4826 * mad, MAD_FLOOR)
    out[enough] = np.abs(z).max(axis=1)
    return out


class Histograms:
    """HBOS: per-input equal-width histograms; the score sums -log of the relative bin height."""

    def fit(self, x):
        self.low, self.high = x.min(axis=0), x.max(axis=0)
        self.width = np.where(self.high > self.low, (self.high - self.low) / BINS, 1.0)
        bins = self.bins(x)
        self.cost = np.empty((BINS, x.shape[1]))
        for j in range(x.shape[1]):
            counts = np.bincount(bins[:, j], minlength=BINS)
            self.cost[:, j] = -np.log(np.maximum(counts / counts.max(), 1 / (len(x) + 1)))
        return self

    def bins(self, x):
        return np.clip(((x - self.low) / self.width).astype(int), 0, BINS - 1)

    def score(self, x):
        bins = self.bins(x)
        return self.cost[bins, np.arange(x.shape[1])].sum(axis=1)


class Copula:
    """COPOD with tail probabilities estimated on the training rows."""

    def fit(self, x):
        self.columns = np.sort(x, axis=0)
        self.negative_skew = skew(x, axis=0) < 0
        return self

    def score(self, x):
        n = len(self.columns)
        left, right = np.empty(x.shape), np.empty(x.shape)
        for j in range(x.shape[1]):
            column = self.columns[:, j]
            left[:, j] = -np.log((np.searchsorted(column, x[:, j], side="right") + 1) / (n + 1))
            right[:, j] = -np.log((n - np.searchsorted(column, x[:, j], side="left") + 1) / (n + 1))
        chosen = np.where(self.negative_skew, left, right)
        return np.maximum.reduce([left.sum(axis=1), right.sum(axis=1), chosen.sum(axis=1)])


def standardise(x, train):
    mean, std = x[train].mean(axis=0), x[train].std(axis=0)
    return (x - mean) / np.where(std == 0, 1.0, std)


def neighbour_scores(method, z, train, test, seed):
    """`lof` or `knn` against a seeded subsample of the training rows.

    Returns the subsample's own scores (each row excluded from its neighbours) for the gate,
    and the test scores.
    """
    rng = np.random.default_rng(seed)
    reference = z[rng.choice(train, size=min(NEIGHBOUR_ROWS, len(train)), replace=False)]
    if method == "lof":
        model = LocalOutlierFactor(n_neighbors=NEIGHBOURS, novelty=True).fit(reference)
        return -model.negative_outlier_factor_, -model.score_samples(z[test])
    model = NearestNeighbors(n_neighbors=NEIGHBOURS).fit(reference)
    return model.kneighbors()[0].mean(axis=1), model.kneighbors(z[test])[0].mean(axis=1)


# ---------------------------------------------------------------------------
# Fitting and scoring one method on one fold.


class Inputs:
    """Shared inputs, built once: features, upward-only features, windows and edges."""

    def __init__(self, data, root):
        self.data = data
        self.root = root
        self.x, self.names = data.features("c")
        self._lags = self._edges = self._zscore = self._causal = None

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

    @property
    def zscore(self):
        """Robust z-score per development row (NaN elsewhere), from raw daily counts."""
        if self._zscore is None:
            rows = self.development()
            days, identities = self.data.days[rows], self.data.v["identity"][rows]
            counts = raw_counts(self.root, days, identities)
            scores = np.full(len(self.data.days), np.nan)
            scores[rows] = robust_z(
                np.log1p(counts), lags(days, identities, window=REFERENCE_DAYS + 1)
            )
            self._zscore = scores
        return self._zscore

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


def fit_and_score(method, inputs, train, test, seed, start):
    """(scores on training rows, scores on test rows); higher is more suspicious."""
    data, x = inputs.data, inputs.x
    y = data.v["label"][train]
    if (y < 0).any():
        raise ValueError("Sealed label in development training")
    if method in ("rf", "if"):
        model = research.fit(method, x[train], y if method == "rf" else None, seed)
        return research.score(model, x[train]), research.score(model, x[test])
    if method == "ecod_top5":
        up = upward(x, inputs.names)
        model = research.fit("ecod_top5", up[train], None, seed, inputs.names)
        return research.score(model, up[train]), research.score(model, up[test])
    if method in ("edge", "graphsage"):
        graph = Graph(inputs.edges, start)
        scorer = EdgeScorer(graph) if method == "edge" else SageScorer(graph, seed)
        days, identities = data.days, data.v["identity"]
        return (
            edge_scores(scorer, inputs.edges, days[train], identities[train]),
            edge_scores(scorer, inputs.edges, days[test], identities[test]),
        )
    if method in ("zscore", "edge_causal"):
        scores = inputs.zscore if method == "zscore" else inputs.causal
        return scores[train], scores[test]
    if method == "pct_max":
        columns = [j for j, n in enumerate(inputs.names) if n.startswith("percentile:")]
        return x[train][:, columns].max(axis=1), x[test][:, columns].max(axis=1)
    if method in ("hbos", "copod"):
        model = (Histograms() if method == "hbos" else Copula()).fit(x[train])
        return model.score(x[train]), model.score(x[test])
    if method in ("lof", "knn"):
        return neighbour_scores(method, standardise(x, train), train, test, seed)
    if method == "ocsvm":
        z = standardise(x, train)
        rows = np.random.default_rng(seed).choice(
            train, size=min(SVM_ROWS, len(train)), replace=False
        )
        model = OneClassSVM(kernel="rbf", gamma="scale", nu=SVM_NU).fit(z[rows])
        return -model.decision_function(z[train]), -model.decision_function(z[test])
    if method == "logreg":
        z = standardise(x, train)
        model = LogisticRegression(C=1.0, class_weight="balanced", max_iter=1000).fit(z[train], y)
        return model.decision_function(z[train]), model.decision_function(z[test])
    from . import neural

    z = neural.Standardizer(x[train])(x)
    if method in ("gru", "gru_next"):

        def maker(rows):
            return windows(z, inputs.lagged[rows])

    else:

        def maker(rows):
            return lambda positions: z[rows[positions]]

    if method in ("mlp", "gru"):
        scorer = neural.classifier(method, maker(train), y, seed)
    elif method == "autoencoder":
        scorer = neural.reconstruction(maker(train), len(train), seed)
    elif method == "gru_next":
        scorer = neural.next_day(maker(train), len(train), x.shape[1], seed)
    else:
        raise ValueError("Unknown method: " + method)
    return scorer(maker(train), len(train)), scorer(maker(test), len(test))


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
                gate = float(np.quantile(fitted, GATE_QUANTILE))
                queue = research.replay(data, test, s, gate, start, end, POLICY, queue_config)
                metrics, _ = research.measure(data, test, s, gate, queue, truths[start], start, end)
                events = truths[start]
                runs.append(
                    {
                        "method": method,
                        "seed": seed,
                        "fold": start,
                        "gate": gate,
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
    result = {"incident_folds": len(units), "methods": table}
    save_json(out / "analysis.json", result)
    write_report(root / "reports/METHODS_STUDY.md", result)
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


def write_report(path, result):
    t = result["methods"]
    f = lambda v: f"{v:.3f}"  # noqa: E731
    lines = [
        "# Methods study: detection methods compared",
        "",
        "Development folds August to November 2010 (expanding training window from 2010-06-08), "
        "feature set `c`, gate at the 0.99 quantile of each method's training scores, the maintained "
        "one-a-day queue. Specification, fixed before any result: "
        "[docs/methods-study.md](../docs/methods-study.md). The holdout is not used. Intervals are "
        "95% paired bootstrap intervals (incident-folds for reach, test days for average precision); "
        f"the baseline is `{BASELINE}`.",
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
                if m == BASELINE
                else f"{r['ap_difference']:+.3f} [{dlo:+.3f}, {dhi:+.3f}] {r['ap_reading']}"
            )
            + f" | {f(r['roc_auc'])} | {r['incidents_reached']:.1f} [{rlo:.1f}, {rhi:.1f}] | "
            + (
                "—"
                if m == BASELINE
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
