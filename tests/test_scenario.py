"""Scenarios: YAML loading, runner triggering, and the two M1 acceptance runs."""

import pytest

from catsim.bus import (
    AnyEvent,
    Command,
    CorrectionApplied,
    ErrorInjected,
    InjectPauli,
    IonLost,
    LogicalError,
    LossDetected,
    QubitReplaced,
    ReplacementDispatched,
    RoundStarted,
    SetNoiseScale,
    SyndromeFired,
)
from catsim.codes import get_code
from catsim.component import MemoryBlockService, MemoryBlockSpec, QubitFactoryService
from catsim.decoder import DecoderService
from catsim.scenario import Scenario, ScenarioRunner, list_scenarios, load_scenario
from tests.conftest import REPO_ROOT, ListSink

SCENARIO_DIR = REPO_ROOT / "configs" / "scenarios"


def test_shipped_scenarios_load() -> None:
    scenarios = list_scenarios(SCENARIO_DIR)
    names = [s.name for s in scenarios]
    assert {"single-decoherence", "beyond-distance", "ion-loss", "factory-yield"} <= set(names)
    assert all(s.description for s in scenarios)


def test_load_by_name_and_by_path() -> None:
    by_name = load_scenario("single-decoherence", SCENARIO_DIR)
    by_path = load_scenario(SCENARIO_DIR / "single-decoherence.yaml")
    assert by_name == by_path


def test_step_requires_exactly_one_action() -> None:
    with pytest.raises(ValueError, match="exactly one action"):
        Scenario.model_validate({"name": "x", "description": "y", "steps": [{"at": {"round": 1}}]})


def test_runner_fires_at_the_scripted_round(list_sink: ListSink) -> None:
    scenario = load_scenario("single-decoherence", SCENARIO_DIR)
    runner = ScenarioRunner(scenario, list_sink)
    assert runner.handle(RoundStarted(source="block0", shot=0, round=1)) is True
    assert not list_sink.events, "round 1 is before the scripted round 2"
    assert runner.handle(RoundStarted(source="block0", shot=0, round=2)) is False
    assert runner.done
    (command,) = list_sink.events
    assert isinstance(command, InjectPauli)
    assert command.target == "block0"


def test_runner_ignores_other_sources(list_sink: ListSink) -> None:
    scenario = load_scenario("single-decoherence", SCENARIO_DIR)
    runner = ScenarioRunner(scenario, list_sink)
    runner.handle(RoundStarted(source="block1", shot=0, round=5))
    assert not list_sink.events


class _Fanout:
    """In-memory bus: records everything and forwards to attached handlers."""

    def __init__(self) -> None:
        self.events: list[AnyEvent] = []
        self.handlers: list[object] = []

    def publish(self, event: AnyEvent) -> None:
        self.events.append(event)
        for handle in self.handlers:
            handle(event)  # type: ignore[operator]


class _CommandPipe:
    """Delivers runner commands straight into the block, synchronously."""

    def __init__(self, block: MemoryBlockService) -> None:
        self._block = block

    def publish(self, event: AnyEvent) -> None:
        assert isinstance(event, Command)
        self._block.handle_command(event)


class _CommandRouter:
    """Qubit-factory sink: commands go straight to the block, events to the fanout."""

    def __init__(self, fan: _Fanout, block: MemoryBlockService) -> None:
        self._fan = fan
        self._block = block

    def publish(self, event: AnyEvent) -> None:
        if isinstance(event, Command):
            self._fan.events.append(event)
            self._block.handle_command(event)
        else:
            self._fan.publish(event)


def _run_scenario(
    name: str, paper_noise: object, *, with_qubit_factory: bool = False
) -> list[AnyEvent]:
    """Block + decoder (+ qubit factory) + scenario wired synchronously in memory."""
    spec = MemoryBlockSpec(code=get_code("surface", distance=3), noise=paper_noise, rounds=8)  # type: ignore[arg-type]
    fan = _Fanout()
    block = MemoryBlockService(spec, fan, seed=1)
    try:
        decoder = DecoderService(fan)
        runner = ScenarioRunner(load_scenario(name, SCENARIO_DIR), _CommandPipe(block))
        fan.handlers = [runner.handle, decoder.handle]
        if with_qubit_factory:
            factory = QubitFactoryService(_CommandRouter(fan, block))
            fan.handlers.append(factory.handle)
        block.configure()
        block.run(2)
    finally:
        block.close()
    return fan.events


def test_single_decoherence_is_corrected_without_logical_error(
    paper_noise: object,
) -> None:
    events = _run_scenario("single-decoherence", paper_noise)
    injected = [e for e in events if isinstance(e, ErrorInjected)]
    assert [(e.pauli, e.qubits) for e in injected] == [("Z", [10])]
    fired = [e for e in events if isinstance(e, SyndromeFired)]
    assert fired, "the injected error must fire checks"
    corrections = [e for e in events if isinstance(e, CorrectionApplied)]
    assert corrections and corrections[0].qubits, "the decoder must blame qubits"
    assert not [e for e in events if isinstance(e, LogicalError)], (
        "a single error is within the code distance: logical state survives"
    )


def test_beyond_distance_lands_a_logical_error(paper_noise: object) -> None:
    events = _run_scenario("beyond-distance", paper_noise)
    injected = [e for e in events if isinstance(e, ErrorInjected)]
    assert [(e.pauli, e.qubits) for e in injected] == [("X", [1, 8])]
    assert [e for e in events if isinstance(e, LogicalError)], (
        "a burst wider than the distance must defeat the decoder"
    )


def test_ion_loss_recovers_end_to_end(paper_noise: object) -> None:
    """M3 acceptance: loss -> detection -> dispatch -> mid-shot rejoin, no logical error."""
    events = _run_scenario("ion-loss", paper_noise, with_qubit_factory=True)
    assert [e.qubit for e in events if isinstance(e, IonLost)] == [10]
    detected = [e for e in events if isinstance(e, LossDetected)]
    dispatched = [e for e in events if isinstance(e, ReplacementDispatched)]
    replaced = [e for e in events if isinstance(e, QubitReplaced)]
    assert [e.qubit for e in detected] == [10]
    assert [(e.qubit, e.block) for e in dispatched] == [(10, "block0")]
    assert [e.qubit for e in replaced] == [10]
    assert replaced[0].round is not None, "the factory path replaces mid-shot"
    assert not [e for e in events if isinstance(e, LogicalError)], (
        "loss recovery within the code distance must not cost a logical qubit"
    )


def test_factory_yield_broadcasts_noise_steps(list_sink: ListSink) -> None:
    scenario = load_scenario("factory-yield", SCENARIO_DIR)
    assert scenario.target == "*"
    runner = ScenarioRunner(scenario, list_sink)
    # "*" scenarios trigger on any component's rounds and broadcast commands.
    runner.handle(RoundStarted(source="block0", shot=0, round=0))
    (command,) = list_sink.events
    assert isinstance(command, SetNoiseScale)
    assert command.target == "*"
    runner.handle(RoundStarted(source="block0", shot=5, round=0))
    assert runner.done
