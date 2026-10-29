---
title: "AI-Friendly Syntax Design"
document_type: "Research note"
formatted: 2026-10-28
---

# AI-Friendly Syntax Design

> Designing programming-language syntax and grammars to minimize LLM errors, reduce token consumption, improve code generation reliability, and make programs easier for AI systems to understand, generate, validate, and modify.

AI-Friendly Syntax Design is an approach to programming-language design that treats AI systems—particularly large language models (LLMs)—as first-class language users. Instead of optimizing syntax exclusively for human readability, compiler implementation, or runtime efficiency, it considers how reliably a model can generate, interpret, transform, and reason about programs expressed in the language.

The central premise is that a programming language's syntax can influence how often an AI model makes mistakes when working with code.

Traditional language design generally assumes a human programmer will understand the language's abstractions, consult documentation, use an IDE, and rely on compiler errors to correct mistakes. AI-assisted programming introduces a different workflow: a model predicts sequences of tokens, often using incomplete context, and may produce plausible-looking code that is syntactically valid but semantically incorrect.

A language designed with AI in mind could reduce these errors through explicit structure, consistent grammar, predictable conventions, strong constraints, and representations that are easy to generate incrementally.

This does not mean making a language that only machines can read. The goal is to find a productive balance among human ergonomics, machine verification, model reliability, and representation efficiency.

## Contents

