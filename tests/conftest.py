"""Shared fixtures: repo-anchored noise configs, in-memory sink, fd-leak guard."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from catsim.bus import AnyEvent
from catsim.component import DepolarizingNoise, load_noise_model

REPO_ROOT = Path(__file__).resolve().parent.parent
NOISE_DIR = REPO_ROOT / "configs" / "noise"


class ListSink:
    """EventSink that records events in order, for asserting on emissions."""

    def __init__(self) -> None:
        """Start with an empty event log."""
        self.events: list[AnyEvent] = []

    def publish(self, event: AnyEvent) -> None:
        """Record the event."""
        self.events.append(event)


@pytest.fixture
def list_sink() -> ListSink:
    """A fresh in-memory sink per test."""
    return ListSink()


@pytest.fixture
def paper_noise() -> DepolarizingNoise:
    """The canonical paper-baseline noise model, loaded from its shipped YAML."""
    return load_noise_model(NOISE_DIR / "paper-baseline.yaml")


@pytest.fixture
def busy_noise() -> DepolarizingNoise:
    """100x paper noise: guarantees syndromes fire within a few rounds in tests."""
    return load_noise_model(NOISE_DIR / "paper-baseline.yaml").scaled(100.0)


def _open_fd_count() -> int:
    """This process's open file descriptors (via /dev/fd — macOS and Linux)."""
    return len(os.listdir("/dev/fd"))


_FD_GROWTH_ALLOWANCE = 48
"""Legitimate suite-lifetime growth: the shared zmq context's internal pipes,
matplotlib/stim caches, log handles. Well below one leak per bus object."""


@pytest.fixture(autouse=True, scope="session")
def fd_leak_guard() -> Iterator[None]:
    """Regression guard: the suite must not leak file descriptors.

    Per-object zmq contexts once leaked fds until EMFILE at macOS's default
    ulimit of 256 — and 40 chips (M6) would only hit it sooner. Every socket
    must come from the one process-level bus context and be closed by its
    owner; if this trips, find the unclosed socket or fresh context, do not
    raise the allowance (or the ulimit).
    """
    start = _open_fd_count()
    yield
    growth = _open_fd_count() - start
    assert growth < _FD_GROWTH_ALLOWANCE, (
        f"test suite grew from {start} to {start + growth} open fds; "
        "something is creating zmq contexts or leaving sockets unclosed"
    )
