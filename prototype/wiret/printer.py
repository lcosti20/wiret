"""Canonical writer and hashes (spec section 2.5).

A graph is written as its `exec` statements in the order they run, walked from its Entry
node (section 2.3). The writer decides how each node is written: inline in the one input it
feeds, as an `exec` statement where control reaches it, under a name (`node name = ...`) when
it is read or entered from more than one place, or after a `!` when nothing reaches it."""
from __future__ import annotations

import copy
import hashlib
import math
import re
import unicodedata

from .model import (Attr, Binding, Box, Class, Const, Enum, Interface, ExecOut, Extern, Graph, ITEM_ORDER, Lit,
                    META_ORDER, Module, NODE_GENERICS, Node, PinRef, SEMANTIC_ATTRS, Struct, Use, Var,
                    item_kind, strip_comments)
from .registry import (PLACE_MUTATORS, ModuleIndex, Sig, field_place, lit_equal, lit_fits,
                       signature)

IND = "  "

PLACE_PROP_ORDER = ["pos", "label", "color", "size", "collapsed", "hidden"]
BOX_PROP_ORDER = ["title", "pos", "size", "color"]
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")
# names the printer does not choose for a node it has to name: values and `self`. Keywords
# are contextual, so a node a person named `exec` or `box` keeps that name (section 2.1)
_NOT_NAMES = {"true", "false", "null", "self"}


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


def fmt_type(t: str) -> str:
    """A type as written: the model spells generic types `array#<i32>`, the text `array#<i32>`."""
    return t.replace("#<", "#<")


def fmt_args(a: Attr) -> str:
    if a.args is None:
        return ""
    return "(" + ", ".join((f"{k}: " if k else "") + fmt_lit(v) for k, v in a.args) + ")"


def fmt_attr(a: Attr) -> str:
    return f"@{a.name}{fmt_args(a)}"


def sorted_attrs(attrs: list) -> list:
    """Known semantic attributes alphabetically, then unknown ones as written."""
    sem = sorted((a for a in attrs if a.name in SEMANTIC_ATTRS), key=lambda a: a.name)
    return sem + [a for a in attrs if a.name not in SEMANTIC_ATTRS]


def fmt_attrs(attrs: list) -> str:
    """Semantic decorators written before an element on its line: `@id("p1") `."""
    return "".join(fmt_attr(a) + " " for a in sorted_attrs(attrs))


def sorted_meta(meta: list) -> list:
    """`doc`, `category`, `keywords`, then notes, then anything else; stable within each."""
    order = {k: i for i, k in enumerate(META_ORDER)}
    return sorted(meta, key=lambda a: order.get(a.name, len(order)))


def fmt_meta(meta: list, indent: str, semantic=False) -> list:
    """The metadata decorator lines above an element (section 2.4); none in the semantic text."""
    if semantic:
        return []
    return [f"{indent}{fmt_attr(a)}" for a in sorted_meta(meta)]


def fmt_comment(lines: list, indent: str) -> list:
    """The `//` lines attached to an element, directly above it (section 2.1)."""
    return [f"{indent}//" + (f" {c}" if c else "") for c in lines]


def decorator_lines(x, indent: str, semantic=False, attrs=True) -> list:
    """What stands directly above a declaration or statement: its `//` lines, its metadata
    decorators, then (with `attrs`) its semantic decorators, one per line."""
    out = fmt_comment(getattr(x, "comment", []) or [], indent) + \
        fmt_meta(getattr(x, "meta", []) or [], indent, semantic)
    if attrs:
        out += [f"{indent}{fmt_attr(a)}" for a in sorted_attrs(getattr(x, "attrs", []) or [])]
    return out


def above(x, indent: str, semantic=False) -> list:
    return decorator_lines(x, indent, semantic)


def fmt_param(p) -> str:
    s = f"{fmt_attrs(p.attrs)}{p.name}: {fmt_type(p.type)}"
    if p.default is not None:
        s += f" = {fmt_lit(p.default)}"
    return s


def fmt_params(ps: list, receiver: bool = False) -> str:
    parts = (["self"] if receiver else []) + [fmt_param(p) for p in ps or []]
    return "(" + ", ".join(parts) + ")"


def fmt_props(props: list, order=PLACE_PROP_ORDER) -> str:
    """`{key=value, ...}`: a node's or box's attribute block (section 2.3)."""
    rank = {k: i for i, k in enumerate(order)}
    ps = sorted(props, key=lambda kv: rank.get(kv[0], len(rank)))
    return "{" + ", ".join(f"{k}={fmt_lit(v)}" for k, v in ps) + "}"


def place_props(g: Graph, nid: str) -> list:
    p = g.place(nid)
    if p is None:
        return []
    return [("pos", Lit("tuple", [Lit("int", p.x), Lit("int", p.y)]))] + list(p.props)


def box_props(b: Box) -> list:
    return ([("title", Lit("string", b.title)),
             ("pos", Lit("tuple", [Lit("int", b.x), Lit("int", b.y)])),
             ("size", Lit("tuple", [Lit("int", b.w), Lit("int", b.h)]))] + list(b.props))


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


