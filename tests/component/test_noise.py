"""Noise model loading, freezing, and uniform scaling."""

import pytest

from catsim.component import DepolarizingNoise, load_noise_model
from tests.conftest import NOISE_DIR


def test_paper_baseline_matches_charter() -> None:
    noise = load_noise_model(NOISE_DIR / "paper-baseline.yaml")
    assert noise.two_qubit_gate_error == 1e-4
    assert noise.single_qubit_gate_error == 1e-5
    assert noise.ion_loss_probability == 1e-7


def test_load_by_name() -> None:
    noise = load_noise_model("pessimistic", noise_dir=NOISE_DIR)
    assert noise.name == "pessimistic"


def test_scaled_preserves_ratios(paper_noise: DepolarizingNoise) -> None:
    scaled = paper_noise.scaled(10.0)
    assert scaled.two_qubit_gate_error == pytest.approx(1e-3)
    assert scaled.single_qubit_gate_error == pytest.approx(1e-4)
    assert scaled.name == "paper-baseline-x10"
    assert paper_noise.two_qubit_gate_error == 1e-4  # original untouched


def test_noise_is_frozen(paper_noise: DepolarizingNoise) -> None:
    with pytest.raises(Exception, match="frozen"):
        paper_noise.two_qubit_gate_error = 0.5
