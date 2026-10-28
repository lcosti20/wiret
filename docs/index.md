# Introduction

Wiret is a **visual scripting language whose source of truth is text**. A Wiret program is a set of
*graphs*: nodes connected by execution wires (what happens next) and data wires (what flows between
nodes). Editors draw those graphs the way Unreal Engine draws Blueprints. Underneath, every graph is
stored in a line-oriented, diff-friendly text format, compiled to a compact typed bytecode, and run by a
small embeddable runtime with a C API.

```
 graph editor ──►  .wiret text  ──►  wiretc  ──►  .wirb bytecode  ──►  libwiret (embedded in the host)
 (people)          (Git, LLMs)      (compiler)    (verified, typed)     (VM, GC, fibers, C API)
```

## Why text?

Nobody is expected to *type* Wiret, but a text format changes what a visual language can do:

| Need | What the text format gives you |
| --- | --- |
| Source control | One fact per line; connections are owned by exactly one node, so a rewire changes one line and merges cleanly. Layout lives in its own block so moving nodes never conflicts with logic edits. |
| Review | A pull request diff reads like a changelog of the graph: `in b = 2` became `in b = %limit.value`. |
| AI tools | A model can read a graph, explain it, and generate or patch one. The format is explicit (typed, named pins, no positional tricks) so generation errors are detectable and the compiler's diagnostics name the node and pin. |
| Collaboration | Node positions, comment boxes, colors and collapsed state are stored in the file, so every developer's editor shows the same picture. Purely personal state (zoom, scroll, selection) is *not* stored. |

## Design goals

1. **Friendly for non-programmers.** Few concepts: nodes, pins, wires, variables. Execution order is
   visible as white wires. Pure nodes (no white wires) just compute. No hidden control flow.
2. **Capable of general programming.** Typed locals and globals, structs, classes with interfaces,
   arrays/maps/sets, delegates, recursion, loops (cycles), macros, coroutine-style *latent* calls.
3. **Text that reads.** IR-like (typed, explicit) but with markup features: attributes, metadata,
   named pins, layout.
4. **Deterministic and safe to embed.** The bytecode is verified before it runs; integer arithmetic
   wraps; map iteration is insertion-ordered; execution has instruction budgets and memory limits;
   a script can only reach what the host registers.
5. **Debuggable as a graph.** Every instruction maps back to a graph node. A trap, breakpoint or hook
   reports `loop/check`, not `pc 0x35`.

## How the pieces fit

| Part | Document | Analogy |
| --- | --- | --- |
| Text format (`.wiret`) | [Text format](02-text-format.md), [Standard nodes](03-standard-nodes.md) | LLVM IR + DOT/GML attributes |
| Bytecode (`.wirb`) | [Bytecode](04-bytecode.md) | WebAssembly sections, JVM-style typed verification |
| Runtime API (`wiret.h`) | [Runtime API](05-runtime-api.md) | The Lua C API |
| Compiler and tools | [Tooling](06-tooling.md) | `clang`, `wasm-validate`, a Git merge driver |

## From Blueprints to Wiret

| Blueprint concept | Wiret |
| --- | --- |
| Event Graph / Function Graph | `event` / `function` with a `graph { … }` block |
| Exec pin (white) | `exec <pin> -> %target` (owned by the *source* node; at most one target per output pin) |
| Data pin (colored) | `in <pin> = %source.pin` or a literal (owned by the *consuming* node; one source per input pin) |
| Pin default value | the literal after `=` in `in <pin> = 5`; omitted pins take the declared or type default |
| Pure node | a node with no exec pins: evaluated on demand, immediately before each consumer runs |
| Macro / Collapsed graph | `macro` (inlined at compile time; generic with `<T>`; may have several exec pins) |
| Sequence, Branch, Switch | `Sequence<N>`, `Branch`, `Switch<i32>` |
| ForLoop, DoOnce, … | `std.flow` macros written in Wiret itself |
| Latent node (Delay) | a `latent` function; the calling event becomes a coroutine |
| Variable / Local variable | `var` (module or class field) / `local $name` |
| Struct, Enum | `struct`, `enum` (structs are immutable values; "Set members" returns a new struct) |
| Blueprint Class, Interface | `class` (single inheritance), `interface` |
| Event Dispatcher | `dispatcher<Signature>` field + `Broadcast` node |
| Cast To | `Cast<Class>` with `then` / `failed` exec outputs |
| Comment box, node position, reroute | `layout { … }` block (positions are integers) |

Deliberate differences: arrays, maps and sets are **reference types** (assignment aliases; use
`ArrayClone` to copy); macro data inputs are **snapshots** taken when the macro is entered (Blueprint
macros re-evaluate them on every use); a trap **stops the fiber** and reports the node instead of
logging "Accessed None" and continuing.

## A first look

This is a complete program. `Fib` is a *pure* function: it has no white wires leaving the graph
except the ones that choose what to return.

```wiret
wiret 0.1

module "examples.fibonacci"
meta doc = "Recursive Fibonacci: the smallest useful Wiret program."

export pure function Fib(n: i32 [tooltip = "Which Fibonacci number to compute"]) -> (result: i32) {
  meta category = "Math"
  graph {
    node %entry : Entry {
      exec then -> %is_base
    }
    node %lt : Lt<i32> {
      in a = %entry.n
      in b = 2
    }
    node %is_base : Branch {
      in condition = %lt.result
      exec then -> %ret_n
      exec else -> %ret_sum
    }
    node %ret_n : Return {
      in result = %entry.n
    }
    node %n_minus_1 : Sub<i32> {
      in a = %entry.n
      in b = 1
    }
    node %n_minus_2 : Sub<i32> {
      in a = %entry.n
      in b = 2
    }
    node %fib_1 : Call<@Fib> {
      in n = %n_minus_1.result
    }
    node %fib_2 : Call<@Fib> {
      in n = %n_minus_2.result
    }
    node %sum : Add<i32> {
      in a = %fib_1.result
      in b = %fib_2.result
    }
    node %ret_sum : Return {
      in result = %sum.result
    }
  }
  layout {
    %entry at (0, 0)
    %lt at (260, 160)
    %is_base at (520, 0)
    %ret_n at (860, -40)
    %n_minus_1 at (260, 340)
    %n_minus_2 at (260, 500)
    %fib_1 at (520, 340)
    %fib_2 at (520, 500)
    %sum at (800, 420)
    %ret_sum at (1060, 380)
    box "Base case" at (-20, -70) size (1180, 330) [color = #3a5f8a]
  }
}
```



*The picture above is generated from the `layout` block by the reference tool `wiret_ref svg`; any
editor that honours the layout shows the same arrangement.*

Compiled, `Fib` is 267 bytes including debug maps. Its code section disassembles to:

```
func f0 Fib pure (i32) -> (i32)
  regs: r0:i32, r1:i32, r2:bool, r3:i32, r4:i32, r5:i32, r6:i32, r7:i32, r8:i32
  ; --- %lt
         CONST.i32   r1 2
         LT.i32      r2 r0 r1
  ; --- %is_base
         JMPIFNOT    r2 @000d
  ; --- %ret_n
         RET         (r0)
  ; --- %n_minus_1
  @000d: CONST.i32   r1 1
         SUB.i32     r3 r0 r1
  ; --- %fib_1
         CALL        Fib (r3) (r4)
  ; --- %n_minus_2
         CONST.i32   r5 2
         SUB.i32     r6 r0 r5
  ; --- %fib_2
         CALL        Fib (r6) (r7)
  ; --- %sum
         ADD.i32     r8 r4 r7
  ; --- %ret_sum
         RET         (r8)
```

Each `; --- %node` line comes from the `wiret.nodemap` debug section. Notice that the pure nodes
`%n_minus_1` and `%n_minus_2` were emitted right before the `Call` that consumes them, and that the
Branch became a single `JMPIFNOT` that falls through into the "then" path.

Run it from the command line with the reference implementation, or embed it:

```c
wiret_getexport(F, m, "Fib");
wiret_pushi32(F, 10);
wiret_pcall(F, 1, 1);
printf("%d\n", wiret_checki32(F, -1));   /* 55 */
```

## Status of this specification

This is **version 0.1 (draft)**. A reference implementation of the text parser, formatter,
compiler, binary encoder, verifier, interpreter, disassembler and graph renderer accompanies it
(`reference/wiret_ref`, Python). It executes every example in these documents. Features that are
specified but not yet exercised by the reference implementation are marked **[spec only]**: classes,
interfaces, structs, maps/sets, delegates/dispatchers, fibers/latent calls, and the C runtime itself
(`wiret.h` is the specified, compile-checked interface).


---

# Text format

A Wiret source file (`.wiret`) is UTF-8 text. It is designed to be **generated and read by tools**:
explicit, typed, regular, and canonical when formatted by `wiret fmt`. This chapter is normative.

## Lexical structure

* **Whitespace** (space, tab, CR, LF) separates tokens and is otherwise insignificant. The parser is
  *not* line-oriented, so a model that wraps lines differently still produces valid input. The
  canonical formatter always emits LF line endings, 2-space indentation and one item per line.
* **Comments** start with `;` and run to the end of the line. Comments are not preserved by tools;
  use `meta doc = "…"` or `meta comment = "…"` for text that must survive round trips.
* **Identifiers**: `[A-Za-z_][A-Za-z0-9_]*`. Keywords are contextual (a pin may be called `in`).
* **Sigils** make references unambiguous, like LLVM-IR:

| Token | Meaning | Example |
| --- | --- | --- |
| `%name` | a node in the current graph | `%add_k3f9` |
| `%node.pin` | an output pin of that node (as a data source) | `%entry.amount` |
| `@name`, `@Class.member`, `@alias.name` | a module-level symbol (function, variable, field) | `Call<@Fib>` |
| `$name` | a local variable or macro state | `GetLocal<$acc>` |
| `#rrggbb` | a color (attribute values only) | `#3a5f8a` |

* **Literals**

| Kind | Syntax | Notes |
| --- | --- | --- |
| integer | `42`, `-7`, `0xFF` | range-checked against the pin type; an integer literal may initialize a float pin |
| float | `3.14`, `1e-3`, `-2.5E4`, `inf`, `-inf`, `nan` | a decimal point or exponent makes it a float |
| bool | `true`, `false` | |
| string | `"text"` | escapes `\n \t \r \" \\ \0 \u{1F600}`; no raw newlines |
| null | `null` | any nullable reference type |
| list | `[1, 2, 3]` | array / set literals (and `cases` properties) |
| struct | `{x: 1, y: 2}` | |
| enum | `DoorState.Open` | |

## Types

```
i32  i64  f32  f64  bool  string  any
array<T>   map<K,V>   set<T>
Name                 ; a struct, enum, class, interface, delegate or extern type declared in scope
alias.Name           ; the same, from a `use`d module
dispatcher<Delegate> ; a multicast event dispatcher over a declared delegate type
```

`i32`/`i64` are two's-complement and wrap on overflow. `f32`/`f64` are IEEE-754. Enums are `i32`
underneath. Strings are immutable UTF-8 and never null (default `""`). All other reference types
default to `null`, except `array<T>` pin defaults which are a fresh empty array.

Smaller integer types and vectors are reserved for a later version (see *Roadmap* in Tooling).

## File structure

```
file      = "wiret" VERSION  decl*
decl      = "module" STRING
          | "meta" ID "=" value
          | "use" STRING "as" ID
          | [mods] "extern" "function" ID "=" STRING pins ["->" pins]
          | "extern" "type" ID "=" STRING
          | "enum" ID "{" (ID ["=" INT] [attrs] ",")* "}"
          | "struct" ID "{" (ID ":" type ["=" literal] [attrs] ",")* "}"
          | "delegate" ID pins ["->" pins]
          | "interface" ID "{" function-signature* "}"
          | "class" ID [":" type ("," type)*] "{" class-member* "}"
          | ("var" | "const") ID ":" type ["=" literal] [attrs]
          | [mods] ("function" | "event" | "macro") ID ["<" ID ("," ID)* ">"] pins ["->" pins] [body]
mods      = ("export" | "pure" | "latent")*
pins      = "(" [ pin ("," pin)* ] ")"
pin       = ID ":" type ["=" literal] [attrs]       ; data pin
          | "exec" ID                              ; exec pin (macros only)
attrs     = "[" ID "=" value ("," ID "=" value)* "]"
body      = "{" ("meta" ID "=" value | local | state | graph | layout)* "}"
local     = "local" "$"ID ":" type ["=" literal] [attrs]
state     = "state" "$"ID ":" type ["=" literal] [attrs]
graph     = "graph" "{" node* "}"
node      = "node" "%"ID ":" kind ["<" targ ("," targ)* ">"] "{" node-item* "}"
node-item = "meta" ID "=" value                     ; tooling data, never affects code
          | "prop" ID "=" value                     ; compile-time configuration
          | "in" ID "=" ( literal | "%"ID "." ID )  ; data input binding
          | "exec" ID "->" "%"ID ["." ID]           ; exec output connection
kind      = ID ("." ID)*                            ; Add, Branch, flow.ForLoop, ...
targ      = type | "@"symbol | "$"ID | INT | STRING
layout    = "layout" "{" ( "%"ID "at" point [attrs]
                         | "box" STRING "at" point "size" point [attrs] )* "}"
point     = "(" INT "," INT ")"
```

`value` in attributes may be any literal, a bare identifier, a color, or a list.

### Declarations

* **`module`** names the compilation unit (dotted, e.g. `"game.inventory"`). It is the namespace other
  modules import.
* **`use "std.flow" as flow`** imports a module's macros and types under an alias; its macros are used
  as node kinds (`flow.ForLoop`).
* **`extern function`** declares a *native* implemented by the host. The string is the registry name
  (`"module.function"`); the host must register it with a matching signature before instantiation.
  `pure` means no observable effects and results depend only on arguments; `latent` means it may
  suspend. `extern type` declares an opaque host handle type.
* **`var`** at module level is a global; inside a `class` it is an instance field. `const` is a global that
  nodes cannot set.
* **`function`** has one exec entry (the `Entry` node) and any number of `Return` nodes. A function with
  results must reach a `Return` on every path (error `E0301`). A function without results ends where
  a path ends.
* **`event`** is a function that is an entry point for the host or for dispatchers. It is exported
  automatically; it may be `latent`.
* **`pure function`** may be called as a pure node (no white wires): it may read globals but must not
  modify globals/fields or call impure functions (`E0202`). It may have internal control flow and
  locals.
* **`latent`** functions may call latent functions and natives. A non-latent function calling a latent
  one is an error (`E0201`). The runtime runs latent calls on a fiber (see Runtime API).
* **`macro`** declares reusable *inlined* subgraphs; see [Macros](#macros).
* **Metadata**: `meta key = value` lines (module, function, class, node) and trailing `[k = v]` lists (on
  `var`, parameters, fields, enum members). Well-known keys: `doc`, `category`, `tooltip`,
  `display_name`, `deprecated`, `keywords`, `color`, `comment` (shown as a node bubble). Unknown keys
  are preserved. Metadata never changes generated code and is excluded from the semantic hash.

## Graphs

A `graph` is an unordered set of node blocks. **Order is not significant**, but tools must preserve
the existing order and insert new nodes directly after the node they were created from, which keeps
diffs local. `wiret fmt --reading-order` rewrites a file in depth-first execution order.

### Node blocks

```
node %id : Kind<type-args> {
  meta key = value        ; optional
  prop key = value        ; optional compile-time configuration
  in pin = source         ; one line per bound input pin
  exec pin -> %target     ; one line per connected exec output pin
}
```

* **`%id`** is unique within the function and **never reused or renumbered** by editors. Ids are
  `slug` + short random suffix by convention (`%add_k3f9`), so two developers adding a node at the
  same time do not collide.
* **`Kind<…>`** selects a node from the [standard set](03-standard-nodes.md), a macro (`flow.ForLoop`),
  or `Call<@function>`. Type arguments are explicit: there are no wildcard pins in text, which keeps
  the file unambiguous. The editor shows wildcards and fills the type arguments for you.
* **`in pin = …`** binds a data input to a literal or to `%node.pin`. Unbound inputs take the declared
  default (parameter default or the type default: `0`, `0.0`, `false`, `""`, `null`, empty array).
  **Each input pin has at most one source**; an output pin may feed any number of inputs.
* **`exec pin -> %target`** connects an exec output to the exec input of `%target`. The default input
  is the node's first exec input (`in`); other inputs are named: `-> %once.reset`. **Each exec output
  has at most one target**; an exec input may be the target of many wires (a merge).

Because a data wire is written by its *consumer* and an exec wire by its *producer*, every wire in the
graph is exactly one line in exactly one place. Deleting a node leaves dangling lines only in nodes
that referenced it, and those are reported as `E0110`/`E0112`, never silently dropped.

### Evaluation semantics

1. **Execution** starts at `Entry` and follows exec wires. A node runs when execution reaches it.
   Cycles are legal and are how loops are made.
2. **Pure nodes** (no exec pins) run on demand: immediately **before each impure node that needs their
   result**, once per such execution (a pure node feeding two impure nodes runs twice; feeding two
   inputs of one impure node runs once). Data cycles are an error (`E0105`).
3. **Impure node outputs** are stored: reading `%call_1.result` later reads the value from the last
   time `%call_1` ran. Function parameters are the outputs of `%entry`.
4. **End of a path**: an unconnected exec output ends that path. Inside a `Sequence` branch, ending a
   path continues with the next branch; otherwise the function returns (or is an error if it has
   results).
5. **Sequence** `Sequence<N>` runs `then_0` to the end of its path, then `then_1`, …. The last branch
   runs in tail position (no state remains), so loops built on Sequence do not grow any stack.
6. **Evaluation order of inputs** within one node is unspecified except that pure inputs are all
   computed before the node runs. Pure nodes cannot have side effects, so this is unobservable.

### Macros

A macro is a subgraph that is **expanded inline** at every use site. It may have several exec inputs
and outputs and generic type parameters:

```
macro ForEach<T>(exec in, items: array<T>) -> (exec body, element: T, index: i32, exec completed) {
  local $i: i32
  graph {
    node %entry : Entry { exec in -> %init }
    …
    node %exit : Exit { in element = %item.value  in index = %get_i.value }
  }
}
```

* Parameters that are `exec NAME` are exec inputs; they become exec *outputs* of the `Entry` node
  inside the macro. Result `exec NAME` pins are exec outputs; they are exec *inputs* of the `Exit` node.
* A macro graph has exactly one `Entry` and one `Exit`.
* **Data inputs are snapshots**: they are evaluated once each time an exec input fires, and the
  macro's graph reads the stored copy (`%entry.items`).
* **Data outputs belong to the exec result before them in the signature.** In the example, `element`
  and `index` are computed and stored only when `body` fires, so `completed` never evaluates
  `ArrayGet` one past the end. Data results listed *before* every exec result are written on every exit.
* `local $x` is per activation of the enclosing function; **`state $x`** persists for the lifetime of the
  module instance, one slot per expansion site (this is how `DoOnce` remembers). Because each function
  has its own graph, a node's state is shared only by paths through that node in that function.
* After expansion, macro-internal node ids become path-style ids: `loop/check` (inner node), and
  synthetic binding nodes `loop!in`, `loop!body` (entry and exit stubs). These ids appear in node maps,
  traces and breakpoints so a debugger can step *into* a macro.
* Recursive macros are rejected (`E0310`).

The standard flow macros (`ForLoop`, `ForEach`, `DoOnce`, `DoN`) are written in Wiret and ship as
`std.flow`; see [Standard nodes](03-standard-nodes.md).

## Layout

```
layout {
  %entry at (0, 0)
  %lt at (260, 160) [collapsed = true]
  box "Base case" at (-20, -70) size (1180, 330) [color = #3a5f8a]
}
```

* One line per node, keyed by `%id`. Coordinates are **integers** in editor units (y grows downward);
  editors snap before saving so a drag never yields float noise in diffs.
* A `box` is a comment box; it contains whatever nodes lie inside it (membership is geometric, not a list,
  so moving a node never edits the box).
* Attributes: `collapsed`, `color`, `size` (resized nodes), `hidden_pins` (list of pin names), `note`.
* **Shared vs. personal view state.** Everything in the layout block is *shared* and committed.
  Zoom, scroll position, selection, and open tabs are *personal* and must be stored outside the file
  (for example in `.wiret-workspace` next to it, which is `.gitignore`d).
* The layout block is excluded from the **semantic hash** (see Tooling), so a rearranged graph is
  recognised as "same program, new picture" by CI, caches and incremental builds.

## Canonical form

`wiret fmt` is a deterministic function of the parse tree:

1. Header, then `module`, then module `meta`, then blank-line-separated blocks in the order: `use`,
   `extern`, `enum`, `struct`, `delegate`, `interface`, `var`/`const`, `class`, functions and macros.
2. In a node block, items appear as `meta`, `prop`, `in`, `exec`, each group in its original order.
3. Attribute lists are written `[k = v, …]` with keys sorted; numbers and strings are normalised.
4. Declaration and node **order is preserved**.

Parsing the formatted output yields an identical tree, and formatting is idempotent; the reference
tests check both on every example.

## Diagnostics

The compiler reports structured diagnostics: a stable code, a message, the function, the node id and,
where relevant, the pin. Editors use these to underline nodes; LLM tools can feed them back verbatim.

| Code | Meaning |
| --- | --- |
| E0101 | unknown node kind |
| E0102 | pin type mismatch or invalid literal |
| E0103 | missing or malformed type argument |
| E0104 | operation not defined for that type (`Sqrt<i32>`, `Lt<bool>`) |
| E0105 | data cycle through pure nodes |
| E0110 | reference to an unknown node |
| E0111 | unknown input/output pin |
| E0112 | exec connection to an unknown node |
| E0113 | unknown exec output pin |
| E0114 | exec target has no such exec input |
| E0120–E0122 | unknown local/state, global variable, or function |
| E0130, E0131 | duplicate node id; missing or duplicate `Entry` |
| E0201 | latent call from a non-latent function |
| E0202 | pure function performs a side effect |
| E0301 | an execution path ends without `Return` |
| E0305 | `Sequence` re-enters itself unboundedly |
| E0310, E0311 | recursive macro; macro without exactly one `Entry`/`Exit` |
| W0001 | node unreachable from `Entry` (warning) |


---

# Standard nodes

Nodes are identified by *kind* (`Add`), optional *type arguments* (`<i32>`), and pin names. This chapter
lists every intrinsic node, its pins, and the bytecode it lowers to. Nodes marked **[spec only]** are
specified but not yet implemented by the reference compiler.

Legend: **P** = pure (no exec pins, evaluated on demand); **X** = impure (has `in` exec input and a `then`
output unless stated). "→" shows the instruction(s) emitted.

## Entry, exit and flow control

| Kind | Pins | Notes |
| --- | --- | --- |
| `Entry` | exec out `then`; one data output per parameter (`%entry.n`), plus `self` in methods | Exactly one per function. In a macro, exec outputs are the macro's exec inputs. |
| `Return` | exec in `in`; one data input per result | Many allowed. → `RET` |
| `Exit` | macros only: exec inputs named after the macro's exec results | One per macro. |
| `Branch` | in `condition: bool`; exec out `then`, `else` | → `JMPIFNOT c, else`; falls through into `then` |
| `Sequence<N>` | exec out `then_0 … then_{N-1}` | Runs the branches in order (see *Evaluation semantics*). No instruction of its own; the compiler duplicates continuation code per nesting context. |
| `Switch<i32>` | in `value`; `prop cases = [v0, v1, …]`; exec out `case_0 … case_k`, `default` | Dense cases `0..n-1` → `SWITCH`; otherwise a compare-and-branch chain. |
| `Trap` | `prop message = "…"`; terminal | → `TRAP` |

Loops are not special: a cycle in the exec wires *is* a loop. A while loop is a `Branch` whose `then`
path leads back to the node that computes its condition (see `Collatz` below).

## Arithmetic, comparison and logic (P)

| Kind | Type args | Pins | → |
| --- | --- | --- | --- |
| `Add Sub Mul Div Rem Min Max` | `<i32/i64/f32/f64>` | in `a`, `b`; out `result` | `ADD.t` … |
| `Neg Abs` | numeric | in `a`; out `result` | `NEG.t`, `ABS.t` |
| `Sqrt` | `<f32/f64>` | in `a`; out `result` | `SQRT.t` |
| `BitAnd BitOr BitXor Shl Shr` | `<i32/i64>` | in `a`, `b`; out `result` | `AND.t` … (`Shr` is arithmetic; shift counts are masked) |
| `BitNot` | `<i32/i64>` | in `a`; out `result` | `NOT.t` |
| `Eq Ne Lt Le Gt Ge` | numeric, `string`, `bool` (`Eq`/`Ne` only) | in `a`, `b`; out `result: bool` | `EQ.t` …, `STR.EQ` … |
| `And Or Xor Not` | – | in `a`, `b`; out `result: bool` | `AND.bool` … (not short-circuit: both inputs are pure) |
| `Select<T>` | any | in `condition`, `a`, `b`; out `result` | `SELECT` |
| `Convert<A,B>` | see conversion table | in `value`; out `result` | `CVT.A.B` |
| `Const<T>` | any literal type | `prop value = …`; out `value` | `CONST.t` |
| `Concat` | – | in `a`, `b: string`; out `result` | `STR.CONCAT` |
| `StrLen` | – | in `text`; out `length: i32` (UTF-8 bytes) | `STR.LEN` |
| `Reroute<T>` | any | in `value`; out `value` | none (editor knot) |

Semantics worth knowing: integer `Div`/`Rem` truncate toward zero and trap on a zero divisor;
`INT_MIN / -1` wraps to `INT_MIN` and `INT_MIN % -1` is `0`. Float division follows IEEE-754 (no trap).
`Min`/`Max` on floats return NaN if either operand is NaN. Float → integer conversions saturate and map
NaN to 0. String comparison is by UTF-8 bytes.

## Variables (P/X)

| Kind | Pins | → |
| --- | --- | --- |
| `GetLocal<$x>` (P) | out `value` | none (reads the local's register) |
| `SetLocal<$x>` (X) | in `value` | `MOV` |
| `GetVar<@g>` (P) | out `value` | `GLOBAL.get` |
| `SetVar<@g>` (X) | in `value` | `GLOBAL.set` |
| `GetState<$s>` / `SetState<$s>` | macros: persistent per-expansion state | `GLOBAL.get/set` on a hidden global |

## Calls

| Kind | Pins | Notes |
| --- | --- | --- |
| `Call<@f>` | one input per parameter (defaults from the declaration); one output per result | X, or P if `f` is `pure`. Works for functions and `extern` natives. → `CALL` |
| `Call<@Class.method>` **[spec only]** | `target` + parameters | virtual dispatch → `CALLV` |
| `Call<@Interface.method>` **[spec only]** | `target` + parameters | → `CALLI` |
| `CallDelegate<D>` **[spec only]** | `delegate` + parameters | → `CALLD` |

## Arrays

`array<T>` is a mutable reference type. Indices are zero-based; out-of-range access traps.

| Kind (all `<T>`) | Class | Pins |
| --- | --- | --- |
| `ArrayNew` | X | out `array` → `ARR.new` |
| `ArrayLen` | P | in `array`; out `length: i32` |
| `ArrayGet` | P | in `array`, `index`; out `value` (traps if out of range) |
| `ArraySet` | X | in `array`, `index`, `value` |
| `ArrayPush` | X | in `array`, `value` |
| `ArrayPop` | X | in `array`; out `value` (traps if empty) |
| `ArrayInsert` | X | in `array`, `index`, `value` |
| `ArrayRemoveAt` | X | in `array`, `index` |
| `ArrayClear` | X | in `array` |
| `ArrayClone` | X | in `array`; out `clone` (shallow copy) |

## Maps, sets, structs, objects, delegates **[spec only]**

| Kind | Pins and notes |
| --- | --- |
| `MapNew<K,V>` X, `MapLen` P | `map` / `length` |
| `MapGet<K,V>` P | in `map`, `key`; out `value`; traps if missing |
| `MapTryGet<K,V>` P | in `map`, `key`; out `value`, `found: bool` |
| `MapSet<K,V>` X, `MapHas` P, `MapRemove` X (out `removed`) | |
| `MapKeyAt<K,V>`, `MapValueAt<K,V>` P | in `map`, `index`: iterate in **insertion order** |
| `SetNew<T>`, `SetAdd` (out `added`), `SetHas`, `SetRemove`, `SetAt`, `SetLen` | |
| `MakeStruct<S>` P | in one pin per field → out `value` |
| `GetMember<S.f>` P, `SetMember<S.f>` P | `SetMember`: in `struct`, `value`; out `result`: a **new** struct |
| `New<C>` X | out `object` |
| `Self<C>` P | out `value` (the receiver) |
| `GetField<@C.f>` P, `SetField<@C.f>` X | in `target` (+ `value`) |
| `Cast<C>` X | in `object`; exec out `then`, `failed`; out `result: C` → `CAST.try` + branch |
| `IsNull<T>` P | in `value`; out `result` |
| `ToAny<T>` P, `FromAny<T>` X | `FromAny` has exec out `then`, `failed`; out `value` |
| `MakeDelegate<D>` P | `prop function = @f`; in `target` (optional) |
| `Bind<@C.d>`, `Unbind<@C.d>`, `Broadcast<@C.d>`, `ClearBindings<@C.d>` X | in `target`, `delegate` or the delegate's parameters |

`Broadcast` calls every bound handler in binding order. Handlers that are `latent` are started on their
own fibers; the broadcast does not wait.

## std.flow (written in Wiret)

`use "std.flow" as flow`. These are ordinary macros; they are the best worked examples of the macro
rules. `While` is deliberately absent: it is a `Branch` with a back wire, because a loop condition must be
re-evaluated every iteration and macro inputs are snapshots.

| Macro | Signature | Behaviour |
| --- | --- | --- |
| `ForLoop` | `(exec in, first: i32 = 0, last: i32 = 0) -> (exec body, index: i32, exec completed)` | runs `body` for `first..=last` |
| `ForEach<T>` | `(exec in, items: array<T>) -> (exec body, element: T, index: i32, exec completed)` | runs `body` per element; the array is snapshotted by reference, so appending inside the body extends the loop |
| `DoOnce` | `(exec in, exec reset) -> (exec completed)` | passes only the first execution until `reset` fires |
| `DoN` | `(exec in, exec reset, n: i32 = 1) -> (exec completed)` | passes at most `n` executions until `reset` |

Source of `ForLoop` and `DoOnce` exactly as shipped:

```wiret
macro ForLoop(exec in, first: i32 = 0, last: i32 = 0) -> (exec body, index: i32, exec completed) {
  meta doc = "Runs body once for each index from first to last (inclusive), then completed."
  local $i: i32
  graph {
    node %entry : Entry {
      exec in -> %init
    }
    node %init : SetLocal<$i> {
      in value = %entry.first
      exec then -> %check
    }
    node %get_i : GetLocal<$i> {}
    node %le : Le<i32> {
      in a = %get_i.value
      in b = %entry.last
    }
    node %check : Branch {
      in condition = %le.result
      exec then -> %seq
      exec else -> %exit.completed
    }
    node %seq : Sequence<2> {
      exec then_0 -> %exit.body
      exec then_1 -> %step
    }
    node %inc : Add<i32> {
      in a = %get_i.value
      in b = 1
    }
    node %step : SetLocal<$i> {
      in value = %inc.result
      exec then -> %check
    }
    node %exit : Exit {
      in index = %get_i.value
    }
  }
}
```

```wiret
macro DoOnce(exec in, exec reset) -> (exec completed) {
  meta doc = "Lets execution through the first time only, until reset is triggered."
  state $done: bool = false
  graph {
    node %entry : Entry {
      exec in -> %check
      exec reset -> %clear
    }
    node %get_done : GetState<$done> {}
    node %check : Branch {
      in condition = %get_done.value
      exec else -> %mark
    }
    node %mark : SetState<$done> {
      in value = true
      exec then -> %exit.completed
    }
    node %clear : SetState<$done> {
      in value = false
    }
    node %exit : Exit {}
  }
}
```

## Worked examples

All of these compile, verify and run on the reference implementation (`examples/flow.wiret`).

**`SumTo(n)`** uses `ForLoop` with a local accumulator. `SumTo(100)` returns 5050.



Its disassembly shows the macro expanded inline: the back edge is the final `JMP @0018`, and the
entry stub `%loop!in` is where the macro's inputs are snapshotted.

```
func f1 SumTo (i32) -> (i32)
  regs: r0:i32, r1:i32, r2:i32, r3:i32, r4:i32, r5:i32, r6:bool, r7:i32, r8:i32
  ; --- %entry
         CONST.i32   r3 0
         MOV         r1 r3
         CONST.i32   r3 0
         MOV         r2 r3
  ; --- %loop!in
         CONST.i32   r3 1
         MOV         r4 r3
         MOV         r5 r0
  ; --- %loop/init
         MOV         r2 r4
  ; --- %loop/le
  @0018: LE.i32      r6 r2 r5
  ; --- %loop/check
         JMPIFNOT    r6 @0035
  ; --- %loop!body
         MOV         r7 r2
  ; --- %plus
         ADD.i32     r3 r1 r7
  ; --- %accumulate
         MOV         r1 r3
  ; --- %loop/inc
         CONST.i32   r3 1
         ADD.i32     r8 r2 r3
  ; --- %loop/step
         MOV         r2 r8
         JMP         @0018
  ; --- %done
  @0035: RET         (r1)
```

**`FizzBuzz(limit)`** prints through a native: `extern function print = "std.print"(text: string)`.
Calling `FizzBuzz(15)` prints `1 2 Fizz 4 Buzz Fizz 7 8 Fizz Buzz 11 Fizz 13 14 FizzBuzz`.

**`Collatz(start)`** is a while loop made of a `Branch` and a back wire, with `Select` choosing the next
value: `Collatz(27)` returns 111.

**`Ordering()`** has `Sequence<3>` whose first branch is two calls long: it prints `A A2 B C`.

**`Divide(1, 0)`** traps, and the VM reports the graph node, not a program counter:

```
trap: integer divide by zero
    at Divide (node %div)
```


---

# Bytecode specification

Wiret bytecode (`.wirb`) is a **typed register machine** with a binary module format modelled on
WebAssembly (sections, LEB128, validation before execution) and a type system in the spirit of the JVM
(statically typed, verified, garbage-collected references). This chapter is normative.

## Why a typed register machine

| Decision | Reason |
| --- | --- |
| Registers, not an operand stack | Every data pin of an impure node is a variable that other nodes read *later*. A stack machine would need `dup`/`swap` shuffling to express that; registers map pins directly, and debuggers can show a pin's value (`wiret.pins`). |
| Every register has one static type | Verification is a single linear pass: no dataflow fix-point as in the classic JVM verifier. The GC knows which registers hold references without per-instruction stack maps. |
| Typed opcodes (`ADD.i32`) | No runtime type dispatch; the verifier checks operand types by opcode alone. |
| Explicit operand lists for calls | Calls copy arguments and results between register windows, so register types never change across a call. |
| Structured by sections, with custom sections | A runtime can skip debug info it does not want; new data can be added without a format break. |

## Module binary format

```
module  = magic version section*
magic   = 0x00 0x57 0x52 0x54            ; "\0WRT"
version = u32 little-endian              ; 1
section = id:u8  size:uleb128  payload
```

Integers are **LEB128** (`uleb128` unsigned, `sleb128` signed) unless stated. Floats are little-endian
IEEE-754. A *name* is `uleb128 length` + UTF-8 bytes. Non-custom sections appear **at most once, in
increasing id order**; custom sections (id 0) may appear anywhere.

| Id | Section | Contents |
| --- | --- | --- |
| 0 | Custom | `name`, then section-specific payload |
| 1 | Type | `count`, then type entries |
| 2 | Import | `count`, then `module:name field:name kind:u8 sigtype:uleb flags:u8` (kind 0 = function) |
| 3 | Function | `count`, then `sigtype:uleb flags:u8` per defined function |
| 4 | Global | `count`, then `valtype mutable:u8 init` (init = a constant encoded by type) |
| 5 | Export | `count`, then `name kind:u8 index:uleb` (kind 0 = function) |
| 6 | Start | `uleb`: 0 = none, otherwise function index + 1 |
| 7 | String | `count`, then names: the constant pool |
| 8 | Code | `count`, then function bodies, in Function-section order |

**Function index space**: imports first (in Import order), then defined functions. `CALL` uses this
index. **Function flags**: bit 0 `pure`, bit 1 `latent`, bit 2 `event`.

### Value types

```
valtype = 0x7F i32 | 0x7E i64 | 0x7D f32 | 0x7C f64 | 0x7B bool | 0x70 string | 0x6F any
        | 0x6E typeidx:uleb                ; a reference to a composite type-section entry
```

### Type section entries

| Byte | Entry | Payload |
| --- | --- | --- |
| `0x60` | func | `nparams valtype* nresults valtype*` |
| `0x5D` | array | `elem:valtype` |
| `0x5C` | map | `key:valtype value:valtype` |
| `0x5B` | set | `elem:valtype` |
| `0x56` | host | `name` (an opaque host type, resolved at link time) |
| `0x5F` | struct **[spec only]** | `nfields valtype*` (immutable value type) |
| `0x5E` | class **[spec only]** | `super:uleb(0=none, else idx+1) niface iface-typeidx* nfields valtype* nslots funcidx* imap` — `funcidx*` is the complete virtual table (inherited slots included); `imap` lists, per interface, the function implementing each method |
| `0x5A` | interface **[spec only]** | `nmethods sigtype*` |
| `0x58` | delegate **[spec only]** | `sigtype` (single-cast function reference with optional bound target) |
| `0x57` | dispatcher **[spec only]** | `sigtype` (multicast list of delegates) |

Enums are `i32` at the bytecode level; their names live in a custom section. Identical entries are
shared (the type section is a set).

### Code section: function body

```
body    = size:uleb  nregs:uleb  ngroups:uleb  (count:uleb valtype)*  instruction*
```

The register groups run-length-encode the register types. **Registers `r0 … r(p-1)` are the
parameters** and must match the signature. All other registers are locals and temporaries. Every
register is zero-initialised when the frame is created: numbers `0`, `bool` false, `string` `""`,
references `null`, struct registers hold their default value.

### Custom sections

| Name | Payload | Purpose |
| --- | --- | --- |
| `wiret.names` | module name; `(kind:u8 index name)*` (kind 0 function, 1 global) | symbol names for traces, reflection and export tools |
| `wiret.nodemap` | local string table; per function: `funcindex nentries (pc-delta:uleb node-string)*` | maps each byte offset to the graph node that produced it (`loop/check`, `loop!body`). A pc belongs to the nearest preceding entry. |
| `wiret.pins` | local string table; per function: `funcindex n (register node pin)*` | which register holds which output pin, for value probes |

Runtimes may ignore any custom section (`WIRET_CFG_NO_DEBUG_INFO`). Unknown custom sections must be skipped.

### Annotated example: `Fib`

```
00 57 52 54 01 00 00 00           magic, version 1
01 06  01 60 01 7f 01 7f          Type: 1 entry: func (i32) -> (i32)
02 01 00                          Import: none
03 03  01 00 01                   Function: 1 function, signature 0, flags = pure
04 01 00                          Global: none
05 07  01 03 46 69 62 00 00       Export: "Fib", function, index 0
06 01 00                          Start: none
07 01 00                          String pool: empty
08 38  01 36                      Code: 1 body, 0x36 bytes
   09  03 02 7f 01 7b 06 7f       9 registers: 2×i32, 1×bool, 6×i32
   11 01 02                       CONST.i32  r1, 2
   28 02 00 01                    LT.i32     r2, r0, r1
   04 02 03                       JMPIFNOT   r2, +3
   06 01 00                       RET        (r0)
   11 01 01 …                     CONST.i32  r1, 1     ; @000d – the else path
   …
00 26  0b "wiret.names" …         custom sections: names, nodemap, pins
```

`JMPIFNOT r2, +3` skips the 3-byte `RET (r0)`: offsets are relative to the first byte *after* the
branch instruction.

## Execution model

* **Frames.** Calling a function creates a frame of `nregs` registers. `CALL f, (args…), (results…)`
  copies the argument registers into the callee's `r0…`, runs it, and copies the registers named in the
  callee's `RET` into the result registers. Types must match exactly.
* **Values.** `i32`/`i64`: two's complement, arithmetic wraps. `f32`/`f64`: IEEE-754 binary32/64, round
  to nearest even, no traps; NaN payloads are unspecified. `bool`: 0/1. `string`: immutable UTF-8 reference.
  Aggregates and objects are references managed by the GC.
* **Traps** abort the current fiber with a status and a message; there is no catching inside bytecode.
  The host observes the trap from `wiret_pcall`/`wiret_resume`, with a traceback of
  (function, node id) pairs from the node map. Traps: integer divide/remainder by zero, array/map/set
  index or key errors, null dereference, failed `CAST`, `ANY.unbox` mismatch, `TRAP`, call-stack
  overflow, budget exhaustion, memory limit.
* **Budget.** The VM counts instructions. When the host-set budget is exhausted it traps with
  `WIRET_ERR_BUDGET` at the next instruction boundary. Hosts use this to run untrusted graphs.
* **GC safepoints.** Allocation, `CALL`, and backward branches. References are found through the
  per-function register type table, so no stack maps are needed.
* **Determinism.** The only unspecified results are NaN payloads. Maps and sets iterate in insertion order, `STR.LT` is bytewise,
  float-to-string uses the shortest representation that round-trips. With a deterministic native set
  (`WIRET_CFG_DETERMINISTIC`) a program's behaviour is reproducible across platforms.
* **Latent calls and fibers.** A `CALL` to a function flagged `latent` may suspend the fiber (a
  latent native returns `WIRET_YIELD`). Suspension is only possible inside latent functions; the verifier
  enforces this, so non-latent code never observes a suspension. `YIELD` ends the current time slice
  voluntarily. `SPAWN f, (args…)` starts a new fiber that runs `f` to completion independently.

## Validation

A module must be validated before execution. Validation is linear and stateless per instruction:

1. Header, version, section order and sizes are well-formed; all indices (types, functions, globals,
   strings, registers) are in range; the function and code counts agree.
2. Parameter registers have the types of the signature; every register type is a valid valtype.
3. Each instruction's operand registers have exactly the types required by its opcode (the
   mnemonic's `.type` suffix; `MOV`, `SELECT` and `GLOBAL.*` require equal types; array operations
   require `array<T>` with matching element types).
4. `CALL`/`SPAWN` argument types equal the callee's parameter types; `CALL` result registers equal its
   result types; `RET` registers equal the function's result types.
5. A `CALL` to a `latent` callee appears only in a `latent` function.
6. Every branch target is the first byte of an instruction **in the same function**.
7. The last instruction of a body is `RET`, `JMP`, `TRAP` or `SWITCH` (control cannot fall off the end).
8. Imports resolve at instantiation (`WIRET_ERR_LINK`), with exactly matching signatures and flags.

The reference verifier implements 1–7 for the instruction subset the reference VM executes and checks
indices for all others; the typing rules for composite opcodes follow the same pattern and are listed in
the opcode tables.

## Instruction encoding

An instruction is a one-byte opcode followed by operands encoded as the opcode table prescribes.

| Operand | Encoding |
| --- | --- |
| `r` register | `uleb128` index |
| `s` signed immediate | `sleb128` |
| `u` unsigned immediate / index | `uleb128` |
| `L` branch offset | `sleb128`, relative to the first byte after the instruction |
| `rl` register list | `uleb128 count`, then that many registers |
| `sw` switch table | `uleb128 n`, then `n` offsets, then the default offset |
| `f32`, `f64` | 4 / 8 raw bytes |
| `vt` | a valtype |

Opcodes `0xF0`–`0xFF` are reserved for extension prefixes; `0xFF` is permanently invalid. Unassigned
opcodes are validation errors, so new instructions require a bytecode version bump or a declared feature.

## Instruction reference

Operand names: `d` destination register, `a b c` source registers. **Ref** = executed by the
reference VM (the rest are verified structurally and specified here).

### Control, constants and variables

| Code | Mnemonic | Operands | Meaning | Ref |
| --- | --- | --- | --- | --- |
| `0x00` | `NOP` | – | no operation | ✓ |
| `0x01` | `TRAP` | str | raise a runtime error with a constant message | ✓ |
| `0x02` | `JMP` | label | unconditional branch | ✓ |
| `0x03` | `JMPIF` | reg label | branch if the bool register is true | ✓ |
| `0x04` | `JMPIFNOT` | reg label | branch if the bool register is false | ✓ |
| `0x05` | `SWITCH` | reg switch | jump table on an i32 register: value 0..n-1 selects an offset, anything else the default | ✓ |
| `0x06` | `RET` | (regs) | return the listed registers (types must equal the result types) | ✓ |
| `0x07` | `CALL` | fn (regs) (regs) | call function; args list; result registers list | ✓ |
| `0x08` | `CALLV` | type uimm (regs) (regs) | virtual call: class type, vtable slot, args (receiver first), results |  |
| `0x09` | `CALLI` | type uimm (regs) (regs) | interface call: interface type, method index, args, results |  |
| `0x0A` | `CALLD` | reg (regs) (regs) | call through a delegate register |  |
| `0x0B` | `SPAWN` | fn (regs) | start a new fiber running fn(args); results discarded |  |
| `0x0C` | `YIELD` | – | end the time slice; resume on the next scheduler step | ✓ |
| `0x0D` | `BREAK` | – | debugger breakpoint; no effect without a hook | ✓ |
| `0x10` | `MOV` | reg reg | d = a (same type) | ✓ |
| `0x11` | `CONST.i32` | reg simm | load constant | ✓ |
| `0x12` | `CONST.i64` | reg simm | load constant | ✓ |
| `0x13` | `CONST.f32` | reg f32 | load constant | ✓ |
| `0x14` | `CONST.f64` | reg f64 | load constant | ✓ |
| `0x15` | `CONST.bool` | reg uimm | load 0/1 | ✓ |
| `0x16` | `CONST.str` | reg str | load string from the constant pool | ✓ |
| `0x17` | `CONST.null` | reg | null reference (or default struct) | ✓ |
| `0x18` | `GLOBAL.get` | reg global | read global | ✓ |
| `0x19` | `GLOBAL.set` | global reg | write global | ✓ |

### Numeric instructions

Each family exists for the four numeric types. The opcode is the family base plus the listed offset.
`d`, `a`, `b` all have the type in the suffix, except comparisons, whose `d` is `bool`.

| Family | Operands | i32 | i64 | f32 | f64 |
| --- | --- | --- | --- | --- | --- |
| `ADD` | reg reg reg | `0x20` | `0x40` | `0x60` | `0x70` |
| `SUB` | reg reg reg | `0x21` | `0x41` | `0x61` | `0x71` |
| `MUL` | reg reg reg | `0x22` | `0x42` | `0x62` | `0x72` |
| `DIV` | reg reg reg | `0x23` | `0x43` | `0x63` | `0x73` |
| `REM` | reg reg reg | `0x24` | `0x44` | `0x64` | `0x74` |
| `NEG` | reg reg | `0x25` | `0x45` | `0x65` | `0x75` |
| `EQ` | reg reg reg | `0x26` | `0x46` | `0x66` | `0x76` |
| `NE` | reg reg reg | `0x27` | `0x47` | `0x67` | `0x77` |
| `LT` | reg reg reg | `0x28` | `0x48` | `0x68` | `0x78` |
| `LE` | reg reg reg | `0x29` | `0x49` | `0x69` | `0x79` |
| `GT` | reg reg reg | `0x2A` | `0x4A` | `0x6A` | `0x7A` |
| `GE` | reg reg reg | `0x2B` | `0x4B` | `0x6B` | `0x7B` |
| `MIN` | reg reg reg | `0x2C` | `0x4C` | `0x6C` | `0x7C` |
| `MAX` | reg reg reg | `0x2D` | `0x4D` | `0x6D` | `0x7D` |
| `ABS` | reg reg | `0x2E` | `0x4E` | `0x6E` | `0x7E` |
| `SQRT` | reg reg | – | – | `0x6F` | `0x7F` |
| `AND` | reg reg reg | `0x30` | `0x50` | – | – |
| `OR` | reg reg reg | `0x31` | `0x51` | – | – |
| `XOR` | reg reg reg | `0x32` | `0x52` | – | – |
| `SHL` | reg reg reg | `0x33` | `0x53` | – | – |
| `SHR` | reg reg reg | `0x34` | `0x54` | – | – |
| `NOT` | reg reg | `0x35` | `0x55` | – | – |

Semantics: `ADD SUB MUL NEG` wrap for integers. `DIV`/`REM` are signed, truncating, trap on a zero
divisor, and wrap `INT_MIN / -1`. `SHL`/`SHR` mask the count by `bits-1`; `SHR` is arithmetic.
`MIN`/`MAX`/`ABS` on integers are ordinary; on floats NaN propagates. `SQRT` of a negative is NaN.

### Booleans, conversions, strings

| Code | Mnemonic | Operands | Meaning | Ref |
| --- | --- | --- | --- | --- |
| `0x80` | `AND.bool` | reg reg reg |  | ✓ |
| `0x81` | `OR.bool` | reg reg reg |  | ✓ |
| `0x82` | `XOR.bool` | reg reg reg |  | ✓ |
| `0x83` | `NOT.bool` | reg reg |  | ✓ |
| `0x84` | `EQ.bool` | reg reg reg |  | ✓ |
| `0x85` | `NE.bool` | reg reg reg |  | ✓ |
| `0x88` | `CVT.i32.i64` | reg reg |  | ✓ |
| `0x89` | `CVT.i64.i32` | reg reg |  | ✓ |
| `0x8A` | `CVT.i32.f32` | reg reg |  | ✓ |
| `0x8B` | `CVT.i32.f64` | reg reg |  | ✓ |
| `0x8C` | `CVT.i64.f32` | reg reg |  | ✓ |
| `0x8D` | `CVT.i64.f64` | reg reg |  | ✓ |
| `0x8E` | `CVT.f32.i32` | reg reg |  | ✓ |
| `0x8F` | `CVT.f32.i64` | reg reg |  | ✓ |
| `0x90` | `CVT.f64.i32` | reg reg |  | ✓ |
| `0x91` | `CVT.f64.i64` | reg reg |  | ✓ |
| `0x92` | `CVT.f32.f64` | reg reg |  | ✓ |
| `0x93` | `CVT.f64.f32` | reg reg |  | ✓ |
| `0x94` | `CVT.bool.i32` | reg reg |  | ✓ |
| `0x95` | `CVT.i32.bool` | reg reg |  | ✓ |
| `0x96` | `CVT.i32.string` | reg reg |  | ✓ |
| `0x97` | `CVT.i64.string` | reg reg |  | ✓ |
| `0x98` | `CVT.f32.string` | reg reg |  | ✓ |
| `0x99` | `CVT.f64.string` | reg reg |  | ✓ |
| `0x9A` | `CVT.bool.string` | reg reg |  | ✓ |
| `0xA0` | `STR.CONCAT` | reg reg reg | d = a + b | ✓ |
| `0xA1` | `STR.LEN` | reg reg | length in UTF-8 bytes | ✓ |
| `0xA2` | `STR.EQ` | reg reg reg |  | ✓ |
| `0xA3` | `STR.NE` | reg reg reg |  | ✓ |
| `0xA4` | `STR.LT` | reg reg reg |  | ✓ |
| `0xA5` | `STR.LE` | reg reg reg |  | ✓ |
| `0xA6` | `STR.GT` | reg reg reg |  | ✓ |
| `0xA7` | `STR.GE` | reg reg reg |  | ✓ |
| `0xA8` | `SELECT` | reg reg reg reg | d = cond ? a : b (equal types) | ✓ |

Conversion rules: `i64→i32` keeps the low 32 bits; float→int saturates and maps NaN to 0; `i32→bool` is
`≠ 0`. To-string conversions are decimal; floats use the shortest digits that round-trip (with a
`.0` if integral); `bool` is `true`/`false`.

### Aggregates, objects, containers, boxing, delegates **[spec only]**

| Code | Mnemonic | Operands | Meaning | Ref |
| --- | --- | --- | --- | --- |
| `0xB0` | `STRUCT.new` | reg type (regs) | build an immutable struct from field registers |  |
| `0xB1` | `STRUCT.get` | reg reg uimm | read field |  |
| `0xB2` | `STRUCT.with` | reg reg uimm reg | copy with one field replaced |  |
| `0xB8` | `OBJ.new` | reg type | allocate object with default fields |  |
| `0xB9` | `FIELD.get` | reg reg uimm | read field (traps on null) |  |
| `0xBA` | `FIELD.set` | reg uimm reg | write field (traps on null) |  |
| `0xBB` | `IS.inst` | reg reg type | d:bool = a is instance of type |  |
| `0xBC` | `CAST` | reg reg type | checked cast; traps on failure |  |
| `0xBD` | `CAST.try` | reg reg type | cast or null |  |
| `0xBE` | `REF.eq` | reg reg reg | reference equality |  |
| `0xBF` | `REF.isnull` | reg reg | d:bool = a is null |  |
| `0xC0` | `ARR.new` | reg type | new empty array of the type | ✓ |
| `0xC1` | `ARR.len` | reg reg | length | ✓ |
| `0xC2` | `ARR.get` | reg reg reg | d = a[i]; traps if out of range | ✓ |
| `0xC3` | `ARR.set` | reg reg reg | a[i] = v; traps if out of range | ✓ |
| `0xC4` | `ARR.push` | reg reg | append | ✓ |
| `0xC5` | `ARR.insert` | reg reg reg | insert at index (0..len) | ✓ |
| `0xC6` | `ARR.remove` | reg reg | remove at index | ✓ |
| `0xC7` | `ARR.clear` | reg | remove all | ✓ |
| `0xC8` | `ARR.clone` | reg reg | shallow copy | ✓ |
| `0xC9` | `ARR.pop` | reg reg | remove and return last; traps if empty | ✓ |
| `0xCC` | `MAP.new` | reg type | new empty map |  |
| `0xCD` | `MAP.len` | reg reg | count |  |
| `0xCE` | `MAP.get` | reg reg reg | d = m[k]; traps if missing |  |
| `0xCF` | `MAP.tryget` | reg reg reg reg | d (default if missing), found:bool, m, k |  |
| `0xD0` | `MAP.set` | reg reg reg | insert or replace (insertion order kept) |  |
| `0xD1` | `MAP.has` | reg reg reg | d:bool |  |
| `0xD2` | `MAP.remove` | reg reg reg | d:bool removed, m, k |  |
| `0xD3` | `MAP.keyat` | reg reg reg | i-th key in insertion order |  |
| `0xD4` | `MAP.valat` | reg reg reg | i-th value in insertion order |  |
| `0xD5` | `MAP.clear` | reg | remove all |  |
| `0xD6` | `SET.new` | reg type | new empty set |  |
| `0xD7` | `SET.len` | reg reg | count |  |
| `0xD8` | `SET.add` | reg reg reg | d:bool added, s, v |  |
| `0xD9` | `SET.has` | reg reg reg | d:bool |  |
| `0xDA` | `SET.remove` | reg reg reg | d:bool removed |  |
| `0xDB` | `SET.at` | reg reg reg | i-th element in insertion order |  |
| `0xDC` | `SET.clear` | reg | remove all |  |
| `0xDE` | `ANY.box` | reg reg | box a value with its static type |  |
| `0xDF` | `ANY.unbox` | reg reg valtype | unbox to the type; traps on mismatch |  |
| `0xE0` | `ANY.tryunbox` | reg reg reg valtype | d, ok:bool, any, type |  |
| `0xE1` | `ANY.is` | reg reg valtype | d:bool = box holds that type |  |
| `0xE4` | `DELG.new` | reg type fn uimm | d, delegate type, function, target register+1 (0 = unbound) |  |
| `0xE6` | `DISP.new` | reg type | new empty dispatcher |  |
| `0xE7` | `DISP.bind` | reg reg | add delegate to the end |  |
| `0xE8` | `DISP.unbind` | reg reg | remove first equal delegate |  |
| `0xE9` | `DISP.broadcast` | reg (regs) | call every bound delegate in order |  |
| `0xEA` | `DISP.clear` | reg | remove all |  |
| `0xEB` | `DISP.count` | reg reg | number bound |  |

Notes. `STRUCT.*` operate on immutable values; `STRUCT.with` allocates a new value. `CAST` traps when the
object is not an instance of the target type; `CAST.try` yields `null`. `ARR.get`/`set`/`remove`/`insert` trap
on a bad index; `ARR.pop` traps when empty. `MAP.get` traps on a missing key, `MAP.tryget` does not.
`MAP.keyat`/`valat` and `SET.at` index in insertion order. `ANY.box` records the static type of its source;
`ANY.unbox` traps on mismatch. `DISP.broadcast` calls handlers in binding order and starts latent
handlers as new fibers.

## How graphs lower to bytecode

The compiler (reference: `wiret_ref/compiler.py`) follows these rules, which are part of the
specification because they define observable behaviour (evaluation order, node maps):

1. **Expand macros.** Each macro node is replaced by a clone of its graph with ids prefixed by
   the node id (`loop/`), type parameters substituted, and two kinds of *binding stubs*: entry stubs
   `loop!in` copy the macro's data inputs into registers; exit stubs `loop!body` compute that exit's data
   results and then continue to whatever the macro's exec output is wired to.
2. **Allocate registers.** Parameters take `r0…`. Locals follow, initialised at function entry. The output
   pins of every impure node get a dedicated register that lives for the whole function. Pure results
   are temporaries released after their consumer.
3. **Emit impure nodes as code blocks, in execution order.** For each impure node: emit its *pure
   cone* (the pure nodes feeding its inputs, dependencies first, each once), then the node itself.
   Follow the primary exec wire (`then`, or `Branch`'s `then`) as a fall-through; other targets become
   labels. A node reached again emits a `JMP` to its existing label.
4. **Sequence contexts.** The compiler tracks a stack of pending `Sequence` continuations while walking
   the exec graph. When a path ends it resumes the next branch of the innermost sequence. A node
   reachable under two different stacks is emitted twice; the last branch of a sequence pops its entry,
   so loop bodies do not grow the stack. Nesting deeper than 12 is `E0305`.
5. **Switch.** Dense `0..n-1` cases become `SWITCH`; others compare in sequence.
6. **Record the node map.** Every instruction is tagged with the node that emitted it.
7. **Assemble.** Branch offsets are resolved by iterating instruction sizes to a fixed point (LEB128
   offsets change size).

Equivalent text-to-bytecode behaviour is therefore: *same semantic graph ⇒ same bytecode*. Layout, metadata,
node order and node ids do not influence the instruction stream (ids only appear in custom sections).

## Versioning and extension

* The version word changes only for incompatible changes. Additive changes use new opcodes in the
  reserved prefix space, announced by a custom section `wiret.features` (list of feature names); a runtime
  must refuse a module requiring an unknown feature.
* Planned: `i8/i16/u8` types, `v128` vectors, tail calls, an exception-handling proposal for `try`-like nodes,
  and a `wiret.debug` section with source graph hashes.


---

# Runtime API

`libwiret` is the embeddable runtime: a verifier, interpreter, garbage collector, fiber scheduler and a
C API (`wiret.h`). Its shape follows the Lua C API: a small set of functions, a *typed value stack* for
exchanging values with scripts, protected calls, registry references, and natives written as C
functions. The header ships with this specification and compiles cleanly as C99 and C++17.

The compiler is a separate library (`libwiretc`, see Tooling): a game or app that only loads
precompiled `.wirb` files links `libwiret` alone.

## Concepts

| Object | Role | Lua analogue |
| --- | --- | --- |
| `wiret_VM` | The heap, the module registry, registered natives, GC state, limits. Single-threaded. | the global state |
| `wiret_Module` | A loaded, verified, immutable image; after `instantiate` it also owns globals. | a loaded chunk + its upvalues |
| `wiret_Fiber` | One thread of execution (call stack) plus the host *value stack*. `wiret_main(vm)` is the always-present main fiber. | `lua_State` / coroutine |
| `wiret_Sched` | Optional scheduler that resumes fibers each tick and implements `std.delay`. | – |

**Typed values.** Unlike Lua, every value on the stack has a static Wiret type (`wiret_type`,
`wiret_typename`). A call is checked against the function's signature, so passing a string where an `i32`
is expected fails with `WIRET_ERR_TYPE` before any script code runs.

**Stack indices.** `1` is the first slot of the current frame, `-1` the top. Natives see their arguments in
`1..n`. Pointers returned by `wiret_tolstring`/`wiret_pushstring` stay valid while the value is on the
stack (or otherwise reachable) and are never invalidated by a GC.

**Errors.** Functions returning `wiret_Status` report failure by value. Functions that *raise*
(`wiret_error`, `wiret_check*`, `wiret_call`) unwind to the innermost `wiret_pcall` /`wiret_resume`,
implemented with `setjmp/longjmp` in C builds and with exceptions when `WIRET_USE_EXCEPTIONS` is
defined. Natives written in C++ must not let their own exceptions cross the boundary.

## Quick start

```c
#include "wiret.h"

static int host_log(wiret_Fiber *F, void *ud) {
  size_t n; const char *s = wiret_checklstring(F, 1, &n);   /* arg 1, must be a string */
  printf("%s%.*s\n", (const char *)ud, (int)n, s);
  return 0;                                                  /* number of results pushed */
}

int main(void) {
  wiret_VM *vm = wiret_vm_new(NULL);                         /* defaults */
  wiret_Fiber *F = wiret_main(vm);
  wiret_register(vm, "std.print", "(string)->()", host_log, "[wiret] ", 0);

  wiret_Module *m; wiret_Diag diag;
  if (wiret_module_load(vm, image, size, "flow", 0, &m, &diag) != WIRET_OK ||
      wiret_module_instantiate(F, m, &diag) != WIRET_OK) {
    fprintf(stderr, "%s (in %s at %s)\n", diag.message, diag.function, diag.node);
    return 1;
  }

  wiret_getexport(F, m, "SumTo");          /* push the function            */
  wiret_pushi32(F, 100);                   /* push the argument            */
  if (wiret_pcall(F, 1, 1) == WIRET_OK)    /* 1 argument, 1 result         */
    printf("%d\n", wiret_checki32(F, -1)); /* 5050                         */
  wiret_pop(F, 1);

  wiret_vm_free(vm);
}
```

The complete program is `examples/host_example.c`.

## Lifecycle: load, link, run

1. **`wiret_module_load`** decodes and *validates* the image (see Bytecode → Validation). Nothing runs.
   Failure returns `WIRET_ERR_LOAD` or `WIRET_ERR_VERIFY` and fills `wiret_Diag` (message, function, node id,
   pc). Load is safe on hostile input.
2. **Register natives** (`wiret_register`, `wiret_register_lib`, `wiret_open_std`) before instantiation.
   Imports are resolved by name **and signature**; there is no ambient authority. A module can only call what
   the host registered.
3. **`wiret_module_instantiate`** resolves imports (other loaded modules by name, then natives), allocates
   globals with their initial values, and runs the start function. It needs a fiber because the start
   function may call natives.
4. **Call** exports with `wiret_getexport` + `wiret_pcall` (or run them on a fiber).
5. **`wiret_module_release`** drops the host's reference; the VM frees modules at `wiret_vm_free`.

## Natives

A native is `int fn(wiret_Fiber *F, void *ud)`. The VM has already checked the arguments against the declared
signature; the native pushes exactly the declared number of results and returns that count.

```c
static int host_clamp(wiret_Fiber *F, void *ud) {
  wiret_F32 x = wiret_checkf32(F, 1), lo = wiret_checkf32(F, 2), hi = wiret_checkf32(F, 3);
  wiret_pushf32(F, x < lo ? lo : x > hi ? hi : x);
  return 1;
}
...
wiret_register(vm, "game.clamp", "(f32,f32,f32)->(f32)", host_clamp, NULL,
               WIRET_NATIVE_PURE | WIRET_NATIVE_DETERMINISTIC);
```

* **Signature strings** use the type syntax of `.wiret` files: `"(string,array<i32>)->(bool,i32)"`.
* **Flags.** `PURE` lets the compiler and graph editor draw the native as a pure node; `LATENT` allows
  `wiret_yield`; `DETERMINISTIC` is required when the VM is configured with `WIRET_CFG_DETERMINISTIC`.
* A native declared in a `.wiret` file as `extern function` must match the registered signature and
  flags exactly, or linking fails with `WIRET_ERR_LINK`.
* **Errors from natives**: `return wiret_error(F, "texture %s not found", name);` raises a trap that
  carries the script's node id in its traceback.
* `wiret_register_lib` registers an array of `wiret_NativeReg` at once (like `luaL_Reg`).
  `wiret_open_std` registers the standard library: `std.print`, `std.math.*`, `std.string.*`, `std.time.now`,
  `std.delay`, `std.wait_frames`, `std.yield`.

### Host handles

Host objects (a texture, an entity) appear in scripts as values of an `extern type`. The host registers the
type once and creates handles:

```c
typedef struct { int id; } Texture;
static void tex_free(void *p) { release_texture(((Texture *)p)->id); }

wiret_HostType tt = { "host.Texture", sizeof(Texture), tex_free, NULL };
wiret_register_hosttype(vm, &tt);

Texture *t = wiret_pushhost(F, "host.Texture");     /* allocates, pushes, returns payload */
t->id = load_texture(path);
```

`wiret_checkhost(F, idx, "host.Texture")` retrieves the payload in a native, raising a type error for any
other value. The GC calls `finalize` once when the handle becomes unreachable. If a payload holds
references to script values, supply `trace` and call `wiret_mark` on each.

## Passing values

| Direction | Functions |
| --- | --- |
| host → script | `wiret_pushbool/i32/i64/f32/f64/string/lstring/fstring/null`, `wiret_pushany` |
| script → host (non-raising) | `wiret_tobool/toi32/…/tolstring(F, idx, &ok)`, `wiret_type`, `wiret_isnull` |
| script → host (raising) | `wiret_checki32 …` for natives |
| structs, objects | `wiret_pushstruct`, `wiret_newobject`, `wiret_getfield`, `wiret_setfield`, `wiret_getmethod` |
| arrays | `wiret_newarray("i32")`, `wiret_arraylen/get/set/push` |
| maps | `wiret_newmap("string","i32")`, `wiret_mapget/set/at/len` |

**Value vs. reference semantics.** Structs are values: `wiret_setfield` on a struct replaces the stack
slot with a modified copy. Objects, arrays, maps, sets and host handles are references: changes are
visible to every holder. Strings are immutable.

```c
wiret_newarray(F, "i32");                       /* [.. arr]               */
for (int i = 0; i < 4; i++) { wiret_pushi32(F, i * 10); wiret_arraypush(F, -2); }
wiret_getexport(F, m, "SumArray");              /* [.. arr fn]            */
wiret_insert(F, -2);                            /* [.. fn arr]            */
wiret_pcall(F, 1, 2);                           /* [.. sum count]         */
```

## Calling into Wiret

`wiret_pcall(F, nargs, nresults)` expects `[… fn arg1 … argN]`, checks the arguments against the
signature, runs to completion and leaves `nresults` values (which must equal the function's declared result
count). On failure the stack top holds an error string; `wiret_traceback` renders it with
function and **graph node ids**:

```
trap: integer divide by zero
    at Divide (node %div)
    at Main (node %call_divide)
```

`wiret_call` is the unprotected variant for use inside natives (errors propagate to the outer
`pcall`). Re-entrancy is allowed: a native may call back into Wiret on the same fiber, to a depth bounded by
`max_call_depth`.

Events are exported functions, so the host raises them the same way:
`wiret_getexport(F, m, "OnHit"); wiret_pushi32(F, 5); wiret_pcall(F, 1, 0);`. For events on a class instance,
`wiret_getmethod(F, obj_idx, "Interact")` pushes a delegate already bound to the object. **[spec only]**

## Fibers and latent calls

A **latent** function (one that calls a latent native such as `std.delay`) can suspend. Run those on their
own fiber; the fiber keeps its call stack while suspended:

```c
wiret_Fiber *co = wiret_fiber_new(vm);
wiret_getexport(co, m, "OpenTemporarily");  wiret_pushf32(co, 2.5f);
int nres; wiret_Status st = wiret_resume(co, 1, &nres);   /* first resume starts the call */
while (st == WIRET_YIELD) {
  /* ... do other work; later: */
  st = wiret_resume(co, 0, &nres);
}
```

* A latent native suspends with `return wiret_yield(F, nresults);`. It can record *why* with
  `wiret_setwait(F, tag, data)`, which the host reads with `wiret_getwait` to decide when to resume
  (a timer, a network reply, a gameplay event).
* **Built-in scheduler.** `wiret_sched_new`, `wiret_sched_start(s, fiber, nargs)` and
  `wiret_sched_tick(s, dt)` implement `std.delay(seconds)`, `std.wait_frames(n)` and `std.yield()` so a game only
  has to call `tick` once per frame.
* `wiret_cancel(F)` unwinds a suspended fiber at its next resume (finalizers still run).
* Latent functions can only be called from latent functions, so a *non-latent* call never suspends and the
  host can rely on `wiret_pcall` returning `WIRET_OK` or an error, never `WIRET_YIELD`. Calling a latent
  export through `wiret_pcall` returns `WIRET_ERR_TYPE`.

## Memory and the garbage collector

Heap values (strings, structs, objects, arrays, maps, sets, delegates, host handles) are managed by an
incremental, precise, non-moving mark-and-sweep collector. Roots are fiber stacks, module globals and
registry references.

* **Keeping values alive from C.** `wiret_ref(F)` pops the top value and returns an integer handle; `wiret_getref`
  pushes it again; `wiret_unref` releases it. Anything not referenced from the stack, globals or a ref may be collected.
* `wiret_gc(vm, op, arg)`: `COLLECT` (full), `STOP`/`RESTART`, `STEP`, `BYTES` (current heap size),
  `SETPAUSE`, `SETSTEPMUL`. Games typically `STEP` a little every frame.
* `wiret_Config.alloc` supplies your allocator (arenas, tracking); `memory_limit` makes allocation fail
  with `WIRET_ERR_MEMORY` instead of growing without bound.

## Sandboxing and limits

| Limit | Setting | On breach |
| --- | --- | --- |
| Instructions per resume | `wiret_Config.default_budget`, `wiret_setbudget` | `WIRET_ERR_BUDGET` |
| Memory | `memory_limit`, `wiret_setmemlimit` | `WIRET_ERR_MEMORY` |
| Call depth | `max_call_depth` | `WIRET_ERR_STACK` |
| Host stack size | `max_stack_slots` | `WIRET_ERR_STACK` |
| Capabilities | only registered natives resolve | `WIRET_ERR_LINK` |
| Nondeterminism | `WIRET_CFG_DETERMINISTIC` | natives without the flag refuse to link |

A script cannot allocate unbounded memory, loop forever, or reach the filesystem or network unless the
host hands it a native that can.

## Debugging and visual tooling

Every frame knows its **graph node**. Editors build their debugger on these calls:

* `wiret_sethook(F, fn, mask, ud)` with `WIRET_HOOK_NODE` fires each time execution enters a new node
  (macro-internal nodes included, e.g. `loop/check`), `CALL`/`RETURN` on function boundaries and `TRAP` on errors.
* `wiret_getstack(F, level, &info)` returns module, function, node id and pc for any frame.
* `wiret_getpin(F, level, "add_1", "result")` pushes the current value of an output pin so the editor can show
  values on wires (the "data probe" of Blueprint debugging).
* `wiret_setbreak(module, "Fib", "is_base", 1)` plants a breakpoint on a node (it patches the first instruction
  to `BREAK`; the hook receives `WIRET_HOOK_NODE`).
* Without debug info (`WIRET_CFG_NO_DEBUG_INFO`) the node fields are `NULL`.

## Threads and ABI

* A VM and everything reachable from it must be used from one thread at a time. Use one VM per thread;
  `wiret_Module` images may be loaded into several VMs from the same bytes (`WIRET_LOAD_BORROW`).
* No function is async-signal-safe. Do not call the API from a finalizer except `wiret_unref`.
* The C ABI is stable within a major version: structs with a `struct_size` field (`wiret_Config`) can grow;
  enums only gain values at the end. `WIRET_BYTECODE_VERSION` in the header must equal the version the
  module was compiled for.

## Differences from the Lua C API

| Lua | Wiret |
| --- | --- |
| Dynamically typed stack | Statically typed values; calls are checked against signatures |
| `lua_getglobal` / tables | Exports and fields by name; arrays/maps are typed containers |
| `lua_pushcclosure` upvalues | one `void *ud` per native; host handles for state |
| `lua_pcall` with message handler | `wiret_pcall` + `wiret_traceback` (node ids) |
| Coroutines created by script | Fibers created by the host; script code only suspends in `latent` calls |
| `lua_sethook` per line | `wiret_sethook` per **node** |
| `luaL_Reg` | `wiret_NativeReg` with signature strings |
| `lua_gc` | `wiret_gc` |
| Userdata with metatables | `wiret_HostType` with finalizer and trace |


---

# Tooling and workflow

## The toolchain

| Tool | Purpose | Reference implementation |
| --- | --- | --- |
| `wiret fmt` | Canonical formatting (idempotent) | `python3 -m wiret_ref fmt FILE` |
| `wiret check` | Parse, resolve, type-check, lower, verify; prints diagnostics | `… check FILE` |
| `wiret build` | `.wiret` → `.wirb` | `… build FILE [OUT]` |
| `wiret dis` | Disassemble a `.wirb` (or build+disassemble a `.wiret`) with node markers | `… dis FILE` |
| `wiret run` | Compile and run an export with the standard natives | `… run FILE Export args…` |
| `wiret svg` | Draw a function from its layout block | `… svg FILE Function > graph.svg` |
| `wiret hash` | Semantic hash (see below) **[spec only]** | – |
| `wiret diff` / `merge` | Node-level diff and Git merge driver **[spec only]** | – |
| `wiret fmt --reading-order` | Reorder nodes into depth-first execution order **[spec only]** | – |

Run the reference tools from `reference/`:

```
python3 -m wiret_ref check ../examples/flow.wiret
python3 -m wiret_ref run   ../examples/flow.wiret SumTo 100        # 5050
python3 -m wiret_ref run   ../examples/flow.wiret FizzBuzz 15
python3 -m wiret_ref svg   ../examples/fibonacci.wiret Fib > fib.svg
python3 tests.py                                                    # conformance suite
```

## Compiler API (`libwiretc`) **[spec only]**

The compiler is a library so that editors, build systems and servers can call it in-process.

```c
typedef struct wiretc_Diagnostic {
  const char *code;        /* "E0102" */
  int         severity;    /* 0 error, 1 warning, 2 note */
  const char *message;
  const char *module, *function, *node, *pin;   /* any may be NULL; ids use macro paths: "loop/check" */
  int         line, column;                      /* position in the .wiret text, 1-based */
} wiretc_Diagnostic;

typedef struct wiretc_Result {
  void *image; size_t image_size;                /* the .wirb, NULL on error */
  wiretc_Diagnostic *diags; size_t ndiags;
  uint8_t semantic_hash[32];
} wiretc_Result;

wiretc_Status wiretc_compile(const char *text, size_t len, const wiretc_Options *opts, wiretc_Result *out);
wiretc_Status wiretc_format(const char *text, size_t len, char **out, size_t *out_len);
void          wiretc_result_free(wiretc_Result *r);
```

Options include module search paths (for `use`), a debug-info level (`none`, `nodes`, `nodes+pins`), and an
optimisation level. Diagnostics are the table in [Text format](02-text-format.md#diagnostics). All
diagnostics are *recoverable*: the compiler continues after an error where it can, so an editor can show every
problem at once.

### Optimisations

Optimisations must preserve the observable behaviour and the node map's meaning (every instruction still
maps to *a* node). Specified passes: constant folding of pure nodes with literal inputs, common
sub-expression elimination **within one cone only** (pure nodes are re-evaluated per consumer by definition, so
cross-consumer CSE must prove no state is written between), dead pure-node elimination (a pure node no one
reads is never emitted: the reference compiler already does this implicitly), jump threading, and
register coalescing. A `-O0` build emits exactly what the lowering rules in *Bytecode* describe.

## Semantic hash

`semantic_hash` is SHA-256 over a canonical serialization of the program that **excludes** layout blocks,
`meta` lines, attribute lists, comments and declaration order, and **sorts** declarations by name and
nodes by id. Two files with the same semantic hash compile to the same instruction stream. Uses:

* CI can skip rebuilds and skip re-running tests when a commit only moved nodes or edited documentation.
* Caches (hot reload, asset pipelines) key on it.
* Review tools can label a diff "layout only" or "metadata only".

The reference test-suite checks the underlying property: removing the layout and metadata, or reversing the
node order, does not change a single instruction.

## Working with Git

Recommended `.gitattributes`:

```
*.wiret text eol=lf diff=wiret merge=wiret
*.wirb  binary
```

Why the format merges well:

1. **One owner per wire.** A data wire is a line in its consumer; an exec wire is a line in its producer.
   Two people rewiring different pins never touch the same line.
2. **Stable ids with random suffixes.** Ids are never renumbered, and a new node's id is unlikely to collide
   with a teammate's new node.
3. **Layout is separate.** Dragging nodes edits the `layout` block only; logic edits never touch it.
   Layout lines are one-per-node, so two people moving different nodes do not conflict.
4. **Canonical text.** Formatting differences cannot appear.

### Node-level merge (specified behaviour of `wiret merge`)

A three-way merge on the parse tree, keyed rather than line-based:

| Unit | Key |
| --- | --- |
| declaration | kind + name |
| node | function + `%id` |
| node item | node + (`in`/`exec`/`prop`/`meta`) + pin or key |
| layout entry | function + `%id` (or box title) |

* Changes to different keys merge automatically; added nodes in both branches are kept.
* **Conflicts**: the same item changed to different values; a node deleted on one side and modified on the
  other; the same exec output connected to two targets after merge (an *invariant* conflict: a merged
  result that is not a valid graph is reported even though no line collided).
* Layout conflicts resolve to "theirs for the node's position, then the editor's auto-layout nudge for overlaps"
  and are never blocking.
* Unresolvable conflicts are written as ordinary text conflict markers around the offending node block, so
  any text merge tool can finish the job.

## Working with language models

The format was shaped for reading and writing by models:

* **Everything is named and typed.** No positional pins, no implicit wildcard resolution, no coordinates needed
  to understand logic (a model may omit the `layout` block; editors auto-layout and fill it in).
* **Local edits.** Adding a node is: one node block + one changed line in its neighbour. Models can emit unified
  diffs against the file safely.
* **Closed-loop correctness.** The compiler's diagnostics (`E0102` + function + node + pin) are
  machine-readable and designed to be pasted back to the model verbatim; the reference test-suite covers a
  representative error for each class. Suggested loop: *generate → `wiret check` → feed diagnostics back → repeat*.
* **Explanation.** `wiret dis` output with `; --- %node` markers lets a model (or a person) relate behaviour to nodes.
* A compact prompt contract: *"Return a complete `.wiret` file or a unified diff. Use only node kinds listed in
  Standard nodes. Give every node a unique `%slug_xxxx` id. Do not renumber ids. Bind every required input.
  Connect every non-terminal exec output or leave it deliberately unconnected."*

## Contract for graph editors

An editor is conformant if it:

1. Parses any valid file and writes back a file whose **semantic hash is unchanged** unless the user changed logic.
2. Preserves node and item order, unknown `meta` keys, and unknown layout attributes.
3. Writes canonical text (or calls `wiretc_format`).
4. Writes integer layout coordinates and **keeps personal view state out of the file**.
5. Never reuses a deleted node's id within the same file's history window (use random suffixes).
6. Surfaces compiler diagnostics on the named node/pin, including macro paths (`loop/check` highlights the
   macro node `loop` and, if expanded in the view, the inner node).
7. Shows wildcard/generic nodes with their resolved type arguments and writes them explicitly.

## Reference implementation

`reference/wiret_ref` is a ~2,500-line Python implementation used to validate this specification:

| Module | Spec chapter | Contents |
| --- | --- | --- |
| `syntax.py` | Text format | lexer, parser (the full grammar), canonical formatter |
| `compiler.py` | Standard nodes, Bytecode | macro expansion, validation, lowering, assembly |
| `stdlib.py` | Standard nodes | `std.flow` written in Wiret |
| `ops.py` | Bytecode | the opcode table that generates the reference tables in this document |
| `binary.py` | Bytecode | encoder, decoder, verifier, disassembler |
| `vm.py` | Bytecode, Runtime API | interpreter, traps with node ids, budget, node hook |
| `render.py` | Text format | draws a function from its `layout` block |
| `tests.py` | all | conformance tests |

What it covers: the whole text grammar (declarations of structs, enums, classes, interfaces, delegates are
parsed and formatted), functions, events, macros with generics and state, all arithmetic/logic/string/array
nodes, calls and natives, `Sequence`/`Branch`/`Switch`, the binary format with all sections, validation, and
execution of 138 of the 181 defined opcodes. Not covered (specified only): object, struct, map/set,
delegate/dispatcher and boxing instructions and nodes, fibers and latent suspension in the interpreter, and
the C runtime.

The test suite (`python3 tests.py`) checks: LEB128; formatter idempotence and canonical form for every
example; program results (Fibonacci, loops, FizzBuzz, arrays, Collatz, DoOnce with reset, Sequence order,
traps naming the node); layout- and order-independence of code generation; verifier rejection of type errors,
fall-through, bad targets and latent misuse; one diagnostic per error class; instruction budgets; and a
fuzz run of 4,000 corrupted modules that must be rejected cleanly.

## Roadmap and open questions

**Next, in order of dependency**

1. C runtime implementing `wiret.h` (verifier + interpreter + GC) validated against `tests.py` by a shared
   conformance corpus of `.wiret` programs with expected outputs.
2. Classes, interfaces, structs and containers in the reference compiler (the instruction set is specified).
3. Fibers and the scheduler; latent natives.
4. `wiret merge` / `wiret diff` and the semantic hash.
5. A bytecode JIT or faster interpreter dispatch (the encoding is deliberately easy to pre-decode).

**Decisions worth revisiting with real users**

* *Reference vs. value arrays.* Blueprint arrays are values; Wiret's are references. A copy-on-write
  value mode could be added per pin without changing the bytecode.
* *Macro input snapshots.* Safer for newcomers, but advanced users sometimes want Blueprint's
  re-evaluating inputs; a `live` annotation on a macro parameter could provide it.
* *Per-function graphs.* Blueprint's single Event Graph lets many events share nodes. Wiret requires a shared
  node to be a function that events call. This keeps entry points explicit and diffs local; an `EventGraph`
  construct that desugars to that is possible.
* *Exec reroute knots.* They are an editor concern, stored as layout waypoints on a wire (not specified yet).
* *Exceptions.* Traps end the fiber. A structured `try` node would need an unwinding story in the bytecode.
* *Smaller integer types and vectors.* Needed by many game hosts; reserved in the bytecode.

---

`README.md`

# Wiret (draft 0.1)

Visual scripting in a text format: `.wiret` text -> `.wirb` typed bytecode -> embeddable runtime.

* `index.md`  – the full specification in one Markdown file (also published as the docs site)
* `docs/`          – the six chapters
* `include/wiret.h`– the C runtime API (compiles as C99 and C++17)
* `examples/`      – fibonacci, flow (loops, FizzBuzz, arrays, DoOnce, Sequence), door (classes/events, syntax only), host_example.c
* `reference/`     – Python reference implementation + `tests.py` (57 checks); `python3 tests.py`
* `generated/`     – compiled .wirb, disassembly listings, graph SVGs

---

`build/fib.dis.txt`

```
; module examples.fibonacci

func f0 Fib pure (i32) -> (i32)
  regs: r0:i32, r1:i32, r2:bool, r3:i32, r4:i32, r5:i32, r6:i32, r7:i32, r8:i32
  ; --- %lt
         CONST.i32   r1 2
         LT.i32      r2 r0 r1
  ; --- %is_base
         JMPIFNOT    r2 @000d
  ; --- %ret_n
         RET         (r0)
  ; --- %n_minus_1
  @000d: CONST.i32   r1 1
         SUB.i32     r3 r0 r1
  ; --- %fib_1
         CALL        Fib (r3) (r4)
  ; --- %n_minus_2
         CONST.i32   r5 2
         SUB.i32     r6 r0 r5
  ; --- %fib_2
         CALL        Fib (r6) (r7)
  ; --- %sum
         ADD.i32     r8 r4 r7
  ; --- %ret_sum
         RET         (r8)
```

---

`build/fib.svg`

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="-60 -110 1360 730" width="1360" height="730" font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="11">
<rect x="-60" y="-110" width="1360" height="730" fill="#1b1e24"/>
<rect x="-20" y="-70" width="1180" height="330" rx="6" fill="#3a5f8a" fill-opacity="0.16" stroke="#3a5f8a" stroke-opacity="0.6"/>
<text x="-10" y="-52" fill="#3a5f8a" font-size="13" font-weight="600">Base case</text>
<path d="M200.0,61.0 C240.0,61.0 220.0,199.0 260.0,199.0" fill="none" stroke="#4fc3a1" stroke-width="1.6" stroke-linecap="round"/>
<path d="M460.0,199.0 C500.0,199.0 480.0,61.0 520.0,61.0" fill="none" stroke="#d9534f" stroke-width="1.6" stroke-linecap="round"/>
<path d="M200.0,61.0 C530.0,61.0 530.0,21.0 860.0,21.0" fill="none" stroke="#4fc3a1" stroke-width="1.6" stroke-linecap="round"/>
<path d="M200.0,61.0 C240.0,61.0 220.0,379.0 260.0,379.0" fill="none" stroke="#4fc3a1" stroke-width="1.6" stroke-linecap="round"/>
<path d="M200.0,61.0 C240.0,61.0 220.0,539.0 260.0,539.0" fill="none" stroke="#4fc3a1" stroke-width="1.6" stroke-linecap="round"/>
<path d="M460.0,379.0 C500.0,379.0 480.0,379.0 520.0,379.0" fill="none" stroke="#4fc3a1" stroke-width="1.6" stroke-linecap="round"/>
<path d="M460.0,539.0 C500.0,539.0 480.0,539.0 520.0,539.0" fill="none" stroke="#4fc3a1" stroke-width="1.6" stroke-linecap="round"/>
<path d="M720.0,379.0 C760.0,379.0 760.0,459.0 800.0,459.0" fill="none" stroke="#4fc3a1" stroke-width="1.6" stroke-linecap="round"/>
<path d="M720.0,539.0 C760.0,539.0 760.0,481.0 800.0,481.0" fill="none" stroke="#4fc3a1" stroke-width="1.6" stroke-linecap="round"/>
<path d="M1000.0,459.0 C1040.0,459.0 1020.0,441.0 1060.0,441.0" fill="none" stroke="#4fc3a1" stroke-width="1.6" stroke-linecap="round"/>
<path d="M200.0,39.0 C360.0,39.0 360.0,39.0 520.0,39.0" fill="none" stroke="#f2f2f2" stroke-width="2.6" stroke-linecap="round"/>
<path d="M720.0,39.0 C790.0,39.0 790.0,-1.0 860.0,-1.0" fill="none" stroke="#f2f2f2" stroke-width="2.6" stroke-linecap="round"/>
<path d="M720.0,61.0 C890.0,61.0 890.0,419.0 1060.0,419.0" fill="none" stroke="#f2f2f2" stroke-width="2.6" stroke-linecap="round"/>
<rect x="0" y="0" width="200" height="80" rx="7" fill="#2a2e37" stroke="#434a57"/>
<path d="M0,7 a7,7 0 0 1 7,-7 h186 a7,7 0 0 1 7,7 v21 h-200 z" fill="#c0392b" fill-opacity="0.85"/>
<text x="10" y="18" fill="#fff" font-weight="600">Entry</text>
<path d="M195,33.0 h6 l5,6 l-5,6 h-6 z" fill="#f2f2f2"/>
<text x="188" y="43.0" fill="#d6dae0" text-anchor="end">then</text>
<circle cx="200" cy="61.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="188" y="65.0" fill="#d6dae0" text-anchor="end">n</text>
<rect x="260" y="160" width="200" height="80" rx="7" fill="#2a2e37" stroke="#434a57"/>
<path d="M260,167 a7,7 0 0 1 7,-7 h186 a7,7 0 0 1 7,7 v21 h-200 z" fill="#4f9d69" fill-opacity="0.85"/>
<text x="270" y="178" fill="#fff" font-weight="600">Lt&lt;i32&gt;</text>
<circle cx="260" cy="199.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="272" y="203.0" fill="#d6dae0" text-anchor="start">a</text>
<circle cx="260" cy="221.0" r="5" fill="#1b1e24" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="272" y="225.0" fill="#d6dae0" text-anchor="start">b = 2</text>
<circle cx="460" cy="199.0" r="5" fill="#d9534f" stroke="#d9534f" stroke-width="1.6"/>
<text x="448" y="203.0" fill="#d6dae0" text-anchor="end">result</text>
<rect x="520" y="0" width="200" height="80" rx="7" fill="#2a2e37" stroke="#434a57"/>
<path d="M520,7 a7,7 0 0 1 7,-7 h186 a7,7 0 0 1 7,7 v21 h-200 z" fill="#7f8c8d" fill-opacity="0.85"/>
<text x="530" y="18" fill="#fff" font-weight="600">Branch</text>
<path d="M515,33.0 h6 l5,6 l-5,6 h-6 z" fill="#f2f2f2"/>
<text x="532" y="43.0" fill="#d6dae0" text-anchor="start">in</text>
<circle cx="520" cy="61.0" r="5" fill="#d9534f" stroke="#d9534f" stroke-width="1.6"/>
<text x="532" y="65.0" fill="#d6dae0" text-anchor="start">condition</text>
<path d="M715,33.0 h6 l5,6 l-5,6 h-6 z" fill="#f2f2f2"/>
<text x="708" y="43.0" fill="#d6dae0" text-anchor="end">then</text>
<path d="M715,55.0 h6 l5,6 l-5,6 h-6 z" fill="#f2f2f2"/>
<text x="708" y="65.0" fill="#d6dae0" text-anchor="end">else</text>
<rect x="860" y="-40" width="200" height="80" rx="7" fill="#2a2e37" stroke="#434a57"/>
<path d="M860,-33 a7,7 0 0 1 7,-7 h186 a7,7 0 0 1 7,7 v21 h-200 z" fill="#c0392b" fill-opacity="0.85"/>
<text x="870" y="-22" fill="#fff" font-weight="600">Return</text>
<path d="M855,-7.0 h6 l5,6 l-5,6 h-6 z" fill="#f2f2f2"/>
<text x="872" y="3.0" fill="#d6dae0" text-anchor="start">in</text>
<circle cx="860" cy="21.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="872" y="25.0" fill="#d6dae0" text-anchor="start">result</text>
<rect x="260" y="340" width="200" height="80" rx="7" fill="#2a2e37" stroke="#434a57"/>
<path d="M260,347 a7,7 0 0 1 7,-7 h186 a7,7 0 0 1 7,7 v21 h-200 z" fill="#4f9d69" fill-opacity="0.85"/>
<text x="270" y="358" fill="#fff" font-weight="600">Sub&lt;i32&gt;</text>
<circle cx="260" cy="379.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="272" y="383.0" fill="#d6dae0" text-anchor="start">a</text>
<circle cx="260" cy="401.0" r="5" fill="#1b1e24" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="272" y="405.0" fill="#d6dae0" text-anchor="start">b = 1</text>
<circle cx="460" cy="379.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="448" y="383.0" fill="#d6dae0" text-anchor="end">result</text>
<rect x="260" y="500" width="200" height="80" rx="7" fill="#2a2e37" stroke="#434a57"/>
<path d="M260,507 a7,7 0 0 1 7,-7 h186 a7,7 0 0 1 7,7 v21 h-200 z" fill="#4f9d69" fill-opacity="0.85"/>
<text x="270" y="518" fill="#fff" font-weight="600">Sub&lt;i32&gt;</text>
<circle cx="260" cy="539.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="272" y="543.0" fill="#d6dae0" text-anchor="start">a</text>
<circle cx="260" cy="561.0" r="5" fill="#1b1e24" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="272" y="565.0" fill="#d6dae0" text-anchor="start">b = 2</text>
<circle cx="460" cy="539.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="448" y="543.0" fill="#d6dae0" text-anchor="end">result</text>
<rect x="520" y="340" width="200" height="58" rx="7" fill="#2a2e37" stroke="#434a57"/>
<path d="M520,347 a7,7 0 0 1 7,-7 h186 a7,7 0 0 1 7,7 v21 h-200 z" fill="#3b7dd8" fill-opacity="0.85"/>
<text x="530" y="358" fill="#fff" font-weight="600">Call&lt;@Fib&gt;</text>
<circle cx="520" cy="379.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="532" y="383.0" fill="#d6dae0" text-anchor="start">n</text>
<circle cx="720" cy="379.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="708" y="383.0" fill="#d6dae0" text-anchor="end">result</text>
<rect x="520" y="500" width="200" height="58" rx="7" fill="#2a2e37" stroke="#434a57"/>
<path d="M520,507 a7,7 0 0 1 7,-7 h186 a7,7 0 0 1 7,7 v21 h-200 z" fill="#3b7dd8" fill-opacity="0.85"/>
<text x="530" y="518" fill="#fff" font-weight="600">Call&lt;@Fib&gt;</text>
<circle cx="520" cy="539.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="532" y="543.0" fill="#d6dae0" text-anchor="start">n</text>
<circle cx="720" cy="539.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="708" y="543.0" fill="#d6dae0" text-anchor="end">result</text>
<rect x="800" y="420" width="200" height="80" rx="7" fill="#2a2e37" stroke="#434a57"/>
<path d="M800,427 a7,7 0 0 1 7,-7 h186 a7,7 0 0 1 7,7 v21 h-200 z" fill="#4f9d69" fill-opacity="0.85"/>
<text x="810" y="438" fill="#fff" font-weight="600">Add&lt;i32&gt;</text>
<circle cx="800" cy="459.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="812" y="463.0" fill="#d6dae0" text-anchor="start">a</text>
<circle cx="800" cy="481.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="812" y="485.0" fill="#d6dae0" text-anchor="start">b</text>
<circle cx="1000" cy="459.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="988" y="463.0" fill="#d6dae0" text-anchor="end">result</text>
<rect x="1060" y="380" width="200" height="80" rx="7" fill="#2a2e37" stroke="#434a57"/>
<path d="M1060,387 a7,7 0 0 1 7,-7 h186 a7,7 0 0 1 7,7 v21 h-200 z" fill="#c0392b" fill-opacity="0.85"/>
<text x="1070" y="398" fill="#fff" font-weight="600">Return</text>
<path d="M1055,413.0 h6 l5,6 l-5,6 h-6 z" fill="#f2f2f2"/>
<text x="1072" y="423.0" fill="#d6dae0" text-anchor="start">in</text>
<circle cx="1060" cy="441.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="1072" y="445.0" fill="#d6dae0" text-anchor="start">result</text>
</svg>
```

---

`build/fibonacci.wirb`

```hex
0057 5254 0100 0000 0106 0160 017f 017f
0201 0003 0301 0001 0401 0005 0701 0346
6962 0000 0601 0007 0100 0838 0136 0903
027f 017b 067f 1101 0228 0200 0104 0203
0601 0011 0101 2103 0001 0700 0103 0104
1105 0221 0600 0507 0001 0601 0720 0804
0706 0108 0026 0b77 6972 6574 2e6e 616d
6573 1265 7861 6d70 6c65 732e 6669 626f
6e61 6363 6901 0000 0346 6962 0061 0d77
6972 6574 2e6e 6f64 656d 6170 0902 6c74
0769 735f 6261 7365 0572 6574 5f6e 096e
5f6d 696e 7573 5f31 0566 6962 5f31 096e
5f6d 696e 7573 5f32 0566 6962 5f32 0373
756d 0772 6574 5f73 756d 0100 0900 0007
0103 0203 0307 0406 0507 0606 0704 0800
1a0a 7769 7265 742e 7069 6e73 0205 656e
7472 7901 6e01 0001 0000 01
```

---

`build/sumto.svg`

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="-40 -100 1040 420" width="1040" height="420" font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="11">
<rect x="-40" y="-100" width="1040" height="420" fill="#1b1e24"/>
<path d="M200.0,61.0 C240.0,61.0 220.0,83.0 260.0,83.0" fill="none" stroke="#4fc3a1" stroke-width="1.6" stroke-linecap="round"/>
<path d="M460.0,239.0 C500.0,239.0 460.0,239.0 500.0,239.0" fill="none" stroke="#4fc3a1" stroke-width="1.6" stroke-linecap="round"/>
<path d="M460.0,83.0 C500.0,83.0 460.0,261.0 500.0,261.0" fill="none" stroke="#4fc3a1" stroke-width="1.6" stroke-linecap="round"/>
<path d="M700.0,239.0 C740.0,239.0 720.0,141.0 760.0,141.0" fill="none" stroke="#4fc3a1" stroke-width="1.6" stroke-linecap="round"/>
<path d="M460.0,239.0 C610.0,239.0 610.0,1.0 760.0,1.0" fill="none" stroke="#4fc3a1" stroke-width="1.6" stroke-linecap="round"/>
<path d="M200.0,39.0 C240.0,39.0 220.0,39.0 260.0,39.0" fill="none" stroke="#f2f2f2" stroke-width="2.6" stroke-linecap="round"/>
<path d="M460.0,39.0 C610.0,39.0 610.0,119.0 760.0,119.0" fill="none" stroke="#f2f2f2" stroke-width="2.6" stroke-linecap="round"/>
<path d="M460.0,61.0 C610.0,61.0 610.0,-21.0 760.0,-21.0" fill="none" stroke="#f2f2f2" stroke-width="2.6" stroke-linecap="round"/>
<rect x="0" y="0" width="200" height="80" rx="7" fill="#2a2e37" stroke="#434a57"/>
<path d="M0,7 a7,7 0 0 1 7,-7 h186 a7,7 0 0 1 7,7 v21 h-200 z" fill="#c0392b" fill-opacity="0.85"/>
<text x="10" y="18" fill="#fff" font-weight="600">Entry</text>
<path d="M195,33.0 h6 l5,6 l-5,6 h-6 z" fill="#f2f2f2"/>
<text x="188" y="43.0" fill="#d6dae0" text-anchor="end">then</text>
<circle cx="200" cy="61.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="188" y="65.0" fill="#d6dae0" text-anchor="end">n</text>
<rect x="260" y="0" width="200" height="102" rx="7" fill="#2a2e37" stroke="#434a57"/>
<path d="M260,7 a7,7 0 0 1 7,-7 h186 a7,7 0 0 1 7,7 v21 h-200 z" fill="#5c6b7a" fill-opacity="0.85"/>
<text x="270" y="18" fill="#fff" font-weight="600">flow.ForLoop</text>
<path d="M255,33.0 h6 l5,6 l-5,6 h-6 z" fill="#f2f2f2"/>
<text x="272" y="43.0" fill="#d6dae0" text-anchor="start">in</text>
<circle cx="260" cy="61.0" r="5" fill="#1b1e24" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="272" y="65.0" fill="#d6dae0" text-anchor="start">first = 1</text>
<circle cx="260" cy="83.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="272" y="87.0" fill="#d6dae0" text-anchor="start">last</text>
<path d="M455,33.0 h6 l5,6 l-5,6 h-6 z" fill="#f2f2f2"/>
<text x="448" y="43.0" fill="#d6dae0" text-anchor="end">body</text>
<path d="M455,55.0 h6 l5,6 l-5,6 h-6 z" fill="#f2f2f2"/>
<text x="448" y="65.0" fill="#d6dae0" text-anchor="end">completed</text>
<circle cx="460" cy="83.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="448" y="87.0" fill="#d6dae0" text-anchor="end">index</text>
<rect x="260" y="200" width="200" height="58" rx="7" fill="#2a2e37" stroke="#434a57"/>
<path d="M260,207 a7,7 0 0 1 7,-7 h186 a7,7 0 0 1 7,7 v21 h-200 z" fill="#4f9d69" fill-opacity="0.85"/>
<text x="270" y="218" fill="#fff" font-weight="600">GetLocal&lt;$acc&gt;</text>
<circle cx="460" cy="239.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="448" y="243.0" fill="#d6dae0" text-anchor="end">value</text>
<rect x="500" y="200" width="200" height="80" rx="7" fill="#2a2e37" stroke="#434a57"/>
<path d="M500,207 a7,7 0 0 1 7,-7 h186 a7,7 0 0 1 7,7 v21 h-200 z" fill="#4f9d69" fill-opacity="0.85"/>
<text x="510" y="218" fill="#fff" font-weight="600">Add&lt;i32&gt;</text>
<circle cx="500" cy="239.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="512" y="243.0" fill="#d6dae0" text-anchor="start">a</text>
<circle cx="500" cy="261.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="512" y="265.0" fill="#d6dae0" text-anchor="start">b</text>
<circle cx="700" cy="239.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="688" y="243.0" fill="#d6dae0" text-anchor="end">result</text>
<rect x="760" y="80" width="200" height="80" rx="7" fill="#2a2e37" stroke="#434a57"/>
<path d="M760,87 a7,7 0 0 1 7,-7 h186 a7,7 0 0 1 7,7 v21 h-200 z" fill="#d98c2f" fill-opacity="0.85"/>
<text x="770" y="98" fill="#fff" font-weight="600">SetLocal&lt;$acc&gt;</text>
<path d="M755,113.0 h6 l5,6 l-5,6 h-6 z" fill="#f2f2f2"/>
<text x="772" y="123.0" fill="#d6dae0" text-anchor="start">in</text>
<circle cx="760" cy="141.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="772" y="145.0" fill="#d6dae0" text-anchor="start">value</text>
<path d="M955,113.0 h6 l5,6 l-5,6 h-6 z" fill="#f2f2f2"/>
<text x="948" y="123.0" fill="#d6dae0" text-anchor="end">then</text>
<rect x="760" y="-60" width="200" height="80" rx="7" fill="#2a2e37" stroke="#434a57"/>
<path d="M760,-53 a7,7 0 0 1 7,-7 h186 a7,7 0 0 1 7,7 v21 h-200 z" fill="#c0392b" fill-opacity="0.85"/>
<text x="770" y="-42" fill="#fff" font-weight="600">Return</text>
<path d="M755,-27.0 h6 l5,6 l-5,6 h-6 z" fill="#f2f2f2"/>
<text x="772" y="-17.0" fill="#d6dae0" text-anchor="start">in</text>
<circle cx="760" cy="1.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="772" y="5.0" fill="#d6dae0" text-anchor="start">sum</text>
</svg>
```

---

`docs/00-concepts.md`

# 00 — Concepts: the Wiret graph model

This chapter defines *what a Wiret program means*, independent of how it is written (Chapter 01) or compiled (Chapter 03). Readers who know Unreal Blueprints will recognise nearly all of it; differences are called out in **Δ Blueprint** notes.

## 1. Programs

| Term | Meaning |
|---|---|
| **Module** | The unit of compilation, distribution and loading. One `.wiret` file = one module = one `.wbc` file. |
| **Declaration** | A top-level item: `var`, `struct`, `enum`, `class`, `function`, `event`, `macro`, `extern …`, `import`. |
| **Graph** | The body of a `function`, `event` or `macro`: a set of nodes and wires. |
| **Node** | One operation. Has a *kind* (e.g. `Branch`, `Math.Add`), optional type arguments, attributes, and pins. |
| **Pin** | A named, typed connection point on a node. |
| **Wire** | A directed connection from an output pin to an input pin. |

## 2. Two kinds of wires

Every pin is either an **exec pin** (type `exec`) or a **data pin** (any value type).

* **Exec wires** carry *control*. They say "after this node finishes, run that node". They are drawn white in a Blueprint-style editor.
* **Data wires** carry *values*. They say "this input takes the value this output produced".

Rules (checked by the compiler, not left to chance):

1. An **exec output** has **at most one** outgoing wire. (To run several things, use `Sequence`.)
2. An **exec input** may have **any number** of incoming wires (a join). Whichever arrives first runs the node.
3. A **data input** has **exactly one** source: a data wire, a literal written inline, or — if neither — the type's **default value** (`0`, `false`, `""`, empty collection, `null`).
4. A **data output** may feed any number of inputs.
5. Wire endpoints must have **identical types**, with one exception: a class-typed output may feed an input of a *base* class (upcast; the built-in root is `@Object`). There are no other implicit conversions; use a `Convert` node. (**Δ Blueprint**: Blueprints inserts conversion nodes silently; Wiret makes them explicit nodes so the text is unambiguous.)
6. The data-wire graph must be **acyclic**. Exec wires may form cycles (that is how loops work).

## 3. Execution

A **function call** begins at its `Entry` node and runs along exec wires. A node with exec pins is **impure** ("an action"): it runs *when control reaches it*. When it finishes, control leaves through one of its exec outputs (`Branch` chooses `then` or `else`; most nodes have a single `then`). Control ends at a `Return` node, or at a dangling exec output when the flow stack (§3.0) is empty.

### 3.0 The flow stack

Each function activation owns a **flow stack** of pending continuations, exactly as in Blueprints' execution model. Some nodes *push* continuations before they transfer control: `Sequence` pushes `then_1 … then_{n-1}` and runs `then_0`; `ForLoop`, `ForEach` and `While` push "go round again" and run `body`. When control reaches a **dangling exec output** (an exec output with no wire), the top continuation is popped and control goes there. If the stack is empty, the function returns (with default values for any results — a compiler warning, since it is usually a forgotten `Return`). A `Return` node discards the whole flow stack.

This is what makes `Sequence` and loop bodies read naturally: *run this whole chain to its end, then carry on with the next thing.* It is a **semantic** model; the compiler resolves it statically where it can (almost always) and falls back to an explicit continuation stack where it cannot (Chapter 02 §11).

### 3.1 Pure nodes

A node with **no exec pins** is **pure**: `Math.Add`, `Cmp.Gt`, `Var.Get`, `MakeStruct`. It has no side effects and runs *on demand*.

> **Pure evaluation rule.** When an impure node is about to run, every pure node it depends on (directly or transitively through pure nodes) is evaluated first, in dependency order, **exactly once per activation of that impure node**. Results are not shared between different impure nodes.

Consequences: a pure chain feeding two different impure nodes is evaluated twice (once for each); a pure node feeding a `While` condition is re-evaluated at each loop check. If you want a value computed once and reused, store it in a local variable or use an impure node's output. (**Δ Blueprint**: same observable behaviour, now specified.)

### 3.2 Outputs of impure nodes — latched values

An impure node's data outputs (`ForLoop.index`, `Call` results, `Cast.result`) are **latched**: they hold the value from the node's most recent execution *in this activation of the function*, and the type's default before the node has ever run. Downstream nodes reading them simply see that latched value; reading never re-runs the impure node. This makes every graph, however tangled, deterministic.

### 3.3 Latent nodes and fibers

Some nodes take time: `Flow.Delay`, `Flow.NextTick`, `Flow.Await`, or a call to a function that contains one. These are **latent**. A latent node *suspends* the running **fiber** (Wiret's lightweight cooperative thread) and the host resumes it later. Other fibers, and the host, keep running in between. Local variables, latched values and the call stack survive suspension.

Rules: a function containing a latent node is automatically `latent` (the compiler records this); a latent function may only be called from a latent context — an `event`, or another latent function; pure functions are never latent.

There are no preemptive threads inside a VM: fibers interleave only at latent nodes, so no locks are needed. (**Δ Blueprint**: this matches the game-thread model; "latent actions" become ordinary suspensions.)

### 3.4 Errors

A runtime error — array index out of range, integer divide by zero, null access, failed hard cast, exceeded instruction budget — **traps**: the current fiber stops and the host receives an error with a call-stack trace expressed in *node IDs* (so the editor can highlight the offending node). Traps never corrupt the VM; other fibers are unaffected. v1 has no in-graph try/catch (reserved for v2); validate inputs with `Branch` or use the `*.GetOr`/`Try*` library nodes that return defaults.

## 4. Types

| Family | Types | Semantics |
|---|---|---|
| Boolean | `bool` | `true` / `false` (lowers to `i32` 0/1) |
| Integers | `i8 i16 i32 i64 u8 u16 u32 u64` | Two's-complement, wrapping arithmetic. Narrow types lower to `i32`/`i64` with re-normalisation after each operation. |
| Floats | `f32 f64` | IEEE-754 binary32/64 |
| Text | `string` | Immutable UTF-8 |
| Enums | `@Name` (declared `enum`) | Named integers over an underlying integer type |
| Structs | `@Name` (declared `struct`) | **Value semantics**: copying a struct copies its fields |
| Classes | `@Name` (declared `class`, `extern class`) | **Reference semantics**, nullable, single inheritance |
| Collections | `array<T>`, `map<K,V>`, `set<T>` | **Value semantics** (like Blueprint arrays/maps/sets) |
| Functions | `fn(T1, T2) -> (R1)` | First-class function values: *delegates*. May be bound to an object. |
| Control | `exec` | Only on pins; not a value type |

**Value semantics, precisely.** Assigning a struct/array/map/set to a variable, field or collection element stores an independent copy; passing it to a function parameter does *not* copy (parameters are read-only inside the callee, so no one can tell). The compiler inserts `clone` operations at the store points and elides provably-unneeded ones. For authors this means: *if I put an array in a variable and change that variable, nobody else's array changes* — no aliasing surprises.

**Map keys** may be `bool`, any integer, `string`, or an enum. **Set elements**: same. Iteration order of `map`/`set` is *insertion order*, specified, so results are identical on every machine. (**Δ Blueprint**: unordered hash order is a notorious source of nondeterminism.)

**Defaults.** Numeric `0`, `bool` `false`, `string` `""`, enum = value declared `= 0` (or its first member), struct = each field's declared default, collections empty, class/function `null`.

## 5. Variables, structs, classes, events

* **Global variable** (`var @Name: T = default`) — one per module, shared by all fibers (safe: fibers interleave only at latent nodes).
* **Local variable** (`local name: T = default` inside a graph) — one per function activation; survives suspension.
* **Static** (`static name: T = default`) — persists across activations: one slot per function, or one per *instance* inside a macro (this is how `DoOnce` remembers it fired).
* **Struct** — named record of fields; value type. Created with `MakeStruct`, read with `BreakStruct`/`Struct.Get`, updated with `Struct.With` (pure, returns a modified copy) or `Struct.Set` (impure, updates a variable's field in place).
* **Class** — named record with single inheritance and methods. Methods are ordinary functions whose first parameter is `self`. Overridable methods are `[virtual]`; overrides are `[override]`. Instances are created with `Class.New` and are garbage-collected.
* **Extern class / extern function** — types and functions implemented by the **host** application (an `Actor`, `Log`, `Spawn`). They are the only way a program touches the outside world.
* **Event** — a graph the host (or another module) starts as a new fiber by name. Parameters in, no results. `OnStart`, `OnTick`, `OnHit` are just events the host chooses to fire.
* **Macro** — a graph that is *inlined* into each use, may have several exec inputs/outputs, and is erased before bytecode (like Blueprint macros). Standard `DoOnce`, `DoN`, `Gate`, `FlipFlop` are macros in the `std` module.

## 6. Pin derivation: nodes are not free-form

A node's pins are a **pure function of (kind, type arguments, attributes)** and, for `Call`/`Macro`/`Event.Fire`, of the referenced declaration's signature. Examples:

* `Math.Add<f32>` → inputs `a: f32`, `b: f32`; output `result: f32`.
* `Sequence [count=3]` → exec input `in`; exec outputs `then_0`, `then_1`, `then_2`.
* `Call [fn=@Actor.SetOpen]` → exec `in`/`then`; inputs `self`, `open`.

Consequence: the text never lists a node's pins; tools derive them. A wire naming a pin that does not exist is a compile error, and an LLM can validate its own output against the node library (Chapter 02).

## 7. Collaboration model

Because two people editing a graph must see the same picture, every visual fact is stored in the file as **metadata**: node position (`at`), size, colour, display name, comment boxes, collapsed state, wire knots. Metadata is carried by `#{ … }` clauses, never changes compiled behaviour, and has a registry of well-known keys with namespacing for editor-specific extensions (Chapter 01 §7). The canonical text form (§8 there) sorts nodes and wires deterministically and uses stable node IDs, so that moving a node changes one line, adding a node adds lines, and two people changing different nodes rarely conflict.


---

`docs/01-introduction.md`

# Introduction

Wiret is a **visual scripting language whose source of truth is text**. A Wiret program is a set of
*graphs*: nodes connected by execution wires (what happens next) and data wires (what flows between
nodes). Editors draw those graphs the way Unreal Engine draws Blueprints. Underneath, every graph is
stored in a line-oriented, diff-friendly text format, compiled to a compact typed bytecode, and run by a
small embeddable runtime with a C API.

```
 graph editor ──►  .wiret text  ──►  wiretc  ──►  .wirb bytecode  ──►  libwiret (embedded in the host)
 (people)          (Git, LLMs)      (compiler)    (verified, typed)     (VM, GC, fibers, C API)
```

## Why text?

Nobody is expected to *type* Wiret, but a text format changes what a visual language can do:

| Need | What the text format gives you |
| --- | --- |
| Source control | One fact per line; connections are owned by exactly one node, so a rewire changes one line and merges cleanly. Layout lives in its own block so moving nodes never conflicts with logic edits. |
| Review | A pull request diff reads like a changelog of the graph: `in b = 2` became `in b = %limit.value`. |
| AI tools | A model can read a graph, explain it, and generate or patch one. The format is explicit (typed, named pins, no positional tricks) so generation errors are detectable and the compiler's diagnostics name the node and pin. |
| Collaboration | Node positions, comment boxes, colors and collapsed state are stored in the file, so every developer's editor shows the same picture. Purely personal state (zoom, scroll, selection) is *not* stored. |

## Design goals

1. **Friendly for non-programmers.** Few concepts: nodes, pins, wires, variables. Execution order is
   visible as white wires. Pure nodes (no white wires) just compute. No hidden control flow.
2. **Capable of general programming.** Typed locals and globals, structs, classes with interfaces,
   arrays/maps/sets, delegates, recursion, loops (cycles), macros, coroutine-style *latent* calls.
3. **Text that reads.** IR-like (typed, explicit) but with markup features: attributes, metadata,
   named pins, layout.
4. **Deterministic and safe to embed.** The bytecode is verified before it runs; integer arithmetic
   wraps; map iteration is insertion-ordered; execution has instruction budgets and memory limits;
   a script can only reach what the host registers.
5. **Debuggable as a graph.** Every instruction maps back to a graph node. A trap, breakpoint or hook
   reports `loop/check`, not `pc 0x35`.

## How the pieces fit

| Part | Document | Analogy |
| --- | --- | --- |
| Text format (`.wiret`) | [Text format](02-text-format.md), [Standard nodes](03-standard-nodes.md) | LLVM IR + DOT/GML attributes |
| Bytecode (`.wirb`) | [Bytecode](04-bytecode.md) | WebAssembly sections, JVM-style typed verification |
| Runtime API (`wiret.h`) | [Runtime API](05-runtime-api.md) | The Lua C API |
| Compiler and tools | [Tooling](06-tooling.md) | `clang`, `wasm-validate`, a Git merge driver |

## From Blueprints to Wiret

| Blueprint concept | Wiret |
| --- | --- |
| Event Graph / Function Graph | `event` / `function` with a `graph { … }` block |
| Exec pin (white) | `exec <pin> -> %target` (owned by the *source* node; at most one target per output pin) |
| Data pin (colored) | `in <pin> = %source.pin` or a literal (owned by the *consuming* node; one source per input pin) |
| Pin default value | the literal after `=` in `in <pin> = 5`; omitted pins take the declared or type default |
| Pure node | a node with no exec pins: evaluated on demand, immediately before each consumer runs |
| Macro / Collapsed graph | `macro` (inlined at compile time; generic with `<T>`; may have several exec pins) |
| Sequence, Branch, Switch | `Sequence<N>`, `Branch`, `Switch<i32>` |
| ForLoop, DoOnce, … | `std.flow` macros written in Wiret itself |
| Latent node (Delay) | a `latent` function; the calling event becomes a coroutine |
| Variable / Local variable | `var` (module or class field) / `local $name` |
| Struct, Enum | `struct`, `enum` (structs are immutable values; "Set members" returns a new struct) |
| Blueprint Class, Interface | `class` (single inheritance), `interface` |
| Event Dispatcher | `dispatcher<Signature>` field + `Broadcast` node |
| Cast To | `Cast<Class>` with `then` / `failed` exec outputs |
| Comment box, node position, reroute | `layout { … }` block (positions are integers) |

Deliberate differences: arrays, maps and sets are **reference types** (assignment aliases; use
`ArrayClone` to copy); macro data inputs are **snapshots** taken when the macro is entered (Blueprint
macros re-evaluate them on every use); a trap **stops the fiber** and reports the node instead of
logging "Accessed None" and continuing.

## A first look

This is a complete program. `Fib` is a *pure* function: it has no white wires leaving the graph
except the ones that choose what to return.

```wiret
wiret 0.1

module "examples.fibonacci"
meta doc = "Recursive Fibonacci: the smallest useful Wiret program."

export pure function Fib(n: i32 [tooltip = "Which Fibonacci number to compute"]) -> (result: i32) {
  meta category = "Math"
  graph {
    node %entry : Entry {
      exec then -> %is_base
    }
    node %lt : Lt<i32> {
      in a = %entry.n
      in b = 2
    }
    node %is_base : Branch {
      in condition = %lt.result
      exec then -> %ret_n
      exec else -> %ret_sum
    }
    node %ret_n : Return {
      in result = %entry.n
    }
    node %n_minus_1 : Sub<i32> {
      in a = %entry.n
      in b = 1
    }
    node %n_minus_2 : Sub<i32> {
      in a = %entry.n
      in b = 2
    }
    node %fib_1 : Call<@Fib> {
      in n = %n_minus_1.result
    }
    node %fib_2 : Call<@Fib> {
      in n = %n_minus_2.result
    }
    node %sum : Add<i32> {
      in a = %fib_1.result
      in b = %fib_2.result
    }
    node %ret_sum : Return {
      in result = %sum.result
    }
  }
  layout {
    %entry at (0, 0)
    %lt at (260, 160)
    %is_base at (520, 0)
    %ret_n at (860, -40)
    %n_minus_1 at (260, 340)
    %n_minus_2 at (260, 500)
    %fib_1 at (520, 340)
    %fib_2 at (520, 500)
    %sum at (800, 420)
    %ret_sum at (1060, 380)
    box "Base case" at (-20, -70) size (1180, 330) [color = #3a5f8a]
  }
}
```

{{SVG:fib}}

*The picture above is generated from the `layout` block by the reference tool `wiret_ref svg`; any
editor that honours the layout shows the same arrangement.*

Compiled, `Fib` is 267 bytes including debug maps. Its code section disassembles to:

```
{{FIB_DIS}}
```

Each `; --- %node` line comes from the `wiret.nodemap` debug section. Notice that the pure nodes
`%n_minus_1` and `%n_minus_2` were emitted right before the `Call` that consumes them, and that the
Branch became a single `JMPIFNOT` that falls through into the "then" path.

Run it from the command line with the reference implementation, or embed it:

```c
wiret_getexport(F, m, "Fib");
wiret_pushi32(F, 10);
wiret_pcall(F, 1, 1);
printf("%d\n", wiret_checki32(F, -1));   /* 55 */
```

## Status of this specification

This is **version 0.1 (draft)**. A reference implementation of the text parser, formatter,
compiler, binary encoder, verifier, interpreter, disassembler and graph renderer accompanies it
(`reference/wiret_ref`, Python). It executes every example in these documents. Features that are
specified but not yet exercised by the reference implementation are marked **[spec only]**: classes,
interfaces, structs, maps/sets, delegates/dispatchers, fibers/latent calls, and the C runtime itself
(`wiret.h` is the specified, compile-checked interface).


---

`docs/01-overview.md`

# Wiret: Overview

Wiret is a **visual scripting language whose canonical form is text**. Its graphs are what you see in a Blueprint-style editor (nodes, pins, wires, comment boxes), but the file on disk is a line-oriented, diff-friendly, schema-checked text format that humans can read, Git can merge, and LLMs can generate.

A Wiret program travels through three representations:

```
 graph editor  <──────►  Wiret text (.wiret)  ──compile──►  Wiret bytecode (.wirb)  ──load/verify──►  embeddable runtime
 (what people          (what Git, CI and LLMs               (typed register machine,                  (libwiret, C API,
  see and edit)         see; canonical + layout)             WASM-style modules)                       Lua-style stack)
```

| Layer | Spec | Inspiration |
|---|---|---|
| Text format | [Text Syntax](#02-text-syntax) | LLVM IR (typed, sigils, one construct per line), DOT/GML (nodes, edges, attributes) |
| Bytecode | [Bytecode Specification](#03-bytecode) | WebAssembly (sections, LEB128, validation) and the JVM (typed instructions, verifier, classes) |
| Runtime | [Runtime API](#04-runtime-api) | The Lua C API (virtual stack, registry refs, native functions, coroutines) |
| Graph semantics | this chapter + [Standard Nodes](#06-standard-nodes) | Unreal Engine 5.7 Blueprints |

## Design goals

1. **Friendly to non-programmers.** The model is the one Blueprint users already know: white *exec* wires say what happens next, coloured *data* wires say where values come from. There is no syntax to learn in the editor, and the text format is never required reading.
2. **Capable of general programming.** Loops, recursion, arrays, maps, structs, classes, interfaces, delegates, coroutines and host functions are all present. Nothing is "node graph only"; anything the runtime can do, a graph can express.
3. **Text first, for the sake of everyone around the editor.** Source control, code review, search, CI, and language models all work on text. The text format therefore has to be *canonical* (one way to write a graph), *local* (a change to one wire changes one line) and *self-describing* (readable without the editor).
4. **Collaborators see the same graph.** Node positions, comment boxes and sizes are stored in the file, in a separate `layout` block that never affects execution. Per-user state (zoom, scroll, selection) is deliberately *not* stored.
5. **Safe to embed.** Bytecode is typed and verified at load time. A module can only touch what the host registered. Execution can be metered, memory-limited and stopped.

## The graph model

### Nodes and pins

A **node** has a *kind* (`Add<i32>`, `Branch`, `Call<@Fib>`), optional *type arguments*, and **pins**. Pins are either:

- **exec pins**: control flow. An impure node has one exec input (`in`) and zero or more named exec outputs (`then`, `else`, `completed`, …).
- **data pins**: typed values. Every data input has exactly one source (a wire from another node's data output, or a literal); a data output may feed any number of inputs.

### Exactly one owner per connection

Wiret stores each connection **once**, on the node that "owns" it:

| Connection | Cardinality | Stored on | Text |
|---|---|---|---|
| exec output → exec input | one target per output pin | the source node | `exec then -> %next` |
| data output → data input | one source per input pin | the consuming node | `in a = %other.result` |

This is what makes the format merge-friendly: re-wiring something edits exactly one line, in exactly one node. There is no separate, order-sensitive edge list.

### Pure and impure nodes

- **Impure** nodes have exec pins and run when control reaches them (`SetLocal`, `Call` of a normal function, `Branch`).
- **Pure** nodes have no exec pins (`Add`, `Lt`, `GetLocal`, `Call` of a `pure` function). They have no side effects.

**Evaluation rule (same as Blueprints).** A pure node is evaluated *on demand*: immediately before each impure node that needs it (directly or through other pure nodes), exactly once per execution of that impure node. If two impure nodes use the same pure node, it runs twice, once per consumer, and sees the world as it is at that moment. Pure nodes may not form cycles (`E0105`).

### Control flow

Control flow is a graph, so **loops are cycles**: connect an exec output back to an earlier node. Higher-level constructs (`ForLoop`, `ForEach`, `DoOnce`, …) are *macros* written in Wiret itself ([std.flow](#06-standard-nodes)).

`Sequence<N>` runs its outputs in order: `then_0` runs to the end of its path, then `then_1`, and so on. "End of its path" means an exec output with nothing connected. This is the same semantics as Blueprints' execution stack, and it is what lets `ForLoop` be an ordinary macro (body is `then_0`; the increment is `then_1`). Each path is compiled with its own *continuation context*, so shared nodes are correct; see [lowering](#05-compiler-and-tooling).

### Macros, functions, events

| Construct | Exec in | Exec out | Data in/out | Expanded? | Can hold state? |
|---|---|---|---|---|---|
| `function` | one | one (`Return`) | any | no (called) | locals only |
| `event` | none (entry point) | one | inputs only | no | locals only |
| `macro` | several | several | any (+ type parameters) | yes (inlined) | `state` slots |

Functions can be `pure`, `latent` (may suspend, like Blueprint's Delay) and `export`ed. Macro data inputs are **snapshots**: evaluated once, when an exec input fires. (Blueprint macros re-evaluate them continually; snapshots are far less surprising.)

### Values and types

`bool i32 i64 f32 f64 string any`, `array<T> map<K,V> set<T>`, user `struct` (immutable value type), `enum` (an `i32` with names), `class` (garbage-collected reference type with single inheritance and interfaces), `delegate`/`dispatcher<D>`, and `host` types supplied by the embedder. Arrays, maps and sets are **mutable reference types**; assignment aliases and `ArrayClone` copies. Maps and sets iterate in insertion order, so programs are deterministic.

All arithmetic is defined: integers wrap (two's complement), integer division by zero traps, floats follow IEEE 754.

## A first program

```wiret
wiret 0.1

module "examples.fibonacci"
meta doc = "Recursive Fibonacci: the smallest useful Wiret program."

export pure function Fib(n: i32 [tooltip = "Which Fibonacci number to compute"]) -> (result: i32) {
  graph {
    node %entry : Entry {
      exec then -> %is_base
    }
    node %lt : Lt<i32> {
      in a = %entry.n
      in b = 2
    }
    node %is_base : Branch {
      in condition = %lt.result
      exec then -> %ret_n
      exec else -> %ret_sum
    }
    node %ret_n : Return {
      in result = %entry.n
    }
    ; ... %n_minus_1, %n_minus_2, %fib_1, %fib_2, %sum, %ret_sum
  }
  layout {
    %entry at (0, 0)
    %lt at (260, 160)
    ; ...
    box "Base case" at (-20, -70) size (1180, 330) [color = #3a5f8a]
  }
}
```

The complete file is `examples/fibonacci.wiret`. Because the `layout` block is part of the file, every collaborator's editor draws this:

{{SVG:fib.svg}}

Compile and run it with the reference toolchain:

```
$ python -m wiret_ref build examples/fibonacci.wiret      # text -> .wirb (267 bytes)
$ python -m wiret_ref run   examples/fibonacci.wiret Fib 10
55
```

And from C:

```c
wiret_VM *vm = wiret_vm_new(NULL);
wiret_open_std(vm);                                   /* print, math, string, delay... */

wiret_Module *m;
wiret_Diag diag;
if (wiret_module_load(vm, bytes, len, "fibonacci", &m, &diag) != WIRET_OK) { /* diag.message */ }

wiret_Fiber *F = wiret_main(vm);
wiret_module_instantiate(F, m);

wiret_getexport(F, m, "Fib");      /* push function */
wiret_pushi32(F, 10);              /* push argument */
if (wiret_pcall(F, 1, 1) == WIRET_OK)
    printf("%d\n", wiret_toi32(F, -1, NULL));   /* 55 */
wiret_pop(F, 1);
```

## Blueprint concepts in Wiret

| Unreal Engine Blueprint | Wiret |
|---|---|
| Blueprint class asset | `module` (one or more `class`es, functions, variables) |
| Event Graph, custom event | `event` (an entry point; `latent` events may wait) |
| Function graph, pure function | `function`, `pure function` |
| Macro library | `macro` (inlined; `std.flow` ships Wiret-source macros) |
| Variable, local variable | `var` (module/class), `local $x` |
| Struct, Enum | `struct` (immutable value), `enum` |
| Exec pin / data pin / wildcard pin | exec pin / data pin / explicit type argument (`Add<i32>`) |
| Default value on an unconnected pin | literal in `in a = 5`; omitted pins take the pin default |
| Branch, Sequence, Switch | `Branch`, `Sequence<N>`, `Switch<i32>` |
| ForLoop, ForEachLoop, DoOnce, DoN | `std.flow` macros |
| While loop | `Branch` plus a wire back (a cycle) |
| Delay, latent actions | `latent` host function + coroutine fibers |
| Event dispatcher | `dispatcher<D>` field, `Bind`/`Unbind`/`Broadcast` |
| Interface, Cast To | `interface`, `Cast<Class>` with success/failure exec |
| Reroute node | `Reroute<T>` (pure pass-through; position in `layout`) |
| Comment box | `box "title" at … size …` in `layout` |
| Collapse to function/macro | create a `macro`, replace nodes by one macro node |
| Node comment/tooltip, category | `meta comment = "…"`, `[tooltip = "…"]`, `meta category = "…"` |
| Breakpoint, watch values on wires | debug hooks + the `wiret.nodemap` / `wiret.pins` sections |

## Deliberate differences

- **No implicit conversions.** `Convert<i32,f64>` is a node, not an invisible cast. Integer *literals* may initialise float pins.
- **Struct values are immutable.** `SetMember` returns a new struct. No aliasing surprises.
- **Collections are references.** Clone to copy.
- **Macro inputs are snapshots**, evaluated once per entry.
- **A trap is a trap.** Out-of-range index, null dereference or divide-by-zero stops the fiber with a traceback naming the graph node; nothing is silently logged and continued.
- **One entry per graph.** A function or event has exactly one `Entry`; shared behaviour lives in functions or macros, not in a single sprawling event graph.

## Conformance of this documentation

Every code listing marked as output was produced by the **reference toolchain** in `reference/wiret_ref` (a Python parser, compiler, verifier and interpreter written alongside this specification). It implements: the complete text grammar (parse and canonical format), the numeric/string/array/control-flow subset of the node library with macros, the full binary format for the type kinds it uses, the verifier for the instructions it executes, and an interpreter for those instructions. Sections describing classes, delegates, maps/sets, structs, `any` and fibers are normative design; the reference compiler rejects them with `E0002`. Each such section is marked **(specified, not in the reference toolchain)**.


---

`docs/01-text-syntax.md`

# 01 — Wiret Text: syntax specification

File extension `.wiret`, media type `text/x-wiret`, encoding UTF-8 (no BOM), line endings LF (CRLF accepted on input, never produced).

Wiret Text borrows from three families: **LLVM IR** (sigils for symbols, typed, one operation per line, explicit), **DOT/GML** (nodes and edges as separate statements; attribute lists) and **markup languages** (metadata that rides along without changing meaning).

## 1. Lexical structure

**Whitespace and lines.** Spaces and tabs separate tokens. A **newline ends a statement** unless the line ends inside `( )`, `[ ]`, `{ }`-literal or `#{ }`, or the next non-blank token is `->`. A `;` may be used instead of a newline. Blank lines are ignored.

**Comments.** `// …` to end of line, `/* … */` (not nested). Comments are **not preserved** by tooling; use `#{ comment: "…" }` or a `note` for text that must survive.

**Tokens.**

| Token | Form | Example |
|---|---|---|
| `IDENT` | `[A-Za-z_][A-Za-z0-9_]*` | `then`, `max_tries` |
| `NODEID` | `%` IDENT | `%branch_7k2q` |
| `SYMBOL` | `@` IDENT (`::` IDENT)* (`.` IDENT)* | `@Doors`, `@Std::Vec3`, `@Actor.SetOpen`, `@Color.Red` |
| `INT` | decimal, `0x` hex, `0b` binary; `_` separators allowed; optional leading `-` | `42`, `-7`, `0xFF`, `1_000` |
| `FLOAT` | digits `.` digits, optional exponent; or `nan`, `inf`, `-inf` | `1.0`, `2.5e-3`, `inf` |
| `STRING` | `"…"` with escapes `\n \r \t \\ \" \u{HEX}` | `"hello"` |
| `INTSUFFIX`/`FLOATSUFFIX` | optional type tag directly after a number | `255u8`, `1.5f32` |

Literal typing: a bare integer or float literal takes the type of the pin it binds to; suffixes are only needed where no pin gives the type (global `var` initialisers have the declared type, so even there they are rarely needed).

**Keywords** (reserved as bare words in declaration position): `wiret module import as extern var local static struct enum class function event macro note true false null`. Node kinds, pin names and attribute keys are *not* keywords; they are plain `IDENT`s interpreted by context.

**Sigils.** `@` = a module-level symbol (type, function, global, enum member). `%` = a node inside the current graph. Bare words = keywords, kinds, pins, attribute keys, field names. A reader can tell what any token refers to by its first character.

## 2. Grammar (EBNF)

Notation: `a b` sequence · `a | b` choice · `[a]` optional · `{a}` zero or more · `( )` grouping · `NL` a statement terminator (newline or `;`). Terminals in quotes.

```ebnf
file        = header NL { NL } module { NL } ;
header      = "wiret" INT ;                         (* format major version, currently 1 *)

module      = "module" SYMBOL [ attrs ] "{" NL { item NL } "}" ;
item        = meta | import | extern | var | struct | enum | class
            | function | event | macro ;

import      = "import" STRING "as" SYMBOL ;         (* import "std" as @Std  -> @Std::Name *)
extern      = "extern" ( "class" SYMBOL [ ":" SYMBOL ] [ meta ]
                       | "function" SYMBOL signature [ attrs ] [ meta ] ) ;

var         = "var" SYMBOL ":" type [ "=" value ] [ attrs ] [ meta ] ;
struct      = "struct" SYMBOL [ attrs ] [ meta ] "{" NL { field NL } "}" ;
class       = "class" SYMBOL [ ":" SYMBOL ] [ attrs ] [ meta ] "{" NL { field NL } "}" ;
field       = IDENT ":" type [ "=" value ] [ meta ] ;
enum        = "enum" SYMBOL [ ":" inttype ] [ attrs ] [ meta ] "{" NL { member NL } "}" ;
member      = IDENT [ "=" INT ] [ meta ] ;

function    = "function" SYMBOL signature [ attrs ] [ meta ] graph ;
event       = "event" SYMBOL params [ attrs ] [ meta ] graph ;
macro       = "macro" SYMBOL signature [ attrs ] [ meta ] graph ;

signature   = params [ "->" params ] ;
params      = "(" [ param { "," param } ] ")" ;
param       = IDENT ":" type [ "=" value ] ;        (* in macros, type may be `exec` *)

graph       = "{" NL { gstmt NL } "}" ;
gstmt       = meta | local | node | wire | note ;
local       = ( "local" | "static" ) IDENT ":" type [ "=" value ] [ meta ] ;
node        = NODEID "=" kind [ typeargs ] [ attrs ] [ inputs ] [ meta ] ;
kind        = IDENT { "." IDENT } ;
typeargs    = "<" type { "," type } ">" ;
inputs      = "(" [ bind { "," bind } ] ")" ;
bind        = IDENT ":" ( pinref | value ) ;
pinref      = NODEID "." IDENT ;
wire        = endpoint "->" endpoint { "->" endpoint } [ meta ] ;
endpoint    = NODEID [ "." IDENT ] ;
note        = "note" NODEID "=" STRING [ meta ] ;

attrs       = "[" attr { "," attr } "]" ;
attr        = IDENT [ "=" value ] ;
meta        = "#{" [ mentry { "," mentry } [ "," ] ] "}" ;
mentry      = IDENT { "." IDENT } ":" value ;

type        = prim | SYMBOL
            | "array" "<" type ">" | "set" "<" type ">" | "map" "<" type "," type ">"
            | "fn" "(" [ type { "," type } ] ")" [ "->" "(" [ type { "," type } ] ")" ]
            | "exec" ;
prim        = "bool" | inttype | "f32" | "f64" | "string" ;
inttype     = "i8" | "i16" | "i32" | "i64" | "u8" | "u16" | "u32" | "u64" ;

value       = INT | FLOAT | STRING | "true" | "false" | "null" | SYMBOL
            | "[" [ value { "," value } ] "]"                    (* list: arrays, sets, attribute lists *)
            | "(" value { "," value } ")"                        (* tuple: coordinates, sizes *)
            | "{" [ value ":" value { "," value ":" value } ] "}"  (* map literal *)
            | SYMBOL "{" [ IDENT ":" value { "," IDENT ":" value } ] "}" ; (* struct literal *)
```

Notes on the grammar:

* `meta` attaches to the declaration/statement on the same line (or, as a stand-alone line inside a `{ }` body, to the enclosing container).
* A `pinref` (`%n.pin`) and a `value` are distinguishable by their first token; no ambiguity with `map` literals because `meta` always starts with `#{`.
* Inside `wire` chains, **interior endpoints must be bare** (`%a -> %b -> %c`): the incoming wire lands on `%b`'s sole exec input and the outgoing one leaves its sole exec output.
* A **bare endpoint** `%n` is legal only if the node has exactly one exec pin in that direction (usually `in`/`then`). Otherwise name the pin.

## 3. Declarations

```
wiret 1
module @Inventory [export] {
  #{ title: "Inventory rules", doc: "Pure logic for stacking items." }

  import "std" as @Std

  enum @Rarity : u8 { Common = 0, Rare = 1, Epic = 2 }

  struct @Item {
    name: string = ""
    count: i32 = 1
    rarity: @Rarity = @Rarity.Common
  }

  class @Bag : @Std::Object { items: array<@Item> }

  var @max_stack: i32 = 99

  extern class @Player
  extern function @Player.Notify(self: @Player, text: string) [latent]
}
```

* **Symbols are module-scoped.** Inside a module, refer to its own declarations as `@Name`. Imported modules are reached through their alias: `@Std::Vec3`.
* **Methods** are functions named `@Class.method` whose first parameter is `self: @Class`.
* **Order of declarations does not matter** (forward references are legal); the canonical form fixes it anyway (§8).
* `extern` declarations name host-provided classes and functions. Their *signatures are part of the module* and are checked when the module is linked to a VM (Chapter 04).

### 3.1 Semantic attributes (`[ … ]`)

Attributes change meaning. **Unknown attribute keys are errors**, except keys starting `x_` (extension attributes: preserved, ignored by the standard compiler, reported as a warning).

| Applies to | Attribute | Meaning |
|---|---|---|
| module | `export` | Re-export all public declarations to importers (default: public declarations only) |
| function, event | `export` | Callable from the host by name (events are always exported) |
| function | `pure` | No exec pins; side-effect free; node form is a pure node. Graph must contain no impure nodes |
| function | `latent` | Asserted; the compiler *infers* latency and errors if the assertion is wrong |
| function (method) | `virtual`, `override` | Virtual dispatch (single inheritance) |
| any declaration | `deprecated="message"` | Warn on use |
| var | `const` | Initialiser only; `Var.Set` is a compile error |
| var | `export` | Host may read/write by name |
| enum | `flags` | Members are bit flags; library offers `Enum.HasFlag` |
| node | kind-specific, see Chapter 02 | e.g. `name=@attempts`, `count=3`, `cases=[1,2,3]` |

## 4. Graphs

A function body is a flat list of statements. The statement forms:

```
local retries: i32 = 0                                   // per-activation variable
static calls: i32 = 0                                    // persists across activations (per function; per instance in a macro)
%n = Kind<T>[attr=…](pin: source, …)  #{ at: (x, y) }    // node
%a.then -> %b.in                                         // exec wire
note %c1 = "Check the lock first" #{ at: (0, -80), size: (200, 60) }   // comment box
```

### 4.1 Node statements

```
%read  = Var.Get<i32> [name=@attempts]
%plus1 = Math.Add<i32>(a: %read.value, b: 1)
%bump  = Var.Set<i32> [name=@attempts](value: %plus1.result)
```

* **Kind** — a library node (`Math.Add`, `Branch`, `ForLoop`…) or one of the special kinds `Call`, `Macro`, `Event.Fire`.
* **`<…>`** — type arguments. **Required** whenever the node kind is generic; never inferred.
* **`[…]`** — static node parameters (attributes).
* **`(…)`** — *data inputs only*. Each binding is `pin: source`. A source is `%node.pin` (a data wire), or a literal/value. Bindings may be omitted; the pin then takes its default. Bindings for the same pin twice are an error.
* **`#{…}`** — metadata.

Exec connections are **never** written inside `( )`; they are separate wire statements. That keeps *control flow* readable at a glance (arrows) while *data flow* stays attached to the node that consumes it.

### 4.2 Wire statements

```
%entry -> %gate                      // sole-exec shorthand
%gate.then -> %bump                  // named source, bare target
%gate.else -> %open
%loop.body -> %step -> %loop         // chain: body→step, then step→loop (back edge)
%ok -> %loop.break                   // named target pin
```

Back edges (loops) are ordinary wires. An exec output may be wired at most once; wiring it twice is an error.

### 4.3 Entry and exit nodes

Every function and event has exactly one `Entry` node. Its *data outputs are the function's parameters* (same names); its exec output is `then`. `Return` nodes have *data inputs for the declared results* and one exec input; a function may have several. Events use `Return` with no inputs. Macros use `Entry` and `Exit [pin=name]` (Chapter 02 §10).

```
function @Clamp01(x: f32) -> (y: f32) [pure] {
  %entry = Entry
  %c     = Math.Clamp<f32>(value: %entry.x, min: 0.0, max: 1.0)
  %ret   = Return(y: %c.result)
}
```

A `[pure]` function has no exec wires; its `Return` is reached by dependency, not control.

## 5. Values and literals

| Type | Literal | Notes |
|---|---|---|
| `bool` | `true`, `false` | |
| integers | `-12`, `0xFF`, `7u8` | range-checked against the pin type |
| floats | `3.5`, `1e9`, `nan`, `inf`, `-inf` | |
| `string` | `"text\n"` | |
| enum | `@Rarity.Rare` | |
| struct | `@Item{ name: "Gem", count: 3 }` | omitted fields take defaults |
| `array<T>`, `set<T>` | `[1, 2, 3]` | |
| `map<K,V>` | `{ "a": 1, "b": 2 }` | insertion order is preserved |
| class, `fn` | `null` | the only class/function literal |
| global/`fn` reference | `@Doors::TryOpen` | symbol as value: a function value (type `fn`) or a global's *name* where an attribute expects one |

Global variable initialisers and field/parameter defaults must be constant expressions made of literals.

## 6. Metadata (`#{ … }`)

Metadata is the part of the file that exists so that **every collaborator's editor shows the same thing**. It never influences compiled behaviour. Rules:

1. Any declaration, field, node, wire or note may carry one `#{…}` clause, at the end of its line.
2. Keys are `IDENT` or dotted `IDENT.IDENT…`. Values are any `value`.
3. **Unknown keys are preserved byte-for-byte in meaning** by every tool (round-trip safe). Tools must never delete metadata they do not understand.
4. Third-party editors store private data under a namespace: `editor.<vendor>.<key>`, e.g. `editor.acme.snap: true`.
5. The compiler may emit metadata into a custom section of the bytecode (`wiret.meta`), but the VM never reads it.

**Well-known keys** (the *core metadata registry*):

| Key | Value | Applies to | Meaning |
|---|---|---|---|
| `at` | `(x, y)` ints | node, note | Top-left position in graph units (1 unit = 1 px at 100% zoom, y grows downward) |
| `size` | `(w, h)` ints | note, resizable nodes | Box size |
| `label` | string | node, declaration | Display name override |
| `color` | `"#RRGGBB"` or `"#RRGGBBAA"` | node, note | Title/background tint |
| `comment` | string | node | Bubble comment on a node |
| `collapsed` | bool | node | Rendered minimised |
| `hidden_pins` | `[pin, …]` | node | Pins hidden in the editor (wires still apply) |
| `group` | string | node | Name of a visual group the node belongs to |
| `contains` | `[%id, …]` | note | Nodes enclosed by a comment box (moves with them) |
| `via` | `[(x,y), …]` | exec wire | Spline knots for the wire |
| `doc` | string | declaration | Documentation text (Markdown) |
| `category` | string | function, event | Palette category, `"A|B"` for nesting |
| `keywords` | `[string, …]` | function, event | Search keywords |
| `title` | string | module | Human title |
| `view` | `{ pan: (x,y), zoom: f }` | function, event, macro | Last editor viewport (optional; tools should not rewrite it on every open) |

*Data wires have no metadata.* To route a data wire around the canvas, insert a `Reroute<T>` node, which has an `at` like any other node and is erased at compile time.

## 7. Attributes versus metadata, at a glance

| | Attribute `[ ]` | Metadata `#{ }` |
|---|---|---|
| Changes program meaning | **Yes** | **Never** |
| Unknown keys | error (unless `x_`) | preserved |
| In semantic hash | yes | no |
| Value syntax | `key` or `key=value` | `key: value` |
| Written by | author / editor logic | editors, doc tools, humans |

## 8. Canonical form

Every tool that writes Wiret Text — editors, the compiler's formatter `wiretc fmt`, LLM post-processors — must emit **canonical form**, so that equal programs have byte-identical text and Git diffs are minimal.

1. UTF-8, LF, two-space indent, no tabs, no trailing whitespace, one final newline.
2. **Module item order:** `#{}`, imports (by alias), externs, enums, structs, classes, vars, then functions/events/macros — each group sorted by name (ordinal, case-sensitive).
3. **Graph statement order:** `#{}` and `local`s (by name), then nodes in *reading order*, then `note`s (by id), then wires.
4. **Reading order.** Depth-first from `Entry` along exec wires, following a node's exec outputs in the node's declared pin order; a node is emitted at its first visit. A pure node (and any pure inputs it needs) is emitted *immediately before the first node that consumes it*, in input-pin order. Nodes unreachable from `Entry` follow, sorted by ID. Reading order depends only on graph structure, never on coordinates — dragging a node never reorders the file.
5. **Wires:** one per line, no chains, sorted by (source node's reading-order index, source pin's declared order). Bare endpoints wherever legal.
6. **Within a node:** attributes sorted by key; input bindings in pin declaration order; metadata keys sorted by key; no line wrapping (a node is always exactly one line).
7. **Literals:** integers decimal without `_` or suffix; floats as the shortest string that round-trips, always with a `.` or exponent; strings with minimal escaping.
8. Pin names, kinds and attributes are written exactly as spelled in the node library.

### 8.1 Node IDs and merging

Node IDs are **stable, unique within a graph, and never reassigned**. Editors should generate `kindslug_xxxx` (e.g. `%branch_7k2q`, four random base-32 characters) so concurrent branches rarely invent the same ID; humans and LLMs may use any readable name (`%gate`, `%read`). On a merge that produces duplicate IDs, tools append `_2`. Because each node and each wire is one line, three-way merges succeed unless both sides touch the *same* node or wire — the same granularity a developer expects from code.

### 8.2 Semantic hash

`semantic_hash = SHA-256(canonical text with every #{…} and note removed and node IDs replaced by their reading-order index)`. The compiler embeds it in the bytecode (`wiret.hash`). Two sources with equal hashes compile to identical code; CI can use it to assert that a "layout only" commit changes no behaviour.

## 9. Diagnostics

Tools report errors with a code, a 1-based line:column, and the **node ID** where applicable, so graph editors can highlight the node. Families: `E1xx` lexical, `E2xx` grammar, `E3xx` declarations/symbols, `E4xx` types and pin typing, `E5xx` graph rules (exec fan-out, data cycles, missing `Entry`), `E6xx` purity/latency, `W` warnings (unreachable node, unconnected exec output, deprecated use, unknown `x_` attribute). The full code list is maintained with the compiler.

## 10. Worked example: a loop

```
function @Sum(values: array<i32>) -> (total: i32) {
  local acc: i32 = 0
  %entry = Entry
  %each  = ForEach<i32>(array: %entry.values)                 #{ at: (200, 0) }
  %get   = Local.Get<i32> [name=acc]                          #{ at: (200, 140) }
  %add   = Math.Add<i32>(a: %get.value, b: %each.item)        #{ at: (380, 140) }
  %set   = Local.Set<i32> [name=acc](value: %add.result)      #{ at: (380, 0) }
  %fin   = Local.Get<i32> [name=acc]                          #{ at: (560, 140) }
  %ret   = Return(total: %fin.value)                          #{ at: (560, 0) }
  %entry -> %each
  %each.body -> %set
  %each.done -> %ret
}
```

Reading it: *for each item of `values`: set `acc` to `acc + item`; when done, return `acc`.* Note that `%set` has no outgoing wire. An exec output with no wire is **dangling**; when control reaches one, it pops the activation's **flow stack** (Chapter 00 §3.2) and the loop carries on with the next item. Wiring a body's end back to the loop's own `in` pin is *not* how loops continue — that would restart the loop (for `ForLoop`/`ForEach`, resetting the index).


---

`docs/02-node-library.md`

# 02 — Standard node library and lowering

This chapter lists every built-in node kind: its **pins** (derived from kind + type arguments + attributes, per Chapter 00 §6) and its **lowering** to bytecode (Chapter 03). A tool can validate a graph by consulting only this chapter.

## 1. Conventions

* Pin tables use `in`/`out` for direction, `exec` for control pins and a type for data pins. `T` is the node's type argument.
* **Impure** = has exec pins. **Pure** = none (Chapter 00 §3.1). Pin names never change between versions; new pins are only added.
* *Numeric* means `i8…i64, u8…u64, f32, f64`; *integer* means the integer subset; *key type* means `bool`, integers, `string`, enums.
* A **place** is a variable location a node reads or updates, named by exactly one attribute: `var=@Global`, `local=name` (local or `static`), or `field=name` (with an `object` input pin; for struct-typed places the place is the `object`'s field).
* **Upcasts.** The only implicit conversion: a wire may connect a class-typed output to an input of a *base* class of it (`@Door` → `@Actor` → `@Object`). `@Object` is the built-in root class. Everything else needs `Convert` or `Cast`.

## 2. Structure and flow

| Kind | Type args / attrs | Pins | Meaning |
|---|---|---|---|
| `Entry` | — | out `then`: exec; out *one data pin per parameter* | Start of a function/event; macros see §10. Exactly one per graph. |
| `Return` | — | in `in`: exec; in *one data pin per result* | Ends the activation, discarding the flow stack. Results not bound take their default. |
| `Branch` | — | in `in`; in `cond`: bool; out `then`, `else` | `then` if `cond`, else `else`. |
| `Sequence` | `count=N` (N ≥ 2) | in `in`; out `then_0 … then_{N-1}` | Runs `then_0`'s chain to its end, then `then_1`, … (flow stack). |
| `Switch<T>` | `T` integer, `string` or enum; `cases=[v0, v1, …]` | in `in`; in `value`: T; out `case_0 … case_{k-1}`, `default` | First case equal to `value` wins; no match → `default`. Cases must be distinct. |
| `Select<T>` | any `T` | in `cond`: bool, `a`: T, `b`: T; out `result`: T | **Pure.** `a` if `cond` else `b`. Both are evaluated (they are pure, so only time is spent). |
| `Reroute<T>` | `T` any type or `exec` | `in` → `out` (data) or `in` → `then` (exec) | Identity. Exists for layout; erased by the compiler. |

`Sequence` is the only fan-out for control. A `Switch` over `string` compares by byte equality.

## 3. Loops

All loops are impure, take a `break` exec input, and have `body`/`done` exec outputs. Control reaching a dangling exec output inside `body` pops the flow stack, which returns to the loop (Chapter 00 §3.0).

| Kind | Type args | Pins | Meaning |
|---|---|---|---|
| `ForLoop` | — | in `in`, `break`; in `first`: i32, `last`: i32; out `body`, `done`; out `index`: i32 | Runs `body` for `index = first … last` inclusive; none if `first > last`. Bounds are read once at entry. |
| `ForEach<T>` | `T` any | in `in`, `break`; in `array`: array<T>; out `body`, `done`; out `item`: T, `index`: i32 | Iterates a snapshot of `array` taken at entry (the compiler clones only if `body` might mutate the source). |
| `ForEachMap<K,V>` | key type, any | in `in`, `break`; in `map`: map<K,V>; out `body`, `done`; out `key`: K, `value`: V | Insertion-order iteration over a snapshot. |
| `While` | — | in `in`, `break`; in `cond`: bool; out `body`, `done` | Evaluates `cond` (pure chain re-evaluated each round); runs `body` while true. |

`break` (wired from any exec output inside the loop to `%loop.break`) abandons the loop and continues at `done`. Loops started again from `in` re-initialise.

Latched outputs: `index`, `item`, `key`, `value` are valid during `body` and keep their last value afterwards (Chapter 00 §3.2).

## 4. Variables and places

| Kind | Type args / attrs | Pins | Meaning |
|---|---|---|---|
| `Var.Get<T>` | `name=@Global` | out `value`: T | **Pure.** Read global. |
| `Var.Set<T>` | `name=@Global` | in `in`; in `value`: T; out `then` | Store (cloned if value-typed). |
| `Local.Get<T>` | `name=ident` | out `value`: T | **Pure.** Read local or static. |
| `Local.Set<T>` | `name=ident` | in `in`; in `value`: T; out `then` | Store. |
| `Field.Get<@C>` | `field=name`; `@C` struct or class | in `object`: @C; out `value`: field type | **Pure.** Traps if `object` is a null class reference. |
| `Field.Set<@C>` | `field=name`; class only | in `in`, `object`: @C, `value`; out `then` | Store into a class instance. |
| `Struct.With<@S>` | `field=name` | in `struct`: @S, `value`; out `result`: @S | **Pure.** Copy of `struct` with one field replaced. |
| `MakeStruct<@S>` | — | in one pin per field (defaults apply); out `result`: @S | **Pure.** |
| `BreakStruct<@S>` | — | in `struct`: @S; out one pin per field | **Pure.** |
| `Class.New<@C>` | — | in `in`; out `then`; out `object`: @C | Allocates an instance with field defaults. |

Statics and locals are declared with `local` / `static` statements (Chapter 01 §4). A `static` in a *function* is one slot shared by all activations of that function; a `static` in a *macro* is one slot per macro **instance**.

## 5. Calls and delegates

| Kind | Type args / attrs | Pins | Meaning |
|---|---|---|---|
| `Call` | `fn=@F`; optional `virtual` | If `@F` is `[pure]`: its parameters (in), results (out). Else additionally exec `in`/`then`. | Calls a function, method or extern function. `virtual` dispatches on `self`'s class. A call to a `latent` function is latent. |
| `Event.Fire` | `fn=@Ev` | in `in`; in event parameters; out `then` | Starts `@Ev` as a **new fiber** and continues immediately. |
| `Fn.Make` | `fn=@F` | out `value`: fn(…)→(…) | **Pure.** Function value for `@F` (unbound). |
| `Fn.Bind` | `fn=@C.method` | in `self`: @C; out `value`: fn(…)→(…) | **Pure.** Bound method value (receiver captured). |
| `Fn.Call<fn(A…)->(R…)>` | the function type | in `in`, `target`: that type, `arg_0…`; out `then`, `ret_0…` | Calls a function value. Traps on `null`. |
| `Fn.IsNull<fn…>` | function type | in `value`; out `result`: bool | **Pure.** |

## 6. Latent nodes

| Kind | Pins | Lowering |
|---|---|---|
| `Flow.Delay` | in `in`, `seconds`: f64; out `then` | `sleep` |
| `Flow.NextTick` | in `in`; out `then` | `yield` |
| `Flow.Await` | in `in`, `waitable`: `@Std::Awaitable`; out `then` | `await` |

`@Std::Awaitable` is a host-implemented class (a timer, a download, "animation finished"…) that the host signals when done. Any function containing a latent node, or calling a latent function, is latent; `[pure]` functions and non-event call sites in non-latent contexts are rejected (`E601`).

## 7. Types and conversion

| Kind | Type args | Pins | Meaning |
|---|---|---|---|
| `Convert<A,B>` | numeric/bool/string pairs below | in `value`: A; out `result`: B | **Pure.** |
| `Cast<@T>` | class `@T` | in `in`, `object`: `@Object`; out `then`, `failed`; out `result`: @T | Succeeds (`then`) iff `object` is an instance of `@T`. |
| `Is<@T>` | class | in `object`: @Object; out `result`: bool | **Pure.** `ref.test`. |
| `IsNull<@C>` | class | in `object`: @C; out `result`: bool | **Pure.** |
| `Equal.Ref<@C>` | class | in `a`, `b`; out `result`: bool | **Pure.** Identity. |

`Convert` pairs: any numeric ↔ any numeric (integer narrowing wraps; float→integer saturates, NaN→0); numeric → `string`; `bool` → integer (0/1); integer → `bool` (≠ 0); enum ↔ its underlying integer; `string` → numeric is the separate `String.Parse*` node because it can fail.

## 8. Math, comparison, logic

All **pure**. `T` is the node's type argument. Result type equals `T` unless noted. Integer types narrower than 32 bits are re-normalised after each operation (`u8`: `and 0xFF`; `i8`: `i32.extend8_s`; `u16`: `and 0xFFFF`; `i16`: `i32.extend16_s`).

| Kind | T | Pins | Lowering (i32 / i64 / f32 / f64 respectively) |
|---|---|---|---|
| `Math.Add Sub Mul` | numeric | `a`, `b` → `result` | `add sub mul` |
| `Math.Div` | numeric | `a`, `b` → `result` | `div_s`/`div_u` · `div`. Integer divide by zero **traps** unless `[on_zero=zero]`, which yields 0 |
| `Math.Mod` | integer | `a`, `b` → `result` | `rem_s`/`rem_u`. Same `on_zero` attribute |
| `Math.Neg` | signed, float | `value` → `result` | `0 - x` · `neg` |
| `Math.Abs` | signed, float | `value` → `result` | `select`-based · `abs` |
| `Math.Min Max` | numeric | `a`, `b` → `result` | compare + `select` · `min max` |
| `Math.Clamp` | numeric | `value`, `min`, `max` → `result` | min/max pair |
| `Math.Sqrt Floor Ceil Round Trunc` | float | `value` → `result` | `sqrt floor ceil nearest trunc` |
| `Math.Sin Cos Tan Asin Acos Atan Exp Log Pow Atan2` | `f32`/`f64` | `value` (or `a`,`b`) → `result` | `call` of `wiret.math` imports (§12) |
| `Bit.And Or Xor` | integer | `a`, `b` → `result` | `and or xor` |
| `Bit.Not` | integer | `value` → `result` | `xor -1` |
| `Bit.Shl ShrS ShrU` | integer | `value`, `count`: i32 → `result` | `shl shr_s shr_u` |
| `Cmp.Eq Ne` | numeric, `bool`, enum | `a`, `b` → `result`: bool | `eq ne` |
| `Cmp.Lt Le Gt Ge` | numeric, enum | `a`, `b` → `result`: bool | `lt_s`/`lt_u`/`lt` … by signedness |
| `Logic.And Or Xor` | — | `a`, `b`: bool → `result`: bool | `and or xor` on `i32`; **both operands are always evaluated** |
| `Logic.Not` | — | `value`: bool → `result`: bool | `i32.eqz` |

`Math.Div<f32>` follows IEEE-754 (`x/0` = ±inf, never traps). Strings and classes use the `String.*` / `Equal.Ref` nodes below.

## 9. Collections and strings

### 9.1 Arrays, maps, sets

Read-only nodes are **pure** and take the collection as an ordinary input pin (no copy). **Mutating** nodes are impure and name a **place** (§1) holding the collection; they update that stored collection in place. Exactly one of `var=`, `local=`, `field=` is required on every mutator.

| Kind (`<T>` = element, `<K,V>` = key/value) | Pins | Lowering |
|---|---|---|
| `Array.Length<T>` | in `array` → `result`: i32 | `array.len` |
| `Array.Get<T>` | `array`, `index`: i32 → `result`: T | `array.get`; **traps** if out of range |
| `Array.GetOr<T>` | `array`, `index`, `default`: T → `result`: T | bounds test, then `array.get` or `default` |
| `Array.Find<T>` | `array`, `item`: T → `index`: i32 | `array.find` (−1 if absent) |
| `Array.Contains<T>` | `array`, `item` → `result`: bool | `array.find` ≥ 0 |
| `Array.Add<T>` `[place]` | in `in`, `item`; out `then` | `array.push` |
| `Array.Insert<T>` `[place]` | `in`, `index`, `item` | `array.insert` |
| `Array.Set<T>` `[place]` | `in`, `index`, `item` | `array.set` |
| `Array.RemoveAt<T>` `[place]` | `in`, `index` | `array.remove` |
| `Array.Pop<T>` `[place]` | `in` → `then`, `item`: T | `array.pop` |
| `Array.Clear<T>` `[place]` | `in` | `array.clear` |
| `Array.Resize<T>` `[place]` | `in`, `size`: i32 | `array.resize` |
| `Map.Count<K,V>` | `map` → `result`: i32 | `map.len` |
| `Map.Has<K,V>` | `map`, `key` → `result`: bool | `map.has` |
| `Map.Get<K,V>` | `map`, `key` → `result`: V | `map.get`; **traps** if missing |
| `Map.GetOr<K,V>` | `map`, `key`, `default`: V → `result`: V | `map.get_or` |
| `Map.Keys<K,V>` / `Map.Values<K,V>` | `map` → `result`: array<K> / array<V> | `map.keys` / `map.values` |
| `Map.Set<K,V>` `[place]` | `in`, `key`, `value` | `map.set` |
| `Map.Remove<K,V>` `[place]` | `in`, `key` → `then`, `removed`: bool | `map.remove` |
| `Map.Clear<K,V>` `[place]` | `in` | `map.clear` |
| `Set.Count<T>`, `Set.Has<T>`, `Set.ToArray<T>` | as maps | `set.len`, `set.has`, `set.to_array` |
| `Set.Add<T>` `[place]` | `in`, `item` → `then`, `added`: bool | `set.add` |
| `Set.Remove<T>` `[place]` | `in`, `item` → `then`, `removed`: bool | `set.remove` |
| `Set.Clear<T>` `[place]` | `in` | `set.clear` |

Example — append to a global array:

```
%add = Array.Add<string> [var=@log](item: %entry.message)
```

### 9.2 Strings

All pure; `string` is immutable.

| Kind | Pins | Lowering |
|---|---|---|
| `String.Concat` | `a`, `b` → `result` | `str.concat` |
| `String.Length` | `text` → `result`: i32 | `str.len` (Unicode scalar values) |
| `String.Equals` | `a`, `b` → `result`: bool | `str.eq` |
| `String.Compare` | `a`, `b` → `result`: i32 (−1/0/1) | `str.cmp` |
| `String.Substring` | `text`, `start`: i32, `length`: i32 → `result` | `str.sub` |
| `String.Find` | `text`, `needle` → `index`: i32 (−1 if absent) | `str.find` |
| `String.Replace` | `text`, `from`, `to` → `result` | `str.replace` |
| `String.Split` | `text`, `separator` → `result`: array<string> | `str.split` |
| `String.Join` | `parts`: array<string>, `separator` → `result` | `str.join` |
| `String.Upper`, `String.Lower`, `String.Trim` | `text` → `result` | `str.upper` … |
| `String.ParseInt` | `text` → `value`: i64, `ok`: bool | `str.parse_i64` |
| `String.ParseFloat` | `text` → `value`: f64, `ok`: bool | `str.parse_f64` |

## 10. Macros

A **macro** is a graph inlined into every use. It is the unit for reusable *control-flow* (Blueprint macros): several exec inputs, several exec outputs, per-instance state. Macros are erased before bytecode generation and may not be recursive.

```
macro @DoOnce(in: exec, reset: exec) -> (then: exec) {
  static done: bool = false
  %entry = Entry
  %isdone = Local.Get<bool> [name=done]
  %gate  = Branch(cond: %isdone.value)
  %mark  = Local.Set<bool> [name=done](value: true)
  %out   = Exit [pin=then]
  %clear = Local.Set<bool> [name=done](value: false)
  %entry.in -> %gate
  %gate.else -> %mark -> %out
  %entry.reset -> %clear
}
```

* The **parameters of type `exec`** are the macro's exec *inputs*; **results of type `exec`** are its exec *outputs*; all other parameters/results are data pins.
* Inside the macro, `Entry` has one **exec output per exec input** (same names) and one **data output per data input**. `Exit [pin=name]` is the way out through exec output `name`; it has an exec input `in` and a **data input for each data result** (data results are latched by whichever `Exit` runs).
* **Use** with `Macro [name=@Std::DoOnce]`: the instance has exec *input pins* `in`, `reset` (wire targets) and exec *output* `then`.
* `static` slots in a macro are allocated **per instance**; locals are per activation of the enclosing function.

```
%once = Macro [name=@Std::DoOnce]
%entry -> %once
%once.then -> %greet
```

## 11. Lowering rules

These are normative for the standard compiler: other compilers may produce different code but **must preserve the observable behaviour** specified here (results, order of side effects, traps).

### 11.1 Storage
Every parameter, `local`, latched impure output and **pure-node result** gets a bytecode local (parameters occupy locals `0 … n-1`). Pure results are written into temporaries; an optimiser may fuse single-use trees into stack expressions. This keeps the invariant **the operand stack is empty at every branch** (Chapter 03 §8), which in turn lets pure nodes with internal branching (`Array.GetOr`, `Math.Abs` on signed ints) lower to ordinary blocks.

### 11.2 Pure evaluation
Before an impure node's code, the compiler emits the transitive pure inputs in dependency order (Chapter 00 §3.1). The same pure subtree consumed by two impure nodes is emitted twice. Inputs sourced from impure outputs read the latched local.

### 11.3 Blocks and wires
Each impure node becomes a labelled block. An exec wire becomes `br` (or fall-through when the target is next). `Branch` is `br_if`/fall-through. `Switch` over a dense integer range uses `br_table`; otherwise a compare chain. `Return` is `ret` with result locals pushed. A `[pure]` function lowers its single `Return` as one expression sequence.

### 11.4 Flow stack
The compiler computes for every dangling exec output its **continuation set** — the set of continuations that can be on top of the flow stack when it is reached.
1. **Singleton set (the overwhelming case):** emit `br` to that continuation.
2. **Several continuations, small region:** *tail-duplicate* the region once per continuation.
3. **Otherwise:** allocate an `array<i32>` local as an explicit continuation stack. A push is `array.push` of the continuation's small integer ID; a dangling output is `array.pop` then `br_table` over all possible IDs (empty stack ⇒ implicit return).
`Return` simply `ret`s, discarding any of this.

### 11.5 Loop lowering (sketch)

`ForLoop` with locals `i`, `last` (index and bound, read once):

```
        <first>  local.set i
        <last>   local.set last
        local.get i ; local.get last ; i32.gt_s ; br_if L_done   ; empty range
L_body: ...body...                                               ; body's dangling end -> L_next
L_next: local.get i ; local.get last ; i32.eq ; br_if L_done     ; compare before increment:
        local.get i ; i32.const 1 ; i32.add ; local.set i         ;   no overflow at i32 max
        br L_body
L_done: ...                                                      ; `break` also branches here
```

`ForEach` snapshots the array reference (with `clone` only if the body can mutate the source place), keeps an index local, and loads `item` into its latched local at each round. `While` is `L_check: <cond> br_ifnot L_done; body; br L_check`.

`Sequence [count=3]`: if all three chains are disjoint (typical), emit them one after another, each chain's dangling end branching to the next block; otherwise §11.4.

### 11.6 Latent nodes
`Flow.Delay` → `<seconds> sleep`; `Flow.NextTick` → `yield`; `Flow.Await` → `<waitable> await`. Locals, latched values and the call stack are preserved by the VM across suspension. Calling a latent function is an ordinary `call`; the VM suspends the *whole fiber* (all frames).

### 11.7 Source map
For every emitted instruction range the compiler records `(function, pc range, node ID, role)` in the `wiret.map` section (Chapter 03 §10): this is how traps, breakpoints and "currently executing node" highlighting reach the graph editor. Data pins also get `(local index → node.pin)` entries so a debugger can show wire values.

## 12. The `std` module and host libraries

**`@Std` (shipped as `std.wiret`):** macros `DoOnce(in, reset) → then`, `DoN(in, reset, n: i32) → then`, `Gate(in, open, close, toggle; start_closed: bool) → then`, `FlipFlop(in) → a, b, is_a: bool`, `MultiGate`; math structs `Vec2`, `Vec3`, `Color`, `Rect`; `@Std::Awaitable`; and pure `[pure]` helpers (`Lerp`, `InverseLerp`, `MapRange`, …). Everything in it is expressed in Wiret itself.

**Runtime libraries** opened with `wiret_openlibs` (Chapter 04 §11), as host imports under module name `wiret.*`: `wiret.math` (`sin cos tan asin acos atan atan2 exp log pow` for `f32`/`f64`), `wiret.time` (`now`, `delta`), `wiret.random` (seedable PRNG, deterministic by seed), `wiret.debug` (`print`, `assert`, `breakpoint`). Nodes: `Debug.Print(text)`, `Debug.Assert(cond, message)`, `Time.Now`, `Time.DeltaSeconds`, `Random.Int(min,max)`, `Random.Float()`.


---

`docs/02-text-format.md`

# Text format

A Wiret source file (`.wiret`) is UTF-8 text. It is designed to be **generated and read by tools**:
explicit, typed, regular, and canonical when formatted by `wiret fmt`. This chapter is normative.

## Lexical structure

* **Whitespace** (space, tab, CR, LF) separates tokens and is otherwise insignificant. The parser is
  *not* line-oriented, so a model that wraps lines differently still produces valid input. The
  canonical formatter always emits LF line endings, 2-space indentation and one item per line.
* **Comments** start with `;` and run to the end of the line. Comments are not preserved by tools;
  use `meta doc = "…"` or `meta comment = "…"` for text that must survive round trips.
* **Identifiers**: `[A-Za-z_][A-Za-z0-9_]*`. Keywords are contextual (a pin may be called `in`).
* **Sigils** make references unambiguous, like LLVM-IR:

| Token | Meaning | Example |
| --- | --- | --- |
| `%name` | a node in the current graph | `%add_k3f9` |
| `%node.pin` | an output pin of that node (as a data source) | `%entry.amount` |
| `@name`, `@Class.member`, `@alias.name` | a module-level symbol (function, variable, field) | `Call<@Fib>` |
| `$name` | a local variable or macro state | `GetLocal<$acc>` |
| `#rrggbb` | a color (attribute values only) | `#3a5f8a` |

* **Literals**

| Kind | Syntax | Notes |
| --- | --- | --- |
| integer | `42`, `-7`, `0xFF` | range-checked against the pin type; an integer literal may initialize a float pin |
| float | `3.14`, `1e-3`, `-2.5E4`, `inf`, `-inf`, `nan` | a decimal point or exponent makes it a float |
| bool | `true`, `false` | |
| string | `"text"` | escapes `\n \t \r \" \\ \0 \u{1F600}`; no raw newlines |
| null | `null` | any nullable reference type |
| list | `[1, 2, 3]` | array / set literals (and `cases` properties) |
| struct | `{x: 1, y: 2}` | |
| enum | `DoorState.Open` | |

## Types

```
i32  i64  f32  f64  bool  string  any
array<T>   map<K,V>   set<T>
Name                 ; a struct, enum, class, interface, delegate or extern type declared in scope
alias.Name           ; the same, from a `use`d module
dispatcher<Delegate> ; a multicast event dispatcher over a declared delegate type
```

`i32`/`i64` are two's-complement and wrap on overflow. `f32`/`f64` are IEEE-754. Enums are `i32`
underneath. Strings are immutable UTF-8 and never null (default `""`). All other reference types
default to `null`, except `array<T>` pin defaults which are a fresh empty array.

Smaller integer types and vectors are reserved for a later version (see *Roadmap* in Tooling).

## File structure

```
file      = "wiret" VERSION  decl*
decl      = "module" STRING
          | "meta" ID "=" value
          | "use" STRING "as" ID
          | [mods] "extern" "function" ID "=" STRING pins ["->" pins]
          | "extern" "type" ID "=" STRING
          | "enum" ID "{" (ID ["=" INT] [attrs] ",")* "}"
          | "struct" ID "{" (ID ":" type ["=" literal] [attrs] ",")* "}"
          | "delegate" ID pins ["->" pins]
          | "interface" ID "{" function-signature* "}"
          | "class" ID [":" type ("," type)*] "{" class-member* "}"
          | ("var" | "const") ID ":" type ["=" literal] [attrs]
          | [mods] ("function" | "event" | "macro") ID ["<" ID ("," ID)* ">"] pins ["->" pins] [body]
mods      = ("export" | "pure" | "latent")*
pins      = "(" [ pin ("," pin)* ] ")"
pin       = ID ":" type ["=" literal] [attrs]       ; data pin
          | "exec" ID                              ; exec pin (macros only)
attrs     = "[" ID "=" value ("," ID "=" value)* "]"
body      = "{" ("meta" ID "=" value | local | state | graph | layout)* "}"
local     = "local" "$"ID ":" type ["=" literal] [attrs]
state     = "state" "$"ID ":" type ["=" literal] [attrs]
graph     = "graph" "{" node* "}"
node      = "node" "%"ID ":" kind ["<" targ ("," targ)* ">"] "{" node-item* "}"
node-item = "meta" ID "=" value                     ; tooling data, never affects code
          | "prop" ID "=" value                     ; compile-time configuration
          | "in" ID "=" ( literal | "%"ID "." ID )  ; data input binding
          | "exec" ID "->" "%"ID ["." ID]           ; exec output connection
kind      = ID ("." ID)*                            ; Add, Branch, flow.ForLoop, ...
targ      = type | "@"symbol | "$"ID | INT | STRING
layout    = "layout" "{" ( "%"ID "at" point [attrs]
                         | "box" STRING "at" point "size" point [attrs] )* "}"
point     = "(" INT "," INT ")"
```

`value` in attributes may be any literal, a bare identifier, a color, or a list.

### Declarations

* **`module`** names the compilation unit (dotted, e.g. `"game.inventory"`). It is the namespace other
  modules import.
* **`use "std.flow" as flow`** imports a module's macros and types under an alias; its macros are used
  as node kinds (`flow.ForLoop`).
* **`extern function`** declares a *native* implemented by the host. The string is the registry name
  (`"module.function"`); the host must register it with a matching signature before instantiation.
  `pure` means no observable effects and results depend only on arguments; `latent` means it may
  suspend. `extern type` declares an opaque host handle type.
* **`var`** at module level is a global; inside a `class` it is an instance field. `const` is a global that
  nodes cannot set.
* **`function`** has one exec entry (the `Entry` node) and any number of `Return` nodes. A function with
  results must reach a `Return` on every path (error `E0301`). A function without results ends where
  a path ends.
* **`event`** is a function that is an entry point for the host or for dispatchers. It is exported
  automatically; it may be `latent`.
* **`pure function`** may be called as a pure node (no white wires): it may read globals but must not
  modify globals/fields or call impure functions (`E0202`). It may have internal control flow and
  locals.
* **`latent`** functions may call latent functions and natives. A non-latent function calling a latent
  one is an error (`E0201`). The runtime runs latent calls on a fiber (see Runtime API).
* **`macro`** declares reusable *inlined* subgraphs; see [Macros](#macros).
* **Metadata**: `meta key = value` lines (module, function, class, node) and trailing `[k = v]` lists (on
  `var`, parameters, fields, enum members). Well-known keys: `doc`, `category`, `tooltip`,
  `display_name`, `deprecated`, `keywords`, `color`, `comment` (shown as a node bubble). Unknown keys
  are preserved. Metadata never changes generated code and is excluded from the semantic hash.

## Graphs

A `graph` is an unordered set of node blocks. **Order is not significant**, but tools must preserve
the existing order and insert new nodes directly after the node they were created from, which keeps
diffs local. `wiret fmt --reading-order` rewrites a file in depth-first execution order.

### Node blocks

```
node %id : Kind<type-args> {
  meta key = value        ; optional
  prop key = value        ; optional compile-time configuration
  in pin = source         ; one line per bound input pin
  exec pin -> %target     ; one line per connected exec output pin
}
```

* **`%id`** is unique within the function and **never reused or renumbered** by editors. Ids are
  `slug` + short random suffix by convention (`%add_k3f9`), so two developers adding a node at the
  same time do not collide.
* **`Kind<…>`** selects a node from the [standard set](03-standard-nodes.md), a macro (`flow.ForLoop`),
  or `Call<@function>`. Type arguments are explicit: there are no wildcard pins in text, which keeps
  the file unambiguous. The editor shows wildcards and fills the type arguments for you.
* **`in pin = …`** binds a data input to a literal or to `%node.pin`. Unbound inputs take the declared
  default (parameter default or the type default: `0`, `0.0`, `false`, `""`, `null`, empty array).
  **Each input pin has at most one source**; an output pin may feed any number of inputs.
* **`exec pin -> %target`** connects an exec output to the exec input of `%target`. The default input
  is the node's first exec input (`in`); other inputs are named: `-> %once.reset`. **Each exec output
  has at most one target**; an exec input may be the target of many wires (a merge).

Because a data wire is written by its *consumer* and an exec wire by its *producer*, every wire in the
graph is exactly one line in exactly one place. Deleting a node leaves dangling lines only in nodes
that referenced it, and those are reported as `E0110`/`E0112`, never silently dropped.

### Evaluation semantics

1. **Execution** starts at `Entry` and follows exec wires. A node runs when execution reaches it.
   Cycles are legal and are how loops are made.
2. **Pure nodes** (no exec pins) run on demand: immediately **before each impure node that needs their
   result**, once per such execution (a pure node feeding two impure nodes runs twice; feeding two
   inputs of one impure node runs once). Data cycles are an error (`E0105`).
3. **Impure node outputs** are stored: reading `%call_1.result` later reads the value from the last
   time `%call_1` ran. Function parameters are the outputs of `%entry`.
4. **End of a path**: an unconnected exec output ends that path. Inside a `Sequence` branch, ending a
   path continues with the next branch; otherwise the function returns (or is an error if it has
   results).
5. **Sequence** `Sequence<N>` runs `then_0` to the end of its path, then `then_1`, …. The last branch
   runs in tail position (no state remains), so loops built on Sequence do not grow any stack.
6. **Evaluation order of inputs** within one node is unspecified except that pure inputs are all
   computed before the node runs. Pure nodes cannot have side effects, so this is unobservable.

### Macros

A macro is a subgraph that is **expanded inline** at every use site. It may have several exec inputs
and outputs and generic type parameters:

```
macro ForEach<T>(exec in, items: array<T>) -> (exec body, element: T, index: i32, exec completed) {
  local $i: i32
  graph {
    node %entry : Entry { exec in -> %init }
    …
    node %exit : Exit { in element = %item.value  in index = %get_i.value }
  }
}
```

* Parameters that are `exec NAME` are exec inputs; they become exec *outputs* of the `Entry` node
  inside the macro. Result `exec NAME` pins are exec outputs; they are exec *inputs* of the `Exit` node.
* A macro graph has exactly one `Entry` and one `Exit`.
* **Data inputs are snapshots**: they are evaluated once each time an exec input fires, and the
  macro's graph reads the stored copy (`%entry.items`).
* **Data outputs belong to the exec result before them in the signature.** In the example, `element`
  and `index` are computed and stored only when `body` fires, so `completed` never evaluates
  `ArrayGet` one past the end. Data results listed *before* every exec result are written on every exit.
* `local $x` is per activation of the enclosing function; **`state $x`** persists for the lifetime of the
  module instance, one slot per expansion site (this is how `DoOnce` remembers). Because each function
  has its own graph, a node's state is shared only by paths through that node in that function.
* After expansion, macro-internal node ids become path-style ids: `loop/check` (inner node), and
  synthetic binding nodes `loop!in`, `loop!body` (entry and exit stubs). These ids appear in node maps,
  traces and breakpoints so a debugger can step *into* a macro.
* Recursive macros are rejected (`E0310`).

The standard flow macros (`ForLoop`, `ForEach`, `DoOnce`, `DoN`) are written in Wiret and ship as
`std.flow`; see [Standard nodes](03-standard-nodes.md).

## Layout

```
layout {
  %entry at (0, 0)
  %lt at (260, 160) [collapsed = true]
  box "Base case" at (-20, -70) size (1180, 330) [color = #3a5f8a]
}
```

* One line per node, keyed by `%id`. Coordinates are **integers** in editor units (y grows downward);
  editors snap before saving so a drag never yields float noise in diffs.
* A `box` is a comment box; it contains whatever nodes lie inside it (membership is geometric, not a list,
  so moving a node never edits the box).
* Attributes: `collapsed`, `color`, `size` (resized nodes), `hidden_pins` (list of pin names), `note`.
* **Shared vs. personal view state.** Everything in the layout block is *shared* and committed.
  Zoom, scroll position, selection, and open tabs are *personal* and must be stored outside the file
  (for example in `.wiret-workspace` next to it, which is `.gitignore`d).
* The layout block is excluded from the **semantic hash** (see Tooling), so a rearranged graph is
  recognised as "same program, new picture" by CI, caches and incremental builds.

## Canonical form

`wiret fmt` is a deterministic function of the parse tree:

1. Header, then `module`, then module `meta`, then blank-line-separated blocks in the order: `use`,
   `extern`, `enum`, `struct`, `delegate`, `interface`, `var`/`const`, `class`, functions and macros.
2. In a node block, items appear as `meta`, `prop`, `in`, `exec`, each group in its original order.
3. Attribute lists are written `[k = v, …]` with keys sorted; numbers and strings are normalised.
4. Declaration and node **order is preserved**.

Parsing the formatted output yields an identical tree, and formatting is idempotent; the reference
tests check both on every example.

## Diagnostics

The compiler reports structured diagnostics: a stable code, a message, the function, the node id and,
where relevant, the pin. Editors use these to underline nodes; LLM tools can feed them back verbatim.

| Code | Meaning |
| --- | --- |
| E0101 | unknown node kind |
| E0102 | pin type mismatch or invalid literal |
| E0103 | missing or malformed type argument |
| E0104 | operation not defined for that type (`Sqrt<i32>`, `Lt<bool>`) |
| E0105 | data cycle through pure nodes |
| E0110 | reference to an unknown node |
| E0111 | unknown input/output pin |
| E0112 | exec connection to an unknown node |
| E0113 | unknown exec output pin |
| E0114 | exec target has no such exec input |
| E0120–E0122 | unknown local/state, global variable, or function |
| E0130, E0131 | duplicate node id; missing or duplicate `Entry` |
| E0201 | latent call from a non-latent function |
| E0202 | pure function performs a side effect |
| E0301 | an execution path ends without `Return` |
| E0305 | `Sequence` re-enters itself unboundedly |
| E0310, E0311 | recursive macro; macro without exactly one `Entry`/`Exit` |
| W0001 | node unreachable from `Entry` (warning) |


---

`docs/02-text-syntax.md`

# Wiret Text Syntax

File extension `.wiret`, encoding UTF-8, canonical line ending LF. This chapter is normative for the **Wiret text format, version 0.1**.

## Design principles

1. **One fact per line.** Every pin binding, every exec connection and every metadata entry is its own line, so a Git diff of a graph reads like a list of edits.
2. **Connections are stored once**, by their owner (see the [overview](#01-overview)): `in` lines on the consumer, `exec` lines on the source.
3. **Semantics, metadata and layout are separate.** Semantics live in `graph`; presentation-only data lives in `layout`; descriptive data lives in `meta`/`[...]` attributes. Changing a node's position never touches the lines that define behaviour, so semantic and layout edits from different people do not conflict.
4. **Whitespace is not significant** (newlines included), so sloppy generator output still parses. The *formatter* defines the canonical layout and tools should always write it.
5. **Explicit over inferred.** Types are always written (`Add<i32>`); output pins are always named (`%add.result`). There is no inference for a model or a merge tool to get wrong.

## Lexical structure

| Token | Form | Examples |
|---|---|---|
| comment | `;` to end of line | `; this is ignored` |
| identifier | `[A-Za-z_][A-Za-z0-9_]*` | `Fib`, `then_0` |
| node id | `%` identifier | `%entry`, `%add_k3f9` |
| symbol | `@` dotted identifier | `@Fib`, `@flow.ForLoop`, `@Door.Toggle` |
| local | `$` identifier | `$acc` |
| integer | decimal or `0x` hex, optional `-` | `42`, `-7`, `0xFF` |
| float | decimal with `.` or exponent; `inf`, `-inf`, `nan` | `3.14`, `1e-3` |
| string | `"` … `"` with `\n \t \r \" \\ \0 \u{hex}` | `"hello\n"` |
| colour | `#` 3–8 hex digits | `#3a5f8a` |
| punctuation | `{ } ( ) [ ] < > , : = . ->` | |

Comments are discarded by the parser and **not preserved by tools**. Human commentary belongs in `meta comment = "..."`, which every editor can show and keep.

Keywords (`node`, `in`, `exec`, `prop`, `meta`, `graph`, `layout`, `local`, `state`, …) are *contextual*: they are only special where the grammar expects them, so `in` is a valid pin name.

### Identifier conventions

Node ids are chosen by the editor and **never renumbered or reused**. Recommended form: a readable slug plus a 4-character random suffix, `%branch_k3f9`. The suffix makes it vanishingly unlikely that two collaborators who each add an "add" node on separate branches pick the same id, which would otherwise be a spurious merge conflict. Ids expanded from macros are path-like in diagnostics and debug info: `%loop/check` (inside macro node `%loop`) and `%loop!body` (the exit stub for its `body` pin).

## File structure

```
file      = "wiret" VERSION  decl*
decl      = module | meta | use | extern | enum | struct | delegate | interface
          | class | var | function | event | macro
```

The first token must be `wiret` followed by the format version (`0.1`). Readers reject a newer **major** version and ignore unknown `meta`/attribute keys, which is how the format grows compatibly.

### Module header, imports, externs

```wiret
wiret 0.1

module "game.inventory"
meta doc = "Inventory rules."
meta author = "larry"

use "std.flow" as flow                     ; Wiret library module, referenced as flow.X

extern function print = "std.print"(text: string)                    ; host function
pure extern function sqrt = "std.math.sqrt"(x: f64) -> (r: f64)
latent extern function delay = "std.delay"(seconds: f32)
extern type Texture = "host.Texture"                                  ; opaque host type
```

`extern function NAME = "module.field"` declares a function the **host** provides. It becomes `@NAME` in graphs and an *import* in the bytecode, which the runtime must resolve at link time. Modifiers `pure` and `latent` are part of the contract and checked at link time.

### Types

```
type = IDENT [ "." IDENT ] [ "<" type { "," type } ">" ]
```

Primitive: `bool i32 i64 f32 f64 string any`. Generic builtins: `array<T> map<K,V> set<T> dispatcher<D>`. Anything else is a user `struct`, `enum`, `class`, `interface`, `delegate` or `extern type` name, optionally qualified by a `use` alias.

### Enums, structs, delegates

```wiret
enum Rarity {
  Common = 0,
  Rare,
  Epic = 10 [color = #a335ee],
}

struct Item {
  id: i32,
  name: string = "unnamed",
  tags: array<string>,
}

delegate OnDamage(amount: i32, source: string)
```

Enum members count up from the previous value. Enums are `i32` in bytecode; the names are metadata. Structs are **immutable values**.

### Variables

```wiret
var gold: i32 = 0 [category = "Economy", tooltip = "Coins carried"]
const max_stack: i32 = 99
```

Module-level `var`s are globals (shared by everything in the VM instance). Inside a class, `var` declares an instance field.

### Classes and interfaces  *(specified, not in the reference toolchain)*

```wiret
interface Openable {
  function Open() -> (ok: bool)
}

class Door : Entity, Openable {
  meta category = "World"
  var is_open: bool = false
  var on_opened: dispatcher<OnDamage>

  function Open() -> (ok: bool) { graph { /* ... self available on Entry */ } }
  latent event Interact(who: string) { graph { /* ... */ } }
}
```

A class has at most one base class and any number of interfaces. Methods have an implicit `self` output on their `Entry` node. Dispatch is virtual by name and signature.

## Functions, events and macros

```
func   = { "export" | "pure" | "latent" } ("function" | "event" | "macro") NAME
         [ "<" TPARAM { "," TPARAM } ">" ]          ; macros only
         "(" pins ")" [ "->" "(" pins ")" ]
         [ "{" { meta | local | state | graph | layout } "}" ]
pins   = pin { "," pin }
pin    = NAME ":" type [ "=" literal ] [ attrs ]     ; data pin
       | "exec" NAME                                  ; exec pin (macros only)
```

```wiret
export function SumTo(n: i32) -> (sum: i32) {
  meta category = "Math"
  local $acc: i32 = 0
  graph { ... }
  layout { ... }
}
```

- **Modifiers.** `export` makes the function callable by the host. `pure` forbids side effects (no global writes, only pure calls). `latent` may suspend. Events are always exported.
- **Locals.** `local $name: type [= literal]` declares a per-call register, accessed by `GetLocal<$name>` / `SetLocal<$name>`.
- **State.** `state $name: type [= literal]` (macros) declares a slot that persists across calls and belongs to *that expansion of the macro* (see `DoOnce`). Accessed by `GetState` / `SetState`.
- **Macros.** Exec pins are declared with `exec`. A data *result* belongs to the exec result that **precedes it** in the list and is computed only when that exec fires; results before any exec result belong to all of them.

```wiret
macro ForLoop(exec in, first: i32 = 0, last: i32 = 0)
    -> (exec body, index: i32, exec completed) { ... }
```

Here `index` is written only when `body` fires. A macro must contain exactly one `Entry` node (its exec outputs are the macro's exec inputs, its data outputs the macro's data inputs) and exactly one `Exit` node (its exec *inputs* are the macro's exec outputs; its `in` bindings are the macro's data results).

## The graph block

```
graph  = "graph" "{" { node } "}"
node   = "node" NODEID ":" KIND [ "<" targ { "," targ } ">" ] "{" { item } "}"
KIND   = IDENT { "." IDENT }
targ   = type | SYMBOL | LOCAL | integer | string
item   = "meta" NAME "=" value
       | "prop" NAME "=" value                 ; compile-time configuration
       | "in"   PIN  "=" ( literal | NODEID "." PIN )   ; data input binding
       | "exec" PIN  "->" NODEID [ "." PIN ]            ; exec output connection
```

### The four item kinds

| Item | Meaning | Affects execution? |
|---|---|---|
| `in a = %n.out` / `in a = 5` | data input comes from a wire or a literal | yes |
| `exec then -> %next` / `-> %macro.reset` | exec output connects to a target's exec input (default: its first exec input) | yes |
| `prop cases = [1, 2, 5]` | compile-time constant configuration | yes |
| `meta comment = "..."` | information for people and tools | no |

Canonical item order is `meta`, `prop`, `in`, `exec`; order is otherwise preserved from the file.

### Rules

- **Unlisted data inputs** take the pin's default: the declared default for function/macro parameters, otherwise the type default (`0`, `0.0`, `false`, `""`, `null`, a fresh empty array).
- **Unlisted exec outputs** mean *end of this path* (the flow returns to the innermost `Sequence`, or ends the function; see the [overview](#01-overview)). A function with results must reach a `Return` on every path (`E0301`).
- **An exec input may have many incoming connections** (a merge). An exec output has at most one target (that is why `exec` is a single line).
- **Data cycles** between pure nodes are errors (`E0105`). Exec cycles are loops.
- Pins are *always* named; there is no default output pin.
- **Integer literals may initialise float pins**, `in b = 2` on an `f32` pin is fine; a float on an integer pin is `E0102`.

### Literals

```
literal = integer | float | string | "true" | "false" | "null"
        | "[" [ literal { "," literal } ] "]"            ; array
        | "{" NAME ":" literal { "," ... } "}"            ; struct
        | ENUM "." MEMBER                                 ; enum member
```

### Examples of node kinds

```wiret
node %lt : Lt<i32> {                    ; pure: compare
  in a = %entry.n
  in b = 2
}
node %check : Branch {                  ; impure, two exec outputs
  in condition = %lt.result
  exec then -> %base_case
  exec else -> %recurse
}
node %pick : Switch<i32> {              ; prop configures the pins case_0.. + default
  prop cases = [10, 20, 30]
  in value = %entry.code
  exec case_0 -> %a
  exec case_1 -> %b
  exec default -> %fallback
}
node %loop : flow.ForLoop {             ; macro instance (qualified by `use` alias)
  in first = 1
  in last = %entry.n
  exec body -> %add
  exec completed -> %done
}
node %log : Call<@print> {              ; call a function or host function
  in text = "hello"
}
```

## The layout block

```
layout = "layout" "{" { place | box } "}"
place  = NODEID "at" "(" INT "," INT ")" [ attrs ]
box    = "box" STRING "at" "(" INT "," INT ")" "size" "(" INT "," INT ")" [ attrs ]
```

```wiret
layout {
  %entry at (0, 0)
  %lt at (260, 160) [collapsed = true]
  box "Base case" at (-20, -70) size (1180, 330) [color = #3a5f8a]
}
```

- Coordinates are **integers** in editor units (1 unit = 1 px at 100% zoom), x right, y down. Editors snap to integers so that layout never produces float-formatting noise.
- Entries are one per line and keyed by node id, so moving two different nodes never conflicts.
- A node without an entry is placed by the editor's auto-layout; editors should then write the position they chose so that everyone sees the same thing.
- Layout never affects the bytecode or the **semantic hash**. Comment boxes can *contain* nodes by geometry (an editor concept); the file stores only the rectangle.
- **Not stored**: zoom, scroll position, selection, which pins are expanded in the details panel. These are per-user and live in the editor's own workspace files, so opening a graph does not dirty it.

Recognised layout attributes: `collapsed`, `color`, `width` (for resizable nodes), `comment_bubble`. Unknown attributes are preserved.

## Attributes and metadata

Block declarations (`module`, `function`, `class`, `node`, …) take `meta NAME = value` lines. Single-line declarations (`var`, parameters, fields, enum members, struct fields) take a trailing `[name = value, ...]`, written sorted by name in canonical form. Well-known keys: `doc`, `category`, `tooltip`, `comment`, `deprecated`, `display_name`, `keywords`, `color`. They never change generated code; a conforming compiler may only read them for diagnostics.

## Canonical form

`wiret fmt` must produce **byte-identical output for equal ASTs**:

- 2-space indentation, LF, a single trailing newline, one blank line between top-level declarations.
- `node %id : Kind<args> {}` with `{}` on the same line if the node has no items; otherwise one item per line.
- Numbers in shortest round-trip decimal form; floats always contain `.` or an exponent.
- Attribute lists sorted by key. `meta` lines keep their order.
- **Order of nodes is preserved**, never sorted, so a reader sees the author's reading order and a diff stays local. New nodes should be written directly after the node they were created from. `wiret fmt --sort` orders nodes by exec-flow reading order for tools that want a normal form.

### Semantic hash

`wiret hash` is a SHA-256 over the canonical form with all `layout` blocks and all `meta`/attributes removed and nodes sorted by id. Two files with the same hash compile to the same bytecode. CI can use this to skip recompilation or to flag "layout-only" commits.

## Complete example: loops and calls

```wiret
use "std.flow" as flow

export function SumTo(n: i32) -> (sum: i32) {
  local $acc: i32 = 0
  graph {
    node %entry : Entry {
      exec then -> %loop
    }
    node %loop : flow.ForLoop {
      in first = 1
      in last = %entry.n
      exec body -> %accumulate
      exec completed -> %done
    }
    node %get_acc : GetLocal<$acc> {}
    node %plus : Add<i32> {
      in a = %get_acc.value
      in b = %loop.index
    }
    node %accumulate : SetLocal<$acc> {
      in value = %plus.result
    }
    node %done : Return {
      in sum = %get_acc.value
    }
  }
}
```

{{SVG:sumto.svg}}

Note that `%accumulate` has no `exec` line: the end of the loop body returns to the loop. `%done` is wired from `completed`.

## Why not XML, JSON, DOT or GML directly?

- **XML/JSON** can carry the data but bury it: every pin becomes several nested objects, diffs show brackets and commas, and an LLM must track deep nesting to find "what feeds this input".
- **DOT** describes *edges* in a separate list with no types and no notion of pin direction. A Wiret edge is stored with the node that owns it and carries a type.
- **GML** is the closest in spirit (nested key-value lists) but is weakly typed and has no canonical form.

Wiret borrows the good parts: LLVM's one-instruction-per-line typed operands, DOT's `->` for flow and `[attr=value]` for annotation, GML's nested `graph`/`node` structure and editor geometry (`layout`).

## Grammar summary

```
file        = "wiret" VERSION { decl }
decl        = "module" STRING
            | "meta" NAME "=" value
            | "use" STRING "as" NAME
            | [ "pure" | "latent" ] "extern" ( "function" NAME "=" STRING "(" pins ")" [ "->" "(" pins ")" ]
                                              | "type" NAME "=" STRING )
            | "enum" NAME "{" { NAME [ "=" INT ] [ attrs ] "," } "}"
            | "struct" NAME "{" { NAME ":" type [ "=" literal ] [ attrs ] "," } "}"
            | "delegate" NAME "(" pins ")" [ "->" "(" pins ")" ]
            | "interface" NAME "{" { func } "}"
            | "class" NAME [ ":" type { "," type } ] "{" { meta | var | func } "}"
            | ( "var" | "const" ) NAME ":" type [ "=" literal ] [ attrs ]
            | func
attrs       = "[" NAME "=" value { "," NAME "=" value } "]"
value       = literal | COLOUR | IDENT
```


---

`docs/03-bytecode.md`

# 03 — Wiret Bytecode (WBC) specification

WBC is the compiled form of a Wiret module: a compact, **typed stack machine** with a section-based binary container. It borrows the container and encoding style of **WebAssembly** (sections, LEB128, validation before execution, traps), and the object model of the **JVM** (typed references, classes with single inheritance and vtables, a verifier, garbage-collected heap), while adding two things graph languages need: **fibers** (suspension is a first-class instruction) and a **node source map** (every instruction range knows which node it came from).

Design goals: (1) *one-pass verifiable* in linear time; (2) *deterministic* — same inputs, same results on every platform; (3) *small* — a typical module is a few KB; (4) *safe* — no raw memory access, no undefined behaviour; a verified module can only trap, never corrupt the VM.

## 1. Conventions

* Multi-byte fixed-width numbers are **little-endian**.
* `u32`, `u64` — unsigned **LEB128**; `s32`, `s64`, `s33` — signed LEB128 (at most 5, 10, 5 bytes).
* `f32`, `f64` — IEEE-754 binary32/64, little-endian bytes.
* `string` — `u32` byte length followed by UTF-8 bytes (no terminator, must be valid UTF-8).
* `vec(T)` — `u32` count followed by that many `T`.
* `rel32` — signed 32-bit little-endian *fixed-width* branch offset (fixed width so code generators can patch forward branches).
* File extension `.wbc`; media type `application/x-wiret-bytecode`.

## 2. Container

```
module  = magic version section*
magic   = 0x00 0x57 0x42 0x43          ; "\0WBC"
version = 0x01 0x00 0x00 0x00          ; u32 little-endian, = 1
section = id:u8  size:u32  payload[size]
```

Non-custom sections appear **at most once, in ascending id order**. Custom sections (id 0) may appear anywhere and are ignored by the VM unless it recognises the name.

| Id | Section | Content |
|---|---|---|
| 0 | Custom | `name:string` then opaque bytes (§10) |
| 1 | Types | `vec(typedef)` |
| 2 | Imports | `vec(import)` |
| 3 | Functions | `vec(typeidx:u32)` — signature of each *defined* function |
| 4 | Globals | `vec(global)` |
| 5 | Exports | `vec(export)` |
| 6 | Constants | `vec(string)` — string constant pool for `str.const` |
| 7 | Code | `vec(body)` — one per defined function, same order as section 3 |

**Index spaces.** *Type indices* count entries of the Types section. *Function indices* count imported functions first (in import order), then defined functions. *Global indices* count the Globals section. *Local indices* are per function: parameters first, then declared locals.

## 3. Value types

| Encoding | Type | Meaning |
|---|---|---|
| `0x7F` | `i32` | 32-bit integer (also `bool`, `i8`/`i16`/`u8`/`u16`/`u32`) |
| `0x7E` | `i64` | 64-bit integer (also `u64`) |
| `0x7D` | `f32` | |
| `0x7C` | `f64` | |
| `0x70 h` | `ref h` | Nullable reference; `h` is a heap type (`s33`) |

**Heap types** `h`: negative values are built-in — `-1` `string`, `-2` `object` (root of all class types; also the type of `await` operands). Non-negative values are indices into the Types section and must denote a class, struct, array, map, set or function type.

Integer signedness is *not* part of the type; it lives in the instruction (`lt_s` vs `lt_u`). `bool` is `i32` restricted to 0/1 by the compiler.

**Subtyping.** `ref C ≤ ref D` iff `C` is `D` or a descendant of `D` along `super` links, or `D` is `object` and `C` is any class type. All other reference types are only subtypes of themselves; `string` is not an `object`. Null is a member of every reference type.

## 4. Types section

Each `typedef` starts with a kind byte:

| Kind | Form |
|---|---|
| `0x60` func | `params:vec(valtype)  results:vec(valtype)` |
| `0x61` struct | `name:string  fields:vec(field)` — **value semantics** (§7.2) |
| `0x62` class | `name:string  super:u32  flags:u8  fields:vec(field)  vtable:vec(u32)` |
| `0x63` array | `elem:valtype` |
| `0x64` map | `key:valtype  value:valtype` |
| `0x65` set | `elem:valtype` |

* `name` is the **fully qualified** name (`Doors::Item`). Types with equal qualified names in different modules are **unified at link time** and must have identical structure (this is how `@Std::Vec3` is shared).
* class `super`: `0` = root (`object`), else `typeidx + 1`. The hierarchy must be acyclic and ancestors must be defined *earlier* in the section.
* class `flags`: bit 0 = **extern** (host-implemented: no fields, no vtable; instances are created by the host; linking fails if the host has not registered a type of that name — Chapter 04 §7).
* class `vtable`: the **complete** table of function indices for virtual methods (inherited, overridden and new, in slot order); a subclass's table begins with its parent's slots, and each entry has a signature equal to the parent's except that `self` may be a subtype.
* `field = name:string  type:valtype  default:default`.
* Map keys / set elements must be `i32`, `i64` or `ref string`. (`bool`, enums and all integer types lower to `i32`/`i64`.)

**`default` encoding** (used by fields and globals): a tag byte followed by:

| Tag | Meaning | Payload |
|---|---|---|
| `0x00` | zero / `null` | — |
| `0x01` | fresh default instance of the field's own type (empty array/map/set, default struct) | — |
| `0x02` | integer constant | `s64` (narrowed to `i32` if the field is `i32`) |
| `0x03` | float constant | 4 bytes (`f32` field) or 8 bytes (`f64` field) |
| `0x04` | string constant | `u32` index into Constants |

`rec.new`, `array.new`, `map.new`, `set.new` construct defaults; initialising a `ref string` field with tag `0x00` yields **the empty string**, not null (strings are never null in verified code; `ref.null string` is rejected).

## 5. Imports, functions, globals, exports

```
import  = module:string  name:string  kind:u8  typeidx:u32       ; kind 0 = function
global  = name:string  type:valtype  flags:u8  default           ; flags: bit0 mutable, bit1 exported
export  = name:string  kind:u8  index:u32  flags:u8              ; kind 0 = function, 1 = global; flags: bit0 = event
```

* An import's `(module, name)` is resolved at link time: `module` is a registered **host library** (`"host"`, `"wiret.math"`, …) or another loaded WBC module. Signatures must match exactly (Chapter 04 §6).
* Export names are unique. Functions marked `event` are the entry points the host may fire as new fibers; exported non-event functions are callable but are normally invoked from the host as plain calls.
* Static slots (`static`) and macro-instance statics are compiled to non-exported mutable **globals**.

## 6. Code section

```
body   = size:u32  flags:u8  max_stack:u32  locals:vec(localgroup)  code[...]
localgroup = count:u32  type:valtype
```

* `flags`: bit 0 **latent** (contains or transitively calls `yield`/`sleep`/`await`/a latent import), bit 1 `pure` (informational), bit 2 `event`.
* `max_stack` — maximum operand-stack depth, **verified** by the loader.
* Declared locals come after the parameters; all locals start as zero / `null` (verified code initialises value-typed locals explicitly).
* `code` runs to the end of `size`; **the last instruction must be unconditional** (`br`, `br_table`, `ret`, `unreachable`).
* Branch offsets are `rel32`, **relative to the address of the branching instruction's opcode byte**, and must land on an instruction boundary inside the same body.

## 7. Execution model

### 7.1 State
A **VM** owns the heap, loaded modules and host registrations. A **fiber** owns a call stack of **frames** (locals + operand stack). Fibers are cooperative: exactly one runs at a time per VM thread of execution; a fiber runs until it returns, traps, or executes a suspending instruction. *No other fiber is scheduled in between*, so no locking is needed in bytecode.

Fiber states: `READY → RUNNING → {SUSPENDED, DONE, FAILED}`. `yield` makes the fiber ready for the next `tick`; `sleep` suspends it until VM time advances by the given seconds (time only moves when the host calls `tick`); `await` suspends until the host signals the awaitable. A host function may also suspend the fiber (Chapter 04 §9).

### 7.2 Memory and value semantics
Heap objects are strings (immutable), records (struct/class), arrays, maps, sets, and function values. Memory is reclaimed by a precise garbage collector whose strategy is implementation-defined; extern class instances carry a host finaliser.

Source-level *value semantics* of struct/array/map/set is implemented by the **compiler**, with the `clone` instruction at store points (Chapter 00 §4). The VM itself treats them as ordinary references: `rec.set` stores the reference it is given. Every operation that creates a new object (`rec.new`, `clone`, `array.new`…) produces a *unique* reference.

### 7.3 Calling convention
Arguments are popped from the caller's operand stack into the callee's locals `0 … n-1` (first argument = local 0). On `ret` the callee's results are pushed onto the caller's stack. Maximum call depth is a VM limit (default 256); exceeding it traps `STACK_OVERFLOW`.

### 7.4 Determinism
Given identical module bytes, host-function results and `tick` sequence, execution is identical on every platform: integers wrap; shifts mask their count; float operations are IEEE-754 round-to-nearest-even with **no fused operations**; any arithmetic NaN result is the canonical quiet NaN (`0x7FC00000` / `0x7FF8000000000000`); `map`/`set`/`keys` order is insertion order; `str.*` are defined on Unicode scalar values with a fixed Unicode version (15.1).

### 7.5 Traps
A **trap** aborts the fiber and delivers an error (code, message, backtrace of `(function, pc)` pairs) to the host. The VM stays valid.

| Code | Name | Raised by |
|---|---|---|
| 1 | `UNREACHABLE` | `unreachable` |
| 2 | `NULL_REF` | field access, call, `array.*` etc. on null |
| 3 | `INDEX_RANGE` | `array.get/set/insert/remove`, `array.pop` of empty |
| 4 | `DIV_ZERO` | integer `div`/`rem` by 0 |
| 5 | `INT_OVERFLOW` | `i32.div_s` / `i64.div_s` of MIN / −1 |
| 6 | `CAST_FAIL` | `ref.cast` |
| 7 | `KEY_MISSING` | `map.get` |
| 8 | `STACK_OVERFLOW` | call depth or operand-stack limit |
| 9 | `OUT_OF_MEMORY` | allocation beyond the VM limit |
| 10 | `HOST_ERROR` | a host function reported an error |
| 11 | `BAD_AWAIT` | `await` on a null or foreign object |

(An exhausted *instruction budget* is not a trap: the fiber is paused and may be resumed — Chapter 04 §9.)

## 8. Verification

Loading **must** verify before any code runs. All checks are linear time and single pass.

**Module level:** magic/version; sections in order and exactly sized; all indices in range; types well-formed (acyclic hierarchy, valid vtables, key/element restrictions); defined function count equals code count; export uniqueness; constant strings valid UTF-8.

**Per function** (the core invariant — Wiret's stand-in for stack maps):

1. Decode all instructions, record instruction boundaries; reject truncated or unknown opcodes (including every reserved opcode).
2. Collect all branch targets; each must be a boundary in the same body.
3. Walk forward with an **abstract type stack**, starting empty. For each instruction: pop/check operand types (with subtyping for references), push results.
4. **Empty-stack rule:** the abstract stack must be **empty** (a) immediately after the operand-popping of every `br`, `br_if`, `br_ifnot`, `br_table`; (b) at every instruction that is a branch target; (c) after every unconditional transfer (`br`, `br_table`, `ret`, `unreachable`), where the walk resumes with an empty stack. *No values live on the operand stack across control flow.* The compiler guarantees this by keeping values in locals between blocks (Chapter 02 §11.1).
5. `ret` requires exactly the result types on the stack and nothing else; locals are checked by declared type; `local.tee`, `select` obey their stack types; `ref.null string` is rejected; `ref.cast`/`ref.test` must target a type that is a *subtype-or-supertype* of the operand's static type.
6. The final instruction is an unconditional transfer.
7. The computed maximum stack depth must be ≤ `max_stack`.

A module failing any check is rejected whole with an error naming the function and byte offset.

## 9. Instruction set

All opcodes are one byte, followed by immediates. Stack effects are written `[consumed] -> [produced]`, top of stack rightmost. Opcodes not listed (`0x0D–0x0F`, `0x14–0x1F`, `0x25–0x2F`, `0x36–0x3F`, `0xBD–0xBF`, `0xCB–0xFA`, `0xFC–0xFF`) are **reserved** and rejected by the verifier.

<!-- BEGIN OPCODES -->
| Hex | Mnemonic | Immediates | Stack | Notes |
|---|---|---|---|---|
| `00` | `nop` | — | `[] -> []` | No operation. |
| `01` | `unreachable` | — | `[] -> trap` | Always traps (code UNREACHABLE). |
| `02` | `br` | rel32 | `[] -> []` | Unconditional branch. Stack must be empty. |
| `03` | `br_if` | rel32 | `[i32] -> []` | Branch if value != 0. Stack must be empty after the pop. |
| `04` | `br_ifnot` | rel32 | `[i32] -> []` | Branch if value == 0. Stack must be empty after the pop. |
| `05` | `br_table` | n:u32, (n+1)*rel32 | `[i32] -> []` | Jump table; index n or greater selects the last (default) entry. Stack empty after the pop. |
| `06` | `ret` | — | `[results] -> []` | Return from function; stack holds exactly the declared results. |
| `07` | `call` | func:u32 | `[params] -> [results]` | Direct call (module function or import). |
| `08` | `call_ref` | type:u32 | `[params, fn] -> [results]` | Call a function value; type is the expected signature. Traps on null. |
| `09` | `call_virt` | type:u32, slot:u32 | `[self, params] -> [results]` | Virtual call through the receiver's class vtable. Traps on null receiver. |
| `0A` | `yield` | — | `[] -> []` | Suspend the fiber until the next scheduler tick. |
| `0B` | `sleep` | — | `[f64] -> []` | Suspend the fiber for the given number of seconds of VM time. |
| `0C` | `await` | — | `[ref any] -> []` | Suspend until the host-owned awaitable object signals completion. |
| `10` | `drop` | — | `[t] -> []` | Discard top value. |
| `11` | `dup` | — | `[t] -> [t t]` | Duplicate top value. |
| `12` | `swap` | — | `[a b] -> [b a]` | Swap top two values. |
| `13` | `select` | — | `[a b i32] -> [t]` | Pushes a if cond != 0 else b. a and b must have the same type. Both are already evaluated. |
| `20` | `local.get` | idx:u32 | `[] -> [t]` | Push local (parameters are locals 0..n-1). |
| `21` | `local.set` | idx:u32 | `[t] -> []` | Pop into local. |
| `22` | `local.tee` | idx:u32 | `[t] -> [t]` | Store into local, keep value. |
| `23` | `global.get` | idx:u32 | `[] -> [t]` | Push module global. |
| `24` | `global.set` | idx:u32 | `[t] -> []` | Pop into module global. |
| `30` | `i32.const` | v:s32 | `[] -> [i32]` | LEB128 signed immediate. |
| `31` | `i64.const` | v:s64 | `[] -> [i64]` | LEB128 signed immediate. |
| `32` | `f32.const` | v:f32 | `[] -> [f32]` | 4 bytes little-endian. |
| `33` | `f64.const` | v:f64 | `[] -> [f64]` | 8 bytes little-endian. |
| `34` | `str.const` | idx:u32 | `[] -> [string]` | Push string from constant pool. |
| `35` | `ref.null` | heap:s33 | `[] -> [ref]` | Push null reference of the given heap type. |
| `40` | `i32.eqz` | — | `[i32] -> [i32]` | Compare; result 1 or 0. |
| `41` | `i32.eq` | — | `[i32 i32] -> [i32]` | Compare; result 1 or 0. |
| `42` | `i32.ne` | — | `[i32 i32] -> [i32]` | Compare; result 1 or 0. |
| `43` | `i32.lt_s` | — | `[i32 i32] -> [i32]` | Compare; result 1 or 0. |
| `44` | `i32.lt_u` | — | `[i32 i32] -> [i32]` | Compare; result 1 or 0. |
| `45` | `i32.gt_s` | — | `[i32 i32] -> [i32]` | Compare; result 1 or 0. |
| `46` | `i32.gt_u` | — | `[i32 i32] -> [i32]` | Compare; result 1 or 0. |
| `47` | `i32.le_s` | — | `[i32 i32] -> [i32]` | Compare; result 1 or 0. |
| `48` | `i32.le_u` | — | `[i32 i32] -> [i32]` | Compare; result 1 or 0. |
| `49` | `i32.ge_s` | — | `[i32 i32] -> [i32]` | Compare; result 1 or 0. |
| `4A` | `i32.ge_u` | — | `[i32 i32] -> [i32]` | Compare; result 1 or 0. |
| `4B` | `i64.eqz` | — | `[i64] -> [i32]` | Compare; result 1 or 0. |
| `4C` | `i64.eq` | — | `[i64 i64] -> [i32]` | Compare; result 1 or 0. |
| `4D` | `i64.ne` | — | `[i64 i64] -> [i32]` | Compare; result 1 or 0. |
| `4E` | `i64.lt_s` | — | `[i64 i64] -> [i32]` | Compare; result 1 or 0. |
| `4F` | `i64.lt_u` | — | `[i64 i64] -> [i32]` | Compare; result 1 or 0. |
| `50` | `i64.gt_s` | — | `[i64 i64] -> [i32]` | Compare; result 1 or 0. |
| `51` | `i64.gt_u` | — | `[i64 i64] -> [i32]` | Compare; result 1 or 0. |
| `52` | `i64.le_s` | — | `[i64 i64] -> [i32]` | Compare; result 1 or 0. |
| `53` | `i64.le_u` | — | `[i64 i64] -> [i32]` | Compare; result 1 or 0. |
| `54` | `i64.ge_s` | — | `[i64 i64] -> [i32]` | Compare; result 1 or 0. |
| `55` | `i64.ge_u` | — | `[i64 i64] -> [i32]` | Compare; result 1 or 0. |
| `56` | `f32.eq` | — | `[f32 f32] -> [i32]` | IEEE-754 compare; any NaN operand gives 0 (1 for ne). |
| `57` | `f32.ne` | — | `[f32 f32] -> [i32]` | IEEE-754 compare; any NaN operand gives 0 (1 for ne). |
| `58` | `f32.lt` | — | `[f32 f32] -> [i32]` | IEEE-754 compare; any NaN operand gives 0 (1 for ne). |
| `59` | `f32.gt` | — | `[f32 f32] -> [i32]` | IEEE-754 compare; any NaN operand gives 0 (1 for ne). |
| `5A` | `f32.le` | — | `[f32 f32] -> [i32]` | IEEE-754 compare; any NaN operand gives 0 (1 for ne). |
| `5B` | `f32.ge` | — | `[f32 f32] -> [i32]` | IEEE-754 compare; any NaN operand gives 0 (1 for ne). |
| `5C` | `f64.eq` | — | `[f64 f64] -> [i32]` | IEEE-754 compare; any NaN operand gives 0 (1 for ne). |
| `5D` | `f64.ne` | — | `[f64 f64] -> [i32]` | IEEE-754 compare; any NaN operand gives 0 (1 for ne). |
| `5E` | `f64.lt` | — | `[f64 f64] -> [i32]` | IEEE-754 compare; any NaN operand gives 0 (1 for ne). |
| `5F` | `f64.gt` | — | `[f64 f64] -> [i32]` | IEEE-754 compare; any NaN operand gives 0 (1 for ne). |
| `60` | `f64.le` | — | `[f64 f64] -> [i32]` | IEEE-754 compare; any NaN operand gives 0 (1 for ne). |
| `61` | `f64.ge` | — | `[f64 f64] -> [i32]` | IEEE-754 compare; any NaN operand gives 0 (1 for ne). |
| `62` | `i32.clz` | — | `[i32] -> [i32]` | Bit count. |
| `63` | `i32.ctz` | — | `[i32] -> [i32]` | Bit count. |
| `64` | `i32.popcnt` | — | `[i32] -> [i32]` | Bit count. |
| `65` | `i32.add` | — | `[i32 i32] -> [i32]` | Wraps (two's complement). |
| `66` | `i32.sub` | — | `[i32 i32] -> [i32]` | Wraps. |
| `67` | `i32.mul` | — | `[i32 i32] -> [i32]` | Wraps. |
| `68` | `i32.div_s` | — | `[i32 i32] -> [i32]` | Traps on divide by zero or INT_MIN / -1. |
| `69` | `i32.div_u` | — | `[i32 i32] -> [i32]` | Traps on divide by zero. |
| `6A` | `i32.rem_s` | — | `[i32 i32] -> [i32]` | Traps on divide by zero; INT_MIN % -1 = 0. |
| `6B` | `i32.rem_u` | — | `[i32 i32] -> [i32]` | Traps on divide by zero. |
| `6C` | `i32.and` | — | `[i32 i32] -> [i32]` | Bitwise / rotate. |
| `6D` | `i32.or` | — | `[i32 i32] -> [i32]` | Bitwise / rotate. |
| `6E` | `i32.xor` | — | `[i32 i32] -> [i32]` | Bitwise / rotate. |
| `6F` | `i32.shl` | — | `[i32 i32] -> [i32]` | Shift count taken modulo bit width. |
| `70` | `i32.shr_s` | — | `[i32 i32] -> [i32]` | Arithmetic shift; count modulo bit width. |
| `71` | `i32.shr_u` | — | `[i32 i32] -> [i32]` | Logical shift; count modulo bit width. |
| `72` | `i32.rotl` | — | `[i32 i32] -> [i32]` | Bitwise / rotate. |
| `73` | `i32.rotr` | — | `[i32 i32] -> [i32]` | Bitwise / rotate. |
| `74` | `i64.clz` | — | `[i64] -> [i64]` | Bit count. |
| `75` | `i64.ctz` | — | `[i64] -> [i64]` | Bit count. |
| `76` | `i64.popcnt` | — | `[i64] -> [i64]` | Bit count. |
| `77` | `i64.add` | — | `[i64 i64] -> [i64]` | Wraps (two's complement). |
| `78` | `i64.sub` | — | `[i64 i64] -> [i64]` | Wraps. |
| `79` | `i64.mul` | — | `[i64 i64] -> [i64]` | Wraps. |
| `7A` | `i64.div_s` | — | `[i64 i64] -> [i64]` | Traps on divide by zero or INT_MIN / -1. |
| `7B` | `i64.div_u` | — | `[i64 i64] -> [i64]` | Traps on divide by zero. |
| `7C` | `i64.rem_s` | — | `[i64 i64] -> [i64]` | Traps on divide by zero; INT_MIN % -1 = 0. |
| `7D` | `i64.rem_u` | — | `[i64 i64] -> [i64]` | Traps on divide by zero. |
| `7E` | `i64.and` | — | `[i64 i64] -> [i64]` | Bitwise / rotate. |
| `7F` | `i64.or` | — | `[i64 i64] -> [i64]` | Bitwise / rotate. |
| `80` | `i64.xor` | — | `[i64 i64] -> [i64]` | Bitwise / rotate. |
| `81` | `i64.shl` | — | `[i64 i64] -> [i64]` | Shift count taken modulo bit width. |
| `82` | `i64.shr_s` | — | `[i64 i64] -> [i64]` | Arithmetic shift; count modulo bit width. |
| `83` | `i64.shr_u` | — | `[i64 i64] -> [i64]` | Logical shift; count modulo bit width. |
| `84` | `i64.rotl` | — | `[i64 i64] -> [i64]` | Bitwise / rotate. |
| `85` | `i64.rotr` | — | `[i64 i64] -> [i64]` | Bitwise / rotate. |
| `86` | `f32.abs` | — | `[f32] -> [f32]` | IEEE-754 (nearest = ties-to-even). |
| `87` | `f32.neg` | — | `[f32] -> [f32]` | IEEE-754 (nearest = ties-to-even). |
| `88` | `f32.ceil` | — | `[f32] -> [f32]` | IEEE-754 (nearest = ties-to-even). |
| `89` | `f32.floor` | — | `[f32] -> [f32]` | IEEE-754 (nearest = ties-to-even). |
| `8A` | `f32.trunc` | — | `[f32] -> [f32]` | IEEE-754 (nearest = ties-to-even). |
| `8B` | `f32.nearest` | — | `[f32] -> [f32]` | IEEE-754 (nearest = ties-to-even). |
| `8C` | `f32.sqrt` | — | `[f32] -> [f32]` | IEEE-754 (nearest = ties-to-even). |
| `8D` | `f32.add` | — | `[f32 f32] -> [f32]` | IEEE-754; min/max propagate NaN. |
| `8E` | `f32.sub` | — | `[f32 f32] -> [f32]` | IEEE-754; min/max propagate NaN. |
| `8F` | `f32.mul` | — | `[f32 f32] -> [f32]` | IEEE-754; min/max propagate NaN. |
| `90` | `f32.div` | — | `[f32 f32] -> [f32]` | IEEE-754; min/max propagate NaN. |
| `91` | `f32.min` | — | `[f32 f32] -> [f32]` | IEEE-754; min/max propagate NaN. |
| `92` | `f32.max` | — | `[f32 f32] -> [f32]` | IEEE-754; min/max propagate NaN. |
| `93` | `f32.copysign` | — | `[f32 f32] -> [f32]` | IEEE-754; min/max propagate NaN. |
| `94` | `f64.abs` | — | `[f64] -> [f64]` | IEEE-754 (nearest = ties-to-even). |
| `95` | `f64.neg` | — | `[f64] -> [f64]` | IEEE-754 (nearest = ties-to-even). |
| `96` | `f64.ceil` | — | `[f64] -> [f64]` | IEEE-754 (nearest = ties-to-even). |
| `97` | `f64.floor` | — | `[f64] -> [f64]` | IEEE-754 (nearest = ties-to-even). |
| `98` | `f64.trunc` | — | `[f64] -> [f64]` | IEEE-754 (nearest = ties-to-even). |
| `99` | `f64.nearest` | — | `[f64] -> [f64]` | IEEE-754 (nearest = ties-to-even). |
| `9A` | `f64.sqrt` | — | `[f64] -> [f64]` | IEEE-754 (nearest = ties-to-even). |
| `9B` | `f64.add` | — | `[f64 f64] -> [f64]` | IEEE-754; min/max propagate NaN. |
| `9C` | `f64.sub` | — | `[f64 f64] -> [f64]` | IEEE-754; min/max propagate NaN. |
| `9D` | `f64.mul` | — | `[f64 f64] -> [f64]` | IEEE-754; min/max propagate NaN. |
| `9E` | `f64.div` | — | `[f64 f64] -> [f64]` | IEEE-754; min/max propagate NaN. |
| `9F` | `f64.min` | — | `[f64 f64] -> [f64]` | IEEE-754; min/max propagate NaN. |
| `A0` | `f64.max` | — | `[f64 f64] -> [f64]` | IEEE-754; min/max propagate NaN. |
| `A1` | `f64.copysign` | — | `[f64 f64] -> [f64]` | IEEE-754; min/max propagate NaN. |
| `A2` | `i32.wrap_i64` | — | `[i64] -> [i32]` | Keep low 32 bits. |
| `A3` | `i32.trunc_f32_s` | — | `[f32] -> [i32]` | Saturating; NaN -> 0. |
| `A4` | `i32.trunc_f32_u` | — | `[f32] -> [i32]` | Saturating; NaN -> 0. |
| `A5` | `i32.trunc_f64_s` | — | `[f64] -> [i32]` | Saturating; NaN -> 0. |
| `A6` | `i32.trunc_f64_u` | — | `[f64] -> [i32]` | Saturating; NaN -> 0. |
| `A7` | `i64.extend_i32_s` | — | `[i32] -> [i64]` | Sign-extend. |
| `A8` | `i64.extend_i32_u` | — | `[i32] -> [i64]` | Zero-extend. |
| `A9` | `i64.trunc_f32_s` | — | `[f32] -> [i64]` | Saturating; NaN -> 0. |
| `AA` | `i64.trunc_f32_u` | — | `[f32] -> [i64]` | Saturating; NaN -> 0. |
| `AB` | `i64.trunc_f64_s` | — | `[f64] -> [i64]` | Saturating; NaN -> 0. |
| `AC` | `i64.trunc_f64_u` | — | `[f64] -> [i64]` | Saturating; NaN -> 0. |
| `AD` | `f32.convert_i32_s` | — | `[i32] -> [f32]` | Round to nearest. |
| `AE` | `f32.convert_i32_u` | — | `[i32] -> [f32]` | Round to nearest. |
| `AF` | `f32.convert_i64_s` | — | `[i64] -> [f32]` | Round to nearest. |
| `B0` | `f32.convert_i64_u` | — | `[i64] -> [f32]` | Round to nearest. |
| `B1` | `f32.demote_f64` | — | `[f64] -> [f32]` | Round to nearest. |
| `B2` | `f64.convert_i32_s` | — | `[i32] -> [f64]` | Exact. |
| `B3` | `f64.convert_i32_u` | — | `[i32] -> [f64]` | Exact. |
| `B4` | `f64.convert_i64_s` | — | `[i64] -> [f64]` | Round to nearest. |
| `B5` | `f64.convert_i64_u` | — | `[i64] -> [f64]` | Round to nearest. |
| `B6` | `f64.promote_f32` | — | `[f32] -> [f64]` | Exact. |
| `B7` | `i32.reinterpret_f32` | — | `[f32] -> [i32]` | Bit cast. |
| `B8` | `i64.reinterpret_f64` | — | `[f64] -> [i64]` | Bit cast. |
| `B9` | `f32.reinterpret_i32` | — | `[i32] -> [f32]` | Bit cast. |
| `BA` | `f64.reinterpret_i64` | — | `[i64] -> [f64]` | Bit cast. |
| `BB` | `i32.extend8_s` | — | `[i32] -> [i32]` | Sign-extend low 8 bits. |
| `BC` | `i32.extend16_s` | — | `[i32] -> [i32]` | Sign-extend low 16 bits. |
| `C0` | `rec.new` | type:u32 | `[] -> [ref]` | Allocate zero/default-initialised struct or class instance. |
| `C1` | `rec.get` | type:u32, field:u32 | `[ref] -> [t]` | Read field. Traps on null. |
| `C2` | `rec.set` | type:u32, field:u32 | `[ref t] -> []` | Write field. Traps on null. |
| `C3` | `clone` | type:u32 | `[ref] -> [ref]` | Deep copy of a value-semantics object (struct, array, map, set). Nested value-type members are copied; class references are shared. |
| `C4` | `ref.is_null` | — | `[ref] -> [i32]` | 1 if null. |
| `C5` | `ref.eq` | — | `[ref ref] -> [i32]` | Reference identity. |
| `C6` | `ref.cast` | type:u32 | `[ref] -> [ref]` | Checked downcast; traps on failure (null passes). |
| `C7` | `ref.test` | type:u32 | `[ref] -> [i32]` | 1 if non-null and an instance of type. |
| `C8` | `ref.cast_or_null` | type:u32 | `[ref] -> [ref]` | Downcast; yields null on failure. |
| `C9` | `fn.ref` | func:u32 | `[] -> [ref fn]` | Unbound function value. |
| `CA` | `fn.bind` | — | `[ref fn, ref self] -> [ref fn]` | Bind receiver as the first argument. |

**Extended instructions** — opcode `0xFB` followed by a LEB128 `u32` sub-opcode.

| Sub | Mnemonic | Immediates | Stack | Notes |
|---|---|---|---|---|
| `00` | `array.new` | type:u32 | `[] -> [ref]` | Empty array of array type. |
| `01` | `array.len` | — | `[ref] -> [i32]` | Element count. |
| `02` | `array.get` | — | `[ref i32] -> [t]` | Traps if index out of range. |
| `03` | `array.set` | — | `[ref i32 t] -> []` | Traps if index out of range. |
| `04` | `array.push` | — | `[ref t] -> []` | Append. |
| `05` | `array.pop` | — | `[ref] -> [t]` | Remove and return last. Traps if empty. |
| `06` | `array.insert` | — | `[ref i32 t] -> []` | Insert before index (index may equal len). |
| `07` | `array.remove` | — | `[ref i32] -> []` | Remove at index. Traps if out of range. |
| `08` | `array.clear` | — | `[ref] -> []` | Remove all. |
| `09` | `array.resize` | — | `[ref i32] -> []` | Grow with default values or truncate. |
| `0A` | `array.find` | — | `[ref t] -> [i32]` | Index of first equal element, or -1 (value equality for primitives and strings, identity for classes). |
| `20` | `map.new` | type:u32 | `[] -> [ref]` | Empty map. |
| `21` | `map.len` | — | `[ref] -> [i32]` | Entry count. |
| `22` | `map.has` | — | `[ref k] -> [i32]` | 1 if key present. |
| `23` | `map.get` | — | `[ref k] -> [v]` | Traps if key missing. |
| `24` | `map.get_or` | — | `[ref k v] -> [v]` | Value for key, or the supplied fallback. |
| `25` | `map.set` | — | `[ref k v] -> []` | Insert or overwrite. |
| `26` | `map.remove` | — | `[ref k] -> [i32]` | 1 if removed. |
| `27` | `map.clear` | — | `[ref] -> []` | Remove all. |
| `28` | `map.keys` | — | `[ref] -> [ref array<k>]` | Snapshot of keys in insertion order. |
| `29` | `map.values` | — | `[ref] -> [ref array<v>]` | Snapshot of values in insertion order. |
| `40` | `set.new` | type:u32 | `[] -> [ref]` | Empty set. |
| `41` | `set.len` | — | `[ref] -> [i32]` | Element count. |
| `42` | `set.has` | — | `[ref t] -> [i32]` | Membership. |
| `43` | `set.add` | — | `[ref t] -> [i32]` | 1 if newly added. |
| `44` | `set.remove` | — | `[ref t] -> [i32]` | 1 if removed. |
| `45` | `set.clear` | — | `[ref] -> []` | Remove all. |
| `46` | `set.to_array` | — | `[ref] -> [ref array<t>]` | Snapshot in insertion order. |
| `60` | `str.concat` | — | `[string string] -> [string]` | Concatenate. |
| `61` | `str.len` | — | `[string] -> [i32]` | Length in Unicode scalar values. |
| `62` | `str.byte_len` | — | `[string] -> [i32]` | Length in UTF-8 bytes. |
| `63` | `str.eq` | — | `[string string] -> [i32]` | Equality (byte-wise). |
| `64` | `str.cmp` | — | `[string string] -> [i32]` | -1 / 0 / 1 by code point order. |
| `65` | `str.sub` | — | `[string i32 i32] -> [string]` | Substring (start, length) in scalar values; clamped. |
| `66` | `str.find` | — | `[string string] -> [i32]` | Scalar index of first match or -1. |
| `67` | `str.replace` | — | `[string string string] -> [string]` | Replace all occurrences. |
| `68` | `str.split` | — | `[string string] -> [ref array<string>]` | Split on separator. |
| `69` | `str.join` | — | `[ref array<string> string] -> [string]` | Join with separator. |
| `6A` | `str.upper` | — | `[string] -> [string]` | Unicode default upper-casing. |
| `6B` | `str.lower` | — | `[string] -> [string]` | Unicode default lower-casing. |
| `6C` | `str.trim` | — | `[string] -> [string]` | Strip Unicode whitespace both ends. |
| `6D` | `str.from_i64` | — | `[i64] -> [string]` | Decimal text. |
| `6E` | `str.from_f64` | — | `[f64] -> [string]` | Shortest round-trip decimal text. |
| `6F` | `str.parse_i64` | — | `[string] -> [i64 i32]` | Parsed value and ok flag (0 on failure, value 0). |
| `70` | `str.parse_f64` | — | `[string] -> [f64 i32]` | Parsed value and ok flag. |
<!-- END OPCODES -->

**Notes.**
* *Saturating conversions:* all float→integer instructions saturate to the target range and map NaN to 0 — they never trap.
* *Comparisons* return `i32` 1/0.
* *Value equality* for `array.find`: integers and floats by value (floats: `==`, so NaN never found), strings by content, all other references by identity.
* *Strings* are always non-null; `str.*` operate on Unicode scalar values (not UTF-16 units). Invalid indices are clamped as stated, never trap.
* `call` on an imported function invokes the host (Chapter 04 §6); a host function may suspend the fiber.

## 10. Custom sections

| Name | Content | Purpose |
|---|---|---|
| `wiret.names` | `vec(funcidx:u32, name:string)`, `vec(typeidx:u32, name:string)`, enum tables `vec(enum)` where `enum = typename:string, underlying:u8, vec(member: string, s64)` | Debugging; hosts reflecting on enums |
| `wiret.map` | `vec(fnmap)`; `fnmap = funcidx:u32, vec(range), vec(localpin)`; `range = pc_start:u32, pc_end:u32, node:string, role:u8`; `localpin = local:u32, node:string, pin:string` | **Node source map.** `pc` is the byte offset from the start of the function's `code`. Ranges are sorted and disjoint. `role`: 0 = node body, 1 = evaluation of a pure input, 2 = transfer of a wire/continuation |
| `wiret.hash` | 32 bytes | Semantic hash of the source (Chapter 01 §8.2) |
| `wiret.meta` | opaque | Optional copy of source metadata, never interpreted by the VM |

Unknown custom sections are skipped. The VM uses `wiret.map` for backtraces, breakpoints and the node-trace hook (Chapter 04 §12); a module without it runs identically.

## 11. Extensibility and versioning

* The 4-byte `version` is bumped only for incompatible changes. A VM must reject a module with a higher major version than it implements.
* New instructions are added in **reserved** opcode ranges or as new `0xFB` sub-opcodes; modules that need them declare it with a custom section `wiret.requires` (`vec(string)` of feature names) so older VMs fail with a clear message rather than a verifier error.
* Reserved for v2: `try`/`catch` (structured errors), `i128`/`v128`, tail calls, module-level `memory` for raw byte buffers, 64-bit `rel` branches for gigantic bodies.

## 12. Limits (defaults; VMs may raise them but must enforce *some* bound)

| Item | Limit |
|---|---|
| Types / functions / globals / constants per module | 1,048,576 each |
| Locals per function (params + declared) | 65,535 |
| `max_stack` | 65,535 |
| Fields per record | 65,535 |
| Body size | 16 MiB |
| `br_table` entries | 65,536 |
| String constant length | 16 MiB |
| Call depth | 256 (runtime configurable) |


---

`docs/03-standard-nodes.md`

# Standard nodes

Nodes are identified by *kind* (`Add`), optional *type arguments* (`<i32>`), and pin names. This chapter
lists every intrinsic node, its pins, and the bytecode it lowers to. Nodes marked **[spec only]** are
specified but not yet implemented by the reference compiler.

Legend: **P** = pure (no exec pins, evaluated on demand); **X** = impure (has `in` exec input and a `then`
output unless stated). "→" shows the instruction(s) emitted.

## Entry, exit and flow control

| Kind | Pins | Notes |
| --- | --- | --- |
| `Entry` | exec out `then`; one data output per parameter (`%entry.n`), plus `self` in methods | Exactly one per function. In a macro, exec outputs are the macro's exec inputs. |
| `Return` | exec in `in`; one data input per result | Many allowed. → `RET` |
| `Exit` | macros only: exec inputs named after the macro's exec results | One per macro. |
| `Branch` | in `condition: bool`; exec out `then`, `else` | → `JMPIFNOT c, else`; falls through into `then` |
| `Sequence<N>` | exec out `then_0 … then_{N-1}` | Runs the branches in order (see *Evaluation semantics*). No instruction of its own; the compiler duplicates continuation code per nesting context. |
| `Switch<i32>` | in `value`; `prop cases = [v0, v1, …]`; exec out `case_0 … case_k`, `default` | Dense cases `0..n-1` → `SWITCH`; otherwise a compare-and-branch chain. |
| `Trap` | `prop message = "…"`; terminal | → `TRAP` |

Loops are not special: a cycle in the exec wires *is* a loop. A while loop is a `Branch` whose `then`
path leads back to the node that computes its condition (see `Collatz` below).

## Arithmetic, comparison and logic (P)

| Kind | Type args | Pins | → |
| --- | --- | --- | --- |
| `Add Sub Mul Div Rem Min Max` | `<i32/i64/f32/f64>` | in `a`, `b`; out `result` | `ADD.t` … |
| `Neg Abs` | numeric | in `a`; out `result` | `NEG.t`, `ABS.t` |
| `Sqrt` | `<f32/f64>` | in `a`; out `result` | `SQRT.t` |
| `BitAnd BitOr BitXor Shl Shr` | `<i32/i64>` | in `a`, `b`; out `result` | `AND.t` … (`Shr` is arithmetic; shift counts are masked) |
| `BitNot` | `<i32/i64>` | in `a`; out `result` | `NOT.t` |
| `Eq Ne Lt Le Gt Ge` | numeric, `string`, `bool` (`Eq`/`Ne` only) | in `a`, `b`; out `result: bool` | `EQ.t` …, `STR.EQ` … |
| `And Or Xor Not` | – | in `a`, `b`; out `result: bool` | `AND.bool` … (not short-circuit: both inputs are pure) |
| `Select<T>` | any | in `condition`, `a`, `b`; out `result` | `SELECT` |
| `Convert<A,B>` | see conversion table | in `value`; out `result` | `CVT.A.B` |
| `Const<T>` | any literal type | `prop value = …`; out `value` | `CONST.t` |
| `Concat` | – | in `a`, `b: string`; out `result` | `STR.CONCAT` |
| `StrLen` | – | in `text`; out `length: i32` (UTF-8 bytes) | `STR.LEN` |
| `Reroute<T>` | any | in `value`; out `value` | none (editor knot) |

Semantics worth knowing: integer `Div`/`Rem` truncate toward zero and trap on a zero divisor;
`INT_MIN / -1` wraps to `INT_MIN` and `INT_MIN % -1` is `0`. Float division follows IEEE-754 (no trap).
`Min`/`Max` on floats return NaN if either operand is NaN. Float → integer conversions saturate and map
NaN to 0. String comparison is by UTF-8 bytes.

## Variables (P/X)

| Kind | Pins | → |
| --- | --- | --- |
| `GetLocal<$x>` (P) | out `value` | none (reads the local's register) |
| `SetLocal<$x>` (X) | in `value` | `MOV` |
| `GetVar<@g>` (P) | out `value` | `GLOBAL.get` |
| `SetVar<@g>` (X) | in `value` | `GLOBAL.set` |
| `GetState<$s>` / `SetState<$s>` | macros: persistent per-expansion state | `GLOBAL.get/set` on a hidden global |

## Calls

| Kind | Pins | Notes |
| --- | --- | --- |
| `Call<@f>` | one input per parameter (defaults from the declaration); one output per result | X, or P if `f` is `pure`. Works for functions and `extern` natives. → `CALL` |
| `Call<@Class.method>` **[spec only]** | `target` + parameters | virtual dispatch → `CALLV` |
| `Call<@Interface.method>` **[spec only]** | `target` + parameters | → `CALLI` |
| `CallDelegate<D>` **[spec only]** | `delegate` + parameters | → `CALLD` |

## Arrays

`array<T>` is a mutable reference type. Indices are zero-based; out-of-range access traps.

| Kind (all `<T>`) | Class | Pins |
| --- | --- | --- |
| `ArrayNew` | X | out `array` → `ARR.new` |
| `ArrayLen` | P | in `array`; out `length: i32` |
| `ArrayGet` | P | in `array`, `index`; out `value` (traps if out of range) |
| `ArraySet` | X | in `array`, `index`, `value` |
| `ArrayPush` | X | in `array`, `value` |
| `ArrayPop` | X | in `array`; out `value` (traps if empty) |
| `ArrayInsert` | X | in `array`, `index`, `value` |
| `ArrayRemoveAt` | X | in `array`, `index` |
| `ArrayClear` | X | in `array` |
| `ArrayClone` | X | in `array`; out `clone` (shallow copy) |

## Maps, sets, structs, objects, delegates **[spec only]**

| Kind | Pins and notes |
| --- | --- |
| `MapNew<K,V>` X, `MapLen` P | `map` / `length` |
| `MapGet<K,V>` P | in `map`, `key`; out `value`; traps if missing |
| `MapTryGet<K,V>` P | in `map`, `key`; out `value`, `found: bool` |
| `MapSet<K,V>` X, `MapHas` P, `MapRemove` X (out `removed`) | |
| `MapKeyAt<K,V>`, `MapValueAt<K,V>` P | in `map`, `index`: iterate in **insertion order** |
| `SetNew<T>`, `SetAdd` (out `added`), `SetHas`, `SetRemove`, `SetAt`, `SetLen` | |
| `MakeStruct<S>` P | in one pin per field → out `value` |
| `GetMember<S.f>` P, `SetMember<S.f>` P | `SetMember`: in `struct`, `value`; out `result`: a **new** struct |
| `New<C>` X | out `object` |
| `Self<C>` P | out `value` (the receiver) |
| `GetField<@C.f>` P, `SetField<@C.f>` X | in `target` (+ `value`) |
| `Cast<C>` X | in `object`; exec out `then`, `failed`; out `result: C` → `CAST.try` + branch |
| `IsNull<T>` P | in `value`; out `result` |
| `ToAny<T>` P, `FromAny<T>` X | `FromAny` has exec out `then`, `failed`; out `value` |
| `MakeDelegate<D>` P | `prop function = @f`; in `target` (optional) |
| `Bind<@C.d>`, `Unbind<@C.d>`, `Broadcast<@C.d>`, `ClearBindings<@C.d>` X | in `target`, `delegate` or the delegate's parameters |

`Broadcast` calls every bound handler in binding order. Handlers that are `latent` are started on their
own fibers; the broadcast does not wait.

## std.flow (written in Wiret)

`use "std.flow" as flow`. These are ordinary macros; they are the best worked examples of the macro
rules. `While` is deliberately absent: it is a `Branch` with a back wire, because a loop condition must be
re-evaluated every iteration and macro inputs are snapshots.

| Macro | Signature | Behaviour |
| --- | --- | --- |
| `ForLoop` | `(exec in, first: i32 = 0, last: i32 = 0) -> (exec body, index: i32, exec completed)` | runs `body` for `first..=last` |
| `ForEach<T>` | `(exec in, items: array<T>) -> (exec body, element: T, index: i32, exec completed)` | runs `body` per element; the array is snapshotted by reference, so appending inside the body extends the loop |
| `DoOnce` | `(exec in, exec reset) -> (exec completed)` | passes only the first execution until `reset` fires |
| `DoN` | `(exec in, exec reset, n: i32 = 1) -> (exec completed)` | passes at most `n` executions until `reset` |

Source of `ForLoop` and `DoOnce` exactly as shipped:

```wiret
{{STDFLOW_FORLOOP}}
```

```wiret
{{STDFLOW_DOONCE}}
```

## Worked examples

All of these compile, verify and run on the reference implementation (`examples/flow.wiret`).

**`SumTo(n)`** uses `ForLoop` with a local accumulator. `SumTo(100)` returns 5050.

{{SVG:sumto}}

Its disassembly shows the macro expanded inline: the back edge is the final `JMP @0018`, and the
entry stub `%loop!in` is where the macro's inputs are snapshotted.

```
{{SUMTO_DIS}}
```

**`FizzBuzz(limit)`** prints through a native: `extern function print = "std.print"(text: string)`.
Calling `FizzBuzz(15)` prints `1 2 Fizz 4 Buzz Fizz 7 8 Fizz Buzz 11 Fizz 13 14 FizzBuzz`.

**`Collatz(start)`** is a while loop made of a `Branch` and a back wire, with `Select` choosing the next
value: `Collatz(27)` returns 111.

**`Ordering()`** has `Sequence<3>` whose first branch is two calls long: it prints `A A2 B C`.

**`Divide(1, 0)`** traps, and the VM reports the graph node, not a program counter:

```
trap: integer divide by zero
    at Divide (node %div)
```


---

`docs/04-bytecode.md`

# Bytecode specification

Wiret bytecode (`.wirb`) is a **typed register machine** with a binary module format modelled on
WebAssembly (sections, LEB128, validation before execution) and a type system in the spirit of the JVM
(statically typed, verified, garbage-collected references). This chapter is normative.

## Why a typed register machine

| Decision | Reason |
| --- | --- |
| Registers, not an operand stack | Every data pin of an impure node is a variable that other nodes read *later*. A stack machine would need `dup`/`swap` shuffling to express that; registers map pins directly, and debuggers can show a pin's value (`wiret.pins`). |
| Every register has one static type | Verification is a single linear pass: no dataflow fix-point as in the classic JVM verifier. The GC knows which registers hold references without per-instruction stack maps. |
| Typed opcodes (`ADD.i32`) | No runtime type dispatch; the verifier checks operand types by opcode alone. |
| Explicit operand lists for calls | Calls copy arguments and results between register windows, so register types never change across a call. |
| Structured by sections, with custom sections | A runtime can skip debug info it does not want; new data can be added without a format break. |

## Module binary format

```
module  = magic version section*
magic   = 0x00 0x57 0x52 0x54            ; "\0WRT"
version = u32 little-endian              ; 1
section = id:u8  size:uleb128  payload
```

Integers are **LEB128** (`uleb128` unsigned, `sleb128` signed) unless stated. Floats are little-endian
IEEE-754. A *name* is `uleb128 length` + UTF-8 bytes. Non-custom sections appear **at most once, in
increasing id order**; custom sections (id 0) may appear anywhere.

| Id | Section | Contents |
| --- | --- | --- |
| 0 | Custom | `name`, then section-specific payload |
| 1 | Type | `count`, then type entries |
| 2 | Import | `count`, then `module:name field:name kind:u8 sigtype:uleb flags:u8` (kind 0 = function) |
| 3 | Function | `count`, then `sigtype:uleb flags:u8` per defined function |
| 4 | Global | `count`, then `valtype mutable:u8 init` (init = a constant encoded by type) |
| 5 | Export | `count`, then `name kind:u8 index:uleb` (kind 0 = function) |
| 6 | Start | `uleb`: 0 = none, otherwise function index + 1 |
| 7 | String | `count`, then names: the constant pool |
| 8 | Code | `count`, then function bodies, in Function-section order |

**Function index space**: imports first (in Import order), then defined functions. `CALL` uses this
index. **Function flags**: bit 0 `pure`, bit 1 `latent`, bit 2 `event`.

### Value types

```
valtype = 0x7F i32 | 0x7E i64 | 0x7D f32 | 0x7C f64 | 0x7B bool | 0x70 string | 0x6F any
        | 0x6E typeidx:uleb                ; a reference to a composite type-section entry
```

### Type section entries

| Byte | Entry | Payload |
| --- | --- | --- |
| `0x60` | func | `nparams valtype* nresults valtype*` |
| `0x5D` | array | `elem:valtype` |
| `0x5C` | map | `key:valtype value:valtype` |
| `0x5B` | set | `elem:valtype` |
| `0x56` | host | `name` (an opaque host type, resolved at link time) |
| `0x5F` | struct **[spec only]** | `nfields valtype*` (immutable value type) |
| `0x5E` | class **[spec only]** | `super:uleb(0=none, else idx+1) niface iface-typeidx* nfields valtype* nslots funcidx* imap` — `funcidx*` is the complete virtual table (inherited slots included); `imap` lists, per interface, the function implementing each method |
| `0x5A` | interface **[spec only]** | `nmethods sigtype*` |
| `0x58` | delegate **[spec only]** | `sigtype` (single-cast function reference with optional bound target) |
| `0x57` | dispatcher **[spec only]** | `sigtype` (multicast list of delegates) |

Enums are `i32` at the bytecode level; their names live in a custom section. Identical entries are
shared (the type section is a set).

### Code section: function body

```
body    = size:uleb  nregs:uleb  ngroups:uleb  (count:uleb valtype)*  instruction*
```

The register groups run-length-encode the register types. **Registers `r0 … r(p-1)` are the
parameters** and must match the signature. All other registers are locals and temporaries. Every
register is zero-initialised when the frame is created: numbers `0`, `bool` false, `string` `""`,
references `null`, struct registers hold their default value.

### Custom sections

| Name | Payload | Purpose |
| --- | --- | --- |
| `wiret.names` | module name; `(kind:u8 index name)*` (kind 0 function, 1 global) | symbol names for traces, reflection and export tools |
| `wiret.nodemap` | local string table; per function: `funcindex nentries (pc-delta:uleb node-string)*` | maps each byte offset to the graph node that produced it (`loop/check`, `loop!body`). A pc belongs to the nearest preceding entry. |
| `wiret.pins` | local string table; per function: `funcindex n (register node pin)*` | which register holds which output pin, for value probes |

Runtimes may ignore any custom section (`WIRET_CFG_NO_DEBUG_INFO`). Unknown custom sections must be skipped.

### Annotated example: `Fib`

```
00 57 52 54 01 00 00 00           magic, version 1
01 06  01 60 01 7f 01 7f          Type: 1 entry: func (i32) -> (i32)
02 01 00                          Import: none
03 03  01 00 01                   Function: 1 function, signature 0, flags = pure
04 01 00                          Global: none
05 07  01 03 46 69 62 00 00       Export: "Fib", function, index 0
06 01 00                          Start: none
07 01 00                          String pool: empty
08 38  01 36                      Code: 1 body, 0x36 bytes
   09  03 02 7f 01 7b 06 7f       9 registers: 2×i32, 1×bool, 6×i32
   11 01 02                       CONST.i32  r1, 2
   28 02 00 01                    LT.i32     r2, r0, r1
   04 02 03                       JMPIFNOT   r2, +3
   06 01 00                       RET        (r0)
   11 01 01 …                     CONST.i32  r1, 1     ; @000d – the else path
   …
00 26  0b "wiret.names" …         custom sections: names, nodemap, pins
```

`JMPIFNOT r2, +3` skips the 3-byte `RET (r0)`: offsets are relative to the first byte *after* the
branch instruction.

## Execution model

* **Frames.** Calling a function creates a frame of `nregs` registers. `CALL f, (args…), (results…)`
  copies the argument registers into the callee's `r0…`, runs it, and copies the registers named in the
  callee's `RET` into the result registers. Types must match exactly.
* **Values.** `i32`/`i64`: two's complement, arithmetic wraps. `f32`/`f64`: IEEE-754 binary32/64, round
  to nearest even, no traps; NaN payloads are unspecified. `bool`: 0/1. `string`: immutable UTF-8 reference.
  Aggregates and objects are references managed by the GC.
* **Traps** abort the current fiber with a status and a message; there is no catching inside bytecode.
  The host observes the trap from `wiret_pcall`/`wiret_resume`, with a traceback of
  (function, node id) pairs from the node map. Traps: integer divide/remainder by zero, array/map/set
  index or key errors, null dereference, failed `CAST`, `ANY.unbox` mismatch, `TRAP`, call-stack
  overflow, budget exhaustion, memory limit.
* **Budget.** The VM counts instructions. When the host-set budget is exhausted it traps with
  `WIRET_ERR_BUDGET` at the next instruction boundary. Hosts use this to run untrusted graphs.
* **GC safepoints.** Allocation, `CALL`, and backward branches. References are found through the
  per-function register type table, so no stack maps are needed.
* **Determinism.** The only unspecified results are NaN payloads. Maps and sets iterate in insertion order, `STR.LT` is bytewise,
  float-to-string uses the shortest representation that round-trips. With a deterministic native set
  (`WIRET_CFG_DETERMINISTIC`) a program's behaviour is reproducible across platforms.
* **Latent calls and fibers.** A `CALL` to a function flagged `latent` may suspend the fiber (a
  latent native returns `WIRET_YIELD`). Suspension is only possible inside latent functions; the verifier
  enforces this, so non-latent code never observes a suspension. `YIELD` ends the current time slice
  voluntarily. `SPAWN f, (args…)` starts a new fiber that runs `f` to completion independently.

## Validation

A module must be validated before execution. Validation is linear and stateless per instruction:

1. Header, version, section order and sizes are well-formed; all indices (types, functions, globals,
   strings, registers) are in range; the function and code counts agree.
2. Parameter registers have the types of the signature; every register type is a valid valtype.
3. Each instruction's operand registers have exactly the types required by its opcode (the
   mnemonic's `.type` suffix; `MOV`, `SELECT` and `GLOBAL.*` require equal types; array operations
   require `array<T>` with matching element types).
4. `CALL`/`SPAWN` argument types equal the callee's parameter types; `CALL` result registers equal its
   result types; `RET` registers equal the function's result types.
5. A `CALL` to a `latent` callee appears only in a `latent` function.
6. Every branch target is the first byte of an instruction **in the same function**.
7. The last instruction of a body is `RET`, `JMP`, `TRAP` or `SWITCH` (control cannot fall off the end).
8. Imports resolve at instantiation (`WIRET_ERR_LINK`), with exactly matching signatures and flags.

The reference verifier implements 1–7 for the instruction subset the reference VM executes and checks
indices for all others; the typing rules for composite opcodes follow the same pattern and are listed in
the opcode tables.

## Instruction encoding

An instruction is a one-byte opcode followed by operands encoded as the opcode table prescribes.

| Operand | Encoding |
| --- | --- |
| `r` register | `uleb128` index |
| `s` signed immediate | `sleb128` |
| `u` unsigned immediate / index | `uleb128` |
| `L` branch offset | `sleb128`, relative to the first byte after the instruction |
| `rl` register list | `uleb128 count`, then that many registers |
| `sw` switch table | `uleb128 n`, then `n` offsets, then the default offset |
| `f32`, `f64` | 4 / 8 raw bytes |
| `vt` | a valtype |

Opcodes `0xF0`–`0xFF` are reserved for extension prefixes; `0xFF` is permanently invalid. Unassigned
opcodes are validation errors, so new instructions require a bytecode version bump or a declared feature.

## Instruction reference

Operand names: `d` destination register, `a b c` source registers. **Ref** = executed by the
reference VM (the rest are verified structurally and specified here).

### Control, constants and variables

{{OPS_CONTROL}}

### Numeric instructions

Each family exists for the four numeric types. The opcode is the family base plus the listed offset.
`d`, `a`, `b` all have the type in the suffix, except comparisons, whose `d` is `bool`.

{{OPS_NUMERIC}}

Semantics: `ADD SUB MUL NEG` wrap for integers. `DIV`/`REM` are signed, truncating, trap on a zero
divisor, and wrap `INT_MIN / -1`. `SHL`/`SHR` mask the count by `bits-1`; `SHR` is arithmetic.
`MIN`/`MAX`/`ABS` on integers are ordinary; on floats NaN propagates. `SQRT` of a negative is NaN.

### Booleans, conversions, strings

{{OPS_MISC}}

Conversion rules: `i64→i32` keeps the low 32 bits; float→int saturates and maps NaN to 0; `i32→bool` is
`≠ 0`. To-string conversions are decimal; floats use the shortest digits that round-trip (with a
`.0` if integral); `bool` is `true`/`false`.

### Aggregates, objects, containers, boxing, delegates **[spec only]**

{{OPS_COMPOSITE}}

Notes. `STRUCT.*` operate on immutable values; `STRUCT.with` allocates a new value. `CAST` traps when the
object is not an instance of the target type; `CAST.try` yields `null`. `ARR.get`/`set`/`remove`/`insert` trap
on a bad index; `ARR.pop` traps when empty. `MAP.get` traps on a missing key, `MAP.tryget` does not.
`MAP.keyat`/`valat` and `SET.at` index in insertion order. `ANY.box` records the static type of its source;
`ANY.unbox` traps on mismatch. `DISP.broadcast` calls handlers in binding order and starts latent
handlers as new fibers.

## How graphs lower to bytecode

The compiler (reference: `wiret_ref/compiler.py`) follows these rules, which are part of the
specification because they define observable behaviour (evaluation order, node maps):

1. **Expand macros.** Each macro node is replaced by a clone of its graph with ids prefixed by
   the node id (`loop/`), type parameters substituted, and two kinds of *binding stubs*: entry stubs
   `loop!in` copy the macro's data inputs into registers; exit stubs `loop!body` compute that exit's data
   results and then continue to whatever the macro's exec output is wired to.
2. **Allocate registers.** Parameters take `r0…`. Locals follow, initialised at function entry. The output
   pins of every impure node get a dedicated register that lives for the whole function. Pure results
   are temporaries released after their consumer.
3. **Emit impure nodes as code blocks, in execution order.** For each impure node: emit its *pure
   cone* (the pure nodes feeding its inputs, dependencies first, each once), then the node itself.
   Follow the primary exec wire (`then`, or `Branch`'s `then`) as a fall-through; other targets become
   labels. A node reached again emits a `JMP` to its existing label.
4. **Sequence contexts.** The compiler tracks a stack of pending `Sequence` continuations while walking
   the exec graph. When a path ends it resumes the next branch of the innermost sequence. A node
   reachable under two different stacks is emitted twice; the last branch of a sequence pops its entry,
   so loop bodies do not grow the stack. Nesting deeper than 12 is `E0305`.
5. **Switch.** Dense `0..n-1` cases become `SWITCH`; others compare in sequence.
6. **Record the node map.** Every instruction is tagged with the node that emitted it.
7. **Assemble.** Branch offsets are resolved by iterating instruction sizes to a fixed point (LEB128
   offsets change size).

Equivalent text-to-bytecode behaviour is therefore: *same semantic graph ⇒ same bytecode*. Layout, metadata,
node order and node ids do not influence the instruction stream (ids only appear in custom sections).

## Versioning and extension

* The version word changes only for incompatible changes. Additive changes use new opcodes in the
  reserved prefix space, announced by a custom section `wiret.features` (list of feature names); a runtime
  must refuse a module requiring an unknown feature.
* Planned: `i8/i16/u8` types, `v128` vectors, tail calls, an exception-handling proposal for `try`-like nodes,
  and a `wiret.debug` section with source graph hashes.


---

`docs/05-runtime-api.md`

# Runtime API

`libwiret` is the embeddable runtime: a verifier, interpreter, garbage collector, fiber scheduler and a
C API (`wiret.h`). Its shape follows the Lua C API: a small set of functions, a *typed value stack* for
exchanging values with scripts, protected calls, registry references, and natives written as C
functions. The header ships with this specification and compiles cleanly as C99 and C++17.

The compiler is a separate library (`libwiretc`, see Tooling): a game or app that only loads
precompiled `.wirb` files links `libwiret` alone.

## Concepts

| Object | Role | Lua analogue |
| --- | --- | --- |
| `wiret_VM` | The heap, the module registry, registered natives, GC state, limits. Single-threaded. | the global state |
| `wiret_Module` | A loaded, verified, immutable image; after `instantiate` it also owns globals. | a loaded chunk + its upvalues |
| `wiret_Fiber` | One thread of execution (call stack) plus the host *value stack*. `wiret_main(vm)` is the always-present main fiber. | `lua_State` / coroutine |
| `wiret_Sched` | Optional scheduler that resumes fibers each tick and implements `std.delay`. | – |

**Typed values.** Unlike Lua, every value on the stack has a static Wiret type (`wiret_type`,
`wiret_typename`). A call is checked against the function's signature, so passing a string where an `i32`
is expected fails with `WIRET_ERR_TYPE` before any script code runs.

**Stack indices.** `1` is the first slot of the current frame, `-1` the top. Natives see their arguments in
`1..n`. Pointers returned by `wiret_tolstring`/`wiret_pushstring` stay valid while the value is on the
stack (or otherwise reachable) and are never invalidated by a GC.

**Errors.** Functions returning `wiret_Status` report failure by value. Functions that *raise*
(`wiret_error`, `wiret_check*`, `wiret_call`) unwind to the innermost `wiret_pcall` /`wiret_resume`,
implemented with `setjmp/longjmp` in C builds and with exceptions when `WIRET_USE_EXCEPTIONS` is
defined. Natives written in C++ must not let their own exceptions cross the boundary.

## Quick start

```c
#include "wiret.h"

static int host_log(wiret_Fiber *F, void *ud) {
  size_t n; const char *s = wiret_checklstring(F, 1, &n);   /* arg 1, must be a string */
  printf("%s%.*s\n", (const char *)ud, (int)n, s);
  return 0;                                                  /* number of results pushed */
}

int main(void) {
  wiret_VM *vm = wiret_vm_new(NULL);                         /* defaults */
  wiret_Fiber *F = wiret_main(vm);
  wiret_register(vm, "std.print", "(string)->()", host_log, "[wiret] ", 0);

  wiret_Module *m; wiret_Diag diag;
  if (wiret_module_load(vm, image, size, "flow", 0, &m, &diag) != WIRET_OK ||
      wiret_module_instantiate(F, m, &diag) != WIRET_OK) {
    fprintf(stderr, "%s (in %s at %s)\n", diag.message, diag.function, diag.node);
    return 1;
  }

  wiret_getexport(F, m, "SumTo");          /* push the function            */
  wiret_pushi32(F, 100);                   /* push the argument            */
  if (wiret_pcall(F, 1, 1) == WIRET_OK)    /* 1 argument, 1 result         */
    printf("%d\n", wiret_checki32(F, -1)); /* 5050                         */
  wiret_pop(F, 1);

  wiret_vm_free(vm);
}
```

The complete program is `examples/host_example.c`.

## Lifecycle: load, link, run

1. **`wiret_module_load`** decodes and *validates* the image (see Bytecode → Validation). Nothing runs.
   Failure returns `WIRET_ERR_LOAD` or `WIRET_ERR_VERIFY` and fills `wiret_Diag` (message, function, node id,
   pc). Load is safe on hostile input.
2. **Register natives** (`wiret_register`, `wiret_register_lib`, `wiret_open_std`) before instantiation.
   Imports are resolved by name **and signature**; there is no ambient authority. A module can only call what
   the host registered.
3. **`wiret_module_instantiate`** resolves imports (other loaded modules by name, then natives), allocates
   globals with their initial values, and runs the start function. It needs a fiber because the start
   function may call natives.
4. **Call** exports with `wiret_getexport` + `wiret_pcall` (or run them on a fiber).
5. **`wiret_module_release`** drops the host's reference; the VM frees modules at `wiret_vm_free`.

## Natives

A native is `int fn(wiret_Fiber *F, void *ud)`. The VM has already checked the arguments against the declared
signature; the native pushes exactly the declared number of results and returns that count.

```c
static int host_clamp(wiret_Fiber *F, void *ud) {
  wiret_F32 x = wiret_checkf32(F, 1), lo = wiret_checkf32(F, 2), hi = wiret_checkf32(F, 3);
  wiret_pushf32(F, x < lo ? lo : x > hi ? hi : x);
  return 1;
}
...
wiret_register(vm, "game.clamp", "(f32,f32,f32)->(f32)", host_clamp, NULL,
               WIRET_NATIVE_PURE | WIRET_NATIVE_DETERMINISTIC);
```

* **Signature strings** use the type syntax of `.wiret` files: `"(string,array<i32>)->(bool,i32)"`.
* **Flags.** `PURE` lets the compiler and graph editor draw the native as a pure node; `LATENT` allows
  `wiret_yield`; `DETERMINISTIC` is required when the VM is configured with `WIRET_CFG_DETERMINISTIC`.
* A native declared in a `.wiret` file as `extern function` must match the registered signature and
  flags exactly, or linking fails with `WIRET_ERR_LINK`.
* **Errors from natives**: `return wiret_error(F, "texture %s not found", name);` raises a trap that
  carries the script's node id in its traceback.
* `wiret_register_lib` registers an array of `wiret_NativeReg` at once (like `luaL_Reg`).
  `wiret_open_std` registers the standard library: `std.print`, `std.math.*`, `std.string.*`, `std.time.now`,
  `std.delay`, `std.wait_frames`, `std.yield`.

### Host handles

Host objects (a texture, an entity) appear in scripts as values of an `extern type`. The host registers the
type once and creates handles:

```c
typedef struct { int id; } Texture;
static void tex_free(void *p) { release_texture(((Texture *)p)->id); }

wiret_HostType tt = { "host.Texture", sizeof(Texture), tex_free, NULL };
wiret_register_hosttype(vm, &tt);

Texture *t = wiret_pushhost(F, "host.Texture");     /* allocates, pushes, returns payload */
t->id = load_texture(path);
```

`wiret_checkhost(F, idx, "host.Texture")` retrieves the payload in a native, raising a type error for any
other value. The GC calls `finalize` once when the handle becomes unreachable. If a payload holds
references to script values, supply `trace` and call `wiret_mark` on each.

## Passing values

| Direction | Functions |
| --- | --- |
| host → script | `wiret_pushbool/i32/i64/f32/f64/string/lstring/fstring/null`, `wiret_pushany` |
| script → host (non-raising) | `wiret_tobool/toi32/…/tolstring(F, idx, &ok)`, `wiret_type`, `wiret_isnull` |
| script → host (raising) | `wiret_checki32 …` for natives |
| structs, objects | `wiret_pushstruct`, `wiret_newobject`, `wiret_getfield`, `wiret_setfield`, `wiret_getmethod` |
| arrays | `wiret_newarray("i32")`, `wiret_arraylen/get/set/push` |
| maps | `wiret_newmap("string","i32")`, `wiret_mapget/set/at/len` |

**Value vs. reference semantics.** Structs are values: `wiret_setfield` on a struct replaces the stack
slot with a modified copy. Objects, arrays, maps, sets and host handles are references: changes are
visible to every holder. Strings are immutable.

```c
wiret_newarray(F, "i32");                       /* [.. arr]               */
for (int i = 0; i < 4; i++) { wiret_pushi32(F, i * 10); wiret_arraypush(F, -2); }
wiret_getexport(F, m, "SumArray");              /* [.. arr fn]            */
wiret_insert(F, -2);                            /* [.. fn arr]            */
wiret_pcall(F, 1, 2);                           /* [.. sum count]         */
```

## Calling into Wiret

`wiret_pcall(F, nargs, nresults)` expects `[… fn arg1 … argN]`, checks the arguments against the
signature, runs to completion and leaves `nresults` values (which must equal the function's declared result
count). On failure the stack top holds an error string; `wiret_traceback` renders it with
function and **graph node ids**:

```
trap: integer divide by zero
    at Divide (node %div)
    at Main (node %call_divide)
```

`wiret_call` is the unprotected variant for use inside natives (errors propagate to the outer
`pcall`). Re-entrancy is allowed: a native may call back into Wiret on the same fiber, to a depth bounded by
`max_call_depth`.

Events are exported functions, so the host raises them the same way:
`wiret_getexport(F, m, "OnHit"); wiret_pushi32(F, 5); wiret_pcall(F, 1, 0);`. For events on a class instance,
`wiret_getmethod(F, obj_idx, "Interact")` pushes a delegate already bound to the object. **[spec only]**

## Fibers and latent calls

A **latent** function (one that calls a latent native such as `std.delay`) can suspend. Run those on their
own fiber; the fiber keeps its call stack while suspended:

```c
wiret_Fiber *co = wiret_fiber_new(vm);
wiret_getexport(co, m, "OpenTemporarily");  wiret_pushf32(co, 2.5f);
int nres; wiret_Status st = wiret_resume(co, 1, &nres);   /* first resume starts the call */
while (st == WIRET_YIELD) {
  /* ... do other work; later: */
  st = wiret_resume(co, 0, &nres);
}
```

* A latent native suspends with `return wiret_yield(F, nresults);`. It can record *why* with
  `wiret_setwait(F, tag, data)`, which the host reads with `wiret_getwait` to decide when to resume
  (a timer, a network reply, a gameplay event).
* **Built-in scheduler.** `wiret_sched_new`, `wiret_sched_start(s, fiber, nargs)` and
  `wiret_sched_tick(s, dt)` implement `std.delay(seconds)`, `std.wait_frames(n)` and `std.yield()` so a game only
  has to call `tick` once per frame.
* `wiret_cancel(F)` unwinds a suspended fiber at its next resume (finalizers still run).
* Latent functions can only be called from latent functions, so a *non-latent* call never suspends and the
  host can rely on `wiret_pcall` returning `WIRET_OK` or an error, never `WIRET_YIELD`. Calling a latent
  export through `wiret_pcall` returns `WIRET_ERR_TYPE`.

## Memory and the garbage collector

Heap values (strings, structs, objects, arrays, maps, sets, delegates, host handles) are managed by an
incremental, precise, non-moving mark-and-sweep collector. Roots are fiber stacks, module globals and
registry references.

* **Keeping values alive from C.** `wiret_ref(F)` pops the top value and returns an integer handle; `wiret_getref`
  pushes it again; `wiret_unref` releases it. Anything not referenced from the stack, globals or a ref may be collected.
* `wiret_gc(vm, op, arg)`: `COLLECT` (full), `STOP`/`RESTART`, `STEP`, `BYTES` (current heap size),
  `SETPAUSE`, `SETSTEPMUL`. Games typically `STEP` a little every frame.
* `wiret_Config.alloc` supplies your allocator (arenas, tracking); `memory_limit` makes allocation fail
  with `WIRET_ERR_MEMORY` instead of growing without bound.

## Sandboxing and limits

| Limit | Setting | On breach |
| --- | --- | --- |
| Instructions per resume | `wiret_Config.default_budget`, `wiret_setbudget` | `WIRET_ERR_BUDGET` |
| Memory | `memory_limit`, `wiret_setmemlimit` | `WIRET_ERR_MEMORY` |
| Call depth | `max_call_depth` | `WIRET_ERR_STACK` |
| Host stack size | `max_stack_slots` | `WIRET_ERR_STACK` |
| Capabilities | only registered natives resolve | `WIRET_ERR_LINK` |
| Nondeterminism | `WIRET_CFG_DETERMINISTIC` | natives without the flag refuse to link |

A script cannot allocate unbounded memory, loop forever, or reach the filesystem or network unless the
host hands it a native that can.

## Debugging and visual tooling

Every frame knows its **graph node**. Editors build their debugger on these calls:

* `wiret_sethook(F, fn, mask, ud)` with `WIRET_HOOK_NODE` fires each time execution enters a new node
  (macro-internal nodes included, e.g. `loop/check`), `CALL`/`RETURN` on function boundaries and `TRAP` on errors.
* `wiret_getstack(F, level, &info)` returns module, function, node id and pc for any frame.
* `wiret_getpin(F, level, "add_1", "result")` pushes the current value of an output pin so the editor can show
  values on wires (the "data probe" of Blueprint debugging).
* `wiret_setbreak(module, "Fib", "is_base", 1)` plants a breakpoint on a node (it patches the first instruction
  to `BREAK`; the hook receives `WIRET_HOOK_NODE`).
* Without debug info (`WIRET_CFG_NO_DEBUG_INFO`) the node fields are `NULL`.

## Threads and ABI

* A VM and everything reachable from it must be used from one thread at a time. Use one VM per thread;
  `wiret_Module` images may be loaded into several VMs from the same bytes (`WIRET_LOAD_BORROW`).
* No function is async-signal-safe. Do not call the API from a finalizer except `wiret_unref`.
* The C ABI is stable within a major version: structs with a `struct_size` field (`wiret_Config`) can grow;
  enums only gain values at the end. `WIRET_BYTECODE_VERSION` in the header must equal the version the
  module was compiled for.

## Differences from the Lua C API

| Lua | Wiret |
| --- | --- |
| Dynamically typed stack | Statically typed values; calls are checked against signatures |
| `lua_getglobal` / tables | Exports and fields by name; arrays/maps are typed containers |
| `lua_pushcclosure` upvalues | one `void *ud` per native; host handles for state |
| `lua_pcall` with message handler | `wiret_pcall` + `wiret_traceback` (node ids) |
| Coroutines created by script | Fibers created by the host; script code only suspends in `latent` calls |
| `lua_sethook` per line | `wiret_sethook` per **node** |
| `luaL_Reg` | `wiret_NativeReg` with signature strings |
| `lua_gc` | `wiret_gc` |
| Userdata with metatables | `wiret_HostType` with finalizer and trace |


---

`docs/06-tooling.md`

# Tooling and workflow

## The toolchain

| Tool | Purpose | Reference implementation |
| --- | --- | --- |
| `wiret fmt` | Canonical formatting (idempotent) | `python3 -m wiret_ref fmt FILE` |
| `wiret check` | Parse, resolve, type-check, lower, verify; prints diagnostics | `… check FILE` |
| `wiret build` | `.wiret` → `.wirb` | `… build FILE [OUT]` |
| `wiret dis` | Disassemble a `.wirb` (or build+disassemble a `.wiret`) with node markers | `… dis FILE` |
| `wiret run` | Compile and run an export with the standard natives | `… run FILE Export args…` |
| `wiret svg` | Draw a function from its layout block | `… svg FILE Function > graph.svg` |
| `wiret hash` | Semantic hash (see below) **[spec only]** | – |
| `wiret diff` / `merge` | Node-level diff and Git merge driver **[spec only]** | – |
| `wiret fmt --reading-order` | Reorder nodes into depth-first execution order **[spec only]** | – |

Run the reference tools from `reference/`:

```
python3 -m wiret_ref check ../examples/flow.wiret
python3 -m wiret_ref run   ../examples/flow.wiret SumTo 100        # 5050
python3 -m wiret_ref run   ../examples/flow.wiret FizzBuzz 15
python3 -m wiret_ref svg   ../examples/fibonacci.wiret Fib > fib.svg
python3 tests.py                                                    # conformance suite
```

## Compiler API (`libwiretc`) **[spec only]**

The compiler is a library so that editors, build systems and servers can call it in-process.

```c
typedef struct wiretc_Diagnostic {
  const char *code;        /* "E0102" */
  int         severity;    /* 0 error, 1 warning, 2 note */
  const char *message;
  const char *module, *function, *node, *pin;   /* any may be NULL; ids use macro paths: "loop/check" */
  int         line, column;                      /* position in the .wiret text, 1-based */
} wiretc_Diagnostic;

typedef struct wiretc_Result {
  void *image; size_t image_size;                /* the .wirb, NULL on error */
  wiretc_Diagnostic *diags; size_t ndiags;
  uint8_t semantic_hash[32];
} wiretc_Result;

wiretc_Status wiretc_compile(const char *text, size_t len, const wiretc_Options *opts, wiretc_Result *out);
wiretc_Status wiretc_format(const char *text, size_t len, char **out, size_t *out_len);
void          wiretc_result_free(wiretc_Result *r);
```

Options include module search paths (for `use`), a debug-info level (`none`, `nodes`, `nodes+pins`), and an
optimisation level. Diagnostics are the table in [Text format](02-text-format.md#diagnostics). All
diagnostics are *recoverable*: the compiler continues after an error where it can, so an editor can show every
problem at once.

### Optimisations

Optimisations must preserve the observable behaviour and the node map's meaning (every instruction still
maps to *a* node). Specified passes: constant folding of pure nodes with literal inputs, common
sub-expression elimination **within one cone only** (pure nodes are re-evaluated per consumer by definition, so
cross-consumer CSE must prove no state is written between), dead pure-node elimination (a pure node no one
reads is never emitted: the reference compiler already does this implicitly), jump threading, and
register coalescing. A `-O0` build emits exactly what the lowering rules in *Bytecode* describe.

## Semantic hash

`semantic_hash` is SHA-256 over a canonical serialization of the program that **excludes** layout blocks,
`meta` lines, attribute lists, comments and declaration order, and **sorts** declarations by name and
nodes by id. Two files with the same semantic hash compile to the same instruction stream. Uses:

* CI can skip rebuilds and skip re-running tests when a commit only moved nodes or edited documentation.
* Caches (hot reload, asset pipelines) key on it.
* Review tools can label a diff "layout only" or "metadata only".

The reference test-suite checks the underlying property: removing the layout and metadata, or reversing the
node order, does not change a single instruction.

## Working with Git

Recommended `.gitattributes`:

```
*.wiret text eol=lf diff=wiret merge=wiret
*.wirb  binary
```

Why the format merges well:

1. **One owner per wire.** A data wire is a line in its consumer; an exec wire is a line in its producer.
   Two people rewiring different pins never touch the same line.
2. **Stable ids with random suffixes.** Ids are never renumbered, and a new node's id is unlikely to collide
   with a teammate's new node.
3. **Layout is separate.** Dragging nodes edits the `layout` block only; logic edits never touch it.
   Layout lines are one-per-node, so two people moving different nodes do not conflict.
4. **Canonical text.** Formatting differences cannot appear.

### Node-level merge (specified behaviour of `wiret merge`)

A three-way merge on the parse tree, keyed rather than line-based:

| Unit | Key |
| --- | --- |
| declaration | kind + name |
| node | function + `%id` |
| node item | node + (`in`/`exec`/`prop`/`meta`) + pin or key |
| layout entry | function + `%id` (or box title) |

* Changes to different keys merge automatically; added nodes in both branches are kept.
* **Conflicts**: the same item changed to different values; a node deleted on one side and modified on the
  other; the same exec output connected to two targets after merge (an *invariant* conflict: a merged
  result that is not a valid graph is reported even though no line collided).
* Layout conflicts resolve to "theirs for the node's position, then the editor's auto-layout nudge for overlaps"
  and are never blocking.
* Unresolvable conflicts are written as ordinary text conflict markers around the offending node block, so
  any text merge tool can finish the job.

## Working with language models

The format was shaped for reading and writing by models:

* **Everything is named and typed.** No positional pins, no implicit wildcard resolution, no coordinates needed
  to understand logic (a model may omit the `layout` block; editors auto-layout and fill it in).
* **Local edits.** Adding a node is: one node block + one changed line in its neighbour. Models can emit unified
  diffs against the file safely.
* **Closed-loop correctness.** The compiler's diagnostics (`E0102` + function + node + pin) are
  machine-readable and designed to be pasted back to the model verbatim; the reference test-suite covers a
  representative error for each class. Suggested loop: *generate → `wiret check` → feed diagnostics back → repeat*.
* **Explanation.** `wiret dis` output with `; --- %node` markers lets a model (or a person) relate behaviour to nodes.
* A compact prompt contract: *"Return a complete `.wiret` file or a unified diff. Use only node kinds listed in
  Standard nodes. Give every node a unique `%slug_xxxx` id. Do not renumber ids. Bind every required input.
  Connect every non-terminal exec output or leave it deliberately unconnected."*

## Contract for graph editors

An editor is conformant if it:

1. Parses any valid file and writes back a file whose **semantic hash is unchanged** unless the user changed logic.
2. Preserves node and item order, unknown `meta` keys, and unknown layout attributes.
3. Writes canonical text (or calls `wiretc_format`).
4. Writes integer layout coordinates and **keeps personal view state out of the file**.
5. Never reuses a deleted node's id within the same file's history window (use random suffixes).
6. Surfaces compiler diagnostics on the named node/pin, including macro paths (`loop/check` highlights the
   macro node `loop` and, if expanded in the view, the inner node).
7. Shows wildcard/generic nodes with their resolved type arguments and writes them explicitly.

## Reference implementation

`reference/wiret_ref` is a ~2,500-line Python implementation used to validate this specification:

| Module | Spec chapter | Contents |
| --- | --- | --- |
| `syntax.py` | Text format | lexer, parser (the full grammar), canonical formatter |
| `compiler.py` | Standard nodes, Bytecode | macro expansion, validation, lowering, assembly |
| `stdlib.py` | Standard nodes | `std.flow` written in Wiret |
| `ops.py` | Bytecode | the opcode table that generates the reference tables in this document |
| `binary.py` | Bytecode | encoder, decoder, verifier, disassembler |
| `vm.py` | Bytecode, Runtime API | interpreter, traps with node ids, budget, node hook |
| `render.py` | Text format | draws a function from its `layout` block |
| `tests.py` | all | conformance tests |

What it covers: the whole text grammar (declarations of structs, enums, classes, interfaces, delegates are
parsed and formatted), functions, events, macros with generics and state, all arithmetic/logic/string/array
nodes, calls and natives, `Sequence`/`Branch`/`Switch`, the binary format with all sections, validation, and
execution of 138 of the 181 defined opcodes. Not covered (specified only): object, struct, map/set,
delegate/dispatcher and boxing instructions and nodes, fibers and latent suspension in the interpreter, and
the C runtime.

The test suite (`python3 tests.py`) checks: LEB128; formatter idempotence and canonical form for every
example; program results (Fibonacci, loops, FizzBuzz, arrays, Collatz, DoOnce with reset, Sequence order,
traps naming the node); layout- and order-independence of code generation; verifier rejection of type errors,
fall-through, bad targets and latent misuse; one diagnostic per error class; instruction budgets; and a
fuzz run of 4,000 corrupted modules that must be rejected cleanly.

## Roadmap and open questions

**Next, in order of dependency**

1. C runtime implementing `wiret.h` (verifier + interpreter + GC) validated against `tests.py` by a shared
   conformance corpus of `.wiret` programs with expected outputs.
2. Classes, interfaces, structs and containers in the reference compiler (the instruction set is specified).
3. Fibers and the scheduler; latent natives.
4. `wiret merge` / `wiret diff` and the semantic hash.
5. A bytecode JIT or faster interpreter dispatch (the encoding is deliberately easy to pre-decode).

**Decisions worth revisiting with real users**

* *Reference vs. value arrays.* Blueprint arrays are values; Wiret's are references. A copy-on-write
  value mode could be added per pin without changing the bytecode.
* *Macro input snapshots.* Safer for newcomers, but advanced users sometimes want Blueprint's
  re-evaluating inputs; a `live` annotation on a macro parameter could provide it.
* *Per-function graphs.* Blueprint's single Event Graph lets many events share nodes. Wiret requires a shared
  node to be a function that events call. This keeps entry points explicit and diffs local; an `EventGraph`
  construct that desugars to that is possible.
* *Exec reroute knots.* They are an editor concern, stored as layout waypoints on a wire (not specified yet).
* *Exceptions.* Traps end the fiber. A structured `try` node would need an unwinding story in the bytecode.
* *Smaller integer types and vectors.* Needed by many game hosts; reserved in the bytecode.


---

`examples/door.wiret`

```wiret
wiret 0.1

module "examples.door"
meta doc = "A door that opens on interaction and closes itself after a delay."

extern function print = "std.print"(text: string)
latent extern function delay = "std.delay"(seconds: f32)

enum DoorState {
  Closed = 0,
  Open = 1,
  Locked = 2,
}

struct Hit {
  damage: i32 = 1,
  source: string = "",
}

delegate OnStateChanged(previous: DoorState, current: DoorState)

interface Interactable {
  function Interact(instigator: string)
}

class Door : Interactable {
  meta category = "Props"
  var state: DoorState = DoorState.Closed [tooltip = "Current state of the door"]
  var changed: dispatcher<OnStateChanged>
  var auto_close_seconds: f32 = 2.5

  export latent event Interact(instigator: string) {
    graph {
      node %entry : Entry {
        exec then -> %is_closed
      }
      node %get_state : GetField<@Door.state> {
        in target = %self.value
      }
      node %self : Self<Door> {}
      node %closed : Eq<DoorState> {
        in a = %get_state.value
        in b = DoorState.Closed
      }
      node %is_closed : Branch {
        in condition = %closed.result
        exec then -> %open
      }
      node %open : SetField<@Door.state> {
        in target = %self.value
        in value = DoorState.Open
        exec then -> %announce
      }
      node %announce : Broadcast<@Door.changed> {
        in target = %self.value
        in previous = DoorState.Closed
        in current = DoorState.Open
        exec then -> %wait
      }
      node %get_delay : GetField<@Door.auto_close_seconds> {
        in target = %self.value
      }
      node %wait : Call<@delay> {
        in seconds = %get_delay.value
        exec then -> %close
      }
      node %close : SetField<@Door.state> {
        in target = %self.value
        in value = DoorState.Closed
      }
    }
    layout {
      %entry at (0, 0)
      %self at (0, 160)
      %get_state at (240, 160)
      %closed at (500, 160)
      %is_closed at (500, 0)
      %open at (760, 0)
      %announce at (1020, 0)
      %get_delay at (1020, 220)
      %wait at (1300, 0)
      %close at (1560, 0)
    }
  }
}

```

---

`examples/fibonacci.wiret`

```wiret
wiret 0.1

module "examples.fibonacci"
meta doc = "Recursive Fibonacci: the smallest useful Wiret program."

export pure function Fib(n: i32 [tooltip = "Which Fibonacci number to compute"]) -> (result: i32) {
  meta category = "Math"
  graph {
    node %entry : Entry {
      exec then -> %is_base
    }
    node %lt : Lt<i32> {
      in a = %entry.n
      in b = 2
    }
    node %is_base : Branch {
      in condition = %lt.result
      exec then -> %ret_n
      exec else -> %ret_sum
    }
    node %ret_n : Return {
      in result = %entry.n
    }
    node %n_minus_1 : Sub<i32> {
      in a = %entry.n
      in b = 1
    }
    node %n_minus_2 : Sub<i32> {
      in a = %entry.n
      in b = 2
    }
    node %fib_1 : Call<@Fib> {
      in n = %n_minus_1.result
    }
    node %fib_2 : Call<@Fib> {
      in n = %n_minus_2.result
    }
    node %sum : Add<i32> {
      in a = %fib_1.result
      in b = %fib_2.result
    }
    node %ret_sum : Return {
      in result = %sum.result
    }
  }
  layout {
    %entry at (0, 0)
    %lt at (260, 160)
    %is_base at (520, 0)
    %ret_n at (860, -40)
    %n_minus_1 at (260, 340)
    %n_minus_2 at (260, 500)
    %fib_1 at (520, 340)
    %fib_2 at (520, 500)
    %sum at (800, 420)
    %ret_sum at (1060, 380)
    box "Base case" at (-20, -70) size (1180, 330) [color = #3a5f8a]
  }
}

```

---

`examples/flow.wiret`

```wiret
wiret 0.1

module "examples.flow"

use "std.flow" as flow

extern function print = "std.print"(text: string)

var visits: i32 = 0

export function SumTo(n: i32) -> (sum: i32) {
  local $acc: i32 = 0
  graph {
    node %entry : Entry {
      exec then -> %loop
    }
    node %loop : flow.ForLoop {
      in first = 1
      in last = %entry.n
      exec body -> %accumulate
      exec completed -> %done
    }
    node %get_acc : GetLocal<$acc> {}
    node %plus : Add<i32> {
      in a = %get_acc.value
      in b = %loop.index
    }
    node %accumulate : SetLocal<$acc> {
      in value = %plus.result
    }
    node %done : Return {
      in sum = %get_acc.value
    }
  }
  layout {
    %entry at (0, 0)
    %loop at (260, 0)
    %get_acc at (260, 200)
    %plus at (500, 200)
    %accumulate at (760, 80)
    %done at (760, -60)
  }
}

export function FizzBuzz(limit: i32) {
  graph {
    node %entry : Entry {
      exec then -> %loop
    }
    node %loop : flow.ForLoop {
      in first = 1
      in last = %entry.limit
      exec body -> %by15
    }
    node %mod15 : Rem<i32> {
      in a = %loop.index
      in b = 15
    }
    node %is15 : Eq<i32> {
      in a = %mod15.result
      in b = 0
    }
    node %by15 : Branch {
      in condition = %is15.result
      exec then -> %say_fizzbuzz
      exec else -> %by3
    }
    node %say_fizzbuzz : Call<@print> {
      in text = "FizzBuzz"
    }
    node %mod3 : Rem<i32> {
      in a = %loop.index
      in b = 3
    }
    node %is3 : Eq<i32> {
      in a = %mod3.result
      in b = 0
    }
    node %by3 : Branch {
      in condition = %is3.result
      exec then -> %say_fizz
      exec else -> %by5
    }
    node %say_fizz : Call<@print> {
      in text = "Fizz"
    }
    node %mod5 : Rem<i32> {
      in a = %loop.index
      in b = 5
    }
    node %is5 : Eq<i32> {
      in a = %mod5.result
      in b = 0
    }
    node %by5 : Branch {
      in condition = %is5.result
      exec then -> %say_buzz
      exec else -> %say_number
    }
    node %say_buzz : Call<@print> {
      in text = "Buzz"
    }
    node %number_text : Convert<i32, string> {
      in value = %loop.index
    }
    node %say_number : Call<@print> {
      in text = %number_text.result
    }
  }
}

export function SumArray(values: array<i32>) -> (sum: i32, count: i32) {
  local $acc: i32 = 0
  graph {
    node %entry : Entry {
      exec then -> %each
    }
    node %each : flow.ForEach<i32> {
      in items = %entry.values
      exec body -> %accumulate
      exec completed -> %done
    }
    node %get_acc : GetLocal<$acc> {}
    node %plus : Add<i32> {
      in a = %get_acc.value
      in b = %each.element
    }
    node %accumulate : SetLocal<$acc> {
      in value = %plus.result
    }
    node %len : ArrayLen<i32> {
      in array = %entry.values
    }
    node %done : Return {
      in count = %len.length
      in sum = %get_acc.value
    }
  }
}

export function Collatz(start: i32) -> (steps: i32) {
  local $n: i32
  local $steps: i32 = 0
  graph {
    node %entry : Entry {
      exec then -> %init
    }
    node %init : SetLocal<$n> {
      in value = %entry.start
      exec then -> %check
    }
    node %get_n : GetLocal<$n> {}
    node %not_one : Ne<i32> {
      in a = %get_n.value
      in b = 1
    }
    node %check : Branch {
      in condition = %not_one.result
      exec then -> %step
      exec else -> %finish
    }
    node %odd_bit : Rem<i32> {
      in a = %get_n.value
      in b = 2
    }
    node %is_even : Eq<i32> {
      in a = %odd_bit.result
      in b = 0
    }
    node %half : Div<i32> {
      in a = %get_n.value
      in b = 2
    }
    node %triple : Mul<i32> {
      in a = %get_n.value
      in b = 3
    }
    node %triple_plus_one : Add<i32> {
      in a = %triple.result
      in b = 1
    }
    node %next : Select<i32> {
      in condition = %is_even.result
      in a = %half.result
      in b = %triple_plus_one.result
    }
    node %step : SetLocal<$n> {
      in value = %next.result
      exec then -> %count
    }
    node %get_steps : GetLocal<$steps> {}
    node %steps_plus_one : Add<i32> {
      in a = %get_steps.value
      in b = 1
    }
    node %count : SetLocal<$steps> {
      in value = %steps_plus_one.result
      exec then -> %check
    }
    node %finish : Return {
      in steps = %get_steps.value
    }
  }
}

export function Announce(reset: bool) {
  graph {
    node %entry : Entry {
      exec then -> %pick
    }
    node %pick : Branch {
      in condition = %entry.reset
      exec then -> %once.reset
      exec else -> %once
    }
    node %once : flow.DoOnce {
      exec completed -> %say
    }
    node %say : Call<@print> {
      in text = "first visit only"
    }
  }
}

export function Ordering() {
  graph {
    node %entry : Entry {
      exec then -> %seq
    }
    node %seq : Sequence<3> {
      exec then_0 -> %a
      exec then_1 -> %b
      exec then_2 -> %c
    }
    node %a : Call<@print> {
      in text = "A"
      exec then -> %a2
    }
    node %a2 : Call<@print> {
      in text = "A2"
    }
    node %b : Call<@print> {
      in text = "B"
    }
    node %c : Call<@print> {
      in text = "C"
    }
  }
}

export function Divide(a: i32, b: i32) -> (quotient: i32) {
  graph {
    node %entry : Entry {
      exec then -> %ret
    }
    node %div : Div<i32> {
      in a = %entry.a
      in b = %entry.b
    }
    node %ret : Return {
      in quotient = %div.result
    }
  }
}

```

---

`examples/host_example.c`

```wiret
/* Embeds the runtime, registers a native, loads fibonacci.wirb and flow.wirb and calls them. */
#include <stdio.h>
#include <stdlib.h>
#include "wiret.h"

static int host_log(wiret_Fiber *F, void *ud) {
  const char *prefix = (const char *)ud;
  size_t n; const char *s = wiret_checklstring(F, 1, &n);
  printf("%s%.*s\n", prefix, (int)n, s);
  return 0;                                  /* no results */
}

static void *read_file(const char *path, size_t *n) {
  FILE *f = fopen(path, "rb"); if (!f) return NULL;
  fseek(f, 0, SEEK_END); *n = (size_t)ftell(f); fseek(f, 0, SEEK_SET);
  void *buf = malloc(*n); if (fread(buf, 1, *n, f) != *n) { free(buf); buf = NULL; }
  fclose(f); return buf;
}

int main(void) {
  wiret_Config cfg = {0}; cfg.struct_size = sizeof cfg; cfg.default_budget = 10 * 1000 * 1000;
  wiret_VM *vm = wiret_vm_new(&cfg);
  wiret_Fiber *F = wiret_main(vm);
  wiret_register(vm, "std.print", "(string)->()", host_log, (void *)"[wiret] ", 0);

  size_t size; void *img = read_file("generated/flow.wirb", &size);
  wiret_Module *m; wiret_Diag diag;
  if (!img || wiret_module_load(vm, img, size, "flow", 0, &m, &diag) != WIRET_OK ||
      wiret_module_instantiate(F, m, &diag) != WIRET_OK) {
    fprintf(stderr, "load failed: %s (%s %s)\n", diag.message, diag.function, diag.node);
    return 1;
  }
  free(img);

  wiret_getexport(F, m, "SumTo");            /* push function     */
  wiret_pushi32(F, 100);                     /* push argument     */
  if (wiret_pcall(F, 1, 1) != WIRET_OK) {    /* call, 1 result    */
    char tb[512]; fprintf(stderr, "%s\n", wiret_traceback(F, tb, sizeof tb));
    return 1;
  }
  printf("SumTo(100) = %d\n", wiret_checki32(F, -1));
  wiret_pop(F, 1);

  wiret_getexport(F, m, "Divide"); wiret_pushi32(F, 1); wiret_pushi32(F, 0);
  if (wiret_pcall(F, 2, 1) != WIRET_OK) {    /* traps: integer divide by zero */
    char tb[512]; printf("error: %s\n", wiret_traceback(F, tb, sizeof tb));
  }
  wiret_vm_free(vm);
  return 0;
}

```

---

`generated/fib.hex.txt`

```
00 57 52 54 01 00 00 00 01 06 01 60 01 7f 01 7f 02 01 00 03 03 01 00 01 04 01 00 05 07 01 03 46 69 62 00 00 06 01 00 07 01 00 08 38 01 36 09 03 02 7f 01 7b 06 7f 11 01 02 28 02 00 01 04 02 03 06 01 00 11 01 01 21 03 00 01 07 00 01 03 01 04 11 05 02 21 06 00 05 07 00 01 06 01 07 20 08 04 07 06 01 08 00 26 0b 77 69 72 65 74 2e 6e 61 6d 65 73 12 65 78 61 6d 70 6c 65 73 2e 66 69 62 6f 6e 61 63 63 69 01 00 00 03 46 69 62 00 61 0d 77 69 72 65 74 2e 6e 6f 64 65 6d 61 70 09 02 6c 74 07 69 73 5f 62 61 73 65 05 72 65 74 5f 6e 09 6e 5f 6d 69 6e 75 73 5f 31 05 66 69 62 5f 31 09 6e 5f 6d 69 6e 75 73 5f 32 05 66 69 62 5f 32 03 73 75 6d 07 72 65 74 5f 73 75 6d 01 00 09 00 00 07 01 03 02 03 03 07 04 06 05 07 06 06 07 04 08 00 1a 0a 77 69 72 65 74 2e 70 69 6e 73 02 05 65 6e 74 72 79 01 6e 01 00 01 00 00 01
```

---

`generated/fib.svg`

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="-60 -110 1360 730" width="1360" height="730" font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="11">
<rect x="-60" y="-110" width="1360" height="730" fill="#1b1e24"/>
<rect x="-20" y="-70" width="1180" height="330" rx="6" fill="#3a5f8a" fill-opacity="0.16" stroke="#3a5f8a" stroke-opacity="0.6"/>
<text x="-10" y="-52" fill="#3a5f8a" font-size="13" font-weight="600">Base case</text>
<path d="M200.0,61.0 C240.0,61.0 220.0,199.0 260.0,199.0" fill="none" stroke="#4fc3a1" stroke-width="1.6" stroke-linecap="round"/>
<path d="M460.0,199.0 C500.0,199.0 480.0,61.0 520.0,61.0" fill="none" stroke="#d9534f" stroke-width="1.6" stroke-linecap="round"/>
<path d="M200.0,61.0 C530.0,61.0 530.0,21.0 860.0,21.0" fill="none" stroke="#4fc3a1" stroke-width="1.6" stroke-linecap="round"/>
<path d="M200.0,61.0 C240.0,61.0 220.0,379.0 260.0,379.0" fill="none" stroke="#4fc3a1" stroke-width="1.6" stroke-linecap="round"/>
<path d="M200.0,61.0 C240.0,61.0 220.0,539.0 260.0,539.0" fill="none" stroke="#4fc3a1" stroke-width="1.6" stroke-linecap="round"/>
<path d="M460.0,379.0 C500.0,379.0 480.0,379.0 520.0,379.0" fill="none" stroke="#4fc3a1" stroke-width="1.6" stroke-linecap="round"/>
<path d="M460.0,539.0 C500.0,539.0 480.0,539.0 520.0,539.0" fill="none" stroke="#4fc3a1" stroke-width="1.6" stroke-linecap="round"/>
<path d="M720.0,379.0 C760.0,379.0 760.0,459.0 800.0,459.0" fill="none" stroke="#4fc3a1" stroke-width="1.6" stroke-linecap="round"/>
<path d="M720.0,539.0 C760.0,539.0 760.0,481.0 800.0,481.0" fill="none" stroke="#4fc3a1" stroke-width="1.6" stroke-linecap="round"/>
<path d="M1000.0,459.0 C1040.0,459.0 1020.0,441.0 1060.0,441.0" fill="none" stroke="#4fc3a1" stroke-width="1.6" stroke-linecap="round"/>
<path d="M200.0,39.0 C360.0,39.0 360.0,39.0 520.0,39.0" fill="none" stroke="#f2f2f2" stroke-width="2.6" stroke-linecap="round"/>
<path d="M720.0,39.0 C790.0,39.0 790.0,-1.0 860.0,-1.0" fill="none" stroke="#f2f2f2" stroke-width="2.6" stroke-linecap="round"/>
<path d="M720.0,61.0 C890.0,61.0 890.0,419.0 1060.0,419.0" fill="none" stroke="#f2f2f2" stroke-width="2.6" stroke-linecap="round"/>
<rect x="0" y="0" width="200" height="80" rx="7" fill="#2a2e37" stroke="#434a57"/>
<path d="M0,7 a7,7 0 0 1 7,-7 h186 a7,7 0 0 1 7,7 v21 h-200 z" fill="#c0392b" fill-opacity="0.85"/>
<text x="10" y="18" fill="#fff" font-weight="600">Entry</text>
<path d="M195,33.0 h6 l5,6 l-5,6 h-6 z" fill="#f2f2f2"/>
<text x="188" y="43.0" fill="#d6dae0" text-anchor="end">then</text>
<circle cx="200" cy="61.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="188" y="65.0" fill="#d6dae0" text-anchor="end">n</text>
<rect x="260" y="160" width="200" height="80" rx="7" fill="#2a2e37" stroke="#434a57"/>
<path d="M260,167 a7,7 0 0 1 7,-7 h186 a7,7 0 0 1 7,7 v21 h-200 z" fill="#4f9d69" fill-opacity="0.85"/>
<text x="270" y="178" fill="#fff" font-weight="600">Lt&lt;i32&gt;</text>
<circle cx="260" cy="199.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="272" y="203.0" fill="#d6dae0" text-anchor="start">a</text>
<circle cx="260" cy="221.0" r="5" fill="#1b1e24" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="272" y="225.0" fill="#d6dae0" text-anchor="start">b = 2</text>
<circle cx="460" cy="199.0" r="5" fill="#d9534f" stroke="#d9534f" stroke-width="1.6"/>
<text x="448" y="203.0" fill="#d6dae0" text-anchor="end">result</text>
<rect x="520" y="0" width="200" height="80" rx="7" fill="#2a2e37" stroke="#434a57"/>
<path d="M520,7 a7,7 0 0 1 7,-7 h186 a7,7 0 0 1 7,7 v21 h-200 z" fill="#7f8c8d" fill-opacity="0.85"/>
<text x="530" y="18" fill="#fff" font-weight="600">Branch</text>
<path d="M515,33.0 h6 l5,6 l-5,6 h-6 z" fill="#f2f2f2"/>
<text x="532" y="43.0" fill="#d6dae0" text-anchor="start">in</text>
<circle cx="520" cy="61.0" r="5" fill="#d9534f" stroke="#d9534f" stroke-width="1.6"/>
<text x="532" y="65.0" fill="#d6dae0" text-anchor="start">condition</text>
<path d="M715,33.0 h6 l5,6 l-5,6 h-6 z" fill="#f2f2f2"/>
<text x="708" y="43.0" fill="#d6dae0" text-anchor="end">then</text>
<path d="M715,55.0 h6 l5,6 l-5,6 h-6 z" fill="#f2f2f2"/>
<text x="708" y="65.0" fill="#d6dae0" text-anchor="end">else</text>
<rect x="860" y="-40" width="200" height="80" rx="7" fill="#2a2e37" stroke="#434a57"/>
<path d="M860,-33 a7,7 0 0 1 7,-7 h186 a7,7 0 0 1 7,7 v21 h-200 z" fill="#c0392b" fill-opacity="0.85"/>
<text x="870" y="-22" fill="#fff" font-weight="600">Return</text>
<path d="M855,-7.0 h6 l5,6 l-5,6 h-6 z" fill="#f2f2f2"/>
<text x="872" y="3.0" fill="#d6dae0" text-anchor="start">in</text>
<circle cx="860" cy="21.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="872" y="25.0" fill="#d6dae0" text-anchor="start">result</text>
<rect x="260" y="340" width="200" height="80" rx="7" fill="#2a2e37" stroke="#434a57"/>
<path d="M260,347 a7,7 0 0 1 7,-7 h186 a7,7 0 0 1 7,7 v21 h-200 z" fill="#4f9d69" fill-opacity="0.85"/>
<text x="270" y="358" fill="#fff" font-weight="600">Sub&lt;i32&gt;</text>
<circle cx="260" cy="379.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="272" y="383.0" fill="#d6dae0" text-anchor="start">a</text>
<circle cx="260" cy="401.0" r="5" fill="#1b1e24" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="272" y="405.0" fill="#d6dae0" text-anchor="start">b = 1</text>
<circle cx="460" cy="379.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="448" y="383.0" fill="#d6dae0" text-anchor="end">result</text>
<rect x="260" y="500" width="200" height="80" rx="7" fill="#2a2e37" stroke="#434a57"/>
<path d="M260,507 a7,7 0 0 1 7,-7 h186 a7,7 0 0 1 7,7 v21 h-200 z" fill="#4f9d69" fill-opacity="0.85"/>
<text x="270" y="518" fill="#fff" font-weight="600">Sub&lt;i32&gt;</text>
<circle cx="260" cy="539.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="272" y="543.0" fill="#d6dae0" text-anchor="start">a</text>
<circle cx="260" cy="561.0" r="5" fill="#1b1e24" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="272" y="565.0" fill="#d6dae0" text-anchor="start">b = 2</text>
<circle cx="460" cy="539.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="448" y="543.0" fill="#d6dae0" text-anchor="end">result</text>
<rect x="520" y="340" width="200" height="58" rx="7" fill="#2a2e37" stroke="#434a57"/>
<path d="M520,347 a7,7 0 0 1 7,-7 h186 a7,7 0 0 1 7,7 v21 h-200 z" fill="#3b7dd8" fill-opacity="0.85"/>
<text x="530" y="358" fill="#fff" font-weight="600">Call&lt;@Fib&gt;</text>
<circle cx="520" cy="379.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="532" y="383.0" fill="#d6dae0" text-anchor="start">n</text>
<circle cx="720" cy="379.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="708" y="383.0" fill="#d6dae0" text-anchor="end">result</text>
<rect x="520" y="500" width="200" height="58" rx="7" fill="#2a2e37" stroke="#434a57"/>
<path d="M520,507 a7,7 0 0 1 7,-7 h186 a7,7 0 0 1 7,7 v21 h-200 z" fill="#3b7dd8" fill-opacity="0.85"/>
<text x="530" y="518" fill="#fff" font-weight="600">Call&lt;@Fib&gt;</text>
<circle cx="520" cy="539.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="532" y="543.0" fill="#d6dae0" text-anchor="start">n</text>
<circle cx="720" cy="539.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="708" y="543.0" fill="#d6dae0" text-anchor="end">result</text>
<rect x="800" y="420" width="200" height="80" rx="7" fill="#2a2e37" stroke="#434a57"/>
<path d="M800,427 a7,7 0 0 1 7,-7 h186 a7,7 0 0 1 7,7 v21 h-200 z" fill="#4f9d69" fill-opacity="0.85"/>
<text x="810" y="438" fill="#fff" font-weight="600">Add&lt;i32&gt;</text>
<circle cx="800" cy="459.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="812" y="463.0" fill="#d6dae0" text-anchor="start">a</text>
<circle cx="800" cy="481.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="812" y="485.0" fill="#d6dae0" text-anchor="start">b</text>
<circle cx="1000" cy="459.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="988" y="463.0" fill="#d6dae0" text-anchor="end">result</text>
<rect x="1060" y="380" width="200" height="80" rx="7" fill="#2a2e37" stroke="#434a57"/>
<path d="M1060,387 a7,7 0 0 1 7,-7 h186 a7,7 0 0 1 7,7 v21 h-200 z" fill="#c0392b" fill-opacity="0.85"/>
<text x="1070" y="398" fill="#fff" font-weight="600">Return</text>
<path d="M1055,413.0 h6 l5,6 l-5,6 h-6 z" fill="#f2f2f2"/>
<text x="1072" y="423.0" fill="#d6dae0" text-anchor="start">in</text>
<circle cx="1060" cy="441.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="1072" y="445.0" fill="#d6dae0" text-anchor="start">result</text>
</svg>
```

---

`generated/fibonacci.dis.txt`

```
; module examples.fibonacci

func f0 Fib pure (i32) -> (i32)
  regs: r0:i32, r1:i32, r2:bool, r3:i32, r4:i32, r5:i32, r6:i32, r7:i32, r8:i32
  ; --- %lt
         CONST.i32   r1 2
         LT.i32      r2 r0 r1
  ; --- %is_base
         JMPIFNOT    r2 @000d
  ; --- %ret_n
         RET         (r0)
  ; --- %n_minus_1
  @000d: CONST.i32   r1 1
         SUB.i32     r3 r0 r1
  ; --- %fib_1
         CALL        Fib (r3) (r4)
  ; --- %n_minus_2
         CONST.i32   r5 2
         SUB.i32     r6 r0 r5
  ; --- %fib_2
         CALL        Fib (r6) (r7)
  ; --- %sum
         ADD.i32     r8 r4 r7
  ; --- %ret_sum
         RET         (r8)
```

---

`generated/fibonacci.wirb`

```hex
0057 5254 0100 0000 0106 0160 017f 017f
0201 0003 0301 0001 0401 0005 0701 0346
6962 0000 0601 0007 0100 0838 0136 0903
027f 017b 067f 1101 0228 0200 0104 0203
0601 0011 0101 2103 0001 0700 0103 0104
1105 0221 0600 0507 0001 0601 0720 0804
0706 0108 0026 0b77 6972 6574 2e6e 616d
6573 1265 7861 6d70 6c65 732e 6669 626f
6e61 6363 6901 0000 0346 6962 0061 0d77
6972 6574 2e6e 6f64 656d 6170 0902 6c74
0769 735f 6261 7365 0572 6574 5f6e 096e
5f6d 696e 7573 5f31 0566 6962 5f31 096e
5f6d 696e 7573 5f32 0566 6962 5f32 0373
756d 0772 6574 5f73 756d 0100 0900 0007
0103 0203 0307 0406 0507 0606 0704 0800
1a0a 7769 7265 742e 7069 6e73 0205 656e
7472 7901 6e01 0001 0000 01
```

---

`generated/flow.dis.txt`

```
; module examples.flow
global g0 visits: i32 = 0
global g1 Announce$once/done: bool = False
import f0 std.print (string) -> ()

func f1 SumTo (i32) -> (i32)
  regs: r0:i32, r1:i32, r2:i32, r3:i32, r4:i32, r5:i32, r6:bool, r7:i32, r8:i32
  ; --- %entry
         CONST.i32   r3 0
         MOV         r1 r3
         CONST.i32   r3 0
         MOV         r2 r3
  ; --- %loop!in
         CONST.i32   r3 1
         MOV         r4 r3
         MOV         r5 r0
  ; --- %loop/init
         MOV         r2 r4
  ; --- %loop/le
  @0018: LE.i32      r6 r2 r5
  ; --- %loop/check
         JMPIFNOT    r6 @0035
  ; --- %loop!body
         MOV         r7 r2
  ; --- %plus
         ADD.i32     r3 r1 r7
  ; --- %accumulate
         MOV         r1 r3
  ; --- %loop/inc
         CONST.i32   r3 1
         ADD.i32     r8 r2 r3
  ; --- %loop/step
         MOV         r2 r8
         JMP         @0018
  ; --- %done
  @0035: RET         (r1)

func f2 FizzBuzz (i32) -> ()
  regs: r0:i32, r1:i32, r2:i32, r3:i32, r4:i32, r5:bool, r6:i32, r7:i32, r8:i32, r9:string
  ; --- %entry
         CONST.i32   r2 0
         MOV         r1 r2
  ; --- %loop!in
         CONST.i32   r2 1
         MOV         r3 r2
         MOV         r4 r0
  ; --- %loop/init
         MOV         r1 r3
  ; --- %loop/le
  @0012: LE.i32      r5 r1 r4
  ; --- %loop/check
         JMPIFNOT    r5 @0084
  ; --- %loop!body
         MOV         r6 r1
  ; --- %mod15
         CONST.i32   r2 15
         REM.i32     r7 r6 r2
  ; --- %is15
         CONST.i32   r8 0
         EQ.i32      r5 r7 r8
  ; --- %by15
         JMPIFNOT    r5 @0042
  ; --- %say_fizzbuzz
         CONST.str   r9 'FizzBuzz'
         CALL        print (r9) ()
  ; --- %loop/inc
  @0036: CONST.i32   r8 1
         ADD.i32     r7 r1 r8
  ; --- %loop/step
         MOV         r1 r7
         JMP         @0012
  ; --- %mod3
  @0042: CONST.i32   r7 3
         REM.i32     r8 r6 r7
  ; --- %is3
         CONST.i32   r2 0
         EQ.i32      r5 r8 r2
  ; --- %by3
         JMPIFNOT    r5 @005d
  ; --- %say_fizz
         CONST.str   r9 'Fizz'
         CALL        print (r9) ()
         JMP         @0036
  ; --- %mod5
  @005d: CONST.i32   r2 5
         REM.i32     r8 r6 r2
  ; --- %is5
         CONST.i32   r7 0
         EQ.i32      r5 r8 r7
  ; --- %by5
         JMPIFNOT    r5 @0079
  ; --- %say_buzz
         CONST.str   r9 'Buzz'
         CALL        print (r9) ()
         JMP         @0036
  ; --- %number_text
  @0079: CVT.i32.string r9 r6
  ; --- %say_number
         CALL        print (r9) ()
         JMP         @0036
  @0084: RET         ()

func f3 SumArray (array<i32>) -> (i32, i32)
  regs: r0:array<i32>, r1:i32, r2:i32, r3:i32, r4:array<i32>, r5:bool, r6:i32, r7:i32, r8:i32
  ; --- %entry
         CONST.i32   r3 0
         MOV         r1 r3
         CONST.i32   r3 0
         MOV         r2 r3
  ; --- %each!in
         MOV         r4 r0
  ; --- %each/init
         CONST.i32   r3 0
         MOV         r2 r3
  ; --- %each/len
  @0015: ARR.len     r3 r4
  ; --- %each/lt
         LT.i32      r5 r2 r3
  ; --- %each/check
         JMPIFNOT    r5 @003c
  ; --- %each/item
         ARR.get     r3 r4 r2
  ; --- %each!body
         MOV         r6 r3
         MOV         r7 r2
  ; --- %plus
         ADD.i32     r3 r1 r6
  ; --- %accumulate
         MOV         r1 r3
  ; --- %each/inc
         CONST.i32   r3 1
         ADD.i32     r8 r2 r3
  ; --- %each/step
         MOV         r2 r8
         JMP         @0015
  ; --- %len
  @003c: ARR.len     r8 r0
  ; --- %done
         RET         (r1, r8)

func f4 Collatz (i32) -> (i32)
  regs: r0:i32, r1:i32, r2:i32, r3:i32, r4:bool, r5:i32, r6:i32, r7:i32, r8:i32, r9:i32, r10:i32, r11:i32, r12:i32, r13:i32
  ; --- %entry
         CONST.i32   r3 0
         MOV         r1 r3
         CONST.i32   r3 0
         MOV         r2 r3
  ; --- %init
         MOV         r1 r0
  ; --- %not_one
  @000f: CONST.i32   r3 1
         NE.i32      r4 r1 r3
  ; --- %check
         JMPIFNOT    r4 @0051
  ; --- %odd_bit
         CONST.i32   r3 2
         REM.i32     r5 r1 r3
  ; --- %is_even
         CONST.i32   r6 0
         EQ.i32      r4 r5 r6
  ; --- %half
         CONST.i32   r7 2
         DIV.i32     r8 r1 r7
  ; --- %triple
         CONST.i32   r9 3
         MUL.i32     r10 r1 r9
  ; --- %triple_plus_one
         CONST.i32   r11 1
         ADD.i32     r12 r10 r11
  ; --- %next
         SELECT      r13 r4 r8 r12
  ; --- %step
         MOV         r1 r13
  ; --- %steps_plus_one
         CONST.i32   r13 1
         ADD.i32     r12 r2 r13
  ; --- %count
         MOV         r2 r12
         JMP         @000f
  ; --- %finish
  @0051: RET         (r2)

func f5 Announce (bool) -> ()
  regs: r0:bool, r1:bool, r2:string
  ; --- %pick
         JMPIFNOT    r0 @000b
  ; --- %once/clear
         CONST.bool  r1 0
         GLOBAL.set  Announce$once/done r1
  @0009: RET         ()
  ; --- %once/get_done
  @000b: GLOBAL.get  r1 Announce$once/done
  ; --- %once/check
         JMPIFNOT    r1 @0013
         JMP         @0009
  ; --- %once/mark
  @0013: CONST.bool  r1 1
         GLOBAL.set  Announce$once/done r1
  ; --- %say
         CONST.str   r2 'first visit only'
         CALL        print (r2) ()
         JMP         @0009

func f6 Ordering () -> ()
  regs: r0:string
  ; --- %a
         CONST.str   r0 'A'
         CALL        print (r0) ()
  ; --- %a2
         CONST.str   r0 'A2'
         CALL        print (r0) ()
  ; --- %b
         CONST.str   r0 'B'
         CALL        print (r0) ()
  ; --- %c
         CONST.str   r0 'C'
         CALL        print (r0) ()
         RET         ()

func f7 Divide (i32, i32) -> (i32)
  regs: r0:i32, r1:i32, r2:i32
  ; --- %div
         DIV.i32     r2 r0 r1
  ; --- %ret
         RET         (r2)
```

---

`generated/flow.wirb`

```hex
0057 5254 0100 0000 0124 085d 7f60 0170
0060 017f 017f 6001 7f00 6001 6e00 027f
7f60 017b 0060 0000 6002 7f7f 017f 020e
0103 7374 6405 7072 696e 7400 0100 030f
0702 0003 0004 0002 0005 0006 0007 0004
0702 7f01 007b 0100 0548 0705 5375 6d54
6f00 0108 4669 7a7a 4275 7a7a 0002 0853
756d 4172 7261 7900 0307 436f 6c6c 6174
7a00 0408 416e 6e6f 756e 6365 0005 084f
7264 6572 696e 6700 0606 4469 7669 6465
0007 0601 0007 2e08 0846 697a 7a42 757a
7a04 4669 7a7a 0442 757a 7a10 6669 7273
7420 7669 7369 7420 6f6e 6c79 0141 0241
3201 4201 4308 e003 0740 0903 067f 017b
027f 1103 0010 0103 1103 0010 0203 1103
0110 0403 1005 0010 0204 2906 0205 0406
1610 0702 2003 0107 1001 0311 0301 2008
0203 1002 0802 6306 0101 9001 0a04 057f
017b 037f 0170 1102 0010 0102 1102 0110
0302 1004 0010 0103 2905 0104 0405 ea00
1006 0111 020f 2407 0602 1108 0026 0507
0804 0514 1609 0007 0001 0900 1108 0120
0701 0810 0107 0250 1107 0324 0806 0711
0200 2605 0802 0405 0a16 0901 0700 0109
0002 5911 0205 2408 0602 1107 0026 0508
0704 050b 1609 0207 0001 0900 02bd 7f96
0906 0700 0109 0002 b27f 0600 5109 0501
6e00 037f 016e 0001 7b03 7f11 0300 1001
0311 0300 1002 0310 0400 1103 0010 0203
c103 0428 0502 0304 051d c203 0402 1006
0310 0702 2003 0106 1001 0311 0301 2008
0203 1002 0802 59c1 0800 0602 0108 5c0e
0304 7f01 7b09 7f11 0300 1001 0311 0300
1002 0310 0100 1103 0127 0401 0304 0438
1103 0224 0501 0311 0600 2604 0506 1107
0223 0801 0711 0903 220a 0109 110b 0120
0c0a 0ba8 0d04 080c 1001 0d11 0d01 200c
020d 1002 0c02 be7f 0601 0229 0302 027b
0170 0400 0815 0100 1901 0106 0018 0101
0401 0202 7615 0101 1901 0116 0203 0700
0102 0002 6626 0101 0170 1600 0407 0001
0000 1600 0507 0001 0000 1600 0607 0001
0000 1600 0707 0001 0000 0600 0b03 0103
7f23 0200 0106 0102 0088 010b 7769 7265
742e 6e61 6d65 730d 6578 616d 706c 6573
2e66 6c6f 770a 0000 0570 7269 6e74 0001
0553 756d 546f 0002 0846 697a 7a42 757a
7a00 0308 5375 6d41 7272 6179 0004 0743
6f6c 6c61 747a 0005 0841 6e6e 6f75 6e63
6500 0608 4f72 6465 7269 6e67 0007 0644
6976 6964 6501 0006 7669 7369 7473 0101
1241 6e6e 6f75 6e63 6524 6f6e 6365 2f64
6f6e 6500 f304 0d77 6972 6574 2e6e 6f64
656d 6170 3c05 656e 7472 7907 6c6f 6f70
2169 6e09 6c6f 6f70 2f69 6e69 7407 6c6f
6f70 2f6c 650a 6c6f 6f70 2f63 6865 636b
096c 6f6f 7021 626f 6479 0470 6c75 730a
6163 6375 6d75 6c61 7465 086c 6f6f 702f
696e 6309 6c6f 6f70 2f73 7465 7004 646f
6e65 056d 6f64 3135 0469 7331 3504 6279
3135 0c73 6179 5f66 697a 7a62 757a 7a04
6d6f 6433 0369 7333 0362 7933 0873 6179
5f66 697a 7a04 6d6f 6435 0369 7335 0362
7935 0873 6179 5f62 757a 7a0b 6e75 6d62
6572 5f74 6578 740a 7361 795f 6e75 6d62
6572 0765 6163 6821 696e 0965 6163 682f
696e 6974 0865 6163 682f 6c65 6e07 6561
6368 2f6c 740a 6561 6368 2f63 6865 636b
0965 6163 682f 6974 656d 0965 6163 6821
626f 6479 0865 6163 682f 696e 6309 6561
6368 2f73 7465 7003 6c65 6e04 696e 6974
076e 6f74 5f6f 6e65 0563 6865 636b 076f
6464 5f62 6974 0769 735f 6576 656e 0468
616c 6606 7472 6970 6c65 0f74 7269 706c
655f 706c 7573 5f6f 6e65 046e 6578 7404
7374 6570 0e73 7465 7073 5f70 6c75 735f
6f6e 6505 636f 756e 7406 6669 6e69 7368
0470 6963 6b0a 6f6e 6365 2f63 6c65 6172
0d6f 6e63 652f 6765 745f 646f 6e65 0a6f
6e63 652f 6368 6563 6b09 6f6e 6365 2f6d
6172 6b03 7361 7901 6102 6132 0162 0163
0364 6976 0372 6574 0701 0b00 000c 0109
0203 0304 0403 0503 0604 0703 0807 0905
0a02 1600 0006 0109 0203 0304 0404 0503
0b07 0c07 0d03 0e08 0807 0905 0f07 1007
1103 120a 1307 1407 1503 160b 1703 1803
0e00 000c 1903 1a06 1b03 1c04 1d03 1e04
1f06 0604 0703 2007 2105 2203 0a04 0e00
000c 2303 2407 2503 2607 2707 2807 2907
2a07 2b05 2c03 2d07 2e06 2f05 0600 3003
3108 3203 3305 3406 3506 0400 3608 3708
3808 3907 0200 3a04 3b00 e101 0a77 6972
6574 2e70 696e 7317 0565 6e74 7279 016e
0424 6163 6305 7661 6c75 6507 246c 6f6f
702f 6907 6c6f 6f70 2369 6e05 6669 7273
7404 6c61 7374 046c 6f6f 7005 696e 6465
7805 6c69 6d69 7406 7661 6c75 6573 0724
6561 6368 2f69 0765 6163 6823 696e 0569
7465 6d73 0465 6163 6807 656c 656d 656e
7405 7374 6172 7402 246e 0624 7374 6570
7305 7265 7365 7401 6101 6206 0106 0000
0101 0203 0204 0304 0506 0505 0707 0809
0205 0000 0a01 0403 0305 0604 0507 0608
0903 0600 000b 0102 0302 0c03 040d 0e06
0f10 070f 0904 0300 0011 0112 0302 1303
0501 0000 1407 0200 0015 0100 16
```

---

`generated/sumto.svg`

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="-40 -100 1040 420" width="1040" height="420" font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="11">
<rect x="-40" y="-100" width="1040" height="420" fill="#1b1e24"/>
<path d="M200.0,61.0 C240.0,61.0 220.0,83.0 260.0,83.0" fill="none" stroke="#4fc3a1" stroke-width="1.6" stroke-linecap="round"/>
<path d="M460.0,239.0 C500.0,239.0 460.0,239.0 500.0,239.0" fill="none" stroke="#4fc3a1" stroke-width="1.6" stroke-linecap="round"/>
<path d="M460.0,83.0 C500.0,83.0 460.0,261.0 500.0,261.0" fill="none" stroke="#4fc3a1" stroke-width="1.6" stroke-linecap="round"/>
<path d="M700.0,239.0 C740.0,239.0 720.0,141.0 760.0,141.0" fill="none" stroke="#4fc3a1" stroke-width="1.6" stroke-linecap="round"/>
<path d="M460.0,239.0 C610.0,239.0 610.0,1.0 760.0,1.0" fill="none" stroke="#4fc3a1" stroke-width="1.6" stroke-linecap="round"/>
<path d="M200.0,39.0 C240.0,39.0 220.0,39.0 260.0,39.0" fill="none" stroke="#f2f2f2" stroke-width="2.6" stroke-linecap="round"/>
<path d="M460.0,39.0 C610.0,39.0 610.0,119.0 760.0,119.0" fill="none" stroke="#f2f2f2" stroke-width="2.6" stroke-linecap="round"/>
<path d="M460.0,61.0 C610.0,61.0 610.0,-21.0 760.0,-21.0" fill="none" stroke="#f2f2f2" stroke-width="2.6" stroke-linecap="round"/>
<rect x="0" y="0" width="200" height="80" rx="7" fill="#2a2e37" stroke="#434a57"/>
<path d="M0,7 a7,7 0 0 1 7,-7 h186 a7,7 0 0 1 7,7 v21 h-200 z" fill="#c0392b" fill-opacity="0.85"/>
<text x="10" y="18" fill="#fff" font-weight="600">Entry</text>
<path d="M195,33.0 h6 l5,6 l-5,6 h-6 z" fill="#f2f2f2"/>
<text x="188" y="43.0" fill="#d6dae0" text-anchor="end">then</text>
<circle cx="200" cy="61.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="188" y="65.0" fill="#d6dae0" text-anchor="end">n</text>
<rect x="260" y="0" width="200" height="102" rx="7" fill="#2a2e37" stroke="#434a57"/>
<path d="M260,7 a7,7 0 0 1 7,-7 h186 a7,7 0 0 1 7,7 v21 h-200 z" fill="#5c6b7a" fill-opacity="0.85"/>
<text x="270" y="18" fill="#fff" font-weight="600">flow.ForLoop</text>
<path d="M255,33.0 h6 l5,6 l-5,6 h-6 z" fill="#f2f2f2"/>
<text x="272" y="43.0" fill="#d6dae0" text-anchor="start">in</text>
<circle cx="260" cy="61.0" r="5" fill="#1b1e24" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="272" y="65.0" fill="#d6dae0" text-anchor="start">first = 1</text>
<circle cx="260" cy="83.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="272" y="87.0" fill="#d6dae0" text-anchor="start">last</text>
<path d="M455,33.0 h6 l5,6 l-5,6 h-6 z" fill="#f2f2f2"/>
<text x="448" y="43.0" fill="#d6dae0" text-anchor="end">body</text>
<path d="M455,55.0 h6 l5,6 l-5,6 h-6 z" fill="#f2f2f2"/>
<text x="448" y="65.0" fill="#d6dae0" text-anchor="end">completed</text>
<circle cx="460" cy="83.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="448" y="87.0" fill="#d6dae0" text-anchor="end">index</text>
<rect x="260" y="200" width="200" height="58" rx="7" fill="#2a2e37" stroke="#434a57"/>
<path d="M260,207 a7,7 0 0 1 7,-7 h186 a7,7 0 0 1 7,7 v21 h-200 z" fill="#4f9d69" fill-opacity="0.85"/>
<text x="270" y="218" fill="#fff" font-weight="600">GetLocal&lt;$acc&gt;</text>
<circle cx="460" cy="239.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="448" y="243.0" fill="#d6dae0" text-anchor="end">value</text>
<rect x="500" y="200" width="200" height="80" rx="7" fill="#2a2e37" stroke="#434a57"/>
<path d="M500,207 a7,7 0 0 1 7,-7 h186 a7,7 0 0 1 7,7 v21 h-200 z" fill="#4f9d69" fill-opacity="0.85"/>
<text x="510" y="218" fill="#fff" font-weight="600">Add&lt;i32&gt;</text>
<circle cx="500" cy="239.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="512" y="243.0" fill="#d6dae0" text-anchor="start">a</text>
<circle cx="500" cy="261.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="512" y="265.0" fill="#d6dae0" text-anchor="start">b</text>
<circle cx="700" cy="239.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="688" y="243.0" fill="#d6dae0" text-anchor="end">result</text>
<rect x="760" y="80" width="200" height="80" rx="7" fill="#2a2e37" stroke="#434a57"/>
<path d="M760,87 a7,7 0 0 1 7,-7 h186 a7,7 0 0 1 7,7 v21 h-200 z" fill="#d98c2f" fill-opacity="0.85"/>
<text x="770" y="98" fill="#fff" font-weight="600">SetLocal&lt;$acc&gt;</text>
<path d="M755,113.0 h6 l5,6 l-5,6 h-6 z" fill="#f2f2f2"/>
<text x="772" y="123.0" fill="#d6dae0" text-anchor="start">in</text>
<circle cx="760" cy="141.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="772" y="145.0" fill="#d6dae0" text-anchor="start">value</text>
<path d="M955,113.0 h6 l5,6 l-5,6 h-6 z" fill="#f2f2f2"/>
<text x="948" y="123.0" fill="#d6dae0" text-anchor="end">then</text>
<rect x="760" y="-60" width="200" height="80" rx="7" fill="#2a2e37" stroke="#434a57"/>
<path d="M760,-53 a7,7 0 0 1 7,-7 h186 a7,7 0 0 1 7,7 v21 h-200 z" fill="#c0392b" fill-opacity="0.85"/>
<text x="770" y="-42" fill="#fff" font-weight="600">Return</text>
<path d="M755,-27.0 h6 l5,6 l-5,6 h-6 z" fill="#f2f2f2"/>
<text x="772" y="-17.0" fill="#d6dae0" text-anchor="start">in</text>
<circle cx="760" cy="1.0" r="5" fill="#4fc3a1" stroke="#4fc3a1" stroke-width="1.6"/>
<text x="772" y="5.0" fill="#d6dae0" text-anchor="start">sum</text>
</svg>
```

---

`include/wiret.h`

```c
/*
** wiret.h - Wiret embeddable runtime, C API (version 0.1, draft)
**
** Conventions
**   - Every function is prefixed `wiret_`; types are `wiret_Xxx`; macros are `WIRET_XXX`.
**   - Hosts talk to a fiber through a typed value stack, as in the Lua C API:
**     positive indices count from the bottom of the current frame (1 = first),
**     negative indices from the top (-1 = top). 0 is never valid.
**   - Functions that can fail return a wiret_Status. Functions that "raise" (wiret_error,
**     wiret_check*) never return; they unwind to the nearest protected call (wiret_pcall).
**   - Strings are UTF-8, length-prefixed, and may contain NUL bytes.
**   - A wiret_VM is single-threaded. Use one VM per thread; loaded module images are immutable.
*/
#ifndef WIRET_H
#define WIRET_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#if defined(_WIN32) && defined(WIRET_BUILD_SHARED)
#  define WIRET_API __declspec(dllexport)
#elif defined(_WIN32) && defined(WIRET_USE_SHARED)
#  define WIRET_API __declspec(dllimport)
#elif defined(__GNUC__)
#  define WIRET_API __attribute__((visibility("default")))
#else
#  define WIRET_API
#endif

#define WIRET_VERSION_MAJOR 0
#define WIRET_VERSION_MINOR 1
#define WIRET_BYTECODE_VERSION 1
#define WIRET_VERSION_NUM (WIRET_VERSION_MAJOR * 100 + WIRET_VERSION_MINOR)

/* ------------------------------------------------------------------ opaque types */
typedef struct wiret_VM     wiret_VM;      /* heap, module registry, natives, GC          */
typedef struct wiret_Fiber  wiret_Fiber;   /* a thread of execution + the host value stack */
typedef struct wiret_Module wiret_Module;  /* a loaded, verified module image              */
typedef struct wiret_Sched  wiret_Sched;   /* optional built-in scheduler                  */

typedef int32_t  wiret_I32;
typedef int64_t  wiret_I64;
typedef float    wiret_F32;
typedef double   wiret_F64;
typedef int      wiret_Ref;                /* registry reference; WIRET_NOREF means none   */
#define WIRET_NOREF (-1)

/* ------------------------------------------------------------------ status codes */
typedef enum wiret_Status {
  WIRET_OK = 0,
  WIRET_YIELD,         /* fiber suspended; resume it later                                 */
  WIRET_ERR_RUNTIME,   /* trap: divide by zero, bad index, null access, failed cast, ...   */
  WIRET_ERR_BUDGET,    /* instruction budget exhausted                                     */
  WIRET_ERR_MEMORY,    /* allocation failed or memory limit reached                        */
  WIRET_ERR_STACK,     /* call depth or host stack limit reached                           */
  WIRET_ERR_LOAD,      /* malformed binary image                                           */
  WIRET_ERR_VERIFY,    /* image is well-formed but violates a validation rule              */
  WIRET_ERR_LINK,      /* unresolved import, missing export, signature mismatch            */
  WIRET_ERR_TYPE,      /* host API misuse: wrong value type on the stack                   */
  WIRET_ERR_CANCELLED  /* fiber was cancelled by the host                                  */
} wiret_Status;

/* ------------------------------------------------------------------ value types */
typedef enum wiret_Type {
  WIRET_TNONE = -1,    /* invalid / out-of-range index                                     */
  WIRET_TBOOL = 0, WIRET_TI32, WIRET_TI64, WIRET_TF32, WIRET_TF64,
  WIRET_TSTRING, WIRET_TANY,
  WIRET_TSTRUCT, WIRET_TOBJECT, WIRET_TARRAY, WIRET_TMAP, WIRET_TSET,
  WIRET_TDELEGATE, WIRET_TDISPATCHER, WIRET_THOST,
  WIRET_TNULL          /* a null reference (object, array, map, set, delegate, host)       */
} wiret_Type;

/* ------------------------------------------------------------------ configuration */
typedef void *(*wiret_Alloc)(void *ud, void *ptr, size_t old_size, size_t new_size);
typedef void  (*wiret_LogFn)(void *ud, int level, const char *message);

enum { WIRET_LOG_TRACE, WIRET_LOG_INFO, WIRET_LOG_WARN, WIRET_LOG_ERROR };

enum {                                   /* wiret_Config.flags                              */
  WIRET_CFG_DETERMINISTIC = 1u << 0,     /* refuse natives not flagged WIRET_NATIVE_DETERMINISTIC */
  WIRET_CFG_NO_DEBUG_INFO = 1u << 1,     /* ignore node maps (saves memory, no node ids in traces) */
  WIRET_CFG_STRICT_LINK   = 1u << 2      /* fail instantiation on any unused-but-unresolved import */
};

typedef struct wiret_Config {
  size_t       struct_size;              /* set to sizeof(wiret_Config)                     */
  wiret_Alloc  alloc;                    /* NULL = malloc/realloc/free                      */
  void        *alloc_ud;
  size_t       memory_limit;             /* bytes, 0 = unlimited                            */
  uint32_t     max_call_depth;           /* 0 = default (200)                               */
  uint32_t     max_stack_slots;          /* host value stack slots per fiber, 0 = 1 million */
  uint64_t     default_budget;           /* instructions per resume, 0 = unlimited          */
  uint32_t     flags;
  wiret_LogFn  log;                      /* NULL = discard                                  */
  void        *log_ud;
} wiret_Config;

WIRET_API const char *wiret_version(void);                       /* "0.1.0"                */
WIRET_API wiret_VM   *wiret_vm_new(const wiret_Config *cfg);     /* cfg may be NULL        */
WIRET_API void        wiret_vm_free(wiret_VM *vm);               /* frees everything       */
WIRET_API wiret_Fiber *wiret_main(wiret_VM *vm);                 /* the VM's main fiber    */
WIRET_API wiret_VM   *wiret_fiber_vm(wiret_Fiber *F);

/* ------------------------------------------------------------------ loading modules */
typedef struct wiret_Diag {              /* filled in on load/verify/link failure          */
  wiret_Status status;
  char message[256];
  char function[96];                     /* function name, or "" */
  char node[96];                         /* graph node id (e.g. "loop/check"), or ""        */
  uint32_t pc;                           /* byte offset in the function body                */
} wiret_Diag;

/* Decode + validate an image. The image is copied (or referenced if WIRET_LOAD_BORROW). */
enum { WIRET_LOAD_BORROW = 1u << 0 };
WIRET_API wiret_Status wiret_module_load(wiret_VM *vm, const void *image, size_t size,
                                         const char *name, unsigned flags,
                                         wiret_Module **out, wiret_Diag *diag);

/* Link imports, create globals, run the start function (may itself call natives). */
WIRET_API wiret_Status wiret_module_instantiate(wiret_Fiber *F, wiret_Module *m, wiret_Diag *diag);
WIRET_API wiret_Module *wiret_module_find(wiret_VM *vm, const char *name);
WIRET_API void          wiret_module_release(wiret_Module *m);
WIRET_API const char   *wiret_module_name(const wiret_Module *m);

/* ------------------------------------------------------------------ native functions */
typedef int (*wiret_NativeFn)(wiret_Fiber *F, void *ud);
/*
** A native receives its arguments in stack slots 1..n, already type-checked against the
** declared signature. It pushes its results and returns how many it pushed.
**   return wiret_error(F, "message");   raise a trap
**   return wiret_yield(F, nresults);     suspend the fiber (latent natives only)
*/
enum {
  WIRET_NATIVE_PURE          = 1u << 0,  /* no observable effects; may be evaluated any number of times */
  WIRET_NATIVE_LATENT        = 1u << 1,  /* may yield                                                   */
  WIRET_NATIVE_DETERMINISTIC = 1u << 2   /* same inputs always give same outputs                        */
};

typedef struct wiret_NativeReg {
  const char    *name;        /* "module.function", e.g. "std.print"                      */
  const char    *signature;   /* "(string,i32)->(bool)"; same type syntax as .wiret files */
  wiret_NativeFn fn;
  unsigned       flags;
} wiret_NativeReg;

WIRET_API wiret_Status wiret_register(wiret_VM *vm, const char *name, const char *signature,
                                      wiret_NativeFn fn, void *ud, unsigned flags);
WIRET_API wiret_Status wiret_register_lib(wiret_VM *vm, const wiret_NativeReg *regs, size_t n, void *ud);
WIRET_API wiret_Status wiret_open_std(wiret_VM *vm);   /* std.print, std.math.*, std.string.*, std.delay, ... */

/* ------------------------------------------------------------------ host types (opaque handles) */
typedef struct wiret_HostType {
  const char *name;                       /* "host.Texture"                                  */
  size_t      size;                       /* bytes of payload                                */
  void      (*finalize)(void *payload);   /* called once when the GC frees the handle        */
  void      (*trace)(wiret_Fiber *F, void *payload);  /* optional: wiret_mark() contained refs */
} wiret_HostType;

WIRET_API wiret_Status wiret_register_hosttype(wiret_VM *vm, const wiret_HostType *t);
WIRET_API void *wiret_pushhost(wiret_Fiber *F, const char *type_name);     /* returns payload  */
WIRET_API void *wiret_tohost(wiret_Fiber *F, int idx, const char *type_name); /* NULL if not  */
WIRET_API void *wiret_checkhost(wiret_Fiber *F, int idx, const char *type_name);
WIRET_API void  wiret_mark(wiret_Fiber *F, int idx);                        /* for trace()      */

/* ------------------------------------------------------------------ stack manipulation */
WIRET_API int  wiret_gettop(wiret_Fiber *F);
WIRET_API void wiret_settop(wiret_Fiber *F, int idx);          /* idx = new top; fills with defaults */
WIRET_API void wiret_pop(wiret_Fiber *F, int n);
WIRET_API int  wiret_absindex(wiret_Fiber *F, int idx);
WIRET_API void wiret_pushvalue(wiret_Fiber *F, int idx);       /* copy of the value at idx          */
WIRET_API void wiret_rotate(wiret_Fiber *F, int idx, int n);
WIRET_API void wiret_remove(wiret_Fiber *F, int idx);
WIRET_API void wiret_insert(wiret_Fiber *F, int idx);          /* move top to idx                   */
WIRET_API int  wiret_checkstack(wiret_Fiber *F, int extra);    /* 1 on success                      */
WIRET_API void wiret_xmove(wiret_Fiber *from, wiret_Fiber *to, int n);

/* ------------------------------------------------------------------ pushing values */
WIRET_API void wiret_pushbool(wiret_Fiber *F, int b);
WIRET_API void wiret_pushi32(wiret_Fiber *F, wiret_I32 v);
WIRET_API void wiret_pushi64(wiret_Fiber *F, wiret_I64 v);
WIRET_API void wiret_pushf32(wiret_Fiber *F, wiret_F32 v);
WIRET_API void wiret_pushf64(wiret_Fiber *F, wiret_F64 v);
WIRET_API const char *wiret_pushstring(wiret_Fiber *F, const char *s);               /* NUL-terminated */
WIRET_API const char *wiret_pushlstring(wiret_Fiber *F, const char *s, size_t len);
WIRET_API const char *wiret_pushfstring(wiret_Fiber *F, const char *fmt, ...);       /* %s %d %I %f %% */
WIRET_API void wiret_pushnull(wiret_Fiber *F);
WIRET_API void wiret_pushany(wiret_Fiber *F, int idx);          /* box the value at idx into an any  */

/* ------------------------------------------------------------------ inspecting values */
WIRET_API wiret_Type  wiret_type(wiret_Fiber *F, int idx);
WIRET_API const char *wiret_typename(wiret_Fiber *F, int idx);  /* full type, e.g. "array<i32>"      */
WIRET_API int         wiret_isnull(wiret_Fiber *F, int idx);

/* "to" functions return a value and set *ok (if non-NULL) to 1/0; they never raise. */
WIRET_API int         wiret_tobool(wiret_Fiber *F, int idx, int *ok);
WIRET_API wiret_I32   wiret_toi32(wiret_Fiber *F, int idx, int *ok);
WIRET_API wiret_I64   wiret_toi64(wiret_Fiber *F, int idx, int *ok);
WIRET_API wiret_F32   wiret_tof32(wiret_Fiber *F, int idx, int *ok);
WIRET_API wiret_F64   wiret_tof64(wiret_Fiber *F, int idx, int *ok);
WIRET_API const char *wiret_tolstring(wiret_Fiber *F, int idx, size_t *len); /* NULL if not string;
                                                     valid until the value is popped or collected */

/* "check" functions raise a type error (like luaL_check*) - convenient inside natives. */
WIRET_API int         wiret_checkbool(wiret_Fiber *F, int idx);
WIRET_API wiret_I32   wiret_checki32(wiret_Fiber *F, int idx);
WIRET_API wiret_I64   wiret_checki64(wiret_Fiber *F, int idx);
WIRET_API wiret_F32   wiret_checkf32(wiret_Fiber *F, int idx);
WIRET_API wiret_F64   wiret_checkf64(wiret_Fiber *F, int idx);
WIRET_API const char *wiret_checklstring(wiret_Fiber *F, int idx, size_t *len);

/* ------------------------------------------------------------------ aggregates */
/* Structs have value semantics: setfield on a struct replaces the slot at idx with a
   modified copy. Objects have reference semantics: setfield mutates in place. */
WIRET_API wiret_Status wiret_pushstruct(wiret_Fiber *F, wiret_Module *m, const char *type_name);
WIRET_API wiret_Status wiret_newobject(wiret_Fiber *F, wiret_Module *m, const char *class_name);
WIRET_API wiret_Status wiret_getfield(wiret_Fiber *F, int idx, const char *field);   /* pushes   */
WIRET_API wiret_Status wiret_setfield(wiret_Fiber *F, int idx, const char *field);   /* pops     */
WIRET_API wiret_Status wiret_getmethod(wiret_Fiber *F, int idx, const char *method); /* pushes a bound delegate */

/* Arrays, maps and sets are mutable reference types; `elem`/`key`/`value` are type strings. */
WIRET_API void   wiret_newarray(wiret_Fiber *F, const char *elem_type);
WIRET_API size_t wiret_arraylen(wiret_Fiber *F, int idx);
WIRET_API wiret_Status wiret_arrayget(wiret_Fiber *F, int idx, size_t i);   /* pushes element    */
WIRET_API wiret_Status wiret_arrayset(wiret_Fiber *F, int idx, size_t i);   /* pops value        */
WIRET_API wiret_Status wiret_arraypush(wiret_Fiber *F, int idx);            /* pops value        */
WIRET_API void   wiret_newmap(wiret_Fiber *F, const char *key_type, const char *value_type);
WIRET_API size_t wiret_maplen(wiret_Fiber *F, int idx);
WIRET_API int    wiret_mapget(wiret_Fiber *F, int idx);   /* pops key; pushes value; returns found */
WIRET_API wiret_Status wiret_mapset(wiret_Fiber *F, int idx);               /* pops value, key   */
WIRET_API wiret_Status wiret_mapat(wiret_Fiber *F, int idx, size_t i);      /* pushes key, value (insertion order) */

/* ------------------------------------------------------------------ calling into Wiret */
/* Pushes the exported function `name` as a delegate. Fails with WIRET_ERR_LINK if absent. */
WIRET_API wiret_Status wiret_getexport(wiret_Fiber *F, wiret_Module *m, const char *name);

/* Stack on entry: [... fn arg1 ... argN]. On success they are replaced by nresults results.
   The argument count and types must match the function's signature (checked).               */
WIRET_API wiret_Status wiret_pcall(wiret_Fiber *F, int nargs, int nresults);   /* protected  */
WIRET_API void         wiret_call(wiret_Fiber *F, int nargs, int nresults);    /* raises on error */

/* After a failed pcall the error message is on the stack top. */
WIRET_API const char *wiret_traceback(wiret_Fiber *F, char *buf, size_t size); /* with node ids */

/* ------------------------------------------------------------------ errors */
WIRET_API int wiret_error(wiret_Fiber *F, const char *fmt, ...);       /* never returns        */
WIRET_API int wiret_typeerror(wiret_Fiber *F, int idx, const char *expected);

/* ------------------------------------------------------------------ fibers (coroutines) */
/*
** A fiber runs one call at a time and can suspend inside latent calls. Typical use:
**     wiret_Fiber *co = wiret_fiber_new(vm);
**     wiret_getexport(co, m, "Interact"); wiret_pushstring(co, "player");
**     st = wiret_resume(co, 1, &nres);          // first resume starts the call
**     while (st == WIRET_YIELD) { ...; st = wiret_resume(co, 0, &nres); }
*/
WIRET_API wiret_Fiber *wiret_fiber_new(wiret_VM *vm);
WIRET_API void         wiret_fiber_release(wiret_Fiber *F);
WIRET_API wiret_Status wiret_resume(wiret_Fiber *F, int nargs, int *nresults);
WIRET_API wiret_Status wiret_fiber_status(wiret_Fiber *F);     /* WIRET_OK=idle/finished, WIRET_YIELD=suspended */
WIRET_API void         wiret_cancel(wiret_Fiber *F);
WIRET_API int          wiret_yield(wiret_Fiber *F, int nresults);   /* inside natives: `return wiret_yield(F, 0);` */
WIRET_API void         wiret_setwait(wiret_Fiber *F, uint64_t tag, void *host_data);   /* why it is waiting */
WIRET_API uint64_t     wiret_getwait(wiret_Fiber *F, void **host_data);

/* Optional scheduler: runs fibers, implements std.delay / std.wait_frames / std.yield. */
WIRET_API wiret_Sched *wiret_sched_new(wiret_VM *vm);
WIRET_API void         wiret_sched_free(wiret_Sched *s);
WIRET_API wiret_Fiber *wiret_sched_spawn(wiret_Sched *s);                 /* new fiber owned by s */
WIRET_API wiret_Status wiret_sched_start(wiret_Sched *s, wiret_Fiber *F, int nargs);
WIRET_API void         wiret_sched_tick(wiret_Sched *s, double dt_seconds);
WIRET_API size_t       wiret_sched_active(const wiret_Sched *s);

/* ------------------------------------------------------------------ references and GC */
WIRET_API wiret_Ref wiret_ref(wiret_Fiber *F);                  /* pops top, roots it, returns handle */
WIRET_API void      wiret_getref(wiret_Fiber *F, wiret_Ref r);  /* pushes the value                   */
WIRET_API void      wiret_unref(wiret_Fiber *F, wiret_Ref r);

typedef enum wiret_GcOp { WIRET_GC_COLLECT, WIRET_GC_STOP, WIRET_GC_RESTART, WIRET_GC_STEP,
                          WIRET_GC_BYTES, WIRET_GC_SETPAUSE, WIRET_GC_SETSTEPMUL } wiret_GcOp;
WIRET_API size_t wiret_gc(wiret_VM *vm, wiret_GcOp op, size_t arg);

/* ------------------------------------------------------------------ limits */
WIRET_API void     wiret_setbudget(wiret_Fiber *F, uint64_t instructions);  /* per resume; 0 = unlimited */
WIRET_API uint64_t wiret_budget_left(wiret_Fiber *F);
WIRET_API void     wiret_setmemlimit(wiret_VM *vm, size_t bytes);

/* ------------------------------------------------------------------ debugging (graph-aware) */
typedef struct wiret_FrameInfo {
  const char *module;
  const char *function;
  const char *node;        /* current graph node id, e.g. "loop/check"; NULL without debug info */
  uint32_t    pc;
  int         is_native;
} wiret_FrameInfo;

enum { WIRET_HOOK_NODE = 1, WIRET_HOOK_CALL = 2, WIRET_HOOK_RETURN = 4, WIRET_HOOK_TRAP = 8 };
typedef void (*wiret_HookFn)(wiret_Fiber *F, int event, const wiret_FrameInfo *where, void *ud);

WIRET_API void wiret_sethook(wiret_Fiber *F, wiret_HookFn fn, int mask, void *ud);
WIRET_API int  wiret_getstack(wiret_Fiber *F, int level, wiret_FrameInfo *out);       /* 0 = innermost */
/* Push the current value of an output pin (e.g. node "add_1", pin "result") of a frame. */
WIRET_API wiret_Status wiret_getpin(wiret_Fiber *F, int level, const char *node, const char *pin);
WIRET_API wiret_Status wiret_setbreak(wiret_Module *m, const char *function, const char *node, int enable);

#ifdef __cplusplus
}
#endif
#endif /* WIRET_H */

```

---

`reference/build_docs.py`

```py
"""Assemble the documentation: substitute generated listings, render the HTML site and a combined Markdown file."""
import os, re, sys, html
sys.path.insert(0, os.path.dirname(__file__))
import markdown
from wiret_ref.ops import OPS, ref_impl, NUM_BASE
from wiret_ref.stdlib import STD_FLOW
from wiret_ref import *

ROOT = os.path.join(os.path.dirname(__file__), "..")
DOCS, GEN = f"{ROOT}/docs", f"{ROOT}/generated"
CHAPTERS = [("introduction", "01-introduction.md", "Introduction"),
            ("text-format", "02-text-format.md", "Text format"),
            ("standard-nodes", "03-standard-nodes.md", "Standard nodes"),
            ("bytecode", "04-bytecode.md", "Bytecode"),
            ("runtime-api", "05-runtime-api.md", "Runtime API"),
            ("tooling", "06-tooling.md", "Tooling")]

DESC = {
 "NOP": "no operation", "TRAP": "raise a runtime error with a constant message", "JMP": "unconditional branch",
 "JMPIF": "branch if the bool register is true", "JMPIFNOT": "branch if the bool register is false",
 "SWITCH": "jump table on an i32 register: value 0..n-1 selects an offset, anything else the default",
 "RET": "return the listed registers (types must equal the result types)",
 "CALL": "call function; args list; result registers list", "CALLV": "virtual call: class type, vtable slot, args (receiver first), results",
 "CALLI": "interface call: interface type, method index, args, results", "CALLD": "call through a delegate register",
 "SPAWN": "start a new fiber running fn(args); results discarded", "YIELD": "end the time slice; resume on the next scheduler step",
 "BREAK": "debugger breakpoint; no effect without a hook", "MOV": "d = a (same type)",
 "CONST.i32": "load constant", "CONST.i64": "load constant", "CONST.f32": "load constant", "CONST.f64": "load constant",
 "CONST.bool": "load 0/1", "CONST.str": "load string from the constant pool", "CONST.null": "null reference (or default struct)",
 "GLOBAL.get": "read global", "GLOBAL.set": "write global",
 "STR.CONCAT": "d = a + b", "STR.LEN": "length in UTF-8 bytes", "SELECT": "d = cond ? a : b (equal types)",
 "STRUCT.new": "build an immutable struct from field registers", "STRUCT.get": "read field", "STRUCT.with": "copy with one field replaced",
 "OBJ.new": "allocate object with default fields", "FIELD.get": "read field (traps on null)", "FIELD.set": "write field (traps on null)",
 "IS.inst": "d:bool = a is instance of type", "CAST": "checked cast; traps on failure", "CAST.try": "cast or null",
 "REF.eq": "reference equality", "REF.isnull": "d:bool = a is null",
 "ARR.new": "new empty array of the type", "ARR.len": "length", "ARR.get": "d = a[i]; traps if out of range", "ARR.set": "a[i] = v; traps if out of range",
 "ARR.push": "append", "ARR.insert": "insert at index (0..len)", "ARR.remove": "remove at index", "ARR.clear": "remove all", "ARR.clone": "shallow copy", "ARR.pop": "remove and return last; traps if empty",
 "MAP.new": "new empty map", "MAP.len": "count", "MAP.get": "d = m[k]; traps if missing", "MAP.tryget": "d (default if missing), found:bool, m, k",
 "MAP.set": "insert or replace (insertion order kept)", "MAP.has": "d:bool", "MAP.remove": "d:bool removed, m, k", "MAP.keyat": "i-th key in insertion order",
 "MAP.valat": "i-th value in insertion order", "MAP.clear": "remove all", "SET.new": "new empty set", "SET.len": "count", "SET.add": "d:bool added, s, v",
 "SET.has": "d:bool", "SET.remove": "d:bool removed", "SET.at": "i-th element in insertion order", "SET.clear": "remove all",
 "ANY.box": "box a value with its static type", "ANY.unbox": "unbox to the type; traps on mismatch", "ANY.tryunbox": "d, ok:bool, any, type",
 "ANY.is": "d:bool = box holds that type", "DELG.new": "d, delegate type, function, target register+1 (0 = unbound)",
 "DISP.new": "new empty dispatcher", "DISP.bind": "add delegate to the end", "DISP.unbind": "remove first equal delegate",
 "DISP.broadcast": "call every bound delegate in order", "DISP.clear": "remove all", "DISP.count": "number bound",
}
KIND = {"r": "reg", "s": "simm", "u": "uimm", "f32": "f32", "f64": "f64", "L": "label", "str": "str", "fn": "fn", "g": "global",
        "t": "type", "vt": "valtype", "rl": "(regs)", "sw": "switch"}

def ops_rows(names):
    rows = ["| Code | Mnemonic | Operands | Meaning | Ref |", "| --- | --- | --- | --- | --- |"]
    for n in names:
        code, spec, _ = OPS[n]
        rows.append(f"| `0x{code:02X}` | `{n}` | {' '.join(KIND[k] for k in spec) or '–'} | {DESC.get(n, '')} | {'✓' if ref_impl(n) else ''} |")
    return "\n".join(rows)

def by_range(lo, hi, exclude=()):
    return sorted([n for n, (c, _, _) in OPS.items() if lo <= c <= hi and n not in exclude], key=lambda n: OPS[n][0])

def numeric_table():
    fam = ["ADD", "SUB", "MUL", "DIV", "REM", "NEG", "EQ", "NE", "LT", "LE", "GT", "GE", "MIN", "MAX", "ABS", "SQRT",
           "AND", "OR", "XOR", "SHL", "SHR", "NOT"]
    rows = ["| Family | Operands | i32 | i64 | f32 | f64 |", "| --- | --- | --- | --- | --- | --- |"]
    for f in fam:
        cells, spec = [], None
        for t in ("i32", "i64", "f32", "f64"):
            n = f"{f}.{t}"
            if n in OPS:
                cells.append(f"`0x{OPS[n][0]:02X}`"); spec = OPS[n][1]
            else:
                cells.append("–")
        rows.append(f"| `{f}` | {' '.join(KIND[k] for k in spec)} | " + " | ".join(cells) + " |")
    return "\n".join(rows)

def listing(name):
    return open(f"{GEN}/{name}").read().rstrip()

def subs(text):
    d = open(f"{GEN}/flow.dis.txt").read()
    i = d.index("func f1 SumTo"); j = d.index("func f2 FizzBuzz")
    macros = ["macro " + m for m in STD_FLOW.split("\nmacro ")[1:]]
    pick = lambda nm: next(m for m in macros if m.startswith(f"macro {nm}")).rstrip()
    rep = {"{{FIB_DIS}}": listing("fibonacci.dis.txt").split("\n", 2)[2].strip("\n"),
           "{{SUMTO_DIS}}": d[i:j].strip("\n"),
           "{{STDFLOW_FORLOOP}}": pick("ForLoop"), "{{STDFLOW_DOONCE}}": pick("DoOnce"),
           "{{OPS_CONTROL}}": ops_rows(by_range(0x00, 0x19)),
           "{{OPS_NUMERIC}}": numeric_table(),
           "{{OPS_MISC}}": ops_rows(by_range(0x80, 0xA8)),
           "{{OPS_COMPOSITE}}": ops_rows(by_range(0xB0, 0xEB, exclude=("SELECT",)))}
    for k, v in rep.items():
        text = text.replace(k, v)
    return text

# ---- simple highlighter for wiret source
KW = r"\b(wiret|module|meta|use|as|extern|function|event|macro|enum|struct|class|interface|delegate|var|const|local|state|graph|layout|node|in|out|exec|prop|export|pure|latent|at|size|box)\b"
def hl_wiret(code):
    esc = html.escape(code, quote=False)
    tok = re.compile(r'(;[^\n]*)|("(?:[^"\\\n]|\\.)*")|(%[A-Za-z_][\w]*(?:/[\w]+)*|%[\w]+![\w]+)|(@[A-Za-z_][\w.]*)|(\$[A-Za-z_]\w*)|(\b-?\d[\w.]*\b|-?\d+)|(' + KW + r')|(\b(?:i32|i64|f32|f64|bool|string|any|array|map|set)\b)')
    def r(m):
        if m.group(1): return f'<span class="c">{m.group(1)}</span>'
        if m.group(2): return f'<span class="s">{m.group(2)}</span>'
        if m.group(3): return f'<span class="n">{m.group(3)}</span>'
        if m.group(4): return f'<span class="y">{m.group(4)}</span>'
        if m.group(5): return f'<span class="y">{m.group(5)}</span>'
        if m.group(6): return f'<span class="v">{m.group(6)}</span>'
        if m.group(7): return f'<span class="k">{m.group(7)}</span>'
        return f'<span class="t">{m.group(0)}</span>'
    return tok.sub(r, esc)

def render_md(text, cid):
    # protect svg placeholders
    svgs = {}
    def svg(m):
        k = f"@@SVG{len(svgs)}@@"; svgs[k] = open(f"{GEN}/{m.group(1)}.svg").read(); return k
    text = re.sub(r"\{\{SVG:(\w+)\}\}", svg, text)
    # fenced wiret blocks -> highlighted html (stash)
    stash = {}
    def fence(m):
        lang, code = m.group(1), m.group(2)
        k = f"@@CODE{len(stash)}@@"
        body = hl_wiret(code) if lang in ("wiret", "dis") else html.escape(code, quote=False)
        stash[k] = f'<pre class="code lang-{lang or "text"}"><code>{body}</code></pre>'
        return "\n" + k + "\n"
    text = re.sub(r"```(\w*)\n(.*?)```", fence, text, flags=re.S)
    # chapter links
    for c, f, _ in CHAPTERS:
        text = text.replace(f"({f}#", f"(#{c}-").replace(f"({f})", f"(#{c})")
    h = markdown.markdown(text, extensions=["tables", "toc", "sane_lists"],
                          extension_configs={"toc": {"slugify": lambda v, s: f"{cid}-" + re.sub(r"[^a-z0-9]+", "-", v.lower()).strip("-")}})
    for k, v in stash.items():
        h = h.replace(f"<p>{k}</p>", v).replace(k, v)
    for k, v in svgs.items():
        h = h.replace(f"<p>{k}</p>", f'<figure class="graph">{v}</figure>')
    return h

def main():
    combined, sections, nav = [], [], []
    for cid, fname, title in CHAPTERS:
        text = subs(open(f"{DOCS}/{fname}").read())
        combined.append(re.sub(r"\{\{SVG:\w+\}\}", "", text))
        h = render_md(text, cid)
        heads = re.findall(r'<h2 id="([^"]+)">(.*?)</h2>', h)
        nav.append((cid, title, heads))
        sections.append(f'<section class="chapter" id="{cid}" data-title="{title}" hidden>{h}</section>')
    open(f"{ROOT}/wiret-spec.md", "w").write("\n\n---\n\n".join(combined))
    tpl = open(f"{ROOT}/reference/site_template.html").read()
    navhtml = ""
    for cid, title, heads in nav:
        navhtml += f'<div class="ch"><a class="chlink" href="#{cid}" data-ch="{cid}">{title}</a><ul>'
        for hid, ht in heads:
            navhtml += f'<li><a href="#{hid}">{re.sub("<[^>]+>", "", ht)}</a></li>'
        navhtml += "</ul></div>"
    out = tpl.replace("{{NAV}}", navhtml).replace("{{CONTENT}}", "\n".join(sections))
    open(f"{ROOT}/site/index.html", "w").write(out)
    print("site", len(out) // 1024, "KB")

main()

```

---

`reference/site_template.html`

```html
<title>Wiret Reference</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+Condensed:wght@500;600&family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;1,400&display=swap">
<style>
/* Layout: sticky chapter rail beside a single reading column; one chapter shown at a time, routed by hash.
   Palette is the graph editor's own: data-wire teal on cool paper, code always on the editor's dark canvas. */
:root {
  --bg: #f2f5f7; --surface: #ffffff; --fg: #15202b; --muted: #566575; --line: #d6dde4;
  --accent: #087a72; --accent-soft: #dcefed; --warn: #a45a00; --warn-soft: #f8ecd9;
  --canvas: #15181e; --canvas-fg: #dde3ea; --canvas-line: #2c323c;
  --c-comment: #7b8795; --c-str: #e68ae0; --c-num: #a6d65e; --c-node: #7db7ff; --c-sym: #ffb454; --c-kw: #ff7f75; --c-type: #4fc3a1; --c-local: #ffb454;
  --f-sans: "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --f-head: "IBM Plex Sans Condensed", "IBM Plex Sans", system-ui, sans-serif;
  --f-mono: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #0e1116; --surface: #151a21; --fg: #e5e9ee; --muted: #94a1af; --line: #29313b;
  --accent: #46d1c0; --accent-soft: #14302e; --warn: #f0b35c; --warn-soft: #2f2414;
  --canvas: #0a0c10; --canvas-line: #262c35; color-scheme: dark; } }
:root[data-theme="dark"] {
  --bg: #0e1116; --surface: #151a21; --fg: #e5e9ee; --muted: #94a1af; --line: #29313b;
  --accent: #46d1c0; --accent-soft: #14302e; --warn: #f0b35c; --warn-soft: #2f2414;
  --canvas: #0a0c10; --canvas-line: #262c35; color-scheme: dark; }
* { box-sizing: border-box; }
body { background: var(--bg); color: var(--fg); font-family: var(--f-sans); font-size: 16px; line-height: 1.62;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); padding-block: 0; }
a { color: var(--accent); text-underline-offset: 2px; }
.top { display: flex; align-items: center; gap: 14px; padding-block: 14px; border-bottom: 1px solid var(--line); max-width: 1180px; margin: 0 auto; }
.mark { flex: none; }
.brand { font-family: var(--f-head); font-weight: 600; font-size: 24px; letter-spacing: .01em; line-height: 1; }
.brand small { display: block; font-family: var(--f-sans); font-weight: 400; font-size: 12.5px; color: var(--muted); letter-spacing: 0; margin-top: 4px; }
.tag { margin-left: auto; font-family: var(--f-mono); font-size: 12px; color: var(--muted); border: 1px solid var(--line); border-radius: 4px; padding: 3px 8px; white-space: nowrap; }
.menu { display: none; font: inherit; background: var(--surface); color: var(--fg); border: 1px solid var(--line); border-radius: 6px; padding: 6px 12px; cursor: pointer; }
.wrap { display: grid; grid-template-columns: 250px minmax(0, 1fr); gap: 48px; max-width: 1180px; margin: 0 auto; padding-block: 28px 64px; }
nav.rail { position: sticky; top: 16px; align-self: start; max-height: calc(100vh - 32px); overflow-y: auto; font-size: 14px; padding-right: 8px; }
.ch { margin-bottom: 14px; }
.chlink { display: block; font-family: var(--f-head); font-weight: 600; font-size: 16px; color: var(--fg); text-decoration: none; padding: 4px 8px; border-left: 3px solid transparent; }
.chlink.on { border-left-color: var(--accent); color: var(--accent); }
.ch ul { list-style: none; margin: 2px 0 0; padding: 0 0 0 11px; display: none; }
.ch.open ul { display: block; }
.ch li a { display: block; color: var(--muted); text-decoration: none; padding: 2px 8px; line-height: 1.4; }
.ch li a:hover { color: var(--fg); }
main { min-width: 0; max-width: 78ch; }
.chapter h1 { font-family: var(--f-head); font-weight: 600; font-size: 40px; line-height: 1.1; margin: 0 0 20px; text-wrap: balance; letter-spacing: -.005em; }
.chapter h2 { font-family: var(--f-head); font-weight: 600; font-size: 26px; line-height: 1.2; margin: 44px 0 12px; padding-top: 18px; border-top: 1px solid var(--line); text-wrap: balance; scroll-margin-top: 12px; }
.chapter h3 { font-family: var(--f-head); font-weight: 600; font-size: 19px; margin: 28px 0 8px; scroll-margin-top: 12px; }
.chapter p, .chapter li { text-wrap: pretty; }
.chapter ul, .chapter ol { padding-left: 1.3em; }
.chapter li { margin: 4px 0; }
code { font-family: var(--f-mono); font-size: .86em; background: var(--accent-soft); padding: .08em .35em; border-radius: 4px; overflow-wrap: anywhere; }
pre.code { background: var(--canvas); color: var(--canvas-fg); border: 1px solid var(--canvas-line); border-radius: 8px; padding: 14px 16px; overflow-x: auto; font-size: 13px; line-height: 1.55; margin: 16px 0; }
pre.code code { background: none; padding: 0; font-size: inherit; color: inherit; overflow-wrap: normal; }
.c { color: var(--c-comment); } .s { color: var(--c-str); } .n { color: var(--c-node); } .y { color: var(--c-sym); } .v { color: var(--c-local); }
.k { color: var(--c-kw); } .t { color: var(--c-type); }
table { display: block; overflow-x: auto; border-collapse: collapse; margin: 16px 0; font-size: 14.5px; width: 100%; }
th, td { text-align: left; padding: 7px 12px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { font-family: var(--f-head); font-weight: 600; background: var(--surface); position: sticky; left: 0; white-space: nowrap; }
td code { white-space: nowrap; }
td:last-child code { white-space: normal; }
blockquote { margin: 16px 0; padding: 4px 16px; border-left: 3px solid var(--warn); background: var(--warn-soft); }
figure.graph { margin: 20px 0; border-radius: 8px; overflow-x: auto; border: 1px solid var(--canvas-line); background: var(--canvas); }
figure.graph svg { display: block; min-width: 760px; width: 100%; height: auto; }
.pager { display: flex; justify-content: space-between; gap: 16px; margin-top: 56px; padding-top: 18px; border-top: 1px solid var(--line); flex-wrap: wrap; }
.pager a { font-family: var(--f-head); font-weight: 600; font-size: 17px; text-decoration: none; }
em { color: inherit; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
@media (max-width: 900px) {
  .wrap { grid-template-columns: minmax(0, 1fr); gap: 0; padding-top: 16px; }
  .menu { display: inline-block; }
  nav.rail { display: none; position: static; max-height: none; margin-bottom: 18px; padding: 10px 6px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); }
  nav.rail.show { display: block; }
  .chapter h1 { font-size: 32px; }
  .tag { display: none; }
  .top { padding-top: 12px; }
}
@media (prefers-reduced-motion: no-preference) { html { scroll-behavior: smooth; } }
</style>

<header class="top">
  <svg class="mark" width="44" height="30" viewBox="0 0 44 30" aria-hidden="true">
    <rect x="1" y="3" width="14" height="10" rx="2.5" fill="none" stroke="currentColor" stroke-width="2"/>
    <rect x="29" y="17" width="14" height="10" rx="2.5" fill="none" stroke="currentColor" stroke-width="2"/>
    <path d="M15 8 C24 8 20 22 29 22" fill="none" stroke="var(--accent)" stroke-width="2.4" stroke-linecap="round"/>
  </svg>
  <div class="brand">Wiret<small>Visual scripting, written as text</small></div>
  <span class="tag">draft 0.1 · bytecode v1</span>
  <button class="menu" id="menu" type="button" aria-expanded="false" aria-controls="rail">Contents</button>
</header>
<div class="wrap">
  <nav class="rail" id="rail" aria-label="Chapters">{{NAV}}</nav>
  <main id="main">{{CONTENT}}<div class="pager" id="pager"></div></main>
</div>
<script>
(function () {
  var chapters = Array.prototype.slice.call(document.querySelectorAll('.chapter'));
  var ids = chapters.map(function (c) { return c.id; });
  var rail = document.getElementById('rail');
  function show(id) {
    chapters.forEach(function (c) { c.hidden = c.id !== id; });
    document.querySelectorAll('.ch').forEach(function (el) {
      var on = el.querySelector('.chlink').dataset.ch === id;
      el.classList.toggle('open', on); el.querySelector('.chlink').classList.toggle('on', on);
    });
    var i = ids.indexOf(id), p = document.getElementById('pager');
    var prev = i > 0 ? '<a href="#' + ids[i - 1] + '">← ' + chapters[i - 1].dataset.title + '</a>' : '<span></span>';
    var next = i < ids.length - 1 ? '<a href="#' + ids[i + 1] + '">' + chapters[i + 1].dataset.title + ' →</a>' : '<span></span>';
    p.innerHTML = prev + next;
    document.title = chapters[i].dataset.title + ' – Wiret Reference';
  }
  function route() {
    var h = decodeURIComponent(location.hash.slice(1)), target = null, id = ids[0];
    if (h) {
      if (ids.indexOf(h) >= 0) id = h;
      else { target = document.getElementById(h); var c = target && target.closest('.chapter'); if (c) id = c.id; }
    }
    show(id);
    rail.classList.remove('show'); document.getElementById('menu').setAttribute('aria-expanded', 'false');
    if (target) target.scrollIntoView(); else window.scrollTo(0, 0);
  }
  document.getElementById('menu').addEventListener('click', function () {
    var s = rail.classList.toggle('show'); this.setAttribute('aria-expanded', String(s));
  });
  window.addEventListener('hashchange', route);
  route();
})();
</script>

```

---

`reference/tests.py`

```py
"""Spec conformance tests for the reference implementation. Run: python3 tests.py"""
import sys, glob, os, copy
sys.path.insert(0, os.path.dirname(__file__))
from wiret_ref import *
from wiret_ref import syntax
from wiret_ref.binary import encode_module, decode_module, uleb, sleb, Reader, VerifyError, WiretError

EX = os.path.join(os.path.dirname(__file__), "..", "examples")
passed = failed = 0
def check(name, cond, detail=""):
    global passed, failed
    if cond: passed += 1
    else: failed += 1; print("FAIL", name, detail)

def prog(name):
    return open(os.path.join(EX, name)).read()

def load(text):
    out = []
    vm = VM(); vm.register("std.print", lambda t: out.append(t))
    mod, warns = compile_text(text)
    data = encode_module(mod)
    return vm.load(data), out, data, warns

# LEB128
for v in [0, 1, 63, 64, 127, 128, 300, 2**31, 2**63]:
    check(f"uleb {v}", Reader(uleb(v)).uleb() == v)
for v in [0, 1, -1, 63, -64, 64, -65, 2**31 - 1, -2**31, 2**62, -2**62]:
    check(f"sleb {v}", Reader(sleb(v)).sleb() == v)

# formatter: round trip + idempotence on every example and the std library
from wiret_ref.stdlib import STD_FLOW
for name, text in [(os.path.basename(p), open(p).read()) for p in sorted(glob.glob(EX + "/*.wiret"))] + [("std.flow", STD_FLOW)]:
    out = format_module(parse(text))
    check(f"fmt idempotent {name}", format_module(parse(out)) == out)
    if name != "std.flow":
        check(f"fmt canonical {name}", out == text)

# semantics
inst, out, data, w = load(prog("fibonacci.wiret"))
check("fib", [inst.call("Fib", n) for n in range(12)] == [0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89])
inst, out, data, w = load(prog("flow.wiret"))
check("no warnings", w == [], w)
check("sumto", inst.call("SumTo", 100) == 5050 and inst.call("SumTo", 0) == 0)
inst.call("FizzBuzz", 15)
check("fizzbuzz", out == "1 2 Fizz 4 Buzz Fizz 7 8 Fizz Buzz 11 Fizz 13 14 FizzBuzz".split(), out)
check("sumarray", inst.call("SumArray", [3, 4, 5, 6]) == [18, 4] and inst.call("SumArray", []) == [0, 0])
check("collatz", inst.call("Collatz", 27) == 111 and inst.call("Collatz", 1) == 0)
out.clear(); inst.call("Announce", False); inst.call("Announce", False)
check("doonce", out == ["first visit only"], out)
out.clear(); inst.call("Announce", True); inst.call("Announce", False); inst.call("Announce", False)
check("doonce reset", out == ["first visit only"], out)
out.clear(); inst.call("Ordering")
check("sequence", out == ["A", "A2", "B", "C"], out)
try:
    inst.call("Divide", 1, 0); check("div trap", False)
except Trap as t:
    check("div trap names node", t.frames[0] == ("Divide", "div"), t.frames)
check("div trunc", inst.call("Divide", -7, 2) == -3)
check("wrap", True)

# determinism: layout, node order, ids' order and metadata do not change the instruction stream
src = prog("fibonacci.wiret")
ast = parse(src)
f = ast.funcs[0]
base = encode_module(compile_module(ast)[0])
f2 = copy.deepcopy(ast); f2.funcs[0].layout = []; f2.funcs[0].meta = []
nm = lambda mod: [(fn.instrs) for fn in mod.funcs]
check("layout-independent code", nm(compile_module(f2)[0]) == nm(compile_module(ast)[0]))
f3 = copy.deepcopy(ast); f3.funcs[0].nodes.reverse()
check("node-order-independent code", nm(compile_module(f3)[0]) == nm(compile_module(ast)[0]))

# verifier rejects bad modules
def mutate(data, fn):
    b = bytearray(data); fn(b); return bytes(b)
dm = decode_module(base); verify_module(dm)
bad = [("bad magic", mutate(base, lambda b: b.__setitem__(1, 0x58))),
       ("truncated", base[:60])]
for name, d in bad:
    try:
        verify_module(decode_module(d)); check(name, False)
    except WiretError:
        check(name, True)
# type error: hand-built module with i32 + f32
from wiret_ref.binary import Module, Func
m = Module("bad"); f = Func("f", [], ["i32"]); f.regtypes = ["i32", "f32"]
f.instrs = [["ADD.i32", [0, 0, 1]], ["RET", [[0]]]]; f.nodes = [None, None]; m.funcs.append(f)
try:
    verify_module(decode_module(encode_module(m))); check("verify type error", False)
except VerifyError as e:
    check("verify type error", "r1 is f32" in str(e), str(e))
f.instrs = [["ADD.i32", [0, 0, 0]]]; f.nodes = [None]
try:
    verify_module(decode_module(encode_module(m))); check("verify fallthrough", False)
except VerifyError:
    check("verify fallthrough", True)
m2 = Module("bad2"); g = Func("g", [], []); g.regtypes = []; g.instrs = [["JMP", [5]]]; g.nodes = [None]
try:
    encode_module(m2)
except Exception: pass
# latent rule
m3 = Module("lat"); m3.imports.append(("host", "wait", [], [], 2, "wait"))
h = Func("h", [], []); h.regtypes = []; h.instrs = [["CALL", [0, [], []]], ["RET", [[]]]]; h.nodes = [None, None]; m3.funcs.append(h)
try:
    verify_module(decode_module(encode_module(m3))); check("latent rule", False)
except VerifyError as e:
    check("latent rule", "latent" in str(e))

# compile errors carry codes and nodes
def err(text):
    try: compile_text(text); return None
    except CompileError as e: return e
hdr = 'wiret 0.1\nmodule "t"\n'
e = err(hdr + 'export function F() -> (r: i32) { graph { node %entry : Entry {} } }')
check("E0301", e and e.code == "E0301", e)
e = err(hdr + 'export function F(a: i32) -> (r: bool) { graph { node %entry : Entry { exec then -> %r } node %r : Return { in r = %entry.a } } }')
check("E0102", e and e.code == "E0102" and e.node == "r", e)
e = err(hdr + 'export function F() { graph { node %entry : Entry { exec then -> %nope } } }')
check("E0112", e and e.code == "E0112", e)
e = err(hdr + 'export function F() { graph { node %entry : Entry {} node %x : Frobnicate {} } }')
check("E0101", e and e.code == "E0101", e)
e = err(hdr + 'export function F() -> (r: i32) { graph { node %entry : Entry { exec then -> %r } node %a : Add<i32> { in a = %b.result } node %b : Add<i32> { in a = %a.result } node %r : Return { in r = %a.result } } }')
check("E0105", e and e.code == "E0105", e)
e = err(hdr + 'latent extern function wait = "host.wait"()\nexport function F() { graph { node %entry : Entry { exec then -> %w } node %w : Call<@wait> {} } }')
check("E0201", e and e.code == "E0201", e)
e = err(hdr + 'var g: i32 = 0\nexport pure function F() { graph { node %entry : Entry { exec then -> %s } node %s : SetVar<@g> { in value = 1 } } }')
check("E0202", e and e.code == "E0202", e)

# budget / budget trap
inst, out, data, w = load(prog("flow.wiret"))
inst.vm.budget = inst.steps + 100
try:
    inst.call("SumTo", 10**6); check("budget", False)
except Trap as t:
    check("budget", "budget" in t.msg)

# conformance of op tables
from wiret_ref.ops import OPS, BY_CODE
check("opcode uniqueness", len(OPS) == len(BY_CODE))
check("0xFF unassigned", 0xFF not in BY_CODE)

# loader fuzz: corrupted images must be rejected with WiretError, never crash
import random
random.seed(7)
crashes = 0
for fname in ("fibonacci", "flow"):
    img = encode_module(compile_text(prog(fname + ".wiret"))[0])
    for _ in range(2000):
        b = bytearray(img)
        for _ in range(random.randint(1, 4)):
            b[random.randrange(len(b))] = random.randrange(256)
        if random.random() < .2:
            b = b[:random.randrange(len(b))]
        try:
            verify_module(decode_module(bytes(b)))
        except WiretError:
            pass
        except Exception:
            crashes += 1
check("fuzz: 4000 corrupted images, no crashes", crashes == 0, crashes)

print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)

```

---

`reference/wiret_ref/__init__.py`

```py
"""Wiret reference implementation (specification validator)."""
from .syntax import parse, format_module
from .compiler import compile_text, compile_module, CompileError
from .binary import encode_module, decode_module, verify_module, disassemble
from .vm import VM, Trap

__all__ = ["parse", "format_module", "compile_text", "compile_module", "CompileError",
           "encode_module", "decode_module", "verify_module", "disassemble", "VM", "Trap"]

```

---

`reference/wiret_ref/__main__.py`

```py
"""wiret-ref command line:  python -m wiret_ref <command> ..."""
import sys
from . import *
from .render import render_module


def main(argv):
    if len(argv) < 2:
        print("usage: wiret_ref (fmt|check|build|dis|run|svg) FILE [args]")
        return 2
    cmd, path = argv[0], argv[1]
    rest = argv[2:]
    if cmd == "dis" and path.endswith(".wirb"):
        print(disassemble(decode_module(open(path, "rb").read())))
        return 0
    text = open(path, encoding="utf-8").read()
    try:
        if cmd == "fmt":
            sys.stdout.write(format_module(parse(text)))
        elif cmd == "check":
            mod, warns = compile_text(text)
            verify_module(decode_module(encode_module(mod)))
            for w in warns:
                print(w)
            print("ok")
        elif cmd in ("build", "dis"):
            mod, warns = compile_text(text)
            for w in warns:
                print(w, file=sys.stderr)
            data = encode_module(mod)
            if cmd == "build":
                out = rest[0] if rest else path.rsplit(".", 1)[0] + ".wirb"
                open(out, "wb").write(data)
                print(f"wrote {out} ({len(data)} bytes)")
            else:
                print(disassemble(decode_module(data)))
        elif cmd == "run":
            mod, _ = compile_text(text)
            vm = VM()
            vm.register("std.print", lambda t: print(t))
            inst = vm.load(encode_module(mod))
            args = []
            for a in rest[1:]:
                args.append(int(a) if a.lstrip("-").isdigit() else (a == "true" if a in ("true", "false") else a))
            print(inst.call(rest[0], *args))
        elif cmd == "svg":
            sys.stdout.write(render_module(parse(text), rest[0]))
        else:
            print("unknown command", cmd)
            return 2
    except (CompileError, WiretError, Exception) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

```

---

`reference/wiret_ref/binary.py`

```py
"""Wiret binary module format: encoder, decoder, verifier, disassembler."""
import struct
from .ops import OPS, BY_CODE

MAGIC = b"\x00WRT"
VERSION = 1

PRIM = {"i32": 0x7F, "i64": 0x7E, "f32": 0x7D, "f64": 0x7C, "bool": 0x7B, "string": 0x70, "any": 0x6F}
PRIM_REV = {v: k for k, v in PRIM.items()}
VT_REF = 0x6E
T_FUNC, T_STRUCT, T_CLASS, T_ARRAY, T_MAP, T_SET, T_IFACE, T_DELEGATE, T_DISPATCHER, T_HOST = \
    0x60, 0x5F, 0x5E, 0x5D, 0x5C, 0x5B, 0x5A, 0x58, 0x57, 0x56
F_PURE, F_LATENT, F_EVENT = 1, 2, 4

SEC_CUSTOM, SEC_TYPE, SEC_IMPORT, SEC_FUNCTION, SEC_GLOBAL, SEC_EXPORT, SEC_START, SEC_STRING, SEC_CODE = range(9)


class WiretError(Exception):
    pass


class VerifyError(WiretError):
    pass


# ---------------------------------------------------------------- LEB128
def uleb(n):
    assert n >= 0
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def sleb(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if (n == 0 and not b & 0x40) or (n == -1 and b & 0x40):
            out.append(b)
            return bytes(out)
        out.append(b | 0x80)


class Reader:
    def __init__(self, data, pos=0, end=None):
        self.d, self.p, self.end = data, pos, len(data) if end is None else end

    def eof(self):
        return self.p >= self.end

    def u8(self):
        if self.p >= self.end:
            raise WiretError("unexpected end of data")
        b = self.d[self.p]
        self.p += 1
        return b

    def uleb(self):
        r = s = 0
        while True:
            b = self.u8()
            r |= (b & 0x7F) << s
            s += 7
            if not b & 0x80:
                return r

    def sleb(self):
        r = s = 0
        while True:
            b = self.u8()
            r |= (b & 0x7F) << s
            s += 7
            if not b & 0x80:
                if b & 0x40:
                    r -= 1 << s
                return r

    def raw(self, n):
        if self.p + n > self.end:
            raise WiretError("unexpected end of data")
        v = self.d[self.p:self.p + n]
        self.p += n
        return v

    def name(self):
        return self.raw(self.uleb()).decode("utf-8")


def enc_name(s):
    b = s.encode("utf-8")
    return uleb(len(b)) + b


# ---------------------------------------------------------------- type table
def split_targs(s):
    parts, depth, cur = [], 0, ""
    for ch in s:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return parts


def type_head(t):
    """'array<i32>' -> ('array', ['i32']); 'i32' -> ('i32', [])"""
    if "<" in t:
        h, rest = t.split("<", 1)
        return h, split_targs(rest[:-1])
    return t, []


class TypeTable:
    def __init__(self):
        self.entries = []   # tuples
        self.index = {}

    def add(self, entry):
        if entry not in self.index:
            self.index[entry] = len(self.entries)
            self.entries.append(entry)
        return self.index[entry]

    def func(self, params, results):
        return self.add(("func", tuple(params), tuple(results)))

    def vt(self, t):
        """valtype bytes for a type string"""
        if t in PRIM:
            return bytes([PRIM[t]])
        h, a = type_head(t)
        if h == "array":
            i = self.add(("array", a[0]))
        elif h == "map":
            i = self.add(("map", a[0], a[1]))
        elif h == "set":
            i = self.add(("set", a[0]))
        elif h == "host":
            i = self.add(("host", a[0]))
        else:
            raise WiretError(f"type {t!r} not supported by this encoder")
        return bytes([VT_REF]) + uleb(i)

    def encode(self):
        out = uleb(len(self.entries))
        for e in self.entries:
            k = e[0]
            if k == "func":
                out += bytes([T_FUNC]) + uleb(len(e[1])) + b"".join(self.vt(t) for t in e[1])
                out += uleb(len(e[2])) + b"".join(self.vt(t) for t in e[2])
            elif k == "array":
                out += bytes([T_ARRAY]) + self.vt(e[1])
            elif k == "set":
                out += bytes([T_SET]) + self.vt(e[1])
            elif k == "map":
                out += bytes([T_MAP]) + self.vt(e[1]) + self.vt(e[2])
            elif k == "host":
                out += bytes([T_HOST]) + enc_name(e[1])
        return out


# ---------------------------------------------------------------- module model
class Func:
    def __init__(self, name, params, results, flags=0):
        self.name, self.params, self.results, self.flags = name, list(params), list(results), flags
        self.regtypes = []    # list of type strings
        self.instrs = []      # list of [opname, args]
        self.nodes = []       # parallel list: node id string or None
        self.pins = []        # (reg, node, pin)


class Module:
    def __init__(self, name="module"):
        self.name = name
        self.types = TypeTable()
        self.imports = []     # (module, field, params, results, flags, localname)
        self.funcs = []       # Func
        self.globals = []     # (name, type, mutable, init)
        self.exports = []     # (name, funcindex)
        self.strings = []
        self.start = None

    def string(self, s):
        if s not in self.strings:
            self.strings.append(s)
        return self.strings.index(s)


# ---------------------------------------------------------------- encode
def encode_instr_bytes(mod, name, args, rel=None):
    code, spec, _ = OPS[name]
    out = bytearray([code])
    ai = 0
    for k in spec:
        if k == "r" or k == "u" or k == "str" or k == "fn" or k == "g" or k == "t":
            out += uleb(args[ai]); ai += 1
        elif k == "s":
            out += sleb(args[ai]); ai += 1
        elif k == "f32":
            out += struct.pack("<f", args[ai]); ai += 1
        elif k == "f64":
            out += struct.pack("<d", args[ai]); ai += 1
        elif k == "vt":
            out += mod.types.vt(args[ai]); ai += 1
        elif k == "rl":
            out += uleb(len(args[ai])) + b"".join(uleb(r) for r in args[ai]); ai += 1
        elif k == "L":
            out += sleb(rel[0]); rel = rel[1:]; ai += 1
        elif k == "sw":
            labels, dflt = args[ai]
            out += uleb(len(labels))
            for _ in labels:
                out += sleb(rel[0]); rel = rel[1:]
            out += sleb(rel[0]); rel = rel[1:]
            ai += 1
    return bytes(out)


def _label_targets(name, args):
    """list of instruction-index targets referenced by this instruction, in encoding order"""
    _, spec, _ = OPS[name]
    t, ai = [], 0
    for k in spec:
        if k == "L":
            t.append(args[ai])
        elif k == "sw":
            t += list(args[ai][0]) + [args[ai][1]]
        ai += 1
    return t


def assemble(mod, f):
    """returns (code bytes, pcs list) with branch offsets resolved (size fix-point)."""
    n = len(f.instrs)
    targets = [_label_targets(nm, a) for nm, a in f.instrs]
    sizes = [len(encode_instr_bytes(mod, nm, a, [0] * len(t))) for (nm, a), t in zip(f.instrs, targets)]
    for _ in range(64):
        pcs, p = [], 0
        for s in sizes:
            pcs.append(p)
            p += s
        pcs.append(p)
        new = []
        for i, ((nm, a), t) in enumerate(zip(f.instrs, targets)):
            end = pcs[i] + sizes[i]
            rel = [pcs[x] - end for x in t]
            new.append(len(encode_instr_bytes(mod, nm, a, rel)))
        if new == sizes:
            break
        sizes = new
    out = bytearray()
    for i, ((nm, a), t) in enumerate(zip(f.instrs, targets)):
        end = pcs[i] + sizes[i]
        rel = [pcs[x] - end for x in t]
        b = encode_instr_bytes(mod, nm, a, rel)
        assert len(b) == sizes[i]
        out += b
    return bytes(out), pcs[:n]


def _const_bytes(mod, t, v):
    if t in ("i32", "i64"):
        return sleb(int(v or 0))
    if t == "f32":
        return struct.pack("<f", float(v or 0))
    if t == "f64":
        return struct.pack("<d", float(v or 0))
    if t == "bool":
        return bytes([1 if v else 0])
    if t == "string":
        return uleb(mod.string(v or ""))
    return b""


def _section(sid, payload):
    return bytes([sid]) + uleb(len(payload)) + payload


def encode_module(mod):
    # signatures first (so the type table is complete before encoding)
    imp_sigs = [mod.types.func(i[2], i[3]) for i in mod.imports]
    fn_sigs = [mod.types.func(f.params, f.results) for f in mod.funcs]
    codes, pcs_all = [], []
    for f in mod.funcs:
        raw, pcs = assemble(mod, f)
        groups = []
        for t in f.regtypes:
            if groups and groups[-1][1] == t:
                groups[-1][0] += 1
            else:
                groups.append([1, t])
        body = uleb(len(f.regtypes)) + uleb(len(groups))
        for c, t in groups:
            body += uleb(c) + mod.types.vt(t)
        body += raw
        codes.append(uleb(len(body)) + body)
        pcs_all.append(pcs)
    glob_enc = []
    for (nm, t, mut, init) in mod.globals:
        glob_enc.append(mod.types.vt(t) + bytes([1 if mut else 0]) + _const_bytes(mod, t, init))
    out = bytearray(MAGIC + struct.pack("<I", VERSION))
    out += _section(SEC_TYPE, mod.types.encode())
    p = uleb(len(mod.imports))
    for (m, fld, _, _, fl, _), sig in zip(mod.imports, imp_sigs):
        p += enc_name(m) + enc_name(fld) + b"\x00" + uleb(sig) + bytes([fl])
    out += _section(SEC_IMPORT, p)
    p = uleb(len(mod.funcs)) + b"".join(uleb(s) + bytes([f.flags]) for s, f in zip(fn_sigs, mod.funcs))
    out += _section(SEC_FUNCTION, p)
    out += _section(SEC_GLOBAL, uleb(len(glob_enc)) + b"".join(glob_enc))
    nimp = len(mod.imports)
    p = uleb(len(mod.exports)) + b"".join(enc_name(n) + b"\x00" + uleb(i) for n, i in mod.exports)
    out += _section(SEC_EXPORT, p)
    out += _section(SEC_START, uleb(0 if mod.start is None else mod.start + 1))
    out += _section(SEC_STRING, uleb(len(mod.strings)) + b"".join(enc_name(s) for s in mod.strings))
    out += _section(SEC_CODE, uleb(len(codes)) + b"".join(codes))
    # custom: names
    names = [(0, i, n) for i, (_, _, _, _, _, n) in enumerate(mod.imports)]
    names += [(0, nimp + i, f.name) for i, f in enumerate(mod.funcs)]
    names += [(1, i, g[0]) for i, g in enumerate(mod.globals)]
    p = enc_name("wiret.names") + enc_name(mod.name) + uleb(len(names))
    for k, i, n in names:
        p += bytes([k]) + uleb(i) + enc_name(n)
    out += _section(SEC_CUSTOM, p)
    # custom: nodemap (pc -> node id)
    strs = []

    def sidx(s):
        if s not in strs:
            strs.append(s)
        return strs.index(s)
    body = b""
    cnt = 0
    for fi, (f, pcs) in enumerate(zip(mod.funcs, pcs_all)):
        entries, last = [], None
        for pc, nd in zip(pcs, f.nodes):
            if nd != last and nd is not None:
                entries.append((pc, sidx(nd)))
            last = nd
        if not entries:
            continue
        cnt += 1
        body += uleb(nimp + fi) + uleb(len(entries))
        prev = 0
        for pc, si in entries:
            body += uleb(pc - prev) + uleb(si)
            prev = pc
    hdr = uleb(len(strs)) + b"".join(enc_name(s) for s in strs)
    out += _section(SEC_CUSTOM, enc_name("wiret.nodemap") + hdr + uleb(cnt) + body)
    # custom: pins (register -> node.pin) for value probes
    strs2 = []

    def sidx2(s):
        if s not in strs2:
            strs2.append(s)
        return strs2.index(s)
    body, cnt = b"", 0
    for fi, f in enumerate(mod.funcs):
        if not f.pins:
            continue
        cnt += 1
        body += uleb(nimp + fi) + uleb(len(f.pins))
        for reg, nd, pin in f.pins:
            body += uleb(reg) + uleb(sidx2(nd)) + uleb(sidx2(pin))
    hdr = uleb(len(strs2)) + b"".join(enc_name(s) for s in strs2)
    out += _section(SEC_CUSTOM, enc_name("wiret.pins") + hdr + uleb(cnt) + body)
    return bytes(out)


# ---------------------------------------------------------------- decode
class DModule:
    """decoded module"""
    def __init__(self):
        self.types = []        # raw entries
        self.imports = []      # dict(module, field, sig, flags)
        self.funcs = []        # dict(sig, flags, regtypes, code(list of (pc,name,args)), size)
        self.globals = []
        self.exports = []
        self.strings = []
        self.start = None
        self.customs = {}
        self.names = {}
        self.nodemap = {}      # funcindex -> [(pc, node)]
        self.pins = {}         # funcindex -> {reg: (node, pin)}


def _read_vt(r, types):
    b = r.u8()
    if b in PRIM_REV:
        return PRIM_REV[b]
    if b == VT_REF:
        return ("ref", r.uleb())
    raise WiretError(f"bad valtype 0x{b:02x}")


def type_name(dm, t):
    """normalise decoded valtype to a type string"""
    if isinstance(t, str):
        return t
    e = dm.types[t[1]]
    k = e[0]
    if k == "array":
        return f"array<{type_name(dm, e[1])}>"
    if k == "set":
        return f"set<{type_name(dm, e[1])}>"
    if k == "map":
        return f"map<{type_name(dm, e[1])},{type_name(dm, e[2])}>"
    if k == "host":
        return f"host<{e[1]}>"
    return f"#type{t[1]}"


def decode_module(data):
    try:
        return _decode_module(data)
    except WiretError:
        raise
    except (IndexError, KeyError, ValueError, struct.error, UnicodeDecodeError, OverflowError, RecursionError) as e:
        raise WiretError(f"malformed module: {e}") from None


def _decode_module(data):
    r = Reader(data)
    if r.raw(4) != MAGIC:
        raise WiretError("bad magic")
    ver = struct.unpack("<I", r.raw(4))[0]
    if ver != VERSION:
        raise WiretError(f"unsupported version {ver}")
    dm = DModule()
    last = 0
    while not r.eof():
        sid = r.u8()
        size = r.uleb()
        if r.p + size > len(data):
            raise WiretError("section extends past end of module")
        sr = Reader(data, r.p, r.p + size)
        r.p += size
        if sid != SEC_CUSTOM:
            if sid <= last:
                raise WiretError("sections out of order")
            last = sid
        if sid == SEC_TYPE:
            for _ in range(sr.uleb()):
                k = sr.u8()
                if k == T_FUNC:
                    ps = [_read_vt(sr, None) for _ in range(sr.uleb())]
                    rs = [_read_vt(sr, None) for _ in range(sr.uleb())]
                    dm.types.append(("func", ps, rs))
                elif k == T_ARRAY:
                    dm.types.append(("array", _read_vt(sr, None)))
                elif k == T_SET:
                    dm.types.append(("set", _read_vt(sr, None)))
                elif k == T_MAP:
                    dm.types.append(("map", _read_vt(sr, None), _read_vt(sr, None)))
                elif k == T_HOST:
                    dm.types.append(("host", sr.name()))
                else:
                    raise WiretError(f"unsupported type kind 0x{k:02x}")
        elif sid == SEC_IMPORT:
            for _ in range(sr.uleb()):
                m, f, kind, sig, fl = sr.name(), sr.name(), sr.u8(), sr.uleb(), sr.u8()
                dm.imports.append(dict(module=m, field=f, kind=kind, sig=sig, flags=fl))
        elif sid == SEC_FUNCTION:
            for _ in range(sr.uleb()):
                dm.funcs.append(dict(sig=sr.uleb(), flags=sr.u8()))
        elif sid == SEC_GLOBAL:
            for _ in range(sr.uleb()):
                t = _read_vt(sr, None)
                mut = sr.u8()
                tn = type_name(dm, t)
                if tn in ("i32", "i64"):
                    v = sr.sleb()
                elif tn == "f32":
                    v = struct.unpack("<f", sr.raw(4))[0]
                elif tn == "f64":
                    v = struct.unpack("<d", sr.raw(8))[0]
                elif tn == "bool":
                    v = bool(sr.u8())
                elif tn == "string":
                    v = ("str", sr.uleb())
                else:
                    v = None
                dm.globals.append(dict(type=tn, mutable=mut, init=v))
        elif sid == SEC_EXPORT:
            for _ in range(sr.uleb()):
                dm.exports.append((sr.name(), sr.u8(), sr.uleb()))
        elif sid == SEC_START:
            v = sr.uleb()
            dm.start = None if v == 0 else v - 1
        elif sid == SEC_STRING:
            dm.strings = [sr.name() for _ in range(sr.uleb())]
        elif sid == SEC_CODE:
            n = sr.uleb()
            if n != len(dm.funcs):
                raise WiretError("code/function count mismatch")
            for fi in range(n):
                size = sr.uleb()
                br = Reader(data, sr.p, sr.p + size)
                sr.p += size
                nregs, ng = br.uleb(), br.uleb()
                rts = []
                for _ in range(ng):
                    c = br.uleb()
                    t = _read_vt(br, None)
                    rts += [type_name(dm, t)] * c
                if len(rts) != nregs:
                    raise WiretError("register count mismatch")
                dm.funcs[fi]["regtypes"] = rts
                dm.funcs[fi]["code"] = _decode_code(dm, br)
        elif sid == SEC_CUSTOM:
            nm = sr.name()
            dm.customs[nm] = (sr.p, sr.end)
            if nm == "wiret.names":
                dm.names["module"] = sr.name()
                for _ in range(sr.uleb()):
                    k, i, n = sr.u8(), sr.uleb(), sr.name()
                    dm.names[(k, i)] = n
            elif nm == "wiret.nodemap":
                strs = [sr.name() for _ in range(sr.uleb())]
                for _ in range(sr.uleb()):
                    fi = sr.uleb()
                    pc, lst = 0, []
                    for _ in range(sr.uleb()):
                        pc += sr.uleb()
                        lst.append((pc, strs[sr.uleb()]))
                    dm.nodemap[fi] = lst
            elif nm == "wiret.pins":
                strs = [sr.name() for _ in range(sr.uleb())]
                for _ in range(sr.uleb()):
                    fi = sr.uleb()
                    d = {}
                    for _ in range(sr.uleb()):
                        reg = sr.uleb()
                        d[reg] = (strs[sr.uleb()], strs[sr.uleb()])
                    dm.pins[fi] = d
        else:
            raise WiretError(f"unknown section id {sid}")
    return dm


def _decode_code(dm, br):
    code = []
    start = br.p
    while not br.eof():
        pc = br.p - start
        opc = br.u8()
        if opc not in BY_CODE:
            raise WiretError(f"unknown opcode 0x{opc:02x} at pc {pc}")
        name = BY_CODE[opc]
        _, spec, _ = OPS[name]
        args = []
        for k in spec:
            if k in ("r", "u", "str", "fn", "g", "t"):
                args.append(br.uleb())
            elif k == "s":
                args.append(br.sleb())
            elif k == "f32":
                args.append(struct.unpack("<f", br.raw(4))[0])
            elif k == "f64":
                args.append(struct.unpack("<d", br.raw(8))[0])
            elif k == "vt":
                args.append(type_name(dm, _read_vt(br, None)))
            elif k == "rl":
                args.append([br.uleb() for _ in range(br.uleb())])
            elif k == "L":
                args.append(("rel", br.sleb()))
            elif k == "sw":
                n = br.uleb()
                labs = [("rel", br.sleb()) for _ in range(n)]
                args.append((labs, ("rel", br.sleb())))
        code.append([pc, name, args, br.p - start])
    # resolve relative labels to absolute pcs
    for ins in code:
        end = ins[3]
        new = []
        for a in ins[2]:
            if isinstance(a, tuple) and len(a) == 2 and a[0] == "rel":
                new.append(end + a[1])
            elif isinstance(a, tuple) and isinstance(a[0], list):
                new.append(([end + x[1] for x in a[0]], end + a[1][1]))
            else:
                new.append(a)
        ins[2] = new
    return code


# ---------------------------------------------------------------- verifier
def _fail(fi, pc, msg):
    raise VerifyError(f"function #{fi} pc {pc}: {msg}")


def verify_module(dm):
    try:
        _verify_module(dm)
    except WiretError:
        raise
    except (IndexError, KeyError, TypeError, ValueError, AttributeError) as e:
        raise VerifyError(f"invalid module: {type(e).__name__}: {e}") from None


def _verify_module(dm):
    nimp = len(dm.imports)
    sigs = []
    for e in dm.types:
        sigs.append(e)

    def sig_of(fidx):
        if fidx < nimp:
            e = dm.types[dm.imports[fidx]["sig"]]
            fl = dm.imports[fidx]["flags"]
        else:
            e = dm.types[dm.funcs[fidx - nimp]["sig"]]
            fl = dm.funcs[fidx - nimp]["flags"]
        if e[0] != "func":
            raise VerifyError(f"function {fidx}: signature is not a func type")
        return [type_name(dm, t) for t in e[1]], [type_name(dm, t) for t in e[2]], fl

    for fi, f in enumerate(dm.funcs):
        gi = nimp + fi
        params, results, flags = sig_of(gi)
        rt = f["regtypes"]
        if rt[:len(params)] != params:
            _fail(gi, 0, "parameter registers do not match signature")
        code = f["code"]
        starts = {c[0] for c in code}
        if not code:
            _fail(gi, 0, "empty body")
        if code[-1][1] not in ("RET", "JMP", "TRAP", "SWITCH"):
            _fail(gi, code[-1][0], "function can fall off its end")
        for pc, name, args, _ in code:
            _check(dm, gi, pc, name, args, rt, starts, sig_of, results, flags)
    for (nm, k, i) in dm.exports:
        if k == 0 and i >= nimp + len(dm.funcs):
            raise VerifyError(f"export {nm}: bad function index")


def _check(dm, gi, pc, name, args, rt, starts, sig_of, results, flags):
    code, spec, _ = OPS[name]

    def R(i):
        if i >= len(rt):
            _fail(gi, pc, f"{name}: register r{i} out of range")
        return rt[i]

    def want(i, t, what="operand"):
        if R(i) != t:
            _fail(gi, pc, f"{name}: r{i} is {R(i)}, expected {t}")
    for k, a in zip(spec, args):
        if k == "r":
            R(a)
        elif k == "L":
            if a not in starts:
                _fail(gi, pc, f"{name}: branch target {a} is not an instruction boundary")
        elif k == "sw":
            for x in list(a[0]) + [a[1]]:
                if x not in starts:
                    _fail(gi, pc, f"{name}: branch target {x} is not an instruction boundary")
        elif k == "str" and a >= len(dm.strings):
            _fail(gi, pc, f"{name}: string index {a} out of range")
        elif k == "g" and a >= len(dm.globals):
            _fail(gi, pc, f"{name}: global index {a} out of range")
        elif k == "fn" and a >= len(dm.imports) + len(dm.funcs):
            _fail(gi, pc, f"{name}: function index {a} out of range")
        elif k == "t" and a >= len(dm.types):
            _fail(gi, pc, f"{name}: type index {a} out of range")
    base, _, rest = name.partition(".")
    a = args
    if base in ("ADD", "SUB", "MUL", "DIV", "REM", "NEG", "MIN", "MAX", "ABS", "SQRT", "AND", "OR", "XOR",
                "SHL", "SHR", "NOT", "EQ", "NE", "LT", "LE", "GT", "GE") and rest in ("i32", "i64", "f32", "f64", "bool"):
        cmpop = base in ("EQ", "NE", "LT", "LE", "GT", "GE")
        want(a[0], "bool" if cmpop else rest)
        for r in a[1:]:
            want(r, rest)
    elif base == "STR" and rest != "":
        if rest == "CONCAT":
            for r in a: want(r, "string")
        elif rest == "LEN":
            want(a[0], "i32"); want(a[1], "string")
        else:
            want(a[0], "bool"); want(a[1], "string"); want(a[2], "string")
    elif base == "CONST":
        want(a[0], {"i32": "i32", "i64": "i64", "f32": "f32", "f64": "f64", "bool": "bool", "str": "string"}.get(rest, R(a[0])))
    elif base == "CVT":
        _, frm, to = name.split(".")
        want(a[0], to); want(a[1], frm)
    elif name == "MOV":
        if R(a[0]) != R(a[1]):
            _fail(gi, pc, f"MOV: type mismatch {R(a[0])} vs {R(a[1])}")
    elif name == "SELECT":
        want(a[1], "bool")
        if not (R(a[0]) == R(a[2]) == R(a[3])):
            _fail(gi, pc, "SELECT: operand types differ")
    elif name in ("JMPIF", "JMPIFNOT"):
        want(a[0], "bool")
    elif name == "SWITCH":
        want(a[0], "i32")
    elif name == "GLOBAL.get":
        want(a[0], dm.globals[a[1]]["type"])
    elif name == "GLOBAL.set":
        want(a[1], dm.globals[a[0]]["type"])
    elif name == "RET":
        if [R(x) for x in a[0]] != results:
            _fail(gi, pc, f"RET: register types {[R(x) for x in a[0]]} do not match results {results}")
    elif name in ("CALL", "SPAWN"):
        p, rs, fl = sig_of(a[0])
        if [R(x) for x in a[1]] != p:
            _fail(gi, pc, f"{name}: argument types {[R(x) for x in a[1]]} do not match {p}")
        if name == "CALL":
            if [R(x) for x in a[2]] != rs:
                _fail(gi, pc, f"CALL: result registers {[R(x) for x in a[2]]} do not match {rs}")
            if fl & F_LATENT and not flags & F_LATENT:
                _fail(gi, pc, "CALL: latent function called from a non-latent function")
    elif base == "ARR":
        arr = R(a[0]) if rest not in ("new", "len", "clone", "pop") else None
        if rest == "new":
            pass
        else:
            ai = a[1] if rest in ("len", "clone", "pop", "get") else a[0]
            t = R(ai)
            if not t.startswith("array<"):
                _fail(gi, pc, f"{name}: r{ai} is {t}, expected an array")
            el = t[6:-1]
            if rest == "len": want(a[0], "i32")
            elif rest == "get": want(a[0], el); want(a[2], "i32")
            elif rest == "set": want(a[1], "i32"); want(a[2], el)
            elif rest == "push": want(a[1], el)
            elif rest == "insert": want(a[1], "i32"); want(a[2], el)
            elif rest == "remove": want(a[1], "i32")
            elif rest == "pop": want(a[0], el)
            elif rest == "clone": want(a[0], t)


# ---------------------------------------------------------------- disassembler
def disassemble(dm, show_pc=True):
    nimp = len(dm.imports)
    out = []

    def fname(i):
        return dm.names.get((0, i), f"f{i}")

    out.append(f"; module {dm.names.get('module', '?')}")
    for i, g in enumerate(dm.globals):
        out.append(f"global g{i} {dm.names.get((1, i), '?')}: {g['type']} = {g['init']!r}")
    for i, im in enumerate(dm.imports):
        e = dm.types[im["sig"]]
        out.append(f"import f{i} {im['module']}.{im['field']} "
                   f"({', '.join(type_name(dm, t) for t in e[1])}) -> ({', '.join(type_name(dm, t) for t in e[2])})"
                   f"{' latent' if im['flags'] & F_LATENT else ''}{' pure' if im['flags'] & F_PURE else ''}")
    for fi, f in enumerate(dm.funcs):
        gi = nimp + fi
        e = dm.types[f["sig"]]
        flg = (" pure" if f["flags"] & F_PURE else "") + (" latent" if f["flags"] & F_LATENT else "") + \
              (" event" if f["flags"] & F_EVENT else "")
        out.append("")
        out.append(f"func f{gi} {fname(gi)}{flg} ({', '.join(type_name(dm, t) for t in e[1])}) "
                   f"-> ({', '.join(type_name(dm, t) for t in e[2])})")
        out.append("  regs: " + ", ".join(f"r{i}:{t}" for i, t in enumerate(f["regtypes"])))
        targets = set()
        for pc, name, args, _ in f["code"]:
            for k, a in zip(OPS[name][1], args):
                if k == "L":
                    targets.add(a)
                elif k == "sw":
                    targets.update(a[0]); targets.add(a[1])
        nm = dict()
        for pc, node in dm.nodemap.get(gi, []):
            nm[pc] = node
        for pc, name, args, _ in f["code"]:
            if pc in nm:
                out.append(f"  ; --- %{nm[pc]}")
            parts = []
            for k, a in zip(OPS[name][1], args):
                if k == "r": parts.append(f"r{a}")
                elif k == "L": parts.append(f"@{a:04x}")
                elif k == "sw": parts.append("[" + ", ".join(f"@{x:04x}" for x in a[0]) + f"] else @{a[1]:04x}")
                elif k == "rl": parts.append("(" + ", ".join(f"r{x}" for x in a) + ")")
                elif k == "fn": parts.append(fname(a))
                elif k == "g": parts.append(dm.names.get((1, a), f"g{a}"))
                elif k == "str": parts.append(repr(dm.strings[a]))
                elif k == "f32" or k == "f64": parts.append(repr(a))
                else: parts.append(str(a))
            label = f"@{pc:04x}:" if pc in targets else "      "
            out.append(f"  {label} {name:<11} {' '.join(parts)}".rstrip())
    return "\n".join(out)

```

---

`reference/wiret_ref/compiler.py`

```py
"""Wiret graph compiler: parsed module -> bytecode module.

Pipeline: resolve -> expand macros -> validate -> lower (exec graph -> basic blocks,
pure cones -> register code) -> assemble.
"""
import re
from . import syntax, binary
from .binary import Func, Module, F_PURE, F_LATENT, F_EVENT, type_head, split_targs
from .stdlib import LIBS

NUM = ("i32", "i64", "f32", "f64")
INTS = ("i32", "i64")
BIN = {"Add": "ADD", "Sub": "SUB", "Mul": "MUL", "Div": "DIV", "Rem": "REM", "Min": "MIN", "Max": "MAX"}
BITBIN = {"BitAnd": "AND", "BitOr": "OR", "BitXor": "XOR", "Shl": "SHL", "Shr": "SHR"}
UNARY = {"Neg": "NEG", "Abs": "ABS", "Sqrt": "SQRT"}
CMP = {"Eq": "EQ", "Ne": "NE", "Lt": "LT", "Le": "LE", "Gt": "GT", "Ge": "GE"}
BOOLB = {"And": "AND", "Or": "OR", "Xor": "XOR"}
MAX_CTX = 12


class CompileError(Exception):
    def __init__(self, code, msg, func=None, node=None):
        self.code, self.msg, self.func, self.node = code, msg, func, node
        where = ""
        if func:
            where = f" (in {func}" + (f" at %{node}" if node else "") + ")"
        super().__init__(f"{code}: {msg}{where}")


class Sig:
    def __init__(self, ins=None, outs=None, xin=None, xout=None, pure=False, terminal=False, defaults=None):
        self.ins, self.outs = ins or {}, outs or {}
        self.xin, self.xout = xin or [], xout or []
        self.pure, self.terminal = pure, terminal
        self.defaults = defaults or {}


def subst(t, m):
    if not m:
        return t
    return re.sub(r"[A-Za-z_][A-Za-z0-9_]*", lambda g: m.get(g.group(), g.group()), t)


class Ctx:
    """module-level symbol tables"""
    def __init__(self, ast):
        self.ast = ast
        self.macros = {}      # name -> syntax.Func (with alias prefixes)
        self.funcs = {}       # name -> dict(params, results, flags, index, decl, extern)
        self.globals = {}     # name -> (type, index)
        self.fn_order = []
        self.libs = []
        for path, alias in ast.uses:
            if path not in LIBS:
                raise CompileError("E0001", f"unknown module {path!r}")
            lib = syntax.parse(LIBS[path])
            self.libs.append(lib)
            for f in lib.funcs:
                if f.kind == "macro":
                    self.macros[f"{alias}.{f.name}"] = f
        for f in ast.funcs:
            if f.kind == "macro":
                self.macros[f.name] = f
        idx = 0
        for kind, n, target, ps, rs, mods in ast.externs:
            if kind != "function":
                continue
            fl = (F_PURE if "pure" in mods else 0) | (F_LATENT if "latent" in mods else 0)
            mod, _, field = target.rpartition(".")
            self.funcs[n] = dict(params=[(p.name, p.type, p.default) for p in ps],
                                 results=[(p.name, p.type) for p in rs], flags=fl, index=idx,
                                 extern=(mod, field), decl=None)
            idx += 1
        self.nimports = idx
        for f in ast.funcs:
            if f.kind == "macro" or not f.has_body:
                continue
            fl = (F_PURE if "pure" in f.mods else 0) | (F_LATENT if "latent" in f.mods else 0) | \
                 (F_EVENT if f.kind == "event" else 0)
            self.funcs[f.name] = dict(params=[(p.name, p.type, p.default) for p in f.params],
                                      results=[(p.name, p.type) for p in f.results], flags=fl, index=idx,
                                      extern=None, decl=f)
            self.fn_order.append(f.name)
            idx += 1
        for i, v in enumerate(ast.vars):
            self.globals[v.name] = (v.type, i)


# ------------------------------------------------------------------ signatures
def targ(node, i, kind="type"):
    if i >= len(node.targs) or node.targs[i][0] != kind:
        raise CompileError("E0103", f"{node.kind} needs a {kind} argument #{i + 1}", node=node.id)
    return node.targs[i][1]


def sig_of(node, ctx, scope):
    """scope: object with .locals (name->type), .fdecl, .fname"""
    k = node.kind
    f = scope.fdecl
    if k == "Entry":
        if f.kind == "macro":
            return Sig(outs={p.name: p.type for p in f.params if p.type != "exec"},
                       xout=[p.name for p in f.params if p.type == "exec"])
        outs = {p.name: p.type for p in f.params}
        return Sig(outs=outs, xout=["then"])
    if k == "Return":
        return Sig(ins={p.name: p.type for p in f.results}, xin=["in"], terminal=True,
                   defaults={p.name: p.default for p in f.results})
    if k == "Exit":
        return Sig(ins={p.name: p.type for p in f.results if p.type != "exec"},
                   xin=[p.name for p in f.results if p.type == "exec"], terminal=True,
                   defaults={p.name: p.default for p in f.results})
    if k == "Branch":
        return Sig(ins={"condition": "bool"}, xin=["in"], xout=["then", "else"])
    if k == "Sequence":
        n = targ(node, 0, "int")
        return Sig(xin=["in"], xout=[f"then_{i}" for i in range(n)])
    if k == "Switch":
        cases = dict(node.props).get("cases", ("list", []))[1]
        return Sig(ins={"value": "i32"}, xin=["in"], xout=[f"case_{i}" for i in range(len(cases))] + ["default"])
    if k == "Trap":
        return Sig(xin=["in"], terminal=True)
    if k in BIN or k in BITBIN:
        t = targ(node, 0)
        if t not in (INTS if k in BITBIN else NUM):
            raise CompileError("E0104", f"{k}<{t}> is not defined", node=node.id)
        return Sig(ins={"a": t, "b": t}, outs={"result": t}, pure=True)
    if k in UNARY or k == "BitNot":
        t = targ(node, 0)
        ok = INTS if k == "BitNot" else (("f32", "f64") if k == "Sqrt" else NUM)
        if t not in ok:
            raise CompileError("E0104", f"{k}<{t}> is not defined", node=node.id)
        return Sig(ins={"a": t}, outs={"result": t}, pure=True)
    if k in CMP:
        t = targ(node, 0)
        if t not in NUM + ("string", "bool"):
            raise CompileError("E0104", f"{k}<{t}> is not defined", node=node.id)
        if t == "bool" and k not in ("Eq", "Ne"):
            raise CompileError("E0104", f"{k}<bool> is not defined", node=node.id)
        return Sig(ins={"a": t, "b": t}, outs={"result": "bool"}, pure=True)
    if k in BOOLB:
        return Sig(ins={"a": "bool", "b": "bool"}, outs={"result": "bool"}, pure=True)
    if k == "Not":
        return Sig(ins={"a": "bool"}, outs={"result": "bool"}, pure=True)
    if k == "Const":
        t = targ(node, 0)
        return Sig(outs={"value": t}, pure=True)
    if k == "Convert":
        a, b = targ(node, 0), targ(node, 1)
        if f"CVT.{a}.{b}" not in binary.OPS:
            raise CompileError("E0104", f"no conversion from {a} to {b}", node=node.id)
        return Sig(ins={"value": a}, outs={"result": b}, pure=True)
    if k == "Select":
        t = targ(node, 0)
        return Sig(ins={"condition": "bool", "a": t, "b": t}, outs={"result": t}, pure=True)
    if k == "Concat":
        return Sig(ins={"a": "string", "b": "string"}, outs={"result": "string"}, pure=True)
    if k == "StrLen":
        return Sig(ins={"text": "string"}, outs={"length": "i32"}, pure=True)
    if k == "Reroute":
        t = targ(node, 0)
        return Sig(ins={"value": t}, outs={"value": t}, pure=True)
    if k in ("GetLocal", "SetLocal", "GetState", "SetState"):
        name = targ(node, 0, "local")
        t = scope.locals.get(name) if k.endswith("Local") else scope.states.get(name)
        if t is None:
            raise CompileError("E0120", f"unknown {'local' if k.endswith('Local') else 'state'} ${name}", node=node.id)
        if k.startswith("Get"):
            return Sig(outs={"value": t}, pure=True)
        return Sig(ins={"value": t}, xin=["in"], xout=["then"])
    if k in ("GetVar", "SetVar"):
        name = targ(node, 0, "sym")
        if name not in ctx.globals:
            raise CompileError("E0121", f"unknown variable @{name}", node=node.id)
        t = ctx.globals[name][0]
        if k == "GetVar":
            return Sig(outs={"value": t}, pure=True)
        return Sig(ins={"value": t}, xin=["in"], xout=["then"])
    if k == "Call":
        name = targ(node, 0, "sym")
        fn = ctx.funcs.get(name)
        if fn is None:
            raise CompileError("E0122", f"unknown function @{name}", node=node.id)
        pure = bool(fn["flags"] & F_PURE)
        return Sig(ins={n: t for n, t, _ in fn["params"]}, outs={n: t for n, t in fn["results"]},
                   xin=[] if pure else ["in"], xout=[] if pure else ["then"], pure=pure,
                   defaults={n: d for n, _, d in fn["params"]})
    if k.startswith("Array"):
        t = targ(node, 0)
        arr = f"array<{t}>"
        table = {
            "ArrayNew": Sig(outs={"array": arr}, xin=["in"], xout=["then"]),
            "ArrayLen": Sig(ins={"array": arr}, outs={"length": "i32"}, pure=True),
            "ArrayGet": Sig(ins={"array": arr, "index": "i32"}, outs={"value": t}, pure=True),
            "ArraySet": Sig(ins={"array": arr, "index": "i32", "value": t}, xin=["in"], xout=["then"]),
            "ArrayPush": Sig(ins={"array": arr, "value": t}, xin=["in"], xout=["then"]),
            "ArrayPop": Sig(ins={"array": arr}, outs={"value": t}, xin=["in"], xout=["then"]),
            "ArrayInsert": Sig(ins={"array": arr, "index": "i32", "value": t}, xin=["in"], xout=["then"]),
            "ArrayRemoveAt": Sig(ins={"array": arr, "index": "i32"}, xin=["in"], xout=["then"]),
            "ArrayClear": Sig(ins={"array": arr}, xin=["in"], xout=["then"]),
            "ArrayClone": Sig(ins={"array": arr}, outs={"clone": arr}, xin=["in"], xout=["then"]),
        }
        if k in table:
            return table[k]
    m = ctx.macros.get(k)
    if m is not None:
        mp = {tp: node.targs[i][1] for i, tp in enumerate(m.tparams) if i < len(node.targs)}
        return Sig(ins={p.name: subst(p.type, mp) for p in m.params if p.type != "exec"},
                   outs={p.name: subst(p.type, mp) for p in m.results if p.type != "exec"},
                   xin=[p.name for p in m.params if p.type == "exec"],
                   xout=[p.name for p in m.results if p.type == "exec"],
                   defaults={p.name: p.default for p in m.params if p.type != "exec"})
    raise CompileError("E0101", f"unknown node kind {k}", node=node.id)


def type_default_lit(t):
    if t in ("i32", "i64"):
        return ("int", 0)
    if t in ("f32", "f64"):
        return ("float", 0.0)
    if t == "bool":
        return ("bool", False)
    if t == "string":
        return ("str", "")
    return ("null",)


# ------------------------------------------------------------------ per-function compilation
class Scope:
    def __init__(self, fdecl):
        self.fdecl = fdecl
        self.locals = {p.name: p.type for p in fdecl.locals}
        self.states = {p.name: p.type for p in fdecl.states}
        self.local_init = {p.name: p.default for p in fdecl.locals}


class FnCompiler:
    def __init__(self, ctx, mod, fdecl, global_inits):
        self.ctx, self.mod, self.fdecl = ctx, mod, fdecl
        self.info = ctx.funcs[fdecl.name]
        self.scope = Scope(fdecl)
        self.fname = fdecl.name
        self.global_inits = global_inits        # list collecting (globalname, type) for hidden state
        self.nodes = {}
        self.vpins = {}                          # (nodeid,pin) -> type for macro in/out registers
        self.f = Func(fdecl.name, [t for _, t, _ in self.info["params"]], [t for _, t in self.info["results"]],
                      self.info["flags"])
        self.free = {}
        self.pinreg = {}
        self.localreg = {}
        self.cur = None
        self.warnings = []

    def err(self, code, msg, node=None):
        raise CompileError(code, msg, self.fname, node)

    # ---------------- macro expansion
    def expand(self):
        for n in self.fdecl.nodes:
            if n.id in self.nodes:
                self.err("E0130", f"duplicate node id %{n.id}", n.id)
            self.nodes[n.id] = n.clone()
        for depth in range(32):
            macs = [n for n in self.nodes.values() if n.kind in self.ctx.macros]
            if not macs:
                return
            for m in macs:
                self.expand_one(m)
        self.err("E0310", "macro expansion too deep (recursive macro?)")

    def expand_one(self, M):
        md = self.ctx.macros[M.kind]
        mp = {tp: M.targs[i][1] for i, tp in enumerate(md.tparams) if i < len(M.targs)}
        if len(M.targs) != len(md.tparams):
            self.err("E0103", f"{M.kind} expects {len(md.tparams)} type argument(s)", M.id)
        entries = [n for n in md.nodes if n.kind == "Entry"]
        exits = [n for n in md.nodes if n.kind == "Exit"]
        if len(entries) != 1 or len(exits) != 1:
            self.err("E0311", f"macro {md.name} needs exactly one Entry and one Exit node", M.id)
        E, X = entries[0], exits[0]
        pre = M.id + "/"
        rid = lambda x: pre + x
        xin_pins = [p for p in md.params if p.type == "exec"]
        din_pins = [p for p in md.params if p.type != "exec"]
        xout_pins = [p for p in md.results if p.type == "exec"]
        dout_pins = [p for p in md.results if p.type != "exec"]
        for lp in md.locals:
            nm = pre + lp.name
            self.scope.locals[nm] = subst(lp.type, mp)
            self.scope.local_init[nm] = lp.default
        for sp in md.states:
            nm = pre + sp.name
            t = subst(sp.type, mp)
            self.scope.states[nm] = t
            gname = f"{self.fname}${nm}"
            self.global_inits.append((gname, t, sp.default))

        def remap_ref(src):
            if src[0] != "ref":
                return src
            _, nid, pin = src
            if nid == E.id:
                return ("ref", M.id + "#in", pin)
            return ("ref", rid(nid), pin)

        def remap_tgt(t):
            tn, tp = t
            if tn == X.id:
                q = tp or xout_pins[0].name
                return (M.id + "!" + q, None)
            return (rid(tn), tp)

        new = {}
        for n in md.nodes:
            if n.id in (E.id, X.id):
                continue
            c = n.clone()
            c.id = rid(n.id)
            c.targs = [(k, subst(v, mp) if k == "type" else (pre + v if k == "local" else v)) for k, v in n.targs]
            if c.kind in ("GetState", "SetState", "GetLocal", "SetLocal"):
                pass
            c.ins = [(p, remap_ref(s)) for p, s in n.ins]
            c.execs = [(p, remap_tgt(t)) for p, t in n.execs]
            new[c.id] = c
        # entry stubs
        in_bind = {p: s for p, s in M.ins}
        for xp in xin_pins:
            st = syntax.Node(M.id + "!" + xp.name, "$Bind")
            st.binds = []
            for dp in din_pins:
                src = in_bind.get(dp.name)
                if src is None:
                    src = ("lit", dp.default if dp.default is not None else type_default_lit(subst(dp.type, mp)))
                st.binds.append(((M.id + "#in", dp.name), src, subst(dp.type, mp)))
                self.vpins[(M.id + "#in", dp.name)] = subst(dp.type, mp)
            ent = [t for p, t in E.execs if p == xp.name]
            if ent:
                st.execs = [("then", remap_tgt(ent[0]))]
            new[st.id] = st
        # exit stubs
        x_in = {p: s for p, s in X.ins}
        m_exec = {p: t for p, t in M.execs}
        common, groups, cur = [], {}, None
        for p_ in md.results:           # a data result belongs to the exec result that precedes it
            if p_.type == "exec":
                cur = p_.name
                groups[cur] = []
            elif cur is None:
                common.append(p_)
            else:
                groups[cur].append(p_)
        for dp in dout_pins:
            self.vpins[(M.id, dp.name)] = subst(dp.type, mp)
        for xq in xout_pins:
            st = syntax.Node(M.id + "!" + xq.name, "$Bind")
            st.binds = []
            for dp in common + groups[xq.name]:
                src = x_in.get(dp.name)
                if src is None:
                    src = ("lit", dp.default if dp.default is not None else type_default_lit(subst(dp.type, mp)))
                else:
                    src = remap_ref(src)
                st.binds.append(((M.id, dp.name), src, subst(dp.type, mp)))
                self.vpins[(M.id, dp.name)] = subst(dp.type, mp)
            if xq.name in m_exec:
                st.execs = [("then", m_exec[xq.name])]
            new[st.id] = st
        del self.nodes[M.id]
        self.nodes.update(new)
        first = xin_pins[0].name
        for n in self.nodes.values():
            n.execs = [(p, ((M.id + "!" + (tp or first), None) if tn == M.id else (tn, tp))) for p, (tn, tp) in n.execs]

    # ---------------- validation
    def sig(self, n):
        if n.kind == "$Bind":
            return Sig(xin=["in"], xout=["then"] if n.execs else [])
        return sig_of(n, self.ctx, self.scope)

    def validate(self):
        entries = [n for n in self.nodes.values() if n.kind == "Entry"]
        if len(entries) != 1:
            self.err("E0131", f"function needs exactly one Entry node (found {len(entries)})")
        self.entry = entries[0]
        for n in self.nodes.values():
            s = self.sig(n)
            for pin, src in n.ins:
                if pin not in s.ins:
                    self.err("E0111", f"node kind {n.kind} has no input pin {pin!r}", n.id)
                if src[0] == "ref":
                    tn, tp = src[1], src[2]
                    if (tn, tp) in self.vpins:
                        continue
                    if tn not in self.nodes:
                        self.err("E0110", f"reference to unknown node %{tn}", n.id)
                    if tp not in self.sig(self.nodes[tn]).outs:
                        self.err("E0111", f"node %{tn} has no output pin {tp!r}", n.id)
            for pin, (tn, tp) in n.execs:
                if pin not in s.xout:
                    self.err("E0113", f"node kind {n.kind} has no exec output {pin!r}", n.id)
                if tn not in self.nodes:
                    self.err("E0112", f"exec connection to unknown node %{tn}", n.id)
                ts = self.sig(self.nodes[tn])
                if (tp or (ts.xin[0] if ts.xin else None)) not in ts.xin:
                    self.err("E0114", f"%{tn} has no exec input {tp or 'in'!r}", n.id)
        # reachability warnings
        seen, st = set(), [self.entry.id]
        while st:
            x = st.pop()
            if x in seen:
                continue
            seen.add(x)
            st += [t[0] for _, t in self.nodes[x].execs]
        for n in self.nodes.values():
            s = self.sig(n)
            if n.id not in seen and not s.pure and n.kind != "$Bind" and "/" not in n.id and "!" not in n.id:
                self.warnings.append(f"W0001: node %{n.id} is not reachable from Entry")

    # ---------------- registers
    def tmp(self, t, temps):
        fl = self.free.get(t)
        if fl:
            r = fl.pop()
        else:
            r = len(self.f.regtypes)
            self.f.regtypes.append(t)
        temps.append(r)
        return r

    def release(self, temps):
        for r in temps:
            self.free.setdefault(self.f.regtypes[r], []).append(r)
        temps.clear()

    def persist(self, key, t):
        if key not in self.pinreg:
            r = len(self.f.regtypes)
            self.f.regtypes.append(t)
            self.pinreg[key] = r
            self.f.pins.append((r, key[0], key[1]))
        return self.pinreg[key]

    def emit(self, op, *args):
        self.f.instrs.append([op, list(args)])
        self.f.nodes.append(self.cur)
        return len(self.f.instrs) - 1

    # ---------------- value evaluation
    def const(self, t, lit, temps, where):
        r = self.tmp(t, temps)
        k = lit[0]
        if lit == ("null",) and t.startswith("array<"):
            self.emit("ARR.new", r, self.mod.types.add(("array", type_head(t)[1][0])))
            return r
        if t in ("i32", "i64"):
            if k != "int":
                self.err("E0102", f"literal {syntax.fmt_lit(lit)} is not a valid {t}", where)
            lim = 31 if t == "i32" else 63
            if not -(1 << lim) <= lit[1] < (1 << lim):
                self.err("E0102", f"integer literal {lit[1]} out of range for {t}", where)
            self.emit(f"CONST.{t}", r, lit[1])
        elif t in ("f32", "f64"):
            if k not in ("int", "float"):
                self.err("E0102", f"literal {syntax.fmt_lit(lit)} is not a valid {t}", where)
            self.emit(f"CONST.{t}", r, float(lit[1]))
        elif t == "bool":
            if k != "bool":
                self.err("E0102", f"literal {syntax.fmt_lit(lit)} is not a valid bool", where)
            self.emit("CONST.bool", r, 1 if lit[1] else 0)
        elif t == "string":
            if k != "str":
                self.err("E0102", f"literal {syntax.fmt_lit(lit)} is not a valid string", where)
            self.emit("CONST.str", r, self.mod.string(lit[1]))
        elif k == "null":
            self.emit("CONST.null", r)
        else:
            self.err("E0002", f"literals of type {t} are not supported by the reference compiler", where)
        return r

    def eval_src(self, src, t, memo, temps, where):
        if src is None:
            return self.const(t, type_default_lit(t), temps, where)
        if src[0] == "lit":
            return self.const(t, src[1], temps, where)
        _, nid, pin = src
        r = self.eval_ref(nid, pin, memo, temps, where)
        if self.f.regtypes[r] != t:
            self.err("E0102", f"type mismatch: %{nid}.{pin} is {self.f.regtypes[r]} but the input expects {t}", where)
        return r

    def eval_ref(self, nid, pin, memo, temps, where):
        if (nid, pin) in self.vpins:
            return self.persist((nid, pin), self.vpins[(nid, pin)])
        n = self.nodes[nid]
        s = self.sig(n)
        if n.kind == "Entry":
            return self.pinreg[(nid, pin)]
        if not s.pure:
            return self.persist((nid, pin), s.outs[pin])
        if nid not in memo:
            if nid in self.visiting:
                self.err("E0105", f"data cycle through %{nid}", where)
            self.visiting.add(nid)
            memo[nid] = self.eval_pure(n, s, memo, temps)
            self.visiting.discard(nid)
        return memo[nid][pin]

    def gather_ins(self, n, s, memo, temps):
        bound = dict(n.ins)
        regs = {}
        for pin, t in s.ins.items():
            src = bound.get(pin)
            if src is None:
                d = s.defaults.get(pin)
                src = ("lit", d) if d is not None else None
            regs[pin] = self.eval_src(src, t, memo, temps, n.id)
        return regs

    def eval_pure(self, n, s, memo, temps):
        saved = self.cur
        self.cur = n.id
        regs = self.gather_ins(n, s, memo, temps)
        k = n.kind
        if k == "GetLocal":
            self.cur = saved
            return {"value": self.localreg[targ(n, 0, "local")]}
        if k == "Reroute":
            self.cur = saved
            return {"value": regs["value"]}
        out = {p: self.tmp(t, temps) for p, t in s.outs.items()}
        self.lower(n, s, regs, out, temps)
        self.cur = saved
        return out

    # ---------------- lowering of one node to instructions
    def lower(self, n, s, a, o, temps):
        k = n.kind
        if k in BIN:
            self.emit(f"{BIN[k]}.{targ(n, 0)}", o["result"], a["a"], a["b"])
        elif k in BITBIN:
            self.emit(f"{BITBIN[k]}.{targ(n, 0)}", o["result"], a["a"], a["b"])
        elif k in UNARY:
            self.emit(f"{UNARY[k]}.{targ(n, 0)}", o["result"], a["a"])
        elif k == "BitNot":
            self.emit(f"NOT.{targ(n, 0)}", o["result"], a["a"])
        elif k in CMP:
            t = targ(n, 0)
            self.emit(f"STR.{CMP[k]}" if t == "string" else f"{CMP[k]}.{t}", o["result"], a["a"], a["b"])
        elif k in BOOLB:
            self.emit(f"{BOOLB[k]}.bool", o["result"], a["a"], a["b"])
        elif k == "Not":
            self.emit("NOT.bool", o["result"], a["a"])
        elif k == "Const":
            t = targ(n, 0)
            v = dict(n.props).get("value")
            if v is None:
                self.err("E0140", "Const needs a 'value' property", n.id)
            r = self.const(t, v, temps, n.id)
            self.emit("MOV", o["value"], r)
        elif k == "Convert":
            self.emit(f"CVT.{targ(n, 0)}.{targ(n, 1)}", o["result"], a["value"])
        elif k == "Select":
            self.emit("SELECT", o["result"], a["condition"], a["a"], a["b"])
        elif k == "Concat":
            self.emit("STR.CONCAT", o["result"], a["a"], a["b"])
        elif k == "StrLen":
            self.emit("STR.LEN", o["length"], a["text"])
        elif k == "GetVar":
            self.emit("GLOBAL.get", o["value"], self.ctx.globals[targ(n, 0, "sym")][1])
        elif k == "SetVar":
            self.emit("GLOBAL.set", self.ctx.globals[targ(n, 0, "sym")][1], a["value"])
        elif k == "GetState":
            self.emit("GLOBAL.get", o["value"], self.state_index(targ(n, 0, "local")))
        elif k == "SetState":
            self.emit("GLOBAL.set", self.state_index(targ(n, 0, "local")), a["value"])
        elif k == "SetLocal":
            self.emit("MOV", self.localreg[targ(n, 0, "local")], a["value"])
        elif k == "Call":
            name = targ(n, 0, "sym")
            fn = self.ctx.funcs[name]
            if fn["flags"] & F_LATENT and not self.info["flags"] & F_LATENT:
                self.err("E0201", f"latent function @{name} called from non-latent function {self.fname}", n.id)
            if not fn["flags"] & F_PURE:
                pass
            self.emit("CALL", fn["index"], [a[p] for p, _, _ in fn["params"]], [o[p] for p, _ in fn["results"]])
        elif k.startswith("Array"):
            t = targ(n, 0)
            ti = self.mod.types.add(("array", t))
            if k == "ArrayNew":
                self.emit("ARR.new", o["array"], ti)
            elif k == "ArrayLen":
                self.emit("ARR.len", o["length"], a["array"])
            elif k == "ArrayGet":
                self.emit("ARR.get", o["value"], a["array"], a["index"])
            elif k == "ArraySet":
                self.emit("ARR.set", a["array"], a["index"], a["value"])
            elif k == "ArrayPush":
                self.emit("ARR.push", a["array"], a["value"])
            elif k == "ArrayPop":
                self.emit("ARR.pop", o["value"], a["array"])
            elif k == "ArrayInsert":
                self.emit("ARR.insert", a["array"], a["index"], a["value"])
            elif k == "ArrayRemoveAt":
                self.emit("ARR.remove", a["array"], a["index"])
            elif k == "ArrayClear":
                self.emit("ARR.clear", a["array"])
            elif k == "ArrayClone":
                self.emit("ARR.clone", o["clone"], a["array"])
        else:
            self.err("E0002", f"node kind {k} is not supported by the reference compiler", n.id)

    def state_index(self, name):
        gname = f"{self.fname}${name}"
        for i, g in enumerate(self.mod.globals):
            if g[0] == gname:
                return i
        self.err("E0121", f"unknown state {name}")

    # ---------------- exec-flow emission
    def tkey(self, tgt, ctx):
        return ("$end", ctx) if tgt is None else (tgt[0], ctx)

    def resolve_end(self, ctx):
        while ctx:
            seq, i = ctx[-1]
            N = targ(self.nodes[seq], 0, "int")
            j = i + 1
            tgt = dict(self.nodes[seq].execs).get(f"then_{j}")
            ctx = ctx[:-1] if j == N - 1 else ctx[:-1] + ((seq, j),)
            if tgt is not None:
                return (tgt[0], ctx)
            if j == N - 1:
                continue
        return None

    def chain(self, nid, ctx):
        while True:
            key = (nid, ctx)
            if key in self.emitted:
                self.emit("JMP", ("fix", key))
                return
            self.emitted.add(key)
            self.labels[key] = len(self.f.instrs)
            if nid == "$end":
                self.cur = None
                r = self.resolve_end(ctx)
                if r is None:
                    if self.info["results"]:
                        self.err("E0301", "an execution path ends without reaching a Return node")
                    self.emit("RET", [])
                    return
                nid, ctx = r
                continue
            nxt = self.emit_node(nid, ctx)
            if nxt is None:
                return
            nid, ctx = nxt

    def push(self, key):
        if key not in self.emitted:
            self.pending.append(key)

    def emit_node(self, nid, ctx):
        n = self.nodes[nid]
        s = self.sig(n)
        self.cur = nid
        temps, memo = [], {}
        k = n.kind
        ex = dict(n.execs)

        def nxt(pin="then"):
            return self.tkey(ex.get(pin), ctx)
        if k == "Entry":
            return nxt()
        if k == "Return":
            regs = self.gather_ins(n, s, memo, temps)
            self.emit("RET", [regs[p.name] for p in self.fdecl.results])
            self.release(temps)
            return None
        if k == "Trap":
            msg = dict(n.props).get("message", ("str", "trap"))[1]
            self.emit("TRAP", self.mod.string(msg))
            return None
        if k == "Branch":
            r = self.gather_ins(n, s, memo, temps)["condition"]
            els = self.tkey(ex.get("else"), ctx)
            self.emit("JMPIFNOT", r, ("fix", els))
            self.push(els)
            self.release(temps)
            return nxt("then")
        if k == "Sequence":
            N = targ(n, 0, "int")
            if N < 1:
                self.err("E0141", "Sequence needs at least one output", nid)
            c2 = ctx + ((nid, 0),) if N > 1 else ctx
            if len(c2) > MAX_CTX:
                self.err("E0305", "Sequence nesting too deep (a Sequence re-enters itself)", nid)
            return self.tkey(ex.get("then_0"), c2)
        if k == "Switch":
            r = self.gather_ins(n, s, memo, temps)["value"]
            cases = dict(n.props).get("cases", ("list", []))[1]
            vals = [c[1] for c in cases]
            dflt = self.tkey(ex.get("default"), ctx)
            keys = [self.tkey(ex.get(f"case_{i}"), ctx) for i in range(len(vals))]
            if vals == list(range(len(vals))) and vals:
                self.emit("SWITCH", r, ([("fix", x) for x in keys], ("fix", dflt)))
            else:
                for v, kk in zip(vals, keys):
                    c = self.tmp("i32", temps); b = self.tmp("bool", temps)
                    self.emit("CONST.i32", c, v)
                    self.emit("EQ.i32", b, r, c)
                    self.emit("JMPIF", b, ("fix", kk))
                self.emit("JMP", ("fix", dflt))
            for x in keys + [dflt]:
                self.push(x)
            self.release(temps)
            return None
        if k == "$Bind":
            regs = []
            for (key, src, t) in n.binds:
                regs.append((self.persist(key, t), self.eval_src(src, t, memo, temps, nid)))
            dests = {d for d, _ in regs}
            for d, sr in regs:
                if sr in dests and sr != d:
                    t2 = self.tmp(self.f.regtypes[sr], temps)
                    self.emit("MOV", t2, sr)
                    regs = [(dd, t2 if ss == sr else ss) for dd, ss in regs]
            for d, sr in regs:
                if d != sr:
                    self.emit("MOV", d, sr)
            self.release(temps)
            return nxt()
        # ordinary impure node
        if s.pure:
            self.err("E0150", f"pure node %{nid} has an execution connection", nid)
        regs = self.gather_ins(n, s, memo, temps)
        out = {p: self.persist((nid, p), t) for p, t in s.outs.items()}
        if self.info["flags"] & F_PURE and k in ("SetVar", "SetState"):
            self.err("E0202", "a pure function cannot modify global state", nid)
        if self.info["flags"] & F_PURE and k == "Call" and not self.ctx.funcs[targ(n, 0, "sym")]["flags"] & F_PURE:
            self.err("E0202", "a pure function can only call pure functions", nid)
        self.lower(n, s, regs, out, temps)
        self.release(temps)
        return nxt()

    # ---------------- driver
    def compile(self):
        self.expand()
        self.validate()
        f = self.f
        for (name, t, _) in self.info["params"]:
            r = len(f.regtypes)
            f.regtypes.append(t)
            self.pinreg[(self.entry.id, name)] = r
            f.pins.append((r, self.entry.id, name))
        self.visiting = set()
        self.cur = self.entry.id
        temps = []
        for name, t in self.scope.locals.items():
            r = len(f.regtypes)
            f.regtypes.append(t)
            self.localreg[name] = r
            f.pins.append((r, "$" + name, "value"))
        for name, t in self.scope.locals.items():
            d = self.scope.local_init.get(name)
            r = self.localreg[name]
            if d is not None or t in NUM + ("bool", "string") or t.startswith("array<"):
                c = self.const(t, d if d is not None else type_default_lit(t), temps, self.entry.id)
                self.emit("MOV", r, c)
                self.release(temps)
        self.labels, self.emitted, self.pending = {}, set(), []
        self.pending.append((self.entry.id, ()))
        while self.pending:
            nid, ctx = self.pending.pop()
            if (nid, ctx) not in self.emitted:
                self.chain(nid, ctx)
        # resolve labels
        for ins in f.instrs:
            ins[1] = [self._fix(a) for a in ins[1]]
        return f

    def _fix(self, a):
        if isinstance(a, tuple) and len(a) == 2 and a[0] == "fix":
            return self.labels[a[1]]
        if isinstance(a, tuple) and len(a) == 2 and isinstance(a[0], list):
            return ([self._fix(x) for x in a[0]], self._fix(a[1]))
        return a


# ------------------------------------------------------------------ module driver
def compile_module(ast, name=None):
    ctx = Ctx(ast)
    mod = Module(name or ast.name or "module")
    warnings = []
    for v in ast.vars:
        init = None
        if v.default is not None:
            init = v.default[1]
        mod.globals.append((v.name, v.type, "const" not in v.attrs, init))
    hidden = []
    fcs = []
    for fname in ctx.fn_order:
        fc = FnCompiler(ctx, mod, ctx.funcs[fname]["decl"], hidden)
        fcs.append(fc)
    # macro state variables become hidden module globals; discover them by expanding first
    for fc in fcs:
        pre = FnCompiler(ctx, mod, fc.fdecl, hidden)
        pre.expand()
        for gname, t, d in hidden:
            if not any(g[0] == gname for g in mod.globals):
                mod.globals.append((gname, t, True, d[1] if d is not None else None))
    hidden.clear()
    for im_name, fn in sorted(((n, f) for n, f in ctx.funcs.items() if f["extern"]), key=lambda x: x[1]["index"]):
        mod_, field = fn["extern"]
        mod.imports.append((mod_, field, [t for _, t, _ in fn["params"]], [t for _, t in fn["results"]], fn["flags"], im_name))
    for fc in fcs:
        f = fc.compile()
        mod.funcs.append(f)
        warnings += [f"{fc.fname}: {w}" for w in fc.warnings]
        info = ctx.funcs[fc.fname]
        if fc.fdecl.kind == "event" or "export" in fc.fdecl.mods:
            mod.exports.append((fc.fname, info["index"]))
    # start function: allocate array/map/set globals
    needs = [(i, g) for i, g in enumerate(mod.globals) if g[1].startswith(("array<",))]
    if needs:
        f = Func("$init", [], [])
        f.cur = None
        for i, g in needs:
            r = len(f.regtypes)
            f.regtypes.append(g[1])
            f.instrs.append(["ARR.new", [r, mod.types.add(("array", type_head(g[1])[1][0]))]])
            f.instrs.append(["GLOBAL.set", [i, r]])
            f.nodes += [None, None]
        f.instrs.append(["RET", [[]]])
        f.nodes.append(None)
        mod.funcs.append(f)
        mod.start = ctx.nimports + len(mod.funcs) - 1
    return mod, warnings


def compile_text(text, name=None):
    ast = syntax.parse(text)
    return compile_module(ast, name)

```

---

`reference/wiret_ref/ops.py`

```py
"""Wiret bytecode opcode table (single source of truth for encoder, verifier, VM, docs).

Operand kinds in `spec`:
  r   register index (uleb)            s  signed immediate (sleb)
  u   unsigned immediate (uleb)        f32 / f64  raw little-endian float
  L   branch offset (sleb, relative to the first byte AFTER the instruction)
  str string-constant index (uleb)     fn function index (uleb)
  g   global index (uleb)              t  type index (uleb)
  vt  valtype encoding                 rl register list: count(uleb) then registers
  sw  switch table: n(uleb), n x L, default L
"""

OPS = {}      # name -> (code, spec tuple, doc)
BY_CODE = {}  # code -> name


def _op(name, code, spec, doc=""):
    assert code not in BY_CODE, (name, hex(code))
    assert name not in OPS, name
    OPS[name] = (code, tuple(spec.split()), doc)
    BY_CODE[code] = name


# ---- control -------------------------------------------------------------
_op("NOP", 0x00, "", "no operation")
_op("TRAP", 0x01, "str", "raise a runtime error with a constant message")
_op("JMP", 0x02, "L", "unconditional branch")
_op("JMPIF", 0x03, "r L", "branch if bool register is true")
_op("JMPIFNOT", 0x04, "r L", "branch if bool register is false")
_op("SWITCH", 0x05, "r sw", "jump table on an i32 register (0..n-1), else default")
_op("RET", 0x06, "rl", "return the listed registers (must match the result types)")
_op("CALL", 0x07, "fn rl rl", "call function: args list, result registers list")
_op("CALLV", 0x08, "t u rl rl", "virtual call: class type, vtable slot, args (receiver first), results")
_op("CALLI", 0x09, "t u rl rl", "interface call: interface type, method index, args (receiver first), results")
_op("CALLD", 0x0A, "r rl rl", "call through a delegate register")
_op("SPAWN", 0x0B, "fn rl", "start a new fiber running fn(args); results are discarded")
_op("YIELD", 0x0C, "", "end the current time slice; resume on the next scheduler step")
_op("BREAK", 0x0D, "", "debugger breakpoint (no effect without a hook)")

# ---- constants, moves, globals ----------------------------------------------
_op("MOV", 0x10, "r r", "dst = src (same type)")
_op("CONST.i32", 0x11, "r s")
_op("CONST.i64", 0x12, "r s")
_op("CONST.f32", 0x13, "r f32")
_op("CONST.f64", 0x14, "r f64")
_op("CONST.bool", 0x15, "r u")
_op("CONST.str", 0x16, "r str")
_op("CONST.null", 0x17, "r", "dst = null (any nullable reference register) / default struct")
_op("GLOBAL.get", 0x18, "r g")
_op("GLOBAL.set", 0x19, "g r")

# ---- numeric families ------------------------------------------------------
_ARITH = ["ADD", "SUB", "MUL", "DIV", "REM", "NEG", "EQ", "NE", "LT", "LE", "GT", "GE",
          "MIN", "MAX", "ABS", "SQRT"]
_INTX = ["AND", "OR", "XOR", "SHL", "SHR", "NOT"]
NUM_BASE = {"i32": 0x20, "i64": 0x40, "f32": 0x60, "f64": 0x70}
UNARY = {"NEG", "ABS", "SQRT", "NOT"}
CMP = {"EQ", "NE", "LT", "LE", "GT", "GE"}
for _ty, _base in NUM_BASE.items():
    for _i, _n in enumerate(_ARITH):
        if _n == "SQRT" and _ty in ("i32", "i64"):
            continue
        _op(f"{_n}.{_ty}", _base + _i, "r r" if _n in UNARY else "r r r")
    if _ty in ("i32", "i64"):
        for _i, _n in enumerate(_INTX):
            _op(f"{_n}.{_ty}", _base + 16 + _i, "r r" if _n in UNARY else "r r r")

for _i, _n in enumerate(["AND", "OR", "XOR", "NOT", "EQ", "NE"]):
    _op(f"{_n}.bool", 0x80 + _i, "r r" if _n == "NOT" else "r r r")

# ---- conversions -----------------------------------------------------------
CVT = [("i32", "i64"), ("i64", "i32"), ("i32", "f32"), ("i32", "f64"), ("i64", "f32"),
       ("i64", "f64"), ("f32", "i32"), ("f32", "i64"), ("f64", "i32"), ("f64", "i64"),
       ("f32", "f64"), ("f64", "f32"), ("bool", "i32"), ("i32", "bool"), ("i32", "string"),
       ("i64", "string"), ("f32", "string"), ("f64", "string"), ("bool", "string")]
for _i, (_a, _b) in enumerate(CVT):
    _op(f"CVT.{_a}.{_b}", 0x88 + _i, "r r")

# ---- strings / select --------------------------------------------------------
_op("STR.CONCAT", 0xA0, "r r r")
_op("STR.LEN", 0xA1, "r r", "length in UTF-8 bytes")
for _i, _n in enumerate(["EQ", "NE", "LT", "LE", "GT", "GE"]):
    _op(f"STR.{_n}", 0xA2 + _i, "r r r", "ordinal byte-wise comparison")
_op("SELECT", 0xA8, "r r r r", "dst = cond ? a : b")

# ---- structs (immutable value types) ------------------------------------------
_op("STRUCT.new", 0xB0, "r t rl")
_op("STRUCT.get", 0xB1, "r r u")
_op("STRUCT.with", 0xB2, "r r u r", "dst = copy of src with one field replaced")

# ---- objects ---------------------------------------------------------------
_op("OBJ.new", 0xB8, "r t")
_op("FIELD.get", 0xB9, "r r u")
_op("FIELD.set", 0xBA, "r u r")
_op("IS.inst", 0xBB, "r r t")
_op("CAST", 0xBC, "r r t", "checked cast; traps on failure")
_op("CAST.try", 0xBD, "r r t", "dst = src if instance else null")
_op("REF.eq", 0xBE, "r r r")
_op("REF.isnull", 0xBF, "r r")

# ---- arrays ----------------------------------------------------------------
_op("ARR.new", 0xC0, "r t")
_op("ARR.len", 0xC1, "r r")
_op("ARR.get", 0xC2, "r r r")
_op("ARR.set", 0xC3, "r r r")
_op("ARR.push", 0xC4, "r r")
_op("ARR.insert", 0xC5, "r r r")
_op("ARR.remove", 0xC6, "r r")
_op("ARR.clear", 0xC7, "r")
_op("ARR.clone", 0xC8, "r r")
_op("ARR.pop", 0xC9, "r r")

# ---- maps and sets (insertion-ordered) ---------------------------------------
_op("MAP.new", 0xCC, "r t")
_op("MAP.len", 0xCD, "r r")
_op("MAP.get", 0xCE, "r r r", "traps if key missing")
_op("MAP.tryget", 0xCF, "r r r r", "dst, found, map, key")
_op("MAP.set", 0xD0, "r r r")
_op("MAP.has", 0xD1, "r r r")
_op("MAP.remove", 0xD2, "r r r", "dst(bool removed), map, key")
_op("MAP.keyat", 0xD3, "r r r")
_op("MAP.valat", 0xD4, "r r r")
_op("MAP.clear", 0xD5, "r")
_op("SET.new", 0xD6, "r t")
_op("SET.len", 0xD7, "r r")
_op("SET.add", 0xD8, "r r r", "dst(bool added), set, value")
_op("SET.has", 0xD9, "r r r")
_op("SET.remove", 0xDA, "r r r")
_op("SET.at", 0xDB, "r r r")
_op("SET.clear", 0xDC, "r")

# ---- any / boxing ----------------------------------------------------------
_op("ANY.box", 0xDE, "r r")
_op("ANY.unbox", 0xDF, "r r vt", "traps on type mismatch")
_op("ANY.tryunbox", 0xE0, "r r r vt", "dst, ok, any")
_op("ANY.is", 0xE1, "r r vt")

# ---- delegates / dispatchers ---------------------------------------------------
_op("DELG.new", 0xE4, "r t fn u", "dst, delegate type, function, target register + 1 (0 = unbound)")
_op("DISP.new", 0xE6, "r t")
_op("DISP.bind", 0xE7, "r r")
_op("DISP.unbind", 0xE8, "r r")
_op("DISP.broadcast", 0xE9, "r rl")
_op("DISP.clear", 0xEA, "r")
_op("DISP.count", 0xEB, "r r")

# Reference-implementation coverage (VM executes these; others are verified structurally only)
REF_IMPL_PREFIXES = ("NOP", "TRAP", "JMP", "SWITCH", "RET", "CALL", "MOV", "CONST", "GLOBAL",
                     "ADD", "SUB", "MUL", "DIV", "REM", "NEG", "EQ", "NE", "LT", "LE", "GT", "GE",
                     "MIN", "MAX", "ABS", "SQRT", "AND", "OR", "XOR", "SHL", "SHR", "NOT",
                     "CVT", "STR.", "SELECT", "ARR.", "BREAK", "YIELD")


def ref_impl(name):
    return name.startswith(REF_IMPL_PREFIXES) and name != "CALLV" and name != "CALLI" and name != "CALLD"

```

---

`reference/wiret_ref/render.py`

```py
"""Render a function graph to SVG using the file's own layout block (what every editor would show)."""
from html import escape
from . import syntax
from .compiler import Ctx, Scope, sig_of, CompileError, Sig

W, HEAD, ROW, PAD = 200, 28, 22, 8
TYPE_COL = {"i32": "#4fc3a1", "i64": "#2fa37f", "f32": "#9fd356", "f64": "#7fb83a", "bool": "#d9534f",
            "string": "#e27fd9", "any": "#9aa0a6"}
CATS = [("Entry", "#c0392b"), ("Return", "#c0392b"), ("Exit", "#c0392b"), ("Branch", "#7f8c8d"), ("Sequence", "#7f8c8d"),
        ("Switch", "#7f8c8d"), ("Call", "#3b7dd8"), ("Set", "#d98c2f"), ("Get", "#4f9d69"), ("Array", "#8e6bbf")]


def _color(t):
    if t in TYPE_COL:
        return TYPE_COL[t]
    if t.startswith("array"):
        return "#8e6bbf"
    return "#b0b7c3"


def _head_color(kind, pure):
    for p, c in CATS:
        if kind.startswith(p):
            return c
    return "#4f9d69" if pure else "#5c6b7a"


def _title(n):
    t = n.kind
    if n.targs:
        a = []
        for k, v in n.targs:
            a.append("@" + v if k == "sym" else "$" + v if k == "local" else str(v))
        t += "<" + ",".join(a) + ">"
    return t


def render_function(ctx, f, title=None):
    scope = Scope(f)
    pos = {it[1]: it[2] for it in f.layout if it[0] == "node"}
    boxes = [it for it in f.layout if it[0] == "box"]
    info = {}
    for n in f.nodes:
        try:
            s = sig_of(n, ctx, scope)
        except CompileError:
            s = Sig()
        left = [("x", p) for p in s.xin] + [("d", p, t) for p, t in s.ins.items()]
        right = [("x", p) for p in s.xout] + [("d", p, t) for p, t in s.outs.items()]
        rows = max(len(left), len(right), 1)
        x, y = pos.get(n.id, (0, 0))
        info[n.id] = dict(n=n, s=s, left=left, right=right, x=x, y=y, h=HEAD + rows * ROW + PAD)
    minx = min([i["x"] for i in info.values()] + [b[2][0] for b in boxes] + [0]) - 40
    miny = min([i["y"] for i in info.values()] + [b[2][1] for b in boxes] + [0]) - 40
    maxx = max([i["x"] + W for i in info.values()] + [b[2][0] + b[3][0] for b in boxes] + [W]) + 40
    maxy = max([i["y"] + i["h"] for i in info.values()] + [b[2][1] + b[3][1] for b in boxes] + [100]) + 40

    def pin_xy(nid, side, name, kind):
        i = info[nid]
        lst = i["left"] if side == "L" else i["right"]
        for idx, it in enumerate(lst):
            if it[0] == kind and it[1] == name:
                return (i["x"] if side == "L" else i["x"] + W, i["y"] + HEAD + idx * ROW + ROW / 2)
        return None
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{minx} {miny} {maxx - minx} {maxy - miny}" '
           f'width="{maxx - minx}" height="{maxy - miny}" font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="11">',
           f'<rect x="{minx}" y="{miny}" width="{maxx - minx}" height="{maxy - miny}" fill="#1b1e24"/>']
    for b in boxes:
        col = b[4].get("color", ("color", "#3a5f8a"))[1]
        (x, y), (w, h) = b[2], b[3]
        out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{col}" fill-opacity="0.16" stroke="{col}" stroke-opacity="0.6"/>')
        out.append(f'<text x="{x + 10}" y="{y + 18}" fill="{col}" font-size="13" font-weight="600">{escape(b[1])}</text>')
    edges = []
    for nid, i in info.items():
        n = i["n"]
        for pin, (tn, tp) in n.execs:
            if tn not in info:
                continue
            a = pin_xy(nid, "R", pin, "x")
            tgt = info[tn]
            tpn = tp or (tgt["s"].xin[0] if tgt["s"].xin else "in")
            b = pin_xy(tn, "L", tpn, "x")
            if a and b:
                edges.append((a, b, "#f2f2f2", 2.6))
        for pin, src in n.ins:
            if src[0] != "ref" or src[1] not in info:
                continue
            a = pin_xy(src[1], "R", src[2], "d")
            b = pin_xy(nid, "L", pin, "d")
            t = info[src[1]]["s"].outs.get(src[2], "?")
            if a and b:
                edges.append((a, b, _color(t), 1.6))
    for (a, b, c, w) in sorted(edges, key=lambda e: e[3]):
        dx = max(40, abs(b[0] - a[0]) * 0.5)
        out.append(f'<path d="M{a[0]:.1f},{a[1]:.1f} C{a[0] + dx:.1f},{a[1]:.1f} {b[0] - dx:.1f},{b[1]:.1f} {b[0]:.1f},{b[1]:.1f}" '
                   f'fill="none" stroke="{c}" stroke-width="{w}" stroke-linecap="round"/>')
    for nid, i in info.items():
        n, s, x, y, h = i["n"], i["s"], i["x"], i["y"], i["h"]
        hc = _head_color(n.kind, s.pure)
        out.append(f'<rect x="{x}" y="{y}" width="{W}" height="{h}" rx="7" fill="#2a2e37" stroke="#434a57"/>')
        out.append(f'<path d="M{x},{y + 7} a7,7 0 0 1 7,-7 h{W - 14} a7,7 0 0 1 7,7 v{HEAD - 7} h-{W} z" fill="{hc}" fill-opacity="0.85"/>')
        out.append(f'<text x="{x + 10}" y="{y + 18}" fill="#fff" font-weight="600">{escape(_title(n))}</text>')
        bound = dict(n.ins)
        for side, lst in (("L", i["left"]), ("R", i["right"])):
            for idx, it in enumerate(lst):
                cy = y + HEAD + idx * ROW + ROW / 2
                cx = x if side == "L" else x + W
                if it[0] == "x":
                    out.append(f'<path d="M{cx - 5},{cy - 6} h6 l5,6 l-5,6 h-6 z" fill="#f2f2f2"/>')
                    lx = cx + 12 if side == "L" else cx - 12
                    if it[1] in ("in", "then") and len(lst) and False:
                        continue
                    out.append(f'<text x="{lx}" y="{cy + 4}" fill="#d6dae0" text-anchor="{"start" if side == "L" else "end"}">{escape(it[1])}</text>')
                else:
                    col = _color(it[2])
                    connected = it[1] in bound and bound[it[1]][0] == "ref" if side == "L" else True
                    out.append(f'<circle cx="{cx}" cy="{cy}" r="5" fill="{col if connected else "#1b1e24"}" stroke="{col}" stroke-width="1.6"/>')
                    label = it[1]
                    if side == "L" and it[1] in bound and bound[it[1]][0] == "lit":
                        label += " = " + syntax.fmt_lit(bound[it[1]][1])
                    lx = cx + 12 if side == "L" else cx - 12
                    out.append(f'<text x="{lx}" y="{cy + 4}" fill="#d6dae0" text-anchor="{"start" if side == "L" else "end"}">{escape(label)}</text>')
    out.append("</svg>")
    return "\n".join(out)


def render_module(ast, fname):
    ctx = Ctx(ast)
    for f in ast.funcs:
        if f.name == fname:
            return render_function(ctx, f)
    raise KeyError(fname)

```

---

`reference/wiret_ref/stdlib.py`

```py
"""Built-in Wiret libraries (written in Wiret itself)."""

STD_FLOW = r'''wiret 0.1

module "std.flow"

macro ForLoop(exec in, first: i32 = 0, last: i32 = 0) -> (exec body, index: i32, exec completed) {
  meta doc = "Runs body once for each index from first to last (inclusive), then completed."
  local $i: i32
  graph {
    node %entry : Entry {
      exec in -> %init
    }
    node %init : SetLocal<$i> {
      in value = %entry.first
      exec then -> %check
    }
    node %get_i : GetLocal<$i> {}
    node %le : Le<i32> {
      in a = %get_i.value
      in b = %entry.last
    }
    node %check : Branch {
      in condition = %le.result
      exec then -> %seq
      exec else -> %exit.completed
    }
    node %seq : Sequence<2> {
      exec then_0 -> %exit.body
      exec then_1 -> %step
    }
    node %inc : Add<i32> {
      in a = %get_i.value
      in b = 1
    }
    node %step : SetLocal<$i> {
      in value = %inc.result
      exec then -> %check
    }
    node %exit : Exit {
      in index = %get_i.value
    }
  }
}

macro ForEach<T>(exec in, items: array<T>) -> (exec body, element: T, index: i32, exec completed) {
  meta doc = "Runs body once per element of items, in order, then completed."
  local $i: i32
  graph {
    node %entry : Entry {
      exec in -> %init
    }
    node %init : SetLocal<$i> {
      in value = 0
      exec then -> %check
    }
    node %get_i : GetLocal<$i> {}
    node %len : ArrayLen<T> {
      in array = %entry.items
    }
    node %lt : Lt<i32> {
      in a = %get_i.value
      in b = %len.length
    }
    node %check : Branch {
      in condition = %lt.result
      exec then -> %seq
      exec else -> %exit.completed
    }
    node %item : ArrayGet<T> {
      in array = %entry.items
      in index = %get_i.value
    }
    node %seq : Sequence<2> {
      exec then_0 -> %exit.body
      exec then_1 -> %step
    }
    node %inc : Add<i32> {
      in a = %get_i.value
      in b = 1
    }
    node %step : SetLocal<$i> {
      in value = %inc.result
      exec then -> %check
    }
    node %exit : Exit {
      in element = %item.value
      in index = %get_i.value
    }
  }
}

macro DoOnce(exec in, exec reset) -> (exec completed) {
  meta doc = "Lets execution through the first time only, until reset is triggered."
  state $done: bool = false
  graph {
    node %entry : Entry {
      exec in -> %check
      exec reset -> %clear
    }
    node %get_done : GetState<$done> {}
    node %check : Branch {
      in condition = %get_done.value
      exec else -> %mark
    }
    node %mark : SetState<$done> {
      in value = true
      exec then -> %exit.completed
    }
    node %clear : SetState<$done> {
      in value = false
    }
    node %exit : Exit {}
  }
}

macro DoN(exec in, exec reset, n: i32 = 1) -> (exec completed) {
  meta doc = "Lets execution through at most n times, until reset is triggered."
  state $count: i32 = 0
  graph {
    node %entry : Entry {
      exec in -> %check
      exec reset -> %clear
    }
    node %get_count : GetState<$count> {}
    node %lt : Lt<i32> {
      in a = %get_count.value
      in b = %entry.n
    }
    node %check : Branch {
      in condition = %lt.result
      exec then -> %bump
    }
    node %inc : Add<i32> {
      in a = %get_count.value
      in b = 1
    }
    node %bump : SetState<$count> {
      in value = %inc.result
      exec then -> %exit.completed
    }
    node %clear : SetState<$count> {
      in value = 0
    }
    node %exit : Exit {}
  }
}
'''

LIBS = {"std.flow": STD_FLOW}

```

---

`reference/wiret_ref/syntax.py`

```py
"""Wiret text format: lexer, parser, canonical formatter."""
import re


class SyntaxErr(Exception):
    def __init__(self, msg, line=0):
        super().__init__(f"line {line}: {msg}" if line else msg)
        self.line = line


# ------------------------------------------------------------------ lexer
_NUM = re.compile(r"-?(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)")
_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SYM = re.compile(r"@[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
_COL = re.compile(r"#[0-9a-fA-F]{3,8}")
_ESC = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "0": "\0"}


def lex(src):
    toks, i, line, n = [], 0, 1, len(src)
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1; i += 1; continue
        if c in " \t\r":
            i += 1; continue
        if c == ";":
            while i < n and src[i] != "\n":
                i += 1
            continue
        if src.startswith("->", i):
            toks.append(("p", "->", line, "->")); i += 2; continue
        if c == "%" or c == "$":
            m = _ID.match(src, i + 1)
            if not m:
                raise SyntaxErr(f"bad identifier after {c!r}", line)
            toks.append(("node" if c == "%" else "local", m.group(), line, c + m.group())); i = m.end(); continue
        if c == "@":
            m = _SYM.match(src, i)
            if not m:
                raise SyntaxErr("bad symbol reference", line)
            toks.append(("sym", m.group()[1:], line, m.group())); i = m.end(); continue
        if c == "#":
            m = _COL.match(src, i)
            if not m:
                raise SyntaxErr("bad color literal", line)
            toks.append(("color", m.group().lower(), line, m.group())); i = m.end(); continue
        if c == '"':
            j, out = i + 1, []
            while True:
                if j >= n:
                    raise SyntaxErr("unterminated string", line)
                ch = src[j]
                if ch == '"':
                    break
                if ch == "\n":
                    raise SyntaxErr("newline in string", line)
                if ch == "\\":
                    j += 1
                    e = src[j]
                    if e == "u":
                        m = re.compile(r"\{([0-9a-fA-F]+)\}").match(src, j + 1)
                        if not m:
                            raise SyntaxErr("bad \\u escape", line)
                        out.append(chr(int(m.group(1), 16))); j = m.end(); continue
                    if e not in _ESC:
                        raise SyntaxErr(f"bad escape \\{e}", line)
                    out.append(_ESC[e]); j += 1; continue
                out.append(ch); j += 1
            toks.append(("str", "".join(out), line, src[i:j + 1])); i = j + 1; continue
        if src.startswith("-inf", i) and not _ID.match(src, i + 4):
            toks.append(("float", float("-inf"), line, "-inf")); i += 4; continue
        if c.isdigit() or (c == "-" and i + 1 < n and src[i + 1].isdigit()):
            m = _NUM.match(src, i)
            t = m.group()
            if re.search(r"[.eE]", t) and not t.lower().lstrip("-").startswith("0x"):
                toks.append(("float", float(t), line, t))
            else:
                toks.append(("int", int(t, 0) if "x" in t.lower() else int(t), line, t))
            i = m.end(); continue
        m = _ID.match(src, i)
        if m:
            toks.append(("id", m.group(), line, m.group())); i = m.end(); continue
        if c in "{}()[]<>,:=.":
            toks.append(("p", c, line, c)); i += 1; continue
        raise SyntaxErr(f"unexpected character {c!r}", line)
    toks.append(("eof", None, line, ""))
    return toks


# ------------------------------------------------------------------ AST
class Pin:
    def __init__(self, name, type, default=None, attrs=None):
        self.name, self.type, self.default, self.attrs = name, type, default, attrs or {}


class Node:
    def __init__(self, id, kind, targs=None):
        self.id, self.kind, self.targs = id, kind, targs or []
        self.ins, self.execs, self.props, self.meta = [], [], [], []   # lists of tuples for stable order

    def clone(self):
        n = Node(self.id, self.kind, list(self.targs))
        n.ins, n.execs = list(self.ins), list(self.execs)
        n.props, n.meta = list(self.props), list(self.meta)
        return n


class Func:
    def __init__(self, name, kind="function"):
        self.name, self.kind = name, kind          # kind: function | event | macro
        self.mods, self.tparams = set(), []
        self.params, self.results = [], []         # [Pin]
        self.meta, self.locals, self.states = [], [], []
        self.nodes = []                            # [Node] in file order
        self.layout = []
        self.has_body = False
        self.line = 0


class Module:
    def __init__(self):
        self.version = None
        self.name = None
        self.meta, self.uses, self.externs, self.enums = [], [], [], []
        self.structs, self.classes, self.ifaces, self.delegates = [], [], [], []
        self.vars, self.funcs = [], []             # funcs include macros
        self.order = []                            # declaration order for the formatter


# ------------------------------------------------------------------ parser
class Parser:
    def __init__(self, src):
        self.t = lex(src)
        self.i = 0

    # token helpers
    def peek(self, k=0):
        return self.t[min(self.i + k, len(self.t) - 1)]

    def next(self):
        t = self.t[self.i]
        self.i += 1
        return t

    def err(self, msg):
        raise SyntaxErr(msg, self.peek()[2])

    def is_p(self, v, k=0):
        t = self.peek(k)
        return t[0] == "p" and t[1] == v

    def is_id(self, v=None, k=0):
        t = self.peek(k)
        return t[0] == "id" and (v is None or t[1] == v)

    def accept_p(self, v):
        if self.is_p(v):
            self.i += 1
            return True
        return False

    def expect_p(self, v):
        if not self.accept_p(v):
            self.err(f"expected {v!r}, found {self.peek()[3]!r}")

    def expect_id(self, v=None):
        t = self.peek()
        if t[0] != "id" or (v is not None and t[1] != v):
            self.err(f"expected {v or 'identifier'}, found {t[3]!r}")
        self.i += 1
        return t[1]

    def expect_kind(self, k, what):
        t = self.peek()
        if t[0] != k:
            self.err(f"expected {what}, found {t[3]!r}")
        self.i += 1
        return t[1]

    # types
    def type(self):
        name = self.expect_id()
        while self.is_p(".") and self.peek(1)[0] == "id":
            self.i += 1
            name += "." + self.expect_id()
        if self.accept_p("<"):
            args = [self.type()]
            while self.accept_p(","):
                args.append(self.type())
            self.expect_p(">")
            name += "<" + ",".join(args) + ">"
        return name

    # literals / values
    def literal(self):
        t = self.peek()
        k = t[0]
        if k == "int":
            self.i += 1; return ("int", t[1])
        if k == "float":
            self.i += 1; return ("float", t[1])
        if k == "str":
            self.i += 1; return ("str", t[1])
        if k == "color":
            self.i += 1; return ("color", t[1])
        if k == "p" and t[1] == "[":
            self.i += 1
            items = []
            while not self.is_p("]"):
                items.append(self.literal())
                if not self.accept_p(","):
                    break
            self.expect_p("]")
            return ("list", items)
        if k == "p" and t[1] == "{":
            self.i += 1
            fields = []
            while not self.is_p("}"):
                n = self.expect_id()
                self.expect_p(":")
                fields.append((n, self.literal()))
                if not self.accept_p(","):
                    break
            self.expect_p("}")
            return ("struct", fields)
        if k == "id":
            v = t[1]
            if v in ("true", "false"):
                self.i += 1; return ("bool", v == "true")
            if v == "null":
                self.i += 1; return ("null",)
            if v == "inf":
                self.i += 1; return ("float", float("inf"))
            if v == "nan":
                self.i += 1; return ("float", float("nan"))
            self.i += 1
            if self.is_p(".") and self.peek(1)[0] == "id":
                self.i += 1
                return ("enum", v, self.expect_id())
            return ("ident", v)
        self.err(f"expected a value, found {t[3]!r}")

    def attrs(self):
        out = {}
        if self.accept_p("["):
            while not self.is_p("]"):
                k = self.expect_id()
                self.expect_p("=")
                out[k] = self.literal()
                if not self.accept_p(","):
                    break
            self.expect_p("]")
        return out

    # pin lists
    def pins(self, allow_exec):
        pins = []
        self.expect_p("(")
        while not self.is_p(")"):
            if allow_exec and self.is_id("exec"):
                self.i += 1
                pins.append(Pin(self.expect_id(), "exec"))
            else:
                n = self.expect_id()
                self.expect_p(":")
                ty = self.type()
                d = self.literal() if self.accept_p("=") else None
                pins.append(Pin(n, ty, d, self.attrs()))
            if not self.accept_p(","):
                break
        self.expect_p(")")
        return pins

    # declarations
    def parse(self):
        m = Module()
        self.expect_id("wiret")
        v = self.next()
        if v[0] not in ("float", "int"):
            raise SyntaxErr("expected format version after 'wiret'", v[2])
        m.version = v[3]
        while self.peek()[0] != "eof":
            self.top(m)
        return m

    def top(self, m):
        mods = set()
        while self.is_id() and self.peek()[1] in ("export", "pure", "latent") and not self.is_p(":", 1):
            mods.add(self.next()[1])
        t = self.peek()
        if t[0] != "id":
            self.err(f"unexpected {t[3]!r} at top level")
        kw = t[1]
        if kw == "module":
            self.i += 1; m.name = self.expect_kind("str", "module name")
        elif kw == "meta":
            self.i += 1
            k = self.expect_id(); self.expect_p("="); m.meta.append((k, self.literal()))
        elif kw == "use":
            self.i += 1
            path = self.expect_kind("str", "module path"); self.expect_id("as")
            m.uses.append((path, self.expect_id()))
        elif kw == "extern":
            self.i += 1
            what = self.expect_id()
            if what == "type":
                n = self.expect_id(); self.expect_p("="); m.externs.append(("type", n, self.expect_kind("str", "host type name"), None, None, set()))
            elif what == "function":
                n = self.expect_id(); self.expect_p("=")
                target = self.expect_kind("str", "native name")
                ps = self.pins(False)
                rs = self.pins(False) if self.accept_p("->") else []
                m.externs.append(("function", n, target, ps, rs, mods))
            else:
                self.err("expected 'type' or 'function' after extern")
        elif kw == "enum":
            self.i += 1
            n = self.expect_id(); under = "i32"
            self.expect_p("{")
            members, nxt = [], 0
            while not self.is_p("}"):
                mn = self.expect_id()
                if self.accept_p("="):
                    nxt = self.expect_kind("int", "enum value")
                members.append((mn, nxt, self.attrs()))
                nxt += 1
                if not self.accept_p(","):
                    break
            self.expect_p("}")
            m.enums.append((n, members))
        elif kw == "struct":
            self.i += 1
            n = self.expect_id(); self.expect_p("{")
            fields = []
            while not self.is_p("}"):
                fn = self.expect_id(); self.expect_p(":")
                ty = self.type()
                d = self.literal() if self.accept_p("=") else None
                fields.append(Pin(fn, ty, d, self.attrs()))
                if not self.accept_p(","):
                    break
            self.expect_p("}")
            m.structs.append((n, fields))
        elif kw == "delegate":
            self.i += 1
            n = self.expect_id(); ps = self.pins(False)
            rs = self.pins(False) if self.accept_p("->") else []
            m.delegates.append((n, ps, rs))
        elif kw == "interface":
            self.i += 1
            n = self.expect_id(); self.expect_p("{")
            meths = []
            while not self.is_p("}"):
                meths.append(self.func(set()))
            self.expect_p("}")
            m.ifaces.append((n, meths))
        elif kw == "class":
            self.i += 1
            n = self.expect_id()
            bases = []
            if self.accept_p(":"):
                bases.append(self.type())
                while self.accept_p(","):
                    bases.append(self.type())
            self.expect_p("{")
            meta, fields, meths = [], [], []
            while not self.is_p("}"):
                cm = set()
                while self.is_id() and self.peek()[1] in ("export", "pure", "latent"):
                    cm.add(self.next()[1])
                if self.is_id("var"):
                    fields.append(self.var())
                elif self.is_id("meta"):
                    self.i += 1
                    k = self.expect_id(); self.expect_p("="); meta.append((k, self.literal()))
                else:
                    meths.append(self.func(cm))
            self.expect_p("}")
            m.classes.append((n, bases, meta, fields, meths))
        elif kw in ("var", "const"):
            v = self.var()
            if kw == "const":
                v.attrs["const"] = ("bool", True)
            m.vars.append(v)
        elif kw in ("function", "event", "macro"):
            m.funcs.append(self.func(mods))
        else:
            self.err(f"unknown declaration {kw!r}")

    def var(self):
        self.i += 1
        n = self.expect_id(); self.expect_p(":")
        ty = self.type()
        d = self.literal() if self.accept_p("=") else None
        return Pin(n, ty, d, self.attrs())

    def func(self, mods):
        mods = set(mods)
        while self.is_id() and self.peek()[1] in ("export", "pure", "latent"):
            mods.add(self.next()[1])
        line = self.peek()[2]
        kind = self.expect_id()
        if kind not in ("function", "event", "macro"):
            self.err(f"expected function, event or macro, found {kind!r}")
        f = Func(self.expect_id(), kind)
        f.mods, f.line = mods, line
        if kind == "macro" and self.accept_p("<"):
            f.tparams.append(self.expect_id())
            while self.accept_p(","):
                f.tparams.append(self.expect_id())
            self.expect_p(">")
        f.params = self.pins(kind == "macro")
        if self.accept_p("->"):
            f.results = self.pins(kind == "macro")
        if self.accept_p("{"):
            f.has_body = True
            while not self.is_p("}"):
                kw = self.expect_id()
                if kw == "meta":
                    k = self.expect_id(); self.expect_p("="); f.meta.append((k, self.literal()))
                elif kw == "local":
                    t = self.expect_kind("local", "$name"); self.expect_p(":")
                    ty = self.type()
                    d = self.literal() if self.accept_p("=") else None
                    f.locals.append(Pin(t, ty, d, self.attrs()))
                elif kw == "state":
                    t = self.expect_kind("local", "$name"); self.expect_p(":")
                    ty = self.type()
                    d = self.literal() if self.accept_p("=") else None
                    f.states.append(Pin(t, ty, d, self.attrs()))
                elif kw == "graph":
                    self.expect_p("{")
                    while not self.is_p("}"):
                        f.nodes.append(self.node())
                    self.expect_p("}")
                elif kw == "layout":
                    self.expect_p("{")
                    while not self.is_p("}"):
                        f.layout.append(self.layout_item())
                    self.expect_p("}")
                else:
                    self.i -= 1
                    self.err(f"unexpected {kw!r} in function body")
            self.expect_p("}")
        return f

    def node(self):
        self.expect_id("node")
        nid = self.expect_kind("node", "node id (%name)")
        self.expect_p(":")
        kind = self.expect_id()
        while self.is_p(".") and self.peek(1)[0] == "id":
            self.i += 1
            kind += "." + self.expect_id()
        targs = []
        if self.accept_p("<"):
            while True:
                t = self.peek()
                if t[0] == "sym":
                    self.i += 1; targs.append(("sym", t[1]))
                elif t[0] == "local":
                    self.i += 1; targs.append(("local", t[1]))
                elif t[0] in ("int", "str"):
                    self.i += 1; targs.append((t[0], t[1]))
                else:
                    targs.append(("type", self.type()))
                if not self.accept_p(","):
                    break
            self.expect_p(">")
        n = Node(nid, kind, targs)
        self.expect_p("{")
        while not self.is_p("}"):
            kw = self.expect_id()
            if kw == "in":
                pin = self.expect_id(); self.expect_p("=")
                if self.peek()[0] == "node":
                    src = ("ref", self.next()[1], (self.expect_p(".") or self.expect_id()))
                else:
                    src = ("lit", self.literal())
                n.ins.append((pin, src))
            elif kw == "exec":
                pin = self.expect_id(); self.expect_p("->")
                tn = self.expect_kind("node", "node id")
                tp = None
                if self.accept_p("."):
                    tp = self.expect_id()
                n.execs.append((pin, (tn, tp)))
            elif kw == "prop":
                k = self.expect_id(); self.expect_p("="); n.props.append((k, self.literal()))
            elif kw == "meta":
                k = self.expect_id(); self.expect_p("="); n.meta.append((k, self.literal()))
            else:
                self.i -= 1
                self.err(f"unexpected {kw!r} in node (expected in, exec, prop or meta)")
        self.expect_p("}")
        return n

    def layout_item(self):
        t = self.peek()
        if t[0] == "node":
            self.i += 1
            self.expect_id("at")
            pos = self.point()
            return ("node", t[1], pos, self.attrs())
        kw = self.expect_id()
        if kw == "box":
            title = self.expect_kind("str", "box title")
            self.expect_id("at"); pos = self.point()
            self.expect_id("size"); size = self.point()
            return ("box", title, pos, size, self.attrs())
        self.i -= 1
        self.err("expected %node or 'box' in layout")

    def point(self):
        self.expect_p("(")
        x = self.expect_kind("int", "integer")
        self.expect_p(",")
        y = self.expect_kind("int", "integer")
        self.expect_p(")")
        return (x, y)


def parse(src):
    return Parser(src).parse()


# ------------------------------------------------------------------ formatter
def fmt_lit(l):
    k = l[0]
    if k == "int":
        return str(l[1])
    if k == "float":
        v = l[1]
        if v != v:
            return "nan"
        if v in (float("inf"), float("-inf")):
            return "inf" if v > 0 else "-inf"
        s = repr(v)
        return s if any(c in s for c in ".en") else s + ".0"
    if k == "str":
        return fmt_str(l[1])
    if k == "bool":
        return "true" if l[1] else "false"
    if k == "null":
        return "null"
    if k == "color" or k == "ident":
        return l[1]
    if k == "enum":
        return f"{l[1]}.{l[2]}"
    if k == "list":
        return "[" + ", ".join(fmt_lit(x) for x in l[1]) + "]"
    if k == "struct":
        return "{" + ", ".join(f"{n}: {fmt_lit(v)}" for n, v in l[1]) + "}"
    raise ValueError(k)


def fmt_str(s):
    out = ['"']
    for ch in s:
        if ch == '"': out.append('\\"')
        elif ch == "\\": out.append("\\\\")
        elif ch == "\n": out.append("\\n")
        elif ch == "\t": out.append("\\t")
        elif ch == "\r": out.append("\\r")
        elif ord(ch) < 32: out.append("\\u{%x}" % ord(ch))
        else: out.append(ch)
    out.append('"')
    return "".join(out)


def fmt_attrs(a):
    if not a:
        return ""
    return " [" + ", ".join(f"{k} = {fmt_lit(v)}" for k, v in sorted(a.items())) + "]"


def fmt_pins(pins):
    parts = []
    for p in pins:
        if p.type == "exec":
            parts.append(f"exec {p.name}")
        else:
            s = f"{p.name}: {p.type}"
            if p.default is not None:
                s += " = " + fmt_lit(p.default)
            parts.append(s + fmt_attrs(p.attrs))
    return "(" + ", ".join(parts) + ")"


def fmt_targ(t):
    k, v = t
    if k == "sym":
        return "@" + v
    if k == "str":
        return fmt_str(v)
    if k == "local":
        return "$" + v
    return str(v)


def fmt_func(f, ind):
    pad = "  " * ind
    mods = "".join(m + " " for m in ("export", "pure", "latent") if m in f.mods)
    head = f"{pad}{mods}{f.kind} {f.name}"
    if f.tparams:
        head += "<" + ", ".join(f.tparams) + ">"
    head += fmt_pins(f.params)
    if f.results:
        head += " -> " + fmt_pins(f.results)
    if not f.has_body:
        return [head]
    out = [head + " {"]
    p2 = pad + "  "
    for k, v in f.meta:
        out.append(f"{p2}meta {k} = {fmt_lit(v)}")
    for l in f.locals:
        out.append(f"{p2}local ${l.name}: {l.type}" +
                   (f" = {fmt_lit(l.default)}" if l.default is not None else "") + fmt_attrs(l.attrs))
    for l in f.states:
        out.append(f"{p2}state ${l.name}: {l.type}" + (f" = {fmt_lit(l.default)}" if l.default is not None else "") + fmt_attrs(l.attrs))
    if f.nodes:
        out.append(f"{p2}graph {{")
        for n in f.nodes:
            out += fmt_node(n, ind + 2)
        out.append(f"{p2}}}")
    if f.layout:
        out.append(f"{p2}layout {{")
        for it in f.layout:
            if it[0] == "node":
                out.append(f"{p2}  %{it[1]} at ({it[2][0]}, {it[2][1]}){fmt_attrs(it[3])}")
            else:
                out.append(f"{p2}  box {fmt_str(it[1])} at ({it[2][0]}, {it[2][1]}) size ({it[3][0]}, {it[3][1]}){fmt_attrs(it[4])}")
        out.append(f"{p2}}}")
    out.append(pad + "}")
    return out


def fmt_node(n, ind):
    pad = "  " * ind
    kind = n.kind
    if n.targs:
        kind += "<" + ", ".join(fmt_targ(t) for t in n.targs) + ">"
    head = f"{pad}node %{n.id} : {kind}"
    if not (n.ins or n.execs or n.props or n.meta):
        return [head + " {}"]
    out = [head + " {"]
    p2 = pad + "  "
    for k, v in n.meta:
        out.append(f"{p2}meta {k} = {fmt_lit(v)}")
    for k, v in n.props:
        out.append(f"{p2}prop {k} = {fmt_lit(v)}")
    for pin, src in n.ins:
        s = f"%{src[1]}.{src[2]}" if src[0] == "ref" else fmt_lit(src[1])
        out.append(f"{p2}in {pin} = {s}")
    for pin, (tn, tp) in n.execs:
        out.append(f"{p2}exec {pin} -> %{tn}" + (f".{tp}" if tp else ""))
    out.append(pad + "}")
    return out


def format_module(m):
    out = [f"wiret {m.version}", ""]
    if m.name is not None:
        out.append(f"module {fmt_str(m.name)}")
    for k, v in m.meta:
        out.append(f"meta {k} = {fmt_lit(v)}")
    blocks = []
    if m.uses:
        blocks.append([f"use {fmt_str(p)} as {a}" for p, a in m.uses])
    if m.externs:
        b = []
        for kind, n, target, ps, rs, mods in m.externs:
            if kind == "type":
                b.append(f"extern type {n} = {fmt_str(target)}")
            else:
                md = "".join(x + " " for x in ("pure", "latent") if x in mods)
                b.append(f"{md}extern function {n} = {fmt_str(target)}{fmt_pins(ps)}" + (f" -> {fmt_pins(rs)}" if rs else ""))
        blocks.append(b)
    for n, members in m.enums:
        blocks.append([f"enum {n} {{"] + [f"  {mn} = {v}{fmt_attrs(a)}," for mn, v, a in members] + ["}"])
    for n, fields in m.structs:
        b = [f"struct {n} {{"]
        for p in fields:
            b.append(f"  {p.name}: {p.type}" + (f" = {fmt_lit(p.default)}" if p.default is not None else "") + fmt_attrs(p.attrs) + ",")
        blocks.append(b + ["}"])
    for n, ps, rs in m.delegates:
        blocks.append([f"delegate {n}{fmt_pins(ps)}" + (f" -> {fmt_pins(rs)}" if rs else "")])
    for n, meths in m.ifaces:
        b = [f"interface {n} {{"]
        for f in meths:
            b += fmt_func(f, 1)
        blocks.append(b + ["}"])
    for p in m.vars:
        kw = "const" if "const" in p.attrs else "var"
        a = {k: v for k, v in p.attrs.items() if k != "const"}
        blocks.append([f"{kw} {p.name}: {p.type}" + (f" = {fmt_lit(p.default)}" if p.default is not None else "") + fmt_attrs(a)])
    for n, bases, meta, fields, meths in m.classes:
        b = [f"class {n}" + (" : " + ", ".join(bases) if bases else "") + " {"]
        for k, v in meta:
            b.append(f"  meta {k} = {fmt_lit(v)}")
        for p in fields:
            b.append(f"  var {p.name}: {p.type}" + (f" = {fmt_lit(p.default)}" if p.default is not None else "") + fmt_attrs(p.attrs))
        for f in meths:
            b.append("")
            b += fmt_func(f, 1)
        blocks.append(b + ["}"])
    for f in m.funcs:
        blocks.append(fmt_func(f, 0))
    for b in blocks:
        out.append("")
        out += b
    return "\n".join(out) + "\n"

```

---

`reference/wiret_ref/vm.py`

```py
"""Reference interpreter for Wiret bytecode (executes the subset marked in the opcode table)."""
import math
import struct
from . import binary
from .binary import decode_module, verify_module, WiretError, F_LATENT
from .ops import OPS


class Trap(WiretError):
    def __init__(self, msg):
        super().__init__(msg)
        self.msg = msg
        self.frames = []   # (function name, node id or None)

    def __str__(self):
        s = f"trap: {self.msg}"
        for fn, node in self.frames:
            s += f"\n    at {fn}" + (f" (node %{node})" if node else "")
        return s


def w32(x):
    return ((x + 0x80000000) & 0xFFFFFFFF) - 0x80000000


def w64(x):
    return ((x + 0x8000000000000000) & 0xFFFFFFFFFFFFFFFF) - 0x8000000000000000


def f32(x):
    try:
        return struct.unpack("<f", struct.pack("<f", x))[0]
    except OverflowError:
        return math.copysign(math.inf, x)


def _tdiv(a, b):
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def fdiv(a, b):
    if b == 0:
        if a == 0 or a != a:
            return math.nan
        return math.copysign(math.inf, a) * math.copysign(1.0, b)
    return a / b


def fmin(a, b):
    return math.nan if a != a or b != b else min(a, b)


def fmax(a, b):
    return math.nan if a != a or b != b else max(a, b)


def sat(x, lo, hi):
    if x != x:
        return 0
    if x >= hi:
        return hi
    if x <= lo:
        return lo
    return int(x)


def fstr(x, single):
    if x != x:
        return "nan"
    if x in (math.inf, -math.inf):
        return "inf" if x > 0 else "-inf"
    if single:
        for p in range(1, 10):
            s = "%.*g" % (p, x)
            if f32(float(s)) == x:
                break
    else:
        s = repr(x)
    if "e" in s or "E" in s:
        return s
    return s if "." in s else s + ".0"


def build_numops():
    t = {}
    for ty, wrap in (("i32", w32), ("i64", w64)):
        bits = 32 if ty == "i32" else 64
        def idiv(a, b, wrap=wrap):
            if b == 0:
                raise Trap("integer divide by zero")
            return wrap(_tdiv(a, b))

        def irem(a, b, wrap=wrap):
            if b == 0:
                raise Trap("integer remainder by zero")
            return wrap(a - _tdiv(a, b) * b)
        t[f"ADD.{ty}"] = lambda a, b, wrap=wrap: wrap(a + b)
        t[f"SUB.{ty}"] = lambda a, b, wrap=wrap: wrap(a - b)
        t[f"MUL.{ty}"] = lambda a, b, wrap=wrap: wrap(a * b)
        t[f"DIV.{ty}"] = idiv
        t[f"REM.{ty}"] = irem
        t[f"NEG.{ty}"] = lambda a, wrap=wrap: wrap(-a)
        t[f"ABS.{ty}"] = lambda a, wrap=wrap: wrap(abs(a))
        t[f"MIN.{ty}"] = min
        t[f"MAX.{ty}"] = max
        t[f"AND.{ty}"] = lambda a, b: a & b
        t[f"OR.{ty}"] = lambda a, b: a | b
        t[f"XOR.{ty}"] = lambda a, b: a ^ b
        t[f"NOT.{ty}"] = lambda a: ~a
        t[f"SHL.{ty}"] = lambda a, b, wrap=wrap, bits=bits: wrap(a << (b & (bits - 1)))
        t[f"SHR.{ty}"] = lambda a, b, bits=bits: a >> (b & (bits - 1))
    for ty, rnd in (("f32", f32), ("f64", float)):
        t[f"ADD.{ty}"] = lambda a, b, r=rnd: r(a + b)
        t[f"SUB.{ty}"] = lambda a, b, r=rnd: r(a - b)
        t[f"MUL.{ty}"] = lambda a, b, r=rnd: r(a * b)
        t[f"DIV.{ty}"] = lambda a, b, r=rnd: r(fdiv(a, b))
        t[f"REM.{ty}"] = lambda a, b, r=rnd: r(math.nan if b == 0 or a != a or b != b or math.isinf(a) else math.fmod(a, b))
        t[f"NEG.{ty}"] = lambda a: -a
        t[f"ABS.{ty}"] = abs
        t[f"MIN.{ty}"] = fmin
        t[f"MAX.{ty}"] = fmax
        t[f"SQRT.{ty}"] = lambda a, r=rnd: r(math.sqrt(a)) if a >= 0 else math.nan
    for ty in ("i32", "i64", "f32", "f64"):
        t[f"EQ.{ty}"] = lambda a, b: a == b
        t[f"NE.{ty}"] = lambda a, b: a != b
        t[f"LT.{ty}"] = lambda a, b: a < b
        t[f"LE.{ty}"] = lambda a, b: a <= b
        t[f"GT.{ty}"] = lambda a, b: a > b
        t[f"GE.{ty}"] = lambda a, b: a >= b
    t["AND.bool"] = lambda a, b: a and b
    t["OR.bool"] = lambda a, b: a or b
    t["XOR.bool"] = lambda a, b: a != b
    t["NOT.bool"] = lambda a: not a
    t["EQ.bool"] = lambda a, b: a == b
    t["NE.bool"] = lambda a, b: a != b
    b8 = lambda s: s.encode("utf-8")
    t["STR.CONCAT"] = lambda a, b: a + b
    t["STR.LEN"] = lambda a: len(b8(a))
    t["STR.EQ"] = lambda a, b: a == b
    t["STR.NE"] = lambda a, b: a != b
    t["STR.LT"] = lambda a, b: b8(a) < b8(b)
    t["STR.LE"] = lambda a, b: b8(a) <= b8(b)
    t["STR.GT"] = lambda a, b: b8(a) > b8(b)
    t["STR.GE"] = lambda a, b: b8(a) >= b8(b)
    cv = {
        "i32.i64": lambda a: a, "i64.i32": w32, "i32.f32": lambda a: f32(float(a)), "i32.f64": float,
        "i64.f32": lambda a: f32(float(a)), "i64.f64": float,
        "f32.i32": lambda a: sat(a, -2**31, 2**31 - 1), "f32.i64": lambda a: sat(a, -2**63, 2**63 - 1),
        "f64.i32": lambda a: sat(a, -2**31, 2**31 - 1), "f64.i64": lambda a: sat(a, -2**63, 2**63 - 1),
        "f32.f64": float, "f64.f32": f32, "bool.i32": int, "i32.bool": lambda a: a != 0,
        "i32.string": str, "i64.string": str, "f32.string": lambda a: fstr(a, True),
        "f64.string": lambda a: fstr(a, False), "bool.string": lambda a: "true" if a else "false",
    }
    for k, v in cv.items():
        t["CVT." + k] = v
    return t


NUMOPS = build_numops()
DEFAULTS = {"i32": 0, "i64": 0, "f32": 0.0, "f64": 0.0, "bool": False, "string": ""}


class Instance:
    def __init__(self, vm, dm):
        self.vm, self.dm = vm, dm
        self.nimp = len(dm.imports)
        self.globals = []
        for g in dm.globals:
            v = g["init"]
            if isinstance(v, tuple) and v and v[0] == "str":
                v = dm.strings[v[1]]
            elif v is None:
                v = DEFAULTS.get(g["type"])
            self.globals.append(v)
        self.natives = []
        for im in dm.imports:
            key = f"{im['module']}.{im['field']}"
            if key not in vm.natives:
                raise WiretError(f"link error: unresolved import {key}")
            self.natives.append(vm.natives[key])
        self.code = []
        for fi, f in enumerate(dm.funcs):
            pc2i = {ins[0]: i for i, ins in enumerate(f["code"])}
            dec = []
            for pc, name, args, _ in f["code"]:
                spec = OPS[name][1]
                na = []
                for k, a in zip(spec, args):
                    if k == "L":
                        na.append(pc2i[a])
                    elif k == "sw":
                        na.append(([pc2i[x] for x in a[0]], pc2i[a[1]]))
                    else:
                        na.append(a)
                dec.append((name, na))
            nm = {}
            for pc, node in dm.nodemap.get(self.nimp + fi, []):
                nm[pc2i[pc]] = node
            self.code.append((dec, nm))
        self.depth = 0
        self.steps = 0

    def fname(self, gi):
        return self.dm.names.get((0, gi), f"f{gi}")

    def find_export(self, name):
        for n, k, i in self.dm.exports:
            if n == name:
                return i
        raise WiretError(f"no export named {name!r}")

    def call(self, name, *args):
        gi = self.find_export(name) if isinstance(name, str) else name
        res = self.invoke(gi, list(args))
        return res[0] if len(res) == 1 else res

    def invoke(self, gi, args):
        vm = self.vm
        if gi < self.nimp:
            fn, nres = self.natives[gi]
            r = fn(*args)
            if nres == 0:
                return []
            if nres == 1:
                return [r]
            return list(r)
        self.depth += 1
        if self.depth > vm.max_depth:
            self.depth -= 1
            raise Trap("call stack overflow")
        try:
            return self.run(gi, args)
        finally:
            self.depth -= 1

    def run(self, gi, args):
        fi = gi - self.nimp
        f = self.dm.funcs[fi]
        dec, nmap = self.code[fi]
        regs = [DEFAULTS.get(t) for t in f["regtypes"]]
        regs[:len(args)] = args
        vm = self.vm
        hook = vm.hook
        pc = 0
        try:
            while True:
                if hook is not None and pc in nmap:
                    hook(self.fname(gi), nmap[pc])
                name, a = dec[pc]
                pc += 1
                self.steps += 1
                if self.steps > vm.budget:
                    raise Trap("instruction budget exhausted")
                op = NUMOPS.get(name)
                if op is not None:
                    if len(a) == 3:
                        regs[a[0]] = op(regs[a[1]], regs[a[2]])
                    else:
                        regs[a[0]] = op(regs[a[1]])
                    continue
                if name == "MOV":
                    regs[a[0]] = regs[a[1]]
                elif name.startswith("CONST."):
                    t = name[6:]
                    if t == "str":
                        regs[a[0]] = self.dm.strings[a[1]]
                    elif t == "bool":
                        regs[a[0]] = bool(a[1])
                    elif t == "null":
                        regs[a[0]] = None
                    else:
                        regs[a[0]] = a[1]
                elif name == "JMP":
                    pc = a[0]
                elif name == "JMPIF":
                    if regs[a[0]]:
                        pc = a[1]
                elif name == "JMPIFNOT":
                    if not regs[a[0]]:
                        pc = a[1]
                elif name == "SWITCH":
                    v = regs[a[0]]
                    labs, d = a[1]
                    pc = labs[v] if 0 <= v < len(labs) else d
                elif name == "RET":
                    return [regs[r] for r in a[0]]
                elif name == "CALL":
                    res = self.invoke(a[0], [regs[r] for r in a[1]])
                    for r, v in zip(a[2], res):
                        regs[r] = v
                elif name == "SELECT":
                    regs[a[0]] = regs[a[2]] if regs[a[1]] else regs[a[3]]
                elif name == "GLOBAL.get":
                    regs[a[0]] = self.globals[a[1]]
                elif name == "GLOBAL.set":
                    self.globals[a[0]] = regs[a[1]]
                elif name == "TRAP":
                    raise Trap(self.dm.strings[a[0]])
                elif name == "ARR.new":
                    regs[a[0]] = []
                elif name == "ARR.len":
                    regs[a[0]] = len(regs[a[1]])
                elif name == "ARR.get":
                    arr, i = regs[a[1]], regs[a[2]]
                    if not 0 <= i < len(arr):
                        raise Trap(f"array index {i} out of range (length {len(arr)})")
                    regs[a[0]] = arr[i]
                elif name == "ARR.set":
                    arr, i = regs[a[0]], regs[a[1]]
                    if not 0 <= i < len(arr):
                        raise Trap(f"array index {i} out of range (length {len(arr)})")
                    arr[i] = regs[a[2]]
                elif name == "ARR.push":
                    regs[a[0]].append(regs[a[1]])
                elif name == "ARR.insert":
                    arr, i = regs[a[0]], regs[a[1]]
                    if not 0 <= i <= len(arr):
                        raise Trap(f"array index {i} out of range (length {len(arr)})")
                    arr.insert(i, regs[a[2]])
                elif name == "ARR.remove":
                    arr, i = regs[a[0]], regs[a[1]]
                    if not 0 <= i < len(arr):
                        raise Trap(f"array index {i} out of range (length {len(arr)})")
                    del arr[i]
                elif name == "ARR.clear":
                    regs[a[0]].clear()
                elif name == "ARR.clone":
                    regs[a[0]] = list(regs[a[1]])
                elif name == "ARR.pop":
                    if not regs[a[1]]:
                        raise Trap("pop from empty array")
                    regs[a[0]] = regs[a[1]].pop()
                elif name in ("NOP", "BREAK", "YIELD"):
                    pass
                else:
                    raise Trap(f"opcode {name} is not implemented by the reference VM")
        except Trap as t:
            node = None
            for ipc in sorted(nmap):
                if ipc <= pc - 1:
                    node = nmap[ipc]
            t.frames.append((self.fname(gi), node))
            raise


class VM:
    def __init__(self, budget=50_000_000, max_depth=400):
        self.natives = {}
        self.budget, self.max_depth = budget, max_depth
        self.hook = None

    def register(self, name, fn, nresults=0):
        self.natives[name] = (fn, nresults)

    def load(self, data):
        dm = decode_module(data)
        verify_module(dm)
        inst = Instance(self, dm)
        if dm.start is not None:
            inst.invoke(dm.start, [])
        return inst

```

---

`tools/build_docs.py`

```py
#!/usr/bin/env python3
"""Regenerate the opcode tables inside docs/03-bytecode.md from opcodes.py."""
import os, re, sys
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
import opcodes
opcodes.check()
path = os.path.join(here, "..", "docs", "03-bytecode.md")
text = open(path, encoding="utf-8").read()
begin, end = "<!-- BEGIN OPCODES -->", "<!-- END OPCODES -->"
new = re.sub(re.escape(begin) + r".*?" + re.escape(end),
             lambda m: begin + "\n" + opcodes.tables() + "\n" + end, text, flags=re.S)
open(path, "w", encoding="utf-8").write(new)
print("updated", path)

```
---

`tools/opcodes.py`

```py
#!/usr/bin/env python3
"""Single source of truth for the Wiret bytecode instruction set.

Used to (a) generate the opcode tables in docs/03-bytecode.md and
(b) assemble the worked example in examples/.
Run:  python3 opcodes.py            -> prints markdown tables
"""
import sys

# (mnemonic, opcode, immediates, stack effect, description)
OPS = []
def op(name, code, imm, effect, desc):
    OPS.append((name, code, imm, effect, desc))

# ---- control (0x00-0x0F)
op("nop",        0x00, "",            "[] -> []", "No operation.")
op("unreachable",0x01, "",            "[] -> trap", "Always traps (code UNREACHABLE).")
op("br",         0x02, "rel32",       "[] -> []", "Unconditional branch. Stack must be empty.")
op("br_if",      0x03, "rel32",       "[i32] -> []", "Branch if value != 0. Stack must be empty after the pop.")
op("br_ifnot",   0x04, "rel32",       "[i32] -> []", "Branch if value == 0. Stack must be empty after the pop.")
op("br_table",   0x05, "n:u32, (n+1)*rel32", "[i32] -> []", "Jump table; index n or greater selects the last (default) entry. Stack empty after the pop.")
op("ret",        0x06, "",            "[results] -> []", "Return from function; stack holds exactly the declared results.")
op("call",       0x07, "func:u32",    "[params] -> [results]", "Direct call (module function or import).")
op("call_ref",   0x08, "type:u32",    "[params, fn] -> [results]", "Call a function value; type is the expected signature. Traps on null.")
op("call_virt",  0x09, "type:u32, slot:u32", "[self, params] -> [results]", "Virtual call through the receiver's class vtable. Traps on null receiver.")
op("yield",      0x0A, "",            "[] -> []", "Suspend the fiber until the next scheduler tick.")
op("sleep",      0x0B, "",            "[f64] -> []", "Suspend the fiber for the given number of seconds of VM time.")
op("await",      0x0C, "",            "[ref any] -> []", "Suspend until the host-owned awaitable object signals completion.")

# ---- stack / variables (0x10-0x2F)
op("drop",       0x10, "",            "[t] -> []", "Discard top value.")
op("dup",        0x11, "",            "[t] -> [t t]", "Duplicate top value.")
op("swap",       0x12, "",            "[a b] -> [b a]", "Swap top two values.")
op("select",     0x13, "",            "[a b i32] -> [t]", "Pushes a if cond != 0 else b. a and b must have the same type. Both are already evaluated.")
op("local.get",  0x20, "idx:u32",     "[] -> [t]", "Push local (parameters are locals 0..n-1).")
op("local.set",  0x21, "idx:u32",     "[t] -> []", "Pop into local.")
op("local.tee",  0x22, "idx:u32",     "[t] -> [t]", "Store into local, keep value.")
op("global.get", 0x23, "idx:u32",     "[] -> [t]", "Push module global.")
op("global.set", 0x24, "idx:u32",     "[t] -> []", "Pop into module global.")

# ---- constants (0x30-0x3F)
op("i32.const",  0x30, "v:s32",       "[] -> [i32]", "LEB128 signed immediate.")
op("i64.const",  0x31, "v:s64",       "[] -> [i64]", "LEB128 signed immediate.")
op("f32.const",  0x32, "v:f32",       "[] -> [f32]", "4 bytes little-endian.")
op("f64.const",  0x33, "v:f64",       "[] -> [f64]", "8 bytes little-endian.")
op("str.const",  0x34, "idx:u32",     "[] -> [string]", "Push string from constant pool.")
op("ref.null",   0x35, "heap:s33",    "[] -> [ref]", "Push null reference of the given heap type.")

# ---- comparisons 0x40-0x61
def cmp_int(base, p):
    names = ["eqz","eq","ne","lt_s","lt_u","gt_s","gt_u","le_s","le_u","ge_s","ge_u"]
    for i, n in enumerate(names):
        t = "[%s] -> [i32]" % p if n == "eqz" else "[%s %s] -> [i32]" % (p, p)
        op("%s.%s" % (p, n), base + i, "", t, "Compare; result 1 or 0.")
cmp_int(0x40, "i32"); cmp_int(0x4B, "i64")
def cmp_f(base, p):
    for i, n in enumerate(["eq","ne","lt","gt","le","ge"]):
        op("%s.%s" % (p, n), base + i, "", "[%s %s] -> [i32]" % (p, p), "IEEE-754 compare; any NaN operand gives 0 (1 for ne).")
cmp_f(0x56, "f32"); cmp_f(0x5C, "f64")

# ---- integer arithmetic 0x62-0x85
def arith_int(base, p):
    un = ["clz","ctz","popcnt"]
    bi = ["add","sub","mul","div_s","div_u","rem_s","rem_u","and","or","xor","shl","shr_s","shr_u","rotl","rotr"]
    d = {"div_s":"Traps on divide by zero or INT_MIN / -1.","div_u":"Traps on divide by zero.",
         "rem_s":"Traps on divide by zero; INT_MIN % -1 = 0.","rem_u":"Traps on divide by zero.",
         "shl":"Shift count taken modulo bit width.","shr_s":"Arithmetic shift; count modulo bit width.",
         "shr_u":"Logical shift; count modulo bit width.","add":"Wraps (two's complement).",
         "sub":"Wraps.","mul":"Wraps."}
    i = 0
    for n in un:
        op("%s.%s" % (p, n), base + i, "", "[%s] -> [%s]" % (p, p), "Bit count."); i += 1
    for n in bi:
        op("%s.%s" % (p, n), base + i, "", "[%s %s] -> [%s]" % (p, p, p), d.get(n, "Bitwise / rotate.")); i += 1
arith_int(0x62, "i32"); arith_int(0x74, "i64")

# ---- float arithmetic 0x86-0xA1
def arith_f(base, p):
    un = ["abs","neg","ceil","floor","trunc","nearest","sqrt"]
    bi = ["add","sub","mul","div","min","max","copysign"]
    i = 0
    for n in un:
        op("%s.%s" % (p, n), base + i, "", "[%s] -> [%s]" % (p, p), "IEEE-754 (nearest = ties-to-even)."); i += 1
    for n in bi:
        op("%s.%s" % (p, n), base + i, "", "[%s %s] -> [%s]" % (p, p, p), "IEEE-754; min/max propagate NaN."); i += 1
arith_f(0x86, "f32"); arith_f(0x94, "f64")

# ---- conversions 0xA2-0xBC
conv = [
 ("i32.wrap_i64","i64","i32","Keep low 32 bits."),
 ("i32.trunc_f32_s","f32","i32","Saturating; NaN -> 0."),("i32.trunc_f32_u","f32","i32","Saturating; NaN -> 0."),
 ("i32.trunc_f64_s","f64","i32","Saturating; NaN -> 0."),("i32.trunc_f64_u","f64","i32","Saturating; NaN -> 0."),
 ("i64.extend_i32_s","i32","i64","Sign-extend."),("i64.extend_i32_u","i32","i64","Zero-extend."),
 ("i64.trunc_f32_s","f32","i64","Saturating; NaN -> 0."),("i64.trunc_f32_u","f32","i64","Saturating; NaN -> 0."),
 ("i64.trunc_f64_s","f64","i64","Saturating; NaN -> 0."),("i64.trunc_f64_u","f64","i64","Saturating; NaN -> 0."),
 ("f32.convert_i32_s","i32","f32","Round to nearest."),("f32.convert_i32_u","i32","f32","Round to nearest."),
 ("f32.convert_i64_s","i64","f32","Round to nearest."),("f32.convert_i64_u","i64","f32","Round to nearest."),
 ("f32.demote_f64","f64","f32","Round to nearest."),
 ("f64.convert_i32_s","i32","f64","Exact."),("f64.convert_i32_u","i32","f64","Exact."),
 ("f64.convert_i64_s","i64","f64","Round to nearest."),("f64.convert_i64_u","i64","f64","Round to nearest."),
 ("f64.promote_f32","f32","f64","Exact."),
 ("i32.reinterpret_f32","f32","i32","Bit cast."),("i64.reinterpret_f64","f64","i64","Bit cast."),
 ("f32.reinterpret_i32","i32","f32","Bit cast."),("f64.reinterpret_i64","i64","f64","Bit cast."),
 ("i32.extend8_s","i32","i32","Sign-extend low 8 bits."),("i32.extend16_s","i32","i32","Sign-extend low 16 bits."),
]
for i, (n, a, b, d) in enumerate(conv):
    op(n, 0xA2 + i, "", "[%s] -> [%s]" % (a, b), d)

# ---- records / references 0xC0-0xCF
op("rec.new",    0xC0, "type:u32",            "[] -> [ref]", "Allocate zero/default-initialised struct or class instance.")
op("rec.get",    0xC1, "type:u32, field:u32", "[ref] -> [t]", "Read field. Traps on null.")
op("rec.set",    0xC2, "type:u32, field:u32", "[ref t] -> []", "Write field. Traps on null.")
op("clone",      0xC3, "type:u32",            "[ref] -> [ref]", "Deep copy of a value-semantics object (struct, array, map, set). Nested value-type members are copied; class references are shared.")
op("ref.is_null",0xC4, "",                    "[ref] -> [i32]", "1 if null.")
op("ref.eq",     0xC5, "",                    "[ref ref] -> [i32]", "Reference identity.")
op("ref.cast",   0xC6, "type:u32",            "[ref] -> [ref]", "Checked downcast; traps on failure (null passes).")
op("ref.test",   0xC7, "type:u32",            "[ref] -> [i32]", "1 if non-null and an instance of type.")
op("ref.cast_or_null", 0xC8, "type:u32",      "[ref] -> [ref]", "Downcast; yields null on failure.")
op("fn.ref",     0xC9, "func:u32",            "[] -> [ref fn]", "Unbound function value.")
op("fn.bind",    0xCA, "",                    "[ref fn, ref self] -> [ref fn]", "Bind receiver as the first argument.")

# ---- extended prefix 0xFB, sub-opcode is u32 LEB
EXT = []
def ext(name, sub, imm, effect, desc):
    EXT.append((name, sub, imm, effect, desc))

ext("array.new",    0x00, "type:u32", "[] -> [ref]", "Empty array of array type.")
ext("array.len",    0x01, "", "[ref] -> [i32]", "Element count.")
ext("array.get",    0x02, "", "[ref i32] -> [t]", "Traps if index out of range.")
ext("array.set",    0x03, "", "[ref i32 t] -> []", "Traps if index out of range.")
ext("array.push",   0x04, "", "[ref t] -> []", "Append.")
ext("array.pop",    0x05, "", "[ref] -> [t]", "Remove and return last. Traps if empty.")
ext("array.insert", 0x06, "", "[ref i32 t] -> []", "Insert before index (index may equal len).")
ext("array.remove", 0x07, "", "[ref i32] -> []", "Remove at index. Traps if out of range.")
ext("array.clear",  0x08, "", "[ref] -> []", "Remove all.")
ext("array.resize", 0x09, "", "[ref i32] -> []", "Grow with default values or truncate.")
ext("array.find",   0x0A, "", "[ref t] -> [i32]", "Index of first equal element, or -1 (value equality for primitives and strings, identity for classes).")
ext("map.new",      0x20, "type:u32", "[] -> [ref]", "Empty map.")
ext("map.len",      0x21, "", "[ref] -> [i32]", "Entry count.")
ext("map.has",      0x22, "", "[ref k] -> [i32]", "1 if key present.")
ext("map.get",      0x23, "", "[ref k] -> [v]", "Traps if key missing.")
ext("map.get_or",   0x24, "", "[ref k v] -> [v]", "Value for key, or the supplied fallback.")
ext("map.set",      0x25, "", "[ref k v] -> []", "Insert or overwrite.")
ext("map.remove",   0x26, "", "[ref k] -> [i32]", "1 if removed.")
ext("map.clear",    0x27, "", "[ref] -> []", "Remove all.")
ext("map.keys",     0x28, "", "[ref] -> [ref array<k>]", "Snapshot of keys in insertion order.")
ext("map.values",   0x29, "", "[ref] -> [ref array<v>]", "Snapshot of values in insertion order.")
ext("set.new",      0x40, "type:u32", "[] -> [ref]", "Empty set.")
ext("set.len",      0x41, "", "[ref] -> [i32]", "Element count.")
ext("set.has",      0x42, "", "[ref t] -> [i32]", "Membership.")
ext("set.add",      0x43, "", "[ref t] -> [i32]", "1 if newly added.")
ext("set.remove",   0x44, "", "[ref t] -> [i32]", "1 if removed.")
ext("set.clear",    0x45, "", "[ref] -> []", "Remove all.")
ext("set.to_array", 0x46, "", "[ref] -> [ref array<t>]", "Snapshot in insertion order.")
ext("str.concat",   0x60, "", "[string string] -> [string]", "Concatenate.")
ext("str.len",      0x61, "", "[string] -> [i32]", "Length in Unicode scalar values.")
ext("str.byte_len", 0x62, "", "[string] -> [i32]", "Length in UTF-8 bytes.")
ext("str.eq",       0x63, "", "[string string] -> [i32]", "Equality (byte-wise).")
ext("str.cmp",      0x64, "", "[string string] -> [i32]", "-1 / 0 / 1 by code point order.")
ext("str.sub",      0x65, "", "[string i32 i32] -> [string]", "Substring (start, length) in scalar values; clamped.")
ext("str.find",     0x66, "", "[string string] -> [i32]", "Scalar index of first match or -1.")
ext("str.replace",  0x67, "", "[string string string] -> [string]", "Replace all occurrences.")
ext("str.split",    0x68, "", "[string string] -> [ref array<string>]", "Split on separator.")
ext("str.join",     0x69, "", "[ref array<string> string] -> [string]", "Join with separator.")
ext("str.upper",    0x6A, "", "[string] -> [string]", "Unicode default upper-casing.")
ext("str.lower",    0x6B, "", "[string] -> [string]", "Unicode default lower-casing.")
ext("str.trim",     0x6C, "", "[string] -> [string]", "Strip Unicode whitespace both ends.")
ext("str.from_i64", 0x6D, "", "[i64] -> [string]", "Decimal text.")
ext("str.from_f64", 0x6E, "", "[f64] -> [string]", "Shortest round-trip decimal text.")
ext("str.parse_i64",0x6F, "", "[string] -> [i64 i32]", "Parsed value and ok flag (0 on failure, value 0).")
ext("str.parse_f64",0x70, "", "[string] -> [f64 i32]", "Parsed value and ok flag.")

def check():
    seen = {}
    for n, c, *_ in OPS:
        assert 0 <= c < 0xFB, (n, c)
        assert c not in seen, "dup opcode %02X: %s / %s" % (c, n, seen[c])
        seen[c] = n
    names = [o[0] for o in OPS] + [e[0] for e in EXT]
    assert len(names) == len(set(names)), "dup mnemonic"
    subs = [e[1] for e in EXT]
    assert len(subs) == len(set(subs)), "dup ext subop"

BY_NAME = {o[0]: o[1] for o in OPS}
EXT_BY_NAME = {e[0]: e[1] for e in EXT}

def md_row(cells):
    return "| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |"

def tables():
    out = []
    out.append("| Hex | Mnemonic | Immediates | Stack | Notes |")
    out.append("|---|---|---|---|---|")
    for n, c, imm, eff, d in sorted(OPS, key=lambda o: o[1]):
        out.append(md_row(["`%02X`" % c, "`%s`" % n, imm or "—", "`%s`" % eff, d]))
    out.append("")
    out.append("**Extended instructions** — opcode `0xFB` followed by a LEB128 `u32` sub-opcode.")
    out.append("")
    out.append("| Sub | Mnemonic | Immediates | Stack | Notes |")
    out.append("|---|---|---|---|---|")
    for n, c, imm, eff, d in sorted(EXT, key=lambda e: e[1]):
        out.append(md_row(["`%02X`" % c, "`%s`" % n, imm or "—", "`%s`" % eff, d]))
    return "\n".join(out)

if __name__ == "__main__":
    check()
    print(tables())
    print("\n%d core + %d extended instructions" % (len(OPS), len(EXT)), file=sys.stderr)

```

---

**END**
