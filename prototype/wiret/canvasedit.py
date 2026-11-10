"""The edits the graph canvas makes, without the canvas: wiring two pins, dropping a wire on a
node, disconnecting a pin and setting an input's value. The desktop editor (editor.py) and the
web page (webapi.edit) both make their canvas edits through these, so the rules are the same.

Each function changes the graph and returns a short description of the edit (for the status
line and the undo history), returns None when there is nothing to do, or raises Refused with
the reason to show.
"""
from __future__ import annotations

import re
from typing import Callable, Optional

from . import ops
from . import palette as pal
from .checker import GraphInfo
from .explain import type_words
from .model import Attr, Box, Graph, Lit, PinRef, set_note_text
from .parser import ParseError, parse_literal
from .registry import PRIM_TYPES, can_convert, enum_values, lit_fits

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
    target = g.node(nb)
    if out.type == inp.type or (target is not None and target.kind == "Format"
                                and out.type in PRIM_TYPES):
        # a Format input takes the type of what is bound to it (section 3.3)
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
    if p.type in idx.enums and "." not in text and "::" not in text:
        text = f"{p.type}::{text}"          # a bare member name is enough
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


# -- the context menu's edits ------------------------------------------------------------
# Each takes what was typed into the menu's prompt. The desktop editor asks with its dialogs,
# the web page with a box over the canvas; both then call these.

def set_enum(g: Graph, nid: str, pin: str, ty: str, member: str) -> str:
    ops.bind(g, nid, pin, Lit("enum", f"{ty}.{member}"))
    return f"Set {nid}.{pin} = {ty}.{member}"


def break_struct(g: Graph, nid: str, pin: str, ty: str, geom: Geom) -> tuple:
    """A BreakStruct to the right of a struct output, wired to it: (its id, description)."""
    gm = geom(nid)
    x, y = (gm[0] + gm[2] + 60, gm[1]) if gm else (0, 0)
    n = ops.create_node(g, "BreakStruct", ty, [], x, y)
    ops.bind(g, n.id, "obj", PinRef(nid, pin))
    return n.id, f"Added {n.id}: {nid}.{pin} split into fields"


def make_for_pin(g: Graph, nid: str, pin: str, ty: str, geom: Geom) -> tuple:
    """A MakeStruct to the left of a struct input, wired into it: (its id, description)."""
    gm = geom(nid)
    x, y = (gm[0] - 220, gm[1]) if gm else (0, 0)
    n = ops.create_node(g, "MakeStruct", ty, [], x, y)
    ops.bind(g, nid, pin, PinRef(n.id, "result"))
    return n.id, f"Added {n.id}: a {ty} for {nid}.{pin}"


def rename_node(g: Graph, nid: str, new: str) -> Optional[str]:
    """Give a node a new id; every wire follows. None when the id is unchanged."""
    from .parser import RESERVED
    if not new or new == nid:
        return None
    if "." in nid:
        raise Refused(f"'{nid}' is written inside the input it feeds, so its name says where it "
                      f"is. Wire its output into a second input to give it a name of its own.")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", new) or new in RESERVED:
        raise Refused("Not a valid identifier.")
    if g.node(new) or g.box(new):
        raise Refused(f"'{new}' is already used in this graph (E0102).")
    ops.rename_node(g, nid, new)
    return f"Renamed {nid} to {new}"


def _place_of(g: Graph, nid: str, remembered: dict):
    p = g.place(nid)
    if p is None:
        x, y = remembered.get((g.name, nid), (0, 0))
        ops.place(g, nid, x, y)
        p = g.place(nid)
    return p


def current_prop(g: Graph, nid: str, key: str) -> str:
    """A node's or box's `label` or `color`, as text ("" when it has none)."""
    p = g.place(nid) or g.box(nid)
    v = p.prop(key) if p else None
    return v.value if v is not None else ""


def set_label(g: Graph, nid: str, text: str, remembered: dict) -> str:
    """A node's display label (layout only); empty clears it."""
    _place_of(g, nid, remembered).set_prop("label", Lit("string", text) if text else None)
    return f"Labelled {nid}"


def set_color(g: Graph, nid: str, text: str, remembered: dict) -> str:
    """A node's or box's colour, #RRGGBB; empty clears it."""
    if text and not re.fullmatch(r"#[0-9A-Fa-f]{6}", text):
        raise Refused("Use the form #RRGGBB.")
    p = g.box(nid) or _place_of(g, nid, remembered)
    p.set_prop("color", Lit("string", text.upper()) if text else None)
    return f"Coloured {nid}"


def toggle_attr(g: Graph, nid: str, name: str) -> str:
    n = g.node(nid)
    if n.attr(name):
        n.attrs = [a for a in n.attrs if a.name != name]
    else:
        n.attrs.append(Attr(name))
    return f"Toggled @{name} on {nid}"


def int_attr(g: Graph, nid: str, name: str, default: int = 2) -> int:
    a = g.node(nid).attr(name)
    return a.args[0][1].value if a and a.args else default


