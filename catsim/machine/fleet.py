"""The all-in-one fleet backend: proxy + scheduler + provisioner on one host.

Exists so ``catsim serve --fleet N`` (and tests) bring up the whole elastic
runtime with one object when Docker is not in play: chips spawn as local
processes through the same join protocol the containers use, so nothing
downstream can tell the difference.
"""

from __future__ import annotations

import threading
import time

from catsim.bus import BusProxy, ScaleUp, ZmqPublisher, ZmqSubscriber
from catsim.machine.config import MachineConfig
from catsim.machine.provisioner import ProcessSpawner, ProvisionerService, Spawner
from catsim.machine.scheduler import SchedulerService

_SLOW_JOINER_S = 0.3
_JOIN_TIMEOUT_S = 10.0


class FleetBackend:
    """Runs the elastic machine's fixed services over a private bus.

    Chips are NOT run here: the provisioner starts each one as its own
    process (or container, with a custom spawner) and the fleet assembles
    itself over the bus — the same code path the on-stage growth uses.
    """

    def __init__(
        self,
        unit: MachineConfig,
        *,
        chips: int = 1,
        noise_name: str = "paper-baseline",
        rounds: int = 10,
        seed: int = 0,
        tick_seconds: float = 0.5,
        behavioral_rate: float = 1.0,
        spawner: Spawner | None = None,
        heartbeat_timeout_s: float = 5.0,
    ) -> None:
        """Wire proxy, scheduler, and provisioner; :meth:`start` boots the fleet.

        Args:
            unit: The unit-chip machine config (composition + fleet workload).
            chips: Initial fleet size (the demo starts at 1).
            noise_name: Noise config name passed to every chip process.
            rounds: SE rounds per live memory shot on chips.
            seed: Base seed passed to every chip process.
            tick_seconds: Live-stack wall pace per SE round.
            behavioral_rate: Machine seconds per wall second on behavioral
                chips (1.0 = real time; sweeps fast-forward with more).
            spawner: Chip lifecycle backend; None = local processes.
            heartbeat_timeout_s: Scheduler's chip-loss deadline.
        """
        self._chips = chips
        self._proxy = BusProxy()
        self._proxy.start()
        self._sockets: list[ZmqPublisher | ZmqSubscriber] = []
        self._threads: list[threading.Thread] = []

        self._scheduler = SchedulerService(
            self._pub(), unit, heartbeat_timeout_s=heartbeat_timeout_s
        )
        self._threads.append(threading.Thread(target=self._scheduler.run, args=(self._sub(),)))

        chip_args = [
            "node",
            "--role",
            "chip",
            "--frontend",
            self._proxy.frontend_address,
            "--backend",
            self._proxy.backend_address,
            "--noise",
            noise_name,
            "--rounds",
            str(rounds),
            "--seed",
            str(seed),
            "--pace-ms",
            str(tick_seconds * 1000.0),
            "--behavioral-rate",
            str(behavioral_rate),
            "--machine-name",
            unit.name,
        ]
        self._provisioner = ProvisionerService(self._pub(), spawner or ProcessSpawner(chip_args))
        self._threads.append(threading.Thread(target=self._provisioner.run, args=(self._sub(),)))
        self._command_pub = self._pub()

    def _pub(self) -> ZmqPublisher:
        """A new publisher on the proxy frontend, tracked for teardown."""
        pub = ZmqPublisher(self._proxy.frontend_address)
        self._sockets.append(pub)
        return pub

    def _sub(self) -> ZmqSubscriber:
        """A new subscriber on the proxy backend, tracked for teardown."""
        sub = ZmqSubscriber(self._proxy.backend_address)
        self._sockets.append(sub)
        return sub

    @property
    def frontend_address(self) -> str:
        """Where publishers (dashboard commands) connect."""
        return self._proxy.frontend_address

    @property
    def backend_address(self) -> str:
        """Where subscribers (dashboard relay) connect."""
        return self._proxy.backend_address

    @property
    def scheduler(self) -> SchedulerService:
        """The fleet scheduler (read access for status/tests)."""
        return self._scheduler

    def start(self) -> None:
        """Start scheduler and provisioner, then boot the initial fleet."""
        for thread in self._threads:
            thread.start()
        time.sleep(_SLOW_JOINER_S)  # let SUB subscriptions propagate before publishing
        if self._chips:
            self._command_pub.publish(
                ScaleUp(source="fleet-backend", target="provisioner", n=self._chips)
            )

    def stop(self) -> None:
        """Drain every chip, stop the fixed services, and close the bus."""
        self._provisioner.shutdown_fleet()
        self._scheduler.stop()
        self._provisioner.stop()
        for thread in self._threads:
            if thread.is_alive():
                thread.join(timeout=_JOIN_TIMEOUT_S)
        for socket in self._sockets:
            socket.close()
        self._proxy.stop()
