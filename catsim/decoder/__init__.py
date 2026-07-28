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
    get_decoder,
    register_decoder,
)
from catsim.decoder.service import DecoderService
from catsim.decoder.sinter_adapter import sinter_decoders

register_decoder(MatchingDecoder.name, MatchingDecoder)
register_decoder(BpOsdWrapper.name, BpOsdWrapper)

__all__ = [
    "BpOsdWrapper",
    "DecodeResult",
    "Decoder",
    "DecoderService",
    "MatchingDecoder",
    "available_decoders",
    "get_decoder",
    "register_decoder",
    "sinter_decoders",
]
