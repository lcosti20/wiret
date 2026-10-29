---
title: "LLM Tokenization and Syntax Predictability"
document_type: "Research note"
formatted: 2026-10-28
---

# LLM Tokenization and Syntax Predictability

LLM Tokenization and Syntax Predictability is the study of how the way a programming language, markup language, or intermediate representation (IR) is written affects an AI model's ability to understand it, generate it accurately, edit it, and reason about its structure.

The central design question is:

Can we design a syntax that makes correct output easier for an LLM to produce than incorrect output?

This matters for AI-generated code, visual programming languages, workflow graphs, configuration files, structured data, and languages designed specifically for AI-assisted development. It is especially relevant when an LLM must generate a large structured artifact, modify one part without damaging another, or keep a textual representation synchronized with a graphical editor.

The initial hypothesis is promising: a flat, explicit, line-oriented representation may be more reliable for some AI tasks than deeply nested JSON or XML. However, token count, syntactic complexity, and generation reliability are related but distinct properties. The best design optimizes all three without sacrificing semantic clarity or human usability.

## Contents

- [1. What tokenization means for code](#1-what-tokenization-means-for-code)
- [2. Why deeply nested syntax can be harder to generate](#2-why-deeply-nested-syntax-can-be-harder-to-generate)
- [3. Syntax predictability: what makes a format AI-friendly?](#3-syntax-predictability-what-makes-a-format-ai-friendly)
- [4. Token efficiency is not the same as syntactic simplicity](#4-token-efficiency-is-not-the-same-as-syntactic-simplicity)
- [5. How the model predicts syntax](#5-how-the-model-predicts-syntax)
- [6. Why grammar validity is not enough](#6-why-grammar-validity-is-not-enough)
- [7. Designing a token-efficient graph IR](#7-designing-a-token-efficient-graph-ir)
- [8. Bidirectional editing and partial generation](#8-bidirectional-editing-and-partial-generation)
- [9. How to test the hypothesis scientifically](#9-how-to-test-the-hypothesis-scientifically)
- [Experimental design](#experimental-design)
- [10. Related research and further reading](#10-related-research-and-further-reading)
- [11. Conclusions and open questions](#11-conclusions-and-open-questions)

## 1. What tokenization means for code

LLMs generally process text as a sequence of tokens rather than directly as characters, words, or abstract syntax trees.

A tokenizer maps text into token IDs. Depending on the tokenizer, a token might represent a complete keyword, a common identifier, a punctuation mark, part of an identifier, or a sequence of characters.

For example, the following code:

```text
total = price + tax
```

might be split into tokens resembling:

```json
["total", " =", " price", " +", " tax"]
```

This is illustrative, not the guaranteed output of any particular model's tokenizer. Another tokenizer might split the identifiers or punctuation differently.

### Three levels of representation

1. **Source text** — `node_17 [x, y] -> [result]`
2. **Token sequence** — A tokenizer-specific sequence of token IDs; identifiers and punctuation may occupy one or several tokens.
3. **Model prediction** — The model predicts successive tokens conditioned on the preceding context and its learned representations.

The important consequence is that two syntaxes expressing the same computation can have different token costs and different generation characteristics.

### Why tokenization matters

- **Context-window consumption:** More tokens for the same program leave less context available for requirements, examples, documentation, and surrounding code.
- **Generation cost and latency:** Longer outputs generally require more token-generation steps.
- **Identifier consistency:** Unusual names or repeated fragments may tokenize inefficiently, although token count alone does not determine whether the model remembers them correctly.
- **Structural learning:** Common, repeated syntax patterns may be easier for a model to continue because it has encountered similar patterns during training.
- **Error opportunities:** Every generated token is another opportunity for a mistake, but the risk depends on the grammar and decoding process—not merely the number of tokens.

Tokenization is therefore one component of a larger problem: designing representations that align well with how models predict structured sequences.

## 2. Why deeply nested syntax can be harder to generate

Consider a simple dataflow graph containing two nodes and one connection.

### Representation A: Nested JSON

```json
{
  "nodes": [
    {
      "id": "add_1",
      "type": "Add",
      "inputs": {
        "a": {
          "value": 10
        },
        "b": {
          "value": 20
        }
      },
      "outputs": {
        "result": {
          "type": "Number"
        }
      }
    }
  ],
  "connections": []
}
```

### Representation B: Flat, line-oriented IR

```text
node add_1: Add
 input a = 10
 input b = 20
 output result: Number
```

The flat representation makes the main semantic unit—the node—explicit. Each line has a relatively predictable purpose, and a reader can inspect or modify one property without navigating several layers of nested objects.

| Property | Nested JSON | Flat line-oriented IR |
| --- | --- | --- |
| Structural delimiters | Many braces, brackets, and commas | Few delimiters |
| Local edits | May require editing nested objects | Often limited to one line |
| Visual scanning | Requires navigating object hierarchy | Easy to scan line by line |
| Error localization | Can be difficult when delimiters are mismatched | Often localized to one record |
| Partial generation | May leave unfinished objects or arrays | Can end after a complete record |
| Expressiveness | Naturally supports nested data | May need explicit references for complex structures |

These are design tendencies, not universal guarantees. JSON is widely represented in training data, and modern models can generate it very effectively. A flat format can also be difficult if it has ambiguous delimiters, inconsistent conventions, or numerous special cases.

The relevant comparison is not simply JSON versus flat text. It is how much structural work the model must perform to express a given semantic operation.

### A third representation: Explicit graph edges

For a visual programming language, a graph-oriented IR could be even more compact:

```text
node input_1: Number = 10
node input_2: Number = 20
node add_1: Add

edge input_1.value -> add_1.a
edge input_2.value -> add_1.b
edge add_1.result -> output_1.value
```

This representation separates node declarations from connections. It also makes graph topology explicit rather than hiding it inside nested input and output objects.

The syntax is regular enough to parse line by line, while identifiers provide stable references to individual nodes and ports.

There are trade-offs: references must resolve correctly, port names must exist, and the format needs rules for forward references, duplicate IDs, and type mismatches. A representation that is easy to generate syntactically can still be semantically invalid.

## 3. Syntax predictability: what makes a format AI-friendly?

Syntax predictability describes how consistently a model can anticipate the valid structure and continuation of a representation.

A predictable syntax typically has the following properties.

1. **Repeated structural patterns** — Similar entities follow the same template. A node declaration always uses the same field order, connection syntax, and termination convention. The model can reuse a familiar pattern instead of inventing a new arrangement for every entity.
2. **Locality of meaning** — Most of a line's meaning can be understood without examining distant parts of the document. For example, `edge add_1.result -> output_1.value` communicates one connection in isolation.
3. **Minimal structural ambiguity** — Separators, quoting, escaping, comments, and multiline values have clear rules. A parser should not need to guess whether a character is syntax or data.
4. **Canonical representation** — The same semantic structure has one preferred textual form. Stable field order, normalized identifiers, and consistent quoting reduce unnecessary variation during generation and comparison.
5. **Explicit constraints** — Required fields, valid references, types, and permissible operations are defined formally. The model can be guided by these rules, and a validator can enforce them independently.

An especially useful principle is regularity without unnecessary verbosity. A format should make common cases easy and uniform, while providing an explicit, predictable mechanism for exceptional cases.

## 4. Token efficiency is not the same as syntactic simplicity

A critical distinction for this research is that the number of characters, the number of tokens, the complexity of the grammar, and the reliability of the generated result are separate variables.

Consider these equivalent-looking declarations:

```text
node calculate_total: Add
```

```json
{"kind":"node","name":"calculate_total","operation":"Add"}
```

The line-oriented declaration is shorter in characters. It may also use fewer tokens, but that must be measured with the tokenizer of the target model.

A tokenizer may encode frequently occurring JSON fragments efficiently. Conversely, an unusual domain-specific operator or identifier may be split into many tokens. There is no general rule that every flat syntax uses fewer tokens than JSON.

### Four quantities worth measuring

| Quantity | What it measures | Why it matters |
| --- | --- | --- |
| Token count | Encoded length under a specific tokenizer | Context usage and generation cost |
| Structural complexity | Nesting, grammar rules, and structural dependencies | How much syntax the model must manage |
| Continuation predictability | How constrained the next valid part is, given a prefix | How readily the model can continue a partial artifact |
| Validity and correctness | Whether output parses and expresses the intended result | Actual usefulness of generated artifacts |

These measures can move in different directions. For example, a highly compressed syntax may save tokens but require the model to remember many conventions. A more explicit syntax may use more tokens but make its meaning and expected continuation clearer.

### A useful research hypothesis

A promising hypothesis to test is:

> For structured artifacts of comparable semantic complexity, a canonical, line-oriented representation with explicit references and locally regular grammar will improve editability and syntactic reliability relative to a deeply nested representation, even when the two representations have similar token counts.

This formulation is more precise and falsifiable than claiming that flat syntax is always superior. It also allows token efficiency and reliability to be evaluated independently.

## 5. How the model predicts syntax

An autoregressive LLM generates a sequence incrementally. At each step, it estimates a probability distribution over possible next tokens, conditioned on the prompt and the tokens already generated.

For example, given:

```text
node add_1: Add
```

the next continuation might begin a new node, specify a property, or finish the current declaration, depending on the grammar.

A format can improve predictability when the preceding context strongly indicates the next structural element. Consistent record templates help because the model can learn recurring sequences and their associations.

However, the model does not automatically know which continuations are formally legal. It can assign probability to an invalid field name, nonexistent node ID, mismatched port, or malformed delimiter.

Research on grammar-constrained generation demonstrates that a model can be paired with a parser or automaton that restricts the available continuations to those that preserve grammatical validity. The challenge includes aligning character-level grammar rules with tokenizers whose tokens may span multiple characters or structural boundaries.

*Source: Google Research (+1 more)*

This gives us two complementary strategies:

- **Design for predictability:** Make the common valid continuation easy for the model to learn.
- **Enforce validity:** Use a parser, grammar constraint, type checker, or semantic validator to reject invalid continuations or repair invalid output.

A well-designed language should benefit from both.

## 6. Why grammar validity is not enough

A central finding in recent programming-language research is that syntactic correctness represents only one layer of program correctness.

A graph description can parse perfectly while still containing:

- References to nonexistent nodes.
- Connections to nonexistent ports.
- Type mismatches between connected ports.
- Cycles where the execution model prohibits cycles.
- Valid operations wired together in a way that produces the wrong result.

This suggests a hierarchy of constraints.

**Layer 1 — Lexical validity**

Are identifiers, strings, and tokens well-formed?

**Layer 2 — Syntactic validity**

Does the text conform to the language grammar?

**Layer 3 — Structural validity**

Do node IDs, ports, and references resolve correctly?

**Layer 4 — Type and semantic validity**

Are connections type-safe and operations meaningful?

**Layer 5 — Behavioral correctness**

Does the graph actually perform the intended computation?

These layers are not always strictly sequential—some checks can happen together—but the distinction is valuable for language design.

A 2025 paper, Type-Constrained Code Generation with Language Models, demonstrates the potential of enforcing type constraints in addition to syntax. Its evaluation reports substantial reductions in compilation errors and improvements in functional correctness across several code-generation tasks.

*Source: DOI (+1 more)*

The implication for an AI-friendly intermediate representation is important: the ideal format should not merely be easy to generate; it should also be easy to validate.

## 7. Designing a token-efficient graph IR

For a graph-based visual programming language, the recommended approach is to explore a compact, line-oriented representation with explicit node and edge declarations.

One possible design is outlined below.

```text
graph Calculator

node n1: Constant
 value = 10

node n2: Constant
 value = 20

node n3: Add

edge n1.value -> n3.a
edge n2.value -> n3.b

output result = n3.result
```

This design has several useful properties:

- Each node has a stable identifier.
- Node type and configuration are explicit.
- Connections are first-class declarations.
- Graph structure is independent of visual layout.
- A node or edge can be added, removed, or replaced locally.
- A parser can process declarations incrementally.

The representation is a proposal for investigation, not an empirically proven optimal syntax.

### Design decisions worth investigating

| Design choice | Recommended starting point | Reason |
| --- | --- | --- |
| Record boundaries | One declaration per line | Simplifies parsing and local edits |
| Node identity | Explicit, stable IDs | Reduces ambiguity during graph edits |
| Connection syntax | `source.port -> target.port` | Makes direction and endpoints visible |
| Field ordering | Canonical ordering | Reduces representational variation |
| Types | Named types or explicit annotations | Makes compatibility checks easier |
| Optional fields | Omit defaults where unambiguous | Avoids redundant output |
| Complex values | A defined expression or literal grammar | Avoids reinventing nested syntax for every feature |
| Comments | Clearly distinguish comments from semantic data | Supports explanations without changing graph meaning |

One subtle issue is the use of abbreviated identifiers. Short IDs can reduce token usage, but identifiers such as `n1` and `n2` are not necessarily more predictable than meaningful names such as `player_speed` or `multiply`. They can also make the graph harder to understand.

A good compromise is stable IDs for identity and descriptive names for human-facing labels.

### Avoid the opposite extreme: overcompression

Consider:

```text
N1 C 10
N2 C 20
N3 A
E N1.v N3.a
E N2.v N3.b
```

This is compact, but the meaning of `C`, `A`, `v`, and `E` must be learned or looked up. The syntax may save tokens at the expense of interpretability, debuggability, and reliable generalization.

The design goal should be to minimize total cost, not just character count:

$$
\text{Total cost} = \text{generation cost} +\text{validation cost} +\text{repair cost} +\text{interpretation cost}
$$

This is a conceptual model rather than a standardized metric, but it helps explain why the shortest syntax is not necessarily the best.

## 8. Bidirectional editing and partial generation

A particularly interesting application is a graph editor that synchronizes a visual graph with a textual representation.

In that setting, the representation needs to support more than initial generation. It must also survive repeated edits by humans and models.

Suppose an LLM is asked to add a multiplication node between two existing nodes. With explicit edge declarations, the edit might be:

```text
node n4: Multiply
edge n3.result -> n4.a
edge n2.value -> n4.b
```

A graph-aware editing system could interpret this as a localized change rather than regenerate the entire artifact.

This is useful because regeneration creates opportunities for accidental changes to unrelated nodes, IDs, connections, or metadata.

A robust design would distinguish three kinds of state:

1. **Semantic state:** nodes, ports, values, and connections.
2. **Presentation state:** positions, colors, grouping, and visual layout.
3. **Editing state:** comments, formatting, partial declarations, and perhaps stable source locations.

Separating these concerns lets the graph editor update presentation details without rewriting semantic declarations unnecessarily. It also lets an LLM modify the computation without having to reproduce every coordinate and styling attribute.

For synchronization, the text representation should have a well-defined canonical form, and the system should maintain a mapping between text declarations and graph entities. Stable IDs are especially useful here.

One caution: canonical formatting alone does not solve concurrent editing conflicts. If the user moves a node while the LLM edits its connections, the system needs explicit conflict-resolution and change-tracking rules.

## 9. How to test the hypothesis scientifically

The strongest research contribution would be an empirical comparison of different syntaxes rather than an argument based solely on visual simplicity.

The recommendation is to test at least four representations of the same graph tasks.

## Experimental design

**A. Nested JSON**

A conventional structured-data baseline.

**B. Flat key-value records**

Explicit fields with one record per line.

**C. Graph-oriented IR**

Node declarations and explicit edge statements.

**D. Compact custom DSL**

A deliberately concise syntax designed for AI generation.

All four formats should encode the same underlying graph, types, constraints, and operations. Otherwise, the experiment would confound syntax with task difficulty.

### Metrics

| Metric | Measurement |
| --- | --- |
| Token efficiency | Median input and output tokens per equivalent graph |
| Parse success | Percentage of outputs accepted by the parser |
| Structural validity | Percentage with valid IDs, ports, and references |
| Type validity | Percentage passing the same type checker |
| Semantic correctness | Percentage producing the expected graph behavior |
| Edit locality | Number of unrelated declarations changed during an edit |
| Repair burden | Tokens or edit operations needed to fix invalid outputs |
| Task completion | Percentage of requested graph modifications completed correctly |
| Latency and cost | Generation time and inference cost under comparable conditions |

Use the actual tokenizer for each evaluated model. Report both raw token counts and quality outcomes, since a format may be compact but unreliable or verbose but reliable.

### Experiments that would be especially revealing

Experiment 1: Initial generation. Generate graphs from natural-language requirements, ranging from simple arithmetic graphs to larger workflows.

Experiment 2: Targeted editing. Start from an existing graph and ask the model to modify one node or connection. Measure whether unrelated declarations change.

Experiment 3: Partial completion. Give the model a valid prefix ending at different points in a declaration. Measure the rate at which it completes the structure correctly.

Experiment 4: Error recovery. Introduce missing references, invalid ports, or malformed records and measure how well the model repairs them.

Experiment 5: Scale. Increase graph size and connectivity to see whether performance degrades as dependencies grow.

Experiment 6: Token budget. Compare representations under the same maximum generation budget and report both success rates and completion rates.

To avoid misleading results, use the same task instances, model versions, decoding settings, and validation rules across conditions. Run multiple generations per task and report uncertainty, not just a single success percentage.

An important control is familiarity: a model may already have seen extensive JSON examples during training. A custom DSL could initially perform worse simply because it is unfamiliar. Testing both with and without concise grammar documentation—and, where feasible, training examples—would help distinguish intrinsic syntax properties from learned familiarity.

## 10. Related research and further reading

The following works provide a useful starting point for grounding the research in formal methods and empirical results.

- [Automata-based Constraints for Language Model Decoding](https://research.google/pubs/automata-based-constraints-for-language-model-decoding/) — *Terry Koo, Frederick Liu, and Luheng He · 2024.* Explores automata-based methods for constraining LLM output to formal languages, including structured data and schema-guided generation. Particularly relevant to syntax enforcement and tokenizer/grammar alignment. *(Google Research).*
- [Grammar-Aligned Decoding](https://mlanthology.org/neurips/2024/park2024neurips-grammaraligned/) — *NeurIPS 2024.* Studies how grammar-constrained decoding can distort the language model's original probability distribution. Important because enforcing validity can sometimes affect output quality. *(ML Anthology).*
- [Type-Constrained Code Generation with Language Models](https://doi.org/10.1145/3729274) — *Niels Mündler and colleagues · PLDI 2025.* Extends constrained generation from syntax to type correctness. Relevant to the distinction between easy-to-parse syntax and semantically valid graph connections. *(DOI (+1 more)).*
- [CRANE: Reasoning with Constrained LLM Generation](https://proceedings.mlr.press/v267/banerjee25a.html) — *ICML 2025.* Investigates the relationship between output constraints and reasoning capabilities. Useful for evaluating whether an overly restrictive grammar limits the model's ability to construct a correct solution. *(Proceedings of Machine Learning Research).*

## 11. Conclusions and open questions

LLM Tokenization and Syntax Predictability is best treated as a problem at the intersection of language design, information representation, probabilistic modeling, and formal verification.

The most promising principles are:

1. Measure tokenization rather than guessing. Character count is not a reliable proxy for token count.
2. Prefer regular, canonical syntax. Repeated patterns and predictable record boundaries are valuable.
3. Make dependencies explicit. Stable IDs, typed ports, and explicit edges are particularly useful in graph-based IRs.
4. Optimize for edits, not just generation. Local modifications and incremental parsing matter in practical AI-assisted tools.
5. Separate syntax from semantics. A valid parse does not guarantee a valid graph or correct computation.
6. Use enforcement where appropriate. Parsers, type checkers, constrained decoding, and validators can complement syntax design.
7. Evaluate competing hypotheses empirically. The best representation may vary by model, task, artifact size, and training familiarity.

The most interesting open question is whether there exists a general class of AI-friendly languages whose structural regularity, token efficiency, and semantic explicitness consistently improve generation and editing across different models—not merely one custom syntax that works well for one benchmark.

That question is directly testable and could lead to useful design principles for programming languages, markup formats, configuration languages, and intermediate representations intended for human–LLM collaboration.

The hypothesis should be tested empirically across models and tasks, measuring token use, syntactic validity, semantic correctness, edit locality, and repair effort rather than assuming one syntax is universally superior.
