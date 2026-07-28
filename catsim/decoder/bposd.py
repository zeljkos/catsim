"""BP+OSD decoding via the ldpc package — the qLDPC production decoder.

Exists because qLDPC error mechanisms are hyperedges no matching graph can
hold: the decoder consumes the detector error model whole (detectors x error
mechanisms), runs belief propagation, and falls back to ordered-statistics
post-processing when BP does not converge (Panteleev-Kalachev / Roffe).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import stim
from ldpc.bposd_decoder import BpOsdDecoder
from scipy.sparse import csr_matrix

from catsim.decoder.protocol import DecodeResult


@dataclass(frozen=True)
class _DemMatrices:
    """A detector error model as the matrices BP+OSD consumes.

    One column per error mechanism; mechanisms with identical detector and
    observable signatures are merged (probabilities XOR-combined) so the
    decoder sees each distinguishable fault class once.
    """

    checks: csr_matrix
    observables: csr_matrix
    priors: tuple[float, ...]
    detector_sets: tuple[tuple[int, ...], ...]


def _dem_matrices(dem: stim.DetectorErrorModel) -> _DemMatrices:
    """Fold a DEM into check/observable matrices, priors, and detector sets."""
    merged: dict[tuple[tuple[int, ...], tuple[int, ...]], float] = {}
    for inst in dem.flattened():
        if inst.type != "error":
            continue
        p = float(inst.args_copy()[0])
        dets, obs = [], []
        for t in inst.targets_copy():
            if t.is_relative_detector_id():
                dets.append(t.val)
            elif t.is_logical_observable_id():
                obs.append(t.val)
        key = (tuple(sorted(dets)), tuple(sorted(obs)))
        q = merged.get(key, 0.0)
        merged[key] = q + p - 2.0 * q * p  # XOR of independent flips
    keys = list(merged)
    det_rows, det_cols, obs_rows, obs_cols = [], [], [], []
    for e, (dets_t, obs_t) in enumerate(keys):
        det_rows += list(dets_t)
        det_cols += [e] * len(dets_t)
        obs_rows += list(obs_t)
        obs_cols += [e] * len(obs_t)
    shape_d = (dem.num_detectors, len(keys))
    shape_o = (dem.num_observables, len(keys))
    return _DemMatrices(
        checks=csr_matrix((np.ones(len(det_rows), np.uint8), (det_rows, det_cols)), shape=shape_d),
        observables=csr_matrix(
            (np.ones(len(obs_rows), np.uint8), (obs_rows, obs_cols)), shape=shape_o
        ),
        priors=tuple(merged[k] for k in keys),
        detector_sets=tuple(k[0] for k in keys),
    )


class BpOsdWrapper:
    """ldpc's BpOsdDecoder behind the Decoder protocol, throttleable at runtime.

    Decodes the full detector vector against the DEM's check matrix; the
    predicted observable flips are the observable matrix applied to the
    estimated error vector.
    """

    name = "bposd"

    def __init__(
        self,
        *,
        dem: str,
        slowdown_factor: float = 1.0,
        max_iter: int = 30,
        ms_scaling_factor: float = 0.625,
        osd_method: str = "OSD_0",
        osd_order: int = 0,
    ) -> None:
        """Build BP+OSD from a serialized detector error model.

        Args:
            dem: stim DEM text, as served at the block's query address.
            slowdown_factor: Artificial latency multiplier (1.0 = none).
            max_iter: BP iterations before OSD post-processing kicks in.
            ms_scaling_factor: Min-sum normalization (0.625 per Roffe et al.).
            osd_method: ``OSD_0`` (fast) | ``OSD_E`` | ``OSD_CS`` (thorough).
            osd_order: Search order for the exhaustive/combination-sweep methods.
        """
        self._matrices = _dem_matrices(stim.DetectorErrorModel(dem))
        self._bposd = BpOsdDecoder(
            self._matrices.checks,
            error_channel=list(self._matrices.priors),
            max_iter=max_iter,
            bp_method="minimum_sum",
            ms_scaling_factor=ms_scaling_factor,
            osd_method=osd_method,
            osd_order=osd_order,
        )
        self.slowdown_factor = slowdown_factor

    def decode(self, syndrome: npt.NDArray[np.uint8]) -> DecodeResult:
        """Decode one detector vector; latency is real wall-clock, throttle included."""
        t0 = time.perf_counter()
        error_estimate = self._bposd.decode(syndrome)
        flips = (self._matrices.observables @ error_estimate) % 2
        blamed = tuple(self._matrices.detector_sets[int(e)] for e in np.flatnonzero(error_estimate))
        elapsed = time.perf_counter() - t0
        if self.slowdown_factor > 1.0:
            time.sleep(elapsed * (self.slowdown_factor - 1.0))
        return DecodeResult(
            predicted_flips=tuple(int(i) for i in np.flatnonzero(flips)),
            matched_detectors=blamed,
            latency_s=time.perf_counter() - t0,
        )
