"""Layer 3 — discrete-event model of the full tiled machine (SimPy + ZeroMQ).

Exists to model chips, factories, Bell links, and the scheduler as an elastic
runtime: the machine is whatever chips are currently registered on the bus.
"""

from catsim.machine.backend import MachineBackend
from catsim.machine.calibration import Calibration
from catsim.machine.config import (
    MachineConfig,
    available_machines,
    load_machine_config,
)
from catsim.machine.live import LiveBackend
from catsim.machine.model import MachineModel, MachineSnapshot
from catsim.machine.prediction import MachinePrediction, predict_machine
from catsim.machine.pricing import ChipBill, price_chip
from catsim.machine.report import (
    PredictedVsMeasured,
    collect_predicted_vs_measured,
    write_pvm_csv,
)
from catsim.machine.runner import DemoReport, run_memory_demo
from catsim.machine.service import MachineService

__all__ = [
    "Calibration",
    "ChipBill",
    "DemoReport",
    "LiveBackend",
    "MachineBackend",
    "MachineConfig",
    "MachineModel",
    "MachinePrediction",
    "MachineService",
    "MachineSnapshot",
    "PredictedVsMeasured",
    "available_machines",
    "collect_predicted_vs_measured",
    "load_machine_config",
    "predict_machine",
    "price_chip",
    "run_memory_demo",
    "write_pvm_csv",
]
