"""Surface code plugin: parameters and registry behavior."""

import pytest

from catsim.codes import SurfaceCode, available_codes, get_code


def test_registry_builds_surface_code() -> None:
    code = get_code("surface", distance=5)
    assert isinstance(code, SurfaceCode)
    assert code.name == "surface-d5"
    assert code.num_data_qubits == 25
    assert code.num_logical == 1


def test_unknown_family_raises() -> None:
    with pytest.raises(KeyError, match="unknown code family"):
        get_code("does-not-exist")


def test_surface_is_registered() -> None:
    assert "surface" in available_codes()


@pytest.mark.parametrize("bad", [1, 2, 4, -3])
def test_invalid_distance_rejected(bad: int) -> None:
    with pytest.raises(ValueError, match="odd integer"):
        SurfaceCode(distance=bad)
