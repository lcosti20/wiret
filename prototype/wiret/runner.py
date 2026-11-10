"""Helpers shared by the CLI and the editor for calling a function with typed arguments."""
from __future__ import annotations

from typing import Optional

from .model import Lit, Module
from .natives import float_to_text
from .parser import ParseError, Parser, parse_literal
from .registry import (FLOAT_TYPES, ModuleIndex, array_elem, enum_values, is_container,
                       lit_fits, map_types, set_elem, lane_lit_fits, lane_value)
from . import lanes
from .lanes import LANE_FIELDS


def lit_value(lit: Lit, ty: str, name: str, idx: Optional[ModuleIndex] = None):
    """A Python value for a literal argument of type `ty`: arrays and sets from `[a, b, ...]`,
    maps from `{k: v, ...}`, enum members as `Mode.Chase`. Structs cannot be typed as an
    argument."""
    elem = array_elem(ty)
    if elem is not None:
        if lit.kind != "list":
            raise ValueError(f"argument {name}: write an array as [1, 2, 3]")
        return tuple(lit_value(x, elem, name, idx) for x in lit.value)
    elem = set_elem(ty)
    if elem is not None:
        if lit.kind != "list":
            raise ValueError(f"argument {name}: write a set as [1, 2, 3]")
        return {lit_value(x, elem, name, idx): None for x in lit.value}
    kv = map_types(ty)
    if kv is not None:
        if lit.kind == "list" and not lit.value:
            return {}
        if lit.kind != "map":
            raise ValueError(f"argument {name}: write a map as {{\"a\": 1, \"b\": 2}}")
        return {lit_value(k, kv[0], name, idx): lit_value(v, kv[1], name, idx)
                for k, v in lit.value}
    if ty in LANE_FIELDS:               # a lane literal: (0, 1, 0), nested for a transform
        if not lane_lit_fits(lit, ty):
            example = "((0, 0, 0), (0, 0, 0, 1), (1, 1, 1))" if ty == "transform" else                 "(" + ", ".join("0" for _ in LANE_FIELDS[ty]) + ")"
            raise ValueError(f"argument {name}: write a {ty} as {example}")
        return lanes.normalise(ty, lane_value(lit, ty))
    if idx is not None and ty in idx.structs:
        raise ValueError(f"argument {name}: a {ty} struct cannot be typed as an argument; "
                         f"call a function that makes one instead")
    if idx is not None and ty in idx.enums:
        values = dict(enum_values(idx.enums[ty]))
        member = lit.value.split(".", 1)[1] if lit.kind == "enum" else None
        if not lit_fits(lit, ty) or member not in values:
            names = ", ".join(f"{ty}::{m}" for m in values)
            raise ValueError(f"argument {name}: write one of {names}")
        return values[member]
    if not lit_fits(lit, ty):
        raise ValueError(f"argument {name}: {lit.value!r} is not a {ty}")
    if ty == "bool":
        return 1 if lit.value else 0
    if ty in FLOAT_TYPES:
        return float(lit.value)
    return lit.value


def parse_args_for(m: Module, func: str, texts: list) -> list:
    g = m.graph(func)
    if g is None or g.kind == "macro":
        raise ValueError(f"no function '{func}'")
    if len(texts) != len(g.params):
        sig = ", ".join(f"{p.name}: {p.type}" for p in g.params)
        raise ValueError(f"{func}({sig}) takes {len(g.params)} argument(s), got {len(texts)}")
    out = []
    idx = ModuleIndex(m)
    for p, t in zip(g.params, texts):
        try:
            if is_container(p.type):
                parser = Parser(t)
                lit = parser.value()
            else:
                lit = parse_literal(t if p.type != "string" or t.startswith('"') else f'"{t}"')
        except ParseError as e:
            raise ValueError(f"argument {p.name}: {e.msg}")
        out.append(lit_value(lit, p.type, p.name, idx))
    return out


