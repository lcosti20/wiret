## 2. Text syntax

### 2.1 Files and lexical structure

A `.wiret` file is UTF-8 (no BOM) with LF line endings and holds exactly one module. Statements end at a newline. Inside `( )`, `{ }` and `[ ]` a newline separates items the way a comma does, so a list written one item per line needs no commas, and a list on one line separates its items with commas (section 2.3). A trailing comma is allowed and never written by the formatter.

`//` starts a line comment. A run of comment lines that stands directly above a declaration, a member of a `struct`, `enum`, `interface` or `class`, a `local` or `state` statement, a `node`, `exec`, `goto` or `box` statement or an input binding, with no blank line between, is **attached** to it, as are comment lines among its decorator lines:

```
// Applies damage and reports whether the player died.
func TakeDamage(self, amount: i32) -> (died: bool) {
  // health is stored first, so the check reads the new value
  exec SetLocal new_hp(
```

An attached comment is part of the model. The formatter and every editor write it back above its element, at the element's indentation and above any decorator lines, a merge carries it like any other field of its element (section 7.1), and it moves with its element. Like metadata it is outside the semantic hash and inside the layout hash (section 2.5). The text after `//` is kept as written, except that one space after `//` is the canonical separator. A node that carries a comment is never written inline in an input (section 2.3), so its comment has a line of its own to stand above.

A comment that is attached to nothing (one that ends a line of code, or is followed by a blank line or a closing `}`) is *trivia*, and the canonical writer cannot keep it. It never drops one silently: `wiretc fmt` reports `W0603` for each comment it would lose and exits non-zero, unless told what to do with them: `--convert-comments` turns each comment into an `@note("...")` on the node on its line, or else the next node or declaration (section 2.4), so the text stays with what it was written beside, and `--drop-comments` discards them. An editor that opens a file containing such comments offers the same choice.

Comments are for whoever reads the text. Explanations that the graph editor shows are written as an `@note` (an explanation of a graph, node or box), an `@doc` (the short tooltip text of a declaration or node), or a `box` (a frame drawn around a group of nodes).

