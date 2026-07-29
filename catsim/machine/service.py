"""The machine as a bus service: model in lockstep with the real block's rounds.

Exists so Layer 3 couples to the running Layer-1/2 services only through the
event bus: machine time advances one SEC per real ``round_started``, cat
acceptance is calibrated from the live cat service's measured rate, factory
kill/revive commands (``set_paused``) reach the model over the same bus the
injection console uses — and the machine view is fed by published statuses.
"""

from __future__ import annotations

from catsim.bus import (
    AnyEvent,
    BlockAccounting,
    BlockHealth,
    ChipConfigured,
    ChipStatus,
    EventSink,
    EventSource,
    FactoryAccepted,
    FactoryHealth,
    FactoryRejected,
    LogicalError,
    MachineStatus,
    RoundStarted,
    RunFinished,
    SetPaused,
    ShotFinished,
)
from catsim.machine.model import MachineModel, MachineSnapshot
from catsim.machine.prediction import MachinePrediction, predict_machine
from catsim.machine.pricing import MEMORY_BLOCK_LOGICAL, price_chip


class MachineService:
    """Publishes chip/machine statuses; consumes rounds, verdicts, and commands.

    The pace block's ``round_started`` is the machine clock (one SEC per
    round); statuses go out every ``status_every_rounds`` of it.
    """

    def __init__(
        self,
        model: MachineModel,
        sink: EventSink,
        *,
        source: str = "machine0",
        pace_block: str = "block0",
    ) -> None:
        """Wrap a built model; nothing is published until :meth:`announce`.

        Args:
            model: The SimPy machine model (single-thread use, per its docs).
            sink: Where machine events are published.
            source: Component id; becomes the bus topic.
            pace_block: The block whose rounds drive machine time.
        """
        self._model = model
        self._sink = sink
        self._source = source
        self._pace_block = pace_block
        self._rounds_seen = 0
        self._shots = 0
        self._logical_errors = 0
        self._stopped = False
        config = model.config
        chip = config.chip
        codes = [b.code for b in chip.blocks] * config.chips
        self._prediction: MachinePrediction = predict_machine(
            codes,
            [MEMORY_BLOCK_LOGICAL[c] for c in codes],
            list(chip.magic_factories) * config.chips,
        )

    def announce(self) -> None:
        """Publish every chip's composition and the first machine status."""
        config = self._model.config
        chip = config.chip
        bill = price_chip([b.code for b in chip.blocks], list(chip.magic_factories))
        snapshot = self._model.snapshot()
        for chip_index in range(config.chips):
            chip_id = f"chip{chip_index}"
            blocks = [
                BlockAccounting(
                    block_id=b.block_id,
                    code_name=b.code,
                    num_logical=MEMORY_BLOCK_LOGICAL[b.code],
                    memory_qubits=memory,
                    cat_qubits=cat,
                )
                for b, memory, cat in zip(
                    snapshot.chip_blocks(chip_id), bill.memory_qubits, bill.cat_qubits, strict=True
                )
            ]
            self._sink.publish(
                ChipConfigured(
                    source=self._source,
                    chip_id=chip_id,
                    machine_name=config.name,
                    nominal_qubits=chip.nominal_qubits,
                    paper_qubits=bill.total,
                    logical_qubits=sum(b.num_logical for b in blocks),
                    accounting=chip.accounting,
                    accounting_note=chip.accounting_note,
                    blocks=blocks,
                    magic_factories=list(chip.magic_factories),
                )
            )
        self._publish_status(snapshot)

    def handle(self, event: AnyEvent) -> bool:
        """Ingest one bus event; returns False once the run is over."""
        if isinstance(event, RoundStarted) and event.source == self._pace_block:
            self._on_round()
        elif isinstance(event, (FactoryAccepted | FactoryRejected)):
            self._model.set_cat_acceptance(event.source, event.acceptance_rate)
        elif isinstance(event, SetPaused):
            self._on_set_paused(event)
        elif isinstance(event, ShotFinished):
            self._shots += 1
        elif isinstance(event, LogicalError):
            self._logical_errors += 1
        elif isinstance(event, RunFinished) and event.source == self._pace_block:
            return False
        return True

    def run(self, subscriber: EventSource, idle_timeout_s: float | None = None) -> None:
        """Consume bus events until the pace block signs off (or the bus goes quiet)."""
        idle = 0.0
        while not self._stopped and (idle_timeout_s is None or idle < idle_timeout_s):
            event = subscriber.receive(timeout_s=0.05)
            if event is None:
                idle += 0.05
                continue
            idle = 0.0
            if not self.handle(event):
                return

    def stop(self) -> None:
        """Ask the run loop to exit at its next poll."""
        self._stopped = True

    def _on_round(self) -> None:
        """Advance machine time one SEC; re-announce and publish statuses on cadence.

        Chips re-announce like blocks and factories do, so late joiners (a
        dashboard connecting after start) bootstrap; consumers dedupe
        unchanged announcements.
        """
        self._model.step(self._model.sec_seconds)
        self._rounds_seen += 1
        if self._rounds_seen % self._model.config.assumptions.status_every_rounds == 0:
            self.announce()

    def _on_set_paused(self, command: SetPaused) -> None:
        """Mirror factory kill/revive commands into the model."""
        if command.target == "*":
            for factory in self._model.snapshot().factories:
                self._model.set_factory_paused(factory.source, command.paused)
        else:
            self._model.set_factory_paused(command.target, command.paused)

    def _publish_status(self, snapshot: MachineSnapshot) -> None:
        """Publish one chip_status per chip plus the machine roll-up."""
        for chip_index in range(self._model.config.chips):
            chip_id = f"chip{chip_index}"
            self._sink.publish(self._chip_status(snapshot, chip_id))
        per_logical = (
            self._logical_errors / (self._shots * self._prediction.logical_qubits)
            if self._shots and self._prediction.logical_qubits
            else 0.0
        )
        config = self._model.config
        self._sink.publish(
            MachineStatus(
                source=self._source,
                chips=config.chips,
                logical_qubits=self._prediction.logical_qubits,
                physical_qubits_nominal=config.chips * config.chip.nominal_qubits,
                physical_qubits_paper=self._prediction.physical_qubits,
                predicted_t_per_day=self._prediction.t_per_day,
                measured_t_per_day=snapshot.t_per_day,
                t_queue_depth=snapshot.t_queue_depth,
                t_stall_reason=self._prediction.t_stall_reason,
                machine_seconds=snapshot.seconds,
                measured_shots=self._shots,
                measured_logical_errors=self._logical_errors,
                logical_error_per_logical_per_shot=per_logical,
            )
        )

    def _chip_status(self, snapshot: MachineSnapshot, chip_id: str) -> ChipStatus:
        """Roll one chip's block and factory snapshots into a status event."""
        blocks = snapshot.chip_blocks(chip_id)
        factories = snapshot.chip_factories(chip_id)
        rounds = sum(b.rounds for b in blocks)
        stalled = sum(b.stalled_rounds for b in blocks)
        healthy = all(b.state == "ok" for b in blocks) and all(f.state == "ok" for f in factories)
        return ChipStatus(
            source=self._source,
            chip_id=chip_id,
            state="ok" if healthy else "degraded",
            blocks=[
                BlockHealth(
                    block_id=b.block_id,
                    state=b.state,  # type: ignore[arg-type]
                    rounds=b.rounds,
                    stalled_rounds=b.stalled_rounds,
                    cat_buffer=b.cat_buffer,
                    cat_buffer_capacity=b.cat_buffer_capacity,
                )
                for b in blocks
            ],
            factories=[
                FactoryHealth(source=f.source, kind=f.kind, state=f.state)  # type: ignore[arg-type]
                for f in factories
            ],
            utilization=rounds / (rounds + stalled) if rounds + stalled else 1.0,
        )
