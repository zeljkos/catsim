"""MatchingDecoder: registry construction, trivial and real decodes, throttle."""

import numpy as np

from catsim.codes import get_code
from catsim.component import DepolarizingNoise, build_memory_circuit
from catsim.decoder import MatchingDecoder, available_decoders, get_decoder


def _dem(noise: DepolarizingNoise) -> tuple[str, int]:
    """A d=3 memory DEM as text, plus its detector count."""
    circuit = build_memory_circuit(get_code("surface", distance=3), noise, rounds=3)
    dem = circuit.detector_error_model(decompose_errors=True)
    return str(dem), dem.num_detectors


def test_registered_and_buildable(busy_noise: DepolarizingNoise) -> None:
    dem, _ = _dem(busy_noise)
    decoder = get_decoder("pymatching", dem=dem)
    assert isinstance(decoder, MatchingDecoder)
    assert "pymatching" in available_decoders()


def test_trivial_syndrome_decodes_to_nothing(busy_noise: DepolarizingNoise) -> None:
    dem, n = _dem(busy_noise)
    result = get_decoder("pymatching", dem=dem).decode(np.zeros(n, dtype=np.uint8))
    assert result.predicted_flips == ()
    assert result.matched_detectors == ()
    assert result.latency_s > 0.0


def test_real_shot_decodes(busy_noise: DepolarizingNoise) -> None:
    circuit = build_memory_circuit(get_code("surface", distance=3), busy_noise, rounds=3)
    dem = circuit.detector_error_model(decompose_errors=True)
    decoder = get_decoder("pymatching", dem=str(dem))
    dets = circuit.compile_detector_sampler(seed=1).sample(32)
    predictions = [decoder.decode(shot.astype(np.uint8)) for shot in dets]
    fired = [i for i, shot in enumerate(dets) if shot.any()]
    assert fired, "busy noise must fire some detectors in 32 shots"
    assert any(p.matched_detectors for i, p in enumerate(predictions) if i in fired)


def test_slowdown_factor_inflates_latency(busy_noise: DepolarizingNoise) -> None:
    dem, n = _dem(busy_noise)
    fast = get_decoder("pymatching", dem=dem)
    slow = get_decoder("pymatching", dem=dem, slowdown_factor=50.0)
    syndrome = np.zeros(n, dtype=np.uint8)
    fast_t = min(fast.decode(syndrome).latency_s for _ in range(5))
    slow_t = min(slow.decode(syndrome).latency_s for _ in range(5))
    assert slow_t > fast_t
