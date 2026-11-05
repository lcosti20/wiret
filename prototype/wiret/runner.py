"""Helpers shared by the CLI and the editor for calling a function with typed arguments."""
from __future__ import annotations

from typing import Optional

from .model import Lit, Module
from .natives import float_to_text
from .parser import ParseError, Parser, parse_literal
from .registry import FLOAT_TYPES, ModuleIndex, array_elem, enum_values, lit_fits


def lit_value(lit: Lit, ty: str, name: str, idx: Optional[ModuleIndex] = None):
    """A Python value for a literal argument of type `ty` (arrays from `[a, b, ...]`, enum
    members as `Mode.Chase`). Structs cannot be typed as an argument."""
    elem = array_elem(ty)
    if elem is not None:
        if lit.kind != "list":
            raise ValueError(f"argument {name}: write an array as [1, 2, 3]")
        return tuple(lit_value(x, elem, name, idx) for x in lit.value)
    if idx is not None and ty in idx.structs:
        raise ValueError(f"argument {name}: a {ty} struct cannot be typed as an argument; "
                         f"call a function that makes one instead")
    if idx is not None and ty in idx.enums:
        values = dict(enum_values(idx.enums[ty]))
        member = lit.value.split(".", 1)[1] if lit.kind == "enum" else None
        if not lit_fits(lit, ty) or member not in values:
            names = ", ".join(f"{ty}.{m}" for m in values)
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
            if array_elem(p.type) is not None:
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
    if idx is not None and ty in idx.structs and isinstance(v, tuple):
        fields = idx.structs[ty].fields
        inner = ", ".join(f"{f.name}: {format_value(f.type, x, idx)}" for f, x in zip(fields, v))
        return f"{ty} {{ {inner} }}" if inner else f"{ty} {{}}"
    if idx is not None and ty in idx.enums:
        base = idx.enum_base(ty)
        for name, value in enum_values(idx.enums[ty]):
            if format_value(base, value) == format_value(base, v):
                return f"{ty}.{name}"
        return f"{ty}({format_value(base, v)})"   # Convert does not check membership
    elem = array_elem(ty) if ty else None
    if elem is not None or isinstance(v, tuple):
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
