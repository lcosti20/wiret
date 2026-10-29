"""The searchable node palette: what can be added to a graph, with beginner descriptions."""
from __future__ import annotations

import re
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import ttk
from typing import Callable, Optional

from .model import Graph, Node
from .natives import STD
from .registry import (CONSTRAINTS, STATIC_KINDS, ModuleIndex, array_elem, can_convert,
                       signature)

# kind or symbol -> (description, extra search words)
DESCRIBE = {
    "Entry": ("Where the function starts.", "start begin"),
    "Return": ("Finishes the function and hands back its results.", "end exit result output"),
    "Branch": ("If/else: follows 'then' when the condition is true, otherwise 'else'.",
               "if else condition when check decide"),
    "Sequence": ("Does several things in order: everything after then0 first, then then1, …",
                 "order steps first then do"),
    "Switch": ("Chooses a path by comparing a value with several cases.",
               "case match choose which"),
    "Select": ("Picks value a when the condition is true, otherwise value b.",
               "choose pick ternary if"),
    "Reroute": ("A bend point that tidies up wires. It does nothing else.", "tidy bend"),
    "Convert": ("Turns a value into another type, for example a number into text.",
                "cast change type to string text number"),
    "Add": ("Adds two numbers: a + b.", "+ plus sum total"),
    "Sub": ("Subtracts: a − b.", "- minus subtract difference"),
    "Mul": ("Multiplies: a × b.", "* times multiply product"),
    "Div": ("Divides: a ÷ b. Whole numbers drop the remainder.", "/ divide quotient"),
    "Rem": ("The remainder after dividing a by b (a mod b). Handy for even/odd checks.",
            "% mod modulo remainder even odd"),
    "Min": ("The smaller of a and b.", "smallest minimum lower"),
    "Max": ("The larger of a and b.", "largest maximum bigger"),
    "Neg": ("Flips the sign: −value.", "negative minus opposite"),
    "Abs": ("Distance from zero (absolute value).", "absolute positive"),
    "Eq": ("True when a equals b.", "== equal same is"),
    "Ne": ("True when a is different from b.", "!= not equal different"),
    "Lt": ("True when a is less than b (a < b).", "< less smaller below"),
    "Le": ("True when a is less than or equal to b (a ≤ b).", "<= at most"),
    "Gt": ("True when a is greater than b (a > b).", "> greater bigger more above"),
    "Ge": ("True when a is greater than or equal to b (a ≥ b).", ">= at least"),
    "And": ("True only when a and b are both true.", "&& both"),
    "Or": ("True when a or b (or both) is true.", "|| either"),
    "Xor": ("True when exactly one of a and b is true.", "exclusive"),
    "Not": ("Flips true to false and false to true.", "! opposite invert"),
    "BitAnd": ("Bitwise AND of two whole numbers.", "& bits mask"),
    "BitOr": ("Bitwise OR of two whole numbers.", "| bits"),
    "BitXor": ("Bitwise XOR of two whole numbers.", "^ bits"),
    "BitNot": ("Flips every bit of a whole number.", "~ bits"),
    "Shl": ("Shifts bits left (multiplies by 2 for each step).", "<< shift bits"),
    "Shr": ("Shifts bits right (divides by 2 for each step).", ">> shift bits"),
    "GetLocal": ("Reads a local variable.", "variable get read value"),
    "SetLocal": ("Stores a value in a local variable.", "variable set assign store save ="),
    "GetVar": ("Reads a module variable, shared by every function.", "global variable get read"),
    "SetVar": ("Stores a value in a module variable.", "global variable set assign store"),
    "GetState": ("Reads a value this graph remembers between runs.", "state remember"),
    "SetState": ("Stores a value this graph remembers between runs.", "state remember"),
    "Exit": ("Leaves the macro through this output.", "exit leave"),
    "MakeArray": ("Makes a new array from the items wired into it.",
                  "list array new create collection make"),
    "ArrayGet": ("The item at a position in the array. Positions start at 0.",
                 "list array item element index at get read"),
    "ArrayLength": ("How many items the array holds.", "list array size count length"),
    "ArrayAdd": ("Adds an item to the end of an array variable.",
                 "list array append push add"),
    "ArraySet": ("Replaces the item at a position in an array variable.",
                 "list array replace change set"),
    "ArrayInsert": ("Inserts an item at a position in an array variable.", "list array insert"),
    "ArrayRemove": ("Removes the item at a position from an array variable.",
                    "list array remove delete"),
    "ArrayClear": ("Empties an array variable.", "list array clear empty reset"),
    "std.flow.ForEach": (None, "each every item list array for"),
    "host.Log": ("Prints a line of text in the console.", "print output say write console show"),
    "std.string.Concat": ("Joins two texts together.", "join append combine + text string"),
    "std.string.Length": ("How many bytes a text has.", "size count text string"),
    "std.string.Substring": ("Part of a text, from a start position for a length.",
                             "slice part cut text"),
    "std.string.Find": ("Where a text appears inside another (−1 if it doesn't).",
                        "search index position text"),
    "std.string.ToUpper": ("The text in CAPITAL letters.", "upper caps text"),
    "std.string.ToLower": ("The text in small letters.", "lower text"),
    "std.string.Repeat": ("The text repeated a number of times.", "repeat text"),
    "std.math.Sqrt": ("Square root.", "root √"),
    "std.math.Pow": ("a to the power of b.", "power exponent ^"),
    "std.math.Floor": ("Rounds down to a whole number.", "round down"),
    "std.math.Ceil": ("Rounds up to a whole number.", "round up"),
    "std.math.Round": ("Rounds to the nearest whole number.", "round nearest"),
    "std.math.Sin": ("Sine of an angle in radians.", "trig angle"),
    "std.math.Cos": ("Cosine of an angle in radians.", "trig angle"),
    "std.math.Tan": ("Tangent of an angle in radians.", "trig angle"),
    "std.math.Atan2": ("The angle (in radians) of the point (x, y).", "trig angle"),
    "std.math.Exp": ("e to the power of x.", "exponential"),
    "std.math.Log": ("Natural logarithm.", "ln logarithm"),
    "std.math.Lerp": ("Blends from a to b: t = 0 gives a, t = 1 gives b.", "blend mix interpolate"),
    "std.math.Pi": ("The number π.", "pi circle"),
    "std.flow.ForRange": (None, "loop for count each repeat range"),
    "std.flow.Repeat": (None, "loop times do again"),
    "std.flow.DoOnce": (None, "once first only"),
    "std.flow.DoN": (None, "limit times count"),
    "std.flow.FlipFlop": (None, "toggle alternate switch"),
}

