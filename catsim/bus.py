"""Event schemas (pydantic) and ZeroMQ transport — the system's only runtime coupling.

Every running service publishes and subscribes through these versioned models;
nothing else may couple services at runtime. Topic = source component id.
"""

from __future__ import annotations

import contextlib
import threading
from typing import Annotated, Literal, Protocol

import zmq
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

SCHEMA_VERSION = 1

DEFAULT_FRONTEND_ADDRESS = "tcp://127.0.0.1:5561"
"""Where publishers connect (the proxy's XSUB side)."""

DEFAULT_BACKEND_ADDRESS = "tcp://127.0.0.1:5562"
"""Where subscribers connect (the proxy's XPUB side)."""


class Event(BaseModel):
    """Common envelope for every bus event; concrete subclasses set ``type``."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = SCHEMA_VERSION
    source: str
    tick: int | None = None


class BlockConfigured(Event):
    """A memory block announced its circuit; carries the DEM a decoder needs."""

    type: Literal["block_configured"] = "block_configured"
    code_name: str
    distance: int
    rounds_per_shot: int
    num_data_qubits: int
    num_logical: int
    noise_name: str
    dem: str


class ErrorInjected(Event):
    """A physical error hit qubits (natural noise or console injection)."""

    type: Literal["error_injected"] = "error_injected"
    shot: int
    round: int
    qubits: list[int]
    pauli: str
    cause: Literal["noise", "injected"] = "injected"


class SyndromeFired(Event):
    """Stabilizer checks flagged this round; ids index detectors in the DEM."""

    type: Literal["syndrome_fired"] = "syndrome_fired"
    shot: int
    round: int
    check_ids: list[int]


class DecodeStarted(Event):
    """The decoder began working on the syndrome history of a shot."""

    type: Literal["decode_started"] = "decode_started"
    shot: int
    round: int


class DecodeFinished(Event):
    """Decode result: measured wall-clock latency plus what the decoder blamed.

    ``identified_qubits`` stays empty until M1 adds detector-to-qubit geometry;
    ``matched_detectors`` are the matched detector pairs (-1 = boundary).
    """

    type: Literal["decode_finished"] = "decode_finished"
    shot: int
    round: int
    latency_s: float
    identified_qubits: list[int]
    matched_detectors: list[tuple[int, int]]


class CorrectionApplied(Event):
    """The decoder's Pauli-frame correction: which logical observables it flips."""

    type: Literal["correction_applied"] = "correction_applied"
    shot: int
    round: int
    observables: list[int]


class LogicalError(Event):
    """Decoder prediction disagreed with the true frame: a logical error landed."""

    type: Literal["logical_error"] = "logical_error"
    shot: int
    observables: list[int]


class ShotFinished(Event):
    """A memory shot ended; carries the true observable flips for the verdict."""

    type: Literal["shot_finished"] = "shot_finished"
    shot: int
    actual_flips: list[int]


class RunFinished(Event):
    """The component finished its run; services may drain and stop."""

    type: Literal["run_finished"] = "run_finished"
    shots: int


class IonLost(Event):
    """An ion physically left the trap (schema reserved for M3)."""

    type: Literal["ion_lost"] = "ion_lost"
    qubit: int


class QubitReplaced(Event):
    """A replacement ion was loaded for a lost one (schema reserved for M3)."""

    type: Literal["qubit_replaced"] = "qubit_replaced"
    qubit: int


AnyEvent = Annotated[
    (
        BlockConfigured
        | ErrorInjected
        | SyndromeFired
        | DecodeStarted
        | DecodeFinished
        | CorrectionApplied
        | LogicalError
        | ShotFinished
        | RunFinished
        | IonLost
        | QubitReplaced
    ),
    Field(discriminator="type"),
]

_ADAPTER: TypeAdapter[AnyEvent] = TypeAdapter(AnyEvent)


def encode_event(event: AnyEvent) -> bytes:
    """Serialize an event to JSON bytes for the wire."""
    return event.model_dump_json().encode()


def decode_event(data: bytes) -> AnyEvent:
    """Parse wire bytes back into the concrete event type via the discriminator."""
    return _ADAPTER.validate_json(data)


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
        """Pump messages between the two sides until the context dies."""
        with contextlib.suppress(zmq.ZMQError):  # context terminated: normal shutdown
            zmq.proxy(self._xsub, self._xpub)

    def start(self) -> None:
        """Start forwarding in a daemon thread."""
        self._thread.start()

    def stop(self) -> None:
        """Tear down sockets and context, unblocking the forwarder thread."""
        self._ctx.destroy(linger=0)
        self._thread.join(timeout=2.0)
