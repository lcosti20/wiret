# Graph Layout Algorithms

Graph layout algorithms automatically assign positions to nodes and route edges so that a graph is readable, understandable, and easy to navigate. They are a core component of visual programming environments, node editors, dependency visualizers, workflow designers, UML tools, circuit editors, and graph-based knowledge systems.

The central challenge is that a graph's logical structure does not uniquely determine its visual arrangement. A layout engine must choose where nodes go, how edges travel between them, how much space to allocate, and which visual relationships to emphasize.

For research into graph editors and visual programming languages, three particularly important technologies are Graphviz, Eclipse Layout Kernel (ELK), and the family of Sugiyama-style layered algorithms. They address overlapping but distinct needs: graph rendering, interactive diagram layout, and hierarchical arrangement of directed graphs.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://www.graphviz.org\&sz=32)

Graphviz+2



## 1. What a graph layout algorithm does

A graph consists of vertices (nodes) and edges (connections). A layout algorithm converts that abstract structure into geometric information.

[Graphviz 使用教程-腾讯云开发者社区-腾讯云](https://images.openai.com/static-rsc-4/TM8GpxFgqy3l_pnYlH7-ZM9etChJpWfD43rp2ogJoyDgQt4HMxPwSVg1BfrDOvn4UnuriFFOVIdHQ1wIwRT2AM5MSSBcdZJRD4TFQF8bwguxCTuk5Y-cQrbTsak6R8mpB63aCmi70dOr2MmKV_4U5Qr9i8up52qyGsGFEbFufMc?purpose=inline)

1\. Interpret the graph

Identify nodes, edges, directions, weights, groups, ports, dependencies, and any user-specified constraints.

[How to draw hierarchy diagram? - GoJS - Northwoods Software](https://images.openai.com/static-rsc-4/3B693pc3CSy-whz-pCS2kj7s_9kYIrq6UWaxLrhUWXaUQ9LhBuvIAt3wrBXe4sR3QhepeJyEyVPjkE8dzPfpuuamui9la5nn-BjYB6yF0xLGjpgyIHUYnnPCrfDhr-6U9fBYQoGLpYTA_v6_kgkXgD60RXXJaRZFIFaiXi35IhI?purpose=inline)

2\. Compute a layout

Assign nodes to layers or regions, order them, calculate coordinates, and choose edge routes.

[Convert HSV to RGB - python - Tech-Artists.Org](https://images.openai.com/static-rsc-4/ZY9srpwdwsJ8UrtvzmE0Uefn0fJr1ntmbPQt4Ikr8qqTL1K2XP5h3Lnp78qKfrMhgvx4qLSZ0toWq9rz2f-DrTiuO0UY9u4xMhf_p7yP_nT01CIhPqkpeV---MhXIXBrhRbesVAR8Z29yMLF-dopp9jmfqRwX8SWaIe_DHYynfE?purpose=inline)

3\. Render the result

Use the computed geometry to draw nodes, connection lines, arrowheads, ports, labels, and groups in the editor.

A layout engine typically returns node positions and dimensions, along with edge bend points or routing information. The rendering application remains responsible for displaying that geometry and integrating it with its interaction model.

### What makes a layout good?

There is no single universally optimal layout. Common quality objectives include:

- Few edge crossings: reduce intersections between connections.
- Short edges: avoid unnecessarily long connections.
- Clear direction: make control flow and dependency direction obvious.
- Low edge complexity: reduce bends, overlaps, and awkward routing.
- Balanced spacing: avoid crowding and excessive whitespace.
- Preserved grouping: keep related nodes together.
- Stable positioning: avoid moving unrelated nodes after small edits.
- Constraint satisfaction: respect fixed nodes, port positions, alignment, and ordering requirements.

These objectives can conflict. Minimizing edge length may increase crossings; reducing crossings may create an unusually wide graph. A practical layout engine therefore uses heuristics, optimization methods, and configurable priorities rather than guaranteeing a perfect drawing.

## 2. Major families of graph layout algorithms

[PPT - Layered Graph Drawing (Sugiyama Method) PowerPoint Presentation, free download - ID:1356958](https://images.openai.com/static-rsc-4/b4sM8n6_h0xX6JnVcQVyc3pEgwIT3hC13ZBxijzXeh4ptNC6Z2aTJ1-lPIRugyQ5bYA9W77D98sZyhEcmdqjgIXSsVqRYNEI0Asz7HtHD2d97pGcDvbUBT490W_Wqi0rql7bBWc_BKhut2927u1AQC8e4hWJeDhcYraHjt6zWG4?purpose=inline)

Layered / hierarchical

Best for directed flow

Places nodes in successive layers, usually following the direction of edges. Useful for execution graphs, data pipelines, dependency graphs, and state transitions.

[Force-Directed Graph Layout](https://images.openai.com/static-rsc-4/V1FJAYFrCWebWilUfmRndP60NH9Xa2FoFb-FSmX62hB9KCXqRcGImNceCNXcOKoJqsLicFLPdVK8_yVso_ATOOzw3QU51rybM6vGKcQUwDNnCiKgz0bK9w47BYSemsdlW_eeHSYiRjD3QysE7JiazZYNMUS2KRgGtEtSLVvuDYg?purpose=inline)

Force-directed

Models nodes as repelling particles and edges as attractive springs, or uses related energy-minimization formulations. Useful for social networks, knowledge graphs, and exploratory visualization.

[About Radial Layout](https://images.openai.com/static-rsc-4/VyLhHuVOWz-5P7KCcEGICDqnO76ezYurXAv7T8j39exLz7mt_iAt6htp-iIbbZQtKfhHbH_hisFnr9hE7AZ4HTT2tHYbt-Docj7WAtYyDCi0tS_7U_1hsrsmmVT2nc3p2ZKIfKd8L9EqiX7w3nenNp5ZgaJKg5GbupZtLpjTYRE?purpose=inline)

Radial / circular

Places nodes around a center or on circular paths. Useful for cyclic dependencies, radial hierarchies, and graphs where centrality or cyclic structure matters.

[16.3 From Expressions to Statements](https://images.openai.com/static-rsc-4/2oeLFx7bLLcuiKs8sX5NG_zogVq4ZE3IRAaLYEYaRSs10Cu7bk_Vk6G4givJI0fAXNOL591vlXqtd-tJyxFWKmdB_MiYji7gT0efAuuPot7usY8TFqTaIxQyOIXjnzKkGC0FcNefGJU9GOO_t1cJ6U82W4Wk9PLtYuL-4LyvuKo?purpose=inline)

Tree / tidy-tree

Arranges parent-child relationships into a compact hierarchy. Useful for syntax trees, scene hierarchies, file trees, and organizational structures.

[About Orthogonal Layout](https://images.openai.com/static-rsc-4/BBx_RX0xvYA92CIcgw4eoaf-TUHaJQYgpz5lYTVpT_zoiU3umy2MjUjvgNNJSK9_fsSZGV9jYFRYBKH9co1_hKyxERKbOAh3Ai73sNsoksD1QlFn1nFQfSLpwjY22EVH8cIMrViFFPjIw_Wle1CZVxaztAIMMZI42D7zhoBTCw8?purpose=inline)

Orthogonal / constraint-based

Routes edges along horizontal and vertical segments, often respecting ports and alignment constraints. Useful for circuit diagrams, block diagrams, and technical editors.

These families are not mutually exclusive. A layered algorithm can use orthogonal edge routing; a tree layout can be combined with compound grouping; a force-directed layout can preserve fixed node positions.

## 3. The Sugiyama method in detail

The Sugiyama method is one of the most important algorithms for directed graph drawing. It is especially relevant to visual programming because execution flow, dependencies, and data transformations naturally suggest a layered arrangement.

Its traditional pipeline has five phases: cycle removal, layer assignment, crossing minimization, node positioning, and edge routing.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://tikz.dev\&sz=32)

PGF/TikZ Manual+1



Input graph

Nodes, edges, sizes, constraints

1\. Cycle removal

Temporarily reverse selected edges

2\. Layer assignment

Determine which rank each node occupies

3\. Crossing minimization

Reorder nodes within each layer

4\. Coordinate assignment

Compute node positions and spacing

5\. Edge routing

Calculate paths, bends, and port connections

Output layout

Node coordinates and edge geometry

### Phase 1: Cycle removal

Layered layouts work most naturally when edges point forward through the layers. Real graphs, however, can contain cycles.

Consider a graph where A leads to B, B leads to C, and C leads back to A. All three nodes cannot be arranged in strictly increasing layers while preserving every edge's forward direction.

The algorithm temporarily reverses one or more edges to break cycles, computes the layout, and restores the original edge directions during routing.

The important distinction is that the algorithm changes its internal representation, not the program's actual semantics. A visual programming editor must never accidentally change an execution connection just because a layout algorithm temporarily reversed it.

### Phase 2: Layer assignment

Each node receives a layer or rank. For a simple directed acyclic graph, a useful baseline is:

\\[ r(v)= \begin{cases} 0 & \text{if }v\text{ has no predecessors}\\\ 1+\max\limits\_{u\to v}r(u) & \text{otherwise} \end{cases} \\]

This assigns each node to a layer one greater than its deepest predecessor.

For example:

- Layer 0: input nodes
- Layer 1: transformations
- Layer 2: output nodes

More sophisticated methods optimize graph height, edge lengths, and overall width. ELK Layered supports multiple strategies, including network-simplex-based layer assignment.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://eclipse.dev\&sz=32)

Eclipse Foundation+1



### Phase 3: Crossing minimization

Nodes in the same layer can be arranged in many different orders. Those orders can dramatically change the number of edge crossings.

A common heuristic is the barycenter method. It estimates a node's preferred position using the positions of its neighbors in the adjacent layer, then reorders nodes according to those estimates. Repeated sweeps refine the ordering.

This is an optimization problem, not a guarantee of the globally best result. Layered algorithms therefore combine heuristics, repeated passes, and sometimes local swaps to improve the drawing.

### Phase 4: Coordinate assignment

After the node ordering has been selected, the engine calculates actual \\(x,y\\) coordinates.

It must account for:

- Variable node widths and heights.
- Minimum separation between nodes and layers.
- Alignment of related nodes.
- Edge straightness and bend count.
- Overall aspect ratio.
- Group boundaries and port positions.

This phase is particularly important in a node editor where a node may contain a variable number of pins, long labels, embedded controls, or dynamically sized content.

### Phase 5: Edge routing

Finally, the engine calculates how connections travel between nodes.

Typical routing styles include:

- Straight: direct connections where possible.
- Polyline: a sequence of straight segments.
- Orthogonal: horizontal and vertical segments.
- Spline: smooth curved connections.

In technical node editors, orthogonal routing can be especially useful because connections look structured and can respect port constraints. ELK Layered supports all of these broad routing styles.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://eclipse.dev\&sz=32)

Eclipse Foundation+1



## 4. Comparing Graphviz, ELK, and other tools

[How to visualize or draw graph from nodes and edges ? Javascript dependency graph generation | by BinaryBenevolence | Medium](https://images.openai.com/static-rsc-4/CIUJ9pbUehDZM-Q8WhbvWvrGkDpFRVSNy2oZS5Tj4Yb9f7Le1jj5CTgV5ZOpn6ah3RoQsLnc90dPts5pG1uNE3xzZpTJMgDkZ-3J7sXy-etv3mJIUWFYLwP0nvibNiEN0vK6UtUGihSi9XGsUtsXl9jdjq59UMMF4senOiE0F7I?purpose=inline)

Graphviz

Best for general graph rendering and batch generation

A mature graph visualization toolkit with multiple layout engines. Its `dot` engine specializes in hierarchical directed graphs; `neato` and `fdp` handle spring or force-based layouts, while `sfdp` targets larger graphs and `circo` and `twopi` offer circular and radial arrangements.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://www.graphviz.org\&sz=32)

Graphviz+2



[Layout engines documentation](https://graphviz.org/docs/layouts/?utm_source=chatgpt.com)

[The Eclipse Layout Kernel   sirius con 2017 | PDF](https://images.openai.com/static-rsc-4/VqUCwwrAdn2IazYkFwUDy7SE60S8COM0rOqYexMEvBcV2yV95PFUotpJfYzRc5OjKV8Ivo7VVjip4Z1AVhU2nq-dO7Q4MayZf5iVajO_6ZzF81wS_CtbtSfw3E9JoSQRjwk1P8Cp8liylMOSIz3Q3JQfU2joxPKABG9gmyy3Zcs?purpose=inline)

Eclipse Layout Kernel (ELK)

Best for structured interactive diagram editors

Provides algorithms and infrastructure for diagram applications. ELK Layered supports ports, multiple edges, labels, nested graphs, and different routing styles, making it particularly relevant to node-based programming interfaces.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://eclipse.dev\&sz=32)

Eclipse Foundation+1



[ELK Layered reference](https://eclipse.dev/elk/reference/algorithms/org-eclipse-elk-layered.html?utm_source=chatgpt.com)

[d3.js force-directed graph with randomly-colored circles as nodes and accompanying text labels](https://images.openai.com/static-rsc-4/okW23cj83hn-EYvzu3t3wwSmV7gH3hCPRDxIiCVy07tFyJYVz_jx7hAYkZpawICAt2rZixq6psWpXt6_sP20W6WOPLc_TEr4rtvjO_l1sMwkuEvWxlerLmz0j2Rr8-lutDMbEK1d6BB9GPAxkVkZqQCF9LJQN7yv7IftLd0uV8E?purpose=inline)

D3.js force simulation

Best for browser-based exploratory networks

Offers a flexible force simulation for applications that want to control node motion, forces, and simulation behavior directly. It is well suited to exploratory networks, but it does not automatically provide all the diagram-specific routing and layered constraints of a specialized layout engine.

[D3 force documentation](https://d3js.org/d3-force?utm_source=chatgpt.com)

[Dagre Layout | G6 Graph Visualization Framework in JavaScript](https://images.openai.com/static-rsc-4/f0xiZniv6ojnPaIP_2yHO-Om-rq5QIg9ykVdFo0OHC0pmr-DIbk9RgDTKchWxirPtNwuBemaJZrKhfJw8VF4oGgeplLJ8_ZBlklMZU03q22AA_Pkyi6gqK1xopo2uS6-ayVMwELWyQdmd39I4aTWWJJqkE4HeOSvnn35sEr__NE?purpose=inline)

Dagre

Best for relatively lightweight directed layouts

A JavaScript library focused on client-side directed graph layout. Worth evaluating for web applications that need hierarchical positioning without adopting a larger diagram-layout framework.

[Dagre project](https://github.com/dagrejs/dagre?utm_source=chatgpt.com)

### Practical comparison

| Capability                     | Graphviz `dot`                       | ELK Layered                                   | D3 force                               |
| ------------------------------ | ------------------------------------ | --------------------------------------------- | -------------------------------------- |
| Layered directed layout        | Yes                                  | Yes                                           | Not built in                           |
| Force-directed layout          | Other Graphviz engines               | Other ELK algorithms                          | Yes                                    |
| Port-aware routing             | More limited for interactive editors | Strong support                                | Custom implementation                  |
| Nested diagram support         | Clusters and subgraphs               | Compound graph support                        | Custom implementation                  |
| Browser integration            | Often through a renderer or service  | Available through integrations such as ELK.js | Native JavaScript                      |
| Incremental interactive layout | Not its main focus                   | Supports interactive layout options           | Simulation can be updated continuously |

These are broad architectural comparisons, not universal performance rankings. Actual capabilities depend on the engine, integration, graph structure, and configuration.

## 5. The difficult problem: preserving a user's layout

For an interactive visual programming editor, computing a good layout from scratch is only half the problem.

Suppose a user has manually positioned 40 nodes, aligned a group of arithmetic operations, and routed several important connections. They add one new node and connect it to an existing branch.

A naive automatic layout may rearrange all 40 existing nodes. Even if the new drawing is mathematically cleaner, the editor has destroyed the user's spatial organization.

This leads to several important concepts.

### Incremental layout

Instead of laying out the entire graph from scratch, update only the affected portion when possible.

Possible strategies include:

- Reposition only newly added nodes.
- Recompute a local neighborhood around an edited connection.
- Keep unrelated connected components fixed.
- Preserve the existing ordering of unaffected nodes.
- Use prior positions as reference points during optimization.

ELK exposes interactive layout configuration, including a reference-point option, although the exact behavior depends on the selected algorithm and its configuration.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://eclipse.dev\&sz=32)

Eclipse Foundation+1



### Stability versus optimality

A useful layout objective is to minimize not just crossings and edge lengths, but also displacement from the previous layout:

\\[ E = \alpha C+\beta L+\gamma B+\delta D \\]

where:

- \\(C\\) = edge-crossing penalty
- \\(L\\) = edge-length penalty
- \\(B\\) = bend and routing penalty
- \\(D\\) = displacement from existing node positions
- \\(\alpha,\beta,\gamma,\delta\\) = configurable weights

This is a conceptual objective function, not a formula implemented identically by every engine. The key insight is that an editor can explicitly value stability alongside visual quality.

### Pinning and partial automation

A useful editor should distinguish between:

- Fully automatic: the engine controls every position.
- Semi-automatic: the engine arranges nodes while preserving constraints.
- Local automatic: only selected nodes or regions are rearranged.
- Manual: the user controls all positions.
- Hybrid: user positions are preserved by default, with explicit commands to reorganize a region or the entire graph.

The hybrid approach is often the most useful for programming tools: automatic layout should be an assistant to the user, not an authority that continually overrides their work.

## 6. Layout algorithms for visual programming languages

Visual programming introduces requirements beyond those of a conventional graph drawing.

[Construct 2 Style "Event Sheets" in UE4 - Feedback & Requests - Epic Developer Community Forums](https://images.openai.com/static-rsc-4/qPNOvmTntXcqN7jlytEaSsdUtVwdZYorna9NNatCg_h9yseWy0IJ0n62Jx3PH-iq5cXSouHsMoaLCmmS5kvR2GcNcSfjfIiTJPf42vlvpQOQTNYXkc6zYVeSCoX-0iy0XEuF26mNS-cPYDcO82yR2BS72GlmYeSwkynhmXYXUsQ?purpose=inline)

Execution-flow graphs

Prioritize execution direction, sequence ordering, branches, loops, and readable control-flow paths. A left-to-right or top-to-bottom layered layout is a natural starting point.

[Madrigal Games](https://images.openai.com/static-rsc-4/wOhB5-FNVdpEeOqoCxlOa082LZ6_fKMUzkkiGdDK3ALMdEsZHzjXbY-zLdMUYwLZsHcBJcH7dsKyCibptKDmYVgT1FaxH2TCnXhigVxFxae7ovJFREO9mJcuT_kDKOTXGgUVeOV9oiEVmleap28ePkjGtM19uz5yKx8Nbun48Fo?purpose=inline)

Data-flow graphs

Prioritize the direction from producers to consumers, data type compatibility, and readable wire routing. A node may have many inputs and outputs whose ordering must remain meaningful.

[RFE: Comment Boxes - General TouchDesigner Discussion - TouchDesigner forum](https://images.openai.com/static-rsc-4/u1heKt9S6uCHEdzKh1wMay9irn3eKicR9c4_xys_d-5cPCdVlMTZYZrWvdvIXSoQtNabndRNSbXT-mz2yAR9UNbw8vmBktW5y7ne2ntJRyH4Enlh8kUlVY7BIH7inZfXIc-YXxQPcPrpw3P31baN0JparTOA21pOEbfKVtD5xos?purpose=inline)

Mixed graphs

Combine execution edges, data edges, reroutes, annotations, groups, and feedback loops. Different edge classes may need different weights or routing rules.

A good implementation should explicitly model node dimensions, pin locations, connection direction, edge type, group membership, and user constraints. Treating the graph as merely a collection of points and lines will miss many of the details that make visual programs readable.

## 7. Recommended architecture for an automatic layout subsystem

For a graph editor with both textual and visual representations, I would separate the system into four layers.

Graph model

Nodes · Edges · Ports · Groups · Constraints

Layout policy

Algorithm selection · Direction · Spacing · Stability

Layout engine adapter

ELK.js · Graphviz · Custom algorithms

Geometry and rendering

Node coordinates · Edge paths · Hit testing · Viewport

This architecture keeps layout decisions independent of the programming language's semantics and the UI framework.

### A useful layout API

An application-level API could look like this:

```
type LayoutRequest = {
  graph: Graph;
  algorithm: "layered" | "force" | "tree";
  direction: "right" | "down" | "left" | "up";
  mode: "full" | "incremental" | "selection";
  spacing: {
    nodes: number;
    layers: number;
  };
  constraints: {
    fixedNodes: string[];
    preserveOrder: boolean;
    preserveGroups: boolean;
  };
};

type LayoutResult = {
  nodePositions: Map<NodeId, { x: number; y: number }>;
  edgeRoutes: Map<EdgeId, Point[]>;
};
```

This is an illustrative application-level interface, not the native API of Graphviz or ELK. In production, it would also need dimensions, port geometry, cancellation, error handling, coordinate conventions, and possibly nested layout results.

A separate adapter can translate this stable internal representation into the specific format expected by whichever engine is selected.

## 8. Implementation details worth researching

The algorithm itself is only one part of a robust layout system. The following issues often determine whether an implementation feels polished.

| Topic                  | Key research question                                                         |
| ---------------------- | ----------------------------------------------------------------------------- |
| Node measurement       | How are dynamic node sizes and labels incorporated before layout?             |
| Port constraints       | Can the algorithm preserve input/output sides and pin ordering?               |
| Edge routing           | How are crossings, overlaps, loops, and parallel edges handled?               |
| Incremental layout     | How can the affected region be identified and recomputed efficiently?         |
| Determinism            | Does identical input produce the same layout across runs?                     |
| User constraints       | Can positions, alignments, groups, and relative ordering be pinned?           |
| Large graphs           | How does performance scale with thousands of nodes and edges?                 |
| Asynchronous execution | Can layout run in a worker without blocking the UI?                           |
| Layout persistence     | Are positions stored in the graph model, a separate file, or editor metadata? |
| Undo/redo              | Is a layout operation treated as one undoable transaction?                    |

For a bidirectional text-and-graph editor, another distinction is crucial: semantic changes and layout changes should be separate operations. Moving a node should not modify the meaning of a program unless the language explicitly makes spatial position semantic. Likewise, changing the text should not unnecessarily erase manual layout information.

## 9. How to evaluate layout algorithms experimentally

A useful research project should compare algorithms on the same representative graphs rather than judging them by a few attractive screenshots.

Measure at least:

- Edge crossings per graph.
- Total edge length and number of bends.
- Bounding-box area and aspect ratio.
- Node and edge overlap counts.
- Computation time.
- Total displacement after incremental edits.
- Percentage of fixed-position and port constraints satisfied.

Test several graph families: trees, diamonds, long pipelines, dense dependency networks, cyclic graphs, compound graphs, and graphs with highly variable node sizes.

Also test edit sequences, not just static graphs. A layout that looks excellent on a freshly generated graph may perform poorly when a user repeatedly inserts nodes and changes connections.

## 10. Suggested research resources

ELK Layered — algorithm reference

Detailed documentation for algorithm phases, ports, routing, spacing, compound graphs, and configuration.

[Read the reference](https://eclipse.dev/elk/reference/algorithms/org-eclipse-elk-layered.html?utm_source=chatgpt.com)

Graphviz — layout engine catalog

Compare hierarchical, force-directed, circular, radial, and other layout strategies.

[Browse the layout engines](https://graphviz.org/docs/layouts/?utm_source=chatgpt.com)

Sugiyama method — technical overview

A detailed explanation of the layered algorithm's five phases, including node ordering and edge routing.

[Read the PGF/TikZ graph drawing manual](https://tikz.dev/gd-layered?utm_source=chatgpt.com)

ELK — integration and extension documentation

Useful when building a diagram editor, adapting the graph model, or developing a specialized layout algorithm.

[Browse ELK documentation](https://eclipse.dev/elk/documentation.html?utm_source=chatgpt.com)

## Conclusion

For a visual programming editor, I would begin by evaluating ELK Layered for structured node placement and routing, while using Graphviz as a useful reference point for classical graph drawing techniques. A custom incremental layout policy can then address what matters most to interactive users: preserving manual positions, minimizing unnecessary movement, and making small edits feel predictable.

The most promising research question is not simply how to draw a graph automatically, but how to produce a readable layout while respecting the programmer's existing spatial intent.
