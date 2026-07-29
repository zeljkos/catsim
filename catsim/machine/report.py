"""Predicted-vs-measured for a machine config: paper arithmetic against live runs.

Exists so the M5 acceptance numbers (and later the M7 report) come from one
callable, testable path: the prediction side is Table I/V/VII arithmetic, the
measured side is a standalone model run plus a real stim block + decoder run
over the bus. Divergence is reported, never tuned away.
"""

from __future__ import annotations

import csv
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from catsim.bus import AnyEvent, DecodeFinished, LogicalError
from catsim.component import MemoryBlockService, MemoryBlockSpec, NoiseModel, build_block_spec
from catsim.decoder import DecoderService, default_decoder
from catsim.machine.config import MachineConfig
from catsim.machine.model import MachineModel
from catsim.machine.prediction import MachinePrediction, predict_machine
from catsim.machine.pricing import MEMORY_BLOCK_LOGICAL


@dataclass(frozen=True)
class PredictedVsMeasured:
    """One machine's paper prediction next to its measured behavior."""

    machine_name: str
    prediction: MachinePrediction
    nominal_qubits: int
    # model run (machine time)
    machine_seconds: float
    utilization: float
    stalled_rounds: int
    t_queue_depth: int
    measured_t_per_day: float
    # hero-block stim run (real decoder in the loop)
    shots: int
    rounds_per_shot: int
    block_logical: int
    logical_errors: int
    decodes: int
    mean_decode_latency_s: float

    @property
    def logical_error_per_logical_per_shot(self) -> float:
        """Measured logical error rate per logical qubit per memory shot."""
        return self.logical_errors / (self.shots * self.block_logical)

    @property
    def logical_error_bound(self) -> float:
        """When zero errors were seen, the resolution limit of this run."""
        return 1.0 / (self.shots * self.block_logical)


def collect_predicted_vs_measured(
    config: MachineConfig,
    noise: NoiseModel,
    *,
    machine_seconds: float = 600.0,
    shots: int = 50,
    rounds: int = 10,
    seed: int = 0,
) -> PredictedVsMeasured:
    """Run the model (fast-forward) and the hero block (real), collect both sides.

    Args:
        config: The machine instance to evaluate.
        noise: Noise model for the real block run.
        machine_seconds: How much machine time the standalone model simulates.
        shots: Memory shots for the real block + decoder run.
        rounds: SE rounds per shot.
        seed: Reproducibility seed for both runs.

    Returns:
        The paired numbers, ready for the CSV/stat table.
    """
    chip = config.chip
    codes = [b.code for b in chip.blocks] * config.chips
    prediction = predict_machine(
        codes,
        [MEMORY_BLOCK_LOGICAL[c] for c in codes],
        list(chip.magic_factories) * config.chips,
    )
    model = MachineModel(config, seed=seed)
    model.step(machine_seconds)
    snapshot = model.snapshot()
    rounds_done = sum(b.rounds for b in snapshot.blocks)
    stalled = sum(b.stalled_rounds for b in snapshot.blocks)

    hero = chip.blocks[0]
    spec = build_block_spec(hero.family, hero.code, noise, rounds)
    errors, latencies = _measure_hero_block(
        spec, shots=shots, seed=seed, decoder_name=default_decoder(hero.family)
    )
    return PredictedVsMeasured(
        machine_name=config.name,
        prediction=prediction,
        nominal_qubits=config.chips * chip.nominal_qubits,
        machine_seconds=snapshot.seconds,
        utilization=rounds_done / (rounds_done + stalled) if rounds_done + stalled else 1.0,
        stalled_rounds=stalled,
        t_queue_depth=snapshot.t_queue_depth,
        measured_t_per_day=snapshot.t_per_day,
        shots=shots,
        rounds_per_shot=rounds,
        block_logical=MEMORY_BLOCK_LOGICAL[hero.code],
        logical_errors=errors,
        decodes=len(latencies),
        mean_decode_latency_s=sum(latencies) / len(latencies) if latencies else 0.0,
    )


class _InlineBus:
    """Synchronous in-process bus: records events, hands each to the decoder.

    Chosen over the ZMQ demo runner for measurement because BP+OSD's bimodal
    tail (M4 finding: seconds per OSD-0 fallback) can outlive that runner's
    fixed teardown timeouts and silently drop verdicts — here every decode
    completes inline before the run returns.
    """

    def __init__(self) -> None:
        self.events: list[AnyEvent] = []
        self.handlers: list[Callable[[AnyEvent], object]] = []

    def publish(self, event: AnyEvent) -> None:
        """Record and forward one event."""
        self.events.append(event)
        for handle in self.handlers:
            handle(event)


def _measure_hero_block(
    spec: MemoryBlockSpec, *, shots: int, seed: int, decoder_name: str
) -> tuple[int, list[float]]:
    """Run the hero block against a real decoder inline; count errors, time decodes."""
    bus = _InlineBus()
    block = MemoryBlockService(spec, bus, seed=seed)
    try:
        decoder = DecoderService(bus, decoder_name=decoder_name)
        bus.handlers.append(decoder.handle)
        block.configure()
        block.run(shots)
    finally:
        block.close()
    errors = sum(1 for e in bus.events if isinstance(e, LogicalError))
    latencies = [e.latency_s for e in bus.events if isinstance(e, DecodeFinished)]
    return errors, latencies


def write_pvm_csv(result: PredictedVsMeasured, path: Path) -> None:
    """Write the predicted-vs-measured rows as a two-column CSV artifact."""
    ler = (
        f"< {result.logical_error_bound:.3g} (0 errors seen)"
        if result.logical_errors == 0
        else f"{result.logical_error_per_logical_per_shot:.3g}"
    )
    rows = [
        ("machine", result.machine_name, ""),
        ("logical qubits", result.prediction.logical_qubits, result.prediction.logical_qubits),
        ("physical qubits", result.prediction.physical_qubits, f"{result.nominal_qubits} nominal"),
        (
            "T gates per day",
            f"{result.prediction.t_per_day:.4g}",
            f"{result.measured_t_per_day:.4g}",
        ),
        ("T stall reason", result.prediction.t_stall_reason, f"queue {result.t_queue_depth}"),
        ("utilization", 1.0, f"{result.utilization:.4f}"),
        ("stalled rounds", 0, result.stalled_rounds),
        ("machine seconds simulated", "", f"{result.machine_seconds:.1f}"),
        (
            "logical error / logical / shot",
            "suppressed below run resolution",
            f"{ler} ({result.shots} shots x {result.rounds_per_shot} rounds)",
        ),
        (
            "mean decode latency (ms)",
            "< 6 ms SEC budget",
            f"{result.mean_decode_latency_s * 1e3:.3f} over {result.decodes} decodes",
        ),
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "predicted (paper)", "measured"])
        writer.writerows(rows)
