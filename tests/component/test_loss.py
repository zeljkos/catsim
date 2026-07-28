"""Ion-loss recovery: tracker state machine, block path, and the qubit factory."""

from catsim.bus import (
    FactoryAccepted,
    FactoryAttempt,
    InjectLoss,
    IonLost,
    LossDetected,
    QubitReplaced,
    ReplacementDispatched,
    ReplacementReady,
    RoundStarted,
    RunFinished,
)
from catsim.codes import get_code
from catsim.component import (
    DepolarizingNoise,
    LossTracker,
    MemoryBlockService,
    MemoryBlockSpec,
    QubitFactoryService,
)
from tests.conftest import ListSink

# --- LossTracker -------------------------------------------------------------


def test_tracker_lifecycle_lost_detected_replaced() -> None:
    tracker = LossTracker()
    first = tracker.advance({5})
    assert first.newly_lost == (5,) and first.scramble == (5,)
    second = tracker.advance(set())
    assert second.newly_detected == (5,) and second.scramble == (5,)
    tracker.mark_ready(5)
    third = tracker.advance(set())
    assert third.replaced == (5,)
    assert third.scramble == (5,), "the rejoining qubit is scrambled exactly once"
    assert tracker.advance(set()).scramble == ()
    assert tracker.lost == frozenset()


def test_tracker_shot_end_fallback_clears_state() -> None:
    tracker = LossTracker()
    tracker.advance({3, 7})
    assert tracker.reset_shot() == (3, 7)
    assert tracker.lost == frozenset()
    assert tracker.advance(set()).scramble == ()


def test_tracker_ready_before_detection_still_replaces() -> None:
    tracker = LossTracker()
    tracker.advance({2})
    tracker.mark_ready(2)
    effects = tracker.advance(set())
    assert effects.replaced == (2,) and effects.newly_detected == ()


def test_tracker_ignores_duplicate_loss() -> None:
    tracker = LossTracker()
    tracker.advance({4})
    assert tracker.advance({4}).newly_lost == ()


# --- MemoryBlockService loss path ---------------------------------------------


def _block(sink: ListSink, noise: DepolarizingNoise, rounds: int = 6) -> MemoryBlockService:
    spec = MemoryBlockSpec(code=get_code("surface", distance=3), noise=noise, rounds=rounds)
    return MemoryBlockService(spec, sink, seed=0)


def test_block_detects_loss_one_round_after_it_lands(
    list_sink: ListSink, paper_noise: DepolarizingNoise
) -> None:
    service = _block(list_sink, paper_noise.scaled(0.0))
    try:
        service.handle_command(InjectLoss(source="test", target="block0", qubits=[5]))
        service.run(1)
    finally:
        service.close()
    lost = next(e for e in list_sink.events if isinstance(e, IonLost))
    detected = next(e for e in list_sink.events if isinstance(e, LossDetected))
    assert lost.round is not None
    assert (detected.qubit, detected.round) == (5, lost.round + 1)


def test_block_without_factory_falls_back_to_shot_end(
    list_sink: ListSink, paper_noise: DepolarizingNoise
) -> None:
    service = _block(list_sink, paper_noise)
    try:
        service.handle_command(InjectLoss(source="test", target="block0", qubits=[5]))
        service.run(1)
    finally:
        service.close()
    (replaced,) = [e for e in list_sink.events if isinstance(e, QubitReplaced)]
    assert replaced.qubit == 5
    assert replaced.round is None, "no factory answered: shot-end fallback"


class _AutoFactorySink(ListSink):
    """Records events and answers every loss_detected like an instant qubit factory."""

    def __init__(self) -> None:
        super().__init__()
        self.block: MemoryBlockService | None = None

    def publish(self, event: object) -> None:
        super().publish(event)  # type: ignore[arg-type]
        if isinstance(event, LossDetected) and self.block is not None:
            self.block.handle_command(
                ReplacementReady(source="qf0", target="block0", qubit=event.qubit)
            )


def test_block_replacement_ready_rejoins_mid_shot(paper_noise: DepolarizingNoise) -> None:
    sink = _AutoFactorySink()
    service = _block(sink, paper_noise.scaled(0.0), rounds=8)
    sink.block = service
    try:
        service.handle_command(InjectLoss(source="test", target="block0", qubits=[5]))
        service.run(1)
    finally:
        service.close()
    detected = next(e for e in sink.events if isinstance(e, LossDetected))
    (replaced,) = [e for e in sink.events if isinstance(e, QubitReplaced)]
    assert replaced.round is not None, "the factory path replaces mid-shot"
    assert replaced.round == detected.round + 1


# --- QubitFactoryService --------------------------------------------------------


def test_qubit_factory_dispatches_and_delivers(list_sink: ListSink) -> None:
    factory = QubitFactoryService(list_sink, dispatch_rounds=2)
    factory.configure()
    assert factory.handle(LossDetected(source="block0", qubit=9, shot=0, round=3)) is True
    dispatched = next(e for e in list_sink.events if isinstance(e, ReplacementDispatched))
    assert (dispatched.qubit, dispatched.block, dispatched.ready_in_rounds) == (9, "block0", 2)
    assert [e for e in list_sink.events if isinstance(e, FactoryAttempt)]
    factory.handle(RoundStarted(source="block0", shot=0, round=4))
    assert not [e for e in list_sink.events if isinstance(e, ReplacementReady)]
    factory.handle(RoundStarted(source="block0", shot=0, round=5))
    (ready,) = [e for e in list_sink.events if isinstance(e, ReplacementReady)]
    assert (ready.target, ready.qubit) == ("block0", 9)
    (accepted,) = [e for e in list_sink.events if isinstance(e, FactoryAccepted)]
    assert accepted.acceptance_rate == 1.0


def test_qubit_factory_ignores_other_blocks_rounds(list_sink: ListSink) -> None:
    factory = QubitFactoryService(list_sink, dispatch_rounds=1)
    factory.handle(LossDetected(source="block0", qubit=2, shot=0, round=1))
    factory.handle(RoundStarted(source="block1", shot=0, round=2))
    assert not [e for e in list_sink.events if isinstance(e, ReplacementReady)]
    factory.handle(RoundStarted(source="block0", shot=0, round=2))
    assert [e for e in list_sink.events if isinstance(e, ReplacementReady)]


def test_qubit_factory_dedupes_pending_requests(list_sink: ListSink) -> None:
    factory = QubitFactoryService(list_sink, dispatch_rounds=5)
    factory.handle(LossDetected(source="block0", qubit=2, shot=0, round=1))
    factory.handle(LossDetected(source="block0", qubit=2, shot=0, round=2))
    assert len([e for e in list_sink.events if isinstance(e, ReplacementDispatched)]) == 1


def test_qubit_factory_stops_on_run_finished(list_sink: ListSink) -> None:
    factory = QubitFactoryService(list_sink)
    assert factory.handle(RunFinished(source="block0", shots=1)) is False
