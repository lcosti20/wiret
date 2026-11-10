"""Resolver, type checker and graph validator (spec sections 4.3 and 4.7)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Optional

from .model import Enum, Graph, Lit, Module, Node, PinRef, SEMANTIC_ATTRS, Struct, note_detached, notes
from .model import Const, Extern, Var

# Names that are metadata, not semantic attributes: `@doc` is `#[doc]` (section 2.4).
META_NAMES = {"doc", "category", "keywords", "note"}
from .registry import (HANDLE_TYPES, assignable, field_place, handle_ok, parent_method, BUILTIN_TYPE_NAMES, PLACE_MUTATORS, INT_RANGES, ModuleIndex, Sig,
                       array_elem, enum_values, instantiate, lit_fits, lit_in_range, signature,
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


def check(module: Module, comments_ok=False, project=None) -> list:
    """Every diagnostic for a module. With a `project` (wiret.ids.Project), also the identity
    checks that need the project's id registry: E0140 and W0202 (section 2.4)."""
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
        if isinstance(it, (Var, Const)):
            typed.append(it)
        for p in typed:
            ty = substitute(p.type, {t: "i32" for t in tparams})
            if ty != "exec" and not handle_ok(ty, idx):
                D("E0501", unknown_type_message(p.type, module.name),
                  getattr(it, "name", None), type=p.type)
                continue
            default = p.value if isinstance(p, Const) else p.default
            if default is not None and default.kind == "enum":
                if check_enum_value(default, idx, D, getattr(it, "name", None), pin=p.name) \
                        and not lit_fits(default, ty):
                    D("E0110", f"default of '{p.name}' is a {default.value.split('.')[0]} value, "
                               f"not {ty}", getattr(it, "name", None), pin=p.name, literal=True,
                      dst=ty)
            elif default is not None and not (lit_fits(default, ty, idx)
                                              and lit_in_range(default, ty)):
                # a const, var, parameter, local or state initialiser (E0110), including a
                # vector tuple of the wrong length (section 3.1.1)
                D("E0110", f"the value of '{p.name}' does not fit type {ty}",
                  getattr(it, "name", None), pin=p.name, literal=True, dst=ty)
    check_type_decls(module, idx, D)
    check_attr_names(module, D)
    check_capabilities(module, project, D)
    if project is not None:
        from .ids import check_ids
        check_ids(module, project, D)
    for owner in [module] + [i for i in module.items if not isinstance(i, Graph)]:
        for nt in notes(owner.meta):
            if note_detached(nt) is not None:
                D("W0604", f"a note is detached from '{note_detached(nt)}', which was deleted",
                  getattr(owner, "name", None) if owner is not module else None)
    if module.comments and not comments_ok:
        for c in module.comments:
            D("W0603", f"line {c.line}: this '//' comment is not directly above a statement, "
                       f"input or flow wire, so it is attached to nothing and would be dropped; "
                       f"move it above what it explains, or convert it to a note")

    for g in module.graphs():
        if g.tparams:   # check a generic macro through one instance of it
            check_graph(instantiate(g, ["i32"] * len(g.tparams)), idx, D)
        else:
            check_graph(g, idx, D)
    check_macro_recursion(module, idx, D)
    return diags


def unknown_type_message(ty: str, module_name: str) -> str:
    if "dispatcher::<" in ty:
        return (f"type '{ty}': a dispatcher is declared as a class member, "
                f"'dispatcher OnDied(amount: i32)', and is not a type you can store")
    if any(h in ty for h in HANDLE_TYPES) and ty not in HANDLE_TYPES:
        return (f"type '{ty}': a signal can be a parameter, result, local, state or variable, "
                f"but not a struct field or an item in an array, map or set")
    prefix = module_name + "."
    base = array_elem(ty) or ty
    if base.startswith(prefix):
        return (f"type '{ty}' names a type of this module with its module prefix; "
                f"write '{ty.replace(prefix, '')}'")
    return f"unknown type '{ty}': not a built-in type, struct or enum of this module"


