"""Versioned pydantic event and command schemas — the bus contract.

Exists as the single source of truth for what services may say to each other;
changing any model is a breaking change requiring a schema version bump.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

SCHEMA_VERSION = 3
"""v3: decode_finished.matched_detectors generalizes from matched pairs to
detector sets (BP+OSD blames hyperedges, matching blames edges); set_decoder
command added for runtime decoder swap.
v2: block_configured carries a query address instead of the inline DEM;
command events and round_started added; correction_applied names qubits."""


class Event(BaseModel):
    """Common envelope for every bus event; concrete subclasses set ``type``."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = SCHEMA_VERSION
    source: str
    tick: int | None = None


class BlockConfigured(Event):
    """A memory block announced itself: summary fields only, kept wire-small.

    Bulk artifacts (the detector error model, the qubit layout) are served
    on request from ``query_address`` — see :mod:`catsim.bus.query`.
    """

    type: Literal["block_configured"] = "block_configured"
    code_name: str
    distance: int
    rounds_per_shot: int
    num_data_qubits: int
    num_logical: int
    noise_name: str
    noise_scale: float = 1.0
    query_address: str


class RoundStarted(Event):
    """A syndrome-extraction round began; the dashboard's frame clock."""

    type: Literal["round_started"] = "round_started"
    shot: int
    round: int


class ErrorInjected(Event):
    """A physical error hit qubits (natural noise or console injection)."""

    type: Literal["error_injected"] = "error_injected"
    shot: int
    round: int
    qubits: list[int]
    pauli: str
    cause: Literal["noise", "injected"] = "injected"


class SyndromeFired(Event):
    """Stabilizer checks flagged this round; ids index detectors in the DEM."""

    type: Literal["syndrome_fired"] = "syndrome_fired"
    shot: int
    round: int
    check_ids: list[int]


class DecodeStarted(Event):
    """The decoder began working on the syndrome history of a shot."""

    type: Literal["decode_started"] = "decode_started"
    shot: int
    round: int


class DecodeFinished(Event):
    """Decode result: measured wall-clock latency plus what the decoder blamed.

    ``identified_qubits`` are the data qubits the decoder holds responsible
    (via the block's served detector-to-qubit geometry); ``matched_detectors``
    holds one detector set per blamed error mechanism — pairs with -1 for the
    boundary from matching decoders, arbitrary-size sets from BP+OSD.
    """

    type: Literal["decode_finished"] = "decode_finished"
    shot: int
    round: int
    latency_s: float
    identified_qubits: list[int]
    matched_detectors: list[list[int]]


class CorrectionApplied(Event):
    """The decoder's Pauli-frame correction: observable flips and blamed qubits."""

    type: Literal["correction_applied"] = "correction_applied"
    shot: int
    round: int
    observables: list[int]
    qubits: list[int] = []


class LogicalError(Event):
    """Decoder prediction disagreed with the true frame: a logical error landed."""

    type: Literal["logical_error"] = "logical_error"
    shot: int
    observables: list[int]


class ShotFinished(Event):
    """A memory shot ended; carries the true observable flips for the verdict."""

    type: Literal["shot_finished"] = "shot_finished"
    shot: int
    actual_flips: list[int]


class RunFinished(Event):
    """The component finished its run; services may drain and stop."""

    type: Literal["run_finished"] = "run_finished"
    shots: int


class IonLost(Event):
    """An ion physically left the trap; the qubit idles maximally mixed."""

    type: Literal["ion_lost"] = "ion_lost"
    qubit: int
    shot: int | None = None
    round: int | None = None


class QubitReplaced(Event):
    """A replacement ion was loaded for a lost one (at block re-init until M3)."""

    type: Literal["qubit_replaced"] = "qubit_replaced"
    qubit: int
    shot: int | None = None


class Command(Event):
    """Base for console/scenario commands: ``target`` names the component id."""

    target: str


class InjectPauli(Command):
    """Apply a deterministic Pauli to qubits at the target's next round."""

    type: Literal["inject_pauli"] = "inject_pauli"
    qubits: list[int]
    pauli: Literal["X", "Y", "Z"]


class InjectLoss(Command):
    """Mark ions as lost at the target's next round."""

    type: Literal["inject_loss"] = "inject_loss"
    qubits: list[int]


class SetNoiseScale(Command):
    """Rescale every noise channel (applied at the next shot boundary)."""

    type: Literal["set_noise_scale"] = "set_noise_scale"
    scale: float = Field(gt=0.0)


class SetPace(Command):
    """Set the wall-clock pause per round (slow motion; 0 = flat out)."""

    type: Literal["set_pace"] = "set_pace"
    tick_seconds: float = Field(ge=0.0)


class SetPaused(Command):
    """Freeze or resume round advancement at the target."""

    type: Literal["set_paused"] = "set_paused"
    paused: bool


class SetDecoder(Command):
    """Swap the target decoder service's implementation at runtime by name."""

    type: Literal["set_decoder"] = "set_decoder"
    name: str


AnyEvent = Annotated[
    (
        BlockConfigured
        | RoundStarted
        | ErrorInjected
        | SyndromeFired
        | DecodeStarted
        | DecodeFinished
        | CorrectionApplied
        | LogicalError
        | ShotFinished
        | RunFinished
        | IonLost
        | QubitReplaced
        | InjectPauli
        | InjectLoss
        | SetNoiseScale
        | SetPace
        | SetPaused
        | SetDecoder
    ),
    Field(discriminator="type"),
]

_ADAPTER: TypeAdapter[AnyEvent] = TypeAdapter(AnyEvent)


def encode_event(event: AnyEvent) -> bytes:
    """Serialize an event to JSON bytes for the wire."""
    return event.model_dump_json().encode()


def decode_event(data: bytes) -> AnyEvent:
    """Parse wire bytes back into the concrete event type via the discriminator."""
    return _ADAPTER.validate_json(data)
