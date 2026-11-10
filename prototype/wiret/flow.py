"""`wiretc view --flow`: a reading view of a module in flow order (spec section 7)."""
from __future__ import annotations

from .checker import GraphInfo
from .model import Graph, Module, PinRef
from .printer import IND, fmt_graph, print_module
from .registry import ModuleIndex


def flow_order(g: Graph, info: GraphInfo) -> list:
    """Depth-first from Entry along exec outputs in pin order; each pure node immediately
    before its first consumer; unreachable nodes last, sorted by id."""
    out, seen = [], set()

    def emit_pure(nid):
        for b in info.nodes[nid].bindings:
            if isinstance(b.value, PinRef):
                d = b.value.node
                if d in info.nodes and d not in seen and info.sigs[d].pure:
                    seen.add(d)
                    emit_pure(d)
                    out.append(d)

    def visit(nid):
        if nid in seen or nid not in info.nodes:
            return
        seen.add(nid)
        emit_pure(nid)
        out.append(nid)
        n = info.nodes[nid]
        sig = info.sigs[nid]
        order = {p.name: i for i, p in enumerate(sig.exec_outs)}
        for e in sorted(n.execs, key=lambda e: order.get(info.exec_pin(n, e), 99)):
            visit(e.target)

    entry = info.entry()
    if entry:
        visit(entry)
    out += sorted(nid for nid in info.nodes if nid not in seen)
    return out


def view_flow(m: Module) -> str:
    """The canonical text with every graph's node statements and `flow` wires in flow order."""
    idx = ModuleIndex(m)
    canonical = print_module(m)
    out = []
    for g in m.graphs():
        info = GraphInfo(g, idx)
        outer = IND if g.owner else ""      # a method is printed inside its class
        before = "\n".join(fmt_graph(g, idx, outer))
        out.append((before, "\n".join(fmt_graph(g, idx, outer, order=flow_order(g, info)))))
    for before, after in out:
        canonical = canonical.replace(before, after, 1)
    return canonical
