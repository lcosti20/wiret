"""`wiretc merge base ours theirs`: the keyed three-way merge of section 7.1.

Every element is matched by key across the three versions and merged per field: a field
changed on one side takes that change, the same change on both sides is no change, and
different changes are a conflict. Layout never blocks a merge; notes merge as a list.
Conflicts are written as markers around the lines concerned, and the result is validated.
"""
from __future__ import annotations

import copy
import difflib
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Callable, Optional

from .checker import check
from .ids import get_id
from .model import (Binding, Box, Const, Enum, EnumMember, ExecOut, Extern, Field, Graph, Lit,
                    Local, Module, Node, Param, PinRef, Place, Struct, Use, Var, Class,
                    IfaceMethod, Interface, Dispatcher)
from .parser import ParseError, parse
from .printer import fmt_args, fmt_attr, fmt_lit, fmt_params, print_module
from .registry import ModuleIndex, signature


@dataclass
class Conflict:
    where: str                         # "Main.plus.b", for the report
    what: str
    set_theirs: Callable[[Module], None]   # apply theirs' side to a copy of the merged model


@dataclass
class MergeResult:
    text: str
    conflicts: list = field(default_factory=list)       # [Conflict]
    semantic: list = field(default_factory=list)        # [Diag] new errors in the merge
    notices: list = field(default_factory=list)         # [str] layout decisions
    fallback: bool = False                              # a side did not parse: text merge

    @property
    def clean(self) -> bool:
        return not self.conflicts and not self.semantic


# -- field maps --------------------------------------------------------------------------
MISSING = None


def val_text(v) -> str:
    return f"{v.node}.{v.pin}" if isinstance(v, PinRef) else fmt_lit(v)


def meta_text(a) -> str:
    return f"#[{a.name}{fmt_args(a)}]"


def attr_fields(attrs: list, prefix="attr") -> dict:
    out = {}
    for a in attrs:
        key = f"{prefix}:{a.name}"
        out[key] = (out[key][0] + " " + fmt_attr(a), out[key][1] + [a]) if key in out \
            else (fmt_attr(a), [a])
    return out


def comment_field(out: dict, key: str, lines: list) -> None:
    """An attached `//` comment as a field, so it merges like any other (section 7.1)."""
    if lines:
        out[key] = ("\n".join(lines), list(lines))


def node_fields(n: Node, single_out: Optional[str], comments=False) -> dict:
    out = {"kind": (n.kind, n.kind), "symbol": (n.symbol or "", n.symbol)}
    for i, t in enumerate(n.targs):
        out[f"targ:{i}"] = (t, t)
    out.update(attr_fields(n.attrs))
    for b in n.bindings:
        out[f"bind:{b.pin}"] = (val_text(b.value), b)
    for x in n.execs:
        pin = x.pin or single_out or "then"
        target = x.target + (f".{x.target_pin}" if x.target_pin else "")
        out[f"exec:{pin}"] = (target, ExecOut(pin, x.target, x.target_pin))
        if comments:
            comment_field(out, f"cmt:exec:{pin}", x.comment)
    if comments:
        comment_field(out, "cmt", n.comment)
        for b in n.bindings:
            comment_field(out, f"cmt:bind:{b.pin}", b.comment)
    return out


def build_node(proto: Node, fields: dict) -> Node:
    n = copy.deepcopy(proto)
    n.kind = fields["kind"][1]
    n.symbol = fields["symbol"][1] if "symbol" in fields else None
    targs = sorted((int(k.split(":")[1]), v[1]) for k, v in fields.items()
                   if k.startswith("targ:"))
    n.targs = [t for _, t in targs]
    n.attrs = [a for k, v in sorted(fields.items()) if k.startswith("attr:") for a in v[1]]
    n.bindings = [copy.deepcopy(v[1]) for k, v in sorted(fields.items()) if k.startswith("bind:")]
    n.execs = [copy.deepcopy(v[1]) for k, v in sorted(fields.items()) if k.startswith("exec:")]
    n.comment = list(fields.get("cmt", ("", []))[1])
    for b in n.bindings:
        b.comment = list(fields.get(f"cmt:bind:{b.pin}", ("", []))[1])
    for e in n.execs:
        e.comment = list(fields.get(f"cmt:exec:{e.pin}", ("", []))[1])
    return n


