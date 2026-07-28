"""Dashboard configuration: panels, pacing presets, buffers — from YAML, frozen.

Exists so every dashboard knob is a config edit, never a code edit (charter
hard requirement); loaded once and passed by constructor injection.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_CONFIG_PATH = Path("configs/dashboard.yaml")


class NoiseSliderConfig(BaseModel):
    """Range of the live noise-scale slider (multiplier on the base model)."""

    model_config = ConfigDict(frozen=True)

    min: float = Field(default=0.1, gt=0.0)
    max: float = Field(default=100.0, gt=0.0)
    default: float = Field(default=1.0, gt=0.0)


class PanelsConfig(BaseModel):
    """Which views the page shows."""

    model_config = ConfigDict(frozen=True)

    block_view: bool = True
    event_log: bool = True
    injection_console: bool = True
    replay: bool = True
    factories: bool = True


class DashboardConfig(BaseModel):
    """Everything the dashboard frontend and backend take from YAML."""

    model_config = ConfigDict(frozen=True)

    title: str = "catsim — walking cat simulator"
    ring_buffer_rounds: int = Field(default=240, ge=2)
    event_log_limit: int = Field(default=400, ge=10)
    pace_presets_ms: list[float] = [0, 6, 100, 500, 1000]
    default_pace_ms: float = 500
    noise_scale: NoiseSliderConfig = NoiseSliderConfig()
    panels: PanelsConfig = PanelsConfig()
    machine_accent: str = "#E8701A"
    workload_accent: str = "#3B82F6"
    scenario_dir: Path = Path("configs/scenarios")


def load_dashboard_config(path: str | Path = DEFAULT_CONFIG_PATH) -> DashboardConfig:
    """Load and validate the dashboard config; an empty file means all defaults."""
    with Path(path).open() as f:
        raw = yaml.safe_load(f)
    return DashboardConfig.model_validate(raw or {})
