"""Canonical writer and hashes (spec section 2.5)."""
from __future__ import annotations

import copy
import hashlib
import math
import re
import unicodedata

from .model import (Attr, Binding, Box, Class, Const, Enum, Interface, ExecOut, Extern, Graph, ITEM_ORDER, Lit,
                    META_ORDER, Module, Node, PinRef, SEMANTIC_ATTRS, Struct, Use, Var,
                    item_kind, strip_comments)
from .registry import (PLACE_MUTATORS, ModuleIndex, Sig, field_place, lit_equal, lit_fits,
                       signature)

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
    if k == "enum":                     # "Mode.Chase" in the model
        return v.value.replace(".", "::", 1)
    if k == "ident":
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


def fmt_comment(lines: list, indent: str) -> list:
    """The `//` lines attached to an element, directly above it (section 2.1)."""
    return [f"{indent}//" + (f" {c}" if c else "") for c in lines]


def above(x, indent: str, semantic=False) -> list:
    """What stands directly above a declaration: its `//` lines, then its `#[...]` lines."""
    return fmt_comment(getattr(x, "comment", []), indent) + fmt_meta(x.meta, indent, semantic)


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
            if d is not None and lit_fits(b.value, pin.type) and lit_equal(d, b.value) \
                    and not b.comment:
                continue
        out.append(b)
    return sorted(out, key=lambda b: order.get(b.pin, len(order)))


def _ordered_execs(node: Node, sig: Sig) -> list:
    order = {p.name: i for i, p in enumerate(sig.exec_outs)}
    return sorted(node.execs, key=lambda e: order.get(e.pin, len(order)) if e.pin else -1)


def fmt_target(e: ExecOut, names: "GraphNames" = None) -> str:
    return (names.name(e.target) if names else e.target) + (f".{e.target_pin}" if e.target_pin else "")


def fmt_wires(node: Node, sig: Sig, names: "GraphNames" = None) -> list:
    """The node's exec wires as `flow` lines (without indentation), each after its `//` lines."""
    execs = _ordered_execs(node, sig)
    single = len(sig.exec_outs) == 1 or (not sig.exec_outs and len(execs) == 1 and execs[0].pin is None)
    nid = names.name(node.id) if names else node.id
    out = []
    for e in execs:
        if single and len(execs) == 1:
            src = nid                                         # shorthand
        else:
            src = f"{nid}.{e.pin or (sig.exec_outs[0].name if sig.exec_outs else 'then')}"
        out.extend(fmt_comment(e.comment, ""))
        out.append(f"{src} -> {fmt_target(e, names)}")
    return out


def fmt_targs(targs: list) -> str:
    return "::<" + ", ".join(targs) + ">" if targs else ""


def qualified_symbol(node: Node, g: Graph, idx: ModuleIndex) -> str:
    """The symbol as the canonical form writes it. Inside a method the reader also accepts a
    member of the method's class by its bare name (`GetField health`, `Broadcast OnDied`,
    `ArrayAdd::<i32> items`); it is written `Player.health` everywhere, so a node reads the
    same in a method and in a free function (section 2.3, rule 3)."""
    sym = node.symbol
    if not sym or "." in sym or g is None or not g.owner or g.owner not in idx.classes:
        return sym
    k = node.kind
    if k in ("GetField", "SetField", "Bind", "Unbind", "Broadcast") or \
            (k in PLACE_MUTATORS and field_place(sym, g, idx) is not None):
        return f"{g.owner}.{sym}"
    return sym


def fmt_head(node: Node, names: "GraphNames" = None) -> str:
    """`Kind symbol::<targs>`, or `ArrayAdd::<i32> acc` for a place mutator (section 3.3)."""
    targs = fmt_targs(node.targs)
    sym = names.symbol(node) if names is not None else node.symbol
    if node.kind == "Format" and sym is not None:       # its template is a string
        sym = fmt_string(sym)
    if node.kind in PLACE_MUTATORS:
        return node.kind + targs + (f" {sym}" if sym else "")
    return node.kind + (f" {sym}" if sym else "") + targs


_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")


