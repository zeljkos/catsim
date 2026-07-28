"""Block geometry extracted from the circuit: what the dashboard and decoder render on.

Exists so detector-to-qubit knowledge lives in the component layer (which owns
the circuit) and is *served* over the query channel — the dashboard renders it
and the decoder maps matched edges through it, neither computing any physics.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import stim

from catsim.component.circuits import memory_detector_error_model, split_into_rounds


@dataclass(frozen=True)
class BlockLayout:
    """Geometry of one memory block, keyed by circuit qubit indices.

    ``detector_checks`` maps every detector id to the check ancilla that
    measured it; ``edge_qubits`` maps each decoder edge (a 1- or 2-detector
    error mechanism) to the data qubits a representative physical error hits.
    """

    data_qubits: dict[int, tuple[float, float]]
    check_qubits: dict[int, tuple[float, float]]
    check_basis: dict[int, str]
    detector_checks: dict[int, int]
    edge_qubits: dict[frozenset[int], tuple[int, ...]]

    def to_json(self) -> str:
        """Serialize for the query channel (edge keys become sorted lists)."""
        return json.dumps(
            {
                "data_qubits": [
                    {"index": q, "x": x, "y": y} for q, (x, y) in sorted(self.data_qubits.items())
                ],
                "checks": [
                    {"index": q, "x": x, "y": y, "basis": self.check_basis.get(q, "?")}
                    for q, (x, y) in sorted(self.check_qubits.items())
                ],
                "detectors": {str(d): a for d, a in sorted(self.detector_checks.items())},
                "edges": [
                    {"detectors": sorted(dets), "qubits": list(qubits)}
                    for dets, qubits in self.edge_qubits.items()
                ],
            }
        )


def block_layout(circuit: stim.Circuit) -> BlockLayout:
    """Extract the renderable geometry of a memory circuit.

    Args:
        circuit: A memory experiment from :func:`build_memory_circuit`.

    Returns:
        The layout; ancillas are the body's MR targets, data qubits the final
        measurement targets, X-checks the ancillas the body Hadamards.
    """
    segments = split_into_rounds(circuit)
    ancillas = _targets(segments.body, "MR")
    data = _targets(segments.final, "M")
    x_checks = _targets(segments.body, "H")
    coords = {q: (xy[0], xy[1]) for q, xy in circuit.get_final_qubit_coordinates().items()}
    return BlockLayout(
        data_qubits={q: coords[q] for q in sorted(data)},
        check_qubits={q: coords[q] for q in sorted(ancillas)},
        check_basis={q: ("X" if q in x_checks else "Z") for q in sorted(ancillas)},
        detector_checks=_detector_checks(circuit, {coords[q]: q for q in ancillas}),
        edge_qubits=_edge_qubits(circuit, data),
    )


def _targets(segment: stim.Circuit, gate: str) -> set[int]:
    """Qubit indices targeted by ``gate`` anywhere in the segment."""
    found: set[int] = set()
    for inst in segment:
        if isinstance(inst, stim.CircuitInstruction) and inst.name == gate:
            found.update(t.value for t in inst.targets_copy())
    return found


def _detector_checks(
    circuit: stim.Circuit, check_at: dict[tuple[float, float], int]
) -> dict[int, int]:
    """Map each detector id to its check ancilla by shared (x, y) coordinate."""
    mapping: dict[int, int] = {}
    for det, coords in circuit.get_detector_coordinates().items():
        ancilla = check_at.get((coords[0], coords[1]))
        if ancilla is not None:
            mapping[det] = ancilla
    return mapping


def _edge_qubits(circuit: stim.Circuit, data: set[int]) -> dict[frozenset[int], tuple[int, ...]]:
    """Map decoder edges (detector sets) to representative culprit data qubits.

    Explanations are keyed by their full detector set (stim dedupes them);
    each decomposed error splits into components at separators, and every
    component (at most two detectors) inherits the error's culprit qubits.
    qLDPC hyperedges never decompose, so each is one component keyed whole —
    the same detector sets a BP+OSD decoder blames.
    """
    dem = memory_detector_error_model(circuit)
    explained = circuit.explain_detector_error_model_errors(
        dem_filter=dem, reduce_to_one_representative_error=True
    )
    qubits_by_set: dict[frozenset[int], tuple[int, ...]] = {}
    for error in explained:
        dets = frozenset(
            t.dem_target.val
            for t in error.dem_error_terms
            if t.dem_target.is_relative_detector_id()
        )
        location = error.circuit_error_locations[0]
        touched = {t.gate_target.value for t in location.flipped_pauli_product}
        qubits_by_set[dets] = tuple(sorted(touched & data)) or tuple(sorted(touched))
    edges: dict[frozenset[int], tuple[int, ...]] = {}
    for instruction in dem.flattened():
        if instruction.type != "error":
            continue
        targets = instruction.targets_copy()
        full = frozenset(t.val for t in targets if t.is_relative_detector_id())
        qubits = qubits_by_set.get(full, ())
        component: set[int] = set()
        for target in [*targets, None]:
            if target is None or target.is_separator():
                if component:
                    edges.setdefault(frozenset(component), qubits)
                component = set()
            elif target.is_relative_detector_id():
                component.add(target.val)
    return edges
