"""Lexer and parser for `.wiret` text (spec sections 2.1 to 2.4)."""
from __future__ import annotations

import re
from typing import Optional

from .model import (Attr, Binding, Box, Class, Comment, Dispatcher, IfaceMethod, Interface, Const, Enum, EnumMember, ExecOut, Extern,
                    Field, Graph, Lit, Local, Module, Node, Param, PinRef, Place, Struct, Use,
                    Var)

KEYWORDS = set("wiret module use extern const var local enum struct interface class impl macro "
               "func event dispatcher node state flow layout box at size".split())
# Keywords are contextual (section 2.1): each is a keyword only where a statement of its kind
# can start, so `size`, `state` or `func` is a fine name for a field, pin, local or node. Only
# these words can never be a name, since they are values wherever a value can stand.
RESERVED = {"true", "false", "null"}

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
            raw = text[i + 2:j].rstrip()
            own = not toks or toks[-1].kind == "nl"      # nothing before it on its line
            comments.append((line, col, raw.strip(), len(toks), own,
                             raw[1:] if raw.startswith(" ") else raw))
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
        self.graph_name = None     # the graph whose body is being parsed
        # own-line `//` comments by line, and those attached to an element so far (2.1)
        self.own = {c[0]: k for k, c in enumerate(self.raw_comments) if c[4]}
        self.taken = set()
        self.defaults = []         # (graph, PinRef, inline node, token): outputs left implicit
        self.bare = None           # the parameters an expression body names bare

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

    def lead_comments(self, top: int, stmt: int) -> list:
        """The `//` lines attached to a statement on line `stmt` whose metadata lines start
        on line `top`: the comment lines among its metadata lines, and the run of comment
        lines directly above, with no blank line between (section 2.1)."""
        free = lambda l: l in self.own and self.own[l] not in self.taken
        above, l = [], top - 1
        while free(l):
            above.append(self.own[l])
            l -= 1
        ks = above[::-1] + [self.own[l] for l in range(top, stmt) if free(l)]
        self.taken.update(ks)
        return [self.raw_comments[k][5] for k in ks]

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
        t0 = self.peek()
        meta = self.meta_lines()
        if not self.at_kw("module"):
            self.error("expected 'module'")
        mt = self.next()
        mod = Module(version, self.qname(), self.attrs(), meta=meta)
        mod.comment = self.lead_comments(t0.line, mt.line)
        self.end_stmt()
        while not self.at("eof"):
            t0 = self.peek()
            meta = self.meta_lines()
            st = self.peek()
            it = self.item()
            it.meta = meta
            it.comment = self.lead_comments(t0.line, st.line)
            mod.items.append(it)
            if isinstance(it, Class):     # its methods are items of their own (model.Graph)
                mod.items.extend(self.pending_methods)
                self.pending_methods = []
            self.skip_nl()
        mod.comments = self.attach_comments()
        resolve_enum_values(mod)
        self.resolve_defaults(mod)
        return mod

    def resolve_defaults(self, mod: Module):
        """A node written without `.pin`, inline or as a declared node's id, feeds in its one
        data output (section 2.3). Which output that is depends on the node's signature, known
        once the whole module is read."""
        if not self.defaults:
            return
        from .registry import ModuleIndex, signature
        idx = ModuleIndex(mod)
        graphs = {g.name: g for g in mod.graphs()}
        for gname, ref, n, tok in self.defaults:
            what = f"{n.kind}(...)" if n is not None else ref.node
            if n is None:
                n = graphs[gname].node(ref.node)
                if n is None:           # kept as written; the checker reports it (E0101)
                    ref.pin = ""
                    continue
            sig = signature(n, graphs[gname], idx)
            outs = sig.data_outs
            if len(outs) == 1:
                ref.pin = outs[0].name
            elif sig.error:
                ref.pin = "result"      # the checker reports the node itself
            elif not outs:
                raise ParseError(f"'{what}' has no output to feed into this input",
                                 tok.line, tok.col)
            else:
                names = ", ".join(o.name for o in outs)
                raise ParseError(f"'{what}' has several outputs ({names}); name the one this "
                                 f"input reads, as in '{what}.{outs[0].name}'",
                                 tok.line, tok.col)

    def attach_comments(self):
        out = []
        for k, (line, _col, text, tok_index, _own, _raw) in enumerate(self.raw_comments):
            if k in self.taken:
                continue
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
        if self.at_p("="):
            self.expr_body(g)
        else:
            self.body(g)
        return g

    def expr_body(self, g: Graph):
        """`func F(x: T) -> (r: U) @attrs = value` (section 2.3): an Entry wired to a Return
        whose one input is the value, in which the parameters are named bare (`x`)."""
        t = self.next()
        if g.kind != "func" or g.owner or g.results is None or len(g.results) != 1:
            raise ParseError("only a function with exactly one result, outside a class, is "
                             "written '= value'; give this one a body in braces", t.line, t.col)
        self.graph_name = g.name
        res = g.results[0].name
        self.skip_nl()
        self.bare = {p.name for p in g.params}
        try:
            self.anchors.append((self.i, ("node", g.name, "ret")))
            val, inline = self.input_value(f"ret.{res}")
        finally:
            self.bare = None
        g.nodes = [Node("entry", "Entry", execs=[ExecOut(None, "ret")]),
                   Node("ret", "Return", bindings=[Binding(res, val)])] + inline
        self.end_stmt()

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
            t0 = self.peek()
            meta = self.meta_lines()
            cm = self.lead_comments(t0.line, self.peek().line)
            named = self.at_p(":", 1)           # `name: type`: a field, whatever its name
            if not named and (self.at_kw("func") or self.at_kw("event")):
                start = self.i
                kw = self.next().value
                g = self.graph(kw, start, owner=c.name)
                g.meta, g.comment = meta, cm
                self.pending_methods.append(g)
                self.skip_nl()
                continue
            if not named and self.at_kw("dispatcher"):
                self.next()
                d = Dispatcher(self.ident("dispatcher name"), meta=meta, comment=cm)
                d.params = self.params()
                if self.at_p("->"):
                    self.error("a dispatcher has no results: its handlers' results would have "
                               "nowhere to go")
                d.attrs = self.attrs()
                c.dispatchers.append(d)
                self.end_stmt()
                continue
            if not named and self.at_kw("macro"):
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
            c.fields.append(Field(name, ty, default, self.attrs(), meta, cm))
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
            t0 = self.peek()
            meta = self.meta_lines()
            if not self.at("id"):
                self.error(f"expected {what}")
            cm = self.lead_comments(t0.line, self.peek().line)
            m = member()
            m.meta, m.comment = meta, cm
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
        if self.at("id") and self.at_p("::", 1) and self.at("id", k=2):
            return self.enum_value()
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
        if self.at_p("("):          # a lane literal, `(0, 1, 0)`, nested for a transform (3.1.1)
            items = self._seq("(", ")")
            for x in items:
                if x.kind not in ("int", "float", "tuple"):
                    raise ParseError("a vector literal holds numbers, as in (0, 1.5, 0)",
                                     t.line, t.col)
            return Lit("tuple", items)
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
        if t.kind == "id" and self.at_p("::", 1) and self.at("id", k=2):
            return self.enum_value()
        if t.kind == "id" and self.at_p(".", 1) and self.at("id", k=2):
            name = self.qname()                 # the dotted form of Draft 0.11 and earlier
            if name.count(".") == 1:
                return Lit("enum", name)
            raise ParseError(f"an enum value is written 'Enum::Member', not '{name}'",
                             t.line, t.col)
        self.error("expected a literal")

    def enum_value(self) -> Lit:
        """`Mode::Chase` (section 2.1). `::` followed by a name, never by `<`, so it cannot
        be read as type arguments or as a wire."""
        name = self.ident()
        self.expect_p("::")
        return Lit("enum", f"{name}.{self.ident('enum member')}")

    # -- graph bodies --------------------------------------------------------
    def body(self, g: Graph):
        self.graph_name = g.name
        self.expect_p("{")
        self.skip_nl()
        wires = []
        metas = []      # (token, node id, metadata lines) from the layout block
        while not self.at_p("}"):
            mt = self.peek()
            meta = self.meta_lines()
            t = self.peek()
            if meta and self.at_kw("node"):
                raise ParseError("a node's metadata lines go in the graph's layout block, "
                                 "directly above the node's line there", mt.line, mt.col)
            if meta and not (self.at_kw("local") or self.at_kw("state")):
                raise ParseError("in a graph body, a metadata line may only stand above a "
                                 "'local' or 'state' statement", mt.line, mt.col)
            cm = self.lead_comments(mt.line, t.line) if t.kind == "id" and t.value in (
                "local", "state", "node") else []
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
                    Local(name, ty, default, self.attrs(), meta, cm))
                self.end_stmt()
            elif self.at_kw("node"):
                at = len(self.anchors)
                self.anchors.append((self.i, None))
                self.next()
                ns = self.node()           # adds the anchors of its inline nodes after this one
                self.anchors[at] = (self.anchors[at][0], ("node", g.name, ns[0].id))
                ns[0].comment = cm
                g.nodes.extend(ns)
                self.end_stmt()
            elif self.at_kw("flow"):
                self.next()
                wires.extend(self.flow())
            elif self.at_kw("markup"):
                self.error(MARKUP_HINT)
            elif self.at_kw("layout"):
                self.next()
                self.layout(g, metas)
            else:
                self.error("expected 'local', 'state', 'node', 'flow' or 'layout'")
        self.next()
        self.end_stmt()
        nodes = {n.id: n for n in g.nodes}
        for tok, nid, meta in metas:
            if nid not in nodes:
                # a stale name, usually an inline node whose position in the text changed:
                # kept as written and reported (W0605), never a reason to reject the file
                g.orphan_meta.setdefault(nid, []).extend(meta)
                continue
            nodes[nid].meta.extend(meta)
        for tok, src, pin, e, cm in wires:
            if src not in nodes:
                raise ParseError(f"flow wire starts at '{src}', which is not a node of "
                                 f"'{g.name}'", tok.line, tok.col)
            nodes[src].execs.append(ExecOut(pin, *e, comment=cm))

    def node(self) -> list:
        """`node id = Kind[::<targs>] [symbol](.pin <- value, ...) @attrs` (section 2.3).
        Returns the node, then the nodes written inline in its inputs."""
        nid = self.ident("node id")
        if self.at_p("."):
            self.error("a declared node's id is an identifier; a dotted name such as "
                       "'show.message' belongs to a node written inline in an input")
        self.expect_p("=")
        out = self.node_expr(nid)
        n = out[0]
        n.attrs.extend(self.attrs())
        if self.at_p("->") or self.at_p("{"):
            self.error("exec wires go in the graph's 'flow' block, not on the node line "
                       f"(write '{nid} -> target' there)")
        return out

    def node_expr(self, nid: str) -> list:
        """`Kind [symbol][::<targs>](inputs)`: a node with the given id, then its inline nodes."""
        kind = self.ident("node kind")
        n = Node(nid, kind)
        if self.at("id"):
            n.symbol = self.qname()
        elif kind == "Format" and self.at("str"):      # its template (section 3.3)
            n.symbol = self.next().value
        if self.at_p("<"):
            self.generics_hint()
        if self.at_p("::"):
            n.targs = self.generic_args(self.type)
            # `ArrayAdd::<i32> acc` (section 3.3) writes the symbol after the type arguments
            if n.symbol is None and self.at("id"):
                n.symbol = self.qname()
        if not self.at_p("("):
            j = self.i
            while self.toks[j].kind == "nl":
                j += 1
            if self.toks[j].kind == "punct" and self.toks[j].value == ".":
                self.error("a node's inputs are written in parentheses after it, separated "
                           "by commas: 'Kind(.pin <- value, ...)'")
            self.error(f"expected '(' after the node; a node without inputs is written "
                       f"'{kind}()'")
        self.next()
        out = [n]
        self.skip_nl()
        while not self.at_p(")"):
            if not self.at_p("."):
                self.error("expected an input, '.pin <- value', or ')'")
            cm = self.lead_comments(self.peek().line, self.peek().line)
            self.next()
            pin = self.ident("pin name")
            self.expect_p("<-")
            self.skip_nl()
            val, inline = self.input_value(f"{nid}.{pin}")
            n.bindings.append(Binding(pin, val, cm))
            out.extend(inline)
            self.skip_nl()
            if self.at_p(","):
                self.next()
                self.skip_nl()
            elif not self.at_p(")"):
                self.error("expected ',' or ')' after an input")
        self.next()
        return out

    def input_value(self, path: str):
        """The value bound to an input: a literal, a pin reference `node.pin` (the node may be
        an inline node's dotted name), or a node written inline, `Kind(...).pin`, which gets
        the id `path`; `.pin` may be left out when the node, declared or inline, has one
        data output. In an expression body a parameter is named bare. Returns (value, inline
        nodes)."""
        t = self.peek()
        if t.kind == "id" and self.at_p("::", 1) and self.at("id", k=2):
            return self.enum_value(), []
        if t.kind == "id" and t.value not in ("true", "false", "null"):
            if self.at_p(".", 1):
                parts = self.qname().split(".")
                return PinRef(".".join(parts[:-1]), parts[-1]), []
            if self.bare is not None and t.value in self.bare and not (
                    self.at_p("(", 1) or self.at_p("::", 1) or self.at_p("<", 1)
                    or self.at("id", k=1) or self.at("str", k=1)):
                self.next()
                return PinRef("entry", t.value), []
            if not (self.at_p("(", 1) or self.at_p("::", 1) or self.at_p("<", 1)
                    or self.at("id", k=1) or self.at("str", k=1)):
                self.next()                         # a declared node: its one data output
                ref = PinRef(t.value, None)
                self.defaults.append((self.graph_name, ref, None, t))
                return ref, []
            self.anchors.append((self.i, ("node", self.graph_name, path)))
            inline = self.node_expr(path)
            if not self.at_p("."):
                ref = PinRef(path, None)            # its one data output, resolved later
                self.defaults.append((self.graph_name, ref, inline[0], t))
                return ref, inline
            self.next()
            return PinRef(path, self.ident("pin name")), inline
        return self.literal(), []

    def endpoint(self, what):
        node = self.ident(what)
        pin = None
        if self.at_p("."):
            self.next()
            pin = self.ident("exec pin")
        return node, pin

    def flow(self) -> list:
        """`flow { src[.pin] -> dst[.pin] ... }`; returns (token, src, pin, (dst, dst_pin),
        comment lines)."""
        self.expect_p("{")
        self.skip_nl()
        out = []
        while not self.at_p("}"):
            tok = self.peek()
            if self.at_p("#["):
                self.error("flow wires cannot carry metadata; put a note above the node instead")
            cm = self.lead_comments(tok.line, tok.line)
            src, pin = self.endpoint("exec source")
            self.expect_p("->")
            out.append((tok, src, pin, self.endpoint("exec target"), cm))
            self.end_stmt()
        self.next()
        self.end_stmt()
        return out

    def layout(self, g: Graph, metas: list):
        """`layout { [meta] name [at (x, y) [props]] ... box ... }`: a line per node, by the
        name it is written with, carrying its metadata lines, and its position if it has one."""
        self.expect_p("{")
        self.skip_nl()
        while not self.at_p("}"):
            mt = self.peek()
            meta = self.meta_lines()
            if self.at_kw("box") and self.at("id", k=1) and self.at("str", k=2):
                self.next()
                bid = self.ident("box id")
                title = self.expect("str", None, "box title").value
                self.expect("id", "at")
                x, y = self.int_pair()
                self.expect("id", "size")
                w, h = self.int_pair()
                g.boxes.append(Box(bid, x, y, self.props(), title=title, w=w, h=h, meta=meta))
            else:
                t = self.peek()
                nid = self.qname() if self.at("id") else self.ident("node id")
                if meta:
                    metas.append((mt, nid, meta))
                if self.at_kw("at"):
                    self.next()
                    x, y = self.int_pair()
                    g.places.append(Place(nid, x, y, self.props()))
                elif not meta:
                    raise ParseError(f"expected 'at (x, y)' after '{nid}'; a line with only a "
                                     f"node's name carries the metadata lines above it",
                                     t.line, t.col)
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
    """The dotted enum value of Draft 0.11 and earlier: `.pin <- Mode.Chase` reads like a
    wire from node `Mode`. When the graph has no node with that id and the module declares an
    enum with that name, it is the enum value instead, which the formatter writes
    `Mode::Chase`. `@cases(Mode.Idle, ...)` arguments become enum values the same way."""
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
