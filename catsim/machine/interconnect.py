"""The inter-module photonic interconnect: a heralded Bell-pair bank (M7).

Exists to model cross-module entanglement as what it physically is — a
probabilistic, heralded pair source orders of magnitude slower than the
intra-module transport-based Bell factories — with EVERY parameter an
ASSUMPTION from :class:`~catsim.machine.config.InterconnectConfig`, NOT from
arXiv:2604.19481 (a single-machine blueprint). Pure and wall-clock-free, like
the machine model: the scheduler advances it in machine time; cross-module
logical operations consume banked pairs, and a severed link turns demand into
a visible queue instead of served gates.
"""

from __future__ import annotations

from catsim.machine.config import InterconnectConfig


class InterconnectModel:
    """Bell-pair bank between modules, advanced in machine seconds.

    Pairs herald into the bank at the (assumed) success rate while the link
    is up; cross-module T gates consume one banked pair each. Demand that
    finds the bank empty queues — it is never dropped — and drains as pairs
    regenerate. Single-threaded, like :class:`~catsim.machine.model.MachineModel`.
    """

    def __init__(self, config: InterconnectConfig) -> None:
        """Start with an empty bank on an intact link.

        Args:
            config: The assumption-marked link parameters (rate, latency, cap).
        """
        self._config = config
        self._bank = 0.0
        self._severed = False
        self._queue = 0.0
        self._served_total = 0.0
        self._handover = 0.0

    @property
    def config(self) -> InterconnectConfig:
        """The assumption-marked parameters this model runs on."""
        return self._config

    @property
    def bank(self) -> float:
        """Bell pairs currently banked."""
        return self._bank

    @property
    def severed(self) -> bool:
        """True while the photonic link is cut (bank stops refilling)."""
        return self._severed

    @property
    def cross_queue(self) -> float:
        """Cross-module T gates waiting for a banked pair."""
        return self._queue

    @property
    def cross_served(self) -> float:
        """Cross-module T gates served (pairs consumed) since boot."""
        return self._served_total

    def set_severed(self, severed: bool) -> None:
        """Cut or restore the link (the interconnect-outage kill switch)."""
        self._severed = severed

    def advance(self, dt: float, cross_demand_per_s: float, *, active: bool) -> None:
        """Advance machine time: herald pairs, serve or queue cross demand.

        Args:
            dt: Machine seconds elapsed since the last advance.
            cross_demand_per_s: Cross-module T-gate demand rate right now.
            active: Whether more than one module is populated (no second
                module, no link: nothing heralds and nothing crosses).
        """
        if dt <= 0 or not active:
            return
        # Heralding and consumption are concurrent within a step: serve from
        # bank + inflow, then cap what remains at the bank's capacity.
        inflow = 0.0 if self._severed else self._config.pair_rate_hz * dt
        available = self._bank + inflow
        want = cross_demand_per_s * dt + self._queue
        served = min(want, available)
        self._bank = min(available - served, float(self._config.bank_capacity))
        self._queue = want - served
        self._served_total += served
        self._handover += served

    def take_handover(self) -> int:
        """Whole served gates not yet handed to a factory (fraction carries)."""
        whole = int(self._handover)
        self._handover -= whole
        return whole