def fmt_targs(targs: list) -> str:
    return "#<" + ", ".join(fmt_type(t) for t in targs) + ">" if targs else ""


def qualified_symbol(node: Node, g: Graph, idx: ModuleIndex) -> str:
    """The symbol as the canonical form writes it. Inside a method the reader also accepts a
    member of the method's class by its bare name (`GetField health`, `Broadcast OnDied`,
    `ArrayAdd#<i32> items`); it is written `Player.health` everywhere, so a node reads the
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
    """`Kind symbol#<targs>#count<n>`, or `ArrayAdd#<i32> acc` for a place mutator (3.3)."""
    targs = fmt_targs(node.targs)
    sym = names.symbol(node) if names is not None else node.symbol
    if node.kind == "Format" and sym is not None:       # its template is a string
        sym = fmt_string(sym)
    if node.kind in PLACE_MUTATORS:
        head = node.kind + targs + (f" {sym}" if sym else "")
    else:
        head = node.kind + (f" {sym}" if sym else "") + targs
    for a in node.attrs:
        if a.name in NODE_GENERICS:
            head += f"#{a.name}<" + ", ".join(fmt_lit(v) for _, v in a.args or []) + ">"
    return head


def node_decorators(node: Node) -> list:
    """The semantic decorators of a node: all but its named generics."""
    return [a for a in node.attrs if a.name not in NODE_GENERICS]


class _Exec:
    """An `exec` statement of the tree: a node and its exec outputs' blocks. A block of
    None is the flattened last output: the statements after it continue from it."""
    __slots__ = ("nid", "outs", "comment")

    def __init__(self, nid, comment=None):
        self.nid = nid
        self.outs = []          # [[pin, [statements] | None]]
        self.comment = comment or []


class _Goto:
    __slots__ = ("target", "tpin", "comment", "bound")

    def __init__(self, target, tpin, comment):
        self.target, self.tpin, self.comment = target, tpin, comment
        self.bound = False      # `goto pin`: an exec input bound by an enclosing block


class GraphNames:
    """How a graph's nodes are written (section 2.3).

    - A node is written **inline**, inside the one input that reads it, when it has no exec
      pins, is not named, carries no `//` comment and exactly one input reads it. Its id is
      its consumer's id, a dot and the input (`3.message`).
    - A node with exec pins is an **`exec` statement** where control first reaches it. Its id
      is its **execution position**: its index among the `exec` statements of its block,
      after the block's own position (`1.body.0`).
    - A node is **named** (`node name = ...`) when it was named, when its output is read
      somewhere it cannot be written inline or bound by a block, or when it is entered from
      more than one place (a `goto`). Its id is its name.
    - A node that nothing reaches is written after a `!`, with the id `~r`, or `~r.k` inside
      a `!{ }` block, `r` counting the `!` statements."""

    def __init__(self, g: Graph, idx: ModuleIndex, sigs: dict = None, semantic=False):
        self.g, self.idx, self.semantic = g, idx, semantic
        self.current = None
        self.sigs = sigs if sigs is not None else {n.id: signature(n, g, idx) for n in g.nodes}
        self.nodes = {}
        for n in g.nodes:
            self.nodes.setdefault(n.id, n)
        self.entry = next((n.id for n in g.nodes if n.kind == "Entry"), None)
        self.params = {p.name for p in g.params} | ({"self"} if g.receiver else set())
        self._inline()
        self._tree()
        self._names()
        self._ids()

    # -- which nodes are inline ------------------------------------------------
    def _inline(self):
        g, nodes = self.g, self.nodes
        refs = {}                   # node id -> [(consumer id, pin)]
        for n in g.nodes:
            for b in n.bindings:
                if isinstance(b.value, PinRef) and b.value.node in nodes:
                    refs.setdefault(b.value.node, []).append((n.id, b.pin))
        self.refs = refs
        self.targets = {}
        for n in g.nodes:
            for e in n.execs:
                self.targets.setdefault(e.target, []).append((n.id, e))
        ids = [n.id for n in g.nodes]
        self.parent = {}            # inline node id -> (consumer id, pin)
        for n in g.nodes:
            sig = self.sigs.get(n.id)
            r = refs.get(n.id, [])
            if (sig is not None and len(r) == 1 and r[0][0] != n.id and ids.count(n.id) == 1
                    and ids.count(r[0][0]) == 1 and not n.named and not n.execs
                    and not n.comment
                    and n.id not in self.targets and not sig.error and not sig.exec_ins
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

    def root(self, nid):
        """The node whose statement an inline node is written in."""
        seen = set()
        while nid in self.parent and nid not in seen:
            seen.add(nid)
            nid = self.parent[nid][0]
        return nid

    def is_exec(self, nid) -> bool:
        """Whether a node that is not inline is written as an `exec` statement."""
        n, sig = self.nodes[nid], self.sigs[nid]
        # a node whose signature is unknown (an error, or a type parameter of a generic
        # macro) is an exec statement only when nothing reads it
        return bool(sig.exec_ins or sig.exec_outs or n.execs or nid in self.targets
                    or (sig.error and not self.refs.get(nid))
                    or n.kind in ("Entry", "Return", "Exit", "Leave"))

    def default_in(self, nid, tpin) -> bool:
        """Whether an exec wire enters `nid` at its default input."""
        if tpin is None:
            return True
        n = self.nodes.get(nid)
        if n is None:
            return False
        ins = self.sigs[nid].exec_ins
        return bool(ins) and ins[0].name == tpin

    # -- the exec tree ---------------------------------------------------------
    def _tree(self):
        """The statements, walked from Entry along exec wires in pin order. Every block is
        kept first; the last output of a node is flattened afterwards unless its block binds
        a name."""
        self.owner = {}             # node entered from several places -> the edge it is written at
        self.regions = []           # ("exec", [stmts]) | ("block", [stmts]) | ("pure", nid)
        if self.entry is not None:
            self._choose_owners()
            self.placed, self.top = set(), []
            self._walk(self.entry, self.top)
            missed = {s.target for s in self._gotos(self.top)} - self.placed
            if any(t in self.nodes and self._reaches(self.entry, t) for t in missed):
                self.owner = {}     # an owner the walk never reached: write each where first met
                self.placed, self.top = set(), []
                self._walk(self.entry, self.top)
        else:
            self.placed, self.top = set(), []
        rest = [n.id for n in self.g.nodes if n.id not in self.parent and n.id not in self.placed
                and self.is_exec(n.id)]
        if self.semantic:
            rest.sort(key=lambda i: (self.nodes[i].kind, self.nodes[i].symbol or "", i))
        seen = set()
        rest = [i for i in rest if not (i in seen or seen.add(i))]
        # a region starts at a node that no other unreached node wires into
        fed = {e.target for i in rest for e in self.nodes[i].execs}
        for nid in [i for i in rest if i not in fed] + rest:
            if nid in self.placed:
                continue
            stmts = []
            self._walk(nid, stmts)
            alone = len(stmts) == 1 and not stmts[0].outs
            self.regions.append(("exec" if alone else "block", stmts))
        pure = [n.id for n in self.g.nodes if n.id not in self.parent and n.id not in self.placed
                and not self.is_exec(n.id) and not n.named and not self.refs.get(n.id)]
        if self.semantic:
            pure.sort(key=lambda i: (self.nodes[i].kind, self.nodes[i].symbol or "", i))
        for nid in pure:
            self.regions.append(("pure", nid))
        self._flatten_all()

    def _gotos(self, stmts):
        for st in stmts:
            if isinstance(st, _Goto):
                yield st
            else:
                for _pin, blk in st.outs:
                    yield from self._gotos(blk or [])

    def _reaches(self, a, b) -> bool:
        """Whether exec wires lead from `a` to `b`."""
        seen, work = set(), [a]
        while work:
            x = work.pop()
            if x == b:
                return True
            if x in seen or x not in self.nodes:
                continue
            seen.add(x)
            work.extend(e.target for e in self.nodes[x].execs)
        return False

    def _choose_owners(self):
        """Where to write a node that several exec wires enter: at the entering wire whose
        statement is least deeply nested, the first such one met, never at a wire that comes
        back from the node itself (a loop's back edge). Every other wire is a `goto`.

        A probe walk measures depth: a node's last exec output continues in its block (depth
        unchanged, as it is usually flattened), any other output opens a block (depth + 1)."""
        preds = {}
        for n in self.g.nodes:
            for e in n.execs:
                if self.default_in(e.target, e.target_pin):
                    preds.setdefault(e.target, []).append(e)
        multi = {t for t, es in preds.items() if len(es) > 1 and t in self.nodes}
        if not multi:
            return
        depth, seen_edges = {self.entry: 0}, []
        self.placed = set()
        self._probe(self.entry, 0, depth, seen_edges)
        best = {}
        for k, (src, e, d) in enumerate(seen_edges):
            t = e.target
            if t not in multi or self._reaches(t, src):
                continue
            if t not in best or (d, k) < best[t][0]:
                best[t] = ((d, k), e)
        self.owner = {t: e for t, (_key, e) in best.items()}

    def _probe(self, nid, d, depth, seen_edges):
        stack = [(nid, d)]
        while stack:
            nid, d = stack.pop()
            if nid in self.placed or nid not in self.nodes:
                continue
            self.placed.add(nid)
            n, sig = self.nodes[nid], self.sigs[nid]
            edges = _ordered_execs(n, sig)
            nxt = []
            single = len(edges) == 1 and len(sig.exec_outs) <= 1
            for i, e in enumerate(edges):
                last = i == len(edges) - 1
                cd = d if single or (last and self.flattens(nid)) else d + 1
                seen_edges.append((nid, e, cd))
                t = e.target
                if t in self.nodes and t not in self.parent and self.is_exec(t):
                    nxt.append((t, cd))
            stack.extend(reversed(nxt))

    def _walk(self, nid, stmts):
        """Place `nid` in `stmts` and follow its wires: one output continues in the same
        block, several open a block each."""
        while True:
            self.placed.add(nid)
            st = _Exec(nid)
            stmts.append(st)
            n, sig = self.nodes[nid], self.sigs[nid]
            edges = _ordered_execs(n, sig)
            if not edges:
                return
            outs = sig.exec_outs
            single = len(edges) == 1 and len(outs) <= 1 and (
                edges[0].pin is None or (outs and edges[0].pin == outs[0].name))
            if not single:
                for e in edges:
                    blk = []
                    st.outs.append([e.pin or (outs[0].name if outs else "then"), blk])
                    nxt = self._follow(e, blk)
                    if nxt is not None:
                        self._walk(nxt, blk)
                return
            nxt = self._follow(edges[0], stmts)
            if nxt is None:
                return
            nid = nxt

    def _follow(self, e: ExecOut, stmts):
        """The node an exec wire places next, or None after writing a `goto` for it."""
        t = e.target
        owner = self.owner.get(t)
        if t in self.nodes and t not in self.placed and t not in self.parent \
                and self.default_in(t, e.target_pin) and self.is_exec(t) \
                and (owner is None or owner is e):
            if e.comment:
                self.nodes[t].comment = list(e.comment) + list(self.nodes[t].comment)
            return t
        stmts.append(_Goto(t, None if self.default_in(t, e.target_pin) else e.target_pin,
                           list(e.comment)))
        return None

    def _flatten_all(self):
        """Flatten each node's last output into the block it is in, unless that output's block
        binds a name: a read of one of the node's outputs or a `goto` to one of its other exec
        inputs, from inside it."""
        uses = self._uses()
        for stmts in [self.top] + [s for k, s in self.regions if k != "pure"]:
            self._flatten(stmts, uses)

    def _flatten(self, stmts, uses):
        i = 0
        while i < len(stmts):
            st = stmts[i]
            if isinstance(st, _Exec) and st.outs:
                for out in st.outs:
                    if out[1] is not None:
                        self._flatten(out[1], uses)
                last = st.outs[-1]
                if last[1] is not None and (st.nid, last[0]) not in uses \
                        and self.flattens(st.nid):
                    stmts[i + 1:i + 1] = last[1]
                    last[1] = None
            i += 1

    def flattens(self, nid) -> bool:
        """Whether a node's last exec output continues in its block: as it was written, else
        for a Try or Sequence, whose last output means "and then" (section 2.5)."""
        n = self.nodes[nid]
        if n.flat is not None and not self.semantic:
            return n.flat
        return n.kind in ("Try", "Sequence")

    def _sites(self):
        """For each statement node and goto: the blocks around it, outermost first, as
        (node, output pin) pairs."""
        self.site = {}
        self.goto_sites = []

        def visit(stmts, anc):
            for st in stmts:
                if isinstance(st, _Goto):
                    self.goto_sites.append((st, anc))
                    continue
                self.site[st.nid] = anc
                for pin, blk in st.outs:
                    if blk is not None:
                        visit(blk, anc + [(st.nid, pin)])

        visit(self.top, [])
        for kind, s in self.regions:
            if kind != "pure":
                visit(s, [])

    def reads(self):
        """(site blocks, producer id, output pin, consumer id) for every data wire that is
        not written inline."""
        out = []
        for n in self.g.nodes:
            if n.id in self.parent:
                continue
            root = self.root(n.id)
            anc = [] if self._declared(root) else self.site.get(root, [])
            for b in n.bindings:
                if isinstance(b.value, PinRef) and b.value.node in self.nodes and \
                        self.parent.get(b.value.node, (None,))[0] != n.id:
                    out.append((anc, b.value.node, b.value.pin, n.id))
        for nid in self.parent:     # reads from inside inline nodes
            n = self.nodes[nid]
            root = self.root(nid)
            anc = [] if self._declared(root) else self.site.get(root, [])
            for b in n.bindings:
                if isinstance(b.value, PinRef) and b.value.node in self.nodes and \
                        self.parent.get(b.value.node, (None,))[0] != nid:
                    out.append((anc, b.value.node, b.value.pin, nid))
        return out

    def _declared(self, nid) -> bool:
        """Whether a node is declared with `node`, at the top of the function, where no
        block's names are in scope."""
        return nid in getattr(self, "name_of", {}) or self.nodes[nid].named

    def _uses(self):
        """(node, pin) of every block that a read or goto inside it needs to bind a name in."""
        self.site = {}
        self._sites()
        uses = set()
        for anc, x, pin, _c in self.reads():
            for blk in anc:
                if blk[0] == x and x != self.entry:
                    uses.add(blk)
        for st, anc in self.goto_sites:
            if st.tpin is not None:
                for blk in anc:
                    if blk[0] == st.target:
                        uses.add(blk)
        return uses

    # -- names -----------------------------------------------------------------
    def _names(self):
        """Which nodes are named, and which names each block binds (a fixed point: naming a
        node removes its bindings, which can only remove conflicts)."""
        self._sites()
        g = self.g
        self.named = [n.id for n in g.nodes if n.named and n.id not in self.parent]
        if self.semantic:
            self.named.sort()
        self.name_of = {nid: nid for nid in self.named}
        taken = set(self.name_of.values()) | self.params
        module = getattr(self.idx, "module", None)
        taken |= {i for gn, i in getattr(module, "retired_nodes", ()) if gn == g.name}
        self._taken = taken
        need = set()
        for nid in self.nodes:      # a pure node read by several inputs, or with a comment
            if nid in self.parent or nid in self.name_of or self.is_exec(nid):
                continue
            if self.refs.get(nid) or self.nodes[nid].comment:
                need.add(nid)
        for st, _anc in self.goto_sites:
            if st.tpin is None and st.target in self.nodes:
                need.add(st.target)
        while True:
            for nid in sorted(need - set(self.name_of), key=self._order):
                self._name(nid)
            reads = self.reads()
            self.bound = {}         # (node, pin) of a block -> {name: (node, pin)}
            more = set()
            for anc, x, pin, _c in reads:
                if x == self.entry or x in self.name_of or x in self.parent \
                        or not self.is_exec(x):
                    continue
                blk = next((b for b in anc if b[0] == x), None)
                if blk is None:
                    more.add(x)
                else:
                    self.bound.setdefault(blk, {})[pin] = (x, pin)
            for st, anc in self.goto_sites:
                if st.tpin is None or st.target in self.name_of or st.target not in self.nodes:
                    continue
                blk = next((b for b in anc if b[0] == st.target), None)
                if blk is None:
                    more.add(st.target)
                else:
                    self.bound.setdefault(blk, {})[st.tpin] = (st.target, st.tpin)
            names = set(self.name_of.values()) | self.params
            for blk, bound in self.bound.items():
                if names & set(bound):
                    more.add(blk[0])
            for anc, x, pin, _c in reads:   # an inner block that binds the same name
                if x in self.name_of or x == self.entry:
                    continue
                inside = False
                for b in anc:
                    if b[0] == x:
                        inside = True
                        continue
                    if inside and pin in self.bound.get(b, {}) and self.bound[b][pin][0] != x:
                        more.add(x)
            if not more - set(self.name_of) - {None}:
                break
            need |= more
        # a parameter a named node hides is read through a named Entry
        if self.entry is not None and self.entry not in self.name_of and \
                self.params & (set(self.name_of.values()) - set(self.named)):
            self._name(self.entry)
        elif self.entry is not None and self.entry not in self.name_of and \
                self.params & set(self.named):
            self._name(self.entry)
        for st, anc in self.goto_sites:
            if st.tpin is not None and st.target not in self.name_of:
                st.bound = True

    def _order(self, nid):
        return [n.id for n in self.g.nodes].index(nid) if nid in self.nodes else 0

    def _name(self, nid):
        """A name for a node that must be named: its id when that is a free identifier, else
        one made from its kind and symbol, `_2`, `_3`, ... added when it is taken."""
        n = self.nodes[nid]
        if _IDENT_RE.match(nid) and nid not in self._taken and nid not in _NOT_NAMES:
            name = nid
        else:
            last = (n.symbol or "").split(".")[-1]
            base = "entry" if n.kind == "Entry" else \
                last if last and _IDENT_RE.match(last) and n.kind != "Format" else n.kind
            base = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", base).lower()
            base = re.sub(r"[^a-z0-9_]", "_", base).strip("_") or "node"
            if not _IDENT_RE.match(base) or base in _NOT_NAMES:
                base = "n_" + base
            name, k = base, 2
            while name in self._taken:
                name, k = f"{base}_{k}", k + 1
        self._taken.add(name)
        self.name_of[nid] = name
        self.named.append(nid)

    # -- ids -------------------------------------------------------------------
    def _ids(self):
        """The id each node gets when the text is read back: its name, its execution
        position, or (inline) its consumer's id and the input."""
        self.names = dict(self.name_of)

        def block(stmts, prefix):
            k = 0
            for st in stmts:
                if isinstance(st, _Goto):
                    continue
                if st.nid not in self.names:
                    self.names[st.nid] = f"{prefix}{k}"
                k += 1
                for pin, blk in st.outs:
                    if blk is not None:
                        block(blk, f"{self.names[st.nid]}.{pin}.")

        block(self.top, "")
        for r, (kind, s) in enumerate(self.regions):
            if kind == "pure":
                self.names.setdefault(s, f"~{r}")
            elif kind == "exec":
                self.names.setdefault(s[0].nid, f"~{r}")
                for pin, blk in s[0].outs:
                    if blk is not None:
                        block(blk, f"{self.names[s[0].nid]}.{pin}.")
            else:
                block(s, f"~{r}.")
        for nid in self.nodes:
            if nid not in self.names and nid not in self.parent:
                self.names[nid] = nid

        def name(nid, depth=0):
            if nid not in self.names:
                c, pin = self.parent[nid]
                self.names[nid] = f"{name(c, depth + 1)}.{pin}"
            return self.names[nid]

        for nid in self.parent:
            name(nid)

    def name(self, nid: str) -> str:
        return self.names.get(nid, nid)

    def symbol(self, node: Node) -> str:
        return qualified_symbol(node, self.g, self.idx)

    def inline(self, nid: str) -> bool:
        return nid in self.parent

    def is_named(self, nid: str) -> bool:
        return nid in self.name_of

    def declared(self, nodes: list = None) -> list:
        """The named nodes, in the order they were named."""
        return [self.nodes[nid] for nid in self.named if nid in self.nodes]


