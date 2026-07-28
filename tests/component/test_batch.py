"""Batch mode: sinter collection and CSV output on a tiny task."""

from pathlib import Path

from catsim.codes import get_code
from catsim.component import (
    DepolarizingNoise,
    code_curve_tasks,
    curve_tasks,
    run_curve,
    write_curve_csv,
)
from catsim.decoder import sinter_decoders


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


def test_q102_batch_with_custom_bposd_decoder(paper_noise: DepolarizingNoise) -> None:
    # p2q = 1e-2 (past threshold) so logical errors arrive within a few shots;
    # rounds=2 keeps each BP+OSD decode small enough for a unit test.
    tasks = code_curve_tasks([get_code("gb")], [100.0], paper_noise, rounds=2)
    cells = run_curve(
        tasks,
        decoder="bposd",
        custom_decoders=sinter_decoders(),
        max_shots=24,
        max_errors=4,
        num_workers=2,
    )
    assert len(cells) == 1
    assert cells[0].distance == 9
    assert cells[0].shots > 0
    assert cells[0].errors > 0, "1e-2 is far past threshold; errors must appear"
