"""Lexer and parser for `.wiret` text (spec sections 2.1 to 2.4)."""
from __future__ import annotations

import re
from typing import Optional

from .model import (Attr, Binding, Box, Class, Comment, Dispatcher, IfaceMethod, Interface, Const,
                    Enum, EnumMember, ExecOut, Extern, Field, Graph, Lit, Local, Module, Node,
                    NODE_GENERICS, Param, PinRef, Place, SEMANTIC_ATTRS, Struct, Use, Var)

KEYWORDS = set("wiret module use extern const var local enum struct interface class impl macro "
               "func event dispatcher node state exec goto box self".split())
# Keywords are contextual (section 2.1): each is a keyword only where a statement of its kind
# can start, so `size`, `state` or `func` is a fine name for a field, pin, local or node. Only
# these words can never be a name, since they are values wherever a value can stand.
RESERVED = {"true", "false", "null"}

UNSUPPORTED_ITEMS = set()

INT_TYPES = {"i8", "u8", "i16", "u16", "i32", "u32", "i64", "u64"}

GENERICS_HINT = ("type arguments are written with '#<', as in Add#<i32> or array#<i32>")
FLOW_HINT = ("the 'flow' block was removed: write the nodes as 'exec' statements in the order "
             "they run (section 2.3)")
LAYOUT_HINT = ("the 'layout' block was removed: write a node's position in its attribute block, "
               "'Kind{pos=(x, y)}(...)', and its notes as @note(\"...\") lines above it")


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
        elif text.startswith(("->", "<-", "::"), i):
            toks.append(Tok("punct", text[i:i + 2], line, col))
            i += 2
        elif c in "(){}[]<>,:=.@#!|":
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


