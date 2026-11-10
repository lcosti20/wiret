"""The lane types `vec2`, `vec3`, `quat` and `transform` (spec section 3.1.1).

They are built-in structs with fixed `f32` fields that the VM holds unboxed. In this
prototype a value is a tuple of floats, nested for a transform, which is how the VM holds a
struct too; what makes them lane types is that the compiler emits the lane instructions of
section 5.6 for them instead of `struct.*`, and that they never cost allocation fuel.

Every operation is the `f32` operation of section 4.10: each `+ - * /` and `Sqrt` is computed
in binary64 and rounded once to binary32, which is exact for these operations, and the
formulas run in the order the specification writes them, with no fused multiply-add.
"""
from __future__ import annotations

import math
import struct

LANE_FIELDS = {
    "vec2": [("x", "f32"), ("y", "f32")],
    "vec3": [("x", "f32"), ("y", "f32"), ("z", "f32")],
    "quat": [("x", "f32"), ("y", "f32"), ("z", "f32"), ("w", "f32")],
    "transform": [("translation", "vec3"), ("rotation", "quat"), ("scale", "vec3")],
}
LANE_TYPES = tuple(LANE_FIELDS)
VECTORS = ("vec2", "vec3")

DEFAULTS = {
    "vec2": (0.0, 0.0),
    "vec3": (0.0, 0.0, 0.0),
    "quat": (0.0, 0.0, 0.0, 1.0),
    "transform": ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), (1.0, 1.0, 1.0)),
}
LANE_COUNTS = {"vec2": 2, "vec3": 3, "quat": 4, "transform": 10}


def f32(x: float) -> float:
    try:
        return struct.unpack("<f", struct.pack("<f", x))[0]
    except OverflowError:
        return math.copysign(math.inf, x)


def _div(a: float, b: float) -> float:
    if b == 0:
        if a == 0 or a != a:
            return math.nan
        return math.copysign(math.inf, a) * math.copysign(1.0, b)
    return f32(a / b)


def _sqrt(x: float) -> float:
    return math.nan if x < 0 or x != x else f32(math.sqrt(x))


def _min(a, b):
    if a != a or b != b:
        return math.nan
    if a == b == 0:
        return a if math.copysign(1, a) < 0 else b     # -0 orders before +0
    return a if a < b else b


def _max(a, b):
    if a != a or b != b:
        return math.nan
    if a == b == 0:
        return b if math.copysign(1, a) < 0 else a
    return a if a > b else b


def add(a, b): return tuple(f32(x + y) for x, y in zip(a, b))
def sub(a, b): return tuple(f32(x - y) for x, y in zip(a, b))
def mul(a, b): return tuple(f32(x * y) for x, y in zip(a, b))
def div(a, b): return tuple(_div(x, y) for x, y in zip(a, b))
def vmin(a, b): return tuple(_min(x, y) for x, y in zip(a, b))
def vmax(a, b): return tuple(_max(x, y) for x, y in zip(a, b))
def neg(a): return tuple(-x for x in a)
def vabs(a): return tuple(abs(x) for x in a)
def scale(v, s): return tuple(f32(x * s) for x in v)


def eq(a, b) -> int:
    """Component-wise, in field order, with the f32 rules: NaN is never equal."""
    if isinstance(a[0], tuple):
        return int(all(eq(x, y) for x, y in zip(a, b)))
    return int(all(x == y for x, y in zip(a, b)))


def dot(a, b) -> float:
    """`(a.x*b.x + a.y*b.y) + a.z*b.z`, left to right; over as many components as given."""
    total = f32(a[0] * b[0])
    for x, y in zip(a[1:], b[1:]):
        total = f32(total + f32(x * y))
    return total


def cross(a, b):
    return (f32(f32(a[1] * b[2]) - f32(a[2] * b[1])),
            f32(f32(a[2] * b[0]) - f32(a[0] * b[2])),
            f32(f32(a[0] * b[1]) - f32(a[1] * b[0])))


def perpdot(a, b) -> float:
    return f32(f32(a[0] * b[1]) - f32(a[1] * b[0]))


def lensq(v) -> float:
    return dot(v, v)


def length(v) -> float:
    return _sqrt(dot(v, v))


def distance(a, b) -> float:
    return length(sub(a, b))


def normalize(v):
    """Each component divided by the length when it is > 0; otherwise (zero or NaN) zero."""
    n = length(v)
    return tuple(_div(x, n) for x in v) if n > 0 else tuple(0.0 for _ in v)


def lerp(a, b, t):
    return tuple(f32(x + f32(f32(y - x) * t)) for x, y in zip(a, b))


def reflect(v, n):
    return sub(v, scale(n, f32(2 * dot(v, n))))


