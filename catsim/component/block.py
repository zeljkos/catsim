"""The live memory block: one syndrome-extraction round per tick, events on the bus.

Exists as the continuously ticking Layer-1 process the dashboard watches; batch
statistics reuse the same circuit builders through :mod:`catsim.component.batch`.

M0 scope note: natural noise is observed through syndromes only; ``error_injected``
events start flowing with the M1 injection console.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
import stim

from catsim.bus import BlockConfigured, EventSink, RunFinished, ShotFinished, SyndromeFired
from catsim.codes import QECCode
from catsim.component.circuits import RoundSegments, build_memory_circuit, split_into_rounds
from catsim.component.noise import NoiseModel


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
    ) -> None:
        """Build the circuit and simulator for ``spec``.

        Args:
            spec: Code, noise, and rounds per shot.
            sink: Where events are published (the bus, or a test sink).
            source: Component id; becomes the bus topic.
            seed: Seed for the flip simulator (reproducible runs).
            tick_seconds: Wall-clock pause per SE round (0 = as fast as possible;
                6 ms matches the paper's syndrome-extraction cycle).
        """
        self._spec = spec
        self._sink = sink
        self._source = source
        self._tick_seconds = tick_seconds
        self._circuit = build_memory_circuit(spec.code, spec.noise, spec.rounds)
        self._segments: RoundSegments = split_into_rounds(self._circuit)
        self._dem = self._circuit.detector_error_model(decompose_errors=True)
        self._sim = stim.FlipSimulator(batch_size=1, seed=seed)
        self._tick = 0

    def configure(self) -> None:
        """Announce the block on the bus, handing decoders the DEM they need."""
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
                noise_name=spec.noise.name,
                dem=str(self._dem),
            )
        )

    def run(self, shots: int) -> None:
        """Run ``shots`` memory shots, then signal the end of the run."""
        for shot in range(shots):
            self._run_shot(shot)
        self._sink.publish(RunFinished(source=self._source, tick=self._tick, shots=shots))

    def _run_shot(self, shot: int) -> None:
        """One memory shot: init, tick through SE rounds, measure out, report truth."""
        self._sim.clear()
        self._do_segment(self._segments.init, shot, round_index=0)
        for i in range(self._segments.repeats):
            self._do_segment(self._segments.body, shot, round_index=i + 1)
        self._do_segment(self._segments.final, shot, round_index=self._segments.repeats + 1)
        obs = self._sim.get_observable_flips()[:, 0]
        self._sink.publish(
            ShotFinished(
                source=self._source,
                tick=self._tick,
                shot=shot,
                actual_flips=[int(i) for i in np.flatnonzero(obs)],
            )
        )

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
        if self._tick_seconds > 0:
            time.sleep(self._tick_seconds)
