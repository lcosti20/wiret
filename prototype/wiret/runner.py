"""Helpers shared by the CLI and the editor for calling a function with typed arguments."""
from __future__ import annotations

from typing import Optional

from .model import Lit, Module
from .natives import float_to_text
from .parser import ParseError, Parser, parse_literal
from .registry import FLOAT_TYPES, array_elem, lit_fits


def lit_value(lit: Lit, ty: str, name: str):
    """A Python value for a literal argument of type `ty` (arrays from `[a, b, ...]`)."""
    elem = array_elem(ty)
    if elem is not None:
        if lit.kind != "list":
            raise ValueError(f"argument {name}: write an array as [1, 2, 3]")
        return tuple(lit_value(x, elem, name) for x in lit.value)
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
    for p, t in zip(g.params, texts):
        try:
            if array_elem(p.type) is not None:
                parser = Parser(t)
                lit = parser.value()
            else:
                lit = parse_literal(t if p.type != "string" or t.startswith('"') else f'"{t}"')
        except ParseError as e:
            raise ValueError(f"argument {p.name}: {e.msg}")
        out.append(lit_value(lit, p.type, p.name))
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


def format_value(ty: Optional[str], v) -> str:
    elem = array_elem(ty) if ty else None
    if elem is not None or isinstance(v, tuple):
        return "[" + ", ".join(format_value(elem, x) for x in v) + "]"
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
    return ", ".join(f"{r.name} = {format_value(r.type, v)}" for r, v in zip(g.result_list, values))
