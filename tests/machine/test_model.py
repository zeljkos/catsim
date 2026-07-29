"""SimPy machine-model dynamics: steady state, outage, recovery, T queue."""

from catsim.machine import MachineModel, load_machine_config
from catsim.machine.config import (
    BlockComposition,
    ChipComposition,
    MachineConfig,
    WorkloadConfig,
)
from tests.conftest import REPO_ROOT

MACHINE_DIR = REPO_ROOT / "configs" / "machine"


def _chip_256() -> MachineModel:
    return MachineModel(load_machine_config("chip-256", MACHINE_DIR), seed=1)


def test_steady_state_never_stalls() -> None:
    model = _chip_256()
    model.step(60.0)  # 10,000 SECs
    snap = model.snapshot()
    block = snap.blocks[0]
    assert block.rounds > 9_000
    assert block.stalled_rounds == 0
    assert block.state == "ok"
    assert block.cat_buffer > 0


def test_memory_only_machine_queues_t_gates_without_serving_them() -> None:
    model = _chip_256()
    model.step(60.0)
    snap = model.snapshot()
    assert snap.t_done == 0
    # ~12 T/s demand accumulates unserved
    assert 600 < snap.t_queue_depth < 800
    assert snap.t_per_day == 0.0


def test_cat_outage_stalls_block_and_recovery_refills() -> None:
    model = _chip_256()
    model.step(1.0)
    model.set_factory_paused("cat0", True)
    model.step(1.0)  # ~166 SECs: buffer (24) drains, then stalls accumulate
    stalled = model.snapshot()
    assert stalled.blocks[0].cat_buffer == 0
    assert stalled.blocks[0].stalled_rounds > 50
    assert stalled.blocks[0].state == "stalled"
    assert stalled.factories[0].state == "down"
    model.set_factory_paused("cat0", False)
    model.step(1.0)  # production 2 attempts/SEC vs 1 consumed: refills
    recovered = model.snapshot()
    assert recovered.blocks[0].state == "ok"
    assert recovered.blocks[0].cat_buffer > 20
    assert recovered.blocks[0].stalled_rounds == stalled.blocks[0].stalled_rounds


def test_roadmap_chip_runs_two_blocks_with_own_cat_units() -> None:
    model = MachineModel(load_machine_config("chip-256-roadmap", MACHINE_DIR), seed=1)
    model.step(6.0)
    snap = model.snapshot()
    assert [b.block_id for b in snap.blocks] == ["block0", "block1"]
    assert [f.source for f in snap.factories] == ["cat0", "cat1"]
    assert all(b.stalled_rounds == 0 for b in snap.blocks)
    model.set_factory_paused("cat1", True)
    model.step(1.0)
    snap = model.snapshot()
    assert snap.blocks[0].state == "ok"  # block0's supply is untouched
    assert snap.blocks[1].state == "stalled"


def test_ch2_factory_serves_t_queue_at_predicted_rate() -> None:
    config = MachineConfig(
        name="factory-test",
        chip=ChipComposition(
            nominal_qubits=256,
            blocks=[BlockComposition(family="bb", code="q70")],
            magic_factories=["ch2"],
        ),
        workload=WorkloadConfig(t_per_second=12.0),
    )
    model = MachineModel(config, seed=1)
    model.step(600.0)
    snap = model.snapshot()
    # CH2 serves 2 T per 0.1507 s ≈ 13.3/s > 12/s demand: queue stays bounded
    assert snap.t_queue_depth < 50
    assert abs(snap.t_per_day - 12.0 * 86_400) / (12.0 * 86_400) < 0.05


def test_measured_acceptance_calibration_reaches_production() -> None:
    model = _chip_256()
    model.set_cat_acceptance("cat0", 0.25)  # collapsed factory (100x-noise regime)
    model.step(60.0)
    snap = model.snapshot()
    # 2 attempts/SEC x 0.25 acceptance = 0.5 produced vs 1 consumed: starves
    assert snap.blocks[0].stalled_rounds > 1_000
