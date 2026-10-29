"""Canonical writer and hashes (spec section 2.5)."""
from __future__ import annotations

import copy
import hashlib
import math
import unicodedata

from .model import (Attr, Binding, Box, Const, ExecOut, Extern, Graph, ITEM_ORDER, Lit, Module,
                    Node, PinRef, Use, Var, item_kind)
from .registry import ARRAY_MUTATORS, ModuleIndex, Sig, lit_equal, signature

WRAP = 100
IND = "  "

SEMANTIC_ATTRS = {"id", "pure", "reads", "final", "private", "export", "inline", "deprecated",
                  "count", "cases", "disabled", "capability", "latent"}
DOC_ATTRS = {"doc", "category", "keywords"}
PLACE_PROP_ORDER = ["label", "color", "size", "collapsed", "hidden", "members"]


# -- values ----------------------------------------------------------------------
def fmt_string(s: str) -> str:
    out = ['"']
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append("\\u{%X}" % ord(ch))
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def fmt_float(x: float) -> str:
    if math.isinf(x) or math.isnan(x):
        raise ValueError("non-finite float literal")
    s = repr(float(x))
    if "e" in s:
        mant, exp = s.split("e")
        s = f"{mant}e{int(exp)}"
    return s


def fmt_lit(v: Lit) -> str:
    k = v.kind
    sfx = v.suffix or ""
    if k == "int":
        return f"{v.value}{sfx}"
    if k == "float":
        return f"{fmt_float(v.value)}{sfx}"
    if k == "bool":
        return "true" if v.value else "false"
    if k == "null":
        return "null"
    if k == "string":
        return fmt_string(v.value)
    if k == "ident":
        return v.value
    if k == "tuple":
        return "(" + ", ".join(fmt_lit(x) for x in v.value) + ")"
    if k == "list":
        return "[" + ", ".join(fmt_lit(x) for x in v.value) + "]"
    if k == "map":
        return "{" + ", ".join(f"{fmt_lit(a)}: {fmt_lit(b)}" for a, b in v.value) + "}"
    raise ValueError(k)


def fmt_attr(a: Attr) -> str:
    if a.args is None:
        return f"@{a.name}"
    args = ", ".join((f"{k}: " if k else "") + fmt_lit(v) for k, v in a.args)
    return f"@{a.name}({args})"


def sorted_attrs(attrs: list) -> list:
    sem = sorted((a for a in attrs if a.name in SEMANTIC_ATTRS), key=lambda a: a.name)
    doc = [a for a in attrs if a.name == "doc"]
    rest = [a for a in attrs if a.name not in SEMANTIC_ATTRS and a.name != "doc"]
    return sem + doc + rest


def fmt_attrs(attrs: list) -> str:
    return "".join(" " + fmt_attr(a) for a in sorted_attrs(attrs))


def fmt_params(ps: list) -> str:
    parts = []
    for p in ps:
        s = f"{p.name}: {p.type}"
        if p.default is not None:
            s += f" = {fmt_lit(p.default)}"
        s += fmt_attrs(p.attrs)
        parts.append(s)
    return "(" + ", ".join(parts) + ")"


# -- nodes -----------------------------------------------------------------------
def _ordered_bindings(node: Node, sig: Sig) -> list:
    if sig.error and not sig.inputs:
        return list(node.bindings)
    order = {p.name: i for i, p in enumerate(sig.inputs)}
    out = []
    for b in node.bindings:
        pin = sig.input(b.pin)
        if pin is not None and isinstance(b.value, Lit):
            d = pin.default_lit()
            if d is not None and lit_equal(d, b.value):
                continue
        out.append(b)
    return sorted(out, key=lambda b: order.get(b.pin, len(order)))


def _ordered_execs(node: Node, sig: Sig) -> list:
    order = {p.name: i for i, p in enumerate(sig.exec_outs)}
    return sorted(node.execs, key=lambda e: order.get(e.pin, len(order)) if e.pin else -1)


def fmt_target(e: ExecOut) -> str:
    return e.target + (f".{e.target_pin}" if e.target_pin else "")


