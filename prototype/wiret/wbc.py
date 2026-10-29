"""WBC 1 binary format (spec section 5): opcodes, LEB128 and the section container.

Encoding choices the draft leaves open, fixed here for the prototype:
- every `u32` in the container (section sizes, vector lengths, indices) is unsigned LEB128;
  only magic, version and flags are fixed-width little-endian;
- branch offsets `L` are signed LEB128 padded to exactly 5 bytes, so code can be laid out
  in one pass;
- custom section payload layouts are documented in `prototype/README.md`.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

MAGIC = b"\x00WBC"
VERSION = 1
FLAG_HAS_SOURCE = 1

# value types (section 5.3)
I32, I64, F32, F64, STRING = 0x7F, 0x7E, 0x7D, 0x7C, 0x6E
REF = 0x6B                      # `6B t`: reference to type index t (here: arrays)
VT_NAMES = {I32: "i32", I64: "i64", F32: "f32", F64: "f64", STRING: "string"}
FUNC_TYPE = 0x60
ARRAY_TYPE = 0x5E


@dataclass(frozen=True)
class Ref:
    """Value type `6B t`: a reference to the type entry at index t."""
    type: int


@dataclass(frozen=True)
class ArrayType:
    """Type entry `5E elem`."""
    elem: object                # a value type


def vt_name(vt, types=None) -> str:
    if isinstance(vt, Ref):
        if types is not None and vt.type < len(types) and isinstance(types[vt.type], ArrayType):
            return f"array<{vt_name(types[vt.type].elem, types)}>"
        return f"ref {vt.type}"
    return VT_NAMES.get(vt, f"0x{vt:02X}")

# section ids
SEC_CUSTOM, SEC_TYPE, SEC_IMPORT, SEC_FUNCTION, SEC_GLOBAL, SEC_EXPORT, SEC_DATA, SEC_CODE = range(8)

FN_PURE, FN_LATENT, FN_EVENT = 1, 2, 4
EX_EVENT, EX_LATENT, EX_PURE = 1, 2, 4


class WbcError(Exception):
    pass


# -- opcodes -----------------------------------------------------------------------
# immediates: L = branch label (padded s32), u = u32, s = s32, S = s64, f = f32 bytes,
#             d = f64 bytes, T = br_table, b = u8
OPS: dict[str, tuple] = {
    "unreachable": (0x00, ""), "nop": (0x01, ""), "br": (0x02, "L"), "br_if": (0x03, "L"),
    "br_table": (0x04, "T"), "return": (0x05, ""), "call": (0x06, "u"),
    "cont.push": (0x0A, "L"), "cont.pop": (0x0B, ""),
    "drop": (0x10, ""), "select": (0x11, ""),
    "local.get": (0x12, "u"), "local.set": (0x13, "u"), "local.tee": (0x14, "u"),
    "global.get": (0x15, "u"), "global.set": (0x16, "u"),
    "i32.const": (0x20, "s"), "i64.const": (0x21, "S"), "f32.const": (0x22, "f"),
    "f64.const": (0x23, "d"), "string.const": (0x24, "u"),
    "string.concat": (0xF0, ""), "string.len": (0xF1, ""), "string.eq": (0xF2, ""),
    "string.cmp": (0xF3, ""),
    "array.new": (0xD6, "u"), "array.len": (0xD7, ""), "array.get": (0xD8, "u"),
    "array.set": (0xD9, "u"), "array.push": (0xDA, "u"), "array.insert": (0xDB, "u"),
    "array.remove": (0xDC, "u"), "array.clear": (0xDD, "u"), "array.clone": (0xDE, "u"),
}
INT_OPS = ["eqz", "eq", "ne", "lt_s", "lt_u", "gt_s", "gt_u", "le_s", "le_u", "ge_s", "ge_u",
           "add", "sub", "mul", "div_s", "div_u", "rem_s", "rem_u", "and", "or", "xor", "shl",
           "shr_s", "shr_u", "neg", "not", "extend8_s", "extend16_s"]
FLOAT_OPS = ["eq", "ne", "lt", "gt", "le", "ge", "add", "sub", "mul", "div", "min", "max", "neg",
             "abs", "sqrt", "ceil", "floor", "trunc", "nearest", "copysign"]
for _i, _n in enumerate(INT_OPS):
    OPS[f"i32.{_n}"] = (0x30 + _i, "")
for _i, _n in enumerate(INT_OPS + ["extend32_s"]):
    OPS[f"i64.{_n}"] = (0x50 + _i, "")
for _i, _n in enumerate(FLOAT_OPS):
    OPS[f"f32.{_n}"] = (0x70 + _i, "")
    OPS[f"f64.{_n}"] = (0x90 + _i, "")
_CONV = ["i32.wrap_i64", "i64.extend_i32_s", "i64.extend_i32_u", "i32.trunc_f32_s",
         "i32.trunc_f32_u", "i32.trunc_f64_s", "i32.trunc_f64_u", "i64.trunc_f32_s",
         "i64.trunc_f32_u", "i64.trunc_f64_s", "i64.trunc_f64_u", "f32.convert_i32_s",
         "f32.convert_i32_u", "f32.convert_i64_s", "f32.convert_i64_u", "f64.convert_i32_s",
         "f64.convert_i32_u", "f64.convert_i64_s", "f64.convert_i64_u", "f32.demote_f64",
         "f64.promote_f32", "i32.reinterpret_f32", "i64.reinterpret_f64", "f32.reinterpret_i32",
         "f64.reinterpret_i64"]
for _i, _n in enumerate(_CONV):
    OPS[_n] = (0xB0 + _i, "")

BY_CODE: dict[int, tuple] = {code: (name, imm) for name, (code, imm) in OPS.items()}

# Opcodes the spec defines for later tiers (objects, containers, fibers, faults). They decode,
# but this prototype's verifier rejects them.
LATER_TIER_OPS = {0x07: "call_virtual", 0x08: "call_interface", 0x09: "call_delegate",
                  0x0C: "try.push", 0x0D: "suspend", 0x0E: "throw", 0x25: "ref.null",
                  0x26: "ref.is_null", 0x27: "ref.eq", 0x28: "ref.cast", 0x29: "ref.test",
                  0x2A: "ref.valid", 0x2B: "ref.share"}
for _c in list(range(0xD0, 0xD6)) + list(range(0xE0, 0xF0)):
    LATER_TIER_OPS.setdefault(_c, f"object.0x{_c:02X}")
for _c in (0xF4, 0xF5, 0xF6, 0xF7):
    LATER_TIER_OPS[_c] = f"object.0x{_c:02X}"


# -- byte writer / reader ------------------------------------------------------------
class Writer:
    def __init__(self):
        self.b = bytearray()

    def u8(self, v):
        self.b.append(v & 0xFF)

    def u32(self, v):
        if v < 0:
            raise ValueError("u32 must be non-negative")
        while True:
            byte = v & 0x7F
            v >>= 7
            if v:
                self.b.append(byte | 0x80)
            else:
                self.b.append(byte)
                return

    def sleb(self, v):
        while True:
            byte = v & 0x7F
            v >>= 7
            if (v == 0 and not byte & 0x40) or (v == -1 and byte & 0x40):
                self.b.append(byte)
                return
            self.b.append(byte | 0x80)

    def sleb5(self, v):
        """Signed LEB128 padded to five bytes (branch offsets)."""
        for i in range(5):
            byte = v & 0x7F
            v >>= 7
            self.b.append(byte | (0x80 if i < 4 else 0))

    def f32(self, v):
        self.b += struct.pack("<f", v)

    def f64(self, v):
        self.b += struct.pack("<d", v)

    def raw(self, data: bytes):
        self.b += data

    def name(self, s: str):
        data = s.encode()
        self.u32(len(data))
        self.b += data

    def blob(self, data: bytes):
        self.u32(len(data))
        self.b += data


def write_vt(w: "Writer", vt):
    if isinstance(vt, Ref):
        w.u8(REF)
        w.u32(vt.type)
    else:
        w.u8(vt)


class Reader:
    def __init__(self, data: bytes, pos=0, end=None):
        self.d = data
        self.p = pos
        self.end = len(data) if end is None else end

    def eof(self):
        return self.p >= self.end

    def need(self, n):
        if self.p + n > self.end:
            raise WbcError("unexpected end of data")

    def u8(self):
        self.need(1)
        v = self.d[self.p]
        self.p += 1
        return v

    def u32(self):
        result, shift = 0, 0
        while True:
            b = self.u8()
            result |= (b & 0x7F) << shift
            shift += 7
            if not b & 0x80:
                break
            if shift > 35:
                raise WbcError("LEB128 too long")
        if result > 0xFFFFFFFF:
            raise WbcError("u32 out of range")
        return result

    def sleb(self, bits=64):
        result, shift = 0, 0
        while True:
            b = self.u8()
            result |= (b & 0x7F) << shift
            shift += 7
            if not b & 0x80:
                break
            if shift > bits + 7:
                raise WbcError("LEB128 too long")
        if b & 0x40:
            result -= 1 << shift
        return result

    def f32(self):
        self.need(4)
        v = struct.unpack_from("<f", self.d, self.p)[0]
        self.p += 4
        return v

    def f64(self):
        self.need(8)
        v = struct.unpack_from("<d", self.d, self.p)[0]
        self.p += 8
        return v

    def raw(self, n):
        self.need(n)
        v = bytes(self.d[self.p:self.p + n])
        self.p += n
        return v

    def name(self):
        n = self.u32()
        try:
            return self.raw(n).decode()
        except UnicodeDecodeError:
            raise WbcError("invalid UTF-8 in name")

    def blob(self):
        return self.raw(self.u32())

    def vt(self):
        code = self.u8()
        return Ref(self.u32()) if code == REF else code


# -- instructions --------------------------------------------------------------------
@dataclass
class Instr:
    pc: int
    size: int
    op: int
    name: str
    imms: tuple

    def target(self):
        """Absolute pc of a label immediate."""
        return self.pc + self.size + self.imms[0]


def decode_code(code: bytes) -> list:
    out = []
    r = Reader(code)
    while not r.eof():
        pc = r.p
        op = r.u8()
        if op in BY_CODE:
            name, imm = BY_CODE[op]
        elif op in LATER_TIER_OPS:
            raise WbcError(f"opcode 0x{op:02X} ({LATER_TIER_OPS[op]}) is not supported by this VM")
        else:
            raise WbcError(f"invalid opcode 0x{op:02X} at pc {pc}")
        if imm == "":
            imms = ()
        elif imm == "L":
            imms = (r.sleb(32),)
        elif imm == "u":
            imms = (r.u32(),)
        elif imm == "s":
            imms = (r.sleb(32),)
        elif imm == "S":
            imms = (r.sleb(64),)
        elif imm == "f":
            imms = (r.f32(),)
        elif imm == "d":
            imms = (r.f64(),)
        elif imm == "T":
            n = r.u32()
            imms = tuple(r.sleb(32) for _ in range(n + 1))
        else:
            raise AssertionError(imm)
        out.append(Instr(pc, r.p - pc, op, name, imms))
    return out


def encode_instr(w: Writer, name: str, imms: tuple):
    code, imm = OPS[name]
    w.u8(code)
    if imm == "L":
        w.sleb5(imms[0])
    elif imm == "u":
        w.u32(imms[0])
    elif imm in ("s", "S"):
        w.sleb(imms[0])
    elif imm == "f":
        w.f32(imms[0])
    elif imm == "d":
        w.f64(imms[0])
    elif imm == "T":
        raise NotImplementedError("br_table is not emitted by this compiler")


def instr_size(name: str, imms: tuple) -> int:
    w = Writer()
    encode_instr(w, name, imms)
    return len(w.b)


# -- module --------------------------------------------------------------------------
@dataclass
class Body:
    locals: list            # expanded list of valtypes (params excluded)
    max_stack: int
    max_cont: int
    code: bytes


@dataclass
class WbcModule:
    flags: int = 0
    types: list = field(default_factory=list)      # [(params[vt], results[vt]) | ArrayType]
    imports: list = field(default_factory=list)    # [(module, field, typeidx, flags)]
    funcs: list = field(default_factory=list)      # [(typeidx, flags)]
    globals: list = field(default_factory=list)    # [(vt, mut, init)]
    exports: list = field(default_factory=list)    # [(name, kind, index, flags)]
    data: list = field(default_factory=list)       # [str]
    bodies: list = field(default_factory=list)     # [Body]
    customs: list = field(default_factory=list)    # [(name, bytes)]

    def custom(self, name):
        for n, payload in self.customs:
            if n == name:
                return payload
        return None

    def func_type(self, fidx):
        """(params, results, flags) for a function index (imports first)."""
        if fidx < len(self.imports):
            imp = self.imports[fidx]
            return (*self.types[imp[2]], imp[3])
        t, flags = self.funcs[fidx - len(self.imports)]
        return (*self.types[t], flags)


def _write_const(w: Writer, vt, value):
    if isinstance(vt, Ref):
        return                       # references start empty (an empty array)
    if vt == I32:
        w.raw(struct.pack("<q", value))
    elif vt == I64:
        w.raw(struct.pack("<q", value))
    elif vt == F32:
        w.raw(struct.pack("<f", value) + bytes(4))
    elif vt == F64:
        w.raw(struct.pack("<d", value))
    elif vt == STRING:
        w.u32(value)
    else:
        raise WbcError(f"bad const type {vt}")


def _read_const(r: Reader, vt):
    if isinstance(vt, Ref):
        return None
    if vt in (I32, I64):
        return struct.unpack("<q", r.raw(8))[0]
    if vt == F32:
        return struct.unpack("<f", r.raw(8)[:4])[0]
    if vt == F64:
        return struct.unpack("<d", r.raw(8))[0]
    if vt == STRING:
        return r.u32()
    raise WbcError(f"bad const type 0x{vt:02X}")


def encode_module(m: WbcModule) -> bytes:
    out = Writer()
    out.raw(MAGIC)
    out.raw(struct.pack("<I", VERSION))
    out.raw(struct.pack("<I", m.flags))

    def section(sid, w: Writer):
        out.u8(sid)
        out.blob(bytes(w.b))

    w = Writer()
    w.u32(len(m.types))
    for entry in m.types:
        if isinstance(entry, ArrayType):
            w.u8(ARRAY_TYPE)
            write_vt(w, entry.elem)
            continue
        params, results = entry
        w.u8(FUNC_TYPE)
        w.u32(len(params))
        for p in params:
            write_vt(w, p)
        w.u32(len(results))
        for r in results:
            write_vt(w, r)
    section(SEC_TYPE, w)

    w = Writer()
    w.u32(len(m.imports))
    for mod, fld, t, flags in m.imports:
        w.name(mod)
        w.name(fld)
        w.u8(0)
        w.u32(t)
        w.u8(flags)
    section(SEC_IMPORT, w)

    w = Writer()
    w.u32(len(m.funcs))
    for t, flags in m.funcs:
        w.u32(t)
        w.u8(flags)
    section(SEC_FUNCTION, w)

    w = Writer()
    w.u32(len(m.globals))
    for vt, mut, init in m.globals:
        write_vt(w, vt)
        w.u8(mut)
        _write_const(w, vt, init)
    section(SEC_GLOBAL, w)

    w = Writer()
    w.u32(len(m.exports))
    for name, kind, index, flags in m.exports:
        w.name(name)
        w.u8(kind)
        w.u32(index)
        w.u8(flags)
    section(SEC_EXPORT, w)

    w = Writer()
    w.u32(len(m.data))
    for s in m.data:
        w.blob(s.encode())
    section(SEC_DATA, w)

    w = Writer()
    w.u32(len(m.bodies))
    for body in m.bodies:
        bw = Writer()
        groups = []
        for vt in body.locals:
            if groups and groups[-1][1] == vt:
                groups[-1][0] += 1
            else:
                groups.append([1, vt])
        bw.u32(len(groups))
        for count, vt in groups:
            bw.u32(count)
            write_vt(bw, vt)
        bw.u32(body.max_stack)
        bw.u32(body.max_cont)
        bw.raw(body.code)
        w.blob(bytes(bw.b))
    section(SEC_CODE, w)

    for name, payload in m.customs:
        w = Writer()
        w.name(name)
        w.raw(payload)
        section(SEC_CUSTOM, w)
    return bytes(out.b)


def decode_module(data: bytes) -> WbcModule:
    if len(data) < 12 or data[:4] != MAGIC:
        raise WbcError("not a WBC module (bad magic)")
    version, flags = struct.unpack_from("<II", data, 4)
    if version != VERSION:
        raise WbcError(f"unsupported WBC version {version}")
    if flags & ~FLAG_HAS_SOURCE:
        raise WbcError(f"module requires unknown features (flags 0x{flags:08X})")
    m = WbcModule(flags=flags)
    r = Reader(data, 12)
    last = 0
    while not r.eof():
        sid = r.u8()
        size = r.u32()
        r.need(size)
        s = Reader(data, r.p, r.p + size)
        r.p += size
        if sid == SEC_CUSTOM:
            name = s.name()
            m.customs.append((name, bytes(data[s.p:s.end])))
            continue
        if sid > SEC_CODE:
            raise WbcError(f"unknown section id {sid}")
        if sid <= last:
            raise WbcError(f"section {sid} out of order")
        last = sid
        if sid == SEC_TYPE:
            for _ in range(s.u32()):
                code = s.u8()
                if code == ARRAY_TYPE:
                    m.types.append(ArrayType(s.vt()))
                    continue
                if code != FUNC_TYPE:
                    raise WbcError(f"type entry 0x{code:02X} is not supported by this VM")
                params = [s.vt() for _ in range(s.u32())]
                results = [s.vt() for _ in range(s.u32())]
                m.types.append((params, results))
        elif sid == SEC_IMPORT:
            for _ in range(s.u32()):
                mod, fld = s.name(), s.name()
                if s.u8() != 0:
                    raise WbcError("only function imports are supported")
                m.imports.append((mod, fld, s.u32(), s.u8()))
        elif sid == SEC_FUNCTION:
            for _ in range(s.u32()):
                m.funcs.append((s.u32(), s.u8()))
        elif sid == SEC_GLOBAL:
            for _ in range(s.u32()):
                vt, mut = s.vt(), s.u8()
                m.globals.append((vt, mut, _read_const(s, vt)))
        elif sid == SEC_EXPORT:
            for _ in range(s.u32()):
                m.exports.append((s.name(), s.u8(), s.u32(), s.u8()))
        elif sid == SEC_DATA:
            for _ in range(s.u32()):
                try:
                    m.data.append(s.blob().decode())
                except UnicodeDecodeError:
                    raise WbcError("invalid UTF-8 in data section")
        elif sid == SEC_CODE:
            for _ in range(s.u32()):
                b = Reader(data, s.p, s.p)
                size = s.u32()
                s.need(size)
                b = Reader(data, s.p, s.p + size)
                s.p += size
                locs = []
                for _ in range(b.u32()):
                    count, vt = b.u32(), b.vt()
                    if count > 65536 or len(locs) + count > 65536:
                        raise WbcError("too many locals")
                    locs += [vt] * count
                ms, mc = b.u32(), b.u32()
                m.bodies.append(Body(locs, ms, mc, bytes(data[b.p:b.end])))
        if not s.eof():
            raise WbcError(f"section {sid} has trailing bytes")
    return m
