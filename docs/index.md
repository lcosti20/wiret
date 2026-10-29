# Wiret Language Specification

*Draft 0.3: text syntax, bytecode (WBC) and embedding API for a text-based visual scripting language*

> **Status.** This is a design draft, not an implementation. Nothing here has been run through a real parser, verifier or VM, so treat the grammar and opcode tables as a starting point to test, not a frozen standard. Where I went beyond your reference documents (mainly Blueprint runtime behaviour that the supplied documentation does not spell out), the text says so.

**Draft 0.2.** Revised after comparing three independent proposals (Appendix A lists every change and where it came from). The largest semantic change: `array`, `set` and `map` are now **value types** with copy-on-write, as arrays are in Blueprints (section 4.9). New material: a machine-readable node registry (3.5), a merge and editing protocol for tools and LLMs (7.1, 7.2), cross-module linking and a project manifest (7.3), capabilities, feature bits, interrupts and statistics (5.2, 5.4, 6.5, 6.10), and conformance levels (7.4).

**Draft 0.3.** Incorporates the strongest parts of an independently developed design (Appendix B). Layout moves out of node lines into a per-graph `layout` block, so moving a node and rewiring it no longer touch the same line (2.3, 2.5, 7.1). Macros gain persistent `state` slots (2.3, 4.4). Latency becomes an explicit, compiler- and verifier-checked property of a function (4.4, 4.5, 5.5). Debug data now maps pins to locals, and hosts can probe pin values (5.4, 6.10). The host ABI is hardened (6.3, 6.5, 6.6). Merging is specified as a keyed, node-level operation (7.1). A contract for graph editors and a recommended reference-implementation path are added (7.5, 7.6).

**Implementation status.** Nothing in this document is implemented. Parts expected to change after prototyping are marked **Provisional**: catchable faults (4.6), the copy-on-write rules for containers (4.9), and the choice of a stack rather than a register machine (9.1).

## 1. Overview

### 1.1 What Wiret is

Wiret is a graph-first programming language whose source of truth is a text file. A program is a set of *graphs* made of *nodes* joined by *wires*, as in Unreal Blueprints, but each graph is stored in a line-oriented, IR-like text format that diffs and merges cleanly in Git and that LLMs can read and write. A graph editor is the primary authoring tool; the text format is its storage, review and interchange format. Nobody is expected to type it by hand, but it must be pleasant to read in a diff.

| Artifact | Extension | Purpose |
| --- | --- | --- |
| Source | `.wiret` | Canonical text. This is what gets committed. |
| Bytecode | `.wbc` | Compiled, verified, portable module (WBC = Wiret ByteCode). |
| Runtime | `libwiret` | Embeddable VM with a C API (`wiret.h`, prefix `wr_`). |

### 1.2 Design principles

1. **One node, one line.** A node, with all of its incoming data wires and outgoing exec wires, is a single statement. A rewire is a one-line diff.
2. **Resolved, not inferred.** The file stores the fully resolved graph. Wildcard pins have concrete types, every automatic conversion is an explicit `Convert` node, and no behaviour depends on editor-side inference. What you read is what compiles.
3. **Every wire is written exactly once.** A data wire is written at its consumer; an exec wire is written at its producer. This matches Blueprint's rules (a data input has one source, an exec output has one target) and makes dangling wires impossible to express.
4. **Semantics and presentation are separate.** What changes compiled output is written in the node statements. Where things are drawn (position, colour, size, boxes) lives in a separate `layout` block, so moving a node and rewiring it never touch the same line. Layout never changes bytecode, but it is stored, canonicalised and diffed so every collaborator sees the same graph.
5. **Preserve what you do not understand.** Unknown attributes and layout properties survive load and save unchanged (the GML rule).
6. **Deterministic by construction.** The same `.wbc` with the same host inputs gives the same results: wrapping integer arithmetic, IEEE-754 floats, insertion-ordered maps and sets, a host-driven clock.
7. **Small core, big library.** The compiler knows a few dozen node kinds. Loops, `DoOnce`, `Gate` and similar are macros written in Wiret itself.
8. **Safe to embed.** Bytecode is verified before it runs, modules have no ambient authority (they reach the outside world only through host-registered natives), execution has fuel and memory limits, and the VM never unwinds through host frames.

### 1.3 Pipeline

```
 graph editor <-> .wiret (text) --wiretc--> .wbc (bytecode) --> libwiret VM <-> host (C API)
                      |                          |
                      +-- fmt / check / diff     +-- custom sections: names, debug map, embedded source
```

Compiler stages: parse, resolve names, type-check, validate graphs, expand macros, lower (graph to basic blocks to bytecode), optimise, verify, emit.

### 1.4 What was borrowed from where

| Source | Borrowed idea |
| --- | --- |
| Unreal Blueprints | Exec pins versus data pins, pure versus impure nodes, macros, collapsed graphs, event dispatchers, interfaces, layout boxes, reroute nodes, latent nodes, visible conversion nodes, Sequence-style "finish this branch, then the next". |
| LLVM IR | One instruction per line, named values, explicit types everywhere, metadata attached to the thing it describes (our trailing `@attrs`). |
| DOT | Addressing a part of a node (`node:port` becomes `node.pin`), attribute lists, clusters (our layout boxes). |
| GML | Nested key/value attributes, plain ASCII portability, mandatory preservation of unknown attributes, "unsafe" capitalised keys. |
| WebAssembly | Section-based binary, LEB128 integers, value-type codes, custom sections for names and debug data, single-pass validation. |
| JVM | Class, interface and vtable model, exception handler tables, an attribute system, a verifier that runs before execution. |
| Lua C API | One state object per VM, a virtual stack as the only host/VM data channel, registry references, a pluggable allocator, protected calls, coroutines. |

### 1.5 Terminology

| Term | Meaning |
| --- | --- |
| Graph | The body of a function, event or macro: nodes plus locals. |
| Node | One operation. Written `node id = Kind ...`. |
| Pin | A named input or output of a node. Has a type. |
| Exec pin | A pin of type `exec`. Wires between exec pins carry control flow. |
| Data pin | Any other pin. Wires between data pins carry values. |
| Pure node | No exec pins. Evaluated on demand by whoever consumes it. |
| Impure node | Has exec pins. Runs when control reaches it. |
| Fiber | One thread of VM execution with its own stack. Latent nodes suspend a fiber. |
| Host | The application that embeds `libwiret`. |

## 2. Text syntax

### 2.1 Files and lexical structure

A `.wiret` file is UTF-8 (no BOM) with LF line endings and holds exactly one module. Statements end at a newline. Newlines are ignored inside `( )` and inside exec maps `{ pin -> target, ... }`, so long nodes can wrap.

`//` starts a line comment. Line comments are *trivia*: the canonical writer drops them. Anything that must survive a round trip goes in a `@doc` attribute, or in a layout `box` (section 2.3) when it annotates the diagram.

| Token | Form |
| --- | --- |
| Identifier | `[A-Za-z_][A-Za-z0-9_]*` |
| Qualified name | `std.math.Sqrt` |
| Pin reference | `node_id.pin_name` |
| Integer | `42`, `-7`, `0xFF`, `1_000`; optional suffix `i8 u8 i16 u16 i32 u32 i64 u64` |
| Float | `1.5`, `2e-3`; optional suffix `f32` or `f64` |
| Other literals | `true`, `false`, `null` |
| String | `"text"` with escapes `\\n`, `\\t`, `\\"`, `\\\\` and `\\u{1F600}` |
| Tuple / list / map | `(1, 2)`, `[a, b]`, `{k: v}`; used only inside attributes |

A literal takes the type of the pin it is bound to, so suffixes are only needed where a literal is used without a pin (attribute arguments). Keywords are reserved: `wiret module use extern const var local enum struct interface class impl macro func event dispatcher node state layout box at size`.

### 2.2 Module header and declarations

Every file starts with a version line and a module line:

```
wiret 1
module game.demo @id("mod_k3f9")
```

The module name is the namespace prefix of everything declared in the file (`game.demo.Player`). The grammar below uses `NL` for a newline and `attrs` for zero or more trailing attributes (section 2.4).

```
file       = "wiret" INT NL "module" qname attrs NL { item } ;
item       = use | extern | const | var | enum | struct | interface
           | class | macro | func | event ;
use        = "use" qname [ "as" IDENT ] NL ;
extern     = "extern" ( "func" qname params [ results ] | "type" qname ) attrs NL ;
const      = "const" IDENT ":" type "=" literal attrs NL ;
var        = "var" IDENT ":" type [ "=" literal ] attrs NL ;
enum       = "enum" IDENT [ ":" inttype ] attrs "{" { IDENT [ "=" INT ] attrs NL } "}" ;
struct     = "struct" IDENT attrs "{" { field } "}" ;
field      = IDENT ":" type [ "=" literal ] attrs NL ;
interface  = "interface" IDENT attrs "{" { "func" IDENT params [ results ] attrs NL } "}" ;
class      = "class" IDENT [ ":" qname ] [ "impl" qname { "," qname } ] attrs
             "{" { field | dispatcher | func | event } "}" ;
dispatcher = "dispatcher" IDENT params attrs NL ;
func       = "func" IDENT [ tparams ] params [ results ] attrs "{" body "}" ;
event      = "event" IDENT params attrs "{" body "}" ;
macro      = "macro" IDENT [ tparams ] params [ results ] attrs "{" body "}" ;
params     = "(" [ param { "," param } ] ")" ;
results    = "->" params ;                     (* results are always named *)
param      = IDENT ":" type [ "=" literal ] ;
tparams    = "<" IDENT { "," IDENT } ">" ;
type       = prim | qname | "exec"
           | "array" "<" type ">" | "set" "<" type ">" | "map" "<" type "," type ">"
           | "delegate" "<" tlist [ "->" tlist ] ">" | "dispatcher" "<" tlist ">" ;
tlist      = "(" [ type { "," type } ] ")" ;
prim       = "bool" | "i8" | "u8" | "i16" | "u16" | "i32" | "u32"
           | "i64" | "u64" | "f32" | "f64" | "string" ;
```

Notes on the declarations:

- `struct` is a **value type**: immutable, copied by value, compared by field. `class` is a **reference type**: single inheritance, any number of `interface`s, fields default to the value written in the declaration. An `extern type` is an opaque host object (section 6.6).
- A function declared inside a class is a method. It receives an implicit first parameter `self`, visible in the graph as `entry.self`. Methods are virtual unless marked `@final`.
- An `event` is a function with no results that the host or other graphs can invoke by name, and that may contain latent nodes (section 4.5). A `dispatcher` is a multicast event slot on a class, like a Blueprint Event Dispatcher.
- A `macro` is inlined at every use, so it may contain `exec` pins as parameters and results. Everything else exposes `exec` pins implicitly.
- `extern func host.Log(message: string)` imports a host native. The import module is every segment but the last (`host`), the import name is the last (`Log`).
- `exec` is a type only for macro parameters and for the type arguments of `Reroute`.

### 2.3 Graph bodies: nodes, bindings, exec wiring

The body of a `func`, `event` or `macro` is a list of `local` and `state` declarations and `node` statements, followed by at most one `layout` block. Everything that decides behaviour is in the node statements. Everything about where things are drawn is in the layout block.

```
body    = { local | state | node } [ layout ] ;
local   = "local" IDENT ":" type [ "=" literal ] NL ;
state   = "state" IDENT ":" type [ "=" literal ] NL ;
node    = "node" IDENT "=" KIND [ symbol ] [ "<" types ">" ]
          [ "(" [ binding { "," binding } ] ")" ] [ execout ] attrs NL ;
binding = IDENT ":" ( pinref | literal ) ;
pinref  = IDENT "." IDENT ;
execout = "->" target | "{" IDENT "->" target { "," IDENT "->" target } "}" ;
target  = IDENT [ "." IDENT ] ;
layout  = "layout" "{" { place | box } "}" NL ;
place   = IDENT "at" "(" INT "," INT ")" [ props ] NL ;
box     = "box" STRING "at" "(" INT "," INT ")" "size" "(" INT "," INT ")" [ props ] NL ;
props   = "[" IDENT "=" value { "," IDENT "=" value } "]" ;
```

Rules:

