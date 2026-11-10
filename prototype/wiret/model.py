"""In-memory model of a parsed `.wiret` module (spec section 2).

The model is what the parser produces, what the canonical printer consumes and
what the graph editor mutates. Node order inside a graph is not significant;
the printer sorts everything (section 2.5).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Union


@dataclass
class Lit:
    """A literal or attribute value.

    kind is one of: int, float, bool, string, null, enum, ident, tuple, list, map.
    For an enum member `value` is "Enum.Member"; for tuple/list a list of Lit; for map a
    list of (Lit, Lit).
    """
    kind: str
    value: object
    suffix: Optional[str] = None


# Semantic attributes (`@name`, section 2.4). Any other `@` name is E0104.
SEMANTIC_ATTRS = {"id", "pure", "reads", "final", "private", "export", "inline", "deprecated",
                  "count", "cases", "disabled", "capability", "latent", "live"}
# Metadata attributes (`#[name]`) in canonical order; any other name follows them (section 2.5).
META_ORDER = ["doc", "category", "keywords", "note"]


@dataclass
class Attr:
    """A semantic attribute (`@name(...)`) or, in a `meta` list, a metadata line (`#[name(...)]`)."""
    name: str
    args: Optional[list] = None  # None: written without parentheses; else [(key|None, Lit)]

    def arg(self, i: int = 0):
        if not self.args or i >= len(self.args):
            return None
        return self.args[i][1]

    def kwarg(self, key: str):
        for k, v in self.args or []:
            if k == key:
                return v
        return None


def note(text: str, detached: Optional[str] = None) -> Attr:
    """A `#[note("text")]` line; `detached` names the deleted target it came from (section 2.4)."""
    args = [(None, Lit("string", text))]
    if detached is not None:
        args.append(("detached", Lit("string", detached)))
    return Attr("note", args)


def note_text(a: Attr) -> str:
    v = a.arg()
    return v.value if v is not None and v.kind == "string" else ""


def set_note_text(a: Attr, text: str) -> None:
    a.args = [(None, Lit("string", text))] + list((a.args or [])[1:])


def note_detached(a: Attr) -> Optional[str]:
    v = a.kwarg("detached")
    return v.value if v is not None and v.kind == "string" else None


def notes(meta: list) -> list:
    return [a for a in meta if a.name == "note"]


def meta_value(meta: list, name: str) -> Optional[str]:
    """The string argument of the first `#[name("...")]` line, e.g. a declaration's doc."""
    for a in meta:
        if a.name == name and a.arg() is not None and a.arg().kind == "string":
            return a.arg().value
    return None


@dataclass
class PinRef:
    node: str
    pin: str


@dataclass
class Binding:
    pin: str
    value: Union[PinRef, Lit]
    comment: list = field(default_factory=list)    # the `//` lines directly above its `.pin <-` line


@dataclass
class ExecOut:
    """One exec wire, written in the graph's `flow` block and stored on its source node."""
    pin: Optional[str]          # None: the `source -> target` shorthand
    target: str
    target_pin: Optional[str] = None
    comment: list = field(default_factory=list)    # the `//` lines directly above its line in the flow block


@dataclass
class Node:
    id: str
    kind: str
    symbol: Optional[str] = None
    targs: list = field(default_factory=list)
    bindings: list = field(default_factory=list)   # [Binding]
    execs: list = field(default_factory=list)      # [ExecOut]
    attrs: list = field(default_factory=list)      # [Attr]
    meta: list = field(default_factory=list)       # [Attr], written as `#[...]` lines above
    comment: list = field(default_factory=list)    # the `//` lines directly above it (section 2.1)

    def binding(self, pin: str) -> Optional[Binding]:
        for b in self.bindings:
            if b.pin == pin:
                return b
        return None

    def attr(self, name: str) -> Optional[Attr]:
        for a in self.attrs:
            if a.name == name:
                return a
        return None


@dataclass
class Param:
    name: str
    type: str
    default: Optional[Lit] = None
    attrs: list = field(default_factory=list)


@dataclass
class Local:
    name: str
    type: str
    default: Optional[Lit] = None
    attrs: list = field(default_factory=list)
    meta: list = field(default_factory=list)
    comment: list = field(default_factory=list)    # the `//` lines directly above it (section 2.1)


@dataclass
class Place:
    id: str
    x: int
    y: int
    props: list = field(default_factory=list)      # [(key, Lit)]

    def prop(self, key):
        for k, v in self.props:
            if k == key:
                return v
        return None

    def set_prop(self, key, value: Optional[Lit]):
        self.props = [(k, v) for k, v in self.props if k != key]
        if value is not None:
            self.props.append((key, value))


@dataclass
class Box(Place):
    title: str = ""
    w: int = 200
    h: int = 120
    meta: list = field(default_factory=list)

    def members(self) -> list:
        m = self.prop("members")
        if m is None or m.kind != "list":
            return []
        return [v.value for v in m.value if v.kind == "ident"]


