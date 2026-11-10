"""`wiretc diff a b`: a node-aware semantic diff in flow order (spec section 7).

Changes to behaviour come first, per declaration and per graph: added, removed and changed
nodes, each change named by field (a binding, an exec wire, the kind, ...). Metadata
(`#[...]` lines) and layout-only changes follow in sections of their own, so a reviewer can
tell at a glance whether a commit changed what the program does.
"""
from __future__ import annotations

import difflib

from .checker import GraphInfo
from .flow import flow_order
from .merge import decl_fields, decl_kind, key_of, meta_text, node_fields, sub_fields
from .model import Graph, Module
from .printer import IND, fmt_node
from .registry import ModuleIndex, signature


def raw_diff(a_text: str, b_text: str, a_name="a", b_name="b") -> str:
    return "".join(difflib.unified_diff(a_text.splitlines(True), b_text.splitlines(True),
                                        a_name, b_name))


def _match(a_items: list, b_items: list, key, name_key) -> list:
    """(a, b) pairs by key, an element without an @id falling back to its name key."""
    ka = {key(x): x for x in a_items}
    kb = {key(x): x for x in b_items}
    for side, other in ((ka, kb), (kb, ka)):
        names = {name_key(x): k for k, x in other.items() if k[0] == "id"}
        for k, x in list(side.items()):
            t = names.get(name_key(x)) if k[0] != "id" else None
            if t is not None and t not in side:
                side[t] = side.pop(k)
    keys = list(ka) + [k for k in kb if k not in ka]
    return [(ka.get(k), kb.get(k)) for k in keys]


def _field_changes(fa: dict, fb: dict) -> list:
    """`key: old -> new` for every field that differs."""
    out = []
    for k in sorted(set(fa) | set(fb)):
        va, vb = fa.get(k, (None,))[0], fb.get(k, (None,))[0]
        if va != vb:
            label = k.replace("bind:", ".").replace("exec:", "exec ").replace("attr:", "@")
            out.append(f"{label}: {'(none)' if va is None else va} -> "
                       f"{'(none)' if vb is None else vb}")
    return out


