"""Q70 verification against arXiv:2604.19481: [[70,6,9]] exactly as published."""

import numpy as np
import numpy.typing as npt
import pytest

from catsim.codes import BivariateBicycleCode, get_code
from catsim.codes._gf2 import in_rowspace, rank
from catsim.codes.bb import Q70

Poly = list[tuple[int, int]]

# Appendix E, Table XXXIII: minimum-weight symplectic basis for Q70. Each row
# group shares (Lx,1, Lx,2); Xbar_i is the first row of Kx,i[Lx,1|Lx,2] and
# Zbar_j is [(Kz,j Lx,2)^-1 | (Kz,j Lx,1)^-1] with p^-1(x,y) = p(x^-1,y^-1)
# (the inversion convention under which the published set is a complete
# independent basis). Monomials are (x-exponent, y-exponent) pairs.
_TABLE_XXXIII: list[tuple[Poly, Poly, list[tuple[tuple[int, int], int, tuple[int, int], int]]]] = [
    (
        # Lx,1 = 1 + xy^4 + x^4y^4 + x^6y^4 + x^2 + x^6y, Lx,2 = x^2 + x^4y^2 + x^5y^2
        [(0, 0), (1, 4), (4, 4), (6, 4), (2, 0), (6, 1)],
        [(2, 0), (4, 2), (5, 2)],
        [((2, 0), 3, (1, 0), 1), ((4, 1), 5, (3, 0), 4), ((0, 2), 0, (6, 0), 2)],
    ),
    (
        # Lx,1 = 1 + x^2 + x^3 + x^2y, Lx,2 = x^2 + x^3y + x^4y + x^5y + xy^3
        [(0, 0), (2, 0), (3, 0), (2, 1)],
        [(2, 0), (3, 1), (4, 1), (5, 1), (1, 3)],
        [((1, 1), 1, (3, 0), 3)],
    ),
    (
        # Lx,1 = 1 + x^2 + x^6y + xy^2 + x^3y^2 + y^3, Lx,2 = x^3 + x^4 + y^2
        [(0, 0), (2, 0), (6, 1), (1, 2), (3, 2), (0, 3)],
        [(3, 0), (4, 0), (0, 2)],
        [((3, 0), 2, (3, 0), 5), ((1, 4), 4, (5, 0), 0)],
    ),
]


def _mul(k: tuple[int, int], poly: Poly) -> Poly:
    """Multiply a polynomial by the monomial x^k0 y^k1 (exponents wrap)."""
    return [((a + k[0]) % Q70.ell, (b + k[1]) % Q70.m) for a, b in poly]


def _inv(poly: Poly) -> Poly:
    """p(x^-1, y^-1): negate every exponent modulo (ell, m)."""
    return [((-a) % Q70.ell, (-b) % Q70.m) for a, b in poly]


def _vector(left: Poly, right: Poly) -> npt.NDArray[np.uint8]:
    """A length-70 support vector from per-half monomial exponents."""
    v = np.zeros(Q70.num_data_qubits, dtype=np.uint8)
    for a, b in left:
        v[a * Q70.m + b] ^= 1
    for a, b in right:
        v[Q70.ell * Q70.m + a * Q70.m + b] ^= 1
    return v


Logicals = dict[int, npt.NDArray[np.uint8]]


def _published_logicals() -> tuple[Logicals, Logicals]:
    """All six Xbar_i and six Zbar_j from Table XXXIII as support vectors."""
    xbars: Logicals = {}
    zbars: Logicals = {}
    for lx1, lx2, rows in _TABLE_XXXIII:
        for kx, i, kz, j in rows:
            xbars[i] = _vector(_mul(kx, lx1), _mul(kx, lx2))
            zbars[j] = _vector(_inv(_mul(kz, lx2)), _inv(_mul(kz, lx1)))
    return xbars, zbars


def test_q70_parameters() -> None:
    assert Q70.num_data_qubits == 70
    assert Q70.num_logical == 6
    assert Q70.distance == 9