def implied_output(ref: PinRef, names: GraphNames) -> bool:
    """Whether a wire from a named node is written with its name alone (section 2.3): the
    node has one data output and is not a macro, whose outputs are named results."""
    sig = names.sigs.get(ref.node)
    if sig is None or sig.error or not names.is_named(ref.node):
        return False
    n = names.g.node(ref.node)
    outs = sig.data_outs
    return (n is not None and n.kind not in ("Entry", "Macro") and len(outs) == 1
            and outs[0].name == ref.pin)


def fmt_value(b: Binding, names: GraphNames = None, scope: dict = None) -> str:
    v = b.value
    if not isinstance(v, PinRef):
        return fmt_lit(v)
    if names is None:
        return f"{v.node}.{v.pin}" if v.pin else v.node
    if v.node not in names.nodes:           # a node that does not exist (E0101)
        return v.node if not v.pin else f"{v.node}.{v.pin}"
    if v.node == names.entry and not names.is_named(v.node):
        return v.pin                         # a parameter
    if scope is not None and scope.get(v.pin) == (v.node, v.pin):
        return v.pin                         # a name bound by an enclosing block
    if implied_output(v, names) and (scope is None or names.name(v.node) not in scope):
        return names.name(v.node)
    return f"{names.name(v.node)}.{v.pin}"


