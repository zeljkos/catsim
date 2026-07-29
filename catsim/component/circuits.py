"""Stim circuit builders for memory blocks, plus round segmentation for live ticking.

Exists so every consumer (live loop, sinter batch) gets circuits from the same
builder, and so the live loop can execute one syndrome-extraction round per tick.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import stim

from catsim.codes import QECCode
from catsim.component.css import build_css_memory
from catsim.component.noise import NoiseModel

CircuitBuilder = Callable[[QECCode, NoiseModel, int], stim.Circuit]

_BUILDERS: dict[str, CircuitBuilder] = {}


def register_builder(family: str, builder: CircuitBuilder) -> None:
    """Register a memory-circuit builder for a code family."""
    _BUILDERS[family] = builder


def build_memory_circuit(code: QECCode, noise: NoiseModel, rounds: int) -> stim.Circuit:
    """Build the noisy memory experiment for ``code``: ``rounds`` SE rounds.

    Args:
        code: The QEC code instance (dispatches on ``code.family``).
        noise: Noise model applied at circuit level.
        rounds: Number of syndrome-extraction rounds (>= 2).

    Returns:
        A stim circuit with detectors and logical observables annotated.
    """
    if rounds < 2:
        raise ValueError(f"need at least 2 rounds to tick a live block, got {rounds}")
    if code.family not in _BUILDERS:
        raise KeyError(f"no circuit builder for code family {code.family!r}")
    return _BUILDERS[code.family](code, noise, rounds)


def _build_surface_memory(code: QECCode, noise: NoiseModel, rounds: int) -> stim.Circuit:
    """Rotated surface-code memory (Z basis) via stim's generator.

    Noise mapping (documented divergence, per charter surfaced not tuned):
    stim's ``after_clifford_depolarization`` applies one rate to ALL Clifford
    gates, so single-qubit gates get the two-qubit rate (1e-4 vs the paper's
    1e-5 — conservative). The paper's single-qubit rate is applied as per-round
    data depolarization instead. Rates: CLAUDE.md canonical parameters,
    arXiv:2604.19481.
    """
    return stim.Circuit.generated(
        "surface_code:rotated_memory_z",
        distance=code.distance,
        rounds=rounds,
        after_clifford_depolarization=noise.two_qubit_gate_error,
        before_round_data_depolarization=noise.single_qubit_gate_error,
        before_measure_flip_probability=noise.measurement_error,
        after_reset_flip_probability=noise.reset_error,
    )


def _build_two_block_memory(code: QECCode, noise: NoiseModel, rounds: int) -> stim.Circuit:
    """GB/BB memory (Z basis) through the generic CSS builder."""
    return build_css_memory(code, noise, rounds, basis="Z")


register_builder("surface", _build_surface_memory)
register_builder("gb", _build_two_block_memory)
register_builder("bb", _build_two_block_memory)


def memory_detector_error_model(circuit: stim.Circuit) -> stim.DetectorErrorModel:
    """The circuit's DEM, decomposed into graphlike edges when possible.

    Matching decoders need the decomposition; qLDPC circuits have hyperedge
    error mechanisms stim cannot decompose, so those fall back to the plain
    DEM (which BP+OSD consumes natively).
    """
    try:
        return circuit.detector_error_model(decompose_errors=True)
    except ValueError:
        return circuit.detector_error_model()


@dataclass(frozen=True)
class RoundSegments:
    """A memory circuit cut into live-tickable pieces.

    ``init`` prepares the block and runs round 0; ``body`` is one SE round,
    executed ``repeats`` times; ``final`` measures out and closes detectors.
    """

    init: stim.Circuit
    body: stim.Circuit
    repeats: int
    final: stim.Circuit


def split_into_rounds(circuit: stim.Circuit) -> RoundSegments:
    """Cut a generated memory circuit at its REPEAT block for per-round ticking.

    Args:
        circuit: A memory circuit with exactly one top-level REPEAT block.

    Returns:
        The init/body/final segments; total detector counts are preserved.

    Raises:
        ValueError: If the circuit has no top-level REPEAT block.
    """
    init, final = stim.Circuit(), stim.Circuit()
    body: stim.Circuit | None = None
    repeats = 0
    for inst in circuit:
        if isinstance(inst, stim.CircuitRepeatBlock):
            if body is not None:
                raise ValueError("expected exactly one top-level REPEAT block")
            body, repeats = inst.body_copy(), inst.repeat_count
        elif body is None:
            init.append(inst)
        else:
            final.append(inst)
    if body is None:
        raise ValueError("circuit has no top-level REPEAT block; use rounds >= 2")
    return RoundSegments(init=init, body=body, repeats=repeats, final=final)
