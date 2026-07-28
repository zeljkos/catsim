"""Generic CSS memory circuit: syndrome extraction from check matrices alone.

Exists so any CSS code (GB/Q102 now, more qLDPC families later) runs through
the exact pipeline the surface code proved in M0 — same noise mapping, same
round segmentation, same events.

Schedule note: this builder uses the straightforward per-check CNOT schedule
(step t touches every check's t-th support qubit; ancillas never collide
because each CX pairs one ancilla with one data qubit). The paper's Table X
schedule permutation is the production schedule — it is searched so hook
errors preserve the circuit-level suppression exponent (⌈d_circ/2⌉ = ⌈d/2⌉,
arXiv:2604.19481 Section IX.B). Wiring that permutation in is a documented
follow-up; until then measured curves sit below the paper's (a finding to
surface, per charter, never tune away).
"""

from __future__ import annotations

import math
from typing import Literal

import numpy as np
import stim

from catsim.codes import CSSCode, QECCode
from catsim.component.noise import NoiseModel

Basis = Literal["Z", "X"]

_RING_X_ANCILLA = 8.0
_RING_DATA = (10.0, 12.0)
_RING_Z_ANCILLA = 14.0
"""Block-view rings (inner to outer): X checks, data halves, Z checks.
GB codes are cyclic, not planar; concentric rings indexed by cyclic position
are the generic layout the dashboard renders for any non-planar code."""


def build_css_memory(
    code: QECCode, noise: NoiseModel, rounds: int, basis: Basis = "Z"
) -> stim.Circuit:
    """Noisy memory experiment for a CSS code: ``rounds`` SE rounds.

    Detectors: first round only the basis-deterministic checks (Z checks for a
    |0..0> start, X checks for |+..+>), then every check against its own
    previous outcome, finally the basis checks against the data readout parity.

    Args:
        code: A code satisfying :class:`catsim.codes.CSSCode`.
        noise: Circuit-level noise (same channel mapping as the surface builder).
        rounds: Syndrome-extraction rounds (>= 2).
        basis: ``"Z"`` protects a |0..0> start, ``"X"`` the mirror-image |+..+>.

    Returns:
        The annotated circuit (detectors carry check coordinates, observables
        are the code's logical operators of the memory basis).
    """
    if rounds < 2:
        raise ValueError(f"need at least 2 rounds to tick a live block, got {rounds}")
    if not isinstance(code, CSSCode):
        raise TypeError(f"{code.name} does not expose CSS check matrices")
    b = _CssMemoryBuilder(code, noise, basis)
    return b.build(rounds)


