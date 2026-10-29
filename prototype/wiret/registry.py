"""The node registry (spec section 3.5): pin names, types, defaults and purity.

Static kinds are described as data. Kinds whose pins depend on context (Entry,
Return, Call, Macro, Exit, the variable accessors) are expanded by `signature`.
"""
from __future__ import annotations

import copy
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from .model import Graph, Lit, Module, Node, Extern, Const, Var
from .natives import STD, NativeSpec

INT_TYPES = ["i8", "u8", "i16", "u16", "i32", "u32", "i64", "u64"]
FLOAT_TYPES = ["f32", "f64"]
NUM_TYPES = INT_TYPES + FLOAT_TYPES
PRIM_TYPES = ["bool"] + NUM_TYPES + ["string"]
SIGNED_TYPES = {"i8", "i16", "i32", "i64"}

CONSTRAINTS = {
    "number": NUM_TYPES,
    "int": INT_TYPES,
    "signed": ["i8", "i16", "i32", "i64", "f32", "f64"],
    "eq": ["bool"] + NUM_TYPES + ["string"],
    "ord": NUM_TYPES + ["string"],
    "switch": ["bool"] + INT_TYPES + ["string"],
    "any": PRIM_TYPES,
    "convertible": PRIM_TYPES,
}

ZERO = object()  # pin default: the zero value of the pin's type


def array_elem(ty: str) -> Optional[str]:
    """The element type of `array<T>`, else None."""
    if ty.startswith("array<") and ty.endswith(">"):
        return ty[6:-1]
    return None


def type_ok(ty: str) -> bool:
    """A value type this prototype supports: a primitive or an array of supported types."""
    elem = array_elem(ty)
    return type_ok(elem) if elem is not None else ty in PRIM_TYPES


def substitute(ty: str, subst: dict) -> str:
    """Replace type parameter names in a type (generic macros)."""
    if not subst:
        return ty
    return re.sub(r"[A-Za-z_][A-Za-z0-9_]*", lambda m: subst.get(m.group(0), m.group(0)), ty)

REGISTRY_NAME = "wiret.core"
REGISTRY_VERSION = "0.1-proto"


def zero_lit(ty: str) -> Lit:
    if array_elem(ty) is not None:
        return Lit("null", None)     # the empty array: arrays are values and never null
    if ty == "bool":
        return Lit("bool", False)
    if ty in FLOAT_TYPES:
        return Lit("float", 0.0)
    if ty == "string":
        return Lit("string", "")
    return Lit("int", 0)


def lit_fits(lit: Lit, ty: str) -> bool:
    if ty in INT_TYPES:
        return lit.kind == "int"
    if ty in FLOAT_TYPES:
        return lit.kind in ("int", "float")
    if ty == "bool":
        return lit.kind == "bool"
    if ty == "string":
        return lit.kind == "string"
    return lit.kind == "null"


def lit_equal(a: Lit, b: Lit) -> bool:
    if a.kind in ("int", "float") and b.kind in ("int", "float"):
        return a.value == b.value and (a.suffix == b.suffix)
    return a.kind == b.kind and a.value == b.value


def can_convert(src: str, dst: str) -> bool:
    if src == dst:
        return False
    if dst == "string":
        return src in PRIM_TYPES and src != "string"
    if "bool" in (src, dst):
        return (src if dst == "bool" else dst) in INT_TYPES
    return src in NUM_TYPES and dst in NUM_TYPES


@dataclass
class Pin:
    name: str
    type: str
    default: object = None      # None: no declared default; ZERO; or a Lit

    @property
    def is_exec(self) -> bool:
        return self.type == "exec"

    def default_lit(self) -> Optional[Lit]:
        if self.default is ZERO:
            return zero_lit(self.type)
        return self.default


@dataclass
class Sig:
    inputs: list = field(default_factory=list)
    outputs: list = field(default_factory=list)
    purity: str = "impure"
    error: Optional[tuple] = None           # (code, message)
    category: str = "Other"

    def input(self, name) -> Optional[Pin]:
        return next((p for p in self.inputs if p.name == name), None)

    def output(self, name) -> Optional[Pin]:
        return next((p for p in self.outputs if p.name == name), None)

    @property
    def exec_ins(self):
        return [p for p in self.inputs if p.is_exec]

    @property
    def exec_outs(self):
        return [p for p in self.outputs if p.is_exec]

    @property
    def data_ins(self):
        return [p for p in self.inputs if not p.is_exec]

    @property
    def data_outs(self):
        return [p for p in self.outputs if not p.is_exec]

    @property
    def pure(self) -> bool:
        return self.purity in ("pure", "reads")


