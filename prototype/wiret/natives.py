"""Standard-library and host natives (spec sections 3.4 and 6.6).

`std.*` natives are always available. Host natives (`host.*`) must be declared
with `extern func` in the module; the runtime supplies their implementations.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Callable, Optional


class NativeFault(Exception):
    """Raised by a native to report a fault to the VM."""


@dataclass
class NativeSpec:
    params: list            # [(name, type)]
    results: list           # [(name, type)]
    purity: str             # pure | reads | impure
    fn: Optional[Callable]  # fn(vm, *args) -> tuple of results
    doc: str = ""


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
}

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
    "std.math.FRem32": NativeSpec([("a", "f32"), ("b", "f32")], [("r", "f32")], "pure",
                                  lambda _vm, a, b: (_f32(math.fmod(a, b)) if b else math.nan,)),
    "std.math.FRem64": NativeSpec([("a", "f64"), ("b", "f64")], [("r", "f64")], "pure",
                                  lambda _vm, a, b: (math.fmod(a, b) if b else math.nan,)),
}

# Host natives the reference runtime registers. A module reaches them only through
# `extern func` declarations, whose signatures must match.
HOST: dict[str, NativeSpec] = {
    "host.Log": NativeSpec([("message", "string")], [], "impure", _log,
                           "Write a line to the console."),
}


def all_natives() -> dict[str, NativeSpec]:
    return {**STD, **INTERNAL, **HOST}
