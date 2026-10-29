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

from . import wbc
from .checker import Diag, check, has_errors
from .model import Graph, Lit, Module, Node, PinRef
from .natives import INTERNAL, STD
from .printer import layout_hash, print_module, semantic_hash
from .registry import (ARRAY_MUTATORS, FLOAT_TYPES, INT_TYPES, REGISTRY_NAME, REGISTRY_VERSION,
                       SIGNED_TYPES, ModuleIndex, Pin, Sig, array_elem, attr_int, signature,
                       zero_lit)
from .wbc import F32, F64, I32, I64, STRING

COMPILER_VERSION = "wiretc-proto 0.1"

VT = {"bool": I32, "i8": I32, "u8": I32, "i16": I32, "u16": I32, "i32": I32, "u32": I32,
      "i64": I64, "u64": I64, "f32": F32, "f64": F64, "string": STRING}
PFX = {I32: "i32", I64: "i64", F32: "f32", F64: "f64"}


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
    exits: dict = field(default_factory=dict)
    results: dict = field(default_factory=dict)


@dataclass
class CompileResult:
    ok: bool
    diags: list
    wbc: Optional[bytes] = None
    module: Optional[wbc.WbcModule] = None


class EvalPoint:
    def __init__(self):
        self.uses = Counter()
        self.temps = {}