def check_type_decls(module: Module, idx: ModuleIndex, D):
    """Struct and enum declarations (sections 2.2 and 3.1)."""
    for it in module.items:
        if not isinstance(it, (Struct, Enum)):
            continue
        kind = "struct" if isinstance(it, Struct) else "enum"
        if it.name in BUILTIN_TYPE_NAMES:
            D("E0102", f"{kind} '{it.name}' has the name of a built-in type; choose another name",
              it.name)
        members = it.fields if isinstance(it, Struct) else it.members
        seen = set()
        for x in members:
            if x.name in seen:
                what = "field" if kind == "struct" else "member"
                D("E0102", f"duplicate {what} '{x.name}' in {kind} '{it.name}'", it.name,
                  pin=x.name)
            seen.add(x.name)
        if isinstance(it, Struct):
            for f in it.fields:
                if f.type == "exec":
                    D("E0501", f"field '{it.name}.{f.name}' cannot have type exec: exec is only "
                               f"for macro parameters", it.name, pin=f.name, type=f.type)
                elif not type_ok(f.type, idx):
                    D("E0501", unknown_type_message(f.type, module.name), it.name, pin=f.name,
                      type=f.type)
                elif f.default is not None and f.default.kind == "enum" and \
                        not check_enum_value(f.default, idx, D, it.name, pin=f.name):
                    pass
                elif f.default is not None and not (lit_fits(f.default, f.type)
                                                    and lit_in_range(f.default, f.type)):
                    D("E0110", f"default of field '{it.name}.{f.name}' does not fit type {f.type}",
                      it.name, pin=f.name, literal=True, dst=f.type)
        else:
            base = it.base or "i32"
            if any(a.name == "export" for a in it.attrs):
                D("W0203", f"enum '{it.name}' is marked @export, but an enum is stored as its "
                           f"{base} values and has no type entry, so it is not in the export "
                           f"table; remove @export", it.name)
            lo, hi = INT_RANGES[base]
            for name, v in enum_values(it):
                if not lo <= v <= hi:
                    D("E0110", f"value {v} of enum member '{it.name}.{name}' does not fit its "
                               f"type {base} ({lo} to {hi})", it.name, pin=name, literal=True,
                      dst=base)
    check_struct_cycles(idx, D)
    check_interfaces(module, idx, D)
    check_classes(module, idx, D)


def check_interfaces(module: Module, idx: ModuleIndex, D):
    """Interface declarations (section 2.2): a name that is not a built-in type, unique method
    names, supported parameter and result types. A @latent interface method is E0501 in this
    prototype: WBC has no place to record it, so a non-latent caller could suspend."""
    for it in idx.interfaces.values():
        if it.name in BUILTIN_TYPE_NAMES:
            D("E0102", f"interface '{it.name}' has the name of a built-in type; choose another "
                       f"name", it.name)
        seen = set()
        for m in it.methods:
            if m.name in seen:
                D("E0102", f"duplicate method '{m.name}' in interface '{it.name}'", it.name,
                  pin=m.name)
            seen.add(m.name)
            for p in m.params + m.result_list:
                if p.type == "exec" or not handle_ok(p.type, idx):
                    D("E0501", unknown_type_message(p.type, module.name), it.name, pin=m.name,
                      type=p.type)
            if m.has_attr("latent"):
                D("E0501", f"'{it.name}.{m.name}' is @latent; interface methods that can wait "
                           f"are not supported by this prototype yet", it.name, pin=m.name)


def check_implementations(c, idx: ModuleIndex, D):
    """E0151 for an `impl` name that is not an interface; E0152 for an interface method the
    class (or a base) does not implement, or implements with another signature."""
    for name in c.impls:
        if name not in idx.interfaces:
            what = "a class" if name in idx.classes else "not declared in this module"
            D("E0151", f"class '{c.name}' implements '{name}', which is {what}, not an "
                       f"interface", c.name)
    for name in c.impls:
        it = idx.interfaces.get(name)
        if it is None:
            continue
        for m in it.methods:
            g = idx.find_method(c.name, m.name)
            want = (f"func {m.name}({', '.join(p.type for p in m.params)}) -> "
                    f"({', '.join(r.type for r in m.result_list)})")
            if g is None:
                D("E0152", f"class '{c.name}' implements '{name}' but has no method "
                           f"'{m.name}'; add {want}", c.name, pin=m.name)
            elif (g.kind != "func" or g.has_attr("latent")
                  or [p.type for p in g.params] != [p.type for p in m.params]
                  or [r.type for r in g.result_list] != [r.type for r in m.result_list]):
                D("E0152", f"'{g.name}' does not match '{name}.{m.name}': an implementation is "
                           f"a func that does not wait, written {want}", c.name, pin=m.name)


