"""MachineService: announcements, lockstep pacing, calibration, outage routing."""

from catsim.bus import (
    ChipConfigured,
    ChipStatus,
    FactoryAccepted,
    LogicalError,
    MachineStatus,
    RoundStarted,
    RunFinished,
    SetPaused,
    ShotFinished,
)
from catsim.machine import MachineModel, MachineService, load_machine_config
from tests.conftest import REPO_ROOT, ListSink

MACHINE_DIR = REPO_ROOT / "configs" / "machine"


def _service(sink: ListSink, name: str = "chip-256") -> MachineService:
    model = MachineModel(load_machine_config(name, MACHINE_DIR), seed=1)
    return MachineService(model, sink)


def _round(i: int, source: str = "block0") -> RoundStarted:
    return RoundStarted(source=source, shot=0, round=i)


def test_announce_carries_composition_and_accounting(list_sink: ListSink) -> None:
    _service(list_sink).announce()
    chips = [e for e in list_sink.events if isinstance(e, ChipConfigured)]
    assert len(chips) == 1
    chip = chips[0]
    assert chip.nominal_qubits == 256
    assert chip.paper_qubits == 262
    assert chip.logical_qubits == 6
    assert chip.accounting == "paper"
    assert chip.blocks[0].code_name == "q70"
    assert chip.blocks[0].memory_qubits == 220
    assert chip.blocks[0].cat_qubits == 42
    assert chip.magic_factories == []
    assert any(isinstance(e, MachineStatus) for e in list_sink.events)


def test_roadmap_announce_surfaces_lean_divergence(list_sink: ListSink) -> None:
    _service(list_sink, "chip-256-roadmap").announce()
    chip = next(e for e in list_sink.events if isinstance(e, ChipConfigured))
    assert chip.accounting == "lean"
    assert chip.paper_qubits == 524
    assert chip.nominal_qubits == 256
    assert "524" in chip.accounting_note
    assert len(chip.blocks) == 2


def test_rounds_drive_machine_time_and_status_cadence(list_sink: ListSink) -> None:
    service = _service(list_sink)  # status_every_rounds: 5
    for i in range(10):
        assert service.handle(_round(i))
    statuses = [e for e in list_sink.events if isinstance(e, MachineStatus)]
    assert len(statuses) == 2
    assert abs(statuses[-1].machine_seconds - 10 * 0.006) < 1e-9
    assert statuses[-1].t_stall_reason  # memory-only: attributed, not hidden
    assert statuses[-1].predicted_t_per_day == 0.0


def test_only_pace_block_rounds_advance_time(list_sink: ListSink) -> None:
    service = _service(list_sink, "chip-256-roadmap")
    for i in range(5):
        service.handle(_round(i, source="block1"))
    assert not any(isinstance(e, MachineStatus) for e in list_sink.events)


def test_set_paused_routes_to_model_factory(list_sink: ListSink) -> None:
    service = _service(list_sink)
    service.handle(SetPaused(source="dash", target="cat0", paused=True))
    for i in range(200):
        service.handle(_round(i))
    last_chip = [e for e in list_sink.events if isinstance(e, ChipStatus)][-1]
    assert last_chip.state == "degraded"
    assert last_chip.factories[0].state == "down"
    assert last_chip.blocks[0].state == "stalled"
    assert last_chip.blocks[0].stalled_rounds > 0
    assert last_chip.utilization < 1.0


def test_measured_acceptance_flows_into_model(list_sink: ListSink) -> None:
    service = _service(list_sink)
    service.handle(
        FactoryAccepted(source="cat0", attempt=4, attempts=4, accepted=1, acceptance_rate=0.25)
    )
    for i in range(10_000):
        service.handle(_round(i))
    last_chip = [e for e in list_sink.events if isinstance(e, ChipStatus)][-1]
    assert last_chip.blocks[0].stalled_rounds > 1_000  # 0.5 produced vs 1 consumed per SEC


def test_verdict_counters_and_run_end(list_sink: ListSink) -> None:
    service = _service(list_sink)
    service.handle(ShotFinished(source="block0", shot=0, actual_flips=[]))
    service.handle(LogicalError(source="decoder0", shot=0, observables=[0]))
    for i in range(5):
        service.handle(_round(i))
    status = [e for e in list_sink.events if isinstance(e, MachineStatus)][-1]
    assert status.measured_shots == 1
    assert status.measured_logical_errors == 1
    assert status.logical_error_per_logical_per_shot == 1 / 6
    assert not service.handle(RunFinished(source="block0", shots=1))
