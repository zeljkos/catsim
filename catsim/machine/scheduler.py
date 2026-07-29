"""The fleet scheduler: admission, modules, roles, heartbeats, focus, roll-up.

Exists so the machine is whatever chips are currently registered (M6): it
answers ``chip_announce`` with an identity, a module, and a Table I-balanced
role, keeps the fleet honest through heartbeats (missed beats → ``chip_lost``
→ roles and T demand rebalance — scaling and failure are the same code path),
moves the fidelity-dial focus on request, and publishes the machine roll-up
whose prediction column is the paper's arithmetic for the *current* fleet.
M7: a module fills to its configured capacity and the next opens; roles and
demand balance per module, cross-module demand rides the interconnect bank
(all link parameters ASSUMED, not from the paper — see the ledger).
"""

from __future__ import annotations

import time

from catsim.bus import (
    AddModule,
    AnyEvent,
    BlockAssignment,
    ChipAdmitted,
    ChipAnnounce,
    ChipHeartbeat,
    ChipLeft,
    ChipLost,
    ChipStatus,
    EventSink,
    EventSource,
    LogicalError,
    SetChipMode,
    SetFocus,
    SetInterconnect,
    ShotFinished,
)
from catsim.machine.config import MachineConfig
from catsim.machine.fleet_state import ChipRecord, build_machine_status
from catsim.machine.ledger import FleetLedger
from catsim.machine.roles import FACTORY_CHIP, desired_factories, module_name, next_role

_LIVE_TIMEOUT_FACTOR = 4.0
"""Heartbeat leniency for the live focus chip: BP+OSD's bimodal tail (M4)
can hold its process for whole seconds per decode, so its heartbeats
legitimately gap in ways a behavioral chip's never do."""


