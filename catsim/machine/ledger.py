"""Fleet accounting: measured counters, unserved backlog, interconnect bank.

Exists so the scheduler stays a membership-and-assignment service: everything
it must *account for over machine time* — shots and logical errors observed,
T demand that piled up before any factory existed, and the photonic
interconnect's pair bank with its cross-module demand (M7) — lives here,
advanced from the fleet's machine clock.
"""

from __future__ import annotations

from collections.abc import Mapping

from catsim.bus import InterconnectStatus
from catsim.machine.config import InterconnectConfig, WorkloadConfig
from catsim.machine.interconnect import InterconnectModel
from catsim.machine.roles import split_demand


class FleetLedger:
    """Machine-time accounting the scheduler reads and publishes from.

    Single-threaded, owned by the scheduler; ``accrue`` must be called with a
    monotonically advancing machine clock (the furthest chip's machine time).
    """

    def __init__(self, workload: WorkloadConfig, interconnect: InterconnectConfig) -> None:
        """Start all counters at zero around the configured workload and link."""
        self._workload = workload
        self.interconnect = InterconnectModel(interconnect)
        self.shots = 0
        self.logical_errors = 0
        self._pending = 0.0  # float: per-accrual increments are fractional
        self._marker = 0.0  # machine seconds already accounted
        self._cross_demand = 0.0

    @property
    def pending(self) -> int:
        """Whole T gates owed from before the fleet had any factory."""
        return int(self._pending)

    @property
    def cross_demand_per_second(self) -> float:
        """The cross-module demand rate the link was last advanced with."""
        return self._cross_demand

    def accrue(
        self,
        machine_seconds: float,
        memory_by_module: Mapping[str, int],
        factories_by_module: Mapping[str, int],
    ) -> None:
        """Advance backlog and interconnect to the fleet's machine clock.

        With no factory anywhere, all demand piles into the pending backlog
        (nothing can serve it, local or cross). Otherwise the assumed locality
        split routes the cross portion through the pair bank.
        """
        dt = max(0.0, machine_seconds - self._marker)
        self._marker = machine_seconds
        occupied = {m for m, n in memory_by_module.items() if n > 0}
        occupied |= {m for m, n in factories_by_module.items() if n > 0}
        if not any(factories_by_module.values()):
            self._pending += self._workload.t_per_second * dt
            self._cross_demand = 0.0
        else:
            _, self._cross_demand = split_demand(
                self._workload.t_per_second,
                memory_by_module,
                factories_by_module,
                self._workload.cross_module_fraction,
            )
        self.interconnect.advance(dt, self._cross_demand, active=len(occupied) > 1)

    def local_demand(
        self,
        memory_by_module: Mapping[str, int],
        factories_by_module: Mapping[str, int],
    ) -> dict[str, float]:
        """Per-module locally-served T demand under the assumed locality split."""
        local, _ = split_demand(
            self._workload.t_per_second,
            memory_by_module,
            factories_by_module,
            self._workload.cross_module_fraction,
        )
        return local

    def take_pending(self) -> int:
        """Hand over the whole pending backlog (the fraction carries on)."""
        whole = int(self._pending)
        self._pending -= whole
        return whole

    def add_pending(self, gates: int) -> None:
        """Reclaim T gates still owed (a lost factory's unserved queue)."""
        self._pending += max(0, gates)

    def interconnect_status(self, source: str, modules: int) -> InterconnectStatus:
        """The link roll-up event: bank, assumed parameters, cross traffic."""
        link = self.interconnect
        config = link.config
        return InterconnectStatus(
            source=source,
            modules=modules,
            severed=link.severed,
            bank=int(link.bank),
            bank_capacity=config.bank_capacity,
            pair_rate_hz=config.pair_rate_hz,
            latency_s=config.latency_s,
            cross_demand_per_second=self._cross_demand,
            cross_t_served=int(link.cross_served),
            cross_queue_depth=int(link.cross_queue),
        )