def set_int_attr(g: Graph, nid: str, name: str, value) -> str:
    """@name(value) on a node, value a whole number from 1 to 64 (as Sequence's @count)."""
    try:
        v = int(str(value).strip())
    except ValueError:
        raise Refused("Enter a whole number from 1 to 64.")
    if not 1 <= v <= 64:
        raise Refused("Enter a whole number from 1 to 64.")
    n = g.node(nid)
    n.attrs = [x for x in n.attrs if x.name != name] + [Attr(name, [(None, Lit("int", v))])]
    return f"Set @{name}({v}) on {nid}"


def cases_prompt(g: Graph, idx, nid: str) -> tuple:
    """(what to ask, the current cases as text) for a Switch's @cases."""
    from .printer import fmt_lit
    n = g.node(nid)
    a = n.attr("cases")
    cur = ", ".join(fmt_lit(v) for _, v in a.args) if a and a.args else ""
    ety = n.targs[0] if n.targs and n.targs[0] in idx.enums else None
    prompt = "Case values, comma separated:"
    if ety:
        members = ", ".join(m for m, _ in enum_values(idx.enums[ety]))
        prompt = f"{ety} members, comma separated (one of: {members}):"
    return prompt, cur


def set_cases(g: Graph, idx, nid: str, text: str) -> str:
    """A Switch's @cases from comma-separated values; enum members need no type name."""
    import csv
    n = g.node(nid)
    ty = n.targs[0] if n.targs else None
    parts = [t.strip() for t in next(csv.reader([text], skipinitialspace=True), []) if t.strip()]
    if ty in idx.enums:      # bare member names are enough: Idle, Chase
        parts = [t if "." in t or "::" in t else f"{ty}::{t}" for t in parts]
    try:
        vals = [parse_literal(t) for t in parts]
    except ParseError as e:
        raise Refused(e.msg)
    n.attrs = [x for x in n.attrs if x.name != "cases"] + [Attr("cases", [(None, v) for v in vals])]
    return f"Set cases on {nid}"


def add_note(g: Graph, on: Optional[str], text: str) -> Optional[str]:
    """A note on a node or box, or on the whole graph (`on` None)."""
    if not text:
        return None
    ops.add_note(g, on, text)
    return "Added note"


def edit_note(g: Graph, key: str, text: str) -> Optional[str]:
    _, nt = ops.find_note(g, key)
    if nt is None or not text:
        return None
    set_note_text(nt, text)
    return "Edited note"


def delete_note(g: Graph, key: str) -> str:
    ops.delete_note(g, key)
    return "Deleted note"


def add_box(g: Graph, x: float, y: float, title: str, member: Optional[str] = None) -> Optional[str]:
    """A box at (x, y) titled `title`, holding the selected node (`member`) if there is one."""
    if not title:
        return None
    members = [Lit("ident", member)] if member else []
    g.boxes.append(Box(ops.fresh_id(g, "box"), int(x), int(y), [("members", Lit("list", members))],
                       title=title, w=360, h=220))
    return f"Added box {title!r}"


def set_members(g: Graph, bid: str, text: str) -> str:
    """A box's members: node or box ids, comma separated (membership is explicit, 2.3)."""
    ids = [t.strip() for t in text.split(",") if t.strip()]
    g.box(bid).set_prop("members", Lit("list", [Lit("ident", i) for i in ids]))
    return f"Edited members of {bid}"


def resize_box(g: Graph, bid: str, text: str) -> str:
    """A box's size from "width, height" (at least 40 each)."""
    try:
        w, h = (int(v) for v in (text or "").split(","))
    except ValueError:
        raise Refused("Enter the width and height, as in 360, 220.")
    b = g.box(bid)
    b.w, b.h = max(40, w), max(40, h)
    return f"Resized {bid}"


def retitle_box(g: Graph, bid: str, text: str) -> Optional[str]:
    if not text:
        return None
    g.box(bid).title = text
    return f"Retitled {bid}"


def local_prompt(idx, kw: str = "local") -> str:
    own = sorted(idx.structs) + sorted(idx.enums)
    example = f"  or  pos: {own[0]}" if own else ""
    return f"name: type   (e.g.  count: i32  or  scores: array::<i32>{example})"


def add_local(g: Graph, idx, kw: str, text: str) -> Optional[str]:
    """A local (or state) variable from "name: type"."""
    from .model import Local
    from .registry import type_ok
    if not text or ":" not in text:
        return None
    name, ty = (s.strip() for s in text.split(":", 1))
    if not re.fullmatch(r"[A-Za-z_]\w*", name) or not type_ok(ty, idx):
        own = sorted(idx.structs) + sorted(idx.enums)
        extra = f", or one of this module's types: {', '.join(own)}" if own else ""
        raise Refused("Use a valid name and a type such as i32, string "
                      f"or array::<i32>{extra}.")
    (g.locals if kw == "local" else g.states).append(Local(name, ty))
    return f"Added {kw} {name}"
