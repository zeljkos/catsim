"""The always-on live backend: proxy + ticking block + decoder + factories, on one bus.

Exists so the dashboard (and its tests) can bring up the whole M1–M3 machine
with one object and tear it down cleanly; the M5 SimPy layer will absorb this
role.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence

from catsim.bus import BusProxy, ZmqPublisher, ZmqSubscriber
from catsim.component import (
    FactoryService,
    FactorySpec,
    MemoryBlockService,
    MemoryBlockSpec,
    QubitFactoryService,
)
from catsim.decoder import DecoderService

_SLOW_JOINER_S = 0.3
_JOIN_TIMEOUT_S = 10.0

DEFAULT_FACTORY_KINDS = ("cat", "bell", "magic")


class LiveBackend:
    """Runs a memory block, decoder, and factories as threads over a private bus.

    Everything ticks until :meth:`stop` (paced by ``tick_seconds``, adjustable
    live via ``set_pace`` commands); the qubit factory closes the ion-loss
    loop by answering the block's ``loss_detected`` events.
    """

    def __init__(
        self,
        spec: MemoryBlockSpec,
        *,
        seed: int = 0,
        tick_seconds: float = 0.5,
        decoder_name: str = "pymatching",
        source: str = "block0",
        factory_kinds: Sequence[str] = DEFAULT_FACTORY_KINDS,
        with_qubit_factory: bool = True,
    ) -> None:
        """Wire proxy, block, decoder, and factories; nothing runs until :meth:`start`.

        Args:
            spec: The memory block to run (factories share its noise model).
            seed: Simulator seed (reproducible runs).
            tick_seconds: Initial wall-clock pace per SE round / factory attempt.
            decoder_name: Which registered decoder the service uses.
            source: The block's component id (command target).
            factory_kinds: Which registered stim factories to run ("" = none).
            with_qubit_factory: Run the replacement dispenser (ion-loss path).
        """
        self._proxy = BusProxy()
        self._proxy.start()
        self._sockets: list[ZmqPublisher | ZmqSubscriber] = []
        self._threads: list[threading.Thread] = []

        self._decoder = DecoderService(self._pub(), decoder_name=decoder_name)
        self._threads.append(
            threading.Thread(
                target=self._decoder.run, args=(self._sub(),), kwargs={"idle_timeout_s": None}
            )
        )

        self._block = MemoryBlockService(
            spec,
            self._pub(),
            source=source,
            seed=seed,
            tick_seconds=tick_seconds,
            commands=self._sub(),
        )
        self._block_thread = threading.Thread(target=self._block.run, args=(None,))

        self._factories: list[FactoryService] = []
        for kind in factory_kinds:
            factory = FactoryService(
                FactorySpec(kind=kind, noise=spec.noise),
                self._pub(),
                seed=seed,
                tick_seconds=tick_seconds,
                commands=self._sub(),
            )
            self._factories.append(factory)
            self._threads.append(threading.Thread(target=factory.run, args=(None,)))

        self._qubit_factory: QubitFactoryService | None = None
        if with_qubit_factory:
            self._qubit_factory = QubitFactoryService(self._pub())
            self._threads.append(
                threading.Thread(
                    target=self._qubit_factory.run,
                    args=(self._sub(),),
                    kwargs={"idle_timeout_s": None},
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
        """Start every service thread; the block announces itself first."""
        for thread in self._threads:
            thread.start()
        time.sleep(_SLOW_JOINER_S)  # let SUB subscriptions propagate before publishing
        self._block.configure()
        self._block_thread.start()

    def stop(self) -> None:
        """Stop the block (its run_finished releases the decoder), then tear down."""
        self._block.stop()
        for factory in self._factories:
            factory.stop()
        if self._qubit_factory is not None:
            self._qubit_factory.stop()
        if self._block_thread.is_alive():
            self._block_thread.join(timeout=_JOIN_TIMEOUT_S)
        for thread in self._threads:
            if thread.is_alive():
                thread.join(timeout=_JOIN_TIMEOUT_S)
        self._block.close()
        for socket in self._sockets:
            socket.close()
        self._proxy.stop()
