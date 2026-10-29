"""Lexer and parser for `.wiret` text (spec sections 2.1 to 2.4)."""
from __future__ import annotations

import re

from .model import (Attr, Binding, Box, Comment, Const, ExecOut, Extern, Graph, Lit, Local,
                    Module, Node, Note, Param, PinRef, Place, Use, Var)

KEYWORDS = set("wiret module use extern const var local enum struct interface class impl macro "
               "func event dispatcher node state notes note on layout box at size".split())

UNSUPPORTED_ITEMS = {"enum", "struct", "interface", "class"}


class ParseError(Exception):
    def __init__(self, msg, line=0, col=0):
        super().__init__(f"{line}:{col}: {msg}")
        self.msg = msg
        self.line = line
        self.col = col


class Tok:
    __slots__ = ("kind", "value", "line", "col")

    def __init__(self, kind, value, line, col):
        self.kind = kind      # id int float str nl punct eof
        self.value = value
        self.line = line
        self.col = col

    def __repr__(self):
        return f"Tok({self.kind},{self.value!r},{self.line}:{self.col})"


_NUM = re.compile(
    r"(?P<body>-?(?:0[xX][0-9A-Fa-f_]+|[0-9][0-9_]*(?:\.[0-9][0-9_]*)?(?:[eE][+-]?[0-9]+)?))"
    r"(?P<suffix>i8|u8|i16|u16|i32|u32|i64|u64|f32|f64)?(?![A-Za-z0-9_])")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def lex(text: str):
    toks, comments = [], []
    i, line, col0 = 0, 1, 0
    n = len(text)
    while i < n:
        c = text[i]
        col = i - col0 + 1
        if c == "\n":
            toks.append(Tok("nl", None, line, col))
            i += 1
            line += 1
            col0 = i
        elif c in " \t\r":
            i += 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            comments.append((line, col, text[i + 2:j].strip(), len(toks)))
            i = j
        elif c == '"':
            i, s = _lex_string(text, i, line, col)
            toks.append(Tok("str", s, line, col))
        elif c.isdigit() or (c == "-" and i + 1 < n and text[i + 1].isdigit()):
            m = _NUM.match(text, i)
            if not m:
                raise ParseError("malformed number", line, col)
            i = m.end()
            body, suffix = m.group("body").replace("_", ""), m.group("suffix")
            if body.lower().lstrip("-").startswith("0x"):
                toks.append(Tok("int", (int(body, 16), suffix), line, col))
            elif any(ch in body for ch in ".eE") or suffix in ("f32", "f64"):
                toks.append(Tok("float", (float(body), suffix), line, col))
            else:
                toks.append(Tok("int", (int(body), suffix), line, col))
        elif c.isalpha() or c == "_":
            m = _IDENT.match(text, i)
            toks.append(Tok("id", m.group(0), line, col))
            i = m.end()
        elif text.startswith("->", i):
            toks.append(Tok("punct", "->", line, col))
            i += 2
        elif c in "(){}[]<>,:=.@":
            toks.append(Tok("punct", c, line, col))
            i += 1
        else:
            raise ParseError(f"unexpected character {c!r}", line, col)
    toks.append(Tok("nl", None, line, 0))
    toks.append(Tok("eof", None, line + 1, 0))
    return toks, comments


def _lex_string(text, i, line, col):
    out = []
    i += 1
    while True:
        if i >= len(text) or text[i] == "\n":
            raise ParseError("unterminated string", line, col)
        c = text[i]
        if c == '"':
            return i + 1, "".join(out)
        if c == "\\":
            e = text[i + 1:i + 2]
            if e == "n":
                out.append("\n")
            elif e == "t":
                out.append("\t")
            elif e == '"':
                out.append('"')
            elif e == "\\":
                out.append("\\")
            elif e == "u" and text[i + 2:i + 3] == "{":
                j = text.find("}", i)
                out.append(chr(int(text[i + 3:j], 16)))
                i = j + 1
                continue
            else:
                raise ParseError(f"bad escape \\{e}", line, col)
            i += 2
        else:
            out.append(c)
            i += 1


