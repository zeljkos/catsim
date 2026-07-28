"""Q102 verification against arXiv:2604.19481: [[102,22,9]] exactly as published."""

import numpy as np
import numpy.typing as npt
import pytest

from catsim.codes import GeneralizedBicycleCode, get_code
from catsim.codes._gf2 import in_rowspace, kernel_basis, rank
from catsim.codes.gb import Q102

# Appendix E, Table XXXIV row i=1: weight-9 logical X (first row of [Lx,1|Lx,2],
# Kx = 1), as polynomial exponents over the two circulant halves.
_XBAR9_LEFT = (19, 24, 30, 35, 42)
_XBAR9_RIGHT = (21, 26, 27, 39)
# Appendix E, Table XXXV row j=1: weight-9 logical Z.
_ZBAR9_LEFT = (9, 13, 20, 23, 50)
_ZBAR9_RIGHT = (5, 26, 29, 42)


def _vector(left: tuple[int, ...], right: tuple[int, ...]) -> npt.NDArray[np.uint8]:
    """A length-102 support vector from per-half polynomial exponents."""
    v = np.zeros(Q102.num_data_qubits, dtype=np.uint8)
    for e in left:
        v[e] = 1
    for e in right:
        v[Q102.ell + e] = 1
    return v


def test_q102_parameters() -> None:
    assert Q102.num_data_qubits == 102
    assert Q102.num_logical == 22
    assert Q102.distance == 9


def test_q102_k_from_check_matrix_ranks() -> None:
    assert rank(Q102.hx) == 40
    assert rank(Q102.hz) == 40
    assert Q102.num_data_qubits - rank(Q102.hx) - rank(Q102.hz) == 22


def test_q102_check_weight_8() -> None:
    assert set(Q102.hx.sum(axis=1)) == {8}
    assert set(Q102.hz.sum(axis=1)) == {8}


def test_q102_css_commutation() -> None:
    assert not ((Q102.hx @ Q102.hz.T) % 2).any()


def test_q102_weight_9_logical_x_exists() -> None:
    # d <= 9 sanity check; the paper reports d = 9 exact (Table XXX, exhaustive).
    xbar = _vector(_XBAR9_LEFT, _XBAR9_RIGHT)
    assert int(xbar.sum()) == 9
    assert not ((Q102.hz @ xbar) % 2).any(), "must commute with every Z check"
    assert not in_rowspace(Q102.hx, xbar), "must not be a stabilizer"


def test_q102_weight_9_logical_z_exists() -> None:
    zbar = _vector(_ZBAR9_LEFT, _ZBAR9_RIGHT)
    assert int(zbar.sum()) == 9
    assert not ((Q102.hx @ zbar) % 2).any(), "must commute with every X check"
    assert not in_rowspace(Q102.hz, zbar), "must not be a stabilizer"


def test_q102_logical_operators_are_valid() -> None:
    for ops, h_commute, h_stab in (
        (Q102.logical_z, Q102.hx, Q102.hz),
        (Q102.logical_x, Q102.hz, Q102.hx),
    ):
        assert ops.shape == (22, 102)
        assert not ((h_commute @ ops.T) % 2).any()
        for op in ops:
            assert not in_rowspace(h_stab, op)


def test_registry_builds_q102() -> None:
    code = get_code("gb")
    assert isinstance(code, GeneralizedBicycleCode)
    assert code.name == "q102"
    assert code.distance == 9


def test_registry_builds_custom_gb_code() -> None:
    code = get_code("gb", name="toy", ell=5, a_powers=[0, 1], b_powers=[0, 3], distance=2)
    assert isinstance(code, GeneralizedBicycleCode)
    assert code.num_data_qubits == 10
    assert not ((code.hx @ code.hz.T) % 2).any()


def test_unknown_gb_name_rejected() -> None:
    with pytest.raises(KeyError, match="unknown GB code"):
        get_code("gb", name="q999")


def test_gf2_kernel_is_null_space() -> None:
    kernel = kernel_basis(Q102.hx)
    assert kernel.shape[0] == 102 - rank(Q102.hx)
    assert not ((Q102.hx @ kernel.T) % 2).any()
