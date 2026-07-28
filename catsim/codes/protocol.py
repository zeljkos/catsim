"""The QECCode protocol and registry: YAML names select code implementations.

Exists so builders and decoders depend on one structural interface, and adding
a code is one file plus one registry entry — never an edit elsewhere.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

import numpy as np
import numpy.typing as npt


@runtime_checkable
class QECCode(Protocol):
    """What every pluggable code exposes to the rest of the system."""

    @property
    def family(self) -> str:
        """Registry key shared by all instances of this code family."""
        ...

    @property
    def name(self) -> str:
        """Human-readable instance name, e.g. ``surface-d5``."""
        ...

    @property
    def distance(self) -> int:
        """Code distance."""
        ...

    @property
    def num_data_qubits(self) -> int:
        """Number of data qubits (excluding ancillas)."""
        ...

    @property
    def num_logical(self) -> int:
        """Number of logical qubits the code encodes."""
        ...


@runtime_checkable
class CSSCode(QECCode, Protocol):
    """A code that additionally exposes CSS check matrices and logical operators.

    Exists so one generic syndrome-extraction circuit builder serves every CSS
    code (GB now, further qLDPC families later) with zero edits elsewhere.
    """

    @property
    def hx(self) -> npt.NDArray[np.uint8]:
        """X-check matrix (checks x data qubits), possibly overcomplete."""
        ...

    @property
    def hz(self) -> npt.NDArray[np.uint8]:
        """Z-check matrix (checks x data qubits), possibly overcomplete."""
        ...

    @property
    def logical_z(self) -> npt.NDArray[np.uint8]:
        """K logical-Z representatives, one per row."""
        ...

    @property
    def logical_x(self) -> npt.NDArray[np.uint8]:
        """K logical-X representatives, one per row."""
        ...


CodeFactory = Callable[..., QECCode]

_REGISTRY: dict[str, CodeFactory] = {}


def register_code(family: str, factory: CodeFactory) -> None:
    """Register a code family under its YAML-selectable name."""
    _REGISTRY[family] = factory


def get_code(family: str, **params: object) -> QECCode:
    """Build a code instance by family name with family-specific parameters.

    Args:
        family: Registered family name, e.g. ``"surface"``.
        **params: Passed through to the family's factory (e.g. ``distance=5``).

    Returns:
        A concrete code satisfying :class:`QECCode`.

    Raises:
        KeyError: If the family was never registered.
    """
    if family not in _REGISTRY:
        raise KeyError(f"unknown code family {family!r}; known: {available_codes()}")
    return _REGISTRY[family](**params)


def available_codes() -> tuple[str, ...]:
    """List the registered code family names."""
    return tuple(sorted(_REGISTRY))
