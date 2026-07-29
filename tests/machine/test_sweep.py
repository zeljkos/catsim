"""Scaling sweep: fleet plan arithmetic, prediction points, link sweep, CSVs."""

from pathlib import Path

from catsim.machine import (
    MachineConfig,
    load_machine_config,
    plan_fleet,
    plot_scaling,
    predict_point,
    sweep_interconnect,
    write_interconnect_csv,
    write_scaling_csv,
)
from tests.conftest import REPO_ROOT

MACHINE_DIR = REPO_ROOT / "configs" / "machine"


def _unit() -> MachineConfig:
    return load_machine_config("chip-256", MACHINE_DIR)


def test_plan_fleet_matches_the_scheduler_policy() -> None:
    assert plan_fleet(1) == plan_fleet(1, capacity=40)
    one = plan_fleet(1)
    assert (one.modules, one.memory_chips, one.factory_chips) == (1, 1, 0)
    forty = plan_fleet(40)
    assert (forty.modules, forty.memory_chips, forty.factory_chips) == (1, 38, 2)
    eighty = plan_fleet(80)
    assert (eighty.modules, eighty.memory_chips, eighty.factory_chips) == (2, 76, 4)


def test_predict_point_prices_the_balanced_fleet() -> None:
    point = predict_point(_unit(), 80)
    assert point.modules == 2
    assert point.predicted_logical == 76 * 6
    # 76 x (220 + 42) + 4 x 173 CH2 + 200 shared reservoir (Table V)
    assert point.predicted_physical_paper == 76 * 262 + 4 * 173 + 200
    assert point.physical_nominal == 80 * 256
    assert point.predicted_t_per_day > 4_000_000  # 4 CH2 ≈ 4.6M capacity
    assert not point.measured


def test_interconnect_sweep_finds_the_link_limited_regime() -> None:
    points = sweep_interconnect(_unit(), [1.0, 100.0])
    slow, fast = points
    assert slow.cross_demand_per_second == 3.0  # 12 T/s x 0.25 assumed fraction
    assert slow.link_limited  # 1 pair/s cannot carry 3 gates/s
    assert abs(slow.served_per_second - 1.0) < 0.05
    assert not fast.link_limited
    assert abs(fast.served_per_second - 3.0) < 0.05


def test_csv_and_png_artifacts_land(tmp_path: Path) -> None:
    unit = _unit()
    points = [predict_point(unit, n) for n in (1, 40, 80)]
    link = sweep_interconnect(unit, [1.0, 100.0])
    write_scaling_csv(points, tmp_path / "m7_scaling.csv")
    write_interconnect_csv(link, tmp_path / "m7_interconnect.csv")
    plot_scaling(points, link, tmp_path / "m7_scaling.png")
    header = (tmp_path / "m7_scaling.csv").read_text().splitlines()[0]
    assert header.startswith("n_chips,modules,memory_chips,factory_chips,predicted_logical")
    assert "ASSUMED" not in header  # data columns; the marking lives in config/plot
    assert (tmp_path / "m7_scaling.png").stat().st_size > 10_000
    link_header = (tmp_path / "m7_interconnect.csv").read_text().splitlines()[0]
    assert link_header.startswith("pair_rate_hz,cross_demand_per_second")