class GraphNames:
    """How a graph's nodes are written (section 2.3): which nodes are written inline, inside
    the one input they feed, and the name each node is written with.

    A node is written inline when it has no exec pins, carries no semantic attribute or
    `//` comment, and exactly one input in the graph reads it. Its name is then its consumer's name, a dot and
    the input's name (`show.message`). Every other node is declared with a `node` statement
    under its id; an id that is not an identifier (a node that was inline and now feeds
    several inputs) is declared with its dots turned into underscores, followed by `_2`,
    `_3`, ... when that name is the id of another node or retired in the project."""

    def __init__(self, g: Graph, idx: ModuleIndex, sigs: dict = None):
        self.g, self.idx = g, idx
        self.bare = None            # in an expression body: Entry, whose outputs are bare
        self.current = None         # the node whose inputs are being written
        self.sigs = sigs if sigs is not None else {n.id: signature(n, g, idx) for n in g.nodes}
        nodes = {}
        for n in g.nodes:
            nodes.setdefault(n.id, n)
        refs = {}                   # node id -> [(consumer id, pin)]
        for n in g.nodes:
            for b in n.bindings:
                if isinstance(b.value, PinRef) and b.value.node in nodes:
                    refs.setdefault(b.value.node, []).append((n.id, b.pin))
        targets = {e.target for n in g.nodes for e in n.execs}
        ids = [n.id for n in g.nodes]
        self.parent = {}            # inline node id -> (consumer id, pin)
        for n in g.nodes:
            sig = self.sigs.get(n.id)
            r = refs.get(n.id, [])
            if (sig is not None and len(r) == 1 and r[0][0] != n.id and ids.count(n.id) == 1
                    and ids.count(r[0][0]) == 1 and not n.attrs and not n.execs
                    and not n.comment
                    and n.id not in targets and not sig.error and not sig.exec_ins
                    and not sig.exec_outs and n.kind not in ("Entry", "Return", "Exit", "Leave")
                    and sum(1 for b in nodes[r[0][0]].bindings if b.pin == r[0][1]) == 1):
                self.parent[n.id] = r[0]
        # a ring of nodes that each feed the next has no node to write it under (E0301)
        for nid in list(self.parent):
            seen, cur = [], nid
            while cur in self.parent and cur not in seen:
                seen.append(cur)
                cur = self.parent[cur][0]
            if cur in seen:
                for x in seen[seen.index(cur):]:
                    self.parent.pop(x, None)
        self.children = {}          # consumer id -> {pin: inline node}
        for nid, (c, pin) in self.parent.items():
            self.children.setdefault(c, {})[pin] = nodes[nid]
        self.names = {}
        taken = {i for i in ids if _IDENT_RE.match(i)}
        module = getattr(idx, "module", None)
        taken |= {i for gn, i in getattr(module, "retired_nodes", ()) if gn == g.name}
        for nid in sorted(set(ids)):
            if nid in self.parent:
                continue
            if _IDENT_RE.match(nid):
                self.names[nid] = nid
                continue
            base = re.sub(r"[^A-Za-z0-9_]", "_", nid)
            base = base if _IDENT_RE.match(base) else "n_" + base
            name, k = base, 2
            while name in taken:
                name, k = f"{base}_{k}", k + 1
            taken.add(name)
            self.names[nid] = name

        def name(nid):
            if nid not in self.names:
                c, pin = self.parent[nid]
                self.names[nid] = f"{name(c)}.{pin}"
            return self.names[nid]

        for nid in self.parent:
            name(nid)

    def name(self, nid: str) -> str:
        return self.names.get(nid, nid)

    def symbol(self, node: Node) -> str:
        return qualified_symbol(node, self.g, self.idx)

    def inline(self, nid: str) -> bool:
        return nid in self.parent

    def declared(self, nodes: list) -> list:
        """The nodes written as `node` statements, sorted by the name they are written with."""
        return sorted((n for n in nodes if n.id not in self.parent), key=lambda n: self.name(n.id))


