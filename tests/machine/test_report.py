"""Predicted-vs-measured collection: both sides populated, artifact written."""

from pathlib import Path

from catsim.component import DepolarizingNoise
from catsim.machine import collect_predicted_vs_measured, load_machine_config, write_pvm_csv
from tests.conftest import REPO_ROOT

MACHINE_DIR = REPO_ROOT / "configs" / "machine"


def test_collects_both_sides_and_writes_csv(paper_noise: DepolarizingNoise, tmp_path: Path) -> None:
    config = load_machine_config("chip-256", MACHINE_DIR)
    result = collect_predicted_vs_measured(
        config, paper_noise, machine_seconds=6.0, shots=2, rounds=3, seed=1
    )
    assert result.prediction.logical_qubits == 6
    assert result.prediction.physical_qubits == 462  # 220 + 42 + 200 reservoir
    assert result.nominal_qubits == 256
    assert result.prediction.t_per_day == 0.0 and result.prediction.t_stall_reason
    assert result.machine_seconds == 6.0
    assert result.utilization == 1.0  # healthy machine: no stalls
    assert result.shots == 2 and result.block_logical == 6
    assert result.logical_error_bound == 1 / 12
    assert result.decodes >= 0
    assert result.mean_decode_latency_s >= 0.0
    csv_path = tmp_path / "pvm.csv"
    write_pvm_csv(result, csv_path)
    text = csv_path.read_text()
    assert "predicted (paper)" in text
    assert "462" in text
