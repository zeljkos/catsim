"""Shared fixtures: repo-anchored noise configs and an in-memory event sink."""

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
