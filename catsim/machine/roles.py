"""Fleet role balancing: memory vs factory chips per the paper's Table I mix.

Exists so the scheduler assigns roles from one published ratio instead of ad
hoc: arXiv:2604.19481 Table I pairs 17 Q70 memory blocks with one CH2 factory
for ~1M T gates/day, so with one block per chip the fleet keeps one factory
chip per 17 memory chips. Pure arithmetic — no bus, no state.
"""

from __future__ import annotations

from catsim.machine.config import ChipComposition

MEMORY_BLOCKS_PER_FACTORY = 17
"""Table I (17xQ70 + 1xCH2 = 1M T/day): memory blocks one CH2 factory serves."""

FACTORY_CHIP = ChipComposition(
    nominal_qubits=256,
    accounting="paper",
    blocks=[],
    magic_factories=["ch2"],
)
"""The factory chip: one CH2 magic-state factory (173 qubits, Table V), no
memory blocks. Same container image as a memory chip — the role is assigned
at admission, not baked in."""


def desired_factories(total_chips: int, blocks_per_memory_chip: int = 1) -> int:
    """How many of ``total_chips`` should be factory chips at the Table I mix.

    Args:
        total_chips: Fleet size including the factories themselves.
        blocks_per_memory_chip: Memory blocks hosted per memory chip.

    Returns:
        Factory-chip count: one per ``17 / blocks_per_memory_chip`` memory
        chips (rounded to keep the served ratio at or under 17:1), never
        leaving zero memory chips.
    """
    memory_chips_per_factory = max(1, MEMORY_BLOCKS_PER_FACTORY // blocks_per_memory_chip)
    return min(total_chips // (memory_chips_per_factory + 1), total_chips - 1) if total_chips else 0


def next_role(memory_chips: int, factory_chips: int, blocks_per_memory_chip: int = 1) -> str:
    """The role the next admitted chip should take, given the current mix.

    The first chip is always memory (a factory with nothing to serve is
    dead weight); afterwards a chip becomes a factory whenever the fleet has
    fewer factories than :func:`desired_factories` would give the grown fleet.
    """
    total_after = memory_chips + factory_chips + 1
    if factory_chips < desired_factories(total_after, blocks_per_memory_chip):
        return "factory"
    return "memory"
