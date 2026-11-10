"""The bundled `std.math` implementations of deterministic mode (spec section 4.10).

Functions that IEEE-754 does not require to be correctly rounded (`Sin`, `Cos`, `Tan`, `Exp`,
`Log`, `Pow`, `Atan2`) differ in their last bits between C libraries. In deterministic mode
the VM uses these instead of the platform's `libm`. Each one works in Python's `decimal`
module, whose arithmetic is specified exactly (the General Decimal Arithmetic standard) and
implemented in software, so it gives the same digits on every platform. The result is
computed to WORK significant digits and then converted to binary64 once, with round to
nearest even; that is, almost always, the correctly rounded value as well.

Special values (NaN, infinities, signed zeros) follow C99 Annex F, as `libm` does, and every
NaN result is the canonical quiet NaN.
"""
from __future__ import annotations

import math
from decimal import Decimal, localcontext

WORK = 60                      # significant digits of the working precision
NAN = float("nan")
INF = float("inf")


def _to_float(d: Decimal) -> float:
    """Round a Decimal to the nearest binary64 (Python's float(str) is correctly rounded;
    overflow gives an infinity and underflow a subnormal or zero, keeping the sign)."""
    return float(d)


# -- pi, to enough digits to reduce any finite binary64 argument exactly ------------------
_PI_CACHE: dict = {}


def _pi(digits: int) -> Decimal:
    """pi to `digits` significant digits, by Machin's formula, cached."""
    if digits not in _PI_CACHE:
        with localcontext() as ctx:
            ctx.prec = digits + 10

            def arctan_inv(n: int) -> Decimal:       # atan(1/n), n an integer
                x = Decimal(1) / n
                x2 = x * x
                total, term, k = x, x, 1
                eps = Decimal(10) ** -(digits + 8)
                while abs(term) > eps:
                    term *= -x2
                    k += 2
                    total += term / k
                return total
            pi = 16 * arctan_inv(5) - 4 * arctan_inv(239)
            ctx.prec = digits
            _PI_CACHE[digits] = +pi
    return _PI_CACHE[digits]


# The largest finite binary64 is about 1.8e308, and its exact decimal expansion has 309
# integer digits; reducing it modulo 2*pi exactly needs pi to that many digits and then WORK
# more for the remainder.
_REDUCE_DIGITS = 309 + WORK + 20


def _reduce(x: Decimal) -> Decimal:
    """x modulo 2*pi, into [-pi, pi], exactly enough for any finite binary64 x."""
    with localcontext() as ctx:
        ctx.prec = _REDUCE_DIGITS
        two_pi = 2 * _pi(_REDUCE_DIGITS)
        r = x.remainder_near(two_pi)        # in [-pi, pi]
        ctx.prec = WORK + 10
        return +r


def _sin_series(r: Decimal) -> Decimal:
    """sin r by its Taylor series, |r| <= pi; the context precision is set by the caller."""
    r2 = r * r
    term, total, n = r, r, 1
    eps = Decimal(10) ** -(WORK + 15)
    while abs(term) > eps:
        term *= -r2 / ((n + 1) * (n + 2))
        n += 2
        total += term
    return total


def _cos_series(r: Decimal) -> Decimal:
    r2 = r * r
    term, total, n = Decimal(1), Decimal(1), 0
    eps = Decimal(10) ** -(WORK + 15)
    while abs(term) > eps:
        term *= -r2 / ((n + 1) * (n + 2))
        n += 2
        total += term
    return total


def sin(x: float) -> float:
    if math.isnan(x) or math.isinf(x):
        return NAN
    if x == 0:
        return x                            # keeps the sign of zero
    r = _reduce(Decimal(x))
    with localcontext() as ctx:
        ctx.prec = WORK + 10
        return _to_float(_sin_series(r))


def cos(x: float) -> float:
    if math.isnan(x) or math.isinf(x):
        return NAN
    r = _reduce(Decimal(x))
    with localcontext() as ctx:
        ctx.prec = WORK + 10
        return _to_float(_cos_series(r))


def tan(x: float) -> float:
    if math.isnan(x) or math.isinf(x):
        return NAN
    if x == 0:
        return x
    r = _reduce(Decimal(x))
    with localcontext() as ctx:
        ctx.prec = WORK + 10
        return _to_float(_sin_series(r) / _cos_series(r))


def exp(x: float) -> float:
    if math.isnan(x):
        return NAN
    if x == INF:
        return INF
    if x == -INF:
        return 0.0
    if x > 710:                             # beyond the largest binary64
        return INF
    if x < -746:                            # below half the smallest subnormal
        return 0.0
    with localcontext() as ctx:
        ctx.prec = WORK
        return _to_float(Decimal(x).exp())


