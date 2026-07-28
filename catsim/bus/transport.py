"""ZeroMQ pub/sub transport: publisher, subscriber, and the XSUB/XPUB proxy.

Exists so services couple only through topic-framed events on one well-known
address — the join-protocol contract the elastic runtime (M6) builds on.
"""

from __future__ import annotations

import contextlib
import threading
from typing import Protocol

import zmq

from catsim.bus.events import AnyEvent, decode_event, encode_event

DEFAULT_FRONTEND_ADDRESS = "tcp://127.0.0.1:5561"
"""Where publishers connect (the proxy's XSUB side)."""

DEFAULT_BACKEND_ADDRESS = "tcp://127.0.0.1:5562"
"""Where subscribers connect (the proxy's XPUB side)."""


class EventSink(Protocol):
    """Anything events can be published to; lets tests inject in-memory sinks."""

    def publish(self, event: AnyEvent) -> None:
        """Deliver one event to the bus."""
        ...


class ZmqPublisher:
    """PUB socket connected to the bus proxy; the process's handle for emitting."""

    def __init__(self, frontend_address: str = DEFAULT_FRONTEND_ADDRESS) -> None:
        """Connect to the proxy's XSUB side at ``frontend_address``."""
        self._ctx = zmq.Context()
        self._socket = self._ctx.socket(zmq.PUB)
        self._socket.connect(frontend_address)

    def publish(self, event: AnyEvent) -> None:
        """Send one event, topic-framed by its source component id."""
        self._socket.send_multipart([event.source.encode(), encode_event(event)])

    def close(self) -> None:
        """Release the socket and context."""
        self._socket.close(linger=100)
        self._ctx.term()


class ZmqSubscriber:
    """SUB socket connected to the bus proxy, filtered by topic prefix."""

    def __init__(self, backend_address: str = DEFAULT_BACKEND_ADDRESS, prefix: str = "") -> None:
        """Connect to the proxy's XPUB side; empty ``prefix`` subscribes to all."""
        self._ctx = zmq.Context()
        self._socket = self._ctx.socket(zmq.SUB)
        self._socket.connect(backend_address)
        self._socket.setsockopt(zmq.SUBSCRIBE, prefix.encode())

    def receive(self, timeout_s: float = 0.05) -> AnyEvent | None:
        """Return the next event, or None if nothing arrives within the timeout."""
        if not self._socket.poll(timeout=int(timeout_s * 1000)):
            return None
        _topic, payload = self._socket.recv_multipart()
        return decode_event(payload)

    def close(self) -> None:
        """Release the socket and context."""
        self._socket.close(linger=0)
        self._ctx.term()


class BusProxy:
    """XSUB/XPUB forwarder: the one well-known address everything connects to.

    Exists so services never bind — a chip container needs only the bus address,
    which is the join-protocol contract the elastic runtime (M6) builds on.
    """

    def __init__(
        self,
        frontend_address: str = "tcp://127.0.0.1:*",
        backend_address: str = "tcp://127.0.0.1:*",
    ) -> None:
        """Bind both sides; wildcard ports resolve to real ones at bind time."""
        self._ctx = zmq.Context()
        self._xsub = self._ctx.socket(zmq.XSUB)
        self._xsub.bind(frontend_address)
        self._xpub = self._ctx.socket(zmq.XPUB)
        self._xpub.bind(backend_address)
        self.frontend_address: str = self._xsub.getsockopt_string(zmq.LAST_ENDPOINT)
        self.backend_address: str = self._xpub.getsockopt_string(zmq.LAST_ENDPOINT)
        self._thread = threading.Thread(target=self._forward, daemon=True)

    def _forward(self) -> None:
        """Pump messages until the context terminates, then close our sockets.

        The sockets MUST be closed by this thread (zmq sockets are not
        thread-safe): ``stop``'s ``ctx.term()`` unblocks the proxy with ETERM
        and then waits for exactly this cleanup before returning.
        """
        try:
            with contextlib.suppress(zmq.ZMQError):  # ETERM: normal shutdown
                zmq.proxy(self._xsub, self._xpub)
        finally:
            self._xsub.close(linger=0)
            self._xpub.close(linger=0)

    def start(self) -> None:
        """Start forwarding in a daemon thread."""
        self._thread.start()

    def stop(self) -> None:
        """Terminate the context; the forwarder thread closes its own sockets."""
        if self._thread.ident is None:  # never started: no thread to do cleanup
            self._xsub.close(linger=0)
            self._xpub.close(linger=0)
        self._ctx.term()
        self._thread.join(timeout=2.0)
