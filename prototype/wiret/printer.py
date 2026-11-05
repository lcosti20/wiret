"""Canonical writer and hashes (spec section 2.5)."""
from __future__ import annotations

import copy
import hashlib
import math
import unicodedata

from .model import (Attr, Binding, Box, Const, Enum, ExecOut, Extern, Graph, ITEM_ORDER, Lit,
                    META_ORDER, Module, Node, PinRef, SEMANTIC_ATTRS, Struct, Use, Var,
                    item_kind)
from .registry import ARRAY_MUTATORS, ModuleIndex, Sig, lit_equal, lit_fits, signature

IND = "  "

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
    if k in ("ident", "enum"):
        return v.value
    if k == "tuple":
        return "(" + ", ".join(fmt_lit(x) for x in v.value) + ")"
    if k == "list":
        return "[" + ", ".join(fmt_lit(x) for x in v.value) + "]"
    if k == "map":
        return "{" + ", ".join(f"{fmt_lit(a)}: {fmt_lit(b)}" for a, b in v.value) + "}"
    raise ValueError(k)


def fmt_args(a: Attr) -> str:
    if a.args is None:
        return ""
    return "(" + ", ".join((f"{k}: " if k else "") + fmt_lit(v) for k, v in a.args) + ")"


def fmt_attr(a: Attr) -> str:
    return f"@{a.name}{fmt_args(a)}"


def sorted_attrs(attrs: list) -> list:
    """Known semantic attributes alphabetically, then unknown ones (E0104) as written."""
    sem = sorted((a for a in attrs if a.name in SEMANTIC_ATTRS), key=lambda a: a.name)
    return sem + [a for a in attrs if a.name not in SEMANTIC_ATTRS]


def fmt_attrs(attrs: list) -> str:
    return "".join(" " + fmt_attr(a) for a in sorted_attrs(attrs))


def sorted_meta(meta: list) -> list:
    """`doc`, `category`, `keywords`, then notes, then anything else; stable within each."""
    order = {k: i for i, k in enumerate(META_ORDER)}
    return sorted(meta, key=lambda a: order.get(a.name, len(order)))


def fmt_meta(meta: list, indent: str, semantic=False) -> list:
    """The `#[...]` lines above a statement (section 2.4); none in the semantic text."""
    if semantic:
        return []
    return [f"{indent}#[{a.name}{fmt_args(a)}]" for a in sorted_meta(meta)]


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
            # never drop a binding that does not fit its pin: the checker reports it
            if d is not None and lit_fits(b.value, pin.type) and lit_equal(d, b.value):
                continue
        out.append(b)
    return sorted(out, key=lambda b: order.get(b.pin, len(order)))


def _ordered_execs(node: Node, sig: Sig) -> list:
    order = {p.name: i for i, p in enumerate(sig.exec_outs)}
    return sorted(node.execs, key=lambda e: order.get(e.pin, len(order)) if e.pin else -1)


def fmt_target(e: ExecOut) -> str:
    return e.target + (f".{e.target_pin}" if e.target_pin else "")


def fmt_wires(node: Node, sig: Sig) -> list:
    """The node's exec wires as `flow` lines (without indentation)."""
    execs = _ordered_execs(node, sig)
    single = len(sig.exec_outs) == 1 or (not sig.exec_outs and len(execs) == 1 and execs[0].pin is None)
    out = []
    for e in execs:
        if single and len(execs) == 1:
            src = node.id                                     # shorthand
        else:
            src = f"{node.id}.{e.pin or (sig.exec_outs[0].name if sig.exec_outs else 'then')}"
        out.append(f"{src} -> {fmt_target(e)}")
    return out


def fmt_targs(targs: list) -> str:
    return "::<" + ", ".join(targs) + ">" if targs else ""


def fmt_node(node: Node, sig: Sig, indent: str, semantic=False) -> str:
    """The node line, then one `.pin <- value` line per bound input."""
    head = f"{indent}node {node.id} = {node.kind}"
    targs = fmt_targs(node.targs)
    if node.kind in ARRAY_MUTATORS:      # `ArrayAdd::<i32> acc`, as in section 3.3
        head += targs + (f" {node.symbol}" if node.symbol else "")
    else:
        head += (f" {node.symbol}" if node.symbol else "") + targs
    lines = fmt_meta(node.meta, indent, semantic) + [head + fmt_attrs(node.attrs)]
    for b in _ordered_bindings(node, sig):
        val = (f"{b.value.node}.{b.value.pin}" if isinstance(b.value, PinRef)
               else fmt_lit(b.value))
        lines.append(f"{indent}{IND}.{b.pin} <- {val}")
    return "\n".join(lines)


