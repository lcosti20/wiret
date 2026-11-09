"""Identity: `@id` generation, the project id registry `wiret.ids`, E0140 and W0202
(spec sections 2.3, 2.4, 7.3 and 7.5).

Two kinds of identity exist. Node and box ids are the node's or box's name. Declarations,
parameters, results, fields, enum members, locals and state slots carry an optional `@id`
attribute that survives a rename. Retiring an id means recording, in the project's
`wiret.ids`, that it was deleted, so it is never used again.
"""
from __future__ import annotations

import os
import random
from dataclasses import dataclass, field
from typing import Iterator, Optional

from .model import (Attr, Class, Interface, Const, Enum, Extern, Graph, Lit, Module, Struct, Use, Var)

ID_CHARS = "abcdefghijkmnpqrstuvwxyz23456789"     # no 0/o, 1/l: ids are read aloud

# kind of element -> prefix of a generated @id
PREFIX = {"module": "mod", "use": "use", "extern": "ext", "const": "const", "var": "var",
          "enum": "en", "struct": "st", "func": "fn", "event": "ev", "macro": "mac",
          "param": "p", "result": "r", "field": "f", "member": "m", "local": "l",
          "state": "s", "class": "cls", "interface": "if", "method": "im",
          "dispatcher": "dsp"}


def get_id(attrs: list) -> Optional[str]:
    for a in attrs:
        if a.name == "id" and a.arg() is not None and a.arg().kind == "string":
            return a.arg().value
    return None


@dataclass
class Element:
    """Something that may carry an `@id`."""
    kind: str                 # a key of PREFIX
    name: str                 # its current name, for messages and for matching without an id
    owner: Optional[str]      # the enclosing declaration's name, None for a top-level item
    obj: object               # the model object; its `.attrs` holds the @id

    @property
    def id(self) -> Optional[str]:
        return get_id(self.obj.attrs)


def decl_kind(it) -> str:
    if isinstance(it, Graph):
        return it.kind
    return {Use: "use", Extern: "extern", Const: "const", Var: "var", Enum: "enum",
            Struct: "struct", Class: "class", Interface: "interface"}[type(it)]


def elements(m: Module) -> Iterator[Element]:
    """Every element that may carry an `@id`, in file order."""
    yield Element("module", m.name, None, m)
    for it in m.items:
        k = decl_kind(it)
        yield Element(k, it.name, None, it)
        if isinstance(it, (Graph, Extern)):
            for p in it.params:
                yield Element("param", p.name, it.name, p)
            for r in it.results or []:
                yield Element("result", r.name, it.name, r)
        if isinstance(it, Graph):
            for l in it.locals:
                yield Element("local", l.name, it.name, l)
            for st in it.states:
                yield Element("state", st.name, it.name, st)
        if isinstance(it, Interface):
            for im in it.methods:
                yield Element("method", im.name, it.name, im)
        if isinstance(it, Class):
            for d in it.dispatchers:
                yield Element("dispatcher", d.name, it.name, d)
        if isinstance(it, (Struct, Class)):
            for f in it.fields:
                yield Element("field", f.name, it.name, f)
        if isinstance(it, Enum):
            for mem in it.members:
                yield Element("member", mem.name, it.name, mem)


def new_token(taken: set, prefix: str, rng=random) -> str:
    while True:
        tok = f"{prefix}_" + "".join(rng.choice(ID_CHARS) for _ in range(4))
        if tok not in taken:
            taken.add(tok)
            return tok


def assign_ids(m: Module, rng=random, retired: Optional[set] = None) -> list:
    """Give an `@id` to every element that has none (`wiretc fmt --assign-ids`, and editor
    saves in a project). Existing ids are never changed. Returns the elements changed."""
    taken = {e.id for e in elements(m) if e.id} | set(retired or ())
    changed = []
    for e in elements(m):
        if e.id is None:
            e.obj.attrs.append(Attr("id", [(None, Lit("string", new_token(taken,
                                                                          PREFIX[e.kind], rng)))]))
            changed.append(e)
    return changed


def carry_ids(src: Module, dst: Module) -> int:
    """Copy `@id`s from `src` to the elements of `dst` that have none, matching elements by
    kind, owner and name. An editor's undo restores older text; this keeps the ids assigned
    since then on the elements they belong to, instead of retiring them. Returns how many."""
    known = {(e.kind, e.owner, e.name): e.id for e in elements(src) if e.id}
    taken = {e.id for e in elements(dst) if e.id}
    n = 0
    for e in elements(dst):
        tok = known.get((e.kind, e.owner, e.name))
        if e.id is None and tok and tok not in taken:
            e.obj.attrs.append(Attr("id", [(None, Lit("string", tok))]))
            taken.add(tok)
            n += 1
    return n


# -- the registry ----------------------------------------------------------------------
@dataclass(frozen=True)
class Retired:
    """One line of `wiret.ids`: `module graph kind id`. For an `@id` the graph is `-` and the
    kind is `id`; a node or box id is retired per graph, as `node` or `box`."""
    module: str
    graph: str
    kind: str
    id: str

    def line(self) -> str:
        return f"{self.module} {self.graph} {self.kind} {self.id}"

    def describe(self) -> str:
        return f"@id '{self.id}'" if self.kind == "id" else             f"{self.kind} id '{self.id}' in {self.graph}"


def attach_retired(m: Module, project: Optional["Project"]) -> Module:
    """Tell the printer which node ids the project retired, so a node it declares under a
    new name never reuses one (section 2.3)."""
    if project is not None:
        m.retired_nodes = {(r.graph, r.id) for r in project.retired
                           if r.module == m.name and r.kind == "node"}
    return m


