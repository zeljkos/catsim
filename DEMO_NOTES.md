# DEMO_NOTES — rehearsal beats

One beat per milestone, per the charter convention: **show** (what's on screen),
**say** (the one idea the audience takes away), **stat** (the measured number that
backs it — from this repo's artifacts, never quoted from memory).

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