def check_classes(module: Module, idx: ModuleIndex, D):
    """Class declarations and their methods (section 2.2): E0151 for a base that is not a class
    or an inheritance cycle, E0102 for a field declared twice along the chain, and E0150 for an
    override that changes the signature or overrides a @final method."""
    for c in idx.classes.values():
        if c.name in BUILTIN_TYPE_NAMES:
            D("E0102", f"class '{c.name}' has the name of a built-in type; choose another name",
              c.name)
        if c.base is not None and c.base not in idx.classes:
            D("E0151", f"class '{c.name}' extends '{c.base}', which is not a class of this module",
              c.name)
        chain = idx.class_chain(c.name)
        last = idx.classes[chain[-1]]
        if last.base is not None and last.base in chain:
            D("E0151", f"class '{c.name}' inherits from itself: {' -> '.join(chain + [last.base])}",
              c.name)
            continue
        check_implementations(c, idx, D)
        inherited = {f.name: owner for owner, f in idx.class_fields(c.base)} if c.base else {}
        seen = set()
        for d in c.dispatchers:
            for p in d.params:
                if p.type == "exec" or not handle_ok(p.type, idx):
                    D("E0501", unknown_type_message(p.type, module.name), c.name, pin=d.name,
                      type=p.type)
        if c.base:
            inherited.update({d.name: owner for owner in idx.class_chain(c.base)
                              for d in idx.classes[owner].dispatchers})
        for f in list(c.fields) + list(c.dispatchers):
            if f.name in seen:
                D("E0102", f"duplicate member '{f.name}' in class '{c.name}'", c.name, pin=f.name)
            elif f.name in inherited:
                D("E0102", f"field '{f.name}' of class '{c.name}' is already declared by "
                           f"'{inherited[f.name]}'", c.name, pin=f.name)
            seen.add(f.name)
            if not hasattr(f, "type"):           # a dispatcher: checked above
                continue
            if f.type == "exec" or not type_ok(f.type, idx):
                D("E0501", unknown_type_message(f.type, module.name), c.name, pin=f.name,
                  type=f.type)
            elif f.default is not None and not (lit_fits(f.default, f.type, idx)
                                                and lit_in_range(f.default, f.type)):
                D("E0110", f"default of field '{c.name}.{f.name}' does not fit type {f.type}",
                  c.name, pin=f.name, literal=True, dst=f.type)
        for g in idx.methods(c.name):
            base_m = idx.find_method(c.base, g.short_name) if c.base else None
            if base_m is None:
                continue
            if base_m.has_attr("final"):
                D("E0150", f"'{g.name}' overrides '{base_m.name}', which is @final", g.name)
            elif (base_m.kind != g.kind
                  or [p.type for p in base_m.params] != [p.type for p in g.params]
                  or [r.type for r in base_m.result_list] != [r.type for r in g.result_list]
                  or base_m.has_attr("latent") != g.has_attr("latent")):
                D("E0150", f"'{g.name}' overrides '{base_m.name}' but its signature differs; an "
                           f"override takes the same parameters and results", g.name)


def check_enum_value(lit: Lit, idx: ModuleIndex, D, graph=None, node=None, pin=None) -> bool:
    """E0501 unless `Mode.Chase` names an enum of this module and one of its members."""
    name, _, member = lit.value.partition(".")
    en = idx.enums.get(name)
    if en is None:
        D("E0501", f"unknown enum '{name}' in value '{lit.value.replace('.', '::', 1)}'",
          graph, node, pin)
        return False
    if en.member(member) is None:
        D("E0501", f"enum '{name}' has no member '{member}'", graph, node, pin,
          members=[m.name for m in en.members])
        return False
    return True


