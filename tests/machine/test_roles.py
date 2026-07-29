"""Role policy: the Table I memory:factory mix as the fleet grows."""

from catsim.machine import desired_factories, next_role
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
