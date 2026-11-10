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

from .lanes import DEFAULTS as LANE_DEFAULTS, LANE_FIELDS, LANE_TYPES, VECTORS
from .model import (Class, Interface, Const, Enum, Extern, Field, Graph, Lit, Module, Node,
                    Struct, Var)
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
    "eq": ["bool"] + NUM_TYPES + ["string"] + list(LANE_TYPES),
    "ord": NUM_TYPES + ["string"],
    "switch": ["bool"] + INT_TYPES + ["string"],
    "any": PRIM_TYPES + list(LANE_TYPES),
    "convertible": PRIM_TYPES + list(VECTORS) + ["quat", "transform"],
    # the lane types (section 3.1.1): vectors are component-wise under Add Sub Div Min Max
    # Neg Abs; Mul also composes rotations and transforms; Scale takes a vector
    "arith": NUM_TYPES + list(VECTORS),
    "mul": NUM_TYPES + list(LANE_TYPES),
    "neg": ["i8", "i16", "i32", "i64", "f32", "f64"] + list(VECTORS),
    "vector": list(VECTORS),
}

# Names a struct or enum may not take: they already mean a built-in type.
BUILTIN_TYPE_NAMES = set(PRIM_TYPES) | {"array", "set", "map", "delegate", "dispatcher",
                                        "exec"} | set(LANE_TYPES)


def lane_struct(name: str) -> Struct:
    """A lane type as the struct it behaves like (section 3.1.1): its fixed fields, with the
    defaults that make the type's own default (a transform's scale is (1, 1, 1))."""
    fields = []
    for i, (fname, fty) in enumerate(LANE_FIELDS[name]):
        d = LANE_DEFAULTS[name][i]
        default = lane_lit(d) if isinstance(d, tuple) else Lit("float", d)
        fields.append(Field(fname, fty, default))
    return Struct(name, fields)


def lane_lit(v) -> Lit:
    """A lane value as its literal: a tuple of floats, nested for a transform."""
    return Lit("tuple", [lane_lit(x) if isinstance(x, tuple) else Lit("float", float(x))
                         for x in v])


def lane_value(lit: Lit, ty: str):
    """The value of a lane literal, as floats (not yet rounded to f32)."""
    if ty == "transform":
        return tuple(lane_value(x, t) for x, (_, t) in zip(lit.value, LANE_FIELDS[ty]))
    return tuple(float(x.value) for x in lit.value)


def lane_lit_fits(lit: Lit, ty: str) -> bool:
    """A tuple with one number per field, nested for a transform (section 3.1.1)."""
    if lit.kind != "tuple" or len(lit.value) != len(LANE_FIELDS[ty]):
        return False
    return all(lane_lit_fits(x, t) if t in LANE_FIELDS else x.kind in ("int", "float")
               for x, (_, t) in zip(lit.value, LANE_FIELDS[ty]))

INT_RANGES = {t: ((-(1 << (b - 1)), (1 << (b - 1)) - 1) if t[0] == "i" else (0, (1 << b) - 1))
              for t in INT_TYPES for b in [int(t[1:])]}

# Constraints that also admit structs and/or enums declared in the module (section 3.3).
USER_CONSTRAINTS = {"eq": ("struct", "enum", "class"), "ord": ("enum",), "switch": ("enum",),
                    "any": ("struct", "enum", "class"), "convertible": ("enum",)}


def split_types(s: str) -> list:
    """`i32, map::<string, i32>, f32` -> the three types, splitting only at top-level commas."""
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch in "<(":
            depth += 1
        elif ch in ">)":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def _tlist(s: str) -> Optional[list]:
    s = s.strip()
    if not (s.startswith("(") and s.endswith(")")):
        return None
    return split_types(s[1:-1])


def delegate_sig(ty: str) -> Optional[tuple]:
    """`delegate::<(i32, f32) -> (bool)>` -> (["i32", "f32"], ["bool"]); None otherwise."""
    if not ty.startswith("delegate::<") or not ty.endswith(">"):
        return None
    inner = ty[len("delegate::<"):-1]
    depth, cut = 0, None
    for i, ch in enumerate(inner):
        if ch in "<(":
            depth += 1
        elif ch in ">)":
            depth -= 1
        elif depth == 0 and inner.startswith("->", i):
            cut = i
            break
    params = _tlist(inner if cut is None else inner[:cut])
    results = [] if cut is None else _tlist(inner[cut + 2:])
    if params is None or results is None:
        return None
    return params, results


def dispatcher_params(ty: str) -> Optional[list]:
    """`dispatcher::<(i32)>` -> ["i32"]; None otherwise."""
    if not ty.startswith("dispatcher::<") or not ty.endswith(">"):
        return None
    return _tlist(ty[len("dispatcher::<"):-1])


def delegate_type(params: list, results: list) -> str:
    """The canonical text of a delegate type (results left out when there are none)."""
    t = f"delegate::<({', '.join(params)})"
    return t + (f" -> ({', '.join(results)})>" if results else ">")


def dispatcher_type(params: list) -> str:
    return f"dispatcher::<({', '.join(params)})>"


def allows(constraint: str, ty: str, idx: "Optional[ModuleIndex]" = None) -> bool:
    """Whether a type argument meets a constraint of a registry kind."""
    if ty in CONSTRAINTS[constraint]:
        return True
    if constraint == "eq":
        # every value type has an equality (section 4.9), except a delegate
        return type_ok(ty, idx) and delegate_sig(ty) is None
    if idx is None:
        return False
    kinds = USER_CONSTRAINTS.get(constraint, ())
    return (("struct" in kinds and ty in idx.structs) or ("enum" in kinds and ty in idx.enums)
            or ("class" in kinds and (ty in idx.classes or ty in idx.interfaces)))