def fmt_input(b: Binding, indent: str, names: GraphNames = None, scope: dict = None) -> str:
    """The value of a binding. An inline node is written in place, followed by the pin it is
    read from, `Call F(...).x`, unless that is its one data output: `Call F(...)`."""
    kids = names.children.get(names.current, {}) if names is not None else {}
    kid = kids.get(b.pin)
    if kid is None or not isinstance(b.value, PinRef) or b.value.node != kid.id:
        return fmt_value(b, names, scope)
    sig = names.sigs[kid.id]
    text = fmt_expr(kid, sig, indent, names, scope=scope)
    outs = sig.data_outs
    if not sig.error and len(outs) == 1 and outs[0].name == b.value.pin:
        return text
    return f"{text}.{b.value.pin}"


def _implicit_self(node: Node, b: Binding, names: GraphNames) -> bool:
    """A method call's `self` input that takes the calling method's `self` (section 2.2)."""
    from .parser import self_receiver
    return (b.pin == "self" and isinstance(b.value, PinRef) and b.value.node == names.entry
            and b.value.pin == "self" and not b.comment and not names.is_named(names.entry)
            and self_receiver(node, names.g, names.idx))


def fmt_expr(node: Node, sig: Sig, indent: str, names: GraphNames = None, semantic=False,
             scope: dict = None) -> str:
    """`Kind symbol#<targs>{attrs}(`, one `.pin <- value` line per bound input (after its `//`
    lines and the decorators of the node written in it) and `)`, or `Kind{attrs}()` when no
    input is bound."""
    bindings = _ordered_bindings(node, sig)
    if names is not None:
        bindings = [b for b in bindings if not _implicit_self(node, b, names)]
    head = fmt_head(node, names)
    if names is not None and not semantic and not names.semantic:
        props = place_props(names.g, node.id)
        if props:
            head += fmt_props(props)
    if not bindings:
        return head + "()"
    lines = [head + "("]
    for b in bindings:
        if names is not None:
            names.current = node.id
        kid = names.children.get(node.id, {}).get(b.pin) if names is not None else None
        val = fmt_input(b, indent + IND, names, scope)
        lines.extend(fmt_comment(b.comment, indent + IND))
        if kid is not None and isinstance(b.value, PinRef) and b.value.node == kid.id:
            lines.extend(decorator_lines(Node("", "", meta=kid.meta,
                                              attrs=node_decorators(kid)),
                                         indent + IND, semantic or names.semantic))
        lines.append(f"{indent}{IND}.{b.pin} <- {val}")
    lines.append(f"{indent})")
    return "\n".join(lines)