- [1. Goals of AI-friendly syntax](#1-goals-of-ai-friendly-syntax)
- [2. The key distinction: syntax versus semantics](#2-the-key-distinction-syntax-versus-semantics)
- [3. Core design principles](#3-core-design-principles)
- [4. Token efficiency: optimize the right thing](#4-token-efficiency-optimize-the-right-thing)
- [5. A proposed syntax profile for AI-friendly languages](#5-a-proposed-syntax-profile-for-ai-friendly-languages)
- [6. Syntax design and constrained decoding](#6-syntax-design-and-constrained-decoding)
- [7. A practical design checklist](#7-a-practical-design-checklist)
- [8. How to evaluate whether a syntax is actually AI-friendly](#8-how-to-evaluate-whether-a-syntax-is-actually-ai-friendly)
- [9. Limitations and design risks](#9-limitations-and-design-risks)
- [10. Open research questions](#10-open-research-questions)
- [11. Suggested reading](#11-suggested-reading)
- [Conclusion](#conclusion)

## 1. Goals of AI-friendly syntax

1. **Minimize hallucinations and generation errors** — Make invalid or unintended constructs difficult to express. Reduce ambiguity between similar constructs, encourage explicit references to declarations, and use grammar rules that help models distinguish valid syntax from plausible inventions.
2. **Reduce token consumption** — Represent common operations compactly without introducing excessive punctuation, repetitive boilerplate, or verbose syntax that consumes context-window space. Optimize for actual tokenizer behavior rather than character count alone.
3. **Improve structural predictability** — Use consistent rules for declarations, expressions, control flow, types, imports, and error handling. A model should be able to infer what can appear next from the local syntactic context.
4. **Support incremental generation and repair** — Favor structures that can be completed in small, coherent steps, with clear boundaries between constructs. When a model makes a mistake, the compiler or parser should identify a localized error and help the model correct it.
5. **Make code easy to inspect and transform** — Prefer explicit relationships between declarations and uses, stable formatting, machine-readable structure, and local edits that do not require extensive rewriting of unrelated code.

These goals can conflict. A very compact syntax may be harder to disambiguate; a highly explicit syntax may consume more tokens; a grammar that is easy to parse may be awkward for people to write. AI-friendly design is therefore an optimization problem, not a rule that shorter or more rigid syntax is always better.

## 2. The key distinction: syntax versus semantics

A useful AI-friendly language must address several layers of correctness.

| Layer | What can go wrong? | Relevant design strategies |
| --- | --- | --- |
| Lexical | Incorrect identifiers, delimiters, or literals | Consistent tokens, unambiguous delimiters |
| Syntactic | Missing arguments, malformed blocks, invalid ordering | Predictable grammar, explicit structure |
| Name resolution | Undefined variables or nonexistent functions | Scoped declarations, explicit imports, symbol checking |
| Type correctness | Incompatible values or invalid operations | Strong static typing, inference with clear constraints |
| Semantic correctness | Code compiles but implements the wrong behavior | Contracts, invariants, tests, specifications |
| Operational correctness | Unexpected side effects, resource leaks, unsafe actions | Effect tracking, ownership rules, runtime checks |

Syntax can directly improve the first two layers and indirectly support the others. It cannot, by itself, eliminate semantic hallucinations.

For example, an LLM might generate a perfectly valid loop that iterates over the wrong collection. No punctuation scheme or context-free grammar can establish that the programmer intended a different collection. That requires semantic constraints, task context, tests, or external verification.

A strong design therefore combines generation-friendly syntax with verification-friendly semantics.

## 3. Core design principles

The following principles are proposed design guidelines rather than established laws. Each should be tested against representative models and programming tasks.

### 3.1 Prefer one canonical way to express an operation

Many languages support multiple equivalent forms. This flexibility is useful for human expression, but it increases the number of patterns a model must learn and may make generated code inconsistent.

Consider three ways of expressing a function in different languages:

```python
def add(a, b):
    return a + b
```

```javascript
const add = (a, b) => a + b;
```

```rust
fn add(a: i32, b: i32) -> i32 {
    a + b
}
```

These examples differ in more than syntax: they also reflect different type systems and execution semantics. The design lesson is not to force all languages into one notation, but to avoid gratuitous variation within a language.

For example, a language could choose a single convention for:

- Function declaration and return values.
- Named and positional arguments.
- Conditional expressions and statements.
- Collection literals and indexing.
- Optional values and error propagation.
- Generic type parameters and type annotations.

Design rule: When two constructs serve the same purpose, prefer one standard form unless the alternatives offer a meaningful benefit.

### 3.2 Minimize context-dependent ambiguity

A grammar is especially useful when a prefix makes the legal next constructs predictable.

For example, consider a language that permits both implicit and explicit statement termination, optional parentheses around conditions, and context-sensitive interpretation of braces. Even when a human understands the conventions, an LLM may accidentally combine rules from different languages.

A more predictable design might require:

```text
if (condition) {
    action()
}
```

rather than allowing many interchangeable forms.

However, strict punctuation is not automatically better. A language with indentation-sensitive blocks can also be predictable. What matters is that the grammar has clear, consistent rules and that partial programs can be parsed reliably.

Useful properties include:

- Explicit boundaries between expressions, statements, and declarations.
- Minimal dependence on whitespace unless indentation is the chosen structural rule.
- Few special cases where a token changes meaning according to distant context.
- Clear precedence and associativity rules.
- Limited ambiguity when parsing incomplete source code.

### 3.3 Make important distinctions explicit

Implicit behavior can shorten programs, but it can also hide decisions that the model must infer.

For example:

```text
result = fetch_data()
```

What happens if the operation fails? Does it throw an exception, return an optional value, return a result object, or produce a default?

An explicit design might require:

```text
result: Result<Data, FetchError> = fetch_data()
```

The exact notation is illustrative. The important point is that the type exposes a meaningful distinction between successful and unsuccessful outcomes.

Other candidates for explicit representation include:

- Nullable versus non-nullable values.
- Mutable versus immutable bindings.
- Synchronous versus asynchronous operations.
- Pure computations versus side effects.
- Owned versus borrowed resources.
- Checked versus unchecked conversions.
- Potentially destructive operations.

Not every distinction needs to appear at every call site. The aim is to make consequential behavior visible and statically checkable, not to annotate every trivial operation.

### 3.4 Favor local reasoning

A model should be able to understand a construct without reconstructing a large amount of distant context.

For example, compare:

```text
run(x)
```

with a call whose argument roles are explicit:

```text
run(input = x, mode = "safe")
```

Named arguments can reduce mistakes when functions have multiple parameters of similar types. They also make call sites easier to inspect after an API changes.

The trade-off is additional tokens. For short, stable functions such as `add(a, b)`, positional arguments may be perfectly adequate.

A practical policy is to use named arguments when they improve clarity, particularly for:

- Multiple parameters with the same type.
- Optional parameters.
- Boolean configuration flags.
- Security-sensitive settings.
- Calls to APIs that change frequently.

### 3.5 Make invalid programs difficult to express

Syntax should work with the type system and compiler to eliminate common mistakes before execution.

For example, a language could represent an HTTP response as a tagged union:

```text
Response =
 Ok(value: Data)
 | Failed(error: NetworkError)
```

Code consuming this response would have to handle the relevant variants explicitly, rather than assuming every request succeeds.

The strongest form of this principle is not merely requiring additional keywords. It is designing types and constructs so that invalid states cannot be represented, or are at least difficult to construct accidentally.

This can include:

- Exhaustive pattern matching.
- Explicit optional types.
- Typed error values.
- Restricted constructors.
- Validated data types.
- Compile-time checks for resource ownership.
- Effect constraints on operations with side effects.

The compiler must enforce these rules. A model may still generate an incorrect program, but the language should reject more classes of mistakes automatically.

### 3.6 Keep formatting and structure regular

Regular source code reduces the number of visual and syntactic patterns a model encounters.

A language could standardize:

- Declaration ordering.
- Block delimiters or indentation.
- Type annotation placement.
- Import organization.
- Line wrapping and trailing separators.
- Comment conventions.
- Serialization of syntax trees.

A canonical formatter is particularly useful. It allows a model to edit logical constructs while the toolchain handles presentation consistently.

This reduces formatting variation, makes diffs easier to review, and provides a stable representation for training data and automated tools.

### 3.7 Design for incomplete prefixes

LLMs generate code incrementally. A grammar that is easy to parse only after an entire file is complete may be less convenient for interactive generation.

Consider an incomplete prefix:

```javascript
function calculate(
```

A generation-friendly parser should know that the next tokens must complete a parameter list, not begin an unrelated top-level declaration.

The same idea applies to editor completion, constrained decoding, code repair, and structured output generation.

A language should ideally support:

- Incremental parsing.
- Clear parser states for incomplete constructs.
- Localized diagnostics.
- Stable syntax-tree nodes during edits.
- Well-defined recovery from malformed code.

This principle is supported by research on grammar-constrained generation: formal grammars can restrict an LLM's output to valid continuations. But this guarantee depends on the grammar, tokenizer alignment, and decoding implementation.

## 4. Token efficiency: optimize the right thing

Token consumption is an important consideration, but the shortest source code is not necessarily the most token-efficient or reliable source code.

LLMs typically process text using a tokenizer that splits source into model-specific token units. Character count, byte count, and token count are different metrics.

For example, a short but unfamiliar identifier might tokenize into more pieces than a longer, familiar identifier. Punctuation-heavy syntax may also interact poorly with some tokenizers.

Consider two representations of a configuration:

```text
timeout = 30
retries = 3
enabled = true
```

and:

```text
cfg{t:30,r:3,e:1}
```

The second representation is shorter in characters, but it introduces abbreviations and an encoded boolean convention. Unless those conventions are well established in the model's training or supplied context, the apparent savings may be offset by misinterpretations and correction attempts.

### 4.1 Measure effective token cost

A useful proposed metric is effective token cost:

$$
C_{\mathrm{effective}} =
   C_{\mathrm{source}} +
   C_{\mathrm{context}} +
   C_{\mathrm{repair}} +
   C_{\mathrm{verification}}
$$

Where:

- $C_{\mathrm{source}}$ is the token cost of the generated code.
- $C_{\mathrm{context}}$ is the additional documentation, examples, and declarations needed to understand it.
- $C_{\mathrm{repair}}$ is the cost of fixing errors and regenerating code.
- $C_{\mathrm{verification}}$ is the cost of validation steps attributable to the representation.

This is a conceptual metric, not a standardized measurement. It can be adapted to distinguish input tokens, output tokens, tool calls, and compute cost.

The important insight is that a verbose construct may be cheaper overall if it prevents repeated mistakes, while a compact construct may be expensive if the model needs extensive documentation to understand it.

### 4.2 Avoid unnecessary repetition, not useful redundancy

Repeated syntax is not always wasteful. Some repetition provides valuable local information.

For example:

```text
user.age + order.age
```

is slightly longer than:

```text
u.a + o.a
```

But the descriptive names reduce the need to consult distant declarations and make mistakes easier to notice.

Potentially wasteful repetition includes:

- Requiring boilerplate that could be inferred safely by the compiler.
- Repeating long namespace paths when a clear import is available.
- Requiring redundant type annotations where inference is reliable.
- Duplicating information that can be derived deterministically.

Useful redundancy includes:

- Explicit argument names where positional confusion is likely.
- Types at boundaries between components.
- Error-handling branches.
- Resource and effect annotations.
- Meaningful identifiers and domain terminology.

### 4.3 Prefer tokenizer-aware benchmarks

Any proposal claiming token savings should be evaluated with the actual tokenizers of several target models.

A reasonable benchmark would report:

| Metric | What it reveals |
| --- | --- |
| Characters and bytes | Physical source size |
| Model tokens | Actual context and generation cost |
| Tokens to first valid program | Efficiency of incremental generation |
| Tokens spent on repairs | Cost of correcting mistakes |
| Successful tasks per token | Practical efficiency |
| Total inference latency | Runtime implications |

A language should not be optimized around one tokenizer unless it is explicitly intended for one model or model family.

## 5. A proposed syntax profile for AI-friendly languages

The following profile combines the principles above into a hypothetical language design. It is not a claim that a particular syntax has been empirically proven optimal.

### 5.1 Use explicit, regular declarations

```text
module geometry

type Point = {
 x: Float
 y: Float
}

fn distance(a: Point, b: Point) -> Float {
 let dx: Float = a.x - b.x
 let dy: Float = a.y - b.y
 return sqrt(dx * dx + dy * dy)
}
```

This example illustrates several possible choices:

- Declarations have consistent keyword-based forms.
- Types appear in a predictable position.
- Functions use an explicit return type.
- Bindings are introduced with `let`.
- Blocks have explicit boundaries.
- Member access uses one consistent notation.

The syntax is deliberately conventional. A new language does not necessarily need unusual symbols to be AI-friendly; familiar syntax may benefit from the models' existing programming knowledge.

### 5.2 Make control flow explicit

```text
fn classify(value: Int) -> String {
 if (value < 0) {
 return "negative"
 } else if (value == 0) {
 return "zero"
 } else {
 return "positive"
 }
}
```

The parser can distinguish conditions, branches, and return statements without relying on unconventional punctuation.

A language might also require exhaustive pattern matching when branching on a closed set of variants:

```text
fn describe(result: Result<Int, Error>) -> String {
 match result {
 Ok(value) => "success"
 Err(error) => "failure"
 }
}
```

Here, the compiler could reject a missing variant. That is more valuable than a syntax rule alone because it constrains the program's behavior.

### 5.3 Prefer explicit effects at important boundaries

```text
fn load_config(path: Path) -> IO<Result<Config, ConfigError>> {
 // Read and parse the configuration file.
}
```

This is illustrative notation for a function whose execution performs I/O and may fail. It shows how a language could distinguish effects and error outcomes in the function's type.

An effect system is not mandatory for AI-friendly syntax, and a type annotation does not automatically prove correct error handling. The benefit comes from compiler-enforced rules that make the relevant behaviors visible and verifiable.

### 5.4 Provide a machine-friendly canonical representation

A language could support a standard abstract syntax tree (AST) format alongside its human-readable source syntax.

For example, a simplified representation of a function call might look like:

```json
{
  "kind": "Call",
  "callee": {
    "kind": "Name",
    "name": "sqrt"
  },
  "arguments": [
    {
      "kind": "Binary",
      "operator": "*",
      "left": {
        "kind": "Name",
        "name": "dx"
      },
      "right": {
        "kind": "Name",
        "name": "dx"
      }
    }
  ]
}
```

This makes the relationship between the call, its callee, and its arguments explicit. It also enables structural edits without manipulating punctuation directly.

However, a full AST serialized as JSON can be much more verbose than source code. It is better treated as an optional representation for structural editing, constrained generation, and tool interoperability than as the default format for every task.

A promising design would support both:

1. Surface syntax for ordinary programming and review.
2. Structured syntax for AST-aware tools, editors, agents, and model-constrained generation.

## 6. Syntax design and constrained decoding

AI-friendly syntax should not be studied independently of the tools used to generate it.

Grammar-constrained decoding combines a language model with a parser or grammar engine. At each generation step, the system restricts which next tokens are allowed, aiming to ensure that the final output conforms to a specified grammar. Research has demonstrated this approach for structured outputs and has explored ways to improve how the constraints interact with the model's probability distribution.

*Figure: grammar-constrained decoding loop*

- **Task and program context** — Requirements, available APIs, existing declarations
- **LLM proposes the next token**
- **Constraint engine** — Grammar, symbol environment, type rules
   - *Valid continuation:* Accept and continue
   - *Invalid continuation:* Mask or reject
- **Compile, test, and validate** — Check properties beyond the grammar

A crucial design opportunity is to make the language's grammar easy for such systems to implement efficiently.

### Three levels of generation constraints

| Level | Constraint | What it can prevent |
| --- | --- | --- |
| 1. Syntactic | Formal grammar and parser state | Missing delimiters, invalid statement forms |
| 2. Name- and type-aware | Scope, declarations, type information | Undefined names, incompatible argument types |
| 3. Semantic | Contracts, invariants, domain rules | Some invalid states and behavior that violates formal requirements |

The second level is especially important. A program can be syntactically valid while referring to a nonexistent function or passing the wrong type of argument.

In a 2025 PLDI paper, Type-Constrained Code Generation with Language Models, researchers demonstrated a method that incorporates type-system constraints into generation. Their experiments reported that type-constrained generation reduced compilation errors by more than half across the evaluated synthesis, translation, and repair tasks. These are results for their method and experimental setting, not a guarantee for every language or model.

This suggests an important research direction: design languages whose grammar, symbol resolution, and type system can all provide useful feedback during incremental generation.

## 7. A practical design checklist

The following checklist can be used when evaluating a new language or revising an existing one.

**Design review checklist**

*Grammar*

- [ ] One canonical syntax for common operations
- [ ] Clear statement and expression boundaries
- [ ] Unambiguous operator precedence
- [ ] Incremental parsing of incomplete source

*Types and semantics*

- [ ] Explicit representation of optional and fallible results
- [ ] Predictable type inference rules
- [ ] Exhaustive handling of closed variants
- [ ] Static checks for common invalid states

*Token efficiency*

- [ ] Measured token counts for target models
- [ ] Limited unnecessary boilerplate
- [ ] Descriptive identifiers retained where useful
- [ ] Low repair-token overhead

*Tooling*

- [ ] Machine-readable diagnostics
- [ ] Stable AST and canonical formatter
- [ ] Compiler feedback suitable for iterative repair
- [ ] Optional grammar- and type-constrained decoding

*Human factors*

- [ ] Readable source code
- [ ] Easy debugging and code review
- [ ] Accessible documentation and examples
- [ ] Reasonable learning curve for programmers

## 8. How to evaluate whether a syntax is actually AI-friendly

A language should not be considered AI-friendly simply because its designer believes its grammar is regular or its code is concise. The claim needs empirical support.

A rigorous experiment would compare multiple language designs while holding other variables as constant as possible.

### Experimental design

1. Select a representative set of programming tasks, including code synthesis, translation, completion, and repair.
2. Implement equivalent programs in the candidate syntaxes, preserving their semantics.
3. Test several LLMs with different sizes and tokenizer families.
4. Keep task instructions, available APIs, sampling settings, and evaluation procedures consistent.
5. Compile and test the generated programs automatically.
6. Measure token usage, success rates, repair effort, and human readability.

Useful metrics include:

| Metric | Measurement |
| --- | --- |
| Syntax validity | Percentage of outputs accepted by the parser |
| Type correctness | Percentage accepted by the type checker |
| Functional correctness | Percentage passing behavioral tests |
| Hallucinated references | Frequency of nonexistent symbols and APIs |
| Repair cost | Additional generations or tokens needed for success |
| Token efficiency | Successful tasks per generated token |
| Human usability | Comprehension, editability, and review time |

It is important to distinguish pass rate from pass rate per token. A design might produce fewer tokens but also more failed programs. Conversely, a more explicit syntax might increase initial token usage while substantially improving success rates.

A good benchmark should also measure the effects of training-data familiarity. An unconventional language may initially perform poorly because the model has seen fewer examples, rather than because the grammar itself is intrinsically difficult.

One particularly useful experiment would compare three conditions:

- Ordinary unconstrained generation.
- Generation constrained by the candidate language's grammar.
- Generation constrained by both grammar and types.

This helps distinguish benefits attributable to the language's syntax from benefits provided by its compiler and generation tooling.

## 9. Limitations and design risks

AI-friendly design introduces several potential failure modes of its own.

Over-regularization. Removing useful language features may make programs longer or force awkward workarounds.

Over-verbosity. Explicit annotations and repeated labels may consume more context than they save in error correction.

Model dependence. A syntax optimized for one model or tokenizer may perform worse with another.

False confidence. A compiler-valid program may still implement the wrong algorithm, mishandle edge cases, or introduce security vulnerabilities.

Constraint overhead. Parsing, type-aware decoding, and maintaining symbol environments can increase generation latency and implementation complexity.

Distribution distortion. Restricting the model's candidate tokens can change the relative probabilities of valid outputs, so guaranteeing syntactic validity does not guarantee the highest-quality result. This is a documented concern in research on grammar-constrained and grammar-aligned decoding.

Human usability. A language that is easy for a model to generate may be unpleasant for people to maintain. Human readability, debugging, and code review should remain explicit evaluation criteria.

## 10. Open research questions

AI-Friendly Syntax Design is best treated as an emerging design problem rather than a settled discipline. Several questions deserve systematic investigation:

- **Grammar complexity:** Which grammatical properties best predict reliable generation across models?
- **Syntax versus tooling:** How much improvement comes from the surface language itself, versus constrained decoding and compiler feedback?
- **Explicitness versus inference:** Which facts should appear in source code, and which should be inferred by the compiler?
- **Tokenization:** Can a language be designed to tokenize efficiently across multiple model families without sacrificing readability?
- **Error localization:** Which syntax structures make it easiest for a model to repair a small mistake without rewriting a whole function?
- **Semantic constraints:** How can APIs, types, contracts, and domain rules be exposed to a model at generation time?
- **Training effects:** How much of a syntax's apparent advantage persists after models are trained on comparable amounts of code?
- **Long-context behavior:** Does regularity improve correctness when the model must understand and modify large codebases?
- **Agent workflows:** How should a language support code generation, compilation, execution, testing, and iterative repair by autonomous coding agents?

These questions connect language design to compiler construction, programming-language theory, software engineering, and LLM inference research.

## 11. Suggested reading

The following papers provide a useful foundation for research in this area.

- **Grammar-Constrained Decoding for Structured NLP Tasks without Finetuning (2023)** — *Geng, Josifoski, Peyrard, and West · EMNLP.* Explains how formal grammars can constrain LLM output and improve adherence to structured formats. [Read the paper](https://aclanthology.org/2023.emnlp-main.674/)
- **Grammar-Aligned Decoding (2024)** — *Park, Wang, Berg-Kirkpatrick, Polikarpova, and D'Antoni · NeurIPS.* Investigates the distributional effects of constrained generation and the challenge of producing high-quality outputs while guaranteeing validity. [Read the paper](https://papers.nips.cc/paper_files/paper/2024/hash/2bdc2267c3d7d01523e2e17ac0a754f3-Abstract-Conference.html)
- **Type-Constrained Code Generation with Language Models (2025)** — *Mündler, He, Wang, Sen, Song, and Vechev · PLDI.* Particularly relevant to language design because it explores how type information can constrain code generation beyond syntax alone. [Read the paper](https://doi.org/10.1145/3729274)
- **Flexible and Efficient Grammar-Constrained Decoding (2025)** — *Park, Zhou, and D'Antoni · ICML.* Examines the efficiency of grammar-constrained decoding, an important consideration when evaluating whether a language is practical for AI-driven development. [Read the paper](https://proceedings.mlr.press/v267/park25l.html)
- **Large Language Models for Visual Programming Languages: A Systematic Analysis of Representation, Constraints, and Tasks (2026)** — *Zhang, Chen, Zhou, and Wen · Journal of Systems Architecture, online 22 August 2026.* A systematic review of LLM work on executable visual programming languages, reported to cover 41 studies from 2022–2025; directly relevant to this note's central question. *Verification note: this entry comes from the fact-check report; the publisher page could not be retrieved when these files were corrected, so confirm the details before citing.* [DOI 10.1016/j.sysarc.2026.103968](https://doi.org/10.1016/j.sysarc.2026.103968)

## Conclusion

AI-Friendly Syntax Design seeks to make programming languages easier for LLMs to generate, interpret, and modify reliably, without losing the properties that make them useful to human programmers.

The strongest direction is not necessarily a radically new notation or a compressed programming language. It is a language whose syntax is predictable, whose semantics are explicit where they matter, whose type system rejects common errors, and whose tooling can guide generation incrementally.

The central hypothesis is testable: if two language designs express the same functionality, one may enable models to produce more correct programs with fewer tokens and less repair effort. Establishing when that happens—and why—would provide a rigorous foundation for the field.
