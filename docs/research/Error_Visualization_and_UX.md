---
title: "Error Visualization and UX in Visual Programming Languages"
document_type: "Research note"
formatted: 2026-10-28
---

# Error Visualization and UX in Visual Programming Languages

Error visualization in a visual programming language (VPL) is the discipline of translating compiler diagnostics, runtime failures, type mismatches, and logical errors into visual, localized, actionable explanations within the graph itself.

The central idea is that users should not have to interpret a cryptic stack trace, search through source code, or guess which node is responsible for a failure. The environment should help them understand:

1. What went wrong? — Identify the error in plain language.
2. Where did it go wrong? — Highlight the exact node, wire, pin, or execution path involved.
3. Why did it go wrong? — Explain the violated rule or unexpected value.
4. How can it be fixed? — Offer relevant corrections without silently changing the program.
5. How can it be prevented? — Detect problems early, before execution.

For a graph-based programming environment, error visualization is especially important because the user's mental model is spatial and relational. A failure is not merely a line of code: it may be a broken connection, an incompatible data type, an unexpected value moving through several nodes, or a control-flow path that never executes.

The goal is to make debugging feel like inspecting a system of connected components rather than deciphering a compiler's internal language.

## Contents

- [1. The error-visualization pipeline](#1-the-error-visualization-pipeline)
- [2. Taxonomy of errors and their visual representations](#2-taxonomy-of-errors-and-their-visual-representations)
- [3. Mapping compiler errors back to the graph](#3-mapping-compiler-errors-back-to-the-graph)
- [4. Visual design patterns for communicating errors](#4-visual-design-patterns-for-communicating-errors)
- [5. Error visualization as a user-experience problem](#5-error-visualization-as-a-user-experience-problem)
- [6. Runtime errors: finding the broken wire](#6-runtime-errors-finding-the-broken-wire)
- [7. AI-assisted error explanation and repair](#7-ai-assisted-error-explanation-and-repair)
- [8. Related research and systems](#8-related-research-and-systems)
- [9. Open research questions](#9-open-research-questions)
- [10. Suggested design direction](#10-suggested-design-direction)

## 1. The error-visualization pipeline

A robust design starts by treating error visualization as a translation layer between the language implementation and the user interface.

1. **Error sources** — Parser · Type checker · Compiler · Runtime · Validator
2. **Structured diagnostic** — Error code · Severity · Source span · Node/pin IDs · Expected vs. actual
3. **Graph mapping** — Resolve source locations to nodes, wires, pins, and execution traces
4. **Visual explanation** — Highlight · Annotate · Explain · Suggest a fix
5. **User action and feedback** — Inspect · Correct · Rerun · Verify resolution

Each stage should be independent. The compiler should report what it knows about a failure, while the graph editor decides how to represent that information visually.

This separation also makes the system resilient to changes in the compiler, visual editor, and underlying language.

## 2. Taxonomy of errors and their visual representations

Different errors require different visual treatments. A single red outline around every problematic node is too simplistic: it does not distinguish an invalid connection from a runtime exception or a warning about suspicious behavior.

**A. Syntax and structural errors**

*Parse time*

The text representation is malformed, a required node field is missing, or a graph contains an invalid structure.

**Visualization:** Highlight the node or graph region that cannot be parsed. Show a local explanation such as “This node is missing its required operation.” If the parser cannot identify a precise node, highlight the smallest reliable enclosing region.

**B. Type errors**

A wire carries a value incompatible with the receiving pin's type.

**Visualization:** Highlight the wire and destination pin, show both types, and explain whether a conversion is possible. For example, “Expected a number, but this connection supplies text.”

**C. Runtime errors**

A graph compiles successfully but fails during execution: division by zero, invalid indexing, a missing object, or a failed operation.

**Visualization:** Mark the node that raised the exception, display the failing input values when safe, and trace the data or execution path leading to it.

**D. Logical and behavioral errors**

The program runs without crashing but produces an incorrect result.

**Visualization:** Compare expected and actual values, show relevant execution paths, and let users attach assertions or inspect intermediate values. These errors generally require additional intent or test information; a runtime system cannot always infer what “wrong” means.

**E. Static warnings and suspicious patterns**

Unreachable nodes, unused values, potentially unsafe operations, implicit conversions, or suspicious cycles.

**Visualization:** Use non-blocking warning indicators and explain the possible consequence. Avoid treating every warning as a fatal error.

A useful implementation distinguishes the origin of a failure, the location where it becomes observable, and the location where it can be corrected. These may be three different places in a graph.

## 3. Mapping compiler errors back to the graph

The most important technical challenge is preserving the relationship between a diagnostic and the visual elements that produced it.

A compiler might report an error in generated code, but the user works with nodes and connections. The editor needs a reliable mapping between those representations.

### Source maps for visual programs

A source map usually associates generated code locations with their originating source locations. A VPL can extend this idea to associate generated instructions with stable graph identities.

For example:

**Example graph**

- **Get name** — outputs `String`
- **Add 10** — expects a number
- **Display** — output node
- ⚠ *Cannot add text to a number* (error shown on the connection into **Add 10**)

The `Add 10` node expects a number, but the incoming connection carries text from `Get name`.

**Suggested fixes:** convert the text to a number if it represents a numeric value, or use a text-concatenation operation if the goal is to combine text.

This is a conceptual example, not a screenshot of an existing editor.

A practical source map might look like this:

```json
{
  "generatedRange": {
    "startLine": 42,
    "startColumn": 8,
    "endLine": 42,
    "endColumn": 19
  },
  "graphLocation": {
    "nodeId": "node_add_10",
    "pinId": "input_a",
    "edgeId": "edge_name_to_add"
  },
  "diagnosticId": "TYPE_MISMATCH"
}
```

The identifiers are illustrative. A production implementation should use the actual identifiers from the graph model.

### Important implementation requirements

- **Stable identifiers:** Node and pin IDs must survive ordinary graph edits, saving, reloading, and synchronization with the textual representation.
- **Precise spans:** Map diagnostics to the smallest meaningful target: a pin, a wire, an expression inside a node, or the whole node.
- **Transformation provenance:** If compilation expands one visual node into many instructions, preserve the identity of the original node throughout the transformation.
- **Multiple origins:** Some errors involve two or more nodes. A type mismatch, for example, should identify both the producer and the consumer.
- **Invalid intermediate states:** When the user edits a graph or its text, diagnostics should remain useful even if the program temporarily cannot compile.
- **Stale-diagnostic detection:** If the graph changes after a diagnostic is produced, do not confidently highlight an unrelated node merely because it occupies the same screen position or source line.

This last point is especially important for a text-and-graph editor with bidirectional synchronization. Source offsets can shift, nodes can be deleted, and generated code can change dramatically after a seemingly small edit.

A robust system treats graph identity as authoritative and source offsets as one possible mapping, rather than assuming that line numbers alone are sufficient.

## 4. Visual design patterns for communicating errors

### A. Inline highlighting

Mark the problematic element directly on the graph.

- **Wire:** The connection is incompatible or delivers an invalid value.
- **Input pin:** The receiving operation cannot accept the supplied type.
- **Node:** The operation itself is invalid or raised an exception.
- **Execution path:** The failure depends on a sequence of operations or a control-flow branch.

Use color together with shape, iconography, labels, or line styles. A red wire by itself is not sufficiently descriptive, and color alone is inaccessible to some users.

### B. Progressive disclosure

Avoid showing every technical detail immediately. Present a short, understandable explanation first, then let users expand it.

1. **Level 1 — Immediate feedback:** This connection needs a number.
2. **Level 2 — Explanation:** The upstream node produces text, but this operation accepts numeric values.
3. **Level 3 — Technical details:** Diagnostic `TYPE_MISMATCH`; expected `Number`; actual `String`; location `node_add_10.input_a`.
4. **Level 4 — Possible actions:** Convert to number · Use text concatenation · Explain the type rules.

The appropriate level depends on the user and task. Experienced programmers may prefer exact diagnostic codes and type names; beginners may need an explanation of what a type is.

### C. Error lists linked to the canvas

A separate diagnostics panel is useful for large graphs where errors may be off-screen or numerous.

Each entry should provide:

- A concise description and severity.
- The affected node or connection.
- A navigation action that pans and zooms to the target.
- A grouping strategy, such as by error category, graph region, or root cause.
- An indication of whether the error is new, unresolved, or fixed.

The panel and graph should stay synchronized: selecting an error highlights its graph location, while selecting a highlighted node reveals the relevant diagnostic.

Research on debugging by end-user programmers has explored this combination of visual fault localization, diagnostic lists, and expandable hints. See [Interactive, Visual Fault Localization Support for End-User Programmers](https://doi.org/10.1016/j.jvlc.2004.07.001) and [How End-User Programmers Debug Visual Web-Based Programs](https://epiclab.github.io/publications/cola19-kuttal.pdf).

*Source: ScienceDirect (+1 more)*

### D. Data-flow tracing and execution history

A runtime error is often difficult to understand because the bad value originated several nodes upstream.

A useful debugger should let users inspect:

- The value produced by each node.
- The values received by each input pin.
- Which execution paths were taken.
- Which nodes were skipped.
- The first point at which an observed value diverged from an expected value.
- The sequence of changes leading to the failure.

This approach is supported by research on visual debugging for reactive programs. Hoffswell, Satyanarayan, and Heer describe techniques that combine event timelines, dependency visualization, and in-context annotations to help users trace behavior. Their evaluation found that first-time users could accurately trace errors through unfamiliar specifications.

*Source: MIT Visualization Group (+1 more)*

For a VPL, these ideas suggest that the editor should not merely highlight the node where an exception occurred. It should also let the user travel backward through the relevant data and execution dependencies.

## 5. Error visualization as a user-experience problem

A technically accurate error message can still be a poor user experience. The interface must help users find relevant evidence, understand the problem, and decide what to do next.

One particularly useful finding comes from Kuttal and colleagues' 2019 study of 16 end-user programmers: participants spent 73% of their debugging time searching for relevant information. The study investigated particular web-based visual programming tasks, so the number should not be generalized to every VPL. Nevertheless, it highlights a key design opportunity: reduce the effort required to locate and connect diagnostic information.

*Source: epiclab.github.io*

### Core UX principles

| Principle | Design implication |
| --- | --- |
| Locality | Display the error where the user can act on it. |
| Clarity | Explain the consequence in familiar language before presenting internal terminology. |
| Specificity | Identify the exact node, pin, wire, value, or execution step involved. |
| Actionability | Offer plausible next steps, not just descriptions of failure. |
| Context preservation | Let users inspect errors without losing their place in the graph. |
| Progressive disclosure | Keep the initial explanation concise; expose technical detail on demand. |
| Consistency | Use stable meanings for severity, colors, icons, and diagnostic categories. |
| Accessibility | Provide text labels, keyboard navigation, non-color cues, and screen-reader support. |
| Trustworthiness | Distinguish confirmed causes from suspected causes and speculative fixes. |

A useful principle is to minimize the distance between detecting a problem, understanding it, and correcting it. That distance is cognitive as well as spatial.

### Avoid overwhelming users

Large graphs can produce hundreds of cascading diagnostics from a single underlying mistake. Displaying all of them at once may make debugging harder rather than easier.

A better strategy is to:

- Group related diagnostics.
- Identify likely root causes and their downstream consequences.
- Prioritize errors that prevent execution.
- Keep warnings separate from fatal errors.
- Let users filter, dismiss, or inspect diagnostic categories.
- Update the display as errors are resolved.

Importantly, grouping should not conceal independent problems. A system should explain why diagnostics were grouped and allow the user to inspect the underlying errors.

## 6. Runtime errors: finding the broken wire

Syntax errors and type errors are comparatively straightforward because the compiler often has enough information to identify the problematic construct. Runtime failures are more challenging.

Consider a graph that processes a sequence of records:

*Figure: a failing data pipeline*

- **Load records** — Produces a list of records
- **Extract price** — Produces a number for each record
- **Divide by quantity** — Fails when quantity is zero
   - **Record 18:** price = 50, quantity = 0
   - **Operation:** 50 ÷ 0

In this case, the error originates at the division operation, but the underlying data problem may be an invalid quantity in a particular record.

A strong visual debugger should support several levels of investigation:

1. **Local failure:** Identify the division node and its failing input.
2. **Value inspection:** Show that the denominator is zero.
3. **Data provenance:** Trace the value back to the record and the node that supplied it.
4. **Control-flow context:** Show which branch or iteration led to the failure.
5. **Resolution:** Allow the user to validate the quantity, handle zero explicitly, or define an appropriate fallback.

### Execution history and replay

For data-flow and reactive systems, the editor can record a bounded execution history containing node evaluations, input/output values, branch decisions, and timestamps or sequence numbers.

The user can then step backward through the graph's execution to identify the first unexpected value.

This resembles the timeline and dependency-inspection techniques developed in [Visual Debugging Techniques for Reactive Data Visualization](https://vis.csail.mit.edu/pubs/vega-debugging/).

*Source: MIT Visualization Group*

The challenge is deciding what to record. Full execution traces can be expensive in memory and processing time, especially for large graphs, loops, or real-time systems. Practical options include bounded trace buffers, selective recording, sampling, and re-execution when deterministic replay is possible.

## 7. AI-assisted error explanation and repair

An AI-assisted VPL could go beyond conventional diagnostics by translating technical failures into explanations tailored to the user's apparent goal.

For example, a compiler might report:

> `TypeMismatch: expected Float, received String at input[0]`

An AI-assisted interface could explain:

> This operation needs a number, but the connected node provides text. If that text contains a numeric value, convert it before continuing. If you intend to combine words and numbers, use a text operation instead.

The AI can then suggest a graph edit, such as inserting a conversion node or replacing the operation.

However, this feature needs strict boundaries.

Recommended architecture:

- The compiler or runtime provides authoritative facts about the failure.
- The graph model provides node identities, types, connections, and constraints.
- The AI generates a contextual explanation and proposes a repair.
- A validator checks the proposed graph edit against language rules.
- The user previews or approves the change.
- The system reruns validation and reports whether the problem was resolved.

AI should not invent missing runtime values, claim that a suspected cause is proven, or silently alter the graph based on a speculative diagnosis.

A repair should be presented as a hypothesis when the evidence is incomplete. For example, inserting a string-to-number conversion might resolve a type error but still fail if the text contains nonnumeric characters.

### Repair confidence and evidence

A useful design distinguishes three cases:

- **Deterministic correction:** A required field is missing and the language specifies an unambiguous default or correction.
- **Validated suggestion:** A proposed edit satisfies static constraints but its runtime behavior is not yet verified.
- **Exploratory hypothesis:** Several changes might address the observed behavior, and the user needs to choose based on intent.

This distinction helps preserve user control and makes the AI's limitations visible.

## 8. Related research and systems

These sources provide a useful starting point for a deeper literature review.

- **Visual Debugging Techniques for Reactive Data Visualization (2016)** — *Hoffswell, Satyanarayan, and Heer · EuroVis.* Investigates timelines, data-change histories, dependency relationships, and contextual annotations for understanding interactive behavior. [Paper and research materials](https://vis.csail.mit.edu/pubs/vega-debugging/)
- **Augmenting Code with In Situ Visualizations to Aid Program Understanding (2018)** — *Hoffswell, Satyanarayan, and Heer · CHI.* Studies how embedding runtime information directly into a representation helps users understand program behavior. Its findings are relevant to showing values and state directly on graph nodes. [Paper and research materials](https://vis.mit.edu/pubs/insitu-vis-debugging/)
- **How End-User Programmers Debug Visual Web-Based Programs: An Information Foraging Theory Perspective (2019)** — *Kuttal and colleagues · Journal of Computer Languages.* Examines how end-user programmers locate and interpret debugging information, including the value of to-fix lists, informative cues, and hints. [Read the paper](https://doi.org/10.1016/j.cola.2019.04.003)
- **Interactive, Visual Fault Localization Support for End-User Programmers (2005)** — *Journal of Visual Languages and Computing.* Early work on interactive visual fault localization and human-centered debugging. Particularly relevant to the question of how users interpret and act on highlighted faults. [Read the paper](https://doi.org/10.1016/j.jvlc.2004.07.001)
- **Debugging as Evidence-Driven Reasoning: Visualization Opportunities in Data-Intensive Programming (2026)** — *Chen, Zhu, and Faust.* A recent research direction focused on aligning evidence across artifacts, comparing expected and observed states, and tracing state changes through workflows. [Read the preprint](https://arxiv.org/abs/2606.30884)

These papers address different aspects of debugging rather than providing a single, complete error-visualization architecture. Together, they offer a useful foundation for studying fault localization, runtime observability, information-seeking behavior, and evidence-based diagnosis.

## 9. Open research questions

The most interesting research opportunities lie in the intersection of visual representation, compiler architecture, debugging cognition, and AI assistance.

| Research question | What to investigate |
| --- | --- |
| How precise should highlighting be? | Whether highlighting a pin, wire, node, or larger region best supports different error categories. |
| How should root causes be distinguished from symptoms? | How to group cascading errors without hiding independent failures. |
| How should errors survive graph edits? | Stable diagnostic identity and mapping across text/graph synchronization and incremental compilation. |
| How should runtime state be represented? | Whether values, traces, timelines, or provenance views best help users find the first unexpected state. |
| How much explanation is enough? | Whether layered messages outperform a single detailed diagnostic for novice and expert users. |
| When should AI suggest a repair? | How to balance helpful automation with user control, correctness, and confidence calibration. |
| How can logical errors be detected? | How assertions, examples, tests, invariants, and expected outputs can support failures that do not trigger exceptions. |
| How should uncertainty be communicated? | How to distinguish a proven type mismatch from a likely but unconfirmed behavioral cause. |

### Evaluating an error-visualization system

A research prototype should be evaluated on more than whether users like its interface.

Useful outcome measures include:

- **Localization accuracy:** Do users identify the correct node, wire, or upstream source?
- **Time to diagnosis:** How long does it take to explain the underlying cause?
- **Time to repair:** How quickly can users make a correct change?
- **Repair correctness:** Does the resulting graph behave as intended?
- **Mental-model accuracy:** Can users explain why the failure occurred?
- **Cognitive load:** How much effort do users report or demonstrate while debugging?
- **Error recurrence:** Do users learn to avoid the same class of mistake?
- **Trust calibration:** Can users distinguish reliable diagnostic facts from speculative suggestions?

A controlled study could compare three conditions: ordinary textual diagnostics, graph highlighting with concise explanations, and graph highlighting with explanations plus interactive data-flow tracing. This would help isolate which features provide the greatest benefit.

## 10. Suggested design direction

For a graph editor with a synchronized textual representation, the recommended approach is to prioritize the following architecture:

1. **Structured diagnostic model** — Every diagnostic has a stable ID, category, severity, explanation key, primary graph location, related locations, and optional runtime evidence.
2. **Bidirectional location mapping** — Maintain mappings between graph IDs, textual source spans, and generated instructions. Update them incrementally as the graph changes.
3. **Coordinated diagnostics UI** — Synchronize graph highlights, an error list, contextual explanations, and optional runtime-value inspection.
4. **Validated correction workflow** — Allow a user to preview a proposed fix, validate it, apply it, and confirm that the diagnostic disappears or changes appropriately.

Start with deterministic syntax and type diagnostics. They provide a tractable way to validate the source-mapping infrastructure and the core interaction design. Then add runtime tracing and provenance, followed by AI-generated explanations and repair proposals.

The key research insight: error visualization is not merely about making errors visible. It is about connecting a failure to its cause, presenting enough evidence to understand it, and making the path to a correct repair clear. The strongest VPL debugger will make those relationships explicit without overwhelming users or pretending to know more than the available evidence supports.

Potential next step: narrow the research toward compiler/source-map architecture, novice-facing UX, runtime data-flow tracing, or AI-assisted diagnosis and repair.

The most tractable starting point is compiler and source-map diagnostics, followed by runtime data-flow tracing and AI-assisted repair, with each explanation tied to verifiable evidence.
