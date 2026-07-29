"""The fleet scheduler: admission, roles, heartbeats, focus, machine roll-up.

Exists so the machine is whatever chips are currently registered (M6): it
answers ``chip_announce`` with an identity and a Table I-balanced role, keeps
the fleet honest through heartbeats (missed beats → ``chip_lost`` → roles and
T demand rebalance — scaling and failure are the same code path), moves the
fidelity-dial focus on request, and publishes the machine roll-up whose
prediction column is the paper's arithmetic for the *current* fleet.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from catsim.bus import (
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
    MachineStatus,
    SetChipMode,
    SetFocus,
    ShotFinished,
)
from catsim.machine.config import MachineConfig
from catsim.machine.prediction import predict_machine
from catsim.machine.pricing import MEMORY_BLOCK_LOGICAL
from catsim.machine.roles import FACTORY_CHIP, desired_factories, next_role

_DAY_SECONDS = 86_400.0

_LIVE_TIMEOUT_FACTOR = 4.0
"""Heartbeat leniency for the live focus chip: BP+OSD's bimodal tail (M4)
can hold its process for whole seconds per decode, so its heartbeats
legitimately gap in ways a behavioral chip's never do."""

DEMAND_LIMITED = "demand-limited: factory capacity exceeds the workload"
"""Attribution when factories exist and outpace the configured T demand."""


