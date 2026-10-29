"""Model edit operations (spec section 7.2), used by the graph editor and the CLI.

Each operation changes only the model; callers re-print the canonical text afterwards.
"""
from __future__ import annotations

import random
import re
import string
from typing import Optional

from .model import (Binding, Box, ExecOut, Graph, Lit, Module, Node, Note, PinRef, Place)

_ALPHABET = string.ascii_lowercase + string.digits


def slug(text: str) -> str:
    s = re.sub(r"(?<!^)(?=[A-Z])", "_", text).lower()
    s = re.sub(r"[^a-z0-9_]", "_", s).strip("_")
    return s or "node"


def fresh_id(g: Graph, base: str, rng=random) -> str:
    """A readable slug plus a short random suffix, unique in the graph (section 2.3)."""
    taken = {n.id for n in g.nodes} | {b.id for b in g.boxes} | {n.id for n in g.notes}
    while True:
        cand = f"{slug(base)}_{''.join(rng.choice(_ALPHABET) for _ in range(4))}"
        if cand not in taken:
            return cand


def create_node(g: Graph, kind: str, symbol=None, targs=None, x=0, y=0, nid=None) -> Node:
    base = (symbol.split(".")[-1] if symbol and kind in ("Call", "Macro") else kind)
    n = Node(nid or fresh_id(g, base), kind, symbol, list(targs or []))
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
    """Delete a node and every wire that names it (cascade). Notes are kept (W0604).

    Returns a description of the removed wires.
    """
    removed = []
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
    prune_box_members(g)
    return removed


def prune_box_members(g: Graph) -> None:
    """Drop member ids that name nothing (W0601: removed on the next editor save)."""
    ids = {n.id for n in g.nodes} | {b.id for b in g.boxes}
    for b in g.boxes:
        m = b.prop("members")
        if m is not None and m.kind == "list":
            b.set_prop("members", Lit("list", [v for v in m.value
                                               if v.kind != "ident" or v.value in ids]))


def rename_node(g: Graph, old: str, new: str) -> None:
    for n in g.nodes:
        if n.id == old:
            n.id = new
        for b in n.bindings:
            if isinstance(b.value, PinRef) and b.value.node == old:
                b.value.node = new
        for e in n.execs:
            if e.target == old:
                e.target = new
    for p in g.places:
        if p.id == old:
            p.id = new
    for nt in g.notes:
        if nt.on == old:
            nt.on = new
    for b in g.boxes:
        m = b.prop("members")
        if m is not None and m.kind == "list":
            for v in m.value:
                if v.kind == "ident" and v.value == old:
                    v.value = new


def place(g: Graph, nid: str, x: int, y: int) -> None:
    b = g.box(nid)
    if b is not None:
        b.x, b.y = int(x), int(y)
        return
    p = g.place(nid)
    if p is None:
        g.places.append(Place(nid, int(x), int(y)))
    else:
        p.x, p.y = int(x), int(y)


def add_note(g: Graph, on: Optional[str], text: str) -> Note:
    nt = Note(fresh_id(g, "note"), on, text)
    g.notes.append(nt)
    return nt


def convert_comments(m: Module) -> list:
    """`--convert-comments`: turn each `//` comment into a note (section 2.1).

    Returns messages for comments that had nothing to attach to and were dropped.
    """
    dropped = []
    for c in m.comments:
        a = c.anchor
        g = m.graph(a[1]) if a else None
        if g is None:
            dropped.append(f"line {c.line}: comment outside any graph was dropped: {c.text}")
            continue
        nt = Note(fresh_id(g, "comment"), a[2] if a[0] == "node" else None, c.text)
        g.notes.append(nt)
    m.comments = []
    return dropped
