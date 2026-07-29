"""SchedulerService: admission, modules, role balancing, loss, focus, roll-up."""

import time

from catsim.bus import (
    AddModule,
    ChipAdmitted,
    ChipAnnounce,
    ChipLost,
    ChipStatus,
    InterconnectStatus,
    MachineStatus,
    SetChipMode,
    SetFocus,
    SetInterconnect,
)
from catsim.machine import SchedulerService, load_machine_config
from tests.conftest import REPO_ROOT, ListSink

MACHINE_DIR = REPO_ROOT / "configs" / "machine"


def _scheduler(sink: ListSink) -> SchedulerService:
    return SchedulerService(sink, load_machine_config("chip-256", MACHINE_DIR))


def _announce(scheduler: SchedulerService, n: int, start: int = 0) -> None:
    for i in range(start, start + n):
        scheduler.handle(
            ChipAnnounce(source=f"inst-{i}", nominal_qubits=256, modes=["behavioral", "live"])
        )


def _admissions(sink: ListSink) -> list[ChipAdmitted]:
    return [e for e in sink.events if isinstance(e, ChipAdmitted)]


def test_first_chip_gets_memory_role_and_the_live_focus(list_sink: ListSink) -> None:
    scheduler = _scheduler(list_sink)
    _announce(scheduler, 1)
    admitted = _admissions(list_sink)[0]
    assert admitted.chip_id == "chip0"
    assert admitted.role == "memory"
    assert admitted.mode == "live"
    assert admitted.blocks[0].code == "q70"
    assert scheduler.focus == "chip0"


def test_later_chips_join_behavioral(list_sink: ListSink) -> None:
    scheduler = _scheduler(list_sink)
    _announce(scheduler, 3)
    modes = [a.mode for a in _admissions(list_sink) if a.t_backlog == 0]
    assert modes[0] == "live"
    assert all(m == "behavioral" for m in modes[1:])


def test_reannounce_is_idempotent(list_sink: ListSink) -> None:
    scheduler = _scheduler(list_sink)
    _announce(scheduler, 1)
    scheduler.handle(ChipAnnounce(source="inst-0", nominal_qubits=256))
    admissions = _admissions(list_sink)
    assert {a.chip_id for a in admissions} == {"chip0"}
    assert len(scheduler.chips) == 1


def test_fleet_of_40_balances_roles_per_table_i(list_sink: ListSink) -> None:
    scheduler = _scheduler(list_sink)
    _announce(scheduler, 40)
    roles = [c.role for c in scheduler.chips.values()]
    assert roles.count("memory") == 38
    assert roles.count("factory") == 2
    # Factory chips split the fleet's T demand evenly.
    latest: dict[str, ChipAdmitted] = {a.chip_id: a for a in _admissions(list_sink)}
    factory_demands = [
        latest[c.chip_id].t_demand_per_second
        for c in scheduler.chips.values()
        if c.role == "factory"
    ]
    assert all(abs(d - 6.0) < 1e-9 for d in factory_demands)  # 12 T/s over 2


def test_pre_factory_backlog_is_handed_to_the_first_factory(list_sink: ListSink) -> None:
    scheduler = _scheduler(list_sink)
    _announce(scheduler, 1)
    # The lone memory chip reports machine time: unserved demand accrues.
    scheduler.handle(
        ChipStatus(
            source="chip0",
            chip_id="chip0",
            state="ok",
            blocks=[],
            factories=[],
            utilization=1.0,
            machine_seconds=100.0,
        )
    )
    scheduler.publish_status()
    roll_up = [e for e in list_sink.events if isinstance(e, MachineStatus)][-1]
    assert roll_up.t_queue_depth == 1200  # 12 T/s x 100 machine-seconds
    _announce(scheduler, 17, start=1)  # grow to 18: chip17 becomes the first factory
    factory_admissions = [a for a in _admissions(list_sink) if a.role == "factory"]
    assert sum(a.t_backlog for a in factory_admissions) == 1200


def test_missed_heartbeats_lose_the_chip_and_refocus(list_sink: ListSink) -> None:
    scheduler = _scheduler(list_sink)
    _announce(scheduler, 2)
    scheduler.chips["chip0"].last_seen = time.monotonic() - 60.0
    scheduler.tick(time.monotonic())
    lost = [e for e in list_sink.events if isinstance(e, ChipLost)]
    assert [e.chip_id for e in lost] == ["chip0"]
    assert "chip0" not in scheduler.chips
    assert scheduler.focus == "chip1"  # the drill-down moved to a survivor
    mode_cmds = [e for e in list_sink.events if isinstance(e, SetChipMode)]
    assert mode_cmds[-1].target == "chip1"
    assert mode_cmds[-1].mode == "live"
    roll_up = [e for e in list_sink.events if isinstance(e, MachineStatus)][-1]
    assert roll_up.chips == 1
    assert roll_up.lost_chips == 1


