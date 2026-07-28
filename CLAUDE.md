# CLAUDE.md — Walking Cat Simulator (project: `catsim`)

## What this project is

A classical, containerized simulator of the **walking cat architecture** — IonQ's fault-tolerant
trapped-ion quantum computer blueprint (arXiv:2604.19481) — with a **live, configurable
dashboard** as the primary product. We simulate the *machine*, not the *wavefunction*:
real stabilizer simulation of the error-correction layer, real decoders, and a discrete-event
model of the full tiled machine.

The centerpiece is **cause and effect made visible**: inject a fault — one qubit decoheres,
an ion is lost, a cosmic-ray burst, a factory dies, the decoder falls behind — and watch the
machine's immune system respond in real time, layer by layer: physical error → syndrome fires
→ decoder identifies → correction applied → logical state survives (or, past the design
limits, visibly does not).

**The scale story mirrors IonQ's public roadmap (ionq.com/roadmap), grown LIVE:** the demo
starts with ONE chip container — the 2026 device: 256 physical qubits, 12 logical — shows it
working and surviving faults, then the presenter presses "+39 chips" on the dashboard and
real containers boot, self-register, and assemble the 2027 machine (10,000 physical / 800
logical) in front of the audience; "+40" more join over photonic interconnect for the 2028
machine (20,000 / 1,600). One chip proven → the data center grown from copies of it, on
stage. Regularity, made visible.

**Why this is possible:** everything the architecture does — syndrome extraction, cat states,
Bell pairs, transport, leakage — is Clifford, and Clifford circuits are classically simulable
in polynomial time (Gottesman–Knill). Thousands of qubits run fine on a laptop.

## Non-goals (do not attempt)

- No full state-vector simulation of 100+ qubit registers (2^n kills it) and no "tiling"
  state-vector simulators over a network — entangled states do not factor across boundaries.
  Tiling works only in the stabilizer / discrete-event layers, which is what we build.
- No simulating logical algorithms with large T-counts (cap exact non-Clifford at ~20 T gates).
- No pretending: the dashboard footer always states "stabilizer + behavioral simulation
  calibrated to arXiv:2604.19481." When simulated numbers diverge from the paper's, that is
  a finding to surface, never something to tune away.

## Architecture: three simulation layers + the dashboard

### Layer 1 — Component simulator (stabilizer, package `catsim/component/`)
Stim circuits for each organ, with the paper's noise model, run as a **continuously ticking
live process** (one syndrome-extraction round per tick) that streams events — not just as
offline Monte Carlo:
- `memory_block`: one qLDPC memory block, repeated syndrome extraction.
- `cat_factory`: cat-state preparation + verification (track acceptance rate).
- `bell_factory`: Bell pairs across blocks, verification.
- `magic_factory`: Clifford skeleton of the MEK scheme; distillation acceptance.
Every physical event is emitted on a bus (ZeroMQ pub/sub, one topic per component):
`error_injected`, `syndrome_fired {check_ids}`, `decode_started/finished {latency,
identified_qubits}`, `correction_applied`, `logical_error`, `ion_lost`, `qubit_replaced`.
The dashboard subscribes to this bus. Monte Carlo batch mode (sinter) reuses the same
circuit builders for statistics with error bars.

**Code caveat:** the paper's [[102,22,9]] / [[70,6,9]] check matrices may not be public.
Codes are a pluggable interface (`catsim/codes/`): validate the pipeline with a small surface
code first (known-good, great visuals), then a published qLDPC stand-in of similar rate and
distance. Never hard-code one code.

### Layer 2 — Decoder (package `catsim/decoder/`)
BP+OSD (`ldpc` package) for qLDPC; `pymatching` for the surface-code baseline. Runs in the
live loop (its latency per round is real measured wall-clock, streamed to the dashboard) and
in a batch harness for the p50/p99-vs-6ms-budget race. Decoder must be swappable and
throttleable at runtime (artificial slowdown factor — for the "decoder falls behind" scenario).

### Layer 3 — Machine simulator (discrete-event, package `catsim/machine/`)
SimPy model of the full machine, calibrated by Layer 1/2 measurements: chips host memory
blocks and factories; Bell links are ZeroMQ messages; a scheduler issues logical instructions
and tracks queues, stalls, and throughput.

**The chip unit (matches the 2026 device):** 256 physical qubits ≈ two [[70,6,9]] memory
blocks (6 logical each → 12 logical) + shared cat-factory/routing/reservoir overhead.
`qubits_per_chip`, blocks-per-chip, and roles are YAML config, never hard-coded.