1. **Node ids** are identifiers, unique within the graph and never reused, not even after the node is deleted (a merge could otherwise resurrect an old wire onto a new node). They are the identity of a node for diffs and merges. Display names are not ids; they live in the layout (`label`). Editors generate a readable slug plus a short random suffix, such as `branch_k3m9`; humans and LLMs may choose descriptive ones such as `check_energy`.
2. **Kind** is a PascalCase built-in (`Add`, `Branch`, `SetLocal`, ...; section 3.3). Calling a declared function is always `Call`, so the closed set of built-in kinds never collides with user names.
3. **Symbol** (optional) names the thing the node acts on: `Call std.math.Sqrt`, `GetField health`, `SetLocal acc`, `GetState done`, `New Player`, `Cast Player`, `Macro ForRange`, `Emit each`.
4. **Type arguments** follow the symbol: `Add<i32>`, `Convert<i32, string>`, `Call std.array.Get<f32>`. They are always written out, never inferred.
5. **Bindings** connect input pins. The right-hand side is either a pin reference (`other_node.pin`, a data wire) or a literal. An input that is not listed takes the pin's default value (the declared default, otherwise the zero value of its type); the compiler warns (`W0201`) about unlisted inputs that have no declared default.
6. **Exec wiring** is written on the producer. `-> target` is shorthand for a node with exactly one exec output. The map form names each exec output pin. An exec output that is not listed is unconnected, which means "this chain ends here" (section 4.2).
7. **Targets** are exec inputs. The default exec input is `in`; write `node.pin` to target another one. Any number of producers may target the same exec input (merging flow).
8. **Data wires** may fan out freely: any number of nodes may reference the same output pin.
9. A pin reference must name an output pin of a node in the same graph. Function and event parameters appear as output pins of the `Entry` node (`entry.amount`, and `entry.self` for methods).
10. **`state`** declares a slot that keeps its value between executions of the graph. In a macro there is one slot per expansion site, which is what `DoOnce` and `FlipFlop` need. In a method it lives on the object, in a free function on the module instance. The compiler allocates hidden fields or globals for it, named after the expansion path. Read and write it with `GetState` and `SetState`.
11. `Reroute<T>` is a visual-only node that passes a wire through a bend point. It is erased by the compiler. `Reroute<exec>` reroutes control flow.

#### The layout block

Positions and appearance are not written on node lines. They live in the graph's `layout` block, one line per node:

```
layout {
  chk       at (800, 0)
  log_dead  at (960, -40) [label = "Log death", color = "#C0392B"]
  box "Death handling" at (940, -90) size (330, 120) [color = "#C0392B"]
}
```

- A `place` line gives a node's position, and optionally `label`, `color`, `size`, `collapsed` and `hidden` (a list of pin names). Coordinates are integers, so there is no floating-point noise in diffs.
- A `box` is a visual group. A node is in a box when its position lies inside the box. A box with `collapsed = true` must also list `members = [id, ...]` explicitly; it is drawn as one node whose pins are the wires crossing its edge (the compiler still sees the flat graph).
- A node with no `place` line is auto-placed by the editor, and gets a line when first saved. This makes LLM-generated graphs valid without layout.
- Unknown properties are preserved. The block never affects the semantic hash.
- Personal view state (zoom, scroll, selection, open panels) is never written to the file (section 7.5).

This split is what makes collaboration work: one person moving a node and another rewiring it edit different lines, and they merge without a conflict.

### 2.4 Attributes and editor metadata

Attributes are written after the head of the statement they describe, on the same line (for blocks, before the `{`):

```
attr  = "@" IDENT [ "(" [ arg { "," arg } ] ")" ] ;
arg   = [ IDENT ":" ] value ;
value = literal | IDENT | tuple | list | map ;
```

**Semantic attributes** may change compiled output. Only the ones in this table do; everything else is metadata.

| Attribute | Applies to | Meaning |
| --- | --- | --- |
| `@id("...")` | any declaration, module, parameter, result, field, enum member, local | Stable identity that survives rename and move. Written by editors; optional for hand-written code. |
| `@pure` | `func` | No exec pins. Callable as a pure node. May not contain impure or latent nodes. |
| `@final` | method | Not virtual. Calls are bound at compile time. |
| `@private` | declaration | Not visible outside the module. |
| `@export` | `func`, `event`, `var`, type | Listed in the module's export table for the host and other modules. |
| `@inline` | `func` | Hint to inline at call sites. |
| `@deprecated("msg")` | declaration | Warning at every use. |
| `@count(n)` | `Sequence`, `MakeArray`, ... | Number of dynamic pins. |
| `@cases(v0, v1, ...)` | `Switch` | Case values. Pins are `case0`, `case1`, ... and `default`. |
| `@disabled` | node | Node is skipped: a one-exec-out node passes control straight to its target; data outputs read as zero. |
| @capability("name") | extern func | The import needs this host capability. Listed in the wr.caps section; the load fails unless the host granted it (section 6.5). |
| @latent | func | The function may suspend. Required when it contains a latent node or calls a latent function or event (E0201). Events are implicitly latent. A latent function is never @pure. |

**Documentation attributes** never change bytecode. They are stored and diffed, and they are covered by the layout hash but not the semantic hash (section 2.5). Node positions, labels, colours and sizes are not attributes; they live in the layout block (section 2.3).

| Attribute | Applies to | Meaning |
| --- | --- | --- |
| `@doc("text")` | any declaration or node | Tooltip and reflection text. |
| `@category("Math")`, `@keywords("a", "b")` | `func`, `macro` | Palette organisation. |

A node with no `place` line in the layout block is auto-laid-out by the editor and gets a position when first saved, so graphs written by a tool or an LLM are valid without any layout.

Wires refer to pins by name, so renaming a parameter or result would otherwise break every wire that mentions it. Giving parameters, results, fields, enum members and locals an `@id` lets an editor or merge tool recognise a rename as a rename (the id is unchanged, the name differs) and rewrite the references in one step.

**Preservation rules.**

- Unknown attributes are preserved exactly: the order of arguments and of repeated attributes is kept. A tool may not drop an attribute because it does not recognise it.
- **Unsafe attributes** (borrowed from GML): an attribute whose name starts with a capital letter, for example `@Hash(...)` or `@Cached(...)`, is derived data. Any tool that modifies the graph must delete it, and tools should not write one they cannot keep correct.
- Third parties use a namespaced name such as `@x.acme.review("ok")`. Names without a dot are reserved for this specification.

### 2.5 Canonical form, hashes and Git

The canonical form is a function of the model alone, so two tools always write identical bytes for the same graph. The formatter (`wiretc fmt`) and every editor save produce it.

1. UTF-8 NFC, LF, two-space indentation, one trailing newline.
2. Items ordered by kind (`use`, `extern`, `const`, `var`, `enum`, `struct`, `interface`, `class`, `macro`, `func`, `event`), then by name.
3. Inside a body: `local` statements by name, then `state` statements by name, then `node` statements sorted by **node id** (ASCII order), then the `layout` block last. Wiring never reorders anything.
4. Inside the layout block: `place` lines sorted by node id, then `box` lines sorted by position (y, then x) and title. Moving a node changes only its own `place` line.
5. Bindings are written in the node kind's pin order (from the registry); bindings equal to the pin default are omitted.
6. Attributes: semantic ones alphabetically, then `@doc`. Exec targets precede attributes.
7. A node longer than 100 columns wraps inside its parentheses or exec map, one binding per line.
8. Numbers and strings are written in their shortest unambiguous form.
9. Line comments are dropped.

Two hashes are defined over the canonical form, both SHA-256:

- **Semantic hash**: computed after removing the `layout` block, `@doc`, `@category`, `@keywords`, and `Reroute` nodes, and after sorting declarations by name and nodes by id. It is embedded in the `.wbc`, so CI can prove that a commit changed behaviour or did not. Two properties must hold and should be tested: reversing the order of the nodes in a graph, or deleting its layout block and all documentation attributes, changes neither the semantic hash nor a single byte of the instruction stream.
- **Layout hash**: computed over the entire canonical file. If two collaborators have the same layout hash, they see the identical graph.

Because each node is one line, lines are sorted by id, and layout lives in its own block, plain line-based Git merges succeed whenever two people touch different nodes, and a move never collides with a rewire. Two people adding nodes also rarely collide, because ids are random slugs and sort into different places. The full merge algorithm, which works on the parsed model rather than on text, is in section 7.1. The examples in this document are shown in *flow order* for readability, which `wiretc view --flow` produces; the compiler accepts any order.

Guidance for LLM authors: choose descriptive snake\_case node ids, always write type arguments, never rely on inference, read pin names from the registry (section 3.5) instead of guessing, omit the layout block, and run `wiretc check --json` and `wiretc fmt` on the output (section 7.2).

### 2.6 A complete example

This file is used again in sections 5 and 7.

```
wiret 1
module game.demo @id("mod_k3f9")

extern func host.Log(message: string) @capability("console.write")

class Player {
  health: i32 = 100

  func TakeDamage(amount: i32) -> (died: bool) {
    local new_hp: i32
    node entry     = Entry -> set_new
    node cur       = GetField health (obj: entry.self)
    node sub       = Sub<i32>(a: cur.value, b: entry.amount)
    node set_new   = SetLocal new_hp (value: sub.result) -> store
    node hp        = GetLocal new_hp
    node store     = SetField health (obj: entry.self, value: hp.value) -> chk
    node is_dead   = Le<i32>(a: hp.value, b: 0)
    node chk       = Branch(cond: is_dead.result) { then -> log_dead, else -> ret_alive }
    node log_dead  = Call host.Log(message: "Player died") -> ret_dead
    node ret_dead  = Return(died: true)
    node ret_alive = Return(died: false)
    layout {
      entry     at (0, 0)
      set_new   at (160, 0)
      cur       at (160, 120)
      sub       at (320, 120)
      store     at (480, 0)
      hp        at (480, 120)
      is_dead   at (640, 120)
      chk       at (800, 0)
      log_dead  at (960, -40) [label = "Log death"]
      ret_dead  at (1120, -40)
      ret_alive at (960, 60)
      box "Death handling" at (940, -90) size (330, 120) [color = "#C0392B"]
    }
  }

  event Respawn() {
    node entry = Entry -> wait
    node wait  = Delay(seconds: 2.0) -> reset
    node reset = SetField health (obj: entry.self, value: 100)
  }
}

func Clamp01(v: f32) -> (result: f32) @pure {
  node entry = Entry
  node lo    = Max<f32>(a: entry.v, b: 0.0)
  node hi    = Min<f32>(a: lo.result, b: 1.0)
  node ret   = Return(result: hi.result)
}

macro ForRange(in: exec, first: i32, last: i32) -> (each: exec, done: exec, index: i32) {
  local i: i32
  node entry  = Entry -> init
  node init   = SetLocal i (value: entry.first) -> test
  node cur    = GetLocal i
  node cmp    = Le<i32>(a: cur.value, b: entry.last)
  node test   = Branch(cond: cmp.result) { then -> body, else -> finish }
  node body   = Emit each (index: cur.value) -> bump
  node nxt    = Add<i32>(a: cur.value, b: 1)
  node bump   = SetLocal i (value: nxt.result) -> test
  node finish = Exit done
}

macro DoOnce(in: exec, reset: exec) -> (out: exec) {
  state fired: bool
  node entry = Entry { in -> check, reset -> clear }
  node flag  = GetState fired
  node check = Branch(cond: flag.value) { else -> mark }
  node mark  = SetState fired (value: true) -> fire
  node fire  = Exit out
  node clear = SetState fired (value: false)
}

func SumTo(n: i32) -> (total: i32) {
  local acc: i32
  node entry = Entry -> loop
  node loop  = Macro ForRange(first: 1, last: entry.n) { each -> add, done -> ret }
  node cur   = GetLocal acc
  node sum   = Add<i32>(a: cur.value, b: loop.index)
  node add   = SetLocal acc (value: sum.result)
  node total = GetLocal acc
  node ret   = Return(total: total.value)
}
```

Things to notice:

- `TakeDamage` stores the new health in a local before using it twice. `cur` is pure, so it would be re-evaluated by every impure consumer; reading `health` again after `store` would subtract the damage a second time (section 4.3).
- Node lines carry no positions. Moving `chk` edits one line of the `layout` block and cannot conflict with someone rewiring `chk`.
- `Respawn` is an `event`, which is implicitly latent, so it may contain `Delay`. `TakeDamage` has no latent nodes and is not latent, so a host can call it with `wr_call` and rely on getting a result (section 4.5).
- `add` has no exec output. A chain that ends returns control to whatever pushed it, here the macro (section 4.2), which is what makes the loop continue.
- `loop.index` is a data output of a macro node, readable by any node downstream of `loop`.
- `DoOnce` keeps its flag in a `state` slot. Each expansion of the macro gets its own slot, so two `DoOnce` nodes in one graph do not interfere.

## 3. Types and the built-in node set

### 3.1 Types

| Type | Representation | Notes |
| --- | --- | --- |
| `bool` | i32 (0 or 1) | Default `false`. |
| `i8 u8 i16 u16 i32 u32` | i32 slot | Narrow types wrap on arithmetic (`Convert` is needed to narrow explicitly). Unsigned types use unsigned compare, divide, remainder and shift. |
| `i64 u64` | i64 slot | Same rules. |
| `f32 f64` | IEEE-754 | NaN payloads are not observable except through reinterpretation. |
| `string` | immutable UTF-8 reference | Never null; default is the empty string. Indexing is by byte offset via `std.string`. |
| `enum` | its underlying integer (default `i32`) | Names are kept in the `name` custom section for editors and reflection. |
| `struct` | immutable heap record with value semantics | Equality is structural. "Setting" a field makes a new struct (`WithField`). |
| `class` | nullable reference | Equality is identity. Default `null`. |
| `array<T>` | growable, zero-based; **value type** | Copied on assignment, argument passing and return. The VM copies lazily (copy-on-write, section 4.9), so two variables never alias one array. Equality is element-wise. |
| `set<T>`, `map<K,V>` | insertion-ordered; **value types** | Same copy rules as arrays. Iteration order is insertion order, never hash order. Keys are primitives, `string`, enums or structs of those. Equality ignores order. |
| `delegate<(A)->(R)>` | reference to a function plus optional bound receiver | Single-cast. |
| `dispatcher<(A)>` | reference to an ordered handler list | Multicast; the `dispatcher` member of a class. |
| `extern type` | host handle (index plus generation) | `IsValid` is false once the host destroys the object. |
| `std.Signal`, `std.Fault` | built-in opaque classes | Used by `Await` and `Try`. |

