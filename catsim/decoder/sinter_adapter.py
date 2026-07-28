"""sinter adapter: plug catsim's BP+OSD into Monte Carlo batch collection.

Exists so the batch curve (component layer) can sample with the same decoder
the live loop runs, without the component layer importing this package —
callers pass :func:`sinter_decoders` into ``run_curve`` as plain data.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import sinter
import stim
from ldpc.bposd_decoder import BpOsdDecoder

from catsim.decoder.bposd import _dem_matrices


class _CompiledBpOsd(sinter.CompiledDecoder):  # type: ignore[misc]  # sinter ships no stubs
    """BP+OSD compiled against one task's DEM, decoding bit-packed shots."""

    def __init__(self, dem: stim.DetectorErrorModel) -> None:
        """Build matrices and the ldpc decoder once per task."""
        self._matrices = _dem_matrices(dem)
        self._num_detectors = dem.num_detectors
        self._num_observables = dem.num_observables
        self._bposd = BpOsdDecoder(
            self._matrices.checks,
            error_channel=list(self._matrices.priors),
            max_iter=30,
            bp_method="minimum_sum",
            ms_scaling_factor=0.625,
            osd_method="OSD_0",
        )

    def decode_shots_bit_packed(
        self, *, bit_packed_detection_event_data: npt.NDArray[np.uint8]
    ) -> npt.NDArray[np.uint8]:
        """Decode each shot; return bit-packed observable predictions."""
        shots = bit_packed_detection_event_data.shape[0]
        detections = np.unpackbits(
            bit_packed_detection_event_data,
            axis=1,
            count=self._num_detectors,
            bitorder="little",
        )
        predictions = np.zeros((shots, self._num_observables), dtype=np.uint8)
        for s in range(shots):
            estimate = self._bposd.decode(detections[s])
            predictions[s] = (self._matrices.observables @ estimate) % 2
        return np.packbits(predictions, axis=1, bitorder="little")


class SinterBpOsd(sinter.Decoder):  # type: ignore[misc]  # sinter ships no stubs
    """sinter Decoder wrapper: one compiled BP+OSD per detector error model."""

    def compile_decoder_for_dem(self, *, dem: stim.DetectorErrorModel) -> sinter.CompiledDecoder:
        """Compile for one task's DEM (called in each sinter worker)."""
        return _CompiledBpOsd(dem)


def sinter_decoders() -> dict[str, sinter.Decoder]:
    """The custom decoders catsim contributes to ``sinter.collect``."""
    return {"bposd": SinterBpOsd()}
