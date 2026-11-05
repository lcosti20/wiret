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

from . import canvasedit, ops
from .checker import GraphInfo
from .compiler import compile_module
from .explain import explain, explain_runtime
from .parser import ParseError, Parser
from .printer import print_module
from .registry import ModuleIndex
from .runner import format_results, format_value, run_function
from .viewmodel import graph_json, positions
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
    r = compile_module(m, source, debug=debug)
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
    and optionally "geoms": {node: [x, y, width]} as drawn (to place an inserted Convert node)
    and "comments": "convert". The result is {"ok", "text", "message", "select"} (`select`: a
    node the edit added). When the edit is refused, `ok` is false and `message` says why. The
    canonical text cannot keep `//` comments: then the result is {"ok": false, "comments": n}
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
    return json.dumps({"ok": True, "text": print_module(m), "message": reason,
                       "select": added[0] if added else None})

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
