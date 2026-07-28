// Dashboard bootstrap: WebSocket relay of bus events into a ring buffer of
// round frames, the event log, the replay scrubber, and the injection console.
// Renders events and posts commands — zero physics by charter.

import { createBlockView } from "/static/blockview.js";

const $ = (id) => document.getElementById(id);

let cfg = null;
let layout = null;
let view = null;
let blockId = "block0";
let selectedQubit = null;

// --- round frames (replay ring buffer) -------------------------------------
const frames = [];
let follow = true;
const lost = new Set();
const counters = { shots: 0, logicalErrors: 0, latencyMs: null };

function newFrame(shot, round) {
  const frame = {
    shot, round, injected: [], fired: [], identified: [], corrected: [], logical: false,
  };
  frames.push(frame);
  if (frames.length > cfg.ring_buffer_rounds) frames.shift();
  return frame;
}

function frameAt(shot, round) {
  for (let i = frames.length - 1; i >= 0; i--) {
    if (frames[i].shot === shot && frames[i].round === round) return frames[i];
  }
  return frames.length ? frames[frames.length - 1] : newFrame(shot, round);
}

function renderFrame(index) {
  if (!view || !frames.length) return;
  const i = Math.max(0, Math.min(index, frames.length - 1));
  view.render(frames[i], lost);
  $("scrub").max = frames.length - 1;
  $("scrub").value = i;
  $("frame-label").textContent = `shot ${frames[i].shot} · round ${frames[i].round}`;
  $("live-btn").classList.toggle("active", follow);
}

function renderLive() {
  if (follow) renderFrame(frames.length - 1);
}

// --- event handling ---------------------------------------------------------
async function onEvent(ev) {
  logEvent(ev);
  switch (ev.type) {
    case "block_configured":
      blockId = ev.source;
      $("block-sub").textContent =
        `${ev.code_name} · d=${ev.distance} · ${ev.num_data_qubits} data qubits · ` +
        `${ev.num_logical} logical · noise ${ev.noise_name}`;
      // display formatting of two announced numbers, like ms below — no physics
      $("c-ratio").textContent = (ev.num_data_qubits / ev.num_logical).toFixed(1);
      $("noise-slider").value = Math.log10(ev.noise_scale);
      $("noise-value").textContent = `${ev.noise_scale.toFixed(2)}×`;
      await loadLayout();
      break;
    case "round_started":
      counters.shots = Math.max(counters.shots, ev.shot + 1);
      newFrame(ev.shot, ev.round);
      renderLive();
      break;
    case "error_injected":
      frameAt(ev.shot, ev.round).injected.push({ qubits: ev.qubits, pauli: ev.pauli });
      renderLive();
      break;
    case "syndrome_fired":
      frameAt(ev.shot, ev.round).fired.push(...ev.check_ids);
      renderLive();
      break;
    case "decode_finished": {
      const f = frameAt(ev.shot, ev.round);
      f.identified = ev.identified_qubits;
      counters.latencyMs = ev.latency_s * 1000;
      renderLive();
      break;
    }
    case "correction_applied":
      frameAt(ev.shot, ev.round).corrected = ev.qubits;
      renderLive();
      break;
    case "logical_error":
      counters.logicalErrors += 1;
      if (frames.length) frames[frames.length - 1].logical = true;
      renderLive();
      break;
    case "ion_lost":
      lost.add(ev.qubit);
      renderLive();
      break;
    case "qubit_replaced":
      lost.delete(ev.qubit);
      renderLive();
      break;
  }
  updateCounters();
}

function updateCounters() {
  $("c-shots").textContent = counters.shots;
  $("c-logical").textContent = counters.logicalErrors;
  $("c-latency").textContent =
    counters.latencyMs === null ? "–" : `${counters.latencyMs.toFixed(2)} ms`;
}

// --- event log ---------------------------------------------------------------
function logEvent(ev) {
  const filter = $("log-filter").value;
  const body = $("log-body");
  const row = document.createElement("tr");
  row.dataset.type = ev.type;
  const detail = Object.entries(ev)
    .filter(([k]) => !["type", "source", "schema_version", "tick", "shot", "round"].includes(k))
    .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
    .join(" ");
  row.innerHTML =
    `<td>${ev.type}</td><td>${ev.source}</td>` +
    `<td>${ev.shot ?? ""}</td><td>${ev.round ?? ""}</td><td>${escapeHtml(detail)}</td>`;
  if (filter !== "all" && ev.type !== filter) row.classList.add("hidden");
  body.prepend(row);
  while (body.children.length > cfg.event_log_limit) body.removeChild(body.lastChild);
}

function escapeHtml(s) {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

$("log-filter").addEventListener("change", () => {
  const filter = $("log-filter").value;
  for (const row of $("log-body").children) {
    row.classList.toggle("hidden", filter !== "all" && row.dataset.type !== filter);
  }
});

// --- commands ----------------------------------------------------------------
async function sendCommand(command) {
  await fetch("/api/command", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source: "dashboard", target: blockId, ...command }),
  });
}

