## 1. Overview

### 1.1 What Wiret is

Wiret is a graph-first programming language whose source of truth is a text file. A program is a set of *graphs* made of *nodes* joined by *wires*, as in Unreal Blueprints, but each graph is stored in a line-oriented, IR-like text format that diffs and merges cleanly in Git and that LLMs can read and write. A graph editor is the primary authoring tool; the text format is its storage, review and interchange format. Nobody is expected to type it by hand, but it must be pleasant to read in a diff.

| Artifact | Extension | Purpose |
| --- | --- | --- |
| Source | `.wiret` | Canonical text. This is what gets committed. |
| Bytecode | `.wbc` | Compiled, verified, portable module (WBC = Wiret ByteCode). |
| Runtime | `libwiret` | Embeddable VM with a C API (`wiret.h`, prefix `wr_`). |

### 1.2 Design principles

1. **One input, one line.** A node is one statement, each of its inputs one line of it, and a node that feeds a single input is written inside it. Changing a value or a data wire is a one-line diff.
2. **Resolved, not inferred.** The file stores the fully resolved graph. Wildcard pins have concrete types, every automatic conversion is an explicit `Convert` node, and no behaviour depends on editor-side inference. What you read is what compiles.
3. **Every wire is written exactly once.** A data wire is written at its consumer; an exec wire is the order of `exec` statements, an output's block, or a `goto`. This matches Blueprint's rules (a data input has one source, an exec output has one target) and makes dangling wires impossible to express.
4. **Reads in the order it runs.** A function is written as its `exec` statements from `Entry`, with the blocks of a branching node nested where they run, so the text reads like the graph is followed (section 2.3).
5. **Semantics and presentation are separable.** Where a node is drawn (position, colour, size) is in its attribute block, `{pos=(x, y)}`, and explanations are `@note` decorators; neither ever changes bytecode or the semantic hash, but both are stored, canonicalised and diffed so every collaborator sees the same graph.
6. **Preserve what you do not understand.** Unknown decorators and attributes survive load and save unchanged (the GML rule).
7. **Deterministic in deterministic mode.** With `WR_CFG_DETERMINISTIC`, the same `.wbc` and the same logged sequence of host calls give the same results: wrapping integer arithmetic, specified floating-point and NaN behaviour, insertion-ordered maps and sets, defined scheduling order, a host-driven clock. The conditions and the exclusions (wall-clock interrupts, unlogged host callbacks) are in section 4.10; outside that mode nothing beyond memory safety is promised.
8. **Small core, big library.** The compiler knows a few dozen node kinds. Loops, `DoOnce`, `Gate` and similar are macros written in Wiret itself.
9. **Safe to embed.** Bytecode is verified before it runs, modules have no ambient authority (they reach the outside world only through host-registered natives), execution has fuel and memory limits, and the VM never unwinds through host frames.

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
| LLVM IR | One instruction per line, named values, explicit types everywhere, metadata attached to the thing it describes (our `@` decorators). |
| DOT | Addressing a part of a node (`node:port` becomes `node.pin`), attribute lists (our `{key=value}` attribute blocks), clusters (our boxes). |
| GML | Nested key/value attributes, plain ASCII portability, mandatory preservation of unknown attributes, "unsafe" capitalised keys. |
| WebAssembly | Section-based binary, LEB128 integers, value-type codes, custom sections for names and debug data, single-pass validation. |
| JVM | Class, interface and vtable model, exception handler tables, an attribute system, a verifier that runs before execution. |
| Lua C API | One state object per VM, a virtual stack as the only host/VM data channel, registry references, a pluggable allocator, protected calls, coroutines. |

### 1.5 Terminology

| Term | Meaning |
| --- | --- |
| Graph | The body of a function, event or macro: nodes plus locals. |
| Node | One operation. Written `exec Kind(.pin <- value ...)` where control reaches it, inline as an input's value when exactly one input reads it, or `node name = Kind(...)` when it is used from several places (section 2.3). |
| Pin | A named input or output of a node. Has a type. |
| Exec pin | A pin of type `exec`. Wires between exec pins carry control flow. |
| Data pin | Any other pin. Wires between data pins carry values. |
| Pure node | No exec pins. Evaluated on demand by whoever consumes it. |
| Impure node | Has exec pins. Runs when control reaches it. |
| Fiber | One thread of VM execution with its own stack. Latent nodes suspend a fiber. |
| Host | The application that embeds `libwiret`. |
| Exec statement | `exec Kind(...)` or `exec name`: a node on the path control follows. Each runs after the one before it in its block; a node with several exec outputs writes each as a block, `.then -> { ... }` (section 2.3). |
| Execution position | How an anonymous node is identified: its index among the exec statements of its block, after the block's position, as in `1.body.0` (section 2.3). |
| Decorator | An `@name(...)` line above a declaration, statement or input. A metadata decorator never changes compiled output: `@doc` (tooltip text), `@category` and `@keywords` (palette), `@note` (explanatory prose). A semantic decorator, such as `@pure` or `@disabled`, does (section 2.4). |
| Evaluation point | The moment just before an impure node runs, when its pure inputs are evaluated (section 4.3). |
| Join | An exec input with more than one producer (section 4.2). |

### 1.6 Implementation tiers

The specification covers a language, a canonical format, an editor contract, a merge protocol, macros, async, objects, containers, bytecode, a verifier, a C ABI, capabilities, a debugger and a project manager. It is staged, and the Python prototype in `prototype/` follows the stages: Tiers 0 and 1 run through its parser, checker, compiler, verifier and VM and pass their tests, and Tier 2 has started with `Try` and `Throw`, latent nodes and fibers, classes, interfaces, delegates and dispatchers, copy-on-write containers, and capabilities. A tier is not started until the one before it passes its tests, and a guarantee in this document is only as firm as the tier that contains it.

| Tier | Scope | Done when |
| --- | --- | --- |
| 0. Core | `func`; primitive types and literals; pure arithmetic, comparison and logic; `Entry`, `Return`, `Branch`, `Sequence`; exec back-edges; the `ForRange` macro as the one loop construct (it exercises `Sequence`, `Exit` and the continuation stack); `@pure`; structured diagnostics for these kinds; `exec`, output blocks and `goto`; canonical formatter, both hashes, a reference interpreter over the lowered blocks | The examples in 2.6 that use only Tier 0 features, in canonical form, round-trip byte for byte, produce the traces in 4.2, and every Tier 0 diagnostic has a failing graph. |
| 1. Data and tooling | `struct`, `enum`, `array`/`set`/`map` with **eager** copy (observably identical to 4.9), `Convert`, registry, `state`, `@reads`, metadata decorators and notes, the merge and edit protocol, WBC and the verifier, `wiretc view --flow` and the Git textconv | Editor round trips are byte-stable; merge and edit tests pass; verifier fuzz passes. |
| 2. Deferred | `class`, interfaces, `delegate`, `dispatcher`; latent nodes, fibers, `Signal`; `Try`/`Throw` (catchable faults); copy-on-write containers (an optimisation of Tier 1's semantics, not a change to them); capabilities; the full C API; debugger hooks; the project manager and lockfile | Started only after Tier 1; each item keeps the **Provisional** mark until it has its own tests. |

Sections 4.6 (faults), 4.5 (latent nodes), 4.9 (copy-on-write), the Tier 2 opcodes of 5, 6 (C API) and 7.3 (projects) are therefore specified ahead of the prototype and may change when their tier starts.
