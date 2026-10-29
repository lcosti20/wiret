"""Plain-language explanations of diagnostics and runtime errors, for beginners.

The technical message and code stay available; these sentences are what the editor shows first.
"""
from __future__ import annotations

import re

from .checker import Diag

TYPE_WORDS = {
    "bool": "a true/false value",
    "string": "text",
    "f32": "a decimal number",
    "f64": "a decimal number",
    "exec": "an exec (order) wire",
}


def type_words(ty: str) -> str:
    if ty.startswith("array<") and ty.endswith(">"):
        inner = ty[6:-1]
        words = type_words(inner).split(" (")[0]
        for article in ("a ", "an "):
            if words.startswith(article):
                words = words[len(article):]
        return f"a list of {words}s ({ty})" if not words.endswith("text") else f"a list of texts ({ty})"
    if ty in TYPE_WORDS:
        return f"{TYPE_WORDS[ty]} ({ty})"
    if ty and ty[0] in "iu" and ty[1:].isdigit():
        sign = "" if ty[0] == "i" else "non-negative "
        return f"a {sign}whole number ({ty})"
    return ty


def zero_words(ty: str) -> str:
    return {"bool": "false", "string": "empty text", "f32": "0.0", "f64": "0.0"}.get(ty, "0")


def _quoted(msg: str, i=0):
    found = re.findall(r"'([^']*)'", msg)
    return found[i] if len(found) > i else None


def explain(d: Diag) -> str:
    c, m, node, pin = d.code, d.message, d.node, d.pin
    data = d.data or {}
    here = f"'{pin}'" if pin else "this"
    if c == "E0101":
        if "no Entry" in m:
            return "Every function needs an Entry node, where it starts. Add one: right-click → Flow → Entry."
        return (f"This wire points at a node called '{_quoted(m)}', but there is no such node. "
                f"It may have been renamed or deleted. Reconnect the wire.")
    if c == "E0102":
        if "Entry" in m:
            return "A function can only start in one place, so it can only have one Entry node."
        return f"Two things are called '{_quoted(m) or node}'. Every node needs its own name."
    if c == "E0103":
        return f"{m[0].upper()}{m[1:]}. Check the pin name (the node registry lists every pin)."
    if c == "E0110":
        if data.get("literal"):
            return f"The value typed into {here} isn't {type_words(data['dst'])}."
        if "src" in data:
            fix = ("Drag the wire again and Wiret will add a Convert node for you."
                   if data["src"] != "exec" else "")
            return (f"Input {here} needs {type_words(data['dst'])}, but the wire brings "
                    f"{type_words(data['src'])}. {fix}").strip()
        return m[0].upper() + m[1:] + "."
    if c == "E0111":
        return f"Input {here} is connected twice. An input can only receive one value."
    if c == "E0120":
        return ("White exec wires decide the ORDER things happen in; coloured data wires carry "
                "VALUES. An exec pin can only connect to an exec pin, and a data pin to a data pin.")
    if c == "E0121":
        return (f"Exec output {here} goes to two places. An exec output can only lead to one next "
                f"step. To do several things in order, use a Sequence node.")
    if c == "E0201":
        return "Calling events isn't supported yet in this prototype."
    if c == "E0301":
        return ("These calculations depend on each other in a circle, so none of them can be worked "
                "out first. Break the circle, for example by storing a value in a local variable.")
    if c == "E0302":
        return ("This function promises (with @pure or @reads) that it only calculates a result, but "
                "this node changes something. Remove the promise from the function's signature, or "
                "remove the node.")
    if c == "E0304":
        return ("This function is marked @pure, which promises its result depends only on its "
                "inputs. This node reads or calls something that could change, which breaks the "
                "promise. Pass the value in as an input instead, or remove @pure.")
    if c == "E0401":
        return "This macro uses itself, so expanding it would never end."
    if c == "E0501":
        if "later tier" in m:
            return f"'{_quoted(m)}' nodes aren't available in this prototype yet."
        if "unknown local" in m:
            return (f"There is no local variable called '{_quoted(m)}' in this graph. Add one from "
                    f"Graph → Add local….")
        if "unresolved function" in m:
            return f"There is no function called '{_quoted(m)}'. Check the spelling or create it."
        if "unresolved macro" in m:
            return f"There is no macro called '{_quoted(m)}'. Built-in ones start with std.flow."
        if "unknown node kind" in m:
            return f"Wiret doesn't know a node kind called '{_quoted(m)}'."
        return m[0].upper() + m[1:] + "."
    if c == "E0502":
        kind = m.split()[0]
        return (f"{kind} needs to know what kind of value it works with. Write it like "
                f"{kind}<i32> for whole numbers or {kind}<f64> for decimals.")
    if c == "W0201":
        ty = data.get("type", "")
        return (f"Input {here} isn't connected and has no default, so it will be "
                f"{zero_words(ty)}. Connect a wire, or double-click the pin to type a value.")
    if c == "W0301":
        return ("Nothing leads to this node, so it will never run. Connect a white exec wire into "
                "it from the step that should come before it.")
    if c == "W0302":
        return ("The function can stop here without reaching a Return node, so it would return "
                "zero. Connect this path to a Return.")
    if c == "W0310":
        return (f"This uses a result from '{_quoted(m)}', but '{_quoted(m)}' doesn't run on every "
                f"path before this node. When it hasn't run, the value is zero. Store the value "
                f"in a local variable on every path instead.")
    if c == "W0320":
        return (f"'{_quoted(m)}' reads a variable and is used by more than one step, and each step "
                f"may see a different value. If they should all see the same value, store it in "
                f"a local variable first.")
    if c == "E0130":
        return ("Array nodes that change an array need to know which array to change: the name "
                "of a local variable or module variable that holds it, written after the type, "
                "as in ArrayAdd<i32> scores.")
    if c == "W0601":
        return f"This box lists '{_quoted(m, 1)}' as a member, but nothing has that name."
    if c == "W0602":
        return f"'{_quoted(m)}' is listed in two boxes; it belongs to the first one."
    if c == "W0603":
        return ("This '//' comment isn't saved with the graph. Use File → Convert // comments to "
                "notes to keep it.")
    if c == "W0604":
        return "This note was attached to something that has been deleted."
    return m


