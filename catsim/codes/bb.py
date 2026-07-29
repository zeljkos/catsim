"""Bivariate bicycle (BB) codes — the walking cat's single-code family (Q70).

Exists to implement Q70 = [[70,6,9]] exactly as published (arXiv:2604.19481
Appendix C, Table XXX): HX = [A|B], HZ = [Bᵀ|Aᵀ] with A, B sums of monomials
xᵃyᵇ where x = S_ℓ ⊗ I_m, y = I_ℓ ⊗ S_m (Bravyi et al. convention). GB codes
are the m = 1 special case, so this builder generalizes the GB one.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from functools import cached_property
from typing import ClassVar, cast

import numpy as np

from catsim.codes._gf2 import Matrix, coset_representatives, kernel_basis, rank

Monomial = tuple[int, int]


def monomial_sum(ell: int, m: int, powers: tuple[Monomial, ...]) -> Matrix:
    """The ℓm x ℓm matrix Σ xᵃyᵇ: row (r,s) has 1s at ((r+a) mod ℓ, (s+b) mod m).

    Qubit (r, s) sits at index r*m + s; shifts wrap cyclically per axis, so the
    GB circulant is exactly the m = 1 case.
    """
    mat = np.zeros((ell * m, ell * m), dtype=np.uint8)
    for r in range(ell):
        for s in range(m):
            for a, b in powers:
                mat[r * m + s, ((r + a) % ell) * m + (s + b) % m] ^= 1
    return mat


@dataclass(frozen=True)
class BivariateBicycleCode:
    """A BB code [[2ℓm, k, d]] defined by two bivariate polynomials a(x,y), b(x,y).

    ``distance`` is declared, not computed (same policy as GB): exhaustive
    distance enumeration is a research computation; tests verify d <= distance
    via the published minimum-weight logical operators of Table XXXIII.
    """

    name: str
    ell: int
    m: int
    a_powers: tuple[Monomial, ...]
    b_powers: tuple[Monomial, ...]
    distance: int
    family: ClassVar[str] = "bb"

    def __post_init__(self) -> None:
        """Reject empty or out-of-range polynomials."""
        for powers in (self.a_powers, self.b_powers):
            if not powers or any(not (0 <= a < self.ell and 0 <= b < self.m) for a, b in powers):
                raise ValueError(
                    f"monomial powers must lie in [0, {self.ell}) x [0, {self.m}): {powers}"
                )

    @property
    def num_data_qubits(self) -> int:
        """N = 2ℓm data qubits (two monomial-matrix halves)."""
        return 2 * self.ell * self.m

    @cached_property
    def hx(self) -> Matrix:
        """X-check matrix [A | B]; ℓm rows of weight |a| + |b| (overcomplete)."""
        return np.concatenate(
            [
                monomial_sum(self.ell, self.m, self.a_powers),
                monomial_sum(self.ell, self.m, self.b_powers),
            ],
            axis=1,
        )

    @cached_property
    def hz(self) -> Matrix:
        """Z-check matrix [Bᵀ | Aᵀ]; commutes with hx because monomials commute."""
        return np.concatenate(
            [
                monomial_sum(self.ell, self.m, self.b_powers).T,
                monomial_sum(self.ell, self.m, self.a_powers).T,
            ],
            axis=1,
        )

    @cached_property
    def num_logical(self) -> int:
        """K = n - rank(HX) - rank(HZ) over GF(2)."""
        return self.num_data_qubits - rank(self.hx) - rank(self.hz)

    @cached_property
    def logical_z(self) -> Matrix:
        """K independent logical-Z representatives: ker(HX) modulo rowspace(HZ)."""
        return coset_representatives(kernel_basis(self.hx), self.hz)

    @cached_property
    def logical_x(self) -> Matrix:
        """K independent logical-X representatives: ker(HZ) modulo rowspace(HX)."""
        return coset_representatives(kernel_basis(self.hz), self.hx)


Q70 = BivariateBicycleCode(
    # arXiv:2604.19481 Appendix C, Table XXX (the row marked *, the paper's
    # single-code architecture memory/magic block): BB, w=7, ell=7, m=5,
    # a(x,y) = y^2 + x^2 + x^3 + x^4, b(x,y) = y + x + x^3,
    # [[70, 6, 9]] with d = 9 exact by exhaustive enumeration.
    name="q70",
    ell=7,
    m=5,
    a_powers=((0, 2), (2, 0), (3, 0), (4, 0)),
    b_powers=((0, 1), (1, 0), (3, 0)),
    distance=9,
)

_KNOWN = {Q70.name: Q70}


def _monomials(raw: object) -> tuple[Monomial, ...]:
    """Coerce YAML-style [[a, b], ...] into a tuple of exponent pairs."""
    pairs = cast("Iterable[tuple[int, int]]", raw)
    return tuple((int(a), int(b)) for a, b in pairs)


def make_bb_code(name: str = "q70", **params: object) -> BivariateBicycleCode:
    """Build a BB code by published name, or a custom one from YAML parameters.

    Args:
        name: A known instance (``"q70"``) when no other params are given.
        **params: Alternatively ``ell``, ``m``, ``a_powers``, ``b_powers``
            (lists of [x, y] exponent pairs), ``distance`` define a custom
            instance named ``name``.

    Returns:
        The frozen code instance.

    Raises:
        KeyError: If ``name`` is unknown and no custom parameters were given.
    """
    if params:
        return BivariateBicycleCode(
            name=name,
            ell=int(params["ell"]),  # type: ignore[call-overload]
            m=int(params["m"]),  # type: ignore[call-overload]
            a_powers=_monomials(params["a_powers"]),
            b_powers=_monomials(params["b_powers"]),
            distance=int(params["distance"]),  # type: ignore[call-overload]
        )
    if name not in _KNOWN:
        raise KeyError(f"unknown BB code {name!r}; known: {sorted(_KNOWN)}")
    return _KNOWN[name]
