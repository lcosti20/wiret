"""Single-pass bytecode verifier (spec section 5.5)."""
from __future__ import annotations

from .wbc import (ANYREF, F32, F64, FAULT, FN_LATENT, SIGNAL, FN_PURE, I32, I64, STRING, ArrayType, MapType,
                  ClassType, DelegateType, DispatcherType, FN_EVENT, InterfaceType, Ref,
                  SetType, StructType, WbcError, WbcModule, decode_code, vt_name,
                  FLAG_LANES, LANE_VTS)
from . import lanes

REF_TYPES = (ArrayType, StructType, MapType, SetType, ClassType, InterfaceType, DelegateType,
             DispatcherType)

VALTYPES = {I32, I64, F32, F64, STRING}
# Types allowed in locals, globals and function types but not in struct fields or containers:
# a fault (the local `try.push` names) and a signal (section 4.5).
HANDLE_TYPES = {FAULT, SIGNAL}
_PREFIX = {"i32": I32, "i64": I64, "f32": F32, "f64": F64}
_INT_CMP = {"eq", "ne", "lt_s", "lt_u", "gt_s", "gt_u", "le_s", "le_u", "ge_s", "ge_u"}
_INT_BIN = {"add", "sub", "mul", "div_s", "div_u", "rem_s", "rem_u", "and", "or", "xor", "shl",
            "shr_s", "shr_u"}
_INT_UN = {"neg", "not", "extend8_s", "extend16_s", "extend32_s"}
_F_CMP = {"eq", "ne", "lt", "gt", "le", "ge"}
_F_BIN = {"add", "sub", "mul", "div", "min", "max", "copysign"}
_F_UN = {"neg", "abs", "sqrt", "ceil", "floor", "trunc", "nearest"}
# Wiret type names of the operands of lane instructions -> value types
_LANE_VT = {"f32": F32, "bool": I32, **{name: vt for vt, name in LANE_VTS.items()}}


def lane_effect(name: str, field: int = 0):
    """(pops, pushes) of a lane instruction (section 5.6)."""
    ins, out = lanes.effect(name, field)
    return [_LANE_VT[t] for t in ins], [_LANE_VT[out]]


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


def valid_vt(m: WbcModule, vt) -> bool:
    """A supported value type: a number, a string, or a reference to an array or struct type.
    References may point forward (`struct Tree { children: array::<Tree> }`); the check that a
    struct does not hold itself by value is `check_struct_cycles`."""
    if isinstance(vt, Ref):
        return vt.type < len(m.types) and isinstance(m.types[vt.type], REF_TYPES)
    if vt in LANE_VTS:                  # only in a module that declares them (section 5.2)
        return bool(m.flags & FLAG_LANES)
    return vt in VALTYPES


def key_vt_ok(m: WbcModule, vt, depth=0) -> bool:
    """A map key or set element: a number, a string, or a struct of those (section 3.1)."""
    if not isinstance(vt, Ref):
        return vt in VALTYPES or (vt in LANE_VTS and bool(m.flags & FLAG_LANES))
    entry = m.types[vt.type] if vt.type < len(m.types) else None
    if not isinstance(entry, StructType) or depth > 64:
        return False
    return all(key_vt_ok(m, fvt, depth + 1) for fvt, _ in entry.fields)


def class_chain(m: WbcModule, t: int) -> list:
    """A class type index and its superclasses, nearest first (the hierarchy is acyclic once
    `check_classes` has passed)."""
    out = []
    while t is not None and t not in out:
        out.append(t)
        t = m.types[t].super
    return out


def is_sub(m: WbcModule, got, expected) -> bool:
    """Reference subtyping (section 5.5): a class is a subtype of its superclass chain, and
    every reference is a subtype of anyref."""
    if got == expected:
        return True
    if expected == ANYREF:
        return isinstance(got, Ref)
    if not (isinstance(got, Ref) and isinstance(expected, Ref)
            and isinstance(m.types[got.type], ClassType)):
        return False
    target = m.types[expected.type]
    if isinstance(target, ClassType):
        return expected.type in class_chain(m, got.type)
    if isinstance(target, InterfaceType):    # a class is a subtype of its interfaces
        return any(i == expected.type for i, _ in m.types[got.type].interfaces)
    return False


