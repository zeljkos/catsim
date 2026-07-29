"""Table V price list pins: per-block/factory costs exactly as published."""

import pytest

from catsim.machine import price_chip
from catsim.machine.pricing import (
    CAT_FACTORY_QUBITS,
    GLOBAL_RESERVOIR_QUBITS,
    MAGIC_FACTORY_QUBITS,
    MEMORY_BLOCK_LOGICAL,
    MEMORY_BLOCK_QUBITS,
)


def test_price_list_matches_table_v_derivations() -> None:
    # Memory column / block count: 3,740 / 17 and 1,580 / 5.
    assert MEMORY_BLOCK_QUBITS == {"q70": 220, "q102": 316}
    assert 17 * MEMORY_BLOCK_QUBITS["q70"] == 3_740
    assert 5 * MEMORY_BLOCK_QUBITS["q102"] == 1_580
    # Cat column / block count: 720 / 17 -> 42, 408 / 5 -> 82 (rounded).
    assert CAT_FACTORY_QUBITS == {"q70": 42, "q102": 82}
    # Magic column / factory count: 663 / 3 and 173 / 1.
    assert MAGIC_FACTORY_QUBITS == {"mek": 221, "ch2": 173}
    assert 3 * MAGIC_FACTORY_QUBITS["mek"] == 663
    # Reservoir: 200 in every Table V row, shared machine-wide.
    assert GLOBAL_RESERVOIR_QUBITS == 200


def test_logical_per_block_matches_table_xxx() -> None:
    assert MEMORY_BLOCK_LOGICAL == {"q70": 6, "q102": 22}


def test_chip_256_bill_is_262() -> None:
    bill = price_chip(["q70"], [])
    assert bill.memory_qubits == (220,)
    assert bill.cat_qubits == (42,)
    assert bill.total == 262


def test_roadmap_chip_bill_is_524() -> None:
    assert price_chip(["q70", "q70"], []).total == 524


def test_factory_chip_bill() -> None:
    assert price_chip([], ["ch2"]).total == 173
    assert price_chip(["q70"], ["mek"]).total == 220 + 42 + 221


def test_unknown_code_rejected() -> None:
    with pytest.raises(KeyError, match="no Table V price"):
        price_chip(["q999"], [])
    with pytest.raises(KeyError, match="no Table V price"):
        price_chip(["q70"], ["t-fountain"])