def type_choices(constraint: str, idx: "Optional[ModuleIndex]" = None) -> list:
    """Every type argument a constraint accepts, built-in types first, then the module's
    structs and enums by name: what the palette and menus offer."""
    out = list(CONSTRAINTS[constraint])
    if idx is not None:
        out += [t for t in sorted(idx.structs) + sorted(idx.enums)
                if allows(constraint, t, idx) and t not in out]
    return out


def plain_struct(ty: str, idx: "ModuleIndex") -> bool:
    """Whether a struct holds only primitives, enums and structs of those, as a map key or
    set item must (section 3.1). Structs never hold themselves by value (E0503), so the
    recursion ends; a cycle check guards it anyway."""
    path = set()

    def ok(t):
        if t in idx.structs:
            if t in path:
                return False
            path.add(t)
            result = all(ok(f.type) for f in idx.structs[t].fields)
            path.discard(t)
            return result
        return t in CONSTRAINTS["eq"] or t in idx.enums
    return ok(ty)


ZERO = object()  # pin default: the zero value of the pin's type


def array_elem(ty: str) -> Optional[str]:
    """The element type of `array::<T>`, else None."""
    if ty.startswith("array::<") and ty.endswith(">"):
        return ty[8:-1]
    return None


def map_types(ty: str) -> Optional[tuple]:
    """(K, V) of `map::<K, V>`, else None."""
    if ty.startswith("map::<") and ty.endswith(">"):
        depth = 0
        inner = ty[6:-1]
        for i, ch in enumerate(inner):
            depth += ch == "<"
            depth -= ch == ">"
            if ch == "," and depth == 0:
                return inner[:i].strip(), inner[i + 1:].strip()
    return None


def set_elem(ty: str) -> Optional[str]:
    """The element type of `set::<T>`, else None."""
    if ty.startswith("set::<") and ty.endswith(">"):
        return ty[6:-1]
    return None


def is_container(ty: str) -> bool:
    return array_elem(ty) is not None or map_types(ty) is not None or set_elem(ty) is not None


def key_type_ok(ty: str, idx: "Optional[ModuleIndex]" = None) -> bool:
    """A map key or set element: a primitive, a lane type, an enum, or a struct of those
    (section 3.1)."""
    if ty in CONSTRAINTS["eq"]:
        return True
    return idx is not None and (ty in idx.enums or (ty in idx.structs and plain_struct(ty, idx)))


# Built-in handle types (section 3.1): allowed for parameters, results, locals, state and
# variables, but not as struct fields or container elements, and with no Eq (section 4.5).
HANDLE_TYPES = {"std.Signal"}


def assignable(src: str, dst: str, idx: "Optional[ModuleIndex]" = None) -> bool:
    """Whether a value of type `src` may flow into a pin of type `dst`: the same type, a class
    into one of its bases, or any class into `anyref` (section 3.1)."""
    if src == dst:
        return True
    if idx is None:
        return False
    if src in idx.interfaces:
        return dst == "anyref"
    if src not in idx.classes:
        return False
    return dst == "anyref" or idx.is_subclass(src, dst) or idx.implements(src, dst)


def handle_ok(ty: str, idx: "Optional[ModuleIndex]" = None) -> bool:
    """type_ok, also accepting a handle type such as std.Signal."""
    return ty in HANDLE_TYPES or type_ok(ty, idx)


def type_ok(ty: str, idx: "Optional[ModuleIndex]" = None) -> bool:
    """A value type this prototype supports: a primitive, a struct or enum declared in the
    module (only when `idx` is given), or an array, map or set of supported types."""
    elem = array_elem(ty)
    if elem is not None:
        return type_ok(elem, idx)
    kv = map_types(ty)
    if kv is not None:
        return key_type_ok(kv[0], idx) and type_ok(kv[1], idx)
    elem = set_elem(ty)
    if elem is not None:
        return key_type_ok(elem, idx)
    sig = delegate_sig(ty)
    if sig is not None:
        return all(type_ok(t, idx) or t in HANDLE_TYPES for t in sig[0] + sig[1])
    return ty in PRIM_TYPES or ty in LANE_FIELDS or (idx is not None
                                                     and idx.user_type(ty) is not None)


def enum_values(en: Enum) -> list:
    """(member name, value) in declaration order. A member with no `= INT` is one more than
    the member before it; the first one is 0."""
    out, nxt = [], 0
    for m in en.members:
        v = m.value if m.value is not None else nxt
        out.append((m.name, v))
        nxt = v + 1
    return out


def substitute(ty: str, subst: dict) -> str:
    """Replace type parameter names in a type (generic macros)."""
    if not subst:
        return ty
    return re.sub(r"[A-Za-z_][A-Za-z0-9_]*", lambda m: subst.get(m.group(0), m.group(0)), ty)

REGISTRY_NAME = "wiret.core"
REGISTRY_VERSION = "0.1-proto"


def zero_lit(ty: str) -> Lit:
    if ty in LANE_DEFAULTS:
        return lane_lit(LANE_DEFAULTS[ty])
    if is_container(ty):
        return Lit("null", None)     # the empty container: containers are values, never null
    if ty == "bool":
        return Lit("bool", False)
    if ty in FLOAT_TYPES:
        return Lit("float", 0.0)
    if ty == "string":
        return Lit("string", "")
    return Lit("int", 0)


def lit_fits(lit: Lit, ty: str, idx: "Optional[ModuleIndex]" = None) -> bool:
    """Whether a literal can be written for a value of type `ty`. An enum takes a member of
    its own enum (`Mode.Chase`; whether the member exists is the checker's business). Structs
    have no literal form; arrays take only `null`, the empty array. A class reference, a
    signal and `anyref` take `null` (with `idx`, to know the classes)."""
    if lit.kind == "null" and (ty in ("anyref", "std.Signal") or delegate_sig(ty) is not None
                               or (idx is not None and (ty in idx.classes
                                                        or ty in idx.interfaces))):
        return True
    if lit.kind == "enum":
        return lit.value.rsplit(".", 1)[0] == ty
    if ty in LANE_FIELDS:
        return lane_lit_fits(lit, ty)
    if ty in INT_TYPES:
        return lit.kind == "int"
    if ty in FLOAT_TYPES:
        return lit.kind in ("int", "float")
    if ty == "bool":
        return lit.kind == "bool"
    if ty == "string":
        return lit.kind == "string"
    return is_container(ty) and lit.kind == "null"


