"""Timing harness: round replay, warm-up exclusion, percentiles, and artifacts."""

from pathlib import Path

import pytest

from catsim.codes import get_code
from catsim.component import (
    DepolarizingNoise,
    RoundSegments,
    build_memory_circuit,
    memory_detector_error_model,
    split_into_rounds,
)
from catsim.decoder import (
    plot_latency_race,
    replay_latencies,
    summarize_latencies,
    write_latency_csv,
)


def _boundaries(segments: RoundSegments) -> list[int]:
    counts = (
        [segments.init.num_detectors]
        + [segments.body.num_detectors] * segments.repeats
        + [segments.final.num_detectors]
    )
    out, total = [], 0
    for c in counts:
        total += c
        out.append(total)
    return out


@pytest.fixture
def surface_dem(busy_noise: DepolarizingNoise) -> tuple[str, list[int]]:
    """A small surface-code DEM plus its per-round detector boundaries."""
    circuit = build_memory_circuit(get_code("surface", distance=3), busy_noise, 4)
    return str(memory_detector_error_model(circuit)), _boundaries(split_into_rounds(circuit))


def test_replay_measures_exactly_the_requested_rounds(surface_dem: tuple[str, list[int]]) -> None:
    dem, boundaries = surface_dem
    latencies = replay_latencies(dem, "pymatching", boundaries, min_rounds=30, warmup_rounds=5)
    assert len(latencies) == 30
    assert all(t > 0.0 for t in latencies)


def test_boundary_mismatch_is_rejected(surface_dem: tuple[str, list[int]]) -> None:
    dem, boundaries = surface_dem
    with pytest.raises(ValueError, match="round boundaries"):
        replay_latencies(dem, "pymatching", boundaries[:-1], min_rounds=5, warmup_rounds=0)


def test_summary_percentiles_are_ordered(surface_dem: tuple[str, list[int]]) -> None:
    dem, boundaries = surface_dem
    latencies = replay_latencies(dem, "pymatching", boundaries, min_rounds=40, warmup_rounds=5)
    stats = summarize_latencies("surface d=3", "pymatching", "1×", latencies)
    assert stats.count == 40
    assert 0.0 < stats.p50_ms <= stats.p95_ms <= stats.p99_ms <= stats.max_ms


def test_artifacts_are_written(tmp_path: Path, surface_dem: tuple[str, list[int]]) -> None:
    dem, boundaries = surface_dem
    latencies = replay_latencies(dem, "pymatching", boundaries, min_rounds=20, warmup_rounds=2)
    stats = [
        summarize_latencies("surface d=3", "pymatching", label, latencies) for label in ("1×", "5×")
    ]
    write_latency_csv(stats, tmp_path / "race.csv")
    plot_latency_race(stats, tmp_path / "race.png")
    header, *rows = (tmp_path / "race.csv").read_text().strip().splitlines()
    assert header.startswith("label,decoder_name,noise_label,count,p50_ms")
    assert len(rows) == 2
    assert (tmp_path / "race.png").stat().st_size > 0
