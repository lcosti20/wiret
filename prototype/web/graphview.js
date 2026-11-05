// The graph canvas of the web page: draws one graph described by wiret.webapi.check (see
// wiret/viewmodel.py), the way wiret/graphview.py draws it on the desktop, and turns pointer
// input into edits as the desktop canvas does: drag a node or a box title to move it, drag
// from a pin to a pin (or onto a node) to wire them, click a wire and press Delete to remove
// it, double-click an input to type its value, and add nodes from the palette (Tab, a double
// click on empty canvas, or a wire dropped on empty canvas). A right click, or a long press on a
// touch screen, opens the context menu for what is under it. The page makes the edits
// (on.move, on.connect, ...); this file only reports them. Also: pan, zoom, select, open a
// call, breakpoints.
//
// Everything is in graph units inside one "world" element that a CSS transform pans and zooms.
// Boxes, nodes, notes and value tags are HTML, so the browser measures text; wires and pins
// are SVG, drawn once the node widths are known.

const HEADER = 24, ROW = 20, PIN_R = 5;
const C = {
  nodeBg: "#2b2e35", nodeEdge: "#111214", text: "#e8e8e8", dim: "#8a8f98", select: "#f5b041",
  error: "#e74c3c", warn: "#f39c12", ran: "#2ecc71", current: "#00e5ff", brk: "#ff3b30",
  note: "#f7dc6f", exec: "#f0f0f0",
};
const SVG = "http://www.w3.org/2000/svg";

const h = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
};
const s = (tag, attrs) => {
  const e = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  return e;
};