@dataclass
class _Chip:
    """The scheduler's view of one registered chip."""

    instance_id: str
    chip_id: str
    role: str
    mode: str
    blocks: list[BlockAssignment]
    magic_factories: list[str]
    nominal_qubits: int
    modes: list[str]
    last_seen: float
    status: ChipStatus | None = None
    neighbors: list[str] = field(default_factory=list)

    @property
    def logical_qubits(self) -> int:
        """Logical qubits this chip's memory blocks host."""
        return sum(MEMORY_BLOCK_LOGICAL[b.code] for b in self.blocks)


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
            unit: The unit chip config (memory-chip composition + the fleet's
                total T-gate workload demand).
            source: Component id; becomes the bus topic.
            heartbeat_timeout_s: Silence after which a chip is declared lost.
            status_every_s: Wall seconds between machine roll-ups.
        """
        self._sink = sink
        self._unit = unit
        self._source = source
        self._heartbeat_timeout_s = heartbeat_timeout_s
        self._status_every_s = status_every_s
        self._chips: dict[str, _Chip] = {}
        self._by_instance: dict[str, str] = {}
        self._next_index = 0
        self._focus: str | None = None
        self._lost_chips = 0
        self._shots = 0
        self._logical_errors = 0
        self._pending_backlog = 0.0  # float: per-status increments are fractional
        self._backlog_marker = 0.0  # machine seconds already accounted into backlog
        self._next_status = 0.0
        self._stopped = False

    @property
    def chips(self) -> dict[str, _Chip]:
        """The registered fleet by chip id (read-only view for callers/tests)."""
        return self._chips

    @property
    def focus(self) -> str | None:
        """The chip currently holding the live fidelity dial."""
        return self._focus

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
        elif isinstance(event, ShotFinished):
            self._shots += 1
        elif isinstance(event, LogicalError):
            self._logical_errors += 1
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
        self._accrue_backlog()
        chips = list(self._chips.values())
        block_codes = [b.code for c in chips for b in c.blocks]
        magic = [kind for c in chips for kind in c.magic_factories]
        prediction = predict_machine(
            block_codes, [MEMORY_BLOCK_LOGICAL[c] for c in block_codes], magic
        )
        paper_qubits = prediction.physical_qubits if chips else 0  # no reservoir-only ghost
        statuses = [c.status for c in chips if c.status is not None]
        measured_t_per_day = sum(
            s.t_done / s.machine_seconds * _DAY_SECONDS for s in statuses if s.machine_seconds > 0
        )
        queue = int(self._pending_backlog) + sum(s.t_queue_depth for s in statuses)
        demand = self._unit.workload.t_per_second
        stall = prediction.t_stall_reason
        if not stall and prediction.t_per_day > demand * _DAY_SECONDS:
            stall = DEMAND_LIMITED
        focus_logical = self._chips[self._focus].logical_qubits if self._focus else 0
        per_logical = (
            self._logical_errors / (self._shots * focus_logical)
            if self._shots and focus_logical
            else 0.0
        )
        self._sink.publish(
            MachineStatus(
                source=self._source,
                chips=len(chips),
                lost_chips=self._lost_chips,
                logical_qubits=prediction.logical_qubits,
                physical_qubits_nominal=sum(c.nominal_qubits for c in chips),
                physical_qubits_paper=paper_qubits,
                predicted_t_per_day=prediction.t_per_day,
                measured_t_per_day=measured_t_per_day,
                t_queue_depth=queue,
                t_stall_reason=stall,
                machine_seconds=self._machine_seconds(),
                measured_shots=self._shots,
                measured_logical_errors=self._logical_errors,
                logical_error_per_logical_per_shot=per_logical,
            )
        )

    def _machine_seconds(self) -> float:
        """The fleet's machine clock: the furthest chip's machine time."""
        return max(
            (c.status.machine_seconds for c in self._chips.values() if c.status is not None),
            default=0.0,
        )

    def _accrue_backlog(self) -> None:
        """While no factory chip exists, unserved T demand piles up here."""
        elapsed = self._machine_seconds()
        if not any(c.role == "factory" for c in self._chips.values()):
            demand = self._unit.workload.t_per_second
            self._pending_backlog += demand * max(0.0, elapsed - self._backlog_marker)
        self._backlog_marker = elapsed

    def _admit(self, announce: ChipAnnounce) -> None:
        """Assign identity, role, mode, and links; idempotent per instance."""
        if announce.source in self._by_instance:  # re-announce: resend as-is
            self._send_assignment(self._chips[self._by_instance[announce.source]])
            return
        memory = sum(1 for c in self._chips.values() if c.role == "memory")
        factory = sum(1 for c in self._chips.values() if c.role == "factory")
        role = next_role(memory, factory, len(self._unit.chip.blocks) or 1)
        composition = self._unit.chip if role == "memory" else FACTORY_CHIP
        chip_id = f"chip{self._next_index}"
        self._next_index += 1
        goes_live = self._focus is None and "live" in announce.modes and role == "memory"
        neighbors = [next(reversed(self._chips))] if self._chips else []
        chip = _Chip(
            instance_id=announce.source,
            chip_id=chip_id,
            role=role,
            mode="live" if goes_live else "behavioral",
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

    def _send_assignment(self, chip: _Chip, t_backlog: int = 0) -> None:
        """Publish (or re-publish) one chip's admission."""
        factories = [c for c in self._chips.values() if c.role == "factory"]
        demand = (
            self._unit.workload.t_per_second / len(factories)
            if chip.role == "factory" and factories
            else 0.0
        )
        self._sink.publish(
            ChipAdmitted(
                source=self._source,
                target=chip.instance_id,
                chip_id=chip.chip_id,
                role=chip.role,  # type: ignore[arg-type]
                mode=chip.mode,  # type: ignore[arg-type]
                blocks=chip.blocks,
                magic_factories=chip.magic_factories,
                t_demand_per_second=demand,
                t_backlog=t_backlog,
                bell_neighbors=chip.neighbors,
            )
        )

    def _rebalance(self) -> None:
        """Re-balance roles to the Table I mix and re-split T demand.

        Role flips prefer the newest chips and never touch the focus chip
        (the live drill-down must not be yanked out from under the audience).
        """
        self._accrue_backlog()
        blocks_per = len(self._unit.chip.blocks) or 1
        desired = desired_factories(len(self._chips), blocks_per)
        factories = [c for c in self._chips.values() if c.role == "factory"]
        flippable = [
            c
            for c in reversed(self._chips.values())
            if c.role == "memory" and c.chip_id != self._focus
        ]
        for chip in flippable[: max(0, desired - len(factories))]:
            chip.role = "factory"
            chip.blocks = []
            chip.magic_factories = list(FACTORY_CHIP.magic_factories)
        factories = [c for c in self._chips.values() if c.role == "factory"]
        for chip in factories:
            backlog, self._pending_backlog = int(self._pending_backlog), 0.0  # hand over once
            self._send_assignment(chip, t_backlog=backlog)

    def _deregister(self, chip_id: str, *, lost: bool) -> None:
        """Remove a chip; reclaim its unserved queue; rebalance; move focus."""
        chip = self._chips.pop(chip_id)
        self._by_instance.pop(chip.instance_id, None)
        if lost:
            self._lost_chips += 1
        if chip.role == "factory" and chip.status is not None:
            # Its queued T gates are still owed; hand them to the survivors.
            self._pending_backlog += chip.status.t_queue_depth
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