def common_ref(m: WbcModule, a, b):
    """The type of `select` over two references: one if the other is its subtype, else anyref."""
    if is_sub(m, a, b):
        return b
    if is_sub(m, b, a):
        return a
    return ANYREF


def check_classes(m: WbcModule, nfuncs: int):
    """Superclasses exist and form no cycle; each vtable keeps its superclass's slots, and every
    entry takes a receiver of this class or a superclass, and the parameters and results of
    the slot it fills."""
    for t, entry in enumerate(m.types):
        if not isinstance(entry, ClassType):
            continue
        if entry.super is not None and (entry.super >= len(m.types)
                                        or not isinstance(m.types[entry.super], ClassType)):
            raise VerifyError(f"class type {t} has a superclass that is not a class type")
    for t, entry in enumerate(m.types):
        if isinstance(entry, ClassType):
            seen, cur = set(), t
            while cur is not None:
                if cur in seen:
                    raise VerifyError(f"class type {t} inherits from itself")
                seen.add(cur)
                cur = m.types[cur].super
    for t, entry in enumerate(m.types):
        if not isinstance(entry, ClassType):
            continue
        chain = class_chain(m, t)
        sup = m.types[entry.super] if entry.super is not None else None
        if sup is not None and len(entry.vtable) < len(sup.vtable):
            raise VerifyError(f"class type {t} drops slots of its superclass's vtable")
        mine = [i for i, _ in entry.interfaces]
        if len(set(mine)) != len(mine):
            raise VerifyError(f"class type {t} lists an interface twice")
        if sup is not None and not {i for i, _ in sup.interfaces} <= set(mine):
            raise VerifyError(f"class type {t} drops an interface of its superclass")
        for iface, impl in entry.interfaces:
            if iface >= len(m.types) or not isinstance(m.types[iface], InterfaceType):
                raise VerifyError(f"class type {t} implements type {iface}, not an interface")
            methods = m.types[iface].methods
            if len(impl) != len(methods):
                raise VerifyError(f"class type {t} gives {len(impl)} methods for interface "
                                  f"{iface}, which has {len(methods)}")
            for k, (fi, ft) in enumerate(zip(impl, methods)):
                if fi >= nfuncs or ft >= len(m.types) or not isinstance(m.types[ft], tuple):
                    raise VerifyError(f"class type {t}: interface {iface} method {k} is out "
                                      f"of range")
                params, results, flags = m.func_type(fi)
                if not params or not isinstance(params[0], Ref) or params[0].type not in chain:
                    raise VerifyError(f"class type {t}: interface {iface} method {k} does not "
                                      f"take this class or a superclass as its receiver")
                if list(params[1:]) != list(m.types[ft][0]) or list(results) != list(m.types[ft][1]):
                    raise VerifyError(f"class type {t}: interface {iface} method {k} does not "
                                      f"have the interface's signature")
                if flags & FN_LATENT:
                    raise VerifyError(f"class type {t}: interface {iface} method {k} is latent")
        for slot, fi in enumerate(entry.vtable):
            if fi >= nfuncs:
                raise VerifyError(f"class type {t} slot {slot} names function {fi}, out of range")
            params, results, _ = m.func_type(fi)
            if not params or not isinstance(params[0], Ref) or params[0].type not in chain:
                raise VerifyError(f"class type {t} slot {slot}: the function does not take this "
                                  f"class or a superclass as its receiver")
            if sup is not None and slot < len(sup.vtable):
                bp, br, _ = m.func_type(sup.vtable[slot])
                if list(bp[1:]) != list(params[1:]) or list(br) != list(results):
                    raise VerifyError(f"class type {t} slot {slot} does not have the signature "
                                      f"of the slot it overrides")


