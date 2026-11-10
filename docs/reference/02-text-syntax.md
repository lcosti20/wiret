## 2. Text syntax

### 2.1 Files and lexical structure

A `.wiret` file is UTF-8 (no BOM) with LF line endings and holds exactly one module. Statements end at a newline. Newlines are ignored inside `( )`, so long signatures can wrap, and so can a node's inputs, which are written in parentheses after the node, one per line in canonical form (section 2.3).

`//` starts a line comment. A run of comment lines that stands directly above a declaration, a member of a `struct`, `enum`, `interface` or `class`, a `local` or `state` statement, a node statement, an input binding or a flow wire, with no blank line between, is **attached** to it, as are comment lines among its metadata lines:

```
// Applies damage and reports whether the player died.
func TakeDamage(amount: i32) -> (died: bool) {
  flow {
    // health is stored first, so the check reads the new value
    entry -> set_new
```

An attached comment is part of the model. The formatter and every editor write it back above its element, at the element's indentation and above any metadata lines, a merge carries it like any other field of its element (section 7.1), and it moves with its element when statements are sorted. Like metadata it is outside the semantic hash and inside the layout hash (section 2.5). The text after `//` is kept as written, except that one space after `//` is the canonical separator. A node that carries a comment is always declared, never written inline (section 2.3), so its comment has a line to stand above.