def log(x: float) -> float:
    if math.isnan(x) or x < 0:
        return NAN
    if x == 0:
        return -INF
    if x == INF:
        return INF
    with localcontext() as ctx:
        ctx.prec = WORK
        return _to_float(Decimal(x).ln())


def _is_int(y: float) -> bool:
    return not math.isinf(y) and y == math.floor(y)


def _is_odd_int(y: float) -> bool:
    return _is_int(y) and abs(y) < 2 ** 53 and int(y) % 2 == 1


def pow(x: float, y: float) -> float:
    """x to the power y, with the special cases of C99 Annex F (F.10.4.4)."""
    if y == 0:
        return 1.0                          # even for a NaN x
    if x == 1:
        return 1.0                          # even for a NaN y
    if math.isnan(x) or math.isnan(y):
        return NAN
    if x == 0:
        if y < 0:
            return math.copysign(INF, x) if _is_odd_int(y) else INF
        return x if _is_odd_int(y) else 0.0
    if math.isinf(y):
        if x == -1:
            return 1.0
        if (abs(x) < 1) == (y < 0):
            return INF
        return 0.0
    if math.isinf(x):
        if x > 0:
            return INF if y > 0 else 0.0
        if y > 0:
            return -INF if _is_odd_int(y) else INF
        return -0.0 if _is_odd_int(y) else 0.0
    if x < 0 and not _is_int(y):
        return NAN
    negative = x < 0 and _is_odd_int(y)
    with localcontext() as ctx:
        ctx.prec = WORK
        ax = Decimal(abs(x))
        # a huge |result| only needs its order of magnitude to give inf or 0
        mag = float(y) * math.log10(abs(x)) if abs(x) != 1 else 0.0
        if mag > 400:
            r = INF
        elif mag < -400:
            r = 0.0
        elif _is_int(y) and abs(y) <= 4096:
            r = _to_float(ax ** int(y))     # exact up to rounding
        else:
            r = _to_float((Decimal(y) * ax.ln()).exp())
    return -r if negative else r


def _atan(t: Decimal) -> Decimal:
    """atan t for t >= 0, in the caller's precision: reduce to small t, then the series."""
    if t > 1:
        return _pi(WORK + 15) / 2 - _atan(1 / t)
    halvings = 0
    while t > Decimal("0.1"):               # atan t = 2 atan(t / (1 + sqrt(1 + t^2)))
        t = t / (1 + (1 + t * t).sqrt())
        halvings += 1
    t2 = t * t
    term, total, n = t, t, 1
    eps = Decimal(10) ** -(WORK + 15)
    while abs(term) > eps:
        term *= -t2
        n += 2
        total += term / n
    return total * (2 ** halvings)


def atan2(y: float, x: float) -> float:
    """The angle of the point (x, y), with the special cases of C99 Annex F (F.10.1.4)."""
    if math.isnan(x) or math.isnan(y):
        return NAN
    pi = math.pi                            # the binary64 nearest pi, as libm returns
    if y == 0:
        if x > 0 or (x == 0 and math.copysign(1, x) > 0):
            return y                        # +-0
        return math.copysign(pi, y)
    if x == 0:
        return math.copysign(pi / 2, y)
    if math.isinf(x):
        if math.isinf(y):
            a = pi / 4 if x > 0 else 3 * pi / 4
            return math.copysign(a, y)
        return math.copysign(0.0, y) if x > 0 else math.copysign(pi, y)
    if math.isinf(y):
        return math.copysign(pi / 2, y)
    with localcontext() as ctx:
        ctx.prec = WORK + 15
        a = _atan(abs(Decimal(y) / Decimal(x)))
        if x < 0:
            a = _pi(WORK + 15) - a
        if y < 0:
            a = -a
        return _to_float(a)


def acos(x: float) -> float:
    """The angle in [0, pi] whose cosine is x; NaN outside [-1, 1] (C99 F.10.1.1)."""
    if math.isnan(x) or abs(x) > 1:
        return NAN
    if x == 1:
        return 0.0
    if x == -1:
        return math.pi
    if x == 0:
        return math.pi / 2
    with localcontext() as ctx:
        ctx.prec = WORK + 15
        d = Decimal(x)
        a = _atan(((1 - d) * (1 + d)).sqrt() / abs(d))
        if x < 0:
            a = _pi(WORK + 15) - a
        return _to_float(a)


BUNDLED = {"std.math.Sin": sin, "std.math.Cos": cos, "std.math.Tan": tan,
           "std.math.Exp": exp, "std.math.Log": log, "std.math.Acos": acos}
BUNDLED2 = {"std.math.Pow": pow, "std.math.Atan2": atan2}