class Compiler:
    def __init__(self, module: Module, source: Optional[str] = None, embed_source=True,
                 debug=False):
        self.m = module
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

    # -- tables -------------------------------------------------------------------
    def vt(self, ty: str):
        """The WBC value type of a Wiret type; arrays become references to type entries."""
        elem = array_elem(ty)
        if elem is None:
            return VT[ty]
        return wbc.Ref(self.array_type(elem))

    def array_type(self, elem: str) -> int:
        """Index of the `array<elem>` type entry."""
        key = ("array", elem)
        if key not in self.type_keys:
            entry = wbc.ArrayType(self.vt(elem))     # inner entries come first
            self.type_keys[key] = len(self.types)
            self.types.append(entry)
        return self.type_keys[key]

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
        if array_elem(ty) is not None:
            value = None
        elif ty == "string":
            value = self.string_index(lit.value)
        elif ty == "bool":
            value = 1 if lit.value else 0
        elif ty in FLOAT_TYPES:
            value = float(lit.value)
        else:
            value = wrap_int(ty, int(lit.value))
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
        self.diags = check(self.m, comments_ok=True)
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
                    (wbc.FN_EVENT | wbc.FN_LATENT if g.kind == "event" else 0)
            t = type_index([self.vt(p.type) for p in g.params],
                           [self.vt(r.type) for r in g.result_list])
            mod.funcs.append((t, flags))
        for name, ty, value in self.globals:
            mod.globals.append((self.vt(ty), 1, value))
        for i, fl in enumerate(lowered):
            g = fl.g
            eflags = (wbc.EX_EVENT | wbc.EX_LATENT if g.kind == "event" else 0) | \
                     (wbc.EX_PURE if g.has_attr("pure") else 0)
            mod.exports.append((g.name, 0, len(self.imports) + i, eflags))
        for v in sorted(self.idx.vars.values(), key=lambda v: v.name):
            if v.attrs and any(a.name == "export" for a in v.attrs):
                mod.exports.append((v.name, 1, self.global_index[v.name], 0))
        mod.data = list(self.data)
        mod.types = self.types
        assembled = [fl.assemble() for fl in lowered]
        mod.bodies = [wbc.Body([self.vt(t) for t in fl.local_types[fl.nparams:]], 0xFFFF, 0, code)
                      for fl, (code, *_) in zip(lowered, assembled)]
        mod.customs = self.custom_sections(lowered, assembled)
        if self.embed_source:
            mod.flags |= wbc.FLAG_HAS_SOURCE
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
                  hashlib.sha256((self.source or canonical).encode()).hexdigest()):
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
        for p in g.params:
            self.add_local(p.name, p.type)
            self.pin_map[self.local_index[p.name]] = (entry_id, p.name)
        self.nparams = len(g.params)
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
        for l in sorted(g.locals, key=lambda l: l.name):
            ctx.locals[l.name] = l.name
            self.add_local(l.name, l.type, l.default)
        for s in sorted(g.states, key=lambda s: s.name):
            ctx.states[s.name] = self.c.add_global(f"{g.name}.{s.name}", s.type, s.default)
        self.expand(ctx)

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
            if n.kind == "Exit":
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
            elif n.kind in ARRAY_MUTATORS:
                if n.symbol in ctx.locals:
                    ir.extra["place"] = ("local", ctx.locals[n.symbol])
                else:
                    ir.extra["place"] = ("global", self.c.global_index[n.symbol])
            elif n.kind == "Call":
                callee = self.c.idx.callee(n.symbol)
                if callee.kind in ("func", "event"):
                    ir.extra["func"] = ("func", callee.name)
                else:
                    ir.extra["func"] = self.c.import_ref(callee.name)
                ir.extra["nresults"] = len(callee.results)
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
            sub.states[s.name] = self.c.add_global(f"{self.g.name}/{mpath}.{s.name}", s.type,
                                                   s.default)
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
            self.ir[cid] = ir
        self.expand(sub)

    # -- analysis -----------------------------------------------------------------
    def successors(self, n: IRNode) -> list:
        """Exec successors in layout preference order (fall-through first)."""
        ts = [t for _, t in n.execs]
        if n.kind in ("Branch",):
            ts = list(reversed(ts))
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
        work = [(self.entry, ())]

        def chain_end(nid, S):
            while True:
                if not S:
                    if nid not in warned:
                        warned.add(nid)
                        self.diag("W0302", "this chain can end without reaching Return; the "
                                           "function would return zero values", nid)
                    return
                k, S = S[-1], S[:-1]
                if k is not None:
                    work.append((k, S))
                    return

        while work and len(states) < 20000:
            nid, S = work.pop()
            if (nid, S) in states or len(S) > 64:
                continue
            states.add((nid, S))
            n = self.ir[nid]
            if n.kind == "Return":
                continue
            if n.kind == "Sequence":
                outs = [t for _, t in n.execs]
                if not outs:
                    chain_end(nid, S)
                    continue
                S2 = S + tuple(reversed(outs[1:]))
                nexts = [(outs[0], S2)]
            else:
                nexts = [(t, S) for _, t in n.execs] or [(None, S)]
            for t, s in nexts:
                if t is None:
                    chain_end(nid, s)
                else:
                    work.append((t, s))

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
                        self.slots[key] = self.add_local(f"{s.a}.{s.b}", ty)
                        self.pin_map[self.slots[key]] = key
        if self.c.debug:   # every impure output gets a slot, read or not
            for nid in sorted(self.ir):
                n = self.ir[nid]
                if not n.pure and n.kind == "Call":
                    for p in n.data_outs:
                        key = (nid, p.name)
                        if key not in self.slots:
                            self.slots[key] = self.add_local(f"{nid}.{p.name}", p.type)
                            self.pin_map[self.slots[key]] = key
        self.code = []
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
        elif k in ("Capture", "Exit"):
            self.emit_inputs(n)
            for name in reversed(n.extra["assign"]):
                self.E("local.set", self.local_index[name])
            self.transfer(then, nxt)
        elif k == "SetLocal":
            self.emit_inputs(n)
            self.E("local.set", self.local_index[n.extra["local"]])
            self.transfer(then, nxt)
        elif k in ("SetVar", "SetState"):
            self.emit_inputs(n)
            self.E("global.set", n.extra["global"])
            self.transfer(then, nxt)
        elif k == "Call":
            self.emit_inputs(n)
            self.E("call", n.extra["func"])
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
        elif k in ARRAY_MUTATORS:
            # read the place, apply the mutator (which yields the changed array), store it back
            kind, where = n.extra["place"]
            idx = self.local_index[where] if kind == "local" else where
            self.E(f"{kind}.get", idx)
            self.emit_inputs(n)
            op = {"ArraySet": "array.set", "ArrayAdd": "array.push", "ArrayInsert": "array.insert",
                  "ArrayRemove": "array.remove", "ArrayClear": "array.clear"}[k]
            self.E(op, self.c.array_type(n.targs[0]))
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

    def emit_inputs(self, n: IRNode):
        ep = EvalPoint()
        for _, _, s in n.inputs:
            self.count(s, ep)
        for _, _, s in n.inputs:
            self.eval(s, ep)
        self.ready(n)

    def ready(self, n: IRNode):
        """Debug builds mark the point where a node's inputs are evaluated and it is about to act."""
        if self.c.debug:
            self.code.append(("step", n.id))
            self.E("nop")

    def eval(self, s: Src, ep: EvalPoint):
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

    def emit_const(self, lit: Lit, ty: str):
        elem = array_elem(ty)
        if elem is not None:          # the only array constant is the empty array
            self.E("i32.const", 0)
            self.E("array.new", self.c.array_type(elem))
            return
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

    def emit_eq(self, ty: str):
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
            else:
                self.E("global.get", n.extra["global"])
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
            self.eval(n.inputs[0][2], ep)
            self.eval(n.inputs[1][2], ep)
            self.E("array.get", self.c.array_type(n.targs[0]))
            return
        if k == "ArrayLength":
            self.eval(n.inputs[0][2], ep)
            self.E("array.len")
            return
        if k == "Select":
            ty = n.targs[0]
            (_, _, cond), (_, _, a), (_, _, b) = n.inputs
            self.eval(cond, ep)
            tc = self.temp("bool")
            self.E("local.set", tc)
            self.eval(a, ep)
            self.eval(b, ep)
            self.E("local.get", tc)
            self.E("select")
            return
        for _, _, s in n.inputs:
            self.eval(s, ep)
        if k == "Call":
            self.E("call", n.extra["func"])
            return
        if k == "Convert":
            self.emit_convert(n.targs[0], n.targs[1])
            return
        if k == "Not":
            self.E("i32.eqz")
            return
        if k in ("And", "Or", "Xor"):
            self.E(f"i32.{k.lower()}")
            return
        T = n.targs[0]
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

    def emit_convert(self, f: str, t: str):
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
            self.E(f"{PFX[vt]}.trunc_{PFX[vf]}_{ts}")
            self.narrow(t)
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
        if op == "call":
            return (self.c.func_index(imms[0]),)
        return imms


def compile_module(module: Module, source: Optional[str] = None, embed_source=True,
                   debug=False) -> CompileResult:
    return Compiler(module, source, embed_source, debug).compile()
