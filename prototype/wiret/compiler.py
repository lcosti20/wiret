"""Macro expansion, lowering and WBC emission (spec sections 4.2, 4.3 and 4.8).

Every impure node becomes one block labelled with its (path-style) node id. A block
evaluates the pure subgraph feeding its inputs at that node's evaluation point, performs
the node's operation, stores its outputs in frame slots and ends with an exec transfer.
This is the `-O0` lowering: `cont.push` / `cont.pop` pairs are kept.
"""
from __future__ import annotations

import hashlib
import struct
import zlib
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from . import lanes, wbc
from .checker import Diag, check, has_errors
from .model import Const, Extern, Graph, Lit, Module, Node, PinRef, Var
from .natives import INTERNAL, STD
from .printer import layout_hash, print_module, semantic_hash
from .registry import (class_field_target, field_place, parent_method, delegate_sig, dispatcher_params, dispatcher_target,
                       ARRAY_MUTATORS, FLOAT_TYPES, INT_TYPES, MAP_PURE, PLACE_MUTATORS,
                       REGISTRY_NAME, REGISTRY_VERSION, SET_PURE,
                       SIGNED_TYPES, ModuleIndex, Pin, Sig, array_elem, attr_int, enum_values,
                       format_parts, is_container, map_types, set_elem, signature, zero_lit,
                       lane_value)

# map and set kinds -> their instruction (section 5.6)
CONTAINER_OPS = {"MapFind": "map.find", "MapHas": "map.has", "MapLength": "map.len",
                 "MapKeyAt": "map.key_at", "MapValueAt": "map.value_at", "MapSet": "map.set",
                 "MapRemove": "map.remove", "MapClear": "map.clear", "SetHas": "set.has",
                 "SetLength": "set.len", "SetAt": "set.at", "SetAdd": "set.add",
                 "SetRemove": "set.remove", "SetClear": "set.clear"}
from .wbc import F32, F64, FAULT, I32, I64, SIGNAL, STRING

COMPILER_VERSION = "wiretc-proto 0.1"

VT = {"bool": I32, "i8": I32, "u8": I32, "i16": I32, "u16": I32, "i32": I32, "u32": I32,
      "i64": I64, "u64": I64, "f32": F32, "f64": F64, "string": STRING, "fault": FAULT,
      "std.Signal": SIGNAL}
PFX = {I32: "i32", I64: "i64", F32: "f32", F64: "f64"}
# The lane types (section 3.1.1): their value types and instruction prefixes.
LANE_VT = {name: vt for vt, name in wbc.LANE_VTS.items()}
LP = lanes.PREFIX                          # "vec3" -> "v3"
# arithmetic kinds -> lane operation, for the types section 3.1.1 allows them on
LANE_ARITH = {"Add": "add", "Sub": "sub", "Mul": "mul", "Div": "div", "Min": "min",
              "Max": "max", "Neg": "neg", "Abs": "abs", "Scale": "scale", "Eq": "eq",
              "Ne": "ne"}


def wrap_int(ty: str, v: int) -> int:
    """Normalise an integer to the signed representation of its slot."""
    bits = {"i8": 8, "u8": 8, "i16": 16, "u16": 16}.get(ty)
    if bits:
        v &= (1 << bits) - 1
        if ty.startswith("i") and v >= 1 << (bits - 1):
            v -= 1 << bits
        return v
    width = 64 if VT[ty] == I64 else 32
    v &= (1 << width) - 1
    return v - (1 << width) if v >= 1 << (width - 1) else v


@dataclass
class Src:
    kind: str        # lit | local | node
    a: object        # Lit | local name | node id
    b: object = None  # pin name (node)
    type: str = "i32"


@dataclass
class IRNode:
    id: str
    kind: str
    sig: Optional[Sig]
    symbol: Optional[str] = None
    targs: list = field(default_factory=list)
    inputs: list = field(default_factory=list)   # [(pin, type, Src)]
    execs: list = field(default_factory=list)    # [(pin, target id | None)]
    pure: bool = False
    extra: dict = field(default_factory=dict)
    attrs: list = field(default_factory=list)

    @property
    def data_outs(self):
        return self.sig.data_outs if self.sig else []


@dataclass
class Ctx:
    graph: Graph
    prefix: str
    mpath: Optional[str]
    sigs: dict
    params: dict = field(default_factory=dict)
    locals: dict = field(default_factory=dict)
    states: dict = field(default_factory=dict)
    depth: Optional[str] = None    # a macro with Leave: the local holding its entry depth + 1
    exits: dict = field(default_factory=dict)
    results: dict = field(default_factory=dict)


@dataclass
class CompileResult:
    ok: bool
    diags: list
    wbc: Optional[bytes] = None
    module: Optional[wbc.WbcModule] = None


LAZY_KINDS = ("Select", "And", "Or")   # evaluate only the inputs they need


class EvalPoint:
    def __init__(self):
        self.uses = Counter()
        self.temps = {}


