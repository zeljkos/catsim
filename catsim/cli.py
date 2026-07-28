"""Thin command-line shell over the catsim library.

Exists only to parse arguments and delegate; everything the CLI can do must be
callable (and testable) from Python without subprocesses.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from catsim import codes, component, dashboard, decoder, machine

_DEFAULT_DECODER = {"surface": "pymatching", "gb": "bposd"}
"""Family-appropriate default: matching needs a graphlike DEM, which qLDPC
hyperedges never decompose into; BP+OSD consumes any DEM."""


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

    serve = sub.add_parser("serve", help="dashboard: live block + decoder + web UI")
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
    return requested or _DEFAULT_DECODER.get(family, "pymatching")


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


def _cmd_serve(args: argparse.Namespace) -> None:
    """Start the live backend and serve the dashboard until interrupted."""
    import uvicorn

    noise = component.load_noise_model(args.noise)
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
        config = dashboard.load_dashboard_config(args.dashboard_config)
        app = dashboard.create_app(
            config,
            frontend_address=backend.frontend_address,
            backend_address=backend.backend_address,
            decoders=decoder.available_decoders(),
            active_decoder=decoder_name,
        )
        print(f"dashboard: http://{args.host}:{args.port}  (bus: {backend.backend_address})")
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    finally:
        backend.stop()


def main(argv: list[str] | None = None) -> None:
    """Entry point for the ``catsim`` command."""
    args = build_parser().parse_args(argv)
    if args.command == "batch-curve":
        _cmd_batch_curve(args)
    elif args.command == "live":
        _cmd_live(args)
    elif args.command == "serve":
        _cmd_serve(args)


if __name__ == "__main__":
    main()
