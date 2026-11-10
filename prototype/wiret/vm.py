"""Reference VM: loads, verifies, links and interprets WBC modules (spec sections 5 and 6).

This is the Python stand-in for `libwiret`. It follows the C API's model loosely:
`VM.load` is `wr_load` (decode, verify, link), `VM.call` is `wr_push_func` + `wr_call`,
faults carry a node-level traceback (section 6.9) and execution is bounded by fuel (5.7).
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import lanes, wbc
from .natives import CArray, CMap, NO_FAULT, FaultValue, NativeFault, NativeSpec, Signal, _f32, all_natives
from .verifier import VerifyError, verify
from .wbc import (F32, F64, FAULT, I32, I64, SIGNAL, STRING, OPS, ArrayType, ClassType,
                  DelegateType, DispatcherType, InterfaceType, MapType,
                  Ref, SetType, StructType, WbcError)

STATUS_OK = "WR_OK"
STATUS_FAULT = "WR_ERR_FAULT"
STATUS_FUEL = "WR_ERR_FUEL"
STATUS_LOAD = "WR_ERR_LOAD"
STATUS_VERIFY = "WR_ERR_VERIFY"
STATUS_LINK = "WR_ERR_LINK"
STATUS_API = "WR_ERR_API"
STATUS_INTERRUPT = "WR_ERR_INTERRUPT"
STATUS_YIELD = "WR_YIELD"

# wr_FiberStatus (section 6.4)
FIBER_READY, FIBER_RUNNING, FIBER_SUSPENDED, FIBER_DONE, FIBER_FAULTED = (
    "READY", "RUNNING", "SUSPENDED", "DONE", "FAULTED")

VT_OF = {"bool": I32, "i8": I32, "u8": I32, "i16": I32, "u16": I32, "i32": I32, "u32": I32,
         "i64": I64, "u64": I64, "f32": F32, "f64": F64, "string": STRING,
         "anyref": wbc.ANYREF, "fault": FAULT, "std.Signal": SIGNAL,
         **{name: vt for vt, name in wbc.LANE_VTS.items()}}

MAX_FRAMES = 2000
MAX_CONT = 10000


# Codes of the built-in faults (section 4.6). `Throw` codes are the program's own; the
# built-in ones are negative so that they never collide with a non-negative code.
FAULT_DIVIDE = -1        # integer divide or remainder by zero
FAULT_RANGE = -2         # index out of range, negative array length
FAULT_NULL = -3          # null reference
FAULT_CAST = -4          # failed ref.cast
FAULT_STACK = -5         # call stack or continuation stack overflow
FAULT_NATIVE = -6        # an error returned by a native
FAULT_UNREACHABLE = -7   # unreachable executed


class Fault(Exception):
    """A runtime fault raised inside Wiret code. Catchable by `Try` (section 4.6)."""

    def __init__(self, message: str, code: int = FAULT_NATIVE):
        super().__init__(message)
        self.message = message
        self.code = code


class WiretError(Exception):
    def __init__(self, status: str, message: str, traceback=None, code: int = 0):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code                   # an uncaught fault's code (wr_FaultInfo.code)
        self.traceback = traceback or []   # [(function, node id)], innermost last

    def __str__(self):
        s = f"{self.status}: {self.message}"
        for fn, node in self.traceback:
            s += f"\n  at {fn}" + (f" node {node}" if node else "")
        return s


# -- integer and float helpers ---------------------------------------------------------
def i32(x):
    return ((x + 0x80000000) & 0xFFFFFFFF) - 0x80000000


def u32(x):
    return x & 0xFFFFFFFF


def i64(x):
    return ((x + 0x8000000000000000) & 0xFFFFFFFFFFFFFFFF) - 0x8000000000000000


def u64(x):
    return x & 0xFFFFFFFFFFFFFFFF


def _div_s(wrap, lo):
    def div(a, b):
        if b == 0:
            raise Fault("integer divide by zero", FAULT_DIVIDE)
        if a == lo and b == -1:
            return lo
        q = abs(a) // abs(b)
        return wrap(q if (a < 0) == (b < 0) else -q)
    return div


def _rem_s(wrap, lo):
    def rem(a, b):
        if b == 0:
            raise Fault("integer remainder by zero", FAULT_DIVIDE)
        if a == lo and b == -1:
            return 0
        q = abs(a) // abs(b)
        q = q if (a < 0) == (b < 0) else -q
        return wrap(a - b * q)
    return rem


def _div_u(wrap, unsigned):
    def div(a, b):
        if b == 0:
            raise Fault("integer divide by zero", FAULT_DIVIDE)
        return wrap(unsigned(a) // unsigned(b))
    return div


def _rem_u(wrap, unsigned):
    def rem(a, b):
        if b == 0:
            raise Fault("integer remainder by zero", FAULT_DIVIDE)
        return wrap(unsigned(a) % unsigned(b))
    return rem


def _fdiv(a, b):
    if b == 0:
        if a == 0 or math.isnan(a):
            return math.nan
        return math.copysign(math.inf, a) * math.copysign(1.0, b)
    return a / b


def _fmin(a, b):
    if math.isnan(a) or math.isnan(b):
        return math.nan
    if a == 0 and b == 0:
        return -0.0 if (math.copysign(1, a) < 0 or math.copysign(1, b) < 0) else 0.0
    return min(a, b)


def _fmax(a, b):
    if math.isnan(a) or math.isnan(b):
        return math.nan
    if a == 0 and b == 0:
        return 0.0 if (math.copysign(1, a) > 0 or math.copysign(1, b) > 0) else -0.0
    return max(a, b)


def _keep_sign(fn):
    def f(x):
        if math.isnan(x) or math.isinf(x):
            return x
        r = float(fn(x))
        return math.copysign(r, x) if r == 0 else r
    return f


def _sqrt(x):
    if math.isnan(x) or x < 0:
        return math.nan if x != 0 else x
    return math.sqrt(x)


def _int_to_f32(n: int) -> float:
    """An integer rounded once to the nearest binary32, ties to even (section 4.10). Going
    through binary64 first would round twice, and some 64-bit integers would end up one f32
    step away from the right value."""
    a = abs(n)
    if a < 1 << 24:
        return float(n)
    shift = a.bit_length() - 24
    q, r = a >> shift, a & ((1 << shift) - 1)
    half = 1 << (shift - 1)
    if r > half or (r == half and q & 1):
        q += 1
    return _f32(math.copysign(float(q << shift), n))


CANONICAL_NAN32 = 0x7FC00000                     # the quiet NaN of section 4.10, as bits


def _reinterpret_to_int(src_fmt, dst_fmt, canonical):
    """f32 or f64 bits as an integer. Every NaN gives the canonical quiet NaN's bits, so NaN
    payloads and signs are never observable (section 4.10)."""
    def f(a):
        if a != a:
            return canonical
        return struct.unpack(dst_fmt, struct.pack(src_fmt, a))[0]
    return f


def _trunc_sat(lo, hi, wrap):
    def f(x):
        if math.isnan(x):
            return 0
        if x <= lo:
            return wrap(lo)
        if x >= hi:
            return wrap(hi)
        return wrap(int(x))
    return f


def _build_numeric():
    t = {}

    def ints(prefix, wrap, unsigned, bits, lo):
        mask = bits - 1
        ops = {
            "eqz": (1, lambda a: int(a == 0)), "eq": (2, lambda a, b: int(a == b)),
            "ne": (2, lambda a, b: int(a != b)),
            "lt_s": (2, lambda a, b: int(a < b)), "lt_u": (2, lambda a, b: int(unsigned(a) < unsigned(b))),
            "gt_s": (2, lambda a, b: int(a > b)), "gt_u": (2, lambda a, b: int(unsigned(a) > unsigned(b))),
            "le_s": (2, lambda a, b: int(a <= b)), "le_u": (2, lambda a, b: int(unsigned(a) <= unsigned(b))),
            "ge_s": (2, lambda a, b: int(a >= b)), "ge_u": (2, lambda a, b: int(unsigned(a) >= unsigned(b))),
            "add": (2, lambda a, b: wrap(a + b)), "sub": (2, lambda a, b: wrap(a - b)),
            "mul": (2, lambda a, b: wrap(a * b)),
            "div_s": (2, _div_s(wrap, lo)), "div_u": (2, _div_u(wrap, unsigned)),
            "rem_s": (2, _rem_s(wrap, lo)), "rem_u": (2, _rem_u(wrap, unsigned)),
            "and": (2, lambda a, b: a & b), "or": (2, lambda a, b: a | b),
            "xor": (2, lambda a, b: a ^ b),
            "shl": (2, lambda a, b: wrap(a << (b & mask))),
            "shr_s": (2, lambda a, b: a >> (b & mask)),
            "shr_u": (2, lambda a, b: wrap(unsigned(a) >> (b & mask))),
            "neg": (1, lambda a: wrap(-a)), "not": (1, lambda a: wrap(~a)),
            "extend8_s": (1, lambda a: ((a & 0xFF) ^ 0x80) - 0x80),
            "extend16_s": (1, lambda a: ((a & 0xFFFF) ^ 0x8000) - 0x8000),
            "extend32_s": (1, lambda a: i32(a)),
        }
        for name, v in ops.items():
            key = f"{prefix}.{name}"
            if key in OPS:
                t[OPS[key][0]] = v

    ints("i32", i32, u32, 32, -2**31)
    ints("i64", i64, u64, 64, -2**63)

    for prefix, r in (("f32", _f32), ("f64", float)):
        ops = {
            "eq": (2, lambda a, b: int(a == b)), "ne": (2, lambda a, b: int(a != b)),
            "lt": (2, lambda a, b: int(a < b)), "gt": (2, lambda a, b: int(a > b)),
            "le": (2, lambda a, b: int(a <= b)), "ge": (2, lambda a, b: int(a >= b)),
            "add": (2, lambda a, b, r=r: r(a + b)), "sub": (2, lambda a, b, r=r: r(a - b)),
            "mul": (2, lambda a, b, r=r: r(a * b)), "div": (2, lambda a, b, r=r: r(_fdiv(a, b))),
            "min": (2, _fmin), "max": (2, _fmax),
            "neg": (1, lambda a: -a), "abs": (1, abs),
            "sqrt": (1, lambda a, r=r: r(_sqrt(a))),
            "ceil": (1, _keep_sign(math.ceil)), "floor": (1, _keep_sign(math.floor)),
            "trunc": (1, _keep_sign(math.trunc)), "nearest": (1, _keep_sign(round)),
            "copysign": (2, math.copysign),
        }
        for name, v in ops.items():
            t[OPS[f"{prefix}.{name}"][0]] = v

    def reinterp(src_fmt, dst_fmt):
        return lambda a: struct.unpack(dst_fmt, struct.pack(src_fmt, a))[0]

    conv = {
        "i32.wrap_i64": i32, "i64.extend_i32_s": lambda a: a, "i64.extend_i32_u": u32,
        "i32.trunc_f32_s": _trunc_sat(-2**31, 2**31 - 1, i32),
        "i32.trunc_f32_u": _trunc_sat(0, 2**32 - 1, i32),
        "i32.trunc_f64_s": _trunc_sat(-2**31, 2**31 - 1, i32),
        "i32.trunc_f64_u": _trunc_sat(0, 2**32 - 1, i32),
        "i64.trunc_f32_s": _trunc_sat(-2**63, 2**63 - 1, i64),
        "i64.trunc_f32_u": _trunc_sat(0, 2**64 - 1, i64),
        "i64.trunc_f64_s": _trunc_sat(-2**63, 2**63 - 1, i64),
        "i64.trunc_f64_u": _trunc_sat(0, 2**64 - 1, i64),
        "f32.convert_i32_s": _int_to_f32, "f32.convert_i32_u": lambda a: _int_to_f32(u32(a)),
        "f32.convert_i64_s": _int_to_f32, "f32.convert_i64_u": lambda a: _int_to_f32(u64(a)),
        "f64.convert_i32_s": float, "f64.convert_i32_u": lambda a: float(u32(a)),
        "f64.convert_i64_s": float, "f64.convert_i64_u": lambda a: float(u64(a)),
        "f32.demote_f64": _f32, "f64.promote_f32": float,
        "i32.reinterpret_f32": _reinterpret_to_int("<f", "<i", CANONICAL_NAN32),
        "i64.reinterpret_f64": _reinterpret_to_int("<d", "<q", 0x7FF8000000000000),
        "f32.reinterpret_i32": reinterp("<i", "<f"), "f64.reinterpret_i64": reinterp("<q", "<d"),
    }
    for name, fn in conv.items():
        t[OPS[name][0]] = (1, fn)
    t[OPS["string.concat"][0]] = (2, lambda a, b: a + b)
    t[OPS["string.len"][0]] = (1, lambda a: len(a.encode()))
    t[OPS["string.eq"][0]] = (2, lambda a, b: int(a == b))
    t[OPS["string.cmp"][0]] = (2, lambda a, b: (a.encode() > b.encode()) - (a.encode() < b.encode()))
    return t


NUMERIC = _build_numeric()

(OP_UNREACHABLE, OP_NOP, OP_BR, OP_BR_IF, OP_RETURN, OP_CALL, OP_CONT_PUSH, OP_CONT_POP,
 OP_DROP, OP_SELECT, OP_LGET, OP_LSET, OP_LTEE, OP_GGET, OP_GSET, OP_CONST) = (
    0x00, 0x01, 0x02, 0x03, 0x05, 0x06, 0x0A, 0x0B, 0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x20)
OP_TRY_PUSH, OP_SUSPEND, OP_THROW = 0x0C, 0x0D, 0x0E
OP_CONT_DEPTH, OP_CONT_TRUNC = 0x17, 0x18   # 0x0F is brk, reserved
OP_CALL_VIRTUAL, OP_CALL_INTERFACE, OP_CALL_DELEGATE = 0x07, 0x08, 0x09
OP_DELEGATE_NEW, OP_BIND, OP_UNBIND, OP_BROADCAST = 0xF4, 0xF5, 0xF6, 0xF7
OP_REF_NULL, OP_REF_IS_NULL, OP_REF_EQ, OP_REF_CAST, OP_REF_TEST, OP_REF_VALID = range(0x25, 0x2B)
OP_CLASS_NEW, OP_CLASS_GET, OP_CLASS_SET = 0xD3, 0xD4, 0xD5
OP_REF_SHARE = 0x2B
_CONST_OPS = {0x20, 0x21, 0x22, 0x23}


class ClassInfo:
    """A loaded class type: its name, field layout and defaults, vtable and ancestors."""
    __slots__ = ("index", "name", "field_names", "defaults", "vtable", "ancestors", "itables",
                 "dispatchers", "overrides")

    def __init__(self, index, name, field_names, defaults, vtable, ancestors, itables=None,
                 dispatchers=(), overrides=None):
        self.index, self.name, self.field_names = index, name, field_names
        self.defaults, self.vtable, self.ancestors = defaults, vtable, ancestors
        self.itables = itables or {}     # interface type index -> [function index per method]
        self.dispatchers = dispatchers   # layout slots holding a dispatcher (one per object)
        self.overrides = overrides or {} # a base's function index -> this class's override


class Delegate:
    """A function plus, when `bound`, its receiver (section 3.1). Two delegates are equal when
    they name the same function and the same receiver object, which is what Unbind matches."""
    __slots__ = ("func", "recv", "bound")

    def __init__(self, func: int, recv=None, bound=False):
        self.func, self.recv, self.bound = func, recv, bound

    def __eq__(self, other):
        return (isinstance(other, Delegate) and self.func == other.func
                and self.bound == other.bound and self.recv is other.recv)

    def __hash__(self):
        return hash((self.func, id(self.recv)))

    def __repr__(self):
        return f"<delegate func {self.func}{' bound' if self.bound else ''}>"


class DispatcherObj:
    """A dispatcher member of one object: its handlers in bind order."""
    __slots__ = ("handlers",)

    def __init__(self):
        self.handlers = []

    def __repr__(self):
        return f"<dispatcher, {len(self.handlers)} bound>"


class Obj:
    """A class instance (section 3.1): a reference with identity, so `Eq` is `is`."""
    __slots__ = ("cls", "fields")

    def __init__(self, cls: ClassInfo):
        self.cls = cls
        self.fields = list(cls.defaults)
        for i in cls.dispatchers:        # every object has dispatchers of its own, empty
            self.fields[i] = DispatcherObj()

    def get(self, name: str):
        return self.fields[self.cls.field_names.index(name)]

    def set(self, name: str, value):
        self.fields[self.cls.field_names.index(name)] = value

    def __repr__(self):
        return f"<{self.cls.name} {id(self):x}>"


def normalise(vt, v, types=None):
    if isinstance(vt, Ref):
        entry = types[vt.type] if types is not None else None
        if isinstance(entry, (ClassType, InterfaceType, DelegateType, DispatcherType)) or \
                isinstance(v, (Obj, Delegate)) or v is None:
            return v
        if isinstance(entry, StructType):
            return tuple(normalise(fvt, x, types) for (fvt, _), x in zip(entry.fields, v))
        if isinstance(entry, MapType):
            return CMap({_key(normalise(entry.key, k, types)): normalise(entry.value, x, types)
                         for k, x in dict(v).items()})
        if isinstance(entry, SetType):
            return CMap({_key(normalise(entry.elem, k, types)): None for k in v})
        if entry is None and isinstance(v, dict):          # a native's result, untyped
            return CMap(v)                                 # its own: never the native's
        elem = entry.elem if isinstance(entry, ArrayType) else None
        return CArray(normalise(elem, x, types) if elem is not None else x for x in v)
    if vt == I32:
        return i32(int(v))
    if vt == I64:
        return i64(int(v))
    if vt == F32:
        return _f32(float(v))
    if vt == F64:
        return float(v)
    if vt == FAULT or vt == SIGNAL:
        return v
    if vt in wbc.LANE_VTS:              # a lane value: f32 components, as tuples
        return lanes.normalise(wbc.LANE_VTS[vt], v)
    return str(v)


ZERO = {I32: 0, I64: 0, F32: 0.0, F64: 0.0, STRING: "", FAULT: NO_FAULT, SIGNAL: None,
        wbc.ANYREF: None}
# A lane type's zero value is its default: the identity for quat and transform (3.1.1).
ZERO.update({vt: lanes.DEFAULTS[name] for vt, name in wbc.LANE_VTS.items()})


def export(v):
    """A value as the host sees it: arrays as tuples, maps and sets as dicts, at any depth
    (inside structs too). Objects, delegates and signals stay what they are."""
    if isinstance(v, CArray):
        return tuple(export(x) for x in v)
    if isinstance(v, CMap):
        return {k: export(x) for k, x in v.items()}
    if type(v) is tuple:
        return tuple(export(x) for x in v)
    return v


def zero(vt):
    """Zero value of a value type. A zero container is shared by every holder, so it is marked
    shared and the first change to it makes a copy (section 4.9)."""
    return CArray(shared=True) if isinstance(vt, Ref) else ZERO[vt]


NAN_KEY = float("nan")


def _key(k):
    """A map key or set item as stored. Every NaN is the same key (one canonical NaN object,
    so lookups find it), also inside a struct key; any other key is used as it is."""
    if isinstance(k, float) and k != k:
        return NAN_KEY
    if isinstance(k, tuple):
        return tuple(_key(x) for x in k)
    return k


def own(c, alloc):
    """Copy-on-write (section 4.9): the container itself when it is unshared, else a fresh
    unshared copy, whose size is charged as an allocation."""
    if not c.shared:
        return c
    alloc[0] += len(c)
    return type(c)(c)


def _container_ops(default, alloc) -> dict:
    """Map and set instructions (section 5.6) as (function, operand count). A map is a CMap
    and a set a CMap of None values; both keep insertion order. A change happens in place
    when the container is unshared, else on a copy (section 4.9)."""
    def at(c, i):
        if not 0 <= i < len(c):
            raise Fault(f"index {i} is out of range (length {len(c)})", FAULT_RANGE)
        return i

    def map_ops(entry):
        zero_v = default(entry.value)

        def find(m, k):
            k = _key(k)
            return [m[k], 1] if k in m else [zero_v, 0]

        def set_(m, k, v):
            n = own(m, alloc)
            n[_key(k)] = v
            return [n]

        def remove(m, k):
            k = _key(k)
            if k not in m:
                return [m, 0]
            n = own(m, alloc)
            del n[k]
            return [n, 1]
        return {"map.new": (lambda: [CMap()], 0), "map.find": (find, 2), "map.set": (set_, 3),
                "map.remove": (remove, 2), "map.has": (lambda m, k: [int(_key(k) in m)], 2),
                "map.len": (lambda m: [len(m)], 1),
                "map.key_at": (lambda m, i: [list(m)[at(m, i)]], 2),
                "map.value_at": (lambda m, i: [list(m.values())[at(m, i)]], 2),
                "map.clear": (lambda m: [CMap()], 1)}

    def set_ops(entry):
        def add(st, v):
            v = _key(v)
            if v in st:
                return [st, 0]
            n = own(st, alloc)
            n[v] = None
            return [n, 1]

        def remove(st, v):
            v = _key(v)
            if v not in st:
                return [st, 0]
            n = own(st, alloc)
            del n[v]
            return [n, 1]
        return {"set.new": (lambda: [CMap()], 0), "set.add": (add, 2), "set.remove": (remove, 2),
                "set.has": (lambda st, v: [int(_key(v) in st)], 2),
                "set.len": (lambda st: [len(st)], 1),
                "set.at": (lambda st, i: [list(st)[at(st, i)]], 2),
                "set.clear": (lambda st: [CMap()], 1)}

    cache = {}

    def ops(entry, name):
        """(function, operand count)."""
        if id(entry) not in cache:
            cache[id(entry)] = map_ops(entry) if isinstance(entry, MapType) else set_ops(entry)
        return cache[id(entry)][name]
    return ops


def default_values(types: list, data: list):
    """The default value of each value type, for locals, globals and new array elements.

    A struct is an immutable tuple of its fields. Its default holds each field's declared
    default, else that field's default (section 5.3). The verifier has checked that structs
    do not hold themselves by value, so the recursion ends."""
    cache = {}

    def default(vt):
        if not isinstance(vt, Ref):
            return ZERO[vt]
        entry = types[vt.type]
        if isinstance(entry, (ClassType, InterfaceType, DelegateType, DispatcherType)):
            return None                # a reference starts null
        if isinstance(entry, (MapType, SetType)):
            return CMap(shared=True)   # a default many holders start from: copied on change
        if not isinstance(entry, StructType):
            return CArray(shared=True)
        if vt.type not in cache:
            cache[vt.type] = tuple(
                default(fvt) if d is None else data[d] if fvt == STRING else d
                for fvt, d in entry.fields)
        return cache[vt.type]
    return default


def _array_ops(types: list, default=zero, alloc=None) -> dict:
    """Array instructions (section 5.6). An array is a CArray: a list with a `shared` flag. A
    mutator changes an unshared array in place and returns it, or changes and returns a fresh
    copy of a shared one; `array.new`, `array.clone` and every mutator's result are unshared
    (section 4.9). `alloc[0]` counts elements allocated, for fuel."""
    alloc = alloc if alloc is not None else [0]

    def check(a, i, extra=0):
        if not 0 <= i < len(a) + extra:
            raise Fault(f"array index {i} is out of range (length {len(a)})", FAULT_RANGE)

    def new(elem_vt):
        z = default(elem_vt)

        def f(n):
            if n < 0:
                raise Fault(f"array length {n} is negative", FAULT_RANGE)
            alloc[0] += n
            return CArray([z] * n)
        return f

    def get(a, i):
        check(a, i)
        return a[i]

    def set_(a, i, v):
        check(a, i)
        a = own(a, alloc)
        a[i] = v
        return a

    def push(a, v):
        a = own(a, alloc)
        a.append(v)
        return a

    def insert(a, i, v):
        check(a, i, extra=1)
        a = own(a, alloc)
        a.insert(i, v)
        return a

    def remove(a, i):
        check(a, i)
        a = own(a, alloc)
        del a[i]
        return a

    def clone(a):
        alloc[0] += len(a)
        return CArray(a)

    return {"new": new, "get": get, "set": set_, "push": push, "insert": insert,
            "remove": remove, "clear": lambda a: CArray(), "clone": clone}


ARRAY_ARITY = {0xD6: 1, 0xD7: 1, 0xD8: 2, 0xD9: 3, 0xDA: 2, 0xDB: 3, 0xDC: 2, 0xDD: 1, 0xDE: 1}


@dataclass
class Func:
    index: int
    name: str
    params: list
    results: list
    flags: int
    native: Optional[Callable] = None
    native_name: str = ""
    cost: Optional[Callable] = None                # a native's declared extra fuel
    locals: list = field(default_factory=list)
    zeros: list = field(default_factory=list)      # the starting value of each local
    code: list = field(default_factory=list)       # [(op, arg)]
    pcs: list = field(default_factory=list)        # instruction index -> byte pc
    node_at: list = field(default_factory=list)    # instruction index -> node id
    fault_at: list = field(default_factory=list)   # the same, refined to pure nodes (wr.pure)
    starts: dict = field(default_factory=dict)     # instruction index -> node ids starting there
    local_names: dict = field(default_factory=dict)  # local index -> name
    pins: list = field(default_factory=list)       # [(local index, node id, pin)] from wr.pins
    steps: dict = field(default_factory=dict)      # instruction index -> node id (wr.steps)


@dataclass
class FrameView:
    func: Func
    node: Optional[str]
    locals: list

    def pin_values(self) -> dict:
        """(node id, pin) -> value for every pin kept in a local (wr.pins)."""
        return {(node, pin): self.locals[li] for li, node, pin in self.func.pins}

    def named_locals(self) -> dict:
        return {name: self.locals[li] for li, name in self.func.local_names.items()
                if li < len(self.locals)}


@dataclass(eq=False)
class Fiber:
    """One thread of execution with its own frames (section 4.5). A fiber runs one call; a
    latent one suspends at `Delay`, `Yield` and `Await` and is resumed by the scheduler."""
    id: int
    mod: "LoadedModule"
    name: str
    status: str = FIBER_READY
    results: Optional[list] = None
    error: Optional["WiretError"] = None
    wake: float = 0.0               # virtual time at which it became, or becomes, runnable
    waiting: Optional[str] = None   # "time", "yield" or "signal" while suspended
    signal: Optional[Signal] = None
    # saved machine state: current function, ip, locals, operand stack, continuation stack,
    # and the frames beneath it
    f: Optional["Func"] = None
    ip: int = 0
    locs: list = field(default_factory=list)
    stack: list = field(default_factory=list)
    cont: list = field(default_factory=list)
    frames: list = field(default_factory=list)


@dataclass
class LoadedModule:
    wbc: wbc.WbcModule
    name: str
    funcs: list
    exports: dict
    globals: list
    data: list
    meta: dict
    local_names: dict
    global_names: dict = field(default_factory=dict)   # name -> global index
    classes: dict = field(default_factory=dict)        # class name -> ClassInfo
    capabilities: list = field(default_factory=list)   # wr.caps
    declared: set = field(default_factory=set)         # exports marked @export (flag bit 3)


def parse_pins(m: wbc.WbcModule, debug: dict) -> dict:
    """wr.pins: function index -> [(local, node id, pin name)]."""
    out = {}
    p = m.custom("wr.pins")
    if not p:
        return out
    r = wbc.Reader(p)
    for _ in range(r.u32()):
        fi = r.u32()
        table = debug.get(fi, (None, [], []))[2]
        entries = []
        for _ in range(r.u32()):
            li, ni, pi = r.u32(), r.u32(), r.u32()
            if ni >= len(table) or pi >= len(table):
                raise WbcError("wr.pins index out of range")
            entries.append((li, table[ni], table[pi]))
        out[fi] = entries
    return out


def parse_steps(m: wbc.WbcModule, debug: dict, section: str = "wr.steps") -> dict:
    """wr.steps (debug builds): function index -> [(pc, node id)] where a node's inputs are
    evaluated and it is about to act. wr.pure has the same layout: the pcs where code for a
    pure node starts, and where code for the enclosing node resumes."""
    out = {}
    p = m.custom(section)
    if not p:
        return out
    r = wbc.Reader(p)
    for _ in range(r.u32()):
        fi = r.u32()
        table = debug.get(fi, (None, [], []))[2]
        entries, pc = [], 0
        for _ in range(r.u32()):
            pc += r.u32()
            ni = r.u32()
            if ni >= len(table):
                raise WbcError(f"{section} index out of range")
            entries.append((pc, table[ni]))
        out[fi] = entries
    return out


def parse_global_names(m: wbc.WbcModule) -> dict:
    p = m.custom("name")
    out = {}
    if not p:
        return out
    try:
        r = wbc.Reader(p)
        for _ in range(r.u32()):
            r.u32(), r.name()
        for _ in range(r.u32()):
            r.u32()
            for _ in range(r.u32()):
                r.u32(), r.name()
        for _ in range(r.u32()):
            gi = r.u32()
            out[r.name()] = gi
    except WbcError:
        return {}
    return out


def parse_caps(m: wbc.WbcModule) -> list:
    """wr.caps: the capabilities the module declares it needs, `vec(name)`."""
    p = m.custom("wr.caps")
    if not p:
        return []
    r = wbc.Reader(p)
    return [r.name() for _ in range(r.u32())]


def module_capabilities(data: bytes) -> list:
    """wr_module_each_capability before loading: what a module asks for, read from its
    `wr.caps` without verifying or linking anything, so a host can refuse it first."""
    try:
        return parse_caps(wbc.decode_module(data))
    except (WbcError, IndexError, ValueError, struct.error) as e:
        raise WiretError(STATUS_LOAD, str(e))


def parse_customs(m: wbc.WbcModule):
    names, local_names, debug, meta = {}, {}, {}, {}
    p = m.custom("name")
    if p:
        r = wbc.Reader(p)
        for _ in range(r.u32()):
            i = r.u32()
            names[i] = r.name()
        for _ in range(r.u32()):
            fi = r.u32()
            local_names[fi] = {}
            for _ in range(r.u32()):
                li = r.u32()
                local_names[fi][li] = r.name()
        for _ in range(r.u32()):                 # globals: read by parse_global_names
            r.u32(), r.name()
        if not r.eof():                          # classes: type index, name, field names
            for _ in range(r.u32()):
                ti = r.u32()
                cname = r.name()
                meta[("class", ti)] = (cname, [r.name() for _ in range(r.u32())])
    p = m.custom("wr.debug")
    if p:
        r = wbc.Reader(p)
        for _ in range(r.u32()):
            fi = r.u32()
            graph = r.name()
            table = [r.name() for _ in range(r.u32())]
            entries, pc = [], 0
            for _ in range(r.u32()):
                pc += r.u32()
                ni = r.u32()
                if ni >= len(table):
                    raise WbcError("wr.debug node index out of range")
                entries.append((pc, table[ni]))
            debug[fi] = (graph, entries, table)
    p = m.custom("wr.meta")
    if p:
        r = wbc.Reader(p)
        keys = ["module", "id", "compiler", "registry", "semantic_hash", "layout_hash",
                "source_hash", "exports"]
        for k in keys:
            if r.eof():
                break
            meta[k] = r.name()
    return names, local_names, debug, meta


def _replace_fn(spec: NativeSpec, fn) -> NativeSpec:
    from dataclasses import replace
    return replace(spec, fn=fn)


class VM:
    def __init__(self, output: Callable[[str], None] = print, fuel: int = 50_000_000,
                 hook: Optional[Callable] = None, capabilities=None,
                 deterministic: bool = False):
        # WR_CFG_DETERMINISTIC (section 4.10): bundled std.math instead of the platform's
        # libm, no native that is not deterministic, and an input log of every API call that
        # replay() can run again and check.
        self.deterministic = deterministic
        self.sink = output
        self.output = self._emit
        self.input_log: list = []
        self._depth = 0           # API calls in progress: only the outermost is logged
        self._printed: list = []  # lines printed during the API call being logged
        self._handles: dict = {}  # id(object) -> handle number in the log
        self._handle_objs: list = []
        self.fuel_limit = fuel
        self.fuel = fuel
        # hook(function, node id, pending continuation node ids, call depth, snapshot, phase) runs
        # at the start of every node (phase "enter") and, in debug builds, again once its inputs
        # are evaluated (phase "ready"). snapshot() returns the frames for a debugger (6.10).
        self.hook = hook
        self.natives: dict[str, NativeSpec] = dict(all_natives())
        if deterministic:
            from .detmath import BUNDLED, BUNDLED2
            for q, fn in BUNDLED.items():
                self.natives[q] = _replace_fn(self.natives[q], lambda _vm, x, fn=fn: (fn(x),))
            for q, fn in BUNDLED2.items():
                self.natives[q] = _replace_fn(self.natives[q],
                                              lambda _vm, a, b, fn=fn: (fn(a, b),))
            from .detmath import acos, cos, sin
            from .natives import LANE_TRIG, _lane_natives
            bundled = _lane_natives(sin, cos, acos)
            for q in LANE_TRIG:
                self.natives[q] = bundled[q]
            self.natives = {q: s for q, s in self.natives.items() if s.deterministic}
        # Capabilities granted (wr_grant, section 6.5). This class is both libwiret and the
        # reference host: by default it grants what its own host natives need; pass a list,
        # possibly empty, for a sandbox that grants only those.
        if capabilities is None:
            capabilities = {s.capability for s in self.natives.values() if s.capability}
        self.granted: set = set(capabilities)
        self.interrupted = False
        self.stats = {"instructions": 0, "calls": 0, "replayable": True}
        self.alloc = [0]          # elements allocated by container instructions, for fuel
        # The scheduler (sections 4.5 and 6.8). Time is virtual and moves only in advance().
        self.time = 0.0
        self.fibers: list[Fiber] = []      # live fibers: ready or suspended, by creation order
        self.next_fiber = 1
        # on_fault(fiber) is told when a fiber run by the scheduler faults (wr_Config.on_fault)
        self.on_fault: Optional[Callable] = None
        # A fault in a Broadcast handler is reported here and does not stop the others (3.3)
        self.handler_faults: list = []
        self.on_handler_fault: Optional[Callable] = None

    def register(self, qname: str, spec: NativeSpec):
        """wr_register. A deterministic VM refuses a native not marked deterministic, so a
        replay cannot quietly depend on a clock or a random source (section 6.6)."""
        if self.deterministic and not spec.deterministic:
            raise WiretError(STATUS_LINK, f"{qname} is not deterministic, so a deterministic "
                                          f"VM cannot use it")
        self.natives[qname] = spec

    def _emit(self, line: str):
        if self._depth:
            self._printed.append(line)
        self.sink(line)

    def signal(self) -> Signal:
        """wr_push_signal: a new signal for the host to pass to Wiret and fire later."""
        return Signal()

    def grant(self, capability: str):
        """wr_grant: let modules loaded from now on use imports that need `capability`."""
        self.granted.add(capability)

    def interrupt(self):
        """wr_interrupt. It still stops the running fiber in deterministic mode, but the run
        can no longer be replayed: an interrupt comes from outside the input log (4.10)."""
        self.interrupted = True
        if self.deterministic:
            self.stats["replayable"] = False

    # -- loading ------------------------------------------------------------------
    def load(self, data: bytes) -> LoadedModule:
        try:
            m = wbc.decode_module(data)
        except (WbcError, IndexError, ValueError, struct.error) as e:
            raise WiretError(STATUS_LOAD, str(e))
        try:
            verified = verify(m)
        except VerifyError as e:
            raise WiretError(STATUS_VERIFY, str(e))
        try:
            caps = parse_caps(m)
        except (WbcError, IndexError, ValueError) as e:
            raise WiretError(STATUS_LOAD, f"bad custom section: {e}")
        for cap in caps:                 # what the module declares (wr.caps)
            if cap not in self.granted:
                raise WiretError(STATUS_LINK, f"the module needs capability '{cap}', which the "
                                              f"host has not granted")
        try:
            names, local_names, debug, meta = parse_customs(m)
            pins = parse_pins(m, debug)
            steps = parse_steps(m, debug)
            pure = parse_steps(m, debug, "wr.pure")
        except (WbcError, IndexError, ValueError) as e:
            raise WiretError(STATUS_LOAD, f"bad custom section: {e}")
        funcs = []
        defaults = default_values(m.types, m.data)
        classes = {}
        for ti, entry in enumerate(m.types):
            if not isinstance(entry, ClassType):
                continue
            chain, t = [], ti
            while t is not None:
                chain.append(t)
                t = m.types[t].super
            layout = [fd for c in reversed(chain) for fd in m.types[c].fields]
            cname, fnames = meta.pop(("class", ti), (f"class{ti}", []))
            if len(fnames) != len(layout):
                fnames = [f"field{i}" for i in range(len(layout))]
            vals = [defaults(vt) if d is None else m.data[d] if vt == STRING else d
                    for vt, d in layout]
            itables = {i: list(impl) for i, impl in entry.interfaces}
            # ref.test and ref.cast against an interface see the interfaces as ancestors too
            slots = [i for i, (vt, _) in enumerate(layout)
                     if isinstance(vt, Ref) and isinstance(m.types[vt.type], DispatcherType)]
            overrides = {}                   # what a method delegate on this class calls
            for a in chain[1:]:
                for s, fi in enumerate(m.types[a].vtable):
                    if s < len(entry.vtable):
                        overrides.setdefault(fi, entry.vtable[s])
            classes[ti] = ClassInfo(ti, cname, fnames, vals, list(entry.vtable),
                                    set(chain) | set(itables), itables, tuple(slots), overrides)
        alloc = self.alloc
        arrays = _array_ops(m.types, defaults, alloc)
        containers = _container_ops(defaults, alloc)
        for i, (mod, fld, t, flags) in enumerate(m.imports):
            q = f"{mod}.{fld}"
            spec = self.natives.get(q)
            params, results = m.types[t]
            if spec is None:
                raise WiretError(STATUS_LINK, f"unresolved import {q}")
            if spec.capability and spec.capability not in self.granted:
                # checked on the native as well, so leaving @capability off the extern does
                # not get around a grant
                raise WiretError(STATUS_LINK, f"import {q} needs capability "
                                              f"'{spec.capability}', which the host has not "
                                              f"granted")
            if [VT_OF[x] for _, x in spec.params] != params or \
                    [VT_OF[x] for _, x in spec.results] != results:
                raise WiretError(STATUS_LINK, f"import {q} has a different signature than the "
                                              f"registered native")
            funcs.append(Func(i, q, params, results, flags, native=spec.fn, native_name=q,
                              cost=spec.cost))
        nimp = len(m.imports)
        for i, ((t, flags), body, (instrs, _)) in enumerate(zip(m.funcs, m.bodies, verified)):
            fi = nimp + i
            params, results = m.types[t]
            f = Func(fi, names.get(fi, f"func{fi}"), params, results, flags)
            f.locals = list(body.locals)
            f.zeros = [defaults(vt) for vt in f.locals]
            index_of = {ins.pc: k for k, ins in enumerate(instrs)}
            for ins in instrs:
                if ins.name in ("br", "br_if", "cont.push"):
                    arg = index_of[ins.target()]
                elif ins.name == "try.push":
                    arg = (index_of[ins.target()], ins.imms[1])
                elif ins.op in _CONST_OPS:
                    arg = ins.imms[0]
                elif ins.name == "string.const":
                    arg = m.data[ins.imms[0]]
                elif ins.name == "array.new":
                    arg = arrays["new"](m.types[ins.imms[0]].elem)
                elif ins.name == "array.len":
                    arg = len
                elif ins.name.startswith("array."):
                    arg = arrays[ins.name[6:]]
                elif ins.name.startswith(("map.", "set.")):
                    arg = containers(m.types[ins.imms[0]], ins.name)
                elif ins.op > 0xFF:              # a lane instruction: (operands, function)
                    field = ins.imms[0] if ins.imms else 0
                    arg = (len(lanes.effect(ins.name, field)[0]),
                           lanes.function(ins.name, field))
                elif ins.name == "struct.new":
                    arg = len(m.types[ins.imms[0]].fields)
                elif ins.name in ("struct.get", "struct.with", "class.get", "class.set"):
                    arg = ins.imms[1]
                elif ins.name == "class.new":
                    arg = classes[ins.imms[0]]
                elif ins.name == "call_virtual":
                    t, slot = ins.imms
                    arg = (slot, len(m.func_type(m.types[t].vtable[slot])[0]))
                elif ins.name == "call_delegate":
                    arg = len(m.types[ins.imms[0]][0])
                elif ins.name == "dispatcher.broadcast":
                    arg = len(m.types[m.types[ins.imms[0]].functype][0])
                elif ins.name == "delegate.new":
                    arg = ins.imms
                elif ins.name == "call_interface":
                    t, k = ins.imms
                    arg = (t, k, 1 + len(m.types[m.types[t].methods[k]][0]))
                else:
                    arg = ins.imms[0] if ins.imms else None
                f.code.append((ins.op, arg))
                f.pcs.append(ins.pc)
            graph, entries, _ = debug.get(fi, (None, [], []))
            f.local_names = local_names.get(fi, {})
            f.pins = [(li, node, pin) for li, node, pin in pins.get(fi, [])
                      if li < len(params) + len(f.locals)]
            by_pc = {}
            for pc, node in entries:
                by_pc.setdefault(pc, []).append(node)
            pure_pcs = dict(pure.get(fi, []))
            cur = here = None
            for k, ins in enumerate(instrs):
                if ins.pc in by_pc:
                    cur = here = by_pc[ins.pc][-1]
                    f.starts[k] = tuple(by_pc[ins.pc])
                here = pure_pcs.get(ins.pc, here)
                f.node_at.append(cur)
                f.fault_at.append(here)
            for k, (op, arg) in enumerate(f.code):     # a marker also names its Try node
                if op == OP_TRY_PUSH:
                    f.code[k] = (op, (arg[0], arg[1], f.node_at[k]))
            step_pcs = dict(steps.get(fi, []))
            for k, ins in enumerate(instrs):
                if ins.pc in step_pcs:
                    f.steps[k] = step_pcs[ins.pc]
            funcs.append(f)
        exports = {name: index for name, kind, index, _ in m.exports if kind == 0}
        gvals = [m.data[init] if vt == STRING else defaults(vt) if isinstance(vt, Ref) else init
                 for vt, _, init in m.globals]
        return LoadedModule(m, meta.get("module", ""), funcs, exports, gvals, m.data, meta,
                            local_names, parse_global_names(m),
                            {c.name: c for c in classes.values()}, caps,
                            {name for name, _, _, flags in m.exports if flags & wbc.EX_DECLARED})

    # -- execution ----------------------------------------------------------------
    def _fiber(self, mod: LoadedModule, name: str, args: list) -> Fiber:
        if name not in mod.exports:
            raise WiretError(STATUS_LINK, f"no exported function '{name}'")
        f = mod.funcs[mod.exports[name]]
        if len(args) != len(f.params):
            raise WiretError(STATUS_API, f"'{name}' takes {len(f.params)} argument(s), "
                                         f"got {len(args)}")
        args = [normalise(vt, a, mod.wbc.types) for vt, a in zip(f.params, args)]
        fb = Fiber(self.next_fiber, mod, name, f=f, locs=args + list(f.zeros), wake=self.time)
        self.next_fiber += 1
        return fb

    def call(self, mod: LoadedModule, name: str, args: list) -> list:
        """wr_call on a function that cannot suspend: its results, or a WiretError."""
        fb = self._fiber(mod, name, args)
        if fb.f.flags & wbc.FN_LATENT:
            raise WiretError(STATUS_API, f"'{name}' is latent and may suspend; run it with "
                                         f"start() and advance()")
        self._resume(fb)
        return fb.results

    def start(self, mod: LoadedModule, name: str, args: list, now: bool = False) -> Fiber:
        """wr_start: a new fiber for `name`, queued to run on the next advance(). With
        `now`, its first segment runs at once, as wr_call does for a latent export; a fault
        in it is raised here."""
        fb = self._fiber(mod, name, args)
        self.fibers.append(fb)
        if now:
            self._resume(fb)
        return fb

    def advance(self, dt: float = 0.0) -> list:
        """wr_advance: move virtual time forward by `dt`, then run every fiber that is runnable
        at the new time, ordered by the time it became runnable, then by creation order. Each
        runs until it suspends, finishes or faults, with a fresh fuel budget. A fiber made
        runnable during this advance (a signal fired, a Yield, a zero Delay) runs on the next
        one. Returns the fibers that ran."""
        if dt < 0 or dt != dt:
            raise WiretError(STATUS_API, "advance needs a time step of 0 or more")
        self.time += dt
        due = sorted((fb for fb in self.fibers
                      if fb.status == FIBER_READY
                      or (fb.waiting == "time" and fb.wake <= self.time)),
                     key=lambda fb: (fb.wake, fb.id))
        for fb in due:
            try:
                self._resume(fb)
            except WiretError:
                if self.on_fault is not None:
                    self.on_fault(fb)
        self.fibers = [fb for fb in self.fibers
                       if fb.status in (FIBER_READY, FIBER_SUSPENDED)]
        return due

    def fire(self, signal: Signal):
        """wr_signal_fire: every fiber waiting on `signal` becomes runnable, in the order they
        began waiting. Fibers that Await it later wait for the next fire."""
        waiters, signal.waiters = signal.waiters, []
        for fb in waiters:
            fb.status, fb.waiting, fb.signal, fb.wake = FIBER_READY, None, None, self.time

    def kill(self, fb: Fiber):
        """wr_fiber_kill: end a fiber without running anything more of it."""
        if fb.signal is not None and fb in fb.signal.waiters:
            fb.signal.waiters.remove(fb)
        fb.status, fb.waiting, fb.signal = FIBER_FAULTED, None, None
        fb.error = WiretError(STATUS_FAULT, "killed by the host")

    def next_wake(self) -> Optional[float]:
        """The earliest time a Delay is waiting for, if any: lets a host skip idle time."""
        times = [fb.wake for fb in self.fibers if fb.waiting == "time"]
        return min(times) if times else None

    def new(self, mod: LoadedModule, cls: str) -> Obj:
        """An instance of `cls` with its declared defaults (wr_push_new)."""
        if cls not in mod.classes:
            raise WiretError(STATUS_LINK, f"no class '{cls}'")
        return Obj(mod.classes[cls])

    def call_method(self, mod: LoadedModule, obj: Obj, method: str, args: list) -> list:
        """wr_push_virtual + wr_call: the override of `method` for obj's class, with obj as
        self."""
        if obj is None:
            raise WiretError(STATUS_FAULT, "method call on a null object", code=FAULT_NULL)
        for fi in obj.cls.vtable:
            f = mod.funcs[fi]
            if f.name.rpartition(".")[2] == method:
                name = next((n for n, i in mod.exports.items() if i == fi), None)
                if name is not None:
                    return self.call(mod, name, [obj] + list(args))
        raise WiretError(STATUS_LINK, f"class '{obj.cls.name}' has no method '{method}'")

    def delegate(self, mod: LoadedModule, func: str, obj: Optional[Obj] = None) -> Delegate:
        """A delegate of an exported function, or of a method bound to `obj`, which the host
        can bind (`obj.get("OnHit").handlers.append(d)`) or hand to Wiret."""
        if func not in mod.exports:
            raise WiretError(STATUS_LINK, f"no exported function '{func}'")
        fi = mod.exports[func]
        if obj is not None:
            return Delegate(obj.cls.overrides.get(fi, fi), obj, True)
        return Delegate(fi)

    def broadcast(self, mod: LoadedModule, obj: Obj, dispatcher: str, args: list):
        """Broadcast an object's dispatcher from the host, as the Broadcast node does."""
        disp = obj.get(dispatcher)
        if not isinstance(disp, DispatcherObj):
            raise WiretError(STATUS_API, f"'{dispatcher}' is not a dispatcher of {obj.cls.name}")
        self.fuel = self.fuel_limit
        self._broadcast(mod, disp, list(args))

    def _spawn(self, mod: LoadedModule, f: "Func", args: list) -> Fiber:
        """An event invoked through a delegate starts on a fiber of its own, queued for the
        next advance, so invoking never waits (section 3.3)."""
        fb = Fiber(self.next_fiber, mod, f.name, f=f, locs=list(args) + list(f.zeros),
                   wake=self.time)
        self.next_fiber += 1
        self.fibers.append(fb)
        return fb

    def _broadcast(self, mod: LoadedModule, disp: DispatcherObj, args: list):
        """Run each handler bound when the broadcast starts, in bind order. A handler's fault
        is reported and the others still run; running out of fuel or an interrupt is not a
        fault and ends the broadcast."""
        for d in list(disp.handlers):
            f = mod.funcs[d.func]
            cargs = ([d.recv] if d.bound else []) + list(args)
            if f.flags & wbc.FN_LATENT:
                self._spawn(mod, f, cargs)
                continue
            sub = Fiber(0, mod, f.name, f=f, locs=cargs + list(f.zeros))
            try:
                self._run(sub)
            except WiretError as e:
                if e.status in (STATUS_FUEL, STATUS_INTERRUPT):
                    raise
                self.handler_faults.append(e)
                if self.on_handler_fault is not None:
                    self.on_handler_fault(e)

    def _resume(self, fb: Fiber):
        self.fuel = self.fuel_limit
        self.interrupted = False
        fb.status = FIBER_RUNNING
        try:
            self._run(fb)
        except WiretError as e:
            fb.status, fb.error = FIBER_FAULTED, e
            raise

    @staticmethod
    def _snapshot(frames, f, locs, node) -> list:
        """Frames from outermost to innermost, for a debugger."""
        out = []
        for fr in frames:
            ff, ip, flocs = fr[0], fr[1], fr[2]
            out.append(FrameView(ff, ff.fault_at[max(ip - 1, 0)], list(flocs)))
        out.append(FrameView(f, node, list(locs)))
        return out

    @staticmethod
    def _pending(f, cont) -> list:
        """The continuation stack as node ids, bottom first. A handler marker shows as
        `try!fault`, after the `Try` node that pushed it."""
        return [f.node_at[k] if type(k) is int else f"{k[2]}!fault" for k in cont]

    def _traceback(self, frames, mod):
        tb = []
        for fr in frames:
            f, ip = fr[0], fr[1]
            k = max(ip - 1, 0)
            tb.append((f.name, f.fault_at[k] if k < len(f.fault_at) else None))
        return tb

    def _run(self, fb: Fiber):
        """Run a fiber until it finishes (results in fb.results), suspends, or faults."""
        mod = fb.mod
        funcs = mod.funcs
        gl = mod.globals
        numeric = NUMERIC
        hook = self.hook
        f, ip, locs, stack, cont = fb.f, fb.ip, fb.locs, fb.stack, fb.cont
        alloc = self.alloc
        frames = fb.frames   # saved (f, ip, locs, stack, cont)
        code = f.code
        fuel = self.fuel
        executed = 0
        try:
            while True:
                try:
                    while True:
                        if hook is not None:
                            nodes = f.starts.get(ip)
                            if nodes is not None:
                                pending = self._pending(f, cont)
                                for node in nodes:
                                    hook(f.name, node, pending, len(frames),
                                         lambda node=node: self._snapshot(frames, f, locs, node), "enter")
                            node = f.steps.get(ip)
                            if node is not None:
                                hook(f.name, node, self._pending(f, cont), len(frames),
                                     lambda: self._snapshot(frames, f, locs, node), "ready")
                        op, arg = code[ip]
                        ip += 1
                        fuel -= 1
                        executed += 1
                        if fuel < 0:
                            self.fuel = 0
                            raise WiretError(STATUS_FUEL, "fuel exhausted",
                                             self._traceback(frames + [(f, ip)], mod))
                        if executed & 0xFFF == 0 and self.interrupted:
                            raise WiretError(STATUS_INTERRUPT, "interrupted by the host",
                                             self._traceback(frames + [(f, ip)], mod))
                        if op == OP_LGET:
                            stack.append(locs[arg])
                        elif op == OP_LSET:
                            locs[arg] = stack.pop()
                        elif op in numeric:
                            n, fn = numeric[op]
                            if n == 2:
                                b = stack.pop()
                                stack[-1] = fn(stack[-1], b)
                            else:
                                stack[-1] = fn(stack[-1])
                        elif op > 0xFF:                       # lane instructions (5.6)
                            n, fn = arg
                            if n == 1:
                                stack[-1] = fn(stack[-1])
                            elif n == 2:
                                b = stack.pop()
                                stack[-1] = fn(stack[-1], b)
                            else:
                                operands = stack[len(stack) - n:]
                                del stack[len(stack) - n:]
                                stack.append(fn(*operands))
                        elif op in _CONST_OPS or op == 0x24:
                            stack.append(arg)
                        elif op == OP_LTEE:
                            locs[arg] = stack[-1]
                        elif op == OP_BR:
                            ip = arg
                        elif op == OP_BR_IF:
                            if stack.pop():
                                ip = arg
                        elif op == OP_CONT_PUSH or op == OP_TRY_PUSH:
                            if len(cont) >= MAX_CONT:
                                raise Fault("continuation stack overflow", FAULT_STACK)
                            cont.append(arg)        # a handler marker is a (handler, local) tuple
                        elif op == OP_CONT_POP:
                            while cont:             # discard handler markers on the way
                                k = cont.pop()
                                if type(k) is int:
                                    ip = k
                                    break
                        elif op == OP_CONT_DEPTH:    # handler markers count (section 5.5)
                            stack.append(len(cont))
                        elif op == OP_CONT_TRUNC:
                            d = stack.pop()
                            if 0 <= d < len(cont):
                                del cont[d:]
                        elif op == OP_SUSPEND:
                            # park the whole fiber, every frame included (section 4.5)
                            if arg == 1:
                                secs = stack.pop()
                                fb.waiting, fb.wake = "time", self.time + (secs if secs > 0 else 0.0)
                                fb.status = FIBER_SUSPENDED
                            elif arg == 2:
                                sig = stack.pop()
                                if sig is None:
                                    raise Fault("Await on a null signal", FAULT_NULL)
                                sig.waiters.append(fb)
                                fb.waiting, fb.signal = "signal", sig
                                fb.status = FIBER_SUSPENDED
                            else:            # Yield: runnable again on the next advance
                                fb.waiting, fb.wake = None, self.time
                                fb.status = FIBER_READY
                            fb.f, fb.ip, fb.locs, fb.stack, fb.cont = f, ip, locs, stack, cont
                            self.fuel = fuel
                            return None
                        elif op == OP_THROW:
                            fv = stack.pop()
                            raise Fault(fv.message, fv.code)
                        elif op == OP_GGET:
                            stack.append(gl[arg])
                        elif op == OP_GSET:
                            gl[arg] = stack.pop()
                        elif op == OP_SELECT:
                            c = stack.pop()
                            b = stack.pop()
                            if not c:
                                stack[-1] = b
                        elif op == OP_DROP:
                            stack.pop()
                        elif op == OP_CALL or op == OP_CALL_VIRTUAL or op == OP_CALL_INTERFACE \
                                or op == OP_CALL_DELEGATE:
                            if op == OP_CALL:
                                callee = funcs[arg]
                            elif op == OP_CALL_DELEGATE:  # take the delegate out from under its args
                                at = len(stack) - arg - 1
                                d = stack[at]
                                if d is None:
                                    raise Fault("invoke of a null delegate", FAULT_NULL)
                                if d.bound:
                                    stack[at] = d.recv
                                else:
                                    del stack[at]
                                callee = funcs[d.func]
                                if callee.flags & wbc.FN_LATENT:   # an event: its own fiber
                                    n = len(callee.params)
                                    cargs = stack[len(stack) - n:] if n else []
                                    del stack[len(stack) - n:]
                                    self._spawn(mod, callee, cargs)
                                    continue
                            elif op == OP_CALL_VIRTUAL:   # dispatch on the receiver's class
                                recv = stack[len(stack) - arg[1]]
                                if recv is None:
                                    raise Fault("method call on a null object", FAULT_NULL)
                                callee = funcs[recv.cls.vtable[arg[0]]]
                            else:                   # through the receiver's interface table
                                recv = stack[len(stack) - arg[2]]
                                if recv is None:
                                    raise Fault("method call on a null object", FAULT_NULL)
                                callee = funcs[recv.cls.itables[arg[0]][arg[1]]]
                            fuel -= 4
                            self.stats["calls"] += 1
                            np = len(callee.params)
                            cargs = stack[len(stack) - np:] if np else []
                            del stack[len(stack) - np:]
                            if callee.native is not None:
                                if callee.cost is not None:
                                    fuel -= callee.cost(*cargs)
                                try:
                                    res = callee.native(self, *cargs)
                                except NativeFault as e:
                                    raise Fault(f"{callee.native_name}: {e}", e.code)
                                stack.extend(normalise(vt, v) for vt, v in zip(callee.results, res))
                            else:
                                if len(frames) >= MAX_FRAMES:
                                    raise Fault("stack overflow", FAULT_STACK)
                                frames.append((f, ip, locs, stack, cont))
                                f = callee
                                code = f.code
                                locs = cargs + list(f.zeros)
                                stack, cont, ip = [], [], 0
                        elif op == OP_RETURN:
                            nr = len(f.results)
                            res = stack[len(stack) - nr:] if nr else []
                            if not frames:
                                self.fuel = fuel
                                res = [export(x) for x in res]
                                fb.status, fb.results = FIBER_DONE, res
                                return res
                            f, ip, locs, stack, cont = frames.pop()
                            code = f.code
                            stack.extend(res)
                        elif op in ARRAY_ARITY:
                            n = ARRAY_ARITY[op]
                            if n == 1:
                                stack[-1] = arg(stack[-1])
                            elif n == 2:
                                b = stack.pop()
                                stack[-1] = arg(stack[-1], b)
                            else:
                                c = stack.pop()
                                b = stack.pop()
                                stack[-1] = arg(stack[-1], b, c)
                            if alloc[0]:                       # 1 fuel per 8 elements allocated
                                fuel -= alloc[0] >> 3
                                alloc[0] = 0
                        elif 0xE0 <= op <= 0xEF:               # map.* and set.*
                            fn, nin = arg
                            if nin:
                                operands = stack[len(stack) - nin:]
                                del stack[len(stack) - nin:]
                                res = fn(*operands)
                            else:
                                res = fn()
                            stack.extend(res)
                            if alloc[0]:                       # 1 fuel per 8 entries allocated
                                fuel -= alloc[0] >> 3
                                alloc[0] = 0
                        elif op == 0xD0:                       # struct.new
                            vals = tuple(stack[len(stack) - arg:]) if arg else ()
                            del stack[len(stack) - arg:]
                            stack.append(vals)
                            fuel -= arg >> 3
                        elif op == 0xD1:                       # struct.get
                            stack[-1] = stack[-1][arg]
                        elif op == 0xD2:                       # struct.with
                            v = stack.pop()
                            s0 = stack[-1]
                            stack[-1] = s0[:arg] + (v,) + s0[arg + 1:]
                            fuel -= len(s0) >> 3
                        elif op == OP_CLASS_GET:
                            o = stack[-1]
                            if o is None:
                                raise Fault("field read on a null object", FAULT_NULL)
                            stack[-1] = o.fields[arg]
                        elif op == OP_CLASS_SET:
                            v = stack.pop()
                            o = stack.pop()
                            if o is None:
                                raise Fault("field write on a null object", FAULT_NULL)
                            o.fields[arg] = v
                        elif op == OP_CLASS_NEW:
                            stack.append(Obj(arg))
                            fuel -= len(arg.defaults) >> 3
                        elif op == OP_REF_SHARE:      # the value escapes: copy on next change
                            c = stack[-1]
                            if c is not None:
                                c.shared = True
                        elif op == OP_REF_NULL:
                            stack.append(None)
                        elif op == OP_REF_IS_NULL:
                            stack[-1] = int(stack[-1] is None)
                        elif op == OP_REF_VALID:
                            stack[-1] = int(stack[-1] is not None)
                        elif op == OP_REF_EQ:
                            b = stack.pop()
                            stack[-1] = int(stack[-1] is b)
                        elif op == OP_REF_TEST:
                            o = stack[-1]
                            stack[-1] = int(o is not None and arg in o.cls.ancestors)
                        elif op == OP_REF_CAST:
                            o = stack[-1]
                            if o is not None and arg not in o.cls.ancestors:
                                raise Fault(f"{o.cls.name} cannot be cast to type {arg}",
                                            FAULT_CAST)
                        elif op == OP_DELEGATE_NEW:
                            fi, flags = arg
                            if flags & 1:
                                recv = stack.pop()
                                if recv is None:
                                    raise Fault("delegate bound to a null object", FAULT_NULL)
                                if flags & 2:        # the receiver's own override
                                    fi = recv.cls.overrides.get(fi, fi)
                                stack.append(Delegate(fi, recv, True))
                            else:
                                stack.append(Delegate(fi))
                        elif op == OP_BIND or op == OP_UNBIND:
                            d = stack.pop()
                            disp = stack.pop()
                            if d is None or disp is None:
                                raise Fault(f"{'Bind' if op == OP_BIND else 'Unbind'} with a "
                                            f"null {'handler' if d is None else 'object'}",
                                            FAULT_NULL)
                            if op == OP_BIND:
                                if d not in disp.handlers:
                                    disp.handlers.append(d)
                            elif d in disp.handlers:
                                disp.handlers.remove(d)
                        elif op == OP_BROADCAST:
                            args = stack[len(stack) - arg:] if arg else []
                            del stack[len(stack) - arg:]
                            disp = stack.pop()
                            if disp is None:
                                raise Fault("Broadcast on a null object", FAULT_NULL)
                            self.fuel = fuel
                            self._broadcast(mod, disp, args)
                            fuel = self.fuel
                        elif op == OP_NOP:
                            pass
                        elif op == OP_UNREACHABLE:
                            raise Fault("unreachable executed", FAULT_UNREACHABLE)
                        else:
                            raise WiretError(STATUS_API, f"unimplemented opcode 0x{op:02X}")
                except Fault as e:
                    # Unwind to the nearest handler marker, frame by frame (section 4.6): drop
                    # the continuations above it, store the fault, clear the operand stack and
                    # jump to the handler. With no marker in any frame, the call ends faulted.
                    at = frames + [(f, ip)]
                    while not any(type(k) is tuple for k in cont):
                        if not frames:
                            self.fuel = fuel
                            raise WiretError(STATUS_FAULT, e.message, self._traceback(at, mod),
                                             e.code)
                        f, ip, locs, stack, cont = frames.pop()
                        code = f.code
                    while True:
                        k = cont.pop()
                        if type(k) is tuple:
                            break
                    ip, slot, _ = k
                    locs[slot] = FaultValue(e.message, e.code)
                    stack.clear()
        except RecursionError:
            raise WiretError(STATUS_FAULT, "stack overflow")
        finally:
            self.stats["instructions"] += executed
            self.fuel = max(fuel, 0)