class _Body:
    """What the parser knows about the graph body it is reading (section 2.3)."""

    def __init__(self, g: Graph):
        self.g = g
        self.named = {}          # name -> Node, from `node` statements
        self.placed = set()      # ids of nodes that have their one exec point
        self.bare = []           # (PinRef, name, token): bare names resolved at the end
        self.gotos = []          # (source node, source pin, name, pin, token, comment, scope)
        self.regions = 0         # `!` statements numbered so far
        self.boxes = 0


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
        self.body_state: Optional[_Body] = None

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

    def pin_name(self, what="pin name") -> str:
        """A pin's name after its `.`: a name, or one of a node's variable pins with its index
        right after it, `case[0]`, `item[2]` (section 2.3)."""
        t = self.peek()
        name = self.ident(what)
        b = self.peek()
        if self.at_p("[") and b.line == t.line and b.col == t.col + len(name):
            self.next()
            k = self.expect("int", None, f"the pin's index, as in '{name}[0]'")
            if k.value[1] or k.value[0] < 0:
                self.error(f"a pin's index is a plain number, as in '{name}[0]'", k)
            self.expect_p("]")
            name = f"{name}[{k.value[0]}]"
        return name

    def skip_nl(self) -> bool:
        skipped = False
        while self.at("nl"):
            self.i += 1
            skipped = True
        return skipped

    def end_stmt(self):
        if self.at_p("}"):
            return
        if self.at_p("@") and self.at("id", k=1) and self.peek(1).value in NODE_GENERICS:
            name = self.peek(1).value
            self.error(f"'@{name}(...)' is a named generic argument now, written after the "
                       f"node's kind and type arguments: 'Sequence#{name}<2>()'")
        if self.at_p("@"):
            self.error("a decorator goes on the line above what it describes, or before a "
                       "parameter or field on its line, not after it")
        self.expect("nl", None, "end of line")
        self.skip_nl()

    def lead_comments(self, top: int, stmt: int) -> list:
        """The `//` lines attached to a statement on line `stmt` whose decorator lines start
        on line `top`: the comment lines among its decorator lines, and the run of comment
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

    # -- decorators ------------------------------------------------------------
    def decorators(self, lines=True):
        """`@name` or `@name(args)` decorators (section 2.4), each on its own line above what
        it describes (`lines`), or before it on the same line. Returns (metadata, semantic):
        a name in SEMANTIC_ATTRS changes the program, any other name is metadata."""
        meta, attrs = [], []
        if self.at_p("#") and self.at_p("[", 1):
            self.error("decorators are written @name(...), as in @note(\"...\"), not #[...]")
        while self.at_p("@"):
            t = self.next()
            name = self.qname()
            if name in NODE_GENERICS:
                raise ParseError(f"'@{name}' is a named generic argument now, written after the "
                                 f"node's kind: '#{name}<...>'", t.line, t.col)
            a = Attr(name, self.attr_args() if self.at_p("(") else None)
            (attrs if name in SEMANTIC_ATTRS else meta).append(a)
            if lines and self.at("nl"):
                self.next()
                if self.at("nl") or self.at_p("}") or self.at("eof"):
                    raise ParseError("a decorator must stand directly above what it describes, "
                                     "with no blank line between", t.line, t.col)
            if self.at_p("#") and self.at_p("[", 1):
                self.error("decorators are written @name(...), not #[...]")
        return meta, attrs

    def no_trailing(self):
        if self.at_p("@"):
            self.error("a decorator goes on the line above what it describes, not after it")

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
        meta, attrs = self.decorators()
        if not self.at_kw("module"):
            self.error("expected 'module'")
        mt = self.next()
        mod = Module(version, self.qname(), attrs, meta=meta)
        self.no_trailing()
        mod.comment = self.lead_comments(t0.line, mt.line)
        self.end_stmt()
        while not self.at("eof"):
            t0 = self.peek()
            meta, attrs = self.decorators()
            st = self.peek()
            it = self.item(attrs)
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
        resolve_self(mod)
        return mod

    def resolve_defaults(self, mod: Module):
        """A node written without `.pin`, inline or as a named node, feeds in its one data
        output (section 2.3). Which output that is depends on the node's signature, known
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
        # a comment that ends a line of code belongs to what is on that line, any other one
        # to what comes next, or else to the graph it stands in
        anchors = sorted(self.anchors, key=lambda a: a[0])
        for k, (line, _col, text, tok_index, own, _raw) in enumerate(self.raw_comments):
            if k in self.taken:
                continue
            before = [a for idx, a in anchors if idx < tok_index]
            after = [a for idx, a in anchors if idx >= tok_index]
            if not own and before:
                anchor = before[-1]
            elif after:
                anchor = after[0]
            elif before:
                anchor = ("graph", before[-1][1])
            else:
                anchor = None
            out.append(Comment(line, text, anchor))
        return out

    def item(self, attrs: list):
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
            it = Use(name, alias, attrs)
            self.end_stmt()
            return it
        if kw == "extern":
            if self.at_kw("type"):
                self.next()
                it = Extern("type", self.qname(), attrs=attrs)
            else:
                self.expect("id", "func")
                name = self.qname()
                params = self.params()
                results = None
                if self.at_p("->"):
                    self.next()
                    results = self.params()              # `-> ()`: none, written out
                it = Extern("func", name, params, results, attrs)
            self.end_stmt()
            return it
        if kw == "const":
            name = self.ident()
            self.expect_p(":")
            ty = self.type()
            self.expect_p("=")
            value = self.literal()
            it = Const(name, ty, value, attrs)
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
            it = Var(name, ty, default, attrs)
            self.end_stmt()
            return it
        if kw == "struct":
            return self.struct(attrs)
        if kw == "enum":
            return self.enum(attrs)
        if kw == "class":
            return self.class_decl(attrs)
        if kw == "interface":
            return self.interface(attrs)
        if kw in ("func", "event", "macro"):
            return self.graph(kw, start, attrs)
        self.error("expected a declaration")

    def graph(self, kw: str, start: int, attrs: list, owner: Optional[str] = None) -> Graph:
        short = self.ident()
        g = Graph(kw, f"{owner}.{short}" if owner else short, owner=owner, attrs=attrs)
        self.anchors.append((start, ("graph", g.name)))
        if self.at_p("#"):
            if owner:
                self.error("methods take no type parameters")
            g.tparams = self.generic_args(self.ident)
        elif self.at_p("<") or self.at_p("::"):
            self.generics_hint()
        has_self = []
        g.params = self.params(self_ok=owner is not None, has_self=has_self)
        g.static = owner is not None and not has_self
        if self.at_p("->"):
            self.next()
            g.results = self.params()
        self.no_trailing()
        if self.at_p("="):
            self.expr_body(g)
        else:
            self.body(g)
        return g

    def expr_body(self, g: Graph):
        """`func F(x: T) -> (r: U) = value` (section 2.3): an Entry wired to a Return whose
        one input is the value, in which the parameters are named bare (`x`)."""
        t = self.next()
        if g.kind != "func" or g.owner or g.results is None or len(g.results) != 1:
            raise ParseError("only a function with exactly one result, outside a class, is "
                             "written '= value'; give this one a body in braces", t.line, t.col)
        self.graph_name = g.name
        self.body_state = st = _Body(g)
        res = g.results[0].name
        self.skip_nl()
        self.anchors.append((self.i, ("node", g.name, "1")))
        val, inline = self.input_value(f"1.{res}", [])
        g.nodes = [Node("0", "Entry", execs=[ExecOut(None, "1")]),
                   Node("1", "Return", bindings=[Binding(res, val)])] + inline
        self.finish_body(st)
        self.end_stmt()

    def class_decl(self, attrs: list) -> Class:
        """`class Name [: Base] [impl I, ...] { field | dispatcher | func | event ... }`
        (section 2.2). The methods are collected in `pending_methods`, and the module adds
        them after the class."""
        c = Class(self.ident("class name"), attrs=attrs)
        if self.at_p("#") or self.at_p("<"):
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
        self.no_trailing()
        self.expect_p("{")
        self.skip_nl()
        while not self.at_p("}"):
            t0 = self.peek()
            meta, attrs = self.decorators()
            cm = self.lead_comments(t0.line, self.peek().line)
            named = self.at_p(":", 1)           # `name: type`: a field, whatever its name
            if not named and (self.at_kw("func") or self.at_kw("event")):
                start = self.i
                kw = self.next().value
                g = self.graph(kw, start, attrs, owner=c.name)
                g.meta, g.comment = meta, cm
                self.pending_methods.append(g)
                self.skip_nl()
                continue
            if not named and self.at_kw("dispatcher"):
                self.next()
                d = Dispatcher(self.ident("dispatcher name"), meta=meta, comment=cm, attrs=attrs)
                d.params = self.params()
                if self.at_p("->"):
                    self.error("a dispatcher has no results: its handlers' results would have "
                               "nowhere to go")
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
            c.fields.append(Field(name, ty, default, attrs, meta, cm))
            self.end_stmt()
        self.next()
        self.end_stmt()
        return c

    def members(self, what: str, member) -> list:
        """The `{ ... }` of a struct, enum or interface: one member per line, each after its
        decorators (section 2.4)."""
        self.expect_p("{")
        self.skip_nl()
        out = []
        while not self.at_p("}"):
            t0 = self.peek()
            meta, attrs = self.decorators()
            if not self.at("id"):
                self.error(f"expected {what}")
            cm = self.lead_comments(t0.line, self.peek().line)
            m = member()
            m.meta, m.comment, m.attrs = meta, cm, attrs
            out.append(m)
            self.end_stmt()
        self.next()
        self.end_stmt()
        return out

    def struct(self, attrs: list) -> Struct:
        """`struct Name { field: type [= default] ... }` (section 2.2)."""
        st = Struct(self.ident("struct name"), attrs=attrs)
        if self.at_p("#") or self.at_p("<"):
            self.error("structs take no type parameters")

        def field():
            name = self.ident("field name")
            self.expect_p(":")
            ty = self.type()
            default = None
            if self.at_p("="):
                self.next()
                default = self.literal()
            return Field(name, ty, default)

        st.fields = self.members("a field ('name: type')", field)
        return st

    def interface(self, attrs: list) -> Interface:
        """`interface Name { func Name(self, params) [-> (results)] ... }` (2.2)."""
        it = Interface(self.ident("interface name"), attrs=attrs)
        if self.at_p("#") or self.at_p("<"):
            self.error("interfaces take no type parameters")

        def method():
            if not self.at_kw("func"):
                self.error("an interface lists methods, written 'func Name(self, params) -> "
                           "(results)'")
            self.next()
            t = self.peek()
            m = IfaceMethod(self.ident("method name"))
            has_self = []
            m.params = self.params(self_ok=True, has_self=has_self)
            if not has_self:
                raise ParseError(f"an interface method is called on an object: write "
                                 f"'func {m.name}(self, ...)'", t.line, t.col)
            if self.at_p("->"):
                self.next()
                m.results = self.params()
            if self.at_p("{"):
                self.error("an interface method has no body; the classes that implement the "
                           "interface give one")
            return m

        it.methods = self.members("an interface method", method)
        return it

    def enum(self, attrs: list) -> Enum:
        """`enum Name [: inttype] { Member [= INT] ... }` (section 2.2)."""
        en = Enum(self.ident("enum name"), attrs=attrs)
        if self.at_p(":"):
            self.next()
            t = self.peek()
            base = self.ident("integer type")
            if base not in INT_TYPES:
                raise ParseError(f"an enum's underlying type must be an integer type such as "
                                 f"u8 or i32, not '{base}'", t.line, t.col)
            en.base = base

        def member():
            m = EnumMember(self.ident("enum member"))
            if self.at_p("="):
                self.next()
                t = self.peek()
                if t.kind != "int" or t.value[1] is not None:
                    self.error("an enum member's value is a plain integer, as in 'Idle = 0'")
                m.value = self.next().value[0]
            return m

        en.members = self.members("an enum member", member)
        return en

    def params(self, self_ok=False, has_self=None) -> list:
        """`(name: type [= default], ...)`; a method's list may start with `self`, and each
        parameter may start with decorators, `@id("p1") amount: i32` (section 2.4)."""
        self.expect_p("(")
        out = []
        self.skip_nl()
        first = True
        while not self.at_p(")"):
            if first and self.at_kw("self") and (self.at_p(",", 1) or self.at_p(")", 1)
                                                 or self.at("nl", k=1)):
                t = self.next()
                if not self_ok:
                    raise ParseError("only a method takes 'self'", t.line, t.col)
                has_self.append(True)
            else:
                meta, attrs = self.decorators(lines=False)
                if meta:
                    self.error(f"a parameter takes no metadata such as @{meta[0].name}")
                name = self.ident("parameter name")
                self.expect_p(":")
                ty = self.type()
                default = None
                if self.at_p("="):
                    self.next()
                    default = self.literal()
                self.no_trailing()
                out.append(Param(name, ty, default, attrs))
            first = False
            nl = self.skip_nl()
            if self.at_p(","):
                self.next()
                self.skip_nl()
            elif not self.at_p(")") and not nl:
                self.error("expected ',' or ')'")
        self.next()
        return out

    def type(self) -> str:
        """A type. Generic types are written `array#<i32>`; the model spells them
        `array#<i32>`, the form the registry and the bytecode type table use."""
        if self.at_p("("):
            return self.tlist()
        name = self.qname()
        if self.at_p("<") or self.at_p("::"):
            self.generics_hint()
        if not self.at_p("#"):
            return name
        if name in ("array", "set"):
            self.next()
            self.expect_p("<")
            inner = self.type()
            self.expect_p(">")
            return f"{name}#<{inner}>"
        if name == "map":
            self.next()
            self.expect_p("<")
            k = self.type()
            self.expect_p(",")
            v = self.type()
            self.expect_p(">")
            return f"map#<{k}, {v}>"
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
            return f"{name}#<{a}{r}>"
        self.error(f"'{name}' takes no type arguments")

    def generic_args(self, item) -> list:
        """`#<a, b>`: the type arguments of a node, or the type parameters of a declaration."""
        self.expect_p("#")
        self.expect_p("<")
        out = [item()]
        while self.at_p(","):
            self.next()
            out.append(item())
        self.expect_p(">")
        return out

    def generics_hint(self):
        self.error(GENERICS_HINT)

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
            nl = self.skip_nl()
            if self.at_p(","):
                self.next()
                self.skip_nl()
            elif not self.at_p(")") and not nl:
                self.error("expected ',' or ')'")
        self.next()
        return args

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
        if t.kind == "id" and self.at_p(".", 1):
            self.error("expected a literal; an enum value is written Enum::Member")
        self.error("expected a literal")

    def enum_value(self) -> Lit:
        """`Mode::Chase` (section 2.1)."""
        name = self.ident()
        self.expect_p("::")
        return Lit("enum", f"{name}.{self.ident('enum member')}")

    # -- graph bodies --------------------------------------------------------
    def body(self, g: Graph):
        """`{ local/state ... box ... node ... exec ... }` (section 2.3)."""
        self.graph_name = g.name
        self.body_state = st = _Body(g)
        self.expect_p("{")
        self.skip_nl()
        self.block(st, "", None, [], top=True, region=False)
        self.next()
        self.finish_body(st)
        self.end_stmt()

    def finish_body(self, st: _Body):
        """Resolve what a body names before it is declared: bare names (a named node, else a
        parameter) and goto targets."""
        g = st.g
        entry = next((n.id for n in g.nodes if n.kind == "Entry"), None)
        params = {p.name for p in g.params} | ({"self"} if g.receiver else set())
        for ref, name, tok in st.bare:
            if name in st.named:
                ref.node, ref.pin = name, None
                self.defaults.append((g.name, ref, None, tok))
            elif name in params and entry is not None:
                ref.node, ref.pin = entry, name
            else:                         # kept as written; the checker reports it (E0101)
                ref.node, ref.pin = name, None
                self.defaults.append((g.name, ref, None, tok))
        for src, pin, name, tpin, tok, cm in st.gotos:
            # a target that names no node is kept as written; the checker reports it (E0101)
            src.execs.append(ExecOut(pin, name, tpin, comment=cm))
        self.body_state = None

    def block(self, st: _Body, prefix: str, cur, scope: list, top: bool, region: bool):
        """The statements of a body or of an exec output's block, up to its `}`. `prefix` is
        the execution position of the block (`1.body.`), `cur` the exec output (node, pin)
        that the next `exec` statement continues from, and `scope` the names bound by the
        enclosing blocks, innermost last."""
        g = st.g
        k = 0
        while not self.at_p("}"):
            t0 = self.peek()
            meta, attrs = self.decorators()
            t = self.peek()
            cm = self.lead_comments(t0.line, t.line)
            if self.at_kw("flow") and self.at_p("{", 1):
                self.error(FLOW_HINT)
            if self.at_kw("layout") and self.at_p("{", 1):
                self.error(LAYOUT_HINT)
            if (self.at_kw("local") or self.at_kw("state")) and self.at("id", k=1):
                if not top:
                    self.error("a local is declared at the top of the function")
                self.next()
                name = self.ident()
                self.expect_p(":")
                ty = self.type()
                default = None
                if self.at_p("="):
                    self.next()
                    default = self.literal()
                (g.locals if t.value == "local" else g.states).append(
                    Local(name, ty, default, attrs, meta, cm))
                self.end_stmt()
            elif self.at_kw("box") and self.at_p("{", 1):
                if not top:
                    self.error("a box is declared at the top of the function")
                if attrs:
                    self.error(f"a box takes no @{attrs[0].name}")
                self.next()
                props = self.attr_block()
                g.boxes.append(self.make_box(st, props, meta, t))
                self.end_stmt()
            elif self.at_kw("node") and self.at("id", k=1) and self.at_p("=", 2):
                if not top or region:
                    self.error("a named node is declared at the top of the function, with "
                               "'node name = ...'")
                self.next()
                nt = self.peek()
                name = self.ident("node name")
                if name in st.named:
                    raise ParseError(f"two nodes are named '{name}'", nt.line, nt.col)
                self.expect_p("=")
                at = len(self.anchors)
                self.anchors.append((self.i, ("node", g.name, name)))
                ns = self.node_expr(name, [])
                self.anchors[at] = (self.anchors[at][0], ("node", g.name, name))
                n = ns[0]
                n.named, n.comment = True, cm
                n.meta.extend(meta)
                n.attrs.extend(attrs)
                st.named[name] = n
                g.nodes.extend(ns)
                if self.at_p("."):
                    self.error(f"a named node's exec outputs are written where it runs: "
                               f"'exec {name}.pin -> {{ ... }}'")
                self.end_stmt()
            elif self.at_kw("goto"):
                if meta or attrs:
                    self.error("a goto takes no decorators")
                gt = self.next()
                if cur is None:
                    raise ParseError("nothing runs before this goto: it must follow a node or "
                                     "open an exec output's block", gt.line, gt.col)
                nt = self.peek()
                name = self.ident("node name")
                tpin = None
                if self.at_p("."):
                    self.next()
                    tpin = self.ident("exec input")
                src = g.node(cur[0])
                bound = self.lookup(scope, name)
                if bound is not None and tpin is None:
                    src.execs.append(ExecOut(cur[1], bound[0], bound[1], comment=cm))
                else:
                    st.gotos.append((src, cur[1], name, tpin, nt, cm))
                cur = None
                self.end_stmt()
            elif self.at_kw("exec"):
                self.next()
                first = cur is None and not region
                before = len(g.nodes)
                ref = self.peek()
                cur = self.exec_stmt(st, prefix + str(k), cur, scope, meta, attrs, cm, t)
                placed = g.nodes[before] if len(g.nodes) > before else st.named.get(ref.value)
                self.end_stmt()
                if first and (placed is None or placed.kind != "Entry"):
                    raise ParseError(
                        "nothing continues to this node: the node before it ends with blocks "
                        "only, a goto or a Return. End the last block with '}.pin' to continue "
                        "from that output, or write '!exec' for a node that is not wired",
                        t.line, t.col)
                k += 1
                region = False          # only a region's first node has nothing before it
            elif self.at_p("!"):
                self.next()
                r = st.regions
                st.regions += 1
                if self.at_p("{"):
                    if meta or attrs:
                        self.error("decorators go on the statements inside a '!{ }' block")
                    self.next()
                    self.skip_nl()
                    self.block(st, f"~{r}.", None, [], top=False, region=True)
                    self.next()
                elif self.at_kw("exec"):
                    # a node whose exec input nothing wires; the statements after it do not
                    # continue from it (that is a '!{ }' block)
                    self.next()
                    after = self.exec_stmt(st, f"~{r}", None, scope, meta, attrs, cm, t)
                    if after is not None and after[1] is not None:
                        raise ParseError("'!exec' stands alone; write a chain that nothing "
                                         "reaches as a '!{ ... }' block", t.line, t.col)
                else:                       # a node without exec pins that nothing reads
                    self.anchors.append((self.i, ("node", g.name, f"~{r}")))
                    ns = self.node_expr(f"~{r}", scope)
                    ns[0].meta.extend(meta)
                    ns[0].attrs.extend(attrs)
                    ns[0].comment = cm
                    g.nodes.extend(ns)
                self.end_stmt()
            else:
                self.error("expected 'exec', 'goto', 'node', 'local', 'state', 'box' or '!'")


    @staticmethod
    def lookup(scope: list, name: str):
        for names in reversed(scope):
            if name in names:
                return names[name]
        return None

    def exec_stmt(self, st: _Body, pos: str, cur, scope, meta, attrs, cm, tok):
        """`exec Kind(...)` or `exec name`, then its exec outputs: `.pin|names| -> { ... }`
        blocks, the last of which may be written `.pin` alone to continue in this block. An
        output that takes a value (a Switch's `case[0]`) has it after its name, `.case[0] Mode::Idle
        -> { ... }`: it is the node's input of the same name. Returns the exec output the next
        statement continues from."""
        g = st.g
        named_ref = self.at("id") and not (
            self.at_p("(", 1) or self.at_p("{", 1) or self.at_p("#", 1) or self.at("id", k=1)
            or self.at("str", k=1) or self.at_p("<", 1) or self.at_p("::", 1))
        if named_ref:
            nt = self.next()
            x = st.named.get(nt.value)
            if x is None and nt.value[:1].isupper():
                raise ParseError(f"expected '(' after the node; a node without inputs is "
                                 f"written '{nt.value}()'", nt.line, nt.col)
            if x is None:
                raise ParseError(f"no node is named '{nt.value}'; declare it at the top of the "
                                 f"function with 'node {nt.value} = ...'", nt.line, nt.col)
            if x.id in st.placed:
                raise ParseError(f"'{nt.value}' already has its exec point; use "
                                 f"'goto {nt.value}' to run it from here", nt.line, nt.col)
            if meta or cm:
                raise ParseError(f"decorators and comments of '{nt.value}' go above its "
                                 f"'node' statement", nt.line, nt.col)
            x.attrs.extend(attrs)
        else:
            self.anchors.append((self.i, ("node", g.name, pos)))
            ns = self.node_expr(pos, scope)
            x = ns[0]
            x.meta.extend(meta)
            x.attrs.extend(attrs)
            x.comment = cm
            g.nodes.extend(ns)
        st.placed.add(x.id)
        if cur is not None:
            g.node(cur[0]).execs.append(ExecOut(cur[1], x.id))
        outs = False
        while self.at_p("."):
            self.next()
            pt = self.peek()
            pin = self.pin_name("exec output")
            nt = self.peek()
            if self.at_p("(") and nt.line == pt.line and nt.col == pt.col + len(pin):
                self.error(f"an exec output's block binds names between bars: "
                           f"'.{pin}|name, ...| -> {{ ... }}'")
            if not (self.at_p("|") or self.at_p("->") or self.at_p("<-") or self.at_p("}")
                    or self.at("nl") or self.at("eof")):
                # the output's value: the node's input of the same name (section 2.3)
                val, inline = self.input_value(f"{x.id}.{pin}", scope)
                x.bindings.append(Binding(pin, val))
                g.nodes.extend(inline)
            names = []
            if self.at_p("|"):
                self.next()
                while not self.at_p("|"):
                    names.append(self.ident("output or exec input name"))
                    if self.at_p(","):
                        self.next()
                    elif not self.at_p("|"):
                        self.error("expected ',' or '|'")
                self.next()
            if not self.at_p("->"):
                if names:
                    self.error(f"'.{pin}' continues in this block, so it binds no names; "
                               f"write '.{pin}|{', '.join(names)}| -> {{ ... }}'")
                if not self.at("nl") and not self.at_p("}"):
                    self.error(f"expected '-> {{' after '.{pin}', or the end of the line to "
                               f"continue from it in this block")
                x.flat, x.flat_pin = True, pin
                return x.id, pin
            self.next()
            self.expect_p("{")
            self.skip_nl()
            bound = {n: (x.id, n) for n in names}
            self.block(st, f"{x.id}.{pin}.", (x.id, pin), scope + [bound], top=False,
                       region=False)
            self.next()
            outs = True
        if outs:
            x.flat, x.flat_pin = False, None
            return None
        return x.id, None

    def make_box(self, st: _Body, props: list, meta: list, tok) -> Box:
        """`box {title="...", pos=(x, y), size=(w, h), ...}`: a visual frame. It holds no
        list of members: moving it moves the nodes that lie inside it (section 2.3)."""
        d = dict(props)
        pos, size, title = d.get("pos"), d.get("size"), d.get("title")
        if not _int_pair(pos) or not _int_pair(size):
            raise ParseError("a box needs pos=(x, y) and size=(w, h)", tok.line, tok.col)
        rest = [(k, v) for k, v in props if k not in ("pos", "size", "title")]
        b = Box(f"box.{st.boxes}", pos.value[0].value, pos.value[1].value, rest,
                title=title.value if title is not None and title.kind == "string" else "",
                w=size.value[0].value, h=size.value[1].value, meta=meta)
        st.boxes += 1
        return b

    def attr_block(self) -> list:
        """`{key=value, ...}`: a node's or box's attributes, for display only (section 2.3)."""
        self.expect_p("{")
        out = []
        self.skip_nl()
        while not self.at_p("}"):
            if not self.at("id"):
                self.error("expected an attribute, 'name=value'")
            k = self.qname()
            self.expect_p("=")
            out.append((k, self.value()))
            nl = self.skip_nl()
            if self.at_p(","):
                self.next()
                self.skip_nl()
            elif not self.at_p("}") and not nl:
                self.error("expected ',' or '}'")
        self.next()
        return out

    def node_expr(self, nid: str, scope: list) -> list:
        """`Kind [symbol][#<targs>][#name<args>...][{attrs}](inputs)`: a node with the given
        id, then the nodes written inline in its inputs."""
        kt = self.peek()
        kind = self.ident("node kind")
        n = Node(nid, kind)
        if self.at("id"):
            n.symbol = self.qname()
        elif kind == "Format" and self.at("str"):      # its template (section 3.3)
            n.symbol = self.next().value
        if self.at_p("<") or self.at_p("::"):
            self.generics_hint()
        if self.at_p("#") and self.at_p("<", 1):
            n.targs = self.generic_args(self.type)
            # `ArrayAdd#<i32> acc` (section 3.3) writes the symbol after the type arguments
            if n.symbol is None and self.at("id"):
                n.symbol = self.qname()
        while self.at_p("#") and self.at("id", k=1):
            self.next()
            gt = self.peek()
            name = self.ident()
            if name not in NODE_GENERICS:
                raise ParseError(f"unknown named generic '#{name}'; a node takes "
                                 f"{' or '.join('#' + x for x in NODE_GENERICS)}", gt.line, gt.col)
            self.expect_p("<")
            args = []
            while not self.at_p(">"):
                args.append((None, self.value()))
                if self.at_p(","):
                    self.next()
                elif not self.at_p(">"):
                    self.error("expected ',' or '>'")
            self.next()
            n.attrs.append(Attr(name, args))
        if self.at_p("{"):
            at = self.peek()
            props = self.attr_block()
            pos = dict(props).get("pos")
            rest = [(k, v) for k, v in props if k != "pos"]
            if pos is None:
                if rest:
                    raise ParseError("a node's attribute block needs its position, pos=(x, y)",
                                     at.line, at.col)
            elif not _int_pair(pos):
                raise ParseError("a position is two integers, pos=(x, y)", at.line, at.col)
            else:
                self.body_state.g.places.append(
                    Place(nid, pos.value[0].value, pos.value[1].value, rest))
        if not self.at_p("("):
            j = self.i
            while self.toks[j].kind == "nl":
                j += 1
            if self.toks[j].kind == "punct" and self.toks[j].value == ".":
                self.error("a node's inputs are written in parentheses after it: "
                           "'Kind(.pin <- value ...)'")
            self.error(f"expected '(' after the node; a node without inputs is written "
                       f"'{kind}()'")
        self.next()
        out = [n]
        self.skip_nl()
        while not self.at_p(")"):
            t0 = self.peek()
            meta, attrs = self.decorators()
            if not self.at_p("."):
                self.error("expected an input, '.pin <- value', or ')'")
            cm = self.lead_comments(t0.line, self.peek().line)
            self.next()
            pin = self.pin_name("pin name")
            self.expect_p("<-")
            self.skip_nl()
            val, inline = self.input_value(f"{nid}.{pin}", scope)
            if (meta or attrs) and not inline:
                raise ParseError("a decorator above an input belongs to the node written in "
                                 "it; this input holds no node", t0.line, t0.col)
            if inline:
                inline[0].meta[:0] = meta
                inline[0].attrs[:0] = attrs
            n.bindings.append(Binding(pin, val, cm))
            out.extend(inline)
            nl = self.skip_nl()
            if self.at_p(","):
                self.next()
                self.skip_nl()
            elif not self.at_p(")") and not nl:
                self.error("expected ',', a new line or ')' after an input")
        self.next()
        return out

    def input_value(self, path: str, scope: list):
        """The value bound to an input: a literal, an enum value, a name (bound by an exec
        output's block, a named node, or a parameter), `name.pin`, or a node written inline,
        `Kind(...)[.pin]`, which gets the id `path`. Returns (value, inline nodes)."""
        t = self.peek()
        if t.kind == "id" and self.at_p("::", 1) and self.at("id", k=2):
            return self.enum_value(), []
        if t.kind == "id" and t.value not in RESERVED:
            if self.at_p(".", 1) and self.at("id", k=2):
                self.next()
                self.next()
                return PinRef(t.value, self.ident("pin name")), []
            if not (self.at_p("(", 1) or self.at_p("#", 1) or self.at_p("{", 1) or self.at_p("<", 1)
                    or self.at_p("::", 1) or self.at("id", k=1) or self.at("str", k=1)):
                self.next()
                bound = self.lookup(scope, t.value)
                if bound is not None:
                    return PinRef(*bound), []
                ref = PinRef(t.value, None)
                self.body_state.bare.append((ref, t.value, t))
                return ref, []
            self.anchors.append((self.i, ("node", self.graph_name, path)))
            inline = self.node_expr(path, scope)
            if not (self.at_p(".") and self.at("id", k=1)):
                ref = PinRef(path, None)            # its one data output, resolved later
                self.defaults.append((self.graph_name, ref, inline[0], t))
                return ref, inline
            self.next()
            return PinRef(path, self.ident("pin name")), inline
        return self.literal(), []


