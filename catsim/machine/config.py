"""Machine instance configuration: chip composition and model knobs, from YAML.

Exists so a machine is a config, never code: which blocks a chip hosts, how
its qubits are accounted (paper Table V vs roadmap lean counting), and the
marked behavioral assumptions the SimPy model runs on. Loaded once into
frozen models and passed by constructor injection.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_MACHINE_DIR = Path("configs/machine")


class BlockComposition(BaseModel):
    """One memory block in a chip: which registered code it runs."""

    model_config = ConfigDict(frozen=True)

    family: str = "bb"
    code: str = "q70"


class ChipComposition(BaseModel):
    """What one chip hosts and how its qubits are counted.

    ``accounting: paper`` means the Table V all-in total IS the chip's story;
    ``lean`` means the nominal label under-counts the paper price and
    ``accounting_note`` must document the divergence (surfaced in the machine
    view and the dashboard footer, per charter).
    """

    model_config = ConfigDict(frozen=True)

    nominal_qubits: int = Field(gt=0)
    accounting: Literal["paper", "lean"] = "paper"
    accounting_note: str = ""
    blocks: list[BlockComposition] = []
    magic_factories: list[Literal["ch2", "mek"]] = []

    @model_validator(mode="after")
    def _lean_needs_note(self) -> ChipComposition:
        """Lean counting without a documented divergence is hiding, not accounting."""
        if self.accounting == "lean" and not self.accounting_note:
            raise ValueError("accounting: lean requires an accounting_note documenting divergence")
        return self

    @model_validator(mode="after")
    def _hosts_something(self) -> ChipComposition:
        """A chip hosts memory blocks or factories (M6 factory chips have no blocks)."""
        if not self.blocks and not self.magic_factories:
            raise ValueError("a chip must host at least one block or magic factory")
        return self


class ModelAssumptions(BaseModel):
    """Behavioral parameters of the machine model that are NOT from the paper.

    These shape the cat-supply dynamics (buffer size, production rate) and
    reporting cadence; they are assumptions, marked as such here and in the
    shipped YAMLs.
    """

    model_config = ConfigDict(frozen=True)

    cat_buffer_capacity: int = Field(default=24, gt=0)
    cat_attempts_per_sec: int = Field(default=2, gt=0)
    status_every_rounds: int = Field(default=5, gt=0)


class WorkloadConfig(BaseModel):
    """The logical workload the scheduler runs against the machine."""

    model_config = ConfigDict(frozen=True)

    t_per_second: float = Field(default=12.0, ge=0.0)
    """T-gate demand; default ~12/s tracks the paper's ~1M T/day reference
    throughput (CLAUDE.md canonical parameters)."""


class MachineConfig(BaseModel):
    """A machine instance: N copies of one chip composition plus model knobs."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str = ""
    chips: int = Field(default=1, gt=0)
    chip: ChipComposition
    assumptions: ModelAssumptions = ModelAssumptions()
    workload: WorkloadConfig = WorkloadConfig()


def load_machine_config(spec: str | Path, machine_dir: Path = DEFAULT_MACHINE_DIR) -> MachineConfig:
    """Load a machine config from a YAML path or a bare name under ``machine_dir``."""
    path = Path(spec)
    if not path.exists():
        path = machine_dir / f"{spec}.yaml"
    with path.open() as f:
        return MachineConfig.model_validate(yaml.safe_load(f))


def available_machines(machine_dir: Path = DEFAULT_MACHINE_DIR) -> list[str]:
    """Names of every machine config shipped under ``machine_dir``."""
    if not machine_dir.is_dir():
        return []
    return sorted(p.stem for p in machine_dir.glob("*.yaml"))