function wireConsole() {
  for (const pauli of ["X", "Y", "Z"]) {
    $(`inject-${pauli.toLowerCase()}`).addEventListener("click", () => {
      if (selectedQubit !== null) sendCommand({ type: "inject_pauli", pauli, qubits: [selectedQubit] });
    });
  }
  $("inject-loss").addEventListener("click", () => {
    if (selectedQubit !== null) sendCommand({ type: "inject_loss", qubits: [selectedQubit] });
  });

  const slider = $("noise-slider");
  slider.min = Math.log10(cfg.noise_scale.min);
  slider.max = Math.log10(cfg.noise_scale.max);
  slider.step = 0.01;
  slider.value = Math.log10(cfg.noise_scale.default);
  slider.addEventListener("input", () => {
    $("noise-value").textContent = `${Math.pow(10, slider.value).toFixed(2)}× (pending)`;
  });
  slider.addEventListener("change", () =>
    sendCommand({ type: "set_noise_scale", scale: Math.pow(10, slider.value) }));

  const pace = $("pace-select");
  for (const ms of cfg.pace_presets_ms) {
    const opt = document.createElement("option");
    opt.value = ms;
    opt.textContent = ms === 0 ? "flat out" : ms === 6 ? "6 ms (real SEC)" : `${ms} ms / round`;
    if (ms === cfg.default_pace_ms) opt.selected = true;
    pace.appendChild(opt);
  }
  pace.addEventListener("change", () =>
    sendCommand({ type: "set_pace", tick_seconds: Number(pace.value) / 1000 }));

  const decoderSelect = $("decoder-select");
  for (const name of cfg.decoders ?? []) {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    if (name === cfg.active_decoder) opt.selected = true;
    decoderSelect.appendChild(opt);
  }
  decoderSelect.closest("label").classList.toggle("hidden", !(cfg.decoders ?? []).length);
  decoderSelect.addEventListener("change", () =>
    // target "*": the decoder service id is not the block id
    sendCommand({ type: "set_decoder", name: decoderSelect.value, target: "*" }));

  let paused = false;
  $("pause-btn").addEventListener("click", () => {
    paused = !paused;
    $("pause-btn").textContent = paused ? "▶ resume" : "⏸ pause";
    $("pause-btn").classList.toggle("active", paused);
    sendCommand({ type: "set_paused", paused });
  });

  $("scenario-run").addEventListener("click", async () => {
    const name = $("scenario-select").value;
    if (name) await fetch(`/api/scenarios/${name}`, { method: "POST" });
  });
}

function wireReplay() {
  $("scrub").addEventListener("input", () => {
    follow = false;
    renderFrame(Number($("scrub").value));
  });
  $("step-back").addEventListener("click", () => {
    follow = false;
    renderFrame(Number($("scrub").value) - 1);
  });
  $("step-fwd").addEventListener("click", () => {
    follow = false;
    renderFrame(Number($("scrub").value) + 1);
  });
  $("live-btn").addEventListener("click", () => {
    follow = true;
    renderFrame(frames.length - 1);
  });
}

// --- bootstrap ----------------------------------------------------------------
async function loadLayout() {
  const res = await fetch("/api/layout");
  if (!res.ok) return;
  layout = await res.json();
  view = createBlockView($("block-svg"), layout, (q) => {
    selectedQubit = q;
    $("selected-label").textContent =
      q === null ? "click a qubit to arm the console" : `qubit ${q} selected`;
    for (const b of document.querySelectorAll(".inject-btn")) b.disabled = q === null;
  });
  renderLive();
}

async function loadScenarios() {
  const res = await fetch("/api/scenarios");
  const scenarios = await res.json();
  const select = $("scenario-select");
  for (const s of scenarios) {
    const opt = document.createElement("option");
    opt.value = s.name;
    opt.textContent = s.name;
    opt.title = s.description;
    select.appendChild(opt);
  }
}

function connect() {
  const ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen = () => $("conn").classList.add("up");
  ws.onclose = () => {
    $("conn").classList.remove("up");
    setTimeout(connect, 1000);
  };
  ws.onmessage = (msg) => onEvent(JSON.parse(msg.data));
}

async function main() {
  cfg = await (await fetch("/api/config")).json();
  document.title = cfg.title;
  document.documentElement.style.setProperty("--machine", cfg.machine_accent);
  document.documentElement.style.setProperty("--workload", cfg.workload_accent);
  for (const [panel, on] of Object.entries(cfg.panels)) {
    const node = $(`panel-${panel.replaceAll("_", "-")}`);
    if (node && !on) node.classList.add("hidden");
  }
  wireConsole();
  wireReplay();
  await loadScenarios();
  await loadLayout();
  connect();
}

main();
