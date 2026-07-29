"""FleetLedger: backlog accrual, locality split routing, interconnect status."""

from catsim.machine import InterconnectConfig
from catsim.machine.config import WorkloadConfig
from catsim.machine.ledger import FleetLedger


def _ledger(cross_fraction: float = 0.25) -> FleetLedger:
    return FleetLedger(
        WorkloadConfig(t_per_second=12.0, cross_module_fraction=cross_fraction),
        InterconnectConfig(pair_rate_hz=100.0, bank_capacity=60),
    )


def test_demand_piles_into_pending_while_no_factory_exists() -> None:
    ledger = _ledger()
    ledger.accrue(100.0, {"A": 1}, {})
    assert ledger.pending == 1200  # 12 T/s x 100 machine-seconds
    assert ledger.cross_demand_per_second == 0.0
    assert ledger.take_pending() == 1200
    assert ledger.pending == 0


def test_single_module_routes_nothing_across() -> None:
    ledger = _ledger()
    ledger.accrue(100.0, {"A": 17}, {"A": 1})
    assert ledger.cross_demand_per_second == 0.0
    assert ledger.local_demand({"A": 17}, {"A": 1}) == {"A": 12.0}
    assert ledger.interconnect.cross_served == 0.0


def test_two_modules_split_by_the_assumed_cross_fraction() -> None:
    ledger = _ledger()
    memory, factories = {"A": 19, "B": 19}, {"A": 1, "B": 1}
    ledger.accrue(10.0, memory, factories)
    assert ledger.cross_demand_per_second == 3.0  # 12 x 0.25
    assert ledger.local_demand(memory, factories) == {"A": 4.5, "B": 4.5}
    assert ledger.interconnect.cross_served == 30.0  # 3/s x 10 machine-s


def test_factory_less_module_sends_its_whole_share_across() -> None:
    ledger = _ledger()
    memory, factories = {"A": 30, "B": 10}, {"A": 2}
    local = ledger.local_demand(memory, factories)
    assert local == {"A": 12.0 * 0.75 * 0.75}  # A's share x (1 - cross fraction)
    ledger.accrue(1.0, memory, factories)
    # B's whole 3.0 share + A's 0.25 cross slice
    assert ledger.cross_demand_per_second == 12.0 * 0.75 * 0.25 + 3.0


def test_interconnect_status_echoes_the_assumed_parameters() -> None:
    ledger = _ledger()
    ledger.accrue(10.0, {"A": 19, "B": 19}, {"A": 1, "B": 1})
    status = ledger.interconnect_status("scheduler", modules=2)
    assert status.modules == 2
    assert status.pair_rate_hz == 100.0
    assert status.bank_capacity == 60
    assert status.bank == 60
    assert status.cross_demand_per_second == 3.0
    assert status.cross_t_served == 30
    assert status.cross_queue_depth == 0
    assert not status.severed