def lit_in_range(lit: Lit, ty: str) -> bool:
    """For an integer type, whether the literal's value fits; any other type passes."""
    if ty not in INT_RANGES or lit.kind != "int":
        return True
    lo, hi = INT_RANGES[ty]
    return lo <= lit.value <= hi


def lit_equal(a: Lit, b: Lit) -> bool:
    if a.kind in ("int", "float") and b.kind in ("int", "float"):
        return a.value == b.value and (a.suffix == b.suffix)
    return a.kind == b.kind and a.value == b.value


def can_convert(src: str, dst: str, idx: "Optional[ModuleIndex]" = None) -> bool:
    if src == dst:
        return False
    if idx is not None and (src in idx.enums or dst in idx.enums):
        # an enum converts to its underlying integer type, and back (section 3.2)
        return idx.enum_base(src) == dst or idx.enum_base(dst) == src
    if dst == "string":
        return (src in PRIM_TYPES or src in LANE_FIELDS) and src != "string"
    if src in LANE_FIELDS or dst in LANE_FIELDS:     # only vec2 <-> vec3 (section 3.2)
        return {src, dst} == {"vec2", "vec3"}
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
    # Catchable faults (section 4.6). Try runs `body`; a fault inside it runs `fault`, with
    # the fault's message and code; when either chain ends, `then` runs.
    "Try": ("Flow", "impure", [], [("in", "in", "exec", None), ("body", "out", "exec", None),
                                   ("fault", "out", "exec", None), ("then", "out", "exec", None),
                                   ("message", "out", "string", None),
                                   ("code", "out", "i32", None)]),
    "Throw": ("Flow", "impure", [], [("in", "in", "exec", None), ("message", "in", "string", None),
                                     ("code", "in", "i32", ZERO)]),
    # Latent nodes (section 4.5): each suspends the fiber, only in latent graphs (E0201).
    "Delay": ("Time", "impure", [], [("in", "in", "exec", None), ("seconds", "in", "f64", None),
                                     ("then", "out", "exec", None)]),
    "Yield": ("Time", "impure", [], [("in", "in", "exec", None), ("then", "out", "exec", None)]),
    "Await": ("Time", "impure", [], [("in", "in", "exec", None),
                                     ("signal", "in", "std.Signal", None),
                                     ("then", "out", "exec", None)]),
    "BitNot": ("Bits", "pure", ["int"], _UN),
}
for _k in ("Add", "Sub", "Div", "Min", "Max"):
    STATIC_KINDS[_k] = ("Math", "pure", ["arith"], _BIN)
STATIC_KINDS["Mul"] = ("Math", "pure", ["mul"], _BIN)
STATIC_KINDS["Rem"] = ("Math", "pure", ["number"], _BIN)
for _k in ("Neg", "Abs"):
    STATIC_KINDS[_k] = ("Math", "pure", ["neg"], _UN)
# A vector times a number (section 3.1.1).
STATIC_KINDS["Scale"] = ("Math", "pure", ["vector"], [("v", "in", "T", None),
                                                      ("s", "in", "f32", None),
                                                      ("result", "out", "T", None)])
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
    "Macro": "Macro", "Exit": "Macro", "Leave": "Macro", "Call": "Call", "CallParent": "Call",
    "MakeArray": "Arrays", "ArrayGet": "Arrays", "ArrayLength": "Arrays", "ArraySet": "Arrays",
    "ArrayAdd": "Arrays", "ArrayInsert": "Arrays", "ArrayRemove": "Arrays", "ArrayClear": "Arrays",
    "GetLocal": "Variables", "SetLocal": "Variables", "GetVar": "Variables",
    "SetVar": "Variables", "GetState": "Variables", "SetState": "Variables",
    "MakeStruct": "Structs", "BreakStruct": "Structs", "GetField": "Structs",
    "WithField": "Structs",
    "MapFind": "Maps", "MapHas": "Maps", "MapLength": "Maps", "MapKeyAt": "Maps",
    "MapValueAt": "Maps", "MapSet": "Maps", "MapRemove": "Maps", "MapClear": "Maps",
    "SetHas": "Sets", "SetLength": "Sets", "SetAt": "Sets", "SetAdd": "Sets",
    "SetRemove": "Sets", "SetClear": "Sets",
    "Format": "Text",
}

# Struct kinds and how their symbol is written: the struct (`MakeStruct Vec2`), or the struct
# and one of its fields (`GetField Vec2.x`).
STRUCT_KINDS = {"MakeStruct": "struct", "BreakStruct": "struct", "GetField": "field",
                "WithField": "field"}

# Kinds from the specification that later tiers add (section 1.6).
LATER_TIER_KINDS: set = set()     # every kind of section 3.3 is now in the prototype

DELEGATE_KINDS = {"CreateDelegate", "Invoke", "Bind", "Unbind", "Broadcast"}

ALL_KINDS = sorted(set(STATIC_KINDS) | set(CONTEXT_KINDS))

# Array mutators change a place (section 3.3): (extra input pins as (name, type or "T"))
ARRAY_MUTATORS = {
    "ArraySet": [("index", "i32"), ("item", "T")],
    "ArrayAdd": [("item", "T")],
    "ArrayInsert": [("index", "i32"), ("item", "T")],
    "ArrayRemove": [("index", "i32")],
    "ArrayClear": [],
}