export class GraphView {
  /** host: an empty element to fill. on: {select(nodeId|null), open(graphName),
   *  toggleBreakpoint(nodeId), canEdit() -> true or the reason not, message(text),
   *  move(id, x, y), connect(a, b), connectToNode(a, nodeId), disconnect(node, dir, pin),
   *  deleteNode(id), editPin(node, pin, [screenX, screenY]),
   *  palette([worldX, worldY], [screenX, screenY], pin or null),
   *  menu(target, [screenX, screenY], [worldX, worldY])}. A pin is [node, "in"/"out", pin];
   *  screen points are relative to the canvas. A menu target is as webapi.menu takes it. */
  constructor(host, on) {
    this.host = host;
    this.on = on;
    this.graph = null;
    this.state = {};
    this.scale = 1; this.ox = 80; this.oy = 80;
    this.autoFit = true;
    this.geoms = new Map();
    host.classList.add("gv");
    this.world = h("div", "gv-world");
    this.notesBox = h("div", "gv-notes");
    this.notesOpen = null;      // null: open unless the view is narrow
    this.selWire = null;        // "d|node|pin" (data wire into that input) or "e|node|pin"
    this.temp = s("svg", { class: "gv-svg" });   // the wire being dragged out of a pin
    this.pointer = null;        // the last pointer position over the canvas (for Tab)
    host.tabIndex = 0;
    host.append(this.world, this.notesBox);
    this.#bindInput();
    new ResizeObserver(() => { if (this.autoFit) this.fit(true); else this.#applyView(); }).observe(host);
  }

  /** Show `graph`; fit it to the view unless `keepView` (e.g. when the same graph is edited). */
  setGraph(graph, keepView = false) {
    if (!keepView) this.selWire = null;
    this.graph = graph;
    this.render();
    if (!keepView) this.fit(true);
  }

  /** state: {selected, current, values: {"node.pin": text}, counts: {node: n}, fault,
   *  breakpoints: Set of node ids}. */
  setState(state) {
    this.state = state;
    this.render();
  }

  // ---------- view ----------
  fit(keepAuto = false) {
    this.autoFit = keepAuto;
    const w = Math.max(this.host.clientWidth, 200), hh = Math.max(this.host.clientHeight, 200);
    const xs = [], ys = [];
    for (const g of this.geoms.values()) { xs.push(g.x, g.x + g.w); ys.push(g.y, g.y + g.h); }
    for (const b of this.graph?.boxes ?? []) { xs.push(b.x, b.x + b.w); ys.push(b.y, b.y + b.h); }
    if (!xs.length) return this.#applyView();
    const top = this.notesBox.childElementCount ? this.notesBox.offsetHeight + 10 : 0;
    const minx = Math.min(...xs), maxx = Math.max(...xs), miny = Math.min(...ys), maxy = Math.max(...ys);
    const bw = maxx - minx + 260, bh = maxy - miny + 200;
    this.scale = Math.max(0.3, Math.min(1.3, w / bw, (hh - top) / bh));
    this.ox = (w - (maxx + minx) * this.scale) / 2;
    this.oy = top + (hh - top - (maxy + miny) * this.scale) / 2 + 20;
    this.#applyView();
  }

  zoomAt(sx, sy, factor) {
    this.autoFit = false;
    const scale = Math.min(2.5, Math.max(0.25, this.scale * factor));
    const wx = (sx - this.ox) / this.scale, wy = (sy - this.oy) / this.scale;
    this.scale = scale;
    this.ox = sx - wx * scale;
    this.oy = sy - wy * scale;
    this.#applyView();
  }

  zoom(factor) { this.zoomAt(this.host.clientWidth / 2, this.host.clientHeight / 2, factor); }

  /** Pan so the node is in view, if it is not already. */
  reveal(nodeId) {
    const g = this.geoms.get(nodeId);
    if (!g) return;
    const m = 40, w = this.host.clientWidth, hh = this.host.clientHeight;
    const x0 = g.x * this.scale + this.ox, y0 = g.y * this.scale + this.oy;
    const x1 = (g.x + g.w) * this.scale + this.ox, y1 = (g.y + g.h) * this.scale + this.oy;
    if (x0 >= m && y0 >= m && x1 <= w - m && y1 <= hh - m) return;
    this.autoFit = false;
    this.ox = w / 2 - (g.x + g.w / 2) * this.scale;
    this.oy = hh / 2 - (g.y + g.h / 2) * this.scale;
    this.#applyView();
  }

  #applyView() {
    this.world.style.transform = `translate(${this.ox}px, ${this.oy}px) scale(${this.scale})`;
    const step = 40 * this.scale;
    this.host.style.backgroundSize = step < 12 ? "0 0" : `${step}px ${step}px`;
    this.host.style.backgroundPosition = `${this.ox}px ${this.oy}px`;
  }

  // ---------- drawing ----------
  render() {
    const g = this.graph, st = this.state;
    this.world.replaceChildren();
    this.notesBox.replaceChildren();
    this.geoms = new Map();
    if (!g) return;
    const boxes = h("div"), wires = s("svg", { class: "gv-svg" }), nodes = h("div");
    const pins = s("svg", { class: "gv-svg" }), over = h("div");
    this.world.append(boxes, wires, nodes, pins, over, this.temp);

    for (const b of g.boxes) {
      const d = h("div", "gv-box");
      d.dataset.boxbody = b.id;
      Object.assign(d.style, { left: `${b.x}px`, top: `${b.y}px`, width: `${b.w}px`, height: `${b.h}px`,
                               borderColor: b.color });
      const t = h("div", "gv-box-title", b.title);
      t.style.background = b.color;
      t.dataset.box = b.id;
      d.append(t);
      boxes.append(d);
    }

    // nodes: build, then measure their widths
    const els = [];
    for (const n of g.nodes) {
      const d = h("div", "gv-node");
      d.dataset.id = n.id;
      d.style.left = `${n.x}px`; d.style.top = `${n.y}px`;
      const head = h("div", "gv-head", n.title);
      head.style.background = n.header;
      const body = h("div", "gv-body");
      const ins = h("div", "gv-col"), outs = h("div", "gv-col gv-outs");
      for (const p of n.ins) {
        const r = h("div", "gv-pin", p.label);
        if (!p.bound && !p.exec) r.classList.add("gv-unbound");
        if (!p.exec) { r.dataset.row = p.name; r.title = `${p.name}: ${p.type}\nDouble-click to type a value`; }
        ins.append(r);
      }
      for (const p of n.outs) outs.append(h("div", "gv-pin", p.label));
      body.append(ins, outs);
      d.append(head, body);
      const rows = Math.max(n.ins.length, n.outs.length, n.pure ? 0 : 1);
      d.style.height = `${HEADER + ROW * rows + 6}px`;
      d.title = this.#nodeTip(n);
      nodes.append(d);
      els.push([n, d]);
    }
    for (const [n, d] of els) {
      const w = Math.max(d.offsetWidth, 96);
      d.style.width = `${w}px`;
      const geom = { x: n.x, y: n.y, w, h: d.offsetHeight, pins: new Map() };
      n.ins.forEach((p, i) => geom.pins.set(`in|${p.name}`, [n.x, n.y + HEADER + ROW * (i + 0.5) + 3]));
      n.outs.forEach((p, i) => geom.pins.set(`out|${p.name}`, [n.x + w, n.y + HEADER + ROW * (i + 0.5) + 3]));
      this.geoms.set(n.id, geom);
    }
    const pinAt = (id, dir, name) => this.geoms.get(id)?.pins.get(`${dir}|${name}`);

    // wires
    for (const wv of g.wires) {
      const src = pinAt(wv.from[0], "out", wv.from[1]);
      const dst = pinAt(wv.to[0], "in", wv.to[1]);
      if (src && dst) {
        const key = wv.exec ? `e|${wv.from[0]}|${wv.from[1]}` : `d|${wv.to[0]}|${wv.to[1]}`;
        const sel = this.selWire === key;
        wires.append(this.#curve(src, dst, sel ? C.select : wv.exec ? C.exec : wv.color, wv.exec ? 3.5 : 2.5));
        const hit = this.#curve(src, dst, "transparent", 12);
        hit.classList.add("gv-wirehit");
        hit.dataset.wire = key;
        const tip = s("title", {});
        tip.textContent = `${wv.from.join(".")} → ${wv.to.join(".")}: click, then Delete to remove`;
        hit.append(tip);
        wires.append(hit);
      } else if (dst && !wv.exec) {        // dangling: keep it visible as an error (section 7.5)
        wires.append(this.#curve([dst[0] - 60, dst[1] - 20], dst, C.error, 2.5, true));
        over.append(this.#text(dst[0] - 62, dst[1] - 20, `? ${wv.from[0]}.${wv.from[1]}`, "gv-dangle", "e"));
      } else if (src && wv.exec) {
        wires.append(this.#curve(src, [src[0] + 60, src[1] - 20], C.error, 2.5, true));
        over.append(this.#text(src[0] + 62, src[1] - 20, `? ${wv.to[0]}`, "gv-dangle", "w"));
      }
    }

    // pins, outlines, marks
    const bps = st.breakpoints ?? new Set();
    for (const [n, d] of els) {
      const geom = this.geoms.get(n.id);
      for (const [dir, list] of [["in", n.ins], ["out", n.outs]]) {
        for (const p of list) {
          const [px, py] = geom.pins.get(`${dir}|${p.name}`);
          const fill = p.filled ? p.color : C.nodeBg;
          const shape = p.exec
            ? s("polygon", { points: `${px - PIN_R},${py - PIN_R * 1.2} ${px + PIN_R},${py} ${px - PIN_R},${py + PIN_R * 1.2}` })
            : s("circle", { cx: px, cy: py, r: PIN_R });
          shape.setAttribute("fill", fill);
          shape.setAttribute("stroke", p.color);
          shape.setAttribute("stroke-width", 1.5);
          const hit = s("circle", { cx: px, cy: py, r: PIN_R * 2.4, fill: "transparent", class: "gv-pinhit" });
          Object.assign(hit.dataset, { node: n.id, dir, pin: p.name });
          const tip = s("title", {});
          const v = dir === "out" ? st.values?.[`${n.id}.${p.name}`] : undefined;
          tip.textContent = `${n.id}.${p.name}: ${p.type}${v !== undefined ? ` = ${v}` : ""}` +
                            "\nDrag to wire it" + (dir === "in" && !p.exec ? "; double-click to type a value" : "");
          hit.append(tip);
          pins.append(shape, hit);
        }
      }
      let outline = C.nodeEdge, width = 1;
      if (n.diag === "error") [outline, width] = [C.error, 3];
      else if (n.diag === "warning") [outline, width] = [C.warn, 2];
      const count = st.counts?.[n.id];
      if (count) [outline, width] = [C.ran, 3];
      if (st.fault === n.id) [outline, width] = [C.error, 4];
      if (st.selected === n.id) [outline, width] = [C.select, 3];
      const current = st.current === n.id;
      if (current) [outline, width] = [C.current, 4];
      d.style.outline = `${width}px solid ${outline}`;
      d.style.outlineOffset = `${-width / 2}px`;

      const id = this.#text(n.x + 2, n.y - 3, n.id + (n.disabled ? "  (disabled)" : "") + (n.pure ? "  pure" : ""), "gv-id", "sw");
      over.append(id);
      if (count) over.append(this.#text(n.x + geom.w, n.y - 3, `×${count}`, "gv-count", "se"));
      if (current) {
        const pad = 6, r = h("div", "gv-current");
        Object.assign(r.style, { left: `${n.x - pad}px`, top: `${n.y - pad}px`,
                                 width: `${geom.w + 2 * pad}px`, height: `${geom.h + 2 * pad}px` });
        over.append(r, this.#text(n.x - pad, n.y + geom.h + pad + 2, "▶ runs next", "gv-next", "nw"));
      }
      const dot = h("div", "gv-bp" + (bps.has(n.id) ? " on" : ""));
      dot.style.left = `${n.x}px`; dot.style.top = `${n.y}px`;
      dot.dataset.bp = n.id;
      dot.title = bps.has(n.id) ? "Remove the breakpoint" : "Set a breakpoint: the debugger stops before this node runs";
      over.append(dot);
      if (n.diag) {
        const b = h("div", `gv-badge ${n.diag}`, "!");
        b.style.left = `${n.x + geom.w - 1}px`; b.style.top = `${n.y + 1}px`;
        over.append(b);
      }
    }

    // values the wires carried at the debugger's pause: one tag near each consumer, plus one
    // near the source pin
    if (st.values) {
      const drawn = new Set();
      for (const wv of g.wires) {
        if (wv.exec) continue;
        const key = `${wv.from[0]}.${wv.from[1]}`;
        const v = st.values[key];
        const src = pinAt(wv.from[0], "out", wv.from[1]), dst = pinAt(wv.to[0], "in", wv.to[1]);
        if (v === undefined || !src || !dst) continue;
        const text = v.length > 24 ? v.slice(0, 22) + "…" : v;
        over.append(this.#tag(dst[0] - 30, dst[1], text, `${key} = ${v}`));
        if (!drawn.has(key)) {
          drawn.add(key);
          over.append(this.#tag(src[0] + 30, src[1], text, `${key} = ${v}`));
        }
      }
    }

    // notes: under their node, or for the whole graph at the top left of the view (these
    // can be folded away, and start folded on a narrow screen)
    const byNode = new Map(), graphNotes = [];
    for (const nt of g.notes) {
      if (nt.on && this.geoms.has(nt.on)) {
        if (!byNode.has(nt.on)) byNode.set(nt.on, []);
        byNode.get(nt.on).push(nt);
      } else {
        const p = h("p", nt.detached ? "detached" : "",
                    (nt.detached ? `✎ (detached from ${nt.detached}) ` : "✎ ") + nt.text);
        p.dataset.note = nt.key;
        p.title = "Right-click to edit or delete this note";
        graphNotes.push(p);
      }
    }
    if (graphNotes.length) {
      const open = this.notesOpen ?? this.host.clientWidth >= 600;
      const toggle = h("button", "gv-notes-toggle", open ? "Hide notes" : `✎ Notes (${graphNotes.length})`);
      toggle.onclick = (e) => {
        e.stopPropagation();
        this.notesOpen = !open;
        this.render();
        if (this.autoFit) this.fit(true);
      };
      toggle.onpointerdown = (e) => e.stopPropagation();
      this.notesBox.append(...(open ? graphNotes : []), toggle);
    }
    for (const [id, list] of byNode) {
      const geom = this.geoms.get(id);
      const d = h("div", "gv-note");
      for (const nt of list) {
        const one = h("div", "", "✎ " + nt.text);
        one.dataset.note = nt.key;
        one.title = "Right-click to edit or delete this note";
        d.append(one);
      }
      Object.assign(d.style, { left: `${geom.x}px`, top: `${geom.y + geom.h + 6}px`,
                               width: `${Math.max(140, geom.w * 1.4)}px` });
      over.append(d);
    }
    this.#applyView();
  }

  #nodeTip(n) {
    const lines = [`${n.id}: ${n.title}`];
    if (n.description) lines.push(n.description);
    if (n.opens) lines.push(`Double-click to open ${n.opens}.`);
    return lines.join("\n");
  }

  #curve([x0, y0], [x1, y1], color, width, dashed = false) {
    const dx = Math.max(40, Math.abs(x1 - x0) / 2);
    const p = s("path", { d: `M${x0},${y0} C${x0 + dx},${y0} ${x1 - dx},${y1} ${x1},${y1}`,
                          fill: "none", stroke: color, "stroke-width": width });
    if (dashed) p.setAttribute("stroke-dasharray", "4 3");
    return p;
  }

  /** Text anchored like a Tk canvas item: anchor is a compass point (n, se, w, ...). */
  #text(x, y, text, cls, anchor) {
    const d = h("div", `gv-text ${cls}`, text);
    const tx = anchor.includes("e") ? "-100%" : anchor.includes("w") ? "0" : "-50%";
    const ty = anchor.includes("s") ? "-100%" : anchor.includes("n") ? "0" : "-50%";
    Object.assign(d.style, { left: `${x}px`, top: `${y}px`, transform: `translate(${tx}, ${ty})` });
    return d;
  }

  #tag(x, y, text, title) {
    const d = this.#text(x, y, text, "gv-tag", "c");
    d.title = title;
    return d;
  }

  // ---------- input ----------
  /** The node geometry the page passes with a connect (to place an inserted Convert node). */
  geomsFor(ids) {
    const out = {};
    for (const id of ids) {
      const g = this.geoms.get(id);
      if (g) out[id] = [g.x, g.y, g.w];
    }
    return out;
  }

  /** A small text box over the canvas at point [x, y] (relative to the canvas). Resolves to
   *  the text on Enter, or null on Escape or when it loses focus. */
  ask([x, y], { label, value = "", placeholder = "" }) {
    this.askBox?.remove();
    const box = h("div", "gv-ask");
    const input = h("input");
    input.value = value;
    input.placeholder = placeholder;
    input.setAttribute("aria-label", label);
    box.append(h("div", "gv-ask-label", label), input);
    box.style.left = `${Math.max(4, Math.min(x, this.host.clientWidth - 250))}px`;
    box.style.top = `${Math.max(4, Math.min(y + 12, this.host.clientHeight - 70))}px`;
    box.addEventListener("pointerdown", (e) => e.stopPropagation());
    this.host.append(box);
    this.askBox = box;
    input.focus();
    input.select();
    return new Promise((resolve) => {
      let done = false;
      const finish = (v) => {
        if (done) return;
        done = true;
        box.remove();
        if (this.askBox === box) this.askBox = null;
        this.host.focus({ preventScroll: true });
        resolve(v);
      };
      input.addEventListener("keydown", (e) => {
        e.stopPropagation();
        if (e.key === "Enter") finish(input.value);
        else if (e.key === "Escape") finish(null);
      });
      input.addEventListener("blur", () => finish(null));
    });
  }

  /** The point at the middle of the view: [world, screen], for adding a node there. */
  middle() {
    const sx = this.host.clientWidth / 2, sy = this.host.clientHeight / 3;
    return [[(sx - this.ox) / this.scale, (sy - this.oy) / this.scale], [sx, sy]];
  }

  /** A context menu at [x, y] from webapi.menu's entries. Resolves to the entry chosen, or
   *  null when closed (Escape, or a click elsewhere). */
  menu([x, y], entries) {
    this.askBox?.remove();
    const box = h("div", "gv-menu");
    box.setAttribute("role", "menu");
    const items = [];
    let resolveIt, done = false;
    const finish = (v) => {
      if (done) return;
      done = true;
      box.remove();
      if (this.askBox === box) this.askBox = null;
      this.host.focus({ preventScroll: true });
      resolveIt(v);
    };
    for (const e of entries) {
      if (e.sep) { box.append(h("div", "gv-menu-sep")); continue; }
      if (e.header) { box.append(h("div", "gv-menu-head", e.label)); continue; }
      const b = h("button", e.indent ? "gv-menu-item indent" : "gv-menu-item", e.label);
      b.setAttribute("role", "menuitem");
      b.tabIndex = -1;
      b.addEventListener("click", () => finish(e));
      b.addEventListener("pointerenter", () => b.focus());
      items.push(b);
      box.append(b);
    }
    box.addEventListener("pointerdown", (e) => e.stopPropagation());
    box.addEventListener("contextmenu", (e) => e.preventDefault());
    box.addEventListener("keydown", (e) => {
      e.stopPropagation();
      const i = items.indexOf(document.activeElement);
      if (e.key === "ArrowDown") { e.preventDefault(); items[(i + 1) % items.length]?.focus(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); items[(i - 1 + items.length) % items.length]?.focus(); }
      else if (e.key === "Escape" || e.key === "Tab") { e.preventDefault(); finish(null); }
    });
    box.addEventListener("focusout", (e) => { if (!box.contains(e.relatedTarget)) setTimeout(() => {
      if (!box.contains(document.activeElement)) finish(null);
    }, 0); });
    this.host.append(box);
    this.askBox = box;
    box.style.left = `${Math.max(4, Math.min(x, this.host.clientWidth - box.offsetWidth - 4))}px`;
    box.style.top = `${Math.max(4, Math.min(y, this.host.clientHeight - box.offsetHeight - 4))}px`;
    (items[0] ?? box).focus();
    return new Promise((resolve) => { resolveIt = resolve; });
  }

  /** What a menu would be for: the thing under `el`, as webapi.menu takes it. */
  #menuTarget(el) {
    const pin = el?.closest?.(".gv-pinhit");
    if (pin) return { kind: "pin", node: pin.dataset.node, dir: pin.dataset.dir, pin: pin.dataset.pin };
    const note = el?.closest?.("[data-note]");
    if (note) return { kind: "note", note: note.dataset.note };
    const node = el?.closest?.(".gv-node");
    if (node) return { kind: "node", node: node.dataset.id };
    const wire = el?.closest?.(".gv-wirehit");
    if (wire) return { kind: "wire", wire: wire.dataset.wire };
    const box = el?.closest?.("[data-box], [data-boxbody]");
    if (box) return { kind: "box", box: box.dataset.box ?? box.dataset.boxbody };
    return { kind: "canvas" };
  }

  #openMenu(el, at) {
    const target = this.#menuTarget(el);
    const world = [(at[0] - this.ox) / this.scale, (at[1] - this.oy) / this.scale];
    if (target.kind === "canvas") Object.assign(target, { x: Math.round(world[0]), y: Math.round(world[1]) });
    if (target.kind === "node") this.on.select(target.node);
    if (target.kind === "wire") { this.selWire = target.wire; this.on.select(null); }
    this.on.menu(target, at, world);
  }

  /** The node palette over the canvas at [x, y]: a search box and the best matches.
   *  search(query) -> {items: [{label, category, description, ...}], total}. Resolves to the
   *  item picked, or null when closed (Escape, or a click elsewhere). */
  pick([x, y], { title, search }) {
    this.askBox?.remove();
    const box = h("div", "gv-palette");
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-label", title);
    const input = h("input");
    input.placeholder = "Type to search";
    input.setAttribute("aria-label", "Search nodes");
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-expanded", "true");
    const list = h("ul");
    list.id = "gv-palette-list";
    list.setAttribute("role", "listbox");
    input.setAttribute("aria-controls", list.id);
    const desc = h("div", "gv-palette-desc");
    box.append(h("div", "gv-ask-label", title), input, list, desc);
    const w = Math.min(360, this.host.clientWidth - 8);
    box.style.width = `${w}px`;
    box.style.left = `${Math.max(4, Math.min(x, this.host.clientWidth - w - 4))}px`;
    box.addEventListener("pointerdown", (e) => e.stopPropagation());
    box.addEventListener("wheel", (e) => e.stopPropagation());
    this.host.append(box);
    this.askBox = box;
    let shown = [], sel = 0;
    const place = () => {             // keep it inside the canvas as its contents change
      box.style.top = `${Math.max(4, Math.min(y, this.host.clientHeight - box.offsetHeight - 4))}px`;
    };
    const show = (i) => {
      sel = Math.max(0, Math.min(shown.length - 1, i));
      [...list.children].forEach((li, k) => {
        li.setAttribute("aria-selected", k === sel);
        if (k === sel) li.scrollIntoView({ block: "nearest" });
      });
      const it = shown[sel];
      desc.textContent = it ? (it.description ? `${it.category}: ${it.description}` : it.category)
                            : input.value ? "No matching nodes." : "";
      if (it) input.setAttribute("aria-activedescendant", `gv-pal-${sel}`);
      place();
    };
    const refilter = () => {
      const r = search(input.value);
      shown = r.items;
      list.replaceChildren(...shown.map((it, k) => {
        const li = h("li", "", it.label);
        li.id = `gv-pal-${k}`;
        li.setAttribute("role", "option");
        li.append(h("span", "gv-palette-cat", it.category));
        li.addEventListener("pointerenter", () => show(k));
        li.addEventListener("click", () => finish(shown[k]));
        return li;
      }));
      show(0);
    };
    let done = false, resolveIt;
    const finish = (v) => {
      if (done) return;
      done = true;
      box.remove();
      if (this.askBox === box) this.askBox = null;
      this.host.focus({ preventScroll: true });
      resolveIt(v);
    };
    input.addEventListener("input", refilter);
    input.addEventListener("keydown", (e) => {
      e.stopPropagation();
      if (e.key === "ArrowDown") { e.preventDefault(); show(sel + 1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); show(sel - 1); }
      else if (e.key === "Enter") { e.preventDefault(); if (shown[sel]) finish(shown[sel]); }
      else if (e.key === "Escape") finish(null);
    });
    box.addEventListener("focusout", (e) => { if (!box.contains(e.relatedTarget)) setTimeout(() => {
      if (!box.contains(document.activeElement)) finish(null);
    }, 0); });
    list.tabIndex = -1;
    refilter();
    input.focus();
    return new Promise((resolve) => { resolveIt = resolve; });
  }

  #bindInput() {
    const host = this.host;
    const pointers = new Map();
    let drag = null, pinch = null;
    const local = (e) => { const r = host.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
    const world = ([x, y]) => [(x - this.ox) / this.scale, (y - this.oy) / this.scale];

    host.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 && e.pointerType === "mouse") return;
      // Touch: no emulated mouse events afterwards. (Everything here works from pointer
      // events, and an emulated mousedown would take the focus from a menu a long press opened.)
      if (e.pointerType !== "mouse") e.preventDefault();
      host.focus({ preventScroll: true });
      host.setPointerCapture(e.pointerId);
      pointers.set(e.pointerId, local(e));
      if (pointers.size === 2) {
        const [a, b] = [...pointers.values()];
        pinch = { dist: Math.hypot(a[0] - b[0], a[1] - b[1]), scale: this.scale };
        this.temp.replaceChildren();
        if (drag?.kind === "move" && drag.moved) { drag.item.x = drag.x0; drag.item.y = drag.y0; this.render(); }
        drag = null;
        return;
      }
      if (pointers.size !== 1) return;
      const t = e.target;
      drag = { start: local(e), ox: this.ox, oy: this.oy, moved: false, target: t, kind: "pan" };
      if (e.pointerType !== "mouse") {          // a long press opens the context menu
        const d = drag, at = local(e);
        d.timer = setTimeout(() => {
          if (drag !== d || d.moved) return;
          drag = null;
          this.temp.replaceChildren();
          this.longPressAt = performance.now();
          this.#openMenu(t, at);
        }, 550);
      }
      const pin = t.closest?.(".gv-pinhit");
      const bp = t.closest?.(".gv-bp");          // a node's breakpoint circle: a tap toggles it,
      const nodeEl = t.closest?.(".gv-node") ??  // a drag moves the node
        (bp ? this.world.querySelector(`.gv-node[data-id="${CSS.escape(bp.dataset.bp)}"]`) : null);
      const boxTitle = t.closest?.(".gv-box-title");
      if (pin) {
        drag.kind = "wire";
        drag.from = [pin.dataset.node, pin.dataset.dir, pin.dataset.pin];
        drag.at = this.geoms.get(pin.dataset.node)?.pins.get(`${pin.dataset.dir}|${pin.dataset.pin}`);
      } else if (nodeEl || boxTitle) {
        const id = nodeEl ? nodeEl.dataset.id : boxTitle.dataset.box;
        const item = nodeEl ? this.graph.nodes.find((n) => n.id === id)
                            : this.graph.boxes.find((b) => b.id === id);
        if (item) Object.assign(drag, { kind: "move", id, item, x0: item.x, y0: item.y });
      }
    });

    host.addEventListener("pointermove", (e) => {
      this.pointer = local(e);
      if (!pointers.has(e.pointerId)) return;
      pointers.set(e.pointerId, local(e));
      if (pinch && pointers.size === 2) {
        const [a, b] = [...pointers.values()];
        const dist = Math.hypot(a[0] - b[0], a[1] - b[1]);
        this.zoomAt((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (pinch.scale * dist / pinch.dist) / this.scale);
        return;
      }
      if (!drag) return;
      const [x, y] = local(e);
      const dx = x - drag.start[0], dy = y - drag.start[1];
      if (!drag.moved && Math.hypot(dx, dy) < 4) return;
      clearTimeout(drag.timer);
      if (!drag.moved && drag.kind !== "pan") {
        const ok = this.on.canEdit();
        if (ok !== true) {                  // not now: say why, and pan instead
          this.on.message(ok);
          drag.kind = "pan";
        }
      }
      drag.moved = true;
      if (drag.kind === "pan") {
        this.autoFit = false;
        this.ox = drag.ox + dx; this.oy = drag.oy + dy;
        this.#applyView();
        host.classList.add("panning");
      } else if (drag.kind === "move") {
        drag.item.x = Math.round(drag.x0 + dx / this.scale);
        drag.item.y = Math.round(drag.y0 + dy / this.scale);
        this.render();
      } else if (drag.kind === "wire" && drag.at) {
        const end = world([x, y]);
        const path = drag.from[1] === "in" ? this.#curve(end, drag.at, C.select, 2)
                                           : this.#curve(drag.at, end, C.select, 2);
        this.temp.replaceChildren(path);
      }
    });

    const end = (e) => {
      if (!pointers.has(e.pointerId)) return;
      pointers.delete(e.pointerId);
      host.classList.remove("panning");
      if (pointers.size < 2) pinch = null;
      const d = drag;
      drag = null;
      this.temp.replaceChildren();
      if (!d) return;
      clearTimeout(d.timer);
      if (e.type !== "pointerup") {         // cancelled: put a dragged node back
        if (d.kind === "move" && d.moved) { d.item.x = d.x0; d.item.y = d.y0; this.render(); }
        return;
      }
      if (!d.moved) return this.#click(d.target, local(e));
      if (d.kind === "move") {
        this.on.move(d.id, d.item.x, d.item.y);
      } else if (d.kind === "wire") {
        const under = document.elementFromPoint(e.clientX, e.clientY);
        const pin = under?.closest?.(".gv-pinhit");
        const nodeEl = under?.closest?.(".gv-node");
        if (pin) this.on.connect(d.from, [pin.dataset.node, pin.dataset.dir, pin.dataset.pin]);
        else if (nodeEl && nodeEl.dataset.id !== d.from[0]) this.on.connectToNode(d.from, nodeEl.dataset.id);
        else if (!under?.closest?.(".gv-wirehit, .gv-box")) this.on.palette(world(local(e)), local(e), d.from);
        else this.on.message("Drop the wire on a pin, on a node, or on empty canvas to add a node for it.");
      }
    };
    host.addEventListener("pointerup", end);
    host.addEventListener("pointercancel", end);
    host.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      if (performance.now() - (this.longPressAt ?? 0) < 800) return;   // a long press opened it
      this.#openMenu(document.elementFromPoint(e.clientX, e.clientY), local(e));
    });
    host.addEventListener("wheel", (e) => {
      e.preventDefault();
      const [x, y] = local(e);
      this.zoomAt(x, y, Math.exp(-e.deltaY * (e.deltaMode === 1 ? 0.05 : 0.0015)));
    }, { passive: false });
    host.addEventListener("keydown", (e) => {
      if (e.key === "Delete" || e.key === "Backspace") {
        e.preventDefault();
        if (this.selWire) {
          const [kind, node, pin] = this.selWire.split("|");
          this.on.disconnect(node, kind === "d" ? "in" : "out", pin);
        } else if (this.state.selected) {
          this.on.deleteNode(this.state.selected);
        }
      } else if (e.key === "Escape") {
        this.selWire = null;
        this.on.select(null);
      } else if (e.key === "Tab" && !e.shiftKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        const at = this.pointer ?? this.middle()[1];
        this.on.palette(world(at), at, null);
      }
    });
  }

