"""Pluggable QEC code definitions (leaf layer).

Exists so codes (surface, GB/qLDPC, ...) are swappable behind one ``QECCode``
protocol selected by name from YAML — never hard-coded.
"""

from catsim.codes.gb import GeneralizedBicycleCode, make_gb_code
from catsim.codes.protocol import CSSCode, QECCode, available_codes, get_code, register_code
from catsim.codes.surface import SurfaceCode

register_code(SurfaceCode.family, SurfaceCode)
register_code(GeneralizedBicycleCode.family, make_gb_code)

__all__ = [
    "CSSCode",
    "GeneralizedBicycleCode",
    "QECCode",
    "SurfaceCode",
    "available_codes",
    "get_code",
    "make_gb_code",
    "register_code",
]