# Map and set kinds (section 3.3). Pins use K, V (maps) and T (sets). Pure kinds:
# (inputs after the container, outputs). Mutators change a place like the array mutators:
# (extra inputs, outputs), where the output says whether anything changed.
MAP_PURE = {
    "MapFind": ([("key", "K")], [("value", "V"), ("found", "bool")]),
    "MapHas": ([("key", "K")], [("result", "bool")]),
    "MapLength": ([], [("length", "i32")]),
    "MapKeyAt": ([("index", "i32")], [("key", "K")]),
    "MapValueAt": ([("index", "i32")], [("value", "V")]),
}
MAP_MUTATORS = {
    "MapSet": ([("key", "K"), ("value", "V")], []),
    "MapRemove": ([("key", "K")], [("removed", "bool")]),
    "MapClear": ([], []),
}
SET_PURE = {
    "SetHas": ([("item", "T")], [("result", "bool")]),
    "SetLength": ([], [("length", "i32")]),
    "SetAt": ([("index", "i32")], [("item", "T")]),
}
SET_MUTATORS = {
    "SetAdd": ([("item", "T")], [("added", "bool")]),
    "SetRemove": ([("item", "T")], [("removed", "bool")]),
    "SetClear": ([], []),
}

# Every kind that changes a place: `ArrayAdd::<i32> acc`, `MapSet::<string, i32> scores`.
PLACE_MUTATORS = set(ARRAY_MUTATORS) | set(MAP_MUTATORS) | set(SET_MUTATORS)


@dataclass
class Callee:
    name: str          # resolved name: local graph name or qualified native/extern name
    kind: str          # func | event | extern | native
    params: list       # [Pin]
    results: list      # [Pin]
    purity: str
    latent: bool = False   # may suspend: an event, a @latent func (section 4.5)
    method_of: Optional[str] = None   # a method: the class named in the symbol (self's type)
    final: bool = False               # a @final method: called directly, not through the vtable


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
        self.structs = {i.name: i for i in module.items if isinstance(i, Struct)}
        for name in LANE_TYPES:              # built-in structs (section 3.1.1); a declaration
            self.structs.setdefault(name, lane_struct(name))   # of one is E0102
        self.enums = {i.name: i for i in module.items if isinstance(i, Enum)}
        self.classes = {i.name: i for i in module.items if isinstance(i, Class)}
        self.interfaces = {i.name: i for i in module.items if isinstance(i, Interface)}
        self._instances = {}

    # -- classes (section 2.2) ---------------------------------------------------------
    def class_chain(self, name: str) -> list:
        """The class and its bases, nearest first. Stops at a cycle or an unknown base."""
        out = []
        while name in self.classes and name not in out:
            out.append(name)
            name = self.classes[name].base
        return out

    def is_subclass(self, sub: str, sup: str) -> bool:
        return sup in self.class_chain(sub)

    def class_fields(self, name: str) -> list:
        """(declaring class, Field) for every field, inherited ones first: the object layout."""
        out = []
        for c in reversed(self.class_chain(name)):
            out += [(c, f) for f in self.classes[c].fields]
        return out

    def class_field(self, name: str, fname: str):
        """(declaring class, Field) of a field of `name` or one of its bases, or None."""
        for c in self.class_chain(name):
            f = self.classes[c].field(fname)
            if f is not None:
                return c, f
        return None

    def find_method(self, cls: str, short: str) -> Optional[Graph]:
        """The method `short` as seen from `cls`: its own, else the nearest base's."""
        for c in self.class_chain(cls):
            g = self.graphs.get(f"{c}.{short}")
            if g is not None:
                return g
        return None

    def class_dispatcher(self, cls: str, name: str):
        """(declaring class, Dispatcher) of `name` on `cls` or one of its bases, or None."""
        for c in self.class_chain(cls):
            d = next((x for x in self.classes[c].dispatchers if x.name == name), None)
            if d is not None:
                return c, d
        return None

    def class_layout(self, name: str) -> list:
        """(member name, type) of every slot of an object, inherited ones first: for each
        class its fields, then its dispatchers, then the `state` of its methods (section 5.3)."""
        out = []
        for c in reversed(self.class_chain(name)):
            out += [(f.name, f.type) for f in self.classes[c].fields]
            out += [(d.name, dispatcher_type([p.type for p in d.params]))
                    for d in self.classes[c].dispatchers]
            out += [(slot, ty) for slot, ty, _ in self.class_state(c)]
        return out

    def class_state(self, cls: str) -> list:
        """(slot name, type, default) for the `state` of a class's own methods, macro state
        expanded in them included, in a fixed order. In a method, state lives on the object
        (section 2.3): `Tick.count`, or `Tick/loop.done` for a macro expanded at node loop."""
        out = []
        for g in self.methods(cls):
            for path, s in self.graph_states(g):
                where = f"{g.short_name}/{path}" if path else g.short_name
                out.append((f"{where}.{s.name}", s.type, s.default))
        return out

    def graph_states(self, g: Graph, path: str = "", depth: int = 0) -> list:
        """(macro path, Local) for the state slots a graph needs: its own, then each macro's,
        node by node, as macro expansion visits them."""
        out = [(path, s) for s in sorted(g.states, key=lambda s: s.name)]
        if depth > 32:
            return out
        for n in sorted(g.nodes, key=lambda n: n.id):
            if n.kind == "Macro":
                mg = self.macro(n.symbol, n.targs)
                if mg is not None:
                    out += self.graph_states(mg, f"{path}{n.id}/" if path else f"{n.id}/",
                                             depth + 1)
        return [(p.rstrip("/"), s) for p, s in out]

    def class_interfaces(self, cls: str) -> list:
        """Every interface a class implements, its bases' first, in declaration order."""
        out = []
        for c in reversed(self.class_chain(cls)):
            out += [i for i in self.classes[c].impls if i in self.interfaces and i not in out]
        return out

    def implements(self, cls: str, iface: str) -> bool:
        return iface in self.class_interfaces(cls)

    def methods(self, cls: str) -> list:
        return sorted((g for g in self.graphs.values() if g.owner == cls), key=lambda g: g.name)

    def user_type(self, ty: str):
        """The struct or enum a type name refers to. Types are named without the module
        prefix (`Vec2`, not `game.demo.Vec2`)."""
        return (self.structs.get(ty) or self.enums.get(ty) or self.classes.get(ty)
                or self.interfaces.get(ty))

    def enum_base(self, ty: str) -> Optional[str]:
        """The underlying integer type of an enum type (default `i32`), else None."""
        en = self.enums.get(ty)
        return (en.base or "i32") if en is not None else None

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

    def callee(self, symbol: str, targs=()) -> Optional[Callee]:
        if targs:                  # a generic native: `std.vec.Dot::<vec3>` (section 3.4)
            key = f"{symbol}::<{', '.join(targs)}>"
            n = STD.get(key)
            if n is None:
                return None
            return Callee(key, "native", [Pin(a, t) for a, t in n.params],
                          [Pin(a, t) for a, t in n.results], n.purity)
        s = self._strip(symbol)
        cls, _, short = s.rpartition(".")
        if cls in self.interfaces:                 # dispatched through the interface (5.6)
            m = self.interfaces[cls].method(short)
            if m is None:
                return None
            return Callee(s, "interface",
                          [Pin("self", cls)] + [Pin(p.name, p.type, p.default) for p in m.params],
                          [Pin(r.name, r.type) for r in m.result_list], "impure",
                          m.has_attr("latent"), cls)
        g = self.graphs.get(s)
        if g is None and cls in self.classes:
            g = self.find_method(cls, short)      # an inherited method: `Boss.Heal`
        if g is not None:
            purity = "pure" if g.has_attr("pure") else "reads" if g.has_attr("reads") else "impure"
            params = [Pin(p.name, p.type, p.default) for p in g.params]
            if g.owner:                            # methods take self first (section 2.2)
                params = [Pin("self", cls)] + params
            return Callee(g.name, g.kind, params, [Pin(r.name, r.type) for r in g.result_list],
                          purity, g.kind == "event" or g.has_attr("latent"),
                          cls if g.owner else None, g.has_attr("final"))
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


