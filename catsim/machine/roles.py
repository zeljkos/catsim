"""Fleet role and demand placement: Table I role mix, per-module locality.

Exists so the scheduler assigns roles and routes T demand from published
ratios and marked assumptions instead of ad hoc: arXiv:2604.19481 Table I
pairs 17 Q70 memory blocks with one CH2 factory for ~1M T gates/day, so with
one block per chip the fleet keeps one factory chip per 17 memory chips —
balanced per module (M7), because cross-module gates ride the assumed-scarce
photonic interconnect (NUMA analogy: prefer local placement, cross sparingly).
Pure arithmetic — no bus, no state.
"""

from __future__ import annotations

from collections.abc import Mapping

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
    M7: applied per module, so every module carries its own Table I mix.
    """
    total_after = memory_chips + factory_chips + 1
    if factory_chips < desired_factories(total_after, blocks_per_memory_chip):
        return "factory"
    return "memory"


def module_name(index: int) -> str:
    """Display name of the ``index``-th module: A, B, … (M26, M27, … beyond Z)."""
    return chr(ord("A") + index) if index < 26 else f"M{index}"


def split_demand(
    total: float,
    memory_by_module: Mapping[str, int],
    factories_by_module: Mapping[str, int],
    cross_fraction: float,
) -> tuple[dict[str, float], float]:
    """Split the fleet's T demand into per-module local demand plus cross demand.

    Demand originates at memory chips, proportional to each module's share.
    With one populated module everything is local — there is no link to cross.
    With several, the ASSUMED ``cross_fraction`` of each module's share spans
    modules (consuming banked interconnect pairs), and a module with no local
    factory sends its whole share across — the locality-aware placement's
    fallback while a young module has not yet earned its own factory.

    Args:
        total: Fleet T-gate demand (gates/second).
        memory_by_module: Memory-chip count per module.
        factories_by_module: Factory-chip count per module.
        cross_fraction: Assumed fraction of demand spanning modules.

    Returns:
        (local demand per module, cross-module demand) in gates/second.
    """
    mem_total = sum(memory_by_module.values())
    if mem_total == 0 or total <= 0:
        return {}, 0.0
    origins = [m for m, n in memory_by_module.items() if n > 0]
    occupied = {m for m, n in memory_by_module.items() if n > 0}
    occupied |= {m for m, n in factories_by_module.items() if n > 0}
    if len(occupied) <= 1:
        return {origins[0]: total}, 0.0
    local: dict[str, float] = {}
    cross = 0.0
    for module in origins:
        share = total * memory_by_module[module] / mem_total
        if factories_by_module.get(module, 0) > 0:
            local[module] = share * (1.0 - cross_fraction)
            cross += share * cross_fraction
        else:
            cross += share
    return local, cross
