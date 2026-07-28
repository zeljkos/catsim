"""MWPM decoding via pymatching — the known-good surface-code baseline.

Exists as the M0/M1 reference decoder; its measured wall-clock latency is the
number raced against the 6 ms syndrome-extraction budget.
"""

from __future__ import annotations

import time

import numpy as np
import numpy.typing as npt
import pymatching
import stim

from catsim.decoder.protocol import DecodeResult


class MatchingDecoder:
    """pymatching wrapped behind the Decoder protocol, throttleable at runtime.

    ``slowdown_factor`` > 1 sleeps proportionally to the real decode time — the
    knob behind the "decoder falls behind" scenario (M4).
    """

    name = "pymatching"

    def __init__(self, *, dem: str, slowdown_factor: float = 1.0) -> None:
        """Build the matching graph from a serialized detector error model.

        Args:
            dem: stim DEM text, as carried by the ``block_configured`` event.
            slowdown_factor: Artificial latency multiplier (1.0 = none).
        """
        self._matching = pymatching.Matching.from_detector_error_model(stim.DetectorErrorModel(dem))
        self.slowdown_factor = slowdown_factor

    def decode(self, syndrome: npt.NDArray[np.uint8]) -> DecodeResult:
        """Decode one detector vector; latency is real wall-clock, throttle included."""
        t0 = time.perf_counter()
        prediction = self._matching.decode(syndrome)
        edges = self._matching.decode_to_edges_array(syndrome)
        elapsed = time.perf_counter() - t0
        if self.slowdown_factor > 1.0:
            time.sleep(elapsed * (self.slowdown_factor - 1.0))
        return DecodeResult(
            predicted_flips=tuple(int(i) for i in np.flatnonzero(prediction)),
            matched_detectors=tuple((int(a), int(b)) for a, b in edges),
            latency_s=time.perf_counter() - t0,
        )
