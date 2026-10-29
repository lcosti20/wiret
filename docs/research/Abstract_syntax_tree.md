*(Snapshot of [Markup language – Wikipedia](https://en.wikipedia.org/wiki/Markup_language) as of 27 October 2026)*

---

# Abstract Syntax Tree (AST)

**Source**: [Wikipedia – Abstract syntax tree](https://en.wikipedia.org/wiki/Abstract_syntax_tree)  
**Note**: This article historically lacked sufficient inline citations (as of February 2013). Content has been cleaned and restructured for LLM consumption.

---

## Overview

An **abstract syntax tree** (**AST**) is a data structure used in computer science to represent the structure of a program or code snippet. It is a tree representation of the *abstract* syntactic structure of text (often source code) written in a formal language. Each node of the tree denotes a construct occurring in the text. It is sometimes called simply a **syntax tree**.

The syntax is “abstract” because it does not represent every detail appearing in the real (concrete) syntax, but only the structural or content-related details. For example:

- Grouping parentheses are implicit in the tree structure and do not appear as separate nodes.
- A syntactic construct such as an `if`-condition-then statement can be represented by a single node with three branches (condition, then-branch, else-branch).

This distinguishes abstract syntax trees from **concrete syntax trees** (also called **parse trees**). Parse trees are typically built by a parser during source-code translation and compilation. Once built, additional information is usually added to the AST through subsequent processing (e.g., contextual / semantic analysis).

Abstract syntax trees are also used in program analysis and program transformation systems.

### Illustrative Example

An abstract syntax tree for the following code implementing the Euclidean algorithm:

```text
while b != 0:
    if a > b:
        a := a - b
    else:
        b := b - a
return a
```

(The corresponding tree diagram typically shows a root “statement sequence” containing a `while` node and a `return` node. The `while` node has a condition (`b ≠ 0`) and a body that is a `branch`/`if` node with further comparison and assignment subtrees.)

---

## Application in Compilers

Abstract syntax trees are widely used in compilers to represent the structure of program code. An AST is usually the result of the **syntax analysis** (parsing) phase of a compiler. It often serves as an intermediate representation of the program through several later stages and has a strong influence on the final output of the compiler.

### Motivation

An AST has several properties that aid later compilation steps:

- It can be edited and annotated with extra information (properties, types, source locations, etc.) for every element. Such annotation is impractical on raw source text.
- Compared with source code, an AST omits non-essential punctuation and delimiters (braces, semicolons, parentheses, etc.).
- It usually carries extra information produced by earlier analysis stages (for example, the exact source position of each construct, enabling precise error messages).

Programming languages are frequently specified by a context-free grammar (CFG). However, many language features cannot be expressed by a CFG alone and require contextual information:

- User-declared types and their proper usage.
- Duck typing (type determined by context).
- Operator overloading (meaning depends on operand types).

These contextual constraints are typically checked and recorded while traversing or transforming the AST.

### Design Considerations

The design of an AST is closely linked to the design of the compiler and the features it must support. Core requirements commonly include:

- Preservation of variable types and the source location of each declaration.
- Explicit, well-defined representation of the order of executable statements.
- Correct identification and storage of left- and right-hand sides of binary operations.
- Storage of identifiers and assigned values for assignment statements.

Some operators always take a fixed number of children (e.g., binary addition). Other constructs (argument lists, statement sequences, etc.) may have an arbitrary number of children; the AST data structure must therefore support variable-arity nodes efficiently.

To support compiler verification it should be possible to **unparse** (pretty-print) an AST back into source code that is sufficiently similar in appearance to the original and identical in execution after recompilation.

During **semantic analysis** the compiler intensively uses the AST to:

- Check correct usage of language constructs.
- Build symbol tables.
- Verify overall program correctness by a complete tree traversal.

After verification the AST (or a refined version of it) typically serves as the basis for **code generation**, often by first producing a lower-level intermediate representation (IR).

---

## Other Usages

### AST Differencing (Tree Differencing)

AST differencing computes the list of differences between two ASTs. The resulting list is called an **edit script**. Each edit action refers directly to nodes of the AST (for example, “insert a new function-declaration node”). This technique is useful for fine-grained source-code change extraction and version-control analysis.

### Clone Detection

Because an AST abstracts away incidental syntactic details, it is a powerful representation for detecting code clones (duplicated or near-duplicated fragments).

---

## Formal Definition

### Arities

Let \( S \) be a set of *sorts* (syntactic categories). An *arity* is a tuple

\[
(s_1,\dots,s_n,s) \qquad (s_1,\dots,s_n,s\in S)
\]

also written \( (s_1,\dots,s_n)_s \). More precisely the set of all arities is

\[
\mathrm{Arity}(S) := \coprod_{n\in\mathbb{N}} S^{n+1}.
\]

Let \( O = \{O_\alpha\}_{\alpha\in\mathrm{Arity}(S)} \) be an \(\mathrm{Arity}(S)\)-indexed family of disjoint sets of *operators*. If an operator \( o \) has arity \( (s_1,\dots,s_n)_s \) we say that \( o \) has sort \( s \) and takes \( n \) arguments of sorts \( s_1,\dots,s_n \).

### Abstract Syntax Trees

Fix a finite set of sorts \( S \) and an \(\mathrm{Arity}(S)\)-indexed family of operators \( O \). Let \( X = \{X_s\}_{s\in S} \) be an \( S \)-indexed family of disjoint sets of *variables*. The family of abstract syntax trees

\[
A[X] = \{A[X]_s\}_{s\in S}
\]

is the smallest \( S \)-indexed family of disjoint sets closed under the following two rules:

1. **Variables are ASTs**  
   If \( x\in X_s \), then \( x\in A[X]_s \).

2. **Operators combine ASTs**  
   If \( o \) is an operator of arity \( (s_1,\dots,s_n)_s \) and \( a_i\in A[X]_{s_i} \) for every \( 1\le i\le n \), then

   \[
   o(a_1;\dots;a_n)\in A[X]_s.
   \]

In other words, an AST is either a variable of a given sort or the application of an operator to a correctly sorted tuple of subtrees.

---

## See Also

- Abstract semantic graph (ASG) / term graph
- Composite pattern
- Control-flow graph
- Directed acyclic graph (DAG)
- Document Object Model (DOM)
- Expression tree
- Extended Backus–Naur form (EBNF)
- Lisp (languages whose programs are trees, with macros that manipulate those trees)
- Parse tree (concrete syntax tree)
- Semantic resolution tree (SRT)
- Shunting-yard algorithm
- Syntax (programming languages)
- Symbol table
- TreeDL
- Abstract Syntax Tree Interpreters

---

## References (selected)

1. Fluri, Beat; Würsch, Michael; Pinzger, Martin; Gall, Harald C. (2007). “Change Distilling: Tree Differencing for Fine-Grained Source Code Change Extraction.” *IEEE Transactions on Software Engineering*, 33(11):725–743.
2. Falleri, Jean-Rémy et al. (2014). “Fine-grained and accurate source code differencing.” *Proceedings of the 29th ACM/IEEE International Conference on Automated Software Engineering*, pp. 313–324.
3. Koschke, Rainer; Falke, Raimar; Frenzel, Pierre (2006). “Clone Detection Using Abstract Syntax Suffix Trees.” *2006 13th Working Conference on Reverse Engineering*, IEEE, pp. 253–262.

### Further Reading

- Jones, Joel. “Abstract Syntax Tree Implementation Idioms” (PDF).
- Neamtiu, Iulian; Foster, Jeffrey S.; Hicks, Michael (2005). “Understanding Source Code Evolution Using Abstract Syntax Tree Matching.” *MSR’05*.
- Würsch, Michael. *Improving Abstract Syntax Tree based Source Code Change Detection* (Diploma thesis).
- Lucas, Jason (2006). “Thoughts on the Visual C++ Abstract Syntax Tree (AST).”
- Harper, Robert (2016). *Practical Foundations for Programming Languages* (2nd ed.). Cambridge University Press.

### External Resources

- AST View (Eclipse plugin for visualizing Java ASTs)
- JavaParser – library that produces an AST from Java source
- Spoon – library for analyzing, transforming and rewriting Java source via a well-designed AST
- AST Explorer – web tool for visualizing ASTs of many languages (JavaScript, Python, Go, Java, …)
- OMG Architecture-Driven Modernization: Abstract Syntax Tree Metamodeling (ASTM) standard

---

*Converted and cleaned for LLM-friendly consumption from the English Wikipedia article “Abstract syntax tree”.*

---

> ChatGPT prompt: I'm doing research on Abstract Syntax Trees. Here is the Wikipedia article for it. Can you expand on it?

# Abstract Syntax Trees (ASTs): An Expanded Guide

An abstract syntax tree (AST) is a structured representation of the meaningful syntactic elements of a program. It converts source code from a sequence of characters into a hierarchy of objects that a compiler, interpreter, code editor, or analysis tool can inspect and manipulate.

Your supplied Wikipedia article covers the definition, compiler applications, formal mathematical model, AST differencing, and clone detection. I'll use those topics as the foundation, then expand into practical implementation, design trade-offs, modern tooling, and connections to visual programming and AI-friendly language design.

## 1. The central idea

Consider this expression:

```
result = price + tax * rate
```

A text editor sees characters. A parser recognizes language constructs. An AST represents their relationships, including the fact that multiplication takes precedence over addition.

Assignment

Target

`result`

Addition

`price`

`×`

Right operand is multiplication

More precisely, the addition node has two children:

`price`

Multiply

`tax`

`rate`

The complete tree is conceptually:

```
Assignment
├── Name("result")
└── Add
    ├── Name("price")
    └── Multiply
        ├── Name("tax")
        └── Name("rate")
```

This representation makes operator precedence explicit. A tool does not need to rediscover the meaning of the expression by examining the original characters every time it processes the tree.

The AST is not the program's entire meaning, however. Determining whether `price`, `tax`, and `rate` are defined, whether their types support the operators, or whether an operation has side effects may require further analysis.

## 2. How source code becomes an AST

A conventional compiler or language tool often uses a pipeline like this:

### 1

### Source text

Characters, whitespace, comments, punctuation

### 2

### Lexical analysis

Tokens such as identifiers, numbers and operators

### 3

### Parsing

Grammar rules establish the hierarchical structure

### 4

### AST construction

Create nodes for meaningful language constructs

### 5

### Semantic analysis

Resolve names, check types and enforce constraints

### 6

### Transformation or execution

Optimize, interpret, generate code or edit the program

These are conceptual stages, not a universal mandatory sequence. Some parsers construct AST nodes directly while parsing; some languages interleave parsing and semantic checks; and some tools use intermediate representations between stages.

### Lexing versus parsing

For example:

```
total = 4 + 5
```

A lexer might produce:

```
IDENTIFIER("total")
EQUALS
INTEGER(4)
PLUS
INTEGER(5)
```

The parser then identifies the assignment and its expression. The AST generally retains the meaningful constructs and their relationships rather than the entire token stream.

### AST versus concrete syntax tree

A concrete syntax tree (CST), also called a parse tree, represents the grammar structures used to recognize the input. An AST simplifies this into the constructs needed by later tools.

| Property                | Concrete syntax tree                     | Abstract syntax tree                   |
| ----------------------- | ---------------------------------------- | -------------------------------------- |
| Main purpose            | Represent parsed grammatical structure   | Represent meaningful program structure |
| Grammar details         | Usually retained                         | Often collapsed or omitted             |
| Punctuation             | May appear explicitly                    | Often omitted                          |
| Comments and formatting | Can be preserved in suitable CST designs | Often not preserved directly           |
| Common uses             | Parsing, format-preserving editing       | Compilation, analysis, transformation  |

The distinction is not absolute. Some CSTs discard comments, and some ASTs preserve comments and formatting metadata. What matters is the representation's intended purpose.

## 3. Anatomy of an AST

An AST is more than a collection of nested objects. Its design defines how a language's constructs are represented and what operations can be performed reliably on them.

### Node types

A typical programming-language AST contains several categories of nodes:

Identifiers and literals

Names such as `customer` and values such as `42`, `"hello"` or `true`.

Expression nodes

Addition, comparisons, function calls, member access, assignments and other value-producing constructs.

Statement nodes

Declarations, conditionals, loops, returns, exception handling and other control structures.

Container nodes

Modules, classes, function bodies, parameter lists and sequences of statements.

These are conceptual categories, not a universal schema. Each language decides which constructs deserve distinct node types.

### Fixed-arity and variable-arity nodes

The article's formal discussion of arities is particularly useful here. An operator's arity is the number of arguments it accepts.&#x20;

Abstract_syntax_tree.md



- Fixed arity: a binary addition node has two operands; a unary negation node has one operand.
- Variable arity: a block may contain any number of statements, and a function call may have any number of arguments.
- Optional children: an `if` node may have an optional `else` branch, or a declaration may omit an initializer.

A language's schema must specify which combinations are legal. For example, a binary operator should not accidentally have only one operand or have its left and right operands swapped.

A simplified schema might look like this:

```
type Expr =
  | { kind: "Number"; value: number }
  | { kind: "Name"; name: string }
  | { kind: "Binary"; op: "+" | "-" | "*" | "/";
      left: Expr; right: Expr }
  | { kind: "Call"; callee: Expr; args: Expr[] };

type Stmt =
  | { kind: "Let"; name: string; value: Expr }
  | { kind: "Return"; value: Expr | null }
  | { kind: "Block"; statements: Stmt[] };
```

This example uses a tagged union: each node carries a `kind` identifying its structure, and its fields depend on that kind. The type system can help reject malformed trees before they reach later compiler stages.

### Source locations and metadata

A practical AST frequently carries metadata in addition to its structural children:

```
BinaryExpression
├── operator: "+"
├── source_span: [12, 23)
├── inferred_type: Number
├── left: Name("price")
└── right: Name("tax")
```

Here, the source span identifies where the expression appeared in the original text, while the inferred type is information that a later analysis stage might attach.

Useful metadata includes:

- Source spans, line numbers and column numbers.
- Resolved variable and function references.
- Inferred types and type constraints.
- Comments, documentation and formatting hints.
- Unique node identifiers, analysis results and diagnostic information.

Not every AST should store all of this. A small expression evaluator may need only node kinds and child references. A full IDE needs much richer source mapping and semantic information.

## 4. ASTs in compilers and interpreters

Your article describes ASTs as an important product of parsing and a basis for semantic analysis and code generation.&#x20;

Abstract_syntax_tree.md

&#x20;Let's expand on what that means in practice.



### Semantic analysis

Syntactic validity does not guarantee that a program makes sense.

```
x = unknown_function(10)
```

This may be syntactically valid even if `unknown_function` has never been defined. A semantic-analysis pass can walk the AST, consult symbol tables, resolve identifiers and report errors.

For example, a compiler might annotate a call node with a resolved function symbol and its return type. Those annotations let subsequent passes reason about the program without repeating the same name-resolution work.

### Interpretation

An interpreter can evaluate AST nodes directly. A simplified evaluator might follow rules like these:

```
def evaluate(node, environment):    if node.kind == "Number":        return node.value    if node.kind == "Name":        return environment[node.name]    if node.kind == "Binary":        left = evaluate(node.left, environment)        right = evaluate(node.right, environment)        if node.op == "+":            return left + right        if node.op == "*":            return left * right    raise ValueError("Unsupported expression")
```

This is illustrative pseudocode: a real evaluator must define error handling, operator semantics, evaluation order and all supported node kinds.

### Code generation and intermediate representations

Compilers do not necessarily translate an AST straight into machine instructions. They often transform it into a lower-level intermediate representation (IR), where control flow, data dependencies and machine-independent optimizations are easier to express.

For instance, a source-level loop might become a collection of basic blocks connected by branches in a control-flow graph. The AST represents the source-level construct; the control-flow graph represents how execution can move between blocks.

The stages can therefore be understood as different views of the same program:

| Representation              | Main concern                                             |
| --------------------------- | -------------------------------------------------------- |
| Source text                 | What the programmer wrote                                |
| AST                         | Which language constructs are nested within which others |
| Typed or annotated AST      | What names and expressions mean under language rules     |
| Intermediate representation | How computation and control flow can be transformed      |
| Machine code or bytecode    | How the program is executed                              |

The exact boundaries vary by compiler. CPython, for example, parses Python into an AST, transforms it into an instruction sequence, constructs a control-flow graph, performs optimizations and emits bytecode.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://github.com\&sz=32)

GitHub+1



## 5. A formal perspective: ASTs as typed terms

The supplied article gives a mathematical definition based on sorts, operators, arities and variables.&#x20;

Abstract_syntax_tree.md



This provides a foundation for designing reliable syntax representations.

Suppose the sorts are:

\\[ S = \\{\text{Expr},\text{Stmt}\\} \\]

We can define operators such as:

- `Number : () → Expr`
- `Add : (Expr, Expr) → Expr`
- `Multiply : (Expr, Expr) → Expr`
- `Return : Expr → Stmt`
- `Block : Stmt* → Stmt`

Here, `Stmt*` denotes zero or more statements. The notation is schematic; actual formal definitions may encode literals and variables differently.

An expression such as \\(2 + 3 \times 4\\) becomes:

\\[ \operatorname{Add}\bigl(   \operatorname{Number}(2),   \operatorname{Multiply}(     \operatorname{Number}(3),     \operatorname{Number}(4)   ) \bigr) \\]

The important point is that the tree's shape encodes the grouping. The multiplication node is nested inside the addition node's right operand.

### Why sorts matter

Sorts constrain which operators can receive which children. A `Return` node expects an expression, while an `Add` node expects two expressions.

This gives a distinction between three kinds of correctness:

1. Structural correctness: the tree follows the AST schema.
2. Syntactic correctness: the tree corresponds to a construct permitted by the language grammar.
3. Semantic correctness: the constructs are meaningful under the language's rules.

These levels overlap, but they are not interchangeable. A well-formed AST can still contain a reference to an undefined variable or a type-invalid operation.

## 6. AST differencing, transformations and code clones

The Wikipedia article highlights AST differencing and clone detection as applications beyond conventional compilation.&#x20;

Abstract_syntax_tree.md



### Tree differencing

Consider two versions of a function:

```
def calculate(x):    return x + 1
```

```
def calculate(x):    return x * 2
```

A line-based diff sees a changed line. An AST differencer can identify a more precise change:

```
Update BinaryExpression.operator
From: "+"
To:   "*"

Update NumericLiteral
From: 1
To:   2
```

That structural edit script is useful for code review, refactoring analysis, automated repair and mining software evolution. Research on GumTree and related algorithms emphasizes that detecting moves and matching corresponding nodes can make these scripts better reflect developers' changes.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://doi.org\&sz=32)

DOI+1



However, a structural edit script is not automatically a semantic explanation. Replacing `+` with `*` may have very different consequences depending on operand types and program context.

### Clone detection

Two fragments can differ textually but share a similar AST structure:

```
subtotal = price + fee
```

```
amount = cost + charge
```

A structural detector can recognize the shared pattern by treating identifiers as placeholders. This is useful for detecting duplicated logic despite renamed variables.

More sophisticated detectors can normalize literals, compare subtrees, or combine syntax with control-flow and data-flow information.

### Program transformations

An AST can also serve as a target for refactoring rules:

- Rename a variable while updating references.
- Replace a deprecated API call.
- Introduce a helper function.
- Rewrite an expression into a different form.
- Insert instrumentation or validation code.

A safe transformation should preserve language constraints and, where required, program behavior. Merely producing a tree that satisfies the schema is not enough.

## 7. Important design trade-offs

An AST is a design choice, not simply the inevitable output of a parser. Different representations suit different tasks.

| Design decision | Option A                      | Option B                                 |
| --------------- | ----------------------------- | ---------------------------------------- |
| Source fidelity | Abstract tree; discard trivia | Preserve tokens, comments and formatting |
| Mutability      | Mutable nodes                 | Immutable snapshots                      |
| Relationships   | Strict tree                   | Shared nodes or graph references         |
| Semantic data   | Separate analysis tables      | Annotations attached to nodes            |
| Error handling  | Reject invalid syntax         | Represent incomplete or erroneous syntax |
| Node identity   | Structural equality           | Stable identity across edits             |

Each choice has consequences.

### Abstractness versus source fidelity

A conventional AST might treat these expressions as structurally equivalent:

```
x + y
```

```
x+y
```

That is useful for semantic analysis, but a formatter or refactoring tool may need to preserve the original spacing and comments.

Some tools therefore retain concrete syntax information alongside abstract structure. Microsoft's Roslyn syntax trees, for example, preserve tokens, whitespace, comments and other trivia, and can reproduce the original source text.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://learn.microsoft.com\&sz=32)

Microsoft Learn+1



### Mutable versus immutable trees

A mutable AST allows a transformation to change a node in place. This is straightforward, but shared references can make it difficult to reason about which analyses remain valid after a change.

An immutable AST creates a new version when edited. This supports safe sharing and easier concurrent analysis, although transformations must construct replacement nodes and manage the resulting versions.

Neither strategy is universally superior. The choice depends on the expected editing workload, performance requirements and API design.

### Trees versus graphs

A conventional AST has a single parent for each non-root node. However, compiler systems often need relationships that do not fit a tree:

- Multiple references to the same declaration.
- Control-flow edges between statements.
- Data dependencies between computations.
- Shared expressions in an optimized representation.

These relationships can be maintained in side tables or represented in additional graphs. A directed acyclic graph (DAG) can share subexpressions, for example, while a control-flow graph can contain cycles representing loops.

This distinction matters: an AST, a semantic graph and a control-flow graph are related representations, not interchangeable names for the same structure.

## 8. ASTs in editors and interactive programming

ASTs are especially important when source code must be analyzed while the user is actively editing it.

An ordinary compiler can often wait until the source file is complete. An editor cannot: the user may temporarily leave an expression unfinished, delete a closing bracket or type half a declaration.

An editor-oriented parser therefore benefits from:

- Incremental parsing after small text changes.
- Error recovery for incomplete code.
- Source positions for diagnostics and navigation.
- Efficient queries for declarations, expressions and references.
- Reliable mapping between syntax and the visible text.
