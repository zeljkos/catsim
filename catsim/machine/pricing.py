"""Qubit price list from arXiv:2604.19481 Table V — chip accounting, not physics.

Exists so chip composition is config-driven against one published price list:
a chip YAML lists blocks and factories, this module prices the composition,
and the machine view shows the paper-accounting total next to the nominal
label (divergence displayed, never hidden).

Every price derives from Table V (qubit allocation for walking cat instances).
Per-block prices are the memory/cat columns divided by the block count of the
1M T/day rows (17xQ70 and 5xQ102); factory prices are the magic column per
factory. Bell pairs and transport lanes (~8% of a machine) scale with the
whole machine, not with one chip, so chip-granular accounting excludes them —
the exclusion is documented wherever a total is shown.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

MEMORY_BLOCK_QUBITS = {
    # Table V memory column / block count: 3,740 / 17 (Q70), 1,580 / 5 (Q102).
    # All-in per block: 2n data+ancilla (Table IX) + beacon + local reservoir.
    "q70": 220,
    "q102": 316,
}

MEMORY_BLOCK_LOGICAL = {
    # Table XXX (and Table I): logical qubits per memory block. The real code
    # objects compute the same k from their check matrices (pinned in
    # tests/codes); a mismatch here would be a finding, not a tuning knob.
    "q70": 6,
    "q102": 22,
}

CAT_FACTORY_QUBITS = {
    # Table V cat column / block count: 720 / 17 (Q70), 408 / 5 (Q102).
    # One cat unit per memory block feeds its verification/measurement needs.
    "q70": 42,
    "q102": 82,
}

MAGIC_FACTORY_QUBITS = {
    # Table V magic column / factory count: 663 / 3 (MEK), 173 / 1 (CH2).
    "mek": 221,
    "ch2": 173,
}

GLOBAL_RESERVOIR_QUBITS = 200
"""Table V reservoir column: 200 in every configuration — shared machine-wide,
counted once, never per chip."""


@dataclass(frozen=True)
class ChipBill:
    """A chip composition priced at Table V rates.

    ``total`` covers blocks, their cat units, and local magic factories; the
    shared reservoir and machine-wide transport/Bell overhead are excluded
    (machine-level costs, see module docstring).
    """

    memory_qubits: tuple[int, ...]
    cat_qubits: tuple[int, ...]
    magic_qubits: tuple[int, ...]

    @property
    def total(self) -> int:
        """Paper-accounting qubits for this chip alone."""
        return sum(self.memory_qubits) + sum(self.cat_qubits) + sum(self.magic_qubits)


def price_chip(block_codes: Sequence[str], magic_kinds: Sequence[str]) -> ChipBill:
    """Price a chip composition against the Table V list.

    Args:
        block_codes: Code name per memory block (e.g. ``["q70", "q70"]``);
            each block brings its cat unit.
        magic_kinds: Local magic factories (e.g. ``["ch2"]``; usually empty —
            memory chips have none).

    Returns:
        The itemized bill.

    Raises:
        KeyError: If a code or factory kind has no published price.
    """
    for code in block_codes:
        if code not in MEMORY_BLOCK_QUBITS:
            raise KeyError(
                f"no Table V price for code {code!r}; known: {sorted(MEMORY_BLOCK_QUBITS)}"
            )
    for kind in magic_kinds:
        if kind not in MAGIC_FACTORY_QUBITS:
            raise KeyError(
                f"no Table V price for factory {kind!r}; known: {sorted(MAGIC_FACTORY_QUBITS)}"
            )
    return ChipBill(
        memory_qubits=tuple(MEMORY_BLOCK_QUBITS[c] for c in block_codes),
        cat_qubits=tuple(CAT_FACTORY_QUBITS[c] for c in block_codes),
        magic_qubits=tuple(MAGIC_FACTORY_QUBITS[k] for k in magic_kinds),
    )
