"""Batch mode: sinter collection and CSV output on a tiny task."""

from pathlib import Path

from catsim.component import DepolarizingNoise, curve_tasks, run_curve, write_curve_csv


def test_tiny_curve_collects_and_writes(tmp_path: Path, paper_noise: DepolarizingNoise) -> None:
    tasks = curve_tasks([3], [100.0], paper_noise)  # p2q = 1e-2: errors come fast
    cells = run_curve(tasks, max_shots=2000, max_errors=20, num_workers=2)
    assert len(cells) == 1
    cell = cells[0]
    assert cell.distance == 3
    assert cell.physical_error == 0.01
    assert cell.shots > 0
    assert 0.0 <= cell.logical_error_rate <= 1.0

    out = tmp_path / "curve.csv"
    write_curve_csv(cells, out)
    lines = out.read_text().splitlines()
    assert lines[0].startswith("distance,")
    assert len(lines) == 2
