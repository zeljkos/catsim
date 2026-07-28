"""Bus contract tests: schema round-trips, ZeroMQ delivery, and the query channel."""

import time

import pytest

from catsim import bus

EVENTS: list[bus.AnyEvent] = [
    bus.BlockConfigured(
        source="b0",
        tick=0,
        code_name="surface-d3",
        distance=3,
        rounds_per_shot=5,
        num_data_qubits=9,
        num_logical=1,
        noise_name="paper-baseline",
        noise_scale=1.0,
        query_address="tcp://127.0.0.1:5599",
    ),
    bus.RoundStarted(source="b0", shot=0, round=1),
    bus.ErrorInjected(source="b0", shot=0, round=1, qubits=[4], pauli="Z", cause="noise"),
    bus.SyndromeFired(source="b0", tick=3, shot=0, round=1, check_ids=[2, 7]),
    bus.DecodeStarted(source="d0", shot=0, round=1),
    bus.DecodeFinished(
        source="d0",
        shot=0,
        round=1,
        latency_s=0.0012,
        identified_qubits=[5],
        matched_detectors=[(2, 7), (3, -1)],
    ),
    bus.CorrectionApplied(source="d0", shot=0, round=1, observables=[0], qubits=[5]),
    bus.LogicalError(source="d0", shot=0, observables=[0]),
    bus.ShotFinished(source="b0", shot=0, actual_flips=[0]),
    bus.RunFinished(source="b0", shots=10),
    bus.IonLost(source="b0", qubit=12, shot=0, round=2),
    bus.QubitReplaced(source="b0", qubit=12, shot=0),
    bus.InjectPauli(source="dash", target="b0", qubits=[4], pauli="X"),
    bus.InjectLoss(source="dash", target="b0", qubits=[4]),
    bus.SetNoiseScale(source="dash", target="b0", scale=10.0),
    bus.SetPace(source="dash", target="b0", tick_seconds=0.5),
    bus.SetPaused(source="dash", target="b0", paused=True),
]


@pytest.mark.parametrize("event", EVENTS, ids=lambda e: str(e.type))
def test_event_round_trip(event: bus.AnyEvent) -> None:
    assert bus.decode_event(bus.encode_event(event)) == event


def test_schema_version_stamped() -> None:
    assert bus.RunFinished(source="x", shots=1).schema_version == bus.SCHEMA_VERSION


def test_events_are_frozen() -> None:
    event = bus.RunFinished(source="x", shots=1)
    with pytest.raises(Exception, match="frozen"):
        event.shots = 2


def test_commands_are_commands() -> None:
    for event in EVENTS:
        assert isinstance(event, bus.Command) == event.type.startswith(("inject_", "set_"))


def test_zmq_pub_sub_through_proxy() -> None:
    proxy = bus.BusProxy()
    proxy.start()
    sub = bus.ZmqSubscriber(proxy.backend_address, prefix="b0")
    pub = bus.ZmqPublisher(proxy.frontend_address)
    try:
        time.sleep(0.3)  # slow-joiner: let the subscription propagate
        sent = bus.SyndromeFired(source="b0", tick=1, shot=0, round=1, check_ids=[1])
        pub.publish(sent)
        received = None
        deadline = time.monotonic() + 2.0
        while received is None and time.monotonic() < deadline:
            received = sub.receive(timeout_s=0.1)
        assert received == sent
    finally:
        pub.close()
        sub.close()
        proxy.stop()


def test_query_server_round_trip() -> None:
    server = bus.QueryServer({"dem": lambda: "detector D0", "layout": lambda: "{}"})
    try:
        assert bus.query(server.address, "dem") == "detector D0"
        assert bus.query(server.address, "layout") == "{}"
    finally:
        server.close()


def test_query_unknown_name_raises() -> None:
    server = bus.QueryServer({"dem": lambda: "x"})
    try:
        with pytest.raises(bus.QueryError, match="unknown query"):
            bus.query(server.address, "nope")
    finally:
        server.close()


def test_query_handlers_see_live_state() -> None:
    state = {"value": "before"}
    server = bus.QueryServer({"state": lambda: state["value"]})
    try:
        assert bus.query(server.address, "state") == "before"
        state["value"] = "after"
        assert bus.query(server.address, "state") == "after"
    finally:
        server.close()
