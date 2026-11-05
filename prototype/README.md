# Wiret prototype

A Python prototype of the Wiret graph editor, compiler and runtime, built against
[`docs/reference.md`](../docs/reference.md) (Draft 0.7). It targets **Tier 0** of the spec
(section 1.6) plus a few Tier 1 conveniences. It uses only the Python standard library; the
editor uses Tkinter.

```
graph editor  <->  demo.wiret  --compile-->  demo.wbc  --load/verify/link-->  VM
```

## Running it

Requires Python 3.10+ with Tkinter (python.org builds and Homebrew `python-tk` include it).

```sh
cd prototype
python3 wiret_editor.py                         # the editor, opening Lesson 1
python3 wiret_editor.py examples/demo.wiret     # the editor on a larger example
python3 wiretc.py run examples/demo.wiret Main  # the same program from the command line
python3 -m unittest discover tests              # 114 tests
```

## Building a desktop app

To give the editor to people without Python or a terminal, build it with PyInstaller:

```sh
cd prototype
python3 build.py --zip      # runs the tests, installs PyInstaller if needed, then builds
```

This produces `dist/Wiret/Wiret.exe` on Windows or `dist/Wiret.app` on macOS, plus
`dist/Wiret-<os>.zip` to share. Build on each OS you want to support (PyInstaller does not
cross-compile). The packaged app saves students' lesson copies in `~/Documents/Wiret/my_lessons`
(or `~/Wiret` when there is no Documents folder); set `WIRET_HOME` to use another folder.
Running from source still uses `prototype/my_lessons`. Unsigned builds show a SmartScreen or
Gatekeeper warning on first launch.

## Demo script (about 5 minutes)

1. Run `python3 wiret_editor.py`. Lesson 1 opens with its notes. Press **▶ Run**.
2. Press **⤵ Step** a few times. The node about to run is outlined in cyan.
3. Open **Lessons → 4. Loops**, tick **Animate** and press Run to watch the loop go round.
4. Press **⤵ Step** in the same lesson. Show the values on the wires (`index`, the running
   total) and the **Debugger** tab's call stack and variables.
5. Press Tab, type "if", and add a Branch. Then drag a wire from `count.index` onto empty
   canvas, type "text", and press Enter. The Convert node arrives already wired.
6. Wire a number straight into a text pin through the Source pane. The **Problems** tab
   explains the mistake in plain words.
7. Open **Lessons → 6. Fizzbuzz** and run it as the "putting it together" example.
8. For the language and tooling side, open the Source and Bytecode tabs. Point out that the
   graph and the text are the same program.

## The editor

The window has the graph canvas on the left. On the right are the **Source** pane (the
`.wiret` text), **Problems** (diagnostics in plain language), **Debugger** (call stack and
variables) and **Bytecode** (disassembly of the last build).
A console at the bottom shows program output.

The `.wiret` file is the only copy of the program, and it stays in sync with the editor:

- **Graph edits** (moving, wiring, adding, deleting, renaming) update the model, write the file
  in canonical form (section 2.5) and refresh the Source pane straight away.
- **Typing in the Source pane** re-parses the text after a short pause. If it parses, the graph
  redraws and the file is saved as typed. If it does not, the error line is highlighted and
  graph editing is blocked until the text parses again.
- **Changes made by other programs** (an LLM, `git checkout`, another editor) are noticed by
  polling the file every second, and the editor reloads.

**Run** (F5) compiles the file to a `.wbc` next to it, loads those bytes back from disk into
the VM (decode, verify, link) and calls the function chosen under *Entry*, passing the
comma-separated *Args*. Every node that ran gets a green outline and an `×N` count. If the
program faults, the faulting node gets a red outline. The console explains the error in plain
words, followed by the technical traceback. A run is limited to 5 million instructions, so an
endless loop stops after a few seconds.

### Stepping and breakpoints

