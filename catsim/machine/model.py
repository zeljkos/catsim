"""The SimPy machine model: chips, cat supply, T-gate queue — in machine time.

Exists as Layer 3's discrete-event core: blocks consume verified cat states
each SEC (the walking cat's load-bearing resource), cat units produce them at
the live-calibrated acceptance rate, and a workload's T-gate demand queues
against whatever magic factories the composition has (none on a memory chip —
the queue stalls with attribution). Pure and wall-clock-free: the service
layer advances it in lockstep with the real block's rounds; tests and batch
runs fast-forward it directly.
"""

from __future__ import annotations

import random
from collections.abc import Generator
from dataclasses import dataclass

import simpy

from catsim.machine.calibration import Calibration, t_pair_seconds
from catsim.machine.config import MachineConfig

BlockState = str  # "ok" | "degraded" | "stalled" (bus vocabulary, see machine_events)

_DAY_SECONDS = 86_400.0
_DEGRADED_FRACTION = 0.25


@dataclass(frozen=True)
class BlockSnapshot:
    """One block's model state at snapshot time."""

    block_id: str
    chip_id: str
    code: str
    rounds: int
    stalled_rounds: int
    cat_buffer: int
    cat_buffer_capacity: int
    state: BlockState


@dataclass(frozen=True)
class FactorySnapshot:
    """One factory's model state at snapshot time."""

    source: str
    kind: str
    chip_id: str
    state: str  # "ok" | "down"


@dataclass(frozen=True)
class MachineSnapshot:
    """The whole model at one instant, for the service to publish."""

    seconds: float
    blocks: tuple[BlockSnapshot, ...]
    factories: tuple[FactorySnapshot, ...]
    t_queue_depth: int
    t_done: int

    @property
    def t_per_day(self) -> float:
        """Measured T throughput extrapolated from machine time so far."""
        return self.t_done / self.seconds * _DAY_SECONDS if self.seconds > 0 else 0.0

    def chip_blocks(self, chip_id: str) -> tuple[BlockSnapshot, ...]:
        """The blocks hosted by one chip."""
        return tuple(b for b in self.blocks if b.chip_id == chip_id)

    def chip_factories(self, chip_id: str) -> tuple[FactorySnapshot, ...]:
        """The factories hosted by one chip."""
        return tuple(f for f in self.factories if f.chip_id == chip_id)


class _Block:
    """Mutable per-block state driven by the SimPy processes."""

    def __init__(self, block_id: str, chip_id: str, code: str, capacity: int) -> None:
        self.block_id = block_id
        self.chip_id = chip_id
        self.code = code
        self.capacity = capacity
        self.buffer = capacity  # starts full: the chip boots provisioned
        self.rounds = 0
        self.stalled_rounds = 0
        self.stalled_now = False

    @property
    def state(self) -> BlockState:
        """Stalled when starved this tick, degraded when the buffer runs low."""
        if self.stalled_now:
            return "stalled"
        if self.buffer <= self.capacity * _DEGRADED_FRACTION:
            return "degraded"
        return "ok"


class _Factory:
    """Mutable per-factory state (cat unit or magic factory)."""

    def __init__(self, source: str, kind: str, chip_id: str, acceptance: float) -> None:
        self.source = source
        self.kind = kind
        self.chip_id = chip_id
        self.acceptance = acceptance
        self.paused = False


