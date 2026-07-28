"""The Decoder protocol and registry: YAML names select decoder implementations.

Exists so decoders are swappable at runtime (pymatching now, BP+OSD in M2)
without touching anything outside this package.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np
import numpy.typing as npt


@dataclass(frozen=True)
class DecodeResult:
    """One decode: what the decoder concluded and how long it really took.

    ``matched_detectors`` holds one detector set per blamed error mechanism:
    matching decoders emit pairs (-1 = boundary), BP+OSD emits the full
    detector set of each error mechanism it turned on.
    """

    predicted_flips: tuple[int, ...]
    matched_detectors: tuple[tuple[int, ...], ...]
    latency_s: float


@runtime_checkable
class Decoder(Protocol):
    """What every pluggable decoder exposes to the service loop."""

    name: str
    slowdown_factor: float

    def decode(self, syndrome: npt.NDArray[np.uint8]) -> DecodeResult:
        """Decode a full-length detector vector into a correction."""
        ...


DecoderFactory = Callable[..., Decoder]

_REGISTRY: dict[str, DecoderFactory] = {}


def register_decoder(name: str, factory: DecoderFactory) -> None:
    """Register a decoder under its YAML-selectable name."""
    _REGISTRY[name] = factory


def get_decoder(name: str, *, dem: str, **params: object) -> Decoder:
    """Build a decoder by name for a given detector error model.

    Args:
        name: Registered decoder name, e.g. ``"pymatching"``.
        dem: The stim detector error model, serialized as text.
        **params: Decoder-specific options (e.g. ``slowdown_factor``).

    Returns:
        A ready-to-use decoder.

    Raises:
        KeyError: If the name was never registered.
    """
    if name not in _REGISTRY:
        raise KeyError(f"unknown decoder {name!r}; known: {available_decoders()}")
    return _REGISTRY[name](dem=dem, **params)


def available_decoders() -> tuple[str, ...]:
    """List the registered decoder names."""
    return tuple(sorted(_REGISTRY))
