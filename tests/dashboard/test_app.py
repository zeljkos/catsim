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
    assert config.panels.factories is True, "M3: the factories panel ships enabled"
    assert config.panels.decoder is True, "M4: the decoder race panel ships enabled"
    assert config.decoder_panel.budget_ms == 6.0, "the paper's SEC budget is the line"
    assert config.decoder_slowdown.max > 1.0
    assert set(config.demo_mode.log_filter) == {
        "error_injected",
        "decode_finished",
        "logical_error",
    }


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


def test_hub_replays_factory_announcements_to_late_joiners() -> None:
    import asyncio

    from catsim.bus import FactoryConfigured

    async def scenario() -> None:
        hub = EventHub()
        hub.attach_loop(asyncio.get_running_loop())
        hub.dispatch(
            FactoryConfigured(source="cat0", kind="cat", output_qubits=4, verification_checks=3)
        )
        late = hub.register()
        assert "factory_configured" in late.get_nowait()
        hub.unregister(late)

    asyncio.run(scenario())


def test_shipped_config_parses_machine_panel_and_scale_presets() -> None:
    config = load_dashboard_config(REPO_ROOT / "configs" / "dashboard.yaml")
    assert config.panels.machine is True, "M5: the machine view ships enabled"
    chips = [p.chips for p in config.scale_presets]
    assert chips == [1, 40, 80], "roadmap presets are display sugar defined only here"


def test_hub_replays_machine_announcements_to_late_joiners() -> None:
    import asyncio

    from catsim.bus import BlockAccounting, ChipConfigured, MachineStatus

    chip = ChipConfigured(
        source="machine0",
        chip_id="chip0",
        machine_name="chip-256",
        nominal_qubits=256,
        paper_qubits=262,
        logical_qubits=6,
        accounting="paper",
        blocks=[
            BlockAccounting(
                block_id="block0", code_name="q70", num_logical=6, memory_qubits=220, cat_qubits=42
            )
        ],
    )
    status = MachineStatus(
        source="machine0",
        chips=1,
        logical_qubits=6,
        physical_qubits_nominal=256,
        physical_qubits_paper=462,
        predicted_t_per_day=0.0,
        measured_t_per_day=0.0,
        t_queue_depth=3,
        machine_seconds=1.0,
    )

    async def scenario() -> None:
        hub = EventHub()
        hub.attach_loop(asyncio.get_running_loop())
        hub.dispatch(chip)
        hub.dispatch(status)
        late = hub.register()
        replayed = [late.get_nowait(), late.get_nowait()]
        assert any("chip_configured" in r for r in replayed)
        assert any("machine_status" in r for r in replayed)
        hub.unregister(late)

    asyncio.run(scenario())


def test_fleet_commands_pass_the_command_endpoint(
    stack: tuple[TestClient, BusProxy, ZmqSubscriber],
) -> None:
    client, _, spy = stack
    for body in (
        {"type": "scale_up", "source": "dashboard", "target": "provisioner", "n": 39},
        {"type": "drain", "source": "dashboard", "target": "provisioner", "n": 2},
        {"type": "set_focus", "source": "dashboard", "target": "scheduler", "chip_id": "chip3"},
    ):
        assert client.post("/api/command", json=body).status_code == 200, body["type"]
    received: list[str] = []
    deadline = time.monotonic() + 2.0
    while len(received) < 3 and time.monotonic() < deadline:
        event = spy.receive(timeout_s=0.1)
        if event is not None:
            received.append(event.type)
    assert received == ["scale_up", "drain", "set_focus"]


def test_hub_forgets_lost_and_left_chips() -> None:
    import asyncio

    from catsim.bus import ChipConfigured, ChipLeft, ChipLost

    def configured(chip_id: str) -> ChipConfigured:
        return ChipConfigured(
            source=chip_id,
            chip_id=chip_id,
            machine_name="chip-256",
            nominal_qubits=256,
            paper_qubits=262,
            logical_qubits=6,
            accounting="paper",
            blocks=[],
        )

    async def scenario() -> None:
        hub = EventHub()
        hub.attach_loop(asyncio.get_running_loop())
        hub.dispatch(configured("chip0"))
        hub.dispatch(configured("chip1"))
        hub.dispatch(ChipLost(source="scheduler", chip_id="chip0"))
        hub.dispatch(ChipLeft(source="chip1", chip_id="chip1"))
        assert hub.latest_chips == {}
        assert hub.latest_chip_status == {}
        late = hub.register()
        assert late.qsize() == 0  # no ghost chips replayed to late joiners
        hub.unregister(late)

    asyncio.run(scenario())


def test_layout_source_selects_a_block() -> None:
    import asyncio

    from catsim.bus import BlockConfigured

    hub = EventHub()
    for source in ("block1", "block0"):
        hub.dispatch(
            BlockConfigured(
                source=source,
                code_name="q70",
                distance=9,
                rounds_per_shot=5,
                num_data_qubits=70,
                num_logical=6,
                noise_name="paper",
                query_address="tcp://127.0.0.1:1",
            )
        )
    assert hub.latest_configured is not None
    assert hub.latest_configured.source == "block0", "the hero block is first by source order"
    assert set(hub.latest_blocks) == {"block0", "block1"}
    asyncio.new_event_loop().close()  # no loop needed; dispatch without clients is safe
