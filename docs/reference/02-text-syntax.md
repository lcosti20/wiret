## 2. Text syntax

### 2.1 Files and lexical structure

A `.wiret` file is UTF-8 (no BOM) with LF line endings and holds exactly one module. Statements end at a newline. Newlines are ignored inside `( )` and inside exec maps `{ pin -> target, ... }`, so long nodes can wrap.

`//` starts a line comment. Line comments are *trivia* and are not part of the model, so the canonical writer cannot keep them. It never drops one silently: `wiretc fmt` reports `W0603` for each comment it would lose and exits non-zero, unless told what to do with them: `--convert-comments` turns each comment into a `note` attached to the next node or declaration (section 2.3), and `--drop-comments` discards them. An editor that opens a file containing comments offers the same choice. Anything that must survive a round trip is written as a `note` (graph, node or box explanations), a `@doc` attribute (the short tooltip text of a declaration), or a `box` (visual grouping).

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

A literal takes the type of the pin it is bound to, so suffixes are only needed where a literal is used without a pin (attribute arguments). Keywords are reserved: `wiret module use extern const var local enum struct interface class impl macro func event dispatcher node state notes note on layout box at size`.

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

The body of a `func`, `event` or `macro` is a list of `local` and `state` declarations and `node` statements, followed by at most one `notes` block and at most one `layout` block. Everything that decides behaviour is in the node statements. Explanations for humans are in the notes block. Everything about where things are drawn is in the layout block.

```
body    = { local | state | node } [ notes ] [ layout ] ;
local   = "local" IDENT ":" type [ "=" literal ] NL ;
state   = "state" IDENT ":" type [ "=" literal ] NL ;
node    = "node" IDENT "=" KIND [ symbol ] [ "<" types ">" ]
          [ "(" [ binding { "," binding } ] ")" ] [ execout ] attrs NL ;
binding = IDENT ":" ( pinref | literal ) ;
pinref  = IDENT "." IDENT ;
execout = "->" target | "{" IDENT "->" target { "," IDENT "->" target } "}" ;
target  = IDENT [ "." IDENT ] ;
notes   = "notes" "{" { note } "}" NL ;
note    = "note" IDENT [ "on" IDENT ] STRING attrs NL ;   (* no "on": the whole graph *)
layout  = "layout" "{" { place | box } "}" NL ;
place   = IDENT "at" "(" INT "," INT ")" [ props ] NL ;
box     = "box" IDENT STRING "at" "(" INT "," INT ")" "size" "(" INT "," INT ")" props NL ;
props   = "[" IDENT "=" value { "," IDENT "=" value } "]" ;
```

Rules:

