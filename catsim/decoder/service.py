"""The decoder as a bus service: consumes syndromes, publishes decode verdicts.

Exists so the decoder couples to components only through the event bus — the
same seam that later lets it run as its own container. Bulk inputs (the DEM,
the detector-to-qubit geometry) are fetched from the block's query address.
"""

from __future__ import annotations

import json

import numpy as np
import numpy.typing as npt
import stim

from catsim.bus import (
    AnyEvent,
    BlockConfigured,
    CorrectionApplied,
    DecodeFinished,
    DecodeStarted,
    EventSink,
    LogicalError,
    RunFinished,
    SetDecoder,
    ShotFinished,
    SyndromeFired,
    ZmqSubscriber,
    query,
)
from catsim.decoder.protocol import Decoder, get_decoder


class DecoderService:
    """Tracks each shot's syndrome history and decodes it as rounds arrive.

    Mid-shot decodes pad future detectors with zeros (the standard online
    approximation); the verdict at ``shot_finished`` uses the complete syndrome
    and is exact.
    """

    def __init__(
        self,
        sink: EventSink,
        *,
        decoder_name: str = "pymatching",
        source: str = "decoder0",
        slowdown_factor: float = 1.0,
    ) -> None:
        """Create the service; the decoder itself is built on ``block_configured``.

        Args:
            sink: Where decode events are published.
            decoder_name: Registry name of the decoder implementation.
            source: Component id; becomes the bus topic.
            slowdown_factor: Artificial latency multiplier, adjustable live.
        """
        self._sink = sink
        self._decoder_name = decoder_name
        self._source = source
        self.slowdown_factor = slowdown_factor
        self._decoder: Decoder | None = None
        self._dem: str | None = None
        self._syndrome: npt.NDArray[np.uint8] = np.zeros(0, dtype=np.uint8)
        self._prediction: tuple[int, ...] = ()
        self._edge_qubits: dict[frozenset[int], tuple[int, ...]] = {}
        self._configured_key: dict[str, object] | None = None

    def handle(self, event: AnyEvent) -> bool:
        """Process one bus event; returns False once the run is over."""
        if isinstance(event, BlockConfigured):
            self._configure(event)
        elif isinstance(event, SetDecoder) and event.target in (self._source, "*"):
            self._swap_decoder(event.name)
        elif isinstance(event, SyndromeFired) and self._decoder is not None:
            self._decode_round(event)
        elif isinstance(event, ShotFinished) and self._decoder is not None:
            self._finish_shot(event)
        elif isinstance(event, RunFinished):
            return False
        return True

    def run(self, subscriber: ZmqSubscriber, idle_timeout_s: float | None = 10.0) -> None:
        """Consume events from the bus until the run ends or the bus goes quiet.

        Args:
            subscriber: Connected bus subscriber to drain.
            idle_timeout_s: Give up after this long without any event (safety
                net so an orphaned service never hangs a process); None means
                wait forever — serve mode, where pauses outlive any timeout.
        """
        idle = 0.0
        while idle_timeout_s is None or idle < idle_timeout_s:
            event = subscriber.receive(timeout_s=0.05)
            if event is None:
                idle += 0.05
                continue
            idle = 0.0
            if not self.handle(event):
                return

    def _configure(self, event: BlockConfigured) -> None:
        """Fetch the announced block's DEM and geometry; build the decoder.

        Blocks re-announce every shot so late joiners bootstrap; an unchanged
        announcement is a no-op here (no query, no decoder rebuild).
        """
        key = event.model_dump(exclude={"tick"})
        if key == self._configured_key:
            return
        self._configured_key = key
        self._dem = query(event.query_address, "dem")
        self._decoder = self._build_decoder(self._decoder_name)
        layout = json.loads(query(event.query_address, "layout"))
        self._edge_qubits = {
            frozenset(edge["detectors"]): tuple(edge["qubits"]) for edge in layout["edges"]
        }
        self._syndrome = np.zeros(stim.DetectorErrorModel(self._dem).num_detectors, dtype=np.uint8)
        self._prediction = ()

    def _build_decoder(self, name: str) -> Decoder:
        """Instantiate the named decoder against the current block's DEM."""
        assert self._dem is not None
        return get_decoder(name, dem=self._dem, slowdown_factor=self.slowdown_factor)

    def _swap_decoder(self, name: str) -> None:
        """Runtime decoder swap; a failed build keeps the current decoder.

        A build can fail legitimately — e.g. pymatching rejects a qLDPC DEM
        whose hyperedges cannot decompose into a matching graph.
        """
        if self._dem is None:
            self._decoder_name = name
            return
        try:
            self._decoder = self._build_decoder(name)
        except (KeyError, ValueError) as exc:
            print(f"decoder swap to {name!r} failed, keeping {self._decoder_name!r}: {exc}")
            return
        self._decoder_name = name

    def _identify(self, matched: tuple[tuple[int, ...], ...]) -> list[int]:
        """Name the data qubits blamed by the decoder's detector sets (-1 = boundary)."""
        blamed: set[int] = set()
        for dets in matched:
            key = frozenset(d for d in dets if d >= 0)
            blamed.update(self._edge_qubits.get(key, ()))
        return sorted(blamed)

    def _decode_round(self, event: SyndromeFired) -> None:
        """Fold new checks into the shot's syndrome and decode what is known."""
        self._syndrome[event.check_ids] = 1
        self._sink.publish(DecodeStarted(source=self._source, shot=event.shot, round=event.round))
        assert self._decoder is not None
        result = self._decoder.decode(self._syndrome)
        self._prediction = result.predicted_flips
        identified = self._identify(result.matched_detectors)
        self._sink.publish(
            DecodeFinished(
                source=self._source,
                shot=event.shot,
                round=event.round,
                latency_s=result.latency_s,
                identified_qubits=identified,
                matched_detectors=[list(d) for d in result.matched_detectors],
            )
        )
        self._sink.publish(
            CorrectionApplied(
                source=self._source,
                shot=event.shot,
                round=event.round,
                observables=list(result.predicted_flips),
                qubits=identified,
            )
        )

    def _finish_shot(self, event: ShotFinished) -> None:
        """Compare the decoder's prediction against the true frame; reset for next shot."""
        residual = set(self._prediction) ^ set(event.actual_flips)
        if residual:
            self._sink.publish(
                LogicalError(source=self._source, shot=event.shot, observables=sorted(residual))
            )
        self._syndrome[:] = 0
        self._prediction = ()