# -- graphs and module -----------------------------------------------------------
def fmt_local(kw, l, indent, semantic=False) -> list:
    s = f"{indent}{fmt_attrs(l.attrs)}{kw} {l.name}: {fmt_type(l.type)}"
    if l.default is not None:
        s += f" = {fmt_lit(l.default)}"
    return decorator_lines(l, indent, semantic, attrs=False) + [s]


def expr_value(g: Graph, names: GraphNames):
    """The binding a function is written `= value` with (section 2.3), or None: a function
    outside a class with one result whose graph is Entry wired to Return and the nodes
    written inline in Return's one input, with nothing else to keep: no locals, positions,
    boxes, names, decorators or comments on the two nodes."""
    if g.kind != "func" or g.owner or g.results is None or len(g.results) != 1 or g.locals \
            or g.states or g.places or g.boxes or any(n.meta for n in g.nodes) or names.regions:
        return None
    if len(names.top) != 2 or not all(isinstance(s, _Exec) for s in names.top):
        return None
    entry, ret = names.nodes[names.top[0].nid], names.nodes[names.top[1].nid]
    if entry.kind != "Entry" or ret.kind != "Return" or names.named:
        return None
    if entry.bindings or entry.attrs or entry.comment or ret.attrs or ret.comment or ret.execs:
        return None
    if len(entry.execs) != 1 or entry.execs[0].comment:
        return None
    if len(ret.bindings) != 1 or ret.bindings[0].pin != g.results[0].name \
            or ret.bindings[0].comment:
        return None
    if len(g.nodes) != 2 + sum(1 for nid in names.parent if names.root(nid) == ret.id):
        return None
    return ret.bindings[0]