# kind -> (category, purity, [type param constraints], [(pin, dir, type, default)])
_BIN = [("a", "in", "T", None), ("b", "in", "T", None), ("result", "out", "T", None)]
_CMP = [("a", "in", "T", None), ("b", "in", "T", None), ("result", "out", "bool", None)]
_UN = [("value", "in", "T", None), ("result", "out", "T", None)]
_LOGIC = [("a", "in", "bool", None), ("b", "in", "bool", None), ("result", "out", "bool", None)]

STATIC_KINDS = {
    "Branch": ("Flow", "impure", [], [("in", "in", "exec", None), ("cond", "in", "bool", ZERO),
                                      ("then", "out", "exec", None), ("else", "out", "exec", None)]),
    "Select": ("Flow", "pure", ["any"], [("cond", "in", "bool", ZERO), ("a", "in", "T", None),
                                         ("b", "in", "T", None), ("result", "out", "T", None)]),
    "Convert": ("Math", "pure", ["convertible", "convertible"],
                [("value", "in", "T0", None), ("result", "out", "T1", None)]),
    "Not": ("Logic", "pure", [], [("value", "in", "bool", None), ("result", "out", "bool", None)]),
    "BitNot": ("Bits", "pure", ["int"], _UN),
}
for _k in ("Add", "Sub", "Mul", "Div", "Rem", "Min", "Max"):
    STATIC_KINDS[_k] = ("Math", "pure", ["number"], _BIN)
for _k in ("Neg", "Abs"):
    STATIC_KINDS[_k] = ("Math", "pure", ["signed"], _UN)
for _k in ("Eq", "Ne"):
    STATIC_KINDS[_k] = ("Compare", "pure", ["eq"], _CMP)
for _k in ("Lt", "Le", "Gt", "Ge"):
    STATIC_KINDS[_k] = ("Compare", "pure", ["ord"], _CMP)
for _k in ("And", "Or", "Xor"):
    STATIC_KINDS[_k] = ("Logic", "pure", [], _LOGIC)
for _k in ("BitAnd", "BitOr", "BitXor", "Shl", "Shr"):
    STATIC_KINDS[_k] = ("Bits", "pure", ["int"], _BIN)

# Kinds handled by `signature` directly.
CONTEXT_KINDS = {
    "Entry": "Flow", "Return": "Flow", "Sequence": "Flow", "Switch": "Flow", "Reroute": "Flow",
    "Macro": "Macro", "Exit": "Macro", "Call": "Call",
    "MakeArray": "Arrays", "ArrayGet": "Arrays", "ArrayLength": "Arrays", "ArraySet": "Arrays",
    "ArrayAdd": "Arrays", "ArrayInsert": "Arrays", "ArrayRemove": "Arrays", "ArrayClear": "Arrays",
    "GetLocal": "Variables", "SetLocal": "Variables", "GetVar": "Variables",
    "SetVar": "Variables", "GetState": "Variables", "SetState": "Variables",
}

# Kinds from the specification that later tiers add (section 1.6).
LATER_TIER_KINDS = {
    "Try", "Throw", "Delay", "Yield", "Await", "GetField", "SetField", "WithField", "MakeStruct",
    "BreakStruct", "New", "Cast", "IsValid", "MapFind", "MapHas", "MapLength",
    "MapKeyAt", "MapValueAt", "MapSet", "MapRemove", "MapClear", "SetHas", "SetLength", "SetAt",
    "SetAdd", "SetRemove", "SetClear", "CreateDelegate", "Invoke", "Bind", "Unbind", "Broadcast",
}

ALL_KINDS = sorted(set(STATIC_KINDS) | set(CONTEXT_KINDS))

# Array mutators change a place (section 3.3): (extra input pins as (name, type or "T"))
ARRAY_MUTATORS = {
    "ArraySet": [("index", "i32"), ("item", "T")],
    "ArrayAdd": [("item", "T")],
    "ArrayInsert": [("index", "i32"), ("item", "T")],
    "ArrayRemove": [("index", "i32")],
    "ArrayClear": [],
}


@dataclass
class Callee:
    name: str          # resolved name: local graph name or qualified native/extern name
    kind: str          # func | event | extern | native
    params: list       # [Pin]
    results: list      # [Pin]
    purity: str