def explain_runtime(status: str, message: str, where: str = "") -> str:
    loc = f" in {where}" if where else ""
    if status == "WR_ERR_FAULT":
        if "divide by zero" in message or "remainder by zero" in message:
            return (f"The program tried to divide by zero{loc}. Dividing by zero has no answer, so "
                    f"the program stopped. Use a Branch to check the number first.")
        if "continuation stack overflow" in message:
            return (f"A Sequence keeps starting itself again before it finishes{loc}, so unfinished "
                    f"steps pile up forever. This is a loop that never ends: make sure something "
                    f"lets it stop, for example a Branch.")
        if "stack overflow" in message:
            return (f"A function kept calling itself and never stopped{loc}. A function that calls "
                    f"itself needs a case where it stops (a 'base case').")
        if "array index" in message:
            return (f"The program asked for an item that isn't in the array{loc}: {message}. "
                    f"Array positions start at 0, so the last item is at length − 1.")
        if "Substring" in message:
            return f"The program asked for part of a text that doesn't exist{loc}: {message}."
        return f"The program stopped with an error{loc}: {message}."
    if status == "WR_ERR_FUEL":
        return ("The program ran for too long and was stopped. This usually means a loop never "
                "ends: check that the loop's condition can become false.")
    if status == "WR_ERR_INTERRUPT":
        return "You stopped the program."
    if status == "WR_ERR_LINK":
        return f"The program uses something the runtime doesn't provide: {message}."
    if status in ("WR_ERR_LOAD", "WR_ERR_VERIFY"):
        return f"The compiled file is damaged or invalid: {message}."
    return message
