"""Role and demand placement: Table I mix, module names, locality split."""

from catsim.machine import desired_factories, module_name, next_role, split_demand
from catsim.machine.roles import FACTORY_CHIP


def _grow(n: int, blocks_per: int = 1) -> list[str]:
    roles: list[str] = []
    for _ in range(n):
        memory = roles.count("memory")
        factory = roles.count("factory")
        roles.append(next_role(memory, factory, blocks_per))
    return roles


def test_first_chip_is_always_memory() -> None:
    assert next_role(0, 0) == "memory"


def test_one_factory_per_17_memory_blocks() -> None:
    roles = _grow(40)
    # Chips 18 and 36 (1-based) become factories: 17:1 served ratio (Table I).
    assert [i for i, r in enumerate(roles, start=1) if r == "factory"] == [18, 36]
    assert roles.count("memory") == 38


def test_desired_factories_scales_with_blocks_per_chip() -> None:
    assert desired_factories(17) == 0
    assert desired_factories(18) == 1
    assert desired_factories(40) == 2
    # Two blocks per memory chip: a factory every 8 memory chips (16 blocks).
    assert desired_factories(9, blocks_per_memory_chip=2) == 1
    assert desired_factories(1) == 0


def test_factory_chip_hosts_one_ch2_and_no_blocks() -> None:
    assert FACTORY_CHIP.blocks == []
    assert FACTORY_CHIP.magic_factories == ["ch2"]
    assert FACTORY_CHIP.accounting == "paper"


def test_module_names_run_a_to_z_then_numbered() -> None:
    assert [module_name(i) for i in (0, 1, 25, 26)] == ["A", "B", "Z", "M26"]


def test_split_demand_single_module_is_all_local() -> None:
    local, cross = split_demand(12.0, {"A": 17}, {"A": 1}, cross_fraction=0.25)
    assert local == {"A": 12.0}
    assert cross == 0.0


def test_split_demand_two_modules_cross_by_assumed_fraction() -> None:
    local, cross = split_demand(12.0, {"A": 19, "B": 19}, {"A": 1, "B": 1}, 0.25)
    assert local == {"A": 4.5, "B": 4.5}
    assert cross == 3.0


def test_split_demand_factory_less_module_crosses_entirely() -> None:
    local, cross = split_demand(12.0, {"A": 30, "B": 10}, {"A": 2}, 0.25)
    assert local == {"A": 9.0 * 0.75}  # A's 9.0 share keeps its local fraction
    assert abs(cross - (9.0 * 0.25 + 3.0)) < 1e-12  # B's whole 3.0 rides the link


def test_split_demand_factory_only_far_module_still_counts_as_multi() -> None:
    # Module B holds only factories: A's demand must cross to reach them.
    local, cross = split_demand(12.0, {"A": 10}, {"B": 1}, 0.25)
    assert local == {}
    assert cross == 12.0


def test_split_demand_nothing_to_split() -> None:
    assert split_demand(0.0, {"A": 10}, {"A": 1}, 0.25) == ({}, 0.0)
    assert split_demand(12.0, {}, {}, 0.25) == ({}, 0.0)