1. **Node ids** are identifiers, unique within the graph. They are the identity of a node for diffs and merges. Display names are not ids; they live in the layout (`label`). Editors generate a readable slug plus a short random suffix, such as `branch_k3m9`; humans and LLMs may choose descriptive ones such as `check_energy`. **Non-reuse is a project-level guarantee, not a file-level one.** A single file can only prove that its present ids are unique; it cannot know which ids were deleted earlier. Non-reuse is therefore enforced by the project's id registry `wiret.ids` (section 7.3), which records every retired node id: an editor save or `wiretc edit` that deletes a node appends its id, and a node that reuses a retired id is `E0140`. Without a project (a lone file) editors still generate fresh random suffixes, which makes accidental reuse improbable but not impossible, and `wiretc check` says so (`W0202`).
2. **Kind** is a PascalCase built-in (`Add`, `Branch`, `SetLocal`, ...; section 3.3). Calling a declared function is always `Call`, so the closed set of built-in kinds never collides with user names.
3. **Symbol** (optional) names the thing the node acts on: `Call std.math.Sqrt`, `GetField health`, `SetLocal acc`, `GetState done`, `New Player`, `Cast Player`, `Macro ForRange`, `Exit done`.
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
  box death "Death handling" at (940, -90) size (330, 120) [members = [log_dead, ret_dead], color = "#C0392B"]
}
```

- A `place` line gives a node's position, and optionally `label`, `color`, `size`, `collapsed` and `hidden` (a list of pin names). Coordinates are integers, so there is no floating-point noise in diffs.
- A `box` is a visual group with its own id (unique among node ids and box ids in the graph), a title, a position and a size. **Membership is explicit and authoritative:** `members = [id, ...]` is required and lists node ids and box ids. Position and size only say where the box is drawn; a node lying inside a box's rectangle is not thereby a member, and a member lying outside it is still a member. An editor may offer to add a node dragged into a box to `members`, but the list is what is saved. A box with `collapsed = true` is drawn as one node whose pins are the wires crossing its edge (the compiler still sees the flat graph).
- **Nesting and overlap.** A box may list another box as a member, which nests it; the nesting must be acyclic. A node or box is a member of at most one box. If it appears in several, the box with the smallest id keeps it and `W0602` reports the rest. Rectangles may overlap freely, since they have no effect on membership. A member id that names nothing is `W0601` and is removed on the next editor save.
- A node with no `place` line is auto-placed by the editor, and gets a line when first saved. This makes LLM-generated graphs valid without layout.
- Unknown properties are preserved. The block never affects the semantic hash.
- Personal view state (zoom, scroll, selection, open panels) is never written to the file (section 7.5).

This split is what makes collaboration work: one person moving a node and another rewiring it edit different lines, and they merge without a conflict.

#### The notes block

Explanations that belong to the design rather than to the diagram persist in a `notes` block, one `note` per line, each with its own id:

```
notes {
  note why_local on set_new "Store the new health once: pure nodes are re-evaluated per consumer (section 4.3)."
  note overview "Applies damage and reports death. Called by the combat loop."
  note death_rules on death "Death side effects live here so they can be disabled together."
}
```

- `note <id> on <target> "text"` annotates the node or box named `<target>`. `note <id> "text"` annotates the graph as a whole. Text may contain `\n`; long notes are written as one long line, since line diffs of prose are no worse than for any other node.
- Note ids follow the node-id rules (unique in the graph, readable slug plus suffix). Notes are keyed by id for merging (section 7.1) and sorted by id in canonical form.
- Notes have no effect on compiled output, so they are outside the semantic hash and inside the layout hash. Unknown attributes on a note are preserved.
- A note whose `on` target no longer exists is kept, shown by editors as detached, and reported as `W0604`. A note is never deleted by a tool as a side effect of deleting its target.
- `@doc` remains the short tooltip and reflection text of a declaration or node. Long-form explanation, rationale and region-level comments go in notes.

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
| `@id("...")` | any declaration, module, parameter, result, field, enum member, local | Stable identity that survives rename and move. Editors always write it (`W0202` where it is missing); hand-written and LLM-written code may omit it and gets one on the first editor save or `wiretc fmt --assign-ids`. See the identity rules below. |
| `@pure` | `func` | Effect-free, deterministic and cacheable (section 4.3): the result depends only on the explicit arguments and on `const`s. Callers treat a call as a pure node (no exec pins, evaluated on demand). The graph inside is an ordinary exec graph and may branch, loop and recurse; it may use its own locals, but may not write variables, fields or state (`E0302`), read variables, fields or state, dereference a class reference or host handle, or call anything that is not `@pure` (`E0304`), and may not contain a latent node (`E0302`). |
| `@reads` | `func` | Effect-free and deterministic for a given VM state, but not cacheable: may read variables, fields, state and objects, but not write them. A call is a pure node that is re-evaluated at each consumer (section 4.3), like `GetField`. May call only `@reads` and `@pure` functions (`E0302`) and may not contain a latent node. |
| `@final` | method | Not virtual. Calls are bound at compile time. |
| `@private` | declaration | Not visible outside the module. |
| `@export` | `func`, `event`, `var`, type | Listed in the module's export table for the host and other modules. |
| `@inline` | `func` | Hint to inline at call sites. |
| `@deprecated("msg")` | declaration | Warning at every use. |
| `@count(n)` | `Sequence`, `MakeArray`, ... | Number of dynamic pins. |
| `@cases(v0, v1, ...)` | `Switch` | Case values. Pins are `case0`, `case1`, ... and `default`. |
| `@disabled` | node | Node is skipped: a one-exec-out node passes control straight to its target; data outputs read as zero. |
| @capability("name") | extern func | The import needs this host capability. Listed in the wr.caps section; the load fails unless the host granted it (section 6.5). |
| @latent | func | The function may suspend. Required when it contains a latent node or calls a latent function or event (E0201). Events are implicitly latent. A latent function is never @pure or @reads. |

**Documentation attributes** never change bytecode. They are stored and diffed, and they are covered by the layout hash but not the semantic hash (section 2.5). Node positions, labels, colours and sizes are not attributes; they live in the layout block (section 2.3).

| Attribute | Applies to | Meaning |
| --- | --- | --- |
| `@doc("text")` | any declaration or node | Short tooltip and reflection text. Long-form and region-level explanations are `note`s (section 2.3). |
| `@category("Math")`, `@keywords("a", "b")` | `func`, `macro` | Palette organisation. |

A node with no `place` line in the layout block is auto-laid-out by the editor and gets a position when first saved, so graphs written by a tool or an LLM are valid without any layout.

Wires refer to pins by name, so renaming a parameter or result would otherwise break every wire that mentions it. Giving parameters, results, fields, enum members and locals an `@id` lets an editor or merge tool recognise a rename as a rename (the id is unchanged, the name differs) and rewrite the references in one step.

**Identity rules.**

- **Required.** Every declaration, parameter, result, field, enum member and local that an editor writes carries an `@id`, generated by the editor as a short random token. Node ids are always present, since they are the node's name. An element without `@id` is still valid, but its identity is its name: renaming it is, for a merge, a deletion plus an addition (section 7.1), and `W0202` says so.
- **Present uniqueness.** Within a file, every `@id` is unique among its siblings of the same kind (`E0102`), and a node or box id is unique within its graph. This is all a file can guarantee on its own.
- **Operational non-reuse.** That an id is never used again after its element is deleted is guaranteed only by the project registry `wiret.ids` (section 7.3). Editors and `wiretc edit` append retired ids to it, and CI runs `wiretc ids --check base..head` to catch a commit that deleted an element without registering it. A retired id reappearing is `E0140`.
- **Never regenerated.** Tools keep existing ids on load and save (section 7.5); they only generate ids for elements that have none.

**Preservation rules.**

- Unknown attributes are preserved exactly: the order of arguments and of repeated attributes is kept. A tool may not drop an attribute because it does not recognise it.
- **Unsafe attributes** (borrowed from GML): an attribute whose name starts with a capital letter, for example `@Hash(...)` or `@Cached(...)`, is derived data. Any tool that modifies the graph must delete it, and tools should not write one they cannot keep correct.
- Third parties use a namespaced name such as `@x.acme.review("ok")`. Names without a dot are reserved for this specification.

### 2.5 Canonical form, hashes and Git

The canonical form is a function of the model alone, so two tools always write identical bytes for the same graph. The formatter (`wiretc fmt`) and every editor save produce it.

1. UTF-8 NFC, LF, two-space indentation, one trailing newline.
2. Items ordered by kind (`use`, `extern`, `const`, `var`, `enum`, `struct`, `interface`, `class`, `macro`, `func`, `event`), then by name.
3. Inside a body: `local` statements by name, then `state` statements by name, then `node` statements sorted by **node id** (ASCII order), then the `notes` block, then the `layout` block last. Wiring never reorders anything.
4. Inside the layout block: `place` lines sorted by node id, then `box` lines sorted by box id. Inside a box, `members` are sorted by id. Moving a node changes only its own `place` line; moving a box changes only its own `box` line. Inside the notes block, `note` lines are sorted by note id.
5. Bindings are written in the node kind's pin order (from the registry); bindings equal to the pin default are omitted.
6. Attributes: semantic ones alphabetically, then `@doc`. Exec targets precede attributes.
7. A node longer than 100 columns wraps inside its parentheses or exec map, one binding per line.
8. Numbers and strings are written in their shortest unambiguous form.
9. Line comments are not representable. The formatter refuses to lose one silently (`W0603`, section 2.1); durable annotations are `note`s.

Two hashes are defined over the canonical form, both SHA-256:

- **Semantic hash**: computed after removing the `layout` block, the `notes` block, `@doc`, `@category`, `@keywords`, and `Reroute` nodes, and after sorting declarations by name and nodes by id. It is embedded in the `.wbc`, so CI can prove that a commit changed behaviour or did not. Two properties must hold and should be tested: reversing the order of the nodes in a graph, or deleting its layout block and all documentation attributes, changes neither the semantic hash nor a single byte of the instruction stream.
- **Layout hash**: computed over the entire canonical file. If two collaborators have the same layout hash, they see the identical graph.

Because each node is one line, lines are sorted by id, and layout lives in its own block, plain line-based Git merges succeed whenever two people touch different nodes, and a move never collides with a rewire. Two people adding nodes also rarely collide, because ids are random slugs and sort into different places. The full merge algorithm, which works on the parsed model rather than on text, is in section 7.1. The examples in this document are shown in *flow order* for readability, which `wiretc view --flow` produces; the compiler accepts any order.

**Storage order is not review order.** Sorting by id gives the best merges but scatters a function's execution order across the file. So the id-sorted file is the storage format, and reviewers are not expected to read it raw. The Git setup in section 7 attaches a `textconv` filter that runs `wiretc view --flow` before Git computes a diff, so `git diff`, `git log -p` and hosting-site pull requests that honour the attribute show nodes in flow order. `wiretc diff` goes further and prints a node-aware semantic diff (added, removed and rewired nodes, with layout-only changes separate). Flow order is defined in section 7 so that it is itself deterministic. Whether id-sorted storage should stay the default is decided by the review trial in section 9.1, not assumed here.

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
    notes {
      note why_local on set_new "Store the new health once: pure nodes are re-evaluated per consumer (section 4.3)."
    }
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
      box death "Death handling" at (940, -90) size (330, 120) [members = [log_dead, ret_dead], color = "#C0392B"]
    }
  }

  event Respawn() {
    node entry = Entry -> wait
    node wait  = Delay(seconds: 2.0) -> reset
    node reset = SetField health (obj: entry.self, value: 100)
  }
}

func Clamp01(v: f32) -> (result: f32) @pure {
  node entry = Entry -> ret
  node lo    = Max<f32>(a: entry.v, b: 0.0)
  node hi    = Min<f32>(a: lo.result, b: 1.0)
  node ret   = Return(result: hi.result)
}

func Fib(n: i32) -> (result: i32) @pure {
  node entry   = Entry -> is_base
  node lt      = Lt<i32>(a: entry.n, b: 2)
  node is_base = Branch(cond: lt.result) { then -> ret_n, else -> ret_sum }
  node ret_n   = Return(result: entry.n)
  node n1      = Sub<i32>(a: entry.n, b: 1)
  node n2      = Sub<i32>(a: entry.n, b: 2)
  node f1      = Call Fib(n: n1.result)
  node f2      = Call Fib(n: n2.result)
  node sum     = Add<i32>(a: f1.result, b: f2.result)
  node ret_sum = Return(result: sum.result)
}

macro ForRange(in: exec, first: i32, last: i32) -> (each: exec, done: exec, index: i32) {
  local i: i32
  node entry  = Entry -> init
  node init   = SetLocal i (value: entry.first) -> test
  node cur    = GetLocal i
  node cmp    = Le<i32>(a: cur.value, b: entry.last)
  node test   = Branch(cond: cmp.result) { then -> seq, else -> finish }
  node seq    = Sequence @count(2) { then0 -> each_out, then1 -> bump }
  node each_out = Exit each (index: cur.value)
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
