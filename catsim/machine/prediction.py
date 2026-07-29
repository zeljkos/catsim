"""Table I arithmetic: predicted capacity and throughput for a composition.

Exists so the machine view's predicted-vs-measured panel draws a prediction
line computed from the paper alone (Table V prices, Table VII gate times) for
whatever composition is currently registered — and divergence from the live
measurement is surfaced, never tuned away.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from catsim.machine.calibration import t_pair_seconds
from catsim.machine.pricing import GLOBAL_RESERVOIR_QUBITS, price_chip

_DAY_SECONDS = 86_400.0

NO_MAGIC_FACTORY = "no magic factory — T gates need a factory chip"
"""Stall attribution shown whenever the composition cannot execute T gates."""


@dataclass(frozen=True)
class MachinePrediction:
    """What the paper's arithmetic promises for a composition."""

    logical_qubits: int
    physical_qubits: int
    t_per_day: float
    t_stall_reason: str


def predict_machine(
    block_codes: Sequence[str],
    block_logicals: Sequence[int],
    magic_kinds: Sequence[str],
) -> MachinePrediction:
    """Evaluate Table I arithmetic for a machine-wide composition.

    Args:
        block_codes: Code name of every memory block in the machine.
        block_logicals: Logical qubits per block (same order).
        magic_kinds: Every magic factory in the machine (``ch2``/``mek``).

    Returns:
        Predicted logical qubits (sum of block k), paper-accounting physical
        qubits (Table V prices + the shared reservoir; transport/Bell overhead
        excluded, see :mod:`catsim.machine.pricing`), and T-gate throughput
        (Table VII double-T times; two T gates per magic-state pair).
    """
    bill = price_chip(block_codes, magic_kinds)
    memory_code = block_codes[0] if block_codes else "q70"
    t_per_day = sum(2.0 * _DAY_SECONDS / t_pair_seconds(memory_code, kind) for kind in magic_kinds)
    return MachinePrediction(
        logical_qubits=sum(block_logicals),
        physical_qubits=bill.total + GLOBAL_RESERVOIR_QUBITS,
        t_per_day=t_per_day,
        t_stall_reason="" if magic_kinds else NO_MAGIC_FACTORY,
    )
