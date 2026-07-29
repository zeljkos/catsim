"""Batch decode-latency harness: real wall-clock per SE round, raced vs 6 ms.

Exists to answer M4's question honestly: can this decoder implementation keep
up with the paper's 6 ms syndrome-extraction cycle? Syndromes are sampled from
the block's own detector error model and replayed round by round exactly as
the live service sees them (cumulative history, future rounds zero-padded).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
import stim

from catsim.decoder.protocol import get_decoder


@dataclass(frozen=True)
class LatencyStats:
    """Latency percentiles for one (code, decoder, noise) configuration.

    All times in milliseconds; ``count`` is measured decodes, warm-up excluded.
    """

    label: str
    decoder_name: str
    noise_label: str
    count: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    mean_ms: float
    max_ms: float


def replay_latencies(
    dem: str,
    decoder_name: str,
    round_boundaries: Sequence[int],
    *,
    min_rounds: int = 2000,
    warmup_rounds: int = 100,
    seed: int = 0,
    progress: Callable[[int, int], None] | None = None,
) -> tuple[float, ...]:
    """Measure per-round decode wall-clock against sampled syndrome streams.

    Args:
        dem: The block's detector error model, serialized as stim text.
        decoder_name: Registered decoder to build against the DEM.
        round_boundaries: Cumulative detector count at the end of each SE
            round; the last entry must equal the DEM's detector count.
        min_rounds: Measured decodes to collect (after warm-up).
        warmup_rounds: Leading decodes discarded (JIT/cache/allocator warm-up).
        seed: Syndrome sampler seed (reproducible streams).
        progress: Called after every shot with (decodes done, decodes planned)
            — slow decoders make long runs, and a long run must never be a
            black box.

    Returns:
        One wall-clock latency (seconds) per measured round-decode.
    """
    model = stim.DetectorErrorModel(dem)
    if round_boundaries[-1] != model.num_detectors:
        raise ValueError(
            f"round boundaries end at {round_boundaries[-1]}, DEM has {model.num_detectors}"
        )
    decoder = get_decoder(decoder_name, dem=dem)
    shots = -(-(min_rounds + warmup_rounds) // len(round_boundaries))
    detectors, _, _ = model.compile_sampler(seed=seed).sample(shots=shots)
    latencies: list[float] = []
    planned = shots * len(round_boundaries)
    for shot in detectors:
        syndrome = np.zeros(model.num_detectors, dtype=np.uint8)
        start = 0
        for end in round_boundaries:
            syndrome[start:end] = shot[start:end]
            start = end
            latencies.append(decoder.decode(syndrome).latency_s)
        if progress is not None:
            progress(len(latencies), planned)
    return tuple(latencies[warmup_rounds : warmup_rounds + min_rounds])


def summarize_latencies(
    label: str, decoder_name: str, noise_label: str, latencies: Sequence[float]
) -> LatencyStats:
    """Fold raw per-round latencies into the percentile stats the plot and CSV use."""
    ms = np.asarray(latencies, dtype=np.float64) * 1e3
    return LatencyStats(
        label=label,
        decoder_name=decoder_name,
        noise_label=noise_label,
        count=len(ms),
        p50_ms=float(np.percentile(ms, 50)),
        p95_ms=float(np.percentile(ms, 95)),
        p99_ms=float(np.percentile(ms, 99)),
        mean_ms=float(ms.mean()),
        max_ms=float(ms.max()),
    )
