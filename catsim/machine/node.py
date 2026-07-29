"""Long-running fleet node entry points: chip, scheduler, provisioner.

Exists so ``catsim node --role ...`` (one container image, role from the
environment) is a thin shell over these library calls: each wires zmq sockets
around the corresponding service and runs it until interrupted. The dashboard
role lives in the CLI itself (the machine layer must not import dashboard).
"""

from __future__ import annotations

import contextlib
import zlib

from catsim.bus import BusProxy, ZmqPublisher, ZmqSubscriber
from catsim.component import load_noise_model
from catsim.machine.chip import ChipRuntime
from catsim.machine.config import load_machine_config
from catsim.machine.provisioner import (
    DockerSpawner,
    ProcessSpawner,
    ProvisionerService,
    Spawner,
)
from catsim.machine.scheduler import SchedulerService

DEFAULT_FRONTEND = "tcp://127.0.0.1:5561"
"""Well-known bus frontend (publishers connect) when no address is given."""

DEFAULT_BACKEND = "tcp://127.0.0.1:5562"
"""Well-known bus backend (subscribers connect) when no address is given."""


def derive_seed(base_seed: int, instance_id: str) -> int:
    """A reproducible per-instance seed: base plus a hash of the instance id."""
    return base_seed + zlib.crc32(instance_id.encode()) % 10_000


def run_chip(
    instance_id: str,
    frontend: str,
    backend: str,
    *,
    noise_name: str = "paper-baseline",
    machine_name: str = "chip-256",
    rounds: int = 10,
    seed: int = 0,
    pace_ms: float = 500.0,
    behavioral_rate: float = 1.0,
) -> None:
    """Run one chip runtime against the bus until it is stopped or drained."""
    noise = load_noise_model(noise_name)
    pub = ZmqPublisher(frontend)
    sub = ZmqSubscriber(backend)
    runtime = ChipRuntime(
        pub,
        instance_id=instance_id,
        noise=noise,
        machine_name=machine_name,
        rounds=rounds,
        seed=derive_seed(seed, instance_id),
        tick_seconds=pace_ms / 1000.0,
        behavioral_rate=behavioral_rate,
        live_bus=(frontend, backend),
    )
    try:
        with contextlib.suppress(KeyboardInterrupt):
            runtime.run(sub)
    finally:
        runtime.close()
        pub.close()
        sub.close()


def run_scheduler(
    bind_frontend: str,
    bind_backend: str,
    *,
    machine: str = "chip-256",
    heartbeat_timeout_s: float = 5.0,
) -> None:
    """Bind the bus proxy at well-known addresses and run the scheduler."""
    unit = load_machine_config(machine)
    proxy = BusProxy(bind_frontend, bind_backend)
    proxy.start()
    pub = ZmqPublisher(proxy.frontend_address)
    sub = ZmqSubscriber(proxy.backend_address)
    scheduler = SchedulerService(pub, unit, heartbeat_timeout_s=heartbeat_timeout_s)
    try:
        with contextlib.suppress(KeyboardInterrupt):
            scheduler.run(sub)
    finally:
        pub.close()
        sub.close()
        proxy.stop()


def run_provisioner(
    frontend: str,
    backend: str,
    *,
    spawn: str = "process",
    image: str = "catsim:latest",
    network: str | None = None,
    noise_name: str = "paper-baseline",
    machine_name: str = "chip-256",
    rounds: int = 10,
    seed: int = 0,
    pace_ms: float = 500.0,
    initial_chips: int = 0,
) -> None:
    """Run the provisioner with the chosen chip lifecycle backend."""
    spawner: Spawner
    if spawn == "docker":
        spawner = DockerSpawner(
            image,
            {
                "CATSIM_ROLE": "chip",
                "CATSIM_BUS_FRONTEND": frontend,
                "CATSIM_BUS_BACKEND": backend,
                "CATSIM_NOISE": noise_name,
                "CATSIM_MACHINE_NAME": machine_name,
                "CATSIM_ROUNDS": str(rounds),
                "CATSIM_SEED": str(seed),
                "CATSIM_PACE_MS": str(pace_ms),
            },
            network=network,
        )
    else:
        spawner = ProcessSpawner(
            [
                "node",
                "--role",
                "chip",
                "--frontend",
                frontend,
                "--backend",
                backend,
                "--noise",
                noise_name,
                "--machine-name",
                machine_name,
                "--rounds",
                str(rounds),
                "--seed",
                str(seed),
                "--pace-ms",
                str(pace_ms),
            ]
        )
    pub = ZmqPublisher(frontend)
    sub = ZmqSubscriber(backend)
    service = ProvisionerService(pub, spawner)
    try:
        if initial_chips:  # compose boots the first chip without a click
            service.scale_up(initial_chips)
        with contextlib.suppress(KeyboardInterrupt):
            service.run(sub)
    finally:
        # The run loop has exited, so chip_left events no longer drain the
        # instance list — the short deadline hands off to reap_all quickly.
        service.shutdown_fleet(deadline_s=2.0)
        pub.close()
        sub.close()