CATEGORY_ORDER = ["Flow", "Call", "Variables", "Arrays", "Macro", "Math", "Compare", "Logic",
                  "Bits"]


@dataclass
class Item:
    label: str
    kind: str
    symbol: Optional[str] = None
    targs: list = field(default_factory=list)
    category: str = "Other"
    description: str = ""
    keywords: str = ""

    def text(self) -> str:
        return f"{self.label} {self.category} {self.description} {self.keywords}".lower()


def describe(kind: str, symbol: Optional[str] = None, idx: Optional[ModuleIndex] = None) -> str:
    """A one-sentence, beginner-level description of a node kind or call."""
    if symbol and idx is not None:
        g = idx.graphs.get(symbol) or idx.macros.get(symbol)
        if g is not None:
            doc = next((a.arg().value for a in g.attrs if a.name == "doc" and a.arg()), None)
            if doc:
                return doc
            if kind == "Call":
                return f"Runs the function {symbol}."
    if symbol and symbol in DESCRIBE and DESCRIBE[symbol][0]:
        return DESCRIBE[symbol][0]
    if kind == "Call" and symbol:
        return f"Calls {symbol}."
    return DESCRIBE.get(kind, ("", ""))[0]


def _item(kind, label, cat, symbol=None, targs=None, idx=None) -> Item:
    key =symbol if symbol in DESCRIBE else kind
    words = DESCRIBE.get(key, ("", ""))[1]
    return Item(label, kind, symbol, list(targs or []), cat, describe(kind, symbol, idx), words)