_STD_FLOW = None
STD_FLOW_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "std", "flow.wiret")


def std_flow_macros() -> dict:
    """The `std.flow` macros (section 3.4), written in Wiret and shipped as source."""
    global _STD_FLOW
    if _STD_FLOW is None:
        from .parser import parse
        with open(STD_FLOW_PATH, encoding="utf-8") as f:
            _STD_FLOW = {g.name: g for g in parse(f.read()).graphs(("macro",))}
    return _STD_FLOW


class ModuleIndex:
    """Name lookup over one module, shared by the checker, printer and compiler."""

    def __init__(self, module: Module):
        self.module = module
        self.graphs = {g.name: g for g in module.graphs(("func", "event"))}
        self.macros = {g.name: g for g in module.graphs(("macro",))}
        if module.name != "std.flow":
            for name, g in std_flow_macros().items():
                self.macros.setdefault(f"std.flow.{name}", g)
        self.externs = {i.name: i for i in module.items if isinstance(i, Extern) and i.kind == "func"}
        self.vars = {i.name: i for i in module.items if isinstance(i, Var)}
        self.consts = {i.name: i for i in module.items if isinstance(i, Const)}
        self._instances = {}

    def macro(self, symbol: str, targs: list) -> Optional[Graph]:
        """A macro, instantiated for its type arguments if it is generic."""
        m = self.macros.get(symbol or "")
        if m is None or not m.tparams:
            return m
        key = (symbol, tuple(targs))
        if key not in self._instances:
            self._instances[key] = instantiate(m, targs)
        return self._instances[key]

    def _strip(self, symbol: str) -> str:
        prefix = self.module.name + "."
        return symbol[len(prefix):] if symbol.startswith(prefix) else symbol

    def callee(self, symbol: str) -> Optional[Callee]:
        s = self._strip(symbol)
        if s in self.graphs:
            g = self.graphs[s]
            purity = "pure" if g.has_attr("pure") else "reads" if g.has_attr("reads") else "impure"
            return Callee(s, g.kind, [Pin(p.name, p.type, p.default) for p in g.params],
                          [Pin(r.name, r.type) for r in g.result_list], purity)
        if symbol in self.externs:
            e = self.externs[symbol]
            purity = "pure" if e.has_attr("pure") else "reads" if e.has_attr("reads") else "impure"
            return Callee(symbol, "extern", [Pin(p.name, p.type, p.default) for p in e.params],
                          [Pin(r.name, r.type) for r in (e.results or [])], purity)
        if symbol in STD:
            n: NativeSpec = STD[symbol]
            return Callee(symbol, "native", [Pin(a, t) for a, t in n.params],
                          [Pin(a, t) for a, t in n.results], n.purity)
        return None

    def var_type(self, name: str) -> Optional[str]:
        if name in self.vars:
            return self.vars[name].type
        if name in self.consts:
            return self.consts[name].type
        return None


def type_known(ty: str) -> bool:
    return type_ok(ty)


def instantiate(m: Graph, targs: list) -> Graph:
    """A copy of a generic macro with its type parameters replaced by `targs`."""
    subst = dict(zip(m.tparams, targs))
    g = copy.deepcopy(m)
    g.tparams = []
    for items in (g.params, g.result_list, g.locals, g.states):
        for p in items:
            p.type = substitute(p.type, subst)
    for n in g.nodes:
        n.targs = [substitute(t, subst) for t in n.targs]
    return g


def _static_sig(node: Node) -> Sig:
    cat, purity, tps, pins = STATIC_KINDS[node.kind]
    sig = Sig(purity=purity, category=cat)
    targs = list(node.targs)
    if len(targs) != len(tps):
        sig.error = ("E0502", f"{node.kind} needs {len(tps)} type argument(s), got {len(targs)}")
        targs = (targs + ["i32"] * len(tps))[: len(tps)]
    else:
        for t, c in zip(targs, tps):
            if t not in CONSTRAINTS[c]:
                sig.error = ("E0110", f"{node.kind} does not accept type {t}")
    if node.kind == "Convert" and not sig.error and not can_convert(targs[0], targs[1]) \
            and targs[0] != targs[1]:
        sig.error = ("E0110", f"no conversion from {targs[0]} to {targs[1]}")
    subst = {"T": targs[0] if targs else "i32"}
    for i, t in enumerate(targs):
        subst[f"T{i}"] = t
    for name, d, ty, default in pins:
        pin = Pin(name, subst.get(ty, ty), default)
        (sig.inputs if d == "in" else sig.outputs).append(pin)
    return sig