def _static_sig(node: Node, idx: "Optional[ModuleIndex]" = None) -> Sig:
    cat, purity, tps, pins = STATIC_KINDS[node.kind]
    sig = Sig(purity=purity, category=cat)
    targs = list(node.targs)
    if len(targs) != len(tps):
        sig.error = ("E0502", f"{node.kind} needs {len(tps)} type argument(s), got {len(targs)}")
        targs = (targs + ["i32"] * len(tps))[: len(tps)]
    else:
        for t, c in zip(targs, tps):
            if not allows(c, t, idx):
                sig.error = ("E0110", f"{node.kind} does not accept type {t}")
    if node.kind == "Convert" and not sig.error and not can_convert(targs[0], targs[1], idx) \
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
        return _static_sig(node, idx)
    E = "exec"
    sig = Sig(category=CONTEXT_KINDS.get(k, "Other"))
    is_macro = graph.kind == "macro"

    if k == "Entry":
        if is_macro:
            sig.outputs = [Pin(p.name, p.type) for p in graph.params]
        else:
            sig.outputs = [Pin("then", E)] + [Pin(p.name, p.type) for p in graph.params]
            if graph.owner:                        # a method's implicit receiver
                sig.outputs.insert(1, Pin("self", graph.owner))
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
        if not allows("switch", t, idx):
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
        c = idx.callee(node.symbol or "", node.targs)
        if c is None:
            generic = [q for q in STD if q.startswith(f"{node.symbol}::<")]
            if generic and not node.targs:
                sig.error = ("E0502", f"'{node.symbol}' needs a type argument, as in "
                                      f"'Call {generic[0]}'")
            elif generic:
                sig.error = ("E0110", f"'{node.symbol}' does not take "
                                      f"{', '.join(node.targs)}; it takes "
                                      f"{', '.join(q[len(node.symbol):] for q in generic)}")
            else:
                sig.error = ("E0501", f"unresolved function '{node.symbol}'")
            return sig
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
        bad = [t for t in node.targs if not type_ok(t, idx)]
        if bad:
            sig.error = ("E0501", f"type '{bad[0]}' is not supported by this prototype")
            return sig
        m = idx.macro(node.symbol, node.targs)
        sig.inputs = [Pin(p.name, p.type, p.default) for p in m.params]
        sig.outputs = [Pin(r.name, r.type) for r in m.result_list]
        return sig
    if k in ("Exit", "Leave"):         # Leave also discards the macro's continuations (4.2)
        if not is_macro:
            sig.error = ("E0501", f"{k} is only allowed in a macro")
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
    if k in DELEGATE_KINDS:
        return _delegate_sig(node, graph, idx, sig)
    if k == "CallParent":
        return _call_parent_sig(node, graph, idx, sig)
    if k in CLASS_KINDS or (k in ("GetField", "SetField") and class_field_target(node, graph, idx)):
        return _class_sig(node, graph, idx, sig)
    if k in STRUCT_KINDS:
        return _struct_sig(node, idx, sig)
    if k in MAP_PURE or k in MAP_MUTATORS or k in SET_PURE or k in SET_MUTATORS:
        return _container_sig(node, graph, idx, sig)
    if k == "Format":
        return _format_sig(node, graph, idx, sig)
    if k == "SetField" and (node.symbol or "").split(".")[0] in idx.structs:
        sig.error = ("E0501", f"structs are immutable, so SetField cannot change one; use "
                              f"'WithField {node.symbol}', which makes a changed copy")
        return sig
    if k in LATER_TIER_KINDS:
        sig.error = ("E0501", f"node kind '{k}' belongs to a later tier and is not in this prototype")
    else:
        sig.error = ("E0501", f"unknown node kind '{k}'")
    return sig