def items(g: Graph, idx: ModuleIndex) -> list:
    out = []
    out.append(_item("Branch", "Branch (if / else)", "Flow"))
    out.append(_item("Sequence", "Sequence (do in order)", "Flow"))
    if g.kind != "macro":
        out.append(_item("Return", "Return", "Flow"))
    if not any(n.kind == "Entry" for n in g.nodes):
        out.append(_item("Entry", "Entry", "Flow"))
    for t in CONSTRAINTS["any"]:
        out.append(_item("Select", f"Select<{t}>", "Flow", targs=[t]))
    for t in CONSTRAINTS["switch"]:
        out.append(_item("Switch", f"Switch<{t}>", "Flow", targs=[t]))
    for t in ["exec"] + CONSTRAINTS["any"]:
        out.append(_item("Reroute", f"Reroute<{t}>", "Flow", targs=[t]))
    for k, (cat, _, tps, _) in sorted(STATIC_KINDS.items()):
        if k in ("Convert", "Select", "Branch"):
            continue
        if tps:
            for t in CONSTRAINTS[tps[0]]:
                out.append(_item(k, f"{k}<{t}>", cat, targs=[t]))
        else:
            out.append(_item(k, k, cat))
    for f in CONSTRAINTS["any"]:
        for t in CONSTRAINTS["any"]:
            if can_convert(f, t):
                to = ("text" if t == "string" else "decimal" if t in ("f32", "f64")
                      else "true/false" if t == "bool" else "whole number")
                out.append(_item("Convert", f"Convert<{f}, {t}> (to {to})", "Math", targs=[f, t]))
    for l in sorted(g.locals, key=lambda l: l.name):
        out.append(_item("GetLocal", f"Get {l.name}", "Variables", l.name))
        out.append(_item("SetLocal", f"Set {l.name}", "Variables", l.name))
    for st in sorted(g.states, key=lambda s: s.name):
        out.append(_item("GetState", f"Get state {st.name}", "Variables", st.name))
        out.append(_item("SetState", f"Set state {st.name}", "Variables", st.name))
    for v in sorted(idx.vars):
        out.append(_item("GetVar", f"Get {v}", "Variables", v))
        out.append(_item("SetVar", f"Set {v}", "Variables", v))
    for c in sorted(idx.consts):
        out.append(_item("GetVar", f"Get {c} (const)", "Variables", c))
    for name, fg in sorted(idx.graphs.items()):
        if fg.kind == "func":
            out.append(_item("Call", f"Call {name}", "Call", name, idx=idx))
    for q in sorted(idx.externs):
        out.append(_item("Call", f"Call {q}", "Call", q, idx=idx))
    for q in sorted(STD):
        out.append(_item("Call", f"Call {q}", "Call", q, idx=idx))
    for t in CONSTRAINTS["any"]:
        out.append(_item("MakeArray", f"MakeArray<{t}>", "Arrays", targs=[t]))
        out.append(_item("ArrayGet", f"ArrayGet<{t}>", "Arrays", targs=[t]))
        out.append(_item("ArrayLength", f"ArrayLength<{t}>", "Arrays", targs=[t]))
    places = [(l.name, l.type) for l in g.locals] + [(v.name, v.type) for v in idx.vars.values()]
    for name, ty in sorted(places):
        elem = array_elem(ty)
        if elem is None:
            continue
        for kind in ("ArrayAdd", "ArraySet", "ArrayInsert", "ArrayRemove", "ArrayClear"):
            out.append(_item(kind, f"{kind} {name}", "Arrays", name, [elem]))
    for name in sorted(idx.macros):
        if name == g.name:
            continue
        tps = idx.macros[name].tparams
        if tps:
            for t in CONSTRAINTS["any"]:
                out.append(_item("Macro", f"Macro {name}<{t}>", "Macro", name, [t] * len(tps),
                                 idx=idx))
        else:
            out.append(_item("Macro", f"Macro {name}", "Macro", name, idx=idx))
    if g.kind == "macro":
        for r in g.result_list:
            if r.type == "exec":
                out.append(_item("Exit", f"Exit {r.name}", "Macro", r.name))
    return out


def compatible(item: Item, g: Graph, idx: ModuleIndex, direction: str, ptype: str) -> Optional[str]:
    """The pin of `item` that a wire from (direction, ptype) would connect to, or None.

    direction is the dragged pin's direction: "out" needs an input on the new node.
    """
    sig = signature(Node("__probe", item.kind, item.symbol, item.targs), g, idx)
    if sig.error:
        return None
    pins = sig.inputs if direction == "out" else sig.outputs
    for p in pins:
        if p.type == ptype:
            return p.name
    return None


