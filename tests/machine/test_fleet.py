"""FleetBackend end-to-end: real chip processes join, tick, and drain.

The slowest tests here boot actual ``catsim node --role chip`` subprocesses
(the same join protocol containers use), so generous deadlines guard against
cold-start stim imports, and everything is bounded — no unbounded waits.
"""

import time
from collections.abc import Callable

from catsim.bus import Drain, ScaleUp, ZmqPublisher
from catsim.machine import FleetBackend, load_machine_config
from tests.conftest import REPO_ROOT

MACHINE_DIR = REPO_ROOT / "configs" / "machine"

_BOOT_DEADLINE_S = 60.0  # cold python + stim import per chip process


def _wait(predicate: Callable[[], bool], deadline_s: float, what: str) -> None:
    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError(f"timed out after {deadline_s}s waiting for {what}")


def test_fleet_boots_grows_and_drains() -> None:
    unit = load_machine_config("chip-256", MACHINE_DIR)
    backend = FleetBackend(unit, chips=1, tick_seconds=0.05, rounds=5, heartbeat_timeout_s=10.0)
    commands = ZmqPublisher(backend.frontend_address)
    try:
        backend.start()
        scheduler = backend.scheduler
        _wait(lambda: len(scheduler.chips) == 1, _BOOT_DEADLINE_S, "first chip to join")
        assert scheduler.focus == "chip0"
        assert scheduler.chips["chip0"].role == "memory"

        # Grow by one: the joiner registers itself and stays behavioral.
        commands.publish(ScaleUp(source="test", target="provisioner", n=1))
        _wait(lambda: len(scheduler.chips) == 2, _BOOT_DEADLINE_S, "second chip to join")
        _wait(
            lambda: scheduler.chips["chip1"].status is not None,
            _BOOT_DEADLINE_S,
            "chip1 status",
        )
        status = scheduler.chips["chip1"].status
        assert status is not None and status.mode == "behavioral"
        assert status.machine_seconds > 0  # the behavioral clock is ticking

        # Drain the newest chip: graceful leave, no chip_lost.
        commands.publish(Drain(source="test", target="provisioner", n=1))
        _wait(lambda: len(scheduler.chips) == 1, 30.0, "drained chip to deregister")
        assert "chip0" in scheduler.chips
    finally:
        commands.close()
        start = time.monotonic()
        backend.stop()
        assert time.monotonic() - start < 15.0  # teardown must stay demo-fast
