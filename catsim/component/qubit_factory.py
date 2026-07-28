"""The qubit factory: dispenses replacement ions for losses flagged on the bus.

Exists to close the ion-loss loop end-to-end (detect → dispatch → reinitialize
→ rejoin): it watches ``loss_detected`` events, answers with a dispatch, and
delivers a ``replacement_ready`` command to the block a few rounds later —
the reservoir-and-reload path of arXiv:2604.19481, modeled behaviorally
(production latency in block rounds), not as a stim circuit.
"""

from __future__ import annotations

from catsim.bus import (
    AnyEvent,
    EventSink,
    FactoryAccepted,
    FactoryAttempt,
    FactoryConfigured,
    LossDetected,
    ReplacementDispatched,
    ReplacementReady,
    RoundStarted,
    RunFinished,
    ZmqSubscriber,
)

DEFAULT_DISPATCH_ROUNDS = 2
"""Rounds between dispatch and delivery: loading + recooling a reservoir ion
takes a few physical-operation cycles (arXiv:2604.19481); two SE rounds keeps
the recovery visibly non-instant without dominating a demo shot."""


class QubitFactoryService:
    """Watches the bus for detected losses and delivers timed replacements.

    Production is counted with the same factory events the stim factories
    publish (attempt at dispatch, accepted at delivery) so the dashboard's
    factories panel renders it with no special casing; acceptance is always
    100% — a reservoir dispenses, it does not post-select.
    """

    def __init__(
        self,
        sink: EventSink,
        *,
        source: str = "qubitfactory0",
        dispatch_rounds: int = DEFAULT_DISPATCH_ROUNDS,
    ) -> None:
        """Create the service; it acts only on events fed to :meth:`handle`.

        Args:
            sink: Where dispatches, deliveries, and factory stats are published.
            source: Component id; becomes the bus topic.
            dispatch_rounds: Block rounds between dispatch and delivery.
        """
        self._sink = sink
        self._source = source
        self._dispatch_rounds = dispatch_rounds
        self._pending: dict[tuple[str, int], int] = {}
        self._attempts = 0
        self._delivered = 0
        self._stopped = False

    def stop(self) -> None:
        """Ask the run loop to exit at its next poll."""
        self._stopped = True

    def configure(self) -> None:
        """Announce the factory on the bus for the dashboard's panel."""
        self._sink.publish(
            FactoryConfigured(
                source=self._source, kind="qubit", output_qubits=1, verification_checks=0
            )
        )

    def handle(self, event: AnyEvent) -> bool:
        """Process one bus event; returns False once the run is over."""
        if isinstance(event, LossDetected):
            self._dispatch(event)
        elif isinstance(event, RoundStarted):
            # Round 0 marks a fresh shot: re-announce for late joiners, the
            # same cadence as the block's per-shot re-announce.
            if event.round == 0:
                self.configure()
            self._tick_round(event.source)
        elif isinstance(event, RunFinished):
            return False
        return True

    def run(self, subscriber: ZmqSubscriber, idle_timeout_s: float | None = 10.0) -> None:
        """Consume bus events until the run ends or the bus goes quiet.

        Args:
            subscriber: Connected bus subscriber to drain.
            idle_timeout_s: Give up after this long without any event; None
                means wait forever (serve mode).
        """
        self.configure()
        idle = 0.0
        while not self._stopped and (idle_timeout_s is None or idle < idle_timeout_s):
            event = subscriber.receive(timeout_s=0.05)
            if event is None:
                idle += 0.05
                continue
            idle = 0.0
            if not self.handle(event):
                return

    def _dispatch(self, event: LossDetected) -> None:
        """Start producing a replacement for the flagged ion."""
        key = (event.source, event.qubit)
        if key in self._pending:
            return
        self._pending[key] = self._dispatch_rounds
        self._attempts += 1
        self._sink.publish(
            FactoryAttempt(source=self._source, tick=self._attempts, attempt=self._attempts)
        )
        self._sink.publish(
            ReplacementDispatched(
                source=self._source,
                qubit=event.qubit,
                block=event.source,
                ready_in_rounds=self._dispatch_rounds,
            )
        )

    def _tick_round(self, block: str) -> None:
        """Advance production for ``block``'s pending replacements; deliver ripe ones."""
        for (owner, qubit), remaining in list(self._pending.items()):
            if owner != block:
                continue
            if remaining > 1:
                self._pending[(owner, qubit)] = remaining - 1
                continue
            del self._pending[(owner, qubit)]
            self._deliver(owner, qubit)

    def _deliver(self, block: str, qubit: int) -> None:
        """Hand the replacement to the block and publish the production stats."""
        self._delivered += 1
        self._sink.publish(ReplacementReady(source=self._source, target=block, qubit=qubit))
        self._sink.publish(
            FactoryAccepted(
                source=self._source,
                tick=self._attempts,
                attempt=self._delivered,
                attempts=self._attempts,
                accepted=self._delivered,
                acceptance_rate=1.0,
                residual_checks=[],
                output_error_rate=0.0,
            )
        )
