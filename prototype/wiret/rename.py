"""Rename a declaration, parameter, result, field, enum member, local or state slot and
rewrite every reference to it (the `rename` edit operation, section 7.2). The merge uses
the same rewrite to carry a rename on one side into the other side's additions (7.1)."""
from __future__ import annotations

import re
from typing import Optional

from .ids import Element, elements
from .model import Graph, Lit, Module, PinRef
from .parser import RESERVED

IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")


class RenameError(Exception):
    pass


def find_element(m: Module, token: str) -> Optional[Element]:
    return next((e for e in elements(m) if e.id == token), None)


def _retype(ty: str, old: str, new: str) -> str:
    return re.sub(rf"(?<![A-Za-z0-9_.]){re.escape(old)}(?![A-Za-z0-9_])", new, ty)


def _lits(m: Module):
    """Every literal that may hold an enum value: bindings, defaults, consts, @cases."""
    for it in m.items:
        for attr in ("default", "value"):
            v = getattr(it, attr, None)
            if isinstance(v, Lit):
                yield it, attr
        for p in list(getattr(it, "params", []) or []) + list(getattr(it, "results", []) or []):
            if p.default is not None:
                yield p, "default"
        for f in getattr(it, "fields", []) or []:
            if f.default is not None:
                yield f, "default"
        if isinstance(it, Graph):
            for loc in it.locals + it.states:
                if loc.default is not None:
                    yield loc, "default"
            for n in it.nodes:
                for b in n.bindings:
                    if isinstance(b.value, Lit):
                        yield b, "value"


def _cases(m: Module):
    for g in m.graphs():
        for n in g.nodes:
            a = n.attr("cases")
            if n.kind == "Switch" and a and a.args:
                yield a


def _typed(m: Module):
    """Every object with a `.type`, and every node, for rewriting type names."""
    for it in m.items:
        if hasattr(it, "type"):
            yield it
        for p in list(getattr(it, "params", []) or []) + list(getattr(it, "results", []) or []):
            yield p
        for f in getattr(it, "fields", []) or []:
            yield f
        if isinstance(it, Graph):
            yield from it.locals
            yield from it.states


def _calls(m: Module, kinds: tuple, name: str):
    """(graph, node) for nodes of `kinds` whose symbol names `name` (or module.name)."""
    full = f"{m.name}.{name}"
    for g in m.graphs():
        for n in g.nodes:
            if n.kind in kinds and n.symbol in (name, full):
                yield g, n


def rename(m: Module, token: str, new: str) -> list:
    """Rename the element with `@id` `token` to `new`. Returns a description of every
    reference rewritten. Raises RenameError when the rename is not possible."""
    e = find_element(m, token)
    if e is None:
        raise RenameError(f"no element has @id '{token}'")
    return rename_element(m, e, new)


def rename_element(m: Module, e: Element, new: str) -> list:
    old = e.name
    if not IDENT.match(new) or new in RESERVED:
        raise RenameError(f"'{new}' is not a valid name")
    if new == old:
        return []
    if e.kind == "module":
        raise RenameError("renaming a module moves its file; it is not an edit operation")
    siblings = {x.name for x in elements(m) if x.owner == e.owner and x.kind != "module"
                and _same_namespace(x.kind, e.kind)}
    if new in siblings:
        raise RenameError(f"'{new}' is already used next to '{old}'")
    out = []
    owner = next((it for it in m.items if it.name == e.owner), None) if e.owner else None
    kind = e.kind
    if kind in ("func", "event", "macro"):
        e.obj.name = new
        for g, n in _calls(m, ("Call", "Macro"), old):
            n.symbol = new
            out.append(f"{g.name}.{n.id}")
    elif kind == "extern":
        raise RenameError("an extern's name is the host's; rename it on the host side")
    elif kind in ("var", "const"):
        e.obj.name = new
        for g in m.graphs():
            for n in g.nodes:
                if n.symbol == old and (n.kind in ("GetVar", "SetVar") or
                                        _is_place(n) and g.local(old) is None):
                    n.symbol = new
                    out.append(f"{g.name}.{n.id}")
    elif kind in ("struct", "enum"):
        e.obj.name = new
        for x in _typed(m):
            t = _retype(x.type, old, new)
            if t != x.type:
                x.type = t
                out.append(f"type of {getattr(x, 'name', '?')}")
        for g in m.graphs():
            for n in g.nodes:
                targs = [_retype(t, old, new) for t in n.targs]
                if targs != n.targs:
                    n.targs = targs
                    out.append(f"{g.name}.{n.id}")
                if kind == "struct" and n.kind in ("MakeStruct", "BreakStruct", "GetField",
                                                   "WithField") and n.symbol:
                    head, dot, rest = n.symbol.partition(".")
                    if head == old:
                        n.symbol = new + dot + rest
                        out.append(f"{g.name}.{n.id}")
        if kind == "enum":
            out += _rename_enum_values(m, lambda en, mem: en == old, lambda en, mem: (new, mem))
    elif kind == "member":
        e.obj.name = new
        out += _rename_enum_values(m, lambda en, mem: en == e.owner and mem == old,
                                   lambda en, mem: (en, new))
    elif kind == "field":
        e.obj.name = new
        st = e.owner
        for g in m.graphs():
            for n in g.nodes:
                if n.kind in ("GetField", "WithField") and n.symbol == f"{st}.{old}":
                    n.symbol = f"{st}.{new}"
                    out.append(f"{g.name}.{n.id}")
                if n.kind == "MakeStruct" and n.symbol == st:
                    out += _rename_binding(g, n, old, new)
            breaks = {n.id for n in g.nodes if n.kind == "BreakStruct" and n.symbol == st}
            out += _rename_refs(g, breaks, old, new)
    elif kind in ("param", "result"):
        out += _rename_signature_pin(m, owner, e, old, new)
    elif kind in ("local", "state"):
        e.obj.name = new
        get, set_ = ("GetLocal", "SetLocal") if kind == "local" else ("GetState", "SetState")
        for n in owner.nodes:
            if n.symbol == old and (n.kind in (get, set_) or (kind == "local" and _is_place(n))):
                n.symbol = new
                out.append(f"{owner.name}.{n.id}")
    else:
        raise RenameError(f"a {kind} cannot be renamed")
    return out


