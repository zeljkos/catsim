"""M7 scaling sweep: predicted vs measured, 1 → ~80 chips, plus link sensitivity.

Exists so the M7 report comes from one callable, testable path: the prediction
side is the paper's Table I/V/VII arithmetic evaluated over the same
per-module role plan the live scheduler uses; the measured side is a REAL
elastic fleet (processes through the join protocol) read back off the bus; the
interconnect sensitivity is the same pair-bank model the scheduler runs, swept
over pair rates around the ASSUMED ~10^2 pairs/s literature figure. Divergence
— including from the roadmap markers — is reported, never tuned away.
"""

from __future__ import annotations

import csv
import threading
import time
from dataclasses import dataclass, fields, replace
from pathlib import Path

from catsim.bus import InterconnectStatus, MachineStatus, ZmqSubscriber
from catsim.machine.config import MachineConfig
from catsim.machine.fleet import FleetBackend
from catsim.machine.interconnect import InterconnectModel
from catsim.machine.prediction import predict_machine
from catsim.machine.pricing import MEMORY_BLOCK_LOGICAL
from catsim.machine.roles import next_role

ROADMAP_MARKERS = [(1, 256, 12), (40, 10_000, 800), (80, 20_000, 1_600)]
"""ionq.com/roadmap tiers as (chips, physical, logical) — markers to compare
against, never targets to tune toward."""

RECONCILIATION_NOTE = (
    "roadmap markers assume ~12.5:1 physical:logical at target logical error 1e-7;\n"
    "the prediction line prices Q70 blocks at paper Table V rates (~21:1, toward 1e-10) —\n"
    "more logical qubits are available at a higher target error rate (reliability costs qubits)"
)


@dataclass(frozen=True)
class FleetPlan:
    """The role mix the scheduler's per-module policy gives a fleet of N."""

    modules: int
    memory_chips: int
    factory_chips: int


def plan_fleet(n: int, capacity: int = 40, blocks_per_chip: int = 1) -> FleetPlan:
    """Replay the scheduler's admission policy for N chips, arithmetic only.

    Chips join the newest module until it hits ``capacity``; each module keeps
    its own Table I role mix (M7 locality: a factory serves its own module).
    """
    per_module: list[dict[str, int]] = []
    for _ in range(n):
        if not per_module or sum(per_module[-1].values()) >= capacity:
            per_module.append({"memory": 0, "factory": 0})
        module = per_module[-1]
        module[next_role(module["memory"], module["factory"], blocks_per_chip)] += 1
    return FleetPlan(
        modules=max(1, len(per_module)),
        memory_chips=sum(m["memory"] for m in per_module),
        factory_chips=sum(m["factory"] for m in per_module),
    )


@dataclass(frozen=True)
class ScalingPoint:
    """One fleet size: the paper's promise next to what the live fleet did."""

    n_chips: int
    modules: int
    memory_chips: int
    factory_chips: int
    predicted_logical: int
    predicted_physical_paper: int
    physical_nominal: int
    predicted_t_per_day: float
    demand_t_per_day: float
    measured: bool = False
    measured_t_per_day: float = 0.0
    measured_machine_seconds: float = 0.0
    t_queue_depth: int = 0
    cross_t_served: int = 0
    cross_queue_depth: int = 0
    logical_error_per_logical_per_shot: float = 0.0


def predict_point(unit: MachineConfig, n: int) -> ScalingPoint:
    """Table I/V/VII arithmetic for a fleet of N unit chips, role-balanced."""
    plan = plan_fleet(n, unit.module.capacity_chips, len(unit.chip.blocks) or 1)
    codes = [b.code for b in unit.chip.blocks] * plan.memory_chips
    prediction = predict_machine(
        codes, [MEMORY_BLOCK_LOGICAL[c] for c in codes], ["ch2"] * plan.factory_chips
    )
    return ScalingPoint(
        n_chips=n,
        modules=plan.modules,
        memory_chips=plan.memory_chips,
        factory_chips=plan.factory_chips,
        predicted_logical=prediction.logical_qubits,
        predicted_physical_paper=prediction.physical_qubits,
        physical_nominal=n * unit.chip.nominal_qubits,
        predicted_t_per_day=prediction.t_per_day,
        demand_t_per_day=unit.workload.t_per_second * 86_400.0,
    )


