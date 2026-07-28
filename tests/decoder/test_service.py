"""DecoderService: bus-event handling end to end, without a pub/sub network."""

from collections.abc import Iterator

import pytest

from catsim.bus import (
    BlockConfigured,
    CorrectionApplied,
    DecodeFinished,
    DecodeStarted,
    LogicalError,
    QueryServer,
    RunFinished,
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
    assert kinds == [DecodeStarted, DecodeFinished, CorrectionApplied]
    finished = list_sink.events[1]
    assert isinstance(finished, DecodeFinished)
    assert finished.latency_s > 0.0
    assert finished.identified_qubits, "matched edges must resolve to blamed qubits"
    correction = list_sink.events[2]
    assert isinstance(correction, CorrectionApplied)
    assert correction.qubits == finished.identified_qubits


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
