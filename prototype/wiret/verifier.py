"""Single-pass bytecode verifier (spec section 5.5)."""
from __future__ import annotations

from .wbc import (F32, F64, FN_LATENT, FN_PURE, I32, I64, STRING, ArrayType, Ref, WbcError,
                  WbcModule, decode_code, vt_name)

VALTYPES = {I32, I64, F32, F64, STRING}
_PREFIX = {"i32": I32, "i64": I64, "f32": F32, "f64": F64}
_INT_CMP = {"eq", "ne", "lt_s", "lt_u", "gt_s", "gt_u", "le_s", "le_u", "ge_s", "ge_u"}
_INT_BIN = {"add", "sub", "mul", "div_s", "div_u", "rem_s", "rem_u", "and", "or", "xor", "shl",
            "shr_s", "shr_u"}
_INT_UN = {"neg", "not", "extend8_s", "extend16_s", "extend32_s"}
_F_CMP = {"eq", "ne", "lt", "gt", "le", "ge"}
_F_BIN = {"add", "sub", "mul", "div", "min", "max", "copysign"}
_F_UN = {"neg", "abs", "sqrt", "ceil", "floor", "trunc", "nearest"}


class VerifyError(Exception):
    def __init__(self, msg, func=None, pc=None):
        where = f"function {func}" if func is not None else "module"
        if pc is not None:
            where += f", pc {pc}"
        super().__init__(f"{where}: {msg}")


def simple_effect(name: str):
    """(pops, pushes) for instructions whose typing depends only on the opcode."""
    if name == "string.concat":
        return [STRING, STRING], [STRING]
    if name == "string.len":
        return [STRING], [I32]
    if name in ("string.eq", "string.cmp"):
        return [STRING, STRING], [I32]
    pre, _, op = name.partition(".")
    if pre not in _PREFIX:
        return None
    t = _PREFIX[pre]
    parts = op.split("_")
    if len(parts) >= 2 and parts[0] in ("wrap", "extend", "trunc", "convert", "demote",
                                        "promote", "reinterpret") and parts[1] in _PREFIX:
        return [_PREFIX[parts[1]]], [t]
    if pre in ("i32", "i64"):
        if op == "eqz":
            return [t], [I32]
        if op in _INT_CMP:
            return [t, t], [I32]
        if op in _INT_BIN:
            return [t, t], [t]
        if op in _INT_UN:
            return [t], [t]
    else:
        if op in _F_CMP:
            return [t, t], [I32]
        if op in _F_BIN:
            return [t, t], [t]
        if op in _F_UN:
            return [t], [t]
    return None


def valid_vt(m: WbcModule, vt, before=None) -> bool:
    """A supported value type. Array element types must refer to earlier entries (no cycles)."""
    if isinstance(vt, Ref):
        limit = len(m.types) if before is None else before
        return vt.type < limit and isinstance(m.types[vt.type], ArrayType)
    return vt in VALTYPES


def is_func_type(m: WbcModule, t: int) -> bool:
    return t < len(m.types) and not isinstance(m.types[t], ArrayType)


def verify(m: WbcModule) -> list:
    """Verify a decoded module. Returns, per defined function, (instrs, max_height)."""
    for i, entry in enumerate(m.types):
        vts = [entry.elem] if isinstance(entry, ArrayType) else entry[0] + entry[1]
        for vt in vts:
            if not valid_vt(m, vt, before=i if isinstance(entry, ArrayType) else None):
                raise VerifyError(f"type {i} uses an unsupported value type")
    for mod, fld, t, _ in m.imports:
        if not is_func_type(m, t):
            raise VerifyError(f"import {mod}.{fld} has bad type index {t}")
    for i, (t, flags) in enumerate(m.funcs):
        if not is_func_type(m, t):
            raise VerifyError(f"function has bad type index {t}", i)
        if flags & FN_PURE and flags & FN_LATENT:
            raise VerifyError("a pure function is never latent", i)
    if len(m.bodies) != len(m.funcs):
        raise VerifyError("function and code section counts differ")
    nfuncs = len(m.imports) + len(m.funcs)
    names = set()
    for name, kind, index, _ in m.exports:
        if name in names:
            raise VerifyError(f"duplicate export '{name}'")
        names.add(name)
        if kind == 0 and index >= nfuncs:
            raise VerifyError(f"export '{name}' names function {index}, out of range")
        if kind == 1 and index >= len(m.globals):
            raise VerifyError(f"export '{name}' names global {index}, out of range")
        if kind not in (0, 1):
            raise VerifyError(f"export '{name}' has unsupported kind {kind}")
    for gi, (vt, mut, init) in enumerate(m.globals):
        if not valid_vt(m, vt):
            raise VerifyError(f"global {gi} has unsupported type")
        if vt == STRING and init >= len(m.data):
            raise VerifyError(f"global {gi} initialiser names missing data {init}")
    return [verify_function(m, i) for i in range(len(m.funcs))]


