"""Rotated surface code parameters (the known-good pipeline validator).

Exists per charter: validate the whole pipeline with a code whose behavior is
well known before swapping in a qLDPC stand-in (M2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class SurfaceCode:
    """A distance-d rotated surface code patch encoding one logical qubit."""

    distance: int = 3
    family: ClassVar[str] = "surface"

    def __post_init__(self) -> None:
        """Reject distances the rotated layout cannot realize."""
        if self.distance < 3 or self.distance % 2 == 0:
            raise ValueError(f"distance must be an odd integer >= 3, got {self.distance}")

    @property
    def name(self) -> str:
        """Instance name, e.g. ``surface-d5``."""
        return f"surface-d{self.distance}"

    @property
    def num_data_qubits(self) -> int:
        """d^2 data qubits in the rotated layout."""
        return self.distance * self.distance

    @property
    def num_logical(self) -> int:
        """One logical qubit per patch."""
        return 1
