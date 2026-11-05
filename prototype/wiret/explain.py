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
    if ty.startswith("array::<") and ty.endswith(">"):
        inner = ty[8:-1]
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
    return f"a {ty} value" if ty and ty.isidentifier() else ty


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
        if "built-in type" in m:
            return (f"'{_quoted(m)}' is already the name of a built-in type, so a struct or enum "
                    f"can't use it. Pick a different name, such as {_quoted(m).capitalize()}Info.")
        if "also the name of an enum" in m:
            return (f"This node is called '{_quoted(m)}', the same as an enum, so "
                    f"'{_quoted(m)}.something' could mean either. Rename the node.")
        if "duplicate field" in m or "duplicate member" in m:
            return (f"'{_quoted(m)}' is listed twice in '{_quoted(m, 1)}'. Each field or member "
                    f"needs its own name.")
        return f"Two things are called '{_quoted(m) or node}'. Every node needs its own name."
    if c == "E0103":
        return f"{m[0].upper()}{m[1:]}. Check the pin name (the node registry lists every pin)."
    if c == "E0110":
        if "of enum member" in m:
            return (f"Enum member '{_quoted(m)}' has the value {m.split()[1]}, which is too big or "
                    f"too small for {type_words(data['dst'])}. Give it a smaller value, or give "
                    f"the enum a wider type such as i32.")
        if "default of field" in m:
            return (f"The starting value of field '{_quoted(m)}' isn't "
                    f"{type_words(data['dst'])}. Change it, or remove it to start at "
                    f"{zero_words(data['dst'])}.")
        if m.startswith("case "):
            dst = data["dst"]
            fix = (f" Write each case as {dst}.Member." if "Member" in m else "")
            return (f"Case {m.split()[1]} of this Switch isn't {type_words(dst)}, so the value "
                    f"could never match it.{fix}")
        if "default of '" in m:
            return (f"The starting value of '{_quoted(m)}' is a value of a different enum. It "
                    f"needs to be {type_words(data['dst'])}.")
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
        if "names the struct" in m:
            kind = m.split()[0]
            example = f"{kind} Vec2.x" if "and the field" in m else f"{kind} Vec2"
            return (f"{kind} needs to know which struct it works on. Write it like "
                    f"'{example}', using your own struct's name.")
        if "takes no type arguments; the struct" in m:
            return ("Struct nodes don't take a ::<...> type. The struct's name already says "
                    "what type the node works with.")
        if "unknown struct" in m:
            if "is an enum" in m:
                return (f"'{_quoted(m)}' is an enum, not a struct, so it has no fields to make, "
                        f"break or read.")
            return (f"There is no struct called '{_quoted(m)}'. Check the spelling, or declare "
                    f"it with 'struct {_quoted(m)} {{ ... }}'.")
        if "has no field" in m:
            return (f"Struct '{_quoted(m)}' doesn't have a field called '{_quoted(m, 1)}'. Check "
                    f"the spelling against the struct's declaration.")
        if "structs are immutable" in m:
            return ("A struct can't be changed in place. WithField makes a copy with one field "
                    "changed; store the copy where the old one was.")
        if "unknown enum" in m:
            return (f"There is no enum called '{_quoted(m)}'. Check the spelling, or declare it "
                    f"with 'enum {_quoted(m)} {{ ... }}'.")
        if "has no member" in m:
            names = ", ".join(data.get("members") or [])
            listing = f" Its members are: {names}." if names else " It has no members yet."
            return f"Enum '{_quoted(m)}' doesn't have a member called '{_quoted(m, 1)}'.{listing}"
        if "module prefix" in m:
            return (f"Inside its own module, a type is written without the module name: write "
                    f"'{_quoted(m, 1)}' instead of '{_quoted(m)}'.")
        if "unknown type" in m:
            return (f"There is no type called '{_quoted(m)}'. Check the spelling, or declare it "
                    f"with 'struct {_quoted(m)} {{ ... }}' or 'enum {_quoted(m)} {{ ... }}'.")
        if "cannot compile struct and enum" in m:
            return (f"'{_quoted(m)}' is declared correctly, but this prototype can't run programs "
                    f"that use struct or enum values yet.")
        if "cannot have type exec" in m:
            return ("Exec wires decide the order things happen in; they aren't values, so a field "
                    "can't hold one.")
        if "unknown node kind" in m:
            return f"Wiret doesn't know a node kind called '{_quoted(m)}'."
        return m[0].upper() + m[1:] + "."
    if c == "E0503":
        return (f"Struct '{_quoted(m)}' contains itself ({m.split(': ', 1)[1]}). Every value "
                f"would need another one inside it, forever. Hold the inner one in an array "
                f"instead, which can start empty.")
    if c == "E0502":
        kind = m.split()[0]
        return (f"{kind} needs to know what kind of value it works with. Write it like "
                f"{kind}::<i32> for whole numbers or {kind}::<f64> for decimals.")
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
                "as in ArrayAdd::<i32> scores.")
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
