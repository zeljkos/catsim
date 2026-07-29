"""Scripted, replayable scenarios: a YAML timeline of injections and config changes.

Exists so demo beats are rehearsable units — a scenario watches round_started
events on the bus and publishes the same commands the injection console would,
at the scripted moments. Depends only on the bus layer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from catsim.bus import (
    AnyEvent,
    EventSink,
    InjectLoss,
    InjectPauli,
    RoundStarted,
    RunFinished,
    SetDecoderSlowdown,
    SetInterconnect,
    SetNoiseScale,
    SetPace,
    SetPaused,
    ZmqSubscriber,
)

DEFAULT_SCENARIO_DIR = Path("configs/scenarios")

_SOURCE = "scenario"


class StepAt(BaseModel):
    """When a step fires: the first round_started at or past (shot, round)."""

    model_config = ConfigDict(frozen=True)

    shot: int = 0
    round: int = 0


class InjectSpec(BaseModel):
    """A deterministic Pauli injection."""

    model_config = ConfigDict(frozen=True)

    pauli: Literal["X", "Y", "Z"]
    qubits: list[int]


class ScenarioStep(BaseModel):
    """One timeline entry: a trigger plus exactly one action.

    ``target`` overrides the scenario's target for this step alone — how one
    timeline steers several components (e.g. rounds trigger on the block while
    a kill switch hits its cat factory).
    """

    model_config = ConfigDict(frozen=True)

    at: StepAt
    target: str | None = None
    inject: InjectSpec | None = None
    inject_loss: list[int] | None = None
    set_noise_scale: float | None = None
    set_pace_seconds: float | None = None
    set_paused: bool | None = None
    set_decoder_slowdown: float | None = None
    set_interconnect_severed: bool | None = None

    @model_validator(mode="after")
    def _exactly_one_action(self) -> ScenarioStep:
        """A step means one thing; reject none or several actions."""
        actions = [
            self.inject,
            self.inject_loss,
            self.set_noise_scale,
            self.set_pace_seconds,
            self.set_paused,
            self.set_decoder_slowdown,
            self.set_interconnect_severed,
        ]
        if sum(a is not None for a in actions) != 1:
            raise ValueError("each step must set exactly one action")
        return self

    def command(
        self, target: str
    ) -> (
        InjectPauli
        | InjectLoss
        | SetNoiseScale
        | SetPace
        | SetPaused
        | SetDecoderSlowdown
        | SetInterconnect
    ):
        """Build the bus command this step publishes when it fires."""
        if self.inject is not None:
            return InjectPauli(
                source=_SOURCE, target=target, qubits=self.inject.qubits, pauli=self.inject.pauli
            )
        if self.inject_loss is not None:
            return InjectLoss(source=_SOURCE, target=target, qubits=self.inject_loss)
        if self.set_noise_scale is not None:
            return SetNoiseScale(source=_SOURCE, target=target, scale=self.set_noise_scale)
        if self.set_pace_seconds is not None:
            return SetPace(source=_SOURCE, target=target, tick_seconds=self.set_pace_seconds)
        if self.set_paused is not None:
            return SetPaused(source=_SOURCE, target=target, paused=self.set_paused)
        if self.set_decoder_slowdown is not None:
            factor = self.set_decoder_slowdown
            return SetDecoderSlowdown(source=_SOURCE, target=target, factor=factor)
        assert self.set_interconnect_severed is not None
        return SetInterconnect(source=_SOURCE, target=target, severed=self.set_interconnect_severed)


class Scenario(BaseModel):
    """A named, one-line-described timeline of steps against one target.

    ``target: "*"`` broadcasts every command to all components (block and
    factories alike) and triggers on any component's rounds — the shape the
    factory-yield sweep needs. ``relative: true`` counts step shots from the
    first round observed after the scenario starts instead of from shot 0 —
    for scenarios run mid-demo against a block that has been up for a while.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    target: str = "block0"
    relative: bool = False
    steps: list[ScenarioStep]


def load_scenario(spec: str | Path, scenario_dir: Path = DEFAULT_SCENARIO_DIR) -> Scenario:
    """Load a scenario from a YAML path or a bare name under ``scenario_dir``."""
    path = Path(spec)
    if not path.exists():
        path = scenario_dir / f"{spec}.yaml"
    with path.open() as f:
        return Scenario.model_validate(yaml.safe_load(f))


def list_scenarios(scenario_dir: Path = DEFAULT_SCENARIO_DIR) -> list[Scenario]:
    """Load every scenario shipped under ``scenario_dir``, sorted by name."""
    if not scenario_dir.is_dir():
        return []
    return sorted((load_scenario(p) for p in scenario_dir.glob("*.yaml")), key=lambda s: s.name)


class ScenarioRunner:
    """Fires a scenario's steps as the target block's rounds go by.

    Commands take effect at the block's *next* round, so a step scheduled
    ``at: {shot: S, round: R}`` lands in round R+1 of shot S (or the next
    injectable round after it).
    """

    def __init__(self, scenario: Scenario, sink: EventSink) -> None:
        """Prepare to run ``scenario``, publishing its commands into ``sink``."""
        self._scenario = scenario
        self._sink = sink
        self._fired = [False] * len(scenario.steps)
        self._base_shot: int | None = None

    @property
    def done(self) -> bool:
        """True once every step has fired."""
        return all(self._fired)

    def handle(self, event: AnyEvent) -> bool:
        """Advance on one bus event; returns False when the runner is finished."""
        if isinstance(event, RunFinished):
            return False
        target = self._scenario.target
        if isinstance(event, RoundStarted) and (event.source == target or target == "*"):
            if self._base_shot is None:
                self._base_shot = event.shot if self._scenario.relative else 0
            now = (event.shot - self._base_shot, event.round)
            for i, step in enumerate(self._scenario.steps):
                if not self._fired[i] and now >= (step.at.shot, step.at.round):
                    self._fired[i] = True
                    self._sink.publish(step.command(step.target or self._scenario.target))
        return not self.done

    def run(self, subscriber: ZmqSubscriber, idle_timeout_s: float = 60.0) -> None:
        """Consume bus events until every step fired or the bus goes quiet."""
        idle = 0.0
        while idle < idle_timeout_s:
            event = subscriber.receive(timeout_s=0.05)
            if event is None:
                idle += 0.05
                continue
            idle = 0.0
            if not self.handle(event):
                return