def fmt_node(node: Node, sig: Sig, indent: str) -> str:
    head = f"{indent}node {node.id} = {node.kind}"
    targs = "<" + ", ".join(node.targs) + ">" if node.targs else ""
    if node.kind in ARRAY_MUTATORS:      # `ArrayAdd<i32> acc (item: x)`, as in section 3.3
        head += targs + (f" {node.symbol}" if node.symbol else "")
    else:
        head += (f" {node.symbol}" if node.symbol else "") + targs
    binds = [f"{b.pin}: " + (f"{b.value.node}.{b.value.pin}" if isinstance(b.value, PinRef)
                             else fmt_lit(b.value))
             for b in _ordered_bindings(node, sig)]
    sep = "" if (not node.symbol or node.kind in ("Call", "Macro")) else " "
    execs = _ordered_execs(node, sig)
    single = len(sig.exec_outs) == 1 or (not sig.exec_outs and len(execs) == 1 and execs[0].pin is None)
    if not execs:
        ex = []
    elif single and len(execs) == 1:
        ex = None  # shorthand
    else:
        ex = [f"{e.pin or (sig.exec_outs[0].name if sig.exec_outs else 'then')} -> {fmt_target(e)}"
              for e in execs]
    attrs = fmt_attrs(node.attrs)

    def build(wrap_b, wrap_e):
        s = head
        if binds:
            if wrap_b:
                s += sep + "(\n" + ",\n".join(indent + IND + b for b in binds) + "\n" + indent + ")"
            else:
                s += sep + "(" + ", ".join(binds) + ")"
        if ex is None:
            s += " -> " + fmt_target(execs[0])
        elif ex:
            if wrap_e:
                s += " {\n" + ",\n".join(indent + IND + e for e in ex) + "\n" + indent + "}"
            else:
                s += " { " + ", ".join(ex) + " }"
        return s + attrs

    line = build(False, False)
    if len(line) <= WRAP:
        return line
    line = build(True, False)
    if max(len(l) for l in line.split("\n")) <= WRAP or not ex or len(ex) < 2:
        return line
    return build(True, True)


# -- graphs and module -----------------------------------------------------------
def fmt_local(kw, l, indent) -> str:
    s = f"{indent}{kw} {l.name}: {l.type}"
    if l.default is not None:
        s += f" = {fmt_lit(l.default)}"
    return s + fmt_attrs(l.attrs)


def fmt_props(props: list, sort_members=True) -> str:
    if not props:
        return ""
    order = {k: i for i, k in enumerate(PLACE_PROP_ORDER)}
    ps = sorted(props, key=lambda kv: order.get(kv[0], len(order)))
    parts = []
    for k, v in ps:
        if k == "members" and v.kind == "list" and sort_members:
            v = Lit("list", sorted(v.value, key=lambda x: str(x.value)))
        parts.append(f"{k} = {fmt_lit(v)}")
    return " [" + ", ".join(parts) + "]"


def fmt_graph(g: Graph, idx: ModuleIndex, indent: str = "", semantic=False) -> list:
    head = f"{indent}{g.kind} {g.name}"
    if g.tparams:
        head += "<" + ", ".join(g.tparams) + ">"
    head += fmt_params(g.params)
    if g.results is not None:
        head += " -> " + fmt_params(g.results)
    attrs = [a for a in g.attrs if not (semantic and a.name in DOC_ATTRS)]
    lines = [head + fmt_attrs(attrs) + " {"]
    inner = indent + IND
    for l in sorted(g.locals, key=lambda l: l.name):
        lines.append(fmt_local("local", l, inner))
    for l in sorted(g.states, key=lambda l: l.name):
        lines.append(fmt_local("state", l, inner))
    for n in sorted(g.nodes, key=lambda n: n.id):
        if semantic:
            n = copy.copy(n)
            n.attrs = [a for a in n.attrs if a.name not in DOC_ATTRS]
        lines.append(fmt_node(n, signature(n, g, idx), inner))
    if not semantic and g.notes:
        lines.append(f"{inner}notes {{")
        for nt in sorted(g.notes, key=lambda n: n.id):
            on = f" on {nt.on}" if nt.on else ""
            lines.append(f"{inner}{IND}note {nt.id}{on} {fmt_string(nt.text)}{fmt_attrs(nt.attrs)}")
        lines.append(f"{inner}}}")
    if not semantic and (g.places or g.boxes):
        lines.append(f"{inner}layout {{")
        for p in sorted(g.places, key=lambda p: p.id):
            lines.append(f"{inner}{IND}{p.id} at ({p.x}, {p.y}){fmt_props(p.props)}")
        for b in sorted(g.boxes, key=lambda b: b.id):
            lines.append(f"{inner}{IND}box {b.id} {fmt_string(b.title)} at ({b.x}, {b.y}) "
                         f"size ({b.w}, {b.h}){fmt_props(b.props)}")
        lines.append(f"{inner}}}")
    lines.append(indent + "}")
    return lines