  #click(target, at) {
    // (pointer capture sends dblclick to the host, so double clicks are found here)
    const bp = target.closest?.(".gv-bp");
    if (bp) return this.on.toggleBreakpoint(bp.dataset.bp);
    const wire = target.closest?.(".gv-wirehit");
    const pinHit = target.closest?.(".gv-pinhit");
    const row = target.closest?.("[data-row]");
    const nodeEl = target.closest?.(".gv-node");
    const id = pinHit ? pinHit.dataset.node : nodeEl?.dataset.id ?? null;
    const inPin = pinHit ? (pinHit.dataset.dir === "in" ? pinHit.dataset.pin : null) : row?.dataset.row ?? null;
    const key = `${id}|${inPin}`;
    const now = performance.now(), last = this.lastClick;
    this.lastClick = { key, at: now };
    if (last?.key === key && now - last.at < 400) {
      this.lastClick = null;
      if (!id && !wire && !target.closest?.(".gv-box-title, [data-note]")) {
        return this.on.palette([(at[0] - this.ox) / this.scale, (at[1] - this.oy) / this.scale], at, null);
      }
      if (inPin) return this.on.editPin(id, inPin, at);
      const n = this.graph?.nodes.find((x) => x.id === id);
      if (n?.opens) return this.on.open(n.opens);
    }
    if (wire && !id) {
      this.selWire = wire.dataset.wire;
      this.on.select(null);             // the page redraws, showing the wire selected
      return;
    }
    this.selWire = null;
    this.on.select(id);
  }
}
