"""Single-block live run: block + decoder services wired over a real ZeroMQ bus.

Exists as M0 scaffolding proving events stream end-to-end on the bus; the M5
SimPy machine layer absorbs this orchestration role.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from catsim.bus import (
    AnyEvent,
    BusProxy,
    DecodeFinished,
    LogicalError,
    RunFinished,
    SyndromeFired,
    ZmqPublisher,
    ZmqSubscriber,
)
from catsim.component import MemoryBlockService, MemoryBlockSpec
from catsim.decoder import DecoderService

_JOIN_GRACE_S = 0.5
_SLOW_JOINER_S = 0.3


@dataclass
class DemoReport:
    """What a live run produced, tallied from the events seen on the bus."""

    shots: int
    logical_errors: int
    syndrome_events: int
    decode_events: int
    mean_decode_latency_s: float
    backend_address: str
    events: list[AnyEvent] = field(repr=False, default_factory=list)


def run_memory_demo(
    spec: MemoryBlockSpec,
    *,
    shots: int = 5,
    seed: int = 0,
    tick_seconds: float = 0.0,
    decoder_name: str = "pymatching",
    slowdown_factor: float = 1.0,
) -> DemoReport:
    """Run a live memory block against a decoder service over a real bus.

    Args:
        spec: The memory block to run (code, noise, rounds per shot).
        shots: Number of memory shots.
        seed: Simulator seed (reproducible runs).
        tick_seconds: Wall-clock pace per SE round (0 = flat out).
        decoder_name: Which registered decoder the service uses.
        slowdown_factor: Artificial decoder latency multiplier.

    Returns:
        A report with counters and the full ordered event stream.
    """
    proxy = BusProxy()
    proxy.start()
    events: list[AnyEvent] = []
    collector_sub = ZmqSubscriber(proxy.backend_address)
    collector = threading.Thread(target=_collect, args=(collector_sub, events), daemon=True)
    collector.start()

    decoder_pub = ZmqPublisher(proxy.frontend_address)
    decoder_sub = ZmqSubscriber(proxy.backend_address)
    service = DecoderService(
        decoder_pub, slowdown_factor=slowdown_factor, decoder_name=decoder_name
    )
    decoder_thread = threading.Thread(target=service.run, args=(decoder_sub,), daemon=True)
    decoder_thread.start()

    block_pub = ZmqPublisher(proxy.frontend_address)
    try:
        time.sleep(_SLOW_JOINER_S)  # let SUB subscriptions propagate before publishing
        block = MemoryBlockService(spec, block_pub, seed=seed, tick_seconds=tick_seconds)
        block.configure()
        block.run(shots)
        decoder_thread.join(timeout=10.0)
        collector.join(timeout=10.0)
        return _summarize(events, shots, proxy.backend_address)
    finally:
        block_pub.close()
        decoder_pub.close()
        decoder_sub.close()
        collector_sub.close()
        proxy.stop()


def _collect(subscriber: ZmqSubscriber, events: list[AnyEvent]) -> None:
    """Append every bus event, lingering briefly after run_finished for stragglers."""
    deadline: float | None = None
    idle_deadline = time.monotonic() + 30.0
    while time.monotonic() < (deadline or idle_deadline):
        event = subscriber.receive(timeout_s=0.05)
        if event is None:
            continue
        events.append(event)
        if isinstance(event, RunFinished):
            deadline = time.monotonic() + _JOIN_GRACE_S


def _summarize(events: list[AnyEvent], shots: int, backend_address: str) -> DemoReport:
    """Tally the event stream into the report the caller (and tests) assert on."""
    decode_latencies = [e.latency_s for e in events if isinstance(e, DecodeFinished)]
    return DemoReport(
        shots=shots,
        logical_errors=sum(1 for e in events if isinstance(e, LogicalError)),
        syndrome_events=sum(1 for e in events if isinstance(e, SyndromeFired)),
        decode_events=len(decode_latencies),
        mean_decode_latency_s=(
            sum(decode_latencies) / len(decode_latencies) if decode_latencies else 0.0
        ),
        backend_address=backend_address,
        events=events,
    )