def test_live_chip_gets_heartbeat_leniency_for_decode_tails(list_sink: ListSink) -> None:
    scheduler = _scheduler(list_sink)
    _announce(scheduler, 2)  # chip0 live (focus), chip1 behavioral
    now = time.monotonic()
    # Silent for 2x the timeout: within the live chip's 4x allowance, but past
    # a behavioral chip's plain deadline (BP+OSD tail decodes stall the live
    # chip's process for whole seconds — that must not read as death).
    scheduler.chips["chip0"].last_seen = now - 10.0
    scheduler.chips["chip1"].last_seen = now - 10.0
    scheduler.tick(now)
    lost = [e.chip_id for e in list_sink.events if isinstance(e, ChipLost)]
    assert lost == ["chip1"]
    assert "chip0" in scheduler.chips


def test_lost_factory_chip_hands_its_queue_to_survivors(list_sink: ListSink) -> None:
    scheduler = _scheduler(list_sink)
    _announce(scheduler, 36)  # two factory chips: chip17 and chip35
    factories = [c.chip_id for c in scheduler.chips.values() if c.role == "factory"]
    dead, survivor = factories[0], factories[1]
    scheduler.handle(
        ChipStatus(
            source=dead,
            chip_id=dead,
            state="ok",
            role="factory",
            blocks=[],
            factories=[],
            utilization=1.0,
            machine_seconds=50.0,
            t_queue_depth=77,
        )
    )
    scheduler.chips[dead].last_seen = time.monotonic() - 60.0
    scheduler.tick(time.monotonic())
    assert dead not in scheduler.chips
    handed = [a for a in _admissions(list_sink) if a.chip_id == survivor and a.t_backlog]
    assert handed and handed[-1].t_backlog == 77
    assert handed[-1].t_demand_per_second == 12.0  # sole factory takes it all


def test_set_focus_flips_modes(list_sink: ListSink) -> None:
    scheduler = _scheduler(list_sink)
    _announce(scheduler, 3)
    scheduler.handle(SetFocus(source="dash", target="scheduler", chip_id="chip2"))
    mode_cmds = [e for e in list_sink.events if isinstance(e, SetChipMode)]
    assert [(c.target, c.mode) for c in mode_cmds[-2:]] == [
        ("chip0", "behavioral"),
        ("chip2", "live"),
    ]
    assert scheduler.focus == "chip2"


def _report_time(scheduler: SchedulerService, chip_id: str, machine_seconds: float) -> None:
    """Feed the scheduler one chip status carrying only the machine clock."""
    chip = scheduler.chips[chip_id]
    scheduler.handle(
        ChipStatus(
            source=chip_id,
            chip_id=chip_id,
            state="ok",
            role=chip.role,  # type: ignore[arg-type]
            module=chip.module,
            blocks=[],
            factories=[],
            utilization=1.0,
            machine_seconds=machine_seconds,
        )
    )


def test_module_a_fills_to_capacity_then_b_opens(list_sink: ListSink) -> None:
    scheduler = _scheduler(list_sink)
    _announce(scheduler, 41)  # one past the configured capacity of 40
    modules = [c.module for c in scheduler.chips.values()]
    assert modules.count("A") == 40
    assert modules.count("B") == 1
    assert scheduler.modules == ["A", "B"]
    admissions = {a.chip_id: a for a in _admissions(list_sink)}
    assert admissions["chip40"].module == "B"
    assert admissions["chip40"].bell_neighbors == []  # no transport link across modules


def test_add_module_opens_b_before_a_is_full(list_sink: ListSink) -> None:
    scheduler = _scheduler(list_sink)
    _announce(scheduler, 3)
    scheduler.handle(AddModule(source="dash", target="scheduler"))
    _announce(scheduler, 1, start=3)
    assert scheduler.modules == ["A", "B"]
    assert scheduler.chips["chip3"].module == "B"