def rank(all_items: list, query: str) -> list:
    words = query.lower().split()
    scored = []
    for it in all_items:
        text = it.text()
        if not all(w in text for w in words):
            continue
        label = it.label.lower()
        score = 0
        if words:
            q = query.lower().strip()
            if label.startswith(q):
                score += 100
            elif any(part.startswith(words[0]) for part in re.split(r"[^a-z0-9]+", label)):
                score += 50
            score += sum(10 for w in words if w in it.keywords.split())
        # unqualified generic types first: i32 before i8 when nothing more specific was typed
        if "<i32>" in it.label:
            score += 3
        cat = CATEGORY_ORDER.index(it.category) if it.category in CATEGORY_ORDER else 99
        scored.append((-score, cat, it.label, it))
    scored.sort(key=lambda x: x[:3])
    return [x[3] for x in scored]


class PalettePopup(tk.Toplevel):
    """A small search window: type to filter, Enter to add, Escape to close."""

    def __init__(self, master, x_root: int, y_root: int, all_items: list,
                 on_pick: Callable[[Item], None], title: str = "Add node"):
        super().__init__(master)
        self.overrideredirect(True)
        self.configure(bg="#2b2e35", padx=1, pady=1)
        self.items = all_items
        self.on_pick = on_pick
        frame = tk.Frame(self, bg="#1d1f23")
        frame.pack(fill="both", expand=True)
        tk.Label(frame, text=title, bg="#1d1f23", fg="#8a8f98", anchor="w",
                 font=("Helvetica", 11)).pack(fill="x", padx=8, pady=(6, 0))
        self.var = tk.StringVar()
        self.entry = tk.Entry(frame, textvariable=self.var, font=("Helvetica", 14), bg="#15171a",
                              fg="white", insertbackground="white", relief="flat")
        self.entry.pack(fill="x", padx=8, pady=6, ipady=3)
        self.listbox = tk.Listbox(frame, height=12, width=44, font=("Helvetica", 13),
                                  bg="#15171a", fg="#e8e8e8", selectbackground="#2471a3",
                                  activestyle="none", relief="flat", highlightthickness=0)
        self.listbox.pack(fill="both", expand=True, padx=8)
        self.desc = tk.Label(frame, text="", bg="#1d1f23", fg="#f7dc6f", anchor="w",
                             justify="left", wraplength=380, font=("Helvetica", 12))
        self.desc.pack(fill="x", padx=8, pady=6)
        self.shown: list = []
        self.var.trace_add("write", lambda *_: self.refilter())
        self.entry.bind("<Down>", lambda e: self.move(1))
        self.entry.bind("<Up>", lambda e: self.move(-1))
        self.entry.bind("<Return>", lambda e: self.pick())
        self.entry.bind("<Escape>", lambda e: self.destroy())
        self.listbox.bind("<Double-Button-1>", lambda e: self.pick())
        self.listbox.bind("<<ListboxSelect>>", lambda e: self.show_desc())
        self.bind("<FocusOut>", self._focus_out)
        self.refilter()
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        self.geometry(f"+{min(x_root, sw - w - 10)}+{min(y_root, sh - h - 40)}")
        self.lift()
        self.entry.focus_force()

    def _focus_out(self, _e):
        self.after(100, lambda: self.winfo_exists() and self.focus_get() is None and self.destroy())

    def refilter(self):
        self.shown = rank(self.items, self.var.get())[:200]
        self.listbox.delete(0, "end")
        for it in self.shown:
            self.listbox.insert("end", f"  {it.label}")
            self.listbox.itemconfig("end", foreground="#e8e8e8")
        if self.shown:
            self.listbox.selection_set(0)
        self.show_desc()

    def move(self, d):
        if not self.shown:
            return
        cur = self.listbox.curselection()
        i = max(0, min(len(self.shown) - 1, (cur[0] if cur else 0) + d))
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(i)
        self.listbox.see(i)
        self.show_desc()

    def show_desc(self):
        cur = self.listbox.curselection()
        if cur and self.shown:
            it = self.shown[cur[0]]
            self.desc.config(text=f"{it.category}: {it.description}" if it.description
                             else it.category)
        else:
            self.desc.config(text="No matching nodes." if self.var.get() else "")

    def pick(self):
        cur = self.listbox.curselection()
        if not cur or not self.shown:
            return
        it = self.shown[cur[0]]
        self.destroy()
        self.on_pick(it)
