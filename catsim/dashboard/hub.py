"""Bus-to-WebSocket fanout: one subscriber thread feeding every connected client.

Exists so the dashboard renders bus events verbatim — the hub forwards JSON
payloads untouched and only remembers the latest block announcement so late
joiners can bootstrap (layout fetch, counters context).
"""

from __future__ import annotations

import asyncio
import threading

from catsim.bus import AnyEvent, BlockConfigured, ZmqSubscriber


class EventHub:
    """Relays bus events to asyncio queues, one per connected websocket."""

    def __init__(self) -> None:
        """Start empty; a loop is attached when the web app starts up."""
        self._clients: set[asyncio.Queue[str]] = set()
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.latest_configured: BlockConfigured | None = None

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Bind the asyncio loop client queues live on (the web app's loop)."""
        self._loop = loop

    def start(self, subscriber: ZmqSubscriber, loop: asyncio.AbstractEventLoop) -> None:
        """Begin pumping ``subscriber`` into client queues on ``loop``'s thread."""
        self.attach_loop(loop)
        self._thread = threading.Thread(target=self._pump, args=(subscriber,), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the pump thread (the caller owns and closes the subscriber)."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _pump(self, subscriber: ZmqSubscriber) -> None:
        """Forward every bus event until stopped."""
        while not self._stop.is_set():
            event = subscriber.receive(timeout_s=0.1)
            if event is not None:
                self.dispatch(event)

    def dispatch(self, event: AnyEvent) -> None:
        """Fan one event out to every client queue (thread-safe)."""
        if isinstance(event, BlockConfigured):
            self.latest_configured = event
        payload = event.model_dump_json()
        with self._lock:
            clients = list(self._clients)
        if self._loop is None:
            return
        for queue in clients:
            self._loop.call_soon_threadsafe(queue.put_nowait, payload)

    def register(self) -> asyncio.Queue[str]:
        """Add a client; it immediately receives the cached block announcement."""
        queue: asyncio.Queue[str] = asyncio.Queue()
        if self.latest_configured is not None:
            queue.put_nowait(self.latest_configured.model_dump_json())
        with self._lock:
            self._clients.add(queue)
        return queue

    def unregister(self, queue: asyncio.Queue[str]) -> None:
        """Drop a disconnected client."""
        with self._lock:
            self._clients.discard(queue)