def implied_output(ref: PinRef, names: GraphNames) -> bool:
    """Whether a wire from a declared node is written with its id alone (section 2.3): the
    node has one data output and is not an Entry or a macro, whose outputs are named
    parameters and results."""
    sig = names.sigs.get(ref.node)
    if sig is None or sig.error or not _IDENT_RE.match(names.name(ref.node)):
        return False
    n = names.g.node(ref.node)
    outs = sig.data_outs
    return (n is not None and n.kind not in ("Entry", "Macro") and len(outs) == 1
            and outs[0].name == ref.pin)


def fmt_value(b: Binding, names: GraphNames = None) -> str:
    if isinstance(b.value, PinRef) and names is not None and b.value.node == names.bare:
        return b.value.pin
    if isinstance(b.value, PinRef) and not b.value.pin:      # a node that does not exist
        return names.name(b.value.node) if names else b.value.node
    if isinstance(b.value, PinRef) and names is not None and implied_output(b.value, names):
        return names.name(b.value.node)
    if isinstance(b.value, PinRef):
        return f"{names.name(b.value.node) if names else b.value.node}.{b.value.pin}"
    return fmt_lit(b.value)


def fmt_input(b: Binding, indent: str, names: GraphNames = None) -> str:
    """The value of a binding. An inline node is written in place, followed by the pin it is
    read from, `Call F(...).x`, unless that is its one data output: `Call F(...)`."""
    kids = names.children.get(names.current, {}) if names is not None else {}
    kid = kids.get(b.pin)
    if kid is None or not isinstance(b.value, PinRef) or b.value.node != kid.id:
        return fmt_value(b, names)
    sig = names.sigs[kid.id]
    text = fmt_expr(kid, sig, indent, names)
    outs = sig.data_outs
    if not sig.error and len(outs) == 1 and outs[0].name == b.value.pin:
        return text
    return f"{text}.{b.value.pin}"


def fmt_expr(node: Node, sig: Sig, indent: str, names: GraphNames = None) -> str:
    """`Kind symbol::<targs>(`, one `.pin <- value,` line per bound input (after its `//`
    lines) and `)`, or `Kind()` when no input is bound. An inline node is written in place of
    the value it feeds (`fmt_input`)."""
    bindings = _ordered_bindings(node, sig)
    if not bindings:
        return fmt_head(node, names) + "()"
    lines = [fmt_head(node, names) + "("]
    for b in bindings:
        if names is not None:
            names.current = node.id
        val = fmt_input(b, indent + IND, names)
        lines.extend(fmt_comment(b.comment, indent + IND))
        lines.append(f"{indent}{IND}.{b.pin} <- {val},")
    lines.append(f"{indent})")
    return "\n".join(lines)


def fmt_node(node: Node, sig: Sig, indent: str, semantic=False, names: GraphNames = None) -> str:
    """The node statement `node id = Kind(...) @attrs`, with its inputs one per line and its
    inline nodes written in place (section 2.3). Its metadata lines are in the layout block."""
    nid = names.name(node.id) if names else node.id
    return "\n".join(fmt_comment(node.comment, indent) + [
        f"{indent}node {nid} = {fmt_expr(node, sig, indent, names)}{fmt_attrs(node.attrs)}"])


# -- graphs and module -----------------------------------------------------------
def fmt_local(kw, l, indent, semantic=False) -> list:
    s = f"{indent}{kw} {l.name}: {l.type}"
    if l.default is not None:
        s += f" = {fmt_lit(l.default)}"
    return above(l, indent, semantic) + [s + fmt_attrs(l.attrs)]


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


def expr_value(g: Graph, names: GraphNames):
    """The binding a function is written `= value` with (section 2.3), or None. That is a
    function outside a class with one result whose graph is `entry`, wired to `ret`, and the
    nodes written inline in `ret`'s one input, with nothing else to keep: no locals, no
    attributes, comments or metadata on the two nodes, and no layout."""
    if g.kind != "func" or g.owner or g.results is None or len(g.results) != 1 or g.locals \
            or g.states or g.places or g.boxes or g.orphan_meta \
            or any(n.meta for n in g.nodes):
        return None
    entry, ret = g.node("entry"), g.node("ret")
    if entry is None or ret is None or entry.kind != "Entry" or ret.kind != "Return" \
            or [n.id for n in names.declared(g.nodes)] != ["entry", "ret"]:
        return None
    if entry.bindings or entry.attrs or entry.comment or ret.attrs or ret.comment or ret.execs:
        return None
    if len(entry.execs) != 1:
        return None
    e = entry.execs[0]
    if e.target != "ret" or e.target_pin or e.comment or e.pin not in (None, "then"):
        return None
    if len(ret.bindings) != 1 or ret.bindings[0].pin != g.results[0].name \
            or ret.bindings[0].comment:
        return None
    return ret.bindings[0]