def from_v2(v): return (v[0], v[1], 0.0)
def to_v2(v): return (v[0], v[1])


# -- quaternions ---------------------------------------------------------------------------
IDENTITY = DEFAULTS["quat"]


def qmul(a, b):
    """The Hamilton product: the rotation b, then a."""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    m = lambda x, y: f32(x * y)          # noqa: E731
    return (f32(f32(f32(m(aw, bx) + m(ax, bw)) + m(ay, bz)) - m(az, by)),
            f32(f32(f32(m(aw, by) - m(ax, bz)) + m(ay, bw)) + m(az, bx)),
            f32(f32(f32(m(aw, bz) + m(ax, by)) - m(ay, bx)) + m(az, bw)),
            f32(f32(f32(m(aw, bw) - m(ax, bx)) - m(ay, by)) - m(az, bz)))


def conj(q):
    return (-q[0], -q[1], -q[2], q[3])


def qinverse(q):
    d = dot(q, q)
    return tuple(_div(x, d) for x in conj(q)) if d > 0 else IDENTITY


def qnormalize(q):
    n = length(q)
    return tuple(_div(x, n) for x in q) if n > 0 else IDENTITY


def rotate(q, v):
    """`t = Scale(Cross(u, v), 2)`, then `(v + Scale(t, q.w)) + Cross(u, t)`."""
    u = q[:3]
    t = scale(cross(u, v), 2.0)
    return add(add(v, scale(t, q[3])), cross(u, t))


def quat_natives(sin, cos, acos):
    """The std.quat functions built on Sin, Cos and Acos (natives, section 5.6). The math
    functions are passed in, so that deterministic mode can give the bundled ones."""
    def s(x): return f32(sin(x))
    def c(x): return f32(cos(x))

    def from_axis_angle(axis, angle):
        n = normalize(axis)
        if n == (0.0, 0.0, 0.0):
            return IDENTITY
        h = f32(angle * 0.5)
        sh = s(h)
        return (f32(n[0] * sh), f32(n[1] * sh), f32(n[2] * sh), c(h))

    def slerp(a, b, t):
        d = dot(a, b)
        if d < 0:
            b, d = neg(b), -d
        if d > f32(0.9995):
            return qnormalize(lerp(a, b, t))
        th = f32(acos(d))
        st = s(th)
        wa = _div(s(f32(f32(1 - t) * th)), st)
        wb = _div(s(f32(t * th)), st)
        return add(scale(a, wa), scale(b, wb))

    def angle(a, b):
        d = abs(dot(a, b))
        return f32(2 * f32(acos(_min(d, 1.0))))
    return from_axis_angle, slerp, angle


# -- transforms ----------------------------------------------------------------------------
def apply(t, p):
    return add(t[0], rotate(t[1], mul(t[2], p)))


def apply_vector(t, v):
    return rotate(t[1], mul(t[2], v))


def tmul(a, b):
    """Composition: b, then a. Exact when a's scale is uniform or b's rotation the identity."""
    return (apply(a, b[0]), qmul(a[1], b[1]), mul(a[2], b[2]))


def tinverse(t):
    r = conj(t[1])
    s = tuple(0.0 if x == 0 else _div(1.0, x) for x in t[2])
    return (mul(s, rotate(r, neg(t[0]))), r, s)


# -- text ----------------------------------------------------------------------------------
def to_text(v, single_text) -> str:
    """The literal form (section 3.2): `(0, 1.5, 0)`, nested for a transform."""
    if isinstance(v[0], tuple):
        return "(" + ", ".join(to_text(x, single_text) for x in v) + ")"
    return "(" + ", ".join(single_text(x) for x in v) + ")"


def normalise(ty: str, v):
    """A host value (any numbers, tuples or lists) as the VM holds a lane value."""
    if ty == "transform":
        return (normalise("vec3", v[0]), normalise("quat", v[1]), normalise("vec3", v[2]))
    return tuple(f32(float(x)) for x in v)


# -- lane instructions (section 5.6) -------------------------------------------------------
# block prefix, base sub-opcode, Wiret type, then (index, name, operand types or None for
# "two of the block's type", result type or None for "the block's type").
_VEC = [(0, "make"), (1, "get"), (2, "with"), (3, "add"), (4, "sub"), (5, "mul"), (6, "div"),
        (7, "min"), (8, "max"), (9, "neg"), (10, "abs"), (11, "scale"), (12, "eq"), (13, "ne"),
        (14, "dot"), (15, "len"), (16, "lensq"), (17, "normalize"), (18, "lerp"),
        (19, "reflect")]
