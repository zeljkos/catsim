"""Machine-layer event schemas — the M5/M7 slice of the bus contract.

Exists so the machine view renders the tiled machine from bus events alone:
chip announcements carry composition plus paper-accounting totals (Table V
prices next to the nominal label), periodic statuses carry health, buffers,
queues, and the predicted-vs-measured panel's numbers. M7 adds module
membership on every chip event and the photonic-interconnect roll-up.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from catsim.bus.events import Event

ComponentState = Literal["ok", "degraded", "stalled", "down"]

ChipRole = Literal["memory", "factory"]
"""What a chip contributes: qLDPC memory blocks, or magic-state factories."""

ChipMode = Literal["behavioral", "live"]
"""Fidelity dial: calibrated SimPy loops (cheap, the fleet default) or the
full stim + decoder stack (the drill-down focus chip)."""


class BlockAssignment(BaseModel):
    """One memory block in a chip assignment: which registered code it runs."""

    model_config = ConfigDict(frozen=True)

    family: str = "bb"
    code: str = "q70"


class BlockAccounting(BaseModel):
    """One memory block's composition line in a chip announcement."""

    model_config = ConfigDict(frozen=True)

    block_id: str
    code_name: str
    num_logical: int
    memory_qubits: int
    cat_qubits: int


class BlockHealth(BaseModel):
    """One memory block's live condition in a chip status."""

    model_config = ConfigDict(frozen=True)

    block_id: str
    state: ComponentState
    rounds: int = Field(ge=0)
    stalled_rounds: int = Field(ge=0)
    cat_buffer: int = Field(ge=0)
    cat_buffer_capacity: int = Field(ge=0)


class FactoryHealth(BaseModel):
    """One factory's live condition in a chip status."""

    model_config = ConfigDict(frozen=True)

    source: str
    kind: str
    state: ComponentState


class ChipConfigured(Event):
    """A chip announced itself: composition and qubit accounting.

    ``paper_qubits`` prices the composition with arXiv:2604.19481 Table V
    all-in costs; it sits next to ``nominal_qubits`` (the roadmap label) so
    accounting divergence is displayed, never hidden. ``accounting_note``
    documents the divergence when the two disagree.
    """

    type: Literal["chip_configured"] = "chip_configured"
    chip_id: str
    role: ChipRole = "memory"
    module: str = "A"
    machine_name: str
    nominal_qubits: int
    paper_qubits: int
    logical_qubits: int
    accounting: Literal["paper", "lean"]
    accounting_note: str = ""
    blocks: list[BlockAccounting]
    magic_factories: list[str] = []


class ChipStatus(Event):
    """Periodic per-chip health: block stalls, cat buffers, factory states.

    ``role``/``mode`` make the fleet's fidelity dial visible per chip; the
    ``t_*`` counters and ``machine_seconds`` let the scheduler aggregate
    measured throughput without knowing any chip's internals.
    """

    type: Literal["chip_status"] = "chip_status"
    chip_id: str
    state: ComponentState
    role: ChipRole = "memory"
    mode: ChipMode = "live"
    module: str = "A"
    blocks: list[BlockHealth]
    factories: list[FactoryHealth]
    utilization: float = Field(ge=0.0, le=1.0)
    machine_seconds: float = Field(default=0.0, ge=0.0)
    t_queue_depth: int = Field(default=0, ge=0)
    t_done: int = Field(default=0, ge=0)


class MachineStatus(Event):
    """Periodic machine roll-up: capacity, throughput, predicted vs measured.

    Predictions are the paper's Table I arithmetic evaluated for the current
    composition (Table V prices, Table VII gate times); measured values come
    from the live model and bus events. Divergence is a finding to surface.
    """

    type: Literal["machine_status"] = "machine_status"
    chips: int = Field(ge=0)
    lost_chips: int = Field(default=0, ge=0)
    modules: int = Field(default=1, ge=1)
    logical_qubits: int = Field(ge=0)
    physical_qubits_nominal: int = Field(ge=0)
    physical_qubits_paper: int = Field(ge=0)
    predicted_t_per_day: float = Field(ge=0.0)
    measured_t_per_day: float = Field(ge=0.0)
    t_queue_depth: int = Field(ge=0)
    t_stall_reason: str = ""
    machine_seconds: float = Field(ge=0.0)
    measured_shots: int = Field(default=0, ge=0)
    measured_logical_errors: int = Field(default=0, ge=0)
    logical_error_per_logical_per_shot: float = Field(default=0.0, ge=0.0)


class InterconnectStatus(Event):
    """Periodic photonic-interconnect roll-up (M7); published with ≥2 modules.

    The link parameters echoed here (``pair_rate_hz``, ``latency_s``,
    ``bank_capacity``) are ASSUMPTIONS from the machine config, NOT from the
    paper — the dashboard must present them as assumed. Cross-module traffic
    is a first-class metric: served T gates ride banked pairs; when the link
    is severed the bank drains and ``cross_queue_depth`` grows.
    """

    type: Literal["interconnect_status"] = "interconnect_status"
    modules: int = Field(ge=1)
    severed: bool = False
    bank: int = Field(ge=0)
    bank_capacity: int = Field(gt=0)
    pair_rate_hz: float = Field(gt=0.0)
    latency_s: float = Field(ge=0.0)
    cross_demand_per_second: float = Field(ge=0.0)
    cross_t_served: int = Field(default=0, ge=0)
    cross_queue_depth: int = Field(default=0, ge=0)
