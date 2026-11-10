"""Standard-library and host natives (spec sections 3.4 and 6.6).

`std.*` natives are always available. Host natives (`host.*`) must be declared
with `extern func` in the module; the runtime supplies their implementations.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Callable, Optional

from . import lanes as L


class CArray(list):
    """An array value (section 4.9): a list plus the copy-on-write `shared` flag."""
    __slots__ = ("shared",)

    def __init__(self, items=(), shared=False):
        super().__init__(items)
        self.shared = shared


class CMap(dict):
    """A map, or a set (its values are None): an insertion-ordered dict plus `shared`."""
    __slots__ = ("shared",)

    def __init__(self, items=(), shared=False):
        super().__init__(items)
        self.shared = shared


class NativeFault(Exception):
    """Raised by a native to report a fault to the VM. `code` is the fault code (section 4.6);
    -6 means an error from a native."""

    def __init__(self, message: str, code: int = -6):
        super().__init__(message)
        self.code = code


class Signal:
    """A value of type `std.Signal` (section 4.5): fibers `Await` it and resume, in the order
    they began waiting, when it is fired. Equality is identity."""
    __slots__ = ("waiters",)

    def __init__(self):
        self.waiters = []

    def __repr__(self):
        return f"<signal {id(self):x}, {len(self.waiters)} waiting>"


def _signal_fire(vm, s):
    if s is None:
        raise NativeFault("Fire on a null signal", -3)
    vm.fire(s)
    return ()


@dataclass(frozen=True)
class FaultValue:
    """A value of type `fault` (section 4.6): what `try.push` stores in its local and `throw`
    raises."""
    message: str
    code: int


NO_FAULT = FaultValue("", 0)


@dataclass
class NativeSpec:
    params: list            # [(name, type)]
    results: list           # [(name, type)]
    purity: str             # pure | reads | impure
    fn: Optional[Callable]  # fn(vm, *args) -> tuple of results
    doc: str = ""
    cost: Optional[Callable] = None  # cost(*args) -> fuel beyond the call's own (section 5.7)
    capability: Optional[str] = None  # what an import of it must be granted (section 6.5)
    # WR_NATIVE_DETERMINISTIC (section 6.6): the same arguments and VM state give the same
    # results. A native that reads a clock, input or files is not, and a deterministic VM
    # refuses it (section 4.10).
    deterministic: bool = True


def _f32(x: float) -> float:
    try:
        return struct.unpack("<f", struct.pack("<f", x))[0]
    except OverflowError:
        return math.copysign(math.inf, x)


def float_to_text(x: float, single=False) -> str:
    """Culture-independent, shortest round-tripping text (section 3.2)."""
    if math.isnan(x):
        return "NaN"
    if math.isinf(x):
        return "Infinity" if x > 0 else "-Infinity"
    if single:
        for p in range(1, 10):
            s = f"{x:.{p}g}"
            if _f32(float(s)) == x:
                break
    else:
        s = repr(x)
    if "e" in s:
        mant, exp = s.split("e")
        s = f"{mant}e{int(exp)}"
    elif "." not in s and "inf" not in s:
        s += ".0"
    return s


def _round_half_away(x: float) -> float:
    if math.isnan(x) or math.isinf(x):
        return x
    return math.copysign(math.floor(abs(x) + 0.5), x)


def _substring(_vm, s, start, length):
    b = s.encode()
    if start < 0 or length < 0 or start + length > len(b):
        raise NativeFault(f"Substring({start}, {length}) out of range for length {len(b)}")
    return (b[start:start + length].decode(errors="replace"),)


def _f64_unary(fn):
    def call(_vm, x):
        try:
            return (float(fn(x)),)
        except (ValueError, OverflowError):
            return (math.nan,)
    return call


def _pow(_vm, a, b):
    try:
        return (float(math.pow(a, b)),)
    except (ValueError, OverflowError):
        return (math.inf if a > 0 else math.nan,)


def values_equal(a, b) -> bool:
    """`Eq` on two values of one type, as the VM stores them (section 4.9). An array or a
    struct is a tuple and compares element-wise, each element with its own equality, so NaN
    is never equal and a container holding NaN is not equal to itself. A map or a set is a
    dict and ignores insertion order: the same keys (keys match as in a lookup, so the one NaN
    key matches itself), and for a map equal values under each key."""
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(values_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict):
        return len(a) == len(b) and all(k in b and values_equal(v, b[k]) for k, v in a.items())
    return a == b


def value_size(v) -> int:
    """How many elements, entries and fields `values_equal` may visit."""
    if isinstance(v, (tuple, list)):
        return len(v) + sum(value_size(x) for x in v if isinstance(x, (tuple, list, dict)))
    if isinstance(v, dict):
        return len(v) + sum(value_size(x) for x in v.values()
                            if isinstance(x, (tuple, list, dict)))
    return 0


def _equals(_vm, a, b):
    return (int(values_equal(a, b)),)


def _equals_cost(a, b) -> int:
    """1 fuel per 8 elements visited, like allocation; nothing when the lengths differ."""
    return 0 if len(a) != len(b) else min(value_size(a), value_size(b)) >> 3


def _log(vm, message):
    vm.output(message)
    return ()


F = "f64"
STD: dict[str, NativeSpec] = {
    "std.math.Sqrt": NativeSpec([("x", F)], [("result", F)], "pure", _f64_unary(math.sqrt)),
    "std.math.Sin": NativeSpec([("x", F)], [("result", F)], "pure", _f64_unary(math.sin)),
    "std.math.Cos": NativeSpec([("x", F)], [("result", F)], "pure", _f64_unary(math.cos)),
    "std.math.Tan": NativeSpec([("x", F)], [("result", F)], "pure", _f64_unary(math.tan)),
    "std.math.Exp": NativeSpec([("x", F)], [("result", F)], "pure", _f64_unary(math.exp)),
    "std.math.Log": NativeSpec([("x", F)], [("result", F)], "pure", _f64_unary(math.log)),
    "std.math.Floor": NativeSpec([("x", F)], [("result", F)], "pure", _f64_unary(math.floor)),
    "std.math.Ceil": NativeSpec([("x", F)], [("result", F)], "pure", _f64_unary(math.ceil)),
    "std.math.Round": NativeSpec([("x", F)], [("result", F)], "pure",
                                 lambda _vm, x: (_round_half_away(x),)),
    "std.math.Pow": NativeSpec([("a", F), ("b", F)], [("result", F)], "pure", _pow),
    "std.math.Atan2": NativeSpec([("y", F), ("x", F)], [("result", F)], "pure",
                                 lambda _vm, y, x: (math.atan2(y, x),)),
    "std.math.Lerp": NativeSpec([("a", F), ("b", F), ("t", F)], [("result", F)], "pure",
                                lambda _vm, a, b, t: (a + (b - a) * t,)),
    "std.math.Pi": NativeSpec([], [("result", F)], "pure", lambda _vm: (math.pi,)),
    "std.string.Concat": NativeSpec([("a", "string"), ("b", "string")], [("result", "string")],
                                    "pure", lambda _vm, a, b: (a + b,)),
    "std.string.Length": NativeSpec([("s", "string")], [("result", "i32")], "pure",
                                    lambda _vm, s: (len(s.encode()),)),
    "std.string.Substring": NativeSpec([("s", "string"), ("start", "i32"), ("length", "i32")],
                                       [("result", "string")], "pure", _substring),
    "std.string.Find": NativeSpec([("s", "string"), ("sub", "string")], [("result", "i32")], "pure",
                                  lambda _vm, s, sub: (s.encode().find(sub.encode()),)),
    "std.string.ToUpper": NativeSpec([("s", "string")], [("result", "string")], "pure",
                                     lambda _vm, s: (s.upper(),)),
    "std.string.ToLower": NativeSpec([("s", "string")], [("result", "string")], "pure",
                                     lambda _vm, s: (s.lower(),)),
    "std.string.Repeat": NativeSpec([("s", "string"), ("count", "i32")], [("result", "string")],
                                    "pure", lambda _vm, s, n: (s * max(0, n),)),
    # Signals (section 4.5). New is impure because each call makes a new identity.
    "std.signal.New": NativeSpec([], [("signal", "std.Signal")], "impure",
                                 lambda _vm: (Signal(),),
                                 "Make a new signal that fibers can Await."),
    "std.signal.Fire": NativeSpec([("signal", "std.Signal")], [], "impure", _signal_fire,
                                  "Wake every fiber waiting on the signal. They run on the "
                                  "next advance of time."),
}

STD["std.math.Acos"] = NativeSpec([("x", F)], [("result", F)], "pure", _f64_unary(math.acos))


# The lane types' library (section 3.1.1). Each function with a lane instruction is lowered
# to it by the compiler (lanes.INTRINSICS); the natives here serve the rest, and also a call
# the compiler did not lower, so both give the same bits.
def _lane_natives(sin, cos, acos) -> dict:
    out = {}

    def nat(name, params, results, fn, doc=""):
        out[name] = NativeSpec(params, results, "pure",
                               lambda _vm, *a, fn=fn: (fn(*a),), doc)
    for t in L.VECTORS:
        nat(f"std.vec.Dot::<{t}>", [("a", t), ("b", t)], [("result", "f32")], L.dot)
        nat(f"std.vec.Length::<{t}>", [("v", t)], [("result", "f32")], L.length)
        nat(f"std.vec.LengthSquared::<{t}>", [("v", t)], [("result", "f32")], L.lensq)
        nat(f"std.vec.Distance::<{t}>", [("a", t), ("b", t)], [("result", "f32")], L.distance)
        nat(f"std.vec.Normalize::<{t}>", [("v", t)], [("result", t)], L.normalize,
            "The vector scaled to length 1; the zero vector when it has no direction.")
        nat(f"std.vec.Lerp::<{t}>", [("a", t), ("b", t), ("t", "f32")], [("result", t)], L.lerp)
        nat(f"std.vec.Reflect::<{t}>", [("v", t), ("n", t)], [("result", t)], L.reflect)
    nat("std.vec.Cross", [("a", "vec3"), ("b", "vec3")], [("result", "vec3")], L.cross)
    nat("std.vec.PerpDot", [("a", "vec2"), ("b", "vec2")], [("result", "f32")], L.perpdot)
    nat("std.quat.Rotate", [("q", "quat"), ("v", "vec3")], [("result", "vec3")], L.rotate,
        "Rotate a vector by a unit quaternion.")
    nat("std.quat.Conjugate", [("q", "quat")], [("result", "quat")], L.conj)
    nat("std.quat.Inverse", [("q", "quat")], [("result", "quat")], L.qinverse)
    nat("std.quat.Normalize", [("q", "quat")], [("result", "quat")], L.qnormalize)
    axis_angle, slerp, angle = L.quat_natives(sin, cos, acos)
    nat("std.quat.FromAxisAngle", [("axis", "vec3"), ("angle", "f32")], [("result", "quat")],
        axis_angle, "The rotation by `angle` radians about `axis`.")
    nat("std.quat.Slerp", [("a", "quat"), ("b", "quat"), ("t", "f32")], [("result", "quat")],
        slerp, "Interpolate between two rotations along the shorter arc.")
    nat("std.quat.Angle", [("a", "quat"), ("b", "quat")], [("result", "f32")], angle,
        "The angle in radians between two rotations.")
    nat("std.transform.Apply", [("t", "transform"), ("p", "vec3")], [("result", "vec3")],
        L.apply, "Transform a point: scale, rotate, then translate.")
    nat("std.transform.ApplyVector", [("t", "transform"), ("v", "vec3")],
        [("result", "vec3")], L.apply_vector, "Transform a direction: no translation.")
    nat("std.transform.Inverse", [("t", "transform")], [("result", "transform")], L.tinverse)
    return out


def _safe(fn):
    def f(x):
        try:
            return fn(x)
        except (ValueError, OverflowError):
            return math.nan
    return f


STD.update(_lane_natives(_safe(math.sin), _safe(math.cos), _safe(math.acos)))
# The natives that deterministic mode replaces with ones built on the bundled math (4.10).
LANE_TRIG = ("std.quat.FromAxisAngle", "std.quat.Slerp", "std.quat.Angle")

# Natives the compiler calls on its own to lower `Convert<X, string>` and float `Rem`.
INTERNAL: dict[str, NativeSpec] = {
    "std.convert.FromBool": NativeSpec([("v", "i32")], [("r", "string")], "pure",
                                       lambda _vm, v: ("true" if v else "false",)),
    "std.convert.FromI32": NativeSpec([("v", "i32")], [("r", "string")], "pure",
                                      lambda _vm, v: (str(v),)),
    "std.convert.FromU32": NativeSpec([("v", "i32")], [("r", "string")], "pure",
                                      lambda _vm, v: (str(v & 0xFFFFFFFF),)),
    "std.convert.FromI64": NativeSpec([("v", "i64")], [("r", "string")], "pure",
                                      lambda _vm, v: (str(v),)),
    "std.convert.FromU64": NativeSpec([("v", "i64")], [("r", "string")], "pure",
                                      lambda _vm, v: (str(v & 0xFFFFFFFFFFFFFFFF),)),
    "std.convert.FromF32": NativeSpec([("v", "f32")], [("r", "string")], "pure",
                                      lambda _vm, v: (float_to_text(v, single=True),)),
    "std.convert.FromF64": NativeSpec([("v", "f64")], [("r", "string")], "pure",
                                      lambda _vm, v: (float_to_text(v),)),
    **{f"std.convert.From{t.capitalize()}": NativeSpec(
        [("v", t)], [("r", "string")], "pure",
        lambda _vm, v: (L.to_text(v, lambda x: float_to_text(x, single=True)),))
       for t in ("vec2", "vec3", "quat", "transform")},
    "std.math.FRem32": NativeSpec([("a", "f32"), ("b", "f32")], [("r", "f32")], "pure",
                                  lambda _vm, a, b: (_f32(math.fmod(a, b)) if b else math.nan,)),
    "std.math.FRem64": NativeSpec([("a", "f64"), ("b", "f64")], [("r", "f64")], "pure",
                                  lambda _vm, a, b: (math.fmod(a, b) if b else math.nan,)),
}

# `Throw` makes a fault from its message and code, and `Try` reads them back (section 4.6).
INTERNAL["std.fault.Make"] = NativeSpec([("message", "string"), ("code", "i32")],
                                        [("fault", "fault")], "pure",
                                        lambda _vm, m, c: (FaultValue(m, c),))
INTERNAL["std.fault.Message"] = NativeSpec([("fault", "fault")], [("message", "string")], "pure",
                                           lambda _vm, f: (f.message,))
INTERNAL["std.fault.Code"] = NativeSpec([("fault", "fault")], [("code", "i32")], "pure",
                                        lambda _vm, f: (f.code,))

# `Eq` and `Ne` on containers (section 4.9). One native per container kind, taking anyref so
# that one signature serves every element type; the native reads the values it is given.
for _kind in ("array", "set", "map"):
    INTERNAL[f"std.{_kind}.Equals"] = NativeSpec(
        [("a", "anyref"), ("b", "anyref")], [("r", "bool")], "pure", _equals,
        f"True when two {_kind}s are equal.", cost=_equals_cost)

# Host natives the reference runtime registers. A module reaches them only through
# `extern func` declarations, whose signatures must match.
HOST: dict[str, NativeSpec] = {
    "host.Log": NativeSpec([("message", "string")], [], "impure", _log,
                           "Write a line to the console.", capability="console.write"),
}


def all_natives() -> dict[str, NativeSpec]:
    return {**STD, **INTERNAL, **HOST}
