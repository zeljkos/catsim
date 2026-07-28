"""Generic CSS builder physics on Q102: noiseless sanity both bases, calibration."""

import numpy as np
import pytest

from catsim.codes import get_code
from catsim.component import (
    DepolarizingNoise,
    build_css_memory,
    build_memory_circuit,
    memory_detector_error_model,
    split_into_rounds,
)
from catsim.component.geometry import block_layout

ZERO_NOISE = DepolarizingNoise(
    name="zero",
    two_qubit_gate_error=0.0,
    single_qubit_gate_error=0.0,
    measurement_error=0.0,
    reset_error=0.0,
    ion_loss_probability=0.0,
)


@pytest.mark.parametrize("basis", ["Z", "X"])
def test_noiseless_q102_fires_no_syndromes(basis: str) -> None:
    circuit = build_css_memory(get_code("gb"), ZERO_NOISE, rounds=3, basis=basis)  # type: ignore[arg-type]
    samples = circuit.compile_detector_sampler(seed=7).sample(64)
    assert not samples.any()


def test_q102_circuit_shape() -> None:
    circuit = build_memory_circuit(get_code("gb"), ZERO_NOISE, rounds=4)
    # 51 first-round Z detectors + 102 per later round + 51 final
    assert circuit.num_detectors == 51 + 3 * 102 + 51
    assert circuit.num_observables == 22
    assert circuit.num_qubits == 102 + 51 + 51


def test_q102_calibration_detection_rate_tracks_noise(paper_noise: DepolarizingNoise) -> None:
    def fraction(noise: DepolarizingNoise) -> float:
        circuit = build_memory_circuit(get_code("gb"), noise, rounds=3)
        return float(np.mean(circuit.compile_detector_sampler(seed=42).sample(128)))

    low = fraction(paper_noise.scaled(10.0))
    high = fraction(paper_noise.scaled(100.0))
    assert 0.0 < low < high < 0.5


def test_q102_split_preserves_detector_counts(paper_noise: DepolarizingNoise) -> None:
    circuit = build_memory_circuit(get_code("gb"), paper_noise, rounds=5)
    seg = split_into_rounds(circuit)
    total = seg.init.num_detectors + seg.repeats * seg.body.num_detectors + seg.final.num_detectors
    assert total == circuit.num_detectors
    assert seg.repeats == 4


def test_q102_dem_falls_back_to_hyperedges(paper_noise: DepolarizingNoise) -> None:
    circuit = build_memory_circuit(get_code("gb"), paper_noise, rounds=2)
    dem = memory_detector_error_model(circuit)
    assert dem.num_detectors == circuit.num_detectors
    # at least one error mechanism touches >2 detectors: the qLDPC signature
    max_dets = max(
        sum(1 for t in inst.targets_copy() if t.is_relative_detector_id())
        for inst in dem.flattened()
        if inst.type == "error"
    )
    assert max_dets > 2


def test_q102_layout_serves_generic_rings(paper_noise: DepolarizingNoise) -> None:
    circuit = build_memory_circuit(get_code("gb"), paper_noise, rounds=2)
    layout = block_layout(circuit)
    assert len(layout.data_qubits) == 102
    assert len(layout.check_qubits) == 102
    assert sorted(set(layout.check_basis.values())) == ["X", "Z"]
    assert sum(1 for b in layout.check_basis.values() if b == "X") == 51
    # every detector maps back to the check ancilla that measured it
    assert len(layout.detector_checks) == circuit.num_detectors
    # hyperedge keys exist in the edge map (sets larger than a matching edge)
    assert any(len(dets) > 2 for dets in layout.edge_qubits)


def test_css_builder_rejects_non_css_code(paper_noise: DepolarizingNoise) -> None:
    with pytest.raises(TypeError, match="CSS"):
        build_css_memory(get_code("surface", distance=3), paper_noise, rounds=2)
