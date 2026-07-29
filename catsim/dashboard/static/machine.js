// Machine view: module boxes of chip tiles (composition, accounting, role,
// fidelity mode, health), the photonic-interconnect link between modules, and
// the predicted-vs-measured panel, rendered from machine bus events. Pure
// rendering — every number arrives precomputed on the events; the paper's
// arithmetic runs in the machine layer, never here (charter).

// Required verbatim in two-module mode (M7 sourcing note, CLAUDE.md):
const TWO_MODULE_FOOTER =
  "single-machine architecture per the paper; inter-module link modeled from public roadmap, parameters assumed";

export function createMachinePanel(
  getContainer, getEmptyNote, getSummary, getFooterNote, onFocusChip, onCommand,
) {
  const chips = new Map(); // chip_id -> element
  const chipKeys = new Map(); // chip_id -> last announcement (chips re-announce; dedupe)
  const chipModule = new Map(); // chip_id -> module name
  const modules = new Map(); // module name -> box element
  let linkEl = null; // the interconnect element between module boxes
  let linkSevered = false;

  function fmt(n) {
    if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
    if (n >= 1e4) return `${(n / 1e3).toFixed(0)}k`;
    return Number.isInteger(n) ? String(n) : n.toPrecision(3);
  }

  function moduleBox(name) {
    let box = modules.get(name);
    if (box) return box;
    const empty = getEmptyNote();
    if (empty) empty.classList.add("hidden");
    box = document.createElement("div");
    box.className = "module-box";
    box.dataset.module = name;
    box.innerHTML =
      `<div class="module-head"><span class="module-name">module ${name}</span>` +
      `<span class="module-count muted"></span></div>` +
      `<div class="tiles module-tiles"></div>`;
    modules.set(name, box);
    // Keep boxes in module order with the interconnect link between them.
    const container = getContainer();
    const boxes = [...modules.keys()].sort();
    container.insertBefore(box, boxes.indexOf(name) === 0 ? container.firstChild : null);
    if (modules.size === 2) container.insertBefore(interconnectEl(), container.lastChild);
    return box;
  }

  function interconnectEl() {
    if (linkEl) return linkEl;
    linkEl = document.createElement("div");
    linkEl.className = "interconnect";
    linkEl.innerHTML =
      `<div class="ic-head"><span class="ic-name">photonic interconnect</span>` +
      `<span class="ic-state state-badge ok">linked</span>` +
      `<button class="ic-sever">sever link</button></div>` +
      `<div class="ic-bank muted"></div>` +
      `<div class="ic-traffic muted"></div>` +
      `<div class="ic-params muted"></div>`;
    linkEl.querySelector(".ic-sever").addEventListener("click", () => {
      if (onCommand) {
        onCommand({ type: "set_interconnect", severed: !linkSevered, target: "scheduler" });
      }
    });
    return linkEl;
  }

  function updateModuleCounts() {
    for (const [name, box] of modules) {
      const n = box.querySelectorAll(".chip-tile").length;
      box.querySelector(".module-count").textContent = `${n} chip${n === 1 ? "" : "s"}`;
    }
  }

  function chipTile(chipId, moduleName) {
    let el = chips.get(chipId);
    const name = moduleName || chipModule.get(chipId) || "A";
    if (el) {
      if (chipModule.get(chipId) !== name) {
        moduleBox(name).querySelector(".module-tiles").appendChild(el);
        chipModule.set(chipId, name);
        updateModuleCounts();
      }
      return el;
    }
    el = document.createElement("div");
    el.className = "tile chip-tile joining";
    el.innerHTML =
      `<div class="tile-head"><span class="tile-name"></span>` +
      `<span class="m-module" title="module membership (M7)"></span>` +
      `<span class="m-role muted"></span>` +
      `<span class="m-mode mode-badge behavioral">behavioral</span>` +
      `<span class="m-state state-badge ok">ok</span></div>` +
      `<div class="m-qubits muted"></div>` +
      `<div class="m-blocks"></div>` +
      `<div class="m-factories muted"></div>` +
      `<div class="m-tstats muted"></div>`;
    el.querySelector(".tile-name").textContent = chipId;
    el.querySelector(".m-module").textContent = name;
    el.title = "click to focus: this chip gets the live stim + decoder stack";
    el.addEventListener("click", () => onFocusChip && onFocusChip(chipId));
    moduleBox(name).querySelector(".module-tiles").appendChild(el);
    chips.set(chipId, el);
    chipModule.set(chipId, name);
    updateModuleCounts();
    setTimeout(() => el.classList.remove("joining"), 1200); // arrival flash
    return el;
  }

  function onChipConfigured(ev) {
    const key = JSON.stringify({ ...ev, tick: 0 });
    if (chipKeys.get(ev.chip_id) === key) return;
    chipKeys.set(ev.chip_id, key);
    const el = chipTile(ev.chip_id, ev.module);
    el.querySelector(".tile-name").textContent = `${ev.chip_id} · ${ev.machine_name}`;
    el.querySelector(".m-module").textContent = ev.module;
    const role = el.querySelector(".m-role");
    role.textContent = ev.role === "factory" ? "⚙ factory" : "▦ memory";
    role.title =
      ev.role === "factory"
        ? "magic-state factory chip (Table I role mix, balanced per module)"
        : "qLDPC memory chip";
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
      : ev.blocks.length
        ? "magic: none — T gates need a factory chip (arrives with scale)"
        : "";
    if (ev.accounting === "lean" && getFooterNote()) {
      getFooterNote().textContent = ` · roadmap lean accounting on display — ${ev.accounting_note}`;
    }
  }

  function onChipStatus(ev) {
    const el = chipTile(ev.chip_id, ev.module);
    setBadge(el.querySelector(".m-state"), ev.state);
    const mode = el.querySelector(".m-mode");
    mode.textContent = ev.mode;
    mode.className = `m-mode mode-badge ${ev.mode}`;
    mode.title =
      ev.mode === "live"
        ? "live: full stim + decoder stack (the drill-down focus)"
        : "behavioral: SimPy model calibrated from measured baselines";
    el.classList.toggle("focus", ev.mode === "live");
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
    el.querySelector(".m-tstats").textContent =
      ev.role === "factory"
        ? `T queue ${ev.t_queue_depth} · ${ev.t_done} served · ${ev.machine_seconds.toFixed(0)} machine-s`
        : "";
  }

  function onChipGone(ev, label) {
    const el = chips.get(ev.chip_id);
    if (!el) return;
    const drop = () => {
      el.remove();
      chips.delete(ev.chip_id);
      chipKeys.delete(ev.chip_id);
      chipModule.delete(ev.chip_id);
      updateModuleCounts();
    };
    if (label === "left") {
      drop();
      return;
    }
    el.classList.add("lost");
    setBadge(el.querySelector(".m-state"), "down");
    el.querySelector(".m-state").textContent = "lost";
    // A lost chip that never comes back fades out of the view after a beat.
    setTimeout(drop, 8000);
  }

  function onInterconnect(ev) {
    // Two-module mode: the sourcing footer is mandatory (verbatim, charter).
    const note = document.getElementById("footer-mod-note");
    if (note && ev.modules >= 2) note.textContent = ` · ${TWO_MODULE_FOOTER}`;
    const el = interconnectEl();
    const container = getContainer();
    if (!el.parentElement && container.children.length) {
      container.appendChild(el); // "add module" pressed before any B chip joined
    }
    linkSevered = ev.severed;
    el.classList.toggle("severed", ev.severed);
    const state = el.querySelector(".ic-state");
    state.textContent = ev.severed ? "SEVERED" : "linked";
    state.className = `ic-state state-badge ${ev.severed ? "down" : "ok"}`;
    el.querySelector(".ic-sever").textContent = ev.severed ? "restore link" : "sever link";
    const frac = ev.bank_capacity ? ev.bank / ev.bank_capacity : 0;
    el.querySelector(".ic-bank").innerHTML =
      `Bell-pair bank <span class="buf"><span class="buf-fill ${frac <= 0.25 ? "low" : ""}"` +
      ` style="width:${(frac * 100).toFixed(0)}%"></span></span> ` +
      `${ev.bank}/${ev.bank_capacity} pairs`;
    el.querySelector(".ic-traffic").innerHTML =
      `cross-module T: ${fmt(ev.cross_t_served)} served · ` +
      `<span class="${ev.cross_queue_depth ? "diverges" : ""}">queue ${ev.cross_queue_depth}</span>` +
      ` · demand ${ev.cross_demand_per_second.toFixed(1)}/s`;
    el.querySelector(".ic-params").textContent =
      `~${ev.pair_rate_hz.toFixed(0)} pairs/s heralded · ${(ev.latency_s * 1000).toFixed(0)} ms — ` +
      `ASSUMED, not from the paper`;
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
      `${ev.chips} chip${ev.chips === 1 ? "" : "s"}` +
      (ev.modules > 1 ? ` in ${ev.modules} modules` : "") +
      (ev.lost_chips ? ` · <span class="diverges">${ev.lost_chips} lost</span>` : "") +
      `</div>`;
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
    else if (ev.type === "interconnect_status") onInterconnect(ev);
    else if (ev.type === "chip_lost") onChipGone(ev, "lost");
    else if (ev.type === "chip_left") onChipGone(ev, "left");
  }

  return { onEvent };
}
