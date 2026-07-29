"""ZeroMQ pub/sub transport: publisher, subscriber, and the XSUB/XPUB proxy.

Exists so services couple only through topic-framed events on one well-known
address — the join-protocol contract the elastic runtime (M6) builds on.

Every socket here shares the single process-level context from
:func:`bus_context`: zmq contexts each cost file descriptors and an I/O
thread, and per-object contexts exhausted macOS's default 256-fd limit
(EMFILE) under the test suite — a failure that would only get worse at M6
scale (40 chips). The context is the charter's one sanctioned singleton.
"""

from __future__ import annotations

import contextlib
import threading
from typing import Protocol

import zmq

from catsim.bus.codec import AnyEvent, decode_event, encode_event

DEFAULT_FRONTEND_ADDRESS = "tcp://127.0.0.1:5561"
"""Where publishers connect (the proxy's XSUB side)."""

DEFAULT_BACKEND_ADDRESS = "tcp://127.0.0.1:5562"
"""Where subscribers connect (the proxy's XPUB side)."""


def bus_context() -> zmq.Context[zmq.Socket[bytes]]:
    """The process's single bus context (the charter's singleton carve-out).

    Never ``term()`` this context: owners close their own sockets instead.
    Termination would tear down every bus socket in the process at once —
    shutdown is per-socket, not per-context.
    """
    return zmq.Context.instance()


class EventSink(Protocol):
    """Anything events can be published to; lets tests inject in-memory sinks."""

    def publish(self, event: AnyEvent) -> None:
        """Deliver one event to the bus."""
        ...


class EventSource(Protocol):
    """Anything events can be polled from; lets tests script command feeds."""

    def receive(self, timeout_s: float = 0.05) -> AnyEvent | None:
        """Return the next event, or None if nothing arrives within the timeout."""
        ...


class ZmqPublisher:
    """PUB socket connected to the bus proxy; the process's handle for emitting."""

    def __init__(self, frontend_address: str = DEFAULT_FRONTEND_ADDRESS) -> None:
        """Connect to the proxy's XSUB side at ``frontend_address``."""
        self._socket = bus_context().socket(zmq.PUB)
        self._socket.connect(frontend_address)

    def publish(self, event: AnyEvent) -> None:
        """Send one event, topic-framed by its source component id."""
        self._socket.send_multipart([event.source.encode(), encode_event(event)])

    def close(self) -> None:
        """Release the socket (brief linger so in-flight events still land)."""
        self._socket.close(linger=100)


class ZmqSubscriber:
    """SUB socket connected to the bus proxy, filtered by topic prefix."""

    def __init__(self, backend_address: str = DEFAULT_BACKEND_ADDRESS, prefix: str = "") -> None:
        """Connect to the proxy's XPUB side; empty ``prefix`` subscribes to all."""
        self._socket = bus_context().socket(zmq.SUB)
        self._socket.connect(backend_address)
        self._socket.setsockopt(zmq.SUBSCRIBE, prefix.encode())

    def receive(self, timeout_s: float = 0.05) -> AnyEvent | None:
        """Return the next event, or None if nothing arrives within the timeout."""
        if not self._socket.poll(timeout=int(timeout_s * 1000)):
            return None
        _topic, payload = self._socket.recv_multipart()
        return decode_event(payload)

    def close(self) -> None:
        """Release the socket."""
        self._socket.close(linger=0)


class BusProxy:
    """XSUB/XPUB forwarder: the one well-known address everything connects to.

    Exists so services never bind — a chip container needs only the bus address,
    which is the join-protocol contract the elastic runtime (M6) builds on.
    Stopping is done through a steerable-proxy control socket (TERMINATE), not
    context termination, because the context is shared process-wide.
    """

    def __init__(
        self,
        frontend_address: str = "tcp://127.0.0.1:*",
        backend_address: str = "tcp://127.0.0.1:*",
    ) -> None:
        """Bind both sides; wildcard ports resolve to real ones at bind time."""
        ctx = bus_context()
        self._xsub = ctx.socket(zmq.XSUB)
        self._xsub.bind(frontend_address)
        self._xpub = ctx.socket(zmq.XPUB)
        self._xpub.bind(backend_address)
        self.frontend_address: str = self._xsub.getsockopt_string(zmq.LAST_ENDPOINT)
        self.backend_address: str = self._xpub.getsockopt_string(zmq.LAST_ENDPOINT)
        self._control_address = f"inproc://busproxy-control-{id(self):x}"
        self._control = ctx.socket(zmq.PAIR)
        self._control.bind(self._control_address)
        self._stopped = False
        self._thread = threading.Thread(target=self._forward, daemon=True)

    def _forward(self) -> None:
        """Pump messages until TERMINATE arrives on the control socket.

        The proxy's sockets MUST be closed by this thread (zmq sockets are not
        thread-safe): ``stop`` sends the command and then waits for exactly
        this cleanup before returning.
        """
        control = bus_context().socket(zmq.PAIR)
        control.connect(self._control_address)
        try:
            with contextlib.suppress(zmq.ZMQError):  # closed under us: shutdown
                zmq.proxy_steerable(self._xsub, self._xpub, None, control)
        finally:
            control.close(linger=0)
            self._xsub.close(linger=0)
            self._xpub.close(linger=0)

    def start(self) -> None:
        """Start forwarding in a daemon thread."""
        self._thread.start()

    def stop(self) -> None:
        """Send TERMINATE; the forwarder thread closes its own sockets."""
        if self._stopped:
            return
        self._stopped = True
        if self._thread.ident is None:  # never started: no thread to do cleanup
            self._xsub.close(linger=0)
            self._xpub.close(linger=0)
        else:
            with contextlib.suppress(zmq.ZMQError):
                self._control.send(b"TERMINATE")
            self._thread.join(timeout=2.0)
        self._control.close(linger=0)