def split_args(text: str) -> list:
    """Split comma-separated arguments, keeping [..] arrays and "..." strings together."""
    out, depth, cur, quoted = [], 0, "", False
    for ch in text:
        if ch == '"' and not cur.endswith("\\"):
            quoted = not quoted
        if not quoted and ch == "[":
            depth += 1
        elif not quoted and ch == "]":
            depth -= 1
        if ch == "," and depth == 0 and not quoted:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def format_value(ty: Optional[str], v, idx: Optional[ModuleIndex] = None) -> str:
    """A value as text: `Vec2 { x: 1.0, y: 1.5 }` for a struct and `Mode.Chase` for an enum
    when `idx` knows the type; without it, a struct shows as a list of its field values."""
    if v is None and (ty is None or idx is None or ty in idx.classes):
        return "null"
    if hasattr(v, "cls") and hasattr(v, "fields"):          # a class instance (vm.Obj)
        names = v.cls.field_names
        if idx is not None and v.cls.name in idx.classes:
            types = [f.type for _, f in idx.class_fields(v.cls.name)]
        else:
            types = [None] * len(names)
        inner = ", ".join(f"{n}: {format_value(t, x, idx) if not hasattr(x, 'cls') else '<' + x.cls.name + '>'}"
                          for n, t, x in zip(names, types, v.fields))
        return f"{v.cls.name} {{ {inner} }}" if inner else f"{v.cls.name} {{}}"
    if ty in LANE_FIELDS and isinstance(v, tuple):     # the literal form (section 3.2)
        return lanes.to_text(v, lambda x: format_value("f32", x))
    if idx is not None and ty in idx.structs and isinstance(v, tuple):
        fields = idx.structs[ty].fields
        inner = ", ".join(f"{f.name}: {format_value(f.type, x, idx)}" for f, x in zip(fields, v))
        return f"{ty} {{ {inner} }}" if inner else f"{ty} {{}}"
    if idx is not None and ty in idx.enums:
        base = idx.enum_base(ty)
        for name, value in enum_values(idx.enums[ty]):
            if format_value(base, value) == format_value(base, v):
                return f"{ty}::{name}"
        return f"{ty}({format_value(base, v)})"   # Convert does not check membership
    if isinstance(v, dict):           # a map {k: v} or a set {a, b}
        kv = map_types(ty) if ty else None
        if kv is None and set_elem(ty or "") is None:
            is_map = any(x is not None for x in v.values())   # untyped: set values are None
        else:
            is_map = kv is not None
        if is_map:
            k_ty, v_ty = kv or (None, None)
            return "{" + ", ".join(f"{format_value(k_ty, k, idx)}: {format_value(v_ty, x, idx)}"
                                   for k, x in v.items()) + "}"
        return "{" + ", ".join(format_value(set_elem(ty or ""), x, idx) for x in v) + "}"
    elem = array_elem(ty) if ty else None
    if elem is not None or isinstance(v, (tuple, list)):
        return "[" + ", ".join(format_value(elem, x, idx) for x in v) + "]"
    if ty == "bool":
        return "true" if v else "false"
    if ty == "string":
        return repr(v)
    if ty in ("u8", "u16", "u32"):
        return str(v & 0xFFFFFFFF)
    if ty == "u64":
        return str(v & 0xFFFFFFFFFFFFFFFF)
    if isinstance(v, float):
        return float_to_text(v, single=(ty == "f32"))
    return str(v)


def format_results(m: Optional[Module], func: str, values: list) -> str:
    g = m.graph(func) if m else None
    if g is None:
        return ", ".join(str(v) for v in values) if values else "(no results)"
    if not g.result_list:
        return "(no results)"
    idx = ModuleIndex(m)
    return ", ".join(f"{r.name} = {format_value(r.type, v, idx)}"
                     for r, v in zip(g.result_list, values))


MAX_ADVANCES = 100_000


def run_function(vm, lm, func: str, args: list) -> list:
    """Call `func` and return its results. A latent function or event runs as a fiber (section
    4.5): idle virtual time is skipped, each wait jumping straight to the next timer, so a
    `Delay` of five seconds finishes at once. Stops with WR_YIELD if it waits for a signal
    that nothing can fire any more."""
    from .vm import (FIBER_DONE, FIBER_FAULTED, FIBER_READY, STATUS_FUEL, STATUS_YIELD,
                     WiretError)
    from .wbc import FN_LATENT
    f = lm.funcs[lm.exports[func]] if func in lm.exports else None
    owner = func.rpartition(".")[0]
    if f is not None and owner in lm.classes and len(args) == len(f.params) - 1:
        args = [vm.new(lm, owner)] + list(args)    # a method runs on a new object
    if f is None or not f.flags & FN_LATENT:
        return vm.call(lm, func, args)
    fb = vm.start(lm, func, args, now=True)
    for _ in range(MAX_ADVANCES):
        if fb.status == FIBER_DONE:
            return fb.results
        if fb.status == FIBER_FAULTED:
            raise fb.error
        nxt = vm.next_wake()
        if any(x.status == FIBER_READY for x in vm.fibers):
            vm.advance(0.0)
        elif nxt is not None:
            vm.advance(max(nxt - vm.time, 0.0))
        else:
            raise WiretError(STATUS_YIELD, f"'{func}' is waiting for a signal that nothing will "
                                           f"fire")
    raise WiretError(STATUS_FUEL, f"'{func}' was still running after {MAX_ADVANCES} steps of "
                                  f"virtual time")
