"""Table I arithmetic pins: predictions reproduce the paper's published rows.

Physical totals count Table V's memory/cat/magic/reservoir columns; the
paper's rows additionally include Bell pairs and transport lanes (~8%), which
scale machine-wide, not per chip — the exclusion is documented in pricing.
"""

from catsim.machine import predict_machine
from catsim.machine.prediction import NO_MAGIC_FACTORY


def test_table_i_5xq102_1xch2() -> None:
    p = predict_machine(["q102"] * 5, [22] * 5, ["ch2"])
    assert p.logical_qubits == 110  # Table I: 110
    assert p.t_per_day == 2 * 86_400 / 0.1652  # Table VII; Table I rounds to 1.0M
    assert abs(p.t_per_day - 1.0e6) / 1.0e6 < 0.05
    # Table I total 2,514 incl. Bell (24) + transport (129); counted columns:
    assert p.physical_qubits == 5 * 316 + 5 * 82 + 173 + 200
    assert p.t_stall_reason == ""


def test_table_i_17xq70_1xch2() -> None:
    p = predict_machine(["q70"] * 17, [6] * 17, ["ch2"])
    assert p.logical_qubits == 102  # Table I: 102
    assert abs(p.t_per_day - 1.1e6) / 1.1e6 < 0.05  # Table I: 1.1M


def test_table_i_17xq70_3xmek() -> None:
    p = predict_machine(["q70"] * 17, [6] * 17, ["mek"] * 3)
    assert p.t_per_day == 3 * 2 * 86_400 / 0.4000
    assert abs(p.t_per_day - 1.3e6) / 1.3e6 < 0.01  # Table I: 1.3M


def test_memory_only_machine_stalls_with_attribution() -> None:
    p = predict_machine(["q70"], [6], [])
    assert p.t_per_day == 0.0
    assert p.t_stall_reason == NO_MAGIC_FACTORY
    assert p.logical_qubits == 6
    assert p.physical_qubits == 262 + 200
