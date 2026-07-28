"""Layer 3 — discrete-event model of the full tiled machine (SimPy + ZeroMQ).

Exists to model chips, factories, Bell links, and the scheduler as an elastic
runtime: the machine is whatever chips are currently registered on the bus.
"""

from catsim.machine.live import LiveBackend
from catsim.machine.runner import DemoReport, run_memory_demo

__all__ = ["DemoReport", "LiveBackend", "run_memory_demo"]
