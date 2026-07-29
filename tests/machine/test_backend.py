"""M5 acceptance slice: the machine backend streams chip, block, and factory events."""

import time

from catsim.bus import BlockConfigured, ChipConfigured, MachineStatus, ZmqSubscriber
from catsim.component import DepolarizingNoise
from catsim.machine import MachineBackend, load_machine_config
from tests.conftest import REPO_ROOT

MACHINE_DIR = REPO_ROOT / "configs" / "machine"


def test_machine_backend_streams_chip_and_block_events(busy_noise: DepolarizingNoise) -> None:
    machine = load_machine_config("chip-256-roadmap", MACHINE_DIR)
    backend = MachineBackend(machine, busy_noise, rounds=4, tick_seconds=0.01)
    spy = ZmqSubscriber(backend.backend_address)
    chips: list[ChipConfigured] = []
    blocks: dict[str, BlockConfigured] = {}
    statuses: list[MachineStatus] = []
    try:
        backend.start()
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and not (chips and len(blocks) == 2 and statuses):
            event = spy.receive(timeout_s=0.1)
            if isinstance(event, ChipConfigured):
                chips.append(event)
            elif isinstance(event, BlockConfigured):
                blocks[event.source] = event
            elif isinstance(event, MachineStatus):
                statuses.append(event)
    finally:
        backend.stop()
        spy.close()
    assert chips and chips[0].paper_qubits == 524
    assert set(blocks) == {"block0", "block1"}
    assert all(b.code_name == "q70" and b.num_logical == 6 for b in blocks.values())
    assert backend.active_decoders == {"block0": "bposd", "block1": "bposd"}
    assert statuses and statuses[-1].logical_qubits == 12
