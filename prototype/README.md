# Wiret prototype

A Python prototype of the Wiret graph editor, compiler and runtime, built against
[`docs/reference.md`](../docs/reference.md) (Draft 0.4). It targets **Tier 0** of the spec
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
python3 -m unittest discover tests              # 48 tests
```

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

The **Lessons** menu opens seven short programs from `lessons/`:

1. Hello
2. Variables
3. Decisions
4. Loops
5. Functions
6. FizzBuzz, as a challenge
7. Arrays

Each one has an intro note and a "Try it" note on the graph. Lessons open as copies in
`my_lessons/` (git-ignored), so the originals never change. **Lessons → Start this lesson over**
restores a copy.

Loops use the built-in `std.flow` macros (`ForRange`, `Repeat`, `ForEach`, `DoOnce`, `DoN`, `FlipFlop`).
They are written in Wiret in `wiret/std/flow.wiret`, as section 3.4 describes, and are
available to every module as `Macro std.flow.ForRange` and so on.

| Action | How |
| --- | --- |
| Add a node | Tab or double-click (search), or right-click empty canvas → category menus |
| Wire | Drag from a pin to a pin, or onto a node to use its first compatible pin |
| Wire with a type mismatch | A visible `Convert<From, To>` node is inserted for you (section 7.5) |
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
- Notes are kept even when the node they point at is deleted (shown as detached, `W0604`).
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
| `view --flow FILE` | Reading view with nodes in flow order |
| `schema --json` | The node registry |

## What is implemented

| Area | Status |
| --- | --- |
| Text syntax (2.1–2.4) | Full lexer and parser for `use`, `extern`, `const`, `var`, `func`, `event`, `macro`, `local`, `state`, nodes, bindings, exec maps, attributes, `notes` and `layout` (places and boxes). `enum`/`struct`/`interface`/`class` are rejected with a clear error. |
| Canonical form and hashes (2.5) | Sorted items, nodes, notes and layout lines; registry pin order; default-valued bindings omitted; 100-column wrapping; attribute ordering. Semantic hash (ignores layout, notes, docs and `Reroute`) and layout hash. |
| Node kinds (3.3) | `Entry`, `Return`, `Branch`, `Sequence`, `Switch`, `Select`, `Macro`, `Exit`, `Reroute`, `Get/SetLocal`, `Get/SetVar` (and `const`s), `Get/SetState`, `Call`, `Convert`, all arithmetic, comparison, logic and bit kinds, and the array kinds `MakeArray`, `ArrayGet`, `ArrayLength`, `ArraySet`, `ArrayAdd`, `ArrayInsert`, `ArrayRemove`, `ArrayClear`. Types: `bool`, all integer widths, `f32`, `f64`, `string`, `array<T>`. |
| Execution model (4.2–4.3) | Continuation stack, `Sequence` push/pop, macro inlining with path-style ids (`loop/test`, `loop!in`), `Exit` as a jump, joins, evaluation points with per-point sharing, impure output slots, `@pure` and `@reads` calls as pure nodes, per-expansion `state`. The §4.2 `SumTo(2)` trace is reproduced exactly (see tests). |
| Diagnostics (4.7) | E0101, E0102, E0103, E0110, E0111, E0120, E0121, E0201, E0301, E0302, E0304, E0401, E0501, E0502, W0201, W0301, W0302, W0310, W0320, W0601, W0602, W0603, W0604. |
| Lowering (4.8) | `-O0`: one labelled block per impure node, `local.tee` for shared values, `cont.push`/`cont.pop` kept. Output closely matches the §5.8 listings. |
| WBC (5.2–5.4) | Type, Import, Function, Global, Export, Data and Code sections, plus custom sections `name`, `wr.debug`, `wr.pins`, `wr.pure`, `wr.meta` (hashes), `wr.caps` and `wr.graph` (deflated canonical source). |
| Verifier (5.5) | One linear pass: decoding, branch targets, empty stack at labels, operand typing, returns, `max_stack`, latency/purity flags. Fuzz-tested. |
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
- `Convert<X, string>` and float `Rem` lower to calls to internal `std.convert.*` and
  `std.math.FRem*` natives, since the instruction set has no opcodes for them.

### Deviations and known gaps

- **Exports.** Every `func` and `event` is exported, so the editor can run any of them. The
  spec exports only `@export` declarations.
- **Later tiers (Tier 1 and 2) are not implemented:** structs, enums, classes, `set` and `map`,
  delegates and dispatchers, latent nodes and fibers (`Delay`, `Yield`, `Await`), and
  `Try`/`Throw`. Their node kinds are reported as `E0501` and their opcodes are rejected by
  the verifier.
- **Project-level features are not implemented:** the `wiret.ids` registry, `wiretc merge`,
  `wiretc edit`, the C API and deterministic-mode float rules. `@id` attributes are kept
  but not generated automatically.
- **Optimisation.** There is no `-O1`, so the `cont.push`/`cont.pop` pairs are never replaced
  by direct branches.
- **Saturation for narrow types.** Converting a float to a narrow integer type truncates
  toward zero and then wraps. It does not saturate to the narrow type's range.
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