def attr_int(node: Node, name: str, default: int) -> int:
    a = node.attr(name)
    if a and a.args and a.args[0][1].kind == "int":
        return a.args[0][1].value
    return default


def signature(node: Node, graph: Graph, idx: ModuleIndex) -> Sig:
    k = node.kind
    if k in STATIC_KINDS:
        return _static_sig(node)
    E = "exec"
    sig = Sig(category=CONTEXT_KINDS.get(k, "Other"))
    is_macro = graph.kind == "macro"

    if k == "Entry":
        if is_macro:
            sig.outputs = [Pin(p.name, p.type) for p in graph.params]
        else:
            sig.outputs = [Pin("then", E)] + [Pin(p.name, p.type) for p in graph.params]
        return sig
    if k == "Return":
        sig.inputs = [Pin("in", E)] + [Pin(r.name, r.type) for r in graph.result_list]
        if is_macro:
            sig.error = ("E0501", "Return is not allowed in a macro; use Exit")
        return sig
    if k == "Sequence":
        n = attr_int(node, "count", 2)
        sig.inputs = [Pin("in", E)]
        sig.outputs = [Pin(f"then{i}", E) for i in range(n)]
        return sig
    if k == "Switch":
        if len(node.targs) != 1:
            sig.error = ("E0502", "Switch needs one type argument")
        t = node.targs[0] if node.targs else "i32"
        if t not in CONSTRAINTS["switch"]:
            sig.error = ("E0110", f"Switch does not accept type {t}")
        a = node.attr("cases")
        n = len(a.args) if a and a.args else 0
        sig.inputs = [Pin("in", E), Pin("value", t)]
        sig.outputs = [Pin(f"case{i}", E) for i in range(n)] + [Pin("default", E)]
        return sig
    if k == "Reroute":
        if len(node.targs) != 1:
            sig.error = ("E0502", "Reroute needs one type argument")
        t = node.targs[0] if node.targs else "i32"
        sig.purity = "impure" if t == "exec" else "pure"
        sig.inputs = [Pin("in", t)]
        sig.outputs = [Pin("out", t)]
        return sig
    if k in ("GetLocal", "SetLocal", "GetState", "SetState", "GetVar", "SetVar"):
        if not node.symbol:
            sig.error = ("E0501", f"{k} needs a symbol")
            ty = "i32"
        elif k.endswith("Local"):
            loc = graph.local(node.symbol)
            ty = loc.type if loc else None
            if not loc:
                sig.error = ("E0501", f"unknown local '{node.symbol}'")
        elif k.endswith("State"):
            st = graph.state(node.symbol)
            ty = st.type if st else None
            if not st:
                sig.error = ("E0501", f"unknown state '{node.symbol}'")
        else:
            ty = idx.var_type(node.symbol)
            if ty is None:
                sig.error = ("E0501", f"unknown variable '{node.symbol}'")
            elif k == "SetVar" and node.symbol in idx.consts:
                sig.error = ("E0501", f"'{node.symbol}' is a const and cannot be set")
        ty = ty or "i32"
        if k.startswith("Get"):
            sig.purity = "pure" if k == "GetLocal" or node.symbol in idx.consts else "reads"
            sig.outputs = [Pin("value", ty)]
        else:
            sig.inputs = [Pin("in", E), Pin("value", ty)]
            sig.outputs = [Pin("then", E)]
        return sig
    if k == "Call":
        c = idx.callee(node.symbol or "")
        if c is None:
            sig.error = ("E0501", f"unresolved function '{node.symbol}'")
            return sig
        if c.kind == "event":
            sig.error = ("E0201", "calling an event needs latent support (Tier 2)")
        sig.purity = c.purity
        sig.category = "Call"
        if c.purity == "impure":
            sig.inputs = [Pin("in", E)]
            sig.outputs = [Pin("then", E)]
        sig.inputs += c.params
        sig.outputs += c.results
        return sig
    if k == "Macro":
        generic = idx.macros.get(node.symbol or "")
        if generic is None:
            sig.error = ("E0501", f"unresolved macro '{node.symbol}'")
            return sig
        if len(node.targs) != len(generic.tparams):
            sig.error = ("E0502", f"macro {node.symbol} needs {len(generic.tparams)} type "
                                  f"argument(s), got {len(node.targs)}")
            return sig
        bad = [t for t in node.targs if not type_ok(t)]
        if bad:
            sig.error = ("E0501", f"type '{bad[0]}' is not supported by this prototype")
            return sig
        m = idx.macro(node.symbol, node.targs)
        sig.inputs = [Pin(p.name, p.type, p.default) for p in m.params]
        sig.outputs = [Pin(r.name, r.type) for r in m.result_list]
        return sig
    if k == "Exit":
        if not is_macro:
            sig.error = ("E0501", "Exit is only allowed in a macro")
            return sig
        outs = {r.name: r for r in graph.result_list}
        r = outs.get(node.symbol or "")
        if r is None or r.type != "exec":
            sig.error = ("E0501", f"'{node.symbol}' is not an exec output of macro {graph.name}")
        sig.inputs = [Pin("in", E)] + [Pin(r.name, r.type, ZERO) for r in graph.result_list
                                       if r.type != "exec"]
        return sig
    if k in ("MakeArray", "ArrayGet", "ArrayLength") or k in ARRAY_MUTATORS:
        return _array_sig(node, graph, idx, sig)
    if k in LATER_TIER_KINDS:
        sig.error = ("E0501", f"node kind '{k}' belongs to a later tier and is not in this prototype")
    else:
        sig.error = ("E0501", f"unknown node kind '{k}'")
    return sig