class Differ:
    def __init__(self, a: Module, b: Module):
        self.a, self.b = a, b
        self.ia, self.ib = ModuleIndex(a), ModuleIndex(b)
        self.semantic: list = []
        self.meta: list = []
        self.layout: list = []

    def run(self) -> str:
        a, b = self.a, self.b
        if a.name != b.name:
            self.semantic.append(f"module {a.name} -> {b.name}")
        self.meta_changes("module", a.meta, b.meta)
        for x, y in _match(a.items, b.items, lambda i: key_of(i, decl_kind(i)),
                           lambda i: (decl_kind(i), i.name)):
            self.decl(x, y)
        return self.report()

    def decl(self, x, y):
        it = y or x
        head = f"{decl_kind(it)} {it.name}"
        if x is None:
            self.semantic.append(f"+ {head}")
            return
        if y is None:
            self.semantic.append(f"- {head}")
            return
        lines = []
        if x.name != y.name:
            head = f"{decl_kind(y)} {x.name} -> {y.name} (renamed)"
        fa, fb = decl_fields(x), decl_fields(y)
        fa.pop("name"), fb.pop("name")
        lines += [f"{IND}~ {c}" for c in _field_changes(fa, fb)]
        for attr, kind in (("params", "param"), ("results", "result"), ("fields", "field"),
                           ("members", "member"), ("locals", "local"), ("states", "state")):
            xs, ys = getattr(x, attr, None) or [], getattr(y, attr, None) or []
            for p, q in _match(xs, ys, key_of, lambda s: ("", s.name)):
                if p is None:
                    lines.append(f"{IND}+ {kind} {q.name}")
                elif q is None:
                    lines.append(f"{IND}- {kind} {p.name}")
                else:
                    name = p.name if p.name == q.name else f"{p.name} -> {q.name}"
                    fa, fb = sub_fields(p), sub_fields(q)
                    fa.pop("name"), fb.pop("name")
                    changes = _field_changes(fa, fb)
                    if changes or p.name != q.name:
                        lines.append(f"{IND}~ {kind} {name}" +
                                     (f": {'; '.join(changes)}" if changes else ""))
            if (xs or ys) and [s.name for s in xs] != [s.name for s in ys] and \
                    {s.name for s in xs} == {s.name for s in ys}:
                lines.append(f"{IND}~ {attr} reordered")
        self.meta_changes(y.name, x.meta, y.meta)
        if isinstance(x, Graph) and isinstance(y, Graph):
            lines += self.graph(x, y)
        if lines or head.endswith("(renamed)"):
            self.semantic.append(head)
            self.semantic.extend(lines)

    def graph(self, x: Graph, y: Graph) -> list:
        ia, ib = GraphInfo(x, self.ia), GraphInfo(y, self.ib)
        order = flow_order(y, ib)
        order += [nid for nid in flow_order(x, ia) if y.node(nid) is None]
        rank = {nid: i for i, nid in enumerate(order)}
        out = []

        def single(n, g, idx):
            outs = signature(n, g, idx).exec_outs
            return outs[0].name if len(outs) == 1 else None

        ids = sorted({n.id for n in x.nodes} | {n.id for n in y.nodes},
                     key=lambda i: (rank.get(i, len(rank)), i))
        for nid in ids:
            p, q = x.node(nid), y.node(nid)
            if p is None:
                text = fmt_node(q, signature(q, y, self.ib), "").splitlines()
                out.append(f"{IND}+ {text[0]}")
                out += [f"{IND}    {t}" for t in text[1:]]     # keeps the nesting of inline nodes
            elif q is None:
                out.append(f"{IND}- node {nid} = {p.kind}" + (f" {p.symbol}" if p.symbol else ""))
            else:
                changes = _field_changes(node_fields(p, single(p, x, self.ia)),
                                         node_fields(q, single(q, y, self.ib)))
                if changes:
                    out.append(f"{IND}~ node {nid}: {'; '.join(changes)}")
                self.meta_changes(f"{y.name}.{nid}", p.meta, q.meta)
            if p is not None and q is not None:
                pa, pb = x.place(nid), y.place(nid)
                if pa and pb and (pa.x, pa.y, pa.props) != (pb.x, pb.y, pb.props):
                    self.layout.append(f"{y.name}.{nid}: ({pa.x}, {pa.y}) -> ({pb.x}, {pb.y})"
                                       if (pa.x, pa.y) != (pb.x, pb.y) else
                                       f"{y.name}.{nid}: properties changed")
        ba, bb = {b.id: b for b in x.boxes}, {b.id: b for b in y.boxes}
        for bid in sorted(set(ba) | set(bb)):
            p, q = ba.get(bid), bb.get(bid)
            if p is None or q is None:
                self.layout.append(f"{y.name}: box {bid} {'added' if p is None else 'removed'}")
            elif (p.x, p.y, p.w, p.h, p.title, p.props) != (q.x, q.y, q.w, q.h, q.title, q.props):
                self.layout.append(f"{y.name}: box {bid} changed")
        return out

    def meta_changes(self, where: str, a: list, b: list):
        ta, tb = [meta_text(m) for m in a], [meta_text(m) for m in b]
        for t in ta:
            if t not in tb:
                self.meta.append(f"{where}: - {t}")
        for t in tb:
            if t not in ta:
                self.meta.append(f"{where}: + {t}")

    def report(self) -> str:
        out = []
        if self.semantic:
            out += self.semantic
        if self.meta:
            out += ["", "metadata (does not change behaviour):"] + [f"{IND}{m}" for m in self.meta]
        if self.layout:
            out += ["", "layout only:"] + [f"{IND}{m}" for m in self.layout]
        return "\n".join(out).lstrip("\n") + ("\n" if out else "")


def semantic_diff(a: Module, b: Module) -> str:
    return Differ(a, b).run()
