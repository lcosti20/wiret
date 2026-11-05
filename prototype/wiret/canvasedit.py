"""The edits the graph canvas makes, without the canvas: wiring two pins, dropping a wire on a
node, disconnecting a pin and setting an input's value. The desktop editor (editor.py) and the
web page (webapi.edit) both make their canvas edits through these, so the rules are the same.

Each function changes the graph and returns a short description of the edit (for the status
line and the undo history), returns None when there is nothing to do, or raises Refused with
the reason to show.
"""
from __future__ import annotations

from typing import Callable, Optional

from . import ops
from . import palette as pal
from .checker import GraphInfo
from .explain import type_words
from .model import Graph, Lit, PinRef
from .parser import ParseError, parse_literal
from .registry import can_convert, enum_values, lit_fits

# geom(node id) -> (x, y, width) of a node as drawn, or None; used to place an inserted node
Geom = Callable[[str], Optional[tuple]]


class Refused(Exception):
    """An edit the canvas does not make. The message says why, in plain words."""


def connect(g: Graph, info, idx, a: tuple, b: tuple, geom: Geom) -> Optional[str]:
    """Wire pin `a` to pin `b`, each (node, "in"/"out", pin), in either order. A data wire
    between different types that convert gets a visible Convert node in between."""
    (na, da, pa), (nb, db, pb) = a, b
    if da == db:
        raise Refused("Connect an output pin to an input pin.")
    if da == "in":
        (na, da, pa), (nb, db, pb) = b, a
    if na == nb:
        raise Refused("A node cannot be wired to itself.")
    sig_a, sig_b = info.sigs.get(na), info.sigs.get(nb)
    out = sig_a.output(pa) if sig_a else None
    inp = sig_b.input(pb) if sig_b else None
    if out is None or inp is None:
        return None
    if out.is_exec != inp.is_exec:
        raise Refused("Exec pins connect only to exec pins (E0120).")
    if out.is_exec:
        single = sig_a.exec_outs[0].name if len(sig_a.exec_outs) == 1 else None
        ops.wire_exec(g, na, pa, nb, pb, single)
        return f"Wired {na}.{pa} -> {nb}" + ("" if pb == "in" else f".{pb}")
    if out.type == inp.type:
        ops.bind(g, nb, pb, PinRef(na, pa))
        return f"Bound {nb}.{pb} = {na}.{pa}"
    if can_convert(out.type, inp.type, idx):
        # Insert a visible Convert node rather than changing a type silently (section 7.5)
        ga, gb = geom(na) or (0, 0, 0), geom(nb) or (0, 0, 0)
        conv = ops.create_node(g, "Convert", None, [out.type, inp.type],
                               (ga[0] + ga[2] + gb[0]) / 2 - 60, (ga[1] + gb[1]) / 2 + 40)
        ops.bind(g, conv.id, "value", PinRef(na, pa))
        ops.bind(g, nb, pb, PinRef(conv.id, "result"))
        return f"Inserted {conv.id} = Convert::<{out.type}, {inp.type}>"
    raise Refused(f"Cannot connect {out.type} to {inp.type}: no conversion exists (E0110).")


def connect_to_node(g: Graph, info, idx, a: tuple, nid: str, geom: Geom) -> Optional[str]:
    """A wire from pin `a` dropped on a node: connect it to the first pin there that fits."""
    na, da, pa = a
    sig = info.sigs.get(nid)
    src_sig = info.sigs.get(na)
    if sig is None or src_sig is None:
        return None
    pin = src_sig.output(pa) if da == "out" else src_sig.input(pa)
    if pin is None:
        return None
    if da == "out":
        cands = [p for p in sig.inputs if p.is_exec == pin.is_exec and
                 (pin.is_exec or p.type == pin.type) and
                 (pin.is_exec or g.node(nid).binding(p.name) is None)]
        if cands:
            return connect(g, info, idx, a, (nid, "in", cands[0].name), geom)
    else:
        cands = [p for p in sig.outputs if p.is_exec == pin.is_exec and
                 (pin.is_exec or p.type == pin.type)]
        if cands:
            return connect(g, info, idx, a, (nid, "out", cands[0].name), geom)
    return None


def disconnect(g: Graph, info, nid: str, d: str, pin: str) -> str:
    """Remove the wires at one pin: what feeds an input, or everything an output feeds."""
    sig = info.sigs[nid]
    if d == "in":
        p = sig.input(pin)
        if p is not None and p.is_exec:     # remove every exec wire into this pin
            for m in g.nodes:
                m.execs = [e for e in m.execs
                           if not (e.target == nid and (e.target_pin or "in") == pin)]
        else:
            ops.unbind(g, nid, pin)
    else:
        p = sig.output(pin)
        if p is not None and p.is_exec:
            single = sig.exec_outs[0].name if len(sig.exec_outs) == 1 else None
            ops.unwire_exec(g, nid, pin, single)
        else:
            for m in g.nodes:
                for b in list(m.bindings):
                    if isinstance(b.value, PinRef) and b.value.node == nid and b.value.pin == pin:
                        m.bindings.remove(b)
    return f"Disconnected {nid}.{pin}"


