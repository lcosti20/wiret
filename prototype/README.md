# Wiret prototype

A Python prototype of the Wiret graph editor, compiler and runtime, built against
[`docs/reference.md`](../docs/reference.md) (Draft 0.12). It implements **Tier 0** and **Tier 1**
of the spec (section 1.6). It uses only the Python standard library; the editor uses Tkinter, and the Git
commands need `git`.

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
python3 -m unittest discover tests
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

## Running it in a browser

`web/` runs the same compiler and VM in the browser with [Pyodide](https://pyodide.org)
(CPython compiled to WebAssembly). Like the desktop editor, it shows the graph on the left
(pan, zoom, double-click a call to open it) and the Source, Debugger and Problems tabs on the
right. On the canvas you can drag nodes and box titles to move them, drag from a pin to another
pin (or onto a node) to wire them, click a wire or node and press Delete to remove it, and
double-click an input to type its value, and add nodes from the palette (Tab, a double click
on empty canvas, a wire dropped on empty canvas, or the Add node button). Right-click (or press
and hold on a touch screen) for the same context menus as the desktop editor: set an enum
input, make or break a struct, rename, label, colour, notes, boxes, locals, @count and @cases.
Ctrl+Z and Ctrl+Y undo and redo. You can debug with Step (F11),
Over (F10), Back (Shift+F11), Run/Continue (F5), Animate and breakpoints (click the circle at a
node's top-left corner or beside its line number, or press F9). The Tkinter modules, the Git
commands and file watching are left out.

```sh
cd prototype
python3 web/build_web.py                # packs wiret/, lessons/ and examples/ into web/wiret_bundle.zip
python3 -m http.server -d web 8000      # then open http://localhost:8000
```

### Publishing

`.github/workflows/pages.yml` publishes the page to GitHub Pages at
<https://lcosti20.github.io/wiret/>. Every push to `main` runs the tests, builds the site with
`python3 web/build_web.py --site DIR` (the page, its scripts and the bundle, nothing else from
`web/`) and deploys it. Pull requests into `main` run the same tests and build without
deploying. The repository's Pages source must be set to "GitHub Actions" (Settings → Pages).

### How it works

The page calls `wiret/webapi.py`, which takes plain values and returns JSON. A page has no
thread to block at a breakpoint, so `debug_run` runs the program once and records every point
where the debugger could pause (up to 5,000), with the call stack, variables and wire values.
`web/debugger.js` then steps through that recording, forwards and back, pausing where the
desktop editor would: both use the rules in `wiret/debugstate.py`, and a test (which needs
Node.js) checks they agree. The canvas (`web/graphview.js`) draws from `webapi.check`, which describes
each graph with the same titles, pin labels, colors and automatic layout as the desktop canvas
(`wiret/viewmodel.py`). Canvas edits go through `webapi.edit`, which applies the same rules as
the desktop canvas (`wiret/canvasedit.py`: which pins connect, when a Convert node goes in
between, what a typed value may be) and returns the new text in canonical form. `web/` is a static
site, so any static host (GitHub Pages, for example) can serve it. The first visit downloads
about 10 MB of Pyodide from the jsDelivr CDN.

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

The **Lessons** menu opens fourteen short programs from `lessons/`:

1. Hello
2. Variables
3. Decisions
4. Loops
5. Functions
6. FizzBuzz, as a challenge
7. Arrays
8. Structs and enums
9. Maps: counting fruit with `MapFind`, `MapSet` and `ForEachMap`
10. Errors: `Try` around a divide by zero and around a `Throw` of your own
11. Waiting: a countdown event with `Delay` (its `Main` is an event)
12. Objects: `Animal`, `Dog` and `Cat`, an override, and `CallParent`
13. Interfaces: a `Shape` interface on unrelated classes, and one inherited implementation
14. Events: a button's dispatcher, a function and a method as listeners, `Unbind`, and a
    click count kept in the method's `state`

Each one has an intro note and a "Try it" note on the graph. Lessons open as copies in
`my_lessons/` (git-ignored), so the originals never change. **Lessons → Start this lesson over**
restores a copy, and **Start all lessons over…** restores every one you have opened, which is
what to do after updating the prototype if your copies still hold the old lessons. Other files
you saved in `my_lessons/` are left alone.

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
- A `//` comment directly above a declaration, statement, input or flow wire is kept where
  it is. One attached to nothing is never dropped silently: before the first graph edit, the
  editor asks whether to convert it to a note or drop it (`W0603`).
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
| `diff [--raw] A B` | Node-aware semantic diff in flow order: behaviour per graph, then metadata, then layout-only changes. `--raw` is the id-ordered text diff. Exits 1 when the files differ |
| `merge BASE OURS THEIRS [-o OUT]` | Keyed three-way merge (section 7.1); the Git merge driver. Writes OURS unless `-o` is given; exits 1 on a conflict |
| `init-git` | Configure the merge driver and the flow-order `textconv` for `*.wiret`, and a union merge for `wiret.ids` |
| `edit FILE REQUEST.json\|- [--dry-run]` | Apply JSON edit operations (section 7.2); see *Editing protocol* below |
| `ids --check BASE[..HEAD] [--record]` | Every id deleted between two revisions is retired in `wiret.ids`, and none is reused |

## What is implemented

| Area | Status |
| --- | --- |
| Text syntax (2.1–2.4) | Full lexer and parser for `use`, `extern`, `const`, `var`, `enum`, `struct`, `class` (with methods, dispatchers, a base class and `impl`), `interface`, `func`, `event`, `macro`, `local`, `state`, nodes with their inputs in parentheses (`Kind(.pin <- value, ...)`, `Entry()`), nodes written inline in the one input they feed (naming the output they feed in only when they have several), functions written `= value`, `Format "..."` templates, `//` comments attached to what they stand above, semantic `@` attributes, `#[...]` metadata lines (`#[doc]`, `#[note]`, ...) above declarations, and above nodes' and boxes' lines in the layout block, the `flow` block (exec wires) and `layout` (places and boxes). An old `markup` block is rejected with a hint, and an unknown `@` name such as `@doc` is `E0104`. See *Structs and enums*, *Classes*, *Interfaces* and *Delegates and dispatchers* below. |
| Canonical form and hashes (2.5) | Sorted items (struct fields and enum members keep the order written), the `flow` block before the node statements, nodes (a node read by exactly one input, with no exec pins and no `@` attribute, written inline there and named by its path, such as `show.message`), `flow` wires (by source node id, then exec pin order) and layout lines, each with its metadata lines above it (`doc`, `category`, `keywords`, then notes as written); registry pin order; default-valued bindings omitted; 100-column wrapping; attribute ordering. Semantic hash (ignores layout, every `#[...]` line, every `//` comment and `Reroute`) and layout hash. The §2.6 example, which the spec shows in flow order with no alignment, round-trips byte for byte: `wiretc view --flow` of its canonical form is the example exactly (see tests). |
| Node kinds (3.3) | `Entry`, `Return`, `Branch`, `Sequence`, `Switch`, `Select`, `Macro`, `Exit`, `Reroute`, `Get/SetLocal`, `Get/SetVar` (and `const`s), `Get/SetState`, `Call`, `Convert`, all arithmetic, comparison, logic and bit kinds, `Scale`, and the array kinds `MakeArray`, `ArrayGet`, `ArrayLength`, `ArraySet`, `ArrayAdd`, `ArrayInsert`, `ArrayRemove`, `ArrayClear`, the struct kinds, the map and set kinds (see *Maps and sets* below), `Try` and `Throw` (see *Faults* below), the latent kinds `Delay`, `Yield` and `Await` (see *Fibers* below), the class kinds `New`, `GetField`/`SetField` on objects, `Cast` and `IsValid` (see *Classes* below), and `CreateDelegate`, `Invoke`, `Bind`, `Unbind` and `Broadcast` (see *Delegates and dispatchers* below). Types: `bool`, all integer widths, `f32`, `f64`, `string`, `array::<T>`, `map::<K, V>`, `set::<T>`, structs, enums, classes, interfaces, `delegate::<(A) -> (R)>` and `std.Signal`. |
| Execution model (4.2–4.3) | Continuation stack, `Sequence` push/pop, macro inlining with path-style ids (`loop/test`, `loop!in`), `Exit` as a jump, joins, evaluation points with per-point sharing, impure output slots, `@pure` and `@reads` calls as pure nodes, per-expansion `state`. The §4.2 `SumTo(2)` trace is reproduced exactly (see tests). |
| Diagnostics (4.7) | E0101, E0102, E0103, E0110, E0111, E0120, E0121, E0150, E0151, E0152, E0160, E0201 (latency), E0301, E0302, E0304, E0310, E0320, E0401, E0412, E0501, E0502, E0503, W0201, W0203, W0301, W0302, W0601, W0602, W0603, W0604, W0605. |
| Lowering (4.8) | `-O0`: one labelled block per impure node, `local.tee` for shared values, `cont.push`/`cont.pop` kept. Output closely matches the §5.8 listings. |
| WBC (5.2–5.4) | Type (function, `5E` array and `5F` struct entries), Import, Function, Global, Export, Data and Code sections, plus custom sections `name`, `wr.debug`, `wr.pins`, `wr.pure`, `wr.meta` (hashes and export mode), `wr.caps` and `wr.graph` (deflated canonical source). Export modes as in 5.2: a normal `wiretc build` exports only what is marked `@export` (funcs, events, methods, `var`s, and struct, class and interface types; an enum has no type entry to export, so `@export` on one is warning `W0203`), each with flag bit 3; `wiretc build --export-all`, which `wiretc run`, `wiretc replay`, the editor and the browser version use, also exports every func, event and method, without bit 3. `LoadedModule.declared` holds the bit-3 names. |
| Verifier (5.5) | One linear pass: decoding, branch targets, empty stack at labels, operand typing (including `struct.new`/`get`/`with` and the lane instructions), returns, `max_stack`, latency/purity flags. Type references may point forward, but a struct may not hold itself by value. Fuzz-tested. |
| Lane types (3.1.1) | `vec2`, `vec3`, `quat` and `transform`: tuple literals, struct nodes, component-wise arithmetic, `Scale`, composition, `std.vec`/`std.quat`/`std.transform`, lane instructions in the `FB` prefix space and container flag bit 1. See *Vectors, rotations and transforms* below. |
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

An enum value is written `Mode::Chase`: on a pin (`.b <- Mode::Flee`), as a default
(`mode: Mode = Mode::Idle`) and in `@cases(Mode::Idle, Mode::Chase)`. It never reads like a wire,
so a node may be called `Mode` too. The dotted `Mode.Chase` of earlier drafts is still read where
the graph has no node called `Mode`, and `wiretc fmt` rewrites it. A missing enum or member is
`E0501`, and a value of the wrong enum is `E0110`.

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
- `wiretc run` takes enum arguments as `Mode::Chase` and prints results as
  `Vec2 { x: 1.0, y: 1.5 }` and `Mode::Chase`, and the debugger shows values the same way.
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

### Vectors, rotations and transforms

`vec2`, `vec3`, `quat` and `transform` (Draft 0.13, section 3.1.1) are built-in structs with
fixed `f32` fields that the VM holds unboxed, so vector math in a per-frame graph never
allocates.

```
const Up: vec3 = (0, 1, 0)
var spawn: transform = ((0, 2, 0), (0, 0, 0, 1), (1, 1, 1))

func Step(p: vec3, v: vec3, dt: f32) -> (r: vec3) @pure = Add::<vec3>(
  .a <- p,
  .b <- Scale::<vec3>(
    .v <- v,
    .s <- dt,
  ),
)
```

- **Literals** are tuples, nested for a transform, on pins and as `const`, `var`, field,
  parameter, `local` and `state` values. A tuple of the wrong length is `E0110`. The defaults
  are the zero vectors, the identity rotation `(0, 0, 0, 1)` and the identity transform (scale
  `(1, 1, 1)`), and so is the "zero value" a missing map key or an unbound `Exit` output gets.
- **Struct nodes** work on them unchanged: `MakeStruct vec3`, `BreakStruct quat`,
  `GetField vec3.y`, `GetField transform.rotation`, `WithField transform.scale`. A struct or enum
  named `vec3` is `E0102`.
- **Operators.** `Add Sub Mul Div Min Max Neg Abs` are component-wise on `vec2` and `vec3`;
  the new kind `Scale::<T>` multiplies a vector by an `f32`; `Mul::<quat>` and
  `Mul::<transform>` compose, `b` first and then `a`; `Eq`/`Ne` compare components (NaN is
  never equal); `Select` and map keys take all four. Any other type argument is `E0110`.
  `Convert` goes between `vec2` and `vec3` and to text, and `Format` writes them, as
  `(1.0, 2.5, 3.0)`.
- **Library.** `std.vec` (`Dot`, `Length`, `LengthSquared`, `Distance`, `Normalize`, `Lerp` and
  `Reflect`, each `::<vec2>` or `::<vec3>`, plus `Cross` and `PerpDot`), `std.quat` (`Rotate`,
  `Conjugate`, `Inverse`, `Normalize`, `FromAxisAngle`, `Slerp`, `Angle`) and `std.transform`
  (`Apply`, `ApplyVector`, `Inverse`), with `std.math.Acos`. A generic one without its type
  argument is `E0502`. `Normalize` of a zero vector gives zero, never a fault.
- **Bytecode.** Type codes `76` to `73`, container flag bit 1 (the verifier refuses lane types
  without it), and the lane instructions in the `FB` prefix space: `v3.add` is `FB 23`. Struct
  nodes lower to `v3.make`, `v3.get f` and `v3.with f`, the arithmetic kinds to their lane
  instruction, and the library functions that have one (`Dot`, `Cross`, `Rotate`, `Apply`, ...)
  to it instead of a call, so `Step` above runs in six instructions and six units of fuel.
  `FromAxisAngle`, `Slerp` and `Angle` are natives; in deterministic mode they use the bundled
  `Sin`, `Cos` and `Acos`.
- **Values.** A lane value is a tuple of floats in the VM and through `vm.call`, rounded to
  `f32` after every operation, in the order section 3.1.1 writes each formula. `wiretc run` takes
  them as `(1, 2, 3)` and prints them in the same form, and the disassembler names the field of
  each `get` and `with`.

Not yet in the prototype: `std.quat.FromEuler` and its `EulerOrder` enum (a standard-library
enum needs cross-module enums), and a lesson. The palette lists every node above; lane pins
use the struct colour.

### Maps and sets

`map::<K, V>` and `set::<T>` are value types that keep insertion order (section 3.1). Keys and
set items are primitives, enums, or structs of those (`E0501` otherwise). The pins follow the
array kinds (section 3.3):

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
  is copy-on-write (see *Copy-on-write* below). Updating a key keeps its position.
- Every NaN key is the same key, so a NaN can be looked up again (section 3.1).
- `std.flow.ForEachMap::<K, V>` loops over a map in key order with outputs `key`, `value` and
  `index`. The palette offers map and set nodes for the map and set types the module uses.
- `wiretc run` takes a map as `{"a": 1}` and a set as `[1, 2]`.
- `Eq` and `Ne` take any value type (section 4.9). Arrays compare element-wise; maps and sets
  ignore insertion order (the same keys, and for a map equal values under each). Each element
  uses its own type's equality, so a container holding NaN is not equal to itself, but keys
  match as they do in a lookup, so two sets that each hold NaN are equal. Structs that hold
  containers compare field by field as before.
- Container equality calls `std.array.Equals`, `std.set.Equals` or `std.map.Equals`. Each takes
  two `anyref` (`6D`), so one native signature serves every element type; the verifier accepts
  any reference where `anyref` is expected, and allows `anyref` only in function types. The
  natives declare a fuel cost of 1 per 8 elements visited (section 5.7).

### Faults: `Try` and `Throw`

The first Tier 2 item (section 4.6). `Try` has the exec outputs `body`, `fault` and `then` and
the data outputs `message: string` and `code: i32`; `Throw` takes `message` and `code`.

```
node t = Try()
node ok = Return(
  .q <- Div::<i32>(
    .a <- entry.a,
    .b <- entry.b,
  ),
)
...
flow {
  t.body -> ok
  t.fault -> bad     // bad can read t.message and t.code
}
```

- `Try` pushes `then` as a continuation, then a handler marker above it, and runs `body`. A
  chain end in the body discards the marker and resumes `then`. A fault unwinds to the
  nearest marker, frame by frame, so a fault in a called function reaches the caller's `Try`;
  the continuations above the marker are dropped, the operand stack is cleared, and `fault`
  runs with `then` still pending. So `then` runs after either chain, like the code after a
  try/catch. A `Throw` inside `fault` goes to the next `Try` out.
- Uncaught faults end the call with `WR_ERR_FAULT`, the message, the code and the node-level
  traceback. Fuel exhaustion and an interrupt are not faults and cannot be caught.
- Built-in faults have negative codes, so they never collide with a program's own
  non-negative `Throw` codes: -1 divide by zero, -2 index out of range, -3 null reference,
  -4 failed cast, -5 stack overflow (call or continuation stack), -6 an error from a native,
  -7 `unreachable`.
- `E0412`: nothing outside the body may wire into it, the body may not lead back to its own
  `Try`, and a macro's `Try` body may not reach an `Exit` (it would carry the marker into the
  caller's chain). Loops, joins and macros inside the body are fine.
- Bytecode: `try.push L local` (`0C`) and `throw` (`0E`), and the value type `fault` (`6A`),
  allowed only in locals and native signatures. `Throw` calls the internal native
  `std.fault.Make(message, code)`, and the handler reads the fault back with
  `std.fault.Message` and `std.fault.Code`, since the instruction set has no opcodes for
  that. The tracer and debugger show a marker on the continuation stack as `t!fault`.

### Fibers: `Delay`, `Yield` and `Await`

The second Tier 2 item (sections 4.5 and 6.8). An `event` is latent; a `func` that waits is
declared `@latent` after its signature (`func Wait(s: f64) @latent { ... }`).

| Node | Pins | Waits until |
| --- | --- | --- |
| `Delay` | in `seconds: f64` | that much virtual time has passed |
| `Yield` | none | the next `advance` |
| `Await` | in `signal: std.Signal` | the signal is fired |

- `E0201`: a func that is not `@latent` may not contain a latent node, call a latent func or an
  event, or expand a macro that does any of these. `E0302`: a func is never both `@latent` and
  `@pure` or `@reads`.
- Each lowers to `suspend` (`0D`, kind 0 yield, 1 timer, 2 signal), which the verifier allows
  only in latent functions and only with its own operand on the stack.
- In the VM every call runs on a `Fiber`, which owns its frames, locals, operand stack and
  continuation stacks; `suspend` saves them and returns to the scheduler, and resuming carries
  on at the next instruction with every frame intact, `Try` markers included.
- The Python API stands in for section 6.8: `vm.call` (a non-latent function, never
  suspends), `vm.start(mod, name, args, now=False)` (`wr_start`, or `wr_call` on a latent
  export with `now=True`), `vm.advance(dt)`, `vm.fire(signal)`, `vm.kill(fiber)`,
  `vm.next_wake()`, `vm.time` and `vm.on_fault`. A fiber has `status` (`READY`, `RUNNING`,
  `SUSPENDED`, `DONE`, `FAULTED`), `results` and `error`.
- Scheduling is deterministic. `advance(dt)` moves time on, then runs every fiber that is
  runnable at the new time, ordered by when it became runnable, then by creation order; each
  gets a fresh fuel budget and runs until it suspends, finishes or faults. A fiber made
  runnable during an advance (a fire, a `Yield`, a zero `Delay`) waits for the next one, so
  one advance always ends. A negative or NaN `Delay` waits 0 seconds.
- Signals: `std.Signal` is a handle type, allowed for parameters, results, locals, state and
  variables but not as a struct field or container item, and with no `Eq`. Its default is
  null; `Await` on a null signal is a fault (code -3, catchable). The natives
  `std.signal.New()` and `std.signal.Fire(signal)` make and fire signals from Wiret; a host
  fires one with `vm.fire`. A fire wakes the fibers waiting at that moment, in the order they
  began waiting, and is not remembered.
- A fault in a fiber run by `advance` marks it `FAULTED`, calls `on_fault`, and does not stop
  the others.
- `wiretc run` and the editor's Run run a latent function or event to the end, jumping
  straight to the next timer, and stop with `WR_YIELD` if it waits for a signal that nothing
  is left to fire. `wiretc run` then prints the virtual time it finished at.

### Classes

The third Tier 2 item (sections 2.2, 3.1, 3.3, 5.3 and 5.6). A class is a reference type with
fields, methods and single inheritance:

```
class Boss : Player {
  rage: i32 = 3

  func Describe() -> (text: string) { ... }
}
```

- **Methods are items.** The parser lifts each `func` and `event` out of its class into a
  module item named `Class.Method` (`Player.TakeDamage`) with `owner` set, and the printer
  writes it back inside the class. So diagnostics, exports, `wiretc edit`, merge, diff, the id
  registry and the editor's graph list all treat a method like any other graph. A method takes
  an implicit first parameter `self`, an output of its `Entry`. Canonical order inside a class:
  fields as written (they are the object layout), then funcs, then events, each by name.
- **Nodes.** `New Player` (impure: it makes an identity) has `result`. `GetField` and
  `SetField` name `Class.field` (`GetField Player.health`, as in section 2.6); inside a method
  the bare field name of its own class is also read, and the formatter writes it qualified.
  `GetField` on an object has `reads` purity, so it is evaluated at each consumer. `Cast Boss` and `IsValid` take any object (`anyref`):
  `Cast` gives `result` (null when the object is not a `Boss`) and `ok`. `Eq` and `Ne` on a
  class compare identity. `null` is the class literal.
- **Calls.** `Call Player.TakeDamage` has `self` as its first input. A method that is not
  `@final` is called through the vtable (`call_virtual`), so the object's own override runs;
  `Call Boss.TakeDamage` finds an inherited method. A subclass flows into a base-class pin,
  and any object into `anyref`; never the other way (`E0110`).
- **Checks.** `E0151`: a base that is not a class of the module, or an inheritance cycle.
  `E0102`: a field declared twice along the chain. `E0150`: an override whose parameters,
  results or latency differ from the method it replaces, or that replaces a `@final` method.
  `@pure` may not read object fields (`E0304`); `@pure` and `@reads` may not set them or make
  objects (`E0302`).
- **Bytecode.** The `5B` class type entry (flags 0, superclass, no interfaces yet, own fields
  with defaults, full vtable: the superclass's slots with overrides in place, then new methods
  by name), and `class.new`/`get`/`set`, `ref.null`/`is_null`/`eq`/`test`/`cast`/`valid` and
  `call_virtual`. `class.get` indexes the whole layout, inherited fields first. The verifier
  checks the hierarchy, each vtable against its superclass's, receiver types and subtyping;
  `select` on two references gives their common type, which is how `Cast` is lowered without
  a branch (`ref.test`, `select` against `ref.null`, `ref.cast`). The `name` section gains a
  fourth vector after the globals: per class, its type index, name and field names.
- **VM.** An object is an `Obj` with a class and a field list. A null `GetField`, `SetField`
  or method call faults with code -3, catchable with `Try`; a failed `ref.cast` with -4. The
  host side has `vm.new(mod, "Player")`, `obj.get("health")` / `obj.set(...)`, and
  `vm.call_method(mod, obj, "TakeDamage", [args])`, which dispatches like `wr_push_virtual`.
- **State on the object.** `state` in a method, and the state of a macro expanded in one
  (`DoOnce`, `FlipFlop`), lives on each object: hidden slots after the class's fields and
  dispatchers, named `Tick.count` or `Greet/once.done` (`obj.get("Tick.count")` reads one).
  A free function's state stays a module global.
- **Fields as places.** The array, map and set mutators change a field of an object:
  `ArrayAdd::<i32> Player.items` with `.obj` and `.item`, or `ArrayAdd::<i32> items` inside
  Player's own methods when no local or variable has that name. The field is read without
  being shared, changed (in place when nothing else holds it), and written back; a null `obj`
  faults with -3. `@pure` and `@reads` functions may not do this (`E0302`).
- **`CallParent Tick`**, inside an override, runs the base class's version of the method on
  the same object, as a direct `call` (Blueprint's Parent node). Its pins are the method's,
  without `self`. Outside an override it is `E0501`.
- `wiretc run file Player.TakeDamage 30` and the editor's Run give a method a new object of
  its class as `self`. The palette and the Add menu have a Classes section. Class
  declarations are edited in the Source pane.

### Interfaces

The fourth Tier 2 item (sections 2.2, 3.3, 5.3 and 5.6).

```
interface Damageable {
  func Hit(amount: i32) -> (left: i32)
  func Name() -> (name: string)
}

class Barrel impl Damageable { ... }
class Door : Prop impl Damageable, Openable { ... }
```

- An interface lists method signatures, in the order written: a method's position is its
  dispatch slot, so the canonical form never sorts them. An interface is a reference type
  (`null` by default) usable wherever a class is.
- A class implements an interface by having a `func` of each name with the same parameters
  and results, its own or inherited from a base class (`E0152` otherwise, and for an `event`
  or a `@latent` func). A class also implements its bases' interfaces. An `impl` name that is
  not an interface is `E0151`. A class flows into a pin of an interface it implements, and an
  interface into `anyref`; never back without `Cast` (`E0110`).
- `Call Damageable.Hit` takes `self: Damageable` and lowers to `call_interface`, which runs
  the receiver's class's implementation; a null receiver faults with -3. `Cast Damageable`
  checks whether an object implements it. `Eq` compares identity.
- **Not latent.** An interface method cannot be `@latent` in this prototype (`E0501`), and
  the verifier rejects a latent implementation: the `5A` entry records only function types,
  so a non-latent caller could not know that `call_interface` might suspend.
- **Bytecode.** The `5A` interface entry holds one function type per method, without the
  receiver. A class entry lists every interface it implements, inherited ones included, with
  the function implementing each method, so dispatch never walks the hierarchy. The verifier
  checks that each implementation takes this class or a base as its receiver and has the
  method's signature, and that a class keeps its superclass's interfaces; a class is a
  subtype of the interfaces it lists. Interface names are in the `name` section's class
  vector, with no fields.
- The palette and the Add menu list each interface's methods under Call and a Cast to it;
  `@id` prefixes are `cls_` for classes, `if_` for interfaces and `im_` for interface methods.
  Merge treats interface methods as keyed members, with the signature as one field.

### Delegates and dispatchers

The last Tier 2 language item (sections 2.2, 3.1, 3.3, 5.3 and 5.6).

```
class Player {
  dispatcher OnHit(amount: i32)
  ...
}

node bind = Bind Player.OnHit(
  .obj <- player,
  .handler <- CreateDelegate Counter.Add(     // a method: its object is the target
    .target <- counter,
  ),
)
node fire = Broadcast Player.OnHit(
  .obj <- entry.self,
  .amount <- 5,
)
```

- **Delegates.** `delegate::<(i32) -> (bool)>` is a reference type: a function plus, for a
  method, the object it was made with. `CreateDelegate F` (pure) takes no inputs for a free
  function and `target` for a method; its type follows from the function's signature, without
  the receiver. A method delegate calls the target's own override, as a method call does.
  `Invoke::<D>` has the inputs `delegate`, `arg0`, `arg1`, ... and the outputs `result0`, ...;
  a null delegate faults with -3. Delegates have no `Eq`. A written `-> ()` is dropped, so
  `delegate::<(i32) -> ()>` and `delegate::<(i32)>` are the same type.
- **Waiting.** Invoking never suspends the caller. A delegate of an event starts the event on
  a fiber of its own, queued for the next `advance`; a `@latent` func cannot be made a
  delegate (`E0501`), nor can a native or extern.
- **Dispatchers.** `dispatcher OnHit(amount: i32)` is a class member: every object gets an
  empty handler list of its own. `Bind` and `Unbind` take `obj` and a
  `handler: delegate::<(i32)>`; `Broadcast` takes `obj` and the dispatcher's parameters by
  name. Binding a handler that is already bound (the same function and object) does nothing,
  so a `Bind` that runs twice adds it once; `Unbind` removes it. A broadcast runs the handlers
  bound when it starts, in bind order. A handler's fault does not stop the others: it is
  added to `vm.handler_faults` and passed to `vm.on_handler_fault`. Running out of fuel still
  stops everything. `Bind`, `Unbind`, `Broadcast` and `Invoke` are not allowed in `@pure` or
  `@reads` functions (`E0302`). A dispatcher's name is unique among the class's members.
- **Order and layout.** Inside a class: fields, then dispatchers (both as written), then
  methods. In the object, each class's dispatchers follow its fields.
- **Bytecode.** The `59` delegate and `58` dispatcher type entries, and `delegate.new`
  (`F4 func flags`: bit 0 binds a receiver, bit 1, new here, binds the receiver's override),
  `call_delegate` (`09`, a function type), and `dispatcher.bind`, `.unbind` and `.broadcast`
  (`F5` to `F7`) on the dispatcher a `class.get` reads from the object. `delegate.new` names no
  type, so the verifier finds the module's delegate type for the function's signature.
- **Host.** `vm.delegate(mod, "Counter.Add", obj)`, `obj.get("OnHit").handlers`, and
  `vm.broadcast(mod, obj, "OnHit", [args])`.

### Copy-on-write

Containers keep value semantics (section 4.9) without eager copies, so a loop that appends to
an array costs the same per item however long the array gets (100,000 appends take about
0.3 s in this VM).

- In the VM an array is a `CArray` (a list) and a map or set a `CMap` (a dict), each with a
  `shared` flag. A mutating instruction changes an unshared container in place and returns
  it, and changes a fresh copy of a shared one; the copy is unshared. `array.new`,
  `array.clone` and every mutator's result start unshared. `ref.share` (`2B`) sets the flag.
- The compiler emits `ref.share` after any container input whose consumer can keep the
  value: `SetLocal`, `SetVar`, `SetField`, call and delegate arguments, `Return`, struct and
  array construction, macro inputs (so `ForEach` iterates the array as it was when the loop
  started), `Select`, and so on. Read-only consumers do not share: `ArrayGet`, `ArrayLength`,
  the map and set queries, and `Eq`/`Ne`. A mutation node reads its own place directly, so it
  never marks it.
- Default and zero containers (a new local, a field's starting value, a missing map value)
  are one object each, created shared, so the first change to one copies it.
- Fuel is charged for what is allocated, 1 per 8 elements: `array.new`, `array.clone`, and a
  mutation only when it copies.
- The host still sees tuples and dicts: arguments are converted in, results converted out.

### Capabilities

Sections 2.4, 6.5 and 7.3. An `extern func` names the capability it needs:

```
extern func host.Log(message: string) @capability("console.write")
```

- The compiler lists the capabilities of the imports a module uses in `wr.caps` (an extern
  nothing calls is not imported, so it asks for nothing). `wiretc caps FILE` and
  `module_capabilities(bytes)` read them without loading anything, and the disassembly starts
  with them.
- **Loading checks grants.** A module that needs a capability the VM has not granted fails to
  load with `WR_ERR_LINK`, naming it. A native can also be registered with the capability it
  needs (`NativeSpec(..., capability="console.write")`, as `host.Log` is); an import of it
  needs that grant whether or not its `extern` says so, so leaving the attribute off does not
  get around a grant.
- **Who grants.** The `VM` class is both the runtime and the reference host. `VM()` grants
  what its own host natives need (`console.write` for `host.Log`), so the editor, `wiretc run`
  and the examples work as before. `VM(capabilities=[])` is a sandbox that grants nothing
  until `vm.grant("...")` (`wr_grant`). `wiretc run --sandbox --grant console.write ...` does
  the same from the command line.
- **Build time.** In a project whose `wiret.toml` has a `[capabilities]` table, a capability
  its `allow` list does not name is `E0160` from `wiretc check`, `wiretc build` and the
  editor. A manifest with no such table does not restrict anything. The manifest is read with
  `tomllib` where Python has it (3.11 and later), else with a small reader for this table.
- `@capability` belongs on an `extern func` and takes one string (`E0104` otherwise).

### Deterministic mode

Section 4.10. `VM(deterministic=True)` (`WR_CFG_DETERMINISTIC`) promises that the same
`.wbc`, configuration and input log give the same results, faults, instruction counts, fuel and
output, which is what replays, lockstep networking and save-game reproduction need.

- **Floating point.** Python floats are IEEE binary64 with round to nearest even, and the VM
  never fuses a multiply and add or keeps extra precision. `f32` arithmetic is done in binary64
  and rounded once to binary32, which gives the correctly rounded result for `+ - * /` and
  `Sqrt` (binary64 has more than twice binary32's precision). `Min` and `Max` return NaN if
  either input is NaN and order `-0` before `+0`; `Eq` with a NaN is false. Integer to `f32`
  conversions now round once (a 64-bit integer used to go through `f64` first, which could
  land one `f32` step off); that was wrong in any mode. Reinterpreting a float's bits gives the
  canonical quiet NaN's bits for every NaN, so NaN payloads and signs are never observable.
- **Bundled `std.math`.** `Sin`, `Cos`, `Tan`, `Exp`, `Log`, `Pow` and `Atan2` do not use the
  platform's `libm`, whose last bits differ between systems. `wiret/detmath.py` computes each
  in Python's `decimal` arithmetic (specified exactly and implemented in software, so the
  digits are the same everywhere) to 60 digits, then rounds once to binary64, which is almost
  always the correctly rounded value. Arguments are reduced modulo 2π exactly, so even
  `Sin(1e22)` is right. Special values (zeros, infinities, NaN) follow C99 Annex F, as `libm`
  does. Outside the mode `std.math` uses `libm`.
- **Natives.** A `NativeSpec` has `deterministic=True` unless it reads something outside the
  VM (a clock, input, files). A deterministic VM refuses to register one that is not
  (`WR_ERR_LINK`).
- **The input log.** Every API call (`load`, `grant`, `signal`, `call`, `start`, `advance`,
  `fire`, `kill`, `new`, `call_method`, `delegate`, `broadcast`) is recorded in
  `vm.input_log` as plain JSON: the arguments, the result or the fault, the instructions run,
  the fuel left, and the lines printed. Floats are written in hex so they are exact; objects,
  signals, fibers, delegates and the module are handles numbered in the order the log met
  them, which is why a host signal must come from `vm.signal()`. `load` records the module's
  SHA-256.
- **Replay.** `replay(wbc_bytes, log)` runs the log again on a new deterministic VM and raises
  `ReplayMismatch` at the first entry whose result, fault, instruction count, fuel or output
  differs. `wiretc run --deterministic --record LOG.json FILE FUNC` records a run (a faulting
  one too), and `wiretc replay FILE LOG.json` checks it.
- `vm.interrupt()` still works, but marks the run non-replayable
  (`vm.stats["replayable"]`), since an interrupt does not come from the log.

### Identity and the id registry

A **project** is a directory with a `wiret.toml` (section 7.3); its `wiret.ids` lists every
retired id, one `module graph kind id` line each (`game.demo TakeDamage node set_new`, or
`game.demo - id fn_k3f9` for an `@id`).

- `wiretc fmt --assign-ids` gives an `@id` to every declaration, parameter, result, field, enum
  member, local and state slot that has none, and never changes an existing one.
- Inside a project, `wiretc check` and the editor also report `E0140` (a retired node, box or
  `@id` used again), `E0102` (an `@id` used twice among siblings) and `W0202` (an element without
  an `@id`). A lone file, such as a lesson, gets none of these and needs no `@id`s (section
  2.4).
- Inside a project the editor writes `@id`s on every graph save (section 7.5) and appends each id
  a save removes to `wiret.ids`. An undo keeps the ids assigned since, and takes back an id the
  same session retired, so undoing a delete is not `E0140`.
- `wiretc ids --check BASE[..HEAD]` compares the `.wiret` files changed between two Git revisions
  (or BASE and the working tree) and fails if an id disappeared without being retired, or a
  retired id is used again. `--record` appends the missing ones instead.

### Editing protocol

`wiretc edit` takes `{"if_hash": "<layout hash>", "ops": [...]}` (`wiretc hash` prints the
layout hash) and prints a JSON reply: `ok`, the new `hash`, every diagnostic, a unified `diff`,
the wires a cascading delete removed, and the ids it retired in `wiret.ids`. A stale `if_hash` is
`E0900`, and a failing op rejects the whole request with the op's index; nothing is written.

| Op | Fields |
| --- | --- |
| `create_node` | `graph`, `kind`, optional `id`, `symbol`, `targs`, `attrs`, `bindings` ({pin: value}), `execs` ({pin: "target[.pin]"}), `x`, `y` |
| `bind` / `unbind` | `graph`, `node`, `pin`, and for `bind` a `value` |
| `wire_exec` / `unwire_exec` | `graph`, `from` ("node[.pin]"), and for `wire_exec` a `to` |
| `set_attr` / `remove_attr` | a target, and `attr` ("@count(3)") or `name` |
| `set_meta` / `remove_meta` | a target, and `meta` ('#[doc("...")]') or `name` (and `text`, for one note) |
| `place` | `graph`, `node` (a node or box), optional `x`, `y`, `props` ({key: value}), `members` |
| `delete_node` | `graph`, `node`, optional `cascade`; refused while wired, unless `cascade` |
| `rename` | `id` (an `@id`) and `to`; or `graph`, `node` and `to` for a node id |

A value is written as on the right of `<-`: `"plus.result"`, `"5"`, `"\"hi\""`, `"Mode::Chase"`.
A target is `graph` and `node` (a node or box), `graph` alone, or `decl` (any declaration).
`set_meta` with a note adds one; with any other name it replaces it. Renaming by `@id` rewrites
every reference: calls and macro uses, type names, struct and field symbols, enum values and
`@cases`, `Entry` pins and call-site bindings for parameters, `Return` bindings and call-site
pins for results, and flow wires for a macro's exec parameters and results.

### Merging

`wiretc merge` parses the three versions and merges them by key (section 7.1):

- Declarations are matched by `@id`, else by kind and name; parameters, results, fields,
  members, locals and state slots by `@id`, else by name, within their owner; nodes by id.
  An element without an `@id` is matched to one that has gained an id on the other side, so
  `wiretc fmt --assign-ids` on one branch does not look like a rename.
- Each element merges per field: a node's kind, symbol, each type argument, each attribute,
  each binding and each exec output; a declaration's name, type, default and attributes. A
  field changed on one side takes that change; changed differently on both sides, it is a
  conflict. Deleted on one side and changed on the other is a conflict; deleted and unchanged,
  it is deleted.
- A rename by `@id` is carried into the other side: references it added under the old name are
  rewritten, so a function renamed on one branch and called on another merges cleanly.
- Layout never blocks: positions and properties merge one by one, box `members` as a set, and
  when both sides changed the same property, theirs is kept and a notice is printed.
- `doc`, `category` and `keywords` are one field each; notes merge as a list keyed by text, and
  both sides replacing the same note differently is a conflict.
- Conflicts are written as markers around the lines where the two sides differ: one line each
  for a binding, attribute or wire, and the whole node for a node deleted on one side. Then the
  result is checked, and errors that neither side had are reported as semantic conflicts.
- If a side does not parse, it falls back to `git merge-file` and says so.

### Deviations and known gaps

- **Tier 2 in this prototype:** the language features are done (`Try`/`Throw`, fibers,
  classes, interfaces, delegates and dispatchers), and so are copy-on-write and capabilities.
  The prototype exists to show Wiret as a language, so the embedding and infrastructure items
  are out of its scope: the C API (the `VM` class's Python methods stand in for it), the
  project manager (`wiret.toml` dependencies, `use` of other modules and linking against
  their declared exports, `wiret.lock`, `WR_LOAD_LAZY_LINK` and `wr_link`), and debugger hooks as a host API (the
  editor has its own debugger). A module is one file.
- **No `ref.share` removal.** Without `-O1` there is no liveness analysis, so a function that
  builds a local array and returns it still shares it, and the caller's first change to it
  makes one copy. The
  editor's debugger steps through one fiber, the one Run started.
- **Classes, not yet:** extern (host) types.
- **Deterministic mode, not yet:** a logical heap limit (`max_heap_bytes`); the prototype has
  no memory limit at all. Cross-platform golden traces (section 7.4) are a claim for real
  implementations; this VM is one implementation on one interpreter.
- **Optimisation.** There is no `-O1`, so the `cont.push`/`cont.pop` pairs are never replaced
  by direct branches.
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
  lessons/             fourteen beginner lessons
  examples/demo.wiret
  tests/test_wiret.py
```
