"""What a graph looks like, without drawing it: node titles, pin labels, colors and the
automatic layout of nodes that have no `place` line. The desktop canvas (graphview.py) draws
from these; `graph_json` hands the same to the web page."""
from __future__ import annotations

from collections import Counter

from .explain import type_words
from .palette import describe
from .model import Graph, Lit, PinRef, note_detached, note_text
from .ops import note_key
from .printer import fmt_lit
from .registry import FLOAT_TYPES, INT_TYPES

HEADER = 24     # node header height, in graph units
ROW = 20        # height of one pin row

HEADER_COLORS = {"Arrays": "#b9770e", "Flow": "#566573", "Call": "#2471a3", "Math": "#1e8449", "Compare": "#138d75",
                 "Logic": "#9a7d0a", "Bits": "#873600", "Variables": "#6c3483", "Macro": "#7d3c98",
                 "Structs": "#1f618d", "Time": "#a04000",
                 "Classes": "#1a5276", "Delegates": "#6e2c00", "Other": "#566573"}
ENTRY_RETURN_COLOR = "#a93226"
DISABLED_COLOR = "#4d4d4d"
BOX_COLOR = "#7f8c8d"


def type_color(ty: str, idx=None) -> str:
    if idx is not None and ty in idx.structs:
        return "#5dade2"        # structs: light blue, whatever they hold
    if idx is not None and ty in idx.enums:
        return "#af7ac5"        # enums: lavender (yellow is for the debugger's value tags)
    if ty == "exec":
        return "#ffffff"
    if ty == "bool":
        return "#e74c3c"
    if ty in ("i64", "u64"):
        return "#48c9b0"
    if ty in INT_TYPES:
        return "#1abc9c"
    if ty in FLOAT_TYPES:
        return "#a3d65c"
    if ty == "string":
        return "#e056fd"
    if ty.startswith("map::<"):
        return "#dc7633"        # maps: dark orange
    if ty.startswith("set::<"):
        return "#f8c471"        # sets: pale orange
    if ty.startswith("array::<"):
        return "#f0a830"        # arrays: orange, whatever they hold
    return "#95a5a6"


def node_title(n) -> str:
    t = n.kind
    if n.symbol:
        t += " " + n.symbol.split(".")[-1] if n.kind == "Call" and n.symbol.startswith("std.") \
            else " " + n.symbol
    if n.targs:
        t += "::<" + ", ".join(n.targs) + ">"
    return t


def display_title(g: Graph, n) -> str:
    """The node's `label` from its place line, or its title."""
    place = g.place(n.id)
    label = place.prop("label") if place else None
    return label.value if label is not None and label.kind == "string" else node_title(n)


def input_label(n, pin) -> str:
    if pin.is_exec:
        return "" if pin.name == "in" else pin.name
    b = n.binding(pin.name)
    if b is not None and isinstance(b.value, Lit):
        text = fmt_lit(b.value)
        if len(text) > 22:
            text = text[:20] + "…\""
        return f"{pin.name} = {text}"
    if b is None and pin.default is not None and n.kind not in ("Exit", "Leave"):
        return f"{pin.name} ({fmt_lit(pin.default_lit())})"
    return pin.name


def output_label(sig, pin) -> str:
    """An output pin's label; a lone `then` exec output needs none."""
    return "" if (pin.name == "then" and pin.is_exec and len(sig.exec_outs) == 1) else pin.name


def header_color(g: Graph, n, sig) -> str:
    if n.attr("disabled") is not None:
        return DISABLED_COLOR
    place = g.place(n.id)
    c = place.prop("color") if place else None
    if c is not None and c.kind == "string":
        return c.value
    if n.kind in ("Entry", "Return"):
        return ENTRY_RETURN_COLOR
    return HEADER_COLORS.get(sig.category, HEADER_COLORS["Other"])


def exec_targets(g: Graph) -> set:
    return {(e.target, e.target_pin or "in") for n in g.nodes for e in n.execs}


def used_outputs(g: Graph, info) -> set:
    used = set()
    for n in g.nodes:
        for b in n.bindings:
            if isinstance(b.value, PinRef):
                used.add((b.value.node, b.value.pin))
        for e in n.execs:
            used.add((n.id, info.exec_pin(n, e)))
    return used


def positions(g: Graph, info, remembered: dict) -> dict:
    """node id -> (x, y): from the place lines, and for nodes without one, from `remembered`
    ((graph, node) -> (x, y), updated here) or the automatic layout (section 7.5: lay out
    only what has no layout)."""
    pos = {p.id: (p.x, p.y) for p in g.places}
    if any(n.id not in pos for n in g.nodes):
        auto_layout(g, info, pos, remembered)
    return pos