| Control | What it does |
| --- | --- |
| **⤵ Step** (F11) | Starts paused, or runs one node. It enters called functions, including pure ones such as `Square`. While the program is running, the same button pauses it. |
| **↷ Step Over** (F10) | Runs one node of the current function. Called functions run in one go. |
| **▶ Continue** (F5) | Runs until the next breakpoint or the end. |
| **■ Stop** (Shift+F5) | Ends the run. |
| **Animate** + speed | Run walks the entry function node by node at the chosen speed. |
| Breakpoint (F9, or right-click → Set breakpoint) | Pauses when that node is reached. Shown as a red dot. Never saved to the file. |

While the program is paused:

- The node about to run is outlined in cyan and labelled "▶ runs next".
- Every data wire carries a yellow tag with the value it delivered. Steps pause after a node's
  inputs are computed and before it acts, so the tags show what it is about to use.
- The **Debugger** tab lists the call stack (click a frame to view it) and the parameters,
  locals and module variables.
- Graph editing is locked until the run ends.

A debug build implements this, the `-Og` of section 4.8. Every pin's value is kept in a local
listed in `wr.pins`, and an extra `wr.steps` custom section marks each node's "inputs ready"
point. `wiretc build` still produces the normal build.

### Plain-language messages

Every diagnostic and runtime error has a beginner-level explanation (`wiret/explain.py`) that
names the types in words, such as "a whole number (i32)" or "text (string)", and says how to
fix the problem. The explanation appears in the Problems tab, in the console and when hovering
over a node. The code and the technical message stay alongside it.

### Adding nodes

- **Search palette.** Press Tab, double-click empty canvas, or choose *Search nodes…* from the
  right-click menu. Typing filters by name, by plain-language words ("if", "loop", "print",
  "text", "remainder") and by description. Enter adds the node.
- **Drop a wire on empty canvas.** The palette opens showing only nodes with a matching pin.
  The chosen node is wired up automatically.
- **Hovering a node** shows a one-sentence description of what it does.

### Lessons

The **Lessons** menu opens eight short programs from `lessons/`:

1. Hello
2. Variables
3. Decisions
4. Loops
5. Functions
6. FizzBuzz, as a challenge
7. Arrays
8. Structs and enums

Each one has an intro note and a "Try it" note on the graph. Lessons open as copies in
`my_lessons/` (git-ignored), so the originals never change. **Lessons → Start this lesson over**
restores a copy.

Loops use the built-in `std.flow` macros (`ForRange`, `Repeat`, `ForEach`, `ForEachMap`, `DoOnce`, `DoN`, `FlipFlop`).
They are written in Wiret in `wiret/std/flow.wiret`, as section 3.4 describes, and are
available to every module as `Macro std.flow.ForRange` and so on.

| Action | How |
| --- | --- |
| Add a node | Tab or double-click (search), or right-click empty canvas → category menus |
| Wire | Drag from a pin to a pin, or onto a node to use its first compatible pin |
| Wire with a type mismatch | A visible `Convert::<From, To>` node is inserted for you (section 7.5) |
| Set a literal | Double-click an input pin (bool pins toggle). An empty value unbinds the pin |
| Delete | Select a node or wire and press Delete/Backspace, or use the right-click menu |
| Open a called function/macro | Double-click a `Call` or `Macro` node |
| Rename id, label, colour, note, `@disabled`, `@count`, `@cases` | Right-click a node |
| Boxes | Right-click empty canvas → Add box. Drag a box by its title bar. Members are edited explicitly |
| Pan / zoom | Drag empty canvas / mouse wheel (Shift+wheel pans) |
| Undo / redo graph edits | Cmd+Z / Cmd+Shift+Z on the canvas (the text pane has its own undo) |
| New function / macro, signature, locals, state | **Graph** menu |

The editor also follows the graph-editor contract in section 7.5:

