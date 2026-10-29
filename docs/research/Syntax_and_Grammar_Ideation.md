---
title: "Syntax and Grammar Ideation"
document_type: "Research note"
formatted: 2026-10-28
---

# Syntax and Grammar Ideation

Syntax and Grammar Ideation is the process of inventing, evaluating, and refining the textual notation used to express the nodes, edges, connections, and other structural elements of a text-based visual programming language.

The central question is: What should the programmer actually type to describe a visual graph, and how should that text map unambiguously to the graph's structure?

For example, imagine a visual programming language in which nodes represent operations and edges represent connections between them. The language might use syntax such as:

```text
node add: Add
node result: Output

add.out -> result.in
```

Or it might use a more compact notation:

```text
add = Add()
result = Output(add.out)
```

Both examples can describe a similar graph, but they express different design philosophies. The first makes nodes and connections explicit. The second borrows familiar conventions from programming languages, where values flow through expressions and function calls.

The goal of syntax and grammar ideation is not simply to invent attractive keywords. It is to discover a notation that is expressive, unambiguous, readable, editable, parseable, and well suited to both human programmers and automated tools such as LLMs.

## Contents

- [1. The design space](#1-the-design-space)
- [2. The fundamental distinction: concrete syntax versus graph structure](#2-the-fundamental-distinction-concrete-syntax-versus-graph-structure)
- [3. Node syntax ideation](#3-node-syntax-ideation)
- [4. Edge syntax ideation](#4-edge-syntax-ideation)
- [5. Keyword ideation: what words should the language use?](#5-keyword-ideation-what-words-should-the-language-use)
- [6. Grammar ideation: defining what is legal](#6-grammar-ideation-defining-what-is-legal)
- [7. Syntax decisions that deserve deliberate experimentation](#7-syntax-decisions-that-deserve-deliberate-experimentation)
- [8. AI-friendly syntax and grammar](#8-ai-friendly-syntax-and-grammar)
- [9. Bidirectional text-and-graph editing](#9-bidirectional-text-and-graph-editing)
- [10. A practical syntax ideation workflow](#10-a-practical-syntax-ideation-workflow)
- [11. Suggested research artifacts](#11-suggested-research-artifacts)
- [12. Open research questions](#12-open-research-questions)
- [Recommended direction](#recommended-direction)

## 1. The design space

Syntax and grammar ideation involves several interdependent decisions.

**Node declaration syntax**

How do users introduce a node, assign it an identity, and specify its type or operation?

**Examples:** `node sum: Add`, `sum = Add()`, `Add sum`

**Edge declaration syntax**

How do users express directed connections between nodes, including the particular output and input ports involved?

**Examples:** `a.out -> b.in`, `connect a.out to b.in`, `b.in = a.out`

**Structural grammar**

How are statements, blocks, scopes, nested graphs, comments, and multiline constructs organized?

**Semantic conventions**

What do declarations and operators mean? How are identities, types, execution order, data flow, and missing connections interpreted?

**Notation experimentation**

How do alternative keywords, punctuation, abbreviations, and layouts compare in realistic examples?

These decisions should be explored together. For example, choosing `->` for edges affects not only the appearance of a connection but also how directionality, chaining, operator precedence, and graph serialization are defined.

## 2. The fundamental distinction: concrete syntax versus graph structure

One of the most important decisions is to separate the way a graph is written from the graph that the text represents.

Research on visual-language design distinguishes concrete syntax, the notation users see, from abstract syntax, the underlying computer-interpretable structure. This distinction is useful because one graph can have multiple textual representations and multiple graphical presentations.

*Source: ScienceDirect (+1 more)*

Consider the following three notations.

**Style A · Explicit declarations**

```text
node x: Number
node y: Number
node sum: Add

x.out -> sum.a
y.out -> sum.b
```

Makes node identities, types, and connections explicit. Verbose but easy to extend.

**Style B · Expression-oriented**

```text
sum = Add(x, y)
```

Compact and familiar to programmers. The connections are implicit in argument positions.

**Style C · Graph-oriented**

```text
x -> sum.a
y -> sum.b

sum: Add
```

Emphasizes the connections, with node declarations kept separate.

All three could produce a graph with two inputs connected to an addition node. However, they differ in how they handle node identity, declaration order, implicit creation, and ports.

For a visual programming language with bidirectional text-and-graph editing, this separation is particularly important. The graphical editor should be able to rearrange nodes without changing the program's meaning, while a text edit should update the corresponding graph without accidentally creating or deleting unrelated objects.

A useful principle is:

> Design the abstract graph model first, then explore concrete notations that can represent it faithfully.

The notation should not accidentally dictate the underlying graph model.

## 3. Node syntax ideation

A node declaration typically needs to express some combination of:

- **Identity:** How other statements refer to the node.
- **Kind:** What operation, component, or node type it represents.
- **Configuration:** Its initial values, properties, or parameters.
- **Ports:** Its available inputs and outputs, if they are not inferred from the kind.
- **Metadata:** Optional labels, comments, visual hints, or editor-specific information.

The main challenge is deciding which of these must be explicit.

### Candidate node notations

**Keyword-first**

```text
node total: Add
```

A dedicated keyword clearly announces a declaration. This is easy to parse and gives future syntax room to grow.

Explicit

**Assignment-first**

```text
total = Add()
```

Familiar from many programming languages. The assignment binds a name to a node instance, although the semantics of `=` must be carefully defined.

Familiar

**Type-first**

```text
Add total
```

Concise and readable, but potentially ambiguous if type names, identifiers, and expressions can appear in similar positions.

Compact

**Call-based**

```javascript
let total = Add(left, right)
```

Can combine declaration, identity, and wiring in one expression. Best suited when nodes behave like function calls and inputs have well-defined argument positions.

Compositional

### Questions to resolve

Are node kinds and node identities different things?

Suppose two addition nodes appear in a graph:

```text
node sumA: Add
node sumB: Add
```

`Add` is the kind; `sumA` and `sumB` are distinct identities. The syntax should make this distinction obvious enough that a user or language model does not confuse a node type with a node instance.

Are declarations separate from connections?

Separating them permits connections to be written before or after declarations, and makes it easier to reorder text without changing the graph. Combining them can reduce verbosity but complicates editing and forward references.

Are anonymous nodes allowed?

For example:

```text
result = Add(input, Multiply(a, b))
```

This looks natural in an expression language, but a visual editor may need stable identities for the nested `Add` and `Multiply` nodes. Anonymous nodes therefore require an explicit identity strategy, even if their identities remain hidden from the user.

The initial recommendation is to explore named node declarations as the canonical representation, while allowing compact expressions as optional syntactic sugar if the graph model supports them cleanly.

## 4. Edge syntax ideation

Edges deserve as much attention as nodes. In a visual programming language, a connection is not necessarily just a relationship between two objects. It might connect a specific output port to a specific input port and carry data, execution flow, events, dependencies, or some other relationship.

A basic directed edge might look like:

```text
source.out -> target.in
```

This makes the direction and endpoints visible. But there are several competing approaches.

| Style | Example | Main trade-off |
| --- | --- | --- |
| Arrow | `a.out -> b.in` | Compact, directional, visually intuitive |
| Keyword | `connect a.out to b.in` | Readable, explicit, but verbose |
| Assignment | `b.in = a.out` | Familiar data-flow notation, but may blur connection and value assignment |
| Nested input | `b = Operation(input: a.out)` | Convenient for expressions; less natural for arbitrary graphs |
| Relationship declaration | `edge e: a.out -> b.in` | Supports explicit edge identity and metadata |

### Important edge-design decisions

1. Directionality

Does `a -> b` mean data travels from `a` to `b`, execution passes from `a` to `b`, or merely that a relationship exists?

If a language supports multiple edge types, the notation must distinguish them or provide a well-defined context.

2. Port addressing

Should users write:

```text
a.out -> b.in
```

or:

```text
a:out -> b:in
```

or simply:

```text
a -> b
```

The shortest form works when each node has only one relevant port. Explicit port addressing becomes essential when nodes have multiple inputs or outputs.

3. Edge identity

Can multiple edges connect the same pair of nodes? Can they have labels, conditions, weights, or other properties?

If so, an edge may need its own identity:

```text
edge success: check.yes -> finish.in
edge failure: check.no -> retry.in
```

4. Connection cardinality

Can an input accept multiple connections? Can one output feed multiple inputs? Does the language allow incomplete connections while the graph is being edited?

These are semantic decisions, but they affect the grammar and the error-recovery behavior.

5. Chaining and fan-out

A compact grammar might allow:

```text
a -> b -> c
```

and:

```text
a -> b, c
```

The latter could mean that `a` connects to both `b` and `c`. Such shorthand reduces typing but introduces more rules that parsers, editors, and AI-generated code must handle consistently.

For an initial grammar, the recommended approach is to prefer one unambiguous edge declaration per connection. Chaining and fan-out can be introduced later if they provide enough practical value.

## 5. Keyword ideation: what words should the language use?

Keywords establish the vocabulary and personality of a language. They also influence its length, readability, ambiguity, and ease of generation by AI systems.

For a graph-oriented language, the vocabulary can be divided into several categories.

| Category | Possible keywords or symbols | Purpose |
| --- | --- | --- |
| Declaration | `node`, `edge`, `graph` | Introduce structural elements |
| Connection | `->`, `connect`, `to` | Express relationships |
| Identity | `id`, `as`, `name` | Assign or reference identities |
| Configuration | `with`, `set`, `using` | Specify node or edge properties |
| Structure | `group`, `graph`, `scope` | Organize subgraphs |
| Data flow | `input`, `output`, `in`, `out` | Address ports |
| Control flow | `branch`, `case`, `then`, `else` | Express execution decisions |
| Metadata | `label`, `comment`, `layout` | Describe or annotate the graph |

These are candidates rather than a recommendation to use every keyword. A small language vocabulary is easier to learn and document, but excessive compactness can make the grammar harder to understand.

### Three competing vocabulary philosophies

### A. Explicit and descriptive

```text
node total: Add
connect left.out to total.a
connect right.out to total.b
```

**Strengths:** Easy to read, easy to explain, and explicit about the role of each statement.

**Weaknesses:** Verbose, repetitive, and slower to write.

### B. Symbolic and compact

```text
total = Add()
left.out -> total.a
right.out -> total.b
```

**Strengths:** Short, visually scannable, and suitable for frequent editing.

**Weaknesses:** Symbols such as `=` can acquire multiple meanings unless carefully constrained.

### C. Hybrid

```text
node total: Add
left.out -> total.a
right.out -> total.b
```

**Strengths:** Uses explicit declarations where they add clarity and compact operators where they add convenience.

**Weaknesses:** Requires careful consistency about where keywords are mandatory and where shorthand is allowed.

The starting preference is the hybrid approach. It gives the language a small, predictable structural vocabulary without forcing every relationship to be expressed as a long English-like sentence.

The choice should be tested against actual programs, not just isolated syntax fragments. A keyword that looks elegant in a one-line example may become irritating when repeated hundreds of times.

## 6. Grammar ideation: defining what is legal

Keywords establish the vocabulary; the grammar defines how that vocabulary may be combined.

A grammar must answer questions such as:

- Can an edge refer to a node declared later?
- Can a node be declared more than once?
- Are semicolons required?
- Can statements span multiple lines?
- Are properties positional or named?
- Can graph declarations be nested?
- How are quoted identifiers and strings handled?
- Can incomplete statements be represented while editing?

A useful starting point is a deliberately small grammar.

### A possible grammar for a graph DSL

Here is an illustrative EBNF-style specification:

```text
program = { statement };

statement = node_decl
 | edge_decl
 | comment;

node_decl = "node", identifier, ":", node_kind,
 [ properties ], terminator;

edge_decl = endpoint, "->", endpoint,
 [ properties ], terminator;

endpoint = identifier, ".", identifier;

properties = "{", [ property, { ",", property } ], "}";

property = identifier, "=", value;

terminator = newline | ";";

comment = "//", text, newline;
```

This is a starting sketch, not a complete implementable grammar. In a real specification, the definitions of `identifier`, `node_kind`, `value`, `newline`, and `text` would need to be made precise, along with whitespace, escaping, and lexical precedence.

A corresponding example is:

```text
node source: Number
node double: Multiply { factor = 2 }
node result: Output

source.out -> double.value
double.out -> result.in
```

The grammar distinguishes declarations from connections. It also gives connections a consistent shape: a source endpoint, an arrow, and a destination endpoint.

There are two important layers of validation:

1. **Syntactic validation:** Does the text match the grammar?
2. **Semantic validation:** Do the referenced nodes and ports exist, and are the connections valid?

For example:

```text
source.out -> result.missing
```

could be syntactically valid but semantically invalid if `result` has no `missing` port.

This separation prevents the grammar from becoming entangled with every detail of type checking and graph validation. Formal specifications of visual languages likewise emphasize the value of defining structure and meaning precisely.

*Source: ScienceDirect (+1 more)*

## 7. Syntax decisions that deserve deliberate experimentation

Beyond basic node and edge declarations, several decisions can have a disproportionate effect on the language's usability.

### Identifiers and naming

Compare:

```text
node calculateTotal: Add
```

with:

```text
node calculate_total: Add
```

and:

```text
node "Calculate Total": Add
```

The language should define whether identifiers are case-sensitive, whether they can contain spaces, how reserved keywords are escaped, and whether display labels are separate from stable identities.

For bidirectional editing, the recommendation is to distinguish a node's stable identity from its display label. Renaming the label in the visual editor should not necessarily change references elsewhere in the text.

### Properties and parameters

Compare:

```text
node threshold: Constant(0.75)
```

with:

```text
node threshold: Constant { value = 0.75 }
```

Positional arguments are concise, but their meaning can depend on parameter order. Named properties are more verbose but make generated code easier to inspect and less sensitive to changes in a node's parameter list.

A useful design is to allow positional syntax only when the meaning is obvious and stable, while using named properties for optional or less frequently used parameters.

### Optional syntax and shorthand

Shorthand can make graphs dramatically easier to write:

```text
a.out -> b.in
b.out -> c.in
```

might become:

```text
a -> b -> c
```

However, the compact form assumes that each node has an unambiguous default output and input. That assumption fails for nodes with multiple ports, control-flow branches, or typed connections.

A good rule is to make shorthand an optional convenience whose expansion into the canonical syntax is deterministic.

### Comments and formatting

A graph language should support comments that survive round-tripping between the text and visual editor.

```text
// Normalize the incoming value before comparison.
node normalize: Normalize

// Only values that pass validation reach the output.
normalize.out -> output.in
```

Formatting should ideally be independent of graph semantics. Indentation, blank lines, and declaration ordering should not change the graph unless the language explicitly defines them as meaningful.

Graph-description languages such as Graphviz DOT offer useful precedents for declarations, attributes, ports, and subgraphs. They can serve as a reference point without dictating the syntax of a programming-oriented graph DSL.

*Source: Graphviz (+1 more)*

## 8. AI-friendly syntax and grammar

If the language is intended to be written by LLMs as well as humans, syntax ideation needs an additional dimension: how reliably can a model generate, modify, and repair valid graph programs?

A notation that is pleasant for a human expert is not necessarily the notation that produces the fewest errors in AI-generated output.

Research and existing tools offer useful starting points. For example, yUML publishes an AI-oriented DSL reference intended for use in model prompts, while keeping its formal grammars as the authoritative definition of valid syntax.

*Source: yuml (+1 more)*

### Design principles for AI-generated syntax

**Prefer predictable statement shapes**

If all node declarations follow `node ID: KIND`, a model can reuse a single pattern rather than infer a different syntax for every node type.

**Minimize context-dependent punctuation**

Avoid making the same symbol mean declaration, assignment, connection, and configuration in indistinguishable contexts.

**Make endpoints explicit**

A consistent `node.port -> node.port` convention reduces ambiguity about where an edge begins and ends.

**Use canonical output**

Allow convenient input shorthand if useful, but have the formatter emit one standard representation. This reduces variation in generated output and makes diffs easier to review.

**Make errors local and recoverable**

Missing identifiers, invalid ports, and malformed properties should produce precise diagnostics and, where possible, preserve the rest of the graph.

### A crucial experiment: measure syntax reliability

Do not assume that fewer tokens automatically mean better AI performance. Compare candidate syntaxes using a fixed collection of graph-generation and editing tasks.

Measure:

- Parse success rate.
- Semantic validity rate after parsing.
- Number of nodes and edges incorrectly omitted or added.
- Accuracy of references to ports and node identities.
- Token consumption.
- Number of repair attempts needed.
- Correctness of localized edits to existing graphs.

For example, give the same model a task to construct a conditional branch, a loop, a multi-input node, and a graph with cycles in each candidate syntax. Then compare the results using the same parser and validator.

The winning syntax should be the one that performs well across realistic tasks, not merely the one that produces the shortest example.

## 9. Bidirectional text-and-graph editing

For a language with a synchronized visual editor, syntax design must account for the fact that users can edit the program in two representations.

A user might create a node by dragging it onto the canvas. The editor then generates a textual declaration. Alternatively, the user might type a declaration, causing the editor to create a node.

This introduces a set of requirements beyond ordinary parsing.

### Stable graph identity

Consider:

```text
node calculate: Add
node output: Output

calculate.out -> output.in
```

If the user renames `calculate` to `sum`, the editor must update the corresponding references without confusing the renamed node with a newly created node.

If identity is derived only from a mutable label, renaming can break references or create accidental duplicates. A stable internal identifier, with a separate human-readable name where needed, can help.

### Incremental parsing

While typing, the source may temporarily contain incomplete syntax:

```text
node calculate:
```

A conventional compiler might reject the whole program. A live graph editor should instead preserve the last valid graph where possible, display an error for the incomplete declaration, and continue processing unrelated statements.

The grammar should therefore be designed with editor recovery in mind, even if the final language specification only permits complete statements.

### Round-trip stability

A useful test is:

1. Parse text into a graph.
2. Render the graph in the visual editor.
3. Serialize the graph back to text.
4. Parse the serialized text again.
5. Compare the resulting graph structures.

The final graph should be structurally equivalent to the original. Comments, meaningful labels, stable identifiers, and other user-authored information should also survive wherever possible.

One subtle issue is that structural equivalence is not textual equality. A formatter might reorder declarations or normalize whitespace without changing the graph. The language must decide which textual details are preserved and which are canonicalized.

This is another reason to distinguish the graph's abstract structure from its textual representation.

*Source: web.engr.oregonstate.edu (+1 more)*

## 10. A practical syntax ideation workflow

The recommended approach is to treat the design as a series of small, testable experiments rather than attempting to invent the entire language at once.

1. **Define the graph model** — List the node types, ports, edge types, properties, scopes, and identity requirements the language must represent.
2. **Create a syntax corpus** — Write representative examples covering simple data flow, control flow, multiple inputs, nested graphs, cycles, configuration, and invalid or incomplete programs.
3. **Generate competing notations** — Express the same corpus using explicit keywords, compact symbols, assignment-oriented notation, and hybrid alternatives.
4. **Implement a minimal parser** — Parse each candidate into the same graph representation. Test ambiguity, error recovery, semantic validation, and round-tripping.
5. **Evaluate usability and reliability** — Test with human readers and AI-generated programs. Measure readability, editing effort, token usage, and error rates.
6. **Freeze the core grammar** — Document the canonical syntax, semantics, reserved words, diagnostics, and formatting rules. Add shorthand only when it has a clear benefit.

## 11. Suggested research artifacts

To make Syntax and Grammar Ideation a concrete research topic, the recommended approach is to produce the following artifacts:

| Artifact | What it establishes |
| --- | --- |
| Syntax candidate catalog | Alternative node, edge, property, and scope notations |
| Grammar comparison matrix | Readability, ambiguity, verbosity, extensibility, and parser complexity |
| Example corpus | Representative valid, invalid, and incomplete graph programs |
| Formal grammar | A precise definition of legal textual structures |
| Semantic constraints | Rules that require knowledge of the graph, such as port compatibility |
| Canonical formatting rules | How graphs are serialized into stable, predictable text |
| AI evaluation suite | Benchmarks for generation, modification, repair, and token efficiency |
| Bidirectional editing tests | Whether graph-to-text and text-to-graph transformations preserve meaning |

These artifacts also provide a basis for comparing future language revisions without relying entirely on subjective judgments.

## 12. Open research questions

The most interesting questions are not necessarily which particular keyword to choose, but which broader design principles produce the best language.

- **Declaration versus inference:** Should every node and edge be explicitly declared, or should the parser infer structure from expressions?
- **Textual order versus graph topology:** Should statement order matter, or should a graph's connections determine its structure independently of declaration order?
- **Explicitness versus brevity:** How much shorthand can be introduced before the notation becomes harder to understand or generate correctly?
- **Stable identity versus readable names:** How can nodes be renamed, moved, and regenerated without breaking references?
- **Canonical syntax versus flexible input:** Should the parser accept several equivalent notations while the serializer emits only one?
- **Grammar versus semantic validation:** Which constraints belong in the formal grammar, and which should be checked against the graph model?
- **Human-oriented versus AI-oriented syntax:** Can a single notation serve both audiences, or would optional sugar and canonical output offer a better compromise?
- **Syntax evolution:** How can new node types and language features be added without breaking old programs or existing editor integrations?

These questions connect syntax design to compiler construction, graph theory, programming-language usability, AI-assisted coding, and the engineering of synchronized editing environments.

## Recommended direction

For a first prototype, research should investigate a declaration-oriented hybrid DSL with explicit node declarations, a compact directed-edge operator, explicit port addressing, named properties, stable node identities, and canonical serialization.

For example:

```mermaid
graph Example {
 node input: Number
 node scale: Multiply {
 factor = 2
 }
 node output: Output

 input.out -> scale.value
 scale.out -> output.in
}
```

This is a candidate notation, not a finalized specification. Its value is that it provides a clear baseline from which to test more compact alternatives.

The guiding principle is to keep three things separate: what the text says, what graph the text represents, and how that graph is displayed. If those layers remain cleanly defined, it becomes much easier to experiment with keywords and punctuation without destabilizing the language's underlying design.
