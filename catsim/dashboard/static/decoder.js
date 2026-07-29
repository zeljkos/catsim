// Decoder race panel: rolling p50/p99 latency vs the SEC budget line, queue
// depth, amber/red states. Pure rendering — latencies and queue depths arrive
// measured on bus events; only display percentiles are derived here.

export function createDecoderPanel(cfg, panelEl) {
  const budget = cfg.budget_ms;
  const latencies = []; // rolling window, ms
  let queueDepth = 0;

  const $ = (cls) => panelEl.querySelector(cls);

  function percentile(sorted, p) {
    if (!sorted.length) return null;
    const i = Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1);
    return sorted[Math.max(0, i)];
  }

  function fmt(ms) {
    return ms === null ? "–" : ms >= 100 ? ms.toFixed(0) : ms.toFixed(2);
  }

  function render() {
    const sorted = [...latencies].sort((a, b) => a - b);
    const p50 = percentile(sorted, 50);
    const p99 = percentile(sorted, 99);
    $(".d-p50").textContent = fmt(p50);
    $(".d-p99").textContent = fmt(p99);
    $(".d-queue").textContent = queueDepth;

    const red = queueDepth >= cfg.red_queue_depth;
    const amber = !red && p99 !== null && p99 >= cfg.amber_latency_fraction * budget;
    panelEl.classList.toggle("red", red);
    panelEl.classList.toggle("amber", amber);
    const badge = $(".d-badge");
    badge.textContent = red ? "queue growing" : amber ? "near budget" : "keeping up";
    badge.className = `d-badge ${red ? "red" : amber ? "amber" : "ok"}`;

    drawChart();
  }

  // Strip chart: one bar per recent decode, log-scaled around the budget line.
  function drawChart() {
    const svg = $(".d-chart");
    const W = 100, H = 34, n = latencies.length;
    if (!n) { svg.innerHTML = ""; return; }
    const floor = budget / 100; // 2 decades below budget on screen
    const ceil = budget * 10;   // 1 decade above
    const y = (ms) => {
      const clamped = Math.min(Math.max(ms, floor), ceil);
      return H - (Math.log10(clamped / floor) / Math.log10(ceil / floor)) * H;
    };
    const bw = W / cfg.window;
    const bars = latencies.map((ms, i) => {
      const top = y(ms);
      const over = ms > budget;
      return `<rect x="${(i * bw).toFixed(2)}" y="${top.toFixed(2)}" width="${Math.max(bw - 0.08, 0.15).toFixed(2)}" height="${(H - top).toFixed(2)}" class="${over ? "over" : "under"}"/>`;
    });
    const yb = y(budget);
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.innerHTML =
      bars.join("") +
      `<line x1="0" y1="${yb}" x2="${W}" y2="${yb}" class="budget"/>` +
      `<text x="${W - 1}" y="${yb - 1.2}" class="budget-label" text-anchor="end">${budget} ms budget</text>`;
  }

  function onEvent(ev) {
    switch (ev.type) {
      case "decode_finished":
        latencies.push(ev.latency_s * 1000);
        if (latencies.length > cfg.window) latencies.shift();
        render();
        break;
      case "decode_queue":
        queueDepth = ev.depth;
        render();
        break;
    }
  }

  return { onEvent };
}
