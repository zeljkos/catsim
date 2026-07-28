// Factories panel: one tile per factory source, rendered from bus events.
// Pure rendering — rates and verdicts arrive precomputed on the events; only
// the attempts/s display statistic is derived here (from event arrival times).

export function createFactoriesPanel(getContainer, getEmptyNote) {
  const factories = new Map(); // source -> {el, history, stamps}

  function tile(source) {
    let f = factories.get(source);
    if (f) return f;
    const empty = getEmptyNote();
    if (empty) empty.classList.add("hidden");
    const el = document.createElement("div");
    el.className = "tile";
    el.innerHTML =
      `<div class="tile-head"><span class="tile-name"></span><span class="tile-kind muted"></span></div>` +
      `<div class="tile-stats">` +
      ["produced", "acceptance", "rate", "residual"]
        .map((k, i) => `<div class="tile-stat"><span class="t-${k}">–</span>` +
          `<label>${["produced", "accepted", "attempts/s", "output err"][i]}</label></div>`)
        .join("") +
      `</div><div class="tile-strip"></div><div class="tile-note muted"></div>`;
    el.querySelector(".tile-name").textContent = source;
    getContainer().appendChild(el);
    f = { el, history: [], stamps: [] };
    factories.set(source, f);
    return f;
  }

  function pushVerdict(f, verdict) {
    f.history.push(verdict);
    if (f.history.length > 24) f.history.shift();
    f.el.querySelector(".tile-strip").innerHTML =
      f.history.map((v) => `<span class="dot ${v}"></span>`).join("");
  }

  function onEvent(ev) {
    const f = tile(ev.source);
    const set = (cls, text) => { f.el.querySelector(cls).textContent = text; };
    switch (ev.type) {
      case "factory_configured":
        set(".tile-kind", `${ev.kind} · ${ev.output_qubits}q out · ${ev.verification_checks} checks` +
          (ev.noise_name ? ` · ${ev.noise_name}` : ""));
        break;
      case "factory_attempt":
        f.stamps.push(performance.now());
        if (f.stamps.length > 20) f.stamps.shift();
        if (f.stamps.length >= 2) {
          const secs = (f.stamps[f.stamps.length - 1] - f.stamps[0]) / 1000;
          set(".t-rate", secs > 0 ? ((f.stamps.length - 1) / secs).toFixed(1) : "–");
        }
        break;
      case "factory_accepted":
        set(".t-produced", ev.accepted);
        set(".t-acceptance", `${(ev.acceptance_rate * 100).toFixed(1)}%`);
        set(".t-residual", `${(ev.output_error_rate * 100).toFixed(1)}%`);
        pushVerdict(f, ev.residual_checks.length ? "residual" : "ok");
        break;
      case "factory_rejected":
        set(".t-acceptance", `${(ev.acceptance_rate * 100).toFixed(1)}%`);
        set(".tile-note", `attempt ${ev.attempt} rejected · checks [${ev.failed_checks}]`);
        pushVerdict(f, "reject");
        break;
    }
  }

  return { onEvent };
}