def toggle_bool(g: Graph, nid: str, pin: str) -> str:
    """Flip a bool input's value (true when it has none yet)."""
    b = g.node(nid).binding(pin)
    new = Lit("bool", not (b is not None and isinstance(b.value, Lit) and b.value.value))
    ops.bind(g, nid, pin, new)
    return f"Set {nid}.{pin} = {'true' if new.value else 'false'}"


def literal_prompt(g: Graph, info, idx, nid: str, pin: str) -> Optional[dict]:
    """What to ask when an input's value is edited: {"type", "current", "hint"}, or None when
    the pin takes no typed value (an exec pin)."""
    p = info.sigs[nid].input(pin)
    if p is None or p.is_exec:
        return None
    from .printer import fmt_lit
    b = g.node(nid).binding(pin)
    current = fmt_lit(b.value) if b is not None and isinstance(b.value, Lit) else ""
    hint = ""
    if p.type in idx.enums:
        hint = "One of: " + ", ".join(m for m, _ in enum_values(idx.enums[p.type]))
    return {"type": p.type, "current": current, "hint": hint}


def set_literal(g: Graph, info, idx, nid: str, pin: str, text: str) -> str:
    """Set an input to the value typed for it. Empty text unbinds it (it takes its default).
    A string needs no quotes, and an enum member no type name."""
    p = info.sigs[nid].input(pin)
    if p is None or p.is_exec:
        raise Refused(f"{nid}.{pin} takes no value.")
    if p.type in idx.structs:
        raise Refused(f"A {p.type} has no typed value. Wire a 'Make {p.type}' node into {nid}.{pin}.")
    text = text.strip()
    if not text:
        ops.unbind(g, nid, pin)
        return f"Unbound {nid}.{pin}"
    if p.type == "string" and not text.startswith('"'):
        text = '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if p.type in idx.enums and "." not in text:
        text = f"{p.type}.{text}"           # a bare member name is enough
    try:
        lit = parse_literal(text)
    except ParseError as e:
        if p.type not in idx.enums:
            raise Refused(e.msg)
        lit = None
    if p.type in idx.enums and (lit is None or not lit_fits(lit, p.type) or
                                idx.enums[p.type].member(lit.value.split(".")[1]) is None):
        names = ", ".join(m for m, _ in enum_values(idx.enums[p.type]))
        raise Refused(f"{text} is not a member of {p.type}. Choose one of: {names}")
    if not lit_fits(lit, p.type):
        raise Refused(f"{text} is not a valid {p.type}")
    ops.bind(g, nid, pin, lit)
    return f"Set {nid}.{pin} = {text}"


def palette(g: Graph, info, idx, context: Optional[tuple] = None) -> Optional[tuple]:
    """The node palette: (title, items, ranked by palette.rank). With a pin `context`
    (node, "in"/"out", pin), only nodes with a pin that fits are listed. None when the
    context pin does not exist."""
    candidates = pal.items(g, idx)
    title = "Add node — type to search (↑↓, Enter)"
    if context:
        nid, d, pin = context
        sig = info.sigs.get(nid)
        p = (sig.output(pin) if d == "out" else sig.input(pin)) if sig else None
        if p is None:
            return None
        candidates = [it for it in candidates
                      if pal.compatible(it, g, idx, d, p.type) is not None]
        title = f"Add a node for {nid}.{pin} ({type_words(p.type)})"
    return title, candidates


def add_node(g: Graph, idx, item, x: float, y: float, context: Optional[tuple] = None,
             geom: Optional[Geom] = None) -> tuple:
    """Add the palette item at (x, y): (its id, a description of the edit). With a pin
    `context`, the new node is wired to that pin; a producer for an input goes to its left."""
    if context and context[1] == "in":
        x -= 200
    n = ops.create_node(g, item.kind, item.symbol, item.targs, x, y)
    if not context:
        return n.id, f"Added {n.id}"
    info = GraphInfo(g, idx)
    nid, d, pin = context
    sig = info.sigs[nid]
    p = sig.output(pin) if d == "out" else sig.input(pin)
    other = pal.compatible(item, g, idx, d, p.type)
    reason = connect(g, info, idx, context, (n.id, "in" if d == "out" else "out", other),
                     geom or (lambda _nid: None))
    return n.id, reason or f"Added {n.id}"


def place_unplaced(g: Graph, remembered: dict) -> None:
    """Give every node without a place line one, where the automatic layout put it: auto-placed
    nodes get a place line when first saved (section 2.3)."""
    for n in g.nodes:
        if g.place(n.id) is None:
            x, y = remembered.get((g.name, n.id), (0, 0))
            ops.place(g, n.id, x, y)
    ops.prune_box_members(g)