@dataclass
class Graph:
    """A func, event or macro. A method (a func or event declared in a class) is a module item
    of its own, named `Class.Method`, with `owner` set; the printer writes it inside the
    class (section 2.2)."""
    kind: str                                      # func | event | macro
    name: str
    tparams: list = field(default_factory=list)
    params: list = field(default_factory=list)     # [Param]
    results: Optional[list] = None                 # [Param]; None when no `->` was written
    attrs: list = field(default_factory=list)
    locals: list = field(default_factory=list)     # [Local]
    states: list = field(default_factory=list)     # [Local]
    nodes: list = field(default_factory=list)      # [Node]
    meta: list = field(default_factory=list)       # [Attr]: doc, graph-level notes, ...
    comment: list = field(default_factory=list)    # the `//` lines directly above it (section 2.1)
    places: list = field(default_factory=list)     # [Place]
    # layout-block metadata above a name that is no node of the graph (W0605): kept as
    # written until someone moves it above a node's line or deletes it
    orphan_meta: dict = field(default_factory=dict)    # {name: [Attr]}
    boxes: list = field(default_factory=list)      # [Box]
    owner: Optional[str] = None                    # the class of a method

    @property
    def short_name(self) -> str:
        """The name as written in its declaration: `TakeDamage` for `Player.TakeDamage`."""
        return self.name[len(self.owner) + 1:] if self.owner else self.name

    def node(self, nid: str) -> Optional[Node]:
        for n in self.nodes:
            if n.id == nid:
                return n
        return None

    def place(self, nid: str) -> Optional[Place]:
        for p in self.places:
            if p.id == nid:
                return p
        return None

    def box(self, bid: str) -> Optional[Box]:
        for b in self.boxes:
            if b.id == bid:
                return b
        return None

    def local(self, name: str) -> Optional[Local]:
        for l in self.locals:
            if l.name == name:
                return l
        return None

    def state(self, name: str) -> Optional[Local]:
        for l in self.states:
            if l.name == name:
                return l
        return None

    def has_attr(self, name: str) -> bool:
        return any(a.name == name for a in self.attrs)

    def note_owner(self, on: Optional[str]):
        """The graph (`on` is None), node or box whose `meta` holds the notes on `on`."""
        if on is None:
            return self
        return self.node(on) or self.box(on)

    def all_notes(self) -> list:
        """(target id, or None for the graph; index among that target's notes; the note)."""
        out = [(None, i, a) for i, a in enumerate(notes(self.meta))]
        for o in list(self.nodes) + list(self.boxes):
            out += [(o.id, i, a) for i, a in enumerate(notes(o.meta))]
        return out

    @property
    def result_list(self) -> list:
        return self.results or []


@dataclass
class Use:
    name: str
    alias: Optional[str] = None
    attrs: list = field(default_factory=list)
    meta: list = field(default_factory=list)
    comment: list = field(default_factory=list)    # the `//` lines directly above it (section 2.1)


@dataclass
class Extern:
    kind: str                     # func | type
    name: str                     # qualified
    params: list = field(default_factory=list)
    results: Optional[list] = None
    attrs: list = field(default_factory=list)
    meta: list = field(default_factory=list)
    comment: list = field(default_factory=list)    # the `//` lines directly above it (section 2.1)

    def has_attr(self, name: str) -> bool:
        return any(a.name == name for a in self.attrs)


@dataclass
class Const:
    name: str
    type: str
    value: Lit
    attrs: list = field(default_factory=list)
    meta: list = field(default_factory=list)
    comment: list = field(default_factory=list)    # the `//` lines directly above it (section 2.1)


@dataclass
class Var:
    name: str
    type: str
    default: Optional[Lit] = None
    attrs: list = field(default_factory=list)
    meta: list = field(default_factory=list)
    comment: list = field(default_factory=list)    # the `//` lines directly above it (section 2.1)


@dataclass
class Field:
    """A struct field: `name: type [= default] @attrs` (section 2.2)."""
    name: str
    type: str
    default: Optional[Lit] = None
    attrs: list = field(default_factory=list)
    meta: list = field(default_factory=list)
    comment: list = field(default_factory=list)    # the `//` lines directly above it (section 2.1)


@dataclass
class Struct:
    """A value type. Field order is the order written; it is semantic and never sorted."""
    name: str
    fields: list = field(default_factory=list)     # [Field]
    attrs: list = field(default_factory=list)
    meta: list = field(default_factory=list)
    comment: list = field(default_factory=list)    # the `//` lines directly above it (section 2.1)

    def field(self, name: str) -> Optional[Field]:
        for f in self.fields:
            if f.name == name:
                return f
        return None


@dataclass
class Class:
    """`class Name [: Base] { fields, methods }`, a reference type (section 2.2). Field order is
    the order written. Methods are separate `Graph` items whose `owner` is this class."""
    name: str
    base: Optional[str] = None
    fields: list = field(default_factory=list)     # [Field]
    attrs: list = field(default_factory=list)
    meta: list = field(default_factory=list)
    comment: list = field(default_factory=list)    # the `//` lines directly above it (section 2.1)
    impls: list = field(default_factory=list)      # interface names after `impl`
    dispatchers: list = field(default_factory=list)  # [Dispatcher], in the order written

    def field(self, name: str) -> Optional[Field]:
        for f in self.fields:
            if f.name == name:
                return f
        return None