# -- the input log and replay (section 4.10) -----------------------------------------------------
LOGGED = ("load", "grant", "signal", "call", "start", "advance", "fire", "kill", "new",
          "call_method", "delegate", "broadcast")


class ReplayMismatch(Exception):
    """A replay that did not do what the log recorded: the first entry that differs."""

    def __init__(self, index: int, op: str, what: str, expected, got):
        super().__init__(f"entry {index} ({op}): {what} differs: recorded {expected!r}, "
                         f"replay gave {got!r}")
        self.index, self.op, self.what, self.expected, self.got = index, op, what, expected, got


def _is_handle(v) -> bool:
    return isinstance(v, (Obj, Signal, Fiber, Delegate, DispatcherObj, LoadedModule))


def _encode(vm: "VM", v, new_ok: bool):
    """A value as JSON: numbers exactly (floats as hex), containers by value, and objects,
    signals, fibers, delegates and modules as handles numbered in the order the log first
    meets them. An argument must be a handle the log already has (`new_ok` False)."""
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        return {"f": v.hex()}
    if isinstance(v, (tuple, list)):
        return {"a": [_encode(vm, x, new_ok) for x in v]}
    if isinstance(v, dict):
        return {"m": [[_encode(vm, k, new_ok), _encode(vm, x, new_ok)] for k, x in v.items()]}
    if _is_handle(v):
        h = vm._handles.get(id(v))
        if h is None:
            if not new_ok:
                raise WiretError(STATUS_API, f"{type(v).__name__} did not come from this VM's "
                                             f"API, so a deterministic run cannot log it")
            h = vm._handles[id(v)] = len(vm._handle_objs)
            vm._handle_objs.append(v)
        return {"h": h}
    raise WiretError(STATUS_API, f"cannot log a {type(v).__name__}")


