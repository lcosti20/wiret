# Wiret
A text-based visual scripting language

## Why Wiret exists

Wiret is designed for a very specific problem: visual scripting is powerful for authoring graphs, but it is awkward for version control, automated review, tooling, and AI-assisted generation. Most visual languages are stored in editor-private formats or binary layouts, which makes them hard to diff, hard to validate, and hard to reason about outside an IDE.

Wiret aims to keep the strengths of a visual graph language while making the source form readable, stable, and tool-friendly.

### The core idea

A Wiret program is a graph, but the graph is serialized as text.

This gives Wiret several benefits:

- Git-friendly diffs: node additions, removals, and rewires are plain-text changes
- Canonical output: the same graph serializes the same way everywhere
- Better collaboration: layout metadata and semantic metadata are separated cleanly
- Easier LLM workflows: prompts and code generators can inspect or create graph logic as text
- Editor portability: the text form is not tied to one proprietary editor format
- Verification and tooling: the compiler can parse, validate, lower, and verify the graph before execution

## Design rationale

### 1. Text-first, not editor-first

The source of truth is text, not the graph editor state.

This is a deliberate choice. Editor metadata should describe presentation and not define meaning. A graph editor may move nodes around, change colors, or collapse sections without changing the program semantics. That separation is essential for sensible collaboration and stable diffs.

By storing graphs as text, Wiret avoids the usual problem that visual scripting systems are “easy to edit” but hard to review or merge.

### 2. Graph semantics are explicit

Wiret does not rely on hidden editor inference or implicit layout behavior.

Inputs and outputs are explicit. Types are explicit. Node IDs are stable. Conversions are explicit. Exec wiring is explicit. This keeps the language precise enough to compile and verify.

The goal is to be expressive without being ambiguous. A graph written in Wiret should not rely on editor interpretation to be valid.

### 3. A graph is still a program, not just a diagram

A visual scripting language is often criticized because it can become little more than drag-and-drop orchestration. Wiret is designed to be capable of general programming, not merely event flow or toy automation.

That means it includes:

- typed values
- structured data types
- functions and events
- dispatchers and interfaces
- containers and standard library primitives
- macro expansion and compile-time inlining
- host-native integration through imports and registered functions

It is still graph-native, but it is not restricted to a purely visual scripting mindset.

### 4. Metadata is part of the source model

Wiret distinguishes between semantic attributes and editor metadata.

Examples:

- `@pure`, `@export`, `@count`, `@disabled` affect semantics
- `@ed(...)`, `@doc(...)`, `@category(...)` help tooling and editors

This separation makes source control safer. A contributor can move a node or change its color without accidentally altering the runtime behavior.

### 5. Canonical serialization matters

A text format is only useful if multiple tools write the same bytes for the same graph.

Wiret therefore defines a canonical form:

- deterministic ordering
- stable attribute order
- node IDs drive ordering and merge behavior
- formatter output is normalized
- semantic and layout hashes can be computed from the canonical text

This is crucial for:

- clean Git diffs
- merge tooling
- CI validation
- editor/editor synchronization
- stable AI generation output

## Design trade-offs

### Trade-off: explicitness vs convenience

Wiret prefers explicitness over magical inference.

Examples:

- type arguments are always written
- conversion nodes are visible and explicit
- data and exec flows are distinct
- default values are not silently relied upon unless the graph clearly names them

This makes the language slightly more verbose than an editor that guesses missing data, but it is far easier to compile and review.

### Trade-off: graph readability vs compiler simplicity

The language favors a canonical, graph-IR-like syntax rather than a visually “pretty” free-form layout.

This means the file may not always be the most human-pleasant representation for a graph editor. But it does make the graph machine-readable, diffable, and reliable.

### Trade-off: rich metadata vs simple semantics

Wiret includes editor metadata and reflection metadata intentionally, which means the language has more surface area than a minimal DSL.

This increases design complexity, but it enables:

- UI tooling
- node labels and comments
- stable editor state
- rich host reflection

Without this metadata layer, a text-based graph language would be difficult to use effectively in real editors.

### Trade-off: compact binary format vs human readability

The bytecode format is intentionally compact and structured, inspired by WASM and JVM-style design.

This is good for runtime efficiency and verification, but it means the source format and the runtime representation are not identical. That gap is expected: source is for humans and tools, bytecode is for execution, verification, and embedding.

### Trade-off: strong typing vs low-friction authoring

Wiret is strongly typed and verified.

This is sometimes more demanding than ad hoc visual scripting, especially for non-programmers. However, it is necessary to make the language safe to embed, deterministic to run, and dependable in large collaborative codebases.

## Contributor guidance

When contributing to Wiret, keep these principles in mind:

- preserve the separation of semantic vs editor metadata
- favor explicit types and explicit conversions over implicit behavior
- keep node IDs stable and descriptive
- keep the canonical formatting rules intact
- prefer metadata and attributes that survive round-trips
- avoid hidden editor-only assumptions in the compiler
- ensure any design addition remains compatible with verification and bytecode generation

## Suggested contribution areas

Good first contributions include:

- grammar and parser improvements
- canonical formatter fixes
- validation diagnostics
- type-checking rules
- bytecode verifier enhancements
- standard-library macro definitions
- debugger metadata support
- editor integration and source export tools

## Summary

Wiret is designed to be the textual representation of a visual programming language without losing the discipline required for serious engineering.

The project makes deliberate trade-offs:

- explicit over implicit
- deterministic over ad hoc
- stable over editor-private
- verified over permissive
- text-first over UI-first

That is what makes Wiret practical as a source format, a compiler target, and an embeddable runtime language.
