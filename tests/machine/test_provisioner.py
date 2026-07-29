"""ProvisionerService: scale_up/drain resolution and lifecycle reaping."""

from catsim.bus import ChipAdmitted, ChipLeft, ChipLost, Drain, ScaleUp, StopChip
from catsim.machine import ProvisionerService
from tests.conftest import ListSink


class FakeSpawner:
    """Records lifecycle calls instead of starting anything."""

    def __init__(self) -> None:
        """Start with empty ledgers."""
        self.spawned: list[str] = []
        self.reaped: list[str] = []

    def spawn(self, instance_id: str) -> None:
        """Record the spawn."""
        self.spawned.append(instance_id)

    def reap(self, instance_id: str) -> None:
        """Record the reap."""
        self.reaped.append(instance_id)

    def reap_all(self) -> None:
        """Reap everything spawned and not yet reaped."""
        self.reaped.extend(i for i in self.spawned if i not in self.reaped)


def _admit(service: ProvisionerService, chip_id: str, instance_id: str) -> None:
    service.handle(
        ChipAdmitted(
            source="scheduler",
            target=instance_id,
            chip_id=chip_id,
            role="memory",
            mode="behavioral",
        )
    )


def test_scale_up_spawns_n_instances(list_sink: ListSink) -> None:
    spawner = FakeSpawner()
    service = ProvisionerService(list_sink, spawner)
    service.handle(ScaleUp(source="dash", target="provisioner", n=3))
    assert len(spawner.spawned) == 3
    assert len(set(spawner.spawned)) == 3
    assert service.instances == spawner.spawned


def test_scale_up_for_someone_else_is_ignored(list_sink: ListSink) -> None:
    spawner = FakeSpawner()
    service = ProvisionerService(list_sink, spawner)
    service.handle(ScaleUp(source="dash", target="elsewhere", n=3))
    assert spawner.spawned == []


def test_drain_by_chip_id_asks_the_chip_to_leave_then_reaps(list_sink: ListSink) -> None:
    spawner = FakeSpawner()
    service = ProvisionerService(list_sink, spawner)
    service.handle(ScaleUp(source="dash", target="provisioner", n=1))
    instance = spawner.spawned[0]
    _admit(service, "chip0", instance)
    service.handle(Drain(source="dash", target="provisioner", chip_id="chip0"))
    stop = [e for e in list_sink.events if isinstance(e, StopChip)]
    assert [s.target for s in stop] == ["chip0"]
    assert spawner.reaped == []  # reap waits for the goodbye
    service.handle(ChipLeft(source="chip0", chip_id="chip0"))
    assert spawner.reaped == [instance]
    assert service.instances == []


def test_drain_n_targets_the_newest_chips(list_sink: ListSink) -> None:
    spawner = FakeSpawner()
    service = ProvisionerService(list_sink, spawner)
    service.handle(ScaleUp(source="dash", target="provisioner", n=3))
    for i, instance in enumerate(spawner.spawned):
        _admit(service, f"chip{i}", instance)
    service.handle(Drain(source="dash", target="provisioner", n=2))
    stop = [e.target for e in list_sink.events if isinstance(e, StopChip)]
    assert stop == ["chip2", "chip1"]  # newest first, oldest survives


def test_chip_lost_is_reaped_like_a_leaver(list_sink: ListSink) -> None:
    spawner = FakeSpawner()
    service = ProvisionerService(list_sink, spawner)
    service.handle(ScaleUp(source="dash", target="provisioner", n=1))
    _admit(service, "chip0", spawner.spawned[0])
    service.handle(ChipLost(source="scheduler", chip_id="chip0"))
    assert spawner.reaped == spawner.spawned
    assert service.instances == []


def test_unknown_chip_left_is_ignored(list_sink: ListSink) -> None:
    spawner = FakeSpawner()
    service = ProvisionerService(list_sink, spawner)
    service.handle(ChipLeft(source="chipX", chip_id="chipX"))
    assert spawner.reaped == []