class SchedulerService:
    """Admits chips, balances roles and demand, and publishes the roll-up.

    Single-threaded: feed it events via :meth:`handle` (or :meth:`run`) and
    wall-clock duties via :meth:`tick`.
    """

    def __init__(
        self,
        sink: EventSink,
        unit: MachineConfig,
        *,
        source: str = "scheduler",
        heartbeat_timeout_s: float = 5.0,
        status_every_s: float = 1.0,
    ) -> None:
        """Create the scheduler around the unit-chip composition.

        Args:
            sink: Where admissions, mode changes, and statuses are published.
            unit: The unit chip config (memory-chip composition, the fleet's
                total T-gate workload demand, module capacity, interconnect).
            source: Component id; becomes the bus topic.
            heartbeat_timeout_s: Silence after which a chip is declared lost.
            status_every_s: Wall seconds between machine roll-ups.
        """
        self._sink = sink
        self._unit = unit
        self._source = source
        self._heartbeat_timeout_s = heartbeat_timeout_s
        self._status_every_s = status_every_s
        self._chips: dict[str, ChipRecord] = {}
        self._by_instance: dict[str, str] = {}
        self._next_index = 0
        self._focus: str | None = None
        self._lost_chips = 0
        self._modules = [module_name(0)]
        self._ledger = FleetLedger(unit.workload, unit.interconnect)
        self._next_status = 0.0
        self._stopped = False

    @property
    def chips(self) -> dict[str, ChipRecord]:
        """The registered fleet by chip id (read-only view for callers/tests)."""
        return self._chips

    @property
    def focus(self) -> str | None:
        """The chip currently holding the live fidelity dial."""
        return self._focus

    @property
    def modules(self) -> list[str]:
        """Open modules, oldest first (chips join the newest)."""
        return list(self._modules)

    @property
    def ledger(self) -> FleetLedger:
        """The fleet's accounting (read access for callers/tests)."""
        return self._ledger

    def handle(self, event: AnyEvent) -> bool:
        """Ingest one bus event; returns False only when stopped."""
        if isinstance(event, ChipAnnounce):
            self._admit(event)
        elif isinstance(event, ChipHeartbeat) and event.source in self._chips:
            chip = self._chips[event.source]
            chip.last_seen = time.monotonic()
            chip.mode = event.mode
        elif isinstance(event, ChipStatus) and event.chip_id in self._chips:
            chip = self._chips[event.chip_id]
            chip.last_seen = time.monotonic()
            chip.status = event
        elif isinstance(event, ChipLeft) and event.chip_id in self._chips:
            self._deregister(event.chip_id, lost=False)
        elif isinstance(event, SetFocus) and event.target == self._source:
            self._set_focus(event.chip_id)
        elif isinstance(event, AddModule) and event.target == self._source:
            self._open_module()
        elif isinstance(event, SetInterconnect) and event.target == self._source:
            self._ledger.interconnect.set_severed(event.severed)
            self._publish_interconnect()
        elif isinstance(event, ShotFinished):
            self._ledger.shots += 1
        elif isinstance(event, LogicalError):
            self._ledger.logical_errors += 1
        return not self._stopped

    def tick(self, now: float) -> None:
        """Wall-clock duties: heartbeat sweep and the periodic roll-up."""
        for chip_id in [
            c.chip_id
            for c in self._chips.values()
            if now - c.last_seen
            > self._heartbeat_timeout_s * (_LIVE_TIMEOUT_FACTOR if c.mode == "live" else 1.0)
        ]:
            self._sink.publish(
                ChipLost(source=self._source, chip_id=chip_id, reason="missed heartbeats")
            )
            self._deregister(chip_id, lost=True)
        if now >= self._next_status:
            self.publish_status()
            self._next_status = now + self._status_every_s

    def run(self, source: EventSource) -> None:
        """Consume bus events and duties until :meth:`stop`."""
        while not self._stopped:
            event = source.receive(timeout_s=0.05)
            if event is not None and not self.handle(event):
                return
            self.tick(time.monotonic())

    def stop(self) -> None:
        """Ask the run loop to exit at its next poll."""
        self._stopped = True

    def publish_status(self) -> None:
        """Publish the machine roll-up: paper prediction vs live measurement."""
        self._accrue()
        self._hand_over_cross()
        self._sink.publish(
            build_machine_status(
                self._source,
                list(self._chips.values()),
                lost_chips=self._lost_chips,
                modules=len(self._modules),
                focus_logical=self._chips[self._focus].logical_qubits if self._focus else 0,
                demand_t_per_second=self._unit.workload.t_per_second,
                machine_seconds=self._machine_seconds(),
                ledger=self._ledger,
            )
        )
        if len(self._modules) > 1:
            self._publish_interconnect()

    def _publish_interconnect(self) -> None:
        """Publish the link roll-up (bank, assumed parameters, cross traffic)."""
        self._sink.publish(self._ledger.interconnect_status(self._source, len(self._modules)))

    def _machine_seconds(self) -> float:
        """The fleet's machine clock: the furthest chip's machine time."""
        return max(
            (c.status.machine_seconds for c in self._chips.values() if c.status is not None),
            default=0.0,
        )

    def _by_module(self, role: str) -> dict[str, int]:
        """Chip count per module for one role."""
        counts: dict[str, int] = {}
        for chip in self._chips.values():
            if chip.role == role:
                counts[chip.module] = counts.get(chip.module, 0) + 1
        return counts

    def _accrue(self) -> None:
        """Advance the ledger (backlog + interconnect) to the machine clock."""
        self._ledger.accrue(
            self._machine_seconds(), self._by_module("memory"), self._by_module("factory")
        )

    def _hand_over_cross(self) -> None:
        """Hand served cross-module gates to the factories as backlog chunks."""
        factories = [c for c in self._chips.values() if c.role == "factory"]
        if not factories:
            return
        gates = self._ledger.interconnect.take_handover()
        share, extra = divmod(gates, len(factories))
        for i, chip in enumerate(factories):
            backlog = share + (1 if i < extra else 0)
            if backlog:
                self._send_assignment(chip, t_backlog=backlog)

    def _open_module(self) -> str:
        """Open the next module; subsequent chips join it."""
        name = module_name(len(self._modules))
        self._modules.append(name)
        return name

    def _admit(self, announce: ChipAnnounce) -> None:
        """Assign identity, module, role, mode, links; idempotent per instance."""
        if announce.source in self._by_instance:  # re-announce: resend as-is
            self._send_assignment(self._chips[self._by_instance[announce.source]])
            return
        module = self._modules[-1]
        if sum(1 for c in self._chips.values() if c.module == module) >= (
            self._unit.module.capacity_chips
        ):
            module = self._open_module()
        members = [c for c in self._chips.values() if c.module == module]
        memory = sum(1 for c in members if c.role == "memory")
        role = next_role(memory, len(members) - memory, len(self._unit.chip.blocks) or 1)
        composition = self._unit.chip if role == "memory" else FACTORY_CHIP
        chip_id = f"chip{self._next_index}"
        self._next_index += 1
        goes_live = self._focus is None and "live" in announce.modes and role == "memory"
        neighbors = [c.chip_id for c in reversed(self._chips.values()) if c.module == module][:1]
        chip = ChipRecord(
            instance_id=announce.source,
            chip_id=chip_id,
            role=role,
            mode="live" if goes_live else "behavioral",
            module=module,
            blocks=[BlockAssignment(family=b.family, code=b.code) for b in composition.blocks],
            magic_factories=list(composition.magic_factories),
            nominal_qubits=announce.nominal_qubits,
            modes=list(announce.modes),
            last_seen=time.monotonic(),
            neighbors=neighbors,
        )
        self._chips[chip_id] = chip
        self._by_instance[announce.source] = chip_id
        if goes_live:
            self._focus = chip_id
        self._send_assignment(chip)
        self._rebalance()

    def _send_assignment(self, chip: ChipRecord, t_backlog: int = 0) -> None:
        """Publish (or re-publish) one chip's admission."""
        demand = 0.0
        if chip.role == "factory":
            local = self._ledger.local_demand(self._by_module("memory"), self._by_module("factory"))
            peers = self._by_module("factory").get(chip.module, 0)
            demand = local.get(chip.module, 0.0) / peers if peers else 0.0
        self._sink.publish(
            ChipAdmitted(
                source=self._source,
                target=chip.instance_id,
                chip_id=chip.chip_id,
                role=chip.role,  # type: ignore[arg-type]
                mode=chip.mode,  # type: ignore[arg-type]
                module=chip.module,
                blocks=chip.blocks,
                magic_factories=chip.magic_factories,
                t_demand_per_second=demand,
                t_backlog=t_backlog,
                bell_neighbors=chip.neighbors,
            )
        )

    def _rebalance(self) -> None:
        """Re-balance roles to the Table I mix per module and re-split T demand.

        Role flips prefer the newest chips, stay within their module (a
        factory serves its module's blocks locally — cross-module pairs are
        spent sparingly, never on the steady-state mix), and never touch the
        focus chip (the live drill-down must not be yanked from the audience).
        """
        self._accrue()
        blocks_per = len(self._unit.chip.blocks) or 1
        for module in self._modules:
            members = [c for c in self._chips.values() if c.module == module]
            desired = desired_factories(len(members), blocks_per)
            current = sum(1 for c in members if c.role == "factory")
            flippable = [
                c
                for c in reversed(self._chips.values())
                if c.module == module and c.role == "memory" and c.chip_id != self._focus
            ]
            for chip in flippable[: max(0, desired - current)]:
                chip.role = "factory"
                chip.blocks = []
                chip.magic_factories = list(FACTORY_CHIP.magic_factories)
        for chip in [c for c in self._chips.values() if c.role == "factory"]:
            self._send_assignment(chip, t_backlog=self._ledger.take_pending())

    def _deregister(self, chip_id: str, *, lost: bool) -> None:
        """Remove a chip; reclaim its unserved queue; rebalance; move focus."""
        chip = self._chips.pop(chip_id)
        self._by_instance.pop(chip.instance_id, None)
        if lost:
            self._lost_chips += 1
        if chip.role == "factory" and chip.status is not None:
            # Its queued T gates are still owed; hand them to the survivors.
            self._ledger.add_pending(chip.status.t_queue_depth)
        if self._focus == chip_id:
            self._focus = None
            for candidate in self._chips.values():
                if candidate.role == "memory" and "live" in candidate.modes:
                    self._set_focus(candidate.chip_id)
                    break
        self._rebalance()

    def _set_focus(self, chip_id: str) -> None:
        """Move the live fidelity dial to ``chip_id`` (behavioral for the rest)."""
        if chip_id not in self._chips or chip_id == self._focus:
            return
        if self._focus is not None and self._focus in self._chips:
            previous = self._chips[self._focus]
            previous.mode = "behavioral"
            self._sink.publish(
                SetChipMode(source=self._source, target=previous.chip_id, mode="behavioral")
            )
        chip = self._chips[chip_id]
        chip.mode = "live"
        self._focus = chip_id
        self._sink.publish(SetChipMode(source=self._source, target=chip_id, mode="live"))
