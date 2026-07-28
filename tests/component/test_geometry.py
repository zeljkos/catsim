"""Block geometry: layout completeness and detector/edge attribution."""

import json

import numpy as np
import pymatching
import stim

from catsim.codes import get_code
from catsim.component import DepolarizingNoise, block_layout, build_memory_circuit


def _circuit(noise: DepolarizingNoise, distance: int = 3, rounds: int = 5) -> stim.Circuit:
    return build_memory_circuit(get_code("surface", distance=distance), noise, rounds)


def test_layout_counts_match_the_code(paper_noise: DepolarizingNoise) -> None:
    circuit = _circuit(paper_noise)
    layout = block_layout(circuit)
    assert len(layout.data_qubits) == 9  # d^2
    assert len(layout.check_qubits) == 8  # d^2 - 1
    assert sorted(layout.check_basis.values()).count("X") == 4
    assert not layout.data_qubits.keys() & layout.check_qubits.keys()


def test_every_detector_maps_to_a_check(paper_noise: DepolarizingNoise) -> None:
    circuit = _circuit(paper_noise)
    layout = block_layout(circuit)
    assert set(layout.detector_checks) == set(range(circuit.num_detectors))
    assert set(layout.detector_checks.values()) <= layout.check_qubits.keys()


def test_matched_edges_resolve_to_qubits(busy_noise: DepolarizingNoise) -> None:
    circuit = _circuit(busy_noise)
    layout = block_layout(circuit)
    matching = pymatching.Matching.from_detector_error_model(
        circuit.detector_error_model(decompose_errors=True)
    )
    detectors = circuit.compile_detector_sampler(seed=9).sample(shots=100)
    for row in detectors:
        if not row.any():
            continue
        for a, b in matching.decode_to_edges_array(row.astype(np.uint8)):
            key = frozenset({int(a)} if b == -1 else {int(a), int(b)})
            assert key in layout.edge_qubits
            assert layout.edge_qubits[key], "every edge blames at least one qubit"


def test_layout_json_round_trips(paper_noise: DepolarizingNoise) -> None:
    layout = block_layout(_circuit(paper_noise))
    parsed = json.loads(layout.to_json())
    assert {q["index"] for q in parsed["data_qubits"]} == layout.data_qubits.keys()
    assert {c["index"] for c in parsed["checks"]} == layout.check_qubits.keys()
    assert all(c["basis"] in ("X", "Z") for c in parsed["checks"])
    assert len(parsed["edges"]) == len(layout.edge_qubits)