# -- graphs and module -----------------------------------------------------------
def fmt_local(kw, l, indent, semantic=False) -> list:
    s = f"{indent}{kw} {l.name}: {l.type}"
    if l.default is not None:
        s += f" = {fmt_lit(l.default)}"
    return fmt_meta(l.meta, indent, semantic) + [s + fmt_attrs(l.attrs)]


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
        head += fmt_targs(g.tparams)
    head += fmt_params(g.params)
    if g.results is not None:
        head += " -> " + fmt_params(g.results)
    lines = fmt_meta(g.meta, indent, semantic) + [head + fmt_attrs(g.attrs) + " {"]
    inner = indent + IND
    for l in sorted(g.locals, key=lambda l: l.name):
        lines.extend(fmt_local("local", l, inner, semantic))
    for l in sorted(g.states, key=lambda l: l.name):
        lines.extend(fmt_local("state", l, inner, semantic))
    wires = []
    for n in sorted(g.nodes, key=lambda n: n.id):
        sig = signature(n, g, idx)
        wires.extend(fmt_wires(n, sig))
        lines.append(fmt_node(n, sig, inner, semantic))
    if wires:
        lines.extend(["", f"{inner}flow {{"])
        lines.extend(f"{inner}{IND}{w}" for w in wires)
        lines.append(f"{inner}}}")
    if not semantic and (g.places or g.boxes):
        lines.extend(["", f"{inner}layout {{"])
        for p in sorted(g.places, key=lambda p: p.id):
            lines.append(f"{inner}{IND}{p.id} at ({p.x}, {p.y}){fmt_props(p.props)}")
        for b in sorted(g.boxes, key=lambda b: b.id):
            lines.extend(fmt_meta(b.meta, inner + IND))
            lines.append(f"{inner}{IND}box {b.id} {fmt_string(b.title)} at ({b.x}, {b.y}) "
                         f"size ({b.w}, {b.h}){fmt_props(b.props)}")
        lines.append(f"{inner}}}")
    lines.append(indent + "}")
    return lines


def fmt_type_decl(it, semantic=False) -> list:
    """A struct or enum. Members keep the order written: field order and enum order are
    semantic (layout and implicit values), so the canonical form never sorts them."""
    if isinstance(it, Struct):
        head = f"struct {it.name}"
        members = []
        for f in it.fields:
            line = f"{IND}{f.name}: {f.type}"
            if f.default is not None:
                line += f" = {fmt_lit(f.default)}"
            members.append((f.meta, line + fmt_attrs(f.attrs)))
    else:
        head = f"enum {it.name}" + (f": {it.base}" if it.base else "")
        members = []
        for m in it.members:
            line = f"{IND}{m.name}" + (f" = {m.value}" if m.value is not None else "")
            members.append((m.meta, line + fmt_attrs(m.attrs)))
    head += fmt_attrs(it.attrs)
    if not members:
        return [head + " {}"]
    lines = [head + " {"]
    for meta, line in members:
        lines.extend(fmt_meta(meta, IND, semantic))
        lines.append(line)
    return lines + ["}"]


def fmt_item(it, idx: ModuleIndex, semantic=False) -> list:
    if isinstance(it, Graph):
        return fmt_graph(it, idx, "", semantic)
    if isinstance(it, (Struct, Enum)):
        return fmt_meta(it.meta, "", semantic) + fmt_type_decl(it, semantic)
    return fmt_meta(it.meta, "", semantic) + _fmt_decl(it)


def _fmt_decl(it) -> list:
    if isinstance(it, Use):
        return [f"use {it.name}" + (f" as {it.alias}" if it.alias else "") + fmt_attrs(it.attrs)]
    if isinstance(it, Extern):
        if it.kind == "type":
            return [f"extern type {it.name}{fmt_attrs(it.attrs)}"]
        s = f"extern func {it.name}{fmt_params(it.params)}"
        if it.results is not None:
            s += " -> " + fmt_params(it.results)
        return [s + fmt_attrs(it.attrs)]
    if isinstance(it, Const):
        return [f"const {it.name}: {it.type} = {fmt_lit(it.value)}{fmt_attrs(it.attrs)}"]
    if isinstance(it, Var):
        d = f" = {fmt_lit(it.default)}" if it.default is not None else ""
        return [f"var {it.name}: {it.type}{d}{fmt_attrs(it.attrs)}"]
    raise TypeError(it)


def print_module(m: Module, semantic=False) -> str:
    idx = ModuleIndex(m)
    lines = ([f"wiret {m.version}"] + fmt_meta(m.meta, "", semantic)
             + [f"module {m.name}{fmt_attrs(m.attrs)}"])
    items = sorted(m.items, key=lambda it: (ITEM_ORDER.index(item_kind(it)), it.name))
    prev_kind = None
    for it in items:
        k = item_kind(it)
        block = isinstance(it, (Graph, Struct, Enum))
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