def test_roles_balance_per_module_at_80_chips(list_sink: ListSink) -> None:
    scheduler = _scheduler(list_sink)
    _announce(scheduler, 80)  # two full modules
    for module in ("A", "B"):
        members = [c for c in scheduler.chips.values() if c.module == module]
        assert len(members) == 40
        assert sum(1 for c in members if c.role == "factory") == 2
    # Each factory serves its own module's local demand: 12 x 0.5 share
    # x 0.75 local fraction / 2 factories = 2.25 T/s.
    latest = {a.chip_id: a for a in _admissions(list_sink)}
    for chip in scheduler.chips.values():
        if chip.role == "factory":
            assert abs(latest[chip.chip_id].t_demand_per_second - 2.25) < 1e-9


def test_interconnect_status_appears_with_the_second_module(list_sink: ListSink) -> None:
    scheduler = _scheduler(list_sink)
    _announce(scheduler, 40)
    scheduler.publish_status()
    assert not any(isinstance(e, InterconnectStatus) for e in list_sink.events)
    _announce(scheduler, 40, start=40)
    scheduler.publish_status()
    status = [e for e in list_sink.events if isinstance(e, InterconnectStatus)][-1]
    assert status.modules == 2
    assert status.pair_rate_hz == 100.0  # the ASSUMED config value, echoed
    assert not status.severed
    roll_up = [e for e in list_sink.events if isinstance(e, MachineStatus)][-1]
    assert roll_up.modules == 2


def test_cross_module_gates_ride_the_bank_and_reach_factories(list_sink: ListSink) -> None:
    scheduler = _scheduler(list_sink)
    _announce(scheduler, 80)
    _report_time(scheduler, "chip0", 10.0)  # 10 machine-seconds elapse
    scheduler.publish_status()
    status = [e for e in list_sink.events if isinstance(e, InterconnectStatus)][-1]
    assert status.cross_demand_per_second == 3.0  # 12 T/s x 0.25 assumed
    assert status.cross_t_served == 30
    assert status.cross_queue_depth == 0
    handed = [a.t_backlog for a in _admissions(list_sink) if a.t_backlog]
    assert sum(handed) == 30  # served cross gates handed to factories as backlog


def test_severed_link_drains_the_bank_then_queues_cross_ops(list_sink: ListSink) -> None:
    scheduler = _scheduler(list_sink)
    _announce(scheduler, 80)
    _report_time(scheduler, "chip0", 10.0)
    scheduler.publish_status()  # bank full at 60
    scheduler.handle(SetInterconnect(source="dash", target="scheduler", severed=True))
    assert [e for e in list_sink.events if isinstance(e, InterconnectStatus)][-1].severed
    _report_time(scheduler, "chip0", 50.0)  # 40 severed machine-seconds
    scheduler.publish_status()
    status = [e for e in list_sink.events if isinstance(e, InterconnectStatus)][-1]
    assert status.bank == 0  # 60 banked - 120 demanded
    assert status.cross_queue_depth == 60
    scheduler.handle(SetInterconnect(source="dash", target="scheduler", severed=False))
    _report_time(scheduler, "chip0", 52.0)  # 200 pairs herald back
    scheduler.publish_status()
    status = [e for e in list_sink.events if isinstance(e, InterconnectStatus)][-1]
    assert status.cross_queue_depth == 0
    assert status.bank == 60


def test_roll_up_aggregates_prediction_and_measurement(list_sink: ListSink) -> None:
    scheduler = _scheduler(list_sink)
    _announce(scheduler, 18)  # 17 memory + 1 factory
    for chip_id in list(scheduler.chips):
        role = scheduler.chips[chip_id].role
        scheduler.handle(
            ChipStatus(
                source=chip_id,
                chip_id=chip_id,
                state="ok",
                role=role,  # type: ignore[arg-type]
                blocks=[],
                factories=[],
                utilization=1.0,
                machine_seconds=100.0,
                t_done=1000 if role == "factory" else 0,
            )
        )
    scheduler.publish_status()
    roll_up = [e for e in list_sink.events if isinstance(e, MachineStatus)][-1]
    assert roll_up.chips == 18
    assert roll_up.logical_qubits == 17 * 6
    assert roll_up.physical_qubits_nominal == 18 * 256
    # 17 x (220+42) + 173 CH2 + 200 shared reservoir (Table V)
    assert roll_up.physical_qubits_paper == 17 * 262 + 173 + 200
    assert roll_up.predicted_t_per_day > 1_000_000  # one CH2 ≈ 1.15M T/day
    assert roll_up.measured_t_per_day == 1000 / 100.0 * 86_400
    assert roll_up.t_stall_reason.startswith("demand-limited")
