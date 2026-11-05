"""The calls the web front end makes into the prototype (run under Pyodide in the browser).

Each function takes plain values and returns a JSON string, so the JavaScript side never
handles Python objects. Nothing here uses Tkinter, threads, subprocesses or the file system
beyond the package's own files.
"""
from __future__ import annotations

import json

from .compiler import compile_module
from .parser import ParseError, parse
from .runner import format_results, run_function
from .vm import VM, WiretError


def _diag(d) -> dict:
    return {"severity": d.severity, "code": d.code, "message": str(d),
            "graph": d.graph, "node": d.top_node, "pin": d.pin}


def run(source: str, func: str = "Main", deterministic: bool = False,
        fuel: int = 50_000_000) -> str:
    """Parse, compile and run `func` (no arguments). The result has `ok`, `output` (lines the
    program logged), `result` (formatted return values), `diags` and `error`."""
    out: dict = {"ok": False, "output": [], "result": None, "diags": [], "error": None}
    try:
        m = parse(source)
    except ParseError as e:
        out["diags"].append({"severity": "error", "code": "parse", "message": e.msg,
                             "line": e.line, "col": e.col})
        return json.dumps(out)
    r = compile_module(m, source)
    out["diags"] = [_diag(d) for d in r.diags]
    if not r.ok:
        return json.dumps(out)
    vm = VM(output=out["output"].append, fuel=fuel, deterministic=deterministic)
    try:
        lm = vm.load(r.wbc)
        res = run_function(vm, lm, func, [])
        out["result"] = format_results(m, func, res)
        out["ok"] = True
    except (WiretError, ValueError) as e:
        out["error"] = str(e)
    return json.dumps(out)
