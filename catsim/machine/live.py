"""The always-on live backend: proxy + ticking block + decoder, on one bus.

Exists so the dashboard (and its tests) can bring up the whole M1 machine with
one object and tear it down cleanly; the M5 SimPy layer will absorb this role.
"""

from __future__ import annotations

import threading
import time

from catsim.bus import BusProxy, ZmqPublisher, ZmqSubscriber
from catsim.component import MemoryBlockService, MemoryBlockSpec
from catsim.decoder import DecoderService

_SLOW_JOINER_S = 0.3


class LiveBackend:
    """Runs a memory block and a decoder as threads over a private bus proxy.

    The block ticks forever (paced by ``tick_seconds``, adjustable live via
    ``set_pace`` commands) until :meth:`stop`.
    """

    def __init__(
        self,
        spec: MemoryBlockSpec,
        *,
        seed: int = 0,
        tick_seconds: float = 0.5,
        decoder_name: str = "pymatching",
        source: str = "block0",
    ) -> None:
        """Wire proxy, block, and decoder; nothing runs until :meth:`start`.

        Args:
            spec: The memory block to run.
            seed: Simulator seed (reproducible runs).
            tick_seconds: Initial wall-clock pace per SE round (slow motion).
            decoder_name: Which registered decoder the service uses.
            source: The block's component id (command target).
        """
        self._proxy = BusProxy()
        self._proxy.start()
        self._decoder_pub = ZmqPublisher(self._proxy.frontend_address)
        self._decoder_sub = ZmqSubscriber(self._proxy.backend_address)
        self._decoder = DecoderService(self._decoder_pub, decoder_name=decoder_name)
        self._block_pub = ZmqPublisher(self._proxy.frontend_address)
        self._command_sub = ZmqSubscriber(self._proxy.backend_address)
        self._block = MemoryBlockService(
            spec,
            self._block_pub,
            source=source,
            seed=seed,
            tick_seconds=tick_seconds,
            commands=self._command_sub,
        )
        self._decoder_thread = threading.Thread(
            target=self._decoder.run, args=(self._decoder_sub,), kwargs={"idle_timeout_s": None}
        )
        self._block_thread = threading.Thread(target=self._block.run, args=(None,))

    @property
    def frontend_address(self) -> str:
        """Where publishers (dashboard commands) connect."""
        return self._proxy.frontend_address

    @property
    def backend_address(self) -> str:
        """Where subscribers (dashboard relay) connect."""
        return self._proxy.backend_address

    def start(self) -> None:
        """Start decoder and block threads; the block announces itself first."""
        self._decoder_thread.start()
        time.sleep(_SLOW_JOINER_S)  # let SUB subscriptions propagate before publishing
        self._block.configure()
        self._block_thread.start()

    def stop(self) -> None:
        """Stop the block (its run_finished releases the decoder), then tear down."""
        self._block.stop()
        if self._block_thread.is_alive():
            self._block_thread.join(timeout=10.0)
        if self._decoder_thread.is_alive():
            self._decoder_thread.join(timeout=10.0)
        self._block.close()
        self._block_pub.close()
        self._command_sub.close()
        self._decoder_pub.close()
        self._decoder_sub.close()
        self._proxy.stop()
