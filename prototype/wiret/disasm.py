"""Disassembler (`wiretc dis`, spec section 5.8): bytecode with node ids from `wr.debug`."""
from __future__ import annotations

from . import wbc
from .vm import parse_customs
from .wbc import ArrayType, decode_code, vt_name


def disassemble(data: bytes) -> str:
    m = wbc.decode_module(data)
    names, local_names, debug, meta = parse_customs(m)
    out = []
    if meta:
        out.append(f"; module {meta.get('module', '')}  compiler {meta.get('compiler', '')}")
        out.append(f"; semantic hash {meta.get('semantic_hash', '')[:16]}  "
                   f"layout hash {meta.get('layout_hash', '')[:16]}")
    for i, (mod, fld, t, flags) in enumerate(m.imports):
        params, results = m.types[t]
        out.append(f"import {i} {mod}.{fld} ({', '.join(vt_name(p, m.types) for p in params)}) -> "
                   f"({', '.join(vt_name(r, m.types) for r in results)})" + (" pure" if flags & 1 else ""))
    for gi, (vt, mut, init) in enumerate(m.globals):
        out.append(f"global {gi} {vt_name(vt, m.types)} {names.get(gi, '')}")
    nimp = len(m.imports)
    gnames = {}
    p = m.custom("name")
    if p:
        r = wbc.Reader(p)
        for _ in range(r.u32()):
            r.u32(), r.name()
        for _ in range(r.u32()):
            r.u32()
            for _ in range(r.u32()):
                r.u32(), r.name()
        for _ in range(r.u32()):
            gi = r.u32()
            gnames[gi] = r.name()
    for i, ((t, flags), body) in enumerate(zip(m.funcs, m.bodies)):
        fi = nimp + i
        params, results = m.types[t]
        lnames = local_names.get(fi, {})
        tags = [s for b, s in ((wbc.FN_PURE, "pure"), (wbc.FN_EVENT, "event")) if flags & b]
        out.append("")
        out.append(f"func {names.get(fi, f'func{fi}')} ({', '.join(vt_name(p, m.types) for p in params)})"
                   f" -> ({', '.join(vt_name(r, m.types) for r in results)})"
                   + (f"  [{', '.join(tags)}]" if tags else ""))
        locs = [f"{len(params) + k}:{vt_name(vt, m.types)} {lnames.get(len(params) + k, '')}".rstrip()
                for k, vt in enumerate(body.locals)]
        if locs:
            out.append("  locals: " + ", ".join(locs))
        out.append(f"  max_stack: {body.max_stack}")
        instrs = decode_code(body.code)
        labels = {pc: node for pc, node in debug.get(fi, (None, [], []))[1]}
        targets = {ins.target() for ins in instrs if ins.name in ("br", "br_if", "cont.push")}
        for ins in instrs:
            if ins.pc in labels:
                out.append(f".{labels[ins.pc]}:")
            elif ins.pc in targets:
                out.append(f".pc{ins.pc}:")
            text = ins.name
            comment = ""
            if ins.name in ("br", "br_if", "cont.push"):
                t = ins.target()
                text += " ." + labels.get(t, f"pc{t}")
            elif ins.name == "call":
                text += f" {names.get(ins.imms[0], ins.imms[0])}"
            elif ins.name.startswith("local."):
                text += f" {ins.imms[0]}"
                comment = lnames.get(ins.imms[0], "")
            elif ins.name.startswith("global."):
                text += f" {ins.imms[0]}"
                comment = gnames.get(ins.imms[0], "")
            elif ins.name == "string.const":
                text += f" {ins.imms[0]}"
                s = m.data[ins.imms[0]]
                comment = repr(s if len(s) < 40 else s[:37] + "...")
            elif ins.name.startswith("array.") and ins.imms:
                t = ins.imms[0]
                text += f" {t}"
                if t < len(m.types) and isinstance(m.types[t], ArrayType):
                    comment = f"array<{vt_name(m.types[t].elem, m.types)}>"
            elif ins.imms:
                text += " " + " ".join(str(x) for x in ins.imms)
            line = f"  {text}"
            if comment:
                line = f"{line:<26}; {comment}"
            out.append(line)
    return "\n".join(out) + "\n"
