"""Skeleton smoke tests: the package tree imports cleanly."""

import importlib

import pytest

import catsim

PACKAGES = [
    "catsim",
    "catsim.bus",
    "catsim.cli",
    "catsim.codes",
    "catsim.component",
    "catsim.decoder",
    "catsim.machine",
    "catsim.dashboard",
]


@pytest.mark.parametrize("name", PACKAGES)
def test_package_imports(name: str) -> None:
    assert importlib.import_module(name) is not None


def test_version_is_set() -> None:
    assert catsim.__version__