class MachineModel:
    """One machine instance in machine time (seconds; one SEC per block round).

    All mutators and :meth:`step` must be called from a single thread (the
    machine service's run loop, or the test itself).
    """

    def __init__(
        self,
        config: MachineConfig,
        calibration: Calibration | None = None,
        seed: int = 0,
        label: str | None = None,
    ) -> None:
        """Build chips, blocks, cat units, factories, and the workload processes.

        Args:
            config: The machine instance to model.
            calibration: Timing/acceptance constants (defaults are the cited ones).
            seed: RNG seed for cat-acceptance draws.
            label: Fleet naming for a single-chip model (M6): the chip is
                ``label`` and its components ``{label}-block0`` etc., so ids
                stay unique across a fleet of independently-run chip models.
                Requires ``config.chips == 1``; None keeps the M5 naming.
        """
        if label is not None and config.chips != 1:
            raise ValueError("label naming applies to single-chip models only")
        self._config = config
        self._calibration = calibration or Calibration()
        self._rng = random.Random(seed)
        self._label = label
        self._env = simpy.Environment()
        self._blocks: list[_Block] = []
        self._cats: dict[str, _Factory] = {}
        self._magic: list[_Factory] = []
        self._t_per_second = config.workload.t_per_second
        self.t_queue_depth = 0
        self.t_done = 0
        self._build()

    @property
    def config(self) -> MachineConfig:
        """The machine instance this model runs."""
        return self._config

    @property
    def seconds(self) -> float:
        """Machine time elapsed so far."""
        return float(self._env.now)

    @property
    def sec_seconds(self) -> float:
        """One SEC in machine seconds (the model's clock tick)."""
        return self._calibration.sec_seconds

    def _build(self) -> None:
        """Instantiate model entities and register their SimPy processes."""
        sec = self._calibration.sec_seconds
        assumptions = self._config.assumptions
        prefix = f"{self._label}-" if self._label is not None else ""
        block_index = 0
        for chip_index in range(self._config.chips):
            chip_id = self._label if self._label is not None else f"chip{chip_index}"
            for block_cfg in self._config.chip.blocks:
                block = _Block(
                    block_id=f"{prefix}block{block_index}",
                    chip_id=chip_id,
                    code=block_cfg.code,
                    capacity=assumptions.cat_buffer_capacity,
                )
                cat = _Factory(
                    source=f"{prefix}cat{block_index}",
                    kind="cat",
                    chip_id=chip_id,
                    acceptance=self._calibration.cat_acceptance,
                )
                self._blocks.append(block)
                self._cats[cat.source] = cat
                self._env.process(self._block_process(block, sec))
                self._env.process(
                    self._cat_process(cat, block, sec, assumptions.cat_attempts_per_sec)
                )
                block_index += 1
            for magic_index, kind in enumerate(self._config.chip.magic_factories):
                source = (
                    f"{prefix}magic{magic_index}" if prefix else f"magic{chip_index}_{magic_index}"
                )
                factory = _Factory(
                    source=source,
                    kind=kind,
                    chip_id=chip_id,
                    acceptance=1.0,
                )
                self._magic.append(factory)
                self._env.process(self._magic_process(factory, sec))
        self._env.process(self._workload_process())

    def _block_process(self, block: _Block, sec: float) -> Generator[simpy.Event, None, None]:
        """One SE round per SEC, consuming a verified cat state — or stalling."""
        while True:
            yield self._env.timeout(sec)
            if block.buffer > 0:
                block.buffer -= 1
                block.rounds += 1
                block.stalled_now = False
            else:
                block.stalled_rounds += 1
                block.stalled_now = True

    def _cat_process(
        self, cat: _Factory, block: _Block, sec: float, attempts_per_sec: int
    ) -> Generator[simpy.Event, None, None]:
        """Prepare-and-verify attempts refilling the block's buffer (assumption-marked rate)."""
        while True:
            yield self._env.timeout(sec / attempts_per_sec)
            if cat.paused or block.buffer >= block.capacity:
                continue
            if self._rng.random() < cat.acceptance:
                block.buffer += 1

    def _magic_process(self, factory: _Factory, sec: float) -> Generator[simpy.Event, None, None]:
        """Consume the T queue two gates per pair at the Table VII pair time."""
        # A factory chip hosts no memory blocks of its own; its Table VII pair
        # time is quoted against the fleet's memory code (q70, the unit chip).
        blocks = self._config.chip.blocks
        memory_code = blocks[0].code if blocks else "q70"
        pair_time = t_pair_seconds(memory_code, factory.kind)
        while True:
            if factory.paused or self.t_queue_depth == 0:
                yield self._env.timeout(sec)
                continue
            yield self._env.timeout(pair_time)
            served = min(2, self.t_queue_depth)
            self.t_queue_depth -= served
            self.t_done += served

    def _workload_process(self) -> Generator[simpy.Event, None, None]:
        """T-gate demand into the queue at the current (rebalance-able) rate."""
        sec = self._calibration.sec_seconds
        while True:
            rate = self._t_per_second
            if rate <= 0:  # no demand assigned: idle until the rate changes
                yield self._env.timeout(sec)
                continue
            yield self._env.timeout(1.0 / rate)
            self.t_queue_depth += 1

    def step(self, seconds: float) -> None:
        """Advance machine time (the service calls this once per real block round)."""
        self._env.run(until=self._env.now + seconds)

    def set_factory_paused(self, source: str, paused: bool) -> None:
        """Kill or revive a factory by component id (the outage lever)."""
        for factory in [*self._cats.values(), *self._magic]:
            if factory.source == source:
                factory.paused = paused

    def set_t_demand(self, t_per_second: float) -> None:
        """Rebalance this model's share of the fleet's T-gate demand (M6)."""
        self._t_per_second = max(0.0, t_per_second)

    def add_t_backlog(self, gates: int) -> None:
        """Take over T gates owed from before this chip had a factory (M6)."""
        self.t_queue_depth += max(0, gates)

    def set_cat_acceptance(self, source: str, rate: float) -> None:
        """Live calibration: adopt the stim cat service's measured acceptance."""
        if source in self._cats:
            self._cats[source].acceptance = rate

    def snapshot(self) -> MachineSnapshot:
        """Freeze the current model state for publishing."""
        return MachineSnapshot(
            seconds=self.seconds,
            blocks=tuple(
                BlockSnapshot(
                    block_id=b.block_id,
                    chip_id=b.chip_id,
                    code=b.code,
                    rounds=b.rounds,
                    stalled_rounds=b.stalled_rounds,
                    cat_buffer=b.buffer,
                    cat_buffer_capacity=b.capacity,
                    state=b.state,
                )
                for b in self._blocks
            ),
            factories=tuple(
                FactorySnapshot(
                    source=f.source,
                    kind=f.kind,
                    chip_id=f.chip_id,
                    state="down" if f.paused else "ok",
                )
                for f in [*self._cats.values(), *self._magic]
            ),
            t_queue_depth=self.t_queue_depth,
            t_done=self.t_done,
        )
