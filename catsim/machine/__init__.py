"""Layer 3 — discrete-event model of the full tiled machine (SimPy + ZeroMQ).

Exists to model chips, factories, Bell links, and the scheduler as an elastic
runtime: the machine is whatever chips are currently registered on the bus.
"""

from catsim.machine.backend import MachineBackend
from catsim.machine.calibration import Calibration
from catsim.machine.chip import ChipRuntime
from catsim.machine.config import (
    InterconnectConfig,
    MachineConfig,
    available_machines,
    load_machine_config,
)
from catsim.machine.fleet import FleetBackend
from catsim.machine.interconnect import InterconnectModel
from catsim.machine.ledger import FleetLedger
from catsim.machine.live import LiveBackend
from catsim.machine.model import MachineModel, MachineSnapshot
from catsim.machine.node import (
    DEFAULT_BACKEND,
    DEFAULT_FRONTEND,
    run_chip,
    run_provisioner,
    run_scheduler,
)
from catsim.machine.prediction import MachinePrediction, predict_machine
from catsim.machine.pricing import ChipBill, price_chip
from catsim.machine.provisioner import (
    DockerSpawner,
    ProcessSpawner,
    ProvisionerService,
    Spawner,
)
from catsim.machine.report import (
    PredictedVsMeasured,
    collect_predicted_vs_measured,
    write_pvm_csv,
)
from catsim.machine.roles import desired_factories, module_name, next_role, split_demand
from catsim.machine.runner import DemoReport, run_memory_demo
from catsim.machine.scheduler import SchedulerService
from catsim.machine.service import MachineService
from catsim.machine.sweep import (
    InterconnectPoint,
    ScalingPoint,
    measure_point,
    plan_fleet,
    predict_point,
    sweep_interconnect,
    write_interconnect_csv,
    write_scaling_csv,
)
from catsim.machine.sweep_plot import plot_scaling

__all__ = [
    "DEFAULT_BACKEND",
    "DEFAULT_FRONTEND",
    "Calibration",
    "ChipBill",
    "ChipRuntime",
    "DemoReport",
    "DockerSpawner",
    "FleetBackend",
    "FleetLedger",
    "InterconnectConfig",
    "InterconnectModel",
    "InterconnectPoint",
    "LiveBackend",
    "MachineBackend",
    "MachineConfig",
    "MachineModel",
    "MachinePrediction",
    "MachineService",
    "MachineSnapshot",
    "PredictedVsMeasured",
    "ProcessSpawner",
    "ProvisionerService",
    "ScalingPoint",
    "SchedulerService",
    "Spawner",
    "available_machines",
    "collect_predicted_vs_measured",
    "desired_factories",
    "load_machine_config",
    "measure_point",
    "module_name",
    "next_role",
    "plan_fleet",
    "plot_scaling",
    "predict_machine",
    "predict_point",
    "split_demand",
    "sweep_interconnect",
    "write_interconnect_csv",
    "price_chip",
    "run_chip",
    "run_memory_demo",
    "run_provisioner",
    "run_scheduler",
    "write_pvm_csv",
    "write_scaling_csv",
]