def auto_layout(g: Graph, info, pos: dict, remembered: dict):
    """Place nodes without a `place` line."""
    for n in g.nodes:
        if n.id not in pos and (g.name, n.id) in remembered:
            pos[n.id] = remembered[(g.name, n.id)]
    depth = {}
    entry = info.entry()
    if entry:
        todo = [(entry, 0)]
        while todo:
            nid, d = todo.pop(0)
            if nid in depth:
                continue
            depth[nid] = d
            todo += [(s, d + 1) for s in info.successors(nid)]
    maxd = max(depth.values(), default=0)
    col_rows = Counter()
    for n in sorted(g.nodes, key=lambda n: (depth.get(n.id, maxd + 1), n.id)):
        if n.id in pos or info.sigs[n.id].pure:
            continue
        d = depth.get(n.id, maxd + 1)
        pos[n.id] = (d * 250, col_rows[d] * 200)
        col_rows[d] += 1
    stacked = Counter()

    def place_pure(consumer):
        cx, cy = pos[consumer]
        for b in info.nodes[consumer].bindings:
            if isinstance(b.value, PinRef):
                src = b.value.node
                if src in info.nodes and src not in pos and info.sigs[src].pure:
                    k = stacked[consumer]
                    stacked[consumer] += 1
                    pos[src] = (cx - 200, cy + 110 + k * 90)
                    place_pure(src)

    for n in sorted(g.nodes, key=lambda n: n.id):
        if n.id in pos:
            place_pure(n.id)
    y = 400
    for n in sorted(g.nodes, key=lambda n: n.id):
        if n.id not in pos:
            pos[n.id] = (-250, y)
            y += 90
    for nid, p in pos.items():
        if g.place(nid) is None:
            remembered[(g.name, nid)] = p


def opens(module, n) -> str | None:
    """The graph of this module that a Call or Macro node runs, if any."""
    if module is None or n.kind not in ("Call", "Macro") or not n.symbol:
        return None
    prefix = module.name + "."
    target = n.symbol[len(prefix):] if n.symbol.startswith(prefix) else n.symbol
    return target if module.graph(target) else None


def graph_json(g: Graph, info, idx, diags=(), remembered=None, module=None) -> dict:
    """One graph as plain data for the web page to draw. Positions are in graph units; the
    page works out node widths from its own text measurements, as graphview.py does."""
    remembered = {} if remembered is None else remembered
    pos = positions(g, info, remembered)
    targets, used = exec_targets(g), used_outputs(g, info)
    marks = {}
    for d in diags:
        if d.graph == g.name and d.top_node and marks.get(d.top_node) != "error":
            marks[d.top_node] = d.severity
    nodes, wires = [], []
    for n in g.nodes:
        sig = info.sigs.get(n.id)
        if sig is None:
            continue
        connected = {b.pin for b in n.bindings if isinstance(b.value, PinRef)}
        x, y = pos.get(n.id, (0, 0))
        nodes.append({
            "id": n.id, "title": display_title(g, n), "x": x, "y": y,
            "header": header_color(g, n, sig), "pure": sig.pure,
            "disabled": n.attr("disabled") is not None, "diag": marks.get(n.id),
            "opens": opens(module, n), "description": describe(n.kind, n.symbol, idx, n.targs),
            "ins": [{"name": p.name, "exec": p.is_exec, "type": type_words(p.type),
                     "color": type_color(p.type, idx),
                     "label": input_label(n, p), "bound": n.binding(p.name) is not None,
                     "filled": p.name in connected or (p.is_exec and (n.id, p.name) in targets)}
                    for p in sig.exec_ins + sig.data_ins],
            "outs": [{"name": p.name, "exec": p.is_exec, "type": type_words(p.type),
                      "color": type_color(p.type, idx),
                      "label": output_label(sig, p), "filled": (n.id, p.name) in used}
                     for p in sig.exec_outs + sig.data_outs],
        })
        for b in n.bindings:
            if isinstance(b.value, PinRef):
                pin = sig.input(b.pin)
                wires.append({"exec": False, "from": [b.value.node, b.value.pin],
                              "to": [n.id, b.pin],
                              "color": type_color(pin.type if pin else "", idx)})
        for e in n.execs:
            out = info.exec_pin(n, e)
            if out:
                wires.append({"exec": True, "from": [n.id, out],
                              "to": [e.target, e.target_pin or "in"], "color": "#f0f0f0"})
    notes = []
    for on, i, nt in g.all_notes():
        notes.append({"on": on if on and g.node(on) else None, "text": note_text(nt),
                      "detached": note_detached(nt), "key": note_key(on, i)})
    boxes = []
    for b in g.boxes:
        c = b.prop("color")
        boxes.append({"id": b.id, "title": b.title, "x": b.x, "y": b.y, "w": b.w, "h": b.h,
                      "color": c.value if c is not None and c.kind == "string" else BOX_COLOR})
    return {"name": g.name, "kind": g.kind, "nodes": nodes, "wires": wires, "notes": notes,
            "boxes": boxes}