A comment that is attached to nothing (one that ends a line of code, is followed by a blank line or a closing `}`, or stands in the layout block) is *trivia*, and the canonical writer cannot keep it. It never drops one silently: `wiretc fmt` reports `W0603` for each comment it would lose and exits non-zero, unless told what to do with them: `--convert-comments` turns each comment into a `#[note("...")]` on the next node, declaration or box (section 2.4; a node's notes stand above its line in the layout block), so the text stays with what it was written beside, and `--drop-comments` discards them. An editor that opens a file containing such comments offers the same choice.

Comments are for whoever reads the text. Explanations that the graph editor shows are written as a `#[note]` (an explanation of a graph, node or box), a `#[doc]` (the short tooltip text of a declaration or node), or a `box` (visual grouping).

| Token | Form |
| --- | --- |
| Identifier | `[A-Za-z_][A-Za-z0-9_]*` |
| Qualified name | `std.math.Sqrt` |
| Pin reference | `node_id.pin_name`; an inline node's name has dots of its own, as in `show.message.result` (section 2.3) |
| Comment | `// text`, to the end of the line; kept when it stands directly above what it explains (see above) |
| Type arguments | `::<i32>`, `::<i32, string>`; always introduced by `::` |
| Arrows | `->` (exec wire, results), `<-` (input binding) |
| Integer | `42`, `-7`, `0xFF`, `1_000`; optional suffix `i8 u8 i16 u16 i32 u32 i64 u64` |
| Float | `1.5`, `2e-3`; optional suffix `f32` or `f64` |
| Other literals | `true`, `false`, `null` |
| Enum value | `Mode::Chase`: the enum's name, `::` and one of its members (section 2.3) |
| String | `"text"` with escapes `\\n`, `\\t`, `\\"`, `\\\\` and `\\u{1F600}` |
| Tuple / list / map | `(1, 2)`, `[a, b]`, `{k: v}`; used only inside attributes, except that a tuple of numbers is also the literal of a vector type, `(0, 1, 0)` (section 3.1.1) |
| Semantic attribute | `@pure`, `@count(2)`; at the end of the line it modifies (section 2.4) |
| Metadata attribute | `#[doc("text")]`; on its own line, above what it describes (section 2.4) |

A literal takes the type of the pin it is bound to, so suffixes are only needed where a literal is used without a pin (attribute arguments). The keywords are `wiret module use extern const var local enum struct interface class impl macro func event dispatcher node state flow layout box at size`. They are **contextual**: each is a keyword only where a statement of its kind can start, so any of them may name a node, field, parameter, local, pin, type or declaration. A word next to a `.`, or followed by a single `:`, is always a name, which covers every pin, field, parameter and local (`.size <- 1`, `state: i32`, `layout.size`); inside a class `func: i32` is a field and `func F()` a method; in the layout block `box` starts a box line only when a box id and a title follow it (`box death "Death" at ...`), so a node called `box` is written `box at (x, y)`. Only `true`, `false` and `null` are reserved, since they are values wherever a value can stand.

### 2.2 Module header and declarations

Every file starts with a version line and a module line:

```
wiret 1
module game.demo @id("mod_k3f9")
```

The module name is the namespace prefix of everything declared in the file (`game.demo.Player`). The grammar below uses `NL` for a newline and `attrs` for zero or more trailing semantic attributes (section 2.4). Metadata lines (`#[...]`, section 2.4) may precede the module line, any item, any member of an `enum`, `struct`, `interface` or `class`, and, inside a body, any `local` or `state` statement and, in the layout block, any node's line or `box` line; they are left out of the productions to keep them readable. So are `//` comment lines (section 2.1), which may also stand above a node statement, a binding or a flow wire.

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
func       = "func" IDENT [ tparams ] params [ results ] attrs ( "{" body "}" | "=" value NL ) ;
event      = "event" IDENT params attrs "{" body "}" ;
macro      = "macro" IDENT [ tparams ] params [ results ] attrs "{" body "}" ;
params     = "(" [ param { "," param } ] ")" ;
results    = "->" params ;                     (* results are always named *)
param      = IDENT ":" type [ "=" literal ] ;
tparams    = "::" "<" IDENT { "," IDENT } ">" ;
type       = prim | qname | "exec"
           | "array" "::" "<" type ">" | "set" "::" "<" type ">"
           | "map" "::" "<" type "," type ">"
           | "delegate" "::" "<" tlist [ "->" tlist ] ">" | "dispatcher" "::" "<" tlist ">" ;
tlist      = "(" [ type { "," type } ] ")" ;
prim       = "bool" | "i8" | "u8" | "i16" | "u16" | "i32" | "u32"
           | "i64" | "u64" | "f32" | "f64" | "string"
           | "vec2" | "vec3" | "quat" | "transform" ;
```

Notes on the declarations:

- `struct` is a **value type**: immutable, copied by value, compared by field. `class` is a **reference type**: single inheritance, any number of `interface`s, fields default to the value written in the declaration. An `extern type` is an opaque host object (section 6.6).
- A function declared inside a class is a method. It receives an implicit first parameter `self`, visible in the graph as `entry.self`. Methods are virtual unless marked `@final`. A method's qualified name is `Class.Method` (`Player.TakeDamage`), which is how `Call`, diagnostics and the export table name it. `Call Boss.TakeDamage` finds the nearest declaration along `Boss`'s base classes.
- An override (a method with the name of one in a base class) takes the same parameters and results and has the same latency, and a `@final` method has none (`E0150`). A class extends a class of the same module, and the chain may not loop (`E0151`). A field name is declared once along the chain (`E0102`).
- A class implements each interface named after `impl` with a `func` of the same name, parameters and results, its own or inherited from a base class, and it also implements its base classes' interfaces (`E0152` otherwise; an `impl` name that is not an interface is `E0151`). Interface methods are called with `Call Damageable.Hit`, whose first input is `self` of the interface type.
- **Provisional.** Interface methods are not latent in version 1: the `5A` type entry records only function types, so a caller could not know that `call_interface` might suspend. An implementation is therefore never `@latent`, and the verifier checks it.
- An `event` is a function with no results that the host or other graphs can invoke by name, and that may contain latent nodes (section 4.5). A `dispatcher` is a multicast event slot on a class, like a Blueprint Event Dispatcher.
- A `macro` is inlined at every use, so it may contain `exec` pins as parameters and results. Everything else exposes `exec` pins implicitly.
- `extern func host.Log(message: string)` imports a host native. The import module is every segment but the last (`host`), the import name is the last (`Log`).
- `exec` is a type only for macro parameters and for the type arguments of `Reroute`.
- `vec2`, `vec3`, `quat` and `transform` are built-in struct types (section 3.1.1). Their literals are tuples, nested for a transform: `const Up: vec3 = (0, 1, 0)`, `.offset <- (0, 0.5, 0)`, `spawn: transform = ((0, 2, 0), (0, 0, 0, 1), (1, 1, 1))`. The formatter writes each component as it writes an `f32` literal.
- An enum member without `= INT` is one more than the member before it, and the first member is 0. Every value must fit the underlying type, `i32` unless one is written (`E0110`).
- Struct fields and enum members keep the order they are written in (section 2.5). Field names, and member names, are unique within their declaration (`E0102`), and a struct or enum may not take the name of a built-in type (`E0102`).
- A struct may not hold itself by value, directly or through other structs (`E0503`): it would have no finite default value. Holding it in an array is allowed, since an array starts empty, so `struct Tree` may have a field `children: array::<Tree>`.

### 2.3 Graph bodies: nodes, bindings, exec wiring

The body of a `func`, `event` or `macro` is a list of `local` and `state` declarations, then at most one `flow` block, then the `node` statements, then at most one `layout` block (the reader accepts them in any order). Everything that decides behaviour is in the node statements and the flow block: node statements say *what* each node does and where its data comes from, the flow block says *in which order* nodes run. Everything else about a node is in the layout block: where it is drawn, and the `#[note]` and other metadata lines that explain it (section 2.4). A graph's own notes stand above the graph.

```
body      = { local | state } [ flow ] { node } [ layout ] ;
local     = "local" IDENT ":" type [ "=" literal ] NL ;
state     = "state" IDENT ":" type [ "=" literal ] NL ;
node      = "node" IDENT "=" expr attrs NL ;
expr      = KIND [ symbol | STRING ] [ targs ] "(" [ binding { "," binding } [ "," ] ] ")" ;
targs     = "::" "<" type { "," type } ">" ;            (* STRING: Format's template *)
binding   = "." IDENT "<-" value ;
value     = pinref | literal | expr [ "." IDENT ] ;     (* expr: an inline node *)
pinref    = name "." IDENT | IDENT ;          (* IDENT: a declared node's one output *)
name      = IDENT { "." IDENT } ;            (* a node id, or an inline node's dotted name *)
flow      = "flow" "{" { wire } "}" NL ;
wire      = source "->" target NL ;
source    = IDENT [ "." IDENT ] ;             (* node, or node.exec_output *)
target    = IDENT [ "." IDENT ] ;             (* node, or node.exec_input *)
layout    = "layout" "{" { place | box } "}" NL ;
place   = name [ "at" "(" INT "," INT ")" [ props ] ] NL ;   (* the name alone carries metadata *)
box     = "box" IDENT STRING "at" "(" INT "," INT ")" "size" "(" INT "," INT ")" props NL ;
props   = "[" IDENT "=" value { "," IDENT "=" value } "]" ;
```

Rules:

1. **Node ids** are identifiers, unique within the graph. They are the identity of a node for diffs and merges. A node written inline in another node's input has no id of its own: its name is the path to where it is written, such as `show.message` (see *Inline nodes* below). Display names are not ids; they live in the layout (`label`). Editors generate a readable slug plus a short random suffix, such as `branch_k3m9`; humans and LLMs may choose descriptive ones such as `check_energy`. **Non-reuse is a project-level guarantee, not a file-level one.** A single file can only prove that its present ids are unique; it cannot know which ids were deleted earlier. Non-reuse is therefore enforced by the project's id registry `wiret.ids` (section 7.3), which records every retired node id: an editor save or `wiretc edit` that deletes a node appends its id, and a node that reuses a retired id is `E0140`. Without a project (a lone file) editors still generate fresh random suffixes, which makes accidental reuse improbable but not impossible, and `wiretc check` says so (`W0202`).
2. **Kind** is a PascalCase built-in (`Add`, `Branch`, `SetLocal`, ...; section 3.3). Calling a declared function is always `Call`, so the closed set of built-in kinds never collides with user names.
3. **Symbol** (optional) names the thing the node acts on: `Call std.math.Sqrt`, `GetField Player.health`, `SetLocal acc`, `GetState done`, `New Player`, `Cast Player`, `Macro ForRange`, `Exit done`, and for `Format` its template, a string: `Format "Total: {total}"` (section 3.3). A struct node names its struct, and a field node the struct and the field, since nothing else on the node says which struct it is: `MakeStruct Vec2`, `BreakStruct Vec2`, `GetField Vec2.x`, `WithField Vec2.x`. A member of a class (a field, a dispatcher, or a field that a container node changes) is always written with its class: `GetField Player.health`, `Broadcast Player.OnHit`, `ArrayAdd::<i32> Player.items`. A node therefore reads the same in a method and anywhere else, and moving it between them never changes its text. Inside a method the reader also accepts a member of the method's own class by its bare name, `GetField health`, and the formatter writes it qualified with that class. A member inherited from a base class resolves through the chain, so in a method of `Boss` the bare `health` is written `GetField Boss.health` and names the `health` declared in `Player`.
4. **Type arguments** follow the symbol: `Add::<i32>`, `Convert::<i32, string>`, `Call std.array.Get::<f32>`. They are always written out, never inferred. Every generic argument list in Wiret, on a node, a declaration (`macro ForEach::<T>`) or a type (`array::<i32>`), is introduced by `::`. A node statement binds an id to a kind (`node plus = Add::<i32>(...)`), and with a bare `<` a node such as `NodeType<a, b> variable` would read like a comparison; the `::` removes that ambiguity.
5. **Bindings** connect input pins. They are written in parentheses after the node, `.pin <- value`, separated by commas, and a trailing comma is allowed: `Call host.Log(.message <- "hi")`. Newlines inside the parentheses are ignored, and the canonical form puts each binding on its own line, indented one level further than the node, with a trailing comma (section 2.5). A node with no bound inputs is written with empty parentheses, `Entry()`, so every node reads the same way. `<-` mirrors the `->` of exec wires: data flows *into* the pin. The right-hand side is a pin reference (`other_node.pin`, a data wire; `other_node` alone when that node has one data output, see *Which output* below), a literal, or a node written inline (see *Inline nodes* below). An enum value is written `Mode::Chase`. `::` followed by a name never starts type arguments (those are `::<`), so an enum value never reads like a pin reference, and a node may share an enum's name: `Mode.then` is a wire from node `Mode`, `Mode::Idle` a value. The reader also accepts the dotted `Mode.Chase` of Draft 0.11 and earlier where the graph has no node called `Mode`, and the formatter writes it `Mode::Chase`. An input that is not listed takes the pin's default value (the declared default, otherwise the zero value of its type); the compiler warns (`W0201`) about unlisted inputs that have no declared default.
6. **Exec wiring** is written in the graph's `flow` block, one wire per line, never on node lines (see *The flow block* below). `source -> target` is shorthand for a source node with exactly one exec output; otherwise the output is named, `source.pin -> target`. An exec output with no wire is unconnected, which means "this chain ends here" (section 4.2).
7. **Targets** are exec inputs. The default exec input is `in`; write `node.pin` to target another one. Any number of producers may target the same exec input (merging flow).
8. **Data wires** may fan out freely: any number of nodes may reference the same output pin.
9. A pin reference must name an output pin of a node in the same graph. Function and event parameters appear as output pins of the `Entry` node (`entry.amount`, and `entry.self` for methods).
10. **`state`** declares a slot that keeps its value between executions of the graph. In a macro there is one slot per expansion site, which is what `DoOnce` and `FlipFlop` need. In a method it lives on the object, in a free function on the module instance. On an object, each class's state slots follow its fields and dispatchers: for each method by name, its own `state` by name, then that of each macro it expands, node by node. The compiler allocates hidden fields or globals for it, named after the expansion path. Read and write it with `GetState` and `SetState`.
11. `Reroute::<T>` is a visual-only node that passes a wire through a bend point. It is erased by the compiler. `Reroute::<exec>` reroutes control flow.

#### Inline nodes

An input has exactly one source, so read backwards from the inputs the data wires of a graph form a tree, and only a shared output breaks it. The text uses this: a node whose output feeds a single input is written inside that input instead of being declared and named:

```
node show = Call host.Log(
  .message <- Call std.string.Concat(
    .a <- "Your score is ",
    .b <- Convert::<i32, string>(
      .value <- GetLocal score(),
    ),
  ),
)
```

- **Which output.** A node with one data output feeds that output in, so nothing more is written, the way `entry -> loop` leaves out the exec output of a node that has one. That holds for an inline node (`GetLocal score()`) and for a wire from a declared node (`.value <- hp`, not `hp.value`). A node with several outputs names the one it feeds in: `.len <- BreakStruct Vec2(...).x`, `.x <- parts.x`; leaving it out is a syntax error that lists the outputs. The reader also accepts the one output written out (`GetLocal score().value`, `hp.value`), and the formatter leaves it out, except on a wire from `Entry` or a macro node, whose outputs are parameters and results and are always named (`entry.amount`, `loop.index`). An inline node's dotted name is always followed by its output, since `show.message` alone reads as node `show`, output `message`. A bare name that is no node of the graph is kept as written and reported as `E0101`, so deleting a node never makes the file unreadable.

- **Names.** An inline node's name is its consumer's name, a dot and the input it feeds: above, the `Concat` is `show.message`, the `Convert` is `show.message.b` and the `GetLocal` is `show.message.b.value`. The name is used wherever the node must be named: in the layout block, in a box's `members`, in diagnostics, in the debugger, in `wiretc edit` requests and in pin references (`show.message.b.result`), where the output is always named.
- **Which nodes are inline.** In canonical form a node is written inline exactly when one input in the graph reads it, it has no exec pins (it is pure or `reads`) and it carries no semantic attribute or `//` comment (an attribute ends a node's statement and a comment stands above one, and an inline node has none of its own). Every other node is declared with a `node` statement: a node with exec pins, an unread node, and a node whose outputs feed several inputs. A shared output is the one place where the data graph is not a tree, and the declared node's id is the name it is shared under.
- **Either form is read.** The reader accepts a single-use node declared by name, and the formatter writes it inline. When an edit makes an inline node feed a second input, it is declared, under its dotted name with the dots turned into underscores (`show_message_b`), followed by `_2`, `_3`, ... when that name is already the id of another node of the graph or, in a project, a node id of the graph retired in `wiret.ids` (section 7.3), so a promotion never produces a duplicate or an `E0140`; when a declared node comes to feed a single input, it moves inline and takes the name of where it is.
- **Notation only.** Writing a node inline changes nothing about when or how often it is evaluated (section 4.3): the model has the same nodes and wires, and the compiled instructions are the same.
- **Positions, not identities.** Because an inline node's name says where it is written, it changes when the node moves to another input, and another node may be written there later. Inline names are therefore never retired in `wiret.ids` and are never `E0140` (section 7.3), and a merge matches inline nodes by their position.

#### Expression bodies

A `func` outside a class with exactly one result may be written `= value` instead of a body in braces. In the value, a parameter is named bare:

```
func Clamp01(v: f32) -> (result: f32) @pure = Min::<f32>(
  .a <- Max::<f32>(
    .a <- v,
    .b <- 0.0,
  ),
  .b <- 1.0,
)
```

- It is notation for the graph `entry -> ret` with `node entry = Entry()` and `node ret = Return(.result <- value)`: the model, the compiled code and the semantic hash are those of that graph, `v` is `entry.v`, and the inline nodes are named under `ret` (`ret.result`, `ret.result.a`).
- The canonical form uses it exactly when a function's graph has that shape and nothing else to keep: no locals or states, no layout block, and no attribute, metadata line or comment on `entry`, `ret`, the wire between them or `ret`'s input. Once an editor places the nodes the function is written with braces and a layout block; deleting the layout block writes it as `= value` again.
- A function with several results, a method, an event and a macro always have a body in braces (a syntax error says so).

#### The flow block

Control flow is declared separately from the nodes, in the graph's `flow` block, which comes before the node statements, so a graph reads as the order in which it runs and then the nodes that run. Each line is one wire from an exec output to an exec input:

```
flow {
  entry -> set_new
  set_new -> store
  store -> chk
  chk.then -> log_dead
  chk.else -> ret_alive
  log_dead -> ret_dead
}
```

- A wire's source is a node id, optionally followed by the name of one of its exec outputs. The bare form is allowed only when the node has exactly one exec output (`entry -> start`, `say -> keep`); a node with several names the one it means (`chk.then`, `loop.each`, `seq.then0`; a macro `Entry` names its exec parameters, `entry.in`, `entry.reset`).
- A wire's target is a node id, optionally followed by the exec input to enter; the default is `in` (rule 7).
- An exec output has at most one wire (`E0121`). A wire whose source is not a node of the graph is a syntax error; a target that names no node is `E0101`.
- Keeping wires out of the node statements means a node line reads as a declaration (what the node does and where its data comes from), and the order in which nodes run can be read in one place instead of being followed from node to node like a chain of jumps.
- The flow block is semantic: it is part of the semantic hash. In canonical form wires are sorted by source node id, then by the source node's exec-output order from the registry (section 2.5); `wiretc view --flow` shows them in flow order instead.

#### The layout block

Positions, appearance and explanations are not written in node statements. They live in the graph's `layout` block, one line per node, named the way the node is written, with the node's metadata lines (section 2.4) directly above its line:

```
layout {
  chk at (800, 0)
  chk.cond at (640, 120)
  log_dead at (960, -40) [label = "Log death", color = "#C0392B"]
  #[note("Store the new health once: pure nodes are re-evaluated per consumer (section 4.3).")]
  set_new at (160, 0)
  box death "Death handling" at (940, -90) size (330, 120) [members = [log_dead, ret_dead], color = "#C0392B"]
}
```

- A `place` line gives a node's position, and optionally `label`, `color`, `size`, `collapsed` and `hidden` (a list of pin names). Coordinates are integers, so there is no floating-point noise in diffs.
- A `box` is a visual group with its own id (unique among node ids and box ids in the graph), a title, a position and a size. **Membership is explicit and authoritative:** `members = [id, ...]` is required and lists node ids and box ids. Position and size only say where the box is drawn; a node lying inside a box's rectangle is not thereby a member, and a member lying outside it is still a member. An editor may offer to add a node dragged into a box to `members`, but the list is what is saved. A box with `collapsed = true` is drawn as one node whose pins are the wires crossing its edge (the compiler still sees the flat graph).
- **Nesting and overlap.** A box may list another box as a member, which nests it; the nesting must be acyclic. A node or box is a member of at most one box. If it appears in several, the box with the smallest id keeps it and `W0602` reports the rest. Rectangles may overlap freely, since they have no effect on membership. A member id that names nothing is `W0601` and is removed on the next editor save.
- A node with no `place` line is auto-placed by the editor, and gets a line when first saved. This makes LLM-generated graphs valid without layout. A node that has metadata but no position yet is listed by its name alone, with its metadata lines above it.
- A layout line, or metadata above one, whose name is not a node of the graph is kept as written and reported as `W0605`. This is what a hand edit leaves behind when it moves an inline node, since that changes the node's dotted name (section 2.3). The stale line and its notes stay, in the editor, in `wiretc fmt` and through a merge, until someone renames the line to the node's new name or deletes it, so an edit to a node statement can never make the layout block unreadable or lose a note.
- Unknown properties are preserved. The block never affects the semantic hash.
- Personal view state (zoom, scroll, selection, open panels) is never written to the file (section 7.5).

This split is what makes collaboration work: one person moving a node or rewording its note and another rewiring it edit different lines, and they merge without a conflict. It also keeps a node statement to what changes compiled output.

### 2.4 Attributes and metadata

There are two kinds of attribute, and they are written differently so that a reader can tell at a glance which ones affect the program:

- A **semantic attribute** (`@pure`, `@count(2)`, `@id("...")`) is part of the program. It is written at the end of the line it modifies (for blocks, before the `{`), it is short, and only the attributes in the first table below exist. It is covered by the semantic hash.
- A **metadata attribute** (`#[doc("...")]`, `#[note("...")]`) is information *about* the program and never changes compiled output. It is written on its own line, directly above the statement it describes and at the same indentation, so it can be as long as it needs to be without crowding that statement. A node's metadata stands above the node's line in the layout block (section 2.3), not above the node statement. It is outside the semantic hash and inside the layout hash (section 2.5).

```
attr  = "@" IDENT [ "(" [ arg { "," arg } ] ")" ] ;
meta  = "#[" mname [ "(" [ arg { "," arg } ] ")" ] "]" NL ;
mname = IDENT { "." IDENT } ;
arg   = [ IDENT ":" ] value ;
value = literal | IDENT | tuple | list | map ;
```

```
#[doc("Clamps a value to the range 0 to 1.")]
#[category("Math")]
func Clamp01(v: f32) -> (result: f32) @pure {
```

A metadata line attaches to the next statement that is not itself a metadata line. Section 2.2 lists the statements that may carry one; parameters, bindings, flow wires and node statements may not (a node's metadata goes above its line in the layout block), though a `//` comment may stand above the last three (section 2.1). A metadata line followed by a blank line, a closing `}` or the end of the file is a syntax error, so metadata can never float free in the text.

**Semantic attributes** may change compiled output. Only the attributes in this table exist: an unknown `@` name is `E0104`, and when the name is a metadata attribute (`@doc`, `@category`, `@keywords`) the message shows the `#[...]` form instead.

| Attribute | Applies to | Meaning |
| --- | --- | --- |
| `@id("...")` | any declaration, module, parameter, result, field, enum member, local | Stable identity that survives rename and move. Editors always write it in a project (`W0202` where it is missing); hand-written and LLM-written code may omit it and gets one on the first editor save or `wiretc fmt --assign-ids`. See the identity rules below. |
| `@pure` | `func` | Effect-free, deterministic and cacheable (section 4.3): the result depends only on the explicit arguments and on `const`s. Callers treat a call as a pure node (no exec pins, evaluated on demand). The graph inside is an ordinary exec graph and may branch, loop and recurse; it may use its own locals, but may not write variables, fields or state (`E0302`), read variables, fields or state, dereference a class reference or host handle, or call anything that is not `@pure` (`E0304`), and may not contain a latent node (`E0302`). |
| `@reads` | `func` | Effect-free and deterministic for a given VM state, but not cacheable: may read variables, fields, state and objects, but not write them. A call is a pure node that is re-evaluated at each consumer (section 4.3), like `GetField`. May call only `@reads` and `@pure` functions (`E0302`) and may not contain a latent node. |
| `@final` | method | Not virtual. Calls are bound at compile time. |
| `@private` | declaration | Not visible outside the module. |
| `@export` | `func`, `event`, `var`, type | Listed in the module's export table for the host and other modules. A normal build exports only what carries `@export`; an `--export-all` build (editor run and debug sessions) also exports every `func`, `event` and method, and marks the `@export` ones as declared (section 5.2). |
| `@inline` | `func` | Hint to inline at call sites. |
| `@deprecated("msg")` | declaration | Warning at every use. |
| `@count(n)` | `Sequence`, `MakeArray`, ... | Number of dynamic pins. |
| `@cases(v0, v1, ...)` | `Switch` | Case values. Pins are `case0`, `case1`, ... and `default`. Each value must be a value of the `Switch`'s type (`E0110`); on an enum `Switch` they are members, `@cases(Mode::Idle, Mode::Chase)`. |
| `@live` | node without exec pins | The node is meant to be read again at each consumer, so each sees the current value (section 4.3). It excuses `E0320` for the reads behind it. |
| `@disabled` | node | Node is skipped: a one-exec-out node passes control straight to its target; data outputs read as zero. |
| `@capability("name")` | `extern func` | The import needs this host capability. Listed in the `wr.caps` section; the load fails unless the host granted it (section 6.5). |
| `@latent` | `func` | The function may suspend. Required when it contains a latent node or calls a latent function or event (`E0201`). Events are implicitly latent. A latent function is never `@pure` or `@reads`. |

**Metadata attributes** never change bytecode. They are stored and diffed, and they are covered by the layout hash but not the semantic hash (section 2.5). Node positions, labels, colours and sizes are not attributes; they live in the layout block (section 2.3).

| Attribute | Applies to | Meaning |
| --- | --- | --- |
| `#[doc("text")]` | any declaration or node | Short tooltip and reflection text, for whoever *uses* the declaration or node: one sentence, shown in the palette and on hover, and copied to `wr.reflect` (section 5.4). |
| `#[category("Math")]`, `#[keywords("a", "b")]` | `func`, `macro` | Palette organisation. |
| `#[note("text")]` | any declaration, node or `box` | Explanatory prose for whoever *maintains* the graph: rationale, warnings, region-level explanations. A note on a `func`, `event` or `macro` explains the whole graph. See *Notes* below. |

#### Notes

```
node set_new = SetLocal new_hp(
  .value <- sub.result,
)

layout {
  #[note("Store the new health once: pure nodes are re-evaluated per consumer (section 4.3).")]
  set_new at (160, 0)
}
```

- A target may carry any number of notes. They keep the order they were written in.
- The text is a string and may contain `\n`. A long note is written as one long line, since line diffs of prose are no worse than for any other line. Because a note is a line of its own, in the layout block for a node, rewording it never touches the statement it describes, so it cannot conflict with an edit to that statement (section 7.1).
- A note on a box is written above the `box` line in the layout block.
- **Notes are never deleted as a side effect.** A tool that deletes a node or box moves its notes up to the enclosing graph and records where they came from, as in `#[note("...", detached: "set_new")]`. A note on a deleted declaration moves to the enclosing declaration (the class, for a method), or to the module line for a top-level item. A detached note is reported as `W0604` until someone re-homes it (moves it above another target and removes `detached`) or deletes it.

**Preservation rules.**

- Unknown metadata attributes are preserved exactly: the order of arguments and of repeated attributes is kept. A tool may not drop an attribute because it does not recognise it.
- **Unsafe attributes** (borrowed from GML): a metadata attribute whose name starts with a capital letter, for example `#[Hash(...)]` or `#[Cached(...)]`, is derived data. Any tool that modifies the graph must delete it, and tools should not write one they cannot keep correct.
- Third parties use a namespaced name such as `#[x.acme.review("ok")]`. Names without a dot are reserved for this specification.

A node with no `place` line in the layout block is auto-laid-out by the editor and gets a position when first saved, so graphs written by a tool or an LLM are valid without any layout.

Wires refer to pins by name, so renaming a parameter or result would otherwise break every wire that mentions it. Giving parameters, results, fields, enum members and locals an `@id` lets an editor or merge tool recognise a rename as a rename (the id is unchanged, the name differs) and rewrite the references in one step.

**Identity rules.**

- **Required.** Every declaration, parameter, result, field, enum member and local that an editor writes in a project (section 7.3) carries an `@id`, generated by the editor as a short random token. Node ids are always present, since they are the node's name. An element without `@id` is still valid, but its identity is its name: renaming it is, for a merge, a deletion plus an addition (section 7.1), and in a project `W0202` says so. A file outside a project, such as a tutorial or a snippet, may leave `@id`s out, and editors do not add them there: without a registry nothing could check that its ids are never reused, so they would only add noise.
- **Present uniqueness.** Within a file, every `@id` is unique among its siblings of the same kind (`E0102`), and a node or box id is unique within its graph. This is all a file can guarantee on its own.
- **Operational non-reuse.** That an id is never used again after its element is deleted is guaranteed only by the project registry `wiret.ids` (section 7.3). Editors and `wiretc edit` append retired ids to it, and CI runs `wiretc ids --check base..head` to catch a commit that deleted an element without registering it. A retired id reappearing is `E0140`.
- **Never regenerated.** Tools keep existing ids on load and save (section 7.5); they only generate ids for elements that have none.

### 2.5 Canonical form, hashes and Git

The canonical form is a function of the model alone, so two tools always write identical bytes for the same graph. The formatter (`wiretc fmt`) and every editor save produce it.

1. UTF-8 NFC, LF, two-space indentation, one trailing newline.
2. Items ordered by kind (`use`, `extern`, `const`, `var`, `enum`, `struct`, `interface`, `class`, `macro`, `func`, `event`), then by name. Inside a `struct` or `enum`, fields and members keep the order they are written in: field order is the struct's layout, and member order gives the value of a member written without `= INT`, so reordering them changes the program and its semantic hash. Inside a `class`, fields likewise keep their written order (the object layout), followed by the methods: `func`s, then `event`s, each sorted by name. Inside an `interface`, methods keep their written order, since a method's position is its dispatch slot. A class's `dispatcher` lines come after its fields, in their written order, and before its methods.
3. Inside a body: `local` statements by name, then `state` statements by name, then the `flow` block, then the declared `node` statements sorted by **node id** (ASCII order), then the `layout` block last. The flow block, the node statements and the layout block are each preceded by one blank line unless they open the body, and an empty block is omitted. Wiring an exec pin never reorders node statements; it only adds or removes `flow` lines.
4. Inside the layout block: a line per node sorted by the node's name (so an inline node's line follows its consumer's), each with the node's metadata lines directly above it, then `box` lines sorted by box id. Inside a box, `members` are sorted by id. Moving a node changes only its own `place` line; moving a box changes only its own `box` line. Inside the flow block, wires are sorted by source node id, then by the source's exec-output order from the registry; the bare `source -> target` form is used exactly when the source has one exec output.
5. A node statement is `node <id> = <Kind>(`, then its bindings, one per line, indented two spaces further than the node, each written `.pin <- value,` with a trailing comma, in the node kind's pin order (from the registry), then `)` at the node's indentation. Bindings equal to the pin default are omitted, and a node with no bindings left is written `<Kind>()` on its line. A node that only one input reads, and that has no exec pins and no semantic attribute, is written inline as that input's value, laid out the same way one level deeper and followed by `.output` only when it has more than one data output (section 2.3). A wire from a declared node with one data output is written with the node's id alone, unless the node is `Entry` or a macro. A function whose graph is only `entry` wired to `ret` is written `= value` (section 2.3, *Expression bodies*).
6. Semantic attributes are sorted alphabetically and end the line they modify (on a node, the line with its closing parenthesis). Metadata lines stand directly above their statement, or for a node above its line in the layout block, with no blank line between, in this order: `doc`, `category`, `keywords`, then `note` lines in the order they were written, then any other metadata in the order it was written. A metadata line moves with its statement when statements are sorted.
7. Nothing else wraps: each binding line, each metadata line and each flow wire is a single line.
8. Numbers and strings are written in their shortest unambiguous form.
9. An attached `//` comment stands directly above its element at the element's indentation, one line per comment line, `// text` (`//` for an empty one), above the element's metadata lines. A comment attached to nothing is not representable: the formatter refuses to lose one silently (`W0603`, section 2.1).
10. **No alignment padding.** A node statement is written `node <id> = <Kind> ...` with exactly one space on each side of `=`, and a `place` line is `<id> at (x, y)` with one space before `at`. Nothing is padded to line up with its neighbours. Aligning would put the `=` of every node at the column of the longest id, so adding one long id would change every line of the graph and break the one-line-diff rule (section 1.2, principle 1); the same holds for `at` in the layout block. The reader accepts extra spaces and the formatter removes them. An editor may align in its own display, but never in the saved text.

Two hashes are defined over the canonical form, both SHA-256:

- **Semantic hash**: computed after removing the `layout` block, every metadata line (`#[...]`), every `//` comment, and `Reroute` nodes, and after sorting declarations by name and nodes by id. Because every metadata attribute is written with `#[` and nothing else is, a tool can strip them without knowing their names. The hash is embedded in the `.wbc`, so CI can prove that a commit changed behaviour or did not. Two properties must hold and should be tested: reversing the order of the nodes in a graph, or deleting its layout block and all metadata lines, changes neither the semantic hash nor a single byte of the instruction stream.
- **Layout hash**: computed over the entire canonical file. If two collaborators have the same layout hash, they see the identical graph.

Because each input is one line, declared nodes are sorted by id, and layout and notes live in their own block, plain line-based Git merges succeed whenever two people touch different nodes, and a move never collides with a rewire. Inline nodes trade some of this for readability: a single-use node sits where its value is used, so wiring it into a second input (or unwiring it) moves its lines, and such an edit shows as a larger diff than a rewire of a declared node. Two people adding nodes also rarely collide, because ids are random slugs and sort into different places. The full merge algorithm, which works on the parsed model rather than on text, is in section 7.1. The examples in this document are shown in *flow order* for readability (both node statements and `flow` wires), which `wiretc view --flow` produces; the compiler accepts any order. They follow rule 10 (no alignment), so apart from their order they are in canonical form.

**Storage order is not review order.** Sorting by id gives the best merges but scatters a function's execution order across the file. So the id-sorted file is the storage format, and reviewers are not expected to read it raw. The Git setup in section 7 attaches a `textconv` filter that runs `wiretc view --flow` before Git computes a diff, so `git diff`, `git log -p` and hosting-site pull requests that honour the attribute show nodes in flow order. `wiretc diff` goes further and prints a node-aware semantic diff (added, removed and rewired nodes, with layout-only changes separate). Flow order is defined in section 7 so that it is itself deterministic. Whether id-sorted storage should stay the default is decided by the review trial in section 9.1, not assumed here.

Guidance for LLM authors: write a node that feeds a single input inline in that input, without `.result` when it has one output, write a one-result function that is a single expression as `= value`, build text with `Format`, declare only nodes with exec pins or shared outputs, choose descriptive snake\_case ids for them, always write type arguments, never rely on inference, read pin names from the registry (section 3.5) instead of guessing, omit the layout block, and run `wiretc check --json` and `wiretc fmt` on the output (section 7.2).

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

    flow {
      entry -> set_new
      set_new -> store
      store -> chk
      chk.then -> log_dead
      chk.else -> ret_alive
      log_dead -> ret_dead
    }

    node entry = Entry()
    node set_new = SetLocal new_hp(
      .value <- Sub::<i32>(
        .a <- GetField Player.health(
          .obj <- entry.self,
        ),
        .b <- entry.amount,
      ),
    )
    node hp = GetLocal new_hp()
    node store = SetField Player.health(
      .obj <- entry.self,
      .value <- hp,
    )
    node chk = Branch(
      .cond <- Le::<i32>(
        .a <- hp,
        .b <- 0,
      ),
    )
    node log_dead = Call host.Log(
      .message <- "Player died",
    )
    node ret_dead = Return(
      .died <- true,
    )
    node ret_alive = Return(
      .died <- false,
    )

    layout {
      chk at (800, 0)
      chk.cond at (640, 120)
      entry at (0, 0)
      hp at (480, 120)
      log_dead at (960, -40) [label = "Log death"]
      ret_alive at (960, 60)
      ret_dead at (1120, -40)
      #[note("Store the new health once: pure nodes are re-evaluated per consumer (section 4.3).")]
      set_new at (160, 0)
      set_new.value at (320, 120)
      set_new.value.a at (160, 120)
      store at (480, 0)
      box death "Death handling" at (940, -90) size (330, 120) [color = "#C0392B", members = [log_dead, ret_dead]]
    }
  }

  event Respawn() {
    flow {
      entry -> wait
      wait -> reset
    }

    node entry = Entry()
    node wait = Delay(
      .seconds <- 2.0,
    )
    node reset = SetField Player.health(
      .obj <- entry.self,
      .value <- 100,
    )
  }
}

macro DoOnce(in: exec, reset: exec) -> (out: exec) {
  state fired: bool

  flow {
    entry.in -> check
    entry.reset -> clear
    check.else -> mark
    mark -> fire
  }

  node entry = Entry()
  node check = Branch(
    .cond <- GetState fired(),
  )
  node mark = SetState fired(
    .value <- true,
  )
  node fire = Exit out()
  node clear = SetState fired(
    .value <- false,
  )
}

macro ForRange(in: exec, first: i32, last: i32) -> (each: exec, done: exec, index: i32) {
  local i: i32

  flow {
    entry -> init
    init -> test
    test.then -> seq
    test.else -> finish
    seq.then0 -> each_out
    seq.then1 -> bump
    bump -> test
  }

  node entry = Entry()
  node init = SetLocal i(
    .value <- entry.first,
  )
  node cur = GetLocal i()
  node test = Branch(
    .cond <- Le::<i32>(
      .a <- cur,
      .b <- entry.last,
    ),
  )
  node seq = Sequence() @count(2)
  node each_out = Exit each(
    .index <- cur,
  )
  node bump = SetLocal i(
    .value <- Add::<i32>(
      .a <- cur,
      .b <- 1,
    ),
  )
  node finish = Exit done()
}

#[doc("Clamps a value to the range 0 to 1.")]
#[category("Math")]
func Clamp01(v: f32) -> (result: f32) @pure = Min::<f32>(
  .a <- Max::<f32>(
    .a <- v,
    .b <- 0.0,
  ),
  .b <- 1.0,
)

func Fib(n: i32) -> (result: i32) @pure {
  flow {
    entry -> is_base
    is_base.then -> ret_n
    is_base.else -> ret_sum
  }

  node entry = Entry()
  node is_base = Branch(
    .cond <- Lt::<i32>(
      .a <- entry.n,
      .b <- 2,
    ),
  )
  node ret_n = Return(
    .result <- entry.n,
  )
  node ret_sum = Return(
    .result <- Add::<i32>(
      .a <- Call Fib(
        .n <- Sub::<i32>(
          .a <- entry.n,
          .b <- 1,
        ),
      ),
      .b <- Call Fib(
        .n <- Sub::<i32>(
          .a <- entry.n,
          .b <- 2,
        ),
      ),
    ),
  )
}

func SumTo(n: i32) -> (total: i32) {
  local acc: i32

  flow {
    entry -> loop
    loop.each -> add
    loop.done -> ret
  }

  node entry = Entry()
  node loop = Macro ForRange(
    .first <- 1,
    .last <- entry.n,
  )
  node add = SetLocal acc(
    .value <- Add::<i32>(
      .a <- GetLocal acc(),
      .b <- loop.index,
    ),
  )
  node ret = Return(
    .total <- GetLocal acc(),
  )
}
```

Things to notice:

- Each graph opens with its `flow` block, so it reads as the order in which it runs, then the nodes that run.
- Most data nodes are written inline, where their value is used, and an inline node's one output is not named: `GetLocal acc()` is read where `.total` needs it. `Clamp01` is a single expression, written `= value` with its parameter named bare, and `Fib` is one expression per `Return`. Only nodes with exec pins and nodes whose output feeds several inputs are declared: `hp` feeds both `store` and the comparison in `chk`, and `cur` in `ForRange` feeds three inputs.
- `TakeDamage` stores the new health in a local before using it twice. The `GetField` written inline in `set_new` is pure, so it would be re-evaluated by every impure consumer; reading `health` again after `store` would subtract the damage a second time (section 4.3).
- Node statements carry no positions, notes or exec wires. Moving `chk` edits one line of the `layout` block, and rewiring it edits lines of the `flow` block, so neither can conflict with someone changing `chk`'s bindings. Each input is its own line, so changing one literal input changes exactly one line. Inline nodes appear in the layout block under their dotted names: `chk.cond` is the `Le` written inside `chk`.
- `@capability`, `@pure` and `@count(2)` end the line they modify and change what is compiled. `#[doc]` and `#[category]` sit on their own lines above `Clamp01`, and the `#[note]` on `set_new` above its line in the layout block; deleting all of them changes neither the semantic hash nor the bytecode.
- Nodes with several exec outputs name the one each wire leaves from: `chk.then`, `loop.each`, `seq.then0`. `DoOnce`'s macro `Entry` has two exec parameters, so its wires start at `entry.in` and `entry.reset`.
- `Respawn` is an `event`, which is implicitly latent, so it may contain `Delay`. `TakeDamage` has no latent nodes and is not latent, so a host can call it with `wr_call` and rely on getting a result (section 4.5).
- `add` has no wire in the flow block. A chain that ends returns control to whatever pushed it, here the macro (section 4.2), which is what makes the loop continue.
- `loop.index` is a data output of a macro node, readable by any node downstream of `loop`.
- `DoOnce` keeps its flag in a `state` slot. Each expansion of the macro gets its own slot, so two `DoOnce` nodes in one graph do not interfere.
