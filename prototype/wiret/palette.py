"""The searchable node palette: what can be added to a graph, with beginner descriptions."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .model import Graph, Node, meta_value
from .natives import STD
from .registry import (MAP_MUTATORS, MAP_PURE, SET_MUTATORS, SET_PURE, STATIC_KINDS,
                       ModuleIndex, array_elem, can_convert, is_container, map_types, set_elem,
                       signature, type_choices)

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
    "Try": ("Runs 'body'. If something goes wrong inside it, such as dividing by zero, runs "
            "'fault' instead of stopping the program. Afterwards, runs 'then'.",
            "catch error fault exception handle recover"),
    "Throw": ("Stops with an error that a Try around it can catch, with your message and code.",
              "raise error fault exception fail"),
    "New": ("Makes a new object of a class.", "create object instance make class"),
    "CallParent": ("Runs the parent class's version of this method, on the same object. Use "
                   "it in an override to add to what the parent does instead of replacing it.",
                   "super base parent inherited override call"),
    "CreateDelegate": ("Wraps a function (and, for a method, its object) into a value you can "
                       "store, pass around and call later.",
                       "callback function pointer handler event bind reference"),
    "Invoke": ("Calls the function a delegate holds.", "call run callback delegate"),
    "Bind": ("Adds a handler to an object's dispatcher, so it runs on every Broadcast.",
             "subscribe listen add handler event dispatcher on"),
    "Unbind": ("Removes a handler from an object's dispatcher.",
               "unsubscribe remove handler stop listening"),
    "Broadcast": ("Runs every handler bound to an object's dispatcher, in the order they were "
                  "bound.", "fire notify raise event call all handlers dispatcher"),
    "IsValid": ("True when an object reference is not null.", "null check exists valid none"),
    "Cast": ("Checks whether an object is of a given class.", "is type check downcast as"),
    "Delay": ("Waits for some seconds of game time, then carries on. Only in an event or a "
              "@latent function.", "wait sleep pause timer seconds later"),
    "Yield": ("Waits until the next frame (the next time step), then carries on.",
              "wait next frame tick later"),
    "Await": ("Waits until a signal is fired, then carries on.",
              "wait signal event until notify"),
    "std.signal.New": ("Makes a new signal for Await to wait on.", "signal create make"),
    "std.signal.Fire": ("Wakes everything waiting on a signal.", "signal fire notify wake"),
    "Format": ("Builds text from a template: each {name} in it becomes an input, and a "
               "number or true/false given to it is written as text.",
               "string text template concat join interpolate message number to text"),
    "Convert": ("Turns a value into another type, for example a number into text.",
                "cast change type to string text number"),
    "Add": ("Adds two numbers: a + b.", "+ plus sum total"),
    "Sub": ("Subtracts: a − b.", "- minus subtract difference"),
    "Mul": ("Multiplies: a × b.", "* times multiply product combine compose rotation"),
    "Scale": ("Multiplies every component of a vector by one number: v × s.",
              "* times scale vector stretch speed"),
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
    "Leave": ("Leaves the macro through this output at once, dropping everything the macro "
              "was still going to do, such as a loop's next pass.", "break leave stop exit early"),
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
    "MakeStruct": ("Builds a struct from a value for each of its fields.",
                   "struct make build new create record fields"),
    "BreakStruct": ("Splits a struct into its fields, one output per field.",
                    "struct break split fields unpack parts"),
    "GetField": ("Reads one field of a struct.", "struct field get read part member ."),
    "WithField": ("A copy of a struct with one field changed. The original stays as it was.",
                  "struct field set change update with copy"),
    "MapFind": ("Looks a key up in a map: its value, and whether it was there.",
                "map dictionary lookup find get key value"),
    "MapHas": ("True when the map has the key.", "map dictionary contains has key"),
    "MapLength": ("How many entries the map holds.", "map dictionary size count length"),
    "MapKeyAt": ("The key at a position, in the order keys were first added.",
                 "map dictionary key index at"),
    "MapValueAt": ("The value at a position, in the order keys were first added.",
                   "map dictionary value index at"),
    "MapSet": ("Stores a value under a key in a map variable, adding the key if it is new.",
               "map dictionary set put store add key value"),
    "MapRemove": ("Removes a key from a map variable. 'removed' says whether it was there.",
                  "map dictionary remove delete key"),
    "MapClear": ("Empties a map variable.", "map dictionary clear empty reset"),
    "SetHas": ("True when the set holds the item.", "set contains has member"),
    "SetLength": ("How many items the set holds.", "set size count length"),
    "SetAt": ("The item at a position, in the order items were added.", "set item index at"),
    "SetAdd": ("Adds an item to a set variable. 'added' is false when it was already there.",
               "set add insert unique"),
    "SetRemove": ("Removes an item from a set variable. 'removed' says whether it was there.",
                  "set remove delete"),
    "SetClear": ("Empties a set variable.", "set clear empty reset"),
    "std.flow.ForEach": (None, "each every item list array for"),
    "std.flow.ForEachMap": (None, "each every entry key value map dictionary for loop"),
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

CATEGORY_ORDER = ["Flow", "Time", "Call", "Variables", "Classes", "Delegates", "Structs", "Arrays", "Maps", "Sets", "Macro",
                  "Math", "Compare", "Logic", "Bits"]


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


def describe(kind: str, symbol: Optional[str] = None, idx: Optional[ModuleIndex] = None,
             targs: Optional[list] = None) -> str:
    """A one-sentence, beginner-level description of a node kind or call."""
    if symbol and idx is not None:
        g = idx.graphs.get(symbol) or idx.macros.get(symbol)
        if g is not None:
            doc = meta_value(g.meta, "doc")
            if doc:
                return doc
            if kind == "Call":
                return f"Runs the function {symbol}."
    if kind in ("New", "GetField", "SetField", "Cast") and idx is not None:
        cls, _, fname = (symbol or (targs[0] if targs else "")).rpartition(".")
        cls = cls or symbol or (targs[0] if targs else "")
        if cls in idx.interfaces and kind == "Cast":
            return (f"Checks whether an object implements {cls}: 'ok' says if it does, and "
                    f"'result' is the object as a {cls} (null when it does not).")
        if cls in idx.classes:
            a = "an" if cls[:1].lower() in "aeiou" else "a"
            return {"New": f"Makes a new {cls} object, with every field at its starting value.",
                    "GetField": f"Reads the field '{fname}' of {a} {cls} object.",
                    "SetField": f"Changes the field '{fname}' of {a} {cls} object. Everything "
                                f"that refers to the object sees the change.",
                    "Cast": f"Checks whether an object is {a} {cls}: 'ok' says if it is, and "
                            f"'result' is the object as {a} {cls} (null when it is not)."}[kind]
    if kind in ("MakeStruct", "BreakStruct", "GetField", "WithField") and symbol:
        return describe_struct_node(kind, symbol, idx)
    if symbol and symbol in DESCRIBE and DESCRIBE[symbol][0]:
        return DESCRIBE[symbol][0]
    if kind == "Call" and symbol and idx is not None and \
            symbol.rpartition(".")[0] in idx.interfaces:
        return (f"Calls {symbol} on any object that implements "
                f"{symbol.rpartition('.')[0]}; the object's own class decides what runs.")
    if kind == "Call" and symbol:
        spec = STD.get(f"{symbol}::<{', '.join(targs)}>" if targs else symbol)
        return spec.doc if spec is not None and spec.doc else f"Calls {symbol}."
    return DESCRIBE.get(kind, ("", ""))[0]


def describe_struct_node(kind: str, symbol: str, idx: Optional[ModuleIndex]) -> str:
    name, _, fname = symbol.partition(".")
    st = idx.structs.get(name) if idx is not None else None
    doc = meta_value(st.meta, "doc") if st is not None else None
    f = st.field(fname) if st is not None and fname else None
    fdoc = meta_value(f.meta, "doc") if f is not None else None
    a = "an" if name[:1].lower() in "aeiou" else "a"
    text = {"MakeStruct": f"Builds {a} {name} from a value for each of its fields.",
            "BreakStruct": f"Splits {a} {name} into its fields, one output per field.",
            "GetField": f"Reads the field '{fname}' of {a} {name}.",
            "WithField": f"A copy of {a} {name} with '{fname}' changed. The original stays as "
                         f"it was."}[kind]
    extra = fdoc if kind in ("GetField", "WithField") and fdoc else doc
    return f"{text} {extra}" if extra else text


def _item(kind, label, cat, symbol=None, targs=None, idx=None) -> Item:
    key = symbol if symbol in DESCRIBE else kind
    words = DESCRIBE.get(key, ("", ""))[1]
    return Item(label, kind, symbol, list(targs or []), cat, describe(kind, symbol, idx, targs),
                words)


def container_types(g: Graph, idx: ModuleIndex) -> tuple:
    """The map and set types the module uses (in signatures, locals, state, variables and
    struct fields, also inside other types): ([(K, V)], [T], [every container type]). The
    palette offers map and set nodes, and Eq and Ne on containers, for these rather than for
    every possible key and value type."""
    seen = []
    tys = [p.type for x in [g] + list(idx.graphs.values())
           for p in x.params + x.result_list + x.locals + x.states]
    tys += [v.type for v in idx.vars.values()]
    tys += [f.type for st in idx.structs.values() for f in st.fields]
    maps, sets = [], []

    def walk(ty):
        if ty in seen:
            return
        seen.append(ty)
        kv, el, ar = map_types(ty), set_elem(ty), array_elem(ty)
        if kv is not None:
            maps.append(kv)
            walk(kv[1])
        elif el is not None:
            sets.append(el)
        elif ar is not None:
            walk(ar)
    for ty in tys:
        walk(ty)
    return sorted(set(maps)), sorted(set(sets)), sorted(t for t in seen if is_container(t))


def items(g: Graph, idx: ModuleIndex) -> list:
    out = []
    out.append(_item("Branch", "Branch (if / else)", "Flow"))
    out.append(_item("Sequence", "Sequence (do in order)", "Flow"))
    if g.kind != "macro":
        out.append(_item("Return", "Return", "Flow"))
    if not any(n.kind == "Entry" for n in g.nodes):
        out.append(_item("Entry", "Entry", "Flow"))
    values = type_choices("any", idx)
    for t in values:
        out.append(_item("Select", f"Select::<{t}>", "Flow", targs=[t]))
    for t in type_choices("switch", idx):
        out.append(_item("Switch", f"Switch::<{t}>", "Flow", targs=[t]))
    for t in ["exec"] + values:
        out.append(_item("Reroute", f"Reroute::<{t}>", "Flow", targs=[t]))
    for k, (cat, _, tps, _) in sorted(STATIC_KINDS.items()):
        if k in ("Convert", "Select", "Branch"):
            continue
        if tps:
            for t in type_choices(tps[0], idx):
                out.append(_item(k, f"{k}::<{t}>", cat, targs=[t]))
        else:
            out.append(_item(k, k, cat))
    convertible = type_choices("convertible", idx)
    for f in convertible:
        for t in convertible:
            if can_convert(f, t, idx):
                to = ("text" if t == "string" else "decimal" if t in ("f32", "f64")
                      else "true/false" if t == "bool" else f"a {t}"
                      if t in idx.enums or t in ("vec2", "vec3") else "whole number")
                out.append(_item("Convert", f"Convert::<{f}, {t}> (to {to})", "Math", targs=[f, t]))
    out.append(_item("Format", 'Format "{value}" (text from a template)', "Text", "{value}"))
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
    if g.owner and g.owner in idx.classes and idx.classes[g.owner].base and \
            idx.find_method(idx.classes[g.owner].base, g.short_name) is not None:
        out.append(_item("CallParent", f"CallParent {g.short_name}", "Call", g.short_name,
                         idx=idx))
    for q in sorted(idx.externs):
        out.append(_item("Call", f"Call {q}", "Call", q, idx=idx))
    for q in sorted(STD):
        sym, _, targs = q.partition("::<")      # a generic native: std.vec.Dot::<vec3>
        out.append(_item("Call", f"Call {q}", "Call", sym, idx=idx,
                         targs=[t.strip() for t in targs[:-1].split(",")] if targs else None))
    for name in sorted(idx.classes):
        out.append(_item("New", f"New {name}", "Classes", name, idx=idx))
        out.append(_item("Cast", f"Cast to {name}", "Classes", name, idx=idx))
        for _, f in idx.class_fields(name):
            sym = f"{name}.{f.name}"
            out.append(_item("GetField", f"Get {sym}", "Classes", sym, idx=idx))
            out.append(_item("SetField", f"Set {sym}", "Classes", sym, idx=idx))
    for name in sorted(idx.interfaces):
        out.append(_item("Cast", f"Cast to {name}", "Classes", name, idx=idx))
        for m in idx.interfaces[name].methods:
            sym = f"{name}.{m.name}"
            out.append(_item("Call", f"Call {sym}", "Call", sym, idx=idx))
    if idx.classes:
        out.append(_item("IsValid", "IsValid (not null)", "Classes", idx=idx))
    for name in sorted(idx.classes):
        for d in idx.classes[name].dispatchers:
            sym = f"{name}.{d.name}"
            for k in ("Bind", "Unbind", "Broadcast"):
                out.append(_item(k, f"{k} {sym}", "Delegates", sym, idx=idx))
    for name, fg in sorted(idx.graphs.items()):
        if fg.kind == "event" or not fg.has_attr("latent"):
            out.append(_item("CreateDelegate", f"Delegate of {name}", "Delegates", name,
                             idx=idx))
    for t in sorted({p.type for gr in list(idx.graphs.values()) + [g]
                     for p in list(gr.params) + gr.result_list + list(gr.locals)
                     if p.type.startswith("delegate::<")}):
        out.append(_item("Invoke", f"Invoke::<{t}>", "Delegates", targs=[t], idx=idx))
    for name in sorted(idx.structs):
        out.append(_item("MakeStruct", f"Make {name}", "Structs", name, idx=idx))
        out.append(_item("BreakStruct", f"Break {name}", "Structs", name, idx=idx))
        for f in idx.structs[name].fields:
            sym = f"{name}.{f.name}"
            out.append(_item("GetField", f"Get {sym}", "Structs", sym, idx=idx))
            out.append(_item("WithField", f"With {sym} (changed copy)", "Structs", sym, idx=idx))
    for t in values:
        out.append(_item("MakeArray", f"MakeArray::<{t}>", "Arrays", targs=[t]))
        out.append(_item("ArrayGet", f"ArrayGet::<{t}>", "Arrays", targs=[t]))
        out.append(_item("ArrayLength", f"ArrayLength::<{t}>", "Arrays", targs=[t]))
    places = [(l.name, l.type) for l in g.locals] + [(v.name, v.type) for v in idx.vars.values()]
    places += [(f"{c}.{f.name}", f.type) for c in sorted(idx.classes)       # object fields
               for owner, f in idx.class_fields(c) if owner == c]
    for name, ty in sorted(places):
        elem = array_elem(ty)
        if elem is None:
            continue
        for kind in ("ArrayAdd", "ArraySet", "ArrayInsert", "ArrayRemove", "ArrayClear"):
            out.append(_item(kind, f"{kind} {name}", "Arrays", name, [elem]))
    maps, sets, containers = container_types(g, idx)
    for t in containers:
        for kind in ("Eq", "Ne"):
            out.append(_item(kind, f"{kind}::<{t}>", STATIC_KINDS[kind][0], targs=[t]))
    for k, v in maps:
        for kind in MAP_PURE:
            out.append(_item(kind, f"{kind}::<{k}, {v}>", "Maps", targs=[k, v]))
        if "std.flow.ForEachMap" in idx.macros:
            out.append(_item("Macro", f"Macro std.flow.ForEachMap::<{k}, {v}>", "Macro",
                             "std.flow.ForEachMap", [k, v], idx=idx))
    for t in sets:
        for kind in SET_PURE:
            out.append(_item(kind, f"{kind}::<{t}>", "Sets", targs=[t]))
    for name, ty in sorted(places):
        kv, el = map_types(ty), set_elem(ty)
        if kv is not None:
            for kind in MAP_MUTATORS:
                out.append(_item(kind, f"{kind} {name}", "Maps", name, list(kv)))
        elif el is not None:
            for kind in SET_MUTATORS:
                out.append(_item(kind, f"{kind} {name}", "Sets", name, [el]))
    for name in sorted(idx.macros):
        if name == g.name:
            continue
        tps = idx.macros[name].tparams
        if len(tps) > 1:
            continue        # ForEachMap::<K, V> is offered above, for the maps in use
        if tps:
            for t in values:
                out.append(_item("Macro", f"Macro {name}::<{t}>", "Macro", name, [t] * len(tps),
                                 idx=idx))
        else:
            out.append(_item("Macro", f"Macro {name}", "Macro", name, idx=idx))
    if g.kind == "macro":
        for r in g.result_list:
            if r.type == "exec":
                out.append(_item("Exit", f"Exit {r.name}", "Macro", r.name))
                out.append(_item("Leave", f"Leave {r.name}", "Macro", r.name))
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