- Ids are kept exactly as they are; new nodes get a readable slug plus a random suffix such as
  `branch_k3m9`.
- Nodes with no `place` line are laid out automatically, and get a `place` line the first time
  the graph is saved.
- Unknown attributes and layout properties are kept.
- Notes are kept even when the node or box they explain is deleted: they move to the graph as `#[note("...", detached: "id")]` and show as detached (`W0604`).
- A wire whose source or target no longer exists stays on screen as a red dashed stub.
- `//` comments are never dropped silently: before the first graph edit, the editor asks
  whether to convert them to notes or drop them (`W0603`).
- Zoom, scroll and selection are never written to the file.

## The toolchain (`wiretc.py`)

| Command | Purpose |
| --- | --- |
| `check [--json] FILE` | Diagnostics, one JSON record per line with `--json` |
| `fmt [--check] [--convert-comments \| --drop-comments] FILE` | Canonical formatter |
| `build FILE [-o OUT] [--no-source]` | Compile and verify to `.wbc` |
| `dis FILE.wbc` | Disassemble, labelled with node ids from `wr.debug` |
| `verify FILE.wbc` | Run only the verifier |
| `run FILE FUNC [ARGS…]` | Compile and run on the reference VM |
| `hash FILE` | Semantic and layout hashes |
| `view --flow FILE` | Reading view with nodes and `flow` wires in flow order |
| `schema --json` | The node registry |

## What is implemented

| Area | Status |
| --- | --- |
| Text syntax (2.1–2.4) | Full lexer and parser for `use`, `extern`, `const`, `var`, `enum`, `struct`, `func`, `event`, `macro`, `local`, `state`, nodes, bindings, semantic `@` attributes, `#[...]` metadata lines (`#[doc]`, `#[note]`, ...) above declarations, nodes and boxes, the `flow` block (exec wires) and `layout` (places and boxes). An old `markup` block is rejected with a hint, and an unknown `@` name such as `@doc` is `E0104`. `enum` and `struct` parse, print, hash and type-check (see *Structs and enums* below), but cannot be compiled yet. `interface`/`class` are rejected with a clear error. |
| Canonical form and hashes (2.5) | Sorted items (struct fields and enum members keep the order written), nodes, `flow` wires (by source node id, then exec pin order) and layout lines, each with its metadata lines above it (`doc`, `category`, `keywords`, then notes as written); registry pin order; default-valued bindings omitted; 100-column wrapping; attribute ordering. Semantic hash (ignores layout, every `#[...]` line and `Reroute`) and layout hash. |
| Node kinds (3.3) | `Entry`, `Return`, `Branch`, `Sequence`, `Switch`, `Select`, `Macro`, `Exit`, `Reroute`, `Get/SetLocal`, `Get/SetVar` (and `const`s), `Get/SetState`, `Call`, `Convert`, all arithmetic, comparison, logic and bit kinds, and the array kinds `MakeArray`, `ArrayGet`, `ArrayLength`, `ArraySet`, `ArrayAdd`, `ArrayInsert`, `ArrayRemove`, `ArrayClear`, the struct kinds, and the map and set kinds (see *Maps and sets* below). Types: `bool`, all integer widths, `f32`, `f64`, `string`, `array::<T>`, `map::<K, V>`, `set::<T>`, structs and enums. |
| Execution model (4.2–4.3) | Continuation stack, `Sequence` push/pop, macro inlining with path-style ids (`loop/test`, `loop!in`), `Exit` as a jump, joins, evaluation points with per-point sharing, impure output slots, `@pure` and `@reads` calls as pure nodes, per-expansion `state`. The §4.2 `SumTo(2)` trace is reproduced exactly (see tests). |
| Diagnostics (4.7) | E0101, E0102, E0103, E0110, E0111, E0120, E0121, E0201, E0301, E0302, E0304, E0401, E0501, E0502, E0503, W0201, W0301, W0302, W0310, W0320, W0601, W0602, W0603, W0604. |
| Lowering (4.8) | `-O0`: one labelled block per impure node, `local.tee` for shared values, `cont.push`/`cont.pop` kept. Output closely matches the §5.8 listings. |
| WBC (5.2–5.4) | Type (function, `5E` array and `5F` struct entries), Import, Function, Global, Export, Data and Code sections, plus custom sections `name`, `wr.debug`, `wr.pins`, `wr.pure`, `wr.meta` (hashes), `wr.caps` and `wr.graph` (deflated canonical source). |
| Verifier (5.5) | One linear pass: decoding, branch targets, empty stack at labels, operand typing (including `struct.new`/`get`/`with`), returns, `max_stack`, latency/purity flags. Type references may point forward, but a struct may not hold itself by value. Fuzz-tested. |
| VM (5–6) | Interpreter with exact fuel counting (5.7), faults with node-level tracebacks (6.9), a node hook that drives the editor's trace, linking against `std.*` natives and the host native `host.Log`. |