class Compiler:
    def __init__(self, module: Module, source: Optional[str] = None, embed_source=True,
                 debug=False, project=None, export_all=False):
        self.m = module
        # Export mode (section 5.2): a normal build exports only what is marked @export; an
        # --export-all build (wiretc run, the editor) also exports every func, event and method
        # so that any of them can be run by name.
        self.export_all = export_all
        self.project = project     # for the [capabilities] allow check (E0160)
        self.debug = debug   # -Og: keep every pin's value in a local for the debugger
        self.idx = ModuleIndex(module)
        self.source = source
        self.embed_source = embed_source
        self.diags: list[Diag] = []
        self.globals = []          # [(name, type, init value)]
        self.global_index = {}
        self.data = []
        self.data_index = {}
        self.imports = []          # qualified native names
        self.import_index = {}
        self.types: list = []      # WBC type entries, shared by functions and arrays
        self.type_keys: dict = {}
        self.funcs = sorted(module.graphs(("func", "event")), key=lambda g: g.name)
        self.func_names = {g.name: i for i, g in enumerate(self.funcs)}
        self.caps = set()
        self.uses_lanes = False

    # -- tables -------------------------------------------------------------------
    def vt(self, ty: str):
        """The WBC value type of a Wiret type. An enum is its underlying integer; arrays and
        structs become references to type entries."""
        if ty == "anyref":
            return wbc.ANYREF
        if ty in LANE_VT:
            self.uses_lanes = True           # container feature bit 1 (section 5.2)
            return LANE_VT[ty]
        elem = array_elem(ty)
        if elem is not None:
            return wbc.Ref(self.array_type(elem))
        kv = map_types(ty)
        if kv is not None:
            return wbc.Ref(self.map_type(*kv))
        elem = set_elem(ty)
        if elem is not None:
            return wbc.Ref(self.set_type(elem))
        if ty in self.idx.structs:
            return wbc.Ref(self.struct_type(ty))
        if ty in self.idx.classes:
            return wbc.Ref(self.class_type(ty))
        if ty in self.idx.interfaces:
            return wbc.Ref(self.interface_type(ty))
        sig = delegate_sig(ty)
        if sig is not None:
            return wbc.Ref(self.callable_type("delegate", sig[0], sig[1]))
        params = dispatcher_params(ty)
        if params is not None:
            return wbc.Ref(self.callable_type("dispatcher", params, []))
        return VT[self.base(ty)]

    def base(self, ty: str) -> str:
        """The underlying integer type of an enum; any other type unchanged."""
        return self.idx.enum_base(ty) or ty

    def struct_type(self, name: str) -> int:
        """Index of the struct's `5F` type entry. The index is reserved before the fields are
        lowered, so `children: array::<Tree>` inside `Tree` can refer to it."""
        key = ("struct", name)
        if key not in self.type_keys:
            self.type_keys[key] = len(self.types)
            self.types.append(None)
            fields = []
            for f in self.idx.structs[name].fields:
                vt = self.vt(f.type)
                default = None
                if f.default is not None and not isinstance(vt, wbc.Ref):
                    default = self.const_value(f.default, f.type)
                fields.append((vt, default))
            self.types[self.type_keys[key]] = wbc.StructType(tuple(fields))
        return self.type_keys[key]

    def class_type(self, name: str) -> int:
        """Index of a class's `5B` type entry. The vtable is filled in by `build`, once every
        function index is known."""
        key = ("class", name)
        if key not in self.type_keys:
            self.type_keys[key] = len(self.types)
            self.types.append(None)
            c = self.idx.classes[name]
            sup = self.class_type(c.base) if c.base else None
            fields = []
            for f in c.fields:
                vt = self.vt(f.type)
                default = None
                if f.default is not None and not isinstance(vt, wbc.Ref) and \
                        f.default.kind != "null":
                    default = self.const_value(f.default, f.type)
                fields.append((vt, default))
            for d in c.dispatchers:             # after the fields: one dispatcher per object
                fields.append((self.vt(f"dispatcher::<({', '.join(p.type for p in d.params)})>"),
                               None))
            for _, ty, default in self.idx.class_state(name):   # then the methods' state
                vt = self.vt(ty)
                fields.append((vt, self.const_value(default, ty)
                               if default is not None and not isinstance(vt, wbc.Ref) else None))
            self.types[self.type_keys[key]] = wbc.ClassType(sup, tuple(fields), ())
        return self.type_keys[key]

    def callable_type(self, kind: str, params: list, results: list) -> int:
        """Index of a `59` delegate or `58` dispatcher entry for a signature."""
        key = (kind, tuple(params), tuple(results))
        if key not in self.type_keys:
            ft = self.func_type([self.vt(t) for t in params], [self.vt(t) for t in results])
            self.type_keys[key] = len(self.types)
            self.types.append(wbc.DelegateType(ft) if kind == "delegate"
                              else wbc.DispatcherType(ft))
        return self.type_keys[key]

    def interface_type(self, name: str) -> int:
        """Index of an interface's `5A` entry: one function type per method, no receiver."""
        key = ("interface", name)
        if key not in self.type_keys:
            self.type_keys[key] = len(self.types)
            self.types.append(None)
            it = self.idx.interfaces[name]
            self.types[self.type_keys[key]] = wbc.InterfaceType(tuple(
                self.func_type([self.vt(p.type) for p in m.params],
                               [self.vt(r.type) for r in m.result_list]) for m in it.methods))
        return self.type_keys[key]

    def slots(self, cls: str) -> list:
        """The vtable of a class as [(method name, implementing graph)]: the superclass's slots,
        with overrides in place, then the class's new methods by name (section 5.3)."""
        c = self.idx.classes[cls]
        out = list(self.slots(c.base)) if c.base else []
        names = [s for s, _ in out]
        for g in self.idx.methods(cls):
            if g.short_name in names:
                out[names.index(g.short_name)] = (g.short_name, g.name)
            else:
                out.append((g.short_name, g.name))
                names.append(g.short_name)
        return out

    def class_field_index(self, cls: str, fname: str) -> int:
        return [name for name, _ in self.idx.class_layout(cls)].index(fname)

    def field_index(self, struct: str, field_name: str) -> int:
        return [f.name for f in self.idx.structs[struct].fields].index(field_name)

    def enum_value(self, lit: Lit) -> int:
        """The integer of `Mode.Chase`."""
        name, member = lit.value.split(".")
        return dict(enum_values(self.idx.enums[name]))[member]

    def const_value(self, lit: Lit, ty: str):
        """A literal as the number or data index stored for a global or field default."""
        if ty in LANE_VT:                    # f32 lanes, nested for a transform
            return lanes.normalise(ty, lane_value(lit, ty))
        if ty == "string":
            return self.string_index(lit.value)
        if ty == "bool":
            return 1 if lit.value else 0
        if ty in FLOAT_TYPES:
            return float(lit.value)
        v = self.enum_value(lit) if lit.kind == "enum" else int(lit.value)
        return wrap_int(self.base(ty), v)

    def array_type(self, elem: str) -> int:
        """Index of the `array<elem>` type entry."""
        key = ("array", elem)
        if key not in self.type_keys:
            entry = wbc.ArrayType(self.vt(elem))     # inner entries come first
            self.type_keys[key] = len(self.types)
            self.types.append(entry)
        return self.type_keys[key]

    def map_type(self, k: str, v: str) -> int:
        """Index of the `map<k, v>` type entry."""
        key = ("map", k, v)
        if key not in self.type_keys:
            entry = wbc.MapType(self.vt(k), self.vt(v))
            self.type_keys[key] = len(self.types)
            self.types.append(entry)
        return self.type_keys[key]

    def set_type(self, elem: str) -> int:
        """Index of the `set<elem>` type entry."""
        key = ("set", elem)
        if key not in self.type_keys:
            entry = wbc.SetType(self.vt(elem))
            self.type_keys[key] = len(self.types)
            self.types.append(entry)
        return self.type_keys[key]

    def container_type(self, kind: str, targs: list) -> int:
        """The type entry a map or set node works on."""
        return self.map_type(*targs) if kind.startswith("Map") else self.set_type(targs[0])

    def func_type(self, params: list, results: list) -> int:
        key = ("func", tuple(params), tuple(results))
        if key not in self.type_keys:
            self.type_keys[key] = len(self.types)
            self.types.append((list(params), list(results)))
        return self.type_keys[key]

    def string_index(self, s: str) -> int:
        if s not in self.data_index:
            self.data_index[s] = len(self.data)
            self.data.append(s)
        return self.data_index[s]

    def add_global(self, name: str, ty: str, init: Optional[Lit]) -> int:
        if name in self.global_index:
            return self.global_index[name]
        lit = init if init is not None else zero_lit(ty)
        if ty in LANE_VT:
            value = self.const_value(lit, ty)
        elif is_container(ty) or ty in self.idx.structs or ty in self.idx.classes or \
                ty in self.idx.interfaces or ty == "std.Signal":
            value = None                 # the VM builds the default array or struct
        else:
            value = self.const_value(lit, ty)
        self.global_index[name] = len(self.globals)
        self.globals.append((name, ty, value))
        return self.global_index[name]

    def import_ref(self, qname: str):
        if qname not in self.import_index:
            self.import_index[qname] = len(self.imports)
            self.imports.append(qname)
        return ("import", qname)

    # -- driver -------------------------------------------------------------------
    def compile(self) -> CompileResult:
        self.diags = check(self.m, comments_ok=True, project=self.project)
        if has_errors(self.diags):
            return CompileResult(False, self.diags)
        for v in sorted(self.idx.vars.values(), key=lambda v: v.name):
            self.add_global(v.name, v.type, v.default)
        lowered = []
        for g in self.funcs:
            fl = FuncLowerer(self, g)
            fl.expand_all()
            fl.lower()
            lowered.append(fl)
        if has_errors(self.diags):
            return CompileResult(False, self.diags)
        mod = self.build(lowered)
        return CompileResult(True, self.diags, wbc.encode_module(mod), mod)

    def func_index(self, ref) -> int:
        kind, name = ref
        if kind == "import":
            return self.import_index[name]
        return len(self.imports) + self.func_names[name]

    def build(self, lowered) -> wbc.WbcModule:
        from .verifier import verify
        mod = wbc.WbcModule()
        type_index = self.func_type

        natives = {**STD, **INTERNAL}
        for q in self.imports:
            if q in natives:
                spec = natives[q]
                params = [self.vt(t) for _, t in spec.params]
                results = [self.vt(t) for _, t in spec.results]
                pure = spec.purity == "pure"
            else:
                ext = self.idx.externs[q]
                params = [self.vt(p.type) for p in ext.params]
                results = [self.vt(r.type) for r in ext.results or []]
                pure = ext.has_attr("pure")
                for a in ext.attrs:
                    if a.name == "capability" and a.arg() is not None:
                        self.caps.add(a.arg().value)
            module, _, name = q.rpartition(".")
            mod.imports.append((module, name, type_index(params, results), 1 if pure else 0))
        for fl in lowered:
            g = fl.g
            flags = (wbc.FN_PURE if g.has_attr("pure") else 0) | \
                    (wbc.FN_EVENT | wbc.FN_LATENT if g.kind == "event" else 0) | \
                    (wbc.FN_LATENT if g.has_attr("latent") else 0)
            t = type_index(([self.vt(g.owner)] if g.owner else [])
                           + [self.vt(p.type) for p in g.params],
                           [self.vt(r.type) for r in g.result_list])
            mod.funcs.append((t, flags))
        for name, ty, value in self.globals:
            mod.globals.append((self.vt(ty), 1, value))
        for i, fl in enumerate(lowered):
            g = fl.g
            declared = g.has_attr("export")
            if not (declared or self.export_all):
                continue
            eflags = (wbc.EX_EVENT | wbc.EX_LATENT if g.kind == "event" else 0) | \
                     (wbc.EX_LATENT if g.has_attr("latent") else 0) | \
                     (wbc.EX_PURE if g.has_attr("pure") else 0) | \
                     (wbc.EX_DECLARED if declared else 0)
            mod.exports.append((g.name, wbc.EXPORT_FUNC, len(self.imports) + i, eflags))
        for v in sorted(self.idx.vars.values(), key=lambda v: v.name):
            if _exported(v):
                mod.exports.append((v.name, wbc.EXPORT_GLOBAL, self.global_index[v.name],
                                    wbc.EX_DECLARED))
        # Types only when marked, in either mode. An enum is its underlying integer in WBC and
        # has no type entry to export, so only structs, classes and interfaces are listed.
        named = {**self.idx.structs, **self.idx.classes, **self.idx.interfaces}
        for name in sorted(n for n, t in named.items() if _exported(t)):
            mod.exports.append((name, wbc.EXPORT_TYPE, self.vt(name).type, wbc.EX_DECLARED))
        mod.data = list(self.data)
        for key, ti in list(self.type_keys.items()):
            if key[0] == "class":               # fill each vtable with function indices
                e = self.types[ti]
                ifaces = tuple(
                    (self.interface_type(i), tuple(
                        self.func_index(("func", self.idx.find_method(key[1], m.name).name))
                        for m in self.idx.interfaces[i].methods))
                    for i in self.idx.class_interfaces(key[1]))
                self.types[ti] = wbc.ClassType(e.super, e.fields, tuple(
                    self.func_index(("func", impl)) for _, impl in self.slots(key[1])), ifaces)
        mod.types = self.types
        assembled = [fl.assemble() for fl in lowered]
        mod.bodies = [wbc.Body([self.vt(t) for t in fl.local_types[fl.nparams:]], 0xFFFF, 0, code)
                      for fl, (code, *_) in zip(lowered, assembled)]
        mod.customs = self.custom_sections(lowered, assembled)
        if self.embed_source:
            mod.flags |= wbc.FLAG_HAS_SOURCE
        if self.uses_lanes:
            mod.flags |= wbc.FLAG_LANES
        # The verifier computes the operand stack height; record it and verify again.
        for body, (_, max_h) in zip(mod.bodies, verify(mod)):
            body.max_stack = max_h
        verify(mod)
        return mod

    def custom_sections(self, lowered, assembled) -> list:
        out = []
        w = wbc.Writer()
        nimp = len(self.imports)
        w.u32(len(self.imports) + len(lowered))
        for i, q in enumerate(self.imports):
            w.u32(i)
            w.name(q)
        for i, fl in enumerate(lowered):
            w.u32(nimp + i)
            w.name(f"{self.m.name}.{fl.g.name}")
        w.u32(len(lowered))
        for i, fl in enumerate(lowered):
            w.u32(nimp + i)
            w.u32(len(fl.local_names))
            for li, name in enumerate(fl.local_names):
                w.u32(li)
                w.name(name)
        w.u32(len(self.globals))
        for gi, (name, _, _) in enumerate(self.globals):
            w.u32(gi)
            w.name(name)
        classes = sorted((ti, key[1]) for key, ti in self.type_keys.items()
                         if key[0] in ("class", "interface"))
        w.u32(len(classes))
        for ti, name in classes:
            w.u32(ti)
            w.name(name)
            fields = self.idx.class_layout(name) if name in self.idx.classes else []
            w.u32(len(fields))
            for fname, _ in fields:
                w.name(fname)
        out.append(("name", bytes(w.b)))

        w = wbc.Writer()
        w.u32(len(lowered))
        pins = wbc.Writer()
        pins.u32(len(lowered))
        stepw = wbc.Writer()
        stepw.u32(len(lowered))
        purew = wbc.Writer()
        purew.u32(len(lowered))
        for i, (fl, (_, debug, steps, pure)) in enumerate(zip(lowered, assembled)):
            table = []
            tindex = {}

            def sid(s):
                if s not in tindex:
                    tindex[s] = len(table)
                    table.append(s)
                return tindex[s]

            entries = [(pc, sid(node)) for pc, node in debug]
            pin_entries = [(li, sid(node), sid(pin)) for li, (node, pin) in sorted(fl.pin_map.items())]
            step_entries = [(pc, sid(node)) for pc, node in steps]
            pure_entries = [(pc, sid(node)) for pc, node in pure]
            w.u32(nimp + i)
            w.name(fl.g.name)
            w.u32(len(table))
            for s in table:
                w.name(s)
            w.u32(len(entries))
            last = 0
            for pc, node in entries:
                w.u32(pc - last)
                w.u32(node)
                last = pc
            for tw, tentries in ((stepw, step_entries), (purew, pure_entries)):
                tw.u32(nimp + i)
                tw.u32(len(tentries))
                last = 0
                for pc, node in tentries:
                    tw.u32(pc - last)
                    tw.u32(node)
                    last = pc
            pins.u32(nimp + i)
            pins.u32(len(pin_entries))
            for li, node, pin in pin_entries:
                pins.u32(li)
                pins.u32(node)
                pins.u32(pin)
        out.append(("wr.debug", bytes(w.b)))
        out.append(("wr.pins", bytes(pins.b)))
        out.append(("wr.pure", bytes(purew.b)))
        if self.debug:
            out.append(("wr.steps", bytes(stepw.b)))

        w = wbc.Writer()
        mid = next((a.arg().value for a in self.m.attrs if a.name == "id" and a.arg()), "")
        canonical = print_module(self.m)
        for s in (self.m.name, mid, COMPILER_VERSION, f"{REGISTRY_NAME}@{REGISTRY_VERSION}",
                  semantic_hash(self.m), layout_hash(self.m),
                  hashlib.sha256((self.source or canonical).encode()).hexdigest(),
                  "export-all" if self.export_all else "declared"):
            w.name(s)
        out.append(("wr.meta", bytes(w.b)))

        w = wbc.Writer()
        w.u32(len(self.caps))
        for c in sorted(self.caps):
            w.name(c)
        out.append(("wr.caps", bytes(w.b)))
        if self.embed_source:
            out.append(("wr.graph", zlib.compress(canonical.encode(), 9)))
        return out


