"""InterconnectModel: heralded pair bank, sever/restore, queue, handover."""

from catsim.machine import InterconnectConfig, InterconnectModel


def _model(rate: float = 100.0, cap: int = 60) -> InterconnectModel:
    return InterconnectModel(InterconnectConfig(pair_rate_hz=rate, bank_capacity=cap))


def test_bank_fills_to_capacity_and_no_further() -> None:
    model = _model()
    model.advance(10.0, 0.0, active=True)
    assert model.bank == 60.0


def test_inactive_link_neither_fills_nor_serves() -> None:
    model = _model()
    model.advance(10.0, 5.0, active=False)  # one module: there is no link
    assert model.bank == 0.0
    assert model.cross_served == 0.0
    assert model.cross_queue == 0.0


def test_cross_demand_consumes_banked_pairs() -> None:
    model = _model()
    model.advance(1.0, 0.0, active=True)  # bank at capacity (60)
    model.advance(10.0, 3.0, active=True)  # 30 gates vs 60 banked + 1000 inflow
    assert model.cross_served == 30.0
    assert model.cross_queue == 0.0
    assert model.bank == 60.0  # inflow far outpaces demand: bank stays full


def test_severed_link_drains_the_bank_then_queues() -> None:
    model = _model()
    model.advance(1.0, 0.0, active=True)  # bank full at 60
    model.set_severed(True)
    model.advance(40.0, 3.0, active=True)  # 120 gates demanded, 60 banked
    assert model.bank == 0.0
    assert model.cross_served == 60.0
    assert model.cross_queue == 60.0


def test_restore_refills_and_drains_the_queue() -> None:
    model = _model()
    model.advance(1.0, 0.0, active=True)
    model.set_severed(True)
    model.advance(40.0, 3.0, active=True)
    model.set_severed(False)
    model.advance(2.0, 3.0, active=True)  # 200 pairs herald: queue (60) + demand (6)
    assert model.cross_queue == 0.0
    assert model.cross_served == 126.0
    assert model.bank == 60.0  # back at capacity


def test_slow_link_rate_limits_serving() -> None:
    model = _model(rate=1.0)  # below the 3/s cross demand: the link is the bottleneck
    model.advance(10.0, 3.0, active=True)
    assert model.cross_served == 10.0  # served at the pair rate, not the demand rate
    assert model.cross_queue == 20.0


def test_handover_yields_whole_gates_and_carries_fractions() -> None:
    model = _model()
    model.advance(1.0, 0.0, active=True)
    model.advance(0.5, 3.0, active=True)  # 1.5 gates served
    assert model.take_handover() == 1
    model.advance(0.5, 3.0, active=True)  # +1.5 → carry makes 2.0
    assert model.take_handover() == 2
    assert model.take_handover() == 0