### Encoding choices the draft leaves open

- Every structural `u32` (section sizes, vector lengths, indices) is unsigned LEB128. Only the
  magic, version and flags are fixed-width.
- Branch offsets are signed LEB128 padded to 5 bytes, so code can be laid out in a single pass.
- Custom section layouts:
  - `name`: `vec(func name)`, `vec(func vec(local name))`, `vec(global name)`.
  - `wr.debug`: per function, `func graph vec(string) vec(pc_delta node)`.
  - `wr.pins`: per function, `func vec(local node pin)`, with node and pin as indices into that
    function's `wr.debug` string table.
  - `wr.pure`: per function, `func vec(pc_delta node)`, the same layout as `wr.debug`. It is not
    in the draft. Each entry marks where code for a pure node starts, or where code for the
    node around it resumes. Faults and the debugger's call stack use it to name the pure node
    that failed (an `ArrayGet` out of range, a `Div` by zero) instead of the node that used its
    result. Stepping and run counts ignore it.
  - `wr.meta`: seven names: module, id, compiler, registry, semantic hash, layout hash,
    source hash.
  - `wr.caps`: `vec(name)`.
  - `wr.graph`: zlib-deflated canonical text.
- `Convert::<X, string>` and float `Rem` lower to calls to internal `std.convert.*` and
  `std.math.FRem*` natives, since the instruction set has no opcodes for them.

### Structs and enums

Declarations are checked, and their names can be used as types in signatures, `local`, `state`,
`var` and fields, including inside `array::<T>`:

- Types are written without the module prefix (`Vec2`, not `game.demo.Vec2`).
- Duplicate fields or members, or a struct or enum named after a built-in type, are `E0102`.
- An unknown field type is `E0501`, and so is a field of type `exec`.
- A field default that does not fit its type, or an enum value outside its underlying type
  (default `i32`), is `E0110`. A member without `= INT` is one more than the member before it,
  and the first one is 0.
- A struct that holds itself by value, directly or through other structs, is `E0503`. Holding
  it in an array is fine.

An enum value is written `Mode.Chase`: on a pin (`.b <- Mode.Flee`), as a default
(`mode: Mode = Mode.Idle`) and in `@cases(Mode.Idle, Mode.Chase)`. On a pin it reads like a wire,
so it means the enum value only when the graph has no node called `Mode`. A node with the same id
as an enum is `E0102`. A missing enum or member is `E0501`, and a value of the wrong enum is
`E0110`.

Struct nodes name their struct, and the field nodes name the field too:

