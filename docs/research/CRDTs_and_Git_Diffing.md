---
title: "CRDTs and Git Diffing for Text-Based Visual Programming"
document_type: "Research note"
formatted: 2026-10-28
---

# CRDTs and Git Diffing for Text-Based Visual Programming

The central research question is:

How can a visual programming language represent a graph so that concurrent edits remain easy to diff, merge, review, and synchronize—without losing the meaning of the program?

This problem sits at the intersection of source-code design, graph serialization, version control, collaborative editing, and distributed systems. It is especially important for node-based programming environments, where an apparently small visual change—moving a node, reconnecting a wire, or inserting a node—can cause a traditional XML or JSON serializer to rewrite hundreds of lines.

The key insight is that a graph's logical structure, its visual layout, and its collaborative editing history should not necessarily share the same representation. Once these concerns are separated, Git and CRDTs can each handle the problems they are best suited for.

## Contents

- [1. Why traditional visual formats create merge conflicts](#1-why-traditional-visual-formats-create-merge-conflicts)
- [2. The three layers of the problem](#2-the-three-layers-of-the-problem)
- [3. Design the file so that Git can understand it](#3-design-the-file-so-that-git-can-understand-it)
- [4. Stable identity is more important than line-oriented syntax](#4-stable-identity-is-more-important-than-line-oriented-syntax)
- [5. CRDTs: merging edits as operations on shared data](#5-crdts-merging-edits-as-operations-on-shared-data)
- [6. Git and CRDTs should complement each other](#6-git-and-crdts-should-complement-each-other)
- [7. What a graph CRDT actually needs to model](#7-what-a-graph-crdt-actually-needs-to-model)
- [8. Git merge drivers can make the format graph-aware](#8-git-merge-drivers-can-make-the-format-graph-aware)
- [9. A practical design recommendation](#9-a-practical-design-recommendation)
- [10. Research questions worth investigating](#10-research-questions-worth-investigating)
- [11. Suggested literature and implementation references](#11-suggested-literature-and-implementation-references)
- [Conclusion](#conclusion)

## 1. Why traditional visual formats create merge conflicts

Consider a visual program containing three nodes and two connections. A conventional visual editor might serialize it as JSON:

```json
{
  "nodes": [
    {
      "id": "n1",
      "x": 100,
      "y": 200,
      "type": "Input"
    },
    {
      "id": "n2",
      "x": 300,
      "y": 200,
      "type": "Add"
    },
    {
      "id": "n3",
      "x": 500,
      "y": 200,
      "type": "Output"
    }
  ],
  "connections": [
    {
      "from": "n1.out",
      "to": "n2.a"
    },
    {
      "from": "n2.out",
      "to": "n3.in"
    }
  ]
}
```

Suppose Alice moves `n1`, while Bob changes the position of `n3`.

**Alice's change**

Move the input node from (100, 200) to (120, 240).

**Bob's change**

Move the output node from (500, 200) to (520, 180).

Logically, these edits are independent. Yet a visual editor may reorder nodes, rewrite whitespace, renumber internal objects, or update other metadata during serialization. Git sees text changes rather than the user's intention.

This produces several related problems:

- **Diff noise:** a one-node movement changes many unrelated lines.
- **False conflicts:** two edits to different graph elements overlap in the serialized file.
- **Semantic conflicts:** Git merges text successfully but produces an invalid graph.
- **Unstable diffs:** the same graph can serialize differently across editor versions or sessions.
- **Poor code review:** reviewers see coordinate churn instead of meaningful program changes.

The goal is not simply to make files smaller. It is to make changes local, stable, and semantically understandable.

## 2. The three layers of the problem

**Layer A — Version control**

Git stores snapshots and compares versions. It needs deterministic serialization, meaningful line boundaries, and merge rules.

**Layer B — Graph model**

Nodes, ports, edges, properties, and references need stable identities and explicit structural constraints.

**Layer C — Collaboration**

Concurrent operations need deterministic conflict resolution, causal ordering where required, and convergence across replicas.

These layers overlap, but they solve different problems.

- Git is excellent at reviewing and merging committed snapshots.
- A structured graph model understands nodes, connections, and invariants.
- A CRDT (Conflict-free Replicated Data Type) supports concurrent editing with replicas that eventually converge under its assumptions.

No single layer automatically guarantees correctness in all the others.

## 3. Design the file so that Git can understand it

The first strategy is to make the canonical graph format a well-designed text language rather than a generic serialization dump.

Consider this representation:

```text
graph Main

node n1: Input
 position (100, 200)

node n2: Add
 position (300, 200)

node n3: Output
 position (500, 200)

edge n1.out -> n2.a
edge n2.out -> n3.in
```

Each node has a stable identifier, and each independent property occupies its own line. A change to one coordinate can now produce a tiny diff.

```text
 node n1: Input
- position (100, 200)
+ position (120, 240)
```

This is already a major improvement. Git's ordinary three-way merge can combine independent changes when their edited regions do not overlap. Git also supports custom merge drivers for formats that require more specialized logic.

*Source: gitattributes Documentation (+1 more)*

### Recommended syntax properties

| Design choice | Why it matters |
| --- | --- |
| Stable node IDs | Identifies the same node across revisions. |
| One property per line | Localizes edits and reduces overlapping diff regions. |
| One declaration per node or edge | Makes additions and deletions easy to review. |
| Canonical ordering | Prevents incidental changes caused by nondeterministic serialization. |
| Explicit connections | Makes topology changes visible as distinct edits. |
| No implicit array indexes as identity | Prevents inserting a node from changing the apparent identity of many later nodes. |
| Normalized numeric values | Avoids churn such as `100`, `100.0`, and `1e2` representing the same value. |
| Stable formatting rules | Prevents editor settings from rewriting the entire file. |

The deeper principle is semantic locality: a change to one concept should affect only the portion of the file that represents that concept.

### A subtle issue: ordering

Stable IDs alone do not eliminate merge conflicts. Suppose a serializer emits nodes in visual order, from left to right. Moving one node might reorder a large section of the file.

A safer default is to serialize declarations in a stable order, such as by node ID, rather than by screen coordinates.

Visual ordering can then be represented independently when it is meaningful to the user. This trades a convenient reading order for more stable diffs, so an editor may offer a separate human-friendly rendering.

There is no universally correct ordering strategy. The right choice depends on whether the file is optimized for human reading, mechanical merging, or both.

## 4. Stable identity is more important than line-oriented syntax

Suppose two developers add nodes concurrently.

Alice adds:

```text
node n4: Multiply
```

Bob adds:

```text
node n4: Divide
```

Even though the declarations are on separate lines in each branch, the merge is not safe. Both authors used the same identity for different objects.

A graph language therefore needs an identity policy.

Possible approaches include:

- **Globally unique IDs:** UUIDs or similarly collision-resistant identifiers.
- **Actor-derived IDs:** identifiers incorporating a replica or actor ID and a local counter.
- **Content-derived IDs:** hashes of canonical content, useful for immutable objects but often unsuitable for editable nodes whose contents change.
- **Human-assigned names:** readable identifiers, with explicit handling for naming collisions and renames.

For a collaborative visual programming language, globally unique or actor-derived IDs are usually a better starting point than deriving identity from node type, position, or array index.

One important distinction: identity should not change when a node moves, changes color, or changes its properties. Otherwise, version control interprets an edit as a deletion plus an addition.

## 5. CRDTs: merging edits as operations on shared data

A CRDT is a data structure designed so that independently updated replicas can converge when they exchange changes, provided the algorithm's assumptions are satisfied. It is particularly useful when collaborators work concurrently, disconnect, or synchronize later.

Unlike Git's usual file-level merge, a CRDT does not need to reconstruct intent exclusively by comparing three snapshots. It models updates using rules designed to reconcile concurrent operations.

For a graph editor, the CRDT might represent:

- Nodes as a map keyed by stable node IDs.
- Node properties as independently mergeable fields.
- Connections as identified records with source and destination endpoints.
- Textual expressions as collaborative text objects, if simultaneous text editing is required.
- Node ordering, grouping, or z-order as separate ordered structures.

Structured CRDT libraries such as Automerge provide maps, lists, text, and conflict handling. Their behavior differs by data type: for example, independent map properties can merge while concurrent assignments to the same property may retain multiple conflicting values internally but expose a deterministic winner by default.

*Source: automerge.org (+2 more)*

### Example: two developers move different nodes

Suppose the initial state is:

```text
n1.position = (100, 200)
n2.position = (300, 200)
```

Alice moves `n1` to `(120, 240)`. Bob moves `n2` to `(320, 180)`.

The resulting updates are conceptually:

```text
set n1.position = (120, 240)
set n2.position = (320, 180)
```

Because the edits affect different nodes, a suitably designed graph CRDT can preserve both updates without a conflict.

### Example: two developers move the same node

Now Alice moves `n1` to `(120, 240)`, while Bob independently moves it to `(80, 220)`.

Both edits target the same logical property. The system must decide what this means.

Possible policies include:

1. **Deterministic winner:** select one position consistently across replicas.
2. **Multi-value conflict:** retain both proposed positions and ask the user to resolve them.
3. **Intent-aware resolution:** use application-specific rules to determine which movement should prevail.
4. **Operation-based transformation:** reconcile the movements according to a model that defines how concurrent transformations compose.

A last-writer-wins policy can be deterministic without respecting what a human considers the latest action. In particular, wall-clock timestamps are not a reliable universal ordering for distributed operations.

For node movement, a single deterministic winner may be adequate. For editing code, deleting nodes, or changing connections, silently discarding a concurrent operation may be unacceptable.

Convergence is not the same as preserving intent. This is one of the most important distinctions in CRDT design.

## 6. Git and CRDTs should complement each other

A common misconception is that adopting a CRDT eliminates the need for Git. It does not. The two systems have different goals.

| Capability | Git | CRDT |
| --- | --- | --- |
| Primary purpose | Version history, branches, review | Concurrent updates and replica synchronization |
| Typical unit of change | File snapshots and textual diffs | Operations on replicated data structures |
| Offline editing | Supported through local commits and branches | Supported by local updates and later synchronization |
| Concurrent changes | Three-way merge and conflict resolution | Algorithm-specific deterministic reconciliation |
| Human-readable history | Excellent with well-designed text | Depends on how changes are exported and presented |
| Semantic correctness | Requires language-aware checks | Requires application-level invariants |
| Conflict-free result guaranteed? | No | Convergence is guaranteed under the CRDT's assumptions; semantic validity is not |

Git's documented custom merge drivers provide an extension point for language-specific merging. Automerge, by contrast, provides structured replicated data and conflict handling.

*Source: gitattributes Documentation (+2 more)*

### A hybrid architecture

For a text-based visual programming language, research should investigate this architecture:

*Figure: proposed architecture*

- **Visual editor and text editor** — One logical program, two editing interfaces
- **Canonical graph model** — Stable IDs · typed nodes · explicit edges · properties
- **Live synchronization** — CRDT or structured collaboration engine
- **Persistent source** — Canonical text, Git commits and diffs
- **Validation and conflict resolution** — Syntax · graph invariants · types · unresolved conflicts

The canonical graph model is the key boundary. The editor need not manipulate source text and coordinates as independent truths; it can manipulate a shared model and project that model into either representation.

There are two principal implementation variants:

Variant A — Text-first. The source file is authoritative. The editor parses it into a graph, and edits are translated back into localized text transformations. A CRDT can support concurrent source editing, but structural changes must still preserve the language grammar.

Variant B — Graph-first. The structured graph is authoritative during editing. The text file is a deterministic serialization of that graph. Git operates on the serialization, while the collaboration engine operates on graph operations.

For a visual programming environment with substantial node movement and wiring activity, the recommended approach is to initially favor Variant B. If direct source editing is the dominant workflow, Variant A deserves serious consideration.

A third possibility is a dual representation with explicit reconciliation, but that is more complex: independently editable graph and text representations can diverge, and the system must decide how to resolve that divergence.

## 7. What a graph CRDT actually needs to model

A generic CRDT is not automatically a graph CRDT. The choice of replicated data structures determines how graph edits interact.

A reasonable conceptual model is:

```text
Graph
 nodes: Map<NodeId, Node>
 edges: Map<EdgeId, Edge>

Node
 id: NodeId
 type: NodeType
 properties: Map<PropertyName, Value>
 position: Position

Edge
 id: EdgeId
 source: PortReference
 target: PortReference
```

The map structures provide stable addressing. The edge IDs allow connections to be independently added or removed. But the model also needs explicit policies for concurrency.

### Important conflict cases

**Independent property edits**

Alice changes a node's label while Bob moves another node. Merge both edits.

**Concurrent insertions**

Two users add distinct nodes. Preserve both, provided their identities are distinct and their declarations are valid.

**Delete versus edit**

One user deletes a node while another modifies one of its properties. Define whether deletion wins, the edit resurrects the node, or the conflict requires intervention.

**Conflicting connections**

Two users connect different sources to a single-input port. Both edges may survive the CRDT merge even though the resulting graph violates the language's rules.

**Concurrent movement**

Multiple positions for the same node require a policy. Independent movements of different nodes should normally compose without conflict.

### Graph invariants need their own treatment

Even when all replicas converge, the graph may be invalid. Examples include:

- An edge references a node that has been deleted.
- A port receives more connections than its type permits.
- A connection links incompatible port types.
- A supposedly acyclic dataflow graph contains a cycle.
- A node references a missing type definition.
- Two nodes violate a unique-name constraint.

These are semantic constraints, not ordinary merge rules.

One useful design is to distinguish replicated state from validated state. The collaborative engine preserves updates; a validation layer identifies which combinations form a legal program. The editor can display unresolved or invalid structures rather than silently discarding edits.

For some applications, invariants must be enforced during the merge itself. For others, temporarily invalid collaborative state is acceptable as long as it cannot be executed or committed as a valid program.

## 8. Git merge drivers can make the format graph-aware

Even without a live CRDT, a graph language can substantially improve Git merging.

Git supports custom merge drivers configured through `.gitattributes` and the repository's Git configuration. A driver receives the common ancestor, the current version, and the other branch's version, and can produce a merged file or report a conflict.

*Source: gitattributes Documentation (+1 more)*

The driver could:

1. Parse all three versions into graph models.
2. Compute the logical changes from the common ancestor.
3. Match objects by stable ID.
4. Combine changes to independent nodes and properties.
5. detect conflicting updates and delete-versus-edit cases.
6. Validate connections and other graph invariants.
7. Serialize the merged graph canonically if successful.
8. Report unresolved conflicts otherwise.

A simplified conceptual algorithm:

```python
def merge_graphs(base_text, ours_text, theirs_text):
    base = parse_graph(base_text)
    ours = parse_graph(ours_text)
    theirs = parse_graph(theirs_text)
    ours_changes = diff_graphs(base, ours)
    theirs_changes = diff_graphs(base, theirs)
    merged = merge_independent_changes(
        base,
        ours_changes,
        theirs_changes
    )
    validate_graph(merged)
    return serialize_canonically(merged)
```

This is pseudocode, not a complete implementation. In particular, the merge function needs explicit rules for overlapping changes, object identity, deletion, and invalid intermediate states.

The advantage is that the merge works on graph semantics instead of raw line positions. The resulting file can still be plain text and remain friendly to ordinary Git tools.

Important limitation: a custom merge driver is not automatically installed for everyone just because `.gitattributes` names it. Each developer or build environment must have the corresponding driver configured. Tooling and CI should verify that configuration.

## 9. A practical design recommendation

For a new text-based visual programming language, the recommended approach is to build the system in stages rather than starting with a fully distributed graph CRDT.

1. Stage 1 — Stable, canonical text format

 Give every node and edge a stable ID. Keep independent declarations on separate lines, use deterministic ordering, and ensure repeated serialization produces byte-identical output for unchanged state.
2. Stage 2 — Semantic diff

 Implement a graph-aware differ that identifies node additions, deletions, moves, property changes, and connection changes. Compare this with ordinary Git diffs.
3. Stage 3 — Three-way semantic merge

 Add a custom merge driver. Establish explicit behavior for concurrent updates to the same field, deletion, renaming, and invalid connections.
4. Stage 4 — Bidirectional editor synchronization

 Ensure graph edits update the text representation without reformatting unrelated regions, and text edits update the graph without losing identity or layout.
5. Stage 5 — Collaborative editing

 Introduce a proven CRDT library for the operations that need concurrent synchronization. Evaluate structured state versus text-level CRDTs, and preserve conflict information for operations whose meaning is ambiguous.
6. Stage 6 — Interoperability and correctness

 Test concurrent edits, branch merges, serialization stability, schema migrations, undo/redo, and recovery from partial synchronization. Require validation before execution and release.

This sequence establishes whether good syntax and semantic merging solve most of the problem before adding the extra complexity of distributed collaboration.

## 10. Research questions worth investigating

Several areas deserve focused investigation.

| Research question | What to measure |
| --- | --- |
| How much does canonical line-oriented syntax reduce diff noise? | Changed lines, diff size, and unrelated lines rewritten per edit. |
| When does semantic merging outperform ordinary Git merging? | Automatic merge rate and correctness of merged graphs. |
| What is the right CRDT granularity? | Node-level, property-level, edge-level, or operation-level conflict rates. |
| How should delete-versus-edit conflicts work? | Lost edits, accidental resurrection, and user resolution effort. |
| How should visual layout be stored? | Merge quality for moves, groups, reordering, and layout metadata. |
| What happens when text and graph edits occur concurrently? | Round-trip stability, identity preservation, and unresolved reconciliation cases. |
| Can LLM-generated edits be merged safely? | Parse success, semantic validity, and the number of unintended changes. |
| How should merge history map to Git commits? | Reviewability, reproducibility, and the ability to reconstruct logical changes. |

A useful evaluation should include at least three baselines:

- Conventional JSON or XML serialization with ordinary Git merging.
- Canonical line-oriented source with ordinary Git merging.
- Canonical source with a graph-aware merge driver.

Then evaluate a CRDT-enabled implementation separately, using concurrent collaboration scenarios. This makes it possible to measure the value of each technique rather than attributing every improvement to CRDTs.

## 11. Suggested literature and implementation references

- **Git attributes and custom merge drivers** Official documentation describing merge drivers, conflict handling, and file-level merge behavior. [Read the Git documentation](https://git-scm.com/docs/gitattributes)

**Automerge — Document model and conflicts**

A practical reference for structured collaborative state, conflict retention, map semantics, lists, and collaborative text.

- **[Document model](https://automerge.org/docs/reference/documents/) · [Conflict semantics](https://automerge.org/docs/reference/documents/conflicts/)** — *Peritext: A CRDT for Collaborative Rich Text Editing (2022).* A peer-reviewed study of how to preserve editing intent when concurrent operations interact. Although it concerns rich text rather than graphs, its treatment of stable anchors and intent preservation is relevant to structured source formats. *Source: Martin Kleppmann’s publications (+1 more)* [Read the paper](https://doi.org/10.1145/3555644)

**CRDT fundamentals**

Study convergence, commutativity, causal dependencies, operation identity, and the difference between deterministic conflict resolution and semantic correctness.

[Automerge concepts](https://automerge.org/docs/reference/concepts/) · [CRDT terminology](https://automerge.org/docs/reference/glossary/)

## Conclusion

The strongest design is unlikely to be “use a CRDT instead of Git.” It is to build a language and graph model that make both systems effective.

- Stable identities make graph changes traceable.
- Canonical, line-oriented syntax makes Git diffs compact and reviewable.
- Semantic merge logic combines independent changes and identifies real conflicts.
- CRDTs support concurrent, offline-capable editing and deterministic convergence.
- Graph validation ensures that the merged result is a valid program.

The most important architectural decision is to define the semantics of a graph edit independently of its textual encoding. Once the system knows what it means to move a node, delete an edge, or change a port connection, it can expose those operations through a visual editor, a text editor, a Git merge driver, or a CRDT without making any one of those interfaces the sole source of truth.
