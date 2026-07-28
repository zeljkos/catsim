// Block view: SVG grid of data qubits and check ancillas, rendered per frame.
// Pure rendering of served layout + bus events — no physics lives here.

export function createBlockView(svg, layout, onSelect) {
  const pad = 1.2;
  const xs = [...layout.data_qubits, ...layout.checks].map((q) => q.x);
  const ys = [...layout.data_qubits, ...layout.checks].map((q) => q.y);
  const minX = Math.min(...xs) - pad, maxX = Math.max(...xs) + pad;
  const minY = Math.min(...ys) - pad, maxY = Math.max(...ys) + pad;
  svg.setAttribute("viewBox", `${minX} ${minY} ${maxX - minX} ${maxY - minY}`);
  svg.innerHTML = "";

  const border = el("rect", {
    x: minX + 0.25, y: minY + 0.25, width: maxX - minX - 0.5, height: maxY - minY - 0.5,
    rx: 0.4, class: "block-border",
  });
  svg.appendChild(border);

  const nodes = new Map(); // qubit index -> {group, shape, kind}
  let selected = null;

  for (const c of layout.checks) {
    const g = el("g", { class: `check basis-${c.basis.toLowerCase()}` });
    const s = 0.30;
    const shape = el("rect", {
      x: c.x - s, y: c.y - s, width: 2 * s, height: 2 * s,
      transform: `rotate(45 ${c.x} ${c.y})`,
    });
    g.appendChild(shape);
    svg.appendChild(g);
    nodes.set(c.index, { group: g, kind: "check" });
    attach(g, c.index);
  }
  for (const d of layout.data_qubits) {
    const g = el("g", { class: "data" });
    g.appendChild(el("circle", { cx: d.x, cy: d.y, r: 0.34 }));
    const label = el("text", { x: d.x, y: d.y, class: "qlabel" });
    label.textContent = d.index;
    g.appendChild(label);
    svg.appendChild(g);
    nodes.set(d.index, { group: g, kind: "data" });
    attach(g, d.index);
  }

  function attach(group, index) {
    group.addEventListener("click", () => {
      selected = selected === index ? null : index;
      for (const [i, n] of nodes) n.group.classList.toggle("selected", i === selected);
      onSelect(selected);
    });
  }

  function el(tag, attrs) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    return node;
  }

  const STATES = [
    "err-x", "err-y", "err-z", "fired", "identified", "corrected",
    "lost", "replacing", "replaced",
  ];

  // Render one frame: error flashes red, fired checks amber, decoder blame
  // blue, corrections green; lost ions hollow purple, dispatched replacements
  // pulse, and a rejoined qubit flashes green (the ion-loss recovery beat).
  function render(frame, lost, replacing) {
    for (const n of nodes.values()) n.group.classList.remove(...STATES);
    if (!frame) return;
    for (const inj of frame.injected) {
      for (const q of inj.qubits) mark(q, `err-${inj.pauli.toLowerCase()}`);
    }
    for (const det of frame.fired) {
      const check = layout.detectors[String(det)];
      if (check !== undefined) mark(check, "fired");
    }
    for (const q of frame.identified) mark(q, "identified");
    for (const q of frame.corrected) mark(q, "corrected");
    for (const q of lost) mark(q, "lost");
    for (const q of replacing ?? []) mark(q, "replacing");
    for (const q of frame.replaced ?? []) mark(q, "replaced");
    border.classList.toggle("logical", Boolean(frame.logical));
  }

  function mark(index, cls) {
    const n = nodes.get(index);
    if (n) n.group.classList.add(cls);
  }

  return { render };
}