| Node | Pins |
| --- | --- |
| `MakeStruct Vec2` | in: one per field (default: the field's default, else zero); out `result` |
| `BreakStruct Vec2` | in `obj`; out: one per field |
| `GetField Vec2.x` | in `obj`; out `value` |
| `WithField Vec2.x` | in `obj`, `value`; out `result`, a copy with that field replaced |

All four are pure, also in a `@pure` function: a struct is a value, so reading one cannot see a
change (Draft 0.7; `reads` purity is for `GetField` on a class). `SetField` on a struct is `E0501`
with a pointer to `WithField`.

`Eq`/`Ne` take enums and structs, `Lt`/`Le`/`Gt`/`Ge` take enums, `Select` takes either, and
`Switch` takes enums. `Convert` turns an enum into its own underlying type and back, and nothing
else. Each `@cases` value must be a value of the `Switch`'s type (`E0110`); this now applies to
every `Switch`.

They compile and run:

- An enum is its underlying integer at run time, and `Convert` to or from it emits nothing.
- A struct is a `5F` type entry and an immutable value. `MakeStruct` is `struct.new`,
  `GetField` is `struct.get`, `WithField` is `struct.with`, and `BreakStruct` reads every field
  in turn.
- A struct's default value holds each field's declared default, else that field's default. The
  defaults are written into the type entry (field flag bit 0, section 5.3), so the VM builds
  struct locals and globals from it, and the compiler builds the same value for an unbound
  struct pin.
- `Eq` and `Ne` on structs compare field by field, inline. Arrays cannot be compared in this
  prototype, so `Eq` on a struct that holds an array is `E0110`.
- `wiretc run` takes enum arguments as `Mode.Chase` and prints results as
  `Vec2 { x: 1.0, y: 1.5 }` and `Mode.Chase`, and the debugger shows values the same way.
  Struct arguments cannot be typed on the command line.

In the editor:

- The palette and the right-click menus list *Make*, *Break*, *Get* and *With* nodes for every
  struct, and offer the module's types wherever a kind accepts them (`Switch::<Mode>`,
  `Eq::<Vec2>`, `MakeArray::<Vec2>`, enum `Convert`). A struct's `#[doc]` and its fields'
  `#[doc]` become the palette description.
- Dragging a struct wire onto empty canvas offers the nodes that take it, *Break* first among
  them. Right-clicking a struct output pin offers *Break into fields*, and a struct input pin
  offers *Make a Vec2*, each adding the node already wired.
- Right-clicking an enum input pin lists its members. Typing a literal into one accepts the bare
  member name, and `@cases` on an enum `Switch` does too.
- *Add local* accepts struct and enum types. Struct pins are light blue and enum pins lavender.
- Lesson 8 walks through a struct, an enum, `WithField` and a `Switch` on an enum.

Struct and enum declarations are edited in the Source pane; there is no dialog for them yet.

### Maps and sets

`map::<K, V>` and `set::<T>` are value types that keep insertion order (section 3.1). Keys and
set items are primitives, enums, or structs of those (`E0501` otherwise). The pins, which the
draft leaves open, follow the array kinds:

| Node | Pins |
| --- | --- |
| `MapFind::<K, V>` | in `map`, `key`; out `value`, `found` (a missing key gives the default value) |
| `MapHas` / `MapLength` | in `map` (and `key`); out `result` / `length` |
| `MapKeyAt` / `MapValueAt` | in `map`, `index`; out `key` / `value`, in the order keys were first added |
| `MapSet m`, `MapRemove m`, `MapClear m` | change the place `m`; in `key` (and `value`); `MapRemove` has out `removed` |
| `SetHas`, `SetLength`, `SetAt` | in `set` (and `item` or `index`); out `result`, `length`, `item` |
| `SetAdd s`, `SetRemove s`, `SetClear s` | change the place `s`; in `item`; out `added` / `removed` |

- They lower to the `5D` and `5C` type entries and the `map.*` and `set.*` opcodes (`E0` to
  `EF`). In the VM a map is an insertion-ordered dict and a set one with no values; a change
  copies it, the eager copy that Tier 1 allows. Updating a key keeps its position.
