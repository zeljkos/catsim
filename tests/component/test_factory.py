"""Factories: registry, noiseless acceptance, paper-noise calibration, events."""

import pytest

from catsim.bus import (
    FactoryAccepted,
    FactoryAttempt,
    FactoryConfigured,
    FactoryRejected,
    SetNoiseScale,
)
from catsim.component import (
    DepolarizingNoise,
    FactoryService,
    FactorySpec,
    available_factories,
    build_factory_circuit,
)
from tests.conftest import ListSink

KINDS = ("cat", "bell", "magic")


def _run(kind: str, noise: DepolarizingNoise, attempts: int, seed: int = 7) -> ListSink:
    """Run one factory for ``attempts`` into a fresh sink."""
    sink = ListSink()
    service = FactoryService(FactorySpec(kind=kind, noise=noise), sink, seed=seed)
    service.run(attempts)
    return sink


def _verdicts(sink: ListSink) -> tuple[list[FactoryAccepted], list[FactoryRejected]]:
    accepted = [e for e in sink.events if isinstance(e, FactoryAccepted)]
    rejected = [e for e in sink.events if isinstance(e, FactoryRejected)]
    return accepted, rejected


def test_registry_lists_the_shipped_kinds() -> None:
    assert set(KINDS) <= set(available_factories())


def test_unknown_kind_raises(paper_noise: DepolarizingNoise) -> None:
    with pytest.raises(KeyError, match="unknown factory kind"):
        build_factory_circuit("teleporter", paper_noise)


@pytest.mark.parametrize("kind", KINDS)
def test_noiseless_acceptance_is_100_percent(kind: str, paper_noise: DepolarizingNoise) -> None:
    """Charter gate: zero errors in -> every attempt verifies and is delivered clean."""
    sink = _run(kind, paper_noise.scaled(0.0), attempts=200)
    accepted, rejected = _verdicts(sink)
    assert len(accepted) == 200 and not rejected
    assert accepted[-1].acceptance_rate == 1.0
    assert all(not e.residual_checks for e in accepted)
    assert accepted[-1].output_error_rate == 0.0


@pytest.mark.parametrize("kind", KINDS)
def test_paper_noise_acceptance_is_high(kind: str, paper_noise: DepolarizingNoise) -> None:
    """Calibration: at 1e-4 two-qubit error the short verify circuits reject ~0.1%."""
    sink = _run(kind, paper_noise, attempts=2000)
    accepted, _ = _verdicts(sink)
    assert accepted, "paper noise must not kill the yield"
    assert accepted[-1].acceptance_rate >= 0.99


@pytest.mark.parametrize("kind", KINDS)
def test_heavy_noise_collapses_acceptance(kind: str, busy_noise: DepolarizingNoise) -> None:
    """Calibration under heavy noise.

    At 100x paper noise post-selection visibly rejects attempts (measured
    0.82-0.94 acceptance across the three factories at seed 7).
    """
    sink = _run(kind, busy_noise, attempts=2000)
    accepted, rejected = _verdicts(sink)
    assert rejected, "100x noise must produce rejects"
    rate = (accepted[-1] if accepted else rejected[-1]).acceptance_rate
    assert 0.5 < rate < 0.99
    assert all(e.failed_checks for e in rejected), "rejects must name the failed checks"


def test_heavy_noise_shows_undetected_output_errors(busy_noise: DepolarizingNoise) -> None:
    """The truth oracle grades accepted outputs.

    At 100x noise some outputs slip through verification errored (~3% for
    the cat factory) — surfaced, never hidden.
    """
    sink = _run("cat", busy_noise, attempts=2000)
    accepted, _ = _verdicts(sink)
    assert any(e.residual_checks for e in accepted)
    assert accepted[-1].output_error_rate > 0.0


def test_event_stream_shape(paper_noise: DepolarizingNoise) -> None:
    sink = _run("cat", paper_noise, attempts=5)
    assert isinstance(sink.events[0], FactoryConfigured)
    assert sink.events[0].kind == "cat"
    assert sink.events[0].verification_checks == 3
    attempts = [e for e in sink.events if isinstance(e, FactoryAttempt)]
    accepted, rejected = _verdicts(sink)
    assert [e.attempt for e in attempts] == [1, 2, 3, 4, 5]
    assert len(accepted) + len(rejected) == 5


def test_running_acceptance_rate_is_consistent(busy_noise: DepolarizingNoise) -> None:
    sink = _run("magic", busy_noise, attempts=500)
    verdicts = [e for e in sink.events if isinstance(e, FactoryAccepted | FactoryRejected)]
    for v in verdicts:
        assert v.acceptance_rate == pytest.approx(v.accepted / v.attempts)
    assert verdicts[-1].attempts == 500


def test_same_seed_same_verdicts(busy_noise: DepolarizingNoise) -> None:
    a = _run("bell", busy_noise, attempts=100, seed=11)
    b = _run("bell", busy_noise, attempts=100, seed=11)
    assert [e.model_dump() for e in a.events] == [e.model_dump() for e in b.events]


def test_set_noise_scale_rebuilds_and_reannounces(paper_noise: DepolarizingNoise) -> None:
    sink = ListSink()
    service = FactoryService(FactorySpec(kind="cat", noise=paper_noise), sink, seed=0)
    service.handle_command(SetNoiseScale(source="test", target="cat0", scale=10.0))
    service.run(3)
    configured = [e for e in sink.events if isinstance(e, FactoryConfigured)]
    assert [c.noise_scale for c in configured] == [1.0, 10.0]
    assert configured[1].noise_name.endswith("-x10")


def test_magic_token_carries_residual_estimate(paper_noise: DepolarizingNoise) -> None:
    """The magic output is a token.

    Exactly one Clifford-checked output qubit, whose accepted event carries
    the measured residual-error estimate.
    """
    factory = build_factory_circuit("magic", paper_noise)
    assert factory.output_qubits == (0,)
    assert factory.circuit.num_detectors == factory.num_verification + 1
    sink = _run("magic", paper_noise.scaled(0.0), attempts=1)
    accepted, _ = _verdicts(sink)
    assert accepted[0].residual_checks == []
