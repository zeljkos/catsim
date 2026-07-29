"""The full event union and its wire codec (JSON, discriminated by ``type``).

Exists as the one place every concrete event model is enumerated, so the
transport and every subscriber decode any bus payload into its exact type.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, TypeAdapter

from catsim.bus.events import (
    BlockConfigured,
    CorrectionApplied,
    DecodeFinished,
    DecodeQueue,
    DecodeStarted,
    ErrorInjected,
    InjectLoss,
    InjectPauli,
    IonLost,
    LogicalError,
    QubitReplaced,
    RoundStarted,
    RunFinished,
    SetDecoder,
    SetDecoderSlowdown,
    SetNoiseScale,
    SetPace,
    SetPaused,
    ShotFinished,
    SyndromeFired,
)
from catsim.bus.factory_events import (
    FactoryAccepted,
    FactoryAttempt,
    FactoryConfigured,
    FactoryRejected,
    LossDetected,
    ReplacementDispatched,
    ReplacementReady,
)
from catsim.bus.fleet_events import (
    AddModule,
    ChipAdmitted,
    ChipAnnounce,
    ChipHeartbeat,
    ChipLeft,
    ChipLost,
    Drain,
    ScaleUp,
    SetChipMode,
    SetFocus,
    SetInterconnect,
    StopChip,
)
from catsim.bus.machine_events import (
    ChipConfigured,
    ChipStatus,
    InterconnectStatus,
    MachineStatus,
)

AnyEvent = Annotated[
    (
        BlockConfigured
        | RoundStarted
        | ErrorInjected
        | SyndromeFired
        | DecodeStarted
        | DecodeFinished
        | DecodeQueue
        | CorrectionApplied
        | LogicalError
        | ShotFinished
        | RunFinished
        | IonLost
        | QubitReplaced
        | FactoryConfigured
        | FactoryAttempt
        | FactoryAccepted
        | FactoryRejected
        | LossDetected
        | ReplacementDispatched
        | ReplacementReady
        | ChipConfigured
        | ChipStatus
        | MachineStatus
        | InterconnectStatus
        | ChipAnnounce
        | ChipHeartbeat
        | ChipLost
        | ChipLeft
        | ChipAdmitted
        | ScaleUp
        | Drain
        | StopChip
        | SetChipMode
        | SetFocus
        | AddModule
        | SetInterconnect
        | InjectPauli
        | InjectLoss
        | SetNoiseScale
        | SetPace
        | SetPaused
        | SetDecoder
        | SetDecoderSlowdown
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