def verify_function(m: WbcModule, i: int):
    fidx = len(m.imports) + i
    params, results, flags = m.func_type(fidx)
    body = m.bodies[i]
    for vt in body.locals:
        if not valid_vt(m, vt):
            raise VerifyError("local of unsupported type", fidx)
    local_types = list(params) + list(body.locals)
    try:
        instrs = decode_code(body.code)
    except WbcError as e:
        raise VerifyError(str(e), fidx)
    if not instrs:
        raise VerifyError("empty function body", fidx)
    starts = {ins.pc for ins in instrs}
    labels = set()
    for ins in instrs:
        if ins.name in ("br", "br_if", "cont.push"):
            t = ins.target()
            if t not in starts:
                raise VerifyError(f"branch target {t} is not an instruction boundary", fidx, ins.pc)
            labels.add(t)

    stack: list = []
    reachable = True
    max_h = 0

    def pop(expected, ins):
        if not stack:
            raise VerifyError(f"{ins.name}: operand stack underflow", fidx, ins.pc)
        got = stack.pop()
        if expected is not None and got != expected:
            raise VerifyError(f"{ins.name}: expected {vt_name(expected, m.types)}, found "
                              f"{vt_name(got, m.types)}", fidx, ins.pc)
        return got

    def array_type(ins):
        t = ins.imms[0]
        if t >= len(m.types) or not isinstance(m.types[t], ArrayType):
            raise VerifyError(f"{ins.name}: type {t} is not an array type", fidx, ins.pc)
        return Ref(t), m.types[t].elem

    for ins in instrs:
        if ins.pc in labels:
            if reachable and stack:
                raise VerifyError("operand stack is not empty at a label", fidx, ins.pc)
            reachable = True
        if not reachable:
            raise VerifyError("unreachable instruction without a label", fidx, ins.pc)
        n = ins.name
        eff = simple_effect(n)
        if eff is not None:
            for t in reversed(eff[0]):
                pop(t, ins)
            stack.extend(eff[1])
        elif n == "nop":
            pass
        elif n in ("br", "unreachable"):
            if n == "br" and stack:
                raise VerifyError("br with a non-empty operand stack", fidx, ins.pc)
            stack.clear()
            reachable = False
        elif n == "br_if":
            if stack != [I32]:
                raise VerifyError("br_if needs exactly one i32 on the stack", fidx, ins.pc)
            stack.clear()
        elif n == "cont.push":
            pass
        elif n == "cont.pop":
            if stack:
                raise VerifyError("cont.pop with a non-empty operand stack", fidx, ins.pc)
        elif n == "return":
            if stack != list(results):
                raise VerifyError("stack does not match the function's results at return",
                                  fidx, ins.pc)
            stack.clear()
            reachable = False
        elif n == "call":
            callee = ins.imms[0]
            if callee >= len(m.imports) + len(m.funcs):
                raise VerifyError(f"call to unknown function {callee}", fidx, ins.pc)
            cp, cr, cflags = m.func_type(callee)
            if cflags & FN_LATENT and not flags & FN_LATENT and callee >= len(m.imports):
                raise VerifyError("non-latent function calls a latent function", fidx, ins.pc)
            for t in reversed(cp):
                pop(t, ins)
            stack.extend(cr)
        elif n == "drop":
            pop(None, ins)
        elif n == "select":
            pop(I32, ins)
            b = pop(None, ins)
            pop(b, ins)
            stack.append(b)
        elif n in ("local.get", "local.set", "local.tee"):
            li = ins.imms[0]
            if li >= len(local_types):
                raise VerifyError(f"local {li} out of range", fidx, ins.pc)
            t = local_types[li]
            if n == "local.get":
                stack.append(t)
            else:
                pop(t, ins)
                if n == "local.tee":
                    stack.append(t)
        elif n in ("global.get", "global.set"):
            gi = ins.imms[0]
            if gi >= len(m.globals):
                raise VerifyError(f"global {gi} out of range", fidx, ins.pc)
            t, mut, _ = m.globals[gi]
            if n == "global.get":
                stack.append(t)
            else:
                if not mut:
                    raise VerifyError(f"global {gi} is immutable", fidx, ins.pc)
                pop(t, ins)
        elif n == "i32.const":
            if not -2**31 <= ins.imms[0] < 2**31:
                raise VerifyError("i32.const out of range", fidx, ins.pc)
            stack.append(I32)
        elif n == "i64.const":
            stack.append(I64)
        elif n == "f32.const":
            stack.append(F32)
        elif n == "f64.const":
            stack.append(F64)
        elif n == "array.len":
            got = pop(None, ins)
            if not isinstance(got, Ref) or not isinstance(m.types[got.type], ArrayType):
                raise VerifyError("array.len needs an array", fidx, ins.pc)
            stack.append(I32)
        elif n.startswith("array."):
            ref, elem = array_type(ins)
            operands = {"array.new": [I32], "array.get": [ref, I32],
                        "array.set": [ref, I32, elem], "array.push": [ref, elem],
                        "array.insert": [ref, I32, elem], "array.remove": [ref, I32],
                        "array.clear": [ref], "array.clone": [ref]}[n]
            for t in reversed(operands):
                pop(t, ins)
            stack.append(elem if n == "array.get" else ref)
        elif n == "string.const":
            if ins.imms[0] >= len(m.data):
                raise VerifyError(f"data index {ins.imms[0]} out of range", fidx, ins.pc)
            stack.append(STRING)
        else:
            raise VerifyError(f"instruction {n} is not supported", fidx, ins.pc)
        max_h = max(max_h, len(stack))
    if reachable:
        raise VerifyError("control can fall off the end of the function", fidx)
    if max_h > body.max_stack:
        raise VerifyError(f"operand stack reaches {max_h}, above declared max_stack "
                          f"{body.max_stack}", fidx)
    return instrs, max_h