def fmt_graph(g: Graph, idx: ModuleIndex, indent: str = "", semantic=False,
              order: list = None) -> list:
    """A graph: its locals and states, its `flow` block, its node statements and its layout
    block (section 2.5, rule 3). `order` (node ids) lists the node statements and wires in
    that order instead of by name, for `wiretc view --flow`."""
    head = f"{indent}{g.kind} {g.short_name}"
    if g.tparams:
        head += fmt_targs(g.tparams)
    head += fmt_params(g.params)
    if g.results is not None:
        head += " -> " + fmt_params(g.results)
    head = above(g, indent, semantic) + [head + fmt_attrs(g.attrs)]
    names = GraphNames(g, idx)
    value = expr_value(g, names)
    if value is not None:
        names.bare, names.current = "entry", "ret"
        return head[:-1] + [head[-1] + " = " + fmt_input(value, indent, names)]
    lines = head[:-1] + [head[-1] + " {"]
    top = len(lines)
    inner = indent + IND
    for l in sorted(g.locals, key=lambda l: l.name):
        lines.extend(fmt_local("local", l, inner, semantic))
    for l in sorted(g.states, key=lambda l: l.name):
        lines.extend(fmt_local("state", l, inner, semantic))
    declared = names.declared(g.nodes)
    if order is not None:
        rank = {nid: i for i, nid in enumerate(order)}
        declared.sort(key=lambda n: rank.get(n.id, len(rank)))
    wires = [w for n in declared for w in fmt_wires(n, names.sigs[n.id], names)]
    if wires:
        if len(lines) > top:
            lines.append("")
        lines.append(f"{inner}flow {{")
        lines.extend(f"{inner}{IND}{w}" for w in wires)
        lines.append(f"{inner}}}")
    if declared and len(lines) > top:
        lines.append("")
    for n in declared:
        lines.append(fmt_node(n, names.sigs[n.id], inner, semantic, names))
    if not semantic:
        lines.extend(fmt_layout(g, names, inner))
    lines.append(indent + "}")
    return lines


def fmt_layout(g: Graph, names: GraphNames, inner: str) -> list:
    """The layout block: for each node, by the name it is written with, its metadata lines
    and its `place` line (just the name when it has no position), then the boxes."""
    places = {}
    for p in g.places:
        places.setdefault(p.id, p)
    metas = {}
    for n in g.nodes:
        if n.meta:
            metas.setdefault(n.id, n.meta)
    for nid, meta in g.orphan_meta.items():     # stale names (W0605), kept as written
        if nid not in metas:
            metas[nid] = meta
    ids = sorted(set(places) | set(metas), key=lambda i: names.name(i))
    if not ids and not g.boxes:
        return []
    out = ["", f"{inner}layout {{"]
    for nid in ids:
        out.extend(fmt_meta(metas.get(nid, []), inner + IND))
        p = places.get(nid)
        pos = f" at ({p.x}, {p.y}){fmt_props(p.props)}" if p else ""
        out.append(f"{inner}{IND}{names.name(nid)}{pos}")
    for b in sorted(g.boxes, key=lambda b: b.id):
        out.extend(fmt_meta(b.meta, inner + IND))
        props = b.props
        m = b.prop("members")
        if m is not None and m.kind == "list":
            props = [(k, Lit("list", [Lit("ident", names.name(x.value)) if x.kind == "ident" else x
                                      for x in v.value]) if k == "members" else v)
                     for k, v in b.props]
        out.append(f"{inner}{IND}box {b.id} {fmt_string(b.title)} at ({b.x}, {b.y}) "
                   f"size ({b.w}, {b.h}){fmt_props(props)}")
    out.append(f"{inner}}}")
    return out


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
            members.append((f, line + fmt_attrs(f.attrs)))
    else:
        head = f"enum {it.name}" + (f": {it.base}" if it.base else "")
        members = []
        for m in it.members:
            line = f"{IND}{m.name}" + (f" = {m.value}" if m.value is not None else "")
            members.append((m, line + fmt_attrs(m.attrs)))
    head += fmt_attrs(it.attrs)
    if not members:
        return [head + " {}"]
    lines = [head + " {"]
    for m, line in members:
        lines.extend(above(m, IND, semantic))
        lines.append(line)
    return lines + ["}"]