BLOCKS = {
    "v2": (0x00, "vec2", _VEC + [(20, "perpdot")]),
    "v3": (0x20, "vec3", _VEC + [(20, "cross"), (21, "from_v2"), (22, "to_v2")]),
    "q": (0x40, "quat", [(0, "make"), (1, "get"), (2, "with"), (3, "mul"), (4, "conj"),
                         (5, "inverse"), (6, "normalize"), (7, "dot"), (8, "eq"), (9, "ne"),
                         (10, "rotate")]),
    "t": (0x60, "transform", [(0, "make"), (1, "get"), (2, "with"), (3, "mul"),
                              (4, "inverse"), (5, "apply"), (6, "apply_vector"), (7, "eq"),
                              (8, "ne")]),
}
PREFIX = {ty: p for p, (_, ty, _) in BLOCKS.items()}   # "vec3" -> "v3"

# name -> sub-opcode; field-index immediates for get and with
SUB_OPS = {f"{p}.{name}": base + i for p, (base, _, ops) in BLOCKS.items() for i, name in ops}
IMM_OPS = {name for name in SUB_OPS if name.endswith((".get", ".with"))}


def effect(name: str, field: int = 0):
    """(operand Wiret types, result Wiret type) of a lane instruction."""
    p, _, op = name.partition(".")
    ty = BLOCKS[p][1]
    fields = [t for _, t in LANE_FIELDS[ty]]
    if op == "make":
        return fields, ty
    if op == "get":
        return [ty], fields[field]
    if op == "with":
        return [ty, fields[field]], ty
    if op in ("neg", "abs", "normalize", "conj", "inverse"):
        return [ty], ty
    if op == "scale":
        return [ty, "f32"], ty
    if op in ("eq", "ne"):
        return [ty, ty], "bool"
    if op in ("dot", "perpdot"):
        return [ty, ty], "f32"
    if op in ("len", "lensq"):
        return [ty], "f32"
    if op == "lerp":
        return [ty, ty, "f32"], ty
    if op == "from_v2":
        return ["vec2"], "vec3"
    if op == "to_v2":
        return ["vec3"], "vec2"
    if op == "rotate":
        return ["quat", "vec3"], "vec3"
    if op in ("apply", "apply_vector"):
        return ["transform", "vec3"], "vec3"
    return [ty, ty], ty                 # add sub mul div min max reflect cross, q/t mul


def function(name: str, field: int = 0):
    """The Python function an instruction computes, taking its operands in order."""
    p, _, op = name.partition(".")
    ty = BLOCKS[p][1]
    if op == "make":
        return lambda *xs: tuple(xs)
    if op == "get":
        return lambda v: v[field]
    if op == "with":
        return lambda v, x: v[:field] + (x,) + v[field + 1:]
    if op in ("eq", "ne"):
        return (lambda a, b: eq(a, b)) if op == "eq" else (lambda a, b: 1 - eq(a, b))
    if op == "mul" and ty == "quat":
        return qmul
    if op == "mul" and ty == "transform":
        return tmul
    if op == "normalize" and ty == "quat":
        return qnormalize
    if op == "inverse":
        return qinverse if ty == "quat" else tinverse
    return {"add": add, "sub": sub, "mul": mul, "div": div, "min": vmin, "max": vmax,
            "neg": neg, "abs": vabs, "scale": scale, "dot": dot, "len": length,
            "lensq": lensq, "normalize": normalize, "lerp": lerp, "reflect": reflect,
            "perpdot": perpdot, "cross": cross, "from_v2": from_v2, "to_v2": to_v2,
            "conj": conj, "rotate": rotate, "apply": apply,
            "apply_vector": apply_vector}[op]


# The std.vec, std.quat and std.transform functions that lower to one lane instruction:
# (qualified name with type arguments) -> instruction.
INTRINSICS = {}
for _t, _p in (("vec2", "v2"), ("vec3", "v3")):
    for _fn, _op in (("Dot", "dot"), ("Length", "len"), ("LengthSquared", "lensq"),
                     ("Normalize", "normalize"), ("Lerp", "lerp"), ("Reflect", "reflect")):
        INTRINSICS[f"std.vec.{_fn}::<{_t}>"] = f"{_p}.{_op}"
    INTRINSICS[f"std.vec.Distance::<{_t}>"] = [f"{_p}.sub", f"{_p}.len"]
INTRINSICS["std.vec.Cross"] = "v3.cross"
INTRINSICS["std.vec.PerpDot"] = "v2.perpdot"
INTRINSICS.update({"std.quat.Rotate": "q.rotate", "std.quat.Conjugate": "q.conj",
                   "std.quat.Inverse": "q.inverse", "std.quat.Normalize": "q.normalize",
                   "std.transform.Apply": "t.apply", "std.transform.ApplyVector": "t.apply_vector",
                   "std.transform.Inverse": "t.inverse"})
