"""Layer 1 — stabilizer component simulators (memory blocks, factories).

Exists to run each organ as a continuously ticking stim process that streams
physical events onto the bus, with a batch (sinter) mode reusing the builders.
"""

from catsim.component.batch import CurveCell, curve_tasks, run_curve, write_curve_csv
from catsim.component.block import MemoryBlockService, MemoryBlockSpec
from catsim.component.circuits import (
    RoundSegments,
    build_memory_circuit,
    register_builder,
    split_into_rounds,
)
from catsim.component.geometry import BlockLayout, block_layout
from catsim.component.noise import DepolarizingNoise, NoiseModel, load_noise_model
from catsim.component.report import plot_curve

__all__ = [
    "BlockLayout",
    "CurveCell",
    "DepolarizingNoise",
    "MemoryBlockService",
    "MemoryBlockSpec",
    "NoiseModel",
    "RoundSegments",
    "block_layout",
    "build_memory_circuit",
    "curve_tasks",
    "load_noise_model",
    "plot_curve",
    "register_builder",
    "run_curve",
    "split_into_rounds",
    "write_curve_csv",
]