def fmt_class(c: Class, methods: list, idx: ModuleIndex, semantic=False) -> list:
    """A class: fields in the order written (their layout), then its methods, funcs before
    events, each by name, with a blank line before each method."""
    head = (f"class {c.name}" + (f" : {c.base}" if c.base else "")
            + (f" impl {', '.join(c.impls)}" if c.impls else "") + fmt_attrs(c.attrs))
    if not c.fields and not c.dispatchers and not methods:
        return [head + " {}"]
    lines = [head + " {"]
    for f in c.fields:
        line = f"{IND}{f.name}: {f.type}"
        if f.default is not None:
            line += f" = {fmt_lit(f.default)}"
        lines.extend(above(f, IND, semantic))
        lines.append(line + fmt_attrs(f.attrs))
    for d in c.dispatchers:
        lines.extend(above(d, IND, semantic))
        lines.append(f"{IND}dispatcher {d.name}{fmt_params(d.params)}{fmt_attrs(d.attrs)}")
    for g in sorted(methods, key=lambda g: (g.kind != "func", g.name)):
        if len(lines) > 1:
            lines.append("")
        lines.extend(fmt_graph(g, idx, IND, semantic))     # its #[...] lines included
    return lines + ["}"]


def fmt_interface(it: Interface, semantic=False) -> list:
    """An interface: its method signatures in the order written (their dispatch slots)."""
    head = f"interface {it.name}{fmt_attrs(it.attrs)}"
    if not it.methods:
        return [head + " {}"]
    lines = [head + " {"]
    for m in it.methods:
        s = f"{IND}func {m.name}{fmt_params(m.params)}"
        if m.results is not None:
            s += " -> " + fmt_params(m.results)
        lines.extend(above(m, IND, semantic))
        lines.append(s + fmt_attrs(m.attrs))
    return lines + ["}"]


def fmt_item(it, idx: ModuleIndex, semantic=False, methods=None) -> list:
    if isinstance(it, Graph):
        return fmt_graph(it, idx, "", semantic)        # its `//` and #[...] lines included
    if isinstance(it, Interface):
        return above(it, "", semantic) + fmt_interface(it, semantic)
    if isinstance(it, Class):
        return above(it, "", semantic) + fmt_class(it, methods or [], idx, semantic)
    if isinstance(it, (Struct, Enum)):
        return above(it, "", semantic) + fmt_type_decl(it, semantic)
    return above(it, "", semantic) + _fmt_decl(it)


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
    if semantic:                    # `//` comments are not semantic (section 2.1)
        m = copy.deepcopy(m)
        strip_comments(m)
    idx = ModuleIndex(m)
    lines = ([f"wiret {m.version}"] + above(m, "", semantic)
             + [f"module {m.name}{fmt_attrs(m.attrs)}"])
    owned = {}
    for it in m.items:
        if isinstance(it, Graph) and it.owner:
            owned.setdefault(it.owner, []).append(it)
    items = sorted((it for it in m.items if not (isinstance(it, Graph) and it.owner)),
                   key=lambda it: (ITEM_ORDER.index(item_kind(it)), it.name))
    prev_kind = None
    for it in items:
        k = item_kind(it)
        block = isinstance(it, (Graph, Struct, Enum, Class, Interface))
        if block or k != prev_kind:
            lines.append("")
        lines.extend(fmt_item(it, idx, semantic, owned.get(it.name)))
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
