"""Every detector the research compares, in one place.

Each one is fitted on training identity-days and returns a score where higher is more suspicious.

- Project detectors (`fit`/`score`): Random Forest, HistGradientBoosting, Isolation Forest and
  the upper-tail rarity scorer (`adaptive.TailScorer`), optionally split by weekday and weekend.
- Methods-study detectors (docs/methods-study.md): graph edge surprise (smoothed counts,
  causal counts or GraphSAGE embeddings), robust z-scores, HBOS, COPOD, neighbour distances,
  one-class SVM and logistic regression. The PyTorch networks live in `neural.py`.
"""

import heapq
import math
from collections import Counter, defaultdict
from datetime import date

import numpy as np
from scipy.stats import skew
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    IsolationForest,
    RandomForestClassifier,
)
from sklearn.linear_model import LogisticRegression
from sklearn.neighbors import LocalOutlierFactor, NearestNeighbors
from sklearn.svm import OneClassSVM

from .adaptive import TailScorer

TOP_EDGES = 3
SMOOTHING = 5.0
MIN_REFERENCE, MAD_FLOOR = 7, 0.1
NEIGHBOURS, NEIGHBOUR_ROWS, SVM_ROWS, SVM_NU, BINS = 20, 20_000, 10_000, 0.05, 10


# ---------------------------------------------------------------------------
# Project detectors.


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


# ---------------------------------------------------------------------------
# Methods-study detectors: graph edge surprise.


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


# ---------------------------------------------------------------------------
# Methods-study detectors: statistical, distribution, distance, margin and linear.


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


def one_class_svm(z, train, test, seed):
    """RBF one-class SVM on a seeded training subsample; scores are negated decision values."""
    rows = np.random.default_rng(seed).choice(train, size=min(SVM_ROWS, len(train)), replace=False)
    model = OneClassSVM(kernel="rbf", gamma="scale", nu=SVM_NU).fit(z[rows])
    return -model.decision_function(z[train]), -model.decision_function(z[test])


def logistic(z, y, train, test):
    """L2 logistic regression with balanced class weights; scores are decision values."""
    model = LogisticRegression(C=1.0, class_weight="balanced", max_iter=1000).fit(z[train], y)
    return model.decision_function(z[train]), model.decision_function(z[test])
