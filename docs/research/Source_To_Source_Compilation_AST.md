---
title: "Source-to-Source Compilation with ASTs"
document_type: "Research note"
formatted: 2026-10-28
---

# Source-to-Source Compilation with ASTs

Source-to-source compilation (also called transpilation) is the process of translating one programming language into another while preserving the original program's intended behavior. An Abstract Syntax Tree (AST) is a structured representation of a program that allows a compiler to analyze, transform, optimize, and generate code without relying on fragile text substitutions.

For the text-based visual programming language, this is especially important: if the same program can be edited as text or as a visual graph, you want a compiler that turns the language's semantic representation into clean, portable JavaScript for browser-based applications, including a WYSIWYG HTML editor.

The key architectural idea is:

The language's intermediate representation (IR) should define program meaning; the JavaScript AST should define how that meaning is expressed in JavaScript.

This separation lets you change the syntax of the language, the visual editor, or the JavaScript output strategy without rebuilding the entire compiler.

## Contents

- [1. The compilation pipeline](#1-the-compilation-pipeline)
- [2. What an AST contributes](#2-what-an-ast-contributes)
- [3. Mapping the IR to JavaScript](#3-mapping-the-ir-to-javascript)
- [4. AST transformation techniques](#4-ast-transformation-techniques)
- [5. JavaScript AST libraries and tooling](#5-javascript-ast-libraries-and-tooling)
- [6. A practical implementation with Babel](#6-a-practical-implementation-with-babel)
- [7. The difficult part: preserving semantics](#7-the-difficult-part-preserving-semantics)
- [8. Optimization: where it belongs](#8-optimization-where-it-belongs)
- [9. Source maps and visual debugging](#9-source-maps-and-visual-debugging)
- [10. Live compilation and incremental updates](#10-live-compilation-and-incremental-updates)
- [11. Testing the compiler](#11-testing-the-compiler)
- [12. Recommended architecture for the project](#12-recommended-architecture-for-the-project)
- [13. Further research](#13-further-research)
- [Suggested expansion of the research note](#suggested-expansion-of-the-research-note)

## 1. The compilation pipeline

*Figure: compilation pipeline*

1. **Source language** — Text files, visual nodes, connections, properties
2. **Parse and normalize** — Syntax tree → canonical language IR
3. **Semantic analysis and IR passes** — Name resolution, types, control flow, validation, optimization
4. **JavaScript AST generation** — Map IR constructs to valid ECMAScript nodes
5. **Generate and validate** — Format, emit source maps, parse-check, test
6. **JavaScript output** — Portable code for the browser and supported runtimes

Each stage has a distinct responsibility:

- **Parsing:** determines what the source says syntactically.
- **Normalization:** converts different source representations into one canonical IR.
- **Semantic analysis:** resolves variables, checks types and verifies that operations make sense.
- **IR transformations:** perform language-level rewrites and optimizations.
- **AST generation:** maps each IR construct to one or more JavaScript AST nodes.
- **Code generation:** serializes the AST into readable JavaScript.
- **Validation:** checks generated syntax, behavior and compatibility with the chosen runtime targets.

A visual graph should not need to generate JavaScript independently from the text compiler. Both should converge on the same semantic IR, so the generated output is consistent regardless of how the program was authored.

## 2. What an AST contributes

An AST represents the structure of a program rather than its textual appearance.

Consider this source program:

```text
total = price * quantity + tax
```

A simplified expression AST is:

```text
Assignment
├── Identifier("total")
└── Add
 ├── Multiply
 │ ├── Identifier("price")
 │ └── Identifier("quantity")
 └── Identifier("tax")
```

The tree preserves operator precedence and makes it possible to transform the program safely.

For example, a compiler can:

- Replace a constant expression such as `2 * 3` with `6`.
- Rename variables without accidentally modifying strings or comments.
- Introduce temporary variables when a target language requires them.
- Turn a graph-oriented control-flow construct into a JavaScript `if` statement or function.
- Rewrite an abstract UI operation into calls to browser APIs.
- Preserve source locations so debugging can point back to the original language.

Text replacement cannot reliably perform these tasks because identical text can mean different things in different syntactic contexts.

### The three representations to distinguish

| Representation | Main purpose |
| --- | --- |
| Source AST | Captures the source language's syntax |
| Semantic IR | Captures the meaning and operations of the program |
| JavaScript AST | Captures a legal target-language program |

These structures may overlap, but they should not be conflated. In particular, the source language's nodes should not simply be renamed to JavaScript nodes if their semantics differ.

## 3. Mapping the IR to JavaScript

The most important design question is how much of the language should map directly to JavaScript and how much needs to be lowered into helper functions or runtime abstractions.

Suppose the visual language has a node called `SetText`, which sets the text content of an HTML element. Its IR might be:

```json
{
  "op": "SetText",
  "target": {
    "op": "Variable",
    "name": "element"
  },
  "value": {
    "op": "StringLiteral",
    "value": "Hello, world!"
  }
}
```

A JavaScript backend could translate this into:

```text
element.textContent = "Hello, world!";
```

But a more abstract UI operation might need to become:

```text
runtime.setText(element, "Hello, world!");
```

Both are valid compilation strategies. The first generates idiomatic JavaScript directly; the second centralizes behavior and makes the generated program less dependent on browser-specific implementation details.

For a visual programming language, the design should divide operations into three categories:

| IR operation | Compilation strategy |
| --- | --- |
| Arithmetic, comparisons, basic variables | Direct JavaScript expressions |
| Control flow, functions, local scopes | JavaScript statements and declarations |
| UI nodes, signals, graph execution, special data types | Runtime helpers or explicit lowering passes |

This division avoids turning the backend into a large collection of special cases. It also lets you replace the browser runtime later without redesigning the source language.

### Example: compiling a graph to JavaScript

Imagine a visual graph that checks a score and displays a message.

- **Input:** `score`
- **Condition:** `score >= 10`
   - **True:** show `"Passed"`
   - **False:** show `"Try again"`

A normalized IR could represent the same program as:

```text
If(
 GreaterThanOrEqual(Variable("score"), Number(10)),
 Call("showMessage", ["Passed"]),
 Call("showMessage", ["Try again"])
)
```

The JavaScript backend emits:

```text
if (score >= 10) {
 showMessage("Passed");
} else {
 showMessage("Try again");
}
```

Notice that the backend does not need to know how the nodes were positioned on the canvas. It only needs their meaning and the control-flow relationships between them.

For complex graphs, you may first need to convert execution wires into explicit control-flow blocks. This is especially important for loops, early exits, event handlers, and graphs whose execution order is not obvious from their visual layout.

## 4. AST transformation techniques

An AST transformation takes an existing tree, creates a modified tree, or constructs a new tree from the input. In a compiler, transformations are usually organized into passes.

### Constant folding

Evaluate expressions whose results are already known.

Before:

```javascript
const width = 100 * 2;
```

After:

```javascript
const width = 200;
```

### Dead-code elimination

Remove statements that cannot affect the program's observable behavior.

Before:

```javascript
const unused = 42;
showMessage("Ready");
```

Potentially after:

```text
showMessage("Ready");
```

This is safe only if evaluating the removed declaration has no relevant side effects.

### Lowering

Translate a high-level language construct into simpler operations.

Suppose the language supports a node like:

```text
Repeat(5) {
 showMessage("Hello")
}
```

A direct JavaScript representation could be:

```javascript
for (let i = 0; i < 5; i++) {
  showMessage("Hello");
}
```

If the source language defines repeat counts, iteration variables, or execution semantics differently from JavaScript, the lowering pass must explicitly preserve those semantics.

### Variable and symbol rewriting

The compiler may need to generate names for temporary variables, runtime helpers, or graph outputs. Use symbol identities rather than raw names, and apply hygienic name generation to avoid collisions with user-defined variables.

For example, an internal temporary named `temp` could collide with a variable already declared by the user. A compiler-generated name such as `_ir_tmp_3` is safer, but it still needs collision checking or a symbol allocator.

### Control-flow transformation

Visual graphs can express execution patterns that do not map directly to structured JavaScript. You may need to:

- Convert graph branches into `if`/`else` blocks.
- Convert loops into `while` or `for` statements.
- Represent asynchronous execution using `async` functions and `await`.
- Compile event-driven nodes into callback registrations.
- Introduce state machines for complex control flow that cannot be represented naturally as nested blocks.

These transformations should happen before or during JavaScript AST generation, not through string concatenation.

## 5. JavaScript AST libraries and tooling

You generally do not need to invent your own JavaScript AST format or code printer. Established compiler libraries already provide AST construction, traversal, transformation, and code generation.

*Source: Babel*

**Strong default**

Babel offers JavaScript AST types, traversal utilities, transformations, and code generation. Its generator can emit JavaScript and source maps, making it a natural backend for a custom language compiler.

*Source: Babel*

- **Documentation: [Babel documentation](https://babel.dev/docs/) · [Generator API](https://babel.dev/docs/babel-generator)** — *TypeScript Compiler API.* Useful when you want compiler infrastructure, typed AST construction, diagnostics, and control over emitted JavaScript. Its factory and printer APIs can build output without assembling code strings manually. *(GitHub).* [Compiler API guide](https://github.com/microsoft/TypeScript/wiki/Using-the-Compiler-API)
- **SWC** A performance-oriented compiler toolkit with parsing, transformation, code generation, and source-map support. Worth evaluating if large projects or rapid recompilation become important. *(SWC).* [SWC core API](https://swc.rs/docs/usage/core)

### Recommended choice

For this use case, a suitable starting point is Babel's AST construction and generator APIs, alongside a custom IR and compiler pipeline.

Reasons:

- The system can generate JavaScript directly from the language's own IR without first expressing the source language as TypeScript.
- Babel provides established AST node definitions and traversal tools.
- It supports source-map generation, useful for mapping runtime errors back to visual nodes and original source lines.
- The system can keep the source language independent of the specific JavaScript backend.

TypeScript's compiler API is a reasonable alternative, particularly if you want to reuse TypeScript types or compiler infrastructure. SWC is worth benchmarking if generation throughput becomes a bottleneck. You should evaluate API stability and runtime packaging against the actual deployment environment before committing.

One important distinction: an AST library is not a complete compiler for the language. You still need to define the semantics of the IR and implement the translation from those semantics to the target language.

## 6. A practical implementation with Babel

Here is a small example of generating JavaScript from a custom IR using Babel's AST node builders and generator. This is not a full compiler; it demonstrates the backend boundary The system can build on.

Install the relevant packages:

```bash
npm install @babel/types @babel/generator
```

Suppose the source language has an IR operation `Add`:

```json
{
  "op": "Add",
  "left": {
    "op": "Variable",
    "name": "price"
  },
  "right": {
    "op": "Variable",
    "name": "tax"
  }
}
```

The system can recursively translate that IR into a JavaScript expression AST:

```javascript
import * as t from "@babel/types";
import generate from "@babel/generator";

function emitExpression(ir) {
  switch (ir.op) {
    case "Number":
      return t.numericLiteral(ir.value);

    case "String":
      return t.stringLiteral(ir.value);

    case "Variable":
      return t.identifier(ir.name);

    case "Add":
      return t.binaryExpression(
        "+",
        emitExpression(ir.left),
        emitExpression(ir.right)
      );

    default:
      throw new Error(`Unsupported IR operation: ${ir.op}`);
  }
}

const expression = emitExpression({
  op: "Add",
  left: { op: "Variable", name: "price" },
  right: { op: "Variable", name: "tax" }
});

const output = generate(expression, {
  comments: true,
  compact: false
}).code;

console.log(output);
```

Output:

```text
price + tax
```

The important design decision is that `emitExpression` produces structured AST nodes, not strings. Babel handles the serialization and required formatting. Its generator API is documented at [Babel generator documentation](https://babel.dev/docs/babel-generator).

*Source: Babel*

### Extend the backend by node category

A maintainable compiler should have separate emission functions for expressions and statements:

```text
emitExpression(IRExpression) -> JSExpression
emitStatement(IRStatement) -> JSStatement
emitFunction(IRFunction) -> JSFunction
emitProgram(IRProgram) -> JSProgram
```

This separation is important because JavaScript distinguishes expressions from statements. An addition is an expression; an `if` branch is a statement. Some IR operations may need to expand into multiple JavaScript statements, so a single universal function returning one AST node is not sufficient.

For more sophisticated transformations, Babel's traversal API lets you visit and modify particular AST node types. [Read the traversal documentation](https://babeljs.io/docs/babel-traverse.html).

*Source: Babel*

## 7. The difficult part: preserving semantics

Generating syntactically valid JavaScript is relatively straightforward. Generating JavaScript that behaves exactly like the source language is the harder problem.

Consider these language features:

| Source-language feature | Potential JavaScript mismatch |
| --- | --- |
| Integer arithmetic | JavaScript's ordinary `number` type uses IEEE 754 floating-point arithmetic |
| Boolean conditions | Truthiness may differ from the source language's rules |
| Equality | `==`, `===`, and source-language equality may have different behavior |
| Variable scopes | Lexical scoping and variable lifetimes may differ |
| Evaluation order | Side effects may make apparently equivalent expressions behave differently |
| Missing values | `null`, `undefined`, and a source-language `None` or `Option` may differ |
| Graph execution | Node scheduling and execution wires may not correspond directly to JavaScript statement order |
| Asynchronous operations | Events, promises, cancellation, and errors need explicit semantics |

The safest approach is to specify each IR operation's meaning independently of JavaScript. Then define how that meaning is implemented in the target runtime.

For example, if the language promises integer arithmetic with overflow checking, do not blindly emit `a + b`. You may need a checked arithmetic helper or an explicit validation step. Similarly, if a visual node means “execute these branches concurrently,” emitting a normal `if` statement would be incorrect.

### Define the runtime contract

A small runtime library can isolate source-language semantics:

```javascript
const runtime = {
  checkedAdd(a, b) {
    const result = a + b;

    if (!Number.isSafeInteger(result)) {
      throw new RangeError("Integer overflow");
    }

    return result;
  },

  setText(element, value) {
    element.textContent = String(value);
  }
};
```

The generated program can call these helpers when necessary:

```javascript
const total = runtime.checkedAdd(price, tax);
runtime.setText(outputElement, total);
```

This makes the output slightly more verbose, but it centralizes important behavior and makes semantic changes easier to implement consistently.

For browser-based visual programming, the recommended approach is to use a hybrid backend: emit ordinary JavaScript for common operations and runtime calls for operations with specialized semantics.

## 8. Optimization: where it belongs

There are two useful levels of optimization.

**IR-level optimization**

Understands the language's concepts directly. It can simplify graph structures, remove unreachable nodes, fold constants, eliminate unused values, and lower abstract control flow.

**JavaScript-level optimization**

Understands ECMAScript syntax and runtime constraints. It can simplify generated expressions, remove redundant code, and apply target-specific transformations.

Prefer IR-level optimizations when they depend on the semantics of the language. Use a mature JavaScript optimizer for target-language optimizations rather than reimplementing every JavaScript optimization yourself.

Be conservative around browser APIs, DOM mutations, callbacks, exceptions, and asynchronous operations. These can have observable side effects that invalidate seemingly obvious simplifications.

## 9. Source maps and visual debugging

This is particularly important for a text-based visual programming language.

When the browser reports an error in generated JavaScript, you want to identify the original source expression or visual node—not a line inside a generated helper function.

Standard JavaScript source maps map generated code positions back to original source positions. The format is specified by [ECMA-426](https://tc39.es/ecma426/).

However, the compiler has a further challenge: a visual graph may not have ordinary source-file locations for every node.

The recommendation is to assign stable identifiers to source-level constructs:

```json
{
  "op": "SetText",
  "nodeId": "node-42",
  "sourceSpan": {
    "file": "program",
    "start": 120,
    "end": 158
  },
  "target": {
    "op": "Variable",
    "name": "output"
  },
  "value": {
    "op": "String",
    "value": "Hello"
  }
}
```

The compiler should propagate this origin information through IR transformations and attach it to generated AST nodes wherever practical.

Maintain two mappings:

- **Source map:** generated JavaScript positions to source text positions.
- **Node-origin map:** generated JavaScript positions or AST nodes to visual node IDs.

The second mapping can support selecting a graph node when an error occurs, highlighting the node currently being executed, and displaying generated code for a selected node.

Because one source node can produce multiple JavaScript statements—and multiple source nodes can be optimized into one expression—this mapping should support one-to-many and many-to-one relationships rather than assuming a simple one-to-one correspondence.

Babel's generator supports source-map output, including scenarios involving multiple source files.

*Source: Babel*

## 10. Live compilation and incremental updates

The WYSIWYG editor may need to regenerate code whenever the user edits text, moves a node, changes a connection, or modifies a property.

Recompiling the entire program on every keystroke is a reasonable starting point for small projects. As programs grow, incremental compilation can reduce latency.

A sensible strategy is:

1. Assign stable IDs to IR nodes and symbols.
2. Track which nodes depend on other nodes.
3. Invalidate affected semantic-analysis and optimization results after an edit.
4. Recompute the affected IR region when safe.
5. Regenerate the affected JavaScript region, or the entire output if local regeneration is not yet reliable.
6. Refresh source maps and node-origin mappings.

A warning: incremental compilation is not just caching AST nodes. A change to a variable declaration can affect every use of that variable; a change to a function signature can invalidate many callers. Dependency tracking must account for semantic relationships, not just visual adjacency.

For the first implementation, prioritize deterministic full recompilation. Introduce incremental compilation only after correctness tests and profiling show that it is worthwhile.

## 11. Testing the compiler

A compiler needs more than tests that assert a particular output string. Formatting changes can alter output without changing behavior, and perfectly formatted JavaScript can still be semantically incorrect.

Use several layers of testing:

| Test type | What it verifies |
| --- | --- |
| Golden tests | Representative IR produces expected JavaScript |
| AST validity tests | Generated ASTs serialize and parse successfully |
| Semantic tests | Executing generated code matches the language specification |
| Differential tests | IR interpreter and generated JavaScript produce equivalent results |
| Property-based tests | Many automatically generated programs preserve expected invariants |
| Round-trip tests | Text parsing and graph conversion preserve program meaning |
| Browser integration tests | DOM operations, events and asynchronous behavior work in the intended browser |

A particularly valuable architecture is to implement a small reference interpreter for the IR. For a generated test program, execute it in the interpreter and execute its compiled JavaScript in a controlled environment, then compare results and observable effects.

For a visual language, also test that equivalent text-authored and graph-authored programs normalize to equivalent IR. This catches discrepancies before the JavaScript backend becomes involved.

## 12. Recommended architecture for the project

*Figure: recommended compiler architecture*

- **Text frontend** — Parser, syntax diagnostics
- **Graph frontend** — Nodes, wires, properties
- **Canonical semantic IR** — Stable node IDs, symbols, types, source origins, control flow
- **IR transformation passes** — Validation → lowering → optimization
- **JavaScript backend** — AST generation and source maps
- **IR interpreter** — Reference execution and debugging

The design should make the compiler deterministic: the same normalized IR and compiler configuration should produce the same output. This improves caching, reproducible builds, debugging, testing, and version-control diffs.

For the initial milestone, implement a small subset—literals, variables, arithmetic, function calls, conditionals, and simple loops. Generate JavaScript ASTs, emit readable code, validate the output, and compare its behavior against an IR interpreter. Add graph-specific lowering and DOM operations after the core pipeline is dependable.

## 13. Further research

These resources provide the most useful starting points:

- [Babel Generator](https://babel.dev/docs/babel-generator) — AST-to-code generation, formatting options and source maps.
- [Babel Traverse](https://babeljs.io/docs/babel-traverse.html) — visiting and modifying AST nodes.
- [Babel Core](https://babel.dev/docs/babel-core) — transforming existing ASTs and composing compiler passes.
- [TypeScript Compiler API](https://github.com/microsoft/TypeScript/wiki/Using-the-Compiler-API) — AST construction, diagnostics, symbol resolution and emission.
- [SWC Core API](https://swc.rs/docs/usage/core) — parsing, transforming, and generating JavaScript with source-map support.
- [ECMA-426 Source Map Specification](https://tc39.es/ecma426/) — the standard for mapping generated code to its original source.

## Suggested expansion of the research note

The scope should include mapping IR into optimized JavaScript, semantic preservation, graph-to-control-flow lowering, source maps, stable node identities, and testing, particularly when the same program is edited in both text and visual form.

The central research question is not merely how to generate JavaScript from an AST, but:

How should a language-neutral semantic IR be transformed into idiomatic, portable JavaScript while preserving program behavior, traceable source origins, and consistency between textual and visual representations?

That framing will help guide the design decisions as the language and its editor evolve.

A suitable pipeline uses a language-neutral semantic IR, semantics-preserving lowering passes, a JavaScript code generator, and source maps that retain links to original nodes and locations. Differential and property-based tests can help verify behavior preservation.
