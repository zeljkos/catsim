# catsim — Walking Cat Simulator

A classical, containerized simulator of the **walking cat architecture** — IonQ's
fault-tolerant trapped-ion blueprint (arXiv:2604.19481) — with a live, configurable
dashboard as the primary product. We simulate the *machine*, not the *wavefunction*:
stabilizer simulation of the error-correction layer, real decoders, and a
discrete-event model of the full tiled machine.

See `CLAUDE.md` for the full project charter (architecture, milestones, and
non-negotiable engineering standards).

## Getting started

```sh
make setup   # venv + editable install + dev tools + pre-commit hooks
make check   # lint + mypy --strict + import-linter contracts + tests
```

## Running the demo

```sh
make demo         # elastic fleet, 1 chip, local processes; dashboard on :8000
make demo-docker  # the same fleet as real containers (compose)
make reset        # kill every fleet process/container, fresh slate (<10 s)
```

From the dashboard's machine view, "+N chips" grows the machine live: each
chip is its own process/container that boots knowing only the bus address,
announces itself, and gets a role from the scheduler (memory vs magic-state
factory, balanced per the paper's Table I mix). Exactly one **focus** chip
runs the full stim + decoder stack (`live`); the rest run calibrated SimPy
loops (`behavioral`) — click any chip to move the focus. Killing a chip
(`docker kill`, SIGKILL) exercises the same path as scaling: heartbeats miss,
the chip is declared lost, roles and T-gate demand rebalance.

## Layout

```
catsim/       # the library: codes, component, decoder, machine, dashboard, bus, cli
configs/      # machine / noise / scenario / dashboard YAML — all behavior is config
tests/        # mirrors the package tree
deploy/       # the one fleet image (role from env) + compose for container mode
reports/      # measured-vs-paper comparisons
```
