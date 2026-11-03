"""Label-free tail scoring re-weighted by analyst verdicts, shared by research and replay.

The detector starts as the label-free top-5 upper-tail rarity score. Verdicts on
admitted investigations re-weight the per-input rarities (Active Anomaly Discovery
style); identity-days that were never admitted contribute no labels.
"""

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit

TOP = 5
# Analyst dispositions that count as verdicts; other dispositions add no label.
VERDICTS = {"confirmed": 1, "suspicious": 1, "benign": -1}

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

    def rarity(self, x):
        """Per-input upper-tail rarity, -log P(reference >= value)."""
        n = len(self.columns)
        return np.column_stack(
            [
                -np.log((n - np.searchsorted(c, x[:, j], side="left") + 1) / (n + 1))
                for j, c in enumerate(self.columns.T)
            ]
        )

    def score_samples(self, x):
        rarity = self.rarity(x)
        if self.channels:
            rarity = np.column_stack([rarity[:, group].max(axis=1) for group in self.channels])
        if self.top:
            rarity = np.sort(rarity, axis=1)[:, -self.top :]
        return -rarity.sum(axis=1)


def upward(x, names):
    """Keep only increases in signed personal and peer percentiles."""
    x = x.copy()
    for j, name in enumerate(names):
        if name.startswith("percentile:") or name.startswith("peer_") and "percentile" in name:
            x[:, j] = np.maximum(0.0, x[:, j])
    return x


def vector(row, daily):
    """Corrected 33-input representation with upward-only percentiles for one row."""
    # Imported here because the experiment features depend on the replay module.
    from .experiment_features import corrected
    from .pipeline import matrix

    x, names = matrix([corrected(row, daily)], "PM")
    return upward(x, names)[0], names


def components(scorer, x):
    """Non-negative components: every input rarity plus the top-5 rarity sum (the prior)."""
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


class AdaptiveScorer:
    """Online detector: monthly label-free reference, verdict re-weighting and a quantile gate.

    The reference holds every observed eligible identity-day since `reference_start`.
    It refits on the first scored day of each month, using days before that day only.
    The gate is the `gate_quantile` of reference scores under the current weights.
    """

    def __init__(self, reference_start, lam, gate_quantile):
        self.reference_start = reference_start
        self.lam = lam
        self.gate_quantile = gate_quantile
        self.days, self.rows, self.index = [], [], {}
        self.tail = self.model = self.month = self.learned = None
        self.gate = None
        self.labels = 0

    def observe(self, day, identity, x):
        if day >= self.reference_start:
            self.index[(day, identity)] = len(self.rows)
            self.days.append(day)
            self.rows.append(np.asarray(x, dtype=float))

    def prepare(self, day, verdicts):
        """Make the detector current for scoring `day` with the verdicts available so far."""
        if self.tail is None or day[:7] != self.month:
            reference = np.asarray(self.rows)[np.asarray(self.days) < day]
            self.tail = TailScorer().fit(reference)
            self.z_reference = components(self.tail, reference)
            self.month = day[:7]
            if self.model is None:
                self.model = FeedbackModel(self.z_reference.shape[1], self.lam)
            self.learned = None
        self.learn(verdicts)
        self.gate = float(np.quantile(self.model.score(self.z_reference), self.gate_quantile))

    def learn(self, verdicts):
        """Refit on (verdict, [(day, identity), ...]) pairs when they or the reference change."""
        signature = tuple(
            (key, verdict) for verdict, keys in verdicts for key in keys if key in self.index
        )
        self.labels = len(signature)
        if signature and signature != self.learned:
            x = np.asarray([self.rows[self.index[key]] for key, _ in signature])
            self.model.update(components(self.tail, x), [verdict for _, verdict in signature])
        self.learned = signature

    def score(self, x):
        return self.model.score(components(self.tail, np.atleast_2d(x)))

    def weights(self, names, n=8):
        """Largest learned weights by input name; the last component is the top-5 prior."""
        named = zip([*names, "top5_sum"], self.model.w.tolist(), strict=True)
        return sorted(named, key=lambda t: -t[1])[:n]
