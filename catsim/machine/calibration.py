"""Machine-model calibration: paper timing constants + M1–M4 measured baselines.

Exists so every number driving the SimPy layer is either cited to
arXiv:2604.19481 or pinned to a measurement made by this repo (M3 factory
acceptance, M4 decoder latency) — never invented. Live runs override the
measured values with the current bus measurements as they stream in.
"""

from __future__ import annotations

from dataclasses import dataclass

SEC_SECONDS = 0.006
"""Syndrome-extraction cycle: 30 POC x 200 µs (arXiv:2604.19481; CLAUDE.md
canonical parameters). The machine model's clock tick."""

T_PAIR_SECONDS = {
    # Table VII "T gate x2": time to consume one magic-state pair as two T
    # gates, keyed by (memory code, factory kind). CH2 uses the double T gate,
    # MEK two consecutive T gates.
    ("q70", "ch2"): 0.1507,
    ("q102", "ch2"): 0.1652,
    ("q70", "mek"): 0.4000,
    ("q102", "mek"): 0.4297,
}

CAT_ACCEPTANCE_BASELINE = 0.998
"""M3 measured cat-factory acceptance under paper noise (seeded baselines in
tests/component/test_factory.py: 99.8–99.97%). Live runs replace this with the
cat service's streaming measured rate."""


@dataclass(frozen=True)
class Calibration:
    """The knobs the machine model runs on; defaults are the cited constants."""

    sec_seconds: float = SEC_SECONDS
    cat_acceptance: float = CAT_ACCEPTANCE_BASELINE


def t_pair_seconds(memory_code: str, factory_kind: str) -> float:
    """Table VII double-T time for a factory serving a memory code.

    Raises:
        KeyError: If the (code, factory) pair has no published time.
    """
    key = (memory_code, factory_kind)
    if key not in T_PAIR_SECONDS:
        raise KeyError(f"no Table VII T-pair time for {key}; known: {sorted(T_PAIR_SECONDS)}")
    return T_PAIR_SECONDS[key]