class Parser:
    def __init__(self, text: str):
        self.toks, self.raw_comments = lex(text)
        self.i = 0
        self.anchors = []  # (token index, anchor tuple)

    # -- token helpers -------------------------------------------------------
    def peek(self, k=0) -> Tok:
        return self.toks[min(self.i + k, len(self.toks) - 1)]

    def next(self) -> Tok:
        t = self.toks[self.i]
        self.i += 1
        return t

    def at(self, kind, value=None, k=0) -> bool:
        t = self.peek(k)
        return t.kind == kind and (value is None or t.value == value)

    def at_p(self, value, k=0) -> bool:
        return self.at("punct", value, k)

    def at_kw(self, value, k=0) -> bool:
        return self.at("id", value, k)

    def error(self, msg, tok=None):
        tok = tok or self.peek()
        got = "end of file" if tok.kind == "eof" else ("newline" if tok.kind == "nl" else repr(tok.value))
        raise ParseError(f"{msg} (found {got})", tok.line, tok.col)

    def expect(self, kind, value=None, what=None):
        if not self.at(kind, value):
            self.error(f"expected {what or value or kind}")
        return self.next()

    def expect_p(self, value):
        return self.expect("punct", value)

    def ident(self, what="identifier") -> str:
        return self.expect("id", None, what).value

    def skip_nl(self):
        while self.at("nl"):
            self.i += 1

    def end_stmt(self):
        if self.at_p("}"):
            return
        self.expect("nl", None, "end of line")
        self.skip_nl()

    def qname(self) -> str:
        parts = [self.ident()]
        while self.at_p(".") and self.at("id", k=1):
            self.next()
            parts.append(self.ident())
        return ".".join(parts)

    # -- module --------------------------------------------------------------
    def parse_module(self) -> Module:
        self.skip_nl()
        if not self.at_kw("wiret"):
            self.error("a .wiret file must start with 'wiret 1'")
        self.next()
        version = self.expect("int", None, "version number").value[0]
        if version > 1:
            raise ParseError(f"unsupported wiret version {version}", self.peek().line, 0)
        self.end_stmt()
        if not self.at_kw("module"):
            self.error("expected 'module'")
        self.next()
        mod = Module(version, self.qname(), self.attrs())
        self.end_stmt()
        while not self.at("eof"):
            mod.items.append(self.item())
            self.skip_nl()
        mod.comments = self.attach_comments()
        return mod

    def attach_comments(self):
        out = []
        for line, _col, text, tok_index in self.raw_comments:
            anchor = None
            for idx, a in self.anchors:
                if idx >= tok_index:
                    anchor = a
                    break
            out.append(Comment(line, text, anchor))
        return out

    def item(self):
        t = self.peek()
        if t.kind != "id":
            self.error("expected a declaration")
        kw = t.value
        if kw in UNSUPPORTED_ITEMS:
            raise ParseError(f"'{kw}' declarations are Tier 1/2 and not supported by this prototype",
                             t.line, t.col)
        start = self.i
        self.next()
        if kw == "use":
            name = self.qname()
            alias = None
            if self.at_kw("as"):
                self.next()
                alias = self.ident()
            it = Use(name, alias, self.attrs())
            self.end_stmt()
            return it
        if kw == "extern":
            if self.at_kw("type"):
                self.next()
                it = Extern("type", self.qname(), attrs=[])
                it.attrs = self.attrs()
            else:
                self.expect("id", "func")
                name = self.qname()
                params = self.params()
                results = None
                if self.at_p("->"):
                    self.next()
                    results = self.params()
                it = Extern("func", name, params, results, self.attrs())
            self.end_stmt()
            return it
        if kw == "const":
            name = self.ident()
            self.expect_p(":")
            ty = self.type()
            self.expect_p("=")
            value = self.literal()
            it = Const(name, ty, value, self.attrs())
            self.end_stmt()
            return it
        if kw == "var":
            name = self.ident()
            self.expect_p(":")
            ty = self.type()
            default = None
            if self.at_p("="):
                self.next()
                default = self.literal()
            it = Var(name, ty, default, self.attrs())
            self.end_stmt()
            return it
        if kw in ("func", "event", "macro"):
            g = Graph(kw, self.ident())
            self.anchors.append((start, ("graph", g.name)))
            if self.at_p("<"):
                self.next()
                g.tparams.append(self.ident())
                while self.at_p(","):
                    self.next()
                    g.tparams.append(self.ident())
                self.expect_p(">")
            g.params = self.params()
            if self.at_p("->"):
                self.next()
                g.results = self.params()
            g.attrs = self.attrs()
            self.body(g)
            return g
        self.error("expected a declaration")

    def params(self) -> list:
        self.expect_p("(")
        out = []
        self.skip_nl()
        while not self.at_p(")"):
            name = self.ident("parameter name")
            self.expect_p(":")
            ty = self.type()
            default = None
            if self.at_p("="):
                self.next()
                default = self.literal()
            out.append(Param(name, ty, default, self.attrs()))
            self.skip_nl()
            if self.at_p(","):
                self.next()
                self.skip_nl()
            elif not self.at_p(")"):
                self.error("expected ',' or ')'")
        self.next()
        return out

    def type(self) -> str:
        if self.at_p("("):
            return self.tlist()
        name = self.qname()
        if name in ("array", "set") and self.at_p("<"):
            self.next()
            inner = self.type()
            self.expect_p(">")
            return f"{name}<{inner}>"
        if name == "map" and self.at_p("<"):
            self.next()
            k = self.type()
            self.expect_p(",")
            v = self.type()
            self.expect_p(">")
            return f"map<{k}, {v}>"
        if name in ("delegate", "dispatcher") and self.at_p("<"):
            self.next()
            a = self.tlist()
            r = ""
            if self.at_p("->"):
                self.next()
                r = " -> " + self.tlist()
            self.expect_p(">")
            return f"{name}<{a}{r}>"
        return name

    def tlist(self) -> str:
        self.expect_p("(")
        ts = []
        while not self.at_p(")"):
            ts.append(self.type())
            if self.at_p(","):
                self.next()
        self.next()
        return "(" + ", ".join(ts) + ")"

    # -- attributes and values -----------------------------------------------
    def attrs(self) -> list:
        out = []
        while self.at_p("@"):
            self.next()
            name = self.qname()
            args = None
            if self.at_p("("):
                self.next()
                args = []
                self.skip_nl()
                while not self.at_p(")"):
                    key = None
                    if self.at("id") and self.at_p(":", 1):
                        key = self.ident()
                        self.next()
                    args.append((key, self.value()))
                    self.skip_nl()
                    if self.at_p(","):
                        self.next()
                        self.skip_nl()
                self.next()
            out.append(Attr(name, args))
        return out

    def value(self) -> Lit:
        if self.at_p("("):
            return Lit("tuple", self._seq("(", ")"))
        if self.at_p("["):
            return Lit("list", self._seq("[", "]"))
        if self.at_p("{"):
            self.next()
            pairs = []
            self.skip_nl()
            while not self.at_p("}"):
                k = self.value()
                self.expect_p(":")
                pairs.append((k, self.value()))
                self.skip_nl()
                if self.at_p(","):
                    self.next()
                    self.skip_nl()
            self.next()
            return Lit("map", pairs)
        if self.at("id") and self.peek().value not in ("true", "false", "null"):
            return Lit("ident", self.qname())
        return self.literal()

    def _seq(self, open_, close):
        self.expect_p(open_)
        items = []
        self.skip_nl()
        while not self.at_p(close):
            items.append(self.value())
            self.skip_nl()
            if self.at_p(","):
                self.next()
                self.skip_nl()
        self.next()
        return items

    def literal(self) -> Lit:
        t = self.peek()
        if t.kind == "int":
            self.next()
            return Lit("int", t.value[0], t.value[1])
        if t.kind == "float":
            self.next()
            return Lit("float", t.value[0], t.value[1])
        if t.kind == "str":
            self.next()
            return Lit("string", t.value)
        if t.kind == "id" and t.value in ("true", "false"):
            self.next()
            return Lit("bool", t.value == "true")
        if t.kind == "id" and t.value == "null":
            self.next()
            return Lit("null", None)
        self.error("expected a literal")

    # -- graph bodies --------------------------------------------------------
    def body(self, g: Graph):
        self.expect_p("{")
        self.skip_nl()
        while not self.at_p("}"):
            t = self.peek()
            if self.at_kw("local") or self.at_kw("state"):
                self.next()
                name = self.ident()
                self.expect_p(":")
                ty = self.type()
                default = None
                if self.at_p("="):
                    self.next()
                    default = self.literal()
                (g.locals if t.value == "local" else g.states).append(
                    Local(name, ty, default, self.attrs()))
                self.end_stmt()
            elif self.at_kw("node"):
                self.anchors.append((self.i, None))
                self.next()
                n = self.node()
                self.anchors[-1] = (self.anchors[-1][0], ("node", g.name, n.id))
                g.nodes.append(n)
                self.end_stmt()
            elif self.at_kw("notes"):
                self.next()
                self.notes(g)
            elif self.at_kw("layout"):
                self.next()
                self.layout(g)
            else:
                self.error("expected 'local', 'state', 'node', 'notes' or 'layout'")
        self.next()
        self.end_stmt()

    def node(self) -> Node:
        nid = self.ident("node id")
        self.expect_p("=")
        kind = self.ident("node kind")
        n = Node(nid, kind)
        if self.at("id"):
            n.symbol = self.qname()
        if self.at_p("<"):
            self.next()
            n.targs.append(self.type())
            while self.at_p(","):
                self.next()
                n.targs.append(self.type())
            self.expect_p(">")
            # `ArrayAdd<i32> acc (...)` (section 3.3) writes the symbol after the type arguments
            if n.symbol is None and self.at("id"):
                n.symbol = self.qname()
        if self.at_p("("):
            self.next()
            self.skip_nl()
            while not self.at_p(")"):
                pin = self.ident("pin name")
                self.expect_p(":")
                if self.at("id") and self.at_p(".", 1):
                    node = self.ident()
                    self.next()
                    val = PinRef(node, self.ident("pin name"))
                else:
                    val = self.literal()
                n.bindings.append(Binding(pin, val))
                self.skip_nl()
                if self.at_p(","):
                    self.next()
                    self.skip_nl()
                elif not self.at_p(")"):
                    self.error("expected ',' or ')'")
            self.next()
        seen_exec = False
        while True:
            if self.at_p("@"):
                n.attrs.extend(self.attrs())
            elif not seen_exec and self.at_p("->"):
                self.next()
                n.execs.append(ExecOut(None, *self.target()))
                seen_exec = True
            elif not seen_exec and self.at_p("{"):
                self.next()
                self.skip_nl()
                while not self.at_p("}"):
                    pin = self.ident("exec pin")
                    self.expect_p("->")
                    n.execs.append(ExecOut(pin, *self.target()))
                    self.skip_nl()
                    if self.at_p(","):
                        self.next()
                        self.skip_nl()
                    elif not self.at_p("}"):
                        self.error("expected ',' or '}'")
                self.next()
                seen_exec = True
            else:
                break
        return n

    def target(self):
        node = self.ident("exec target")
        pin = None
        if self.at_p("."):
            self.next()
            pin = self.ident()
        return node, pin

    def notes(self, g: Graph):
        self.expect_p("{")
        self.skip_nl()
        while not self.at_p("}"):
            if not self.at_kw("note"):
                self.error("expected 'note'")
            self.next()
            nid = self.ident("note id")
            on = None
            if self.at_kw("on"):
                self.next()
                on = self.ident()
            text = self.expect("str", None, "note text").value
            g.notes.append(Note(nid, on, text, self.attrs()))
            self.end_stmt()
        self.next()
        self.end_stmt()

    def layout(self, g: Graph):
        self.expect_p("{")
        self.skip_nl()
        while not self.at_p("}"):
            if self.at_kw("box"):
                self.next()
                bid = self.ident("box id")
                title = self.expect("str", None, "box title").value
                self.expect("id", "at")
                x, y = self.int_pair()
                self.expect("id", "size")
                w, h = self.int_pair()
                g.boxes.append(Box(bid, x, y, self.props(), title=title, w=w, h=h))
            else:
                nid = self.ident("node id")
                self.expect("id", "at")
                x, y = self.int_pair()
                g.places.append(Place(nid, x, y, self.props()))
            self.end_stmt()
        self.next()
        self.end_stmt()

    def int_pair(self):
        self.expect_p("(")
        a = self.expect("int", None, "integer").value[0]
        self.expect_p(",")
        b = self.expect("int", None, "integer").value[0]
        self.expect_p(")")
        return a, b

    def props(self) -> list:
        if not self.at_p("["):
            return []
        self.next()
        out = []
        self.skip_nl()
        while not self.at_p("]"):
            k = self.qname()
            self.expect_p("=")
            out.append((k, self.value()))
            self.skip_nl()
            if self.at_p(","):
                self.next()
                self.skip_nl()
        self.next()
        return out


def parse(text: str) -> Module:
    return Parser(text).parse_module()


def parse_literal(text: str) -> Lit:
    """Parse a single literal, as typed into an editor field."""
    p = Parser(text)
    p.skip_nl()
    lit = p.literal()
    p.skip_nl()
    if not p.at("eof"):
        p.error("unexpected text after literal")
    return lit
