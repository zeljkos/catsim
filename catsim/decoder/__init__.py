"""Layer 2 — decoders (BP+OSD for qLDPC, pymatching baseline).

Exists so decoders are swappable and throttleable at runtime, with real
measured wall-clock latency streamed live and raced against the 6 ms budget.
"""

from catsim.decoder.matching import MatchingDecoder
from catsim.decoder.protocol import (
    Decoder,
    DecodeResult,
    available_decoders,
    get_decoder,
    register_decoder,
)
from catsim.decoder.service import DecoderService

register_decoder(MatchingDecoder.name, MatchingDecoder)

__all__ = [
    "DecodeResult",
    "Decoder",
    "DecoderService",
    "MatchingDecoder",
    "available_decoders",
    "get_decoder",
    "register_decoder",
]
