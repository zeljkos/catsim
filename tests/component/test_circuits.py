"""Circuit builder physics: noiseless sanity, calibration, and round splitting."""

import numpy as np
import pytest

from catsim.codes import get_code
from catsim.component import (
    DepolarizingNoise,
    build_memory_circuit,
    split_into_rounds,
)

ZERO_NOISE = DepolarizingNoise(
    name="zero",
    two_qubit_gate_error=0.0,
    single_qubit_gate_error=0.0,
    measurement_error=0.0,
    reset_error=0.0,
    ion_loss_probability=0.0,
)


def _detection_fraction(noise: DepolarizingNoise, shots: int = 256) -> float:
    """Mean fraction of detectors firing per shot at the given noise."""
    circuit = build_memory_circuit(get_code("surface", distance=3), noise, rounds=5)
    samples = circuit.compile_detector_sampler(seed=42).sample(shots)
    return float(np.mean(samples))


def test_noiseless_circuit_fires_no_syndromes() -> None:
    assert _detection_fraction(ZERO_NOISE) == 0.0


def test_calibration_detection_rate_tracks_noise(paper_noise: DepolarizingNoise) -> None:
    low = _detection_fraction(paper_noise.scaled(10.0))  # p2q = 1e-3
    high = _detection_fraction(paper_noise.scaled(100.0))  # p2q = 1e-2
    assert 0.0 < low < high < 0.5
    # p2q = 1e-2 circuit-level: each detector sees O(10) error locations,
    # so the detection fraction lands in the few-percent band.
    assert 0.01 < high < 0.2


def test_split_preserves_detector_counts(paper_noise: DepolarizingNoise) -> None:
    circuit = build_memory_circuit(get_code("surface", distance=3), paper_noise, rounds=7)
    seg = split_into_rounds(circuit)
    total = seg.init.num_detectors + seg.repeats * seg.body.num_detectors + seg.final.num_detectors
    assert total == circuit.num_detectors
    assert seg.repeats == 6  # rounds - 1: round 0 lives in the init segment


def test_too_few_rounds_rejected(paper_noise: DepolarizingNoise) -> None:
    with pytest.raises(ValueError, match="at least 2 rounds"):
        build_memory_circuit(get_code("surface", distance=3), paper_noise, rounds=1)


def test_unknown_family_rejected(paper_noise: DepolarizingNoise) -> None:
    class FakeCode:
        family = "nope"
        name = "nope-d3"
        distance = 3
        num_data_qubits = 9
        num_logical = 1

    with pytest.raises(KeyError, match="no circuit builder"):
        build_memory_circuit(FakeCode(), paper_noise, rounds=3)
