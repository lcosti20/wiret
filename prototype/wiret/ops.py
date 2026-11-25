"""Model edit operations (spec section 7.2), used by the graph editor and the CLI.

Each operation changes only the model; callers re-print the canonical text afterwards.
"""
from __future__ import annotations

import random
import re
import string
from typing import Optional

from .model import (Attr, Binding, Box, ExecOut, Graph, Lit, Module, Node, PinRef, Place, note,
                    notes)

_ALPHABET = string.ascii_lowercase + string.digits


def slug(text: str) -> str:
    s = re.sub(r"(?<!^)(?=[A-Z])", "_", text).lower()
    s = re.sub(r"[^a-z0-9_]", "_", s).strip("_")
    return s or "node"


def fresh_id(g: Graph, base: str, rng=random) -> str:
    """A readable slug plus a short random suffix, unique in the graph (section 2.3)."""
    taken = {n.id for n in g.nodes} | {b.id for b in g.boxes}
    while True:
        cand = f"{slug(base)}_{''.join(rng.choice(_ALPHABET) for _ in range(4))}"
        if cand not in taken:
            return cand


def create_node(g: Graph, kind: str, symbol=None, targs=None, x=0, y=0, nid=None) -> Node:
    """A new node. Given an id it is a named node (`node nid = ...`); otherwise it is anonymous
    and its id is a placeholder until the text is read back (section 2.3)."""
    base = (symbol.split(".")[-1] if symbol and kind in ("Call", "Macro") else kind)
    n = Node(nid or fresh_id(g, base), kind, symbol, list(targs or []), named=nid is not None)
    g.nodes.append(n)
    g.places.append(Place(n.id, int(x), int(y)))
    return n


def bind(g: Graph, node_id: str, pin: str, value) -> None:
    n = g.node(node_id)
    n.bindings = [b for b in n.bindings if b.pin != pin]
    if value is not None:
        n.bindings.append(Binding(pin, value))


def unbind(g: Graph, node_id: str, pin: str) -> None:
    bind(g, node_id, pin, None)


def wire_exec(g: Graph, node_id: str, out_pin: str, target: str, target_pin=None,
              single_out: Optional[str] = None) -> None:
    """Connect an exec output. `single_out` names the node's only exec output, if it has one."""
    n = g.node(node_id)
    n.execs = [e for e in n.execs if (e.pin or single_out) != out_pin]
    n.execs.append(ExecOut(out_pin, target, None if target_pin in (None, "in") else target_pin))


def unwire_exec(g: Graph, node_id: str, out_pin: str, single_out: Optional[str] = None) -> None:
    n = g.node(node_id)
    n.execs = [e for e in n.execs if (e.pin or single_out) != out_pin]


def delete_node(g: Graph, node_id: str) -> list:
    """Delete a node and every wire that names it (cascade). Its notes move to the graph,
    detached (W0604), instead of being deleted (section 2.4).

    Returns a description of the removed wires.
    """
    removed = []
    n = g.node(node_id)
    if n is not None:
        detach_notes(g, n)
    g.nodes = [n for n in g.nodes if n.id != node_id]
    g.places = [p for p in g.places if p.id != node_id]
    for n in g.nodes:
        for b in list(n.bindings):
            if isinstance(b.value, PinRef) and b.value.node == node_id:
                n.bindings.remove(b)
                removed.append(f"{node_id}.{b.value.pin} -> {n.id}.{b.pin}")
        for e in list(n.execs):
            if e.target == node_id:
                n.execs.remove(e)
                removed.append(f"{n.id}.{e.pin or 'then'} -> {node_id}")
    return removed


def delete_box(g: Graph, box_id: str) -> None:
    """Delete a box (not the nodes inside it). Its notes move to the graph, detached."""
    b = g.box(box_id)
    if b is not None:
        detach_notes(g, b)
    g.boxes = [x for x in g.boxes if x.id != box_id]


def detach_notes(g: Graph, owner) -> None:
    """Move the notes of a node or box that is being deleted up to the graph (section 2.4)."""
    for a in notes(owner.meta):
        args = [(k, v) for k, v in (a.args or []) if k != "detached"]
        g.meta.append(Attr("note", args + [("detached", Lit("string", owner.id))]))
    owner.meta = [a for a in owner.meta if a.name != "note"]


def rename_node(g: Graph, old: str, new: str) -> None:
    """Name a node, or rename a named one. A node named for the first time goes after the
    names already there (section 2.3)."""
    for n in list(g.nodes):
        if n.id == old:
            n.id = new
            if not n.named:
                n.named = True
                g.nodes.remove(n)
                g.nodes.append(n)
        for b in n.bindings:
            if isinstance(b.value, PinRef) and b.value.node == old:
                b.value.node = new
        for e in n.execs:
            if e.target == old:
                e.target = new
    for p in g.places:
        if p.id == old:
            p.id = new


def inside(b: Box, p: Place) -> bool:
    return b.x <= p.x <= b.x + b.w and b.y <= p.y <= b.y + b.h


def place(g: Graph, nid: str, x: int, y: int) -> None:
    """Move a node, or a box and every node that lies inside it (section 2.3)."""
    b = g.box(nid)
    if b is not None:
        dx, dy = int(x) - b.x, int(y) - b.y
        for p in [p for p in g.places if inside(b, p)]:
            p.x, p.y = p.x + dx, p.y + dy
        b.x, b.y = int(x), int(y)
        return
    p = g.place(nid)
    if p is None:
        g.places.append(Place(nid, int(x), int(y)))
    else:
        p.x, p.y = int(x), int(y)


def add_note(g: Graph, on: Optional[str], text: str) -> Attr:
    """Add an `@note` to a node or box (`on`), or to the whole graph (`on` is None)."""
    nt = note(text)
    g.note_owner(on).meta.append(nt)
    return nt


def note_key(on: Optional[str], index: int) -> str:
    """A name for one note in the editor: its target and its position among that target's notes."""
    return f"{on or ''}|{index}"


def find_note(g: Graph, key: str):
    """(owner, note) for a `note_key`, or (None, None)."""
    on, _, i = key.rpartition("|")
    owner = g.note_owner(on or None)
    ns = notes(owner.meta) if owner is not None else []
    if not i.isdigit() or int(i) >= len(ns):
        return None, None
    return owner, ns[int(i)]


def delete_note(g: Graph, key: str) -> None:
    owner, nt = find_note(g, key)
    if owner is not None:
        owner.meta = [a for a in owner.meta if a is not nt]


def convert_comments(m: Module) -> list:
    """`--convert-comments`: turn each `//` comment into an `@note` above the next node or
    graph, so it stays where it was written (section 2.1).

    Returns messages for comments that had nothing to attach to and were dropped.
    """
    dropped = []
    for c in m.comments:
        a = c.anchor
        g = m.graph(a[1]) if a else None
        if g is None:
            dropped.append(f"line {c.line}: comment outside any graph was dropped: {c.text}")
            continue
        owner = (g.node(a[2]) if a[0] == "node" else None) or g
        owner.meta.append(note(c.text))
    m.comments = []
    return dropped
