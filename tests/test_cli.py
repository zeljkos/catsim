"""CLI: thin-shell behavior over the library, both subcommands."""

from pathlib import Path

import pytest

from catsim.cli import build_parser, main
from tests.conftest import NOISE_DIR


def test_no_command_exits() -> None:
    with pytest.raises(SystemExit):
        main([])


def test_parser_knows_all_commands() -> None:
    parser = build_parser()
    assert parser.parse_args(["live"]).command == "live"
    assert parser.parse_args(["batch-curve"]).command == "batch-curve"
    assert parser.parse_args(["decoder-race"]).command == "decoder-race"
    assert parser.parse_args(["serve"]).command == "serve"


def test_serve_accepts_machine_config() -> None:
    args = build_parser().parse_args(["serve", "--machine", "chip-256"])
    assert args.machine == "chip-256"
    assert build_parser().parse_args(["serve"]).machine is None  # single-block mode default


def test_serve_fleet_flag() -> None:
    args = build_parser().parse_args(["serve", "--fleet", "1"])
    assert args.fleet == 1
    assert build_parser().parse_args(["serve"]).fleet is None  # M5 backend default


def test_node_role_defaults_to_chip_with_well_known_bus() -> None:
    args = build_parser().parse_args(["node"])
    assert args.command == "node"
    assert args.role == "chip"
    assert args.frontend.startswith("tcp://")
    assert args.backend.startswith("tcp://")
    assert args.instance  # every process gets a transport identity


def test_node_env_overrides_role_and_bus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CATSIM_ROLE", "provisioner")
    monkeypatch.setenv("CATSIM_BUS_FRONTEND", "tcp://bus:5561")
    monkeypatch.setenv("CATSIM_SPAWN", "docker")
    args = build_parser().parse_args(["node"])
    assert args.role == "provisioner"
    assert args.frontend == "tcp://bus:5561"
    assert args.spawn == "docker"


def test_live_prints_summary(capsys: pytest.CaptureFixture[str]) -> None:
    main(
        [
            "live",
            "--distance",
            "3",
            "--rounds",
            "4",
            "--shots",
            "2",
            "--noise",
            str(NOISE_DIR / "pessimistic.yaml"),
            "--tick-seconds",
            "0",
        ]
    )
    out = capsys.readouterr().out
    assert "shots=2" in out
    assert "bus backend: tcp://" in out


def test_batch_curve_writes_reports(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(
        [
            "batch-curve",
            "--distances",
            "3",
            "--scales",
            "100",
            "--max-shots",
            "500",
            "--max-errors",
            "10",
            "--workers",
            "2",
            "--noise",
            str(NOISE_DIR / "paper-baseline.yaml"),
            "--out-dir",
            str(tmp_path),
        ]
    )
    assert (tmp_path / "m0_logical_error_vs_distance.csv").exists()
    assert (tmp_path / "m0_logical_error_vs_distance.png").exists()
    assert "wrote" in capsys.readouterr().out


def test_decoder_race_writes_reports(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(
        [
            "decoder-race",
            "--distances",
            "3",
            "--scales",
            "1",
            "--rounds",
            "20",
            "--warmup",
            "2",
            "--rounds-per-shot",
            "3",
            "--noise",
            str(NOISE_DIR / "paper-baseline.yaml"),
            "--out-dir",
            str(tmp_path),
        ]
    )
    assert (tmp_path / "m4_decoder_race.csv").exists()
    assert (tmp_path / "m4_decoder_race.png").exists()
    out = capsys.readouterr().out
    assert "p99=" in out
    assert "wrote" in out