def _int_pair(v) -> bool:
    return (v is not None and v.kind == "tuple" and len(v.value) == 2
            and all(x.kind == "int" for x in v.value))


def resolve_enum_values(mod: Module):
    """Old-style `#cases<Mode::Idle, ...>` arguments written as bare dotted names become enum
    values, so the checker's message about the old form can show them (registry.signature)."""
    enums = {it.name for it in mod.items if isinstance(it, Enum)}
    if not enums:
        return
    for g in mod.graphs():
        for n in g.nodes:
            for a in n.attrs:
                if a.name == "cases" and a.args:
                    a.args = [(k, Lit("enum", v.value) if v.kind == "ident"
                               and v.value.count(".") == 1 and v.value.split(".")[0] in enums
                               else v) for k, v in a.args]


def self_receiver(n: Node, g: Graph, idx) -> bool:
    """Whether a `Call` in `g` takes `self` from the method it is in when its `self` input is
    left out (section 2.2): `g` is an instance method and the callee is a method of its
    class, of a base class, or of an interface its class implements."""
    if n.kind != "Call" or not g.receiver or not n.symbol or g.receiver not in idx.classes:
        return False
    callee = idx.callee(n.symbol, n.targs)
    if callee is None or not callee.method_of:
        return False
    owner = callee.method_of
    return owner in idx.class_chain(g.receiver) or idx.implements(g.receiver, owner)


def resolve_self(mod: Module):
    """Fill in `self` on the method calls that leave it out (section 2.2)."""
    if not any(g.receiver for g in mod.graphs()):
        return
    from .registry import ModuleIndex
    idx = ModuleIndex(mod)
    for g in mod.graphs():
        entry = next((n.id for n in g.nodes if n.kind == "Entry"), None)
        if not g.receiver or entry is None:
            continue
        for n in g.nodes:
            if n.binding("self") is None and self_receiver(n, g, idx):
                n.bindings.insert(0, Binding("self", PinRef(entry, "self")))


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
