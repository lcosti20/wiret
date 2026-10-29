---
title: "Schema and Serialization for Text-Based Visual Programming Languages"
document_type: "Research note"
formatted: 2026-10-28
---

# Schema and Serialization for Text-Based Visual Programming Languages

Schema and serialization define how a visual programming language represents its programs as persistent data. They determine how a graph of nodes, pins, connections, types, and properties is validated, saved to disk, reconstructed in memory, compared in version control, and exchanged with other tools.

For a text-based visual programming language, this is more than a file-format decision. The serialization format is often the bridge between the visual graph, the textual representation, the compiler, the editor, and AI-driven tools. A well-designed format allows each of these components to manipulate the same program without losing information or producing unnecessary changes.

The central design question is:

> How should a visual program be represented so that it is unambiguous, easy to validate, efficient to process, robust across versions, and understandable in a text diff?

## Contents

- [1. The problem domain](#1-the-problem-domain)
- [2. Schema versus serialization](#2-schema-versus-serialization)
- [3. The major serialization approaches](#3-the-major-serialization-approaches)
- [4. Representing a graph in a schema](#4-representing-a-graph-in-a-schema)
- [5. What the schema should define](#5-what-the-schema-should-define)
- [6. Stable identifiers and referential integrity](#6-stable-identifiers-and-referential-integrity)
- [7. Deterministic serialization and version-control diffs](#7-deterministic-serialization-and-version-control-diffs)
- [8. Preserving visual layout without polluting program semantics](#8-preserving-visual-layout-without-polluting-program-semantics)
- [9. Schema evolution and migration](#9-schema-evolution-and-migration)
- [10. Unknown fields, extensions, and forward compatibility](#10-unknown-fields-extensions-and-forward-compatibility)
- [11. Default values, optional fields, and information loss](#11-default-values-optional-fields-and-information-loss)
- [12. Serialization and AI-generated edits](#12-serialization-and-ai-generated-edits)
- [13. An illustrative schema design](#13-an-illustrative-schema-design)
- [14. A recommended architecture](#14-a-recommended-architecture)
- [15. Testing and measuring the design](#15-testing-and-measuring-the-design)
- [16. Final recommendation](#16-final-recommendation)

## 1. The problem domain

A conventional visual programming environment might store a program as a proprietary binary document or a large JSON object. This can work well for an editor, but becomes cumbersome when the program needs to be reviewed, generated, transformed, or maintained as source code.

A text-based visual programming language introduces several requirements at once.

**Persistence and reconstruction**

The saved representation must contain enough information to rebuild the intended program, including connections, types, defaults, metadata, and any editor state that needs to survive reopening.

**Structural and semantic validation**

The system must distinguish malformed files from structurally valid files that describe an invalid program, such as an incompatible connection or a reference to a nonexistent node.

**Readable and stable diffs**

A small logical edit should ideally produce a small textual change. Reordering unrelated nodes, changing whitespace, or opening and saving a file should not create hundreds of irrelevant lines of diff.

**Evolution and interoperability**

Programs should remain usable when the language gains new node types, properties, or features. Other tools should be able to inspect or transform supported parts of a program without needing the entire editor.

**Machine and AI friendliness**

The representation should be easy for parsers, formatters, code generators, and language models to produce correctly. Its grammar should discourage ambiguous references and redundant information.

These requirements overlap, but they are not identical. A compact binary format can be efficient yet difficult to review. A readable text format can be pleasant to edit yet difficult to evolve safely. Schema design is the process of balancing these trade-offs.

## 2. Schema versus serialization

These concepts are related but should not be conflated.

- **Schema:** Defines what data is valid, including fields, types, required properties, constraints, identifiers, and relationships.
- **Serialization:** Converts an in-memory program into a persistent representation.
- **Deserialization:** Parses that representation and reconstructs the corresponding data structures.
- **Validation:** Determines whether the reconstructed data satisfies structural and semantic rules.
- **Canonicalization:** Converts equivalent representations into one standardized form.
- **Migration:** Converts a document written under an older schema into a newer representation.

For example, a schema might specify that a `Multiply` node has two numeric input pins and one numeric output pin. Serialization determines how the node and its connections are written to a file. Validation checks that the pins and connections are legal. Migration handles changes if a later version renames a pin or changes the node's representation.

A useful architecture separates these responsibilities rather than embedding all of them in one parser.

## 3. The major serialization approaches

There are several ways to encode the same visual program. It is important to distinguish the schema language from the document encoding: JSON Schema describes JSON data, whereas Protocol Buffers defines both a schema language and serialization encodings.

JSON + JSON Schema

**Strong default for structured storage**

JSON stores the document; JSON Schema describes and validates its structure. The format is widely supported and easy to inspect, generate, and process.

*Source: json-schema.org (+1 more)*

Best when interoperability, editor tooling, and straightforward implementation matter more than minimizing file size.

Protocol Buffers (Protobuf)

**Strong for compact data exchange**

A typed schema defines messages, which can be encoded into a compact binary representation or mapped to JSON. Stable field numbers and compatibility rules support schema evolution.

*Source: protobuf.com (+1 more)*

Best when efficient network transfer, generated types, and strict message contracts are priorities. Binary output is less convenient for ordinary Git diffs.

YAML

**Human-oriented configuration**

YAML provides indentation-based structured data and supports features such as aliases. It can reduce punctuation and visual noise, but its parsing rules and presentation flexibility require careful constraints when deterministic output is important.

*Source: IETF*

Best when people manually author configuration or relatively small graph documents. Restricting the accepted YAML subset can make tooling more predictable.

**TOML**

TOML is designed for readable configuration, with explicit key-value pairs and tables. It is less natural for deeply nested graphs and arbitrary collections of interconnected objects.

Best for project settings, compiler options, and editor preferences rather than a complete visual program.

**Custom textual syntax**

A purpose-built language can represent nodes, connections, and values using domain-specific constructs instead of generic data structures.

Best when the textual representation is itself a first-class programming language, particularly when developers and AI systems are expected to edit it directly. It requires more investment in grammar design, diagnostics, tooling, and migration.

**CBOR and other compact encodings**

CBOR provides a compact binary representation of structured data. Similar binary formats can be useful for transport, caches, snapshots, and embedded environments.

Best when size or parsing performance is more important than native text diffs. A separate human-readable source representation is usually desirable for source-controlled programs.

### Comparative evaluation

| Criterion | JSON + schema | Protobuf binary | YAML | Custom text |
| --- | --- | --- | --- | --- |
| Human readability | Good | Poor | Very good | Potentially excellent |
| Git diffs | Good with canonicalization | Poor without decoding | Good with normalization | Excellent if designed for it |
| Structural validation | Strong with JSON Schema | Strong, typed messages | Requires schema/tooling | Depends on implementation |
| Type safety | Runtime schema validation | Generated typed structures | External validation needed | Grammar and semantic checks |
| Schema evolution | Explicit versioning and migration | Mature compatibility conventions | Explicit versioning and migration | Entirely design-dependent |
| AI generation | Good | Poor for raw binary | Good | Potentially excellent |
| Implementation effort | Low–medium | Medium | Low–medium | High |
| Compactness | Moderate | Excellent | Moderate | Variable |

These are general tendencies, not guarantees. For example, a well-canonicalized JSON document can have excellent diffs, while a custom language with unstable generated identifiers can produce terrible ones.

## 4. Representing a graph in a schema

A visual program is not simply a nested tree. It is a graph containing objects with identities and references to other objects. This distinction has major consequences for serialization.

Consider a simple multiplication graph:

```text
Input "A" = 6 ──┐
                ├──► multiply (A × B) ──► Output "Result" = 42
Input "B" = 7 ──┘
```

The serialization must describe at least:

- Node identity and node type.
- Pin identity or a stable way to identify each pin.
- Values assigned to input pins.
- Connections between output and input pins.
- Type information, either explicitly stored or deterministically derived.
- Optional visual properties, such as node position and display state.
- Schema version and any required language or plugin version information.

There are two principal representation strategies.

### Strategy A: Nodes with explicit edges

```json
{
  "format": "example-graph",
  "version": 1,
  "nodes": [
    {
      "id": "a",
      "type": "constant",
      "value": 6
    },
    {
      "id": "b",
      "type": "constant",
      "value": 7
    },
    {
      "id": "mul",
      "type": "multiply"
    }
  ],
  "edges": [
    {
      "from": [
        "a",
        "value"
      ],
      "to": [
        "mul",
        "a"
      ]
    },
    {
      "from": [
        "b",
        "value"
      ],
      "to": [
        "mul",
        "b"
      ]
    }
  ]
}
```

Advantages:

- Connections are explicit and easy to inspect.
- Nodes can be reordered without changing their meaning.
- Graph algorithms can operate directly on node and edge collections.
- A connection change can be represented independently of the nodes.

Disadvantages:

- Each edge needs valid endpoint references.
- Pin names and identifiers must remain stable or be migrated.
- The document can become verbose for graphs with many connections.

### Strategy B: Connections embedded in input pins

```json
{
  "nodes": [
    {
      "id": "mul",
      "type": "multiply",
      "inputs": {
        "a": {
          "from": [
            "a",
            "value"
          ]
        },
        "b": {
          "from": [
            "b",
            "value"
          ]
        }
      }
    }
  ]
}
```

Advantages:

- Connections are close to the input they drive.
- The representation can be intuitive for tree-like or expression-oriented graphs.
- Editing an input's connection is localized.

Disadvantages:

- Enumerating all edges requires traversing the graph.
- Bidirectional graph operations may be less convenient.
- Repeated references and cyclic graphs still need explicit identity rules.

**Recommendation:** For a general-purpose visual programming language, start with explicit node identities and explicit connections, even if the surface syntax later presents connections in a more compact form.

A further distinction is essential: execution order should normally be derived from graph semantics, not from the order in which nodes happen to appear in a serialized list.

## 5. What the schema should define

A good schema defines the contract of the document without duplicating every rule of the programming language.

### Recommended schema layers

**Layer 1 — Document envelope**

Format identifier, schema version, language version, feature declarations, and document metadata.

**Layer 2 — Graph structure**

Nodes, node IDs, pins, edges, endpoint references, subgraphs, and graph-level properties.

**Layer 3 — Node definitions**

Allowed node types, pin signatures, required fields, default values, and node-specific data.

**Layer 4 — Semantic rules**

Type compatibility, execution constraints, cardinality, cycle restrictions, variable resolution, and language-specific invariants.

**Layer 5 — Presentation metadata**

Node positions, canvas zoom, comments, collapsed groups, and optional editor-specific state.

The first four layers describe what the program is and what it means. The last describes how it is presented.

This separation makes it possible to open a graph in a different editor, compile it without a graphical interface, or change the layout without changing program behavior.

### Structural versus semantic validation

JSON Schema can enforce rules such as:

- A node has a string ID and a string type.
- A document contains a node array.
- A numeric field contains a number.
- A property is required or has an allowed value.

However, many graph invariants are cross-referential or semantic. For example, JSON Schema alone is not the right place to implement a complete graph type checker that resolves node references, checks every connection, and infers generic types. JSON Schema is primarily a declarative mechanism for validating document structure and constraints.

*Source: json-schema.org (+1 more)*

Use a layered validation pipeline:

1. Parse the file and report syntax errors.
2. Validate the document against its structural schema.
3. Resolve node types, pins, and references.
4. Validate graph invariants and type compatibility.
5. Run language-specific checks, such as control-flow restrictions.
6. Compile or execute only after the relevant checks succeed.

This also allows an editor to display partially completed graphs while still distinguishing incomplete work from a malformed file.

## 6. Stable identifiers and referential integrity

Identifiers are among the most consequential decisions in a graph format because they affect editing, serialization, diffing, merging, and AI-generated modifications.

Consider three common approaches:

| Identifier strategy | Example | Main trade-off |
| --- | --- | --- |
| Sequential IDs | `node-1`, `node-2` | Readable, but insertion and regeneration policies can cause churn |
| Random persistent IDs | `n-7f2c...` | Stable across edits, but verbose and less readable |
| Content-derived IDs | Hash of node contents | Useful for immutable data, but difficult when nodes are edited or duplicated |

For editable graph nodes, persistent identity is usually preferable to identity derived from content. If a node changes from multiplying two values to adding them, it is still the same logical node. Its identity should not need to change.

A practical design might use short, stable IDs for source-authored documents and opaque persistent IDs for editor-created nodes. The particular representation matters less than the identity rules.

Those rules should answer the following:

- Is an ID unique across the entire project or only within a graph?
- Does duplicating a node create new IDs for the node and all of its owned pins?
- Can a node ID survive a rename, move, or change in node type?
- How are references repaired when a node is deleted?
- Can two independently edited branches create conflicting IDs?

### Connection integrity

Every connection should reference existing endpoints, and the language should define whether a pin permits zero, one, or many incoming connections.

For instance, a multiply node might accept exactly one connection per input pin, whereas a collection input might accept multiple incoming edges.

The validator should reject or diagnose:

- References to nonexistent nodes.
- References to nonexistent pins.
- Connections from input to input or output to output.
- Type-incompatible connections.
- Multiple incoming connections where only one is permitted.
- Duplicate edges when duplicates are not meaningful.
- Cycles where the language prohibits them.

Not every cycle is an error. A dataflow language might prohibit combinational cycles but allow cycles through delay nodes or explicit feedback constructs. The schema establishes what can be represented; the semantic rules establish what it means.

## 7. Deterministic serialization and version-control diffs

For a source-controlled visual language, determinism is a first-class requirement.

Two equivalent in-memory graphs should serialize to the same canonical output, provided they are equivalent under the format's explicitly defined normalization rules.

This is related to, but not identical to, byte-for-byte preservation of the original source.

### What canonical serialization should guarantee

1. A stable ordering for nodes, edges, and other unordered collections.
2. A consistent ordering of object properties, where the chosen format permits it.
3. Consistent number, string, escaping, and newline conventions.
4. No generated timestamps, random IDs, or transient editor data in the semantic source.
5. Stable omission or inclusion rules for default values.
6. No duplicate representations of the same fact.

The JSON Canonicalization Scheme (JCS), specified by [RFC 8785](https://www.rfc-editor.org/rfc/rfc8785.html), standardizes a deterministic JSON representation useful for hashing and signing. It does not, by itself, establish semantic equivalence between different graph documents or determine the correct ordering of graph nodes.

*Source: RFC Editor (+1 more)*

For Git, a pretty-printed canonical format is often more useful than compact canonical JSON. The system can apply deterministic ordering while retaining indentation and line breaks designed for human review.

### Example: noisy versus meaningful diffs

Suppose a user changes a node's constant from `6` to `8`.

A poor serializer might regenerate every node ID, reorder the entire node array, and rewrite all metadata. The diff would show dozens of changes for one logical edit.

A well-designed serializer would ideally show only:

```text
- "value": 6
+ "value": 8
```

The goal is to minimize irrelevant changes, not necessarily the total number of changed bytes.

### Important caveat: canonicalization can hurt readability

Sorting every node by ID may make output deterministic, but it can make related nodes harder to locate. Likewise, forcing every object property into alphabetical order can be less readable than placing `id`, `type`, `inputs`, and `position` in a deliberate order.

A good format distinguishes:

- **Semantic ordering:** ordering that affects program meaning.
- **Canonical ordering:** ordering selected for reproducible output.
- **Presentation ordering:** ordering chosen to help humans understand the program.

These policies should be documented separately.

## 8. Preserving visual layout without polluting program semantics

Visual programming has an additional complication that ordinary source languages do not: the layout can be important to the human reader without affecting execution.

A useful model separates semantic data from presentation data.

**Semantic graph**

Node types, IDs, connections, literal values, types, control flow, and program properties.

Changing this data can change program behavior.

**Presentation graph**

Positions, sizes, colors, comments, collapsed state, and editor-specific annotations.

Changing this data should not change program behavior.

There are three common approaches:

- **Single document:** Store both semantic and presentation data in one file. This simplifies sharing and backup, but layout-only changes appear in the same diffs as logic changes.
- **Separate files:** Store the semantic graph and layout independently. This produces cleaner semantic history but requires a stable mapping between them.
- **Embedded optional metadata:** Keep layout in the graph document under a dedicated metadata field or namespace. This is a useful compromise, provided tools know which fields are semantic.

For a VS Code-based graph editor, a practical default is to keep the graph in one canonical, human-readable source file and include layout metadata in a clearly separated section. Split the files only if layout churn becomes a demonstrated problem.

One subtle issue is that layout changes can be legitimate edits: a developer may intentionally arrange nodes to communicate execution flow. Therefore, the correct goal is not to discard layout, but to make its effects distinguishable from changes to program semantics.

## 9. Schema evolution and migration

A serialization format is a long-lived interface. Once programs are checked into repositories, the format cannot be treated as an implementation detail.

Imagine a version 1 graph with a node called `multiply`. In version 2, the language renames its input pin from `a` to `left`.

If the new editor simply expects `left`, old documents may stop loading. Worse, a naïve loader might silently ignore the old field and replace it with a default, changing the program.

A migration system should handle this deliberately.

### Recommended versioning model

Use a document-level schema version distinct from the language's semantic version and the editor's version.

For example:

```json
{
  "format": "example-graph",
  "schemaVersion": 2,
  "languageVersion": "1.4",
  "nodes": []
}
```

These fields represent different contracts:

- `schemaVersion` describes the serialized document structure.
- `languageVersion` describes the language rules and features under which the program is interpreted.
- The editor version identifies the application release, if that information is needed for diagnostics or reproducibility.

Do not require every file to match the exact version of the editor that created it.

### Migration rules

A robust migration system should:

1. Detect the input version before interpreting version-specific fields.
2. Apply explicit, ordered migrations from old formats to the current in-memory model.
3. Preserve values and unknown extensions whenever safe.
4. Report lossy migrations instead of silently discarding information.
5. Avoid rewriting files merely because they were opened.
6. Test migrations against real historical fixtures.
7. Support a documented failure mode for future or unsupported versions.

For example:

```text
v1 document
 ↓
v1 → v2 migration
 ↓
current graph model
 ↓
structural and semantic validation
 ↓
editor or compiler
```

The reverse direction is a separate capability. Reading an older format does not automatically mean a newer document can be safely saved back to it.

### Compatibility is multidimensional

Compatibility should be evaluated across at least three dimensions:

- **Read compatibility:** Can a new implementation load an old document?
- **Write compatibility:** Can an implementation emit documents an older implementation understands?
- **Round-trip compatibility:** Can an implementation load and save a document without losing its meaning or unsupported data?

Protobuf is instructive here: its evolution rules include stable field numbers and reserved deleted fields. Its unknown-field behavior also shows why merely accepting an unfamiliar field is not sufficient if a later transformation drops it.

*Source: Protocol Buffers Documentation (+1 more)*

For a visual language, unknown node types and extension fields deserve particular attention. An editor might be able to preserve an unfamiliar node as an opaque object even if it cannot execute or display that node correctly.

## 10. Unknown fields, extensions, and forward compatibility

A real programming environment will eventually encounter features that its current implementation does not understand.

Examples include:

- A graph created with a newer version of the language.
- A node supplied by a third-party extension.
- Custom metadata written by another editor.
- A new property introduced by a future schema version.

The format must define what happens in these cases.

There are three broad strategies.

| Strategy | Behavior | Risk |
| --- | --- | --- |
| Reject unknown data | Refuse to load the document | Prevents accidental corruption, but limits interoperability |
| Ignore unknown data | Load recognized fields and discard the rest | Opening and saving can destroy information |
| Preserve unknown data | Retain unrecognized fields or opaque nodes | More implementation complexity, but better round-trip behavior |

For extensible visual programming environments, preservation is generally the most useful strategy for noncritical extensions, with explicit restrictions on whether the document can be edited or executed.

A useful distinction is between unknown syntax and unknown semantics. An editor may understand the structure of an unknown node without understanding what the node does. It can preserve and perhaps display that node, but should not assume it can safely compile or execute it.

### Opaque-node preservation

A node with an unknown type could be represented internally as:

- Its original node type identifier.
- Its raw properties.
- Its connections.
- Its optional layout metadata.
- Any extension-specific data the loader cannot interpret.

The editor could then display a placeholder and warn that the node's implementation is unavailable.

This approach is especially valuable when a graph depends on optional plugins. However, connections and pin information must be preserved exactly enough to avoid breaking the graph when the plugin becomes available again.

Security qualification: Preserving unknown data does not mean trusting it. Unknown executable behavior, external references, and plugin-provided content must not run automatically.

## 11. Default values, optional fields, and information loss

A deceptively difficult schema-design question is whether a field should be omitted when it contains its default value.

Suppose a node has a `visible` property with a default of `true`.

These documents may appear equivalent:

```json
{"id": "n1", "visible": true}
```

```json
{"id": "n1"}
```

But they are equivalent only if the schema guarantees that an omitted `visible` property always means `true`.

Now suppose a later version changes the default to `false`. The meaning of the second document changes unless its language version or schema migration preserves the old interpretation.

This leads to several recommendations:

- Define defaults explicitly in versioned node definitions.
- Distinguish an absent field from an explicit `null` when the language needs that distinction.
- Avoid relying on application-specific defaults that are not part of the format contract.
- Decide whether defaults are materialized during serialization or omitted.
- Make migration behavior explicit when defaults change.

There is no universally correct choice between explicit and implicit defaults. Explicit values improve self-containment and can make diffs clearer when a default changes. Omitted defaults reduce verbosity and can make generated documents more compact.

For AI-generated source, explicit values may be preferable for properties that materially affect behavior, while stable, unambiguous defaults can be omitted to reduce noise.

## 12. Serialization and AI-generated edits

For an AI-friendly visual language, the schema is also a constraint system for generated modifications.

A model might need to add a node, connect two pins, change a constant, or rename a variable. The serialization format determines how much unrelated information the model must reproduce and how easy it is to detect an invalid edit.

Consider two approaches.

**Whole-document generation**

The model produces a complete graph document. This is straightforward, but large graphs consume more tokens, and a small mistake can damage unrelated sections.

**Structured graph operations**

The model produces a set of operations against an existing graph:

```json
{
  "operations": [
    {
      "op": "set_property",
      "node": "n42",
      "property": "value",
      "value": 8
    }
  ]
}
```

A graph-aware engine resolves `n42`, checks that the property exists, validates the value, and commits the edit if it is legal.

The second approach can reduce token consumption and the risk of unrelated changes. It also makes it easier to provide targeted error messages and retry failed operations.

However, the operation format introduces its own contract: operations need preconditions, failure semantics, transaction boundaries, and a clear policy for concurrent edits.

### Schema design principles for AI

1. Use explicit discriminators. A `type` field should unambiguously identify a node's variant.
2. Prefer stable references. Use persistent IDs rather than array indexes to identify nodes.
3. Keep the grammar regular. Avoid multiple interchangeable ways to express the same construct.
4. Make required fields predictable. Different node types should have well-defined property requirements.
5. Separate data from presentation. A model modifying logic should not have to rewrite node positions.
6. Validate edits before committing them. Structural correctness is not sufficient; check references and graph semantics.
7. Return actionable diagnostics. Identify the offending node, property, or connection and explain the constraint that failed.
8. Support localized edits. Let tools modify one node or edge without regenerating the entire document.

These principles complement the design of an AI-friendly grammar: the schema constrains valid structures, while the text syntax determines how easily those structures can be expressed.

## 13. An illustrative schema design

The following is a conceptual JSON Schema fragment for a graph document. It demonstrates document-level validation, not a complete production schema.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": [
    "format",
    "schemaVersion",
    "nodes",
    "edges"
  ],
  "properties": {
    "format": {
      "const": "example-graph"
    },
    "schemaVersion": {
      "type": "integer",
      "minimum": 1
    },
    "nodes": {
      "type": "array",
      "items": {
        "type": "object",
        "required": [
          "id",
          "type"
        ],
        "properties": {
          "id": {
            "type": "string",
            "minLength": 1
          },
          "type": {
            "type": "string",
            "minLength": 1
          },
          "properties": {
            "type": "object"
          },
          "position": {
            "type": "object",
            "properties": {
              "x": {
                "type": "number"
              },
              "y": {
                "type": "number"
              }
            },
            "required": [
              "x",
              "y"
            ]
          }
        }
      }
    },
    "edges": {
      "type": "array",
      "items": {
        "type": "object",
        "required": [
          "from",
          "to"
        ],
        "properties": {
          "from": {
            "$ref": "#/$defs/endpoint"
          },
          "to": {
            "$ref": "#/$defs/endpoint"
          }
        }
      }
    }
  },
  "$defs": {
    "endpoint": {
      "type": "object",
      "required": [
        "node",
        "pin"
      ],
      "properties": {
        "node": {
          "type": "string"
        },
        "pin": {
          "type": "string"
        }
      }
    }
  }
}
```

This schema checks that the document has the expected shape. It does not guarantee that node IDs are unique, that edge endpoints refer to existing nodes, or that the referenced pins exist. Those checks require additional validation logic.

A production schema would also need to specify unknown-field handling, extension points, node-specific variants, numeric constraints, and version-dependent rules.

For current JSON Schema guidance, consult the [official specification](https://json-schema.org/specification).

*Source: Specification (+1 more)*

## 14. A recommended architecture

For a text-based visual programming language intended for Git, IDE integration, and AI-assisted editing, a suitable starting point is this architecture:

*Figure: recommended architecture*

- **Canonical text document** — Versioned source, stable IDs, explicit connections
- **Parser and serializer** — Deterministic formatting, precise source locations, lossless handling where required
- **Versioned graph model** — Nodes, pins, edges, properties, extensions, layout metadata
- **Validation and migration** — Schema checks, ID resolution, type checking, migration, diagnostics
- **Graph editor** — Layout, interaction, visual rendering
- **Compiler and tools** — Code generation, analysis, AI edits

The central principle is that the editor and compiler should share a well-defined graph model rather than inventing separate interpretations of the file.

The text file remains the persistent source of truth. The editor's in-memory representation can be optimized for interaction, but serialization should be a deliberate transformation into the stable public format.

For incremental editing, the parser may additionally maintain source spans or a concrete syntax tree, allowing it to preserve comments, whitespace, and formatting where practical. A plain abstract syntax tree often discards those details.

## 15. Testing and measuring the design

A schema and serializer should be tested as rigorously as a compiler.

| Test | Required property |
| --- | --- |
| Round-trip test | Serialize → deserialize → serialize produces stable output |
| Semantic preservation | Saving and reopening preserves graph meaning |
| Canonicalization | Equivalent graphs produce identical canonical output |
| Diff quality | Small edits produce localized diffs |
| Migration | Historical documents migrate without unintended semantic changes |
| Unknown-field preservation | Supported extension data survives an edit/save cycle |
| Invalid-reference testing | Missing nodes and pins produce clear diagnostics |
| Fuzz testing | Malformed or adversarial input does not crash the parser |
| Large-graph testing | Load, validation, serialization, and editing remain practical at target scale |
| Cross-version testing | Documents behave predictably across supported implementations |

Round-trip tests deserve special care. Byte-for-byte equality is not always the right criterion when the parser intentionally normalizes formatting. Instead, test both canonical output stability and semantic equivalence.

For an AI-friendly format, add measures such as:

- Number of tokens needed to express a typical graph.
- Frequency of malformed model-generated documents.
- Frequency of unresolved node and pin references.
- Number of unrelated lines changed by a localized edit.
- Recovery success after validation errors.
- Percentage of unknown extension data preserved across tool boundaries.

These metrics make the trade-offs measurable instead of relying only on subjective impressions of readability.

## 16. Final recommendation

For most new text-based visual programming languages, the recommended approach is to choose a canonical, human-readable text format backed by an explicit, versioned graph schema.

The concrete implementation depends on whether the text syntax itself is intended to be the language's primary interface.

- If the language is primarily a structured document format, use JSON plus JSON Schema as a practical starting point.
- If the language is intended to be authored directly by humans and AI, consider a purpose-built textual grammar with a rigorously defined graph model.
- If compact storage or network transfer is important, consider a separate binary encoding such as Protobuf or CBOR, while retaining a readable source representation.
- If visual layout matters to users, preserve it explicitly but separate it conceptually from executable semantics.

The most important design decisions are not whether JSON is more elegant than YAML, or whether a binary format is faster. They are whether identities remain stable, references remain valid, schema changes are manageable, serialization is deterministic, and editing tools can preserve information they do not understand.

### Further research directions

1. **Schema evolution:** How should graph formats migrate when node types, pins, type systems, or language semantics change?
2. **Semantic diff and merge:** How can version-control tools compare and merge graph changes by node identity rather than by text lines?
3. **Lossless round-tripping:** How can editors preserve comments, formatting, unknown nodes, and extension metadata?
4. **AI-oriented serialization:** Does a custom grammar reduce token consumption and generation errors compared with canonical JSON?
5. **Incremental parsing:** Can a graph editor update only the affected portion of the in-memory model after a small text edit?
6. **Content addressing:** Can stable graph fragments be hashed for caching, reproducible builds, and deduplicated storage without making editable identities unstable?

These questions connect schema and serialization to the broader problems of bidirectional text/graph synchronization, language design, and collaborative programming.