def sub_fields(x, comments=False) -> dict:
    """A parameter, result, field, enum member, local or state slot."""
    out = {"name": (x.name, x.name)}
    if comments:
        comment_field(out, "cmt", getattr(x, "comment", []))
    if hasattr(x, "type"):
        out["type"] = (x.type, x.type)
    d = getattr(x, "default", None)
    if d is not None:
        out["default"] = (fmt_lit(d), d)
    if isinstance(x, EnumMember) and x.value is not None:
        out["value"] = (str(x.value), x.value)
    if isinstance(x, (IfaceMethod, Dispatcher)):    # the signature merges as one field
        text = fmt_params(x.params) + (" -> " + fmt_params(x.results) if x.results is not None
                                       else "")
        out["sig"] = (text, (x.params, x.results))
    out.update(attr_fields(x.attrs))
    return out


def build_sub(proto, fields: dict):
    x = copy.deepcopy(proto)
    x.name = fields["name"][1]
    if "type" in fields:
        x.type = fields["type"][1]
    if hasattr(x, "default"):
        x.default = fields["default"][1] if "default" in fields else None
    if isinstance(x, EnumMember):
        x.value = fields["value"][1] if "value" in fields else None
    if isinstance(x, IfaceMethod):
        x.params, x.results = copy.deepcopy(fields["sig"][1])
    if isinstance(x, Dispatcher):
        x.params = copy.deepcopy(fields["sig"][1][0])
    x.attrs = [a for k, v in sorted(fields.items()) if k.startswith("attr:") for a in v[1]]
    if hasattr(x, "comment"):
        x.comment = list(fields.get("cmt", ("", []))[1])
    return x


def key_of(x, kind: str = "") -> tuple:
    """Declarations, parameters, fields, members and locals: by @id, else by name."""
    i = get_id(getattr(x, "attrs", []))
    return ("id", i) if i else (kind, x.name)


def decl_kind(it) -> str:
    if isinstance(it, Graph):
        return it.kind
    return {Use: "use", Extern: "extern", Const: "const", Var: "var", Enum: "enum",
            Struct: "struct", Class: "class", Interface: "interface"}[type(it)]


def decl_fields(it, comments=False) -> dict:
    out = {"name": (it.name, it.name)}
    if comments:
        comment_field(out, "cmt", it.comment)
    out.update(attr_fields(it.attrs))
    if isinstance(it, Use):
        out["alias"] = (it.alias or "", it.alias)
    if isinstance(it, Extern):
        out["kind"] = (it.kind, it.kind)
        out["arrow"] = (str(it.results is not None), it.results is not None)
    if isinstance(it, (Const, Var)):
        out["type"] = (it.type, it.type)
        v = it.value if isinstance(it, Const) else it.default
        if v is not None:
            out["value"] = (fmt_lit(v), v)
    if isinstance(it, (Enum, Class)):
        out["base"] = (it.base or "", it.base)
    if isinstance(it, Class):
        out["impls"] = (", ".join(it.impls), list(it.impls))
    if isinstance(it, Graph):
        out["tparams"] = (",".join(it.tparams), list(it.tparams))
        out["arrow"] = (str(it.results is not None), it.results is not None)
    return out


def build_decl(proto, fields: dict):
    it = copy.deepcopy(proto)
    it.name = fields["name"][1]
    it.attrs = [a for k, v in sorted(fields.items()) if k.startswith("attr:") for a in v[1]]
    if isinstance(it, Use):
        it.alias = fields["alias"][1]
    if isinstance(it, (Const, Var)):
        it.type = fields["type"][1]
        v = fields["value"][1] if "value" in fields else None
        if isinstance(it, Const):
            it.value = v
        else:
            it.default = v
    if isinstance(it, (Enum, Class)):
        it.base = fields["base"][1]
    if isinstance(it, Class):
        it.impls = list(fields["impls"][1])
    if isinstance(it, Graph):
        it.tparams = fields["tparams"][1]
    it.comment = list(fields.get("cmt", ("", []))[1])
    return it