def fmt_item(it, idx: ModuleIndex, semantic=False) -> list:
    if isinstance(it, Use):
        return [f"use {it.name}" + (f" as {it.alias}" if it.alias else "") + fmt_attrs(it.attrs)]
    if isinstance(it, Extern):
        if it.kind == "type":
            return [f"extern type {it.name}{fmt_attrs(it.attrs)}"]
        s = f"extern func {it.name}{fmt_params(it.params)}"
        if it.results is not None:
            s += " -> " + fmt_params(it.results)
        return [s + fmt_attrs([a for a in it.attrs if not (semantic and a.name in DOC_ATTRS)])]
    if isinstance(it, Const):
        return [f"const {it.name}: {it.type} = {fmt_lit(it.value)}{fmt_attrs(it.attrs)}"]
    if isinstance(it, Var):
        d = f" = {fmt_lit(it.default)}" if it.default is not None else ""
        return [f"var {it.name}: {it.type}{d}{fmt_attrs(it.attrs)}"]
    if isinstance(it, Graph):
        return fmt_graph(it, idx, "", semantic)
    raise TypeError(it)


def print_module(m: Module, semantic=False) -> str:
    idx = ModuleIndex(m)
    lines = [f"wiret {m.version}", f"module {m.name}{fmt_attrs(m.attrs)}"]
    items = sorted(m.items, key=lambda it: (ITEM_ORDER.index(item_kind(it)), it.name))
    prev_kind = None
    for it in items:
        k = item_kind(it)
        block = isinstance(it, Graph)
        if block or k != prev_kind:
            lines.append("")
        lines.extend(fmt_item(it, idx, semantic))
        prev_kind = k if not block else None
    text = "\n".join(lines) + "\n"
    return unicodedata.normalize("NFC", text)


# -- hashes ----------------------------------------------------------------------
def strip_reroutes(m: Module) -> Module:
    """Bypass and remove Reroute nodes (they are visual only)."""
    m = copy.deepcopy(m)
    for g in m.graphs():
        rr = {n.id: n for n in g.nodes if n.kind == "Reroute"}
        if not rr:
            continue

        def data_src(ref: PinRef, depth=0):
            n = rr.get(ref.node)
            if n is None or depth > 64:
                return ref
            b = n.binding("in")
            if b is None or not isinstance(b.value, PinRef):
                return b.value if b else ref
            return data_src(b.value, depth + 1)

        def exec_tgt(e: ExecOut, depth=0):
            n = rr.get(e.target)
            if n is None or depth > 64:
                return e
            if not n.execs:
                return None
            nxt = n.execs[0]
            return exec_tgt(ExecOut(e.pin, nxt.target, nxt.target_pin), depth + 1)

        for n in g.nodes:
            if n.id in rr:
                continue
            n.bindings = [Binding(b.pin, data_src(b.value)) if isinstance(b.value, PinRef) else b
                          for b in n.bindings]
            n.execs = [x for x in (exec_tgt(e) for e in n.execs) if x is not None]
        g.nodes = [n for n in g.nodes if n.id not in rr]
    return m


def semantic_text(m: Module) -> str:
    return print_module(strip_reroutes(m), semantic=True)


def semantic_hash(m: Module) -> str:
    return hashlib.sha256(semantic_text(m).encode()).hexdigest()


def layout_hash(m: Module) -> str:
    return hashlib.sha256(print_module(m).encode()).hexdigest()
