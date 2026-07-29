# DEMO_NOTES — rehearsal beats

One beat per milestone, per the charter convention: **show** (what's on screen),
**say** (the one idea the audience takes away), **stat** (the measured number that
backs it — from this repo's artifacts, never quoted from memory).

## M6 — the machine grown live, 1 → 40 chips

**Show.** `make demo` (process fallback) or `make demo-docker` (real containers):
the machine view holds ONE chip — chip0, `▦ memory`, badge **live** (blue border:
this chip runs the full stim + BP+OSD stack; the block view is its real physics).
Type **39** in the scale input, press **+N chips**. Tiles flash orange as each
container boots, announces itself on the bus, and gets admitted — one by one, not
as a batch. Around chip 18 the first tile comes up **⚙ factory** instead of memory:
the scheduler is balancing roles to the paper's Table I mix, and the T-gates/day
row in predicted-vs-measured leaves zero for the first time — computation was
bought with chips. Click any chip: the **live** badge moves, the block view now
shows that chip's real syndrome stream (fidelity dial — one chip gets real
physics, the fleet stays behavioral, because real decoding costs ~300 ms/round
against a 6 ms budget; see stat). Then the failure beat: `docker kill` a chip
(factory chips are the cruelest choice) — heartbeats miss, the tile goes red
**lost**, the fleet count drops, its unserved T queue is handed to the surviving
factory, a role flips to restore the mix. Scaling and fault-tolerance are the
same code path, on screen. `make reset` → clean slate in ~5 s.

**Say.** There is exactly one unit of scale: a 256-qubit chip container — one
image, role assigned at admission, booting knowing nothing but the bus address.
A machine is not a topology; it is whatever chips are currently registered. So
"building the 2027 machine" is pressing +39, and losing a chip is just the join
protocol running backwards. Second idea: the fleet's fidelity dial is the trick
that makes this classically watchable — stabilizer physics where you're looking,
calibrated behavioral models everywhere else — and the dashboard never hides
which is which (every chip wears its mode badge).

**Stat.** (seeded; scripts in the M6 acceptance run; fleet dynamics pinned in
`tests/machine/`)

| metric | value |
|---|---|
| growth 1 → 40 chips (process mode) | 4.3 s, chips registering one-by-one; roles balanced 38 memory / 2 CH2 factory (Table I 17:1) |
| capacity at 40 chips | 10,240 nominal / 10,502 paper-accounted (Table V) / 228 logical |
| T gates/day at 40 chips | predicted capacity 2.29M (2× CH2); **measured 1.047M** — right at the paper's ~1M/day reference — queue ≈ 0, attribution "demand-limited: factory capacity exceeds the workload" (12 T/s demand) |
| N=1 vs M5 | logical 6 = 6; paper qubits 462 = 462; T/day 0 = 0 with identical stall attribution; T queue grows at 12.0/s of machine time (= demand); 0 logical errors in 515 shots; live decode mean 243.7 ms over 477 decodes vs M5's 324 ms (same OSD-0-fallback-dominated bimodal regime) |
| kill/recovery, process mode (SIGKILL, mid-growth) | **10/10 clean**, loss declared 2.3–3.0 s (3 s heartbeat timeout); round 5 killed the live focus chip itself — focus re-assigned, live stack rebooted on the survivor |
| kill/recovery, Docker (`docker kill`, mid-growth) | **10/10 clean**, loss declared 4.3–5.2 s (5 s timeout), fleet back to size each round |
| fleet footprint | 40 chip processes ≈ 4.9 GB RSS; teardown 4.3 s; `make reset` from a 12-container stack 5.5 s |
| why the fidelity dial is load-bearing | M4/M5: BP+OSD averages ~300 ms per Q70 decode vs the 6 ms SEC — 40 chips × 2 blocks of live decoding is ~100× oversubscribed on one host; exactly one focus chip runs live |

Findings worth repeating: (1) a live chip's heartbeats legitimately gap during
BP+OSD's seconds-long OSD-0 tail decodes — under host load the scheduler
false-declared the focus chip lost until live-mode chips got a 4× heartbeat
allowance (`_LIVE_TIMEOUT_FACTOR`); the decode-tail problem from M4 reaches all
the way into cluster membership. (2) stim/pymatching publish no linux/aarch64
wheels — the chip image compiles them in a builder stage. (3) A repo directory
named `docker/` shadows the `docker` SDK as a namespace package; it is `deploy/`
now.

## M5 — one chip, priced honestly

**Show.** `catsim serve --machine chip-256-roadmap`: the machine view. Chip0's
composition card — two Q70 [[70,6,9]] blocks at 220 + 42 (cat unit) qubits each —
with the **lean accounting badge**: 256 nominal sitting next to **524
paper-accounted** (hover for the divergence note, also in the footer). Cat-buffer
gauges full and green, the predicted-vs-measured table, and the T queue climbing
with its attribution spelled out: *no magic factory — T gates need a factory
chip.* Then run the `factory-outage` scenario: cat0 dies, its block's buffer
drains one cat per round on screen, the block goes amber → red-stalled,
utilization sags, the chip degrades; the factory revives, the buffer refills at
2 accepts/SEC, stalls freeze, the chip cools back to green.

**Say.** A chip is a bill of materials, and the paper publishes the price list
(Table V). The roadmap's "256 physical / 12 logical" for 2026 only adds up with
lean counting — the same two blocks at the paper's all-in prices cost 524 qubits.
Both numbers stay on screen; divergence is displayed, never tuned away. Second
idea: a memory chip alone is not a computer — with no magic factory the T-gate
queue just grows, so computation is something you *buy with more chips* (that's
Act 2). Third: the cat factory is load-bearing infrastructure, not decoration —
in this architecture syndrome extraction consumes a verified cat state every
round, so when the factory dies, error correction itself starves. Scaling and
fault-tolerance are the same code path.

**Stat.** (seeded; `reports/m5_predicted_vs_measured.csv` via
`catsim machine-report --machine chip-256`; model dynamics pinned in
`tests/machine/`)

| metric | predicted (paper arithmetic) | measured (live) |
|---|---|---|
| logical qubits | 6 (1× Q70) | 6 |
| physical qubits | 462 paper-accounted (220 block + 42 cat + 200 reservoir) | 256 nominal label |
| T gates/day | 0 — no magic factory | 0; queue 7,200 deep after 600 machine-s at 12 T/s demand |
| utilization | 1.0 | 1.0000 (0 stalled rounds in 100k SECs) |
| logical error / logical / shot | suppressed below run resolution | < 3.33e-3 (0 errors, 50 shots × 10 rounds) |
| decode latency | 6 ms SEC budget | mean 324 ms over 51 decodes — BP+OSD-0's bimodal tail on Q70 too |

Prediction module reproduces Table I from Table V prices + Table VII gate times
(pinned in `tests/machine/test_prediction.py`): 5×Q102+1×CH2 → 110 logical,
1.046M T/day (paper: 110, 1.0M); 17×Q70+1×CH2 → 1.147M (paper 1.1M);
17×Q70+3×MEK → 1.296M (paper 1.3M). Outage dynamics: buffer (24) drains in 24
rounds, block stalls; on revival, refill in ~24 rounds and stalls stop dead.

Finding worth repeating: the qLDPC decode-tail problem (M4) is not a Q102
quirk — Q70 with BP+OSD-0 at paper noise averages 324 ms against the 6 ms
budget, dominated by OSD-0 fallbacks. The machine's real-time story still
depends on the paper's custom streaming decoder.

## M4 — the decoder race

**Show.** The decoder race panel during the `decoder-overload` scenario: the block
ticking at the real 6 ms SEC pace, rolling p50/p99 latency against the red budget
line, then the throttle hits — the queue-depth counter climbs (panel border goes
red), corrections lag whole shots behind the block — throttle off, the backlog
drains in a blink and the border cools. Then the batch artifact
`reports/m4_decoder_race.png`: three pymatching columns hugging the floor,
one BP+OSD column spanning five decades straight through the budget line.

**Say.** Error correction is a real-time system: every 6 ms round must be decoded
in under 6 ms, forever, or corrections fall behind and errors pile up faster than
they're fixed. For surface codes, open-source matching wins that race with three
orders of magnitude to spare — decoding is a solved problem. For the qLDPC codes
this machine actually uses, the open-source decoder keeps up *on the median* and
then blows the budget by a factor of ~2,700 in the tail — the p99 is sixteen
seconds, not six milliseconds. That tail is why the paper's team built a custom
streaming decoder (<1 ms/SEC measured) — qLDPC decoding is a genuine hard
engineering problem, and this panel is honest about whose decoder is on screen.

**Stat.** (2,000 measured decodes per config, seeded, warm-up excluded; single
core, `reports/m4_decoder_race.csv`)

| config | noise | p50 | p95 | p99 |
|---|---|---|---|---|
| surface d=3/5/7 · pymatching | 1× and 5× | ~0.003 ms | ≤0.008 ms | ≤0.022 ms |
| Q102 [[102,22,9]] · BP+OSD-0 | 1× (paper) | 0.087 ms | 151 ms | 16,153 ms |
| Q102 [[102,22,9]] · BP+OSD-0 | 5× | 100 ms | 15,300 ms | 17,567 ms |

Live overload beat: throttled 10,000× at 50× noise, the queue peaked **75 rounds
behind** and drained to 0 within a round of the throttle lifting.

Finding worth repeating on stage: BP+OSD latency is violently bimodal — when BP
converges it's ~0.1 ms (inside budget!); when it falls back to OSD-0 it's seconds.
The mean (0.55 s at paper noise) describes neither mode. Real-time decoding is a
tail-latency problem, not a throughput problem.