def _array_sig(node: Node, graph: Graph, idx: ModuleIndex, sig: Sig) -> Sig:
    k = node.kind
    if len(node.targs) != 1:
        sig.error = ("E0502", f"{k} needs one type argument: the element type, as in {k}<i32>")
    t = node.targs[0] if node.targs else "i32"
    if not type_ok(t):
        sig.error = ("E0501", f"type '{t}' is not supported by this prototype")
    arr = f"array<{t}>"
    if k == "MakeArray":
        sig.purity = "pure"
        sig.inputs = [Pin(f"item{i}", t) for i in range(attr_int(node, "count", 2))]
        sig.outputs = [Pin("result", arr)]
    elif k == "ArrayGet":
        sig.purity = "pure"
        sig.inputs = [Pin("array", arr), Pin("index", "i32")]
        sig.outputs = [Pin("item", t)]
    elif k == "ArrayLength":
        sig.purity = "pure"
        sig.inputs = [Pin("array", arr)]
        sig.outputs = [Pin("length", "i32")]
    else:
        # A mutator changes a place: a local or a module variable of type array<T>.
        place = node.symbol
        loc = graph.local(place) if place else None
        ty = loc.type if loc else (idx.vars[place].type if place in idx.vars else None)
        if not place or ty is None:
            sig.error = ("E0130", f"{k} must name the local or variable it changes, as in "
                                  f"{k}<{t}> scores")
        elif ty != arr and not sig.error:
            sig.error = ("E0110", f"'{place}' is {ty}, not {arr}")
        sig.inputs = [Pin("in", "exec")] + [Pin(n, t if pt == "T" else pt)
                                            for n, pt in ARRAY_MUTATORS[k]]
        sig.outputs = [Pin("then", "exec")]
    return sig


def registry_json() -> dict:
    """The registry document printed by `wiretc schema --json`."""
    kinds = []
    for k, (cat, purity, tps, pins) in sorted(STATIC_KINDS.items()):
        entry = {"kind": k, "display": k, "category": cat, "purity": purity, "pins": []}
        if tps:
            entry["typeParams"] = {("T" if len(tps) == 1 else f"T{i}"): c for i, c in enumerate(tps)}
        for name, d, ty, default in pins:
            p = {"name": name, "dir": d, "type": ty}
            if default is ZERO:
                p["default"] = "zero"
            entry["pins"].append(p)
        kinds.append(entry)
    for k, cat in sorted(CONTEXT_KINDS.items()):
        kinds.append({"kind": k, "display": k, "category": cat, "purity": "context",
                      "pins": "derived from the symbol or the enclosing graph"})
    natives = [{"name": n, "purity": s.purity,
                "params": [{"name": a, "type": t} for a, t in s.params],
                "results": [{"name": a, "type": t} for a, t in s.results]}
               for n, s in sorted(STD.items())]
    return {"registry": REGISTRY_NAME, "version": REGISTRY_VERSION, "kinds": kinds,
            "natives": natives}
