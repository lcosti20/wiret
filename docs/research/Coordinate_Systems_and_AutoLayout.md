---
title: "Coordinate Systems and AutoLayout for Text-Based Visual Programming Languages"
document_type: "Research note"
formatted: 2026-10-28
---

# Coordinate Systems and AutoLayout for Text-Based Visual Programming Languages

The central design question is:

Should a visual program's node positions and layout be part of its source code, or should the editor calculate them from the program's structure?

This decision affects source readability, version control, deterministic rendering, collaboration, editor performance, and how well a visual program survives changes to its syntax or graph structure.

For a text-based visual programming language, the challenge is especially interesting because the same program has two representations:

- **Textual representation:** a source file that can be edited, generated, diffed, merged, and processed by tools or AI models.
- **Visual representation:** a graph of nodes, ports, connections, groups, and annotations arranged on a canvas.

The source needs to describe the program's meaning, while the visual editor needs to make that meaning understandable to humans. Those goals overlap, but they are not identical.

## Contents

- [1. The three fundamental layout models](#1-the-three-fundamental-layout-models)
- [2. Separate program semantics from visual presentation](#2-separate-program-semantics-from-visual-presentation)
- [3. Coordinate systems: more than just X and Y](#3-coordinate-systems-more-than-just-x-and-y)
- [4. AutoLayout: how node positions are calculated](#4-autolayout-how-node-positions-are-calculated)
- [5. Where should layout information be stored?](#5-where-should-layout-information-be-stored)
- [6. A better alternative to saving every coordinate: layout intent](#6-a-better-alternative-to-saving-every-coordinate-layout-intent)
- [7. Deterministic layout and reproducibility](#7-deterministic-layout-and-reproducibility)
- [8. Incremental layout: preserving the user's mental map](#8-incremental-layout-preserving-the-users-mental-map)
- [9. Difficult cases the specification should address](#9-difficult-cases-the-specification-should-address)
- [10. Proposed architecture for a text-based graph language](#10-proposed-architecture-for-a-text-based-graph-language)
- [Proposed layout contract](#proposed-layout-contract)
- [11. How to evaluate the design](#11-how-to-evaluate-the-design)
- [12. Further research directions](#12-further-research-directions)
- [Conclusion](#conclusion)

## 1. The three fundamental layout models

**A. Explicit coordinates**

Every node stores its position in the source file or in associated persistent layout data.

```text
node Add at (320, 160)
node Multiply at (560, 160)
```

Best when spatial arrangement is part of the user's authored work.

**B. Fully automatic layout**

Node positions are derived from graph structure, node dimensions, and a layout algorithm.

```text
result = multiply(add(a, b), c)
```

The editor calculates positions without requiring persistent coordinates.

Best for generated graphs, canonical diagrams, and source-first workflows.

**C. Hybrid layout**

The program's structure is authoritative, while layout is partially or wholly persistent. Nodes may be auto-arranged initially and manually adjusted afterward.

Best for a serious visual programming environment where both text editing and graphical editing are first-class.

The hybrid model is often the strongest starting point. However, it is important to distinguish a hybrid data model from a hybrid layout algorithm: the former decides what is persisted, while the latter decides how positions are calculated.

## 2. Separate program semantics from visual presentation

The most important architectural principle is to distinguish three layers of information.

*Figure: three layers of information*

1. **Semantic graph** — Nodes, ports, edges, types, execution order, expressions. *Defines what the program means.*
2. **Layout model** — Positions, ordering constraints, groups, pins, layout hints. *Defines how the graph should be organized.*
3. **Rendered canvas** — Pixel coordinates, zoom, pan, selection, wire routing. *Defines what the user sees now.*

These layers should communicate through well-defined interfaces, not be collapsed into a single data structure.

For example, a node's identity and connections belong to the semantic graph. Its preferred position might belong to the layout model. Its current screen position is a result of layout and viewport transformations.

This distinction is valuable even if everything is stored in one file. It prevents changes to the visual arrangement from accidentally changing the program's meaning.

### What belongs in each layer?

| Property | Recommended layer |
| --- | --- |
| Node ID and operation type | Semantic |
| Input/output ports and connections | Semantic |
| Node label that changes program behavior | Semantic |
| Node position or preferred position | Layout |
| Node ordering constraints | Layout |
| User-created groups and annotations | Usually layout/presentation |
| Edge routing bend points | Layout, unless semantically meaningful |
| Zoom, pan, current selection | Editor session state |
| Automatically calculated node dimensions | Render/layout cache |

There are exceptions. A group might represent a semantic module rather than a visual grouping. A comment might be part of the program's documentation. A node's order might affect evaluation in an imperative language. Those properties must be classified according to their actual semantics, not simply according to how they appear on screen.

## 3. Coordinate systems: more than just X and Y

A visual editor generally needs several coordinate spaces. Treating all coordinates as interchangeable is a common source of bugs.

**World coordinates**

The persistent or logical position of an object in the graph. These should not change when the user zooms or pans the canvas.

**Viewport coordinates**

Positions relative to the visible canvas region. Scrolling, panning, and zooming affect the relationship between world and viewport coordinates.

**Screen coordinates**

Physical or logical display coordinates used for rendering, pointer input, and hit testing. Device pixel ratio can introduce another conversion.

### The basic transformation

For a simple 2D canvas, let:

- $w=(x_w,y_w)$ be a world position.
- $s$ be the zoom scale.
- $t=(t_x,t_y)$ be the viewport translation.
- $v=(x_v,y_v)$ be the viewport position.

Then:

$$ v = sw+t $$
In expanded form:

$$ x_v=sx_w+t_x,\qquad y_v=sy_w+t_y $$
The inverse transformation is:

$$ x_w=\frac{x_v-t_x}{s},\qquad y_w=\frac{y_v-t_y}{s} $$
Suppose a node is at world position $(200,100)$, the zoom is $1.5$, and the viewport translation is $(40,20)$. Its viewport position is $(340,170)$.

If the user drags the node, the editor should convert the pointer position back to world coordinates before saving the new location. Otherwise, zooming in would cause a drag to produce a different logical displacement than intended.

For more sophisticated editors, use affine transformation matrices. These support translation, scaling, rotation, and nested coordinate spaces, and they compose naturally.

### Coordinate-system design choices

- **Origin:** Use a stable world origin, typically at $(0,0)$, without requiring the graph to remain in positive coordinates.
- **Axis direction:** Document whether Y increases downward, as in most GUI canvases, or upward, as in conventional mathematical coordinates.
- **Units:** Use abstract graph units rather than physical screen pixels. Specify whether positions refer to a node's top-left corner, center, or anchor.
- **Precision:** Choose a numeric representation and rounding policy. Fractional positions can be useful during interactive movement, even if final placement snaps to a grid.
- **Grid:** Make grid snapping an interaction policy, not an assumption built into every coordinate calculation.
- **Zoom and pan:** Treat them as viewport state rather than node properties.

The most useful invariant is that zooming, panning, resizing the editor window, or changing display density must not silently modify saved graph positions.

## 4. AutoLayout: how node positions are calculated

AutoLayout is not one algorithm. It is a collection of algorithms that optimize different properties of a graph drawing.

The right choice depends on the kind of visual programming language being designed.

**Layered layout**

Nodes are arranged in ranks, often from left to right or top to bottom. The algorithm attempts to reduce edge crossings and produce a clear directional flow.

Good for dataflow graphs, execution pipelines, and dependency graphs. See Graphviz [dot layout](https://graphviz.org/docs/layouts/dot/) and [ELK Layered](https://eclipse.dev/elk/reference/algorithms/org-eclipse-elk-layered.html).

*Source: Graphviz (+1 more)*

**Force-directed layout**

Nodes behave as if connected by springs and repelling one another. The algorithm seeks a visually balanced arrangement rather than a strict execution direction.

Good for exploratory networks and relationship graphs; less suitable when a specific left-to-right flow is essential.

**Tree layout**

Parent nodes are arranged above or beside their children.

Good for expression trees, syntax trees, and nested control structures.

**Constraint-based and interactive layout**

Layout is calculated subject to existing positions, relative-order constraints, pinned nodes, grouping, and spacing requirements.

Good for hybrid editors that preserve the user's work while accommodating structural changes.

### The typical layered-layout pipeline

A layered algorithm often follows these stages:

1. **Cycle handling:** Identify cycles and choose a representation that allows the graph to be laid out in layers.
2. **Layer assignment:** Determine which nodes belong in which ranks.
3. **Crossing minimization:** Reorder nodes within ranks to reduce intersecting edges.
4. **Node placement:** Calculate actual coordinates and spacing.
5. **Edge routing:** Calculate paths between ports, including bends and orthogonal segments.

The Eclipse Layout Kernel documents these stages in its [Layered algorithm overview](https://eclipse.dev/elk/blog/posts/2025/25-08-21-layered.html).

*Source: Eclipse Foundation (+1 more)*

This pipeline has an important design implication: node positions are the output of a process with multiple competing objectives. A layout algorithm may reduce crossings but produce an unnecessarily wide graph. It may compact the graph but disrupt familiar node positions.

There is no single universally optimal layout.

### Layout objectives to define explicitly

A useful layout system should prioritize its objectives, for example:

1. Never overlap nodes or violate hard pin constraints.
2. Respect required ordering and grouping constraints.
3. Minimize edge crossings.
4. Keep related nodes close together.
5. Minimize long edges and excessive bends.
6. Avoid moving nodes that do not need to move.
7. Keep the graph compact and legible.

For an interactive editor, objective 6 deserves special attention. A mathematically attractive redraw can still be a poor user experience if every small edit rearranges the entire canvas.

## 5. Where should layout information be stored?

There are more than two choices. A language can store layout in its main source file, a sidecar file, an embedded metadata section, or an external project database.

| Storage model | Advantages | Disadvantages |
| --- | --- | --- |
| Inline source | Self-contained; easy to share | Layout changes clutter code diffs |
| Separate sidecar file | Clean semantic source; layout can be versioned independently | Files can become mismatched |
| Embedded metadata | Single artifact with explicit separation | More complicated syntax and tooling |
| Editor-local cache | No source pollution; convenient for personal work | Not portable or reliably shareable |
| External project database | Supports rich editor state and collaboration | Harder to inspect, merge, and use outside the editor |

### Option A: Store coordinates inline

For example, a hypothetical graph language could use:

```mermaid
graph Main {
 node a = Input("x") at (80, 120)
 node b = Add(a, 10) at (320, 120)
 node c = Output(b) at (560, 120)
}
```

This makes the visual arrangement part of the source artifact. It is straightforward to reconstruct the graph exactly, provided the editor honors the stored positions.

However, it introduces several problems:

- Reformatting a graph changes source even when program behavior is unchanged.
- Automatically rearranging nodes can create large, noisy diffs.
- AI-generated edits may waste tokens reproducing coordinates.
- Merging two branches can produce conflicts in otherwise independent visual edits.

Inline coordinates are reasonable when spatial layout is an intentional, reviewable part of the artifact, or when the language is intended to be a self-contained interchange format.

### Option B: Store coordinates in a sidecar file

The semantic source might look like this:

```mermaid
graph Main {
 node a = Input("x")
 node b = Add(a, 10)
 node c = Output(b)
}
```

A corresponding `Main.layout.json` could contain:

```json
{
  "schemaVersion": 1,
  "graph": "Main",
  "nodes": {
    "a": {
      "x": 80,
      "y": 120
    },
    "b": {
      "x": 320,
      "y": 120
    },
    "c": {
      "x": 560,
      "y": 120
    }
  }
}
```

This separates program semantics from spatial presentation while retaining a portable, version-controlled representation of the graph.

The key complication is identity: if a node is renamed, deleted, duplicated, or regenerated, the editor must determine which layout entry belongs to which semantic node.

Use stable node identifiers, not source line numbers or display names, as the primary keys.

### Option C: Embed declarative layout hints

A third option is to store relative constraints rather than exact coordinates:

```text
layout Main {
 direction left_to_right
 place a before b
 place b before c
 keep a, b, c in group "Calculation"
}
```

This allows the editor to choose exact positions while preserving the author's organizational intent.

It also makes layout less sensitive to node dimensions and font changes. However, constraints can become contradictory, and the editor must define how conflicts are resolved.

### Recommended approach

For a new text-based visual programming language, the recommended approach is to use:

- A semantic source file as the authoritative definition of program behavior.
- A portable sidecar file for saved visual arrangement.
- Declarative layout constraints where relative placement matters more than exact coordinates.
- Editor-local session state for zoom, pan, selection, and temporary interactions.
- A deterministic AutoLayout engine as a fallback and a user-invokable operation.

This is a recommendation, not a universal rule. A language designed primarily for generated diagrams or reproducible rendering may benefit from inline coordinates instead.

## 6. A better alternative to saving every coordinate: layout intent

The important distinction is not simply coordinates versus no coordinates. It is what the author intends to preserve.

Consider four levels of layout information:

**Level 1 — Exact position**

Keep this node at a specific world coordinate.

Useful for manually arranged diagrams and precise compositions.

**Level 2 — Relative position**

Keep this node to the left, right, above, or below another.

Useful when layout should adapt to node dimensions.

**Level 3 — Structural grouping**

Keep related nodes together or inside a group.

Useful for subgraphs, functions, and conceptual regions.

**Level 4 — Pure derivation**

Calculate layout entirely from graph structure and layout rules.

Useful for generated graphs, canonical output, and disposable views.

A mature editor can support all four simultaneously. For example, a user could pin a critical node, constrain two branches to remain ordered, group a subgraph, and allow everything else to be automatically arranged.

This avoids the false choice between fully manual and fully automatic layout.

## 7. Deterministic layout and reproducibility

A subtle but important question is whether the same source code always produces the same graph arrangement.

Suppose two developers open the same source file. If their editors independently calculate layout, will the resulting graphs look the same?

Not necessarily.

Layout can vary because of:

- Different algorithm versions or configuration.
- Different font metrics, node sizes, or text wrapping.
- Different ordering of nodes in the input graph.
- Random initialization or nondeterministic tie-breaking.
- Different interpretations of layout constraints.
- Different versions of the editor or rendering engine.

For a text-based language, this matters because generated layouts may appear in screenshots, documentation, code reviews, automated tests, and exported diagrams.

### Three useful reproducibility guarantees

| Guarantee | Meaning |
| --- | --- |
| Semantic reproducibility | The program behaves identically |
| Geometric reproducibility | The calculated node and edge geometry is identical |
| Pixel reproducibility | The rendered image is identical |

The first is essential. The second is valuable for canonical layouts and stable diffs. The third is much harder because rendering also depends on fonts, antialiasing, device scale, and other presentation details.

If deterministic geometry matters, the specification should define stable node ordering, tie-breaking rules, algorithm configuration, numeric precision, and versioning. A random seed alone is not sufficient.

Graphviz's documentation, for example, distinguishes graph semantics from layout engines and supports explicit position attributes for relevant engines. See its [position attribute documentation](https://graphviz.org/docs/attrs/pos/) and [dot layout documentation](https://graphviz.org/docs/layouts/dot/).

*Source: Graphviz (+2 more)*

A practical design is to make the layout engine and its configuration identifiable in the saved metadata, while allowing the editor to migrate old layout files when the engine changes.

## 8. Incremental layout: preserving the user's mental map

A graph editor is not merely a diagram generator. It is an interactive environment in which users develop a mental model of where important nodes are located.

If connecting one node causes 200 other nodes to move, the resulting graph may be aesthetically cleaner but substantially harder to work with.

A useful system distinguishes between three operations:

- **Initial layout:** Arrange a graph that has no saved positions.
- **Incremental layout:** Accommodate newly added, deleted, or connected nodes while preserving as much of the existing arrangement as possible.
- **Full relayout:** Recalculate the entire graph when the user explicitly requests it.

A fourth operation, local relayout, can rearrange a selected region without disturbing unrelated regions.

### Example: adding a node

Suppose the existing graph contains:

```text
Input → Filter → Transform → Output
```

The user adds a validation node:

```text
Input → Filter → Validate → Transform → Output
```

A naive full layout might move every node to make room. An incremental layout could insert `Validate` between `Filter` and `Transform`, move only the affected downstream nodes if necessary, and retain the rest of the graph.

For a robust editor, layout should have a notion of movement cost: moving an existing node is undesirable unless it meaningfully improves readability or is required to satisfy a constraint.

One conceptual objective function is:

$$ L = \alpha C + \beta O + \gamma D + \delta M $$
where:

- $C$ is the number or cost of edge crossings.
- $O$ is the cost of node overlaps.
- $D$ is a measure of excessive edge length or poor spacing.
- $M$ is the amount of movement from the previous layout.
- $\alpha,\beta,\gamma,\delta$ are weights.

In practice, some requirements should be hard constraints rather than weighted penalties. For example, overlapping nodes may be forbidden outright, while minimal movement is a preference.

The editor can use a more expensive algorithm for full layout and a faster, locality-preserving strategy for routine edits.

## 9. Difficult cases the specification should address

A complete coordinate and layout design needs explicit answers for several edge cases.

### Graph edits and stable identity

- What happens to layout when a node is duplicated?
- How are positions preserved when nodes are renamed?
- Does a deleted node's layout record get removed immediately?
- How are layout records for missing nodes handled?
- Can layout metadata refer to nodes inside nested graphs?

Stable semantic IDs should survive harmless source edits. IDs must not be regenerated merely because a user reformats or moves a node declaration.

### Variable node dimensions

Nodes can grow when labels, comments, ports, or expanded expressions change. Positioning only the top-left corner is not enough to prevent collisions.

The layout engine needs current node dimensions and anchor conventions. It should also distinguish between position and size: one may be persisted while the other is calculated from content.

### Cycles and multiple edges

Dataflow graphs can contain cycles, feedback connections, and multiple edges between the same nodes. Layered algorithms must handle these explicitly rather than assuming the graph is a DAG.

### Nested graphs and groups

If a node contains a nested graph, is the child graph positioned in its own coordinate space? Can it overflow its parent? Does resizing a group reposition its contents? Define the transformations and containment rules.

### Collaborative editing

If two users move the same node, or one user changes the graph while another changes its layout, the system needs a conflict policy. Semantic edits and layout edits should be merged independently whenever possible.

### Invalid or outdated layout metadata

A layout file should be treated as recoverable presentation state, not as a reason to make valid source code unusable. If the metadata is malformed, incompatible, or stale, the editor should report the problem and offer to recalculate the layout.

## 10. Proposed architecture for a text-based graph language

The following is a concrete starting specification that could be adapted to a language such as a graph-oriented language.

## Proposed layout contract

Illustrative design proposal, not an existing language standard.

1. **Semantic source** — Defines nodes, ports, edges, node identities, and all execution-relevant properties. Visual position does not change program semantics.
2. **Layout sidecar** — Stores positions, pinned nodes, relative ordering constraints, grouping, optional edge waypoints, and schema version.
3. **Coordinate contract** — Persistent positions use world coordinates, with a documented origin, axis direction, units, and anchor convention. Viewport state is separate.
4. **Layout modes** — Support `automatic`, `incremental`, `manual`, and `hybrid` behavior. These are illustrative mode names.
5. **Identity and recovery** — Layout entries are keyed by stable graph and node IDs. Unknown IDs are ignored or reported, and stale records can be pruned safely.
6. **Determinism** — Define deterministic ordering and tie-breaking where reproducible geometry is required. Record layout-engine version and relevant options.
7. **Editing guarantees** — Ordinary text edits must not overwrite unrelated saved positions. Ordinary layout changes must not alter semantic source unless explicitly requested.

### Example sidecar schema

An extended illustrative representation might look like this:

```json
{
  "schemaVersion": 1,
  "graphId": "main",
  "layout": {
    "mode": "hybrid",
    "direction": "right",
    "gridSize": 16,
    "engine": "layered",
    "engineVersion": "1"
  },
  "nodes": {
    "input-1": {
      "position": [
        80,
        120
      ],
      "pinned": true
    },
    "filter-1": {
      "position": [
        256,
        120
      ]
    },
    "output-1": {
      "position": [
        480,
        120
      ]
    }
  },
  "constraints": [
    {
      "type": "leftOf",
      "first": "input-1",
      "second": "filter-1"
    }
  ]
}
```

This schema is illustrative. A production design would need to define the exact meaning of `pinned`, how constraints interact, how node sizes are determined, and whether engine-specific options are portable.

Notice that the file can preserve both an exact position and a relational constraint. This is intentional: the exact position can be used for interactive editing, while the constraint communicates intent to an AutoLayout engine.

## 11. How to evaluate the design

Before finalizing the language specification, test representative graphs under several workflows.

| Test case | What it reveals |
| --- | --- |
| Open source with no layout file | Initial layout quality |
| Reopen a manually arranged graph | Position persistence |
| Rename and reorder declarations | Stability of node identity |
| Insert a node into a dense graph | Incremental layout behavior |
| Edit source and layout in parallel | Separation of concerns |
| Merge two branches | Diff and conflict behavior |
| Change fonts or node labels | Size and geometry robustness |
| Upgrade the layout engine | Migration and reproducibility |
| Open the graph in another editor | Portability |
| Generate a graph using an LLM | Resistance to unnecessary coordinate tokens |

A particularly important metric is layout churn: how many existing nodes move after a small semantic edit. The system can measure the proportion of nodes that moved, their average displacement, and the number of unaffected graph regions that changed.

You should also evaluate readability: edge crossings, graph area, average edge length, node overlaps, and how easily users can trace data or execution flow.

## 12. Further research directions

These questions are closely related to the design problem and deserve their own research notes:

- **Incremental Graph Layout:** How can a graph be updated without disrupting a user's mental map?
- **Stable Node Identity:** How can semantic node IDs survive text rewrites, refactoring, and LLM-generated code?
- **Canonical Graph Rendering:** Can a language define a canonical geometric representation for reproducible documentation and testing?
- **Layout Constraints as Source:** Should relative positioning and grouping be expressed in the language, metadata, or editor UI?
- **Semantic Diff vs. Visual Diff:** How can tooling distinguish a behavior change from a layout-only change?
- **Collaborative Layout Editing:** How should concurrent changes to node positions and graph structure be reconciled?
- **LLM-Friendly Graph Serialization:** Can source omit coordinates while still giving an AI model enough structural hints to produce understandable visual graphs?
- **Layout Migration:** How should layout files evolve when node shapes, ports, coordinate conventions, or layout algorithms change?

## Conclusion

The key design insight is that program structure, layout intent, calculated geometry, and viewport state are different kinds of information.

For a text-first visual programming language, the design should make semantic source independent of exact coordinates, preserve important layout intent in portable metadata, and support both deterministic full layout and movement-preserving incremental layout.

That gives text-based tools and AI systems a concise semantic representation, while still allowing humans to arrange and maintain complex visual graphs without having their work constantly discarded by the layout engine.

The most important remaining decision is whether the language primarily represents dataflow graphs, execution-flow graphs, or general-purpose graphs. That choice strongly influences the appropriate layout algorithms and persistence rules.

For a general-purpose text-and-graph language, a hybrid policy is appropriate: keep semantic structure independent of coordinates, persist meaningful layout intent separately, and use deterministic full and incremental layout algorithms.
