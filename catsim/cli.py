"""Thin command-line shell over the catsim library.

Exists only to parse arguments and delegate; everything the CLI can do must be
callable (and testable) from Python without subprocesses.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from catsim import codes, component, machine


def build_parser() -> argparse.ArgumentParser:
    """Define the CLI surface: one subcommand per library entry point."""
    parser = argparse.ArgumentParser(prog="catsim", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    curve = sub.add_parser("batch-curve", help="logical-error-vs-distance curve (M0)")
    curve.add_argument("--distances", type=int, nargs="+", default=[3, 5, 7])
    curve.add_argument(
        "--scales",
        type=float,
        nargs="+",
        default=[10.0, 30.0, 100.0],
        help="noise multipliers applied to the base model",
    )
    curve.add_argument("--noise", default="paper-baseline")
    curve.add_argument("--max-shots", type=int, default=2_000_000)
    curve.add_argument("--max-errors", type=int, default=200)
    curve.add_argument("--workers", type=int, default=8)
    curve.add_argument("--out-dir", type=Path, default=Path("reports"))

    live = sub.add_parser("live", help="run a live memory block + decoder on the bus")
    live.add_argument("--distance", type=int, default=3)
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
    return parser


def _cmd_batch_curve(args: argparse.Namespace) -> None:
    """Collect the M0 curve and write CSV + PNG under the reports directory."""
    noise = component.load_noise_model(args.noise)
    tasks = component.curve_tasks(args.distances, args.scales, noise)
    cells = component.run_curve(
        tasks, max_shots=args.max_shots, max_errors=args.max_errors, num_workers=args.workers
    )
    csv_path = args.out_dir / "m0_logical_error_vs_distance.csv"
    png_path = args.out_dir / "m0_logical_error_vs_distance.png"
    component.write_curve_csv(cells, csv_path)
    component.plot_curve(cells, png_path)
    for c in cells:
        print(
            f"d={c.distance}  p2q={c.physical_error:g}  "
            f"errors/shots={c.errors}/{c.shots}  rate={c.logical_error_rate:.3g}"
        )
    print(f"wrote {csv_path} and {png_path}")


def _cmd_live(args: argparse.Namespace) -> None:
    """Run the single-block live demo and print the bus-event tallies."""
    noise = component.load_noise_model(args.noise)
    code = codes.get_code("surface", distance=args.distance)
    spec = component.MemoryBlockSpec(code=code, noise=noise, rounds=args.rounds)
    report = machine.run_memory_demo(
        spec, shots=args.shots, seed=args.seed, tick_seconds=args.tick_seconds
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


def main(argv: list[str] | None = None) -> None:
    """Entry point for the ``catsim`` command."""
    args = build_parser().parse_args(argv)
    if args.command == "batch-curve":
        _cmd_batch_curve(args)
    elif args.command == "live":
        _cmd_live(args)


if __name__ == "__main__":
    main()
