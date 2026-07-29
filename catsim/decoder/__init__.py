"""Layer 2 — decoders (BP+OSD for qLDPC, pymatching baseline).

Exists so decoders are swappable and throttleable at runtime, with real
measured wall-clock latency streamed live and raced against the 6 ms budget.
"""

from catsim.decoder.bposd import BpOsdWrapper
from catsim.decoder.matching import MatchingDecoder
from catsim.decoder.protocol import (
    Decoder,
    DecodeResult,
    available_decoders,
    default_decoder,
    get_decoder,
    register_decoder,
)
from catsim.decoder.report import IMPLEMENTATION_NOTE, plot_latency_race, write_latency_csv
from catsim.decoder.service import DecoderService
from catsim.decoder.sinter_adapter import sinter_decoders
from catsim.decoder.timing import LatencyStats, replay_latencies, summarize_latencies

register_decoder(MatchingDecoder.name, MatchingDecoder)
register_decoder(BpOsdWrapper.name, BpOsdWrapper)

__all__ = [
    "BpOsdWrapper",
    "DecodeResult",
    "Decoder",
    "DecoderService",
    "IMPLEMENTATION_NOTE",
    "LatencyStats",
    "MatchingDecoder",
    "available_decoders",
    "default_decoder",
    "get_decoder",
    "plot_latency_race",
    "register_decoder",
    "replay_latencies",
    "sinter_decoders",
    "summarize_latencies",
    "write_latency_csv",
]
