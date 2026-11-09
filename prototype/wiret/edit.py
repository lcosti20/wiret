"""`wiretc edit`: the editing protocol for tools and LLMs (spec section 7.2).

A request is JSON: `{"if_hash": "<layout hash>", "ops": [ ... ]}`. Each op is an object with
an `"op"` field. Values for inputs are written exactly as on the right of `<-` in the text
(`"plus.result"`, `"5"`, `"\\"hi\\""`, `"Mode.Chase"`), attributes as they are written
(`"@count(3)"`, `"#[doc(\\"Adds one.\\")]"`). The whole request is applied to a copy of the
model; if any op fails, nothing changes. A stale `if_hash` is E0900.
"""
from __future__ import annotations

import copy
import difflib
import json
from dataclasses import dataclass, field
from typing import Optional

from .checker import check
from .ids import Project, attach_retired, retired_between
from .model import Attr, Enum, Graph, Lit, Module, PinRef
from .ops import (bind, create_node, delete_node, place, rename_node, unbind, unwire_exec,
                  wire_exec)
from .parser import ParseError, Parser, parse, resolve_enum_values
from .printer import layout_hash, print_module
from .registry import ModuleIndex, signature
from .rename import RenameError, rename


class EditError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class EditResult:
    ok: bool
    text: str
    hash: str
    diagnostics: list = field(default_factory=list)
    diff: str = ""
    error: Optional[dict] = None
    removed: list = field(default_factory=list)     # wires removed by a cascading delete
    retired: list = field(default_factory=list)     # ids appended to wiret.ids

    def to_json(self) -> dict:
        out = {"ok": self.ok, "hash": self.hash,
               "diagnostics": [json.loads(d.to_json()) for d in self.diagnostics],
               "diff": self.diff}
        if self.error:
            out["error"] = self.error
        if self.removed:
            out["removed_wires"] = self.removed
        if self.retired:
            out["retired"] = [r.line() for r in self.retired]
        return out


def apply_request(text: str, request: dict, project: Optional[Project] = None) -> EditResult:
    """Apply an edit request to a document's text. Never raises for a bad request."""
    cur_hash = ""
    try:
        m = parse(text)
        cur_hash = layout_hash(m)
    except ParseError as e:
        return EditResult(False, text, "", error={"code": "parse", "message": str(e)})
    want = request.get("if_hash")
    if want != cur_hash:
        return EditResult(False, text, cur_hash, error={
            "code": "E0900", "message": "the document changed since the hash this edit was "
                                        "based on; read it again"})
    new = copy.deepcopy(m)
    removed = []
    for i, op in enumerate(request.get("ops") or []):
        try:
            removed += apply_op(new, op) or []
        except EditError as e:
            return EditResult(False, text, cur_hash,
                              error={"op": i, "code": e.code, "message": e.message})
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            return EditResult(False, text, cur_hash,
                              error={"op": i, "code": "request", "message": f"bad op: {e!r}"})
    attach_retired(new, project)
    out = print_module(new)
    try:
        reparsed = parse(out)
    except ParseError as e:             # an op produced something the text cannot hold
        return EditResult(False, text, cur_hash, error={"code": "request",
                                                        "message": f"result does not parse: {e}"})
    retired = []
    if project is not None:
        retired = project.retire(retired_between(m, reparsed))
    diff = "".join(difflib.unified_diff(text.splitlines(True), out.splitlines(True),
                                        "before", "after"))
    return EditResult(True, out, layout_hash(reparsed), check(reparsed, project=project), diff,
                      removed=removed, retired=retired)


# -- operations ------------------------------------------------------------------------
def graph_of(m: Module, op: dict) -> Graph:
    name = op.get("graph")
    g = m.graph(name) if name else None
    if g is None:
        raise EditError("E0501", f"no graph '{name}'")
    return g


def node_of(g: Graph, nid: str):
    n = g.node(nid)
    if n is None:
        raise EditError("E0101", f"no node '{nid}' in {g.name}")
    return n


def value_of(m: Module, g: Graph, text: str):
    """The right-hand side of `.pin <- text`: a pin reference or a literal."""
    p = Parser(str(text))
    p.skip_nl()
    if p.at("id") and p.at_p(".", 1) and p.at("id", k=2):
        j = p.i
        node, _, pin = p.qname().rpartition(".")  # an inline node's name has dots too
        if not p.at("nl") and not p.at("eof"):
            p.i = j
            raise EditError("request", f"unexpected text after '{text}'")
        enums = {it.name for it in m.items if isinstance(it, Enum)}
        if g.node(node) is None and node in enums:   # the parser's rule (section 2.3)
            return Lit("enum", f"{node}.{pin}")
        return PinRef(node, pin)
    try:
        lit = p.literal()
    except ParseError as e:
        raise EditError("request", f"'{text}' is neither a pin reference nor a literal: {e.msg}")
    p.skip_nl()
    if not p.at("eof"):
        raise EditError("request", f"unexpected text after '{text}'")
    return lit


def attr_of(text: str, meta: bool) -> Attr:
    """`@name(args)` or `#[name(args)]`."""
    src = str(text).strip()
    p = Parser(src + "\n")
    p.skip_nl()
    try:
        if meta:
            if not src.startswith("#["):
                raise EditError("request", f"metadata is written #[name(...)], not '{src}'")
            p.next()                               # the #[
            name = p.qname()
            a = Attr(name, p.attr_args() if p.at_p("(") else None)
            p.expect_p("]")
            return a
        if not src.startswith("@"):
            raise EditError("request", f"a semantic attribute is written @name(...), not '{src}'")
        attrs = p.attrs()
        if len(attrs) != 1:
            raise EditError("request", f"expected one attribute in '{src}'")
        return attrs[0]
    except ParseError as e:
        raise EditError("request", f"'{src}': {e.msg}")