Wires connect a source pin to a destination pin of the **same type**, or of a **supertype** (a class wire may feed a pin of its superclass or of an interface it implements). There is no other implicit conversion.

### 3.2 Conversions

The editor, like Blueprint's, offers to insert a conversion node when you connect two compatible but different types. In Wiret that node is real and visible in the text: `Convert<From, To>`.

| From | To | Behaviour |
| --- | --- | --- |
| integer | integer | Wraps (truncates, or sign/zero-extends). |
| integer | float | Nearest representable value. |
| float | integer | Truncates toward zero, **saturating**; NaN becomes 0. Never faults. |
| f64 / f32 | f32 / f64 | IEEE demote / promote. |
| bool | integer | 0 or 1. |
| integer | bool | Non-zero is true. |
| enum | its integer type, and back | Back-conversion does not check that the value names a member. |
| bool, integer, float | string | Culture-independent decimal text. Floats use the shortest text that round-trips. |
| string | number or bool | Not a `Convert`. Use `std.string.TryParse<T>`, which returns `(ok: bool, value: T)`. |

### 3.3 Built-in node kinds

Pin names are fixed per kind. Pure binary operators use inputs `a`, `b` and output `result`. `T` is the type argument. "Impure" kinds have the exec input `in` unless noted.

**Control flow**

| Kind | Pins | Behaviour |
| --- | --- | --- |
| `Entry` | out: the graph's parameters; exec out `then` | Starts a function or event. In a macro, has one exec output per `exec` parameter. |
| `Return` | in: the graph's results | Leaves the function. In a `@pure` function it has no exec input and marks the result. |
| `Branch` | in `cond: bool`; exec out `then`, `else` | Two-way choice. |
| `Sequence` | `@count(n)`; exec out `then0` .. `then{n-1}` | Runs `then0`'s chain to its end, then `then1`'s, and so on. |
| `Switch<T>` | in `value: T`; `@cases(...)`; exec out `case0`.., `default` | `T` is an integer, enum, string or bool. |
| `Select<T>` | pure; in `cond`, `a`, `b`; out `result` | Both `a` and `b` are evaluated (they are pure). |
| `Try` | exec out `body`, `fault`, `then`; out `message: string`, `code: i32` | Runs `body`. Normal end goes to `then`. A catchable fault inside it goes to `fault`. |
| `Throw` | in `message: string`, `code: i32` | Raises a catchable fault. No exec out. |
| `Delay` | in `seconds: f64`; exec out `then` | **Latent.** Suspends the fiber for virtual time. |
| `Yield` | exec out `then` | **Latent.** Resumes on the next `wr_advance`. |
| `Await` | in `signal: std.Signal`; exec out `then` | **Latent.** Resumes when the host fires the signal. |
| `Macro` | symbol: macro name; pins from its signature | Inlined at compile time. |
| `Emit` | symbol: macro exec output; in: its data outputs; exec out `then` | Macro-only. Runs the caller's chain for that output as a subroutine, then continues at `then`. |
| `Exit` | symbol: macro exec output; in: its data outputs | Macro-only. Leaves the macro through that output (a jump). |
| `Reroute<T>` | in `in`, out `out` | Visual only. |

**Variables, fields and objects**

| Kind | Pins | Behaviour |
| --- | --- | --- |
| `GetLocal` / `SetLocal` | `value` | Locals declared with `local`. `SetLocal` is impure. |
| `GetVar` / `SetVar` | `value` | Module-level `var`. |
| `GetField` | in `obj`; out `value` | Pure. Faults on a null class reference. |
| `SetField` | in `obj`, `value` | Impure. On a struct use `WithField`. |
| `WithField` | pure; in `obj`, `value`; out `result` | Returns a copy of a struct with one field replaced. |
| `MakeStruct` / `BreakStruct` | one pin per field | Pure. |
| `New` | out `result`; exec out `then` | Allocates a class instance with declared defaults. Impure because it creates identity. |
| `Cast` | pure; in `obj`; out `result`, `ok: bool` | `result` is null when the cast fails. |
| `IsValid` | pure; in `obj`; out `result: bool` | Non-null and, for host handles, still alive. |
| `Convert<From, To>` | pure; in `value`; out `result` | See section 3.2. |
| GetState / SetState | value | Persistent slots declared with state (section 2.3). SetState is impure. |

**Arithmetic, comparison, logic** (all pure)

| Kinds | Types | Notes |
| --- | --- | --- |
| `Add Sub Mul Div Rem Min Max` | `<T>` any number | Integer `Div`/`Rem` fault on zero. Integer overflow wraps. |
| `Neg Abs` | `<T>` any signed number or float | Input `value`. |
| `Eq Ne` | `<T>` number, bool, string, enum, struct, class, array, set, map (compared element-wise) | Output `bool`. |
| `Lt Le Gt Ge` | `<T>` number, string (ordinal), enum | Output `bool`. |
| `And Or Xor Not` | bool | Not short-circuiting. |
| `BitAnd BitOr BitXor BitNot Shl Shr` | `<T>` integer | Shift counts are masked to the type's width. |

**Containers**

| Kind | Notes |
| --- | --- |
| `MakeArray<T>` | Pure. `@count(n)`, inputs `item0` ... |
| `ArrayGet<T>`, `ArrayLength<T>` | Pure. Out-of-range index is a fault. |
| `ArraySet<T>`, `ArrayAdd<T>`, `ArrayInsert<T>`, `ArrayRemove<T>`, `ArrayClear<T>` | Impure. They change a **place**: the symbol names a local, a module variable, or a field. Examples: `ArrayAdd<i32> acc (item: x)` and `ArrayAdd<i32> Player.items (obj: p, item: x)`. Targeting anything else, such as a call result, is `E0130`. Arrays are value types (section 4.9), so no other variable sees the change. |
| `MapFind<K,V>` | Pure. Out: `value`, `found`. A missing key gives the zero value and `found = false`. |
| `MapHas`, `MapLength`, `MapKeyAt`, `MapValueAt` | Pure. The `At` kinds index by insertion order, which is how `ForEach` over a map is built. |
| `MapSet`, `MapRemove`, `MapClear` | Impure, and change a place exactly like the array mutators. |
| `SetHas`, `SetLength`, `SetAt` / `SetAdd`, `SetRemove`, `SetClear` | Same pattern. |
| `std.array.Append<T>`, `std.array.With<T>`, ... | Pure functional forms that return the updated container and change nothing, for use inside `@pure` functions. |

**Calls and events**

| Kind | Pins | Behaviour |
| --- | --- | --- |
| `Call` | symbol: function, method or extern; its parameters and results | Pure if the callee is `@pure` or a pure native, otherwise impure. A method call has `self` as its first input; dispatch is virtual unless `@final`, and via the interface when the symbol names an interface method. |
| `CreateDelegate` | pure; symbol: function; optional `target`; out `result` | Binds a function (and receiver) into a delegate. |
| `Invoke<D>` | `D` is a delegate type; in `delegate` plus the arguments | Impure. |
| `Bind`, `Unbind` | symbol: dispatcher; in `obj`, `handler: delegate` | Impure. |
| `Broadcast` | symbol: dispatcher; in `obj` plus the arguments | Impure. Handlers run in bind order. A fault in one handler is reported to the host and does not stop the others. |

### 3.4 The standard library

The VM ships these namespaces as natives (callable through `Call`) and as Wiret source:

- `std.math`: `Sqrt`, `Pow`, `Sin`, `Cos`, `Atan2`, `Floor`, `Ceil`, `Round`, `Clamp<T>`, `Lerp`, ... (pure).
- `std.string`: `Concat`, `Length`, `Substring`, `Find`, `Format`, `TryParse<T>`, `Split`, ... (pure).
- `std.array`, `std.map`: `Equals`, `Sort<T>` (stable, caller supplies a comparison delegate), `IndexOf<T>`, ...
- `std.random`: an explicit-state generator class (`New`, `NextI32`, `NextF64`). There is **no ambient randomness, clock or I/O**. The host provides any of those as natives, which keeps modules replayable.
- `std.flow` (macros written in Wiret): `ForRange`, `ForEach<T>`, `ForEachMap<K,V>`, `While`, `DoOnce`, `DoN`, `Gate`, `FlipFlop`, `MultiGate`, `Retriggerable`.

### 3.5 The node registry

The kinds in section 3.3 and every `std.*` function are described by a **registry**: a versioned, machine-readable JSON file that ships with the compiler (`wiretc schema --json` prints it). The registry, not the prose tables in this document, is the authority on pin names, pin types, defaults, purity and display names. Editors build their palettes from it, the compiler uses it to expand a `Kind` into pins, and LLM tooling should read it instead of guessing pin names.

```json
{ "registry": "wiret.core", "version": "1.0",
  "kinds": [
    { "kind": "Branch", "display": "Branch", "category": "Flow", "purity": "impure",
      "pins": [
        { "name": "in",   "dir": "in",  "type": "exec" },
        { "name": "cond", "dir": "in",  "type": "bool", "default": false },
        { "name": "then", "dir": "out", "type": "exec" },
        { "name": "else", "dir": "out", "type": "exec" } ] },
    { "kind": "Add", "display": "Add", "category": "Math", "purity": "pure",
      "typeParams": { "T": "number" },
      "pins": [
        { "name": "a",      "dir": "in",  "type": "T", "default": 0 },
        { "name": "b",      "dir": "in",  "type": "T", "default": 0 },
        { "name": "result", "dir": "out", "type": "T" } ] }
  ] }
```

Rules:

- A `.wiret` file never re-declares the pins of a registry kind. This keeps one line per node and one source of truth. Pins that depend on attributes (`@count`, `@cases`) are described in the registry by a pin pattern such as `then{i}`.
- Functions, methods, events and `extern func` declarations get generated registry entries from their signatures plus `@doc` and `@category`, so the same palette and tooling cover user and host code.
- Display names are for editors and may be localised. They never appear in `.wiret`.
- The registry name and version are recorded in `wr.meta` and in the project lockfile (section 7.3). An unknown kind is `E0501`.

## 4. Execution model and compilation

> **Provenance.** The supplied Blueprint documentation covers pins, macros, latent nodes and so on, but not the runtime rules below (re-evaluation of pure nodes, how a finished chain returns to a Sequence). Those rules reflect how Blueprints are commonly understood to behave and are specified here as Wiret's own semantics. Check them against Blueprint behaviour if exact compatibility matters.

### 4.1 Two kinds of nodes

Control flows along exec wires, one impure node at a time. Values flow along data wires and are produced by pure nodes on demand or by impure nodes when they run. A graph is therefore executable as a control-flow graph whose operands are small dataflow DAGs.

### 4.2 Exec flow and the continuation stack

Each call frame has a small **continuation stack**. Its entries are either a *continuation* (a place to resume) or a *fault handler marker* (section 4.6).

- Following an exec wire is a jump.
- A chain **ends** where an exec output is unconnected (or a node has no exec output). Ending pops the continuation stack and jumps to the popped continuation. If the stack holds no continuation, the frame ends: an event finishes. A function that declares results must have run `Return` first: the compiler rejects (`E0303`) any path it can prove ends with an empty stack, and warns (`W0302`) where it cannot decide. At run time such a function returns the zero value of every result.
- `Sequence` with `n` outputs pushes continuations for outputs `n-1` down to `1`, then jumps to output `0`. Each chain therefore runs to its end before the next starts, and the last chain runs in tail position with nothing pending.
- `Emit` pushes a continuation for its own `then` pin and jumps to the caller's chain for that macro output. When that chain ends, the loop macro resumes. That is how `ForRange` in section 2.6 works with no loop primitive.
- `Return` discards the whole frame, including pending continuations. `Exit` is a plain jump.

Because every bytecode label is a type-safe jump target (section 5.5), the stack's depth does not have to be statically known. When the compiler can prove the depth (the common case), the optimiser replaces the push/pop pair with a direct branch, and the generated code looks like structured code.

### 4.3 Pure nodes and data persistence

- **Evaluation unit.** Before an impure node runs, the compiler evaluates the pure nodes feeding its inputs, each at most once for that execution (shared sub-expressions are computed once). A pure node feeding two different impure nodes is evaluated twice. This is the familiar Blueprint behaviour and it is why `TakeDamage` stores its intermediate result in a local.
- **Impure outputs persist.** A data output of an impure node (a call result, `loop.index`) is stored in a frame slot when the node runs. Any later node may read it. Reading it on a path where the node has not run yet gives the zero value; the compiler warns (`W0310`) when a read is not dominated by the producing node.
- **No short-circuiting.** `And`, `Or` and `Select` evaluate every input. Use `Branch` for conditional evaluation.
- **Macro inputs** are evaluated once, at macro entry, and captured in locals.
- **Cycles** among pure nodes are rejected (`E0301`). Cycles through exec wires are loops and are allowed.

