"""The live memory block: one syndrome-extraction round per tick, events on the bus.

Exists as the continuously ticking Layer-1 process the dashboard watches; batch
statistics reuse the same circuit builders through :mod:`catsim.component.batch`.
Commands (injections, pacing, pause, noise scale) arrive over the bus and take
effect at the next round; bulk artifacts (DEM, layout) are served on request.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
import stim

from catsim.bus import (
    BlockConfigured,
    Command,
    ErrorInjected,
    EventSink,
    InjectLoss,
    InjectPauli,
    IonLost,
    QubitReplaced,
    QueryServer,
    RoundStarted,
    RunFinished,
    SetNoiseScale,
    SetPace,
    SetPaused,
    ShotFinished,
    SyndromeFired,
    ZmqSubscriber,
)
from catsim.codes import QECCode
from catsim.component.circuits import (
    RoundSegments,
    build_memory_circuit,
    memory_detector_error_model,
    split_into_rounds,
)
from catsim.component.geometry import BlockLayout, block_layout
from catsim.component.noise import NoiseModel

_LOSS_DEPOLARIZATION = 0.75
"""A lost ion's qubit is maximally mixed: uniform over {I, X, Y, Z} each round.
M1 loss model — the qubit factory replacement (M3) will replace re-init."""

_PAUSE_POLL_S = 0.05


@dataclass(frozen=True)
class MemoryBlockSpec:
    """Everything needed to instantiate a memory block: code, noise, shot length."""

    code: QECCode
    noise: NoiseModel
    rounds: int


class MemoryBlockService:
    """Runs repeated memory shots on a flip simulator, streaming per-round events.

    Exists so cause and effect are visible live: each tick advances one SE round
    and publishes which checks fired; decoding happens elsewhere, over the bus.
    """

    def __init__(
        self,
        spec: MemoryBlockSpec,
        sink: EventSink,
        *,
        source: str = "block0",
        seed: int = 0,
        tick_seconds: float = 0.0,
        commands: ZmqSubscriber | None = None,
    ) -> None:
        """Build the circuit and simulator for ``spec`` and start the query server.

        Args:
            spec: Code, noise, and rounds per shot.
            sink: Where events are published (the bus, or a test sink).
            source: Component id; becomes the bus topic and command target.
            seed: Seed for the flip simulator (reproducible runs).
            tick_seconds: Wall-clock pause per SE round (0 = as fast as possible;
                6 ms matches the paper's syndrome-extraction cycle).
            commands: Bus subscriber polled for commands between rounds.
        """
        self._spec = spec
        self._sink = sink
        self._source = source
        self.tick_seconds = tick_seconds
        self._commands = commands
        self._sim = stim.FlipSimulator(batch_size=1, seed=seed)
        self._tick = 0
        self._noise_scale = 1.0
        self._pending_scale: float | None = None
        self._pending_paulis: list[tuple[str, list[int]]] = []
        self._pending_losses: list[int] = []
        self._lost: set[int] = set()
        self._paused = False
        self._stopped = False
        self._rebuild()
        self._query = QueryServer({"dem": lambda: str(self._dem), "layout": self._layout.to_json})

    @property
    def query_address(self) -> str:
        """Where the block serves its DEM and layout on request."""
        return self._query.address

    def _rebuild(self) -> None:
        """(Re)build circuit, segments, DEM, and layout for the current noise scale."""
        noise = self._spec.noise
        if self._noise_scale != 1.0:
            noise = noise.scaled(self._noise_scale)
        self._noise_name = noise.name
        self._circuit = build_memory_circuit(self._spec.code, noise, self._spec.rounds)
        self._segments: RoundSegments = split_into_rounds(self._circuit)
        self._dem = memory_detector_error_model(self._circuit)
        self._layout: BlockLayout = block_layout(self._circuit)

    def configure(self) -> None:
        """Announce the block on the bus: summary fields plus the query address."""
        spec = self._spec
        self._sink.publish(
            BlockConfigured(
                source=self._source,
                tick=self._tick,
                code_name=spec.code.name,
                distance=spec.code.distance,
                rounds_per_shot=spec.rounds,
                num_data_qubits=spec.code.num_data_qubits,
                num_logical=spec.code.num_logical,
                noise_name=self._noise_name,
                noise_scale=self._noise_scale,
                query_address=self.query_address,
            )
        )

    def run(self, shots: int | None) -> None:
        """Run ``shots`` memory shots (None = until :meth:`stop`), then sign off."""
        shot = 0
        while not self._stopped and (shots is None or shot < shots):
            self._run_shot(shot)
            shot += 1
        self._sink.publish(RunFinished(source=self._source, tick=self._tick, shots=shot))

    def stop(self) -> None:
        """Ask the run loop to exit after the current shot."""
        self._stopped = True

    def close(self) -> None:
        """Release the query server's socket."""
        self._query.close()

    def handle_command(self, command: Command) -> None:
        """Accept one console/scenario command; it takes effect at the next round."""
        if isinstance(command, InjectPauli):
            self._pending_paulis.append((command.pauli, list(command.qubits)))
        elif isinstance(command, InjectLoss):
            self._pending_losses.extend(command.qubits)
        elif isinstance(command, SetNoiseScale):
            self._pending_scale = command.scale
        elif isinstance(command, SetPace):
            self.tick_seconds = command.tick_seconds
        elif isinstance(command, SetPaused):
            self._paused = command.paused

    def _run_shot(self, shot: int) -> None:
        """One memory shot: init, tick through SE rounds, measure out, report truth."""
        if self._pending_scale is not None:
            self._noise_scale, self._pending_scale = self._pending_scale, None
            self._rebuild()
        # Re-announce every shot so late joiners (a reconnecting dashboard, a
        # fresh decoder) bootstrap; consumers dedupe unchanged announcements.
        self.configure()
        self._sim.clear()
        self._round_prelude(shot, round_index=0, injectable=False)
        self._do_segment(self._segments.init, shot, round_index=0)
        for i in range(self._segments.repeats):
            self._round_prelude(shot, round_index=i + 1)
            self._do_segment(self._segments.body, shot, round_index=i + 1)
        final_round = self._segments.repeats + 1
        self._round_prelude(shot, round_index=final_round)
        self._do_segment(self._segments.final, shot, round_index=final_round)
        obs = self._sim.get_observable_flips()[:, 0]
        self._sink.publish(
            ShotFinished(
                source=self._source,
                tick=self._tick,
                shot=shot,
                actual_flips=[int(i) for i in np.flatnonzero(obs)],
            )
        )
        for qubit in sorted(self._lost):
            self._sink.publish(QubitReplaced(source=self._source, qubit=qubit, shot=shot))
        self._lost.clear()

    def _round_prelude(self, shot: int, round_index: int, injectable: bool = True) -> None:
        """Between rounds: honor pause, drain commands, apply injections and loss."""
        self._poll_commands()
        while self._paused and not self._stopped:
            time.sleep(_PAUSE_POLL_S)
            self._poll_commands()
        self._sink.publish(RoundStarted(source=self._source, shot=shot, round=round_index))
        if not injectable:
            return
        known = self._layout.data_qubits.keys() | self._layout.check_qubits.keys()
        for pauli, qubits in self._pending_paulis:
            hit = sorted(set(qubits) & known)
            if hit:
                self._sim.do(stim.Circuit(f"{pauli}_ERROR(1) " + " ".join(map(str, hit))))
                self._sink.publish(
                    ErrorInjected(
                        source=self._source,
                        tick=self._tick,
                        shot=shot,
                        round=round_index,
                        qubits=hit,
                        pauli=pauli,
                        cause="injected",
                    )
                )
        self._pending_paulis.clear()
        for qubit in sorted(set(self._pending_losses) & known - self._lost):
            self._lost.add(qubit)
            self._sink.publish(
                IonLost(source=self._source, qubit=qubit, shot=shot, round=round_index)
            )
        self._pending_losses.clear()
        if self._lost:
            targets = " ".join(map(str, sorted(self._lost)))
            self._sim.do(stim.Circuit(f"DEPOLARIZE1({_LOSS_DEPOLARIZATION}) {targets}"))

    def _poll_commands(self) -> None:
        """Drain the command subscriber without blocking the tick loop."""
        if self._commands is None:
            return
        while (event := self._commands.receive(timeout_s=0.0)) is not None:
            if isinstance(event, Command) and event.target in (self._source, "*"):
                self.handle_command(event)

    def _do_segment(self, segment: stim.Circuit, shot: int, round_index: int) -> None:
        """Advance one segment, publish any newly fired checks, and pace the tick."""
        before = self._sim.num_detectors
        self._sim.do(segment)
        flips = self._sim.get_detector_flips()
        fired = np.flatnonzero(flips[before:, 0]) + before
        self._tick += 1
        if fired.size:
            self._sink.publish(
                SyndromeFired(
                    source=self._source,
                    tick=self._tick,
                    shot=shot,
                    round=round_index,
                    check_ids=[int(i) for i in fired],
                )
            )
        if self.tick_seconds > 0:
            time.sleep(self.tick_seconds)
