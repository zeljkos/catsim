"""The Factory interface and live loop: prepare, verify, post-select, publish.

Exists so every factory (cat, Bell, magic) is one registered circuit builder
behind a common service — one attempt per tick, post-selection on the noisy
verification checks, and a simulation-only truth oracle grading each accepted
output — all streamed onto the bus for the dashboard's factories panel.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import stim

from catsim.bus import (
    Command,
    EventSink,
    FactoryAccepted,
    FactoryAttempt,
    FactoryConfigured,
    FactoryRejected,
    SetNoiseScale,
    SetPace,
    SetPaused,
    ZmqSubscriber,
)
from catsim.component.noise import NoiseModel

_PAUSE_POLL_S = 0.05

_ANNOUNCE_EVERY = 10
"""Attempts between re-announcements, so late joiners (a reconnecting
dashboard) bootstrap — the factory analogue of the block's per-shot
re-announce; consumers dedupe unchanged announcements."""


def _warm_stim_sampler() -> None:
    """One throwaway draw so stim's lazy numpy imports happen at import time.

    stim imports numpy.core submodules on the FIRST sample() call; when
    several factory threads hit that first call concurrently alongside other
    services' lazy imports, the import machinery deadlocks (observed hang on
    py3.14/macOS). Drawing once here — main thread, before any service thread
    exists — pins those imports to process startup.
    """
    stim.Circuit("M 0\nDETECTOR rec[-1]").compile_detector_sampler().sample(shots=1)


_warm_stim_sampler()


@dataclass(frozen=True)
class FactoryCircuit:
    """A built prepare-and-verify circuit, plus how to read its detectors.

    The first ``num_verification`` detectors are the noisy verification checks
    the factory post-selects on; every later detector is a noiseless truth
    oracle measuring an ideal-output stabilizer (simulation-only — it grades
    accepted outputs, it is not part of the physical circuit).
    """

    kind: str
    circuit: stim.Circuit
    num_verification: int
    output_qubits: tuple[int, ...]


FactoryBuilder = Callable[[NoiseModel], FactoryCircuit]

_BUILDERS: dict[str, FactoryBuilder] = {}


def register_factory(kind: str, builder: FactoryBuilder) -> None:
    """Register a factory circuit builder under its YAML-selectable kind."""
    _BUILDERS[kind] = builder


def available_factories() -> tuple[str, ...]:
    """List the registered factory kinds."""
    return tuple(sorted(_BUILDERS))


def build_factory_circuit(kind: str, noise: NoiseModel) -> FactoryCircuit:
    """Build the named factory's circuit under ``noise``.

    Raises:
        KeyError: If ``kind`` was never registered.
    """
    if kind not in _BUILDERS:
        raise KeyError(f"unknown factory kind {kind!r}; known: {available_factories()}")
    return _BUILDERS[kind](noise)


@dataclass(frozen=True)
class FactorySpec:
    """Everything needed to instantiate a factory service: kind and noise."""

    kind: str
    noise: NoiseModel


class FactoryService:
    """Runs prepare-and-verify attempts continuously, post-selecting on the bus.

    Exists so acceptance rates are live measurements, not offline statistics:
    each tick is one attempt, each verdict an event carrying the running rate.
    """

    def __init__(
        self,
        spec: FactorySpec,
        sink: EventSink,
        *,
        source: str | None = None,
        seed: int = 0,
        tick_seconds: float = 0.0,
        commands: ZmqSubscriber | None = None,
    ) -> None:
        """Build the factory circuit for ``spec`` and prepare the attempt loop.

        Args:
            spec: Factory kind and noise model.
            sink: Where events are published (the bus, or a test sink).
            source: Component id; defaults to ``<kind>0``.
            seed: Seed for the detector sampler (reproducible runs).
            tick_seconds: Wall-clock pause per attempt (0 = flat out).
            commands: Bus subscriber polled for commands between attempts.
        """
        self._spec = spec
        self._sink = sink
        self._source = source or f"{spec.kind}0"
        self._seed = seed
        self.tick_seconds = tick_seconds
        self._commands = commands
        self._noise_scale = 1.0
        self._pending_scale: float | None = None
        self._paused = False
        self._stopped = False
        self._attempts = 0
        self._accepted = 0
        self._residual_outputs = 0
        self._rebuild()

    def _rebuild(self) -> None:
        """(Re)build the circuit and sampler for the current noise scale."""
        noise = self._spec.noise
        if self._noise_scale != 1.0:
            noise = noise.scaled(self._noise_scale)
        self._noise_name = noise.name
        self._factory = build_factory_circuit(self._spec.kind, noise)
        self._sampler = self._factory.circuit.compile_detector_sampler(seed=self._seed)

    def configure(self) -> None:
        """Announce the factory on the bus: kind, output size, check count."""
        self._sink.publish(
            FactoryConfigured(
                source=self._source,
                tick=self._attempts,
                kind=self._spec.kind,
                output_qubits=len(self._factory.output_qubits),
                verification_checks=self._factory.num_verification,
                noise_name=self._noise_name,
                noise_scale=self._noise_scale,
            )
        )

    def run(self, attempts: int | None) -> None:
        """Run ``attempts`` prepare-and-verify attempts (None = until :meth:`stop`)."""
        self.configure()
        done = 0
        while not self._stopped and (attempts is None or done < attempts):
            self._prelude()
            if self._stopped:
                break
            self._attempt()
            done += 1
            if self._attempts % _ANNOUNCE_EVERY == 0:
                self.configure()

    def stop(self) -> None:
        """Ask the attempt loop to exit before its next attempt."""
        self._stopped = True

    def handle_command(self, command: Command) -> None:
        """Accept one console/scenario command; it takes effect at the next attempt."""
        if isinstance(command, SetNoiseScale):
            self._pending_scale = command.scale
        elif isinstance(command, SetPace):
            self.tick_seconds = command.tick_seconds
        elif isinstance(command, SetPaused):
            self._paused = command.paused

    def _prelude(self) -> None:
        """Between attempts: drain commands, honor pause, apply a pending rescale."""
        self._poll_commands()
        while self._paused and not self._stopped:
            time.sleep(_PAUSE_POLL_S)
            self._poll_commands()
        if self._pending_scale is not None:
            self._noise_scale, self._pending_scale = self._pending_scale, None
            self._rebuild()
            self.configure()

    def _poll_commands(self) -> None:
        """Drain the command subscriber without blocking the attempt loop."""
        if self._commands is None:
            return
        while (event := self._commands.receive(timeout_s=0.0)) is not None:
            if isinstance(event, Command) and event.target in (self._source, "*"):
                self.handle_command(event)

    def _attempt(self) -> None:
        """One attempt: sample, post-select on verification, grade the output."""
        self._attempts += 1
        self._sink.publish(
            FactoryAttempt(source=self._source, tick=self._attempts, attempt=self._attempts)
        )
        detectors = self._sampler.sample(shots=1)[0]
        split = self._factory.num_verification
        failed = [int(i) for i in np.flatnonzero(detectors[:split])]
        if failed:
            self._publish_rejected(failed)
        else:
            residual = [int(i) for i in np.flatnonzero(detectors[split:])]
            self._publish_accepted(residual)
        if self.tick_seconds > 0:
            time.sleep(self.tick_seconds)

    def _publish_accepted(self, residual: list[int]) -> None:
        """Publish the acceptance verdict with truth-oracle residual metadata."""
        self._accepted += 1
        if residual:
            self._residual_outputs += 1
        self._sink.publish(
            FactoryAccepted(
                source=self._source,
                tick=self._attempts,
                attempt=self._attempts,
                attempts=self._attempts,
                accepted=self._accepted,
                acceptance_rate=self._accepted / self._attempts,
                residual_checks=residual,
                output_error_rate=self._residual_outputs / self._accepted,
            )
        )

    def _publish_rejected(self, failed: list[int]) -> None:
        """Publish the rejection verdict (post-selection discarded the output)."""
        self._sink.publish(
            FactoryRejected(
                source=self._source,
                tick=self._attempts,
                attempt=self._attempts,
                attempts=self._attempts,
                accepted=self._accepted,
                acceptance_rate=self._accepted / self._attempts,
                failed_checks=failed,
            )
        )