def ids_of(m: Module) -> set:
    """Every id in a module as registry entries: node and box ids per graph, and `@id`s."""
    out = {Retired(m.name, "-", "id", e.id) for e in elements(m) if e.id}
    for g in m.graphs():
        # an inline node's dotted name says where it is written, not which node it is, so
        # it is never retired (section 2.3)
        out |= {Retired(m.name, g.name, "node", n.id) for n in g.nodes if "." not in n.id}
        out |= {Retired(m.name, g.name, "box", b.id) for b in g.boxes}
    return out


def retired_between(old: Optional[Module], new: Optional[Module]) -> list:
    """The ids that `old` has and `new` does not: what deleting them retires. A graph
    renamed without an `@id` retires its node ids too, since they are keyed by graph."""
    if old is None:
        return []
    gone = ids_of(old) - (ids_of(new) if new is not None else set())
    return sorted(gone, key=lambda r: (r.graph, r.kind, r.id))


@dataclass
class Project:
    """A directory with a `wiret.toml` manifest (section 7.3), and its id registry."""
    root: str
    retired: set = field(default_factory=set)
    # `[capabilities] allow` from wiret.toml; None when the manifest has no such table
    capabilities: Optional[set] = None

    @property
    def ids_path(self) -> str:
        return os.path.join(self.root, "wiret.ids")

    def load(self) -> "Project":
        self.retired = set(read_registry(self.ids_path))
        manifest = os.path.join(self.root, "wiret.toml")
        if os.path.exists(manifest):
            with open(manifest, encoding="utf-8") as f:
                self.capabilities = read_allowed_capabilities(f.read())
        return self

    def retire(self, entries) -> list:
        """Append entries not yet in the registry. Returns the ones written."""
        new = [e for e in dict.fromkeys(entries) if e not in self.retired]
        if new:
            with open(self.ids_path, "a", encoding="utf-8", newline="\n") as f:
                f.writelines(e.line() + "\n" for e in new)
            self.retired |= set(new)
        return new

    def unretire(self, entries) -> None:
        """Remove entries again. Only for ids retired by the same unsaved editing session
        (an undo of a delete); history in Git is never rewritten."""
        drop = set(entries) & self.retired
        if not drop:
            return
        lines = read_registry(self.ids_path)
        with open(self.ids_path, "w", encoding="utf-8", newline="\n") as f:
            f.writelines(e.line() + "\n" for e in lines if e not in drop)
        self.retired -= drop


def read_registry(path: str) -> list:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return parse_registry(f.read())


def parse_registry(text: str) -> list:
    out = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        parts = line.split()
        if len(parts) == 4:
            out.append(Retired(*parts))
    return out


def read_allowed_capabilities(text: str) -> Optional[set]:
    """`allow = [...]` in the `[capabilities]` table of wiret.toml (section 7.3), or None
    when there is no such table. Uses tomllib where Python has it (3.11+)."""
    try:
        import tomllib
        caps = tomllib.loads(text).get("capabilities")
        return None if caps is None else set(caps.get("allow", []))
    except ImportError:
        pass
    table, allow = None, None
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line.startswith("["):
            table = line.strip("[] ")
            if table == "capabilities" and allow is None:
                allow = set()
        elif table == "capabilities" and line.startswith("allow") and "=" in line:
            items = line.split("=", 1)[1].strip().strip("[]")
            allow = {x.strip().strip('"') for x in items.split(",") if x.strip()}
    return allow


def find_project(path: str) -> Optional[Project]:
    """The project that contains a file: the nearest directory upwards with a wiret.toml."""
    d = os.path.dirname(os.path.abspath(path))
    while True:
        if os.path.exists(os.path.join(d, "wiret.toml")):
            return Project(d).load()
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


# -- diagnostics ---------------------------------------------------------------------
def check_ids(m: Module, project: Project, D) -> None:
    """E0140 for a reused retired id, E0102 for an `@id` used twice among siblings of the
    same kind, and W0202 for an element without an `@id` (section 2.4). Only in a project:
    a lone file cannot know which ids were retired."""
    for g in m.graphs():
        for n in g.nodes:
            if "." not in n.id and Retired(m.name, g.name, "node", n.id) in project.retired:
                D("E0140", f"node id '{n.id}' was retired in wiret.ids and cannot be reused",
                  g.name, n.id)
        for b in g.boxes:
            if Retired(m.name, g.name, "box", b.id) in project.retired:
                D("E0140", f"box id '{b.id}' was retired in wiret.ids and cannot be reused",
                  g.name, b.id)
    seen = {}
    for e in elements(m):
        where = e.owner or (e.name if e.kind != "module" else None)
        if e.id is None:
            D("W0202", f"{e.kind} '{e.name}' has no @id, so renaming it would merge as a "
                       f"deletion plus an addition", where)
            continue
        if Retired(m.name, "-", "id", e.id) in project.retired:
            D("E0140", f"@id '{e.id}' on {e.kind} '{e.name}' was retired in wiret.ids and "
                       f"cannot be reused", where)
        key = (e.owner, e.kind in ("param", "result"), e.id) if e.kind in (
            "param", "result", "field", "member", "local", "state") else (None, "decl", e.id)
        if key in seen:
            D("E0102", f"@id '{e.id}' is used by both '{seen[key]}' and '{e.name}'", where)
        seen[key] = e.name