def _bound_list(names: GraphNames, nid: str, pin: str) -> str:
    bound = names.bound.get((nid, pin), {})
    if not bound:
        return ""
    sig = names.sigs[nid]
    order = {p.name: i for i, p in enumerate(sig.data_outs + sig.exec_ins)}
    return "(" + ", ".join(sorted(bound, key=lambda k: order.get(k, len(order)))) + ")"


def fmt_stmts(stmts: list, names: GraphNames, indent: str, scope: dict, semantic: bool) -> list:
    lines = []
    for st in stmts:
        if isinstance(st, _Goto):
            if not semantic:
                lines.extend(fmt_comment(st.comment, indent))
            if st.bound:
                lines.append(f"{indent}goto {st.tpin}")
            else:
                t = names.name(st.target)
                lines.append(f"{indent}goto {t}" + (f".{st.tpin}" if st.tpin else ""))
            continue
        lines.extend(fmt_exec(st, names, indent, scope, semantic))
    return lines


def fmt_exec(st: _Exec, names: GraphNames, indent: str, scope: dict, semantic: bool,
             bang: str = "") -> list:
    n, sig = names.nodes[st.nid], names.sigs[st.nid]
    if names.is_named(st.nid):
        lines = [f"{indent}{bang}exec {names.name(st.nid)}"]
    else:
        deco = decorator_lines(Node("", "", meta=n.meta, attrs=node_decorators(n),
                                    comment=n.comment), indent, semantic)
        lines = deco + (f"{indent}{bang}exec " + fmt_expr(n, sig, indent, names, semantic,
                                                         scope)).split("\n")
    for pin, blk in st.outs:
        # the first output follows the node's `)`; each later one follows the `}` that
        # closes the block before it
        if blk is None:             # the flattened last output: `}.pin`
            lines[-1] += f".{pin}"
            continue
        inner = dict(scope)
        inner.update(names.bound.get((st.nid, pin), {}))
        lines[-1] += f".{pin}{_bound_list(names, st.nid, pin)} -> {{"
        lines.extend(fmt_stmts(blk, names, indent + IND, inner, semantic))
        lines.append(f"{indent}}}")
    return lines

