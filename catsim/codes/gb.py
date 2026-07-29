"""Generalized bicycle (GB) codes — the walking cat's high-rate memory family.

Exists to implement Q102 = [[102,22,9]] exactly as published (arXiv:2604.19481
Appendix C, Table XXX): HX = [A|B], HZ = [Bᵀ|Aᵀ] with A, B circulant 51x51
sums of 4 monomial shifts each (check weight 8). GB is the univariate (m = 1)
special case of the bivariate bicycle construction, so all matrix machinery
delegates to :mod:`catsim.codes.bb`.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import ClassVar

from catsim.codes._gf2 import Matrix
from catsim.codes.bb import BivariateBicycleCode


@dataclass(frozen=True)
class GeneralizedBicycleCode:
    """A GB code [[2ℓ, k, d]] defined by two circulant polynomials a(x), b(x).

    ``distance`` is declared, not computed: exhaustive distance enumeration is
    a research computation (the paper reports Q102's d = 9 as exact); tests
    verify d <= distance via published minimum-weight logical operators.
    """

    name: str
    ell: int
    a_powers: tuple[int, ...]
    b_powers: tuple[int, ...]
    distance: int
    family: ClassVar[str] = "gb"

    def __post_init__(self) -> None:
        """Reject empty or out-of-range polynomials."""
        for powers in (self.a_powers, self.b_powers):
            if not powers or any(not 0 <= p < self.ell for p in powers):
                raise ValueError(f"polynomial powers must lie in [0, {self.ell}): {powers}")

    @cached_property
    def _bb(self) -> BivariateBicycleCode:
        """The equivalent m = 1 bivariate code carrying the matrix machinery."""
        return BivariateBicycleCode(
            name=self.name,
            ell=self.ell,
            m=1,
            a_powers=tuple((p, 0) for p in self.a_powers),
            b_powers=tuple((p, 0) for p in self.b_powers),
            distance=self.distance,
        )

    @property
    def num_data_qubits(self) -> int:
        """N = 2ℓ data qubits (two circulant halves)."""
        return 2 * self.ell

    @property
    def hx(self) -> Matrix:
        """X-check matrix [A | B]; ℓ rows of weight |a| + |b| (overcomplete)."""
        return self._bb.hx

    @property
    def hz(self) -> Matrix:
        """Z-check matrix [Bᵀ | Aᵀ]; commutes with hx because circulants commute."""
        return self._bb.hz

    @property
    def num_logical(self) -> int:
        """K = n - rank(HX) - rank(HZ) over GF(2)."""
        return self._bb.num_logical

    @property
    def logical_z(self) -> Matrix:
        """K independent logical-Z representatives: ker(HX) modulo rowspace(HZ)."""
        return self._bb.logical_z

    @property
    def logical_x(self) -> Matrix:
        """K independent logical-X representatives: ker(HZ) modulo rowspace(HX)."""
        return self._bb.logical_x


Q102 = GeneralizedBicycleCode(
    # arXiv:2604.19481 Appendix C, Table XXX (the row marked *, used as the
    # paper's memory code): GB, w=8, ell=51,
    # a(x) = x^22 + x^26 + x^37 + x^50, b(x) = x^19 + x^28 + x^29 + x^35,
    # [[102, 22, 9]] with d = 9 exact by exhaustive enumeration.
    name="q102",
    ell=51,
    a_powers=(22, 26, 37, 50),
    b_powers=(19, 28, 29, 35),
    distance=9,
)

_KNOWN = {Q102.name: Q102}


def make_gb_code(name: str = "q102", **params: object) -> GeneralizedBicycleCode:
    """Build a GB code by published name, or a custom one from YAML parameters.

    Args:
        name: A known instance (``"q102"``) when no other params are given.
        **params: Alternatively ``ell``, ``a_powers``, ``b_powers``, ``distance``
            define a custom instance named ``name``.

    Returns:
        The frozen code instance.

    Raises:
        KeyError: If ``name`` is unknown and no custom parameters were given.
    """
    if params:
        return GeneralizedBicycleCode(
            name=name,
            ell=int(params["ell"]),  # type: ignore[call-overload]
            a_powers=tuple(params["a_powers"]),  # type: ignore[arg-type]
            b_powers=tuple(params["b_powers"]),  # type: ignore[arg-type]
            distance=int(params["distance"]),  # type: ignore[call-overload]
        )
    if name not in _KNOWN:
        raise KeyError(f"unknown GB code {name!r}; known: {sorted(_KNOWN)}")
    return _KNOWN[name]
