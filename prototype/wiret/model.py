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

    kind is one of: int, float, bool, string, null, ident, tuple, list, map.
    For tuple/list `value` is a list of Lit; for map a list of (Lit, Lit).
    """
    kind: str
    value: object
    suffix: Optional[str] = None


@dataclass
class Attr:
    name: str
    args: Optional[list] = None  # None: written without parentheses; else [(key|None, Lit)]

    def arg(self, i: int = 0):
        if not self.args or i >= len(self.args):
            return None
        return self.args[i][1]


@dataclass
class PinRef:
    node: str
    pin: str


@dataclass
class Binding:
    pin: str
    value: Union[PinRef, Lit]


@dataclass
class ExecOut:
    pin: Optional[str]          # None: the `-> target` shorthand
    target: str
    target_pin: Optional[str] = None


@dataclass
class Node:
    id: str
    kind: str
    symbol: Optional[str] = None
    targs: list = field(default_factory=list)
    bindings: list = field(default_factory=list)   # [Binding]
    execs: list = field(default_factory=list)      # [ExecOut]
    attrs: list = field(default_factory=list)      # [Attr]

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


@dataclass
class Note:
    id: str
    on: Optional[str]
    text: str
    attrs: list = field(default_factory=list)


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

    def members(self) -> list:
        m = self.prop("members")
        if m is None or m.kind != "list":
            return []
        return [v.value for v in m.value if v.kind == "ident"]


@dataclass
class Graph:
    """A func, event or macro."""
    kind: str                                      # func | event | macro
    name: str
    tparams: list = field(default_factory=list)
    params: list = field(default_factory=list)     # [Param]
    results: Optional[list] = None                 # [Param]; None when no `->` was written
    attrs: list = field(default_factory=list)
    locals: list = field(default_factory=list)     # [Local]
    states: list = field(default_factory=list)     # [Local]
    nodes: list = field(default_factory=list)      # [Node]
    notes: list = field(default_factory=list)      # [Note]
    places: list = field(default_factory=list)     # [Place]
    boxes: list = field(default_factory=list)      # [Box]

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

    @property
    def result_list(self) -> list:
        return self.results or []


@dataclass
class Use:
    name: str
    alias: Optional[str] = None
    attrs: list = field(default_factory=list)


@dataclass
class Extern:
    kind: str                     # func | type
    name: str                     # qualified
    params: list = field(default_factory=list)
    results: Optional[list] = None
    attrs: list = field(default_factory=list)

    def has_attr(self, name: str) -> bool:
        return any(a.name == name for a in self.attrs)


@dataclass
class Const:
    name: str
    type: str
    value: Lit
    attrs: list = field(default_factory=list)


@dataclass
class Var:
    name: str
    type: str
    default: Optional[Lit] = None
    attrs: list = field(default_factory=list)


@dataclass
class Comment:
    """A `//` comment: trivia, not part of the model (section 2.1)."""
    line: int
    text: str
    anchor: Optional[tuple] = None  # ("node", graph, node_id) | ("graph", graph) | None


@dataclass
class Module:
    version: int
    name: str
    attrs: list = field(default_factory=list)
    items: list = field(default_factory=list)
    comments: list = field(default_factory=list)

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
    if isinstance(item, Graph):
        return item.kind
    raise TypeError(item)