### 4.4 Functions, events, macros and groups

| Construct | Semantics |
| --- | --- |
| Function | Callable, may recurse, returns results. A function that may suspend is declared `@latent`, and the compiler checks the declaration (`E0201`): a function that contains a latent node, or calls a latent function or event, must be latent. A latent function is never `@pure`. Unlike Blueprint functions, Wiret allows this, but only when it is declared. |
| Event | A function with no results, intended as an entry point. Events are implicitly latent. Invoked by the host (`wr_push_func` plus `wr_call` or `wr_start`) or by `Call` from another latent graph. |
| Macro | Expanded in place before type-checking the caller's body. Macro locals are renamed per expansion, so two expansions never share state; `state` slots are one per expansion site. After expansion, node ids are path-style (`loop/test`), and each macro exec pin gets a synthetic stub id (`loop!each`), so debug data and diagnostics point into the macro's own nodes. A macro may not expand itself, directly or indirectly (`E0401`). |
| Collapsed group | Editor-only. A layout `box` with `collapsed = true` and explicit `members` is drawn as a single node whose pins are the wires crossing the box edge. The compiler sees the flat graph. |

### 4.5 Latent nodes and fibers

Every call runs on a **fiber**: its own value stack and call frames, heap-allocated and owned by the VM. A latent node (`Delay`, `Yield`, `Await`) compiles to `suspend`, which parks the whole fiber, including every frame beneath it, until its wake condition. The fiber resumes at the next instruction with all frames intact. Rules:

- **Latency is declared and checked.** Latent nodes (`Delay`, `Yield`, `Await`) and calls to latent functions or events are allowed only inside latent functions and events (`E0201` otherwise). The verifier enforces the same rule on bytecode: `suspend` and calls to a callee flagged latent appear only in functions flagged latent. A call to a non-latent function therefore can never suspend. A host can call a non-latent export with `wr_call` and rely on getting `WR_OK` or an error, never `WR_YIELD`.
- Latent nodes are rejected inside `@pure` functions (`E0302`) and inside natives (natives cannot suspend in version 1; see section 6.6).
- A fiber can only suspend if every frame between it and its base is a Wiret frame. A native that calls back into Wiret and then yields would have to unwind a C frame, which the VM refuses (`WR_ERR_API`), as Lua does for yielding across a C call.
- Time is virtual. `Delay` waits for virtual seconds that advance only when the host calls `wr_advance`. Wake order is by wake time, then by fiber creation order, so execution is deterministic.

### 4.6 Faults

A **fault** is a runtime error: null dereference, array index out of range, integer divide by zero, failed `ref.cast`, stack overflow, `Throw`, or an error returned by a native. Faults are catchable with `Try`. `Try` lowers to a *handler marker* pushed on the continuation stack. On a fault, the VM pops the stack down to the nearest marker, stores the fault in a local, clears the operand stack, and jumps to the handler. Normal chain ends discard markers while looking for the next continuation.

A `Try` body must be properly nested: the nodes reachable from `body` must not also be reachable from outside it (`E0412`). Without that rule a stale marker could survive past the end of the region.

Some faults cannot be caught: fuel exhausted, memory limit exceeded, and a fiber killed by the host. These end the fiber and are reported to the host.

**Provisional.** Catchable faults are the least proven part of this design. If prototyping shows that the nesting rule `E0412` rejects graphs that users find natural, `Try` and `Throw` move to a later version. Every fault would then end its fiber and be reported to the host with a node-level traceback (section 6.9), which is a complete and simpler model on its own.

### 4.7 Diagnostics

| Code | Meaning |
| --- | --- |
| `E0101` / `E0102` | Binding or exec target names an unknown node / duplicate node id. |
| `E0103` | Unknown pin on a node. |
| `E0110` | Wire type mismatch (and no supertype relation). |
| `E0111` | The same input pin is bound twice. |
| `E0120` | Exec output wired to a data pin, or a data wire to an exec pin. |
| `E0121` | An exec output is listed twice. |
| `E0301` | Cycle among pure nodes. |
| `E0302` | `@pure` function contains an impure or latent node. |
| `E0401` | Macro expands itself. |
| `E0412` | `Try` body is not properly nested. |
| `E0501` / `E0502` | Unresolved symbol / missing type argument. |
| `W0201` | Input left unbound and no declared default. |
| `W0301` | Node unreachable from any entry. |
| `W0302` | Chain can end in a function that declares results. |
| `W0310` | Read of an impure output not dominated by its producer. |
| E0130 | Container mutation node does not target a place (local, variable or field). |
| E0900 | Edit rejected: the document changed since the hash the edit was based on (section 7.2). |
| E0201 | A function that is not latent contains a latent node or calls a latent function or event. |
| E0303 | A path provably ends, with no pending continuation, in a function that declares results and has not returned. |

Diagnostics are structured records, not only text: `code`, `severity`, `message`, `module`, `graph`, `node` and `pin`. `wiretc check --json` prints one record per line. An editor uses `node` and `pin` to highlight the exact place on the graph, and an LLM agent feeds the records back to itself until the check is clean (section 7.2). Diagnostics that arise inside an expanded macro carry the path-style node id (section 4.4).

### 4.8 Lowering a graph to bytecode

1. **Expand macros** into the caller, giving every inlined node a path-style id. Entry inputs become locals, `state` slots become hidden fields or globals, and `Emit` and `Exit` become jumps and local assignments.
2. **Assign locals.** Parameters first, then declared `local`s, then one slot for each data output of each impure node that is read by another node, then temporaries.
3. **Form blocks.** Each impure node starts a block labelled with its node id. The block evaluates the pure subgraph for its inputs in dependency order, using `local.tee` for shared values, performs the operation, stores outputs, and ends with the exec transfer.
4. **Emit exec transfers.** A single target becomes `br` (omitted when the target is next in layout). `Branch` becomes `br_if`. `Switch` becomes `br_table` (or a compare chain for strings). `Sequence`, `Emit` and `Try` use the continuation instructions.
5. **Optimise.** Constant folding, removal of unread locals, branch threading, layout so fall-through follows the exec wire, and replacement of statically balanced `cont.push` / `cont.pop` by `br`. At `-Og` nothing that would hide a pin value is removed: every pin of every node is kept in a local, for debugging.
6. **Record debug data.** Each block's start offset is mapped to its node id (`wr.debug`), and each pin's local to its node and pin name (`wr.pins`).
7. **Verify** the result with the same verifier the VM runs at load time (section 5.5). A compiler bug can therefore never produce an unsafe module.

### 4.9 Containers have value semantics

`array<T>`, `set<T>` and `map<K,V>` are value types, as arrays are in Blueprints. Assigning one, passing it to a function, storing it in a field or returning it gives the receiver its own logical copy, and changing one never changes another. Two variables never alias one array.

Copying eagerly would make a loop that appends to an array quadratic, so the VM implements the rule as **copy-on-write** with a single `shared` flag per container object:

- **Fresh containers are unshared.** `array.new`, `array.clone` and the result of any mutating instruction start unshared.
- **Letting a reference escape marks sharing.** When the value of a container variable, field, parameter or element is bound to anything that can retain it (another variable or field, a call argument, a return value, a macro input), the compiler emits `ref.share` after the read. `ref.share` sets the flag and returns the same reference. Read-only nodes (`ArrayGet`, `ArrayLength`, `MapFind`, ...) do not need it.
- **Mutating instructions return the container.** `array.push` and the other mutators take the container and return one. If it is unshared they change it in place and return the same reference. If it is shared they change a fresh copy and return that. The compiler stores the result back into the place being changed, which is how `ArrayAdd<i32> acc (item: x)` works.
- **A mutation node reads its own place without marking it.** A loop that keeps adding to a local array therefore changes it in place, at constant cost per iteration, as long as nothing else has read it.
- **The flag is never cleared.** A holder that still points at a shared object copies it once on its next mutation and then owns an unshared copy. That costs at most one extra copy per sharing event and needs no reference counts, so the tracing collector is unchanged and every run behaves identically.

Consequences:

- `ForEach` iterates the array as it was when the loop started, because a macro input is captured (and so marked shared) at entry. Changing the variable inside the body does not disturb the iteration.
- A struct that contains a container holds it by shared reference. Because every read marks it shared, nothing can change a struct through its array.
- Containers of containers follow the same rule at each level: reading an element that is itself a container marks it shared.
- Classes, delegates and host handles stay reference types. An `array<Player>` copies the references, not the players.
- The optimiser removes a `ref.share` when liveness analysis shows the source holder is dead after the read, which is the common case when a function builds a local array and returns it.
- `Eq` and `Ne` on containers are structural (element-wise for arrays; set and map equality ignores insertion order) and compile to calls to `std.array.Equals`, `std.set.Equals` and `std.map.Equals`.

## 5. Bytecode specification (WBC 1)

### 5.1 Design summary

WBC is a **typed stack machine** with per-function typed locals, in the spirit of WebAssembly's encoding and the JVM's object model. Two decisions follow from graphs rather than structured source:

- **Flat code with labels, not structured blocks.** Exec wiring can form loops with several entry points and merges (irreducible control flow). WebAssembly's `block`/`loop` nesting would force a restructuring pass, which would make bytecode unrelated to the graph. WBC uses plain branches to labels, as the JVM does.
- **The operand stack is empty at every label.** Each impure node is one block that starts and ends with an empty operand stack, and only locals carry values between blocks. Locals have fixed declared types and are zero-initialised, so the verifier needs no stack maps, no merge of type states and no definite-assignment analysis. Verification is a single linear pass, and *any* label is a type-safe jump target, which is what makes the dynamic continuation stack (section 4.2) safe.

All multi-byte fixed-width values are little-endian. Integer immediates are LEB128 (`u32`/`s32`/`s64`).

### 5.2 Container

```
module  = magic version flags section*
magic   = 00 57 42 43            ; NUL 'W' 'B' 'C'
version = u32 (little endian)    ; 1
flags   = u32                    ; bit 0: has embedded source (wr.graph); bits 1-31: required features, unknown bits are rejected
section = id:u8 size:u32 payload ; ids ascending, custom sections (id 0) anywhere
vec(X)  = n:u32 X*               name = vec(u8)  ; UTF-8, no NUL
```

| Id | Section | Contents |
| --- | --- | --- |
| 0 | Custom | `name:name` then payload. Unknown custom sections are skipped. |
| 1 | Type | `vec(typeentry)` |
| 2 | Import | `vec(module:name field:name kind:u8=0 type:u32 flags:u8)`; kind 0 is a function. Flags: bit 0 pure, bit 1 reserved. `module` names a Wiret module or a host namespace; resolution order is in section 7.3. |
| 3 | Function | `vec(typeidx:u32 flags:u8)` for each defined function. Flags: bit 0 pure, bit 1 latent, bit 2 event. Function indices count imports first. |
| 4 | Global | `vec(valtype mut:u8 init:const)` |
| 5 | Export | `vec(name kind:u8 index:u32 flags:u8)`; kind 0 func, 1 global, 2 type. Flags: bit 0 event, 1 latent, 2 pure. Methods are exported as `Class.Method`. |
| 6 | Data | `vec(vec(u8))`: string constants, UTF-8. |
| 7 | Code | `vec(body)` where `body = size:u32 locals:vec(count:u32 valtype) max_stack:u32 max_cont:u32 code:bytes` |

A `const` is 8 bytes (numeric bit pattern), or a `u32` data index for `string`, or empty for references (always null).

### 5.3 Value types and type entries

| Code | Value type |  | Code | Storage-only type |
| --- | --- | --- | --- | --- |
| `7F` | i32 (also bool and all narrow integers) |  | `78` | i8 (loads sign-extend, stores truncate) |
| `7E` | i64 |  | `77` | i16 (same) |
| `7D` | f32 |  |  |  |
| `7C` | f64 |  |  |  |
| `6E` | string (never null) |  |  |  |
| `6B t` | nullable reference to type index `t` (class, struct, array, map, set, interface, delegate, dispatcher) |  |  |  |
| `6A` | fault |  |  |  |
| `69` | signal |  |  |  |
| `6D` | anyref (top of the reference types) |  |  |  |

| Code | Type entry | Body |
| --- | --- | --- |
| `60` | func | `params:vec(valtype) results:vec(valtype)` |
| `5F` | struct | `fields:vec(field)` |
| `5E` | array | `elem:storagetype` |
| `5D` | map | `key:valtype value:valtype` |
| `5C` | set | `elem:valtype` |
| `5B` | class | `flags:u8 super:u32 interfaces:vec(iface:u32 impl:vec(funcidx)) fields:vec(field) vtable:vec(funcidx)`. `super` is 0 for none, else type index + 1. Flag bit 0 marks a host type: then a `name` follows and there are no fields. `fields` are the class's own; inherited fields come first in the layout. `vtable` holds the full slot list, with overrides replacing inherited slots. |
| `5A` | interface | `methods:vec(functype:u32)`; the method index is the dispatch slot. |
| `59` | delegate | `functype:u32` |
| `58` | dispatcher | `functype:u32` (no results) |

`field = storagetype flags:u8 [const]` where flag bit 0 says a default value follows.

