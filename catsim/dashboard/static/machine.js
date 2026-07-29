// Machine view: chip tiles (composition, accounting, health) and the
// predicted-vs-measured panel, rendered from machine bus events.
// Pure rendering — every number arrives precomputed on the events; the paper's
// arithmetic runs in the machine layer, never here (charter).

export function createMachinePanel(getContainer, getEmptyNote, getSummary, getFooterNote) {
  const chips = new Map(); // chip_id -> element
  const chipKeys = new Map(); // chip_id -> last announcement (chips re-announce; dedupe)

  function fmt(n) {
    if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
    if (n >= 1e4) return `${(n / 1e3).toFixed(0)}k`;
    return Number.isInteger(n) ? String(n) : n.toPrecision(3);
  }

  function chipTile(chipId) {
    let el = chips.get(chipId);
    if (el) return el;
    const empty = getEmptyNote();
    if (empty) empty.classList.add("hidden");
    el = document.createElement("div");
    el.className = "tile chip-tile";
    el.innerHTML =
      `<div class="tile-head"><span class="tile-name"></span>` +
      `<span class="m-accounting muted"></span>` +
      `<span class="m-state state-badge ok">ok</span></div>` +
      `<div class="m-qubits muted"></div>` +
      `<div class="m-blocks"></div>` +
      `<div class="m-factories muted"></div>`;
    el.querySelector(".tile-name").textContent = chipId;
    getContainer().appendChild(el);
    chips.set(chipId, el);
    return el;
  }

  function onChipConfigured(ev) {
    const key = JSON.stringify({ ...ev, tick: 0 });
    if (chipKeys.get(ev.chip_id) === key) return;
    chipKeys.set(ev.chip_id, key);
    const el = chipTile(ev.chip_id);
    el.querySelector(".tile-name").textContent = `${ev.chip_id} · ${ev.machine_name}`;
    const acct = el.querySelector(".m-accounting");
    acct.textContent = `${ev.accounting} accounting`;
    acct.title = ev.accounting_note || "Table V all-in prices";
    const divergent = ev.paper_qubits !== ev.nominal_qubits;
    el.querySelector(".m-qubits").innerHTML =
      `${ev.nominal_qubits} qubits nominal · ` +
      `<span class="${divergent ? "diverges" : ""}" title="${escapeAttr(ev.accounting_note)}">` +
      `${ev.paper_qubits} paper-accounted (Table V)</span> · ${ev.logical_qubits} logical`;
    el.querySelector(".m-blocks").innerHTML = ev.blocks
      .map(
        (b) =>
          `<div class="m-block" data-block="${b.block_id}">` +
          `<span class="m-block-name">${b.block_id}</span>` +
          `<span class="muted">${b.code_name} · ${b.num_logical} logical · ` +
          `${b.memory_qubits}+${b.cat_qubits}q</span>` +
          `<span class="m-block-state state-badge ok">ok</span>` +
          `<span class="m-cat-buffer" title="verified cat states buffered"></span>` +
          `<span class="m-stalls muted" title="SE rounds missing cat states"></span></div>`,
      )
      .join("");
    el.querySelector(".m-factories").textContent = ev.magic_factories.length
      ? `magic: ${ev.magic_factories.join(", ")}`
      : "magic: none — T gates need a factory chip (arrives with scale)";
    if (ev.accounting === "lean" && getFooterNote()) {
      getFooterNote().textContent = ` · roadmap lean accounting on display — ${ev.accounting_note}`;
    }
  }

  function onChipStatus(ev) {
    const el = chipTile(ev.chip_id);
    setBadge(el.querySelector(".m-state"), ev.state);
    for (const b of ev.blocks) {
      const row = el.querySelector(`.m-block[data-block="${b.block_id}"]`);
      if (!row) continue;
      setBadge(row.querySelector(".m-block-state"), b.state);
      const frac = b.cat_buffer_capacity ? b.cat_buffer / b.cat_buffer_capacity : 0;
      row.querySelector(".m-cat-buffer").innerHTML =
        `<span class="buf"><span class="buf-fill ${frac <= 0.25 ? "low" : ""}"` +
        ` style="width:${(frac * 100).toFixed(0)}%"></span></span>` +
        ` cats ${b.cat_buffer}/${b.cat_buffer_capacity}`;
      row.querySelector(".m-stalls").textContent =
        b.stalled_rounds ? `${b.stalled_rounds} stalled` : "";
    }
    for (const f of ev.factories) {
      const row = el.querySelector(`.m-block[data-block="${f.source.replace("cat", "block")}"]`);
      if (f.kind === "cat" && row) {
        row.classList.toggle("factory-down", f.state === "down");
      }
    }
  }

  function onMachineStatus(ev) {
    const summary = getSummary();
    if (!summary) return;
    const measuredLer = ev.measured_shots
      ? ev.logical_error_per_logical_per_shot.toExponential(2)
      : "–";
    summary.innerHTML =
      `<table class="pvm">` +
      `<thead><tr><th></th><th>predicted (paper)</th><th>measured (live)</th></tr></thead>` +
      `<tbody>` +
      `<tr><td>logical qubits</td><td>${ev.logical_qubits}</td><td>${ev.logical_qubits}</td></tr>` +
      `<tr><td>physical qubits</td>` +
      `<td title="Table V prices + shared reservoir; transport/Bell overhead excluded">` +
      `${ev.physical_qubits_paper}</td>` +
      `<td title="nominal roadmap label">${ev.physical_qubits_nominal} nominal</td></tr>` +
      `<tr><td>T gates / day</td><td>${fmt(ev.predicted_t_per_day)}</td>` +
      `<td>${fmt(ev.measured_t_per_day)}</td></tr>` +
      `<tr><td>logical error / logical / shot</td><td class="muted">flat as N grows</td>` +
      `<td>${measuredLer} (${ev.measured_logical_errors}/${ev.measured_shots} shots)</td></tr>` +
      `</tbody></table>` +
      `<div class="m-tqueue ${ev.t_queue_depth ? "stalling" : ""}">` +
      `T queue: ${ev.t_queue_depth}` +
      (ev.t_stall_reason ? ` <span class="muted">— ${ev.t_stall_reason}</span>` : "") +
      `</div>` +
      `<div class="muted">machine time ${ev.machine_seconds.toFixed(1)} s · ` +
      `${ev.chips} chip${ev.chips === 1 ? "" : "s"}</div>`;
  }

  function setBadge(node, state) {
    node.textContent = state;
    node.className = `${node.className.split(" ")[0]} state-badge ${state}`;
  }

  function escapeAttr(s) {
    return (s || "").replace(/"/g, "&quot;");
  }

  function onEvent(ev) {
    if (ev.type === "chip_configured") onChipConfigured(ev);
    else if (ev.type === "chip_status") onChipStatus(ev);
    else if (ev.type === "machine_status") onMachineStatus(ev);
  }

  return { onEvent };
}
