"""Layer 1 — stabilizer component simulators (memory blocks, factories).

Exists to run each organ as a continuously ticking stim process that streams
physical events onto the bus, with a batch (sinter) mode reusing the builders.
"""

from catsim.component.batch import (
    CurveCell,
    code_curve_tasks,
    curve_tasks,
    run_curve,
    write_curve_csv,
)
from catsim.component.block import MemoryBlockService, MemoryBlockSpec
from catsim.component.circuits import (
    RoundSegments,
    build_memory_circuit,
    memory_detector_error_model,
    register_builder,
    split_into_rounds,
)
from catsim.component.css import build_css_memory
from catsim.component.factories import (
    build_bell_factory,
    build_cat_factory,
    build_magic_factory,
)
from catsim.component.factory import (
    FactoryCircuit,
    FactoryService,
    FactorySpec,
    available_factories,
    build_factory_circuit,
    register_factory,
)
from catsim.component.geometry import BlockLayout, block_layout
from catsim.component.loss import LossRoundEffects, LossTracker
from catsim.component.noise import DepolarizingNoise, NoiseModel, load_noise_model
from catsim.component.qubit_factory import QubitFactoryService
from catsim.component.report import plot_curve, plot_rate_curve

__all__ = [
    "BlockLayout",
    "CurveCell",
    "DepolarizingNoise",
    "FactoryCircuit",
    "FactoryService",
    "FactorySpec",
    "LossRoundEffects",
    "LossTracker",
    "MemoryBlockService",
    "MemoryBlockSpec",
    "NoiseModel",
    "QubitFactoryService",
    "RoundSegments",
    "available_factories",
    "block_layout",
    "build_bell_factory",
    "build_cat_factory",
    "build_css_memory",
    "build_factory_circuit",
    "build_magic_factory",
    "build_memory_circuit",
    "code_curve_tasks",
    "curve_tasks",
    "load_noise_model",
    "memory_detector_error_model",
    "plot_curve",
    "plot_rate_curve",
    "register_builder",
    "register_factory",
    "run_curve",
    "split_into_rounds",
    "write_curve_csv",
]