### 5.4 Custom sections defined by this version

| Name | Purpose |
| --- | --- |
| `name` | Names of functions, locals, types, fields and enum members, for tools and reflection. |
| `wr.debug` | Maps code offsets to graph position. For each function: its graph item id, a string table of node ids (path-style after macro expansion, such as `loop/test`), and `vec(pc_delta:u32 node:u32)`. Drives node-level breakpoints, stepping and tracebacks. |
| `wr.pins` | For each function: `vec(local:u32 node:u32 pin:u32)`, naming the node output pin that each local holds (indices into the `wr.debug` string table). Complete for `-Og` builds; otherwise it lists the pins that survive optimisation. Lets an editor show the value on a wire and lets the host call `wr_getpin`. |
| `wr.graph` | The canonical `.wiret` text, deflate-compressed. Lets a debugger or editor open a `.wbc` it did not build. |
| `wr.meta` | Module id, compiler and registry versions, **semantic hash** and **layout hash** (section 2.5), source hash. |
| `wr.reflect` | Attribute data for the host: `@doc`, `@category`, parameter names and defaults. |
| `wr.caps` | Every capability the module's imports require, so a host can inspect or refuse a module before loading it. |

**Sidecar.** `wiretc build --sidecar` writes `wr.debug`, `wr.pins`, `wr.graph` and `wr.reflect` to a separate `out.wdbg` file instead of embedding them. `wr.meta` in both files carries the same module id and semantic hash, so a debugger can match them. Release builds can ship the small `.wbc` alone.

### 5.5 Verification

A conforming VM verifies every module before running any of it. The verifier makes one linear pass over each function and requires all of the following.

1. **Structure.** Sections are in order and sizes agree; every index is in range; exports are unique; the class hierarchy is acyclic; each vtable entry and interface implementation has the required signature.
2. **Decoding.** Every instruction decodes; every branch target is an instruction boundary inside the same function. A first pass collects the set of labels.
3. **Empty stack at labels.** The operand stack is empty before every label, after `br`, `br_table`, `return`, `throw`, `unreachable`, and after `cont.pop` (which falls through only when no continuation exists). A branch may only occur when its own operands are the entire stack: `br_if` with exactly one `i32` on the stack, `br_table` likewise.
4. **Typing.** Each instruction's operands match its signature (section 5.6). References follow subtyping: a class is a subtype of its superclass chain and interfaces; every reference type is a subtype of `anyref`; null has every reference type. `local.*` and `global.*` match the declared types.
5. **Returns.** At `return` the stack holds exactly the function's result types.
6. **Limits.** The computed maximum operand stack height is at most `max_stack`. `try.push` names a local of type `fault`.
7. **Suspension and latency.** `suspend`, and any call to a function flagged latent, appear only in functions that are themselves flagged latent. A function flagged pure is never latent. `suspend` executes with only its operands on the stack. A non-latent function therefore cannot suspend, however deeply it calls.

Stack maps for the GC are derived by the verifier at call, allocation and suspend points and cached.

### 5.6 Instruction set

Notation: `[in] -> [out]`. `L` is a branch target, an `s32` offset relative to the end of the instruction. `T` is a type index and `f` a field index. Unless stated, a null reference operand faults.

**Control (00 to 0F)**

| Op | Mnemonic | Immediates | Stack |
| --- | --- | --- | --- |
| 00 | `unreachable` |  | faults |
| 01 | `nop` |  |  |
| 02 | `br` | L |  |
| 03 | `br_if` | L | `[i32]` -> `[]` |
| 04 | `br_table` | n, L0 ... Ln-1, Ldefault | `[i32]` -> `[]` |
| 05 | `return` |  | `[results]` -> |
| 06 | `call` | func | `[params]` -> `[results]` |
| 07 | `call_virtual` | T (declaring class), slot | `[recv, args]` -> `[results]` |
| 08 | `call_interface` | T (interface), method | `[recv, args]` -> `[results]` |
| 09 | `call_delegate` | T (func type) | `[delegate, args]` -> `[results]` |
| 0A | `cont.push` | L |  |
| 0B | `cont.pop` |  | Jumps to the top continuation; discards handler markers on the way; falls through if none. |
| 0C | `try.push` | L, local | Pushes a handler marker. On a fault the VM stores the fault in `local`, unwinds to the marker, clears the operand stack and jumps to L. |
| 0D | `suspend` | kind: 0 yield, 1 timer, 2 signal | `[]`, `[f64]` or `[signal]` -> `[]` |
| 0E | `throw` |  | `[fault]` -> |
| 0F | `brk` |  | Reserved for debuggers. Never appears in a file. |

**Variables and constants (10 to 2F)**

| Op | Mnemonic | Immediates | Stack |
| --- | --- | --- | --- |
| 10 | `drop` |  | `[t]` -> `[]` |
| 11 | `select` |  | `[t, t, i32]` -> `[t]`; first operand when the condition is non-zero. |
| 12 / 13 / 14 | `local.get` / `.set` / `.tee` | index |  |
| 15 / 16 | `global.get` / `.set` | index |  |
| 20 / 21 | `i32.const` / `i64.const` | s32 / s64 | `[]` -> `[i32]` / `[i64]` |
| 22 / 23 | `f32.const` / `f64.const` | 4 / 8 bytes |  |
| 24 | `string.const` | data index | `[]` -> `[string]` |
| 25 | `ref.null` | T | `[]` -> `[ref T]` |
| 26 | `ref.is_null` |  | `[ref]` -> `[i32]` |
| 27 | `ref.eq` |  | `[ref, ref]` -> `[i32]`, identity. |
| 28 | `ref.cast` | T | `[ref]` -> `[ref T]`; faults unless null or an instance of T. |
| 29 | `ref.test` | T | `[ref]` -> `[i32]`; null gives 0. |
| 2A | `ref.valid` |  | `[ref]` -> `[i32]`; non-null and, for host handles, alive. |
| 2B | ref.share |  | \[ref\] -> \[ref\]. Marks an array, set or map object as shared (section 4.9) and returns the same reference. No effect on other references. |

**Numeric.** Four 32-slot blocks. The opcode is the block base plus the index in the table; for example `i32.add` is `30 + 0B = 3B`.

| Block | Base | Operations (index order) |
| --- | --- | --- |
| `i32.` | 30 | 0 `eqz`, 1 `eq`, 2 `ne`, 3 `lt_s`, 4 `lt_u`, 5 `gt_s`, 6 `gt_u`, 7 `le_s`, 8 `le_u`, 9 `ge_s`, 10 `ge_u`, 11 `add`, 12 `sub`, 13 `mul`, 14 `div_s`, 15 `div_u`, 16 `rem_s`, 17 `rem_u`, 18 `and`, 19 `or`, 20 `xor`, 21 `shl`, 22 `shr_s`, 23 `shr_u`, 24 `neg`, 25 `not`, 26 `extend8_s`, 27 `extend16_s` |
| `i64.` | 50 | Same indices, plus 28 `extend32_s`. Comparisons and `eqz` return `i32`. |
| `f32.` | 70 | 0 `eq`, 1 `ne`, 2 `lt`, 3 `gt`, 4 `le`, 5 `ge`, 6 `add`, 7 `sub`, 8 `mul`, 9 `div`, 10 `min`, 11 `max`, 12 `neg`, 13 `abs`, 14 `sqrt`, 15 `ceil`, 16 `floor`, 17 `trunc`, 18 `nearest`, 19 `copysign` |
| `f64.` | 90 | Same as f32. |

Integer `div` and `rem` by zero fault. `INT_MIN / -1` yields `INT_MIN` and the remainder is 0 (no fault). Shift counts are masked to the width. `min`/`max` return NaN if either operand is NaN. Narrow integer types are produced by `and` with a mask (unsigned) or `extend8_s`/`extend16_s` (signed) after arithmetic.

**Conversions (B0 to C8)**

| Op | Mnemonic | Op | Mnemonic | Op | Mnemonic |
| --- | --- | --- | --- | --- | --- |
| B0 | `i32.wrap_i64` | BB | `f32.convert_i32_s` | C3 | `f32.demote_f64` |
| B1 | `i64.extend_i32_s` | BC | `f32.convert_i32_u` | C4 | `f64.promote_f32` |
| B2 | `i64.extend_i32_u` | BD | `f32.convert_i64_s` | C5 | `i32.reinterpret_f32` |
| B3 / B4 | `i32.trunc_f32_s` / `_u` | BE | `f32.convert_i64_u` | C6 | `i64.reinterpret_f64` |
| B5 / B6 | `i32.trunc_f64_s` / `_u` | BF / C0 | `f64.convert_i32_s` / `_u` | C7 | `f32.reinterpret_i32` |
| B7 / B8 | `i64.trunc_f32_s` / `_u` | C1 / C2 | `f64.convert_i64_s` / `_u` | C8 | `f64.reinterpret_i64` |
| B9 / BA | `i64.trunc_f64_s` / `_u` |  |  |  |  |

All `trunc` instructions are **saturating** and map NaN to 0. They never fault.

**Objects and containers (D0 to F8)**

| Op | Mnemonic | Imm | Stack |
| --- | --- | --- | --- |
| D0 | `struct.new` | T | `[fields...]` -> `[ref]` |
| D1 / D2 | `struct.get` / `struct.with` | T, f | `[ref]` -> `[v]` / `[ref, v]` -> `[ref']` (copy with one field replaced) |
| D3 | `class.new` | T | `[]` -> `[ref]`, fields set to declared defaults, dispatchers empty. |
| D4 / D5 | `class.get` / `class.set` | T, f | `[ref]` -> `[v]` / `[ref, v]` -> `[]` |
| D6 | `array.new` | T | `[i32 length]` -> `[ref]`, zero-filled, unshared. |
| D7 | `array.len` |  | `[ref]` -> `[i32]` |
| D8 | `array.get` | T | `[ref, i32]` -> `[v]` (bounds-checked) |
| D9 | `array.set` | T | `[ref, i32, v]` -> `[ref']` |
| DA / DB | `array.push` / `array.insert` | T | `[ref, v]` / `[ref, i32, v]` -> `[ref']` |
| DC / DD | `array.remove` / `array.clear` | T | `[ref, i32]` / `[ref]` -> `[ref']` |
| DE | `array.clone` | T | `[ref]` -> `[ref']`, a fresh unshared copy. |
| E0 | `map.new` | T | `[]` -> `[ref]` |
| E1 | `map.find` | T | `[ref, key]` -> `[value, i32 found]` |
| E2 / E3 / E4 | `map.set` / `map.remove` / `map.has` | T | `[ref, key, v]` -> `[ref']` / `[ref, key]` -> `[ref', i32 was present]` / `[ref, key]` -> `[i32]` |
| E5 / E8 | `map.len` / `map.clear` | T | `[ref]` -> `[i32]` / `[ref]` -> `[ref']` |
| E6 / E7 | `map.key_at` / `map.value_at` | T | `[ref, i32]` -> `[k]` / `[v]`, insertion order. |
| E9 / EA / EB / EC | `set.new` / `.add` / `.remove` / `.has` | T | `add` and `remove` return `[ref', i32 changed]`; `has` returns `[i32]`. |
| ED / EE / EF | `set.len` / `set.at` / `set.clear` | T | as for maps |
| F0 | `string.concat` |  | `[string, string]` -> `[string]` |
| F1 | `string.len` |  | `[string]` -> `[i32]` (bytes) |
| F2 / F3 | `string.eq` / `string.cmp` |  | `[string, string]` -> `[i32]`; `cmp` is -1, 0 or 1 (ordinal bytes). |
| F4 | `delegate.new` | func, flags | `[]` or `[recv]` -> `[ref]`. Flag bit 0: bind a receiver as the first argument. |
| F5 / F6 | `dispatcher.bind` / `.unbind` | T | `[ref, delegate]` -> `[]` |
| F7 | `dispatcher.broadcast` | T | `[ref, args]` -> `[]`. Runs handlers in bind order; a handler's fault is reported to the host and does not stop the others. |
| FB | *prefix* |  | Next byte is a LEB128 sub-opcode. Reserved for future instructions. |

All other opcodes are invalid. Everything else a node needs (string formatting, math, sorting) is a native in `std.*`, which keeps the instruction set small and lets embedders replace library functions.

### 5.7 Fuel

Each instruction costs 1 unit; `call`, `call_virtual`, `call_interface` and `call_delegate` cost 5; allocation adds 1 per 64 bytes (rounded up). Natives cost what they declare at registration. When a fiber's fuel reaches 0 it stops with `WR_ERR_FUEL`, which is not catchable. Counting is exact and deterministic, so fuel is a valid replay and billing unit.

### 5.8 Disassembly

`wiretc dis` prints the bytecode with node ids recovered from `wr.debug`. The two listings below are the compiled forms of `TakeDamage` and `SumTo` from section 2.6 (at `-O1`; at `-O0` the loop keeps its `cont.push` / `cont.pop` pair).

