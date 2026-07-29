"""ChipRuntime: join protocol, fidelity dial, heartbeats, status stream."""

import time

from catsim.bus import (
    ChipAdmitted,
    ChipAnnounce,
    ChipConfigured,
    ChipHeartbeat,
    ChipLeft,
    ChipStatus,
    SetPaused,
    StopChip,
)
from catsim.component import DepolarizingNoise
from catsim.machine import ChipRuntime
from tests.conftest import ListSink


def _runtime(sink: ListSink, noise: DepolarizingNoise, **kwargs: object) -> ChipRuntime:
    return ChipRuntime(sink, instance_id="inst-t", noise=noise, **kwargs)  # type: ignore[arg-type]


def _memory_admission(mode: str = "behavioral", demand: float = 0.0) -> ChipAdmitted:
    return ChipAdmitted(
        source="scheduler",
        target="inst-t",
        chip_id="chip3",
        role="memory",
        mode=mode,  # type: ignore[arg-type]
        blocks=[{"family": "bb", "code": "q70"}],  # type: ignore[list-item]
        t_demand_per_second=demand,
    )


def test_announce_advertises_behavioral_only_without_live_bus(
    list_sink: ListSink, paper_noise: DepolarizingNoise
) -> None:
    runtime = _runtime(list_sink, paper_noise)
    runtime.announce()
    announce = list_sink.events[0]
    assert isinstance(announce, ChipAnnounce)
    assert announce.source == "inst-t"
    assert announce.modes == ["behavioral"]


def test_admission_publishes_composition_and_status(
    list_sink: ListSink, paper_noise: DepolarizingNoise
) -> None:
    runtime = _runtime(list_sink, paper_noise)
    assert runtime.handle(_memory_admission())
    configured = next(e for e in list_sink.events if isinstance(e, ChipConfigured))
    assert configured.chip_id == "chip3"
    assert configured.role == "memory"
    assert configured.paper_qubits == 262  # 220 memory + 42 cat (Table V)
    assert configured.blocks[0].block_id == "chip3-block0"
    status = next(e for e in list_sink.events if isinstance(e, ChipStatus))
    assert status.mode == "behavioral"
    assert status.state == "ok"


def test_admission_for_someone_else_is_ignored(
    list_sink: ListSink, paper_noise: DepolarizingNoise
) -> None:
    runtime = _runtime(list_sink, paper_noise)
    runtime.handle(_memory_admission().model_copy(update={"target": "inst-other"}))
    assert runtime.chip_id is None
    assert list_sink.events == []


def test_behavioral_clock_advances_machine_time(
    list_sink: ListSink, paper_noise: DepolarizingNoise
) -> None:
    runtime = _runtime(list_sink, paper_noise)
    runtime.handle(_memory_admission())
    runtime.tick(time.monotonic() + 10.0)  # 10 wall-seconds at rate 1.0
    runtime.publish_status()
    status = [e for e in list_sink.events if isinstance(e, ChipStatus)][-1]
    assert 9.0 < status.machine_seconds < 11.0
    assert status.blocks[0].rounds > 1_000  # ~166 SEC/s of machine time


def test_heartbeats_carry_sequence_and_mode(
    list_sink: ListSink, paper_noise: DepolarizingNoise
) -> None:
    runtime = _runtime(list_sink, paper_noise, heartbeat_s=0.5)
    runtime.handle(_memory_admission())
    now = time.monotonic()
    runtime.tick(now)
    runtime.tick(now + 0.6)
    beats = [e for e in list_sink.events if isinstance(e, ChipHeartbeat)]
    assert [b.seq for b in beats] == [1, 2]
    assert all(b.source == "chip3" and b.mode == "behavioral" for b in beats)


def test_factory_chip_serves_demand_and_handed_backlog(
    list_sink: ListSink, paper_noise: DepolarizingNoise
) -> None:
    runtime = _runtime(list_sink, paper_noise)
    admission = ChipAdmitted(
        source="scheduler",
        target="inst-t",
        chip_id="chip17",
        role="factory",
        mode="behavioral",
        blocks=[],
        magic_factories=["ch2"],
        t_demand_per_second=12.0,
        t_backlog=100,
    )
    runtime.handle(admission)
    runtime.tick(time.monotonic() + 30.0)
    runtime.publish_status()
    status = [e for e in list_sink.events if isinstance(e, ChipStatus)][-1]
    assert status.role == "factory"
    assert status.t_done > 100  # demand plus the handed-over backlog got served


def test_rebalance_readmission_updates_demand_without_rebuild(
    list_sink: ListSink, paper_noise: DepolarizingNoise
) -> None:
    runtime = _runtime(list_sink, paper_noise)
    runtime.handle(_memory_admission())
    runtime.tick(time.monotonic() + 5.0)
    runtime.publish_status()
    before = [e for e in list_sink.events if isinstance(e, ChipStatus)][-1]
    runtime.handle(_memory_admission(demand=1.0))  # same shape: no rebuild
    runtime.publish_status()
    after = [e for e in list_sink.events if isinstance(e, ChipStatus)][-1]
    assert after.machine_seconds >= before.machine_seconds  # state survived


def test_live_admission_without_live_bus_degrades_to_behavioral(
    list_sink: ListSink, paper_noise: DepolarizingNoise
) -> None:
    runtime = _runtime(list_sink, paper_noise)
    runtime.handle(_memory_admission(mode="live"))
    assert runtime.mode == "behavioral"
    status = next(e for e in list_sink.events if isinstance(e, ChipStatus))
    assert status.mode == "behavioral"


def test_set_paused_mirrors_into_model(list_sink: ListSink, paper_noise: DepolarizingNoise) -> None:
    runtime = _runtime(list_sink, paper_noise)
    runtime.handle(_memory_admission())
    runtime.handle(SetPaused(source="dash", target="chip3-cat0", paused=True))
    runtime.tick(time.monotonic() + 5.0)  # buffer (24) drains, then stalls
    runtime.publish_status()
    status = [e for e in list_sink.events if isinstance(e, ChipStatus)][-1]
    assert status.state == "degraded"
    assert status.factories[0].state == "down"
    assert status.blocks[0].stalled_rounds > 0


def test_stop_chip_publishes_chip_left_and_exits(
    list_sink: ListSink, paper_noise: DepolarizingNoise
) -> None:
    runtime = _runtime(list_sink, paper_noise)
    runtime.handle(_memory_admission())
    assert not runtime.handle(StopChip(source="provisioner", target="chip3"))
    left = list_sink.events[-1]
    assert isinstance(left, ChipLeft)
    assert left.chip_id == "chip3"


def test_stop_chip_for_someone_else_is_ignored(
    list_sink: ListSink, paper_noise: DepolarizingNoise
) -> None:
    runtime = _runtime(list_sink, paper_noise)
    runtime.handle(_memory_admission())
    assert runtime.handle(StopChip(source="provisioner", target="chip9"))
    assert not any(isinstance(e, ChipLeft) for e in list_sink.events)
