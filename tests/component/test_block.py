"""Live memory block: event stream shape and reproducibility."""

from catsim.bus import BlockConfigured, RunFinished, ShotFinished, SyndromeFired
from catsim.codes import get_code
from catsim.component import DepolarizingNoise, MemoryBlockService, MemoryBlockSpec
from tests.conftest import ListSink


def _run(sink: ListSink, noise: DepolarizingNoise, shots: int = 2, seed: int = 3) -> None:
    """Configure and run a small d=3 block into the given sink."""
    spec = MemoryBlockSpec(code=get_code("surface", distance=3), noise=noise, rounds=4)
    service = MemoryBlockService(spec, sink, seed=seed)
    service.configure()
    service.run(shots)


def test_event_stream_shape(list_sink: ListSink, busy_noise: DepolarizingNoise) -> None:
    _run(list_sink, busy_noise)
    events = list_sink.events
    assert isinstance(events[0], BlockConfigured)
    assert events[0].dem  # decoders can be built from the announcement alone
    assert isinstance(events[-1], RunFinished)
    assert sum(1 for e in events if isinstance(e, ShotFinished)) == 2
    syndromes = [e for e in events if isinstance(e, SyndromeFired)]
    assert syndromes, "100x paper noise must fire syndromes in 2 shots"
    assert all(e.check_ids for e in syndromes)


def test_check_ids_index_the_dem(list_sink: ListSink, busy_noise: DepolarizingNoise) -> None:
    _run(list_sink, busy_noise)
    configured = list_sink.events[0]
    assert isinstance(configured, BlockConfigured)
    import stim

    num_detectors = stim.DetectorErrorModel(configured.dem).num_detectors
    for e in list_sink.events:
        if isinstance(e, SyndromeFired):
            assert all(0 <= i < num_detectors for i in e.check_ids)


def test_same_seed_same_stream(busy_noise: DepolarizingNoise) -> None:
    a, b = ListSink(), ListSink()
    _run(a, busy_noise, seed=11)
    _run(b, busy_noise, seed=11)
    assert a.events == b.events
