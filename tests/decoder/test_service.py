"""DecoderService: bus-event handling end to end, without a pub/sub network."""

from collections.abc import Iterator

import pytest

from catsim.bus import (
    BlockConfigured,
    CorrectionApplied,
    DecodeFinished,
    DecodeQueue,
    DecodeStarted,
    LogicalError,
    QueryServer,
    RunFinished,
    SetDecoder,
    SetDecoderSlowdown,
    ShotFinished,
    SyndromeFired,
)
from catsim.codes import get_code
from catsim.component import (
    DepolarizingNoise,
    MemoryBlockSpec,
    block_layout,
    build_memory_circuit,
)
from catsim.decoder import DecoderService
from tests.conftest import ListSink


@pytest.fixture
def configured(busy_noise: DepolarizingNoise) -> Iterator[BlockConfigured]:
    """A block_configured event backed by a real query server serving DEM + layout."""
    spec = MemoryBlockSpec(code=get_code("surface", distance=3), noise=busy_noise, rounds=3)
    circuit = build_memory_circuit(spec.code, spec.noise, spec.rounds)
    dem = circuit.detector_error_model(decompose_errors=True)
    layout = block_layout(circuit)
    server = QueryServer({"dem": lambda: str(dem), "layout": layout.to_json})
    yield BlockConfigured(
        source="b0",
        code_name=spec.code.name,
        distance=3,
        rounds_per_shot=3,
        num_data_qubits=9,
        num_logical=1,
        noise_name=busy_noise.name,
        query_address=server.address,
    )
    server.close()


def test_syndrome_triggers_decode_events(list_sink: ListSink, configured: BlockConfigured) -> None:
    service = DecoderService(list_sink)
    service.handle(configured)
    service.handle(SyndromeFired(source="b0", shot=0, round=1, check_ids=[0]))
    kinds = [type(e) for e in list_sink.events]
    # queue depth 1 on arrival, the decode triple, queue drained back to 0
    assert kinds == [DecodeQueue, DecodeStarted, DecodeFinished, CorrectionApplied, DecodeQueue]
    finished = list_sink.events[2]
    assert isinstance(finished, DecodeFinished)
    assert finished.latency_s > 0.0
    assert finished.identified_qubits, "matched edges must resolve to blamed qubits"
    correction = list_sink.events[3]
    assert isinstance(correction, CorrectionApplied)
    assert correction.qubits == finished.identified_qubits


def test_queue_builds_while_ingesting_and_drains_on_work(
    list_sink: ListSink, configured: BlockConfigured
) -> None:
    """The live-loop shape: ingest without decoding, then work the backlog down."""
    service = DecoderService(list_sink)
    service.ingest(configured)
    service.ingest(SyndromeFired(source="b0", shot=0, round=1, check_ids=[0]))
    service.ingest(SyndromeFired(source="b0", shot=0, round=2, check_ids=[1]))
    assert service.pending_rounds == 2
    depths = [e.depth for e in list_sink.events if isinstance(e, DecodeQueue)]
    assert depths == [1, 2]
    while service.work_one():
        pass
    assert service.pending_rounds == 0
    depths = [e.depth for e in list_sink.events if isinstance(e, DecodeQueue)]
    assert depths == [1, 2, 1, 0]
    assert sum(1 for e in list_sink.events if isinstance(e, DecodeFinished)) == 2


def test_run_finished_drains_queued_verdicts(
    list_sink: ListSink, configured: BlockConfigured
) -> None:
    """A queued shot verdict must not be lost when the run ends behind a backlog."""
    service = DecoderService(list_sink)
    service.ingest(configured)
    service.ingest(SyndromeFired(source="b0", shot=0, round=1, check_ids=[0]))
    service.ingest(ShotFinished(source="b0", shot=0, actual_flips=[0]))
    assert service.handle(RunFinished(source="b0", shots=1)) is False
    assert [e for e in list_sink.events if isinstance(e, DecodeFinished)]


def test_slowdown_command_throttles_the_running_decoder(
    list_sink: ListSink, configured: BlockConfigured
) -> None:
    service = DecoderService(list_sink)
    service.handle(configured)
    service.handle(SyndromeFired(source="b0", shot=0, round=1, check_ids=[0]))  # warm decode
    baseline = [e for e in list_sink.events if isinstance(e, DecodeFinished)][-1].latency_s
    service.handle(SetDecoderSlowdown(source="dash", target="*", factor=200.0))
    assert service.slowdown_factor == 200.0
    service.handle(SyndromeFired(source="b0", shot=0, round=2, check_ids=[0]))
    throttled = [e for e in list_sink.events if isinstance(e, DecodeFinished)][-1].latency_s
    assert throttled > 5.0 * baseline, "a 200x throttle must dominate scheduling jitter"


def test_slowdown_for_other_target_ignored(
    list_sink: ListSink, configured: BlockConfigured
) -> None:
    service = DecoderService(list_sink)
    service.handle(configured)
    service.handle(SetDecoderSlowdown(source="dash", target="someone-else", factor=100.0))
    assert service.slowdown_factor == 1.0


def test_missed_flip_is_a_logical_error(list_sink: ListSink, configured: BlockConfigured) -> None:
    service = DecoderService(list_sink)
    service.handle(configured)
    # No syndromes at all, but the true frame flipped: the decoder cannot know.
    service.handle(ShotFinished(source="b0", shot=0, actual_flips=[0]))
    errors = [e for e in list_sink.events if isinstance(e, LogicalError)]
    assert len(errors) == 1
    assert errors[0].observables == [0]


def test_clean_shot_is_not_a_logical_error(
    list_sink: ListSink, configured: BlockConfigured
) -> None:
    service = DecoderService(list_sink)
    service.handle(configured)
    service.handle(ShotFinished(source="b0", shot=0, actual_flips=[]))
    assert not [e for e in list_sink.events if isinstance(e, LogicalError)]


def test_run_finished_stops_the_service(list_sink: ListSink, configured: BlockConfigured) -> None:
    service = DecoderService(list_sink)
    assert service.handle(configured) is True
    assert service.handle(RunFinished(source="b0", shots=1)) is False


def test_set_decoder_swaps_at_runtime(list_sink: ListSink, configured: BlockConfigured) -> None:
    service = DecoderService(list_sink, decoder_name="pymatching")
    service.handle(configured)
    service.handle(SetDecoder(source="dash", target="*", name="bposd"))
    service.handle(SyndromeFired(source="b0", shot=0, round=1, check_ids=[0]))
    finished = [e for e in list_sink.events if isinstance(e, DecodeFinished)]
    assert finished, "the swapped-in decoder must keep decoding"


def test_set_decoder_unknown_name_keeps_current(
    list_sink: ListSink, configured: BlockConfigured
) -> None:
    service = DecoderService(list_sink)
    service.handle(configured)
    service.handle(SetDecoder(source="dash", target="*", name="nope"))
    service.handle(SyndromeFired(source="b0", shot=0, round=1, check_ids=[0]))
    assert [e for e in list_sink.events if isinstance(e, DecodeFinished)]


def test_set_decoder_for_other_target_ignored(
    list_sink: ListSink, configured: BlockConfigured
) -> None:
    service = DecoderService(list_sink, decoder_name="pymatching")
    service.handle(configured)
    service.handle(SetDecoder(source="dash", target="someone-else", name="bposd"))
    service.handle(SyndromeFired(source="b0", shot=0, round=1, check_ids=[0]))
    assert [e for e in list_sink.events if isinstance(e, DecodeFinished)]