def fmt_graph(g: Graph, idx: ModuleIndex, indent: str = "", semantic=False) -> list:
    """A graph: its decorators and head, then its locals and states, its boxes, its named
    nodes, its `exec` statements from Entry, and the statements that nothing reaches."""
    head = f"{indent}{g.kind} {g.short_name}"
    if g.tparams:
        head += "#<" + ", ".join(g.tparams) + ">"
    head += fmt_params(g.params, receiver=bool(g.receiver))
    if g.results is not None:
        head += " -> " + fmt_params(g.results)
    names = GraphNames(g, idx, semantic=semantic)
    lines = decorator_lines(g, indent, semantic) + [head]
    value = expr_value(g, names)
    if value is not None:
        names.current = names.top[1].nid
        return lines[:-1] + [lines[-1] + " = " + fmt_input(value, indent, names, {})]
    lines[-1] += " {"
    inner = indent + IND
    groups = []
    loc = []
    for l in sorted(g.locals, key=lambda l: l.name):
        loc.extend(fmt_local("local", l, inner, semantic))
    for l in sorted(g.states, key=lambda l: l.name):
        loc.extend(fmt_local("state", l, inner, semantic))
    groups.append(loc)
    if not semantic:
        bx = []
        for b in g.boxes:
            bx.extend(fmt_meta(b.meta, inner))
            bx.append(f"{inner}box {fmt_props(box_props(b), BOX_PROP_ORDER)}")
        groups.append(bx)
    decl = []
    for n in names.declared():
        sig = names.sigs[n.id]
        deco = decorator_lines(Node("", "", meta=n.meta, attrs=node_decorators(n),
                                    comment=n.comment), inner, semantic)
        decl.extend(deco)
        decl.extend((f"{inner}node {names.name(n.id)} = "
                     + fmt_expr(n, sig, inner, names, semantic, {})).split("\n"))
    groups.append(decl)
    groups.append(fmt_stmts(names.top, names, inner, {}, semantic))
    for kind, s in names.regions:
        if kind == "pure":
            n = names.nodes[s]
            deco = decorator_lines(Node("", "", meta=n.meta, attrs=node_decorators(n),
                                        comment=n.comment), inner, semantic)
            groups.append(deco + (f"{inner}!" + fmt_expr(n, names.sigs[s], inner, names,
                                                         semantic, {})).split("\n"))
        elif kind == "exec":
            groups.append(fmt_exec(s[0], names, inner, {}, semantic, bang="!"))
        else:
            groups.append([f"{inner}!{{"] + fmt_stmts(s, names, inner + IND, {}, semantic)
                          + [f"{inner}}}"])
    body = []
    for grp in groups:
        if grp:
            if body:
                body.append("")
            body.extend(grp)
    return lines + body + [indent + "}"]


