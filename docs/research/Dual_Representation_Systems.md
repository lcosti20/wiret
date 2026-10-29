---
title: "Dual Representation Systems"
document_type: "Research note"
formatted: 2026-10-28
---

# Dual Representation Systems

Dual Representation Systems are programming environments that let users work with the same program through two different interfaces: textual code and a visual representation, such as blocks, nodes, or a graph. The central challenge is allowing users to switch between these representations without losing information, changing program behavior, or being forced into a single mode of interaction.

Examples include Microsoft MakeCode switching between blocks and JavaScript, Scratch with extensions that translate blocks into text, and node-based programming systems where a graph can be edited alongside a textual source representation.

The key research problem is not merely translating text into blocks. It is maintaining a consistent, editable program when the two representations have different expressive capabilities and different rules for what constitutes a valid program.

## Contents

- [1. The fundamental problem](#1-the-fundamental-problem)
- [2. The major architectural approaches](#2-the-major-architectural-approaches)
- [3. The key design challenge: invalid text](#3-the-key-design-challenge-invalid-text)
- [4. Bidirectional transformations and synchronization laws](#4-bidirectional-transformations-and-synchronization-laws)
- [5. A recommended architecture: source-preserving, error-tolerant synchronization](#5-a-recommended-architecture-source-preserving-error-tolerant-synchronization)
- [6. Preventing synchronization loops and edit conflicts](#6-preventing-synchronization-loops-and-edit-conflicts)
- [7. The hardest question: what is the source of truth?](#7-the-hardest-question-what-is-the-source-of-truth)
- [8. Research precedents and systems to study](#8-research-precedents-and-systems-to-study)
- [9. A research agenda](#9-a-research-agenda)
- [10. A concrete implementation plan](#10-a-concrete-implementation-plan)
- [Conclusion](#conclusion)

## 1. The fundamental problem

*Figure: dual representation of one program*

- **Textual representation** — JavaScript, Python, or a domain-specific language
   - *Parsing, projection, and reconciliation*
- **Visual representation** — Blocks, nodes, connections, and spatial layout

Both views must preserve program meaning and survive edits in either direction.

A text editor permits incomplete expressions, arbitrary syntax, comments, and intermediate states that may not correspond to any valid program. A visual editor generally expects structured objects with known types, fields, connections, and nesting relationships.

For example, a user might edit JavaScript from:

```javascript
let score = 10;
score = score + 1;
```

to:

```javascript
let score = 10;
score = score +;
```

The second version is temporarily invalid JavaScript. A conventional parser may reject the expression, leaving a block editor unable to reconstruct the program.

Yet the user's intent is understandable: they may simply be in the middle of typing `1`. If the visual editor responds by reverting the source, deleting the broken expression, or refusing the edit, it violates the expectation that the text editor is a first-class interface.

This is the central issue of dual representation design: a program can be incomplete without being disposable.

## 2. The major architectural approaches

There are several ways to synchronize text and visual representations. They differ in which representation is authoritative, how they preserve invalid text, and whether they support unrestricted source code.

**A. Translate between text and blocks**

The system converts a supported subset of source code into visual blocks and generates source code from those blocks.

Best for educational programming and constrained languages. Translation may fail when the text exceeds the visual language's capabilities.

**B. Use a shared semantic model**

Both editors operate on a common abstract syntax tree (AST), typed graph, or intermediate representation (IR). An edit in one view updates the shared model, which then updates the other view.

Best when both interfaces have comparable expressive power. Invalid intermediate text still needs special treatment.

**C. Keep source text and visual structure together**

The system maintains source text, parsed structure, and visual metadata, including layout and editor-specific information. The visual graph is a structured projection of the source rather than the only storage format.

Best for richer programming environments where comments, formatting, custom syntax, and partially invalid code must survive.

These approaches are not mutually exclusive. A robust environment can use a shared semantic model for valid code while retaining the original source and an error-tolerant representation for incomplete code.

## 3. The key design challenge: invalid text

A reliable dual representation system must handle more than valid source code. It must handle the entire editing process, including incomplete and malformed programs.

Consider the same line as it evolves:

**State 1 — Valid code**

```text
total = price + tax;
```

The parser recognizes a complete expression; the visual editor can render it normally.

**State 2 — Incomplete edit**

```text
total = price +;
```

The expression is invalid, but the source must be retained exactly as entered.

**State 3 — Repaired code**

```text
total = price + shipping;
```

The system should recover automatically and update the visual view without losing the user's edits.

The architecture should explicitly distinguish three conditions:

- **Valid and representable:** the text parses and all relevant constructs have visual equivalents.
- **Valid but not representable:** the text parses, but the visual language cannot express some construct.
- **Temporarily invalid:** the text does not currently parse into the required structure.

These conditions require different responses. Treating all three as generic conversion failures leads to unnecessarily fragile editors.

### Five strategies for handling invalid text

1. Preserve the last valid visual state

Continue displaying the last successfully generated graph while the text is invalid. Mark it as stale and show a diagnostic.

This is simple and safe, but the graph no longer represents the current source. The UI must make that distinction unmistakable.

2. Use error-tolerant parsing

Parse incomplete input into an error-recovering syntax tree with missing nodes, error nodes, or explicit holes. Render valid regions and preserve the invalid region in a placeholder.

This offers a more live, synchronized experience, but requires a parser and renderer designed to handle malformed input.

3. Use opaque text blocks

When code cannot be translated into ordinary visual blocks, display a special block containing the original text. MakeCode documents this approach for JavaScript that cannot be represented with its normal blocks.

*Source: Microsoft MakeCode for Minecraft Add-Ons (+1 more)*

This is excellent for unsupported but valid code. For malformed text, the opaque block must also preserve the exact source without claiming the code is valid.

4. Synchronize only valid regions

Keep independently parseable statements or subtrees synchronized, while isolating broken regions. If one expression becomes invalid, unrelated functions and blocks can still update.

This is useful for large programs, but requires stable identities and careful tracking of which regions depend on each other.

5. Use an editable intermediate representation

Represent the program using a tolerant syntax tree or graph that can contain incomplete constructs, missing operands, unresolved references, and source fragments. Both interfaces edit that representation.

This is the most ambitious option. It can provide genuinely bidirectional editing without forcing every intermediate state to be valid, but substantially increases implementation complexity.

Important distinction: preserving the last valid graph is a fallback; representing invalid regions explicitly is a stronger synchronization model. A robust system can combine both.

## 4. Bidirectional transformations and synchronization laws

Dual representation systems are closely related to bidirectional transformations, sometimes studied through the concepts of lenses, projections, and synchronization.

Let:

- $T$ be the text representation.
- $V$ be the visual representation.
- $P(T)$ parse or project text into visual structure.
- $G(V)$ generate text from visual structure.

A naive implementation might simply compute $V=P(T)$ after each text change and $T=G(V)$ after each graph change. But this is insufficient because the two mappings are often lossy.

For example, converting source code to an AST and regenerating it can discard comments, whitespace, quote styles, and other formatting. Converting code to blocks may also discard unsupported syntax or visual layout metadata.

A well-designed system should aim for several laws.

| Law | Desired behavior |
| --- | --- |
| Text round-trip | Converting supported text to a visual form and back preserves its meaning. |
| Visual round-trip | Converting a visual program to text and back preserves its structure and behavior. |
| Edit stability | A small edit does not unnecessarily rewrite unrelated regions. |
| Information preservation | Comments, unsupported constructs, and source fragments are not silently lost. |
| Convergence | After an edit settles, both representations agree wherever synchronization is possible. |

These laws need careful interpretation. Exact textual equality is usually unrealistic when a generator reformats code. A better requirement is either exact preservation of untouched source regions or semantic equivalence, depending on the design.

The theory of bidirectional transformations is useful because it forces the designer to define which information is preserved, which information is derived, and how conflicting updates are resolved.

## 5. A recommended architecture: source-preserving, error-tolerant synchronization

For a new dual representation editor, the recommended approach is to combine a source-preserving text model, an error-tolerant syntax tree, and a structured visual graph.

The crucial design choice is that parsing failure must not be a synchronization failure. The system should have a valid internal state even when the user's program is invalid.

*Figure: layers of a dual-representation editor*

- **1. Source document** — Exact text, comments, whitespace, cursor position, and edit history
- **2. Error-tolerant parser** — Valid syntax nodes, missing nodes, error nodes, and preserved source spans
- **3. Reconciliation layer** — Stable node identities, source mappings, edit origins, conflict handling, and capability checks
- **Text view** — Exact source, syntax diagnostics, completion
- **Visual view** — Structured nodes, connections, error placeholders

The source and syntax model retain information that the visual view cannot express.

### Responsibilities of each layer

Source document. Store the actual text independently of whether it parses. Never reconstruct the entire document from generated visual code on every keystroke.

Error-tolerant parser. Produce a usable representation of incomplete code. A missing right-hand operand, for example, could be represented as an addition node with a missing operand rather than rejecting the entire statement.

Reconciliation layer. Determine which edits should propagate, preserve identities where possible, and prevent generated updates from being mistaken for fresh user edits.

Visual view. Render ordinary nodes for recognized constructs and explicit placeholders for incomplete or unsupported constructs. Do not silently omit source regions that have no visual equivalent.

This resembles techniques used in modern language tooling, but the requirements go beyond ordinary compiler parsing: the intermediate representation must also support editing, preservation, and conversion.

### An example of an incomplete syntax tree

For the text:

```text
total = price +;
```

an error-tolerant parser could produce the following conceptual structure:

```text
Assignment
├── total
└── Addition
    ├── price
    └── (missing operand)
```

Conceptual representation; not a specific parser's output.

If the user subsequently types `shipping`, the missing-operand node becomes an identifier node. The visual representation can recover without discarding the assignment or rebuilding unrelated code.

A placeholder like this should be an actual editable construct, not just a decoration. Otherwise, the graph may display an error without providing a meaningful way to repair it.

## 6. Preventing synchronization loops and edit conflicts

Invalid syntax is only one source of synchronization errors. Even two valid representations can fight each other if updates are not coordinated.

### The feedback-loop problem

Suppose a user drags a node to change an assignment. The graph generates new source, which updates the text editor. The text editor detects a change and parses it again. The parser regenerates the graph, which triggers another update.

Without explicit coordination, this can lead to redundant work, cursor jumps, unnecessary formatting changes, or an infinite feedback loop.

A practical solution is to track the origin and version of every edit.

```text
Text edit
 |
 v
Update source document
 |
 v
Parse and reconcile
 |
 v
Update visual projection
 |
 +-- Mark update as derived from text
 |
 v
Do not treat derived update as a new graph edit
```

For graph-originated edits, reverse the process: update the semantic model, apply a minimal source patch, and mark that patch as graph-originated.

A robust implementation should include:

- **Edit origin:** text, graph, undo/redo, external tool, or automated transformation.
- **Document versions:** each accepted edit refers to a known source version.
- **Stable identities:** syntax nodes and visual nodes retain identity across ordinary edits where possible.
- **Minimal patches:** update affected source spans rather than regenerating the entire file.
- **Undo grouping:** one logical operation should normally correspond to one undo step, even if it changes both views.
- **Conflict policy:** if edits overlap or arrive against an obsolete version, reconcile them explicitly rather than silently overwriting one side.

These principles are particularly important if the text editor uses an incremental language server, the graph is interactive, or multiple tools can modify the same program.

## 7. The hardest question: what is the source of truth?

There are three common policies, each with different trade-offs.

| Policy | Advantages | Main drawback |
| --- | --- | --- |
| Text is authoritative | Preserves arbitrary source and works naturally with conventional programming tools | Visual edits must be translated back into text carefully |
| Graph is authoritative | Guarantees that the primary program model remains structurally valid | Arbitrary textual edits may be rejected or difficult to represent |
| Shared model with source preservation | Supports both interfaces while retaining comments, formatting, and invalid fragments | More complex reconciliation and data structures |

For a system that permits unrestricted textual editing, the recommendation is the third policy.

The source document is authoritative for the exact text the user entered. A shared, error-tolerant model is authoritative for the structure that the system has successfully understood. The visual view is a projection of that model, not a replacement for the source.

This distinction avoids a common conceptual mistake: requiring one representation to be authoritative for everything. Exact source preservation and semantic structure are different responsibilities.

For a constrained educational language whose text syntax is deliberately isomorphic to its blocks, a simpler graph-authoritative or shared-AST architecture may be sufficient. The design should follow the language's actual expressiveness rather than assume every system needs a compiler-grade source-preserving architecture.

## 8. Research precedents and systems to study

The following are useful starting points for a literature review.

**Microsoft MakeCode / PXT**

A particularly useful practical reference for unsupported constructs. Its documented approach uses opaque JavaScript blocks when code cannot be represented by normal blocks, preserving the code when switching views. It also demonstrates that syntactic validity alone does not guarantee visual representability.

*Source: Microsoft MakeCode for Minecraft Add-Ons (+1 more)*

Study: source preservation, language subsets, and conversion limitations.

[JavaScript blocks documentation](https://bedrock.makecode.com/blocks/javascript-blocks)

**Blockly and AST-based conversion**

A 2025 paper by Anahide Silahli, Jose Pablo De la Rosa Gutierrez, and Thiago Rocha Silva describes a dual editor for a domain-specific language, using Blockly code generators in one direction and AST-based conversion in the other. Its application domain is behavior-driven development scenarios for robotics.

- **University of Southern Denmark** Study: real-time synchronization, AST conversion, and evaluation in an end-user programming context. [Read the 2025 paper](https://doi.org/10.1007/978-3-031-95452-8_8)

**Venbrace and MIT App Inventor**

Huang and Turbak's design work explores a textual notation that corresponds closely to App Inventor's visual blocks, including representations for larger parts of a project. Its emphasis on a predictable, fully braced syntax illustrates how language design itself can make bidirectional conversion easier.

- **Wellesley** Study: syntax isomorphism, language design, project-wide representation, and user evaluation. [Read the design paper](https://cs.wellesley.edu/~tinkerblocks/BB19-Venbrace-summary.pdf)

**Tiled Grace and frame-based editing**

These systems explore hybrids that bring structured editing affordances into text-based programming. They are useful comparisons because they question whether users need two entirely separate representations or would benefit from a single editor combining the advantages of both.

*Source: Wellesley (+1 more)*

Study: hybrid interfaces, syntax-error prevention, and structured text editing.

A broader literature review by Yuhan Lin and David Weintrop analyzed 46 block-based environments and classified approaches to transitioning between blocks and text. It provides a useful taxonomy for situating a new dual representation system within existing work.

*Source: ScienceDirect (+1 more)*

## 9. A research agenda

For a research project specifically focused on preventing synchronization errors, research should investigate the following questions.

**RQ1 — Error-tolerant synchronization**

How much of a visual program can remain accurately synchronized while its textual representation is syntactically invalid?

Compare preserving the last valid graph, rendering explicit error nodes, and using a tolerant intermediate representation.

**RQ2 — Information preservation**

Which source details are lost during round trips, and how can source spans, comments, formatting, and unsupported constructs be preserved?

Measure both semantic equivalence and exact preservation of untouched regions.

**RQ3 — Incremental reconciliation**

Can local edits update only affected syntax nodes and graph regions, avoiding whole-program reparsing and visual reconstruction?

Measure latency, identity stability, unnecessary updates, and cursor disruption.

**RQ4 — Representational asymmetry**

What happens when the text language can express constructs that the visual language cannot?

Compare opaque source blocks, custom nodes, and explicit conversion boundaries.

**RQ5 — User trust and recoverability**

Which interface best communicates that the visual graph is incomplete, stale, or only partially synchronized?

Measure accidental data loss, recovery time, perceived reliability, and user understanding of synchronization status.

### Suggested evaluation metrics

| Metric | What it measures |
| --- | --- |
| Source preservation rate | Percentage of user-entered source retained after repeated view switches and edits |
| Semantic round-trip rate | Percentage of supported programs that preserve behavior through conversions |
| Recovery latency | Time between repairing invalid text and restoring synchronization |
| Unaffected-node stability | Percentage of unrelated graph nodes that retain their identity and state |
| Silent-loss rate | Number of cases where source or visual information disappears without an explicit warning |
| Synchronization convergence | Whether the representations agree after editing stops |
| Interaction cost | Extra actions needed to recover, resolve a conflict, or switch views |

Tests should include incomplete expressions, unmatched delimiters, partially typed declarations, unsupported language constructs, comments between statements, changes to nested expressions, and edits made while the parser is still processing a previous version.

## 10. A concrete implementation plan

For a prototype, the architecture should be implemented these features in the following order:

1. Define the representable language subset. Specify which text constructs map to which visual nodes and which must remain opaque.
2. Implement round-trip conversion. Verify that valid programs survive text-to-graph-to-text and graph-to-text-to-graph transformations.
3. Preserve source text independently. Ensure that generating a graph cannot overwrite source that the graph cannot represent.
4. Add error-tolerant parsing. Render incomplete constructs as explicit missing or erroneous nodes.
5. Implement incremental reconciliation. Track edit origins, source spans, stable identities, and document versions.
6. Add conflict handling and undo. Make every transition reversible and prevent stale edits from overwriting newer work.
7. Run adversarial tests. Randomly insert and delete characters, switch representations during incomplete edits, and check for silent data loss.
8. Conduct a user study. Determine whether users understand partial synchronization and can recover naturally from errors.

The most important acceptance test is simple: if a user types an invalid program, switches views, makes further edits, and eventually repairs it, no unacknowledged source should disappear and the system should converge to a consistent representation.

## Conclusion

Dual Representation Systems sit at the intersection of visual programming, language tooling, structured editing, and bidirectional transformations. The difficult part is not generating blocks from valid source; it is maintaining a faithful, editable relationship between representations that cannot express exactly the same things.

The strongest design principle is to preserve the source, model incomplete syntax explicitly, and treat the visual interface as a potentially partial projection rather than forcing every edit to produce a valid graph. This permits a system to remain useful throughout the editing process instead of only when the program is syntactically complete.