def class_fields(m: WbcModule, t: int) -> list:
    """Every field's value type, inherited ones first: the layout `class.get` indexes."""
    out = []
    for c in reversed(class_chain(m, t)):
        out += [vt for vt, _ in m.types[c].fields]
    return out


def is_func_type(m: WbcModule, t: int) -> bool:
    return t < len(m.types) and isinstance(m.types[t], tuple)


def check_struct_cycles(m: WbcModule):
    """A struct field that is a struct (not an array of one) is held by value, so these
    edges must form no cycle: otherwise the struct has no finite default value."""
    state = {}                      # type index -> 1 visiting, 2 done

    def visit(t):
        if state.get(t) == 2:
            return
        if state.get(t) == 1:
            raise VerifyError(f"struct type {t} contains itself by value")
        state[t] = 1
        for vt, _ in m.types[t].fields:
            if isinstance(vt, Ref) and isinstance(m.types[vt.type], StructType):
                visit(vt.type)
        state[t] = 2

    for t, entry in enumerate(m.types):
        if isinstance(entry, StructType):
            visit(t)


def verify(m: WbcModule) -> list:
    """Verify a decoded module. Returns, per defined function, (instrs, max_height)."""
    for i, entry in enumerate(m.types):
        if isinstance(entry, ArrayType):
            vts = [entry.elem]
        elif isinstance(entry, (MapType, SetType)):
            vts = [entry.key, entry.value] if isinstance(entry, MapType) else [entry.elem]
        elif isinstance(entry, (DelegateType, DispatcherType)):
            vts = []
            if not is_func_type(m, entry.functype):
                raise VerifyError(f"type {i} names {entry.functype}, not a function type")
            if isinstance(entry, DispatcherType) and m.types[entry.functype][1]:
                raise VerifyError(f"dispatcher type {i} has results")
        elif isinstance(entry, InterfaceType):
            vts = []
            for ft in entry.methods:
                if not is_func_type(m, ft):
                    raise VerifyError(f"interface type {i} names {ft}, not a function type")
        elif isinstance(entry, (StructType, ClassType)):
            vts = [vt for vt, _ in entry.fields]
            for vt, default in entry.fields:
                if vt == STRING and default is not None and default >= len(m.data):
                    raise VerifyError(f"type {i} has a field default naming missing data")
        else:
            # a function type may also use anyref, which a native such as std.array.Equals
            # takes so that one signature serves every container type (section 4.9)
            # and fault, which std.fault.Make, Message and Code take and return (section 4.6)
            vts = [vt for vt in entry[0] + entry[1] if vt not in (ANYREF, FAULT, SIGNAL)]
        for vt in vts:
            if not valid_vt(m, vt):
                raise VerifyError(f"type {i} uses an unsupported value type")
    check_struct_cycles(m)
    for i, entry in enumerate(m.types):
        if isinstance(entry, (MapType, SetType)):
            k = entry.key if isinstance(entry, MapType) else entry.elem
            if not key_vt_ok(m, k):
                raise VerifyError(f"type {i}: a map key or set item must be a number, a string "
                                  f"or a struct of those")
    for mod, fld, t, _ in m.imports:
        if not is_func_type(m, t):
            raise VerifyError(f"import {mod}.{fld} has bad type index {t}")
    for i, (t, flags) in enumerate(m.funcs):
        if not is_func_type(m, t):
            raise VerifyError(f"function has bad type index {t}", i)
        if flags & ~(FN_PURE | FN_LATENT | FN_EVENT):
            raise VerifyError(f"function has unknown flag bits {flags:#04x}", i)
        if flags & FN_PURE and flags & FN_LATENT:
            raise VerifyError("a pure function is never latent", i)
        if flags & FN_EVENT and (m.types[t][1] or not flags & FN_LATENT):
            raise VerifyError("an event is latent and has no results", i)
    if len(m.bodies) != len(m.funcs):
        raise VerifyError("function and code section counts differ")
    check_classes(m, len(m.imports) + len(m.funcs))
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
        if kind == 2 and index >= len(m.types):
            raise VerifyError(f"export '{name}' names type {index}, out of range")
        if kind not in (0, 1, 2):
            raise VerifyError(f"export '{name}' has unsupported kind {kind}")
    for gi, (vt, mut, init) in enumerate(m.globals):
        if vt != SIGNAL and not valid_vt(m, vt):
            raise VerifyError(f"global {gi} has unsupported type")
        if vt == STRING and init >= len(m.data):
            raise VerifyError(f"global {gi} initialiser names missing data {init}")
    return [verify_function(m, i) for i in range(len(m.funcs))]


