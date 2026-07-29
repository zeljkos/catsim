"""One chip container's runtime: announce, get admitted, tick, heartbeat.

Exists as the fleet's single unit of scale (M6): a chip boots knowing only the
bus address, announces itself, and runs whatever the scheduler assigns — at
one of two fidelity-dial positions. ``behavioral`` (the fleet default) runs
the SimPy chip model calibrated from the measured M1–M5 baselines; ``live``
(the drill-down focus chip) additionally runs the full M5 stim + decoder
stack, with the model advancing in lockstep with the real block's rounds.
A full machine cannot decode every chip for real — M4/M5 measured BP+OSD at
~324 ms per Q70 decode — so exactly the focus gets real physics.
"""

from __future__ import annotations

import threading
import time

from catsim.bus import (
    AnyEvent,
    BlockAccounting,
    BlockHealth,
    ChipAdmitted,
    ChipAnnounce,
    ChipConfigured,
    ChipHeartbeat,
    ChipLeft,
    ChipMode,
    ChipStatus,
    EventSink,
    EventSource,
    FactoryAccepted,
    FactoryHealth,
    FactoryRejected,
    RoundStarted,
    SetChipMode,
    SetPaused,
    StopChip,
    ZmqPublisher,
    ZmqSubscriber,
)
from catsim.component import (
    FactoryService,
    FactorySpec,
    MemoryBlockService,
    NoiseModel,
    QubitFactoryService,
    build_block_spec,
)
from catsim.decoder import DecoderService, default_decoder
from catsim.machine.config import (
    BlockComposition,
    ChipComposition,
    MachineConfig,
    ModelAssumptions,
    WorkloadConfig,
)
from catsim.machine.model import MachineModel
from catsim.machine.pricing import MEMORY_BLOCK_LOGICAL, price_chip

_SLOW_JOINER_S = 0.3
_JOIN_TIMEOUT_S = 10.0
_MAX_CATCHUP_S = 60.0  # behavioral clock: bound the step after a wall-clock stall


class _LiveStack:
    """The per-chip slice of the M5 real-service wiring, on an existing bus.

    One memory block + decoder + cat unit per assigned block (sources
    namespaced by chip id), a magic FactoryService per assigned factory, and
    one qubit factory answering only this chip's losses (topic-prefix
    subscription).
    """

    def __init__(
        self,
        admission: ChipAdmitted,
        *,
        noise: NoiseModel,
        rounds: int,
        seed: int,
        tick_seconds: float,
        frontend_address: str,
        backend_address: str,
    ) -> None:
        """Wire this chip's real services; nothing runs until :meth:`start`."""
        self._frontend = frontend_address
        self._backend = backend_address
        self._sockets: list[ZmqPublisher | ZmqSubscriber] = []
        self._threads: list[threading.Thread] = []
        self._blocks: list[MemoryBlockService] = []
        self._block_threads: list[threading.Thread] = []
        self._factories: list[FactoryService] = []
        chip_id = admission.chip_id
        for i, blk in enumerate(admission.blocks):
            spec = build_block_spec(blk.family, blk.code, noise, rounds)
            decoder = DecoderService(
                self._pub(),
                decoder_name=default_decoder(blk.family),
                source=f"{chip_id}-decoder{i}",
                block=f"{chip_id}-block{i}",
            )
            self._threads.append(
                threading.Thread(
                    target=decoder.run, args=(self._sub(),), kwargs={"idle_timeout_s": None}
                )
            )
            block = MemoryBlockService(
                spec,
                self._pub(),
                source=f"{chip_id}-block{i}",
                seed=seed + i,
                tick_seconds=tick_seconds,
                commands=self._sub(),
            )
            self._blocks.append(block)
            self._block_threads.append(threading.Thread(target=block.run, args=(None,)))
            self._factories.append(
                FactoryService(
                    FactorySpec(kind="cat", noise=noise),
                    self._pub(),
                    source=f"{chip_id}-cat{i}",
                    seed=seed + i,
                    tick_seconds=tick_seconds,
                    commands=self._sub(),
                )
            )
        for i, _kind in enumerate(admission.magic_factories):
            # The stim "magic" factory (M3 Clifford skeleton) shares the model
            # factory's source, so panel, kill switches, and model stay one entity.
            self._factories.append(
                FactoryService(
                    FactorySpec(kind="magic", noise=noise),
                    self._pub(),
                    source=f"{chip_id}-magic{i}",
                    seed=seed + i,
                    tick_seconds=tick_seconds,
                    commands=self._sub(),
                )
            )
        for factory in self._factories:
            self._threads.append(threading.Thread(target=factory.run, args=(None,)))
        self._qubit_factory = QubitFactoryService(self._pub(), source=f"{chip_id}-qubitfactory")
        self._threads.append(
            threading.Thread(
                target=self._qubit_factory.run,
                args=(self._sub(prefix=f"{chip_id}-block"),),
                kwargs={"idle_timeout_s": None},
            )
        )

    def _pub(self) -> ZmqPublisher:
        """A new publisher on the bus frontend, tracked for teardown."""
        pub = ZmqPublisher(self._frontend)
        self._sockets.append(pub)
        return pub

    def _sub(self, prefix: str = "") -> ZmqSubscriber:
        """A new subscriber on the bus backend, tracked for teardown."""
        sub = ZmqSubscriber(self._backend, prefix=prefix)
        self._sockets.append(sub)
        return sub

    def start(self) -> None:
        """Start service threads; blocks announce and then begin ticking."""
        for thread in self._threads:
            thread.start()
        time.sleep(_SLOW_JOINER_S)  # let SUB subscriptions propagate before publishing
        for block in self._blocks:
            block.configure()
        for thread in self._block_threads:
            thread.start()

    def stop(self) -> None:
        """Stop blocks (releasing their decoders), join, and close sockets."""
        for block in self._blocks:
            block.stop()
        for factory in self._factories:
            factory.stop()
        self._qubit_factory.stop()
        for thread in [*self._block_threads, *self._threads]:
            if thread.is_alive():
                thread.join(timeout=_JOIN_TIMEOUT_S)
        for block in self._blocks:
            block.close()
        for socket in self._sockets:
            socket.close()


