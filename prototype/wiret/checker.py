"""Resolver, type checker and graph validator (spec sections 4.3 and 4.7)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Optional

from .model import Graph, Lit, Module, Node, PinRef
from .model import Var
from .registry import (ARRAY_MUTATORS, ModuleIndex, Sig, instantiate, lit_fits, signature,
                       substitute, type_ok)


@dataclass
class Diag:
    code: str
    message: str
    module: str = ""
    graph: Optional[str] = None
    node: Optional[str] = None
    pin: Optional[str] = None
    data: Optional[dict] = None   # structured details (types, names) for friendly messages

    @property
    def severity(self) -> str:
        return "error" if self.code.startswith("E") else "warning"

    @property
    def top_node(self) -> Optional[str]:
        """The node id in the source graph (path-style ids map to their macro call node)."""
        if not self.node:
            return None
        return self.node.split("/")[0].split("!")[0]

    def to_json(self) -> str:
        d = asdict(self)
        d["severity"] = self.severity
        return json.dumps(d)

    def __str__(self):
        where = ".".join(x for x in (self.graph, self.node) if x)
        if self.pin:
            where += f".{self.pin}"
        return f"{self.severity} {self.code}: {where + ': ' if where else ''}{self.message}"


def has_errors(diags) -> bool:
    return any(d.severity == "error" for d in diags)


def exec_target_pin(target_node: Node, pin: Optional[str]) -> str:
    return pin or "in"


class GraphInfo:
    """Resolved signatures and exec edges of one graph; shared by checker and editor."""

    def __init__(self, g: Graph, idx: ModuleIndex):
        self.g = g
        self.nodes = {}
        for n in g.nodes:
            self.nodes.setdefault(n.id, n)
        self.sigs: dict[str, Sig] = {nid: signature(n, g, idx) for nid, n in self.nodes.items()}

    def exec_pin(self, node: Node, e) -> Optional[str]:
        if e.pin is not None:
            return e.pin
        outs = self.sigs[node.id].exec_outs
        return outs[0].name if outs else None

    def successors(self, nid: str) -> list:
        n = self.nodes.get(nid)
        if n is None:
            return []
        return [e.target for e in n.execs if e.target in self.nodes]

    def entry(self) -> Optional[str]:
        for nid, n in self.nodes.items():
            if n.kind == "Entry":
                return nid
        return None


def check(module: Module, comments_ok=False) -> list:
    diags: list[Diag] = []
    idx = ModuleIndex(module)
    mod = module.name

    def D(code, msg, graph=None, node=None, pin=None, **data):
        diags.append(Diag(code, msg, mod, graph, node, pin, data or None))

    seen = {}
    for it in module.items:
        name = getattr(it, "name", None)
        if name in seen:
            D("E0102", f"duplicate declaration '{name}'")
        seen[name] = it
    for it in module.items:
        tparams = set(getattr(it, "tparams", []) or [])
        typed = list(getattr(it, "params", []) or []) + list(getattr(it, "results", []) or [])
        typed += list(getattr(it, "locals", []) or []) + list(getattr(it, "states", []) or [])
        if isinstance(it, Var):
            typed.append(it)
        for p in typed:
            ty = substitute(p.type, {t: "i32" for t in tparams})
            if ty != "exec" and not type_ok(ty):
                D("E0501", f"type '{p.type}' is not supported by this prototype",
                  getattr(it, "name", None))
    if module.comments and not comments_ok:
        for c in module.comments:
            D("W0603", f"line {c.line}: '//' comment is not part of the model and would be dropped; "
                       f"convert it to a note")

    for g in module.graphs():
        if g.tparams:   # check a generic macro through one instance of it
            check_graph(instantiate(g, ["i32"] * len(g.tparams)), idx, D)
        else:
            check_graph(g, idx, D)
    check_macro_recursion(module, idx, D)
    return diags


def check_macro_recursion(module, idx, D):
    def uses(g):
        return {n.symbol for n in g.nodes if n.kind == "Macro" and n.symbol in idx.macros}

    for name in idx.macros:
        stack, seen = [(name, [name])], set()
        while stack:
            cur, path = stack.pop()
            for nxt in uses(idx.macros[cur]):
                if nxt == name:
                    D("E0401", f"macro expands itself: {' -> '.join(path + [nxt])}", name)
                    stack = []
                    break
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append((nxt, path + [nxt]))


def check_graph(g: Graph, idx: ModuleIndex, D):
    G = g.name
    info = GraphInfo(g, idx)
    nodes, sigs = info.nodes, info.sigs

    ids = set()
    for n in g.nodes:
        if n.id in ids:
            D("E0102", f"duplicate node id '{n.id}'", G, n.id)
        ids.add(n.id)
    for b in g.boxes:
        if b.id in ids:
            D("E0102", f"box id '{b.id}' collides with another id", G, b.id)
        ids.add(b.id)

    entries = [n for n in g.nodes if n.kind == "Entry"]
    if not entries:
        D("E0101", "graph has no Entry node", G)
    for extra in entries[1:]:
        D("E0102", "a graph has exactly one Entry node", G, extra.id)

    pure_attr = g.has_attr("pure")
    reads_attr = g.has_attr("reads")

    for n in g.nodes:
        sig = sigs[n.id]
        if sig.error:
            D(sig.error[0], sig.error[1], G, n.id)
        # data bindings
        bound = set()
        for b in n.bindings:
            pin = sig.input(b.pin)
            if b.pin in bound:
                D("E0111", f"input '{b.pin}' is bound twice", G, n.id, b.pin)
            bound.add(b.pin)
            if pin is None:
                if not sig.error:
                    D("E0103", f"{n.kind} has no input pin '{b.pin}'", G, n.id, b.pin)
                continue
            if pin.is_exec:
                D("E0120", f"'{b.pin}' is an exec input; wire it from an exec output", G, n.id, b.pin)
                continue
            if isinstance(b.value, PinRef):
                src = nodes.get(b.value.node)
                if src is None:
                    D("E0101", f"unknown node '{b.value.node}'", G, n.id, b.pin)
                    continue
                spin = sigs[src.id].output(b.value.pin)
                if spin is None:
                    if not sigs[src.id].error:
                        D("E0103", f"{src.kind} '{src.id}' has no output pin '{b.value.pin}'",
                          G, n.id, b.pin)
                    continue
                if spin.is_exec:
                    D("E0120", f"'{src.id}.{spin.name}' is an exec output", G, n.id, b.pin)
                elif spin.type != pin.type:
                    D("E0110", f"wire type mismatch: {spin.type} -> {pin.type}; insert "
                               f"Convert<{spin.type}, {pin.type}>", G, n.id, b.pin,
                      src=spin.type, dst=pin.type)
            else:
                if not lit_fits(b.value, pin.type):
                    D("E0110", f"literal does not fit pin type {pin.type}", G, n.id, b.pin,
                      dst=pin.type, literal=True)
        if not sig.error and n.kind != "Exit":
            for p in sig.data_ins:
                if p.name not in bound and p.default is None:
                    D("W0201", f"input '{p.name}' is unbound and has no default", G, n.id, p.name,
                      type=p.type)
        # exec outputs
        listed = set()
        for e in n.execs:
            pname = info.exec_pin(n, e)
            if pname is None:
                D("E0103", f"{n.kind} has no exec output", G, n.id)
                continue
            if pname in listed:
                D("E0121", f"exec output '{pname}' is listed twice", G, n.id, pname)
            listed.add(pname)
            out = sig.output(pname)
            if out is None and not sig.error:
                D("E0103", f"{n.kind} has no exec output '{pname}'", G, n.id, pname)
            elif out is not None and not out.is_exec:
                D("E0120", f"'{pname}' is a data output, not an exec output", G, n.id, pname)
            tgt = nodes.get(e.target)
            if tgt is None:
                D("E0101", f"exec target names unknown node '{e.target}'", G, n.id, pname)
                continue
            tpin_name = exec_target_pin(tgt, e.target_pin)
            tpin = sigs[tgt.id].input(tpin_name)
            if tpin is None:
                if not sigs[tgt.id].error:
                    D("E0103", f"{tgt.kind} '{tgt.id}' has no exec input '{tpin_name}'",
                      G, n.id, pname)
            elif not tpin.is_exec:
                D("E0120", f"'{tgt.id}.{tpin_name}' is a data input", G, n.id, pname)
        # purity
        if pure_attr or reads_attr:
            attr = "@pure" if pure_attr else "@reads"
            if n.kind in ARRAY_MUTATORS and n.symbol in idx.vars and not g.local(n.symbol):
                D("E0302", f"{attr} function changes the module variable '{n.symbol}'", G, n.id)
            if n.kind in ("SetVar", "SetState"):
                D("E0302", f"{attr} function writes {'a variable' if n.kind == 'SetVar' else 'state'}",
                  G, n.id)
            if pure_attr and n.kind == "GetState":
                D("E0304", "@pure function reads state", G, n.id)
            if pure_attr and n.kind == "GetVar" and n.symbol not in idx.consts:
                D("E0304", "@pure function reads a module variable", G, n.id)
            if n.kind == "Call" and not sig.error:
                if pure_attr and sig.purity != "pure":
                    D("E0304", f"@pure function calls '{n.symbol}', which is not @pure", G, n.id)
                elif reads_attr and sig.purity == "impure":
                    D("E0302", f"@reads function calls '{n.symbol}', which is neither @reads nor "
                               f"@pure", G, n.id)
            if n.kind == "Macro" and n.symbol in idx.macros and idx.macros[n.symbol].states:
                D("E0302", f"{attr} function expands macro '{n.symbol}', which keeps state", G, n.id)

    check_pure_cycles(info, G, D)
    check_flow(info, G, D)
    check_layout(g, ids, G, D)


def pure_deps(info: GraphInfo, nid: str) -> list:
    n = info.nodes[nid]
    return [b.value.node for b in n.bindings
            if isinstance(b.value, PinRef) and b.value.node in info.nodes]


def check_pure_cycles(info: GraphInfo, G, D):
    WHITE, GREY, BLACK = 0, 1, 2
    color = {}
    reported = set()

    def visit(nid, path):
        color[nid] = GREY
        for d in pure_deps(info, nid):
            if not info.sigs[d].pure:
                continue
            c = color.get(d, WHITE)
            if c == GREY:
                cyc = path[path.index(d):] if d in path else [d]
                key = frozenset(cyc)
                if key not in reported:
                    reported.add(key)
                    D("E0301", f"cycle among pure nodes: {' -> '.join(cyc + [d])}", G, d)
            elif c == WHITE:
                visit(d, path + [d])
        color[nid] = BLACK

    for nid, sig in info.sigs.items():
        if sig.pure and color.get(nid, WHITE) == WHITE:
            visit(nid, [nid])


def impure_sources(info: GraphInfo, nid: str, seen=None) -> list:
    """(producer, pin, consumer pin) for impure outputs read at nid's evaluation point."""
    seen = set() if seen is None else seen
    out = []
    n = info.nodes[nid]
    for b in n.bindings:
        if not isinstance(b.value, PinRef) or b.value.node not in info.nodes:
            continue
        src = b.value.node
        if info.sigs[src].pure:
            if src not in seen:
                seen.add(src)
                out += [(p, pin, b.pin) for p, pin, _ in impure_sources(info, src, seen)]
        else:
            out.append((src, b.value.pin, b.pin))
    return out


