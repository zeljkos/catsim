"""Machine config loading: shipped YAMLs validate and mean what they say."""

import pytest
from pydantic import ValidationError

from catsim.machine import available_machines, load_machine_config
from tests.conftest import REPO_ROOT

MACHINE_DIR = REPO_ROOT / "configs" / "machine"


def test_shipped_machines_listed() -> None:
    assert {"chip-256", "chip-256-roadmap"} <= set(available_machines(MACHINE_DIR))


def test_chip_256_is_paper_faithful() -> None:
    cfg = load_machine_config("chip-256", MACHINE_DIR)
    assert cfg.chips == 1
    assert cfg.chip.accounting == "paper"
    assert [b.code for b in cfg.chip.blocks] == ["q70"]
    assert [b.family for b in cfg.chip.blocks] == ["bb"]
    assert cfg.chip.magic_factories == []  # memory-only: T gates need a factory chip


def test_roadmap_chip_documents_divergence() -> None:
    cfg = load_machine_config("chip-256-roadmap", MACHINE_DIR)
    assert cfg.chip.accounting == "lean"
    assert [b.code for b in cfg.chip.blocks] == ["q70", "q70"]
    assert cfg.chip.nominal_qubits == 256
    # the divergence must be documented, not implicit
    assert "524" in cfg.chip.accounting_note
    assert "1e-7" in cfg.chip.accounting_note


def test_two_module_machine_carries_assumed_interconnect() -> None:
    cfg = load_machine_config("chip-256-x80-2mod", MACHINE_DIR)
    assert cfg.chips == 80
    assert cfg.module.capacity_chips == 40  # two modules of 40
    assert cfg.interconnect.pair_rate_hz == 100.0  # ASSUMPTION: ~10^2 pairs/s literature
    assert cfg.interconnect.bank_capacity == 60
    assert cfg.workload.cross_module_fraction == 0.25
    # The sourcing caveat must be in the shipped file, not just in docs.
    text = (MACHINE_DIR / "chip-256-x80-2mod.yaml").read_text()
    assert "ASSUMPTION" in text
    assert "NOT from arXiv:2604.19481" in text


def test_unit_chip_defaults_module_and_interconnect() -> None:
    cfg = load_machine_config("chip-256", MACHINE_DIR)
    assert cfg.module.capacity_chips == 40
    assert cfg.interconnect.latency_s == 0.01  # ASSUMPTION, echoed on the bus


def test_lean_accounting_requires_note() -> None:
    from catsim.machine.config import BlockComposition, ChipComposition

    with pytest.raises(ValidationError, match="accounting_note"):
        ChipComposition(
            nominal_qubits=256, accounting="lean", blocks=[BlockComposition()], accounting_note=""
        )


def test_load_by_path(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "custom.yaml"
    path.write_text(
        "name: custom\nchip:\n  nominal_qubits: 128\n  blocks:\n    - {family: gb, code: q102}\n"
    )
    cfg = load_machine_config(path)
    assert cfg.name == "custom"
    assert cfg.chip.blocks[0].code == "q102"
    assert cfg.workload.t_per_second == 12.0  # default demand