def _same_namespace(a: str, b: str) -> bool:
    top = {"use", "extern", "const", "var", "enum", "struct", "func", "event", "macro"}
    if a in top and b in top:
        return True
    pins = {"param", "result"}
    return a == b or (a in pins and b in pins)


def _is_place(n) -> bool:
    from .registry import PLACE_MUTATORS
    return n.kind in PLACE_MUTATORS


def _rename_binding(g: Graph, n, old: str, new: str) -> list:
    out = []
    for b in n.bindings:
        if b.pin == old:
            b.pin = new
            out.append(f"{g.name}.{n.id}.{old}")
    return out


def _rename_refs(g: Graph, sources: set, old: str, new: str) -> list:
    """Rewrite pin references `src.old` to `src.new` for nodes in `sources`."""
    out = []
    for n in g.nodes:
        for b in n.bindings:
            if isinstance(b.value, PinRef) and b.value.node in sources and b.value.pin == old:
                b.value = PinRef(b.value.node, new)
                out.append(f"{g.name}.{n.id}.{b.pin}")
    return out


def _rename_execs(g: Graph, sources: set, old: str, new: str) -> list:
    out = []
    for n in g.nodes:
        for x in n.execs:
            if n.id in sources and x.pin == old:
                x.pin = new
                out.append(f"{g.name}.{n.id}.{old}")
    return out


def _rename_exec_targets(g: Graph, targets: set, old: str, new: str) -> list:
    out = []
    for n in g.nodes:
        for x in n.execs:
            if x.target in targets and x.target_pin == old:
                x.target_pin = new
                out.append(f"{g.name}.{n.id} -> {x.target}")
    return out


def _rename_signature_pin(m: Module, g, e: Element, old: str, new: str) -> list:
    """A parameter or result of a graph (or of an extern, which has no body)."""
    out = []
    p = e.obj
    p.name = new
    if not isinstance(g, Graph):
        return out
    is_exec = p.type == "exec"
    if e.kind == "param":
        entries = {n.id for n in g.nodes if n.kind == "Entry"}
        out += (_rename_execs(g, entries, old, new) if is_exec
                else _rename_refs(g, entries, old, new))
        for cg, n in _calls(m, ("Call", "Macro"), g.name):
            out += (_rename_exec_targets(cg, {n.id}, old, new) if is_exec
                    else _rename_binding(cg, n, old, new))
    else:
        for n in g.nodes:
            if n.kind == "Return" or (n.kind in ("Exit", "Leave") and not is_exec):
                out += _rename_binding(g, n, old, new)
            if n.kind in ("Exit", "Leave") and is_exec and n.symbol == old:
                n.symbol = new
                out.append(f"{g.name}.{n.id}")
        for cg, n in _calls(m, ("Call", "Macro"), g.name):
            out += (_rename_execs(cg, {n.id}, old, new) if is_exec
                    else _rename_refs(cg, {n.id}, old, new))
    return out


def _rename_enum_values(m: Module, match, change) -> list:
    out = []

    def fix(lit: Lit) -> Optional[Lit]:
        if lit.kind not in ("enum", "ident") or lit.value.count(".") != 1:
            return None
        en, mem = lit.value.split(".")
        if not match(en, mem):
            return None
        en2, mem2 = change(en, mem)
        return Lit(lit.kind, f"{en2}.{mem2}")

    for obj, attr in _lits(m):
        lit = getattr(obj, attr)
        new = fix(lit) if lit.kind == "enum" else None
        if new is not None:
            setattr(obj, attr, new)
            out.append(f"value {new.value}")
    for a in _cases(m):
        args = []
        for k, v in a.args:
            new = fix(v) if v.kind == "enum" else None
            args.append((k, new or v))
            if new is not None:
                out.append(f"case {new.value}")
        a.args = args
    return out
