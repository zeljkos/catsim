"""Ion-loss lifecycle inside a memory block: lost → detected → replaced.

Exists so the block's tick loop stays small: the tracker owns the per-qubit
state machine (detection latency, replacement readiness, shot-end fallback)
and reports, each round, which events to publish and which qubits to scramble.
"""

from __future__ import annotations

from dataclasses import dataclass, field

LOSS_DEPOLARIZATION = 0.75
"""A lost ion's qubit is maximally mixed: uniform over {I, X, Y, Z} each round.
A just-replaced qubit is scrambled once too — the fresh ion arrives in |0>,
a random Pauli away from the code state; syndrome extraction projects it back
and the decoder corrects, which is the visible 're-stabilize' beat."""


@dataclass(frozen=True)
class LossRoundEffects:
    """What one round's loss bookkeeping asks the block to do.

    ``newly_lost``/``newly_detected``/``replaced`` map one-to-one onto the
    ``ion_lost``/``loss_detected``/``qubit_replaced`` bus events; ``scramble``
    lists every qubit to depolarize this round (still-lost ions, plus each
    replaced qubit exactly once as it rejoins).
    """

    newly_lost: tuple[int, ...]
    newly_detected: tuple[int, ...]
    replaced: tuple[int, ...]
    scramble: tuple[int, ...]


@dataclass
class LossTracker:
    """Per-qubit loss state machine driven once per injectable round.

    Loss is detected one round after it happens (the ion's absence shows in
    the following detection/cooling cycle — a faithful one-round latency
    stand-in for the paper's loss detection, arXiv:2604.19481); replacement
    happens the round after :meth:`mark_ready` (the qubit factory answered).
    """

    _undetected: set[int] = field(default_factory=set)
    _detected: set[int] = field(default_factory=set)
    _ready: set[int] = field(default_factory=set)

    @property
    def lost(self) -> frozenset[int]:
        """Every qubit currently lost (detected or not)."""
        return frozenset(self._undetected | self._detected)

    def mark_ready(self, qubit: int) -> None:
        """A replacement ion is ready; the qubit rejoins at the next round."""
        self._ready.add(qubit)

    def advance(self, new_losses: set[int]) -> LossRoundEffects:
        """One round of bookkeeping: rejoin ready qubits, detect, admit losses.

        Args:
            new_losses: Qubits whose loss was injected since the last round
                (already filtered to the block's known qubits).

        Returns:
            The events to publish and qubits to scramble this round.
        """
        replaced = tuple(sorted(self._ready & (self._undetected | self._detected)))
        self._undetected -= self._ready
        self._detected -= self._ready
        self._ready.clear()
        newly_detected = tuple(sorted(self._undetected))
        self._detected |= self._undetected
        self._undetected.clear()
        newly_lost = tuple(sorted(new_losses - self._detected - set(replaced)))
        self._undetected |= set(newly_lost)
        scramble = tuple(sorted(self._undetected | self._detected | set(replaced)))
        return LossRoundEffects(
            newly_lost=newly_lost,
            newly_detected=newly_detected,
            replaced=replaced,
            scramble=scramble,
        )

    def reset_shot(self) -> tuple[int, ...]:
        """End of shot: clear all state, returning still-lost qubits.

        The block replaces those at re-initialization — the fallback when no
        qubit factory answered before the shot ended.
        """
        leftover = tuple(sorted(self._undetected | self._detected))
        self._undetected.clear()
        self._detected.clear()
        self._ready.clear()
        return leftover
