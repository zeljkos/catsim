# DEMO_NOTES — rehearsal beats

One beat per milestone, per the charter convention: **show** (what's on screen),
**say** (the one idea the audience takes away), **stat** (the measured number that
backs it — from this repo's artifacts, never quoted from memory).

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