def _decode(vm: "VM", v):
    if isinstance(v, dict):
        if "f" in v:
            return float.fromhex(v["f"])
        if "a" in v:
            return tuple(_decode(vm, x) for x in v["a"])
        if "m" in v:
            return {_decode(vm, k): _decode(vm, x) for k, x in v["m"]}
        return vm._handle_objs[v["h"]]
    return v


def _logged(name, fn):
    def api(self, *args, **kw):
        if not self.deterministic:
            return fn(self, *args, **kw)
        if self._depth:                     # inside another API call: part of that entry
            self._depth += 1
            try:
                return fn(self, *args, **kw)
            finally:
                self._depth -= 1
        if name == "load":
            import hashlib
            enc_args = [hashlib.sha256(bytes(args[0])).hexdigest()]
        else:
            enc_args = [_encode(self, a, False) for a in args]
        enc_kw = {k: _encode(self, a, False) for k, a in kw.items()}
        before = self.stats["instructions"]
        self._depth, self._printed = 1, []
        entry = {"op": name, "args": enc_args, "kw": enc_kw}
        try:
            result = fn(self, *args, **kw)
            entry["out"], entry["error"] = _encode(self, result, True), None
            return result
        except WiretError as e:
            entry["out"], entry["error"] = None, [e.status, e.message, e.code]
            raise
        finally:
            self._depth = 0
            entry["instructions"] = self.stats["instructions"] - before
            entry["fuel"] = self.fuel
            entry["output"] = list(self._printed)
            self.input_log.append(entry)
    api.__name__, api.__doc__ = fn.__name__, fn.__doc__
    return api


for _name in LOGGED:
    setattr(VM, _name, _logged(_name, getattr(VM, _name)))


def replay(data: bytes, log: list, **vm_args) -> "VM":
    """Run an input log again on a new deterministic VM and check that every call gives the
    same result or fault, executes the same number of instructions, leaves the same fuel and
    prints the same lines (section 4.10). Raises ReplayMismatch at the first difference;
    returns the VM, whose own input_log then equals `log`."""
    vm = VM(deterministic=True, **vm_args)
    for i, entry in enumerate(log):
        op = entry["op"]
        if op == "load":
            import hashlib
            if hashlib.sha256(bytes(data)).hexdigest() != entry["args"][0]:
                raise ReplayMismatch(i, op, "module", entry["args"][0], "different bytes")
            args = [data]
        else:
            args = [_decode(vm, a) for a in entry["args"]]
        kw = {k: _decode(vm, a) for k, a in entry["kw"].items()}
        try:
            getattr(vm, op)(*args, **kw)
        except WiretError:
            pass
        got = vm.input_log[-1]
        for what in ("out", "error", "instructions", "fuel", "output"):
            if got[what] != entry[what]:
                raise ReplayMismatch(i, op, what, entry[what], got[what])
    return vm
