"""BP+OSD decoder: protocol conformance, correction quality, runtime throttle."""

import numpy as np
import pytest
import stim

from catsim.codes import get_code
from catsim.component import build_memory_circuit, load_noise_model, memory_detector_error_model
from catsim.decoder import BpOsdWrapper, Decoder, get_decoder
from tests.conftest import NOISE_DIR


@pytest.fixture(scope="module")
def q102_circuit() -> stim.Circuit:
    noise = load_noise_model(NOISE_DIR / "paper-baseline.yaml").scaled(10.0)
    return build_memory_circuit(get_code("gb"), noise, rounds=2)


@pytest.fixture(scope="module")
def q102_dem(q102_circuit: stim.Circuit) -> str:
    return str(memory_detector_error_model(q102_circuit))


def test_bposd_satisfies_protocol(q102_dem: str) -> None:
    decoder = get_decoder("bposd", dem=q102_dem)
    assert isinstance(decoder, Decoder)
    assert isinstance(decoder, BpOsdWrapper)


def test_bposd_trivial_syndrome_predicts_nothing(q102_dem: str) -> None:
    decoder = get_decoder("bposd", dem=q102_dem)
    dets = stim.DetectorErrorModel(q102_dem).num_detectors
    result = decoder.decode(np.zeros(dets, dtype=np.uint8))
    assert result.predicted_flips == ()
    assert result.matched_detectors == ()
    assert result.latency_s > 0


def test_bposd_corrects_most_shots(q102_dem: str, q102_circuit: stim.Circuit) -> None:
    decoder = get_decoder("bposd", dem=q102_dem)
    shots = 50
    dets, obs = q102_circuit.compile_detector_sampler(seed=11).sample(
        shots, separate_observables=True
    )
    wrong = 0
    for s in range(shots):
        result = decoder.decode(dets[s].astype(np.uint8))
        if set(result.predicted_flips) != set(np.flatnonzero(obs[s])):
            wrong += 1
    # p2q = 1e-3 over 2 rounds: raw syndrome-triggering shots dominate,
    # decoded failures must be a small minority
    assert wrong <= shots * 0.2


def test_bposd_blames_detector_sets(q102_dem: str, q102_circuit: stim.Circuit) -> None:
    decoder = get_decoder("bposd", dem=q102_dem)
    dets, _ = q102_circuit.compile_detector_sampler(seed=3).sample(64, separate_observables=True)
    fired = next(row for row in dets if row.any())
    result = decoder.decode(fired.astype(np.uint8))
    assert result.matched_detectors, "a fired syndrome must blame some mechanism"
    blamed = set().union(*[set(d) for d in result.matched_detectors])
    assert blamed <= set(range(len(fired)))


def test_bposd_slowdown_factor_throttles(q102_dem: str) -> None:
    dets = stim.DetectorErrorModel(q102_dem).num_detectors
    fast = get_decoder("bposd", dem=q102_dem)
    slow = get_decoder("bposd", dem=q102_dem, slowdown_factor=50.0)
    syndrome = np.zeros(dets, dtype=np.uint8)
    t_fast = fast.decode(syndrome).latency_s
    t_slow = slow.decode(syndrome).latency_s
    assert t_slow > t_fast * 5
