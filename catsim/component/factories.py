"""Cat, Bell, and magic (MEK Clifford skeleton) factory circuits.

Exists so the paper's factory organs (arXiv:2604.19481: cat states drive
syndrome extraction, verified Bell pairs link blocks, the MEK scheme feeds
T gates) run through one FactoryCircuit shape: noisy preparation, noisy
verification checks the service post-selects on, then a noiseless truth
oracle grading what post-selection actually delivered.

Documented divergences from the paper (surfaced, never tuned away):
- Verification is a single round of parity checks, not the paper's full
  flagged/repeated verification schedules — acceptance rates here are
  therefore optimistic upper bounds at equal noise.
- The truth oracle (final noiseless MPP stabilizer readouts) is simulation
  instrumentation, not physical circuitry: it grades accepted outputs so the
  bus can report undetected-error rates.
- Magic factory: only the Clifford checking circuitry is simulated, exactly;
  the non-Clifford magic state is a stand-in ``|+>`` proxy, and the accepted
  output is a token carrying the oracle's residual-error estimate (charter
  boundary — no non-Clifford simulation).
"""

from __future__ import annotations

import stim

from catsim.component.factory import FactoryCircuit, register_factory
from catsim.component.noise import NoiseModel

_CAT_SIZE = 4
"""Ions per cat state. The paper's cat states span one check's support;
4 matches the typical check weight of the shipped codes."""

_MAGIC_INPUTS = 5
"""Proxy inputs per magic-state check round (a 5-to-1 style skeleton)."""


def _reset(c: stim.Circuit, noise: NoiseModel, qubits: list[int]) -> None:
    """Reset ``qubits`` with the noise model's reset flip probability."""
    c.append("R", qubits)
    if noise.reset_error > 0:
        c.append("X_ERROR", qubits, noise.reset_error)


def _h(c: stim.Circuit, noise: NoiseModel, qubits: list[int]) -> None:
    """Hadamard ``qubits`` with single-qubit depolarization after."""
    c.append("H", qubits)
    if noise.single_qubit_gate_error > 0:
        c.append("DEPOLARIZE1", qubits, noise.single_qubit_gate_error)


def _cx(c: stim.Circuit, noise: NoiseModel, pairs: list[int]) -> None:
    """CNOT the (control, target) pair list with two-qubit depolarization after."""
    c.append("CX", pairs)
    if noise.two_qubit_gate_error > 0:
        c.append("DEPOLARIZE2", pairs, noise.two_qubit_gate_error)


def _measure_checks(c: stim.Circuit, noise: NoiseModel, ancillas: list[int]) -> int:
    """Measure verification ancillas (noisy) and detect each outcome.

    Returns:
        The number of verification detectors appended.
    """
    if noise.measurement_error > 0:
        c.append("X_ERROR", ancillas, noise.measurement_error)
    c.append("M", ancillas)
    for i in range(len(ancillas)):
        c.append("DETECTOR", [stim.target_rec(-len(ancillas) + i)])
    return len(ancillas)


def _truth_oracle(c: stim.Circuit, stabilizers: list[str]) -> None:
    """Append noiseless MPP readouts of the ideal-output stabilizers.

    Simulation-only instrumentation: grades what post-selection delivered so
    accepted-but-errored outputs are counted, never physical circuitry.
    """
    for product in stabilizers:
        c.append_from_stim_program_text(f"MPP {product}")
        c.append("DETECTOR", [stim.target_rec(-1)])


