"""Pluggable QEC code definitions (leaf layer).

Exists so codes (surface, qLDPC stand-in, ...) are swappable behind one
``QECCode`` protocol selected by name from YAML — never hard-coded.
"""

from catsim.codes.protocol import QECCode, available_codes, get_code, register_code
from catsim.codes.surface import SurfaceCode

register_code(SurfaceCode.family, SurfaceCode)

__all__ = [
    "QECCode",
    "SurfaceCode",
    "available_codes",
    "get_code",
    "register_code",
]
