"""Lexer and parser for `.wiret` text (spec sections 2.1 to 2.4)."""
from __future__ import annotations

import re
from typing import Optional

from .model import (Attr, Binding, Box, Class, Comment, Dispatcher, IfaceMethod, Interface, Const, Enum, EnumMember, ExecOut, Extern,
                    Field, Graph, Lit, Local, Module, Node, Param, PinRef, Place, Struct, Use,
                    Var)

KEYWORDS = set("wiret module use extern const var local enum struct interface class impl macro "
               "func event dispatcher node state flow layout box at size".split())

MARKUP_HINT = ("the 'markup' block was removed: write each note as #[note(\"...\")] on its own "
               "line directly above the node, box or graph it explains")

UNSUPPORTED_ITEMS = set()

INT_TYPES = {"i8", "u8", "i16", "u16", "i32", "u32", "i64", "u64"}


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
        elif text.startswith(("->", "<-", "::", "#["), i):
            toks.append(Tok("punct", text[i:i + 2], line, col))
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
        self.pending_methods = []  # methods of the class just parsed

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
        meta = self.meta_lines()
        if not self.at_kw("module"):
            self.error("expected 'module'")
        self.next()
        mod = Module(version, self.qname(), self.attrs(), meta=meta)
        self.end_stmt()
        while not self.at("eof"):
            meta = self.meta_lines()
            it = self.item()
            it.meta = meta
            mod.items.append(it)
            if isinstance(it, Class):     # its methods are items of their own (model.Graph)
                mod.items.extend(self.pending_methods)
                self.pending_methods = []
            self.skip_nl()
        mod.comments = self.attach_comments()
        resolve_enum_values(mod)
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
            raise ParseError(f"'{kw}' declarations are Tier 2 and not supported by this prototype",
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
        if kw == "struct":
            return self.struct()
        if kw == "enum":
            return self.enum()
        if kw == "class":
            return self.class_decl()
        if kw == "interface":
            return self.interface()
        if kw in ("func", "event", "macro"):
            return self.graph(kw, start)
        self.error("expected a declaration")

    def graph(self, kw: str, start: int, owner: Optional[str] = None) -> Graph:
        short = self.ident()
        g = Graph(kw, f"{owner}.{short}" if owner else short, owner=owner)
        self.anchors.append((start, ("graph", g.name)))
        if self.at_p("::"):
            if owner:
                self.error("methods take no type parameters")
            g.tparams = self.generic_args(self.ident)
        elif self.at_p("<"):
            self.generics_hint()
        g.params = self.params()
        if self.at_p("->"):
            self.next()
            g.results = self.params()
        g.attrs = self.attrs()
        self.body(g)
        return g

    def class_decl(self) -> Class:
        """`class Name [: Base] @attrs { field | func | event ... }` (section 2.2). The methods
        are collected in `pending_methods`, and the module adds them after the class."""
        c = Class(self.ident("class name"))
        if self.at_p("::") or self.at_p("<"):
            self.error("classes take no type parameters")
        if self.at_p(":"):
            self.next()
            c.base = self.qname()
        if self.at_kw("impl"):
            self.next()
            c.impls.append(self.qname())
            while self.at_p(","):
                self.next()
                c.impls.append(self.qname())
        c.attrs = self.attrs()
        self.expect_p("{")
        self.skip_nl()
        while not self.at_p("}"):
            meta = self.meta_lines()
            if self.at_kw("func") or self.at_kw("event"):
                start = self.i
                kw = self.next().value
                g = self.graph(kw, start, owner=c.name)
                g.meta = meta
                self.pending_methods.append(g)
                self.skip_nl()
                continue
            if self.at_kw("dispatcher"):
                self.next()
                d = Dispatcher(self.ident("dispatcher name"), meta=meta)
                d.params = self.params()
                if self.at_p("->"):
                    self.error("a dispatcher has no results: its handlers' results would have "
                               "nowhere to go")
                d.attrs = self.attrs()
                c.dispatchers.append(d)
                self.end_stmt()
                continue
            if self.at_kw("macro"):
                self.error("a class cannot declare a macro; declare it at module level")
            if not self.at("id"):
                self.error("expected a field, func or event")
            name = self.ident("field name")
            self.expect_p(":")
            ty = self.type()
            default = None
            if self.at_p("="):
                self.next()
                default = self.literal()
            c.fields.append(Field(name, ty, default, self.attrs(), meta))
            self.end_stmt()
        self.next()
        self.end_stmt()
        return c

    def members(self, what: str, member) -> list:
        """The `{ ... }` of a struct or enum: one member per line, each may have metadata lines."""
        self.expect_p("{")
        self.skip_nl()
        out = []
        while not self.at_p("}"):
            meta = self.meta_lines()
            if not self.at("id"):
                self.error(f"expected {what}")
            m = member()
            m.meta = meta
            out.append(m)
            self.end_stmt()
        self.next()
        self.end_stmt()
        return out

    def struct(self) -> Struct:
        """`struct Name @attrs { field: type [= default] @attrs ... }` (section 2.2)."""
        st = Struct(self.ident("struct name"))
        if self.at_p("::") or self.at_p("<"):
            self.error("structs take no type parameters")
        st.attrs = self.attrs()

        def field():
            name = self.ident("field name")
            self.expect_p(":")
            ty = self.type()
            default = None
            if self.at_p("="):
                self.next()
                default = self.literal()
            return Field(name, ty, default, self.attrs())

        st.fields = self.members("a field ('name: type')", field)
        return st

    def interface(self) -> Interface:
        """`interface Name @attrs { func Name(params) [-> (results)] @attrs ... }` (2.2)."""
        it = Interface(self.ident("interface name"))
        if self.at_p("::") or self.at_p("<"):
            self.error("interfaces take no type parameters")
        it.attrs = self.attrs()

        def method():
            if not self.at_kw("func"):
                self.error("an interface lists methods, written 'func Name(params) -> (results)'")
            self.next()
            m = IfaceMethod(self.ident("method name"))
            m.params = self.params()
            if self.at_p("->"):
                self.next()
                m.results = self.params()
            m.attrs = self.attrs()
            if self.at_p("{"):
                self.error("an interface method has no body; the classes that implement the "
                           "interface give one")
            return m

        it.methods = self.members("an interface method", method)
        return it

    def enum(self) -> Enum:
        """`enum Name [: inttype] @attrs { Member [= INT] @attrs ... }` (section 2.2)."""
        en = Enum(self.ident("enum name"))
        if self.at_p(":"):
            self.next()
            t = self.peek()
            base = self.ident("integer type")
            if base not in INT_TYPES:
                raise ParseError(f"an enum's underlying type must be an integer type such as "
                                 f"u8 or i32, not '{base}'", t.line, t.col)
            en.base = base
        en.attrs = self.attrs()

        def member():
            m = EnumMember(self.ident("enum member"))
            if self.at_p("="):
                self.next()
                t = self.peek()
                if t.kind != "int" or t.value[1] is not None:
                    self.error("an enum member's value is a plain integer, as in 'Idle = 0'")
                m.value = self.next().value[0]
            m.attrs = self.attrs()
            return m

        en.members = self.members("an enum member", member)
        return en

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
        if self.at_p("<"):
            self.generics_hint()
        if not self.at_p("::"):
            return name
        if name in ("array", "set"):
            self.next()
            self.expect_p("<")
            inner = self.type()
            self.expect_p(">")
            return f"{name}::<{inner}>"
        if name == "map":
            self.next()
            self.expect_p("<")
            k = self.type()
            self.expect_p(",")
            v = self.type()
            self.expect_p(">")
            return f"map::<{k}, {v}>"
        if name in ("delegate", "dispatcher"):
            self.next()
            self.expect_p("<")
            a = self.tlist()
            r = ""
            if self.at_p("->"):
                self.next()
                r = " -> " + self.tlist()
                if r == " -> ()":            # no results: written the short way
                    r = ""
            self.expect_p(">")
            return f"{name}::<{a}{r}>"
        self.error(f"'{name}' takes no type arguments")

    def generic_args(self, item) -> list:
        """`::<a, b>`: the type arguments of a node, or the type parameters of a declaration."""
        self.expect_p("::")
        self.expect_p("<")
        out = [item()]
        while self.at_p(","):
            self.next()
            out.append(item())
        self.expect_p(">")
        return out

    def generics_hint(self):
        self.error("type arguments are written with '::<', as in Add::<i32> or array::<i32>")

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
        """Trailing semantic attributes, `@name` or `@name(args)` (section 2.4)."""
        out = []
        while self.at_p("@"):
            self.next()
            name = self.qname()
            out.append(Attr(name, self.attr_args() if self.at_p("(") else None))
        return out

    def attr_args(self) -> list:
        self.expect_p("(")
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
            elif not self.at_p(")"):
                self.error("expected ',' or ')'")
        self.next()
        return args

    def meta_lines(self) -> list:
        """`#[name(args)]` lines, each directly above the statement they describe (section 2.4)."""
        out = []
        while self.at_p("#["):
            t = self.next()
            name = self.qname()
            out.append(Attr(name, self.attr_args() if self.at_p("(") else None))
            self.expect_p("]")
            if not self.at("nl"):
                self.error("a metadata line ends at its ']'; put the statement it describes on "
                           "the next line")
            self.next()
            if self.at("nl") or self.at_p("}") or self.at("eof"):
                raise ParseError("a metadata line must stand directly above the statement it "
                                 "describes, with no blank line between", t.line, t.col)
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
        if t.kind == "id" and self.at_p(".", 1) and self.at("id", k=2):
            name = self.qname()
            if name.count(".") == 1:
                return Lit("enum", name)
            raise ParseError(f"an enum value is written 'Enum.Member', not '{name}'",
                             t.line, t.col)
        self.error("expected a literal")

    # -- graph bodies --------------------------------------------------------
    def body(self, g: Graph):
        self.expect_p("{")
        self.skip_nl()
        wires = []
        while not self.at_p("}"):
            mt = self.peek()
            meta = self.meta_lines()
            t = self.peek()
            if meta and not (self.at_kw("local") or self.at_kw("state") or self.at_kw("node")):
                raise ParseError("in a graph body, a metadata line may only stand above a "
                                 "'local', 'state' or 'node' statement", mt.line, mt.col)
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
                    Local(name, ty, default, self.attrs(), meta))
                self.end_stmt()
            elif self.at_kw("node"):
                self.anchors.append((self.i, None))
                self.next()
                n = self.node()
                n.meta = meta
                self.anchors[-1] = (self.anchors[-1][0], ("node", g.name, n.id))
                g.nodes.append(n)
                self.end_stmt()
            elif self.at_kw("flow"):
                self.next()
                wires.extend(self.flow())
            elif self.at_kw("markup"):
                self.error(MARKUP_HINT)
            elif self.at_kw("layout"):
                self.next()
                self.layout(g)
            else:
                self.error("expected 'local', 'state', 'node', 'flow' or 'layout'")
        self.next()
        self.end_stmt()
        nodes = {n.id: n for n in g.nodes}
        for tok, src, pin, e in wires:
            if src not in nodes:
                raise ParseError(f"flow wire starts at '{src}', which is not a node of "
                                 f"'{g.name}'", tok.line, tok.col)
            nodes[src].execs.append(ExecOut(pin, *e))

    def node(self) -> Node:
        """`node id = Kind[::<targs>] [symbol] @attrs`, then one `.pin <- value` line per input."""
        nid = self.ident("node id")
        self.expect_p("=")
        kind = self.ident("node kind")
        n = Node(nid, kind)
        if self.at("id"):
            n.symbol = self.qname()
        if self.at_p("<"):
            self.generics_hint()
        if self.at_p("::"):
            n.targs = self.generic_args(self.type)
            # `ArrayAdd::<i32> acc` (section 3.3) writes the symbol after the type arguments
            if n.symbol is None and self.at("id"):
                n.symbol = self.qname()
        if self.at_p("("):
            self.error("node inputs go on their own lines below the node, one per line, "
                       "as in '.pin <- value'")
        n.attrs.extend(self.attrs())
        if self.at_p("->") or self.at_p("{"):
            self.error("exec wires go in the graph's 'flow' block, not on the node line "
                       f"(write '{nid} -> target' there)")
        while self.at("nl"):
            j = self.i
            while self.toks[j].kind == "nl":
                j += 1
            if not (self.toks[j].kind == "punct" and self.toks[j].value == "."):
                break
            self.i = j + 1
            pin = self.ident("pin name")
            self.expect_p("<-")
            if self.at("id") and self.at_p(".", 1):
                node = self.ident()
                self.next()
                val = PinRef(node, self.ident("pin name"))
            else:
                val = self.literal()
            n.bindings.append(Binding(pin, val))
        return n

    def endpoint(self, what):
        node = self.ident(what)
        pin = None
        if self.at_p("."):
            self.next()
            pin = self.ident("exec pin")
        return node, pin

    def flow(self) -> list:
        """`flow { src[.pin] -> dst[.pin] ... }`; returns (token, src, pin, (dst, dst_pin))."""
        self.expect_p("{")
        self.skip_nl()
        out = []
        while not self.at_p("}"):
            tok = self.peek()
            if self.at_p("#["):
                self.error("flow wires cannot carry metadata; put a note above the node instead")
            src, pin = self.endpoint("exec source")
            self.expect_p("->")
            out.append((tok, src, pin, self.endpoint("exec target")))
            self.end_stmt()
        self.next()
        self.end_stmt()
        return out

    def layout(self, g: Graph):
        self.expect_p("{")
        self.skip_nl()
        while not self.at_p("}"):
            mt = self.peek()
            meta = self.meta_lines()
            if meta and not self.at_kw("box"):
                raise ParseError("in a layout block, a metadata line may only stand above a "
                                 "'box' line", mt.line, mt.col)
            if self.at_kw("box"):
                self.next()
                bid = self.ident("box id")
                title = self.expect("str", None, "box title").value
                self.expect("id", "at")
                x, y = self.int_pair()
                self.expect("id", "size")
                w, h = self.int_pair()
                g.boxes.append(Box(bid, x, y, self.props(), title=title, w=w, h=h, meta=meta))
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


def resolve_enum_values(mod: Module):
    """`.pin <- Mode.Chase` reads like a wire from node `Mode`. When the graph has no node
    with that id and the module declares an enum with that name, it is the enum value
    instead. `@cases(Mode.Idle, ...)` arguments become enum values the same way."""
    enums = {it.name for it in mod.items if isinstance(it, Enum)}
    if not enums:
        return
    for g in mod.graphs():
        ids = {n.id for n in g.nodes}
        for n in g.nodes:
            for b in n.bindings:
                v = b.value
                if isinstance(v, PinRef) and v.node in enums and v.node not in ids:
                    b.value = Lit("enum", f"{v.node}.{v.pin}")
            for a in n.attrs:
                if a.name == "cases" and a.args:
                    a.args = [(k, Lit("enum", v.value) if v.kind == "ident"
                               and v.value.count(".") == 1 and v.value.split(".")[0] in enums
                               else v) for k, v in a.args]


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