def target_of(m: Module, op: dict):
    """What an attribute op changes: a node or box (`graph` + `node`), a graph (`graph`),
    or another declaration (`decl`)."""
    if "decl" in op:
        it = next((it for it in m.items if it.name == op["decl"]), None)
        if it is None:
            raise EditError("E0501", f"no declaration '{op['decl']}'")
        return it
    g = graph_of(m, op)
    if "node" in op:
        t = g.node(op["node"]) or g.box(op["node"])
        if t is None:
            raise EditError("E0101", f"no node or box '{op['node']}' in {g.name}")
        return t
    return g


def exec_end(text: str):
    node, _, pin = str(text).partition(".")
    return node, pin or None


def single_exec_out(m: Module, g: Graph, n) -> Optional[str]:
    sig = signature(n, g, ModuleIndex(m))
    return sig.exec_outs[0].name if len(sig.exec_outs) == 1 else None


def apply_op(m: Module, op: dict) -> list:
    kind = op.get("op")
    if kind == "create_node":
        g = graph_of(m, op)
        nid = op.get("id")
        if nid is not None and (g.node(nid) or g.box(nid)):
            raise EditError("E0102", f"'{nid}' is already used in {g.name}")
        n = create_node(g, op["kind"], op.get("symbol"), op.get("targs"), op.get("x", 0),
                        op.get("y", 0), nid)
        for a in op.get("attrs", []):
            n.attrs.append(attr_of(a, meta=False))
        for pin, value in (op.get("bindings") or {}).items():
            bind(g, n.id, pin, value_of(m, g, value))
        for pin, target in (op.get("execs") or {}).items():
            t, tpin = exec_end(target)
            wire_exec(g, n.id, pin or single_exec_out(m, g, n), t, tpin,
                      single_exec_out(m, g, n))
        op["id"] = n.id
        return []
    if kind in ("bind", "unbind"):
        g = graph_of(m, op)
        node_of(g, op["node"])
        if kind == "bind":
            bind(g, op["node"], op["pin"], value_of(m, g, op["value"]))
        else:
            unbind(g, op["node"], op["pin"])
        return []
    if kind in ("wire_exec", "unwire_exec"):
        g = graph_of(m, op)
        src, pin = exec_end(op["from"])
        n = node_of(g, src)
        single = single_exec_out(m, g, n)
        pin = pin or single
        if pin is None:
            raise EditError("E0103", f"'{src}' has several exec outputs; name one, as in "
                                     f"'{src}.then'")
        if kind == "wire_exec":
            t, tpin = exec_end(op["to"])
            node_of(g, t)
            wire_exec(g, src, pin, t, tpin, single)
        else:
            unwire_exec(g, src, pin, single)
        return []
    if kind in ("set_attr", "remove_attr"):
        t = target_of(m, op)
        if kind == "set_attr":
            a = attr_of(op["attr"], meta=False)
            t.attrs = [x for x in t.attrs if x.name != a.name] + [a]
        else:
            name = str(op["name"]).lstrip("@")
            t.attrs = [x for x in t.attrs if x.name != name]
        return []
    if kind in ("set_meta", "remove_meta"):
        t = target_of(m, op)
        if kind == "set_meta":
            a = attr_of(op["meta"], meta=True)
            if a.name == "note":
                t.meta.append(a)            # a target may carry any number of notes
            else:
                t.meta = [x for x in t.meta if x.name != a.name] + [a]
        else:
            name, text_ = str(op["name"]).lstrip("#[").rstrip("]"), op.get("text")
            t.meta = [x for x in t.meta if not (x.name == name and (
                text_ is None or (x.arg() is not None and x.arg().value == text_)))]
        return []
    if kind == "place":
        g = graph_of(m, op)
        nid = op["node"]
        if g.node(nid) is None and g.box(nid) is None:
            raise EditError("E0101", f"no node or box '{nid}' in {g.name}")
        cur = g.box(nid) or g.place(nid)
        place(g, nid, op.get("x", cur.x if cur else 0), op.get("y", cur.y if cur else 0))
        target = g.box(nid) or g.place(nid)
        for key, value in (op.get("props") or {}).items():
            target.set_prop(key, None if value is None else _prop_value(value))
        if "members" in op:
            if g.box(nid) is None:
                raise EditError("request", f"'{nid}' is not a box")
            target.set_prop("members", Lit("list", [Lit("ident", x) for x in op["members"]]))
        return []
    if kind == "delete_node":
        g = graph_of(m, op)
        nid = op["node"]
        node_of(g, nid)
        refs = [f"{n.id}.{b.pin}" for n in g.nodes for b in n.bindings
                if isinstance(b.value, PinRef) and b.value.node == nid]
        refs += [f"{n.id} -> {nid}" for n in g.nodes for x in n.execs if x.target == nid]
        if refs and not op.get("cascade"):
            raise EditError("request", f"'{nid}' is still wired to {', '.join(refs)}; set "
                                       f"cascade to remove those wires too")
        return delete_node(g, nid)
    if kind == "rename":
        if "id" in op:
            try:
                rename(m, op["id"], op["to"])
            except RenameError as e:
                raise EditError("request", str(e))
            resolve_enum_values(m)
            return []
        g = graph_of(m, op)
        node_of(g, op["node"])
        if g.node(op["to"]) or g.box(op["to"]):
            raise EditError("E0102", f"'{op['to']}' is already used in {g.name}")
        rename_node(g, op["node"], op["to"])
        return []
    raise EditError("request", f"unknown op '{kind}'")


def _prop_value(text: str) -> Lit:
    p = Parser(str(text))
    p.skip_nl()
    return p.value()
