"""Dashboard backend: config, endpoints, command publishing, and the event relay."""

import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from catsim.bus import BusProxy, InjectPauli, RoundStarted, ZmqSubscriber
from catsim.dashboard import DashboardConfig, EventHub, create_app, load_dashboard_config
from tests.conftest import REPO_ROOT


def test_shipped_config_loads() -> None:
    config = load_dashboard_config(REPO_ROOT / "configs" / "dashboard.yaml")
    assert config.ring_buffer_rounds >= 2
    assert 6 in config.pace_presets_ms, "the paper's real SEC must be a preset"
    assert config.machine_accent == "#E8701A"


@pytest.fixture
def stack() -> Iterator[tuple[TestClient, BusProxy, ZmqSubscriber]]:
    """A dashboard app over a real bus proxy, plus a spy subscriber."""
    proxy = BusProxy()
    proxy.start()
    spy = ZmqSubscriber(proxy.backend_address)
    config = DashboardConfig(scenario_dir=REPO_ROOT / "configs" / "scenarios")
    app = create_app(
        config,
        frontend_address=proxy.frontend_address,
        backend_address=proxy.backend_address,
    )
    with TestClient(app) as client:
        time.sleep(0.3)  # slow-joiner: let subscriptions propagate
        yield client, proxy, spy
    spy.close()
    proxy.stop()


def test_index_and_config(stack: tuple[TestClient, BusProxy, ZmqSubscriber]) -> None:
    client, _, _ = stack
    assert "block view" in client.get("/").text
    config = client.get("/api/config").json()
    assert config["panels"]["block_view"] is True
    assert config["ring_buffer_rounds"] >= 2


def test_scenarios_listed_and_unknown_404(
    stack: tuple[TestClient, BusProxy, ZmqSubscriber],
) -> None:
    client, _, _ = stack
    names = {s["name"] for s in client.get("/api/scenarios").json()}
    assert {"single-decoherence", "beyond-distance"} <= names
    assert client.post("/api/scenarios/not-a-scenario").status_code == 404


def test_layout_before_any_block_is_503(
    stack: tuple[TestClient, BusProxy, ZmqSubscriber],
) -> None:
    client, _, _ = stack
    assert client.get("/api/layout").status_code == 503


def test_command_is_validated_and_published(
    stack: tuple[TestClient, BusProxy, ZmqSubscriber],
) -> None:
    client, _, spy = stack
    body = {
        "type": "inject_pauli",
        "source": "dashboard",
        "target": "block0",
        "qubits": [5],
        "pauli": "X",
    }
    assert client.post("/api/command", json=body).status_code == 200
    received = None
    deadline = time.monotonic() + 2.0
    while received is None and time.monotonic() < deadline:
        received = spy.receive(timeout_s=0.1)
    assert isinstance(received, InjectPauli)
    assert received.qubits == [5]


def test_non_command_events_are_rejected(
    stack: tuple[TestClient, BusProxy, ZmqSubscriber],
) -> None:
    client, _, _ = stack
    body = {"type": "round_started", "source": "dashboard", "shot": 0, "round": 1}
    assert client.post("/api/command", json=body).status_code == 422
    assert client.post("/api/command", content=b"not json").status_code == 422


def test_hub_fanout_and_bootstrap_replay() -> None:
    import asyncio

    async def scenario() -> None:
        hub = EventHub()
        hub.attach_loop(asyncio.get_running_loop())  # no pump thread needed
        queue = hub.register()
        hub.dispatch(RoundStarted(source="block0", shot=0, round=1))
        await asyncio.sleep(0)  # let call_soon_threadsafe land
        assert "round_started" in await asyncio.wait_for(queue.get(), 1.0)
        hub.unregister(queue)

    asyncio.run(scenario())