def check_switch_cases(n: Node, sig: Sig, idx: ModuleIndex, G, D):
    """Each `@cases` value must be a value of the Switch's type (section 3.3)."""
    a = n.attr("cases")
    vin = sig.input("value")
    if a is None or not a.args or vin is None:
        return
    ty = vin.type
    for i, (_, lit) in enumerate(a.args):
        pin = f"case{i}"
        if lit.kind == "enum":
            if not check_enum_value(lit, idx, D, G, n.id, pin):
                continue
        if not (lit_fits(lit, ty) and lit_in_range(lit, ty)):
            hint = (f"; write it as {ty}.Member" if ty in idx.enums and lit.kind != "enum"
                    else "")
            D("E0110", f"case {i} ({fmt_value(lit)}) is not a value of type {ty}{hint}",
              G, n.id, pin, literal=True, dst=ty)


def fmt_value(lit: Lit) -> str:
    from .printer import fmt_lit
    return fmt_lit(lit)


def check_struct_cycles(idx: ModuleIndex, D):
    """E0503: a struct that holds itself by value, directly or through other structs, has no
    finite zero value. Holding it in an array is fine: the array starts empty."""
    def by_value(st):
        return [f.type for f in st.fields if f.type in idx.structs]

    reported = set()
    for name in sorted(idx.structs):
        stack = [(name, [name])]
        visited = set()
        while stack:
            cur, path = stack.pop()
            for nxt in by_value(idx.structs[cur]):
                if nxt == name:
                    cycle = frozenset(path)
                    if cycle not in reported:
                        reported.add(cycle)
                        D("E0503", f"struct '{name}' contains itself by value: "
                                   f"{' -> '.join(path + [nxt])}", name)
                    stack = []
                    break
                if nxt not in visited:
                    visited.add(nxt)
                    stack.append((nxt, path + [nxt]))


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
        if n.kind == "Switch" and not sig.error:
            check_switch_cases(n, sig, idx, G, D)
        if n.attr("live") is not None and not sig.pure:
            D("E0104", "@live belongs on a node without exec pins: it says that each consumer "
                       "re-reads the node's value (section 4.3)", G, n.id)
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
                    D("E0101", f"unknown node '{b.value.node}'" + (
                        "" if b.value.pin else f" (a node written in place has its inputs in "
                                               f"parentheses, as in '{b.value.node}()')"),
                      G, n.id, b.pin)
                    continue
                spin = sigs[src.id].output(b.value.pin)
                if spin is None:
                    if not sigs[src.id].error:
                        D("E0103", f"{src.kind} '{src.id}' has no output pin '{b.value.pin}'",
                          G, n.id, b.pin)
                    continue
                if spin.is_exec:
                    D("E0120", f"'{src.id}.{spin.name}' is an exec output", G, n.id, b.pin)
                elif not assignable(spin.type, pin.type, idx):
                    D("E0110", f"wire type mismatch: {spin.type} -> {pin.type}; insert "
                               f"Convert::<{spin.type}, {pin.type}>", G, n.id, b.pin,
                      src=spin.type, dst=pin.type)
            else:
                if b.value.kind == "enum" and not check_enum_value(b.value, idx, D, G, n.id,
                                                                   b.pin):
                    continue
                if not lit_fits(b.value, pin.type, idx):
                    D("E0110", f"literal does not fit pin type {pin.type}", G, n.id, b.pin,
                      dst=pin.type, literal=True)
        if not sig.error and n.kind not in ("Exit", "Leave"):
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
            if n.kind in PLACE_MUTATORS and field_place(n.symbol, g, idx) and \
                    not g.local(n.symbol or ""):
                D("E0302", f"{attr} function changes the field '{n.symbol}'", G, n.id)
            if n.kind in PLACE_MUTATORS and n.symbol in idx.vars and not g.local(n.symbol):
                D("E0302", f"{attr} function changes the module variable '{n.symbol}'", G, n.id)
            if n.kind in ("SetVar", "SetState"):
                D("E0302", f"{attr} function writes {'a variable' if n.kind == 'SetVar' else 'state'}",
                  G, n.id)
            if n.kind in ("Bind", "Unbind", "Broadcast", "Invoke"):
                D("E0302", f"{attr} function uses {n.kind}, which changes objects or runs "
                           f"code it cannot check", G, n.id)
            if n.kind == "SetField" and not sig.error:
                D("E0302", f"{attr} function writes the field '{n.symbol}'", G, n.id)
            if n.kind == "New":
                D("E0302", f"{attr} function creates an object, which is an effect", G, n.id)
            if pure_attr and n.kind == "GetField" and sig.purity == "reads":
                D("E0304", f"@pure function reads the field '{n.symbol}' of an object", G, n.id)
            if pure_attr and n.kind == "GetState":
                D("E0304", "@pure function reads state", G, n.id)
            if pure_attr and n.kind == "GetVar" and n.symbol not in idx.consts:
                D("E0304", "@pure function reads a module variable", G, n.id)
            if n.kind in ("Call", "CallParent") and not sig.error:
                if pure_attr and sig.purity != "pure":
                    D("E0304", f"@pure function calls '{n.symbol}', which is not @pure", G, n.id)
                elif reads_attr and sig.purity == "impure":
                    D("E0302", f"@reads function calls '{n.symbol}', which is neither @reads nor "
                               f"@pure", G, n.id)
            if n.kind == "Macro" and n.symbol in idx.macros and idx.macros[n.symbol].states:
                D("E0302", f"{attr} function expands macro '{n.symbol}', which keeps state", G, n.id)

    check_pure_cycles(info, G, D)
    check_flow(info, G, D)
    check_try_nesting(info, G, D)
    check_latency(g, info, idx, G, D)
    check_layout(g, ids, G, D)