**Elastic runtime — the machine grows live (this is the core demo mechanic).**
There is exactly ONE unit of scale: the chip container (one image, one 256-qubit chip
simulation). The machine is never defined as a static topology; it is whatever chips are
currently registered:

- **Join protocol:** a chip container boots knowing only the bus address. It announces
  itself (`chip_announce {capabilities}`), the scheduler admits it, assigns `chip_id`, role
  (memory / magic factory / Bell factory — rebalanced per walking cat Table I ratios as the
  fleet grows), and Bell-link neighbors. Chip starts ticking; capacity counters rise.
- **Leave protocol:** heartbeats on the bus; missed heartbeats → scheduler marks the chip
  lost, reassigns its role, machine degrades gracefully (this doubles as the failure story —
  scaling and fault-tolerance are the same code path, which is exactly the walking cat's
  own philosophy).
- **Provisioner service:** the only component allowed to talk to the Docker API (python
  `docker` SDK, socket mounted into this one container only). It exposes exactly two
  operations on the bus: `scale_up {n}` and `drain {chip_id | n}`. Dashboard buttons call
  these. Nothing else in the system knows Docker exists.
- **Machine tiers are just scale targets** (from ionq.com/roadmap, the demo's three acts):
  1 chip = 2026 (256 physical / 12 logical) → "+39" = 2027 (10,000 / 800) → "+40" = 2028
  (20,000 / 1,600). For 2028, chips 41–80 join as a second module: inter-module Bell links
  are marked **photonic interconnect** with distinct higher latency / lower rate, visible
  in the machine view.
- Fallback for machines without Docker (CI, quick dev): provisioner spawns chips as local
  processes instead — same join protocol, so nothing else changes.

### The dashboard (package `catsim/dashboard/`) — first-class product, not an afterthought
FastAPI + WebSocket backend subscribed to the event bus; single-page frontend. Dark theme,
orange #E8701A machine accent, blue #3B82F6 workload accent (matches the owner's deck/blog).

**Views (all toggleable):**
- **Block view** — the hero view. Grid of physical qubits for a selected memory block.
  Error events flash red on the qubit, triggered stabilizer checks light amber, the decoder's
  identified qubits outline blue, applied corrections flash green, residual logical errors
  turn the block's border red and increment a logical-error counter. A cycle timeline below
  scrubs back through recent rounds (ring buffer) to replay an event slowly.
- **Machine view** — topology of chips, factories, Bell links, scheduler; per-node health,
  queue depths, utilization; amber/red degradation states.
- **Metrics view** — live charts: logical error rate, decoder latency (p50/p99 vs the 6 ms
  line), T-gate throughput, factory acceptance rates, loss/replacement counts.
- **Event log** — filterable stream of bus events with timestamps and cycle numbers.

**Injection console (the demo's steering wheel):** every fault is injectable live, from the UI:
- Click any qubit → inject X / Y / Z error ("decoherence"), ion loss, or leakage, at the
  next cycle.
- Area burst: select a region → correlated multi-qubit error (cosmic-ray scenario).
- Sliders (live, no restart): 2q gate error (1e-5 … 1e-2), measurement error, loss rate,
  decoder slowdown factor, factory acceptance derating.
- Kill switches: pause/kill any factory, chip, or Bell link; sever/restore network partitions.
- Decoder on/off toggle (show what "no error correction" looks like — errors accumulate
  unchecked; brutal and instructive).
- **Scale controls:** "+1 chip", "+N chips", preset buttons for the roadmap tiers
  (1 → 40 → 80), and drain/remove. Pressing "+20" starts 20 real containers; the machine
  view animates each one joining, getting a role, and linking in. This is the money moment
  for scalability — chips must appear one by one as they register, not all at once after a
  batch completes.

**Configurability (hard requirement):** everything above is driven by YAML, no code edits:
- `configs/machine/*.yaml` — machine instances (`chip-2026`, `dc-2027`, `dc-2028`, plus
  paper Table I configs): chips, qubits/blocks per chip, factories, link latencies.
- `configs/noise/*.yaml` — named noise models (paper-baseline, optimistic, pessimistic, custom).
- `configs/dashboard.yaml` — which panels, layout, refresh rates, plot windows, thresholds
  for amber/red.
- `configs/scenarios/*.yaml` — **scripted, replayable scenarios**: a timeline of injections
  and config changes. Scenarios are the rehearsable demo units.

**Shipped scenarios (each a YAML file + one-line description in the UI):**
1. `single-decoherence` — one qubit takes a Z error; syndrome → decode → correct in one
   cycle; logical state untouched. The "immune system" moment.
2. `ion-loss` — an ion disappears; loss detected, qubit factory swaps in a replacement,
   block re-stabilizes.
3. `beyond-distance` — a burst wider than the code distance; watch the decoder lose,
   a logical error land, and the counter tick. Honest about the design limits.
4. `threshold-sweep` — physical error slider ramps from 1e-5 to 1e-2 live; logical error
   rate collapses then explodes as it crosses threshold. **The Moore–Shannon staircase, live**
  — ties directly to the blog post.
5. `factory-outage` — kill a magic-state factory; machine-view queues back up, throughput
   sags, restart, recovery.
6. `decoder-overload` — decoder slowdown factor past the 6 ms budget; backlog grows, errors
   accumulate faster than they're corrected.

## Canonical parameters

From arXiv:2604.19481 (cite section per constant in code):

| Parameter | Value |
|---|---|
| Two-qubit gate error | 1e-4 (single-qubit 1e-5) |
| Ion loss probability | 1e-7 |
| Physical operation cycle (POC) | 200 µs |
| Syndrome-extraction cycle (SEC, logical clock) | 30 POC ≈ 6 ms |
| Memory codes | [[70,6,9]] (6 logical/block) and [[102,22,9]] (22 logical/block) |
| Paper reference configs (Table I) | 5×Q102+1×CH2: 110 logical / 2,514 physical / 1M T/day; 10×Q102+1×CH2: 220 / 4,540 / 1M |
| T-gate latency / throughput | ~75 ms; ~11–13 T/s ≈ 1M/day per CH2 factory |
| Reference workload | 100-site Heisenberg, 162 logical / ~10K physical, ~1 month |

From ionq.com/roadmap (the demo's machine tiers):

| Year | Physical | Logical | Notes |
|---|---|---|---|
| 2026 | 100–256+ | 12 | 99.99% physical fidelity, logical error <1e-7 — THE chip |
| 2027 | 10,000 | 800 | 40× the 2026 chip |
| 2028 | 20,000 | 1,600 | + photonic interconnect between modules |

**Reconciliation note (be ready for the question):** Table I's ratio (~21:1 physical:logical)
targets logical error 1e-10; the roadmap's denser 12.5:1 targets 1e-7. The paper says
explicitly that more logical qubits are available at a higher target logical error rate.
The demo's default target is therefore **1e-7** to match the roadmap; a config switch to the
1e-10 / Table I regime must exist and visibly cost logical qubits — that switch itself is a
good 30-second demo beat (reliability is purchasable with qubits).

## Stack

Python 3.11+: `stim`, `sinter`, `pymatching`, `ldpc`, `simpy`, `pyzmq`, `fastapi`,
`uvicorn`, `pydantic`, `pyyaml`, `numpy`, `pytest`. Frontend: single-page, no build step if
possible (htmx/vanilla + a lightweight chart lib). Docker + compose for tiled mode.
Keep the core library container-agnostic.

## Repository layout

```
catsim/
  codes/        # pluggable code definitions (surface, qLDPC stand-in)
  component/    # Layer 1: stim builders, noise models, live tick loop, event emission
  decoder/      # Layer 2: BP+OSD / pymatching wrappers, throttle, timing harness
  machine/      # Layer 3: simpy model + zmq runtime
  dashboard/    # FastAPI backend + static frontend
  bus/          # event schema (pydantic), zmq transport, on-request query channel
  scenario.py   # scripted scenario schema + runner (bus commands on a timeline)
  cli.py        # catsim run --machine ... --noise ... --scenario ...
configs/
  machine/  noise/  scenarios/  dashboard.yaml
tests/
docker/
reports/
```

## Milestones (dashboard arrives early — it is the product)

- **M0 — Pipeline proof.** Surface-code memory block in stim + pymatching, paper noise,
  live tick loop emitting bus events; logical-error-vs-distance curve in batch mode.
  Acceptance: error suppression visible below threshold; events streaming on the bus.
- **M1 — Dashboard v1 + injection.** Block view + event log + injection console (single-qubit
  errors, loss, sliders) on top of M0. Acceptance: `single-decoherence` and `beyond-distance`
  scenarios run from YAML and look right; replay scrubber works.
- **M2 — qLDPC block + BP+OSD.** Stand-in qLDPC code through the same pipeline; decoder
  swappable at runtime. Acceptance: `threshold-sweep` scenario live on the qLDPC block.
- **M3 — Factories.** Cat/Bell/magic components with acceptance rates; `ion-loss` scenario
  (qubit factory replacement) end-to-end.
- **M4 — Decoder race.** Batch p50/p99 vs 6 ms budget plot; live decoder-latency panel;
  `decoder-overload` scenario. Acceptance: the p99-vs-code-size plot with the 6 ms line.
- **M5 — One chip (`chip-2026`).** SimPy machine layer for the single 256-qubit / 12-logical
  chip, calibrated from M2–M4 numbers; machine view; `factory-outage` scenario. Acceptance:
  the full one-chip demo runs end-to-end — Act 1 done.
- **M6 — Elastic containers to `dc-2027`.** Chip image + join/leave protocol + provisioner;
  dashboard "+N chips" grows the machine live from 1 to ~40 chips (10,000 physical / 800
  logical) on one host. Acceptance: Act 2 done — pressing "+39" on stage works every time;
  killing any chip mid-growth recovers cleanly, 10 consecutive times; T-gates/day with
  bottleneck attribution.
- **M7 — `dc-2028` + polish.** "+40" more chips join as a second module over photonic
  interconnect (distinct latency/rate, visible in machine view) → 20,000 / 1,600;
  `make demo` / `make reset` (<10 s, rehearsable); sensitivity sweeps; report comparing
  measured vs paper and roadmap numbers. Acceptance: all three acts run back-to-back in
  one sitting, driven entirely from dashboard buttons.

## Engineering standards — NON-NEGOTIABLE

This codebase must stay maintainable by one busy person. Modularity is a requirement, not a
style preference. Claude Code: enforce these rules on yourself in every session; refactor
violations on sight rather than extending them.

**Module boundaries and dependency direction.** The packages form a strict layered graph —
imports flow only downward:

```
dashboard  →  bus, machine (read-only queries)
machine    →  bus, decoder, component
decoder    →  bus, codes
component  →  bus, codes
codes      →  (nothing internal — leaf)
bus        →  (nothing internal — leaf)
```

- NEVER import upward or sideways across this graph (e.g. `component` must not import
  `machine`; `codes` must not import `stim` wrappers from `component`). If two modules need
  each other, the design is wrong — extract the shared concept into a lower layer.
- The **event bus is the only runtime coupling** between running services. Components never
  call each other's internals; they publish and subscribe. Event schemas live in `bus.py`
  as pydantic models — they are the contract, versioned, and changing one is a breaking
  change requiring a schema version bump.
- Each package exposes a small public API through `__init__.py`; everything else is private.
  Other packages import ONLY the public API.

**Pluggability via interfaces.** Codes, decoders, and noise models are plugins behind
`Protocol` classes (`QECCode`, `Decoder`, `NoiseModel`) with a registry keyed by name, so a
YAML string selects the implementation. Adding a new code/decoder = one new file + one
registry entry, zero edits elsewhere. If adding a feature requires touching more than two
packages, stop and redesign.

**Size and shape discipline.**
- No module over ~300 lines; no function over ~40; no class doing two jobs. Split early.
- No global mutable state. Configuration is loaded once into frozen pydantic objects and
  passed explicitly (constructor injection). No singletons except the process's bus handle.
- Dashboard contains ZERO physics/business logic — it renders bus events and issues commands
  back onto the bus. If a number is computed in the dashboard, it's in the wrong place.
- CLI is a thin shell over library calls; everything the CLI can do must be callable from
  Python (and therefore testable) without subprocesses.

**Quality gates (wire these up in M0, not later).**
- `ruff` (lint + format) and `mypy --strict` on all of `catsim/`; pre-commit hooks; CI runs
  `make check` = lint + typecheck + tests. A milestone is not done with red checks.
- Tests mirror the package tree (`tests/component/…`); every public API function has at
  least one test; bus schemas have round-trip serialization tests.
- Docstring on every public class/function: one line of what, one line of why it exists.

**Definition of done for any change:** checks green, no new cross-layer imports (enforce
with `import-linter` contracts in CI), docstrings present, and the change describable in one
sentence. If it can't be described in one sentence, split it.

## Conventions

- Every run is a config + seed; reproducible. Every batch metric ships with error bars.
- Every component circuit has a noiseless test (zero errors in → zero syndromes out) and a
  calibration test (known noise in → expected syndrome rate out).
- Scenario YAMLs are the demo units: rehearsed, deterministic where it matters.
- Plots/UI follow the house style (dark bg, ink/gray, orange #E8701A, blue #3B82F6).

## Reference

- Paper: arXiv:2604.19481 — source of truth for physics/architecture parameters (cite section
  per constant). Roadmap tiers: ionq.com/roadmap (2026: 256/12 · 2027: 10,000/800 ·
  2028: 20,000/1,600 + photonic interconnect).
- Stim/sinter: github.com/quantumlib/Stim. Decoders: `ldpc` (BP+OSD, Roffe), `pymatching`.
- Background: Gottesman–Knill (why simulable); Aharonov–Ben-Or threshold theorem (why the
  machine works) — the `threshold-sweep` scenario is this theorem made visible.