class FuncLowerer:
    def __init__(self, comp: Compiler, g: Graph):
        self.c = comp
        self.g = g
        self.local_names: list[str] = []
        self.local_types: list[str] = []
        self.local_index: dict[str, int] = {}
        self.local_defaults: list = []    # [(local name, Lit)]
        self.pin_map: dict[int, tuple] = {}
        entry_id = next((n.id for n in g.nodes if n.kind == "Entry"), "entry")
        params = ([("self", g.owner)] if g.owner else []) + [(p.name, p.type) for p in g.params]
        for name, ty in params:
            self.add_local(name, ty)
            self.pin_map[self.local_index[name]] = (entry_id, name)
        self.nparams = len(params)
        self.ir: dict[str, IRNode] = {}
        self.entry: Optional[str] = None
        self.code: list = []
        self.temp_free: dict[int, list] = {}
        self.temp_count = 0
        self.slots: dict[tuple, int] = {}
        self.debug_locals: dict[tuple, int] = {}
        self.at: list = []         # the node whose code is being emitted, innermost last
        self.uses_end = False

    def add_local(self, name: str, ty: str, default: Optional[Lit] = None) -> int:
        if name not in self.local_index:
            self.local_index[name] = len(self.local_names)
            self.local_names.append(name)
            self.local_types.append(ty)
            if default is not None:
                self.local_defaults.append((name, default))
        return self.local_index[name]

    def diag(self, code, msg, node=None, pin=None):
        self.c.diags.append(Diag(code, msg, self.c.m.name, self.g.name, node, pin))

    # -- expansion ----------------------------------------------------------------
    def sigs_for(self, g: Graph) -> dict:
        return {n.id: signature(n, g, self.c.idx) for n in g.nodes}

    def expand_all(self):
        g = self.g
        ctx = Ctx(g, "", None, self.sigs_for(g))
        ctx.params = {p.name: p.name for p in g.params}
        if g.owner:
            ctx.params["self"] = "self"
        for l in sorted(g.locals, key=lambda l: l.name):
            ctx.locals[l.name] = l.name
            self.add_local(l.name, l.type, l.default)
        for s in sorted(g.states, key=lambda s: s.name):
            ctx.states[s.name] = self.state_slot(None, s)
        self.expand(ctx)

    def state_slot(self, mpath, s):
        """Where a `state` slot lives (section 2.3): a module global in a free function, a
        hidden field of the object in a method (ClassType layout, see ModuleIndex.class_state)."""
        g = self.g
        if not g.owner:
            name = f"{g.name}.{s.name}" if mpath is None else f"{g.name}/{mpath}.{s.name}"
            return self.c.add_global(name, s.type, s.default)
        where = g.short_name if mpath is None else f"{g.short_name}/{mpath}"
        return ("field", self.c.class_type(g.owner),
                self.c.class_field_index(g.owner, f"{where}.{s.name}"))

    def out_target(self, ctx: Ctx, n: Node, pin: str):
        sig = ctx.sigs[n.id]
        for e in n.execs:
            p = e.pin or (sig.exec_outs[0].name if sig.exec_outs else None)
            if p == pin:
                return self.resolve_target(ctx, e.target, e.target_pin)
        return None

    def resolve_target(self, ctx: Ctx, tid: str, tpin: Optional[str], depth=0):
        t = ctx.graph.node(tid)
        if t is None or depth > 64:
            return None
        if t.kind == "Macro":
            return f"{ctx.prefix}{tid}!{tpin or 'in'}"
        if t.kind == "Reroute":
            if not t.execs:
                return None
            e = t.execs[0]
            return self.resolve_target(ctx, e.target, e.target_pin, depth + 1)
        return ctx.prefix + tid

    def resolve_ref(self, ctx: Ctx, ref: PinRef, ty: str, depth=0) -> Src:
        s = ctx.graph.node(ref.node)
        if s is None or depth > 64:
            return Src("lit", zero_lit(ty), type=ty)
        if s.kind == "Entry":
            return Src("local", ctx.params[ref.pin], type=ty)
        if s.kind == "Macro":
            return Src("local", f"{ctx.prefix}{ref.node}.{ref.pin}", type=ty)
        if s.kind == "Reroute":
            b = s.binding("in")
            if b is None:
                return Src("lit", zero_lit(ty), type=ty)
            if isinstance(b.value, Lit):
                return Src("lit", b.value, type=ty)
            return self.resolve_ref(ctx, b.value, ty, depth + 1)
        if s.attr("disabled"):
            return Src("lit", zero_lit(ty), type=ty)
        return Src("node", ctx.prefix + ref.node, ref.pin, ty)

    def src(self, ctx: Ctx, n: Node, pin: Pin) -> Src:
        b = n.binding(pin.name)
        if b is None:
            return Src("lit", pin.default_lit() or zero_lit(pin.type), type=pin.type)
        if isinstance(b.value, Lit):
            return Src("lit", b.value, type=pin.type)
        return self.resolve_ref(ctx, b.value, pin.type)

    def expand(self, ctx: Ctx):
        for n in sorted(ctx.graph.nodes, key=lambda n: n.id):
            sig = ctx.sigs[n.id]
            nid = ctx.prefix + n.id
            if n.kind == "Entry":
                if ctx.mpath is None:
                    self.entry = nid
                    self.ir[nid] = IRNode(nid, "Entry", sig,
                                          execs=[("then", self.out_target(ctx, n, "then"))])
                continue
            if n.kind == "Reroute":
                continue
            if n.kind == "Macro":
                self.expand_macro(ctx, n, sig)
                continue
            if n.attr("disabled"):
                if not sig.pure:
                    first = sig.exec_outs[0].name if sig.exec_outs else None
                    tgt = self.out_target(ctx, n, first) if first else None
                    self.ir[nid] = IRNode(nid, "Nop", sig, execs=[("then", tgt)])
                continue
            ir = IRNode(nid, n.kind, sig, n.symbol, list(n.targs), pure=sig.pure, attrs=n.attrs)
            if n.kind in ("Exit", "Leave"):
                if n.kind == "Leave":
                    ir.extra["leave"] = ctx.depth
                for p in sig.data_ins:
                    if n.binding(p.name) is not None:
                        ir.inputs.append((p.name, p.type, self.src(ctx, n, p)))
                ir.extra["assign"] = [ctx.results[p] for p, _, _ in ir.inputs]
                ir.execs = [("then", ctx.exits.get(n.symbol))]
            else:
                ir.inputs = [(p.name, p.type, self.src(ctx, n, p)) for p in sig.data_ins]
                ir.execs = [(p.name, self.out_target(ctx, n, p.name)) for p in sig.exec_outs]
            if n.kind in ("GetLocal", "SetLocal"):
                ir.extra["local"] = ctx.locals[n.symbol]
            elif n.kind in ("GetState", "SetState"):
                ir.extra["global"] = ctx.states[n.symbol]
            elif n.kind in ("GetVar", "SetVar"):
                if n.symbol in self.c.idx.consts:
                    ir.extra["const"] = self.c.idx.consts[n.symbol].value
                else:
                    ir.extra["global"] = self.c.global_index[n.symbol]
            elif n.kind in PLACE_MUTATORS:
                fp = None if n.symbol in ctx.locals else field_place(n.symbol, ctx.graph,
                                                                       self.c.idx)
                if n.symbol in ctx.locals:
                    ir.extra["place"] = ("local", ctx.locals[n.symbol])
                elif fp is not None:
                    ir.extra["place"] = ("field", (self.c.class_type(fp[0]),
                                                   self.c.class_field_index(fp[0], fp[1])))
                else:
                    ir.extra["place"] = ("global", self.c.global_index[n.symbol])
            elif n.kind == "CallParent":
                ir.extra["func"] = ("func", parent_method(n, ctx.graph, self.c.idx).name)
            elif n.kind == "Call" and self.c.idx.callee(n.symbol, n.targs).name \
                    in lanes.INTRINSICS:
                op = lanes.INTRINSICS[self.c.idx.callee(n.symbol, n.targs).name]
                ir.extra["intrinsic"] = [op] if isinstance(op, str) else op
                self.c.uses_lanes = True
            elif n.kind == "Call":
                callee = self.c.idx.callee(n.symbol, n.targs)
                if callee.kind in ("func", "event"):
                    ir.extra["func"] = ("func", callee.name)
                elif callee.kind != "interface":
                    ir.extra["func"] = self.c.import_ref(callee.name)
                ir.extra["nresults"] = len(callee.results)
                if callee.kind == "interface":
                    it = self.c.idx.interfaces[callee.method_of]
                    short = callee.name.rpartition(".")[2]
                    ir.extra["interface"] = (self.c.interface_type(callee.method_of),
                                             [m.name for m in it.methods].index(short))
                elif callee.method_of and not callee.final:
                    short = callee.name.rpartition(".")[2]
                    names = [s for s, _ in self.c.slots(callee.method_of)]
                    ir.extra["virtual"] = (self.c.class_type(callee.method_of),
                                           names.index(short))
            elif n.kind == "CreateDelegate":
                callee = self.c.idx.callee(n.symbol)
                virtual = bool(callee.method_of) and not callee.final
                ir.extra["delegate"] = (("func", callee.name),
                                        (1 if callee.method_of else 0) | (2 if virtual else 0))
                self.c.vt(sig.outputs[0].type)     # the delegate type entry delegate.new needs
            elif n.kind == "Invoke":
                ds = delegate_sig(n.targs[0])
                ir.extra["functype"] = self.c.func_type([self.c.vt(t) for t in ds[0]],
                                                        [self.c.vt(t) for t in ds[1]])
                self.c.vt(n.targs[0])
            elif n.kind in ("Bind", "Unbind", "Broadcast"):
                cls, name = dispatcher_target(n, ctx.graph, self.c.idx)
                d = self.c.idx.class_dispatcher(cls, name)[1]
                dtype = f"dispatcher::<({', '.join(p.type for p in d.params)})>"
                ir.extra["dispatcher"] = (self.c.class_type(cls),
                                          self.c.class_field_index(cls, name),
                                          self.c.vt(dtype).type)
                if n.kind != "Broadcast":
                    self.c.vt(sig.inputs[2].type)  # the handler's delegate type
            elif n.kind in ("GetField", "SetField") and sig.category == "Classes":
                cls, fname = class_field_target(n, ctx.graph, self.c.idx)
                ir.extra["class_field"] = (self.c.class_type(cls),
                                           self.c.class_field_index(cls, fname))
            self.ir[nid] = ir

    def expand_macro(self, ctx: Ctx, n: Node, sig: Sig):
        mg = self.c.idx.macro(n.symbol, n.targs)
        mpath = ctx.prefix + n.id
        sub = Ctx(mg, mpath + "/", mpath, self.sigs_for(mg))
        for p in mg.params:
            if p.type != "exec":
                sub.params[p.name] = f"{mpath}.{p.name}"
                self.add_local(sub.params[p.name], p.type)
        for r in mg.result_list:
            if r.type == "exec":
                sub.exits[r.name] = self.out_target(ctx, n, r.name)
            else:
                sub.results[r.name] = f"{mpath}.{r.name}"
                self.pin_map[self.add_local(sub.results[r.name], r.type)] = (ctx.prefix + n.id, r.name)
        for l in sorted(mg.locals, key=lambda l: l.name):
            sub.locals[l.name] = f"{mpath}.{l.name}"
            self.add_local(sub.locals[l.name], l.type, l.default)
        for s in sorted(mg.states, key=lambda s: s.name):
            sub.states[s.name] = self.state_slot(mpath, s)
        if any(m.kind == "Leave" for m in mg.nodes):
            sub.depth = f"{mpath}.!depth"
            self.add_local(sub.depth, "i32")
        entry = next((m for m in mg.nodes if m.kind == "Entry"), None)
        data_params = [p for p in sig.data_ins]
        for p in mg.params:
            if p.type != "exec":
                continue
            cid = f"{mpath}!{p.name}"
            ir = IRNode(cid, "Capture", None)
            ir.inputs = [(q.name, q.type, self.src(ctx, n, q)) for q in data_params]
            ir.extra["assign"] = [sub.params[q.name] for q in data_params]
            ir.execs = [("then", self.out_target(sub, entry, p.name) if entry else None)]
            # an input wired straight to a Leave leaves the macro; any other enters it, and
            # records the depth that a Leave discards back to
            first = next((e for e in entry.execs if e.pin == p.name), None) if entry else None
            first = mg.node(first.target) if first is not None else None
            if sub.depth and (first is None or first.kind != "Leave"):
                ir.extra["record"] = sub.depth
            self.ir[cid] = ir
        self.expand(sub)

    # -- analysis -----------------------------------------------------------------
    def successors(self, n: IRNode) -> list:
        """Exec successors in layout preference order (fall-through first)."""
        ts = [t for _, t in n.execs]
        if n.kind in ("Branch",):
            ts = list(reversed(ts))
        elif n.kind == "Try":          # body, fault, then: the handler code falls into fault
            ts = [ts[1], ts[0], ts[2]]
        elif n.kind == "Switch":
            ts = ts[-1:] + ts[:-1]
        return ts

    def reachable(self) -> list:
        order, seen, work = [], set(), [self.entry]
        while work:
            cur = work.pop()
            while cur is not None and cur not in seen and cur in self.ir:
                seen.add(cur)
                order.append(cur)
                succ = self.successors(self.ir[cur])
                for s in reversed(succ[1:]):
                    if s is not None and s not in seen:
                        work.append(s)
                cur = succ[0] if succ else None
        return order

    def check_chain_ends(self):
        """W0302: a chain can end with an empty continuation stack in a function with results."""
        if not self.g.result_list:
            return
        warned, states = set(), set()
        work = [(self.entry, (), ())]       # node, continuation stack, recorded macro depths

        def chain_end(nid, S, M):
            while True:
                if not S:
                    if nid not in warned:
                        warned.add(nid)
                        self.diag("W0302", "this chain can end without reaching Return; the "
                                           "function would return zero values", nid)
                    return
                k, S = S[-1], S[:-1]
                if k is not None:
                    work.append((k, S, M))
                    return

        while work and len(states) < 20000:
            nid, S, M = work.pop()
            if (nid, S, M) in states or len(S) > 64:
                continue
            states.add((nid, S, M))
            n = self.ir[nid]
            if "record" in n.extra:
                M = tuple(sorted(dict(M, **{n.extra["record"]: len(S)}).items()))
            if "leave" in n.extra and n.extra["leave"] in dict(M):
                S = S[:dict(M)[n.extra["leave"]]]
            if n.kind in ("Return", "Throw"):
                continue
            if n.kind == "Try":
                # then is pending under the handler marker (None: skipped by a chain end)
                t = dict(n.execs)
                base = S + ((t["then"],) if t.get("then") else ())
                nexts = [(t.get("body"), base + (None,)), (t.get("fault"), base)]
                for tgt, s in nexts:
                    if tgt is None:
                        chain_end(nid, s, M)
                    else:
                        work.append((tgt, s, M))
                continue
            if n.kind == "Sequence":
                outs = [t for _, t in n.execs]
                if not outs:
                    chain_end(nid, S, M)
                    continue
                S2 = S + tuple(reversed(outs[1:]))
                nexts = [(outs[0], S2)]
            else:
                nexts = [(t, S) for _, t in n.execs] or [(None, S)]
            for t, s in nexts:
                if t is None:
                    chain_end(nid, s, M)
                else:
                    work.append((t, s, M))

    # -- lowering -----------------------------------------------------------------
    def lower(self):
        if self.entry is None:
            return
        order = self.reachable()
        self.check_chain_ends()
        for nid in sorted(self.ir):
            for _, ty, s in self.ir[nid].inputs:
                if s.kind == "node" and s.a in self.ir and not self.ir[s.a].pure:
                    key = (s.a, s.b)
                    if key not in self.slots:
                        # typed by the producer's output: consumers may take a supertype
                        # (a class into an interface pin), and each one reads the same slot
                        sig = self.ir[s.a].sig
                        out = sig.output(s.b) if sig is not None else None
                        self.slots[key] = self.add_local(f"{s.a}.{s.b}",
                                                         out.type if out else ty)
                        self.pin_map[self.slots[key]] = key
        if self.c.debug:   # every impure output gets a slot, read or not
            for nid in sorted(self.ir):
                n = self.ir[nid]
                if not n.pure and (n.kind in ("Call", "CallParent", "Try", "New", "Invoke")
                                   or n.kind in PLACE_MUTATORS):
                    for p in n.data_outs:
                        key = (nid, p.name)
                        if key not in self.slots:
                            self.slots[key] = self.add_local(f"{nid}.{p.name}", p.type)
                            self.pin_map[self.slots[key]] = key
        self.code = []
        self.lazy_cache, self.lazy_count = {}, 0
        for i, nid in enumerate(order):
            nxt = order[i + 1] if i + 1 < len(order) else None
            self.emit_block(self.ir[nid], nxt)
        if self.uses_end:
            self.code.append(("label", "$end"))
            self.emit_chain_end()

    def E(self, op, *imms):
        self.code.append((op, imms))

    def L(self, target):
        if target is None:
            self.uses_end = True
            return "$end"
        return target

    def debug_local(self, nid: str, pin: str, ty: str) -> int:
        key = (nid, pin)
        if key not in self.debug_locals:
            li = self.add_local(f"{nid}.{pin}", ty)
            self.debug_locals[key] = li
            self.pin_map[li] = key
        return self.debug_locals[key]

    def temp(self, ty: str) -> int:
        vt = self.c.vt(ty)
        free = self.temp_free.setdefault(vt, [])
        if free:
            return free.pop()
        self.temp_count += 1
        return self.add_local(f"$t{self.temp_count}", ty)

    def emit_chain_end(self):
        self.E("cont.pop")
        for r in self.g.result_list:
            self.emit_const(zero_lit(r.type), r.type)
        self.E("return")

    def transfer(self, target, nxt):
        if target is None:
            self.emit_chain_end()
        elif target != nxt:
            self.E("br", target)

    def emit_block(self, n: IRNode, nxt):
        self.code.append(("label", n.id))
        self.code.append(("node", n.id))
        self.at = [n.id]
        # temps are reusable from one block to the next
        self.temp_free = {}
        for name, li in self.local_index.items():
            if name.startswith("$t"):
                self.temp_free.setdefault(self.c.vt(self.local_types[li]), []).append(li)
        k = n.kind
        then = n.execs[0][1] if n.execs else None
        if k == "Entry":
            for name, lit in self.local_defaults:
                ty = self.local_types[self.local_index[name]]
                self.emit_const(lit, ty)
                self.E("local.set", self.local_index[name])
            self.ready(n)
            self.transfer(then, nxt)
        elif k == "Nop":
            self.ready(n)
            self.transfer(then, nxt)
        elif k in ("Capture", "Exit", "Leave"):
            if "record" in n.extra:         # depth + 1, so 0 means "not entered"
                self.E("cont.depth")
                self.E("i32.const", 1)
                self.E("i32.add")
                self.E("local.set", self.local_index[n.extra["record"]])
            self.emit_inputs(n)
            for name in reversed(n.extra["assign"]):
                self.E("local.set", self.local_index[name])
            if "leave" in n.extra:          # -1 when not entered: cont.trunc does nothing
                self.E("local.get", self.local_index[n.extra["leave"]])
                self.E("i32.const", 1)
                self.E("i32.sub")
                self.E("cont.trunc")
            self.transfer(then, nxt)
        elif k == "SetLocal":
            self.emit_inputs(n)
            self.E("local.set", self.local_index[n.extra["local"]])
            self.transfer(then, nxt)
        elif k in ("SetVar", "SetState") and isinstance(n.extra["global"], tuple):
            _, t, f = n.extra["global"]           # state on the object
            self.emit_inputs(n, pre=lambda: self.E("local.get", self.local_index["self"]))
            self.E("class.set", t, f)
            self.transfer(then, nxt)
        elif k in ("SetVar", "SetState"):
            self.emit_inputs(n)
            self.E("global.set", n.extra["global"])
            self.transfer(then, nxt)
        elif k == "CallParent":
            self.emit_inputs(n, pre=lambda: self.E("local.get", self.local_index["self"]))
            self.E("call", n.extra["func"])
            for p in reversed(n.sig.data_outs):
                slot = self.slots.get((n.id, p.name))
                if slot is None:
                    self.E("drop")
                else:
                    self.E("local.set", slot)
            self.transfer(then, nxt)
        elif k == "Call":
            self.emit_inputs(n)
            self.emit_call(n)
            for p in reversed(n.sig.data_outs):
                slot = self.slots.get((n.id, p.name))
                if slot is None:
                    self.E("drop")
                else:
                    self.E("local.set", slot)
            self.transfer(then, nxt)
        elif k == "Return":
            self.emit_inputs(n)
            self.E("return")
        elif k == "Branch":
            self.emit_inputs(n)
            targets = dict(n.execs)
            self.E("br_if", self.L(targets.get("then")))
            self.transfer(targets.get("else"), nxt)
        elif k == "Try":
            # Section 4.6: push `then` as a continuation, then a handler marker above it, and
            # run `body`. A chain end in the body discards the marker and resumes `then`; a
            # fault unwinds to the marker, stores the fault and lands on the handler below,
            # which runs `fault` with `then` still pending.
            self.ready(n)
            t = dict(n.execs)
            if t.get("then") is not None:
                self.E("cont.push", t["then"])
            fault_local = self.add_local(f"{n.id}.$fault", "fault")
            handler = f"{n.id}!fault"
            self.E("try.push", handler, fault_local)
            if t.get("body") is None:
                self.emit_chain_end()
            else:
                self.E("br", t["body"])
            self.code.append(("label", handler))
            for pin, native in (("message", "std.fault.Message"), ("code", "std.fault.Code")):
                slot = self.slots.get((n.id, pin))
                if slot is not None:
                    self.E("local.get", fault_local)
                    self.E("call", self.c.import_ref(native))
                    self.E("local.set", slot)
            self.transfer(t.get("fault"), nxt)
        elif k in ("Delay", "Yield", "Await"):
            # suspend parks the fiber, every frame included; it resumes at the next
            # instruction with its continuation stack intact (section 4.5)
            self.emit_inputs(n)
            self.E("suspend", {"Yield": 0, "Delay": 1, "Await": 2}[k])
            self.transfer(then, nxt)
        elif k == "Invoke":
            self.emit_inputs(n)                    # the delegate, then its arguments
            self.E("call_delegate", n.extra["functype"])
            for p in reversed(n.sig.data_outs):
                slot = self.slots.get((n.id, p.name))
                if slot is None:
                    self.E("drop")
                else:
                    self.E("local.set", slot)
            self.transfer(then, nxt)
        elif k in ("Bind", "Unbind", "Broadcast"):
            # obj, then its dispatcher (a hidden slot), then the handler or the arguments
            cls_t, slot, disp_t = n.extra["dispatcher"]
            ep = self.new_ep(n)
            self.eval(n.inputs[0][2], ep)
            self.E("class.get", cls_t, slot)
            for _, _, s in n.inputs[1:]:
                self.eval(s, ep)
            self.ready(n)
            self.E({"Bind": "dispatcher.bind", "Unbind": "dispatcher.unbind",
                    "Broadcast": "dispatcher.broadcast"}[k], disp_t)
            self.transfer(then, nxt)
        elif k == "New":
            self.ready(n)
            self.E("class.new", self.c.class_type(n.symbol))
            slot = self.slots.get((n.id, "result"))
            if slot is None:
                self.E("drop")
            else:
                self.E("local.set", slot)
            self.transfer(then, nxt)
        elif k == "SetField":
            self.emit_inputs(n)                   # obj, then value
            self.E("class.set", *n.extra["class_field"])
            self.transfer(then, nxt)
        elif k == "Throw":
            self.emit_inputs(n)
            self.E("call", self.c.import_ref("std.fault.Make"))
            self.E("throw")
        elif k == "Sequence":
            self.ready(n)
            outs = [t for _, t in n.execs]
            for t in reversed(outs[1:]):
                self.E("cont.push", self.L(t))
            self.transfer(outs[0] if outs else None, nxt)
        elif k == "Switch":
            ty = n.targs[0]
            self.emit_inputs(n)
            tmp = self.temp(ty)
            self.E("local.set", tmp)
            cases = n.attrs and next((a for a in n.attrs if a.name == "cases"), None)
            targets = dict(n.execs)
            for i, (_, lit) in enumerate(cases.args if cases and cases.args else []):
                self.E("local.get", tmp)
                self.emit_const(lit, ty)
                self.emit_eq(ty)
                self.E("br_if", self.L(targets.get(f"case{i}")))
            self.transfer(targets.get("default"), nxt)
        elif k in PLACE_MUTATORS:
            # read the place, apply the mutator (which yields the changed container), store it
            # back; MapRemove, SetAdd and SetRemove also yield whether anything changed
            kind, where = n.extra["place"]
            idx = self.local_index[where] if kind == "local" else where
            if kind == "field":
                # obj, then the field read without sharing it (it is the place this node
                # changes); the changed container goes back with class.set on the same obj
                ep = self.new_ep(n)
                self.eval(n.inputs[0][2], ep, keep=False)
                obj = self.temp(n.inputs[0][1])
                self.E("local.tee", obj)
                self.E("local.get", obj)
                self.E("class.get", *idx)
                for _, _, s in n.inputs[1:]:
                    self.eval(s, ep)
                self.ready(n)
            else:
                self.emit_inputs(n, pre=lambda: self.E(f"{kind}.get", idx))
            if k in ARRAY_MUTATORS:
                op = {"ArraySet": "array.set", "ArrayAdd": "array.push",
                      "ArrayInsert": "array.insert", "ArrayRemove": "array.remove",
                      "ArrayClear": "array.clear"}[k]
                self.E(op, self.c.array_type(n.targs[0]))
            else:
                self.E(CONTAINER_OPS[k], self.c.container_type(k, n.targs))
            for p in reversed(n.sig.data_outs):
                slot = self.slots.get((n.id, p.name))
                if slot is None:
                    self.E("drop")
                else:
                    self.E("local.set", slot)
            if kind == "field":
                self.E("class.set", *idx)
            else:
                self.E(f"{kind}.set", idx)
            self.transfer(then, nxt)
        else:
            raise AssertionError(f"cannot lower impure node kind {k}")

    # -- evaluation points --------------------------------------------------------
    def count(self, s: Src, ep: EvalPoint):
        if s.kind == "node" and s.a in self.ir and self.ir[s.a].pure:
            ep.uses[s.a] += 1
            if ep.uses[s.a] == 1:
                for _, _, inner in self.ir[s.a].inputs:
                    self.count(inner, ep)

    def new_ep(self, n: IRNode) -> EvalPoint:
        """The evaluation point of impure node `n`. When an input reaches a lazy node, every
        input is evaluated into a temp first, in pin order, so the lazy node's branches start
        with an empty operand stack (labels require one, section 5.5)."""
        ep = EvalPoint()
        for _, _, s in n.inputs:
            self.count(s, ep)
        if any(self.has_lazy(s) for _, _, s in n.inputs):
            for _, _, s in n.inputs:
                self.spill(s, ep)
        return ep

    def emit_inputs(self, n: IRNode, pre=None):
        ep = self.new_ep(n)
        if pre is not None:
            pre()
        for _, _, s in n.inputs:
            self.eval(s, ep)
        self.ready(n)

    # -- lazy nodes (Select, And, Or: section 4.3) --------------------------------
    def has_lazy(self, s: Src) -> bool:
        """Whether evaluating `s` reaches a lazy node."""
        if s.kind != "node":
            return False
        t = self.ir.get(s.a)
        if t is None or not t.pure:
            return False
        if s.a not in self.lazy_cache:
            self.lazy_cache[s.a] = False         # a pure cycle is E0301; never loop here
            self.lazy_cache[s.a] = t.kind in LAZY_KINDS or any(
                self.has_lazy(inner) for _, _, inner in t.inputs)
        return self.lazy_cache[s.a]

    def spill(self, s: Src, ep: EvalPoint):
        """Evaluate a pure node into a temp now, with the operand stack empty."""
        if s.kind != "node" or (s.a, s.b) in ep.temps:
            return
        t = self.ir.get(s.a)
        if t is None or not t.pure:
            return
        self._eval(s, ep)
        tmp = self.temp(s.type)
        self.E("local.set", tmp)
        ep.temps[(s.a, s.b)] = tmp

    def branch_value(self, s: Src, ep: EvalPoint, tmp: int):
        """Evaluate `s` into `tmp` on one side of a lazy node. Values computed there are
        only known on that side, so they are forgotten afterwards."""
        saved = dict(ep.temps)
        self._eval(s, ep)
        self.E("local.set", tmp)
        ep.temps = saved

    def emit_lazy(self, n: IRNode, ep: EvalPoint):
        """Select evaluates only the input it chooses; And and Or skip `b` when `a` decides
        the result. Entered with an empty operand stack; leaves the result on it."""
        self.lazy_count += 1
        end = f"{n.id}!lazy{self.lazy_count}"
        out = self.temp(n.data_outs[0].type)
        if n.kind == "Select":
            (_, _, cond), (_, _, a), (_, _, b) = n.inputs
            take_a = end + "a"
            self._eval(cond, ep)
            self.E("br_if", take_a)
            self.branch_value(b, ep, out)
            self.E("br", end)
            self.code.append(("label", take_a))
            self.branch_value(a, ep, out)
        else:                                  # And, Or
            (_, _, a), (_, _, b) = n.inputs
            self._eval(a, ep)
            self.E("local.tee", out)
            if n.kind == "And":
                self.E("i32.eqz")              # a is false: so is the result
            self.E("br_if", end)
            self.branch_value(b, ep, out)
        self.code.append(("label", end))
        self.E("local.get", out)

    def ready(self, n: IRNode):
        """Debug builds mark the point where a node's inputs are evaluated and it is about to act."""
        if self.c.debug:
            self.code.append(("step", n.id))
            self.E("nop")

    def eval(self, s: Src, ep: EvalPoint, keep: bool = True):
        """Push the value of an input. With `keep` (the consumer can retain the value: a
        variable, field, argument, result, struct or macro input), a container gets
        `ref.share`, so its next change copies it (section 4.9). Read-only consumers
        (ArrayGet, ArrayLength, the map and set queries, Eq and Ne) pass keep=False, and a
        mutation node reads its own place without this path."""
        self._eval(s, ep)
        if keep and s.kind != "lit" and is_container(s.type):
            self.E("ref.share")

    def _eval(self, s: Src, ep: EvalPoint):
        if s.kind == "lit":
            self.emit_const(s.a, s.type)
        elif s.kind == "local":
            self.E("local.get", self.local_index[s.a])
        else:
            t = self.ir.get(s.a)
            if t is None:
                self.emit_const(zero_lit(s.type), s.type)
            elif not t.pure:
                slot = self.slots.get((s.a, s.b))
                if slot is None:
                    self.emit_const(zero_lit(s.type), s.type)
                else:
                    self.E("local.get", slot)
            elif (s.a, s.b) in ep.temps:
                self.E("local.get", ep.temps[(s.a, s.b)])
            else:
                outs = t.data_outs
                if t.kind not in LAZY_KINDS and self.has_lazy(s):
                    for _, _, inner in t.inputs:    # so a lazy input starts on an empty stack
                        self.spill(inner, ep)
                # mark the pure node's code, so a fault in it (ArrayGet, Div) names that node
                self.at.append(t.id)
                self.code.append(("pure", t.id))
                self.emit_pure(t, ep)
                self.at.pop()
                if self.at:
                    self.code.append(("pure", self.at[-1]))
                if len(outs) == 1:
                    if ep.uses[s.a] > 1:
                        tmp = self.temp(outs[0].type)
                        self.E("local.tee", tmp)
                        ep.temps[(s.a, s.b)] = tmp
                    if self.c.debug:
                        self.E("local.tee", self.debug_local(s.a, outs[0].name, outs[0].type))
                else:
                    for o in reversed(outs):
                        tmp = self.temp(o.type)
                        self.E("local.set", tmp)
                        ep.temps[(s.a, o.name)] = tmp
                    if self.c.debug:
                        for o in outs:
                            self.E("local.get", ep.temps[(s.a, o.name)])
                            self.E("local.set", self.debug_local(s.a, o.name, o.type))
                    self.E("local.get", ep.temps[(s.a, s.b)])

    def emit_call(self, n: IRNode):
        """A direct call, or call_virtual for a method that is not @final (section 3.3)."""
        if "interface" in n.extra:
            self.E("call_interface", *n.extra["interface"])
        elif "virtual" in n.extra:
            self.E("call_virtual", *n.extra["virtual"])
        else:
            self.E("call", n.extra["func"])

    def emit_const(self, lit: Lit, ty: str):
        if ty == "std.Signal":        # no literal: the null signal, a local never assigned
            self.E("local.get", self.add_local("$null.signal", ty))
            return
        if ty == "anyref" or delegate_sig(ty) is not None:   # null: a local never assigned
            self.E("local.get", self.add_local(f"$null.{ty}", ty))
            return
        if ty in self.c.idx.classes or ty in self.c.idx.interfaces:   # the only literal is null
            self.E("ref.null", self.c.vt(ty).type)
            return
        elem = array_elem(ty)
        if elem is not None:          # the only array constant is the empty array
            self.E("i32.const", 0)
            self.E("array.new", self.c.array_type(elem))
            return
        kv = map_types(ty)
        if kv is not None:            # likewise the empty map and the empty set
            self.E("map.new", self.c.map_type(*kv))
            return
        elem = set_elem(ty)
        if elem is not None:
            self.E("set.new", self.c.set_type(elem))
            return
        if ty in LANE_VT:             # a tuple literal: its lanes, then make (3.1.1)
            if ty == "transform":
                for x, (_, ft) in zip(lit.value, lanes.LANE_FIELDS[ty]):
                    self.emit_const(x, ft)
            else:
                for x in lit.value:
                    self.E("f32.const", float(x.value))
            self.E(f"{LP[ty]}.make")
            return
        if ty in self.c.idx.structs:  # structs have no literal: this is the default struct
            for f in self.c.idx.structs[ty].fields:
                self.emit_const(f.default if f.default is not None else zero_lit(f.type), f.type)
            self.E("struct.new", self.c.struct_type(ty))
            return
        if lit.kind == "enum":
            lit = Lit("int", self.c.enum_value(lit))
        ty = self.c.base(ty)
        vt = VT[ty]
        if ty == "bool":
            self.E("i32.const", 1 if lit.value else 0)
        elif ty == "string":
            self.E("string.const", self.c.string_index(lit.value))
        elif vt == F32:
            self.E("f32.const", float(lit.value))
        elif vt == F64:
            self.E("f64.const", float(lit.value))
        elif vt == I64:
            self.E("i64.const", wrap_int(ty, int(lit.value)))
        else:
            self.E("i32.const", wrap_int(ty, int(lit.value)))

    def narrow(self, ty: str):
        if ty == "i8":
            self.E("i32.extend8_s")
        elif ty == "i16":
            self.E("i32.extend16_s")
        elif ty == "u8":
            self.E("i32.const", 0xFF)
            self.E("i32.and")
        elif ty == "u16":
            self.E("i32.const", 0xFFFF)
            self.E("i32.and")

    NARROW_RANGES = {"i8": (-128, 127), "u8": (0, 255), "i16": (-32768, 32767),
                     "u16": (0, 65535)}

    def clamp_narrow(self, ty: str):
        """Saturate an i32 from a float conversion to a narrow type's range (section 3.2).
        `trunc` already saturates to i32 (or u32), and maps NaN to 0."""
        rng = self.NARROW_RANGES.get(ty)
        if rng is None:
            return
        lo, hi = rng
        signed = ty in SIGNED_TYPES
        t = self.temp("i32")
        self.E("local.set", t)
        if signed:                       # max(v, lo); the unsigned trunc never goes below 0
            self.E("local.get", t)
            self.E("i32.const", lo)
            self.E("local.get", t)
            self.E("i32.const", lo)
            self.E("i32.gt_s")
            self.E("select")
            self.E("local.set", t)
        self.E("local.get", t)           # min(v, hi)
        self.E("i32.const", hi)
        self.E("local.get", t)
        self.E("i32.const", hi)
        self.E("i32.lt_s" if signed else "i32.lt_u")
        self.E("select")

    def emit_eq(self, ty: str):
        """[a, b] -> [i32]. Structs compare field by field (section 3.1); containers call
        std.array.Equals, std.set.Equals or std.map.Equals (section 4.9)."""
        if is_container(ty):
            kind = ("array" if array_elem(ty) is not None else
                    "map" if map_types(ty) is not None else "set")
            self.E("call", self.c.import_ref(f"std.{kind}.Equals"))
            return
        if ty in self.c.idx.classes or ty in self.c.idx.interfaces:   # identity (3.1)
            self.E("ref.eq")
            return
        if ty in LANE_VT:
            self.E(f"{LP[ty]}.eq")
            return
        if ty in self.c.idx.structs:
            t = self.c.struct_type(ty)
            fields = self.c.idx.structs[ty].fields
            tb, ta = self.temp(ty), self.temp(ty)
            self.E("local.set", tb)
            self.E("local.set", ta)
            self.E("i32.const", 1)
            for i, f in enumerate(fields):
                self.E("local.get", ta)
                self.E("struct.get", t, i)
                self.E("local.get", tb)
                self.E("struct.get", t, i)
                self.emit_eq(f.type)
                self.E("i32.and")
            return
        ty = self.c.base(ty)
        if ty == "string":
            self.E("string.eq")
        else:
            self.E(f"{PFX[VT[ty]]}.eq")

    def emit_pure(self, n: IRNode, ep: EvalPoint):
        k = n.kind
        if k == "GetLocal":
            self.E("local.get", self.local_index[n.extra["local"]])
            return
        if k in ("GetVar", "GetState"):
            if "const" in n.extra:
                self.emit_const(n.extra["const"], n.sig.outputs[0].type)
            elif isinstance(n.extra["global"], tuple):     # state on the object
                _, t, f = n.extra["global"]
                self.E("local.get", self.local_index["self"])
                self.E("class.get", t, f)
            else:
                self.E("global.get", n.extra["global"])
            return
        if k in MAP_PURE or k in SET_PURE:
            for _, _, src in n.inputs:     # the container, then the key, item or index
                self.eval(src, ep, keep=False)
            self.E(CONTAINER_OPS[k], self.c.container_type(k, n.targs))
            return
        if k == "MakeArray":
            t = self.c.array_type(n.targs[0])
            self.E("i32.const", len(n.inputs))
            self.E("array.new", t)
            for i, (_, _, item) in enumerate(n.inputs):
                self.E("i32.const", i)
                self.eval(item, ep)
                self.E("array.set", t)
            return
        if k == "ArrayGet":
            self.eval(n.inputs[0][2], ep, keep=False)
            self.eval(n.inputs[1][2], ep)
            self.E("array.get", self.c.array_type(n.targs[0]))
            return
        if k == "ArrayLength":
            self.eval(n.inputs[0][2], ep, keep=False)
            self.E("array.len")
            return
        if k == "GetField" and "class_field" in n.extra:
            self.eval(n.inputs[0][2], ep)
            self.E("class.get", *n.extra["class_field"])
            return
        if k in ("MakeStruct", "BreakStruct", "GetField", "WithField"):
            self.emit_struct_node(n, ep)
            return
        if k == "IsValid":
            self.eval(n.inputs[0][2], ep)
            self.E("ref.valid")
            return
        if k == "CreateDelegate":
            for _, _, s in n.inputs:               # the target, for a method
                self.eval(s, ep)
            self.E("delegate.new", *n.extra["delegate"])
            return
        if k == "Cast":
            # result is obj when it is an instance of the class, else null; ok says which.
            # ref.cast cannot fault here: it sees either an instance or null.
            t = self.c.vt(n.symbol).type           # a class or an interface
            self.eval(n.inputs[0][2], ep)
            obj, ok = self.temp("anyref"), self.temp("bool")
            self.E("local.tee", obj)
            self.E("ref.test", t)
            self.E("local.set", ok)
            self.E("local.get", obj)
            self.E("ref.null", t)
            self.E("local.get", ok)
            self.E("select")
            self.E("ref.cast", t)
            self.E("local.get", ok)
            return
        if k in LAZY_KINDS:
            self.emit_lazy(n, ep)
            return
        if k == "Format":
            self.emit_format(n, ep)
            return
        if k == "CallParent":
            self.E("local.get", self.local_index["self"])
        for _, _, s in n.inputs:          # Eq and Ne only compare, so they do not share
            self.eval(s, ep, keep=k not in ("Eq", "Ne"))
        if k == "Call" and "intrinsic" in n.extra:     # a std.vec, std.quat, std.transform
            for op in n.extra["intrinsic"]:              # function with a lane instruction
                self.E(op)
            return
        if k == "Call":
            self.emit_call(n)
            return
        if k == "CallParent":                       # a @pure parent: self went first
            self.E("call", n.extra["func"])
            return
        if k == "Convert":
            self.emit_convert(n.targs[0], n.targs[1])
            return
        if k == "Not":
            self.E("i32.eqz")
            return
        if k == "Xor":
            self.E("i32.xor")
            return
        T = n.targs[0]
        if T in LANE_VT:                      # component-wise, or composition (3.1.1)
            self.E(f"{LP[T]}.{LANE_ARITH[k]}")
            return
        if T in self.c.idx.structs or T in self.c.idx.classes or T in self.c.idx.interfaces \
                or is_container(T):
            # only Eq and Ne take these
            self.emit_eq(T)
            if k == "Ne":
                self.E("i32.eqz")
            return
        T = self.c.base(T)
        vt = VT[T]
        p = PFX.get(vt)
        signed = T in SIGNED_TYPES
        is_float = T in FLOAT_TYPES
        if k in ("Eq", "Ne"):
            self.emit_eq(T)
            if k == "Ne":
                self.E("i32.eqz")
        elif k in ("Lt", "Le", "Gt", "Ge"):
            op = k.lower()
            if T == "string":
                self.E("string.cmp")
                self.E("i32.const", 0)
                self.E(f"i32.{op}_s")
            elif is_float:
                self.E(f"{p}.{op}")
            else:
                self.E(f"{p}.{op}_{'s' if signed else 'u'}")
        elif k in ("Add", "Sub", "Mul"):
            self.E(f"{p}.{k.lower()}")
            self.narrow(T)
        elif k in ("Div", "Rem"):
            if is_float and k == "Rem":
                self.E("call", self.c.import_ref("std.math.FRem32" if T == "f32" else "std.math.FRem64"))
            elif is_float:
                self.E(f"{p}.div")
            else:
                self.E(f"{p}.{k.lower()}_{'s' if signed else 'u'}")
                self.narrow(T)
        elif k in ("Min", "Max"):
            if is_float:
                self.E(f"{p}.{k.lower()}")
            else:
                ta, tb = self.temp(T), self.temp(T)
                self.E("local.set", tb)
                self.E("local.set", ta)
                self.E("local.get", ta)
                self.E("local.get", tb)
                self.E("local.get", ta)
                self.E("local.get", tb)
                self.E(f"{p}.{'lt' if k == 'Min' else 'gt'}_{'s' if signed else 'u'}")
                self.E("select")
        elif k == "Neg":
            self.E(f"{p}.neg")
            self.narrow(T)
        elif k == "Abs":
            if is_float:
                self.E(f"{p}.abs")
            else:
                t = self.temp(T)
                self.E("local.set", t)
                self.E("local.get", t)
                self.E(f"{p}.neg")
                self.E("local.get", t)
                self.E("local.get", t)
                self.emit_const(Lit("int", 0), T)
                self.E(f"{p}.lt_s")
                self.E("select")
                self.narrow(T)
        elif k in ("BitAnd", "BitOr", "BitXor"):
            self.E(f"{p}.{k[3:].lower()}")
        elif k == "BitNot":
            self.E(f"{p}.not")
            self.narrow(T)
        elif k in ("Shl", "Shr"):
            width = {"i8": 8, "u8": 8, "i16": 16, "u16": 16}.get(T)
            if width:
                self.E("i32.const", width - 1)
                self.E("i32.and")
            if k == "Shl":
                self.E(f"{p}.shl")
                self.narrow(T)
            else:
                self.E(f"{p}.shr_{'s' if signed else 'u'}")
        else:
            raise AssertionError(f"cannot lower pure node kind {k}")

    def emit_struct_node(self, n: IRNode, ep: EvalPoint):
        """MakeStruct, BreakStruct, GetField, WithField. All are pure."""
        k = n.kind
        name, _, fname = (n.symbol or "").partition(".")
        if name in LANE_VT:                   # unboxed: lane instructions, no struct.* (5.6)
            for _, _, src in n.inputs:
                self.eval(src, ep)
            p = LP[name]
            names = [f for f, _ in lanes.LANE_FIELDS[name]]
            if k == "MakeStruct":
                self.E(f"{p}.make")
            elif k in ("GetField", "WithField"):
                self.E(f"{p}.{'get' if k == 'GetField' else 'with'}", names.index(fname))
            else:
                tmp = self.temp(name)
                self.E("local.set", tmp)
                for i in range(len(names)):
                    self.E("local.get", tmp)
                    self.E(f"{p}.get", i)
            return
        t = self.c.struct_type(name)
        for _, _, src in n.inputs:            # fields in order, or obj (and value)
            self.eval(src, ep)
        if k == "MakeStruct":
            self.E("struct.new", t)
        elif k == "GetField":
            self.E("struct.get", t, self.c.field_index(name, fname))
        elif k == "WithField":
            self.E("struct.with", t, self.c.field_index(name, fname))
        else:                                 # BreakStruct: push every field, in order
            tmp = self.temp(name)
            self.E("local.set", tmp)
            for i in range(len(self.c.idx.structs[name].fields)):
                self.E("local.get", tmp)
                self.E("struct.get", t, i)

    def emit_format(self, n: IRNode, ep: EvalPoint):
        """Format: each piece of the template in order, a literal or an input converted to
        text as Convert does, joined with std.string.Concat."""
        srcs = {pin: (ty, s) for pin, ty, s in n.inputs}
        concat = self.c.import_ref("std.string.Concat")
        parts = format_parts(n.symbol)
        for i, (kind, v) in enumerate(parts):
            if kind == "text":
                self.emit_const(Lit("string", v), "string")
            else:
                ty, s = srcs[v]
                self.eval(s, ep)
                self.emit_convert(ty, "string")
            if i:
                self.E("call", concat)
        if not parts:
            self.emit_const(Lit("string", ""), "string")

    def emit_convert(self, f: str, t: str):
        f, t = self.c.base(f), self.c.base(t)    # an enum converts to its integer as-is
        if f == t:
            return
        if f in LANE_VT:                         # to text, or vec2 <-> vec3 (section 3.2)
            if t == "string":
                self.E("call", self.c.import_ref(f"std.convert.From{f.capitalize()}"))
            else:
                self.E("v3.from_v2" if f == "vec2" else "v3.to_v2")
            return
        vf, vt = VT[f], VT[t]
        if t == "string":
            name = {"bool": "FromBool", "u32": "FromU32", "i64": "FromI64", "u64": "FromU64",
                    "f32": "FromF32", "f64": "FromF64"}.get(f, "FromI32")
            self.E("call", self.c.import_ref(f"std.convert.{name}"))
            return
        if t == "bool":
            self.E(f"{PFX[vf]}.eqz")
            self.E("i32.eqz")
            return
        fs = "s" if f in SIGNED_TYPES else "u"
        if f in INT_TYPES + ["bool"] and t in INT_TYPES:
            if vf == I32 and vt == I64:
                self.E(f"i64.extend_i32_{fs}")
            elif vf == I64 and vt == I32:
                self.E("i32.wrap_i64")
            self.narrow(t)
        elif f in INT_TYPES and t in FLOAT_TYPES:
            self.E(f"{PFX[vt]}.convert_{PFX[vf]}_{fs}")
        elif f in FLOAT_TYPES and t in INT_TYPES:
            ts = "s" if t in SIGNED_TYPES else "u"
            self.E(f"{PFX[vt]}.trunc_{PFX[vf]}_{ts}")   # saturates to the 32/64-bit range
            self.clamp_narrow(t)
        elif f == "f32" and t == "f64":
            self.E("f64.promote_f32")
        elif f == "f64" and t == "f32":
            self.E("f32.demote_f64")

    # -- assembly -----------------------------------------------------------------
    def assemble(self):
        """Resolve labels and function references.

        Returns (code bytes, [(pc, node id)] block starts, [(pc, node id)] step points,
        [(pc, node id)] pure-node code).
        """
        pcs, pc = {}, 0
        for item in self.code:
            if item[0] == "label":
                pcs[item[1]] = pc
            elif item[0] not in ("node", "step", "pure"):
                pc += wbc.instr_size(item[0], self._imms(item, {}, 0, final=False))
        w = wbc.Writer()
        tables = {"node": [], "step": [], "pure": []}
        for item in self.code:
            if item[0] == "label":
                continue
            if item[0] in tables:
                tables[item[0]].append((len(w.b), item[1]))
                continue
            start = len(w.b)
            size = wbc.instr_size(item[0], self._imms(item, {}, 0, final=False))
            wbc.encode_instr(w, item[0], self._imms(item, pcs, start + size, final=True))
        return bytes(w.b), tables["node"], tables["step"], tables["pure"]

    def _imms(self, item, pcs, end, final):
        op, imms = item
        kind = wbc.OPS[op][1]
        if kind == "L":
            return (pcs[imms[0]] - end,) if final else (0,)
        if kind == "Lu":
            return (pcs[imms[0]] - end, imms[1]) if final else (0, imms[1])
        if op == "call":
            return (self.c.func_index(imms[0]),)
        if op == "delegate.new":
            return (self.c.func_index(imms[0]), imms[1])
        return imms


def _exported(item) -> bool:
    return any(a.name == "export" for a in (item.attrs or []))


def compile_module(module: Module, source: Optional[str] = None, embed_source=True,
                   debug=False, project=None, export_all=False) -> CompileResult:
    """Compile and verify. `export_all` is `wiretc build --export-all` (section 5.2): pass it
    to run any function by name, never for a build that ships."""
    return Compiler(module, source, embed_source, debug, project, export_all).compile()