LATENT_KINDS = ("Delay", "Yield", "Await")


def graph_latent(g: Graph) -> bool:
    """Events are implicitly latent; a func is latent when declared @latent (section 4.4)."""
    return g.kind == "event" or g.has_attr("latent")


def macro_latent(name: str, idx: ModuleIndex, seen=None) -> bool:
    """Whether expanding a macro brings in a latent node or a call to a latent function."""
    seen = set() if seen is None else seen
    m = idx.macros.get(name)
    if m is None or name in seen:
        return False
    seen.add(name)
    for n in m.nodes:
        if n.kind in LATENT_KINDS:
            return True
        if n.kind == "Call":
            c = idx.callee(n.symbol or "")
            if c is not None and c.latent:
                return True
        if n.kind == "Macro" and macro_latent(n.symbol or "", idx, seen):
            return True
    return False


def check_latency(g: Graph, info: GraphInfo, idx: ModuleIndex, G, D):
    """E0201 and E0302 for latency (section 4.5): a graph that can suspend must be latent, and
    a latent function is never @pure or @reads. Macros are checked where they expand."""
    if g.kind == "macro":
        return
    pure = g.has_attr("pure") or g.has_attr("reads")
    attr = "@pure" if g.has_attr("pure") else "@reads"
    if pure and g.has_attr("latent"):
        D("E0302", f"a function cannot be both @latent and {attr}: suspending is an effect", G)
        return
    if graph_latent(g):
        return
    for nid, n in sorted(info.nodes.items()):
        why = None
        if n.kind in LATENT_KINDS:
            why = f"{n.kind} suspends"
        elif n.kind == "CallParent" and not info.sigs[nid].error:
            pm = parent_method(n, g, idx)
            if pm is not None and (pm.kind == "event" or pm.has_attr("latent")):
                why = f"the parent '{pm.name}' is {'an event' if pm.kind == 'event' else 'latent'}"
        elif n.kind == "Call" and not info.sigs[nid].error:
            c = idx.callee(n.symbol or "")
            if c is not None and c.latent:
                why = f"'{n.symbol}' is {'an event' if c.kind == 'event' else 'latent'}"
        elif n.kind == "Macro" and macro_latent(n.symbol or "", idx):
            why = f"macro '{n.symbol}' can suspend"
        if why is None:
            continue
        if pure:
            D("E0302", f"{attr} function cannot wait: {why}", G, nid)
        else:
            D("E0201", f"{why}, so '{G}' must be declared @latent", G, nid)