def verify_function(m: WbcModule, i: int):
    fidx = len(m.imports) + i
    params, results, flags = m.func_type(fidx)
    body = m.bodies[i]
    for vt in body.locals:
        if vt not in HANDLE_TYPES and vt != ANYREF and not valid_vt(m, vt):
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
        if ins.name in ("br", "br_if", "cont.push", "try.push"):
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
        if expected is not None and is_sub(m, got, expected):
            return got                 # a subclass, or any reference for anyref (5.5)
        if expected is not None and got != expected:
            raise VerifyError(f"{ins.name}: expected {vt_name(expected, m.types)}, found "
                              f"{vt_name(got, m.types)}", fidx, ins.pc)
        return got

    def struct_type(ins):
        t = ins.imms[0]
        if t >= len(m.types) or not isinstance(m.types[t], StructType):
            raise VerifyError(f"{ins.name}: type {t} is not a struct type", fidx, ins.pc)
        fields = [vt for vt, _ in m.types[t].fields]
        if len(ins.imms) > 1 and ins.imms[1] >= len(fields):
            raise VerifyError(f"{ins.name}: struct type {t} has no field {ins.imms[1]}",
                              fidx, ins.pc)
        return Ref(t), fields

    def container_type(ins, cls):
        t = ins.imms[0]
        if t >= len(m.types) or not isinstance(m.types[t], cls):
            raise VerifyError(f"{ins.name}: type {t} is not a {cls.__name__[:-4].lower()} type",
                              fidx, ins.pc)
        return Ref(t), m.types[t]

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
        if ins.op > 0xFF:                  # a lane instruction
            if not m.flags & FLAG_LANES:
                raise VerifyError(f"{n}: lane instructions need feature flag bit 1", fidx,
                                  ins.pc)
            field = ins.imms[0] if ins.imms else 0
            ty = lanes.BLOCKS[n.partition(".")[0]][1]
            if ins.imms and field >= len(lanes.LANE_FIELDS[ty]):
                raise VerifyError(f"{n}: {ty} has no field {field}", fidx, ins.pc)
            eff = lane_effect(n, field)
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
        elif n == "try.push":
            li = ins.imms[1]
            if li >= len(local_types) or local_types[li] != FAULT:
                raise VerifyError("try.push must name a local of type fault", fidx, ins.pc)
        elif n == "suspend":
            kind = ins.imms[0]
            if not flags & FN_LATENT:
                raise VerifyError("suspend in a function that is not latent", fidx, ins.pc)
            if kind > 2:
                raise VerifyError(f"suspend kind {kind} is not 0, 1 or 2", fidx, ins.pc)
            if kind:
                pop(F64 if kind == 1 else SIGNAL, ins)
            if stack:
                raise VerifyError("suspend with more than its operand on the stack", fidx, ins.pc)
        elif n == "throw":
            pop(FAULT, ins)
            stack.clear()
            reachable = False
        elif n == "cont.pop":
            if stack:
                raise VerifyError("cont.pop with a non-empty operand stack", fidx, ins.pc)
        elif n == "cont.depth":
            stack.append(I32)
        elif n == "cont.trunc":
            pop(I32, ins)
        elif n == "return":
            if len(stack) != len(results) or not all(is_sub(m, g, r)
                                                      for g, r in zip(stack, results)):
                raise VerifyError("stack does not match the function's results at return",
                                  fidx, ins.pc)
            stack.clear()
            reachable = False
        elif n in ("call", "call_virtual", "call_interface"):
            if n == "call_interface":
                t, k = ins.imms
                if t >= len(m.types) or not isinstance(m.types[t], InterfaceType):
                    raise VerifyError(f"call_interface: type {t} is not an interface", fidx,
                                      ins.pc)
                if k >= len(m.types[t].methods):
                    raise VerifyError(f"call_interface: interface {t} has no method {k}", fidx,
                                      ins.pc)
                ft = m.types[t].methods[k]
                if ft >= len(m.types) or not isinstance(m.types[ft], tuple):
                    raise VerifyError(f"call_interface: bad function type {ft}", fidx, ins.pc)
                for vt in reversed(m.types[ft][0]):
                    pop(vt, ins)
                pop(Ref(t), ins)
                stack.extend(m.types[ft][1])
            elif n == "call":
                callee = ins.imms[0]
                if callee >= len(m.imports) + len(m.funcs):
                    raise VerifyError(f"call to unknown function {callee}", fidx, ins.pc)
            else:
                t, slot = ins.imms
                if t >= len(m.types) or not isinstance(m.types[t], ClassType):
                    raise VerifyError(f"call_virtual: type {t} is not a class type", fidx, ins.pc)
                if slot >= len(m.types[t].vtable):
                    raise VerifyError(f"call_virtual: class type {t} has no slot {slot}",
                                      fidx, ins.pc)
                callee = m.types[t].vtable[slot]
            if n != "call_interface":
                cp, cr, cflags = m.func_type(callee)
            else:
                cp, cr, cflags = [], [], 0         # done above; implementations are not latent
            if n == "call_virtual":
                cp = [Ref(t)] + list(cp[1:])      # the receiver is typed by the class named
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
            if isinstance(b, Ref) or b == ANYREF:      # two references: their common type
                a = pop(None, ins)
                if not (isinstance(a, Ref) or a == ANYREF):
                    raise VerifyError("select: a reference and a non-reference", fidx, ins.pc)
                stack.append(common_ref(m, a, b))
            else:
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
        elif n == "struct.new":
            ref, fields = struct_type(ins)
            for t in reversed(fields):
                pop(t, ins)
            stack.append(ref)
        elif n == "struct.get":
            ref, fields = struct_type(ins)
            pop(ref, ins)
            stack.append(fields[ins.imms[1]])
        elif n == "struct.with":
            ref, fields = struct_type(ins)
            pop(fields[ins.imms[1]], ins)
            pop(ref, ins)
            stack.append(ref)
        elif n.startswith("map."):
            ref, e = container_type(ins, MapType)
            k, v = e.key, e.value
            ops = {"map.new": ([], [ref]), "map.find": ([ref, k], [v, I32]),
                   "map.set": ([ref, k, v], [ref]), "map.remove": ([ref, k], [ref, I32]),
                   "map.has": ([ref, k], [I32]), "map.len": ([ref], [I32]),
                   "map.key_at": ([ref, I32], [k]), "map.value_at": ([ref, I32], [v]),
                   "map.clear": ([ref], [ref])}
            ins_, outs = ops[n]
            for t in reversed(ins_):
                pop(t, ins)
            stack.extend(outs)
        elif n.startswith("set."):
            ref, e = container_type(ins, SetType)
            el = e.elem
            ops = {"set.new": ([], [ref]), "set.add": ([ref, el], [ref, I32]),
                   "set.remove": ([ref, el], [ref, I32]), "set.has": ([ref, el], [I32]),
                   "set.len": ([ref], [I32]), "set.at": ([ref, I32], [el]),
                   "set.clear": ([ref], [ref])}
            ins_, outs = ops[n]
            for t in reversed(ins_):
                pop(t, ins)
            stack.extend(outs)
        elif n.startswith("class.") or n in ("ref.null", "ref.cast", "ref.test"):
            t = ins.imms[0]
            kinds = (ClassType,) if n.startswith("class.") else (ClassType, InterfaceType)
            if t >= len(m.types) or not isinstance(m.types[t], kinds):
                raise VerifyError(f"{n}: type {t} is not a class type", fidx, ins.pc)
            if n == "class.new":
                stack.append(Ref(t))
            elif n == "ref.null":
                stack.append(Ref(t))
            elif n in ("class.get", "class.set"):
                fields = class_fields(m, t)
                if ins.imms[1] >= len(fields):
                    raise VerifyError(f"{n}: class type {t} has no field {ins.imms[1]}",
                                      fidx, ins.pc)
                if n == "class.set":
                    pop(fields[ins.imms[1]], ins)
                pop(Ref(t), ins)
                if n == "class.get":
                    stack.append(fields[ins.imms[1]])
            else:                                  # ref.cast, ref.test
                pop(ANYREF, ins)
                stack.append(Ref(t) if n == "ref.cast" else I32)
        elif n == "ref.share":
            got = pop(None, ins)
            if not (isinstance(got, Ref) and got.type < len(m.types)
                    and isinstance(m.types[got.type], (ArrayType, MapType, SetType))):
                raise VerifyError("ref.share needs an array, a map or a set", fidx, ins.pc)
            stack.append(got)
        elif n in ("ref.is_null", "ref.valid"):
            pop(ANYREF, ins)
            stack.append(I32)
        elif n == "ref.eq":
            pop(ANYREF, ins)
            pop(ANYREF, ins)
            stack.append(I32)
        elif n == "delegate.new":
            fi, fl = ins.imms
            if fi >= len(m.imports) + len(m.funcs):
                raise VerifyError(f"delegate.new: unknown function {fi}", fidx, ins.pc)
            if fl & ~3 or (fl & 2 and not fl & 1):
                raise VerifyError(f"delegate.new: bad flags {fl}", fidx, ins.pc)
            cp, cr, cflags = m.func_type(fi)
            if cflags & FN_LATENT and not cflags & FN_EVENT:
                raise VerifyError("delegate.new: a latent function that is not an event", fidx,
                                  ins.pc)
            if fl & 1:
                if not cp:
                    raise VerifyError("delegate.new binds a receiver to a function with no "
                                      "parameters", fidx, ins.pc)
                pop(cp[0], ins)
                cp = cp[1:]
            want = (list(cp), list(cr))
            dt = next((t for t, e in enumerate(m.types) if isinstance(e, DelegateType)
                       and is_func_type(m, e.functype)
                       and (list(m.types[e.functype][0]), list(m.types[e.functype][1])) == want),
                      None)
            if dt is None:
                raise VerifyError("delegate.new: the module has no delegate type for this "
                                  "function", fidx, ins.pc)
            stack.append(Ref(dt))
        elif n in ("call_delegate", "dispatcher.bind", "dispatcher.unbind",
                   "dispatcher.broadcast"):
            t = ins.imms[0]
            if n == "call_delegate":
                if not is_func_type(m, t):
                    raise VerifyError(f"call_delegate: type {t} is not a function type", fidx,
                                      ins.pc)
                ft = m.types[t]
            else:
                if t >= len(m.types) or not isinstance(m.types[t], DispatcherType):
                    raise VerifyError(f"{n}: type {t} is not a dispatcher type", fidx, ins.pc)
                ft = m.types[m.types[t].functype]

            def same_delegate(vt):
                e = m.types[vt.type] if isinstance(vt, Ref) and vt.type < len(m.types) else None
                return (isinstance(e, DelegateType)
                        and (list(m.types[e.functype][0]), list(m.types[e.functype][1]))
                        == (list(ft[0]), list(ft[1])))
            if n in ("call_delegate", "dispatcher.broadcast"):
                for vt in reversed(ft[0]):
                    pop(vt, ins)
            if n != "dispatcher.broadcast":
                got = pop(None, ins)
                if not same_delegate(got):
                    raise VerifyError(f"{n}: expected a delegate of type {t}, found "
                                      f"{vt_name(got, m.types)}", fidx, ins.pc)
            if n != "call_delegate":
                pop(Ref(t), ins)
            if n == "call_delegate":
                stack.extend(ft[1])
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