```
func game.demo.Player.TakeDamage (ref Player, i32) -> (i32)
  locals: 2:i32 new_hp
.set_new:
  local.get 0
  class.get Player.health
  local.get 1
  i32.sub
  local.set 2
.store:
  local.get 0
  local.get 2
  class.set Player.health
.chk:
  local.get 2
  i32.const 0
  i32.le_s
  br_if .log_dead
.ret_alive:
  i32.const 0
  return
.log_dead:
  string.const 0          ; "Player died"
  call host.Log
  i32.const 1
  return

func game.demo.SumTo (i32) -> (i32)
  locals: 1:i32 acc, 2:i32 loop.i, 3:i32 loop.last, 4:i32 loop.index
  local.get 0
  local.set 3             ; loop.last = n   (loop.first = 1 folded into the next line)
  i32.const 1
  local.set 2             ; loop.i = first
.test:
  local.get 2
  local.get 3
  i32.le_s
  br_if .body
  local.get 1             ; ret: total = acc
  return
.body:
  local.get 2
  local.set 4             ; Emit each: index = i
  local.get 1
  local.get 4
  i32.add
  local.set 1             ; add: acc = acc + index
  local.get 2
  i32.const 1
  i32.add
  local.set 2             ; bump
  br .test
```

Example encodings: `local.get 1` is `12 01`, `i32.const 1` is `20 01`, `i32.le_s` is `37`, `i32.add` is `3B`.

## 6. Runtime and embedding API (C)

### 6.1 Design

The API follows the Lua C API's central ideas and fixes the parts that do not suit a statically typed, verified language.

| Lua idea | Wiret version |
| --- | --- |
| No global state; everything hangs off `lua_State` | `wr_Vm` owns the heap, modules and scheduler. A `wr_Fiber` owns one value stack and its frames. Nothing is global, so any number of VMs can coexist. |
| A virtual stack is the only data channel | Same: 1-based indices from the bottom, negative from the top. Slots are **typed**, and `wr_type` tells you what is in one. |
| `lua_call` may longjmp; `lua_pcall` does not | Every call is protected. The VM never unwinds through host frames, and natives report errors by returning `wr_fault(...)`. |
| `luaL_ref` registry | `wr_ref` / `wr_pushref` / `wr_unref` keep a value alive from host code. |
| `lua_Alloc` | `wr_AllocFn` is the only way the VM obtains memory. |
| Coroutines (`lua_resume`) | Fibers. Latent nodes suspend them. The host drives time with `wr_advance`. |
| Userdata | Host handles: `(index, generation)` pairs that become invalid when the host says the object is gone. |

**Conventions.** Functions that can fail return `wr_Status`. A value pushed on the stack is owned by the fiber and may be collected once it is removed. Pointers returned by `wr_to_string` and `wr_to_host` are valid only while the value stays on the stack. A `wr_Vm` and all of its fibers belong to one thread at a time; to use several threads, create one VM per thread. The header is plain C99 and exports only `wr_`-prefixed names.

### 6.2 Status codes

| Status | Meaning |
| --- | --- |
| `WR_OK` | Finished. Results are on the stack. |
| `WR_YIELD` | The fiber suspended (`Delay`, `Yield`, `Await`). It is owned by the scheduler now. |
| `WR_ERR_FAULT` | An uncaught fault. See `wr_fault_info`. |
| `WR_ERR_FUEL` | The fuel budget ran out. Not catchable in Wiret. |
| `WR_ERR_MEM` | The heap limit was hit or the allocator failed. Not catchable. |
| `WR_ERR_LOAD` | The `.wbc` is malformed. |
| `WR_ERR_VERIFY` | The module failed verification (section 5.5). |
| `WR_ERR_LINK` | An import, export or name could not be resolved, or its signature differs. |
| `WR_ERR_API` | The host misused the API: wrong stack type, bad index, yielding across a native. |
| WR\_ERR\_INTERRUPT | Stopped by wr\_interrupt, for example by a wall-clock watchdog. Not catchable. |

### 6.3 The header

```c
/* wiret.h (draft) */
#include <stddef.h>
#include <stdint.h>

#define WR_BYTECODE_VERSION 1
#define WR_MULTRET (-1)

typedef struct wr_Vm     wr_Vm;
typedef struct wr_Fiber  wr_Fiber;
typedef struct wr_Module wr_Module;

typedef enum { WR_OK = 0, WR_YIELD, WR_ERR_FAULT, WR_ERR_FUEL, WR_ERR_MEM,
               WR_ERR_LOAD, WR_ERR_VERIFY, WR_ERR_LINK, WR_ERR_API, WR_ERR_INTERRUPT } wr_Status;

typedef enum { WR_T_NULL, WR_T_BOOL, WR_T_I32, WR_T_I64, WR_T_F32, WR_T_F64,
               WR_T_STRING, WR_T_STRUCT, WR_T_CLASS, WR_T_ARRAY, WR_T_MAP, WR_T_SET,
               WR_T_DELEGATE, WR_T_DISPATCHER, WR_T_HOST, WR_T_SIGNAL,
               WR_T_FAULT } wr_Type;

typedef void *(*wr_AllocFn)(void *ud, void *ptr, size_t old_size, size_t new_size);
typedef int   (*wr_NativeFn)(wr_Fiber *f, void *ud);

typedef struct wr_Error { wr_Status status; int code; char message[256]; } wr_Error;

#define WR_CFG_DETERMINISTIC 1   /* refuse natives that are not marked deterministic */

typedef struct wr_Config {
  size_t   struct_size;                  /* set by wr_config_init; lets the struct grow */
  unsigned flags;                        /* WR_CFG_DETERMINISTIC */
  wr_AllocFn alloc;  void *alloc_ud;     /* NULL: malloc family            */
  size_t   max_heap_bytes;               /* 0: unlimited                   */
  uint32_t max_stack_slots;              /* per fiber, default 1<<20       */
  uint32_t max_call_depth;               /* default 4096                   */
  uint32_t max_cont_depth;               /* per frame, default 1024        */
  int64_t  default_fuel;                 /* per wr_call / per wake, <0: unlimited */
  void (*on_fault)(wr_Vm *, wr_Fiber *, void *ud);  /* detached fiber faulted */
  void (*on_log)(wr_Vm *, int level, const char *msg, void *ud);
  void *ud;
} wr_Config;
```

### 6.4 VM lifecycle

```c
void       wr_config_init(wr_Config *cfg);          /* fill defaults */
wr_Vm     *wr_vm_new(const wr_Config *cfg);         /* NULL on allocation failure */
void       wr_vm_free(wr_Vm *vm);                   /* frees fibers, modules, heap */
void      *wr_vm_userdata(wr_Vm *vm);
double     wr_vm_time(wr_Vm *vm);                   /* virtual seconds */

wr_Fiber  *wr_fiber_new(wr_Vm *vm);
void       wr_fiber_free(wr_Fiber *f);              /* not while RUNNING */
typedef enum { WR_FIBER_READY, WR_FIBER_RUNNING, WR_FIBER_SUSPENDED,
               WR_FIBER_DONE, WR_FIBER_FAULTED } wr_FiberStatus;
wr_FiberStatus wr_fiber_status(wr_Fiber *f);
void       wr_fiber_kill(wr_Fiber *f);              /* ends it without running handlers */
```

**ABI stability.** Structs that cross the API (`wr_Config`, `wr_HostType`, `wr_FaultInfo`, `wr_Stats`) begin with `size_t struct_size`, filled in by the matching `*_init` function or by the caller. The VM reads only as many bytes as the caller declared and treats missing trailing fields as zero, so a host built against an older header keeps working against a newer library. In a VM created with `WR_CFG_DETERMINISTIC`, wall-clock budgets (`wr_interrupt`) still work, but registering a native that is neither `WR_NATIVE_DETERMINISTIC` nor `WR_NATIVE_PURE` fails with `WR_ERR_LINK`, so a replay cannot silently depend on a clock or a random source.

### 6.5 Modules

```c
#define WR_LOAD_BORROW    2   /* keep a pointer to the caller's bytes instead of copying; one image can be loaded into several VMs */
#define WR_LOAD_LAZY_LINK 1   /* unresolved imports fault when called, not at load */

wr_Status wr_module_load(wr_Vm *vm, const void *bytes, size_t len, const char *name,
                         unsigned flags, wr_Module **out, wr_Error *err);
wr_Status wr_module_load_file(wr_Vm *vm, const char *path, unsigned flags,
                              wr_Module **out, wr_Error *err);
void      wr_module_release(wr_Vm *vm, wr_Module *m);
const char *wr_module_hash(wr_Module *m, int which);   /* 0 semantic, 1 layout; hex */

typedef struct wr_ExportInfo {
  const char *name;        /* "SumTo", "Player.TakeDamage" */
  const char *signature;   /* "(i32)->(i32)" */
  unsigned    flags;       /* WR_EXPORT_EVENT | _LATENT | _PURE */
} wr_ExportInfo;
void wr_module_each_export(wr_Module *m, void (*fn)(const wr_ExportInfo *, void *), void *ud);
```

Loading decodes, **verifies**, then links. Link resolves each import against natives registered with `wr_register` and compares signatures; any mismatch is `WR_ERR_LINK`, with the offending name in `err->message`. A module cannot reach any capability the host did not register. Loading the same bytes twice gives two independent instances with separate globals.

**Capabilities and linking.** An import can carry `@capability("console.write")` in source. The compiler lists every required capability in the `wr.caps` section, so a host can inspect a module before it runs anything. Nothing is granted by default.

```c
wr_Status wr_grant(wr_Vm *vm, const char *capability);
void      wr_module_each_capability(wr_Module *m, void (*fn)(const char *cap, void *), void *ud);
wr_Status wr_link(wr_Vm *vm);     /* resolve imports left pending by WR_LOAD_LAZY_LINK */
```

An import whose capability is not granted fails the load with `WR_ERR_LINK`, naming the capability. Imports between Wiret modules are resolved against the exports of modules already loaded, then against natives (section 7.3). To load modules that depend on each other in any order, pass `WR_LOAD_LAZY_LINK` to each and call `wr_link` once.

### 6.6 Natives and host types

```c
#define WR_NATIVE_DETERMINISTIC 2   /* result depends only on arguments and VM state */
#define WR_NATIVE_PURE 1   /* no side effects; callable from @pure graphs */

/* name: "host.Log"; sig uses Wiret type syntax: "(string)->()", "(i32,f32)->(bool)" */
wr_Status wr_register(wr_Vm *vm, const char *name, const char *sig,
                      wr_NativeFn fn, void *ud, unsigned flags);

/* A native receives its arguments at stack indices 1..n, already checked against
   the registered signature. It pushes its results and returns how many it pushed,
   or returns wr_fault(...). */
int wr_fault(wr_Fiber *f, const char *fmt, ...);   /* returns -1 */

typedef struct wr_HostType {
  size_t      struct_size;                            /* sizeof(wr_HostType), set by the caller */
  const char *name;                                   /* "engine.Actor" */
  void (*finalize)(wr_Vm *, void *ptr, void *ud);     /* called when the last handle is collected */
  void *ud;
} wr_HostType;
wr_Status wr_register_type(wr_Vm *vm, const wr_HostType *t);
void      wr_push_host(wr_Fiber *f, const char *type, void *ptr);  /* same ptr, same identity */
void     *wr_to_host(wr_Fiber *f, int idx, const char *type);      /* NULL if wrong type or invalidated */
void      wr_host_invalidate(wr_Vm *vm, void *ptr);   /* the host destroyed it: IsValid becomes false */
```

Natives cannot suspend in version 1. Host-side asynchronous work is modelled by returning a `std.Signal` (created with `wr_push_signal`) and firing it later; the graph uses `Await`. A native may call back into Wiret with `wr_call`, but the nested call cannot suspend (it would report `WR_ERR_API`).

### 6.7 The stack

```c
int  wr_gettop(wr_Fiber *f);              void wr_settop(wr_Fiber *f, int idx);
void wr_pop(wr_Fiber *f, int n);          void wr_pushvalue(wr_Fiber *f, int idx);
void wr_remove(wr_Fiber *f, int idx);     void wr_insert(wr_Fiber *f, int idx);
void wr_replace(wr_Fiber *f, int idx);
int  wr_checkstack(wr_Fiber *f, int extra);          /* 0 if it cannot grow */

wr_Type     wr_type(wr_Fiber *f, int idx);
const char *wr_typename(wr_Fiber *f, int idx);       /* "i32", "game.demo.Player", "array<i32>" */

void wr_push_bool(wr_Fiber *f, int b);    void wr_push_i32(wr_Fiber *f, int32_t v);
void wr_push_i64(wr_Fiber *f, int64_t v); void wr_push_f32(wr_Fiber *f, float v);
void wr_push_f64(wr_Fiber *f, double v);
void wr_push_string(wr_Fiber *f, const char *s, size_t len);   /* copies */
void wr_push_null(wr_Fiber *f, const char *type);              /* typed null reference */
void wr_push_signal(wr_Fiber *f);

int         wr_to_bool(wr_Fiber *f, int idx);       int32_t wr_to_i32(wr_Fiber *f, int idx);
int64_t     wr_to_i64(wr_Fiber *f, int idx);        float   wr_to_f32(wr_Fiber *f, int idx);
double      wr_to_f64(wr_Fiber *f, int idx);
const char *wr_to_string(wr_Fiber *f, int idx, size_t *len);   /* valid while on the stack */
```