class ChipRuntime:
    """The chip process's brain: join protocol, fidelity dial, status stream.

    Publishes through ``sink`` and is driven by :meth:`run` polling one
    subscriber — single-threaded except for the live stack's own services.
    ``live_bus`` (frontend, backend addresses) is required to enter live mode;
    without it the chip is behavioral-only (unit tests, constrained hosts).
    """

    def __init__(
        self,
        sink: EventSink,
        *,
        instance_id: str,
        noise: NoiseModel,
        machine_name: str = "chip-256",
        nominal_qubits: int = 256,
        rounds: int = 10,
        seed: int = 0,
        tick_seconds: float = 0.5,
        behavioral_rate: float = 1.0,
        heartbeat_s: float = 1.0,
        status_every_s: float = 1.0,
        assumptions: ModelAssumptions | None = None,
        live_bus: tuple[str, str] | None = None,
    ) -> None:
        """Create the runtime; nothing is published until :meth:`run` announces.

        Args:
            sink: Where this chip publishes (the bus, or a test sink).
            instance_id: Transport identity, unique per container/process.
            noise: Noise model for live-mode stim services.
            machine_name: The unit-chip config name shown on the chip tile.
            nominal_qubits: The roadmap label announced as capability.
            rounds: SE rounds per live memory shot.
            seed: Simulator seed (reproducible runs).
            tick_seconds: Live-stack wall pace per SE round / attempt.
            behavioral_rate: Machine seconds advanced per wall second in
                behavioral mode (1.0 = the architecture's real time).
            heartbeat_s: Wall seconds between heartbeats.
            status_every_s: Wall seconds between chip statuses.
            assumptions: Behavioral model knobs (buffer size, cat rate).
            live_bus: (frontend, backend) addresses for live-stack sockets.
        """
        self._sink = sink
        self._instance_id = instance_id
        self._noise = noise
        self._machine_name = machine_name
        self._nominal_qubits = nominal_qubits
        self._rounds = rounds
        self._seed = seed
        self._tick_seconds = tick_seconds
        self._behavioral_rate = behavioral_rate
        self._heartbeat_s = heartbeat_s
        self._status_every_s = status_every_s
        self._assumptions = assumptions or ModelAssumptions()
        self._live_bus = live_bus
        self._admission: ChipAdmitted | None = None
        self._model: MachineModel | None = None
        self._live: _LiveStack | None = None
        self._seq = 0
        self._stopped = False
        self._last_advance = time.monotonic()
        self._next_heartbeat = 0.0
        self._next_status = 0.0
        self._next_announce = 0.0

    @property
    def chip_id(self) -> str | None:
        """The machine identity assigned at admission (None before)."""
        return self._admission.chip_id if self._admission else None

    @property
    def mode(self) -> str:
        """The fidelity dial position ('behavioral' until admitted live)."""
        return self._admission.mode if self._admission else "behavioral"

    def announce(self) -> None:
        """Ask to join: publish capabilities under the instance id."""
        modes: list[ChipMode] = ["behavioral", "live"] if self._live_bus else ["behavioral"]
        self._sink.publish(
            ChipAnnounce(source=self._instance_id, nominal_qubits=self._nominal_qubits, modes=modes)
        )

    def handle(self, event: AnyEvent) -> bool:
        """Ingest one bus event; returns False once this chip should exit."""
        if isinstance(event, ChipAdmitted) and event.target == self._instance_id:
            self._apply_admission(event)
        elif self._admission is None:
            return True
        elif isinstance(event, StopChip) and event.target in (self.chip_id, "*"):
            self._leave()
            return False
        elif isinstance(event, SetChipMode) and event.target == self.chip_id:
            self._set_mode(event.mode)
        elif isinstance(event, SetPaused):
            self._on_set_paused(event)
        elif isinstance(event, (FactoryAccepted | FactoryRejected)):
            assert self._model is not None
            self._model.set_cat_acceptance(event.source, event.acceptance_rate)
        elif isinstance(event, RoundStarted) and self._is_pace_round(event):
            assert self._model is not None
            self._model.step(self._model.sec_seconds)
        return True

    def run(self, source: EventSource) -> None:
        """Announce, then consume events and time-driven duties until stopped."""
        self.announce()
        self._next_announce = time.monotonic() + 2.0
        while not self._stopped:
            event = source.receive(timeout_s=0.05)
            if event is not None and not self.handle(event):
                return
            self.tick(time.monotonic())

    def stop(self) -> None:
        """Ask the run loop to exit at its next poll (without a chip_left)."""
        self._stopped = True

    def tick(self, now: float) -> None:
        """Advance wall-clock duties: behavioral time, heartbeat, status."""
        if self._admission is None:
            if now >= self._next_announce:  # re-ask until the scheduler answers
                self.announce()
                self._next_announce = now + 2.0
            return
        if self.mode == "behavioral" and self._model is not None:
            step = min((now - self._last_advance) * self._behavioral_rate, _MAX_CATCHUP_S)
            if step > 0:
                self._model.step(step)
        self._last_advance = now
        if now >= self._next_heartbeat:
            self._seq += 1
            self._sink.publish(
                ChipHeartbeat(
                    source=self._admission.chip_id, seq=self._seq, mode=self._admission.mode
                )
            )
            self._next_heartbeat = now + self._heartbeat_s
        if now >= self._next_status:
            self.publish_status()
            self._next_status = now + self._status_every_s
        if now >= self._next_announce:
            self._configure()  # re-announce composition for late joiners
            self._next_announce = now + 5 * self._status_every_s

    def publish_status(self) -> None:
        """Publish this chip's health, mode, and T counters from the model."""
        if self._admission is None or self._model is None:
            return
        chip_id = self._admission.chip_id
        snapshot = self._model.snapshot()
        blocks = snapshot.chip_blocks(chip_id)
        factories = snapshot.chip_factories(chip_id)
        rounds = sum(b.rounds for b in blocks)
        stalled = sum(b.stalled_rounds for b in blocks)
        healthy = all(b.state == "ok" for b in blocks) and all(f.state == "ok" for f in factories)
        self._sink.publish(
            ChipStatus(
                source=chip_id,
                chip_id=chip_id,
                state="ok" if healthy else "degraded",
                role=self._admission.role,
                mode=self._admission.mode,
                module=self._admission.module,
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
                machine_seconds=snapshot.seconds,
                t_queue_depth=snapshot.t_queue_depth,
                t_done=snapshot.t_done,
            )
        )

    def close(self) -> None:
        """Tear down the live stack if any (sockets owned by the caller stay)."""
        if self._live is not None:
            self._live.stop()
            self._live = None

    def _apply_admission(self, admission: ChipAdmitted) -> None:
        """Adopt (or update) identity, role, composition, demand, and mode."""
        previous = self._admission
        same_shape = previous is not None and (
            previous.chip_id,
            previous.role,
            previous.blocks,
            previous.magic_factories,
        ) == (admission.chip_id, admission.role, admission.blocks, admission.magic_factories)
        self._admission = admission
        if same_shape:
            assert self._model is not None
            self._model.set_t_demand(admission.t_demand_per_second)
            self._model.add_t_backlog(admission.t_backlog)
            if previous is not None and previous.mode != admission.mode:
                self._set_mode(admission.mode)
            return
        if self._live is not None:  # composition changed under a live stack
            self._live.stop()
            self._live = None
        self._model = MachineModel(
            self._build_config(admission),
            seed=self._seed,
            label=admission.chip_id,
        )
        self._model.add_t_backlog(admission.t_backlog)
        self._last_advance = time.monotonic()
        if admission.mode == "live":
            self._start_live()
        self._configure()
        self.publish_status()

    def _build_config(self, admission: ChipAdmitted) -> MachineConfig:
        """The single-chip machine config this assignment describes."""
        return MachineConfig(
            name=self._machine_name,
            chips=1,
            chip=ChipComposition(
                nominal_qubits=self._nominal_qubits,
                accounting="paper",
                blocks=[BlockComposition(family=b.family, code=b.code) for b in admission.blocks],
                magic_factories=list(admission.magic_factories),  # type: ignore[arg-type]
            ),
            assumptions=self._assumptions,
            workload=WorkloadConfig(t_per_second=admission.t_demand_per_second),
        )

    def _configure(self) -> None:
        """Publish this chip's composition and Table V accounting."""
        if self._admission is None:
            return
        admission = self._admission
        bill = price_chip([b.code for b in admission.blocks], list(admission.magic_factories))
        blocks = [
            BlockAccounting(
                block_id=f"{admission.chip_id}-block{i}",
                code_name=b.code,
                num_logical=MEMORY_BLOCK_LOGICAL[b.code],
                memory_qubits=memory,
                cat_qubits=cat,
            )
            for i, (b, memory, cat) in enumerate(
                zip(admission.blocks, bill.memory_qubits, bill.cat_qubits, strict=True)
            )
        ]
        self._sink.publish(
            ChipConfigured(
                source=admission.chip_id,
                chip_id=admission.chip_id,
                role=admission.role,
                module=admission.module,
                machine_name=self._machine_name,
                nominal_qubits=self._nominal_qubits,
                paper_qubits=bill.total,
                logical_qubits=sum(b.num_logical for b in blocks),
                accounting="paper",
                blocks=blocks,
                magic_factories=list(admission.magic_factories),
            )
        )

    def _set_mode(self, mode: ChipMode) -> None:
        """Move the fidelity dial; the model keeps its state across the switch."""
        assert self._admission is not None
        if mode == self._admission.mode:
            return
        self._admission = self._admission.model_copy(update={"mode": mode})
        if mode == "live":
            self._start_live()
        elif self._live is not None:
            self._live.stop()
            self._live = None
            self._last_advance = time.monotonic()
        self.publish_status()

    def _start_live(self) -> None:
        """Bring up the real stim + decoder stack (requires live_bus)."""
        assert self._admission is not None
        if self._live_bus is None:
            self._admission = self._admission.model_copy(update={"mode": "behavioral"})
            return
        frontend, backend = self._live_bus
        self._live = _LiveStack(
            self._admission,
            noise=self._noise,
            rounds=self._rounds,
            seed=self._seed,
            tick_seconds=self._tick_seconds,
            frontend_address=frontend,
            backend_address=backend,
        )
        self._live.start()

    def _is_pace_round(self, event: RoundStarted) -> bool:
        """Live clock: our first block's rounds advance machine time one SEC."""
        return (
            self.mode == "live"
            and self._admission is not None
            and event.source == f"{self._admission.chip_id}-block0"
        )

    def _on_set_paused(self, command: SetPaused) -> None:
        """Mirror factory kill/revive into the model; live services react themselves."""
        if self._model is None or self._admission is None:
            return
        if command.target == "*" or command.target == self._admission.chip_id:
            for factory in self._model.snapshot().factories:
                self._model.set_factory_paused(factory.source, command.paused)
        elif command.target.startswith(f"{self._admission.chip_id}-"):
            self._model.set_factory_paused(command.target, command.paused)

    def _leave(self) -> None:
        """Graceful exit: stop real services, then say goodbye on the bus."""
        chip_id = self.chip_id or self._instance_id
        self.close()
        self._sink.publish(ChipLeft(source=chip_id, chip_id=chip_id))
