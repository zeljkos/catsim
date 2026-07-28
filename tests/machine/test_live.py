"""M3 acceptance: the live backend streams block AND factory events on one bus."""

import time

from catsim.bus import FactoryConfigured, ZmqSubscriber
from catsim.codes import get_code
from catsim.component import DepolarizingNoise, MemoryBlockSpec
from catsim.machine import LiveBackend


def test_live_backend_streams_factory_events(busy_noise: DepolarizingNoise) -> None:
    spec = MemoryBlockSpec(code=get_code("surface", distance=3), noise=busy_noise, rounds=4)
    backend = LiveBackend(spec, tick_seconds=0.01)
    spy = ZmqSubscriber(backend.backend_address)
    try:
        backend.start()
        seen: dict[str, str] = {}
        deadline = time.monotonic() + 5.0
        wanted = {"cat0", "bell0", "magic0", "qubitfactory0"}
        while time.monotonic() < deadline and not wanted <= seen.keys():
            event = spy.receive(timeout_s=0.1)
            if isinstance(event, FactoryConfigured):
                seen[event.source] = event.kind
        assert wanted <= seen.keys(), f"missing factory announcements: {wanted - seen.keys()}"
        assert seen["qubitfactory0"] == "qubit"
    finally:
        backend.stop()
        spy.close()