The `wr_to_*` functions return 0 or NULL when the slot has another type; use `wr_type` to branch. Narrow integer parameters (`u8`, `i16`, ...) are pushed and read as `i32`.

**Objects and containers.** All look-ups are by name and return `wr_Status`.

```c
wr_Status wr_push_new(wr_Fiber *f, wr_Module *m, const char *type);  /* class, struct or "array<i32>" ... */
wr_Status wr_getfield(wr_Fiber *f, int idx, const char *field);      /* pushes the field */
wr_Status wr_setfield(wr_Fiber *f, int idx, const char *field);      /* pops a value; a struct slot is replaced by the updated copy */

int       wr_array_len(wr_Fiber *f, int idx);
wr_Status wr_array_get(wr_Fiber *f, int idx, int i);                 /* pushes element */
wr_Status wr_array_set(wr_Fiber *f, int idx, int i);                 /* pops value */
wr_Status wr_array_push(wr_Fiber *f, int idx);                       /* pops value */
int       wr_map_len(wr_Fiber *f, int idx);
wr_Status wr_map_get(wr_Fiber *f, int idx);    /* key on top is replaced by the value; pushes found flag */
wr_Status wr_map_set(wr_Fiber *f, int idx);    /* pops value, then key */
wr_Status wr_map_key_at(wr_Fiber *f, int idx, int i);                /* insertion order */

int  wr_ref(wr_Fiber *f);                      /* pops the top value; returns a ref (> 0) */
void wr_pushref(wr_Fiber *f, int ref);
void wr_unref(wr_Vm *vm, int ref);
```

Containers on the stack follow the value rules of section 4.9. `wr_pushvalue` duplicates a slot and marks a container shared, and so do `wr_ref` and `wr_pushref`. The mutators above (`wr_array_set`, `wr_array_push`, `wr_map_set`) operate on the slot at `idx`; when the container is shared they replace that slot with an updated copy, exactly as `wr_setfield` does for a struct. A copy kept earlier, on the stack or in the registry, never sees the change.

### 6.8 Calling Wiret and running fibers

```c
wr_Status wr_push_func(wr_Fiber *f, wr_Module *m, const char *name);     /* "SumTo", "Player.OnTick" */
wr_Status wr_push_virtual(wr_Fiber *f, int obj_idx, const char *method); /* resolves the override */

wr_Status wr_call(wr_Fiber *f, int nargs, int nresults);   /* run now, on the caller's thread */
wr_Status wr_start(wr_Fiber *f, int nargs);                /* queue; runs during wr_advance */
wr_Status wr_advance(wr_Vm *vm, double dt);                /* advance virtual time, run what is ready */
void      wr_signal_fire(wr_Vm *vm, int signal_ref);       /* wake fibers awaiting it */
```

Calling protocol, as in Lua: push the function, push the arguments left to right, call. `wr_call` pops the function and arguments. On `WR_OK` it pushes `nresults` results (or all of them for `WR_MULTRET`). On `WR_YIELD` the fiber is suspended; when the scheduler later finishes it (`wr_fiber_status` becomes `WR_FIBER_DONE`) the results are on that fiber's stack. A fiber runs one call at a time; reuse it after it is `DONE` by clearing its stack with `wr_settop(f, 0)`.

`wr_advance` is deterministic. It adds `dt` to the virtual clock, wakes timers whose time has come (ordered by wake time, then by fiber creation order), and runs each woken or queued fiber until it suspends again or finishes. Each run gets `default_fuel`. A fault in a detached fiber is passed to `on_fault`.

Latency is part of a function's contract (section 4.5). `wr_call` on an export that is **not** flagged `WR_EXPORT_LATENT` returns `WR_OK` or an error and never `WR_YIELD`. Only latent exports and events can suspend, and a host that calls one with `wr_call` must be prepared for `WR_YIELD`.

### 6.9 Faults and tracebacks

```c
typedef struct wr_Frame {
  const char *function;   /* "game.demo.Player.TakeDamage" */
  const char *node;       /* node id from wr.debug, or NULL */
  uint32_t    pc;
} wr_Frame;

typedef struct wr_FaultInfo {
  size_t      struct_size;   /* set by the caller before the call */
  wr_Status   status;     /* WR_ERR_FAULT, WR_ERR_FUEL, ... */
  int32_t     code;       /* from Throw, or a built-in fault code */
  const char *message;    /* valid until the fiber's next call */
  int         nframes;
} wr_FaultInfo;

int wr_fault_info(wr_Fiber *f, wr_FaultInfo *out);        /* 0 if there is none */
int wr_frame_info(wr_Fiber *f, int level, wr_Frame *out); /* level 0 is the faulting frame */
```

Because `wr_Frame` carries the node id, a host can report `Player.TakeDamage, node store: null reference` and an editor can highlight that node.

### 6.10 Resource control and debugging

```c
void    wr_set_fuel(wr_Fiber *f, int64_t units);   int64_t wr_get_fuel(wr_Fiber *f);
size_t  wr_mem_used(wr_Vm *vm);
typedef enum { WR_GC_COLLECT, WR_GC_STEP, WR_GC_STOP, WR_GC_RESTART } wr_GcOp;
size_t  wr_gc(wr_Vm *vm, wr_GcOp op, size_t arg);

#define WR_HOOK_NODE 1   /* a node starts executing */
#define WR_HOOK_CALL 2
#define WR_HOOK_RETURN 4
#define WR_HOOK_FAULT 8
#define WR_HOOK_BREAK 16 /* a breakpoint was hit */
typedef void (*wr_HookFn)(wr_Fiber *f, int event, const wr_Frame *frame, void *ud);
void      wr_set_hook(wr_Vm *vm, wr_HookFn fn, int mask, void *ud);
wr_Status wr_set_breakpoint(wr_Vm *vm, wr_Module *m, const char *function,
                            const char *node_id, int enabled);
```

The collector is a precise tracing GC. It is non-moving in version 1, but the API never exposes object addresses, so a moving or generational collector can be added later. Hooks run inline on the fiber's thread; a debugger front end blocks inside the hook while the user inspects the stack. Breakpoints work by patching a `brk` instruction (opcode `0F`) over the first instruction of the node's block.

```c
void wr_interrupt(wr_Vm *vm);     /* the only thread-safe call */

typedef struct wr_Stats {
  size_t   struct_size;   /* set by the caller before the call */
  size_t   heap_bytes;  size_t   live_objects;
  uint64_t fuel_used;   uint32_t fibers;  uint32_t modules;
} wr_Stats;
void wr_get_stats(const wr_Vm *vm, wr_Stats *out);
```

Fuel is deterministic but does not bound wall-clock time. `wr_interrupt` may be called from any thread, for example by a watchdog; running fibers stop at the next call or backward branch with `WR_ERR_INTERRUPT`. It is the single exception to the rule that a VM belongs to one thread at a time.

```c
/* Push the last value of a node's output pin in stack frame `level` (0 = top frame).
   Works on suspended or faulted fibers and from hooks. Returns WR_ERR_API if the pin's
   value was not kept (see wr.pins and -Og). */
wr_Status wr_getpin(wr_Fiber *f, int level, const char *node, const char *pin);
```

With `-Og` builds, an editor can show the live value on every wire of a paused graph, and a host can log the inputs of a failing node. The node name is path-style inside macros (`loop/test`).

### 6.11 Example host

```c
#include <stdio.h>
#include <wiret.h>

static int host_log(wr_Fiber *f, void *ud) {
  size_t n; const char *s = wr_to_string(f, 1, &n);
  fwrite(s, 1, n, stdout); fputc('\n', stdout);
  return 0;                                   /* pushed no results */
}

int main(void) {
  wr_Config cfg; wr_config_init(&cfg);
  cfg.default_fuel = 1000000;                 /* sandbox: bounded work per call */
  wr_Vm *vm = wr_vm_new(&cfg);
  wr_register(vm, "host.Log", "(string)->()", host_log, NULL, 0);

  wr_Module *mod; wr_Error err;
  if (wr_module_load_file(vm, "demo.wbc", 0, &mod, &err) != WR_OK) {
    fprintf(stderr, "load failed: %s\n", err.message);
    return 1;
  }

  wr_Fiber *f = wr_fiber_new(vm);

  /* int total = SumTo(10); */
  wr_push_func(f, mod, "SumTo");
  wr_push_i32(f, 10);
  if (wr_call(f, 1, 1) == WR_OK)
    printf("SumTo(10) = %d\n", wr_to_i32(f, -1));      /* 55 */
  wr_settop(f, 0);

  /* Player p = new Player(); bool died = p.TakeDamage(150); */
  wr_push_new(f, mod, "Player");                         /* index 1 */
  wr_push_virtual(f, 1, "TakeDamage");                   /* index 2: the function */
  wr_pushvalue(f, 1);                                    /* self */
  wr_push_i32(f, 150);                                   /* amount */
  if (wr_call(f, 2, 1) == WR_OK)                         /* logs "Player died" */
    printf("died = %d\n", wr_to_bool(f, -1));            /* 1 */
  else {
    wr_FaultInfo fi; wr_fault_info(f, &fi);
    fprintf(stderr, "fault: %s\n", fi.message);
  }

  wr_fiber_free(f);
  wr_module_release(vm, mod);
  wr_vm_free(vm);
  return 0;
}
```

A typical game loop adds one call per frame: `wr_advance(vm, dt)`. Events are started with `wr_start`, or with `wr_call` when the caller wants the first segment to run synchronously.

## 7. Toolchain

| Command | Purpose |
| --- | --- |
| `wiretc check file.wiret` | Parse, resolve, type-check and validate; print diagnostics (section 4.7). |
| `wiretc fmt file.wiret` | Rewrite in canonical form. `--check` fails if the file is not canonical (for CI). |
| `wiretc build file.wiret -o out.wbc` | Compile and verify. `-O0` / `-O1`, `--embed-source`, `--no-debug`. |
| `wiretc dis out.wbc` | Disassemble, with node ids from `wr.debug`. |
| `wiretc view --flow file.wiret` | Print a reading view in flow order (not canonical). `--dot` exports Graphviz DOT, using `node:pin` ports and one cluster per layout box. |
| `wiretc hash file.wiret` | Print the semantic and layout hashes. |
| `wiretc diff a.wiret b.wiret` | Node-level diff: added, removed and rewired nodes; layout-only changes reported separately. |
| `wiretc merge base ours theirs` | Git merge driver. Line-merges, then re-validates (duplicate bindings, dangling ids). |
| `wiretc verify out.wbc` | Run only the verifier. |
| wiretc check --json file.wiret | Structured diagnostics, one JSON record per line (section 4.7). |
| wiretc run file.wiret Func args... | Compile and run an export on the reference VM with the standard natives, for tests and quick experiments. |
| wiretc svg file.wiret Func | Render a graph to SVG from the layout block, so a pull request can show the diagram next to the text diff. |

Suggested Git setup:

```
# .gitattributes
*.wiret merge=wiret diff=wiret
```

### 7.1 Merge procedure

`wiretc merge` implements the following, and an editor's built-in merge should behave the same way.

1. **Parse** base, ours and theirs into models. If any side does not parse, fall back to a plain text merge and say so.
2. **Match by key.** Declarations are keyed by `@id`, otherwise by name; nodes by node id within their graph; parameters, fields and enum members by `@id`.
3. **Merge each key.** Added on one side only: keep. Deleted on one side and unchanged on the other: delete. Deleted on one side and modified on the other: **conflict**. Modified on both sides: merge *per field*, where each input binding, each exec output, each type argument and each attribute is one field. A field changed on only one side takes that change, the same change on both sides is no change, and different changes to the same field are a conflict.
4. **Merge layout separately.** `place` and `box` lines are keyed by node id and title, and their properties merge independently. A layout disagreement never blocks a merge: the later commit wins and a notice is printed.
5. **Validate** the merged model: duplicate ids, an input bound twice, exec targets or pin references that name a node that no longer exists, and every other diagnostic in section 4.7. Violations are reported as **semantic conflicts** keyed by node and pin, so an editor can show them on the graph.
6. **Write** canonical text. Unresolved conflicts are written as conflict markers around the single node line concerned, one line for each side, and the command exits non-zero, so ordinary tools show them too. The merge never silently drops a node, a wire or an unknown attribute.

### 7.2 Editing protocol for tools and LLMs

A program that edits a graph (an editor, a refactoring tool, an LLM agent) should not rewrite whole files. `wiretc edit` accepts a list of operations as JSON and applies them to the parsed model:

| Operation | Effect |
| --- | --- |
| `create_node` | Add a node with a kind, type arguments, bindings and exec wiring. The id may be supplied. |
| `bind` / `unbind` | Connect or disconnect a data input. |
| `wire_exec` / `unwire_exec` | Connect or disconnect an exec output. |
| `set_attr` / `remove_attr` | Change an attribute on a node or declaration. |
| `place` | Change a node's entry in the layout block (position, label, colour), and only that. |
| `delete_node` | Remove a node. Refused while other nodes still reference it, unless `cascade` is set, in which case the removed wires are listed in the reply. |
| `rename` | Rename a declaration, parameter, field or local by its `@id` and rewrite every reference. |

