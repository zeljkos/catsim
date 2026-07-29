"""House-style artifacts for the decoder race: percentile plot + CSV (M4).

Exists so the p99-vs-code plot with the 6 ms line lands in reports/ looking
like the rest of the product, and is always labeled with WHAT implementation
was measured — never mistakable for the paper's custom streaming decoder.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, fields
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.axes import Axes  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

from catsim.decoder.timing import LatencyStats  # noqa: E402

_BG = "#101318"
_INK = "#E5E7EB"
_GRAY = "#9CA3AF"
_ERR = "#EF4444"
_SERIES = ["#E8701A", "#3B82F6", "#9CA3AF", "#F5F5F4"]
_FOOTER = "stabilizer + behavioral simulation calibrated to arXiv:2604.19481"

IMPLEMENTATION_NOTE = (
    "measured: open-source ldpc BP+OSD-0 / pymatching, single core, cumulative decode per round\n"
    "— NOT the paper's custom streaming decoder (their measured baseline: <1 ms/SEC)"
)


def write_latency_csv(stats: list[LatencyStats], path: Path) -> None:
    """Write one row of percentile stats per configuration."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[fld.name for fld in fields(LatencyStats)])
        writer.writeheader()
        for stat in stats:
            writer.writerow(asdict(stat))


def _style(ax: Axes) -> None:
    """Apply the house dark style to one axes."""
    ax.set_facecolor(_BG)
    ax.tick_params(colors=_GRAY)
    for spine in ax.spines.values():
        spine.set_color(_GRAY)
    ax.grid(True, which="both", axis="y", color=_GRAY, alpha=0.15)


def plot_latency_race(
    stats: list[LatencyStats],
    path: Path,
    *,
    budget_ms: float = 6.0,
    title: str = "Decode latency per SE round vs the 6 ms SEC budget",
) -> None:
    """Plot p50/p95/p99 latency per code, one series per noise label, budget line drawn.

    Args:
        stats: One entry per (code, noise) configuration.
        path: Output PNG path (parents created).
        budget_ms: The syndrome-extraction budget line (paper: 6 ms).
        title: Plot title.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    labels = list(dict.fromkeys(s.label for s in stats))
    noises = list(dict.fromkeys(s.noise_label for s in stats))
    fig, ax = plt.subplots(figsize=(8, 5.5), facecolor=_BG)
    _style(ax)
    for n_idx, noise in enumerate(noises):
        color = _SERIES[n_idx % len(_SERIES)]
        offset = (n_idx - (len(noises) - 1) / 2) * 0.18
        for s in (s for s in stats if s.noise_label == noise):
            x = labels.index(s.label) + offset
            ax.vlines(x, s.p50_ms, s.p99_ms, color=color, linewidth=2)
            ax.scatter([x], [s.p50_ms], color=color, marker="o", zorder=3)
            ax.scatter([x], [s.p95_ms], color=color, marker="_", s=90, zorder=3)
            ax.scatter([x], [s.p99_ms], color=color, marker="^", zorder=3)
    ax.axhline(budget_ms, color=_ERR, linestyle="--", linewidth=1.2)
    ax.text(0.02, budget_ms * 1.12, f"{budget_ms:g} ms SEC budget", color=_ERR, fontsize=8)
    ax.set_yscale("log")
    # " · "-separated labels stack into two tick lines (code over decoder)
    ax.set_xticks(range(len(labels)), [lab.replace(" · ", "\n") for lab in labels])
    ax.set_ylabel("decode wall-clock per SE round (ms)", color=_INK)
    ax.set_title(title, color=_INK)
    handles = [
        Line2D([], [], color=_SERIES[i % len(_SERIES)], linewidth=2, label=f"noise {n}")
        for i, n in enumerate(noises)
    ] + [
        Line2D([], [], color=_GRAY, marker=m, linestyle="", label=lab)
        for m, lab in [("o", "p50"), ("_", "p95"), ("^", "p99")]
    ]
    legend = ax.legend(handles=handles, facecolor=_BG, edgecolor=_GRAY, labelcolor=_INK)
    legend.get_frame().set_alpha(0.9)
    fig.text(0.5, 0.055, IMPLEMENTATION_NOTE, ha="center", fontsize=7.5, color=_INK)
    fig.text(0.5, 0.01, _FOOTER, ha="center", fontsize=7, color=_GRAY)
    fig.tight_layout(rect=(0, 0.09, 1, 1))
    fig.savefig(path, dpi=160, facecolor=_BG)
    plt.close(fig)
