# Wiret

Wiret is a text-first visual programming language designed to keep the strengths of graph-based authoring while making programs readable, reviewable, and tool-friendly.

Instead of treating a visual editor as the source of truth, Wiret stores graphs as canonical text. That means you get the benefits of visual workflows without sacrificing version control, static validation, compiler tooling, and AI-friendly authoring.

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