# -- the merger --------------------------------------------------------------------------
class Merger:
    def __init__(self, base: Module, ours: Module, theirs: Module):
        self.b, self.o, self.t = base, ours, theirs
        self.idx = {id(m): ModuleIndex(m) for m in (base, ours, theirs)}
        self.conflicts: list = []
        self.notices: list = []

    # field-level three-way merge
    def merge_fields(self, b: Optional[dict], o: Optional[dict], t: Optional[dict], where: str,
                     setter: Callable[[Module, str, object], None]) -> dict:
        b, o, t = b or {}, o or {}, t or {}
        out = {}
        for k in sorted(set(b) | set(o) | set(t)):
            vb, vo, vt = b.get(k), o.get(k), t.get(k)
            tb, to, tt = (x[0] if x else MISSING for x in (vb, vo, vt))
            if to == tt:
                pick = vo
            elif to == tb:
                pick = vt
            elif tt == tb:
                pick = vo
            else:
                pick = vo
                theirs = vt

                def apply(m, k=k, theirs=theirs):
                    setter(m, k, theirs)
                self.conflicts.append(Conflict(f"{where}.{k.split(':')[-1]}" if ":" in k
                                               else f"{where}.{k}",
                                               f"changed differently on both sides ({k})", apply))
            if pick is not MISSING:
                out[k] = pick
        return out

    def merge_keyed(self, b: list, o: list, t: list, key, where, merge_one, changed,
                    on_conflict, name_key=None) -> list:
        """Three-way merge of a list of keyed elements. `merge_one(kb, ko, kt)` merges an
        element present on both sides; `changed(x, y)` says whether two versions differ;
        `on_conflict(kept, side, k)` records a deleted-on-one-side, changed-on-the-other
        conflict. The result keeps ours' order, with theirs' additions after their
        predecessor (or theirs' order, if only theirs reordered).

        `name_key` gives an element's key without its @id. An element that has no @id is
        matched to an element of another version that has one with the same name key, so
        assigning ids on one side (`wiretc fmt --assign-ids`) does not look like a rename."""
        sides = [{key(x): x for x in lst} for lst in (b, o, t)]
        if name_key is not None:
            by_name = {}
            for side in sides:
                for k, x in side.items():
                    if k[0] == "id":
                        by_name.setdefault(name_key(x), k)
            for side in sides:
                for k, x in list(side.items()):
                    target = by_name.get(k) if k[0] != "id" else None
                    if target is not None and target not in side:
                        del side[k]
                        side[target] = x
        mb, mo, mt = sides
        result = {}
        for k in list(mo) + [k for k in mt if k not in mo]:
            xb, xo, xt = mb.get(k), mo.get(k), mt.get(k)
            if xo is not None and xt is not None:
                result[k] = merge_one(xb, xo, xt)
            elif xb is None:                        # added on one side only
                result[k] = copy.deepcopy(xo if xo is not None else xt)
            elif xo is None and xt is not None:     # deleted in ours
                if changed(xb, xt):
                    on_conflict(None, xt, k, "ours")
            elif xt is None and xo is not None:     # deleted in theirs
                if changed(xb, xo):
                    result[k] = copy.deepcopy(xo)
                    on_conflict(xo, None, k, "theirs")
        order_o = [k for k in mo if k in result]
        order_t = [k for k in mt if k in result]
        common_b = [k for k in mb if k in mo and k in mt]
        base_order = order_t if [k for k in mo if k in common_b] == common_b else order_o
        other = order_o if base_order is order_t else order_t
        order = list(base_order)
        for i, k in enumerate(other):
            if k in order:
                continue
            prev = next((other[j] for j in range(i - 1, -1, -1) if other[j] in order), None)
            order.insert(order.index(prev) + 1 if prev else 0, k)
        for k in result:
            if k not in order:
                order.append(k)
        return [result[k] for k in order]

    # metadata --------------------------------------------------------------------------
    def merge_meta(self, b: list, o: list, t: list, where: str, owner_path) -> list:
        def plain(meta):
            out = {}
            for a in meta:
                if a.name != "note":
                    key = f"meta:{a.name}"
                    prev = out.get(key)
                    out[key] = ((prev[0] + "\n" if prev else "") + meta_text(a),
                                (prev[1] if prev else []) + [a])
            return out

        def setter(m, k, theirs):
            owner = owner_path(m)
            if owner is None:
                return
            name = k.split(":", 1)[1]
            owner.meta = [a for a in owner.meta if a.name != name] + (theirs[1] if theirs else [])
        merged = self.merge_fields(plain(b), plain(o), plain(t), where, setter)
        out = [a for k, v in sorted(merged.items()) for a in v[1]]
        nb = [meta_text(a) for a in b if a.name == "note"]
        no = [meta_text(a) for a in o if a.name == "note"]
        nt = [meta_text(a) for a in t if a.name == "note"]
        by_text = {meta_text(a): a for a in b + o + t if a.name == "note"}
        gone_o = [x for x in nb if x not in no]
        gone_t = [x for x in nb if x not in nt]
        new_o = [x for x in no if x not in nb]
        new_t = [x for x in nt if x not in nb and x not in no]
        keep = [x for x in no if x not in gone_t] + [x for x in new_t]
        if set(gone_o) & set(gone_t) and new_o and new_t:
            # both sides replaced the same note with different text (section 7.1)
            keep = [x for x in keep if x not in new_t]

            def apply(m, nt_=nt):
                owner = owner_path(m)
                if owner is not None:
                    owner.meta = [a for a in owner.meta if a.name != "note"] + \
                        [copy.deepcopy(by_text[x]) for x in nt_]
            self.conflicts.append(Conflict(f"{where} note", "a note was replaced differently "
                                                            "on both sides", apply))
        out += [copy.deepcopy(by_text[x]) for x in keep]
        return out

    # module ----------------------------------------------------------------------------
    def merge(self) -> Module:
        b, o, t = self.b, self.o, self.t
        m = copy.deepcopy(o)
        fields = self.merge_fields({"name": (b.name, b.name), **attr_fields(b.attrs)},
                                   {"name": (o.name, o.name), **attr_fields(o.attrs)},
                                   {"name": (t.name, t.name), **attr_fields(t.attrs)},
                                   "module", self.set_module)
        m.name = fields["name"][1]
        m.attrs = [a for k, v in sorted(fields.items()) if k.startswith("attr:") for a in v[1]]
        m.meta = self.merge_meta(b.meta, o.meta, t.meta, "module", lambda mm: mm)
        m.comment = list(t.comment if o.comment == b.comment else o.comment)
        m.comments = []

        def changed(x, y):
            return self.decl_text(x) != self.decl_text(y)

        def conflict(kept, side_item, k, deleter):
            name = (kept or side_item).name
            if deleter == "ours":
                def apply(mm, it=side_item):
                    mm.items.append(copy.deepcopy(it))
            else:
                def apply(mm, name=name):
                    mm.items = [x for x in mm.items if x.name != name]
            self.conflicts.append(Conflict(name, f"deleted in {deleter}, changed in the other",
                                           apply))
        m.items = self.merge_keyed(b.items, o.items, t.items, lambda x: key_of(x, decl_kind(x)),
                                   "module", self.merge_decl, changed, conflict,
                                   name_key=lambda x: (decl_kind(x), x.name))
        self.carry_renames(m)
        return m

    def set_module(self, m, k, theirs):
        if k == "name":
            m.name = theirs[1]
        else:
            m.attrs = [a for a in m.attrs if f"attr:{a.name}" != k] + (theirs[1] if theirs else [])

    def decl_text(self, it) -> str:
        mm = Module(1, "x", items=[it])
        return print_module(mm)

    def find_decl(self, m: Module, k) -> Optional[object]:
        return next((x for x in m.items if key_of(x, decl_kind(x)) == k), None)

    def merge_decl(self, b, o, t):
        kref = [key_of(o, decl_kind(o))]   # the merged declaration's key, set below
        where = o.name

        def setter(m, fk, theirs):
            it = self.find_decl(m, kref[0])
            if it is None:
                return
            fields = decl_fields(it, comments=True)
            if theirs is None:
                fields.pop(fk, None)
            else:
                fields[fk] = theirs
            new = build_decl(it, fields)
            m.items[m.items.index(it)] = new
        df = lambda x: decl_fields(x, comments=True) if x is not None else None
        fields = self.merge_fields(df(b), df(o), df(t), where, setter)
        it = build_decl(o, fields)
        kref[0] = key_of(it, decl_kind(it))
        k = kref[0]
        it.meta = self.merge_meta(b.meta if b else [], o.meta, t.meta, where,
                                  lambda m: self.find_decl(m, kref[0]))
        subs = []
        if isinstance(it, (Graph, Extern)):
            subs += [("params", "param"), ("results", "result")]
        if isinstance(it, Graph):
            subs += [("locals", "local"), ("states", "state")]
        if isinstance(it, (Struct, Class)):
            subs.append(("fields", "field"))
        if isinstance(it, Interface):
            subs.append(("methods", "method"))
        if isinstance(it, Class):
            subs.append(("dispatchers", "dispatcher"))
        if isinstance(it, Enum):
            subs.append(("members", "member"))
        for attr, kind in subs:
            vb = (getattr(b, attr) or []) if b else []
            merged = self.merge_subs(vb, getattr(o, attr) or [], getattr(t, attr) or [],
                                     f"{where}.{attr}", k, attr)
            if attr == "results" and not fields["arrow"][1]:
                merged = None if not merged else merged
            setattr(it, attr, merged)
        if isinstance(it, Graph):
            self.merge_body(b, o, t, it)
        return it

    def merge_subs(self, b, o, t, where, decl_key, attr) -> list:
        def merge_one(xb, xo, xt):
            sk = key_of(xo)

            def setter(m, fk, theirs):
                it = self.find_decl(m, decl_key)
                lst = getattr(it, attr, None) if it is not None else None
                x = next((y for y in lst or [] if key_of(y) == sk), None)
                if x is None:
                    return
                f = sub_fields(x, comments=True)
                if theirs is None:
                    f.pop(fk, None)
                else:
                    f[fk] = theirs
                lst[lst.index(x)] = build_sub(x, f)
            sf = lambda x: sub_fields(x, comments=True) if x is not None else None
            f = self.merge_fields(sf(xb), sf(xo), sf(xt), f"{where}.{xo.name}", setter)
            x = build_sub(xo, f)
            if hasattr(x, "meta"):
                x.meta = self.merge_meta(getattr(xb, "meta", []) if xb else [], xo.meta, xt.meta,
                                         f"{where}.{xo.name}", lambda m: None)
            return x

        def changed(x, y):
            return sub_fields(x, comments=True) != sub_fields(y, comments=True)

        def conflict(kept, side, k, deleter):
            name = (kept or side).name
            self.conflicts.append(Conflict(f"{where}.{name}",
                                           f"deleted in {deleter}, changed in the other",
                                           lambda m: None))
        return self.merge_keyed(b, o, t, key_of, where, merge_one, changed, conflict,
                                name_key=lambda x: ("", x.name))

    # graph bodies ----------------------------------------------------------------------
    def single_outs(self, m: Module, g: Optional[Graph]) -> dict:
        if g is None:
            return {}
        idx = self.idx.get(id(m)) or ModuleIndex(m)
        out = {}
        for n in g.nodes:
            sig = signature(n, g, idx)
            outs = sig.exec_outs
            out[n.id] = outs[0].name if len(outs) == 1 else None
        return out

    def merge_body(self, b: Optional[Graph], o: Graph, t: Graph, g: Graph):
        name = g.name
        so, st, sb = (self.single_outs(self.o, o), self.single_outs(self.t, t),
                      self.single_outs(self.b, b))
        gk = key_of(g, g.kind)            # the merged graph's key (it may have gained an @id)

        def graph_in(m):
            it = self.find_decl(m, gk)
            return it if isinstance(it, Graph) else None

        def nf(n, singles):
            return node_fields(n, singles.get(n.id), comments=True)

        def merge_one(nb, no, nt):
            nid = no.id

            def setter(m, fk, theirs):
                gg = graph_in(m)
                n = gg.node(nid) if gg else None
                if n is None:
                    return
                f = node_fields(n, None, comments=True)
                if theirs is None:
                    f.pop(fk, None)
                else:
                    f[fk] = theirs
                gg.nodes[gg.nodes.index(n)] = build_node(n, f)
            f = self.merge_fields(nf(nb, sb) if nb else None, nf(no, so), nf(nt, st),
                                  f"{name}.{nid}", setter)
            n = build_node(no, f)
            n.meta = self.merge_meta(nb.meta if nb else [], no.meta, nt.meta, f"{name}.{nid}",
                                     lambda m: (graph_in(m).node(nid) if graph_in(m) else None))
            return n

        def changed(x, y):
            sx = so if x in o.nodes else (st if x in t.nodes else sb)
            sy = so if y in o.nodes else (st if y in t.nodes else sb)
            return nf(x, sx) != nf(y, sy) or [meta_text(a) for a in x.meta] != \
                [meta_text(a) for a in y.meta]

        def conflict(kept, side, k, deleter):
            nid = (kept or side).id
            if deleter == "ours":
                def apply(m, n=side):
                    gg = graph_in(m)
                    if gg is not None:
                        gg.nodes.append(copy.deepcopy(n))
            else:
                def apply(m, nid=nid):
                    gg = graph_in(m)
                    if gg is not None:
                        gg.nodes = [n for n in gg.nodes if n.id != nid]
            self.conflicts.append(Conflict(f"{name}.{nid}",
                                           f"node deleted in {deleter}, changed in the other",
                                           apply))
        g.nodes = self.merge_keyed(b.nodes if b else [], o.nodes, t.nodes, lambda n: n.id,
                                   name, merge_one, changed, conflict)
        g.meta = self.merge_meta(b.meta if b else [], o.meta, t.meta, name, graph_in)
        self.merge_layout(b, o, t, g)

    def merge_layout(self, b: Optional[Graph], o: Graph, t: Graph, g: Graph):
        """Places and boxes merge per property; a disagreement never blocks the merge:
        theirs wins and a notice is printed (section 7.1)."""
        name = g.name
        ids = {n.id for n in g.nodes}

        def pfields(p) -> dict:
            out = {"at": (f"{p.x},{p.y}", (p.x, p.y))}
            for k, v in p.props:
                if k != "members":
                    out[f"prop:{k}"] = (fmt_lit(v), v)
            if isinstance(p, Box):
                out["title"] = (p.title, p.title)
                out["size"] = (f"{p.w},{p.h}", (p.w, p.h))
            return out

        def merge3(fb, fo, ft, where) -> dict:
            out = {}
            for k in sorted(set(fb) | set(fo) | set(ft)):
                vb, vo, vt = fb.get(k), fo.get(k), ft.get(k)
                tb, to, tt = (x[0] if x else None for x in (vb, vo, vt))
                if to == tt or to == tb:
                    pick = vt if to == tb else vo
                elif tt == tb:
                    pick = vo
                else:
                    pick = vt
                    self.notices.append(f"{where}: {k.split(':')[-1]} changed on both sides; "
                                        f"theirs is kept")
                if pick is not None:
                    out[k] = pick
            return out

        def build(proto, f, members=None):
            p = copy.deepcopy(proto)
            p.x, p.y = f["at"][1]
            p.props = [(k.split(":", 1)[1], v[1]) for k, v in f.items() if k.startswith("prop:")]
            if isinstance(p, Box):
                p.title = f["title"][1]
                p.w, p.h = f["size"][1]
                if members is not None:
                    p.props.append(("members", Lit("list", [Lit("ident", x) for x in members])))
            return p

        bp = {p.id: p for p in (b.places if b else [])}
        op_ = {p.id: p for p in o.places}
        tp = {p.id: p for p in t.places}
        places = []
        for nid in sorted(ids):
            pb, po, pt = bp.get(nid), op_.get(nid), tp.get(nid)
            if po is None and pt is None:
                continue
            proto = po or pt
            f = merge3(pfields(pb) if pb else {}, pfields(po) if po else {},
                       pfields(pt) if pt else {}, f"{name}.{nid}")
            if "at" in f:
                places.append(build(proto, f))
        # stale layout lines (W0605) are kept from both sides; theirs wins on a clash
        stale = {p.id: p for side in (o, t) for p in side.places if p.id not in ids}
        places.extend(stale[k] for k in sorted(stale))
        g.orphan_meta = {k: v for side in (o, t) for k, v in side.orphan_meta.items()
                         if k not in ids}
        g.places = places
        bb = {x.id: x for x in (b.boxes if b else [])}
        ob = {x.id: x for x in o.boxes}
        tb = {x.id: x for x in t.boxes}
        boxes = []
        for bid in sorted(set(ob) | set(tb)):
            xb, xo, xt = bb.get(bid), ob.get(bid), tb.get(bid)
            if xb is not None and (xo is None or xt is None):
                continue          # deleted on one side: layout never blocks, the delete wins
            f = merge3(pfields(xb) if xb else {}, pfields(xo) if xo else {},
                       pfields(xt) if xt else {}, f"{name}.box {bid}")
            mb = set(xb.members()) if xb else set()
            mo = set(xo.members()) if xo else set()
            mt = set(xt.members()) if xt else set()
            members = sorted(((mo | mt) - (mb - mo) - (mb - mt)))
            box = build(xo or xt, f, members)
            box.meta = self.merge_meta(xb.meta if xb else [], xo.meta if xo else [],
                                       xt.meta if xt else [], f"{name}.box {bid}", lambda m: None)
            boxes.append(box)
        g.boxes = boxes

    # renames ---------------------------------------------------------------------------
    def carry_renames(self, m: Module):
        """An element renamed on one side, matched by @id, keeps its new name; references
        that the other side added under the old name are rewritten (section 7.4)."""
        from .ids import elements
        from .rename import RenameError, rename_element
        base = {e.id: e for e in elements(self.b) if e.id}
        for e in list(elements(m)):
            old = base.get(e.id)
            if old is None or old.name == e.name or e.kind == "module":
                continue
            new = e.name
            e.obj.name = old.name
            try:
                rename_element(m, type(e)(e.kind, old.name, e.owner, e.obj), new)
            except RenameError:
                e.obj.name = new