CLASS_KINDS = {"New", "Cast", "IsValid"}


_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")


def format_parts(template: str) -> list:
    """A Format template (section 3.3) as [("text", s) | ("pin", name)]: `{name}` is an
    input, `{{` and `}}` are literal braces. Raises ValueError for a malformed template."""
    parts, buf, i, t = [], [], 0, template
    while i < len(t):
        c = t[i]
        if t.startswith("{{", i) or t.startswith("}}", i):
            buf.append(c)
            i += 2
        elif c == "{":
            j = t.find("}", i)
            name = t[i + 1:j] if j >= 0 else ""
            if j < 0 or not _IDENT.match(name):
                raise ValueError(f"a Format template names an input between braces, as in "
                                 f"'{{total}}', and writes a brace as '{{{{' or '}}}}'; "
                                 f"'{t[i:j + 1] if j >= 0 else t[i:]}' is neither")
            if buf:
                parts.append(("text", "".join(buf)))
                buf = []
            parts.append(("pin", name))
            i = j + 1
        elif c == "}":
            raise ValueError("a '}' in a Format template closes no '{'; write a brace as '}}'")
        else:
            buf.append(c)
            i += 1
    if buf:
        parts.append(("text", "".join(buf)))
    return parts


_FORMAT_BUSY: set = set()


def _format_input_type(node: Node, name: str, graph: Graph, idx: ModuleIndex) -> str:
    """A Format input takes the type of what is bound to it: the output it reads, or the
    literal's own type (an unsuffixed integer is i32, a decimal f64). Unbound, it is text."""
    b = node.binding(name)
    if b is None:
        return "string"
    v = b.value
    if isinstance(v, Lit):
        return {"int": v.suffix or "i32", "float": v.suffix or "f64", "bool": "bool",
                "string": "string"}.get(v.kind, v.value.split(".")[0] if v.kind == "enum"
                                        else v.kind)
    src = graph.node(v.node)
    key = (id(graph), v.node)
    if src is None or key in _FORMAT_BUSY:      # a missing node or a cycle: reported elsewhere
        return "string"
    _FORMAT_BUSY.add(key)
    try:
        p = signature(src, graph, idx).output(v.pin)
    finally:
        _FORMAT_BUSY.discard(key)
    return p.type if p is not None and not p.is_exec else "string"


def _format_sig(node: Node, graph: Graph, idx: ModuleIndex, sig: Sig) -> Sig:
    """`Format "Total: {total}"(.total <- ...)`: text built from a template, with an input
    per placeholder that takes a bool, a number or a string (section 3.3)."""
    sig.purity = "pure"
    sig.outputs = [Pin("result", "string")]
    if node.symbol is None:
        sig.error = ("E0501", 'Format needs a template, as in Format "Total: {total}"(...)')
        return sig
    if node.targs:
        sig.error = ("E0502", "Format takes no type arguments: each input takes the type of "
                              "what is bound to it")
    try:
        parts = format_parts(node.symbol)
    except ValueError as e:
        sig.error = ("E0501", str(e))
        return sig
    names = []
    for kind, v in parts:
        if kind == "pin" and v not in names:
            names.append(v)
    for name in names:
        ty = _format_input_type(node, name, graph, idx)
        if ty not in PRIM_TYPES and ty not in LANE_FIELDS and not sig.error:
            sig.error = ("E0110", f"Format writes bool, number, vector and string values, "
                                  f"but '{name}' is {ty}; convert it first")
        sig.inputs.append(Pin(name, ty, ZERO if node.binding(name) is None else None))
    return sig


def class_field_target(node: Node, graph: Graph, idx: ModuleIndex):
    """For GetField and SetField on a class: (class, field name). The symbol is the bare field
    name inside the class's own methods (`GetField health`), else `Class.field`."""
    sym = node.symbol or ""
    cls, _, fname = sym.rpartition(".")
    if cls:
        return (cls, fname) if cls in idx.classes else None
    if graph is not None and graph.owner:
        return graph.owner, sym
    return None


def parent_method(node: Node, graph: Graph, idx: ModuleIndex) -> Optional[Graph]:
    """The method CallParent calls: the nearest base class's version of the symbol."""
    if graph is None or not graph.owner or graph.owner not in idx.classes:
        return None
    base = idx.classes[graph.owner].base
    return idx.find_method(base, node.symbol or graph.short_name) if base else None


def _call_parent_sig(node: Node, graph: Graph, idx: ModuleIndex, sig: Sig) -> Sig:
    """`CallParent TakeDamage`: inside an override, the base class's version of a method,
    called directly on the method's own `self` (Blueprint's Parent node)."""
    sig.category = "Call"
    g = parent_method(node, graph, idx)
    if g is None:
        where = f"'{graph.owner}'s base class" if graph is not None and graph.owner else \
            "a base class"
        sig.error = ("E0501", f"CallParent calls {where}'s version of a method, so it belongs "
                              f"in a method whose class extends a class that has "
                              f"'{node.symbol}'")
        sig.inputs, sig.outputs = [Pin("in", "exec")], [Pin("then", "exec")]
        return sig
    c = idx.callee(g.name)
    sig.purity = c.purity
    if c.purity == "impure":
        sig.inputs, sig.outputs = [Pin("in", "exec")], [Pin("then", "exec")]
    sig.inputs += c.params[1:]                 # self is the method's own
    sig.outputs += c.results
    return sig


