"""Small PyTorch detectors for the methods study (docs/methods-study.md); a CPU is enough.

Every function takes a `make(positions)` callable that returns a float32 batch for those
positions of the training set, so sequence windows are gathered per batch, not stored.
"""

import numpy as np
import torch
from torch import nn

BATCH = 512
LEARNING_RATE = 1e-3
CLASSIFIER_EPOCHS = 8
AUTOENCODER_EPOCHS = 10
NEXT_EPOCHS = 8
HIDDEN = 32
SAGE_EPOCHS = 200
SAGE_LEARNING_RATE = 1e-2


class Standardizer:
    """Training-window mean and standard deviation, applied to any rows."""

    def __init__(self, x):
        self.mean = x.mean(axis=0)
        self.std = x.std(axis=0)
        self.std[self.std == 0] = 1.0

    def __call__(self, x):
        return ((x - self.mean) / self.std).astype(np.float32)


class Recurrent(nn.Module):
    """One GRU layer and a linear head on the last state."""

    def __init__(self, inputs, outputs):
        super().__init__()
        self.gru = nn.GRU(inputs, HIDDEN, batch_first=True)
        self.head = nn.Linear(HIDDEN, outputs)

    def forward(self, x):
        states, _ = self.gru(x)
        return self.head(states[:, -1])


def perceptron(inputs):
    return nn.Sequential(
        nn.Linear(inputs, 64),
        nn.ReLU(),
        nn.Dropout(0.1),
        nn.Linear(64, 32),
        nn.ReLU(),
        nn.Dropout(0.1),
        nn.Linear(32, 1),
    )


def autoencoder(inputs):
    return nn.Sequential(
        nn.Linear(inputs, 16),
        nn.ReLU(),
        nn.Linear(16, 8),
        nn.ReLU(),
        nn.Linear(8, 16),
        nn.ReLU(),
        nn.Linear(16, inputs),
    )


def train(net, n, loss, epochs, seed):
    """Shuffled mini-batch Adam; `loss(positions)` returns the batch loss."""
    generator = torch.Generator().manual_seed(seed)
    optimiser = torch.optim.Adam(net.parameters(), lr=LEARNING_RATE)
    net.train()
    for _ in range(epochs):
        order = torch.randperm(n, generator=generator).numpy()
        for k in range(0, n, BATCH):
            value = loss(order[k : k + BATCH])
            optimiser.zero_grad()
            value.backward()
            optimiser.step()
    net.eval()
    return net


@torch.no_grad()
def apply(net, make, n, reduce):
    out = []
    for k in range(0, n, 8192):
        positions = np.arange(k, min(n, k + 8192))
        out.append(reduce(net, torch.from_numpy(make(positions))).numpy())
    return np.concatenate(out) if out else np.empty(0)


def classifier(kind, make, y, seed):
    """`mlp` on one day's inputs or `gru` on a window; returns a scorer of logits."""
    torch.manual_seed(seed)
    shape = make(np.arange(1)).shape
    net = perceptron(shape[-1]) if kind == "mlp" else Recurrent(shape[-1], 1)
    positives = float(y.sum())
    weight = torch.tensor((len(y) - positives) / max(positives, 1.0))
    criterion = nn.BCEWithLogitsLoss(pos_weight=weight)
    target = torch.from_numpy(y.astype(np.float32))

    def loss(positions):
        return criterion(net(torch.from_numpy(make(positions))).squeeze(-1), target[positions])

    train(net, len(y), loss, CLASSIFIER_EPOCHS, seed)
    return lambda make, n: apply(net, make, n, lambda m, b: m(b).squeeze(-1))


def reconstruction(make, n, seed):
    """Autoencoder on one day's inputs; returns a scorer of reconstruction error."""
    torch.manual_seed(seed)
    net = autoencoder(make(np.arange(1)).shape[-1])

    def loss(positions):
        batch = torch.from_numpy(make(positions))
        return ((net(batch) - batch) ** 2).mean()

    train(net, n, loss, AUTOENCODER_EPOCHS, seed)
    return lambda make, n: apply(net, make, n, lambda m, b: ((m(b) - b) ** 2).mean(dim=1))


def next_day(make, n, outputs, seed):
    """GRU over the previous days predicting today's first `outputs` inputs."""
    torch.manual_seed(seed)
    net = Recurrent(make(np.arange(1)).shape[-1], outputs)

    def error(m, batch):
        return ((m(batch[:, :-1]) - batch[:, -1, :outputs]) ** 2).mean(dim=1)

    train(
        net,
        n,
        lambda positions: error(net, torch.from_numpy(make(positions))).mean(),
        NEXT_EPOCHS,
        seed,
    )
    return lambda make, n: apply(net, make, n, error)


class Sage(nn.Module):
    """Two GraphSAGE layers with mean aggregation over a row-normalised adjacency."""

    def __init__(self, inputs):
        super().__init__()
        self.self1, self.neigh1 = nn.Linear(inputs, HIDDEN), nn.Linear(inputs, HIDDEN)
        self.self2, self.neigh2 = nn.Linear(HIDDEN, HIDDEN), nn.Linear(HIDDEN, HIDDEN)

    def forward(self, x, adjacency):
        h = torch.relu(self.self1(x) + self.neigh1(torch.sparse.mm(adjacency, x)))
        return self.self2(h) + self.neigh2(torch.sparse.mm(adjacency, h))


def graphsage(features, sources, targets, kinds, pools, seed):
    """Node embeddings trained for link prediction.

    `sources`/`targets` are the observed undirected edges and `kinds[k]` the type of edge k;
    a negative for edge k keeps its source and draws a target uniformly from `pools[kinds[k]]`,
    the nodes of that type.
    """
    torch.manual_seed(seed)
    generator = torch.Generator().manual_seed(seed)
    n = len(features)
    rows = np.concatenate([sources, targets])
    cols = np.concatenate([targets, sources])
    degree = np.bincount(rows, minlength=n).astype(np.float32)
    adjacency = torch.sparse_coo_tensor(
        torch.from_numpy(np.stack([rows, cols])),
        torch.from_numpy(1.0 / degree[rows]),
        (n, n),
        check_invariants=True,
    ).coalesce()
    x = torch.from_numpy(features.astype(np.float32))
    net = Sage(x.shape[1])
    optimiser = torch.optim.Adam(net.parameters(), lr=SAGE_LEARNING_RATE)
    src, dst = torch.from_numpy(sources), torch.from_numpy(targets)
    groups = [
        (torch.from_numpy(np.flatnonzero(kinds == k)), torch.from_numpy(np.asarray(pool)))
        for k, pool in enumerate(pools)
    ]
    criterion = nn.BCEWithLogitsLoss()
    for _ in range(SAGE_EPOCHS):
        negative = torch.empty_like(dst)
        for where, pool in groups:
            negative[where] = pool[torch.randint(len(pool), (len(where),), generator=generator)]
        z = net(x, adjacency)
        positive_logits = (z[src] * z[dst]).sum(dim=1)
        negative_logits = (z[src] * z[negative]).sum(dim=1)
        loss = criterion(positive_logits, torch.ones_like(positive_logits)) + criterion(
            negative_logits, torch.zeros_like(negative_logits)
        )
        optimiser.zero_grad()
        loss.backward()
        optimiser.step()
    with torch.no_grad():
        return net(x, adjacency).numpy()