| Token | Form |
| --- | --- |
| Identifier | `[A-Za-z_][A-Za-z0-9_]*` |
| Qualified name | `std.math.Sqrt` |
| Pin reference | `name.pin`, `name` alone for a named node's one output, or a bare name bound by a block or a parameter (section 2.3) |
| Comment | `// text`, to the end of the line; kept when it stands directly above what it explains (see above) |
| Generic arguments | `#<i32>`, `#<i32, string>`; a node's named generic arguments `#count<3>`, `#cases<2>` |
| Arrows | `->` (an exec output's block, results), `<-` (input binding) |
| Attribute block | `{pos=(0, 0), label="Start"}` after a node's kind, or after `box` |
| Integer | `42`, `-7`, `0xFF`, `1_000`; optional suffix `i8 u8 i16 u16 i32 u32 i64 u64` |
| Float | `1.5`, `2e-3`; optional suffix `f32` or `f64` |
| Other literals | `true`, `false`, `null` |
| Enum value | `Mode::Chase`: the enum's name, `::` and one of its members (section 2.3) |
| String | `"text"` with escapes `\\n`, `\\t`, `\\"`, `\\\\` and `\\u{1F600}` |
| Tuple / list / map | `(1, 2)`, `[a, b]`, `{k: v}`; used inside decorator arguments and attribute blocks, except that a tuple of numbers is also the literal of a vector type, `(0, 1, 0)` (section 3.1.1) |
| Decorator | `@pure`, `@note("text")`, `@id("p1")`; on the line above what it describes, or before a parameter, field or enum member on its line (section 2.4) |
| Disabled statement | `!exec ...`, `!{ ... }`, `!Kind(...)`: code that nothing reaches (section 2.3) |

A literal takes the type of the pin it is bound to, so suffixes are only needed where a literal is used without a pin (decorator arguments). The keywords are `wiret module use extern const var local enum struct interface class impl macro func event dispatcher node state exec goto box self`. They are **contextual**: each is a keyword only where a statement of its kind can start, so any of them may name a node, field, parameter, local, pin, type or declaration. A word next to a `.`, followed by `(`, `=` or a single `:`, or not first on its line is always a name, which covers every pin, field, parameter and local (`.box <- 1`, `state: i32`, `exec box`, `goto node`); inside a class `func: i32` is a field and `func F()` a method. Only `true`, `false` and `null` are reserved, since they are values wherever a value can stand, and `self`, which names the receiver of a method.

### 2.2 Module header and declarations

Every file starts with a version line and a module line:

```
wiret 1
@id("mod_k3f9")
module game.demo
```

The module name is the namespace prefix of everything declared in the file (`game.demo.Player`). The grammar below uses `NL` for a newline, `decos` for zero or more decorator lines above a statement, and `inline` for zero or more decorators before an element on its own line (section 2.4). `//` comment lines (section 2.1) may stand above any statement and are left out of the productions to keep them readable.

```
file       = "wiret" INT NL decos "module" qname NL { decos item } ;
item       = use | extern | const | var | enum | struct | interface
           | class | macro | func | event ;
use        = "use" qname [ "as" IDENT ] NL ;
extern     = "extern" ( "func" qname params [ results ] | "type" qname ) NL ;
const      = "const" IDENT ":" type "=" literal NL ;
var        = "var" IDENT ":" type [ "=" literal ] NL ;
enum       = "enum" IDENT [ ":" inttype ] "{" { decos inline IDENT [ "=" INT ] NL } "}" ;
struct     = "struct" IDENT "{" { decos field } "}" ;
field      = inline IDENT ":" type [ "=" literal ] NL ;
interface  = "interface" IDENT "{" { decos "func" IDENT mparams [ results ] NL } "}" ;
class      = "class" IDENT [ ":" qname ] [ "impl" qname { "," qname } ]
             "{" { decos ( field | dispatcher | method ) } "}" ;
dispatcher = "dispatcher" IDENT params NL ;
method     = ( "func" | "event" ) IDENT mparams [ results ] "{" body "}" ;
func       = "func" IDENT [ tparams ] params [ results ] ( "{" body "}" | "=" value NL ) ;
event      = "event" IDENT params "{" body "}" ;
macro      = "macro" IDENT [ tparams ] params [ results ] "{" body "}" ;
params     = "(" [ param { sep param } ] ")" ;
mparams    = "(" [ ( "self" | param ) { sep param } ] ")" ;  (* `self` first: an instance method *)
results    = "->" params ;                     (* results are always named; `-> ()` is none *)
param      = inline IDENT ":" type [ "=" literal ] ;
sep        = "," | NL ;
tparams    = "#" "<" IDENT { "," IDENT } ">" ;
type       = prim | qname | "exec"
           | "array" "#" "<" type ">" | "set" "#" "<" type ">"
           | "map" "#" "<" type "," type ">"
           | "delegate" "#" "<" tlist [ "->" tlist ] ">" | "dispatcher" "#" "<" tlist ">" ;
tlist      = "(" [ type { "," type } ] ")" ;
prim       = "bool" | "i8" | "u8" | "i16" | "u16" | "i32" | "u32"
           | "i64" | "u64" | "f32" | "f64" | "string"
           | "vec2" | "vec3" | "quat" | "transform" ;
```

Notes on the declarations:

- `struct` is a **value type**: immutable, copied by value, compared by field. `class` is a **reference type**: single inheritance, any number of `interface`s, fields default to the value written in the declaration. An `extern type` is an opaque host object (section 6.6).
- A function declared inside a class is a method. A method whose parameter list starts with `self` is an **instance method**: it is called on an object, which its graph reads as `self`. A method without `self` is a **static method**: it belongs to the class's namespace and is called without an object, like a free function. Instance methods are virtual unless marked `@final`; static methods are never virtual. A method's qualified name is `Class.Method` (`Player.TakeDamage`), which is how `Call`, diagnostics and the export table name it. `Call Boss.TakeDamage` finds the nearest declaration along `Boss`'s base classes.
- **`self` fills itself in.** A call to an instance method takes the object as its `self` input. Inside an instance method, a `Call` to an instance method of the same class, of a base class, or of an interface the class implements may leave `self` out, and it takes the calling method's own `self`, the way a Blueprint function's Target pin defaults to Self. The formatter leaves such a binding out. Writing `.self <- other` calls the method on another object.
- **Parameter defaults.** A parameter may declare a default, `by: i32 = 1`. A call that leaves that input unbound passes the default (section 2.3, rule 5), and a binding equal to the default is left out by the formatter. A default is a literal of the parameter's type (`E0110` otherwise).
- An override (an instance method with the name of one in a base class) takes the same parameters and results and has the same latency, and a `@final` method has none (`E0150`). A class extends a class of the same module, and the chain may not loop (`E0151`). A field name is declared once along the chain (`E0102`).
- A class implements each interface named after `impl` with an instance method of the same name, parameters and results, its own or inherited from a base class, and it also implements its base classes' interfaces (`E0152` otherwise; an `impl` name that is not an interface is `E0151`). Interface methods always take `self` (a parse error says so when it is missing) and are called with `Call Damageable.Hit`, whose `self` input is of the interface type.
- **Provisional.** Interface methods are not latent in version 1: the `5A` type entry records only function types, so a caller could not know that `call_interface` might suspend. An implementation is therefore never `@latent`, and the verifier checks it.
- An `event` is a function with no results that the host or other graphs can invoke by name, and that may contain latent nodes (section 4.5). A `dispatcher` is a multicast event slot on a class, like a Blueprint Event Dispatcher.
- A `macro` is inlined at every use, so it may contain `exec` pins as parameters and results. Everything else exposes `exec` pins implicitly.
- `extern func host.Log(message: string)` imports a host native. The import module is every segment but the last (`host`), the import name is the last (`Log`). A function with no results may say so, `-> ()`, or leave the arrow out, like leaving out `void`; the formatter keeps whichever is written.
- `exec` is a type only for macro parameters and for the generic argument of `Reroute`.
- `vec2`, `vec3`, `quat` and `transform` are built-in struct types (section 3.1.1). Their literals are tuples, nested for a transform: `const Up: vec3 = (0, 1, 0)`, `.offset <- (0, 0.5, 0)`, `spawn: transform = ((0, 2, 0), (0, 0, 0, 1), (1, 1, 1))`. The formatter writes each component as it writes an `f32` literal.
- An enum member without `= INT` is one more than the member before it, and the first member is 0. Every value must fit the underlying type, `i32` unless one is written (`E0110`).
- Struct fields and enum members keep the order they are written in (section 2.5). Field names, and member names, are unique within their declaration (`E0102`), and a struct or enum may not take the name of a built-in type (`E0102`).
- A struct may not hold itself by value, directly or through other structs (`E0503`): it would have no finite default value. Holding it in an array is allowed, since an array starts empty, so `struct Tree` may have a field `children: array#<Tree>`.

### 2.3 Graph bodies: exec statements, nodes and bindings

The body of a `func`, `event`, `macro` or method is written in the order it runs. It is a list of `local` and `state` declarations, then `box` statements, then `node` statements that name nodes, then the **exec statements**, which start at the graph's `Entry` node and follow its exec wires, then any **disabled statements** for code that nothing reaches. The formatter writes these groups in that order, each after a blank line.

```
body      = { decos ( local | state ) } { decos box } { decos named }
            { decos stmt } { decos disabled } ;
local     = "local" IDENT ":" type [ "=" literal ] NL ;
state     = "state" IDENT ":" type [ "=" literal ] NL ;
box       = "box" attrs NL ;
named     = "node" IDENT "=" expr NL ;
stmt      = exec | goto ;
exec      = "exec" ( expr | IDENT ) { out } NL ;
out       = "." IDENT [ "[" INT "]" ] [ input ] [ "|" IDENT { "," IDENT } "|" ] "->" "{" { decos stmt } "}"
          | "." IDENT [ "[" INT "]" ] [ input ] ;            (* only last: continue in this block *)
                                             (* input: the output's value, `.case[0] Mode::Idle` *)
goto      = "goto" IDENT [ "." IDENT ] NL ;
disabled  = "!" ( "exec" ( expr | IDENT ) { out } | "{" { decos stmt } "}" | expr ) NL ;
expr      = KIND [ symbol | STRING ] [ targs ] { named_gen } [ attrs ]
            "(" [ binding { sep binding } ] ")" ;
targs     = "#" "<" type { "," type } ">" ;
named_gen = "#" IDENT "<" [ value { "," value } ] ">" ;  (* #count<3>, #cases<2> *)
attrs     = "{" [ IDENT "=" value { "," IDENT "=" value } ] "}" ;
binding   = decos "." IDENT "<-" input ;
input     = expr [ "." IDENT ] | ref | literal ;  (* expr: a node written inline *)
ref       = IDENT [ "." IDENT ] ;
```

#### Exec statements

An `exec` statement places a node on the path that control follows. Each `exec` statement runs after the one before it in its block: the previous node's one exec output is wired to this node's exec input. The first statement of a body is the `Entry` node, which nothing runs before:

```
func Main() {
  exec Entry{pos=(0, 0)}()
  exec Call host.Log{pos=(220, 0)}(
    .message <- "Hello!"
  )
  exec Call host.Log{pos=(489, 0)}(
    .message <- "Programs run one step at a time."
  )
}
```

A node with **several exec outputs** (`Branch`, `Switch`, `Sequence`, `Try`, a loop macro) writes each output that is wired as a block after it, in the order of its pins, `.then -> { ... }`. The statements in a block run when control leaves the node through that output, and a block may itself hold nodes with blocks. An exec output that is not written is not wired, which means "this chain ends here" (section 4.2):

```
exec Branch(
  .cond <- is_adult
).then -> {
  exec Call host.Log(
    .message <- "an adult"
  )
}.else -> {
  exec Call host.Log(
    .message <- "a child"
  )
}
```

- **Flattening.** The last output may be written `.pin` alone, without a block. Then the statements that follow in the enclosing block are that output's block: they continue from it. `Try`'s `.then`, which runs after the body or the fault, and `Sequence`'s last output read most naturally this way, and so does an `if` without an `else` (`}.else` followed by the rest of the function). Flattening is notation only: the graph is the same either way, and the formatter keeps the form that is written. A node created by an editor flattens its last output when it is a `Try` or a `Sequence`.
- **Output names.** An output's block may bind names between bars, `.each|index, item| -> { ... }`. A name is one of the node's data outputs, read in the block as a bare name (`.b <- index`), or one of its other exec inputs, run with `goto` (`.each|index, break| -> { ... goto break }`). Names are matched by pin name, not position, so `.each|item|` binds only `item`; the bars, unlike parentheses, do not read as a call's arguments. A name is in scope in its block and in the blocks inside it, and an inner block's name hides an outer one's. A named node may bind names too, as a shorthand for `name.pin`. A flattened output binds no names. The parenthesised form of earlier drafts, `.each(index) -> {`, is a syntax error that shows the bars.
- **Indexed outputs.** A node with a variable number of exec outputs, counted by a named generic argument (`Sequence#count<n>`, `Switch#cases<n>`), names them with an index in brackets: `.then[0]`, `.case[1]`. The brackets mark them as one list, the outputs a graph editor adds and removes, and the outputs after them (a `Switch`'s `default`) are set apart: the canvas draws a line above them. An index is a plain number. Writing `.case1` is `E0103`, with a message that shows `.case[1]`.
- **Output values.** Some exec outputs take a value: a `Switch`'s `case[0]`, `case[1]`, ... (section 3.3). The value is written after the output's name and before its names or `->`, `.case[0] Mode::Idle -> { ... }`, and is the node's data input of the same name: a literal, an enum value, a name, `name.pin` or a node written inline, as on the right of `.pin <- value`. It is read in the enclosing block's scope. An output that takes a value is written even when nothing is wired to it, with an empty block, `.case[1] Mode::Chase -> {}`, so its value is kept; an empty block is never flattened. Writing a value on an output that takes none is `E0103`.
- A node whose output must be read anywhere else (after its blocks, or from a grandparent's block) is named, and its outputs are read as `name.pin` (see *Named nodes*).

#### Named nodes

A node is **anonymous** unless it is named. An anonymous node has one place in the text: inline, in the one input that reads its output, or as one `exec` statement, where control first reaches it. A node needs a name when it is used from more than one place: its output is read by more than one input, or read from somewhere its block's names do not reach, or its exec input is entered by more than one wire. A named node is declared at the top of the body, `node name = Kind(...)`, and

- its output is read by name, `name` alone when it has one data output, else `name.pin`;
- if it has exec pins, it is placed with `exec name`, once, where it runs, and its outputs' blocks follow that statement (`exec name.then -> { ... }`). Every node has at most one exec point; writing `exec name` twice is a syntax error that suggests `goto`;
- every other wire into its exec input is a `goto name` statement, which ends its block: control jumps to the named node and continues from there. A loop is a `goto` back to a node placed earlier, and a merge is a `goto` to a node placed later. `goto name.pin` enters the node at another of its exec inputs (a loop macro's `break`).

```
func SayHiTenTimes() {
  local count: i32 = 0

  node say_hi = Call host.Log(
    .message <- "Hi!"
  )

  exec Entry()
  exec say_hi
  exec SetLocal count(
    .value <- Add#<i32>(
      .a <- GetLocal count()
      .b <- 1
    )
  )
  exec Branch(
    .cond <- Ge#<i32>(
      .a <- GetLocal count()
      .b <- 10
    )
  ).then -> {
    exec Return()
  }.else
  goto say_hi
}
```

Named nodes are listed in the order they were named: naming a node in an editor adds it after the names already there. When the formatter has to name a node itself (an edit made an anonymous node's output feed a second input, or wired a second exec wire into it), it names it after its symbol or kind in snake case (`concat`, `log`, `convert`), adding `_2`, `_3`, ... when that name is taken or, in a project, retired for the graph in `wiret.ids` (section 7.3), and adds it after the others. A name is never taken back: a node keeps its name when it comes to be used from one place again.

#### Inline nodes

An input has exactly one source, so read backwards from the inputs the data wires of a graph form a tree, and only a shared output breaks it. The text uses this: a node without exec pins whose output feeds a single input is written inside that input:

```
exec Call host.Log(
  .message <- Call std.string.Concat(
    .a <- "Your score is "
    .b <- Convert#<i32, string>(
      .value <- GetLocal score()
    )
  )
)
```

- **Which output.** A node with one data output feeds that output in, so nothing more is written. That holds for an inline node (`GetLocal score()`) and for a named node (`.value <- hp`, not `hp.value`). A node with several outputs names the one it feeds in: `.len <- BreakStruct Vec2(...).x`, `.x <- parts.x`; leaving it out is a syntax error that lists the outputs. The reader also accepts the one output written out (`GetLocal score().value`, `hp.value`), and the formatter leaves it out, except for a macro node, whose outputs are results and are always named. A bare name that is no name of the graph, no name bound by an enclosing block and no parameter is kept as written and reported as `E0101`, so deleting a node never makes the file unreadable.
- **Parameters** are read by their bare name (`.b <- amount`, `.obj <- self`). A named node may not take a parameter's name.
- **Which nodes are inline.** In canonical form a node is written inline exactly when one input in the graph reads it, it has no exec pins (it is pure or `reads`), it is not named and it carries no `//` comment. Its decorators (`@note`, `@live`) stand on their own lines above the `.pin <-` line of the input it is written in.
- **Notation only.** Writing a node inline changes nothing about when or how often it is evaluated (section 4.3): the model has the same nodes and wires, and the compiled instructions are the same.

#### Node identity: names and execution positions

A named node's id is its name. An anonymous node has no name in the text, so tools identify it by **what it is and where it is**: its identifier (the node's kind and symbol, such as `Call host.Log`) and its **execution position**.

- Each `exec` statement of a body has an index, starting at `0` for `Entry`. Inside an output's block the position continues with the output's name and a new index from `0`: the first statement in the `.body` block of the node at `1` is `1.body.0`. A block under a named node starts from its name: `test.then.0`.
- A flattened output's statements continue the enclosing block's numbering, since they are written there.
- A node written inline takes its consumer's position and the input it feeds: `1.fault.0.message` is the node in the `.message` input of `1.fault.0`.
- A disabled statement (below) is numbered `~0`, `~1`, ... in order, and the statements inside a `!{ }` block continue it (`~1.0`, `~1.1`).

```
func Main() {
  exec Entry()                               // 0
  exec Try().body -> {                       // 1
    exec Call CheckAge(                      // 1.body.0
      .age <- -3
    )
  }.fault|message| -> {
    exec Call host.Log(                      // 1.fault.0
      .message <- Call std.string.Concat(    // 1.fault.0.message
        .a <- "Oops: "
        .b <- message
      )
    )
  }.then
  exec Call host.Log(                        // 2
    .message <- "Still running!"
  )
}
```

Diagnostics, the debugger, the canvas, `wiretc edit` requests and the merge use these ids (`Main.1.fault.0`). A position says where a node is written, not which node it is, so it changes when the node moves: it is never retired in `wiret.ids` and never `E0140` (section 7.3), and a merge matches anonymous nodes by identifier and position (section 7.1).

#### Disabled statements

Code that nothing reaches is kept, after a `!`, at the end of the body. It must be valid syntax so the editor can draw it, grayed out. It is part of the graph (it is checked, and `W0301` reports it), but it never runs.

```
@note("This node is declared but its exec input is not wired.")
!exec Call host.Log{pos=(220, 0)}(
  .message <- "Hello!"
)

!{
  @note("These are wired to each other, but not to Entry, so they never run.")
  exec Call host.Log{pos=(220, 100)}(
    .message <- "Hello!"
  )
  exec Call host.Log{pos=(489, 100)}(
    .message <- "Programs run one step at a time."
  )
}

!Add#<i32>{pos=(300, 300)}()
```

- `!exec` holds one node with exec pins that nothing runs, such as a node just added in an editor; its outputs' blocks may follow it.
- `!{ ... }` holds a chain of exec statements that are wired to each other but not reached from `Entry`.
- `!Kind(...)` holds a node without exec pins that nothing reads.

`!` is not `@disabled`. A `@disabled` node is on the path and is skipped when control reaches it (section 2.4); a `!` statement is not on the path at all.

#### Attribute blocks

How a node is drawn is written in its **attribute block**, `{key=value, ...}`, after its identifier (kind, symbol and generic arguments) and before its inputs: `Call host.Log{pos=(420, 0), label="Say hello"}(...)`. It is for display only, may be left out, and never affects the semantic hash.

- `pos=(x, y)` is the node's position; coordinates are integers, so there is no floating-point noise in diffs. A node with an attribute block always has a `pos`. Other keys are `label`, `color`, `size`, `collapsed` and `hidden` (a list of pin names). Unknown keys, including a third party's dotted ones (`x.acme.pin=[a, b]`), are preserved.
- A node without an attribute block is auto-placed by the editor, and gets one when first saved. This makes LLM-generated graphs valid without layout.
- A named node's attribute block is on its `node` line; `exec name` takes none.

A **box** is a frame drawn behind nodes, `box {title="...", pos=(x, y), size=(w, h), color="#2E86C1"}`, at the top of the body, with its `@note` lines above it. A box has no name and no list of members: nodes are not attached to it. Moving a box in an editor moves the nodes whose positions lie inside it, as a Blueprint comment box does, and those moves are ordinary position changes. Boxes are written in the order they were made, and tools refer to one by its index among them.

Personal view state (zoom, scroll, selection, open panels) is never written to the file (section 7.5).

#### Rules

1. **Kind** is a PascalCase built-in (`Add`, `Branch`, `SetLocal`, ...; section 3.3). Calling a declared function is always `Call`, so the closed set of built-in kinds never collides with user names.
2. **Symbol** (optional) names the thing the node acts on: `Call std.math.Sqrt`, `GetField Player.health`, `SetLocal acc`, `GetState done`, `New Player`, `Cast Player`, `Macro ForRange`, `Exit done`, and for `Format` its template, a string: `Format "Total: {total}"` (section 3.3). A struct node names its struct, and a field node the struct and the field: `MakeStruct Vec2`, `GetField Vec2.x`. A member of a class (a field, a dispatcher, or a field that a container node changes) is always written with its class: `GetField Player.health`, `Broadcast Player.OnHit`, `ArrayAdd#<i32> Player.items`. Inside a method the reader also accepts a member of the method's own class by its bare name, `GetField health`, and the formatter writes it qualified with that class.
3. **Generic arguments** follow the symbol: `Add#<i32>`, `Convert#<i32, string>`, `Call std.array.Get#<f32>`, and come before the symbol of a container node: `ArrayAdd#<i32> scores`. They are always written out, never inferred. Every generic argument list in Wiret, on a node, a declaration (`macro ForEach#<T>`) or a type (`array#<i32>`), is introduced by `#`; a bare `<` would read like a comparison. A node's **named generic arguments**, which change its pins, follow its type arguments: `Sequence#count<3>()`, `MakeArray#<i32>#count<4>(...)`, `Switch#<Mode>#cases<2>(...)`. They are written with `#` so they are never confused with decorators. `#cases` counts a `Switch`'s cases; each case's value follows its output, `.case[0] Mode::Idle -> { ... }` (output values, above). Listing the values in `#cases`, as earlier drafts did, is `E0502` with a message that shows the new form.
4. **Bindings** connect input pins: `.pin <- value`, one per line, or separated by commas on one line: `Call host.Log(.message <- "hi")`. The canonical form puts each binding on its own line, indented one level further than the node, without commas (section 2.5). A node with no bound inputs is written with empty parentheses, `Entry()`, so every node reads the same way. `<-` mirrors the `->` of an output's block: data flows *into* the pin. An enum value is written `Mode::Chase`, which never reads like a pin reference. An input that is not listed takes the pin's default value (the declared default, otherwise the zero value of its type); the compiler warns (`W0201`) about unlisted inputs that have no declared default.
5. **Exec inputs.** A wire enters a node at its first exec input, `in` for most nodes and a macro's first exec parameter. `goto name.pin` enters another one.
6. **Data wires** may fan out freely: any number of inputs may read the same output of a named node.
7. **`state`** declares a slot that keeps its value between executions of the graph. In a macro there is one slot per expansion site, which is what `DoOnce` and `FlipFlop` need. In a method it lives on the object, in a free function on the module instance. On an object, each class's state slots follow its fields and dispatchers: for each method by name, its own `state` by name, then that of each macro it expands, node by node. The compiler allocates hidden fields or globals for it, named after the expansion path. Read and write it with `GetState` and `SetState`.
8. `Reroute#<T>` is a visual-only node that passes a wire through a bend point. It is erased by the compiler. `Reroute#<exec>` reroutes control flow.
9. A macro's `Entry` has one exec output per exec parameter. With one, it continues like any node; with several, each is a block, `exec Entry().in -> { ... }.reset -> { ... }`.

#### Expression bodies

A `func` outside a class with exactly one result may be written `= value` instead of a body in braces:

```
@pure
func Clamp01(v: f32) -> (result: f32) = Min#<f32>(
  .a <- Max#<f32>(
    .a <- v
    .b <- 0.0
  )
  .b <- 1.0
)
```

- It is notation for `exec Entry()` followed by `exec Return(.result <- value)`: the model, the compiled code and the semantic hash are those of that graph, and the inline nodes are numbered under the `Return` (`1.result`, `1.result.a`).
- The canonical form uses it exactly when a function's graph has that shape and nothing else to keep: no locals, states, boxes, names or attribute blocks, and no decorator or comment on the two nodes. Once an editor places the nodes the function is written with braces.
- A function with several results, a method, an event and a macro always have a body in braces (a syntax error says so).

### 2.4 Decorators

A **decorator** is written `@name` or `@name(args)`. It stands on its own line directly above what it describes, at the same indentation, or, for a parameter, result, field or enum member, before it on its line (`@id("p1") amount: i32`). There are two kinds:

- A **semantic decorator** (`@pure`, `@id("...")`, `@capability("...")`, `@disabled`) is part of the program. Only the names in the first table below exist. It is covered by the semantic hash.
- A **metadata decorator** (`@doc("...")`, `@note("...")`) is information *about* the program and never changes compiled output. It is outside the semantic hash and inside the layout hash (section 2.5).

```
deco  = "@" mname [ "(" [ arg { "," arg } ] ")" ] ;
mname = IDENT { "." IDENT } ;
arg   = [ IDENT ":" ] value ;
value = literal | IDENT | tuple | list | map ;
```

```
@doc("Clamps a value to the range 0 to 1.")
@category("Math")
@pure
func Clamp01(v: f32) -> (result: f32) = ...
```

Decorator lines may stand above the module line, any item, any member of an `enum`, `struct`, `interface` or `class`, any `local`, `state`, `box`, `node`, `exec` or disabled statement, and any input binding, where they describe the node written in that input. A decorator line followed by a blank line, a closing `}` or the end of the file is a syntax error, so a decorator can never float free in the text. A decorator after what it describes, as in `func F() @pure`, is a syntax error that says where it goes.

**Semantic decorators** may change compiled output. Only the names in this table, and the metadata names below, exist without a dot: any other undotted name is `E0104`.

| Decorator | Applies to | Meaning |
| --- | --- | --- |
| `@id("...")` | any declaration, module, parameter, result, field, enum member, local | Stable identity that survives rename and move. Editors always write it in a project (`W0202` where it is missing); hand-written and LLM-written code may omit it and gets one on the first editor save or `wiretc fmt --assign-ids`. See the identity rules below. |
| `@pure` | `func` | Effect-free, deterministic and cacheable (section 4.3): the result depends only on the explicit arguments and on `const`s. Callers treat a call as a pure node (no exec pins, evaluated on demand). The graph inside is an ordinary exec graph and may branch, loop and recurse; it may use its own locals, but may not write variables, fields or state (`E0302`), read variables, fields or state, dereference a class reference or host handle, or call anything that is not `@pure` (`E0304`), and may not contain a latent node (`E0302`). |
| `@reads` | `func` | Effect-free and deterministic for a given VM state, but not cacheable: may read variables, fields, state and objects, but not write them. A call is a pure node that is re-evaluated at each consumer (section 4.3), like `GetField`. May call only `@reads` and `@pure` functions (`E0302`) and may not contain a latent node. |
| `@final` | instance method | Not virtual. Calls are bound at compile time. |
| `@private` | declaration | Not visible outside the module. |
| `@export` | `func`, `event`, `var`, type | Listed in the module's export table for the host and other modules. A normal build exports only what carries `@export`; an `--export-all` build (editor run and debug sessions) also exports every `func`, `event` and method, and marks the `@export` ones as declared (section 5.2). |
| `@inline` | `func` | Hint to inline at call sites. |
| `@deprecated("msg")` | declaration | Warning at every use. |
| `@live` | node without exec pins | The node is meant to be read again at each consumer, so each sees the current value (section 4.3). It excuses `E0320` for the reads behind it. |
| `@disabled` | node | Node is skipped: a one-exec-out node passes control straight to its target; data outputs read as zero. Unlike a `!` statement (section 2.3), the node stays on the path. |
| `@capability("name")` | `extern func` | The import needs this host capability. Listed in the `wr.caps` section; the load fails unless the host granted it (section 6.5). |
| `@latent` | `func` | The function may suspend. Required when it contains a latent node or calls a latent function or event (`E0201`). Events are implicitly latent. A latent function is never `@pure` or `@reads`. |

The node parameters of earlier drafts, `@count(n)` and `@cases(...)`, are named generic arguments now, `#count<n>` and `#cases<n>` (section 2.3, rule 3); a decorator with either name is a syntax error that shows the new form.

**Metadata decorators** never change bytecode. They are stored and diffed, and they are covered by the layout hash but not the semantic hash (section 2.5). Node positions, labels, colours and sizes are not decorators; they live in the node's attribute block (section 2.3).

| Decorator | Applies to | Meaning |
| --- | --- | --- |
| `@doc("text")` | any declaration or node | Short tooltip and reflection text, for whoever *uses* the declaration or node: one sentence, shown in the palette and on hover, and copied to `wr.reflect` (section 5.4). |
| `@category("Math")`, `@keywords("a", "b")` | `func`, `macro` | Palette organisation. |
| `@note("text")` | any declaration, node or `box` | Explanatory prose for whoever *maintains* the graph: rationale, warnings, region-level explanations. A note on a `func`, `event` or `macro` explains the whole graph. See *Notes* below. |

#### Notes

```
exec Entry()
@note("Store the new health once: pure nodes are re-evaluated per consumer (section 4.3).")
exec SetLocal new_hp(
  .value <- Sub#<i32>(
    .a <- hp
    .b <- amount
  )
)
```

- A target may carry any number of notes. They keep the order they were written in.
- The text is a string and may contain `\n`. A long note is written as one long line, since line diffs of prose are no worse than for any other line.
- A note on a node written inline stands above the `.pin <-` line of the input it is written in. A note on a box stands above its `box` line.
- **Notes are never deleted as a side effect.** A tool that deletes a node or box moves its notes up to the enclosing graph and records where they came from, as in `@note("...", detached: "1.message")`. A note on a deleted declaration moves to the enclosing declaration (the class, for a method), or to the module line for a top-level item. A detached note is reported as `W0604` until someone re-homes it (moves it above another target and removes `detached`) or deletes it.

**Preservation rules.**

- Unknown metadata decorators are preserved exactly: the order of arguments and of repeated decorators is kept. A tool may not drop a decorator because it does not recognise it.
- **Unsafe decorators** (borrowed from GML): a metadata decorator whose name starts with a capital letter, for example `@Hash(...)` or `@Cached(...)`, is derived data. Any tool that modifies the graph must delete it, and tools should not write one they cannot keep correct.
- Third parties use a namespaced name such as `@x.acme.review("ok")`. Names without a dot are reserved for this specification.
- Because both kinds are written `@`, a tool tells them apart by name: the semantic names are the closed set in the first table, and every other name is metadata.

Wires refer to pins by name, so renaming a parameter or result would otherwise break every wire that mentions it. Giving parameters, results, fields, enum members and locals an `@id` lets an editor or merge tool recognise a rename as a rename (the id is unchanged, the name differs) and rewrite the references in one step.

**Identity rules.**

- **Required.** Every declaration, parameter, result, field, enum member and local that an editor writes in a project (section 7.3) carries an `@id`, generated by the editor as a short random token. A named node's id is its name; an anonymous node is identified by its identifier and execution position (section 2.3). An element without `@id` is still valid, but its identity is its name: renaming it is, for a merge, a deletion plus an addition (section 7.1), and in a project `W0202` says so. A file outside a project, such as a tutorial or a snippet, may leave `@id`s out, and editors do not add them there: without a registry nothing could check that its ids are never reused, so they would only add noise.
- **Present uniqueness.** Within a file, every `@id` is unique among its siblings of the same kind (`E0102`), and a node name is unique within its graph. This is all a file can guarantee on its own.
- **Operational non-reuse.** That an id or node name is never used again after its element is deleted is guaranteed only by the project registry `wiret.ids` (section 7.3). Editors and `wiretc edit` append retired ids to it, and CI runs `wiretc ids --check base..head` to catch a commit that deleted an element without registering it. A retired id reappearing is `E0140`.
- **Never regenerated.** Tools keep existing ids on load and save (section 7.5); they only generate ids for elements that have none.

### 2.5 Canonical form, hashes and Git

The canonical form is a function of the model alone, so two tools always write identical bytes for the same graph. The formatter (`wiretc fmt`) and every editor save produce it.

1. UTF-8 NFC, LF, two-space indentation, one trailing newline.
2. Items ordered by kind (`use`, `extern`, `const`, `var`, `enum`, `struct`, `interface`, `class`, `macro`, `func`, `event`), then by name. Inside a `struct` or `enum`, fields and members keep the order they are written in: field order is the struct's layout, and member order gives the value of a member written without `= INT`, so reordering them changes the program and its semantic hash. Inside a `class`, fields likewise keep their written order (the object layout), followed by its `dispatcher` lines in written order, then the methods: `func`s, then `event`s, each sorted by name. Inside an `interface`, methods keep their written order, since a method's position is its dispatch slot.
3. Inside a body: `local` statements by name, then `state` statements by name, then `box` statements in the order they were made, then the named nodes in the order they were named, then the exec statements from `Entry`, then the disabled statements. Each group is preceded by one blank line unless it opens the body.
4. **The exec statements** are written by walking the exec wires from `Entry`, each node's outputs in the order of its pins. A node is written where control first reaches it; a node entered by several wires is named and written at the entering wire whose statement is least deeply nested (the first such one met, never a wire that comes back from the node itself), and every other wire into it is a `goto`. A node's last output is written flattened when it was written so, and for a new `Try` or `Sequence`; it is never flattened when its block binds a name.
5. **Disabled statements**: first the chains that nothing reaches, each from a node that no other unreached node wires into, written as `!exec` for one node and `!{ }` for several; then the nodes without exec pins that nothing reads, as `!Kind(...)`.
6. A node is written `Kind symbol#<targs>#name<args>{attrs}(`, then its bindings, one per line, indented two spaces further than the node, each written `.pin <- value` in the node kind's pin order (from the registry), then `)` at the node's indentation. Bindings equal to the pin default are omitted, and so is a method call's `self` when it is the calling method's own (section 2.2); a node with no bindings left is written `Kind()`. An attribute block lists `pos` first, then `label`, `color`, `size`, `collapsed`, `hidden`, then any other key in written order, separated by `, `. A function whose graph is only an `Entry` and a `Return` is written `= value` (section 2.3, *Expression bodies*).
7. Decorators stand directly above their statement, with no blank line between, in this order: `doc`, `category`, `keywords`, then `note` lines in the order they were written, then any other metadata in the order it was written, then semantic decorators alphabetically. On a parameter, result, field or enum member, semantic decorators come before it on its line, alphabetically. A decorator moves with its statement.
8. Nothing else wraps: each binding line, each decorator line and each `goto` is a single line.
9. Numbers and strings are written in their shortest unambiguous form.
10. An attached `//` comment stands directly above its element at the element's indentation, one line per comment line, `// text` (`//` for an empty one), above the element's decorator lines. A comment attached to nothing is not representable: the formatter refuses to lose one silently (`W0603`, section 2.1).
11. **No alignment padding.** A named node is written `node <name> = <Kind> ...` with exactly one space on each side of `=`. Nothing is padded to line up with its neighbours: aligning would put the `=` of every node at the column of the longest name, so adding one long name would change every line of the graph and break the one-line-diff rule (section 1.2, principle 1). The reader accepts extra spaces and the formatter removes them. An editor may align in its own display, but never in the saved text.

Two hashes are defined over the canonical form, both SHA-256:

- **Semantic hash**: computed over the text written without attribute blocks, `box` statements, metadata decorators, `//` comments and `Reroute` nodes, with declarations sorted by name and disabled statements sorted by node kind. A metadata decorator is any `@` name outside the closed set of semantic names (section 2.4), so a tool can strip them without knowing their names. The hash is embedded in the `.wbc`, so CI can prove that a commit changed behaviour or did not. Two properties must hold and should be tested: rewriting a graph's flattened outputs as blocks, or deleting all of its attribute blocks, boxes and metadata decorators, changes neither the semantic hash nor a single byte of the instruction stream.
- **Layout hash**: computed over the entire canonical file. If two collaborators have the same layout hash, they see the identical graph.

**Merging.** The text is written in the order the graph runs, so a reviewer reads it top to bottom and `git diff` shows changes where they happen; `wiretc view --flow` (section 7) prints the same text. This trades some merge friendliness for readability. Moving a node or rewording its note still edits one line, and changing one input still edits one line, so most edits by two people merge as plain lines. But rewiring exec flow moves whole statements and blocks, and changes the execution positions of the anonymous nodes after the change, so two people rewiring the same function, or one rewiring while another edits a node further down, are more likely to conflict in a line-based merge than with the id-sorted layout of earlier drafts. The keyed merge of section 7.1 works on the parsed model rather than the text, and matches named nodes by name and anonymous nodes by identifier and position, so it resolves many of these; a node that should keep its identity through restructuring can be given a name. `wiretc diff` prints a node-aware semantic diff (added, removed and rewired nodes, with layout-only changes separate). Whether the cost is acceptable is decided by the review trial in section 9.1, not assumed here.

Guidance for LLM authors: write each function in the order it runs, starting with `exec Entry()`; write a node that feeds a single input inline in that input, without `.result` when it has one output; write each output of a branching node as a block, binding the outputs you read (`.each|index| -> { ... }`); name a node (`node name = ...`) only when its output is read from two places or it is entered from two places, and use `goto` for loops; write a one-result function that is a single expression as `= value`; build text with `Format`; always write generic arguments with `#<...>`, never rely on inference; read pin names from the registry (section 3.5) instead of guessing; omit attribute blocks; and run `wiretc check --json` and `wiretc fmt` on the output (section 7.2).

### 2.6 A complete example

This file is used again in sections 5 and 7.

```
wiret 1
@id("mod_k3f9")
module game.demo

@capability("console.write")
extern func host.Log(message: string)

class Player {
  health: i32 = 100

  func TakeDamage(self, amount: i32) -> (died: bool) {
    local new_hp: i32

    node hp = GetLocal new_hp{pos=(480, 120)}()

    exec Entry{pos=(0, 0)}()
    @note("Store the new health once: pure nodes are re-evaluated per consumer (section 4.3).")
    exec SetLocal new_hp{pos=(160, 0)}(
      .value <- Sub#<i32>{pos=(320, 120)}(
        .a <- GetField Player.health{pos=(160, 120)}(
          .obj <- self
        )
        .b <- amount
      )
    )
    exec SetField Player.health{pos=(480, 0)}(
      .obj <- self
      .value <- hp
    )
    exec Branch{pos=(800, 0)}(
      .cond <- Le#<i32>{pos=(640, 120)}(
        .a <- hp
        .b <- 0
      )
    ).then -> {
      exec Call host.Log{pos=(960, -40), label="Log death"}(
        .message <- "Player died"
      )
      exec Return{pos=(1120, -40)}(
        .died <- true
      )
    }.else
    exec Return{pos=(960, 60)}(
      .died <- false
    )
  }

  event Respawn(self) {
    exec Entry()
    exec Delay(
      .seconds <- 2.0
    )
    exec SetField Player.health(
      .obj <- self
      .value <- 100
    )
  }
}

macro DoOnce(in: exec, reset: exec) -> (out: exec) {
  state fired: bool

  exec Entry().in -> {
    exec Branch(
      .cond <- GetState fired()
    ).else
    exec SetState fired(
      .value <- true
    )
    exec Exit out()
  }.reset
  exec SetState fired(
    .value <- false
  )
}

macro ForRange(in: exec, first: i32, last: i32) -> (each: exec, done: exec, index: i32) {
  local i: i32

  node cur = GetLocal i()
  node test = Branch(
    .cond <- Le#<i32>(
      .a <- cur
      .b <- last
    )
  )

  exec Entry()
  exec SetLocal i(
    .value <- first
  )
  exec test.then -> {
    exec Sequence#count<2>().then[0] -> {
      exec Exit each(
        .index <- cur
      )
    }.then[1]
    exec SetLocal i(
      .value <- Add#<i32>(
        .a <- cur
        .b <- 1
      )
    )
    goto test
  }.else
  exec Exit done()
}

@doc("Clamps a value to the range 0 to 1.")
@category("Math")
@pure
func Clamp01(v: f32) -> (result: f32) = Min#<f32>(
  .a <- Max#<f32>(
    .a <- v
    .b <- 0.0
  )
  .b <- 1.0
)

@pure
func Fib(n: i32) -> (result: i32) {
  exec Entry()
  exec Branch(
    .cond <- Lt#<i32>(
      .a <- n
      .b <- 2
    )
  ).then -> {
    exec Return(
      .result <- n
    )
  }.else
  exec Return(
    .result <- Add#<i32>(
      .a <- Call Fib(
        .n <- Sub#<i32>(
          .a <- n
          .b <- 1
        )
      )
      .b <- Call Fib(
        .n <- Sub#<i32>(
          .a <- n
          .b <- 2
        )
      )
    )
  )
}

func SumTo(n: i32) -> (total: i32) {
  local acc: i32

  exec Entry()
  exec Macro ForRange(
    .first <- 1
    .last <- n
  ).each|index| -> {
    exec SetLocal acc(
      .value <- Add#<i32>(
        .a <- GetLocal acc()
        .b <- index
      )
    )
  }.done
  exec Return(
    .total <- GetLocal acc()
  )
}
```

Things to notice:

- Each function reads in the order it runs. `TakeDamage` stores the new health, writes it back, then branches; the `then` block logs and returns, and the flattened `}.else` continues with the last `Return`.
- Most data nodes are written inline, where their value is used, and an inline node's one output is not named: `GetLocal acc()` is read where `.total` needs it. Parameters are read by their bare names (`amount`, `n`, `self`). `Clamp01` is a single expression, written `= value`. Only `hp` in `TakeDamage`, and `cur` and `test` in `ForRange`, are named: `hp` and `cur` feed several inputs, and `test` is entered twice, once in order and once by the loop's `goto test`.
- `TakeDamage` stores the new health in a local before using it twice. The `GetField` written inline in the `SetLocal` is pure, so it would be re-evaluated by every impure consumer; reading `health` again after the `SetField` would subtract the damage a second time (section 4.3).
- Positions and labels are in each node's attribute block (`{pos=(960, -40), label="Log death"}`), which never changes the semantic hash. Moving a node edits only that part of its line. Each input is its own line, so changing one literal input changes exactly one line.
- `@capability` and `@pure` are semantic decorators and change what is compiled. `@doc` and `@category` above `Clamp01`, and the `@note` above the `SetLocal`, are metadata; deleting all of them changes neither the semantic hash nor the bytecode. `@id` on the module line is the module's stable identity.
- `Sequence#count<2>` has two exec outputs, written as a `.then[0]` block and a flattened `.then[1]`. `DoOnce`'s macro `Entry` has two exec parameters, so it writes an `.in` block and a flattened `.reset`.
- `SumTo`'s loop body binds the loop's `index` output, `.each|index| -> { ... }`, and reads it by name. The `SetLocal` in it has no exec output wired: a chain that ends returns control to whatever pushed it, here the macro (section 4.2), which is what makes the loop continue.
- `Respawn` is an `event`, which is implicitly latent, so it may contain `Delay`. `TakeDamage` has no latent nodes and is not latent, so a host can call it with `wr_call` and rely on getting a result (section 4.5). Both are instance methods and take `self`.
- `DoOnce` keeps its flag in a `state` slot. Each expansion of the macro gets its own slot, so two `DoOnce` nodes in one graph do not interfere.