class _CssMemoryBuilder:
    """One-shot builder holding the index/coordinate bookkeeping."""

    def __init__(self, code: CSSCode, noise: NoiseModel, basis: Basis) -> None:
        """Precompute qubit indices, check supports, and ring coordinates."""
        self._noise = noise
        self._basis = basis
        n = code.num_data_qubits
        self._data = list(range(n))
        self._xanc = [n + i for i in range(code.hx.shape[0])]
        self._zanc = [n + len(self._xanc) + i for i in range(code.hz.shape[0])]
        self._xsup = [[int(q) for q in np.flatnonzero(row)] for row in code.hx]
        self._zsup = [[int(q) for q in np.flatnonzero(row)] for row in code.hz]
        self._logical = code.logical_z if basis == "Z" else code.logical_x
        self._coords = _ring_coords(n, len(self._xanc), len(self._zanc))

    def build(self, rounds: int) -> stim.Circuit:
        """Assemble init round + REPEAT body + final readout."""
        anc = self._xanc + self._zanc
        c = stim.Circuit()
        for q in self._data + anc:
            c.append("QUBIT_COORDS", [q], self._coords[q])
        c.append("R", self._data + anc)
        if self._noise.reset_error > 0:
            c.append("X_ERROR", self._data + anc, self._noise.reset_error)
        if self._basis == "X":
            c.append("H", self._data)
        c.append("TICK")
        c += self._se_round()
        first = self._zanc if self._basis == "Z" else self._xanc
        offset = len(self._xanc) if self._basis == "Z" else 0
        for i, q in enumerate(first):
            c.append(
                "DETECTOR",
                [stim.target_rec(-len(anc) + offset + i)],
                [*self._coords[q], 0],
            )
        body = self._se_round()
        for i, q in enumerate(anc):
            body.append(
                "DETECTOR",
                [stim.target_rec(-len(anc) + i), stim.target_rec(-2 * len(anc) + i)],
                [*self._coords[q], 0],
            )
        body.append("SHIFT_COORDS", [], [0, 0, 1])
        c.append(stim.CircuitRepeatBlock(rounds - 1, body))
        return c + self._final(len(anc), offset)

    def _se_round(self) -> stim.Circuit:
        """One syndrome-extraction round: per-check CNOT ladder, then MR."""
        noise, anc = self._noise, self._xanc + self._zanc
        b = stim.Circuit()
        if noise.single_qubit_gate_error > 0:
            b.append("DEPOLARIZE1", self._data, noise.single_qubit_gate_error)
        b.append("H", self._xanc)
        b.append("TICK")
        for supports, ancillas, anc_is_control in (
            (self._xsup, self._xanc, True),
            (self._zsup, self._zanc, False),
        ):
            for t in range(max(len(s) for s in supports)):
                pairs: list[int] = []
                for i, support in enumerate(supports):
                    if t < len(support):
                        a, d = ancillas[i], support[t]
                        pairs += [a, d] if anc_is_control else [d, a]
                b.append("CX", pairs)
                if noise.two_qubit_gate_error > 0:
                    b.append("DEPOLARIZE2", pairs, noise.two_qubit_gate_error)
                b.append("TICK")
        b.append("H", self._xanc)
        b.append("TICK")
        if noise.measurement_error > 0:
            b.append("X_ERROR", anc, noise.measurement_error)
        b.append("MR", anc)
        if noise.reset_error > 0:
            b.append("X_ERROR", anc, noise.reset_error)
        return b

    def _final(self, num_anc: int, offset: int) -> stim.Circuit:
        """Data readout: final-check detectors and logical observables."""
        n = len(self._data)
        fin = stim.Circuit()
        if self._noise.measurement_error > 0:
            flip = "X_ERROR" if self._basis == "Z" else "Z_ERROR"
            fin.append(flip, self._data, self._noise.measurement_error)
        fin.append("M" if self._basis == "Z" else "MX", self._data)
        supports = self._zsup if self._basis == "Z" else self._xsup
        ancillas = self._zanc if self._basis == "Z" else self._xanc
        for i, support in enumerate(supports):
            recs = [stim.target_rec(-n + q) for q in support]
            recs.append(stim.target_rec(-n - num_anc + offset + i))
            fin.append("DETECTOR", recs, [*self._coords[ancillas[i]], 1])
        for j, op in enumerate(self._logical):
            targets = [stim.target_rec(-n + q) for q in np.flatnonzero(op)]
            fin.append("OBSERVABLE_INCLUDE", targets, j)
        return fin


def _ring_coords(n: int, num_x: int, num_z: int) -> dict[int, tuple[float, float]]:
    """Concentric-ring (x, y) for every qubit index, keyed by cyclic position."""
    coords: dict[int, tuple[float, float]] = {}

    def place(index: int, ring: float, position: int, count: int) -> None:
        angle = 2 * math.pi * position / count
        coords[index] = (ring * math.cos(angle), ring * math.sin(angle))

    half = n // 2
    for q in range(n):
        ring = _RING_DATA[0] if q < half else _RING_DATA[1]
        place(q, ring, q % half, half)
    for i in range(num_x):
        place(n + i, _RING_X_ANCILLA, i, num_x)
    for i in range(num_z):
        place(n + num_x + i, _RING_Z_ANCILLA, i, num_z)
    return coords
