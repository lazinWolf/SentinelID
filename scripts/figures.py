"""Report figures from saved results. Run after the research stages: python scripts/figures.py

Needs matplotlib (`pip install -e .[figures]`), which the application itself does not use.

Reads only generated result files (reports' sources under data/research and results.json);
writes PNGs to docs/figures/. One series per chart, so titles name it and no legend is needed.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "data/research"
OUT = ROOT / "docs/figures"
SURFACE, INK, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
SERIES = "#2a78d6"  # categorical slot 1 of the reference palette
EMPHASIS = "#e34948"  # used once, for the blind spot


def load(path):
    return json.loads((RESEARCH / path).read_text())


def style(ax, title, subtitle):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=MUTED, length=0, labelsize=10)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_title(title, loc="left", fontsize=13, color=INK, fontweight="bold", pad=24)
    ax.text(0, 1.02, subtitle, transform=ax.transAxes, fontsize=9.5, color=MUTED)


def bars(ax, labels, values, totals, colors=None, fmt="{:g} / {:g}"):
    y = np.arange(len(labels))[::-1]
    ax.barh(y, values, height=0.56, color=colors or SERIES, edgecolor=SURFACE, linewidth=2)
    ax.set_yticks(y, labels, color=INK)
    for yi, v, t in zip(y, values, totals, strict=True):
        ax.text(
            v + max(totals) * 0.01,
            yi,
            fmt.format(round(v, 1), t),
            va="center",
            fontsize=10,
            color=INK,
        )


def reach():
    """Timely incident reach by detector: development folds and sealed holdout."""
    dev = {
        "Isolation Forest": load("backtest-unsupervised/results.json")["summary"]["candidates"][
            "if"
        ],
        "Label-free rarity (ECOD-style)": load("backtest-unsupervised/results.json")["summary"][
            "candidates"
        ]["ecod_up_top5"],
        "Random Forest (deployed recipe)": load("backtest/results.json")["summary"]["candidates"][
            "deployed_recipe"
        ],
    }
    dev = {k: v["timely_incidents"]["mean"] for k, v in dev.items()}
    feedback = load("feedback/results.json")["variants"]["lambda_0.3"]["totals"]["timely_incidents"]
    dev = {
        **dict(list(dev.items())[:2]),
        "Label-free + analyst feedback": feedback,
        **dict(list(dev.items())[2:]),
    }
    held = defaultdict(list)
    for run in load("holdout-unsupervised/result.json")["runs"]:
        held[run["name"]].append(run["timely_incidents"])
    holdout = {
        "Isolation Forest": np.mean(held["if"]),
        "Label-free rarity (ECOD-style)": np.mean(held["ecod_up_top5"]),
        "Label-free + analyst feedback": load("holdout-feedback/result.json")["variants"][
            "lambda_0.3"
        ]["timely_incidents"],
        "Random Forest (deployed recipe)": np.mean(held["deployed (frozen, fit Jun-Oct)"]),
    }
    fig, axes = plt.subplots(1, 2, figsize=(12, 3.6), facecolor=SURFACE)
    for ax, data, total, title, sub in (
        (axes[0], dev, 61, "Development (Aug–Nov 2010)", "Timely incidents of 61, fold mean"),
        (axes[1], holdout, 24, "Sealed holdout (Dec 2010–May 2011)", "Timely incidents of 24"),
    ):
        bars(ax, list(data), list(data.values()), [total] * len(data))
        ax.set_xlim(0, total * 1.18)
        style(ax, title, sub)
    axes[1].set_yticks(axes[1].get_yticks(), [""] * len(holdout))
    fig.tight_layout(w_pad=3)
    fig.savefig(OUT / "detector-reach.png", dpi=160, facecolor=SURFACE)


def takeover():
    """Labelled days over the gate by scenario and account, November plus holdout."""
    periods = load("identity-coverage.json")["periods"].values()
    rows = [
        ("1", "own", "Scenario 1: data theft"),
        ("2", "own", "Scenario 2: job hunt, theft"),
        ("3", "own", "Scenario 3: attacker's own account"),
        ("3", "hijacked", "Scenario 3: hijacked account"),
    ]
    flagged, total = [], []
    for scenario, role, _ in rows:
        flagged.append(sum(p["role_coverage"][scenario][role]["gate_days"] for p in periods))
        total.append(sum(p["role_coverage"][scenario][role]["identity_days"] for p in periods))
    share = [100 * f / t for f, t in zip(flagged, total, strict=True)]
    fig, ax = plt.subplots(figsize=(9, 3.2), facecolor=SURFACE)
    y = np.arange(len(rows))[::-1]
    ax.barh(y, share, height=0.56, color=[SERIES] * 3 + [EMPHASIS], edgecolor=SURFACE, linewidth=2)
    ax.set_yticks(y, [r[2] for r in rows], color=INK)
    for yi, s, f, t in zip(y, share, flagged, total, strict=True):
        ax.text(s + 1.5, yi, f"{f} of {t} days", va="center", fontsize=10, color=INK)
    ax.set_xlim(0, 118)
    ax.set_xticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])
    style(
        ax,
        "The hijacked account is never flagged",
        "Deployed model: labelled malicious days scoring over the gate, November + holdout",
    )
    fig.tight_layout()
    fig.savefig(OUT / "takeover-coverage.png", dpi=160, facecolor=SURFACE)


def funnel():
    """Holdout funnel: eligible identity-days down to current-positive investigations."""
    run = next(r for r in load("holdout/result.json")["runs"] if "frozen" in r["name"])
    stages = [
        ("Eligible identity-days", run["eligible_days"]),
        ("Over the gate", run["gate_candidates"]),
        ("Investigations", run["admissions"]),
        ("Malicious record in trigger", run["current_positive"]),
    ]
    fig, ax = plt.subplots(figsize=(9, 3.0), facecolor=SURFACE)
    y = np.arange(len(stages))[::-1]
    values = [v for _, v in stages]
    ax.barh(y, values, height=0.56, color=SERIES, edgecolor=SURFACE, linewidth=2)
    ax.set_xscale("log")
    ax.set_xlim(10, values[0] * 6)
    ax.set_yticks(y, [s for s, _ in stages], color=INK)
    for yi, v in zip(y, values, strict=True):
        ax.text(v * 1.15, yi, f"{v:,}", va="center", fontsize=10, color=INK)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    style(
        ax,
        "From 102,494 identity-days to 158 investigations",
        "Sealed holdout, deployed model, one investigation per day (log scale)",
    )
    fig.tight_layout()
    fig.savefig(OUT / "holdout-funnel.png", dpi=160, facecolor=SURFACE)


if __name__ == "__main__":
    if not RESEARCH.exists():
        sys.exit("Run the research stages first; data/research is missing.")
    OUT.mkdir(parents=True, exist_ok=True)
    reach()
    takeover()
    funnel()
    print("Figures written to", OUT)