Every request carries `if_hash`, the layout hash of the document the caller last read. If the document has changed since, the request is rejected with `E0900` and the caller must re-read. On success the reply contains the new hash, all diagnostics, and the resulting text diff. A rejected or invalid request changes nothing. Together with the registry (section 3.5), this lets an LLM make precise, checked edits without guessing pin names and without ever producing a file that fails to parse.

**Prompt contract for LLM agents.** Give the agent three things: the registry entries it may use (section 3.5) and the declarations it may call, the target graph in canonical text, and the task. It answers with edit operations or a complete function body, with no layout block and no commentary. The harness runs `wiretc check --json`, feeds any diagnostics back, and repeats for a bounded number of rounds. A result that still has errors is never saved. An agent must not invent pin names or node kinds; unknown names are `E0103` and `E0501`, and the loop reports them back to the agent.

### 7.3 Projects, modules and linking

A project is a directory with a `wiret.toml` manifest and a generated `wiret.lock`.

```
[project]
name     = "mygame"
wiret    = "1"
registry = "wiret.core@1.0"
roots    = ["src"]

[dependencies]
physics = { path = "../physics" }

[capabilities]
allow = ["console.write"]
```

- A module name maps to a path under a root: `game.player` is `src/game/player.wiret`. `use game.player` makes its exports visible, and `Call game.player.Heal` calls one.
- A call to another Wiret module compiles to an import whose `module` field is the callee's module name. The loader resolves an import against the exports of loaded Wiret modules first (checking the signature), then against registered natives.
- Import cycles between modules are rejected at build time.
- `wiret.lock` records the semantic hash of every dependency and the registry version. `wiretc build` fails if a dependency's hash no longer matches, so a build is reproducible.
- `[capabilities] allow` lists what the build permits modules to request. It is a build-time check; the host's `wr_grant` calls are the runtime authority.

### 7.4 Conformance

An implementation claims one or more levels:

| Level | Requirements |
| --- | --- |
| Reader | Parses `.wiret`, preserves unknown attributes, and round-trips canonical files byte for byte. |
| Editor | Reader, plus writes canonical form, preserves ids, and computes both hashes. |
| Compiler | Editor, plus produces exactly the diagnostics of section 4.7 and emits verifiable `.wbc` with the lowering of section 4.8. |
| Runtime | Verifies before running, enforces limits, implements the instruction semantics of section 5 including value semantics (4.9), and the C API of section 6. |

A shared test suite should cover at least: formatter idempotence (`fmt(fmt(x)) == fmt(x)`); one failing graph for each diagnostic code; golden bytecode for `TakeDamage` and `SumTo`; verifier negative tests and a fuzzer for malformed `.wbc`; arithmetic edge cases (division by zero, `INT_MIN / -1`, saturating truncation, shift masking); a container alias test (copy an array, change the copy, check the original, and check that appending in a loop does not copy on each iteration); determinism (identical fuel counts and results on every platform); C API lifetime tests; and semantic-hash stability under layout-only edits.

Add two metamorphic tests to the suite: reversing the node order of a graph, and deleting its layout block, must change neither the semantic hash nor a byte of the compiled instruction stream. Add a negative test that a non-latent function containing `suspend` fails verification, and a test that a layout-only edit never changes the semantic hash.

### 7.5 Contract for graph editors

An editor that reads and writes `.wiret` files must:

1. **Preserve ids.** Never regenerate node, parameter or declaration ids on load or save.
2. **Write canonical form** with the shared formatter, so opening and saving an unchanged graph produces a byte-identical file and an empty diff.
3. **Lay out only what has no layout.** Auto-place nodes that lack a `place` line and leave every other position alone.
4. **Preserve unknown data**: unknown attributes, unknown layout properties and unknown custom sections.
5. **Insert conversions explicitly.** When a connection needs a conversion, add a real `Convert` node; never change a wire's type silently.
6. **Never delete wires silently.** If a pin changes type or disappears, keep the wire visible as an error and let the user decide.
7. **Show diagnostics on the graph**, using the `node` and `pin` of each record from `wiretc check --json`.
8. **Keep personal view state out of the file.** Zoom, scroll, selection, open tabs and panel layout go in a separate workspace file (for example `.wiret-workspace`) that is excluded from Git.
9. **Use the debug data** when attached to a runtime: node-level breakpoints from `wr.debug`, and wire values from `wr_getpin`.

### 7.6 Reference implementation

This specification should be built alongside a small reference implementation, not after it. The suggested scope is a parser, canonical printer, checker, compiler to WBC, verifier, disassembler and interpreter, written for clarity rather than speed, together with the corpus described in 7.4. Each section of this document should carry a status (specified, implemented, or tested) and the status should be updated as the reference grows. An independently developed design, compared in Appendix B, already has such a reference (about 2,500 lines of Python, with a fuzz test that rejects thousands of corrupted modules); its test corpus and CLI conventions are good starting points to port.

## 8. Versioning and compatibility

- The text header `wiret N` and the bytecode `version` are independent integers. A reader must reject a file with a higher major number than it supports.
- Within a major version, changes are additive: new node kinds, new semantic attributes, new custom sections, new instructions under the `FB` prefix. Old tools keep unknown attributes and skip unknown custom sections, so a new editor's file survives a round trip through an old one.
- A new node kind can only be compiled by a compiler that knows it. Older compilers report `E0501` rather than guessing.
- The semantic hash is stable across editor-only changes. Changing the canonical-form rules in section 2.5 is a major-version change.

## 9. Open questions and next steps

### 9.1 Decisions I would revisit once there is a prototype

1. **Pure-node re-evaluation.** It matches Blueprints and is easy to compile, but it is a known source of surprises (a random-number node feeding two consumers gives two values). Alternatives are caching per event, or an explicit `Latch` node. The compiler could also warn when an impure-reading pure node feeds more than one impure consumer.
2. **Canonical order by node id.** It gives the best merges but a flow-hostile file. If reviewers find it hard to read, an optional `@order(n)` hint (derived from flow order and ignored by the semantic hash) could be added at the cost of noisier diffs.
3. **Nesting rule for `Try`.** `E0412` is conservative. It may reject graphs that users find natural. A region-aware lowering could allow more.
4. **Immutable structs.** `WithField` allocates. Escape analysis in the optimiser should remove most of that, but it should be measured.
5. **Generics by monomorphisation.** Simple and fast, but code size grows with instantiations. Shared generic code with a type descriptor argument is the alternative.
6. **Cooperative-only natives.** Natives cannot suspend. Real engines often want a latent native (async I/O). The `Signal` pattern covers it, but with more ceremony.

Three further questions are open.

- **Stack versus register bytecode.** A register machine gives every pin its own register, which makes value probes trivial and avoids stack bookkeeping. The stack form is denser and easier to emit, and `wr.pins` with `-Og` recovers most of the debugging benefit. A benchmark of both on a real corpus should decide; the graph-to-block lowering would not change.
- **Explicit latency.** Declaring `@latent` gives hosts a hard guarantee but spreads through call chains like `async`. Revisit it if users find it burdensome.
- **Continuations at run time or compile time.** Section 4.2 keeps pending exec continuations on a runtime stack. The alternative, duplicating shared nodes at compile time, needs no such stack but can multiply code and needs a nesting limit.

### 9.2 Not covered in this draft

- Exact pin lists and bodies for every `std.*` function and `std.flow` macro, and string `Format` syntax.
- Interface method call nodes beyond `Call`, enum `Switch` ergonomics, and `Format Text`-style nodes.
- Blueprint features that are really engine features: timelines, construction scripts, components, replication, soft references and data tables. These would be host-provided natives and extern types, or a layer on top of Wiret.
- Hot reload and state migration (the `@id` attributes are there to make this possible), serialisation of suspended fibers for save games, multi-threaded VMs, a wire protocol for remote debugging, and a WebAssembly backend or JIT.

### 9.3 Suggested build order

1. Parser, printer and formatter with round-trip tests. Use section 2.6 as the first golden file and add a test that `fmt(fmt(x)) == fmt(x)`.
2. Resolver, type checker and graph validator, driven by the diagnostics table.
3. Lowering, the verifier and the disassembler. Section 5.8 gives expected output for `TakeDamage` and `SumTo`.
4. A bytecode interpreter with fuel counting, then the C API and the host example in 6.11.
5. The standard library and `std.flow` macros, written in Wiret wherever possible so they double as tests.
6. Debug data, hooks and breakpoints, then the editor integration.

## Appendix A. Changes in Draft 0.2

Three independent proposals were reviewed against Draft 0.1. This table records what changed and why.

| Change | Section | Source |
| --- | --- | --- |
| `array`, `set`, `map` become value types with copy-on-write; mutators return the container; `ref.share`; place-based mutation nodes; structural equality | 3.1, 3.3, 4.9, 5.6, 6.7 | Decision by the project owner: Blueprints copy arrays by value. Replaces 0.1's aliasing arrays. |
| Machine-readable node registry | 3.5 | Proposal 1 (operation registry), without its per-node pin lists. |
| Merge procedure and editing protocol with a document-hash precondition | 7.1, 7.2 | Proposal 1 (merge and AI editing sections). |
| Cross-module linking, project manifest and lockfile | 7.3 | A gap in 0.1; manifest and lock idea from Proposal 1. |
| `@id` on parameters, results, fields, enum members and locals | 2.4 | Review of rename handling. |
| Capabilities, `wr.caps`, required-feature bits in the header | 2.4, 5.2, 5.4, 6.5 | Proposal 1. |
| `wr_interrupt`, `wr_get_stats`, `.wdbg` sidecar | 5.4, 6.10 | Proposal 1. |
| Conformance levels and shared test suite | 7.4 | Proposal 1. |

**Considered and not adopted.** Pins re-declared on every node and ids on every edge (Proposals 1 and 3): they lengthen every line, create a second source of truth next to the registry, and make sequentially numbered ids collide across Git branches. Creation-order canonical layout (Proposals 1 and 3): every addition lands at the end of the file, so concurrent additions conflict. Register-based bytecode (Proposals 1 and 3): the stack form with typed locals is denser and verifies in one pass. Optional async (Proposals 1 and 3): latent nodes are core to the target. Handle-based host API with retain and release (Proposals 1 and 3): the Lua-style stack avoids a second lifetime system next to the garbage collector. Expressions inside bindings and exec pins on arithmetic nodes (Proposal 2): they break the one-node-per-operation, pure-versus-impure model.

## Appendix B. Changes in Draft 0.3

Draft 0.3 takes the strongest parts of an independently developed design that comes with a working Python reference implementation (parser, formatter, checker, compiler, verifier, VM and a fuzz test). The table lists what was adopted and why.

| Change | Section | Reason |
| --- | --- | --- |
| Layout moves into a per-graph `layout` block (`place` and `box` lines); node lines carry no positions; auto-placement; personal view state kept out of the file | 2.3, 2.4, 2.5, 7.5 | Fixes a real flaw in 0.2, where `@ed` shared a line with a node's wiring so a move and a rewire of the same node conflicted. |
| `state` slots for macros and graphs; path-style node ids after expansion; synthetic exec-pin stub ids | 2.3, 4.4, 4.8, 5.4 | `DoOnce` and `FlipFlop` had no mechanism in 0.2. Path ids give debug data and diagnostics an address inside macros. |
| Declared and checked latency: `@latent`, `E0201`, function-section flags, a verifier rule | 2.4, 4.4, 4.5, 5.2, 5.5, 6.8 | A non-latent export can no longer suspend, so a host can rely on `wr_call`. This also mirrors Blueprint's restriction on latent nodes. |
| Pin-level debug data (`wr.pins`), `-Og`, and `wr_getpin` | 4.8, 5.4, 6.10 | Lets an editor show values on wires and a host log the inputs of a failing node. |
| Host ABI hardening: `struct_size`, deterministic mode and native flag, `WR_LOAD_BORROW` | 6.3, 6.4, 6.5, 6.6 | Structs can grow without breaking old hosts; replay cannot depend on a hidden clock; one image can serve several VMs. |
| Keyed, node-level merge with per-field rules and conflict markers | 7.1 | Merges on the model rather than on text lines. |
| Structured diagnostics (`check --json`), `E0303`, an editor contract and an LLM prompt contract; `run` and `svg` commands | 4.7, 7.2, 7.5 | Closed loops for editors and agents. |
| Reference-implementation path, section status, metamorphic hash tests | 7.4, 7.6 | The compared design found bugs by running its spec; this one has not yet. |

**Considered and not adopted.** Sigils (`%node`, `@symbol`, `$local`) and multi-line node blocks: they make each node several lines (a 10-node function became about 50 lines), and bare identifiers are already unambiguous by position. Reference-type containers: they contradict the project's decision that arrays copy by value (section 4.9). Compile-time duplication of nodes for `Sequence` with a nesting limit: kept the runtime continuation stack, recorded as an open question (9.1). Raising errors from natives with a longjmp-style API: natives return `wr_fault` instead, which is safe with C++ and with natives that hold resources. An `any` boxing type: typed wildcards and explicit `Convert` nodes are kept. Preserving node order and inserting after the origin node: two people inserting after the same node collide in a line merge, so canonical order stays sorted by id. Dropping catchable faults: kept `Try`, but marked it Provisional (4.6).