def fmt_type_decl(it, semantic=False) -> list:
    """A struct or enum. Members keep the order written: field order and enum order are
    semantic (layout and implicit values), so the canonical form never sorts them."""
    if isinstance(it, Struct):
        head = f"struct {it.name}"
        members = []
        for f in it.fields:
            line = f"{IND}{fmt_attrs(f.attrs)}{f.name}: {fmt_type(f.type)}"
            if f.default is not None:
                line += f" = {fmt_lit(f.default)}"
            members.append((f, line))
    else:
        head = f"enum {it.name}" + (f": {it.base}" if it.base else "")
        members = []
        for m in it.members:
            line = f"{IND}{fmt_attrs(m.attrs)}{m.name}" + (f" = {m.value}" if m.value is not None else "")
            members.append((m, line))
    if not members:
        return [head + " {}"]
    lines = [head + " {"]
    for m, line in members:
        lines.extend(decorator_lines(m, IND, semantic, attrs=False))
        lines.append(line)
    return lines + ["}"]


def fmt_class(c: Class, methods: list, idx: ModuleIndex, semantic=False) -> list:
    """A class: fields in the order written (their layout), then its methods, funcs before
    events, each by name, with a blank line before each method."""
    head = (f"class {c.name}" + (f" : {c.base}" if c.base else "")
            + (f" impl {', '.join(c.impls)}" if c.impls else ""))
    if not c.fields and not c.dispatchers and not methods:
        return [head + " {}"]
    lines = [head + " {"]
    for f in c.fields:
        line = f"{IND}{fmt_attrs(f.attrs)}{f.name}: {fmt_type(f.type)}"
        if f.default is not None:
            line += f" = {fmt_lit(f.default)}"
        lines.extend(decorator_lines(f, IND, semantic, attrs=False))
        lines.append(line)
    for d in c.dispatchers:
        lines.extend(decorator_lines(d, IND, semantic))
        lines.append(f"{IND}dispatcher {d.name}{fmt_params(d.params)}")
    for g in sorted(methods, key=lambda g: (g.kind != "func", g.name)):
        if len(lines) > 1:
            lines.append("")
        lines.extend(fmt_graph(g, idx, IND, semantic))     # its decorator lines included
    return lines + ["}"]


def fmt_interface(it: Interface, semantic=False) -> list:
    """An interface: its method signatures in the order written (their dispatch slots)."""
    head = f"interface {it.name}"
    if not it.methods:
        return [head + " {}"]
    lines = [head + " {"]
    for m in it.methods:
        s = f"{IND}func {m.name}{fmt_params(m.params, receiver=True)}"
        if m.results is not None:
            s += " -> " + fmt_params(m.results)
        lines.extend(decorator_lines(m, IND, semantic))
        lines.append(s)
    return lines + ["}"]


def fmt_item(it, idx: ModuleIndex, semantic=False, methods=None) -> list:
    if isinstance(it, Graph):
        return fmt_graph(it, idx, "", semantic)
    if isinstance(it, Interface):
        return above(it, "", semantic) + fmt_interface(it, semantic)
    if isinstance(it, Class):
        return above(it, "", semantic) + fmt_class(it, methods or [], idx, semantic)
    if isinstance(it, (Struct, Enum)):
        return above(it, "", semantic) + fmt_type_decl(it, semantic)
    return above(it, "", semantic) + _fmt_decl(it)


def _fmt_decl(it) -> list:
    if isinstance(it, Use):
        return [f"use {it.name}" + (f" as {it.alias}" if it.alias else "")]
    if isinstance(it, Extern):
        if it.kind == "type":
            return [f"extern type {it.name}"]
        s = f"extern func {it.name}{fmt_params(it.params)}"
        if it.results is not None:
            s += " -> " + fmt_params(it.results)
        return [s]
    if isinstance(it, Const):
        return [f"const {it.name}: {fmt_type(it.type)} = {fmt_lit(it.value)}"]
    if isinstance(it, Var):
        d = f" = {fmt_lit(it.default)}" if it.default is not None else ""
        return [f"var {it.name}: {fmt_type(it.type)}{d}"]
    raise TypeError(it)


def print_module(m: Module, semantic=False) -> str:
    if semantic:                    # `//` comments are not semantic (section 2.1)
        m = copy.deepcopy(m)
        strip_comments(m)
    idx = ModuleIndex(m)
    lines = ([f"wiret {m.version}"] + above(m, "", semantic) + [f"module {m.name}"])
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
        decorated = bool(getattr(it, "meta", None) or getattr(it, "attrs", None)
                         or getattr(it, "comment", None))
        if block or k != prev_kind or decorated:
            lines.append("")
        lines.extend(fmt_item(it, idx, semantic, owned.get(it.name)))
        prev_kind = k if not (block or decorated) else None
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