def check_flow(info: GraphInfo, G, D):
    entry = info.entry()
    if entry is None:
        return
    impure = [nid for nid, s in info.sigs.items() if not s.pure]
    succ = {nid: info.successors(nid) for nid in impure}
    reach, todo = {entry}, [entry]
    while todo:
        cur = todo.pop()
        for s in succ.get(cur, []):
            if s not in reach:
                reach.add(s)
                todo.append(s)
    for nid in sorted(impure):
        if nid not in reach and info.nodes[nid].kind != "Entry":
            D("W0301", "node is unreachable from Entry", G, nid)

    # dominators over the exec graph (reachable impure nodes)
    order = [nid for nid in sorted(reach)]
    preds = {nid: [] for nid in order}
    for nid in order:
        for s in succ.get(nid, []):
            if s in preds:
                preds[s].append(nid)
    dom = {nid: set(order) for nid in order}
    dom[entry] = {entry}
    changed = True
    while changed:
        changed = False
        for nid in order:
            if nid == entry:
                continue
            ps = [dom[p] for p in preds[nid]]
            new = (set.intersection(*ps) if ps else set()) | {nid}
            if new != dom[nid]:
                dom[nid] = new
                changed = True

    readers = {}
    for nid in order:
        for prod, pin, cpin in impure_sources(info, nid):
            kind = info.nodes[prod].kind
            if kind == "Entry":
                continue
            if prod not in dom[nid] or prod == nid:
                D("W0310", f"reads '{prod}.{pin}', but '{prod}' does not run on every path to "
                           f"this node (zero value if it has not run)", G, nid, cpin)

    # W0320: a node reading mutable state feeds several impure consumers
    for rid, sig in info.sigs.items():
        if sig.purity != "reads":
            continue
        consumers = set()
        for nid in impure:
            if rid in _pure_closure(info, nid):
                consumers.add(nid)
        if len(consumers) > 1:
            D("W0320", f"'{rid}' reads mutable state and feeds {len(consumers)} impure nodes "
                       f"({', '.join(sorted(consumers))}); they may see different values", G, rid)


def _pure_closure(info: GraphInfo, nid: str) -> set:
    out, todo = set(), list(pure_deps(info, nid))
    while todo:
        d = todo.pop()
        if d in out or not info.sigs[d].pure:
            continue
        out.add(d)
        todo += pure_deps(info, d)
    return out


def check_layout(g: Graph, ids: set, G, D):
    owner = {}
    for b in sorted(g.boxes, key=lambda b: b.id):
        for m in b.members():
            if m not in ids:
                D("W0601", f"box '{b.id}' lists '{m}', which names no node or box", G, b.id)
            elif m in owner:
                D("W0602", f"'{m}' is a member of both '{owner[m]}' and '{b.id}'", G, b.id)
            else:
                owner[m] = b.id
    for nt in g.notes:
        if nt.on and nt.on not in ids:
            D("W0604", f"note '{nt.id}' is attached to '{nt.on}', which no longer exists", G)
