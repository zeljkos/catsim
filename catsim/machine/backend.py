"""The one-chip machine backend: real blocks + factories + SimPy machine, one bus.

Exists so ``catsim serve --machine chip-256`` brings up Act 1 with one object:
every block in the chip composition runs as a real stim service (with its cat
unit and its own decoder), the qubit factory answers ion loss, and the machine
service keeps the SimPy model in lockstep — all torn down cleanly. In M6 the
chip container absorbs the per-chip slice of this wiring.
"""

from __future__ import annotations

import threading
import time

from catsim.bus import BusProxy, ZmqPublisher, ZmqSubscriber
from catsim.component import (
    FactoryService,
    FactorySpec,
    MemoryBlockService,
    NoiseModel,
    QubitFactoryService,
    build_block_spec,
)
from catsim.decoder import DecoderService, default_decoder
from catsim.machine.config import MachineConfig
from catsim.machine.model import MachineModel
from catsim.machine.service import MachineService

_SLOW_JOINER_S = 0.3
_JOIN_TIMEOUT_S = 10.0


class MachineBackend:
    """Runs one chip's real services plus the machine model over a private bus.

    Real stim services are spawned for the first chip's composition (the
    hero instruments); any further chips exist in the model only until the
    M6 container runtime hosts them for real.
    """

    def __init__(
        self,
        machine: MachineConfig,
        noise: NoiseModel,
        *,
        rounds: int = 10,
        seed: int = 0,
        tick_seconds: float = 0.5,
        decoder_name: str | None = None,
    ) -> None:
        """Wire proxy, per-block services, and the machine service; start() runs them.

        Args:
            machine: The machine instance (chip composition, assumptions).
            noise: Noise model shared by every real service.
            rounds: SE rounds per memory shot.
            seed: Base seed; block ``i`` runs on ``seed + i``.
            tick_seconds: Initial wall-clock pace per SE round / attempt.
            decoder_name: Decoder for every block (None = family default).
        """
        self._proxy = BusProxy()
        self._proxy.start()
        self._sockets: list[ZmqPublisher | ZmqSubscriber] = []
        self._threads: list[threading.Thread] = []
        self._blocks: list[MemoryBlockService] = []
        self._block_threads: list[threading.Thread] = []
        self._factories: list[FactoryService] = []
        self.active_decoders: dict[str, str] = {}

        for index, block_cfg in enumerate(machine.chip.blocks):
            spec = build_block_spec(block_cfg.family, block_cfg.code, noise, rounds)
            block_source = f"block{index}"
            name = decoder_name or default_decoder(block_cfg.family)
            self.active_decoders[block_source] = name
            decoder = DecoderService(
                self._pub(), decoder_name=name, source=f"decoder{index}", block=block_source
            )
            self._threads.append(
                threading.Thread(
                    target=decoder.run, args=(self._sub(),), kwargs={"idle_timeout_s": None}
                )
            )
            block = MemoryBlockService(
                spec,
                self._pub(),
                source=block_source,
                seed=seed + index,
                tick_seconds=tick_seconds,
                commands=self._sub(),
            )
            self._blocks.append(block)
            self._block_threads.append(threading.Thread(target=block.run, args=(None,)))
            cat = FactoryService(
                FactorySpec(kind="cat", noise=noise),
                self._pub(),
                source=f"cat{index}",
                seed=seed + index,
                tick_seconds=tick_seconds,
                commands=self._sub(),
            )
            self._factories.append(cat)
            self._threads.append(threading.Thread(target=cat.run, args=(None,)))

        self._qubit_factory = QubitFactoryService(self._pub())
        self._threads.append(
            threading.Thread(
                target=self._qubit_factory.run,
                args=(self._sub(),),
                kwargs={"idle_timeout_s": None},
            )
        )

        self._machine = MachineService(MachineModel(machine, seed=seed), self._pub())
        self._threads.append(
            threading.Thread(
                target=self._machine.run, args=(self._sub(),), kwargs={"idle_timeout_s": None}
            )
        )

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

    def start(self) -> None:
        """Start every service thread; chips and blocks announce themselves first."""
        for thread in self._threads:
            thread.start()
        time.sleep(_SLOW_JOINER_S)  # let SUB subscriptions propagate before publishing
        self._machine.announce()
        for block in self._blocks:
            block.configure()
        for thread in self._block_threads:
            thread.start()

    def stop(self) -> None:
        """Stop blocks (their run_finished releases the decoders), then tear down."""
        for block in self._blocks:
            block.stop()
        for factory in self._factories:
            factory.stop()
        self._qubit_factory.stop()
        self._machine.stop()
        for thread in [*self._block_threads, *self._threads]:
            if thread.is_alive():
                thread.join(timeout=_JOIN_TIMEOUT_S)
        for block in self._blocks:
            block.close()
        for socket in self._sockets:
            socket.close()
        self._proxy.stop()