@dataclass
class Dispatcher:
    """`dispatcher Name(params) @attrs` in a class: a multicast event slot on each object
    (section 2.2), of type `dispatcher::<(param types)>`."""
    name: str
    params: list = field(default_factory=list)     # [Param]
    attrs: list = field(default_factory=list)
    meta: list = field(default_factory=list)
    comment: list = field(default_factory=list)    # the `//` lines directly above it (section 2.1)
    results = None                                 # a dispatcher returns nothing

    @property
    def result_list(self) -> list:
        return []

    def has_attr(self, name: str) -> bool:
        return any(a.name == name for a in self.attrs)


@dataclass
class IfaceMethod:
    """`func Name(params) -> (results) @attrs` inside an interface: a signature, no body."""
    name: str
    params: list = field(default_factory=list)     # [Param]
    results: Optional[list] = None
    attrs: list = field(default_factory=list)
    meta: list = field(default_factory=list)
    comment: list = field(default_factory=list)    # the `//` lines directly above it (section 2.1)

    @property
    def result_list(self) -> list:
        return self.results or []

    def has_attr(self, name: str) -> bool:
        return any(a.name == name for a in self.attrs)


@dataclass
class Interface:
    """`interface Name { func ... }` (section 2.2). Method order is the order written: each
    method's position is its dispatch slot (section 5.3), so it is never sorted."""
    name: str
    methods: list = field(default_factory=list)    # [IfaceMethod]
    attrs: list = field(default_factory=list)
    meta: list = field(default_factory=list)
    comment: list = field(default_factory=list)    # the `//` lines directly above it (section 2.1)

    def method(self, name: str) -> Optional[IfaceMethod]:
        for m in self.methods:
            if m.name == name:
                return m
        return None


@dataclass
class EnumMember:
    """An enum member: `Name [= value] @attrs`."""
    name: str
    value: Optional[int] = None                    # None: no `= INT` written
    attrs: list = field(default_factory=list)
    meta: list = field(default_factory=list)
    comment: list = field(default_factory=list)    # the `//` lines directly above it (section 2.1)


@dataclass
class Enum:
    """`enum Name [: inttype] { ... }`. Member order is the order written, never sorted."""
    name: str
    base: Optional[str] = None                     # None: no `: inttype` written
    members: list = field(default_factory=list)    # [EnumMember]
    attrs: list = field(default_factory=list)
    meta: list = field(default_factory=list)
    comment: list = field(default_factory=list)    # the `//` lines directly above it (section 2.1)

    def member(self, name: str) -> Optional[EnumMember]:
        for m in self.members:
            if m.name == name:
                return m
        return None


@dataclass
class Comment:
    """A `//` comment that is attached to nothing (not directly above an element that keeps
    its comments): trivia, not part of the model (section 2.1)."""
    line: int
    text: str
    anchor: Optional[tuple] = None  # ("node", graph, node_id) | ("graph", graph) | None


@dataclass
class Module:
    version: int
    name: str
    attrs: list = field(default_factory=list)
    items: list = field(default_factory=list)
    meta: list = field(default_factory=list)
    comment: list = field(default_factory=list)    # the `//` lines directly above `module`
    comments: list = field(default_factory=list)   # [Comment]: `//` lines attached to nothing
    # (graph name, node id) pairs retired in the project's wiret.ids (section 7.3). Not part
    # of the text: set by a tool that has the project, so that a node declared under a new
    # name (an inline node that came to feed several inputs) never takes a retired id
    retired_nodes: set = field(default_factory=set, repr=False, compare=False)

    def graphs(self, kinds=("func", "event", "macro")) -> list:
        return [i for i in self.items if isinstance(i, Graph) and i.kind in kinds]

    def graph(self, name: str) -> Optional[Graph]:
        for i in self.items:
            if isinstance(i, Graph) and i.name == name:
                return i
        return None


ITEM_ORDER = ["use", "extern", "const", "var", "enum", "struct", "interface", "class",
              "macro", "func", "event"]


def item_kind(item) -> str:
    if isinstance(item, Use):
        return "use"
    if isinstance(item, Extern):
        return "extern"
    if isinstance(item, Const):
        return "const"
    if isinstance(item, Var):
        return "var"
    if isinstance(item, Enum):
        return "enum"
    if isinstance(item, Struct):
        return "struct"
    if isinstance(item, Class):
        return "class"
    if isinstance(item, Interface):
        return "interface"
    if isinstance(item, Graph):
        return item.kind
    raise TypeError(item)


def strip_comments(obj) -> None:
    """Clear every attached `//` comment in a model tree, in place (the semantic text has none)."""
    seen = set()

    def walk(x):
        if isinstance(x, list):
            for y in x:
                walk(y)
        elif hasattr(x, "__dataclass_fields__") and id(x) not in seen:
            seen.add(id(x))
            if isinstance(getattr(x, "comment", None), list):
                x.comment = []
            for f in x.__dataclass_fields__:
                if f != "comment":
                    walk(getattr(x, f))
    walk(obj)
