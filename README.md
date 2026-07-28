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

## Layout

```
catsim/       # the library: codes, component, decoder, machine, dashboard, bus, cli
configs/      # machine / noise / scenario / dashboard YAML — all behavior is config
tests/        # mirrors the package tree
docker/       # chip image + compose for tiled mode
reports/      # measured-vs-paper comparisons
```
