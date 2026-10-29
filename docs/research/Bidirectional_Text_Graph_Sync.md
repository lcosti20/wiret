---
title: "Bidirectional Text–Graph Synchronization"
document_type: "Research note"
formatted: 2026-10-28
---

# Bidirectional Text–Graph Synchronization

Bidirectional Text–Graph Sync is an editing architecture in which a textual program and its visual graph are two synchronized representations of the same underlying program. Users can modify either representation, and the other updates automatically while preserving the program's meaning.

For a VS Code extension that edits a visual programming language, this means:

- Dragging a node updates its position in the graph's backing text file.
- Adding, renaming, connecting, or deleting nodes updates the textual representation.
- Editing the text file updates the graph, including its nodes, edges, labels, and properties.
- Undo, redo, validation, and error reporting work coherently across both editing modes.

This is a well-established area of software architecture, closely related to bidirectional transformations, model-driven engineering, live programming, and synchronized concrete syntaxes. Research on synchronized textual and graphical editors specifically addresses preserving layout, handling invalid intermediate text, and maintaining a consistent underlying model.

*Source: TU Delft Repository (+1 more)*

The topic is best developed as a technical specification for a live-synchronization subsystem rather than as a feature description.

## Contents

- [1. The core concept](#1-the-core-concept)
- [2. What exactly gets synchronized?](#2-what-exactly-gets-synchronized)
- [3. How synchronization works in practice](#3-how-synchronization-works-in-practice)
- [4. The synchronization engine](#4-the-synchronization-engine)
- [5. Avoiding synchronization loops](#5-avoiding-synchronization-loops)
- [6. The hardest design decisions](#6-the-hardest-design-decisions)
- [7. Bidirectional transformation laws](#7-bidirectional-transformation-laws)
- [8. Implementation architecture for VS Code](#8-implementation-architecture-for-vs-code)
- [9. Performance and correctness under real editing](#9-performance-and-correctness-under-real-editing)
- [10. Testing the synchronization system](#10-testing-the-synchronization-system)
- [11. Existing systems and related research](#11-existing-systems-and-related-research)
- [12. A proposed research definition](#12-a-proposed-research-definition)

## 1. The core concept

*Figure: text and graph views synchronized through a shared semantic model*

- **Text representation** — Source code, node declarations, edges, properties, optional layout metadata
   - *Text → Model:* Parse and reconcile
   - *Graph → Text:* Apply edits and serialize
- **Shared semantic model** — Stable node IDs, edges, properties, validation state, and layout
- **Visual graph editor** — Drag, connect, rename, select, arrange, and edit nodes

The central idea is that the text editor and graph editor must not behave as independent programs that occasionally exchange snapshots. They must participate in a shared document-editing system.

There are three main architectural approaches:

1. **Shared semantic model:** Both editors modify the same in-memory model. Text changes are parsed into it; graph changes mutate it and update the text.
2. **Text as source of truth:** The graph is derived from the text, and visual actions generate source edits. This works especially well when the text file is the canonical, version-controlled artifact.
3. **Synchronized representations:** Each editor has its own representation, and a synchronization engine reconciles changes between them.

For a VS Code extension, a hybrid of the first and second approaches is often the strongest design: VS Code's `TextDocument` is the canonical persisted artifact, while a shared semantic model provides the graph editor with a stable, structured view of it. VS Code's custom editor documentation explicitly requires webview-originated edits to update the document and document changes to update the webview.

*Source: Visual Studio Code Extension API (+1 more)*

## 2. What exactly gets synchronized?

It helps to distinguish three kinds of state.

| State category | Examples | Expected behavior |
| --- | --- | --- |
| Semantic state | Nodes, edges, expressions, inputs, outputs, execution order | Must remain semantically consistent |
| Presentation state | Node coordinates, dimensions, collapsed state, edge routing | Must persist and synchronize if represented in the document or its metadata |
| Editor state | Cursor, selection, zoom, pan, hover, active tool | Usually local to the editor, except when explicitly linked |

This distinction is particularly important for visual programming languages.

Suppose a node moves from `(200, 100)` to `(350, 180)`. The program's execution semantics should remain unchanged, even if the textual layout metadata changes.

Conversely, changing a node's operation from `Add` to `Multiply` is a semantic change. It may alter the program's behavior even if the node stays in exactly the same position.

A well-designed system keeps these categories separate internally, even when they share a file format.

## 3. How synchronization works in practice

Consider a simple visual program:

```text
graph Workflow {
 Start -> Validate
 Validate -> Process
 Process -> End
}
```

The graph editor represents these declarations as nodes and edges. A more complete format might also store node positions:

```text
node Start { x: 100, y: 80 }
node Validate { x: 300, y: 80 }
node Process { x: 300, y: 220 }
node End { x: 500, y: 220 }

edge Start -> Validate
edge Validate -> Process
edge Process -> End
```

The exact syntax is language-specific; these examples are illustrative.

### Direction A: Graph → Text

When a user drags `Process` to a new position, the extension should:

1. Receive a graph interaction event.
2. Identify the node using its stable ID.
3. Update its position in the model.
4. Generate the smallest appropriate textual edit.
5. Apply that edit through VS Code's document-editing API.
6. Update any other views of the same document.

The crucial optimization is minimal edits rather than whole-file replacement. Rewriting the entire file on every drag can cause cursor jumps, lost formatting, noisy Git diffs, and interference with simultaneous text editing. VS Code's custom editor guidance recommends minimal workspace edits.

*Source: Visual Studio Code Extension API (+1 more)*

For example, if only the position changes, the desired result is conceptually:

```text
-node Process { x: 300, y: 220 }
+node Process { x: 420, y: 300 }
```

There should be no need to regenerate unrelated node declarations or connections.

### Direction B: Text → Graph

When the user edits the text file, the extension should:

1. Receive a document-change notification.
2. Update or reparse the textual representation.
3. Recover the semantic model, including any valid portions of the file.
4. Reconcile nodes and edges against the existing graph.
5. Update affected visual elements without resetting unrelated layout or editor state.
6. Display syntax and semantic errors where appropriate.

The graph should not be destroyed and rebuilt from scratch after every keystroke. Stable IDs and incremental reconciliation allow the editor to preserve node selection, drag state, viewport position, and other useful UI state.

A key complication is that source code is frequently incomplete while being edited. A user might temporarily delete a closing brace or type half of an edge declaration. The graph should handle this gracefully, retaining the last valid structure where possible and clearly distinguishing stale elements from currently valid ones.

VS Code's custom editor guidance explicitly warns that document contents may be invalid during editing, and research on synchronized editors treats error recovery and layout preservation as core problems.

*Source: Visual Studio Code Extension API (+1 more)*

## 4. The synchronization engine

A practical implementation benefits from an explicit synchronization layer.

*Figure: synchronization layer*

1. **Event sources** — Text changes · Node moves · Edge edits · Undo/redo
2. **Change normalization** — Convert input into typed, stable-ID operations
3. **Synchronization coordinator** — Order changes, validate revisions, prevent feedback loops
4. **Text adapter** — Parse, locate, patch, serialize
5. **Graph adapter** — Render, reconcile, apply interactions
6. **Shared document state** — Semantic model · layout · source mappings · revision number

The components have distinct responsibilities:

- **Text adapter:** Understands the language grammar, maps source ranges to model elements, and produces text edits.
- **Graph adapter:** Translates pointer and keyboard interactions into model operations and renders the reconciled state.
- **Synchronization coordinator:** Controls update ordering, deduplication, revisions, and consistency.
- **Shared document state:** Stores the current semantic model and relevant metadata.
- **Validation subsystem:** Reports parsing failures, missing references, invalid connections, and other constraints.

This separation prevents the graph renderer from becoming entangled with source-code formatting rules and prevents the text parser from needing to understand canvas behavior.

## 5. Avoiding synchronization loops

One of the most important implementation problems is the feedback loop.

1. **User moves a node** — The graph sends a position change.
2. **Extension edits the text** — VS Code emits a document-change event.
3. **Graph receives the document update** — Without safeguards, the graph may emit another change.
4. **Feedback loop** — Repeated updates, redundant writes, or rendering churn.

There are several complementary safeguards:

- **Origin tracking:** Label operations as originating from the text editor, graph editor, undo/redo, or external changes.
- **Semantic deduplication:** Ignore updates that do not actually change model state.
- **Revision tracking:** Associate each document state and outgoing update with a monotonically increasing revision.
- **Programmatic-update suppression:** Ensure rendering a model update does not produce a new user-edit event.
- **Idempotent reconciliation:** Applying the same update twice should not create duplicate nodes, edges, or changes.

A simple conceptual protocol might look like this:

```typescript
type SyncOrigin = "text" | "graph" | "undo" | "external";

interface SyncUpdate {
  documentUri: string;
  baseRevision: number;
  revision: number;
  origin: SyncOrigin;
  operations: GraphOperation[];
}
```

This is illustrative TypeScript, not a built-in VS Code API. The important idea is that each update carries enough information to determine which document it affects, which state it was based on, and whether it has already been applied.

Origin tracking alone is not sufficient: updates can be delayed, duplicated, or superseded. It should be combined with state comparison and revision checks. VS Code's own custom editor documentation specifically warns about loops caused by propagating a graph edit back into the graph through document-change events.

*Source: Visual Studio Code Extension API (+1 more)*

## 6. The hardest design decisions

### 6.1 Stable identity

Every graph element needs a stable identity that survives textual edits.

For example:

```text
node n17 {
 operation: Add
 inputs: [n12.output, n14.output]
}
```

The graph editor should identify this node by `n17`, not by its current screen coordinates, display label, array index, or source line number.

Otherwise, inserting a new declaration near the beginning of the file could cause the editor to mistake an existing node for a different one.

Stable identity is especially important when supporting:

- Node renaming.
- Moving declarations within the file.
- Connecting and disconnecting nodes.
- Incremental parsing.
- Undo and redo.
- Preserving selection and layout.
- Mapping compiler diagnostics back to graph elements.

If the language does not provide explicit IDs, the implementation needs an identity-reconciliation strategy. Possible alternatives include persistent metadata, syntax-tree identity preservation, or structural matching. Structural matching is inherently less reliable when several nodes are identical.

### 6.2 Preserving source formatting

A semantic model usually does not preserve every detail of the original text. It might discard comments, whitespace, quote styles, and declaration ordering.

Consider:

```text
# Compute the final result
node result { operation: Add, x: 200, y: 100 }
```

If the user drags the node, a naïve serializer might regenerate the entire file and remove the comment or reformat the declaration.

There are three common strategies:

| Strategy | Benefits | Limitations |
| --- | --- | --- |
| Whole-document serialization | Simple; guarantees canonical formatting | Can destroy comments, formatting, and source stability |
| Source-range patching | Preserves unrelated text; produces small diffs | Requires reliable source locations and patch management |
| Concrete syntax tree (CST) or lossless syntax tree | Can preserve comments, whitespace, and original syntax | More complex parser and transformation infrastructure |

**Recommendation:** Use source-range patching backed by a lossless syntax representation when possible. If the language is deliberately canonical and formatting preservation is not a requirement, whole-document serialization may be a reasonable simpler choice.

A hybrid is also viable: preserve source text for existing elements, generate canonical text for new elements, and provide an explicit formatting command.

The trade-off between textual layout preservation and graphical layout preservation is a documented concern in bidirectional editor research.

*Source: TU Delft Repository (+1 more)*

### 6.3 Where should node positions live?

A visual editor has information that a conventional program representation may not need. Node coordinates, edge-routing points, and canvas layout are examples.

There are three common choices.

**Option A — Inline metadata**

Store coordinates alongside node declarations.

Best when the language is designed for visual editing and a single portable file is desirable. Layout changes create source diffs.

**Option B — Sidecar layout file**

Store layout in a companion file, such as `program.graph.json`.

Best when semantic source should remain clean and layout should be versioned separately. Requires reliable association between the files.

**Option C — Derived layout**

Recalculate positions using an automatic layout engine.

Best for generated diagrams or disposable views. Poor for users who expect their carefully arranged graphs to persist.

For a visual programming language where users manually arrange nodes, the preferred approach is persistent layout metadata, either inline or in a sidecar file. Automatic layout should be an explicit command or mode, not something that unexpectedly rearranges the graph after each source edit.

## 7. Bidirectional transformation laws

The synchronization engine can be evaluated using ideas from bidirectional programming.

Let:

- $T$ denote the textual representation.
- $G$ denote the graphical representation.
- $P(T)$ parse text into a semantic model.
- $R(G)$ render the semantic model as a graph.
- $E_G$ apply a graph edit.
- $E_T$ apply a textual edit.

An ideal system satisfies several useful properties.

### Semantic round-trip consistency

If the graph is derived from valid text, converting back should preserve the program's meaning:

$$
\mathrm{sem}(P(T')) = \mathrm{sem}(P(T))
$$

when $T'$ differs from $T$ only in presentation metadata, such as node coordinates.

### Graph-edit preservation

If a user performs a semantic edit on the graph, the generated text should represent that edit:

$$
\mathrm{sem}(P(E_T(T))) = \mathrm{sem}(E_G(P(T)))
$$

This assumes the operation is supported by the language and the resulting program is valid.

### Idempotence

Applying the same synchronization update repeatedly should not cause further changes after the first successful application:

$$
S(S(x)) = S(x)
$$

Here, $S$ represents reconciliation of a representation with the current document state.

### Stability

An unrelated edit should not unnecessarily change unrelated parts of the other representation. For example, renaming one node should not reset the entire graph layout.

These properties are more useful than merely checking whether the two views look similar. They can be translated into automated tests and serve as a foundation for evaluating competing synchronization architectures. Bidirectional transformation research provides a formal basis for these concerns.

*Source: Cornell Computer Science (+1 more)*

## 8. Implementation architecture for VS Code

For an extension, a suitable starting point is a `CustomTextEditorProvider` if the graph is an editable visual representation of a text file. It uses VS Code's `TextDocument` as the document model, allowing ordinary text editing, document synchronization, and familiar editor behavior to participate in the same workflow.

*Source: Visual Studio Code Extension API (+1 more)*

A possible implementation stack is:

*Figure: implementation stack*

- **VS Code extension host** — CustomTextEditorProvider · WorkspaceEdit · document-change events · diagnostics
   - *Typed messages between extension and webview*
- **Synchronization core** — Parser · lossless syntax representation · semantic model · operation queue · revision control
   - *Incremental state updates*
- **Text view** — VS Code's text editor
- **Graph webview** — Canvas, nodes, edges, interactions

The division of responsibilities is important:

- The extension host owns the authoritative document state and applies text edits.
- The graph webview reports user operations rather than independently writing files.
- The parser and model layer translate between source and semantics.
- The synchronization core decides which updates are necessary.
- The renderer consumes model updates without emitting new user-edit operations for programmatic changes.

If the language is complex, a language server may also provide parsing, validation, and semantic analysis. It is not required for synchronization itself, and adding one should be justified by the language's needs. VS Code supports incremental document synchronization for language servers.

*Source: Visual Studio Code Extension API (+1 more)*

## 9. Performance and correctness under real editing

Live synchronization introduces problems that do not appear in a one-time compiler or diagram renderer.

| Problem | Recommended approach |
| --- | --- |
| Rapid node dragging | Coalesce intermediate position updates; commit sensible edit units |
| Fast text typing | Debounce expensive work where appropriate; parse incrementally if feasible |
| Invalid intermediate syntax | Recover partial structure or retain a clearly marked last-valid graph |
| Stale asynchronous parsing | Reject results based on obsolete document revisions |
| Large graphs | Reconcile only changed model elements; virtualize rendering if necessary |
| Concurrent text and graph edits | Use revision checks and reconcile or reject stale graph operations |
| Undo/redo | Make document edits participate in VS Code's undo stack |
| File reload or external edits | Reparse and reconcile against the new authoritative document |
| Multiple graph views | Broadcast updates to every view of the same document |
| Deleted or renamed nodes | Maintain stable IDs and update references consistently |

A particularly important distinction is between debouncing and correctness. Debouncing reduces unnecessary work, but it does not prevent stale results or resolve conflicting edits. Revision checks and a clear ordering model are still necessary.

For node dragging, the editor might update the visual position continuously while persisting changes at a controlled rate. Alternatively, it can persist each meaningful movement and coalesce adjacent operations into a single undo step. The correct choice depends on autosave expectations, document size, and the desired undo behavior.

## 10. Testing the synchronization system

A strong test suite should verify more than whether moving a node changes a line of text.

The testing plan should organize testing into five layers:

1. **Parser and serializer tests:** Valid syntax, comments, formatting, missing IDs, invalid edges, and round trips.
2. **Operation tests:** Moving, renaming, adding, connecting, and deleting graph elements.
3. **Synchronization tests:** Text-to-graph and graph-to-text consistency, duplicate-event handling, and idempotence.
4. **VS Code integration tests:** Undo/redo, external text edits, save/revert, editor splitting, and document lifecycle.
5. **Stress and recovery tests:** Rapid dragging, large files, incomplete syntax, stale asynchronous results, and interrupted webview communication.

A particularly valuable property-based test is:

1. Generate a valid program.
2. Apply a random sequence of supported graph operations.
3. Serialize the result.
4. Parse the serialized text.
5. Compare the resulting semantic model against the expected model.
6. Repeat with equivalent text-side operations.

This can expose bugs that ordinary example-based tests miss, especially around ID preservation, operation ordering, and deletion of referenced elements.

## 11. Existing systems and related research

These projects and resources offer useful points of comparison.

**LangGraph Sync**

An implementation focused on keeping a LangGraph-style visual workflow and its Python source synchronized. It describes graph operations being translated into deterministic source mutations. Particularly relevant if the visual programming language has a Python-based textual representation.

Source: [GitHub repository](https://github.com/kammeows/langgraph-sync)

**Flowmo Flowchart Editor**

A VS Code extension that describes bidirectional synchronization between a drag-and-drop flowchart and a Mermaid-based text format with position metadata. A useful example of embedding layout information in a textual artifact.

Source: [Marketplace listing](https://marketplace.visualstudio.com/items?itemName=flowmo.flowmo-flowchart-editor\)

**Eclipse GLSP**

A framework for graphical modeling tools that can connect diagrams with textual language services, including navigation between diagram elements and their textual implementations. Useful when the extension grows into a full language tooling platform.

Source: [Architecture and features](https://eclipsesource.com/blogs/2021/02/10/web-based-diagram-editor-features-in-eclipse-glsp/)

**Robust Real-Time Synchronization between Textual and Graphical Editors**

A master's thesis studying synchronization across textual and graphical modeling environments. It addresses mappings between syntax and models, error recovery, preservation of layouts, and shared editor services.

Source: [TU Delft repository record](https://repository.tudelft.nl/record/uuid:ba881634-c096-450b-b494-96497f0fcc1f)

## 12. A proposed research definition

The following definition summarizes the topic and the scope recommended for further research.

Bidirectional Text–Graph Synchronization is the mechanism by which a textual representation and a graphical representation of a visual programming language remain mutually consistent during live editing. It translates text changes into updates to a graph model and translates graphical operations into corresponding edits to the textual document.

In a VS Code extension, the mechanism typically integrates a text document, a parser or syntax model, a shared semantic representation, an interactive graph webview, and a synchronization coordinator. It must preserve semantic correctness, stable element identity, and relevant layout information while handling invalid intermediate syntax, undo/redo, rapid changes, external edits, and multiple editor views.

The central engineering challenges are bidirectional transformation correctness, source-format preservation, incremental reconciliation, feedback-loop prevention, operation ordering, and conflict handling. A successful design makes the text and graph behave as two editing interfaces for one program, rather than as independent artifacts connected by one-way code generation.

### Recommended scope for further research

The most important question is not simply how to make the graph update when the text changes. It is what the synchronization system guarantees when either representation changes.

For a rigorous design, research should investigate these questions first:

- Is the text file the canonical representation, or is the semantic model authoritative?
- Must comments and formatting survive graph edits exactly?
- Are node positions part of the language, sidecar metadata, or disposable presentation state?
- How should the graph behave when the source is temporarily invalid?
- How are concurrent edits, undo/redo, and stale updates handled?
- What measurable properties define correct synchronization?

Those decisions determine the appropriate parser, data model, patching algorithm, event protocol, and test strategy. They also distinguish a robust bidirectional editor from a basic graph preview that merely regenerates its contents when a file changes.
