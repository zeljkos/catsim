"""Monte Carlo batch mode: sinter over the same circuit builders as the live loop.

Exists for statistics with error bars — the logical-error-vs-distance curve that
proves error suppression below threshold (M0 acceptance).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import sinter

from catsim.codes import get_code
from catsim.component.circuits import build_memory_circuit
from catsim.component.noise import NoiseModel


@dataclass(frozen=True)
class CurveCell:
    """One (distance, physical error) point of the batch curve, with raw counts."""

    distance: int
    physical_error: float
    noise_name: str
    shots: int
    errors: int

    @property
    def logical_error_rate(self) -> float:
        """Logical errors per shot (the plotted quantity)."""
        return self.errors / self.shots if self.shots else 0.0


def curve_tasks(
    distances: list[int],
    scales: list[float],
    base_noise: NoiseModel,
    family: str = "surface",
) -> list[sinter.Task]:
    """Build sinter tasks for every (distance, noise scale) combination.

    Rounds per shot = distance, the standard memory-experiment convention.

    Args:
        distances: Code distances to sweep.
        scales: Multipliers applied to every channel of ``base_noise``.
        base_noise: The reference noise model (normally paper-baseline).
        family: Code family to instantiate per distance.

    Returns:
        One task per combination, tagged with metadata for later grouping.
    """
    tasks = []
    for scale in scales:
        noise = base_noise.scaled(scale)
        for d in distances:
            code = get_code(family, distance=d)
            circuit = build_memory_circuit(code, noise, rounds=max(d, 2))
            tasks.append(
                sinter.Task(
                    circuit=circuit,
                    json_metadata={
                        "d": d,
                        "p": noise.two_qubit_gate_error,
                        "noise": noise.name,
                    },
                )
            )
    return tasks


def run_curve(
    tasks: list[sinter.Task],
    *,
    max_shots: int = 1_000_000,
    max_errors: int = 100,
    num_workers: int = 4,
) -> list[CurveCell]:
    """Collect Monte Carlo statistics for the curve with pymatching.

    Args:
        tasks: Output of :func:`curve_tasks`.
        max_shots: Per-task shot budget.
        max_errors: Stop a task early once this many logical errors are seen
            (keeps below-threshold cells from burning the whole budget).
        num_workers: Parallel sampling/decoding workers.

    Returns:
        One cell per task, sorted by (physical error, distance).
    """
    stats = sinter.collect(
        num_workers=num_workers,
        tasks=tasks,
        decoders=["pymatching"],
        max_shots=max_shots,
        max_errors=max_errors,
    )
    cells = [
        CurveCell(
            distance=int(s.json_metadata["d"]),
            physical_error=float(s.json_metadata["p"]),
            noise_name=str(s.json_metadata["noise"]),
            shots=s.shots,
            errors=s.errors,
        )
        for s in stats
    ]
    return sorted(cells, key=lambda c: (c.physical_error, c.distance))


def write_curve_csv(cells: list[CurveCell], path: Path) -> None:
    """Write the curve cells to CSV (every batch metric ships with its raw counts)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["distance", "physical_error", "noise", "shots", "errors", "rate"])
        for c in cells:
            writer.writerow(
                [
                    c.distance,
                    c.physical_error,
                    c.noise_name,
                    c.shots,
                    c.errors,
                    c.logical_error_rate,
                ]
            )