- Every NaN key is the same key, so a NaN can be looked up again. The draft does not say.
- `std.flow.ForEachMap::<K, V>` loops over a map in key order with outputs `key`, `value` and
  `index`. The palette offers map and set nodes for the map and set types the module uses.
- `wiretc run` takes a map as `{"a": 1}` and a set as `[1, 2]`.
- `Eq` on arrays, maps and sets (structural equality, section 4.9) is not implemented, and so
  neither is `Eq` on a struct that holds one.

### Identity and the id registry

A **project** is a directory with a `wiret.toml` (section 7.3); its `wiret.ids` lists every
retired id, one `module graph kind id` line each (`game.demo TakeDamage node set_new`, or
`game.demo - id fn_k3f9` for an `@id`).

- `wiretc fmt --assign-ids` gives an `@id` to every declaration, parameter, result, field, enum
  member, local and state slot that has none, and never changes an existing one.
- Inside a project, `wiretc check` and the editor also report `E0140` (a retired node, box or
  `@id` used again), `E0102` (an `@id` used twice among siblings) and `W0202` (an element without
  an `@id`). A lone file, such as a lesson, gets none of these: the draft wants `W0202` there
  too ("non-reuse cannot be checked"), but on every lone file that would be noise.
- Inside a project the editor writes `@id`s on every graph save (section 7.5) and appends each id
  a save removes to `wiret.ids`. An undo keeps the ids assigned since, and takes back an id the
  same session retired, so undoing a delete is not `E0140`.
- `wiretc ids --check BASE[..HEAD]` compares the `.wiret` files changed between two Git revisions
  (or BASE and the working tree) and fails if an id disappeared without being retired, or a
  retired id is used again. `--record` appends the missing ones instead.

### Deviations and known gaps

- **Exports.** Every `func` and `event` is exported, so the editor can run any of them. The
  spec exports only `@export` declarations.
- **Later tiers (Tier 1 and 2) are not implemented:** classes,
  delegates and dispatchers, latent nodes and fibers (`Delay`, `Yield`, `Await`), and
  `Try`/`Throw`. Their node kinds are reported as `E0501` and their opcodes are rejected by
  the verifier.
- **Not implemented:** `wiretc merge`, `wiretc edit`, `wiretc diff`, the rest of the
  project manager (`wiret.lock`, `use` of other modules), the C API and deterministic-mode
  float rules.
- **Optimisation.** There is no `-O1`, so the `cont.push`/`cont.pop` pairs are never replaced
  by direct branches.
- **Example layout.** The spec's examples align the `=` signs; the canonical writer does not.
  If it did, adding one longer node id would change every line of the graph, which breaks the
  one-line-diff rule.
- **Example literals.** The math pins in the registry have no declared defaults, so bindings
  such as `b: 0` are kept rather than omitted. This matches the §2.6 examples.

## Layout

```
prototype/
  wiret_editor.py      GUI entry point
  wiretc.py            CLI entry point
  wiret/
    model.py           in-memory model of a module
    parser.py          lexer and parser
    printer.py         canonical writer, semantic and layout hashes
    registry.py        node kinds, pin signatures, type rules
    checker.py         resolver, type checker, graph validator
    compiler.py        macro expansion, lowering, WBC emission
    wbc.py             binary format, opcodes, LEB128
    verifier.py        bytecode verifier
    vm.py              interpreter
    natives.py         std.* and host natives
    disasm.py          disassembler
    flow.py            flow-order reading view
    ops.py             edit operations (section 7.2)
    runner.py          typed arguments and results
    graphview.py       editor canvas
    editor.py          editor application, debugger, lessons menu
    palette.py         searchable node palette and node descriptions
    explain.py         plain-language diagnostics and runtime errors
    std/flow.wiret     std.flow macros (ForRange, Repeat, DoOnce, DoN, FlipFlop)
  lessons/             seven beginner lessons
  examples/demo.wiret
  tests/test_wiret.py
```