# -- driver ------------------------------------------------------------------------------
def merge_texts(base: str, ours: str, theirs: str) -> MergeResult:
    try:
        mb, mo, mt = parse(base), parse(ours), parse(theirs)
    except ParseError:
        return text_merge(base, ours, theirs)
    mg = Merger(mb, mo, mt)
    merged = mg.merge()
    text = print_module(merged)
    semantic = []
    try:
        reparsed = parse(text)
        seen = {(d.code, d.graph, d.node, d.pin) for side in (mo, mt) for d in check(side)}
        semantic = [d for d in check(reparsed) if d.severity == "error"
                    and (d.code, d.graph, d.node, d.pin) not in seen]
    except ParseError as e:
        semantic = [f"the merged text does not parse: {e}"]
    if mg.conflicts:
        text = with_markers(merged, mg.conflicts)
    return MergeResult(text, mg.conflicts, semantic, mg.notices)


def with_markers(merged: Module, conflicts: list) -> str:
    """Write each conflict as markers around the lines where ours and theirs differ."""
    lines = print_module(merged).splitlines(True)
    regions = []
    for c in conflicts:
        alt = copy.deepcopy(merged)
        c.set_theirs(alt)
        alt_lines = print_module(alt).splitlines(True)
        ops = [op for op in difflib.SequenceMatcher(a=lines, b=alt_lines,
                                                    autojunk=False).get_opcodes()
               if op[0] != "equal"]
        if not ops:
            continue
        i1, i2 = ops[0][1], ops[-1][2]
        j1, j2 = ops[0][3], ops[-1][4]
        regions.append((i1, i2, alt_lines[j1:j2], c))
    out = list(lines)
    last = None
    for i1, i2, theirs, c in sorted(regions, key=lambda r: (r[0], r[1]), reverse=True):
        if last is not None and i2 > last:
            continue                   # overlaps a region already marked
        block = ([f"<<<<<<< ours ({c.where})\n"] + lines[i1:i2] + ["=======\n"] + theirs +
                 [">>>>>>> theirs\n"])
        out[i1:i2] = block
        last = i1
    return "".join(out)


def text_merge(base: str, ours: str, theirs: str) -> MergeResult:
    """A side does not parse: fall back to a plain line merge (`git merge-file`)."""
    with tempfile.TemporaryDirectory() as d:
        paths = []
        for name, text in (("ours", ours), ("base", base), ("theirs", theirs)):
            p = os.path.join(d, name)
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            paths.append(p)
        try:
            r = subprocess.run(["git", "merge-file", "-p", "-L", "ours", "-L", "base", "-L",
                                "theirs"] + paths, capture_output=True, text=True,
                               encoding="utf-8")
        except FileNotFoundError:
            return MergeResult(ours, [Conflict("file", "a side does not parse and git is not "
                                                       "available for a text merge",
                                               lambda m: None)], fallback=True)
    conflicts = [] if r.returncode == 0 else [
        Conflict("file", f"{r.returncode} text conflict(s) in a plain line merge",
                 lambda m: None)]
    return MergeResult(r.stdout, conflicts, fallback=True)
