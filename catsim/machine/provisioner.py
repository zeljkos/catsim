"""The provisioner: the only component that may start or stop chip runtimes.

Exists so nothing else in the system knows how chips come into being: it
exposes exactly two operations on the bus — ``scale_up {n}`` and
``drain {chip_id | n}`` — and turns them into container or process lifecycles.
The Docker SDK (and its socket) live behind :class:`DockerSpawner` only; the
process fallback runs the identical join protocol for CI and no-Docker dev.
"""

from __future__ import annotations

import subprocess
import sys
import time
import uuid
from collections.abc import Sequence
from typing import Any, Protocol

from catsim.bus import (
    AnyEvent,
    ChipAdmitted,
    ChipLeft,
    ChipLost,
    Drain,
    EventSink,
    EventSource,
    ScaleUp,
    StopChip,
)

_REAP_GRACE_S = 5.0


class Spawner(Protocol):
    """How chip instances physically start and stop (process or container)."""

    def spawn(self, instance_id: str) -> None:
        """Start one chip runtime that will announce as ``instance_id``."""
        ...

    def reap(self, instance_id: str) -> None:
        """Stop and clean up the instance (idempotent; instance may be dead)."""
        ...

    def reap_all(self) -> None:
        """Stop every instance this spawner started (teardown path)."""
        ...


class ProcessSpawner:
    """Chips as local subprocesses of ``catsim node --role chip`` (fallback).

    Same join protocol as containers, so nothing else changes without Docker.
    """

    def __init__(self, chip_args: Sequence[str]) -> None:
        """Remember the chip invocation (everything after ``catsim``)."""
        self._chip_args = list(chip_args)
        self._procs: dict[str, subprocess.Popen[bytes]] = {}

    def spawn(self, instance_id: str) -> None:
        """Start one chip process announcing as ``instance_id``."""
        self._procs[instance_id] = subprocess.Popen(
            [sys.executable, "-m", "catsim.cli", *self._chip_args, "--instance", instance_id],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def reap(self, instance_id: str) -> None:
        """Terminate the process if still alive, escalating to kill."""
        proc = self._procs.pop(instance_id, None)
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=_REAP_GRACE_S)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=_REAP_GRACE_S)

    def reap_all(self) -> None:
        """Terminate every spawned process."""
        for instance_id in list(self._procs):
            self.reap(instance_id)


class DockerSpawner:
    """Chips as containers of the one chip image (Docker SDK, socket here only)."""

    def __init__(
        self,
        image: str,
        environment: dict[str, str],
        *,
        network: str | None = None,
        label: str = "catsim-chip",
    ) -> None:
        """Connect to the Docker daemon and remember the chip template.

        Args:
            image: The single chip image (role comes from the environment).
            environment: Env template; CATSIM_INSTANCE is added per spawn.
            network: Docker network chips join (the compose network).
            label: Label stamped on every chip container (reset finds them).
        """
        import docker  # deferred: only this class may touch the Docker API

        self._client = docker.from_env()
        self._image = image
        self._environment = environment
        self._network = network
        self._label = label
        self._containers: dict[str, Any] = {}

    def spawn(self, instance_id: str) -> None:
        """Run one detached chip container announcing as ``instance_id``."""
        self._containers[instance_id] = self._client.containers.run(
            self._image,
            detach=True,
            environment={**self._environment, "CATSIM_INSTANCE": instance_id},
            network=self._network,
            labels={self._label: instance_id},
            name=f"{self._label}-{instance_id}",
            auto_remove=False,
        )

    def reap(self, instance_id: str) -> None:
        """Stop and remove the container (idempotent; container may be gone)."""
        container = self._containers.pop(instance_id, None)
        if container is None:
            return
        import docker

        try:
            container.stop(timeout=int(_REAP_GRACE_S))
            container.remove(force=True)
        except docker.errors.APIError:  # already stopped/removed (e.g. docker kill)
            pass

    def reap_all(self) -> None:
        """Stop and remove every spawned container."""
        for instance_id in list(self._containers):
            self.reap(instance_id)


class ProvisionerService:
    """Turns the two bus operations into spawner calls and reaps the fallen.

    Learns chip_id → instance mappings by watching admissions, so a drain by
    chip id reaches the right process/container; ``chip_left`` and
    ``chip_lost`` both end in a reap — the leave protocol and the failure
    path share their cleanup.
    """

    def __init__(self, sink: EventSink, spawner: Spawner, *, source: str = "provisioner") -> None:
        """Create the service around one spawner backend."""
        self._sink = sink
        self._spawner = spawner
        self._source = source
        self._instances: list[str] = []
        self._chip_to_instance: dict[str, str] = {}
        self._instance_to_chip: dict[str, str] = {}
        self._stopped = False

    @property
    def instances(self) -> list[str]:
        """Instance ids spawned and not yet reaped, oldest first."""
        return list(self._instances)

    def handle(self, event: AnyEvent) -> bool:
        """Ingest one bus event; returns False only when stopped."""
        if isinstance(event, ScaleUp) and event.target == self._source:
            self.scale_up(event.n)
        elif isinstance(event, Drain) and event.target == self._source:
            self._drain(event)
        elif isinstance(event, ChipAdmitted) and event.target in self._instances:
            self._chip_to_instance[event.chip_id] = event.target
            self._instance_to_chip[event.target] = event.chip_id
        elif isinstance(event, (ChipLeft | ChipLost)):
            self._reap_chip(event.chip_id)
        return not self._stopped

    def run(self, source: EventSource) -> None:
        """Consume bus events until :meth:`stop`."""
        while not self._stopped:
            event = source.receive(timeout_s=0.05)
            if event is not None and not self.handle(event):
                return

    def stop(self) -> None:
        """Ask the run loop to exit at its next poll."""
        self._stopped = True

    def scale_up(self, n: int) -> None:
        """Start ``n`` new chip instances; each will announce itself."""
        for _ in range(n):
            instance_id = f"inst-{uuid.uuid4().hex[:8]}"
            self._instances.append(instance_id)
            self._spawner.spawn(instance_id)

    def shutdown_fleet(self, deadline_s: float = 8.0) -> None:
        """Teardown: ask every chip to leave, then reap whatever remains.

        Called from the owner's thread while :meth:`run` keeps draining
        ``chip_left`` events in its own — list ops on ``_instances`` are
        CPython-atomic, and the trailing ``reap_all`` makes stragglers moot.
        """
        self._sink.publish(StopChip(source=self._source, target="*"))
        deadline = time.monotonic() + deadline_s
        while self._instances and time.monotonic() < deadline:
            time.sleep(0.05)
        self._spawner.reap_all()
        self._instances.clear()

    def _drain(self, command: Drain) -> None:
        """Resolve a drain to chips and ask each to leave (reap follows chip_left)."""
        if command.chip_id is not None:
            targets = [command.chip_id]
        else:
            newest = list(reversed(self._instances))[: command.n or 0]
            targets = [self._instance_to_chip.get(i, "") for i in newest]
        for chip_id in targets:
            if chip_id:
                self._sink.publish(StopChip(source=self._source, target=chip_id))

    def _reap_chip(self, chip_id: str) -> None:
        """Clean up after a chip that left or was declared lost."""
        instance_id = self._chip_to_instance.pop(chip_id, None)
        if instance_id is None:
            return
        self._instance_to_chip.pop(instance_id, None)
        if instance_id in self._instances:
            self._instances.remove(instance_id)
        self._spawner.reap(instance_id)