def bindable(c: "Callee") -> Optional[str]:
    """Why a callee cannot be bound into a delegate, or None when it can (section 3.3)."""
    if c.kind not in ("func", "event"):
        return f"only a function, method or event of this module can be bound, not a {c.kind}"
    if c.latent and c.kind != "event":
        return ("a @latent func cannot be bound, since invoking a delegate never waits; "
                "make it an event, which a delegate starts on a fiber of its own")
    return None


def dispatcher_target(node: Node, graph: Graph, idx: ModuleIndex):
    """For Bind, Unbind and Broadcast: (class, dispatcher name), with the bare name inside the
    class's own methods (`Broadcast OnDied`) and `Class.OnDied` anywhere else."""
    sym = node.symbol or ""
    cls, _, name = sym.rpartition(".")
    if cls:
        return cls, name
    return (graph.owner, sym) if graph is not None and graph.owner else (None, sym)


def _delegate_sig(node: Node, graph: Graph, idx: ModuleIndex, sig: Sig) -> Sig:
    """CreateDelegate, Invoke, Bind, Unbind and Broadcast (section 3.3)."""
    k = node.kind
    E = "exec"
    sig.category = "Delegates"
    if k == "CreateDelegate":
        sig.purity = "pure"
        c = idx.callee(node.symbol or "")
        if c is None:
            sig.error = ("E0501", f"unresolved function '{node.symbol}'")
            sig.outputs = [Pin("result", "delegate::<()>")]
            return sig
        why = bindable(c)
        if why:
            sig.error = ("E0501", f"cannot make a delegate of '{node.symbol}': {why}")
        params = c.params[1:] if c.method_of else c.params
        if c.method_of:                        # the receiver to bind
            sig.inputs = [Pin("target", c.method_of)]
        sig.outputs = [Pin("result", delegate_type([p.type for p in params],
                                                   [r.type for r in c.results]))]
        return sig
    if k == "Invoke":
        d = node.targs[0] if len(node.targs) == 1 else None
        ds = delegate_sig(d) if d else None
        if ds is None:
            sig.error = ("E0502", "Invoke needs the delegate type, as in "
                                  "'Invoke::<delegate::<(i32) -> (bool)>>'")
            ds, d = ([], []), "delegate::<()>"
        sig.inputs = [Pin("in", E), Pin("delegate", d)] + [Pin(f"arg{i}", t)
                                                           for i, t in enumerate(ds[0])]
        sig.outputs = [Pin("then", E)] + [Pin(f"result{i}", t) for i, t in enumerate(ds[1])]
        return sig
    cls, name = dispatcher_target(node, graph, idx)
    found = idx.class_dispatcher(cls, name) if cls in idx.classes else None
    if found is None:
        sig.error = ("E0501", f"class '{cls}' has no dispatcher '{name}'" if cls in idx.classes
                     else f"{k} names a dispatcher, as in '{k} Player.OnDied'")
        params = []
    else:
        params = found[1].params
    sig.inputs = [Pin("in", E), Pin("obj", cls or "anyref")]
    if k == "Broadcast":
        sig.inputs += [Pin(p.name, p.type, p.default) for p in params]
    else:
        sig.inputs.append(Pin("handler", delegate_type([p.type for p in params], [])))
    sig.outputs = [Pin("then", E)]
    return sig


def _class_sig(node: Node, graph: Graph, idx: ModuleIndex, sig: Sig) -> Sig:
    """New, Cast, IsValid and the class forms of GetField and SetField (section 3.3)."""
    k = node.kind
    E = "exec"
    sig.category = "Classes"
    if k == "New":
        if node.symbol not in idx.classes:
            sig.error = ("E0501", f"New names the class to make, as in 'New Player'; "
                                  f"'{node.symbol}' is not a class of this module")
        sig.inputs = [Pin("in", E)]
        sig.outputs = [Pin("then", E), Pin("result", node.symbol or "anyref")]
        return sig
    if k == "Cast":
        sig.purity = "pure"
        target = node.symbol
        known = target in idx.classes or target in idx.interfaces
        if not known or node.targs:
            sig.error = ("E0501", "Cast names the class or interface to cast to, as in "
                                  "'Cast Boss'")
            target = target if known else None
        sig.inputs = [Pin("obj", "anyref")]
        sig.outputs = [Pin("result", target or "anyref"), Pin("ok", "bool")]
        return sig
    if k == "IsValid":
        sig.purity = "pure"
        sig.inputs = [Pin("obj", "anyref")]
        sig.outputs = [Pin("result", "bool")]
        return sig
    cls, fname = class_field_target(node, graph, idx)
    found = idx.class_field(cls, fname) if cls in idx.classes else None
    if found is None:
        sig.error = ("E0501", f"class '{cls}' has no field '{fname}'" if cls in idx.classes
                     else f"unknown class '{cls}'")
        ty = "i32"
    else:
        ty = found[1].type
    if k == "GetField":
        # reads purity: re-evaluated at each consumer's evaluation point (section 4.3)
        sig.purity = "reads"
        sig.inputs = [Pin("obj", cls)]
        sig.outputs = [Pin("value", ty)]
    else:
        sig.inputs = [Pin("in", E), Pin("obj", cls), Pin("value", ty)]
        sig.outputs = [Pin("then", E)]
    return sig