def check_try_nesting(info: GraphInfo, G, D):
    """E0412 (section 4.6): a `Try` body is the set of nodes reachable from its `body` output,
    and nothing outside it may reach into it. Otherwise a path into the body would run without
    the handler marker, or the marker would outlive the region. The body may not lead back to
    its own `Try`, and may not contain an `Exit`: that would carry the marker into the
    caller's chain, which the macro cannot see."""
    edges = {}                                   # target -> [(source, exec pin)]
    for nid, n in info.nodes.items():
        for e in n.execs:
            if e.target in info.nodes:
                edges.setdefault(e.target, []).append((nid, info.exec_pin(n, e)))
    for tid, t in sorted(info.nodes.items()):
        if t.kind != "Try" or info.sigs[tid].error:
            continue
        starts = [e.target for e in t.execs
                  if info.exec_pin(t, e) == "body" and e.target in info.nodes]
        body, todo = set(starts), list(starts)
        while todo:
            for s in info.successors(todo.pop()):
                if s not in body:
                    body.add(s)
                    todo.append(s)
        if tid in body:
            D("E0412", f"the body of Try '{tid}' leads back to '{tid}' itself; loop inside the "
                       f"body, or around the whole Try from its 'then'", G, tid)
            continue
        exits = sorted(nid for nid in body if info.nodes[nid].kind == "Exit")
        if exits:
            D("E0412", f"the body of Try '{tid}' reaches Exit '{exits[0]}', which would leave "
                       f"the macro with the fault handler still active", G, tid)
            continue
        for nid in sorted(body):
            outside = [(p, pin) for p, pin in edges.get(nid, [])
                       if p not in body and not (p == tid and pin == "body")]
            if outside:
                p, pin = outside[0]
                D("E0412", f"'{nid}' is inside the body of Try '{tid}' but is also reached from "
                           f"'{p}.{pin}' outside it; the body must be entered only through "
                           f"'{tid}.body'", G, tid)
                break


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
                D("E0310", f"reads '{prod}.{pin}', but '{prod}' does not run on every path to "
                           f"this node (store it in a local on every path instead)", G, nid, cpin)

    # E0320: a node reading mutable state is evaluated again at each impure consumer; two
    # consumers that can run one after the other may see different values (section 4.3)
    later = _runs_after(info, impure, succ)
    live = {nid for nid, n in info.nodes.items() if n.attr("live") is not None}
    for rid, sig in sorted(info.sigs.items()):
        if sig.purity != "reads" or rid in live:
            continue
        # a path through a @live node re-reads on purpose, so it does not count
        consumers = sorted(nid for nid in impure if rid in _pure_closure(info, nid, live))
        pair = next(((a, b) for a in consumers for b in consumers
                     if a != b and b in later.get(a, ())), None)
        if pair is None:
            continue
        a, b = pair
        D("E0320", f"'{rid}' reads mutable state and is evaluated again at '{a}' and at '{b}', "
                   f"which can run one after the other, so they may see different values; "
                   f"store it in a local before '{a}' (SetLocal, then GetLocal), or mark it "
                   f"@live if each should read the current value", G, rid)


def _runs_after(info: GraphInfo, impure: list, succ: dict) -> dict:
    """For each impure node, the impure nodes that can run after it in the same call: those
    reachable along exec wires, where a chain that ends inside a Sequence, a Try or a macro
    resumes that node (section 4.2), so its other outputs, and a loop's next pass, follow."""
    ext = {nid: list(succ.get(nid, [])) for nid in impure}

    def reach(starts, edges):
        seen, todo = set(), list(starts)
        while todo:
            cur = todo.pop()
            if cur in seen or cur not in edges:
                continue
            seen.add(cur)
            todo.extend(edges[cur])
        return seen

    for nid in impure:
        if info.nodes[nid].kind in ("Sequence", "Try", "Macro"):
            for r in reach(succ.get(nid, []), succ):
                if r != nid:
                    ext[r].append(nid)
    return {nid: reach(ext[nid], ext) for nid in impure}


