"""Elastic-runtime event schemas — the M6 slice of the bus contract.

Exists so the machine is whatever chips are currently registered: a booting
chip container knows only the bus address and announces itself; the scheduler
admits it with an identity, a role, and a fidelity mode; heartbeats keep it
registered; the provisioner grows and drains the fleet on exactly two
commands. Scaling and failure share this one vocabulary.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from catsim.bus.events import Command, Event
from catsim.bus.machine_events import BlockAssignment, ChipMode, ChipRole


class ChipAnnounce(Event):
    """A chip container booted and asks to join; ``source`` is its instance id.

    The instance id is transport identity (assigned by whoever started the
    container); the scheduler answers with the machine identity (``chip_id``)
    in :class:`ChipAdmitted`.
    """

    type: Literal["chip_announce"] = "chip_announce"
    nominal_qubits: int = Field(gt=0)
    modes: list[ChipMode] = ["behavioral", "live"]


class ChipAdmitted(Command):
    """The scheduler's assignment to one instance (``target`` = instance id).

    Also re-sent to an already-admitted chip when the fleet rebalances: the
    chip applies the new role/composition/demand in place. ``mode`` selects
    the fidelity dial position — ``live`` runs the full stim+decoder stack,
    ``behavioral`` runs the calibrated SimPy loops only.
    """

    type: Literal["chip_admitted"] = "chip_admitted"
    chip_id: str
    role: ChipRole
    mode: ChipMode
    blocks: list[BlockAssignment] = []
    magic_factories: list[str] = []
    t_demand_per_second: float = Field(default=0.0, ge=0.0)
    t_backlog: int = Field(default=0, ge=0)
    """T gates already owed when the assignment lands (the queue that built up
    while the fleet had no factory chip); the chip adds it to its local queue."""
    bell_neighbors: list[str] = []


class ChipHeartbeat(Event):
    """Periodic liveness beacon from an admitted chip (``source`` = chip id)."""

    type: Literal["chip_heartbeat"] = "chip_heartbeat"
    seq: int = Field(ge=0)
    mode: ChipMode


class ChipLost(Event):
    """The scheduler declared a chip dead after missed heartbeats."""

    type: Literal["chip_lost"] = "chip_lost"
    chip_id: str
    reason: str = "missed heartbeats"


class ChipLeft(Event):
    """A chip left gracefully (drain path); published just before it exits."""

    type: Literal["chip_left"] = "chip_left"
    chip_id: str


class ScaleUp(Command):
    """Grow the fleet by ``n`` chips (``target`` = the provisioner)."""

    type: Literal["scale_up"] = "scale_up"
    n: int = Field(ge=1)


class Drain(Command):
    """Retire one named chip, or the ``n`` newest (``target`` = the provisioner)."""

    type: Literal["drain"] = "drain"
    chip_id: str | None = None
    n: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _exactly_one(self) -> Drain:
        """A drain names a chip or a count, never both and never neither."""
        if (self.chip_id is None) == (self.n is None):
            raise ValueError("drain takes exactly one of chip_id or n")
        return self


class StopChip(Command):
    """Ask one chip to leave gracefully (``target`` = chip id, or ``*``)."""

    type: Literal["stop_chip"] = "stop_chip"


class SetChipMode(Command):
    """Move one chip's fidelity dial (``target`` = chip id)."""

    type: Literal["set_chip_mode"] = "set_chip_mode"
    mode: ChipMode


class SetFocus(Command):
    """Make one chip the live drill-down focus (``target`` = the scheduler).

    The scheduler answers with :class:`SetChipMode` pairs: the previous focus
    drops to behavioral, the named chip goes live.
    """

    type: Literal["set_focus"] = "set_focus"
    chip_id: str
