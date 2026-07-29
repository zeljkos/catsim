"""Live memory block: event stream shape, reproducibility, and command handling."""

import stim

from catsim.bus import (
    AnyEvent,
    BlockConfigured,
    ErrorInjected,
    InjectLoss,
    InjectPauli,
    IonLost,
    QubitReplaced,
    RoundStarted,
    RunFinished,
    SetNoiseScale,
    SetPace,
    SetPaused,
    ShotFinished,
    SyndromeFired,
    query,
)
from catsim.codes import get_code
from catsim.component import DepolarizingNoise, MemoryBlockService, MemoryBlockSpec
from tests.conftest import ListSink


def _run(sink: ListSink, noise: DepolarizingNoise, shots: int = 2, seed: int = 3) -> None:
    """Configure and run a small d=3 block into the given sink."""
    spec = MemoryBlockSpec(code=get_code("surface", distance=3), noise=noise, rounds=4)
    service = MemoryBlockService(spec, sink, seed=seed)
    try:
        service.configure()
        service.run(shots)
    finally:
        service.close()


def test_event_stream_shape(list_sink: ListSink, busy_noise: DepolarizingNoise) -> None:
    _run(list_sink, busy_noise)
    events = list_sink.events
    assert isinstance(events[0], BlockConfigured)
    assert isinstance(events[-1], RunFinished)
    assert sum(1 for e in events if isinstance(e, ShotFinished)) == 2
    syndromes = [e for e in events if isinstance(e, SyndromeFired)]
    assert syndromes, "100x paper noise must fire syndromes in 2 shots"
    assert all(e.check_ids for e in syndromes)
    rounds = [e for e in events if isinstance(e, RoundStarted)]
    assert [e.round for e in rounds if e.shot == 0] == list(range(len(rounds) // 2))


def test_configured_event_is_small_and_queries_serve_the_dem(
    list_sink: ListSink, busy_noise: DepolarizingNoise
) -> None:
    _run(list_sink, busy_noise)
    configured = list_sink.events[0]
    assert isinstance(configured, BlockConfigured)
    assert "dem" not in configured.model_dump()
    assert len(configured.model_dump_json()) < 500, "announcement must stay wire-small"


def test_check_ids_index_the_served_dem(list_sink: ListSink, busy_noise: DepolarizingNoise) -> None:
    spec = MemoryBlockSpec(code=get_code("surface", distance=3), noise=busy_noise, rounds=4)
    service = MemoryBlockService(spec, list_sink, seed=3)
    try:
        service.configure()
        service.run(2)
        configured = list_sink.events[0]
        assert isinstance(configured, BlockConfigured)
        dem = stim.DetectorErrorModel(query(configured.query_address, "dem"))
        for e in list_sink.events:
            if isinstance(e, SyndromeFired):
                assert all(0 <= i < dem.num_detectors for i in e.check_ids)
    finally:
        service.close()


def test_same_seed_same_stream(busy_noise: DepolarizingNoise) -> None:
    a, b = ListSink(), ListSink()
    _run(a, busy_noise, seed=11)
    _run(b, busy_noise, seed=11)
    key = [
        (e.type, e.model_dump(exclude={"query_address"}))  # port differs per run
        for e in a.events
    ]
    key_b = [(e.type, e.model_dump(exclude={"query_address"})) for e in b.events]
    assert key == key_b


def test_injected_pauli_fires_deterministic_syndrome(
    list_sink: ListSink, paper_noise: DepolarizingNoise
) -> None:
    noiseless = paper_noise.scaled(0.0)
    spec = MemoryBlockSpec(code=get_code("surface", distance=3), noise=noiseless, rounds=4)
    service = MemoryBlockService(spec, list_sink, seed=0)
    try:
        service.handle_command(InjectPauli(source="test", target="block0", qubits=[10], pauli="X"))
        service.run(1)
    finally:
        service.close()
    injected = [e for e in list_sink.events if isinstance(e, ErrorInjected)]
    assert len(injected) == 1
    assert injected[0].qubits == [10]
    assert injected[0].cause == "injected"
    syndromes = [e for e in list_sink.events if isinstance(e, SyndromeFired)]
    assert len(syndromes) == 1, "noiseless block: only the injection fires checks"
    assert syndromes[0].round == injected[0].round


def test_injection_on_unknown_qubit_is_ignored(
    list_sink: ListSink, paper_noise: DepolarizingNoise
) -> None:
    noiseless = paper_noise.scaled(0.0)
    spec = MemoryBlockSpec(code=get_code("surface", distance=3), noise=noiseless, rounds=4)
    service = MemoryBlockService(spec, list_sink, seed=0)
    try:
        service.handle_command(InjectPauli(source="test", target="block0", qubits=[999], pauli="X"))
        service.run(1)
    finally:
        service.close()
    assert not [e for e in list_sink.events if isinstance(e, ErrorInjected | SyndromeFired)]


def test_loss_marks_ion_and_replaces_at_shot_end(
    list_sink: ListSink, paper_noise: DepolarizingNoise
) -> None:
    spec = MemoryBlockSpec(code=get_code("surface", distance=3), noise=paper_noise, rounds=4)
    service = MemoryBlockService(spec, list_sink, seed=0)
    try:
        service.handle_command(InjectLoss(source="test", target="block0", qubits=[5]))
        service.run(1)
    finally:
        service.close()
    lost = [e for e in list_sink.events if isinstance(e, IonLost)]
    replaced = [e for e in list_sink.events if isinstance(e, QubitReplaced)]
    assert [e.qubit for e in lost] == [5]
    assert [e.qubit for e in replaced] == [5]
    events = list_sink.events
    assert events.index(replaced[0]) > events.index(lost[0])


def test_noise_scale_rebuilds_at_shot_boundary(
    list_sink: ListSink, paper_noise: DepolarizingNoise
) -> None:
    spec = MemoryBlockSpec(code=get_code("surface", distance=3), noise=paper_noise, rounds=4)
    service = MemoryBlockService(spec, list_sink, seed=0)
    try:
        service.configure()
        service.handle_command(SetNoiseScale(source="test", target="block0", scale=10.0))
        service.run(1)
    finally:
        service.close()
    configured = [e for e in list_sink.events if isinstance(e, BlockConfigured)]
    assert len(configured) == 2, "scale change re-announces the block"
    assert configured[1].noise_scale == 10.0
    assert configured[1].noise_name.endswith("-x10")
    first_round = next(e for e in list_sink.events if isinstance(e, RoundStarted))
    assert list_sink.events.index(configured[1]) < list_sink.events.index(first_round)


class _ScriptedCommands:
    """Command feed handing out one scripted entry per poll (None = bus quiet)."""

    def __init__(self, script: list[AnyEvent | None]) -> None:
        self._script = script

    def receive(self, timeout_s: float = 0.05) -> AnyEvent | None:
        return self._script.pop(0) if self._script else None


def test_injection_armed_while_paused_fires_on_first_resumed_round(
    list_sink: ListSink, paper_noise: DepolarizingNoise
) -> None:
    """Demo-rehearsal guarantee: pause, arm an injection, resume — it lands at once."""
    noiseless = paper_noise.scaled(0.0)
    spec = MemoryBlockSpec(code=get_code("surface", distance=3), noise=noiseless, rounds=4)
    commands = _ScriptedCommands(
        [
            SetPaused(source="test", target="block0", paused=True),
            None,  # pause engages; the block is now waiting
            InjectPauli(source="test", target="block0", qubits=[10], pauli="X"),
            None,  # armed while paused, not yet fired
            SetPaused(source="test", target="block0", paused=False),
        ]
    )
    service = MemoryBlockService(spec, list_sink, seed=0, commands=commands)
    try:
        service.run(1)
    finally:
        service.close()
    injected = [e for e in list_sink.events if isinstance(e, ErrorInjected)]
    assert len(injected) == 1
    assert injected[0].round == 1, "must fire on the first injectable round after resume"
    syndromes = [e for e in list_sink.events if isinstance(e, SyndromeFired)]
    assert syndromes and syndromes[0].round == injected[0].round


def test_set_pace_takes_effect(list_sink: ListSink, paper_noise: DepolarizingNoise) -> None:
    spec = MemoryBlockSpec(code=get_code("surface", distance=3), noise=paper_noise, rounds=4)
    service = MemoryBlockService(spec, list_sink, seed=0, tick_seconds=0.0)
    try:
        service.handle_command(SetPace(source="test", target="block0", tick_seconds=0.25))
        assert service.tick_seconds == 0.25
    finally:
        service.close()
