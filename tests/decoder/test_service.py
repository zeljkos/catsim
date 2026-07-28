"""DecoderService: bus-event handling end to end, without a network."""

from catsim.bus import (
    BlockConfigured,
    CorrectionApplied,
    DecodeFinished,
    DecodeStarted,
    LogicalError,
    RunFinished,
    ShotFinished,
    SyndromeFired,
)
from catsim.codes import get_code
from catsim.component import DepolarizingNoise, MemoryBlockSpec, build_memory_circuit
from catsim.decoder import DecoderService
from tests.conftest import ListSink


def _configured(noise: DepolarizingNoise) -> BlockConfigured:
    """A block_configured event for a d=3 block, as the block would emit it."""
    spec = MemoryBlockSpec(code=get_code("surface", distance=3), noise=noise, rounds=3)
    circuit = build_memory_circuit(spec.code, spec.noise, spec.rounds)
    return BlockConfigured(
        source="b0",
        code_name=spec.code.name,
        distance=3,
        rounds_per_shot=3,
        num_data_qubits=9,
        num_logical=1,
        noise_name=noise.name,
        dem=str(circuit.detector_error_model(decompose_errors=True)),
    )


def test_syndrome_triggers_decode_events(
    list_sink: ListSink, busy_noise: DepolarizingNoise
) -> None:
    service = DecoderService(list_sink)
    service.handle(_configured(busy_noise))
    service.handle(SyndromeFired(source="b0", shot=0, round=1, check_ids=[0]))
    kinds = [type(e) for e in list_sink.events]
    assert kinds == [DecodeStarted, DecodeFinished, CorrectionApplied]
    finished = list_sink.events[1]
    assert isinstance(finished, DecodeFinished)
    assert finished.latency_s > 0.0


def test_missed_flip_is_a_logical_error(list_sink: ListSink, busy_noise: DepolarizingNoise) -> None:
    service = DecoderService(list_sink)
    service.handle(_configured(busy_noise))
    # No syndromes at all, but the true frame flipped: the decoder cannot know.
    service.handle(ShotFinished(source="b0", shot=0, actual_flips=[0]))
    errors = [e for e in list_sink.events if isinstance(e, LogicalError)]
    assert len(errors) == 1
    assert errors[0].observables == [0]


def test_clean_shot_is_not_a_logical_error(
    list_sink: ListSink, busy_noise: DepolarizingNoise
) -> None:
    service = DecoderService(list_sink)
    service.handle(_configured(busy_noise))
    service.handle(ShotFinished(source="b0", shot=0, actual_flips=[]))
    assert not [e for e in list_sink.events if isinstance(e, LogicalError)]


def test_run_finished_stops_the_service(list_sink: ListSink, busy_noise: DepolarizingNoise) -> None:
    service = DecoderService(list_sink)
    assert service.handle(_configured(busy_noise)) is True
    assert service.handle(RunFinished(source="b0", shots=1)) is False
