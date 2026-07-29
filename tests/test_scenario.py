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
    SetDecoderSlowdown,
    SetNoiseScale,
    SetPace,
    SetPaused,
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
    assert {
        "single-decoherence",
        "beyond-distance",
        "ion-loss",
        "factory-yield",
        "factory-outage",
        "decoder-overload",
    } <= set(names)
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


def test_decoder_overload_throttles_then_recovers(list_sink: ListSink) -> None:
    """M4: the overload script broadcasts a past-budget throttle, then removes it."""
    scenario = load_scenario("decoder-overload", SCENARIO_DIR)
    assert scenario.target == "*", "the throttle must reach the decoder service"
    runner = ScenarioRunner(scenario, list_sink)
    runner.handle(RoundStarted(source="block0", shot=0, round=0))
    assert {type(e) for e in list_sink.events} == {SetPace, SetNoiseScale}
    runner.handle(RoundStarted(source="block0", shot=20, round=0))
    throttle = list_sink.events[-1]
    assert isinstance(throttle, SetDecoderSlowdown)
    assert throttle.factor > 1.0, "the throttle must push decode past the budget"
    runner.handle(RoundStarted(source="block0", shot=120, round=0))
    recovery = list_sink.events[-1]
    assert isinstance(recovery, SetDecoderSlowdown)
    assert recovery.factor == 1.0, "removing the throttle is the recovery beat"
    runner.handle(RoundStarted(source="block0", shot=160, round=0))
    assert runner.done


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


def test_factory_outage_kills_and_revives_the_cat_factory(list_sink: ListSink) -> None:
    """M5: the outage script pauses cat0 (per-step target override), then revives it."""
    scenario = load_scenario("factory-outage", SCENARIO_DIR)
    assert scenario.target == "block0", "rounds trigger on the block"
    runner = ScenarioRunner(scenario, list_sink)
    runner.handle(RoundStarted(source="block0", shot=0, round=0))
    assert isinstance(list_sink.events[-1], SetPace)
    runner.handle(RoundStarted(source="block0", shot=2, round=0))
    outage = list_sink.events[-1]
    assert isinstance(outage, SetPaused)
    assert outage.target == "cat0" and outage.paused, "the kill must hit the factory, not the block"
    runner.handle(RoundStarted(source="block0", shot=8, round=0))
    revival = list_sink.events[-1]
    assert isinstance(revival, SetPaused)
    assert revival.target == "cat0" and not revival.paused
    assert runner.done


def test_factory_outage_degrades_and_recovers_the_machine(list_sink: ListSink) -> None:
    """The outage commands, routed through the machine service, stall and heal the chip."""
    from catsim.bus import ChipStatus
    from catsim.machine import MachineModel, MachineService, load_machine_config

    model = MachineModel(load_machine_config("chip-256", REPO_ROOT / "configs" / "machine"), seed=1)
    service = MachineService(model, list_sink)
    runner_sink = ListSink()
    runner = ScenarioRunner(load_scenario("factory-outage", SCENARIO_DIR), runner_sink)

    def drive(shot: int, rounds: int) -> None:
        for r in range(rounds):
            event = RoundStarted(source="block0", shot=shot, round=r)
            runner.handle(event)
            while runner_sink.events:
                service.handle(runner_sink.events.pop(0))
            service.handle(event)

    drive(shot=0, rounds=1)  # set_pace fires (block-side; no machine effect)
    drive(shot=2, rounds=60)  # outage: buffer (24) drains, stalls accumulate
    stalled = [e for e in list_sink.events if isinstance(e, ChipStatus)][-1]
    assert stalled.state == "degraded"
    assert stalled.blocks[0].state == "stalled"
    drive(shot=8, rounds=60)  # revival: buffer refills, stalls stop
    *_, penultimate, recovered = [e for e in list_sink.events if isinstance(e, ChipStatus)]
    assert recovered.state == "ok"
    assert recovered.blocks[0].state == "ok"
    assert recovered.blocks[0].stalled_rounds == penultimate.blocks[0].stalled_rounds, (
        "stalls must stop accumulating once the factory is back"
    )
