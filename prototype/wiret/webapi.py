"""The calls the web front end makes into the prototype (run under Pyodide in the browser).

Each function takes plain values and returns a JSON string, so the JavaScript side never
handles Python objects. Nothing here uses Tkinter, threads, subprocesses or the file system
beyond the package's own files.

The desktop debugger pauses by blocking the VM's thread inside its hook. A browser page has
no thread to block, so `debug_run` records instead: it runs the program once and keeps every
point where the debugger could pause, with the call stack, variables and wire values there.
The page then steps through that recording (forwards and back) without calling Python again.
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Optional

from . import canvasedit, ops, syntax as syn
from . import palette as pal
from .checker import GraphInfo
from .compiler import compile_module
from .explain import explain, explain_runtime
from .parser import ParseError, Parser
from .printer import GraphNames, print_module
from .model import note_text
from .registry import ModuleIndex, enum_values
from .runner import format_results, format_value, run_function
from .viewmodel import graph_json, opens, positions
from .vm import VM, WiretError

MAX_STEPS = 5000      # pause points kept by debug_run; the run itself carries on past them
_REMEMBERED: dict = {}  # (graph, node) -> where the automatic layout put a node without a
                        # place line, so it stays put while the text is edited


def _diag(d) -> dict:
    return {"severity": d.severity, "code": d.code, "message": str(d), "explain": explain(d),
            "graph": d.graph, "node": d.top_node, "pin": d.pin}


def _new_result() -> dict:
    return {"ok": False, "output": [], "result": None, "diags": [], "error": None,
            "explain": None, "fault": None, "nodes": {}}


def _parse(source: str, out: dict):
    """The parsed module, or None with the parse error in `out`. Also fills `out["nodes"]`:
    graph -> node id -> {"line": the 1-based line of its `node`, "what": e.g. "Call host.Log"}."""
    p = Parser(source)
    try:
        m = p.parse_module()
    except ParseError as e:
        out["diags"].append({"severity": "error", "code": "parse", "message": e.msg,
                             "explain": e.msg, "line": e.line, "col": e.col})
        return None
    for tok_index, anchor in p.anchors:
        if anchor and anchor[0] == "node":
            g = m.graph(anchor[1])
            n = g.node(anchor[2]) if g else None
            what = f"{n.kind} {n.symbol}" if n and n.symbol else (n.kind if n else "")
            out["nodes"].setdefault(anchor[1], {})[anchor[2]] = {
                "line": p.toks[tok_index].line, "what": what}
    return m


def _compile(source: str, out: dict, debug: bool):
    """The parsed module and the compile result, or (None, None) with the problems in `out`."""
    m = _parse(source, out)
    if m is None:
        return None, None
    r = compile_module(m, source, debug=debug, export_all=True)   # run any function by name
    out["diags"] = [_diag(d) for d in r.diags]
    return (m, r) if r.ok else (None, None)


def _short(name: str, prefix: str) -> str:
    return name[len(prefix):] if name.startswith(prefix) else name


def _top(node: Optional[str]) -> str:
    """The node id in the source graph (inner macro nodes map to their call node)."""
    return (node or "").split("/")[0].split("!")[0]


def _fault(m, err: WiretError, out: dict):
    out["error"] = str(err)
    prefix = m.name + "."
    where = ""
    for fn, node in reversed(err.traceback or []):
        g = _short(fn, prefix)
        if node and m.graph(g):
            out["fault"] = {"graph": g, "node": _top(node)}
            where = f"node '{_top(node)}' of {g}"
            break
    out["explain"] = explain_runtime(err.status, err.message, where)


def check(source: str) -> str:
    """Parse and check without running: `diags` and `nodes`, as in `run`, and `graphs`, each
    graph as viewmodel.graph_json describes it for drawing (also when it has problems). Cheap
    enough to call while the text is being edited."""
    out = _new_result()
    m = _parse(source, out)
    graphs = []
    if m is not None:
        r = compile_module(m, source)
        out["diags"] = [_diag(d) for d in r.diags]
        idx = ModuleIndex(m)
        graphs = [graph_json(g, GraphInfo(g, idx), idx, r.diags, _REMEMBERED, m)
                  for g in m.graphs()]
    return json.dumps({"diags": out["diags"], "nodes": out["nodes"], "graphs": graphs})



def literal_prompt(source: str, graph: str, node: str, pin: str) -> str:
    """What to ask when an input's value is edited on the canvas: {"type", "current", "hint"},
    or null when the pin takes no value."""
    try:
        m = Parser(source).parse_module()
    except ParseError:
        return "null"
    g = m.graph(graph)
    if g is None or g.node(node) is None:
        return "null"
    idx = ModuleIndex(m)
    return json.dumps(canvasedit.literal_prompt(g, GraphInfo(g, idx), idx, node, pin))


def palette(source: str, graph: str, query: str = "", context: str = "null") -> str:
    """The node palette for `graph`, best matches for `query` first (as the desktop palette
    ranks them): {"title", "items": [{"label", "kind", "symbol", "targs", "category",
    "description"}], "total"}. `context` is JSON: null, or the pin a wire was dragged from,
    [node, "in"/"out", pin], to list only the nodes that fit it. null when there is nothing to
    offer (a parse error, or no such pin)."""
    try:
        m = Parser(source).parse_module()
    except ParseError:
        return "null"
    g = m.graph(graph)
    if g is None:
        return "null"
    idx = ModuleIndex(m)
    ctx = json.loads(context)
    found = canvasedit.palette(g, GraphInfo(g, idx), idx, tuple(ctx) if ctx else None)
    if found is None:
        return "null"
    title, candidates = found
    shown = pal.rank(candidates, query)[:200]
    return json.dumps({"title": title, "total": len(candidates), "items": [
        {"label": it.label, "kind": it.kind, "symbol": it.symbol, "targs": it.targs,
         "category": it.category, "description": it.description} for it in shown]})


def edit(source: str, graph: str, request: str) -> str:
    """Make one canvas edit on `graph` (through canvasedit, as the desktop editor does) and
    return the new text in canonical form. `request` is JSON with an "op":
      move             "moves": [[node or box id, x, y], ...]
      connect          "a", "b": [node, "in"/"out", pin], in either order
      connect_to_node  "a": [node, "in"/"out", pin], "node": the node it was dropped on
      disconnect       "node", "dir", "pin": the wires at that pin
      delete           "node": a node (with its wires) or a box
      literal          "node", "pin", "text": the value typed for an input (empty unbinds it)
      toggle           "node", "pin": flip a bool input
      add              "kind", "symbol", "targs" (a palette item), "x", "y", and optionally
                       "context": the pin a wire was dragged from, to wire the new node to
    and the context menu's edits (see `menu`, which builds these requests): set_enum,
    make_struct, break_struct, rename, label, color, toggle_attr, int_attr, cases, add_note,
    edit_note, delete_note, add_box, members, resize, retitle and add_local.
    and optionally "geoms": {node: [x, y, width]} as drawn (to place an inserted Convert node)
    and "comments": "convert". The result is {"ok", "text", "message", "select"} (`select`: a
    node the edit added). When the edit is refused, `ok` is false and `message` says why. The
    canonical text cannot keep a `//` comment that is attached to nothing (not directly above
    a statement, input or flow wire): then the result is {"ok": false, "comments": n}
    and nothing changes, so the page can ask and send the edit again with "comments":
    "convert", which turns them into notes."""
    req = json.loads(request)
    try:
        m = Parser(source).parse_module()
    except ParseError:
        return json.dumps({"ok": False, "message": "Fix the parse error in the source before editing the graph."})
    g = m.graph(graph)
    if g is None:
        return json.dumps({"ok": False, "message": f"There is no graph {graph}."})
    if m.comments and req.get("comments") != "convert":
        return json.dumps({"ok": False, "comments": len(m.comments)})
    idx = ModuleIndex(m)
    info = GraphInfo(g, idx)
    positions(g, info, _REMEMBERED)            # where nodes without a place line are drawn
    geoms = req.get("geoms") or {}

    def geom(nid):
        v = geoms.get(nid)
        return tuple(v) if v else None

    before = {n.id for n in g.nodes}
    op = req.get("op")
    try:
        if op == "move":
            for nid, x, y in req["moves"]:
                if g.node(nid) or g.box(nid):
                    ops.place(g, nid, round(x), round(y))
            reason = "Moved " + ", ".join(str(x[0]) for x in req["moves"])
        elif op == "connect":
            reason = canvasedit.connect(g, info, idx, tuple(req["a"]), tuple(req["b"]), geom)
        elif op == "connect_to_node":
            reason = canvasedit.connect_to_node(g, info, idx, tuple(req["a"]), req["node"], geom)
        elif op == "disconnect":
            reason = canvasedit.disconnect(g, info, req["node"], req["dir"], req["pin"])
        elif op == "delete":
            nid = req["node"]
            if g.node(nid) is not None:
                removed = ops.delete_node(g, nid)
                reason = f"Deleted {nid}" + (f" and {len(removed)} wire(s): {', '.join(removed)}"
                                             if removed else "")
            elif g.box(nid) is not None:
                ops.delete_box(g, nid)
                reason = f"Deleted box {nid}"
            else:
                reason = None
        elif op == "literal":
            reason = canvasedit.set_literal(g, info, idx, req["node"], req["pin"], req["text"])
        elif op == "toggle":
            reason = canvasedit.toggle_bool(g, req["node"], req["pin"])
        elif op == "set_enum":
            reason = canvasedit.set_enum(g, req["node"], req["pin"], req["type"], req["member"])
        elif op in ("make_struct", "break_struct"):
            make = canvasedit.make_for_pin if op == "make_struct" else canvasedit.break_struct
            _nid, reason = make(g, req["node"], req["pin"], req["type"], geom)
        elif op == "rename":
            reason = canvasedit.rename_node(g, req["node"], req["text"])
        elif op == "label":
            reason = canvasedit.set_label(g, req["node"], req["text"], _REMEMBERED)
        elif op == "color":
            reason = canvasedit.set_color(g, req["node"], req["text"], _REMEMBERED)
        elif op == "toggle_attr":
            reason = canvasedit.toggle_attr(g, req["node"], req["name"])
        elif op == "int_attr":
            reason = canvasedit.set_int_attr(g, req["node"], req["name"], req["text"])
        elif op == "cases":
            reason = canvasedit.set_cases(g, idx, req["node"], req["text"])
        elif op == "add_note":
            reason = canvasedit.add_note(g, req.get("on"), req["text"])
        elif op == "edit_note":
            reason = canvasedit.edit_note(g, req["key"], req["text"])
        elif op == "delete_note":
            reason = canvasedit.delete_note(g, req["key"])
        elif op == "add_box":
            reason = canvasedit.add_box(g, req.get("x", 0), req.get("y", 0), req["text"], req.get("member"))
        elif op == "members":
            reason = canvasedit.set_members(g, req["box"], req["text"])
        elif op == "resize":
            reason = canvasedit.resize_box(g, req["box"], req["text"])
        elif op == "retitle":
            reason = canvasedit.retitle_box(g, req["box"], req["text"])
        elif op == "add_local":
            reason = canvasedit.add_local(g, idx, req.get("kind", "local"), req["text"])
        elif op == "add":
            item = pal.Item("", req["kind"], req.get("symbol"), list(req.get("targs") or []))
            ctx = req.get("context")
            _nid, reason = canvasedit.add_node(g, idx, item, req.get("x", 0), req.get("y", 0),
                                               tuple(ctx) if ctx else None, geom)
        else:
            return json.dumps({"ok": False, "message": f"unknown edit '{op}'"})
    except canvasedit.Refused as e:
        return json.dumps({"ok": False, "message": str(e)})
    if not reason:
        return json.dumps({"ok": False, "message": ""})
    if m.comments:
        dropped = ops.convert_comments(m)
        if dropped:
            reason += " (" + "; ".join(dropped) + ")"
    canvasedit.place_unplaced(g, _REMEMBERED)
    added = [n.id for n in g.nodes if n.id not in before]
    # the page reads the new text back, where a node is known by the name it is written with
    select = GraphNames(g, ModuleIndex(m)).name(added[0]) if added else None
    if select and select != added[0]:
        reason = reason.replace(added[0], select)
    return json.dumps({"ok": True, "text": print_module(m), "message": reason, "select": select})

def menu(source: str, graph: str, target: str) -> str:
    """The context menu for something on the canvas, entry for entry as the desktop editor's
    (editor.context_menu and node_menu). `target` is JSON: {"kind": "canvas"}, {"kind":
    "node", "node"}, {"kind": "pin", "node", "dir", "pin"}, {"kind": "box", "box"}, {"kind":
    "wire", "wire": "d|node|pin" or "e|node|pin"} or {"kind": "note", "note": key}.

    Each entry is {"sep": true}, a heading {"label", "header": true}, or a choice {"label",
    ...} with one of: "action" (a request for `edit`), "ask" ({"label", "value"}: ask for text
    first and send it as the action's "text"), "confirm" (a question to ask first), or
    "client" (something the page does itself: "palette", "breakpoint", "editPin" or
    "open:<graph>"). An empty list when the target is gone or the text does not parse."""
    try:
        m = Parser(source).parse_module()
    except ParseError:
        return "[]"
    g = m.graph(graph)
    if g is None:
        return "[]"
    t = json.loads(target)
    idx = ModuleIndex(m)
    info = GraphInfo(g, idx)
    out: list = []
    sep = {"sep": True}

    def choice(label, op=None, ask=None, value="", client=None, confirm=None, **req):
        e = {"label": label}
        if op:
            e["action"] = {"op": op, **req}
        if ask is not None:
            e["ask"] = {"label": ask, "value": value}
        if client:
            e["client"] = client
            e.update(req)               # what it is about: the node (and pin)
        if confirm:
            e["confirm"] = confirm
        out.append(e)

    def node_menu(nid):
        n = g.node(nid)
        if n is None:
            return
        out.append({"label": f"{nid}  ({n.kind})", "header": True})
        target_graph = opens(m, n)
        if target_graph:
            choice(f"Open {n.symbol}", client=f"open:{target_graph}")
        choice("Breakpoint  (F9)", client="breakpoint", node=nid)
        if "." not in nid:          # an inline node's name says where it is written
            choice("Rename id…", "rename", f"New id for '{nid}' (renames every wire):", nid,
                   node=nid)
        choice("Label…", "label", f"Display label for '{nid}' (layout only; empty to clear):",
               canvasedit.current_prop(g, nid, "label"), node=nid)
        choice("Colour…", "color", "Colour such as #C0392B (empty to clear):",
               canvasedit.current_prop(g, nid, "color"), node=nid)
        choice("Add note…", "add_note", f"Note text on '{nid}':", on=nid)
        if n.kind == "Sequence":
            choice("Set output count (@count)…", "int_attr", "Number of outputs:",
                   str(canvasedit.int_attr(g, nid, "count")), node=nid, name="count")
        if n.kind == "Switch":
            prompt, cur = canvasedit.cases_prompt(g, idx, nid)
            choice("Set cases (@cases)…", "cases", prompt, cur, node=nid)
        if n.kind not in ("Entry",):
            choice(("Enable" if n.attr("disabled") else "Disable") + " (@disabled)", "toggle_attr",
                   node=nid, name="disabled")
        out.append(sep)
        choice("Delete node", "delete", node=nid,
               confirm="Delete the graph's Entry node?" if n.kind == "Entry" else None)

    kind = t.get("kind")
    if kind == "canvas":
        choice("Search nodes…   (Tab)", client="palette")
        out.append(sep)
        choice("Add box here…", "add_box", "Box title:", x=t.get("x", 0), y=t.get("y", 0))
        choice("Add graph note…", "add_note", "Note text for the whole graph:", on=None)
        choice("Add local…", "add_local", "Add local: " + canvasedit.local_prompt(idx), kind="local")
    elif kind == "node":
        node_menu(t["node"])
    elif kind == "pin":
        nid, d, pin = t["node"], t["dir"], t["pin"]
        sig = info.sigs.get(nid)
        p = (sig.input(pin) if d == "in" else sig.output(pin)) if sig else None
        if p is None:
            return "[]"
        if d == "in" and p.type in idx.enums:
            out.append({"label": f"Set '{pin}' to", "header": True})
            for member, _ in enum_values(idx.enums[p.type]):
                out.append({"label": f"{p.type}::{member}", "indent": True,
                            "action": {"op": "set_enum", "node": nid, "pin": pin,
                                       "type": p.type, "member": member}})
        elif d == "in" and p.type in idx.structs:
            choice(f"Make a {p.type} for '{pin}'", "make_struct", node=nid, pin=pin, type=p.type)
        elif d == "in" and not p.is_exec:
            choice(f"Set literal for '{pin}'…", client="editPin", node=nid, pin=pin)
        if d == "out" and p.type in idx.structs:
            choice(f"Break '{pin}' into fields", "break_struct", node=nid, pin=pin, type=p.type)
        choice("Disconnect", "disconnect", node=nid, dir=d, pin=pin)
        out.append(sep)
        node_menu(nid)
    elif kind == "box":
        bid = t["box"]
        b = g.box(bid)
        if b is None:
            return "[]"
        choice("Rename title…", "retitle", "Title:", b.title, box=bid)
        choice("Edit members…", "members",
               "Member node/box ids, comma separated (membership is explicit, section 2.3):",
               ", ".join(b.members()), box=bid)
        choice("Resize…", "resize", "width, height:", f"{b.w}, {b.h}", box=bid)
        choice("Colour…", "color", "Colour such as #C0392B (empty to clear):",
               canvasedit.current_prop(g, bid, "color"), node=bid)
        choice("Add note…", "add_note", f"Note text on '{bid}':", on=bid)
        out.append(sep)
        choice("Delete box", "delete", node=bid)
        out.append(sep)
        choice("Search nodes…   (Tab)", client="palette")
    elif kind == "wire":
        wkind, nid, pin = t["wire"].split("|")
        choice("Delete wire", "disconnect", node=nid, dir="in" if wkind == "d" else "out", pin=pin)
    elif kind == "note":
        _, nt = ops.find_note(g, t["note"])
        if nt is None:
            return "[]"
        choice("Edit note…", "edit_note", "Text:", note_text(nt), key=t["note"])
        choice("Delete note", "delete_note", key=t["note"])
    return json.dumps(out)


def syntax() -> str:
    """The Source pane's highlighting rules (wiret/syntax.py): {"pattern", "keywords",
    "kinds", "colors"}. The page applies them itself (web/syntax.js), as you type."""
    return json.dumps(syn.rules())

def run(source: str, func: str = "Main", deterministic: bool = False,
        fuel: int = 50_000_000) -> str:
    """Parse, compile and run `func` (no arguments). The result has `ok`, `output` (lines the
    program logged), `result` (formatted return values), `diags`, `nodes`, and on a
    fault `error`, `explain` (the same in plain words) and `fault` (the graph and node)."""
    out = _new_result()
    m, r = _compile(source, out, debug=False)
    if m is None:
        return json.dumps(out)
    vm = VM(output=out["output"].append, fuel=fuel, deterministic=deterministic)
    try:
        lm = vm.load(r.wbc)
        res = run_function(vm, lm, func, [])
        out["result"] = format_results(m, func, res)
        out["ok"] = True
    except WiretError as e:
        _fault(m, e, out)
    except ValueError as e:
        out["error"] = out["explain"] = str(e)
    return json.dumps(out)


def debug_run(source: str, func: str = "Main", deterministic: bool = False,
              fuel: int = 50_000_000, max_steps: int = MAX_STEPS) -> str:
    """Run like `run`, recording the debugger's pause points in `steps`, in order. Each step
    has `phase` ("enter": the node is reached, before its inputs are worked out; "ready": its
    inputs are known and it is about to run), `graph`, `node`, `depth` (call depth), `out`
    (how many output lines came before it), `frames` (outermost first, as indexes into
    `frame_table`) and `globals` (an index into `globals_table`). A frame is {`graph`,
    `node`, `vars`: [name, kind, type, value text], `pins`: {"node.pin": value text}}; the
    globals are [name, type, value text]. Most steps share frames with the step before, so
    each distinct one is stored once. `counts` maps graph -> node -> how often it ran,
    over the whole run. `truncated` is true when the run had more than `max_steps` steps."""
    out = _new_result()
    out.update(steps=[], frame_table=[], globals_table=[], counts={}, truncated=False)
    m, r = _compile(source, out, debug=True)
    if m is None:
        return json.dumps(out)
    idx = ModuleIndex(m)
    prefix = m.name + "."
    graph_names = {g.name for g in m.graphs()}
    infos: dict = {}
    counts: Counter = Counter()
    steps = out["steps"]
    loaded = []
    interned: dict = {}

    def intern(table: str, value) -> int:
        key = (table, json.dumps(value, sort_keys=True))
        if key not in interned:
            interned[key] = len(out[table])
            out[table].append(value)
        return interned[key]

    def info(g):
        if g not in infos:
            gdef = m.graph(g)
            infos[g] = GraphInfo(gdef, idx) if gdef else None
        return infos[g]

    def frame(fr) -> dict:
        g = _short(fr.func.name, prefix)
        gdef, gi = m.graph(g), info(g)
        values = fr.named_locals()
        vars_ = []
        if gdef:
            for kind, items in (("parameter", gdef.params), ("local", gdef.locals)):
                for p in items:
                    if p.name in values:
                        vars_.append([p.name, kind, p.type, format_value(p.type, values[p.name], idx)])
        pins = {}
        for (n, p), v in fr.pin_values().items():
            if "/" in n or "!" in n:
                continue
            sig = gi.sigs.get(n) if gi else None
            pin = sig.output(p) if sig else None
            pins[f"{n}.{p}"] = format_value(pin.type if pin else None, v, idx)
        return {"graph": g, "node": _top(fr.node), "vars": vars_, "pins": pins}

    def globals_() -> list:
        if not loaded:
            return []
        lm = loaded[0]
        rows = []
        for v in sorted(idx.vars.values(), key=lambda v: v.name):
            gi = lm.global_names.get(v.name)
            if gi is not None:
                rows.append([v.name, v.type, format_value(v.type, lm.globals[gi], idx)])
        return rows

    def hook(fname, node, _pending, depth, snapshot, phase):
        g = _short(fname, prefix)
        # As in the desktop debugger: macro call sites are stepped at their entry stub,
        # and nodes inside macros and library code are not stepped into.
        if "/" in node or g not in graph_names:
            return
        top = _top(node)
        if phase == "enter":
            counts[(g, top)] += 1
        if len(steps) >= max_steps:
            out["truncated"] = True
            return
        steps.append({"phase": phase, "graph": g, "node": top, "depth": depth,
                      "out": len(out["output"]),
                      "frames": [intern("frame_table", frame(f)) for f in snapshot()],
                      "globals": intern("globals_table", globals_())})

    vm = VM(output=out["output"].append, fuel=fuel, deterministic=deterministic, hook=hook)
    try:
        lm = vm.load(r.wbc)
        loaded.append(lm)
        res = run_function(vm, lm, func, [])
        out["result"] = format_results(m, func, res)
        out["ok"] = True
    except WiretError as e:
        _fault(m, e, out)
    except ValueError as e:
        out["error"] = out["explain"] = str(e)
    for (g, n), c in counts.items():
        out["counts"].setdefault(g, {})[n] = c
    return json.dumps(out)
