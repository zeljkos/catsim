"""Thin command-line shell over the catsim library.

Exists only to parse arguments and delegate; everything the CLI can do must be
callable (and testable) from Python without subprocesses.
"""

from __future__ import annotations

import argparse
import os
import time
from collections.abc import Callable
from pathlib import Path

from catsim import codes, component, dashboard, decoder, machine


def _env(name: str, default: str) -> str:
    """An argparse default that a container's environment can override."""
    return os.environ.get(name, default)


def build_parser() -> argparse.ArgumentParser:
    """Define the CLI surface: one subcommand per library entry point."""
    parser = argparse.ArgumentParser(prog="catsim", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    curve = sub.add_parser("batch-curve", help="batch logical-error curve (M0/M2)")
    curve.add_argument("--family", choices=sorted(codes.available_codes()), default="surface")
    curve.add_argument("--distances", type=int, nargs="+", default=[3, 5, 7])
    curve.add_argument(
        "--scales",
        type=float,
        nargs="+",
        default=[10.0, 30.0, 100.0],
        help="noise multipliers applied to the base model",
    )
    curve.add_argument("--noise", default="paper-baseline")
    curve.add_argument("--decoder", default=None, help="default: family-appropriate")
    curve.add_argument("--max-shots", type=int, default=2_000_000)
    curve.add_argument("--max-errors", type=int, default=200)
    curve.add_argument("--workers", type=int, default=8)
    curve.add_argument("--out-dir", type=Path, default=Path("reports"))

    race = sub.add_parser(
        "decoder-race", help="batch decode-latency percentiles vs the 6 ms SEC budget (M4)"
    )
    race.add_argument("--distances", type=int, nargs="+", default=[3, 5, 7])
    race.add_argument(
        "--scales",
        type=float,
        nargs="+",
        default=[1.0, 5.0],
        help="noise multipliers applied to the base model",
    )
    race.add_argument("--noise", default="paper-baseline")
    race.add_argument("--rounds", type=int, default=2000, help="measured decodes per config")
    race.add_argument("--warmup", type=int, default=100, help="leading decodes discarded")
    race.add_argument(
        "--rounds-per-shot", type=int, default=10, help="SE rounds per sampled memory shot"
    )
    race.add_argument("--seed", type=int, default=0)
    race.add_argument("--out-dir", type=Path, default=Path("reports"))

    live = sub.add_parser("live", help="run a live memory block + decoder on the bus")
    live.add_argument("--code", choices=sorted(codes.available_codes()), default="surface")
    live.add_argument("--distance", type=int, default=3, help="surface family only")
    live.add_argument("--decoder", default=None, help="default: family-appropriate")
    live.add_argument("--rounds", type=int, default=10)
    live.add_argument("--shots", type=int, default=10)
    live.add_argument("--noise", default="pessimistic")
    live.add_argument("--seed", type=int, default=0)
    live.add_argument(
        "--tick-seconds",
        type=float,
        default=0.006,
        help="pace per SE round; 0.006 = the paper's 6 ms SEC",
    )

    pvm = sub.add_parser("machine-report", help="predicted-vs-measured for a machine config (M5)")
    pvm.add_argument("--machine", default="chip-256", help="machine config name/path")
    pvm.add_argument("--noise", default="paper-baseline")
    pvm.add_argument("--machine-seconds", type=float, default=600.0)
    pvm.add_argument("--shots", type=int, default=50)
    pvm.add_argument("--rounds", type=int, default=10)
    pvm.add_argument("--seed", type=int, default=0)
    pvm.add_argument("--out-dir", type=Path, default=Path("reports"))

    sweep = sub.add_parser(
        "scaling-report",
        help="M7 sweep: predicted vs measured from 1 to ~80 chips + interconnect "
        "sensitivity; writes reports/m7_scaling.{csv,png} and m7_interconnect.csv",
    )
    sweep.add_argument("--machine", default="chip-256", help="unit-chip machine config")
    sweep.add_argument("--noise", default="paper-baseline")
    sweep.add_argument("--ns", type=int, nargs="+", default=[1, 5, 10, 20, 40, 60, 80])
    sweep.add_argument(
        "--measure-ns",
        type=int,
        nargs="*",
        default=None,
        help="fleet sizes to actually boot and measure (default: every --ns value); "
        "pass with no values for a prediction-only sweep",
    )
    sweep.add_argument(
        "--wall-seconds", type=float, default=12.0, help="measurement window per fleet"
    )
    sweep.add_argument(
        "--behavioral-rate",
        type=float,
        default=20.0,
        help="machine seconds per wall second on behavioral chips (fast-forward)",
    )
    sweep.add_argument(
        "--rates",
        type=float,
        nargs="+",
        default=[1.0, 3.0, 10.0, 30.0, 100.0, 300.0, 1000.0],
        help="heralded pair rates to sweep (pairs/s; every value an ASSUMPTION)",
    )
    sweep.add_argument("--out-dir", type=Path, default=Path("reports"))

    node = sub.add_parser(
        "node",
        help="one fleet node — role from --role or CATSIM_ROLE "
        "(chip | scheduler | provisioner | dashboard); one image, many roles (M6)",
    )
    node.add_argument(
        "--role",
        choices=["chip", "scheduler", "provisioner", "dashboard"],
        default=_env("CATSIM_ROLE", "chip"),
    )
    node.add_argument("--frontend", default=_env("CATSIM_BUS_FRONTEND", machine.DEFAULT_FRONTEND))
    node.add_argument("--backend", default=_env("CATSIM_BUS_BACKEND", machine.DEFAULT_BACKEND))
    node.add_argument("--instance", default=_env("CATSIM_INSTANCE", f"inst-pid{os.getpid()}"))
    node.add_argument("--noise", default=_env("CATSIM_NOISE", "paper-baseline"))
    node.add_argument("--machine", default=_env("CATSIM_MACHINE", "chip-256"))
    node.add_argument("--machine-name", default=_env("CATSIM_MACHINE_NAME", "chip-256"))
    node.add_argument("--rounds", type=int, default=int(_env("CATSIM_ROUNDS", "10")))
    node.add_argument("--seed", type=int, default=int(_env("CATSIM_SEED", "0")))
    node.add_argument("--pace-ms", type=float, default=float(_env("CATSIM_PACE_MS", "500")))
    node.add_argument(
        "--behavioral-rate",
        type=float,
        default=float(_env("CATSIM_BEHAVIORAL_RATE", "1.0")),
        help="machine seconds per wall second in behavioral mode (1 = real time)",
    )
    node.add_argument(
        "--heartbeat-timeout",
        type=float,
        default=float(_env("CATSIM_HEARTBEAT_TIMEOUT", "5.0")),
        help="scheduler: silence after which a chip is declared lost",
    )
    node.add_argument(
        "--bind-frontend",
        default=_env("CATSIM_BIND_FRONTEND", "tcp://0.0.0.0:5561"),
        help="scheduler: where the bus proxy binds its XSUB side",
    )
    node.add_argument(
        "--bind-backend",
        default=_env("CATSIM_BIND_BACKEND", "tcp://0.0.0.0:5562"),
        help="scheduler: where the bus proxy binds its XPUB side",
    )
    node.add_argument(
        "--spawn",
        choices=["process", "docker"],
        default=_env("CATSIM_SPAWN", "process"),
        help="provisioner: chip lifecycle backend",
    )
    node.add_argument("--image", default=_env("CATSIM_IMAGE", "catsim:latest"))
    node.add_argument("--network", default=_env("CATSIM_NETWORK", "") or None)
    node.add_argument(
        "--initial-chips",
        type=int,
        default=int(_env("CATSIM_INITIAL_CHIPS", "0")),
        help="provisioner: chips to start at boot (compose sets 1)",
    )
    node.add_argument("--dashboard-config", type=Path, default=Path("configs/dashboard.yaml"))
    node.add_argument("--host", default=_env("CATSIM_HOST", "0.0.0.0"))
    node.add_argument("--port", type=int, default=int(_env("CATSIM_PORT", "8000")))

    serve = sub.add_parser("serve", help="dashboard: live block + decoder + web UI")
    serve.add_argument(
        "--fleet",
        type=int,
        default=None,
        metavar="N",
        help="elastic mode (M6): boot the fleet runtime with N chip processes "
        "instead of the in-process M5 backend; --machine names the unit chip",
    )
    serve.add_argument(
        "--machine",
        default=None,
        help="machine config name/path (configs/machine): serve the M5 one-chip "
        "machine — blocks + cat units + machine model; --code is then ignored",
    )
    serve.add_argument("--code", choices=sorted(codes.available_codes()), default="surface")
    serve.add_argument("--distance", type=int, default=3, help="surface family only")
    serve.add_argument("--decoder", default=None, help="default: family-appropriate")
    serve.add_argument("--rounds", type=int, default=10)
    serve.add_argument("--noise", default="paper-baseline")
    serve.add_argument("--seed", type=int, default=0)
    serve.add_argument(
        "--pace-ms",
        type=float,
        default=500.0,
        help="initial slow-motion pace per SE round (adjustable live from the UI)",
    )
    serve.add_argument("--dashboard-config", type=Path, default=Path("configs/dashboard.yaml"))
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    return parser


def _resolve_code(args: argparse.Namespace) -> codes.QECCode:
    """Build the selected code (distance applies to the surface family only)."""
    if args.code == "surface":
        return codes.get_code("surface", distance=args.distance)
    return codes.get_code(args.code)


def _resolve_decoder(family: str, requested: str | None) -> str:
    """The requested decoder, or the family-appropriate default."""
    return requested or decoder.default_decoder(family)


def _cmd_batch_curve(args: argparse.Namespace) -> None:
    """Collect the batch curve and write CSV + PNG under the reports directory."""
    noise = component.load_noise_model(args.noise)
    decoder_name = _resolve_decoder(args.family, args.decoder)
    if args.family == "surface":
        tasks = component.curve_tasks(args.distances, args.scales, noise)
    else:
        tasks = component.code_curve_tasks([codes.get_code(args.family)], args.scales, noise)
    cells = component.run_curve(
        tasks,
        decoder=decoder_name,
        custom_decoders=decoder.sinter_decoders(),
        max_shots=args.max_shots,
        max_errors=args.max_errors,
        num_workers=args.workers,
    )
    _write_curve_outputs(args, cells, decoder_name)


def _write_curve_outputs(
    args: argparse.Namespace, cells: list[component.CurveCell], decoder_name: str
) -> None:
    """Write CSV + the family-appropriate plot, then print the cells."""
    if args.family == "surface":
        stem = "m0_logical_error_vs_distance"
    else:
        stem = f"m2_{args.family}_logical_error_vs_p"
    csv_path = args.out_dir / f"{stem}.csv"
    png_path = args.out_dir / f"{stem}.png"
    component.write_curve_csv(cells, csv_path)
    if args.family == "surface":
        component.plot_curve(cells, png_path)
    else:
        code = codes.get_code(args.family)
        n, k, d = code.num_data_qubits, code.num_logical, code.distance
        component.plot_rate_curve(
            cells,
            png_path,
            label=f"{code.name} [[{n},{k},{d}]] + {decoder_name}",
            title=f"Logical error vs physical error — {code.name}, {decoder_name}",
        )
    for c in cells:
        print(
            f"d={c.distance}  p2q={c.physical_error:g}  "
            f"errors/shots={c.errors}/{c.shots}  rate={c.logical_error_rate:.3g}"
        )
    print(f"wrote {csv_path} and {png_path}")


def _race_configs(distances: list[int]) -> list[tuple[str, codes.QECCode, str]]:
    """The M4 race lineup: pymatching on surface d, BP+OSD on Q102."""
    lineup: list[tuple[str, codes.QECCode, str]] = [
        (f"surface d={d} · pymatching", codes.get_code("surface", distance=d), "pymatching")
        for d in distances
    ]
    q102 = codes.get_code("gb")
    lineup.append((f"{q102.name} [[102,22,9]] · BP+OSD-0", q102, "bposd"))
    return lineup


def _round_boundaries(segments: component.RoundSegments) -> list[int]:
    """Cumulative detector count at the end of each live-tick segment."""
    counts = (
        [segments.init.num_detectors]
        + [segments.body.num_detectors] * segments.repeats
        + [segments.final.num_detectors]
    )
    boundaries: list[int] = []
    total = 0
    for count in counts:
        total += count
        boundaries.append(total)
    return boundaries


def _progress_printer(interval_s: float = 30.0) -> Callable[[int, int], None]:
    """A time-throttled progress line: silent for fast configs, chatty for slow ones."""
    last = [0.0]

    def report(done: int, planned: int) -> None:
        now = time.monotonic()
        if now - last[0] >= interval_s:
            last[0] = now
            print(f"  ... {done}/{planned} decodes", flush=True)

    return report


def _cmd_decoder_race(args: argparse.Namespace) -> None:
    """Measure per-round decode latency per config; write the plot + CSV artifact."""
    base = component.load_noise_model(args.noise)
    stats: list[decoder.LatencyStats] = []
    for scale in args.scales:
        noise = base if scale == 1.0 else base.scaled(scale)
        for label, code, decoder_name in _race_configs(args.distances):
            circuit = component.build_memory_circuit(code, noise, args.rounds_per_shot)
            dem = str(component.memory_detector_error_model(circuit))
            print(f"measuring {label} at noise {scale:g}x ...", flush=True)
            latencies = decoder.replay_latencies(
                dem,
                decoder_name,
                _round_boundaries(component.split_into_rounds(circuit)),
                min_rounds=args.rounds,
                warmup_rounds=args.warmup,
                seed=args.seed,
                progress=_progress_printer(),
            )
            stat = decoder.summarize_latencies(label, decoder_name, f"{scale:g}×", latencies)
            stats.append(stat)
            print(
                f"{label}  noise {scale:g}x  n={stat.count}  "
                f"p50={stat.p50_ms:.3f} ms  p95={stat.p95_ms:.3f} ms  p99={stat.p99_ms:.3f} ms",
                flush=True,
            )
    csv_path = args.out_dir / "m4_decoder_race.csv"
    png_path = args.out_dir / "m4_decoder_race.png"
    decoder.write_latency_csv(stats, csv_path)
    decoder.plot_latency_race(stats, png_path)
    print(f"wrote {csv_path} and {png_path}")


def _cmd_live(args: argparse.Namespace) -> None:
    """Run the single-block live demo and print the bus-event tallies."""
    noise = component.load_noise_model(args.noise)
    code = _resolve_code(args)
    spec = component.MemoryBlockSpec(code=code, noise=noise, rounds=args.rounds)
    report = machine.run_memory_demo(
        spec,
        shots=args.shots,
        seed=args.seed,
        tick_seconds=args.tick_seconds,
        decoder_name=_resolve_decoder(code.family, args.decoder),
    )
    print(f"bus backend: {report.backend_address}")
    print(
        f"shots={report.shots}  syndrome_events={report.syndrome_events}  "
        f"decodes={report.decode_events}  logical_errors={report.logical_errors}  "
        f"mean_decode_latency={report.mean_decode_latency_s * 1e3:.3f} ms"
    )
    for event in report.events[:50]:
        print(f"  {event.source}: {event.model_dump_json()}")
    if len(report.events) > 50:
        print(f"  ... {len(report.events) - 50} more events")


def _cmd_machine_report(args: argparse.Namespace) -> None:
    """Collect predicted-vs-measured for a machine config; write the CSV artifact."""
    config = machine.load_machine_config(args.machine)
    noise = component.load_noise_model(args.noise)
    result = machine.collect_predicted_vs_measured(
        config,
        noise,
        machine_seconds=args.machine_seconds,
        shots=args.shots,
        rounds=args.rounds,
        seed=args.seed,
    )
    csv_path = args.out_dir / "m5_predicted_vs_measured.csv"
    machine.write_pvm_csv(result, csv_path)
    p = result.prediction
    print(f"machine: {result.machine_name}")
    print(f"logical qubits: predicted {p.logical_qubits}")
    print(
        f"physical qubits: {p.physical_qubits} paper-accounted vs {result.nominal_qubits} nominal"
    )
    print(f"T/day: predicted {p.t_per_day:g}, measured {result.measured_t_per_day:g}")
    if p.t_stall_reason:
        print(f"T queue: {result.t_queue_depth} — {p.t_stall_reason}")
    print(
        f"utilization {result.utilization:.4f} over {result.machine_seconds:.0f} machine-seconds "
        f"({result.stalled_rounds} stalled rounds)"
    )
    ler = (
        f"< {result.logical_error_bound:.3g} (0 errors in {result.shots} shots)"
        if result.logical_errors == 0
        else f"{result.logical_error_per_logical_per_shot:.3g}"
    )
    print(f"logical error / logical / shot: {ler}")
    print(
        f"mean decode latency: {result.mean_decode_latency_s * 1e3:.3f} ms "
        f"over {result.decodes} decodes (budget 6 ms)"
    )
    print(f"wrote {csv_path}")


def _cmd_scaling_report(args: argparse.Namespace) -> None:
    """Run the M7 scaling + interconnect sweeps; write CSVs and the PNG artifact."""
    unit = machine.load_machine_config(args.machine)
    measure_ns = set(args.ns if args.measure_ns is None else args.measure_ns)
    points: list[machine.ScalingPoint] = []
    for n in args.ns:
        if n in measure_ns:
            print(f"measuring fleet of {n} chips ...", flush=True)
            point = machine.measure_point(
                unit,
                n,
                wall_seconds=args.wall_seconds,
                behavioral_rate=args.behavioral_rate,
                noise_name=args.noise,
            )
            print(
                f"  n={n}  modules={point.modules}  "
                f"mix={point.memory_chips}m/{point.factory_chips}f  "
                f"T/day predicted {point.predicted_t_per_day:.3g} "
                f"measured {point.measured_t_per_day:.3g}  "
                f"cross served {point.cross_t_served}",
                flush=True,
            )
        else:
            point = machine.predict_point(unit, n)
        points.append(point)
    link_points = machine.sweep_interconnect(unit, args.rates)
    csv_path = args.out_dir / "m7_scaling.csv"
    link_csv_path = args.out_dir / "m7_interconnect.csv"
    png_path = args.out_dir / "m7_scaling.png"
    machine.write_scaling_csv(points, csv_path)
    machine.write_interconnect_csv(link_points, link_csv_path)
    machine.plot_scaling(points, link_points, png_path)
    for p in link_points:
        note = "link-limited" if p.link_limited else "keeps up"
        print(
            f"pair rate {p.pair_rate_hz:g}/s: serves {p.served_per_second:.2f}/s "
            f"of {p.cross_demand_per_second:g}/s cross demand — {note}"
        )
    print(f"wrote {csv_path}, {link_csv_path} and {png_path}")


def _cmd_node(args: argparse.Namespace) -> None:
    """Run one fleet node in the selected role until interrupted."""
    if args.role == "chip":
        machine.run_chip(
            args.instance,
            args.frontend,
            args.backend,
            noise_name=args.noise,
            machine_name=args.machine_name,
            rounds=args.rounds,
            seed=args.seed,
            pace_ms=args.pace_ms,
            behavioral_rate=args.behavioral_rate,
        )
    elif args.role == "scheduler":
        machine.run_scheduler(
            args.bind_frontend,
            args.bind_backend,
            machine=args.machine,
            heartbeat_timeout_s=args.heartbeat_timeout,
        )
    elif args.role == "provisioner":
        machine.run_provisioner(
            args.frontend,
            args.backend,
            spawn=args.spawn,
            image=args.image,
            network=args.network,
            noise_name=args.noise,
            machine_name=args.machine_name,
            rounds=args.rounds,
            seed=args.seed,
            pace_ms=args.pace_ms,
            initial_chips=args.initial_chips,
        )
    else:
        _serve_dashboard(args, args.frontend, args.backend, active_decoder=None)


def _serve_dashboard(
    args: argparse.Namespace,
    frontend_address: str,
    backend_address: str,
    *,
    active_decoder: str | None,
) -> None:
    """Serve the web UI against an already-running bus."""
    import uvicorn

    config = dashboard.load_dashboard_config(args.dashboard_config)
    app = dashboard.create_app(
        config,
        frontend_address=frontend_address,
        backend_address=backend_address,
        decoders=decoder.available_decoders(),
        active_decoder=active_decoder,
    )
    print(f"dashboard: http://{args.host}:{args.port}  (bus: {backend_address})", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


def _cmd_serve(args: argparse.Namespace) -> None:
    """Start the live backend (single block, machine, or fleet) and serve the UI."""
    noise = component.load_noise_model(args.noise)
    backend: machine.LiveBackend | machine.MachineBackend | machine.FleetBackend
    if args.fleet is not None:
        unit = machine.load_machine_config(args.machine or "chip-256")
        backend = machine.FleetBackend(
            unit,
            chips=args.fleet,
            noise_name=args.noise,
            rounds=args.rounds,
            seed=args.seed,
            tick_seconds=args.pace_ms / 1000.0,
        )
        backend.start()
        try:
            _serve_dashboard(
                args,
                backend.frontend_address,
                backend.backend_address,
                active_decoder=decoder.default_decoder(unit.chip.blocks[0].family)
                if unit.chip.blocks
                else None,
            )
        finally:
            backend.stop()
        return
    if args.machine is not None:
        machine_config = machine.load_machine_config(args.machine)
        backend = machine.MachineBackend(
            machine_config,
            noise,
            rounds=args.rounds,
            seed=args.seed,
            tick_seconds=args.pace_ms / 1000.0,
            decoder_name=args.decoder,
        )
        decoder_name = backend.active_decoders.get("block0", "bposd")
    else:
        code = _resolve_code(args)
        spec = component.MemoryBlockSpec(code=code, noise=noise, rounds=args.rounds)
        decoder_name = _resolve_decoder(code.family, args.decoder)
        backend = machine.LiveBackend(
            spec,
            seed=args.seed,
            tick_seconds=args.pace_ms / 1000.0,
            decoder_name=decoder_name,
        )
    backend.start()
    try:
        _serve_dashboard(
            args, backend.frontend_address, backend.backend_address, active_decoder=decoder_name
        )
    finally:
        backend.stop()


def main(argv: list[str] | None = None) -> None:
    """Entry point for the ``catsim`` command."""
    args = build_parser().parse_args(argv)
    if args.command == "batch-curve":
        _cmd_batch_curve(args)
    elif args.command == "decoder-race":
        _cmd_decoder_race(args)
    elif args.command == "live":
        _cmd_live(args)
    elif args.command == "machine-report":
        _cmd_machine_report(args)
    elif args.command == "scaling-report":
        _cmd_scaling_report(args)
    elif args.command == "node":
        _cmd_node(args)
    elif args.command == "serve":
        _cmd_serve(args)


if __name__ == "__main__":
    main()