def test_q70_k_from_check_matrix_ranks() -> None:
    assert rank(Q70.hx) == 32
    assert rank(Q70.hz) == 32
    assert Q70.num_data_qubits - rank(Q70.hx) - rank(Q70.hz) == 6


def test_q70_check_weight_7() -> None:
    assert set(Q70.hx.sum(axis=1)) == {7}
    assert set(Q70.hz.sum(axis=1)) == {7}


def test_q70_css_commutation() -> None:
    assert not ((Q70.hx @ Q70.hz.T) % 2).any()


def test_q70_published_weight_9_logical_x_basis() -> None:
    # d <= 9 sanity check; the paper reports d = 9 exact (Table XXX, exhaustive).
    xbars, _ = _published_logicals()
    assert sorted(xbars) == list(range(6))
    for xbar in xbars.values():
        assert int(xbar.sum()) == 9
        assert not ((Q70.hz @ xbar) % 2).any(), "must commute with every Z check"
        assert not in_rowspace(Q70.hx, xbar), "must not be a stabilizer"
    stacked = np.vstack([Q70.hx, *xbars.values()])
    assert rank(stacked) == rank(Q70.hx) + 6, "must span the full logical-X space"


def test_q70_published_weight_9_logical_z_basis() -> None:
    _, zbars = _published_logicals()
    assert sorted(zbars) == list(range(6))
    for zbar in zbars.values():
        assert int(zbar.sum()) == 9
        assert not ((Q70.hx @ zbar) % 2).any(), "must commute with every X check"
        assert not in_rowspace(Q70.hz, zbar), "must not be a stabilizer"
    stacked = np.vstack([Q70.hz, *zbars.values()])
    assert rank(stacked) == rank(Q70.hz) + 6, "must span the full logical-Z space"


def test_q70_logical_operators_are_valid() -> None:
    for ops, h_commute, h_stab in (
        (Q70.logical_z, Q70.hx, Q70.hz),
        (Q70.logical_x, Q70.hz, Q70.hx),
    ):
        assert ops.shape == (6, 70)
        assert not ((h_commute @ ops.T) % 2).any()
        for op in ops:
            assert not in_rowspace(h_stab, op)


def test_bb_reduces_to_gb_at_m_equals_1() -> None:
    # The GB circulant construction must be exactly the m = 1 case of BB.
    gb = get_code("gb")
    bb = get_code(
        "bb",
        name="q102-as-bb",
        ell=51,
        m=1,
        a_powers=[(22, 0), (26, 0), (37, 0), (50, 0)],
        b_powers=[(19, 0), (28, 0), (29, 0), (35, 0)],
        distance=9,
    )
    assert isinstance(bb, BivariateBicycleCode)
    assert (bb.hx == gb.hx).all()  # type: ignore[attr-defined]
    assert (bb.hz == gb.hz).all()  # type: ignore[attr-defined]


def test_registry_builds_q70() -> None:
    code = get_code("bb")
    assert isinstance(code, BivariateBicycleCode)
    assert code.name == "q70"
    assert code.distance == 9


def test_registry_builds_custom_bb_code() -> None:
    code = get_code(
        "bb", name="toy", ell=3, m=2, a_powers=[[0, 1], [1, 0]], b_powers=[[2, 1]], distance=2
    )
    assert isinstance(code, BivariateBicycleCode)
    assert code.num_data_qubits == 12
    assert not ((code.hx @ code.hz.T) % 2).any()


def test_unknown_bb_name_rejected() -> None:
    with pytest.raises(KeyError, match="unknown BB code"):
        get_code("bb", name="q999")


def test_out_of_range_monomials_rejected() -> None:
    with pytest.raises(ValueError, match="monomial powers"):
        get_code("bb", name="bad", ell=3, m=2, a_powers=[(0, 2)], b_powers=[(1, 0)], distance=1)
