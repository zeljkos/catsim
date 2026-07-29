"""Fleet state shared by the scheduler and its roll-up: chip records, status.

Exists so the scheduler stays a membership-and-assignment service (size
discipline): what the scheduler *knows* about a chip lives here as a record,
and the machine roll-up — the paper's Table I arithmetic evaluated for the
current fleet next to the measured aggregates — is built here from those
records plus the ledger.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from catsim.bus import BlockAssignment, ChipStatus, MachineStatus
from catsim.machine.ledger import FleetLedger
from catsim.machine.prediction import predict_machine
from catsim.machine.pricing import MEMORY_BLOCK_LOGICAL

_DAY_SECONDS = 86_400.0

DEMAND_LIMITED = "demand-limited: factory capacity exceeds the workload"
"""Attribution when factories exist and outpace the configured T demand."""


@dataclass
class ChipRecord:
    """The scheduler's view of one registered chip."""

    instance_id: str
    chip_id: str
    role: str
    mode: str
    module: str
    blocks: list[BlockAssignment]
    magic_factories: list[str]
    nominal_qubits: int
    modes: list[str]
    last_seen: float
    status: ChipStatus | None = None
    neighbors: list[str] = field(default_factory=list)

    @property
    def logical_qubits(self) -> int:
        """Logical qubits this chip's memory blocks host."""
        return sum(MEMORY_BLOCK_LOGICAL[b.code] for b in self.blocks)


def build_machine_status(
    source: str,
    chips: list[ChipRecord],
    *,
    lost_chips: int,
    modules: int,
    focus_logical: int,
    demand_t_per_second: float,
    machine_seconds: float,
    ledger: FleetLedger,
) -> MachineStatus:
    """The machine roll-up: paper prediction vs live measurement for the fleet."""
    block_codes = [b.code for c in chips for b in c.blocks]
    magic = [kind for c in chips for kind in c.magic_factories]
    prediction = predict_machine(block_codes, [MEMORY_BLOCK_LOGICAL[c] for c in block_codes], magic)
    paper_qubits = prediction.physical_qubits if chips else 0  # no reservoir-only ghost
    statuses = [c.status for c in chips if c.status is not None]
    measured_t_per_day = sum(
        s.t_done / s.machine_seconds * _DAY_SECONDS for s in statuses if s.machine_seconds > 0
    )
    stall = prediction.t_stall_reason
    if not stall and prediction.t_per_day > demand_t_per_second * _DAY_SECONDS:
        stall = DEMAND_LIMITED
    shots, errors = ledger.shots, ledger.logical_errors
    return MachineStatus(
        source=source,
        chips=len(chips),
        lost_chips=lost_chips,
        modules=modules,
        logical_qubits=prediction.logical_qubits,
        physical_qubits_nominal=sum(c.nominal_qubits for c in chips),
        physical_qubits_paper=paper_qubits,
        predicted_t_per_day=prediction.t_per_day,
        measured_t_per_day=measured_t_per_day,
        t_queue_depth=ledger.pending + sum(s.t_queue_depth for s in statuses),
        t_stall_reason=stall,
        machine_seconds=machine_seconds,
        measured_shots=shots,
        measured_logical_errors=errors,
        logical_error_per_logical_per_shot=(
            errors / (shots * focus_logical) if shots and focus_logical else 0.0
        ),
    )
