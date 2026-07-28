"""The QECCode protocol and registry: YAML names select code implementations.

Exists so builders and decoders depend on one structural interface, and adding
a code is one file plus one registry entry — never an edit elsewhere.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable


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