def build_cat_factory(noise: NoiseModel) -> FactoryCircuit:
    """Cat-state preparation + verification (arXiv:2604.19481, cat factory).

    Prepares an n-ion cat state with an H + CNOT ladder, then verifies with
    one ancilla-measured ZZ parity per adjacent pair, post-selecting on all
    parities even — the bit-flip errors the ladder can propagate are exactly
    what these checks catch. Phase errors are invisible to ZZ verification
    (physically true for cat states; downstream they act as syndrome
    measurement errors, absorbed by repetition) — the truth oracle's X⊗n
    readout counts them as residual output errors instead of hiding them.
    """
    n = _CAT_SIZE
    data = list(range(n))
    ancillas = [n + i for i in range(n - 1)]
    c = stim.Circuit()
    _reset(c, noise, data + ancillas)
    _h(c, noise, [0])
    for i in range(n - 1):
        _cx(c, noise, [i, i + 1])
    for i, a in enumerate(ancillas):
        _cx(c, noise, [i, a])
        _cx(c, noise, [i + 1, a])
    checks = _measure_checks(c, noise, ancillas)
    xall = "*".join(f"X{q}" for q in data)
    _truth_oracle(c, [xall] + [f"Z{i}*Z{i + 1}" for i in range(n - 1)])
    return FactoryCircuit(kind="cat", circuit=c, num_verification=checks, output_qubits=tuple(data))


def build_bell_factory(noise: NoiseModel) -> FactoryCircuit:
    """Bell-pair preparation + verification (arXiv:2604.19481, Bell factory).

    Prepares two noisy Bell pairs and spends one to check the other — the
    standard bilateral-CNOT purification step (a single round of the paper's
    verified Bell-pair scheme): CNOTs from the kept pair onto the sacrificial
    pair, whose Z measurements must agree. Post-selecting on even parity
    catches bit-flip disagreements; the truth oracle reads the kept pair's
    XX and ZZ stabilizers to grade what survived.
    """
    kept, spent = [0, 1], [2, 3]
    c = stim.Circuit()
    _reset(c, noise, kept + spent)
    _h(c, noise, [kept[0], spent[0]])
    _cx(c, noise, [kept[0], kept[1]])
    _cx(c, noise, [spent[0], spent[1]])
    _cx(c, noise, [kept[0], spent[0]])
    _cx(c, noise, [kept[1], spent[1]])
    if noise.measurement_error > 0:
        c.append("X_ERROR", spent, noise.measurement_error)
    c.append("M", spent)
    c.append("DETECTOR", [stim.target_rec(-1), stim.target_rec(-2)])
    _truth_oracle(c, [f"X{kept[0]}*X{kept[1]}", f"Z{kept[0]}*Z{kept[1]}"])
    return FactoryCircuit(kind="bell", circuit=c, num_verification=1, output_qubits=(0, 1))


def build_magic_factory(noise: NoiseModel) -> FactoryCircuit:
    """Clifford skeleton of the MEK magic-state scheme (arXiv:2604.19481).

    Simulates ONLY the checking circuitry, exactly: the non-Clifford magic
    inputs are ``|+>`` proxies (the standard stabilizer stand-in), and each
    verification ancilla measures an XX parity between the output proxy and
    one other input — deterministic for ideal inputs and flipped by exactly
    the Z-type deviations magic-state checks exist to catch. The accepted
    output is a token: the truth oracle's X readout of the output proxy is
    its measured residual-error estimate, and nothing non-Clifford is ever
    simulated (charter boundary).
    """
    inputs = list(range(_MAGIC_INPUTS))
    ancillas = [_MAGIC_INPUTS + i for i in range(_MAGIC_INPUTS - 1)]
    c = stim.Circuit()
    _reset(c, noise, inputs + ancillas)
    _h(c, noise, inputs)
    for i, a in enumerate(ancillas):
        _h(c, noise, [a])
        _cx(c, noise, [a, 0])
        _cx(c, noise, [a, i + 1])
        _h(c, noise, [a])
    checks = _measure_checks(c, noise, ancillas)
    _truth_oracle(c, ["X0"])
    return FactoryCircuit(kind="magic", circuit=c, num_verification=checks, output_qubits=(0,))


register_factory("cat", build_cat_factory)
register_factory("bell", build_bell_factory)
register_factory("magic", build_magic_factory)
