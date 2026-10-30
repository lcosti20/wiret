# Wiret

Wiret is a text-first visual programming language designed to keep the strengths of graph-based authoring while making programs readable, reviewable, and tool-friendly.

Instead of treating a visual editor as the source of truth, Wiret stores graphs as canonical text. That means you get the benefits of visual workflows without sacrificing version control, static validation, compiler tooling, and AI-friendly authoring.

Example:

![Tkinter UI/graph editor](https://github.com/user-attachments/assets/14bebc8d-d113-47aa-847a-6ae164ac1443)

```wiret
wiret 1
module lessons.variables

extern func host.Log(message: string)

func Main() {
  local score: i32
  node as_text = Convert<i32, string>(value: now.value)
  node bonus = SetLocal score (value: plus.result) -> show
  node entry = Entry -> start
  node line = Call std.string.Concat(a: "Your score is ", b: as_text.result)
  node now = GetLocal score
  node old = GetLocal score
  node plus = Add<i32>(a: old.value, b: 5)
  node show = Call host.Log(message: line.result)
  node start = SetLocal score (value: 10) -> bonus
  notes {
    note add_note on plus "Add reads the score (10) and adds 5."
    note intro "Lesson 2: Variables. A local variable (here: score) is a named box that holds one value. SetLocal puts a value in the box. GetLocal reads what is in the box right now."
    note text_note on as_text "Log needs text, so Convert turns the number into text."
    note try_it "Try it: (1) Step through (F11) and watch the Variables panel in the Debugger tab: score changes from 0 to 10 to 15. (2) Change the bonus: double-click pin b on the Add node and type 100."
  }
  layout {
    as_text at (600, 320)
    bonus at (560, 0)
    entry at (0, 0)
    line at (780, 180)
    now at (440, 420)
    old at (180, 260)
    plus at (360, 160)
    show at (980, 0)
    start at (200, 0)
  }
}
```

## Why Wiret?

Most visual scripting systems are excellent for authoring, but awkward for:

- code review and diffs in Git
- automated validation and CI
- canonical serialization
- editor portability
- LLM-assisted generation and editing
- compiler verification and runtime safety

Wiret was designed to address exactly that gap. It keeps the graph model, but makes the underlying representation explicit, deterministic, and human-readable.

## Core ideas

- Text is the source of truth
- Graph semantics are explicit
- Types, pins, conversion rules, and execution wiring are all visible
- Layout and editor metadata are separated from runtime meaning
- Serialization is canonical, stable, and diff-friendly
- The language is meant to compile, verify, and run, not just draw boxes

## Features

- Graph-based programming with a text representation
- Strongly typed semantics
- Explicit data and execution flow
- Deterministic canonical formatting
- Compiler and verifier pipeline
- Editor/debugger prototype built in Python/Tkinter
- Support for standard-library-style macros and reusable graph logic
- Bytecode generation and interpreter runtime

## Repository layout

- `docs/reference.md` — language reference and design notes
- `prototype/` — prototype editor, compiler, runtime, examples, and tests
- `LICENSE` — MIT license
- `README.md` — project overview

## Prototype status

This repo contains a working prototype of the language and tooling, built around the draft reference specification in `docs/reference.md`.

It includes:

- a Tkinter visual graph editor
- a text parser and source serializer
- compiler and bytecode generation
- validation and diagnostics
- a reference VM for execution and debugging
- sample lessons and example programs

## Quick start

Requirements:

- Python 3.10+
- Tkinter (for the editor UI)

Run the prototype:

```bash
cd prototype
python3 wiret_editor.py
```

Open a sample graph or run from the CLI:

```bash
cd prototype
python3 wiret_editor.py examples/demo.wiret
python3 wiretc.py run examples/demo.wiret Main
python3 -m unittest discover tests
```

## Example workflow

The prototype supports a full loop of editing and execution:

```text
graph editor <-> demo.wiret --compile--> demo.wbc --load/verify/link--> VM
```

This enables:

- editing a graph in the UI
- syncing the graph back to canonical source text
- compiling to bytecode
- loading and verifying the compiled form
- stepping or running the program in a debugger

## Design principles

Wiret intentionally favors explicitness over implicit behavior:

- explicit types instead of hidden inference
- explicit conversions instead of magical coercion
- stable IDs and metadata instead of editor-only assumptions
- deterministic output instead of ad hoc formatting
- verification and toolability instead of permissive ambiguity

This makes the source form more reliable in code review, testing, and long-term engineering workflows.

## Contribution areas

Good places to contribute include:

- grammar and parser improvements
- formatter and canonicalization fixes
- validation and diagnostics
- type-checking rules
- bytecode verifier enhancements
- standard library macro definitions
- editor integration and source export tooling
- debugger and runtime experiences

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.

## Summary

Wiret is a practical experiment in making visual programming behave like a real software artifact: readable, reviewable, robust, and compiler-friendly.

It aims to be the textual representation of a graph language without sacrificing the discipline required for serious engineering.
