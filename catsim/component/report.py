"""House-style plotting for batch results (dark bg, orange/blue accents).

Exists so batch curves land in reports/ looking like the rest of the product,
with binomial error bars on every point per charter.
"""

from __future__ import annotations

from itertools import groupby
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import sinter  # noqa: E402

from catsim.component.batch import CurveCell  # noqa: E402

_BG = "#101318"
_INK = "#E5E7EB"
_GRAY = "#9CA3AF"
_SERIES = ["#E8701A", "#3B82F6", "#9CA3AF", "#F5F5F4"]
_FOOTER = "stabilizer + behavioral simulation calibrated to arXiv:2604.19481"


def plot_curve(cells: list[CurveCell], path: Path, title: str | None = None) -> None:
    """Plot logical error rate vs code distance, one series per physical error.

    Args:
        cells: Batch results from :func:`catsim.component.batch.run_curve`.
        path: Output PNG path (parents created).
        title: Optional title override.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 5.5), facecolor=_BG)
    ax.set_facecolor(_BG)
    by_p = groupby(
        sorted(cells, key=lambda c: (c.physical_error, c.distance)), key=lambda c: c.physical_error
    )
    for color, (p, group) in zip(_SERIES, by_p, strict=False):
        pts = list(group)
        xs = [c.distance for c in pts]
        ys, lows, highs = [], [], []
        for c in pts:
            fit = sinter.fit_binomial(
                num_shots=c.shots, num_hits=c.errors, max_likelihood_factor=1e3
            )
            ys.append(max(fit.best, 1e-12))
            lows.append(max(fit.best - fit.low, 0.0))
            highs.append(max(fit.high - fit.best, 0.0))
        ax.errorbar(
            xs, ys, yerr=[lows, highs], color=color, marker="o", capsize=3, label=f"p2q = {p:g}"
        )
    ax.set_yscale("log")
    ax.set_xticks(sorted({c.distance for c in cells}))
    ax.set_xlabel("code distance d", color=_INK)
    ax.set_ylabel("logical error rate per shot (d rounds)", color=_INK)
    ax.set_title(
        title or "Logical error vs distance — rotated surface code, pymatching", color=_INK
    )
    ax.tick_params(colors=_GRAY)
    for spine in ax.spines.values():
        spine.set_color(_GRAY)
    ax.grid(True, which="both", color=_GRAY, alpha=0.15)
    legend = ax.legend(facecolor=_BG, edgecolor=_GRAY, labelcolor=_INK)
    legend.get_frame().set_alpha(0.9)
    fig.text(0.5, 0.01, _FOOTER, ha="center", fontsize=7, color=_GRAY)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(path, dpi=160, facecolor=_BG)
    plt.close(fig)


def plot_rate_curve(cells: list[CurveCell], path: Path, label: str, title: str) -> None:
    """Plot logical error rate vs physical error rate for one code instance.

    The break-even diagonal makes suppression legible: points below it mean
    the encoded qubit outlives a bare one.

    Args:
        cells: Batch results, one per noise scale (same code).
        path: Output PNG path (parents created).
        label: Series label, e.g. ``"Q102 [[102,22,9]] + BP+OSD"``.
        title: Plot title.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 5.5), facecolor=_BG)
    ax.set_facecolor(_BG)
    pts = sorted(cells, key=lambda c: c.physical_error)
    xs = [c.physical_error for c in pts]
    ys, lows, highs = [], [], []
    for c in pts:
        fit = sinter.fit_binomial(num_shots=c.shots, num_hits=c.errors, max_likelihood_factor=1e3)
        ys.append(max(fit.best, 1e-12))
        lows.append(max(fit.best - fit.low, 0.0))
        highs.append(max(fit.high - fit.best, 0.0))
    ax.errorbar(xs, ys, yerr=[lows, highs], color=_SERIES[0], marker="o", capsize=3, label=label)
    ax.plot(xs, xs, color=_GRAY, linestyle="--", linewidth=1, label="break-even (p_L = p)")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("physical two-qubit error rate p", color=_INK)
    ax.set_ylabel("logical error rate per shot", color=_INK)
    ax.set_title(title, color=_INK)
    ax.tick_params(colors=_GRAY)
    for spine in ax.spines.values():
        spine.set_color(_GRAY)
    ax.grid(True, which="both", color=_GRAY, alpha=0.15)
    legend = ax.legend(facecolor=_BG, edgecolor=_GRAY, labelcolor=_INK)
    legend.get_frame().set_alpha(0.9)
    fig.text(0.5, 0.01, _FOOTER, ha="center", fontsize=7, color=_GRAY)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(path, dpi=160, facecolor=_BG)
    plt.close(fig)