class _LatestStatus:
    """Bus tap keeping the newest machine and interconnect roll-ups."""

    def __init__(self, address: str) -> None:
        self._sub = ZmqSubscriber(address)
        self.machine: MachineStatus | None = None
        self.interconnect: InterconnectStatus | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            event = self._sub.receive(timeout_s=0.05)
            if isinstance(event, MachineStatus):
                self.machine = event
            elif isinstance(event, InterconnectStatus):
                self.interconnect = event

    def close(self) -> None:
        """Stop the tap and release its socket."""
        self._stop.set()
        self._thread.join(timeout=5.0)
        self._sub.close()


def measure_point(
    unit: MachineConfig,
    n: int,
    *,
    wall_seconds: float = 12.0,
    behavioral_rate: float = 20.0,
    noise_name: str = "paper-baseline",
    pace_ms: float = 500.0,
    settle_timeout_s: float = 120.0,
) -> ScalingPoint:
    """Boot a REAL fleet of N chip processes, let it run, read the roll-up back.

    The fleet assembles through the same join protocol the on-stage growth
    uses; measurements are taken from the bus, not from internal state.
    """
    point = predict_point(unit, n)
    backend = FleetBackend(
        unit,
        chips=n,
        noise_name=noise_name,
        tick_seconds=pace_ms / 1000.0,
        behavioral_rate=behavioral_rate,
    )
    tap: _LatestStatus | None = None
    try:
        backend.start()
        tap = _LatestStatus(backend.backend_address)
        deadline = time.monotonic() + settle_timeout_s
        while len(backend.scheduler.chips) < n and time.monotonic() < deadline:
            time.sleep(0.2)
        registered = len(backend.scheduler.chips)
        if registered < n:
            raise TimeoutError(f"only {registered}/{n} chips registered in {settle_timeout_s:g}s")
        time.sleep(wall_seconds)
        machine, link = tap.machine, tap.interconnect
    finally:
        if tap is not None:
            tap.close()
        backend.stop()
    if machine is None:
        raise TimeoutError(f"no machine_status observed from the {n}-chip fleet")
    return replace(
        point,
        measured=True,
        measured_t_per_day=machine.measured_t_per_day,
        measured_machine_seconds=machine.machine_seconds,
        t_queue_depth=machine.t_queue_depth,
        cross_t_served=link.cross_t_served if link else 0,
        cross_queue_depth=link.cross_queue_depth if link else 0,
        logical_error_per_logical_per_shot=machine.logical_error_per_logical_per_shot,
    )


@dataclass(frozen=True)
class InterconnectPoint:
    """One pair-rate setting: what the bank model serves at fixed cross demand."""

    pair_rate_hz: float
    cross_demand_per_second: float
    served_per_second: float
    final_queue_depth: int
    link_limited: bool


def sweep_interconnect(
    unit: MachineConfig,
    rates: list[float],
    *,
    cross_demand_per_s: float | None = None,
    machine_seconds: float = 300.0,
) -> list[InterconnectPoint]:
    """Sweep the (assumed) heralded pair rate through the scheduler's own model.

    ``cross_demand_per_s`` defaults to the two-module steady state: the fleet
    demand times the assumed cross-module fraction.
    """
    demand = (
        unit.workload.t_per_second * unit.workload.cross_module_fraction
        if cross_demand_per_s is None
        else cross_demand_per_s
    )
    points = []
    for rate in rates:
        model = InterconnectModel(unit.interconnect.model_copy(update={"pair_rate_hz": rate}))
        for _ in range(int(machine_seconds)):  # 1 s steps: the scheduler's own cadence
            model.advance(1.0, demand, active=True)
        points.append(
            InterconnectPoint(
                pair_rate_hz=rate,
                cross_demand_per_second=demand,
                served_per_second=model.cross_served / machine_seconds,
                final_queue_depth=int(model.cross_queue),
                link_limited=model.cross_queue >= 1.0,
            )
        )
    return points


def write_scaling_csv(points: list[ScalingPoint], path: Path) -> None:
    """One row per fleet size: prediction columns plus measured overlay."""
    path.parent.mkdir(parents=True, exist_ok=True)
    names = [f.name for f in fields(ScalingPoint)]
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(names)
        writer.writerows([getattr(p, name) for name in names] for p in points)


def write_interconnect_csv(points: list[InterconnectPoint], path: Path) -> None:
    """One row per swept pair rate (all rates ASSUMED — none from the paper)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    names = [f.name for f in fields(InterconnectPoint)]
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(names)
        writer.writerows([getattr(p, name) for name in names] for p in points)