def _struct_sig(node: Node, idx: ModuleIndex, sig: Sig) -> Sig:
    """MakeStruct, BreakStruct, GetField, WithField (section 3.3). All are pure: a struct is a
    value, so reading one cannot see a change (section 4.3)."""
    k = node.kind
    sig.purity = "pure"
    sym = node.symbol or ""
    if STRUCT_KINDS[k] == "field":
        name, _, fname = sym.partition(".")
        if not fname:
            sig.error = ("E0501", f"{k} names the struct and the field, as in '{k} Vec2.x'")
            return sig
    else:
        name, fname = sym, None
        if not sym or "." in sym:
            sig.error = ("E0501", f"{k} names the struct it works on, as in '{k} Vec2'")
            return sig
    if node.targs:
        sig.error = ("E0501", f"{k} takes no type arguments; the struct's name says the type")
        return sig
    st = idx.structs.get(name)
    if st is None:
        what = "that is an enum" if name in idx.enums else "no struct of this module has that name"
        sig.error = ("E0501", f"unknown struct '{name}': {what}")
        return sig
    if k == "MakeStruct":
        sig.inputs = [Pin(f.name, f.type, f.default if f.default is not None else ZERO)
                      for f in st.fields]
        sig.outputs = [Pin("result", name)]
        return sig
    if k == "BreakStruct":
        sig.inputs = [Pin("obj", name)]
        sig.outputs = [Pin(f.name, f.type) for f in st.fields]
        return sig
    f = st.field(fname)
    if f is None:
        sig.error = ("E0501", f"struct '{name}' has no field '{fname}'")
        return sig
    if k == "GetField":
        sig.inputs = [Pin("obj", name)]
        sig.outputs = [Pin("value", f.type)]
    else:
        sig.inputs = [Pin("obj", name), Pin("value", f.type)]
        sig.outputs = [Pin("result", name)]
    return sig


def field_place(place: Optional[str], graph: Graph, idx: ModuleIndex) -> Optional[tuple]:
    """A mutator place that is a class field (section 3.3): `Player.items` anywhere, or the
    bare `items` inside the class's own methods when no local or variable has that name.
    (class, field name, type), or None."""
    if not place:
        return None
    cls, _, fname = place.rpartition(".")
    if not cls:
        if graph is None or not graph.owner or graph.local(place) or place in idx.vars:
            return None
        cls = graph.owner
    if cls not in idx.classes:
        return None
    found = idx.class_field(cls, fname)
    return (cls, fname, found[1].type) if found else None


def place_type(place: Optional[str], graph: Graph, idx: ModuleIndex) -> Optional[str]:
    """The type of a mutator's place: a local of the graph, a module variable, or a field
    of an object."""
    if not place:
        return None
    loc = graph.local(place)
    if loc:
        return loc.type
    if place in idx.vars:
        return idx.vars[place].type
    fp = field_place(place, graph, idx)
    return fp[2] if fp else None


def _container_sig(node: Node, graph: Graph, idx: ModuleIndex, sig: Sig) -> Sig:
    """Map and set kinds (section 3.3)."""
    k = node.kind
    is_map = k.startswith("Map")
    want = 2 if is_map else 1
    example = f"{k}::<string, i32>" if is_map else f"{k}::<i32>"
    if len(node.targs) != want:
        sig.error = ("E0502", f"{k} needs {'the key and value types' if is_map else 'the item type'}"
                              f", as in {example}")
    targs = (list(node.targs) + ["i32", "i32"])[:want]
    if is_map:
        K, V = targs
        container, cname = f"map::<{K}, {V}>", "map"
        subst = {"K": K, "V": V}
        bad_key = None if key_type_ok(K, idx) else K
        bad_value = None if type_ok(V, idx) else V
    else:
        T = targs[0]
        container, cname = f"set::<{T}>", "set"
        subst = {"T": T}
        bad_key, bad_value = (None if key_type_ok(T, idx) else T), None
    if sig.error is None and bad_key is not None:
        sig.error = ("E0501", f"type '{bad_key}' cannot be a {cname} {'key' if is_map else 'item'}"
                              f": keys and set items are primitives, enums or structs of those")
    elif sig.error is None and bad_value is not None:
        sig.error = ("E0501", f"type '{bad_value}' is not supported by this prototype")
    pure = MAP_PURE if is_map else SET_PURE
    if k in pure:
        ins, outs = pure[k]
        sig.purity = "pure"
        sig.inputs = [Pin(cname, container)] + [Pin(n, subst.get(t, t)) for n, t in ins]
        sig.outputs = [Pin(n, subst.get(t, t)) for n, t in outs]
        return sig
    ins, outs = (MAP_MUTATORS if is_map else SET_MUTATORS)[k]
    place = node.symbol
    ty = place_type(place, graph, idx)
    if ty is None:
        sig.error = ("E0130", f"{k} must name the local, variable or field it changes, as in "
                              f"{example} scores")
    elif ty != container and not sig.error:
        sig.error = ("E0110", f"'{place}' is {ty}, not {container}")
    fp = field_place(place, graph, idx) if not graph.local(place or "") else None
    sig.inputs = [Pin("in", "exec")] + ([Pin("obj", fp[0])] if fp else []) + \
        [Pin(n, subst.get(t, t)) for n, t in ins]
    sig.outputs = [Pin("then", "exec")] + [Pin(n, subst.get(t, t)) for n, t in outs]
    return sig


def _array_sig(node: Node, graph: Graph, idx: ModuleIndex, sig: Sig) -> Sig:
    k = node.kind
    if len(node.targs) != 1:
        sig.error = ("E0502", f"{k} needs one type argument: the element type, as in {k}::<i32>")
    t = node.targs[0] if node.targs else "i32"
    if not type_ok(t, idx):
        sig.error = ("E0501", f"type '{t}' is not supported by this prototype")
    arr = f"array::<{t}>"
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
        # A mutator changes a place: a local or a module variable of type array::<T>.
        place = node.symbol
        ty = place_type(place, graph, idx)
        if not place or ty is None:
            sig.error = ("E0130", f"{k} must name the local, variable or field it changes, as "
                                  f"in {k}::<{t}> scores")
        elif ty != arr and not sig.error:
            sig.error = ("E0110", f"'{place}' is {ty}, not {arr}")
        fp = field_place(place, graph, idx) if not graph.local(place or "") else None
        sig.inputs = [Pin("in", "exec")] + ([Pin("obj", fp[0])] if fp else []) + \
            [Pin(n, t if pt == "T" else pt) for n, pt in ARRAY_MUTATORS[k]]
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
