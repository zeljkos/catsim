"""M0 acceptance: the full pipeline streams events over a real ZeroMQ bus."""

from catsim.bus import BlockConfigured, DecodeFinished, RunFinished
from catsim.codes import get_code
from catsim.component import DepolarizingNoise, MemoryBlockSpec
from catsim.machine import run_memory_demo


def test_events_stream_end_to_end(busy_noise: DepolarizingNoise) -> None:
    spec = MemoryBlockSpec(code=get_code("surface", distance=3), noise=busy_noise, rounds=6)
    report = run_memory_demo(spec, shots=3, seed=7)

    assert report.shots == 3
    assert report.syndrome_events > 0, "100x noise must fire syndromes"
    assert report.decode_events >= report.syndrome_events  # final decodes included
    assert report.mean_decode_latency_s > 0.0

    assert isinstance(report.events[0], BlockConfigured)
    assert any(isinstance(e, RunFinished) for e in report.events)
    sources = {e.source for e in report.events}
    assert {"block0", "decoder0"} <= sources, "both services published on the bus"
    latencies = [e.latency_s for e in report.events if isinstance(e, DecodeFinished)]
    assert all(t > 0 for t in latencies)