def _pure_closure(info: GraphInfo, nid: str, stop: set = frozenset()) -> set:
    """The pure nodes evaluated with `nid`, not looking past the nodes in `stop`."""
    out, todo = set(), list(pure_deps(info, nid))
    while todo:
        d = todo.pop()
        if d in out or d in stop or not info.sigs[d].pure:
            continue
        out.add(d)
        todo += pure_deps(info, d)
    return out


def check_capabilities(module: Module, project, D):
    """`@capability("name")` (section 2.4): only on an `extern func`, with one string. In a
    project whose wiret.toml has a `[capabilities]` table, E0160 for a capability that its
    `allow` list does not permit (section 7.3); the host's grants decide at run time."""
    for it in module.items:
        for a in getattr(it, "attrs", []):
            if a.name != "capability":
                continue
            name = it.name if hasattr(it, "name") else None
            if not (isinstance(it, Extern) and it.kind == "func"):
                D("E0104", "@capability belongs on an extern func: it says what that host "
                           "function needs to be granted", name)
                continue
            arg = a.arg()
            if arg is None or arg.kind != "string" or len(a.args or []) != 1:
                D("E0104", '@capability takes the capability name as one string, as in '
                           '@capability("console.write")', name)
                continue
            allowed = getattr(project, "capabilities", None) if project is not None else None
            if allowed is not None and arg.value not in allowed:
                D("E0160", f"'{it.name}' needs capability '{arg.value}', which wiret.toml does "
                           f"not allow; add it to [capabilities] allow", name,
                  capability=arg.value)


def check_attr_names(module: Module, D):
    """E0104: an `@` name that is not a semantic attribute (section 2.4)."""
    def walk(owner, attrs, graph=None, node=None):
        for a in attrs:
            if a.name in SEMANTIC_ATTRS:
                continue
            if a.name in META_NAMES:
                D("E0104", f"'@{a.name}' is metadata, written on its own line above "
                           f"{owner}: #[{a.name}(...)]", graph, node)
            else:
                D("E0104", f"unknown attribute '@{a.name}' on {owner}; '@' is only for semantic "
                           f"attributes, metadata is written #[{a.name}(...)] on the line above",
                  graph, node)

    walk(f"module {module.name}", module.attrs)
    for it in module.items:
        name = getattr(it, "name", "")
        walk(name, it.attrs, name if isinstance(it, Graph) else None)
        for p in list(getattr(it, "params", []) or []) + list(getattr(it, "results", []) or []):
            walk(f"parameter '{p.name}'", p.attrs, name)
        for f in list(getattr(it, "fields", []) or []) + list(getattr(it, "members", []) or []):
            walk(f"'{name}.{f.name}'", f.attrs)
        if isinstance(it, Graph):
            for l in it.locals + it.states:
                walk(f"'{l.name}'", l.attrs, name)
            for n in it.nodes:
                walk(f"node '{n.id}'", n.attrs, name, n.id)


def check_layout(g: Graph, ids: set, G, D):
    nodes = {n.id for n in g.nodes}
    for name in sorted({p.id for p in g.places} | set(g.orphan_meta)):
        if name not in nodes:
            D("W0605", f"the layout block has a line for '{name}', which is not a node of "
                       f"this graph; move its position and notes to the node they belong to, "
                       f"or delete the line", G, name)
    owner = {}
    for b in sorted(g.boxes, key=lambda b: b.id):
        for m in b.members():
            if m not in ids:
                D("W0601", f"box '{b.id}' lists '{m}', which names no node or box", G, b.id)
            elif m in owner:
                D("W0602", f"'{m}' is a member of both '{owner[m]}' and '{b.id}'", G, b.id)
            else:
                owner[m] = b.id
    for nt in notes(g.meta):
        if note_detached(nt) is not None:
            D("W0604", f"a note is detached from '{note_detached(nt)}', which was deleted", G)
