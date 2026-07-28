"""On-request query channel (REQ/REP) for bulk artifacts too big for events.

Exists because broadcast events must stay small: a block announces itself with
summary fields plus a ``query_address``, and consumers fetch heavyweight data
(detector error model, qubit layout) from there only when they need it.
"""

from __future__ import annotations

import contextlib
import json
import threading
from collections.abc import Callable

import zmq

QueryHandler = Callable[[], str]


class QueryServer:
    """REP socket answering named queries with string payloads.

    Handlers are zero-argument callables so served data always reflects the
    owner's current state (e.g. the DEM after a live noise-model rebuild).
    """

    def __init__(
        self,
        handlers: dict[str, QueryHandler],
        address: str = "tcp://127.0.0.1:*",
    ) -> None:
        """Bind the REP socket and start answering in a daemon thread.

        Args:
            handlers: Query name -> callable returning the payload string.
            address: Bind address; the wildcard port resolves at bind time.
        """
        self._handlers = handlers
        self._ctx = zmq.Context()
        self._socket = self._ctx.socket(zmq.REP)
        self._socket.bind(address)
        self.address: str = self._socket.getsockopt_string(zmq.LAST_ENDPOINT)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        """Answer requests until closed; malformed or unknown queries get errors."""
        with contextlib.suppress(zmq.ZMQError):  # context terminated: normal shutdown
            while not self._stop.is_set():
                if not self._socket.poll(timeout=100):
                    continue
                request = self._socket.recv_json()
                name = request.get("query") if isinstance(request, dict) else None
                handler = self._handlers.get(name) if isinstance(name, str) else None
                if handler is None:
                    self._socket.send_json({"ok": False, "error": f"unknown query {name!r}"})
                else:
                    self._socket.send_json({"ok": True, "data": handler()})

    def close(self) -> None:
        """Stop the serving thread, then tear down its socket and context."""
        self._stop.set()
        self._thread.join(timeout=2.0)
        self._ctx.destroy(linger=0)


class QueryError(RuntimeError):
    """The server rejected the query or did not answer in time."""


def query(address: str, name: str, timeout_s: float = 5.0) -> str:
    """Fetch one named payload from a :class:`QueryServer`.

    Args:
        address: The server's resolved address (from ``block_configured``).
        name: Query name, e.g. ``"dem"`` or ``"layout"``.
        timeout_s: How long to wait before giving up.

    Returns:
        The payload string.

    Raises:
        QueryError: On timeout or a server-side error.
    """
    ctx = zmq.Context()
    socket = ctx.socket(zmq.REQ)
    try:
        socket.connect(address)
        socket.send_json({"query": name})
        if not socket.poll(timeout=int(timeout_s * 1000)):
            raise QueryError(f"no reply from {address} for query {name!r}")
        reply = json.loads(socket.recv())
        if not reply.get("ok"):
            raise QueryError(str(reply.get("error", "query failed")))
        return str(reply["data"])
    finally:
        socket.close(linger=0)
        ctx.term()
