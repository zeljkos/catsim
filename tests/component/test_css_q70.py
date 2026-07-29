"""Q70 through the generic CSS pipeline: noiseless sanity, shape, calibration."""

import numpy as np
import pytest

from catsim.codes import get_code
from catsim.component import DepolarizingNoise, build_css_memory, build_memory_circuit
from tests.component.test_css import ZERO_NOISE


@pytest.mark.parametrize("basis", ["Z", "X"])
def test_noiseless_q70_fires_no_syndromes(basis: str) -> None:
    circuit = build_css_memory(get_code("bb"), ZERO_NOISE, rounds=3, basis=basis)  # type: ignore[arg-type]
    samples = circuit.compile_detector_sampler(seed=7).sample(64)
    assert not samples.any()


def test_q70_circuit_shape() -> None:
    circuit = build_memory_circuit(get_code("bb"), ZERO_NOISE, rounds=4)
    # 35 first-round Z detectors + 70 per later round + 35 final
    assert circuit.num_detectors == 35 + 3 * 70 + 35
    assert circuit.num_observables == 6
    assert circuit.num_qubits == 70 + 35 + 35


def test_q70_calibration_detection_rate_tracks_noise(paper_noise: DepolarizingNoise) -> None:
    def fraction(noise: DepolarizingNoise) -> float:
        circuit = build_memory_circuit(get_code("bb"), noise, rounds=3)
        return float(np.mean(circuit.compile_detector_sampler(seed=42).sample(128)))

    low = fraction(paper_noise.scaled(10.0))
    high = fraction(paper_noise.scaled(100.0))
    assert 0.0 < low < high < 0.5
