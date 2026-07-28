"""Noise models: named, YAML-loaded, frozen — plugins behind the NoiseModel protocol.

Exists so a YAML string selects the noise (paper-baseline, pessimistic, ...) and
sweeps scale it uniformly, preserving the paper's ratios between channels.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

import yaml
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_NOISE_DIR = Path("configs/noise")


@runtime_checkable
class NoiseModel(Protocol):
    """What circuit builders need from any noise model implementation."""

    @property
    def name(self) -> str:
        """Model name, used in event payloads and plot labels."""
        ...

    @property
    def two_qubit_gate_error(self) -> float:
        """Depolarizing probability after two-qubit gates."""
        ...

    @property
    def single_qubit_gate_error(self) -> float:
        """Depolarizing probability for idle/single-qubit locations per round."""
        ...

    @property
    def measurement_error(self) -> float:
        """Probability a measurement result is flipped."""
        ...

    @property
    def reset_error(self) -> float:
        """Probability a reset leaves the orthogonal state."""
        ...

    @property
    def ion_loss_probability(self) -> float:
        """Per-operation ion loss probability (consumed from M3 on)."""
        ...

    def scaled(self, factor: float) -> NoiseModel:
        """Return a copy with every channel multiplied by ``factor`` (sweeps)."""
        ...


class DepolarizingNoise(BaseModel):
    """Circuit-level depolarizing noise with the paper's per-channel rates."""

    model_config = ConfigDict(frozen=True)

    name: str
    two_qubit_gate_error: float = Field(ge=0.0, le=1.0)
    single_qubit_gate_error: float = Field(ge=0.0, le=1.0)
    measurement_error: float = Field(ge=0.0, le=1.0)
    reset_error: float = Field(ge=0.0, le=1.0)
    ion_loss_probability: float = Field(ge=0.0, le=1.0)

    def scaled(self, factor: float) -> DepolarizingNoise:
        """Return a copy with every error channel multiplied by ``factor``.

        Preserves the paper's ratios between channels, so a threshold sweep is
        one knob. Loss is scaled too; it is not consumed before M3.
        """
        return DepolarizingNoise(
            name=f"{self.name}-x{factor:g}",
            two_qubit_gate_error=self.two_qubit_gate_error * factor,
            single_qubit_gate_error=self.single_qubit_gate_error * factor,
            measurement_error=self.measurement_error * factor,
            reset_error=self.reset_error * factor,
            ion_loss_probability=self.ion_loss_probability * factor,
        )


def load_noise_model(spec: str | Path, noise_dir: Path = DEFAULT_NOISE_DIR) -> DepolarizingNoise:
    """Load a noise model from a YAML path or a name under ``noise_dir``.

    Args:
        spec: Either a path to a YAML file or a bare name like ``paper-baseline``
            resolved to ``<noise_dir>/<name>.yaml``.
        noise_dir: Directory holding named noise configs.

    Returns:
        The frozen, validated noise model.
    """
    path = Path(spec)
    if not path.exists():
        path = noise_dir / f"{spec}.yaml"
    with path.open() as f:
        raw = yaml.safe_load(f)
    return DepolarizingNoise.model_validate(raw)
