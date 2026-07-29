"""House-style artifact for the M7 scaling sweep: prediction, overlay, markers.

Exists so reports/m7_scaling.png lands looking like the rest of the product
and stays honest: the prediction line is paper arithmetic, the overlay is the
measured fleet, the roadmap markers are labels to compare against (with the
error-target reconciliation note spelled out), and the interconnect panel is
explicitly marked as swept ASSUMPTIONS.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.axes import Axes  # noqa: E402

from catsim.machine.sweep import (  # noqa: E402
    RECONCILIATION_NOTE,
    ROADMAP_MARKERS,
    InterconnectPoint,
    ScalingPoint,
)

_BG = "#101318"
_INK = "#E5E7EB"
_GRAY = "#9CA3AF"
_ERR = "#EF4444"
_MACHINE = "#E8701A"  # prediction (paper arithmetic)
_WORKLOAD = "#3B82F6"  # measurement (live fleet)
_FOOTER = (
    "stabilizer + behavioral simulation calibrated to arXiv:2604.19481 · "
    "single-machine architecture per the paper; inter-module link modeled from "
    "public roadmap, parameters assumed"
)


def _style(ax: Axes) -> None:
    """Apply the house dark style to one axes."""
    ax.set_facecolor(_BG)
    ax.tick_params(colors=_GRAY)
    for spine in ax.spines.values():
        spine.set_color(_GRAY)
    ax.grid(True, which="major", axis="y", color=_GRAY, alpha=0.15)


def _legend(ax: Axes, loc: Literal["center left", "center right", "upper left"]) -> None:
    """One house-style legend."""
    legend = ax.legend(facecolor=_BG, edgecolor=_GRAY, labelcolor=_INK, fontsize=7, loc=loc)
    legend.get_frame().set_alpha(0.9)


def _logical_panel(ax: Axes, points: list[ScalingPoint]) -> None:
    """Predicted logical qubits vs N, with roadmap markers + reconciliation."""
    ns = [p.n_chips for p in points]
    ax.plot(
        ns,
        [p.predicted_logical for p in points],
        color=_MACHINE,
        linewidth=2,
        label="predicted (Table V paper accounting)",
    )
    ax.margins(x=0.07, y=0.14)
    last_n = max(n for n, _, _ in ROADMAP_MARKERS)
    for n, physical, logical in ROADMAP_MARKERS:
        ax.scatter([n], [logical], marker="D", s=48, color=_GRAY, zorder=3)
        rightmost = n == last_n
        ax.annotate(
            f"roadmap {physical:,} phys\n{logical:,} logical",
            (n, logical),
            textcoords="offset points",
            xytext=(-8, -2) if rightmost else (8, -2),
            ha="right" if rightmost else "left",
            va="top" if rightmost else "bottom",
            fontsize=7,
            color=_GRAY,
        )
    ax.set_xlabel("chips (chip-256 × N)", color=_INK)
    ax.set_ylabel("logical qubits", color=_INK)
    ax.set_title("capacity vs fleet size", color=_INK, fontsize=10)
    ax.text(
        0.97,
        0.26,
        RECONCILIATION_NOTE,
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=6.6,
        color=_INK,
        alpha=0.9,
    )
    _legend(ax, "upper left")


def _throughput_panel(ax: Axes, points: list[ScalingPoint]) -> None:
    """Predicted T/day capacity vs measured, with the demand line drawn."""
    ns = [p.n_chips for p in points]
    ax.plot(
        ns,
        [p.predicted_t_per_day / 1e6 for p in points],
        color=_MACHINE,
        linewidth=2,
        label="predicted capacity (Table VII)",
    )
    measured = [p for p in points if p.measured]
    if measured:
        ax.scatter(
            [p.n_chips for p in measured],
            [p.measured_t_per_day / 1e6 for p in measured],
            color=_WORKLOAD,
            s=42,
            zorder=3,
            label="measured (live fleet)",
        )
    ax.margins(y=0.16)
    if points:
        demand = points[0].demand_t_per_day / 1e6
        ax.axhline(demand, color=_GRAY, linestyle="--", linewidth=1)
        ax.text(
            0.03,
            demand,
            f"workload demand {demand:.2f}M/day",
            transform=ax.get_yaxis_transform(),
            va="bottom",
            color=_GRAY,
            fontsize=7,
        )
    ax.set_xlabel("chips (chip-256 × N)", color=_INK)
    ax.set_ylabel("T gates / day (millions)", color=_INK)
    ax.set_title("T throughput vs fleet size", color=_INK, fontsize=10)
    _legend(ax, "upper left")


def _interconnect_panel(ax: Axes, points: list[InterconnectPoint]) -> None:
    """Cross-module serving vs the swept (assumed) heralded pair rate."""
    if not points:
        ax.set_visible(False)
        return
    rates = [p.pair_rate_hz for p in points]
    ax.plot(
        rates,
        [p.served_per_second for p in points],
        color=_WORKLOAD,
        linewidth=2,
        marker="o",
        markersize=4,
        label="cross-module T served /s",
    )
    limited = [p for p in points if p.link_limited]
    if limited:
        ax.scatter(
            [p.pair_rate_hz for p in limited],
            [p.served_per_second for p in limited],
            color=_ERR,
            s=42,
            zorder=3,
            label="link-limited (queue grows)",
        )
    ax.margins(y=0.16)
    demand = points[0].cross_demand_per_second
    ax.axhline(demand, color=_GRAY, linestyle="--", linewidth=1)
    ax.text(
        0.03,
        demand,
        f"cross demand {demand:g}/s",
        transform=ax.get_yaxis_transform(),
        va="top",
        color=_GRAY,
        fontsize=7,
    )
    ax.axvline(100.0, color=_MACHINE, linestyle=":", linewidth=1)
    ax.text(
        100.0,
        0.04,
        "~10² pairs/s ASSUMED baseline ",
        transform=ax.get_xaxis_transform(),
        ha="right",
        va="bottom",
        color=_MACHINE,
        fontsize=7,
    )
    ax.set_xscale("log")
    ax.set_xlabel("heralded pair rate (pairs/s) — swept ASSUMPTION", color=_INK)
    ax.set_ylabel("cross-module T gates /s", color=_INK)
    ax.set_title("interconnect sensitivity", color=_INK, fontsize=10)
    _legend(ax, "center right")


def plot_scaling(
    points: list[ScalingPoint],
    interconnect_points: list[InterconnectPoint],
    path: Path,
    *,
    title: str = "chip-256 × N — paper-accounted prediction vs measured fleet",
) -> None:
    """Write the three-panel scaling artifact (capacity, throughput, link)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.8), facecolor=_BG)
    for ax in axes:
        _style(ax)
    _logical_panel(axes[0], points)
    _throughput_panel(axes[1], points)
    _interconnect_panel(axes[2], interconnect_points)
    fig.suptitle(title, color=_INK, fontsize=12)
    fig.text(0.5, 0.01, _FOOTER, ha="center", fontsize=7, color=_GRAY)
    fig.tight_layout(rect=(0, 0.045, 1, 0.94))
    fig.savefig(path, dpi=160, facecolor=_BG)
    plt.close(fig)
