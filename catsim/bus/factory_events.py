"""Factory and loss-recovery event schemas — the M3 slice of the bus contract.

Exists so every factory (cat, Bell, magic, qubit) speaks one vocabulary the
dashboard's factories panel renders directly: attempts, post-selection
verdicts with running acceptance rates, and the replacement-dispatch path
that closes the ion-loss loop with the memory block.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from catsim.bus.events import Command, Event


class FactoryConfigured(Event):
    """A factory announced itself: what it produces and under which noise."""

    type: Literal["factory_configured"] = "factory_configured"
    kind: str
    output_qubits: int
    verification_checks: int
    noise_name: str = ""
    noise_scale: float = 1.0


class FactoryAttempt(Event):
    """A factory started one prepare-and-verify attempt."""

    type: Literal["factory_attempt"] = "factory_attempt"
    attempt: int


class FactoryAccepted(Event):
    """Verification passed: one output delivered, with residual-error metadata.

    ``residual_checks`` lists the ideal-output stabilizers the delivered state
    actually violates (a simulation-only truth oracle; empty = clean output).
    For the magic factory this event IS the output token: the Clifford
    checking circuitry is simulated exactly, the magic state itself is
    represented only by this measured residual-error estimate.
    """

    type: Literal["factory_accepted"] = "factory_accepted"
    attempt: int
    attempts: int
    accepted: int
    acceptance_rate: float = Field(ge=0.0, le=1.0)
    residual_checks: list[int] = []
    output_error_rate: float = Field(default=0.0, ge=0.0, le=1.0)


class FactoryRejected(Event):
    """Verification failed: the attempt was discarded (post-selection)."""

    type: Literal["factory_rejected"] = "factory_rejected"
    attempt: int
    attempts: int
    accepted: int
    acceptance_rate: float = Field(ge=0.0, le=1.0)
    failed_checks: list[int]


class LossDetected(Event):
    """The block flagged a lost ion (one detection round after the loss)."""

    type: Literal["loss_detected"] = "loss_detected"
    qubit: int
    shot: int
    round: int


class ReplacementDispatched(Event):
    """The qubit factory started producing a replacement for a lost ion."""

    type: Literal["replacement_dispatched"] = "replacement_dispatched"
    qubit: int
    block: str
    ready_in_rounds: int


class ReplacementReady(Command):
    """A replacement ion is ready; the target block reinitializes the qubit."""

    type: Literal["replacement_ready"] = "replacement_ready"
    qubit: int
