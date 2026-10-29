# Intermediate Representations

> **"Intermediate form" redirects here.** For the use of the term in biology, see [Transitional fossil](https://en.wikipedia.org/wiki/Transitional_fossil).

An **intermediate representation** (IR) is the data structure or code used internally by a compiler or virtual machine to represent source code. An IR is designed to be conducive to further processing, such as optimization and translation. A "good" IR must be accurate – capable of representing the source code without loss of information – and independent of any particular source or target language. An IR may take one of several forms: an in-memory data structure, or a special tuple- or stack-based code readable by the program. In the latter case it is also called an intermediate language.

A canonical example is found in most modern compilers. For example, the CPython interpreter transforms the linear human-readable text representing a program into an intermediate graph structure that allows flow analysis and re-arrangement before execution. Use of an intermediate representation such as this allows compiler systems like the GNU Compiler Collection and LLVM to be used by many different source languages to generate code for many different target architectures.

## Intermediate language

> *This section needs more citations. Please help improve this section by adding citations to reliable sources. Unsourced material may be challenged and removed. (February 2025)*

An intermediate language is the language of an abstract machine designed to aid in the analysis of computer programs. The term comes from their use in compilers, where the source code of a program is translated into a form more suitable for code-improving transformations before being used to generate object or machine code for a target machine. The design of an intermediate language typically differs from that of a practical machine language in three fundamental ways:

- Each instruction represents exactly one fundamental operation; e.g. "shift-add" addressing modes common in microprocessors are not present.
- Control flow information may not be included in the instruction set.
- The number of processor registers available may be large, even limitless.

A popular format for intermediate languages is three-address code.

The term is also used to refer to languages used as intermediates by some high-level programming languages which do not output object or machine code themselves, but output the intermediate language only. This intermediate language is submitted to a compiler for such language, which then outputs finished object or machine code. This is usually done to ease the process of optimization or to increase portability by using an intermediate language that has compilers for many processors and operating systems, such as C. Languages used for this fall in complexity between high-level languages and low-level languages, such as assembly languages.

## Languages

Though not explicitly designed as an intermediate language, C's nature as an abstraction of assembly and its ubiquity as the de facto system language in Unix-like and other operating systems has made it a popular intermediate language: Eiffel, Sather, Esterel, some dialects of Lisp (Lush, Gambit), Squeak's Smalltalk-subset Slang, Nim, Cython, SystemTap, Vala, V, and others make use of C as an intermediate language. Variants of C have been designed to provide C's features as a portable assembly language, including C-- and the C Intermediate Language.

Any language targeting a virtual machine or p-code machine can be considered an intermediate language:

- Java bytecode
- Microsoft's Common Intermediate Language is an intermediate language designed to be shared by all compilers for the .NET Framework, before static or dynamic compilation to machine code.
- While most intermediate languages are designed to support statically typed languages, the Parrot intermediate representation is designed to support dynamically typed languages—initially Perl and Python.
- TIMI is used by compilers on the IBM i platform.
- O-code for BCPL
- MATLAB precompiled code
- Microsoft P-Code
- Pascal p-code

The GNU Compiler Collection (GCC) uses several intermediate languages internally to simplify portability and cross-compilation. Among these languages are:

- the historical Register Transfer Language (RTL)
- the tree language GENERIC
- the SSA-based GIMPLE. (Lower-level than GENERIC; input for most optimizers; has a compact "bytecode" notation.)

GCC supports generating these IRs, as a final target:

- HSA Intermediate Layer
- LLVM Intermediate Representation (converted from GIMPLE in the now-defunct llvm-gcc which uses LLVM optimizers and codegen)

The LLVM compiler framework is based on the LLVM IR intermediate language, of which the compact, binary serialized representation is also referred to as "bitcode" and has been productized by Apple. Like GIMPLE Bytecode, LLVM Bitcode is useful in link-time optimization. Like GCC, LLVM also targets some IRs meant for direct distribution, including Google's PNaCl IR and SPIR. A further development within LLVM is the use of Multi-Level Intermediate Representation (MLIR) with the potential to generate code for different heterogeneous targets, and to combine the outputs of different compilers.

The ILOC intermediate language is used in classes on compiler design as a simple target language.

## Other

Static analysis tools often use an intermediate representation. For instance, Radare2 is a toolbox for binary files analysis and reverse-engineering. It uses the intermediate languages ESIL and REIL to analyze binary files.

## See also

- [Abstract syntax tree](https://en.wikipedia.org/wiki/Abstract_syntax_tree) — Tree representation of the abstract syntactic structure of source code
- [BURS](https://en.wikipedia.org/wiki/BURS)
- [Bytecode](https://en.wikipedia.org/wiki/Bytecode) — Instruction set designed to be run by a software interpreter
- [Graph rewriting](https://en.wikipedia.org/wiki/Graph_rewriting) — Creating a new graph from an existing graph
- [Interlingual machine translation](https://en.wikipedia.org/wiki/Interlingual_machine_translation) — Type of machine translation
- [Pivot language](https://en.wikipedia.org/wiki/Pivot_language) — Intermediary language between different languages
- [Source-to-source compiler](https://en.wikipedia.org/wiki/Source-to-source_compiler) — Translator of computer source code
- [Symbol table](https://en.wikipedia.org/wiki/Symbol_table) — Data structure used by a language translator such as a compiler or interpreter
- [Term rewriting](https://en.wikipedia.org/wiki/Term_rewriting) — Replacing subterm in a formula with another term
- [UNCOL](https://en.wikipedia.org/wiki/UNCOL)

## References

1. Walker, David. "CS320: Compilers: Intermediate Representation" (Lecture slides). Retrieved 12 February 2016.
2. Chow, Fred (22 November 2013). "The Challenge of Cross-language Interoperability". *ACM Queue*. 11 (10). Retrieved 12 February 2016.
3. Toal, Ray. "Intermediate Representations". Retrieved 12 February 2016.
4. "Bitcode (iOS, watchOS)". Hacker News. 10 June 2015. Retrieved 17 June 2015.
5. "LLVM Bitcode File Format". llvm.org. Retrieved 17 June 2015.
6. "MLIR".
7. "An ILOC Simulator" (Archived 2009-05-07 at the Wayback Machine) by W. A. Barrett 2007, paraphrasing Keith Cooper and Linda Torczon, *Engineering a Compiler*, Morgan Kaufmann, 2004. ISBN 1-55860-698-X.
8. "CISC 471 Compiler Design" by Uli Kremer.
9. Radare2 Contributors. "ESIL". Radare2 Project. Archived from the original on 18 August 2015. Retrieved 17 June 2015.
10. Sebastian Porst (7 March 2010). "The REIL language – Part I". zynamics.com. Retrieved 17 June 2015.

## External links

- [The Stanford SUIF Group](https://suif.stanford.edu/)

---

**Source:** https://en.wikipedia.org/wiki/Intermediate_representation

## Intermediate Representations: Design Principles and Implementation

An intermediate representation (IR) is one of the central abstractions in compiler design. It is the form in which a compiler, interpreter, optimizer, or analysis tool expresses a program so that it can reason about the program independently of the exact syntax in which a human wrote it or the exact machine on which it will run.

The foundational material introduces intermediate languages, three-address code, virtual-machine bytecode, GCC, LLVM IR, MLIR, and IRs for static analysis and reverse engineering. The following sections examine design principles, representation families, compiler pipelines, optimization techniques, and trade-offs.

One important distinction: the article gives examples of IRs, but IR is a broader concept than a single intermediate language. It can be a syntax tree, a graph of operations, a control-flow graph, a typed dataflow representation, bytecode, or a collection of related representations used at different stages of a toolchain.&#x20;

Intermediate_representation.md

### 1. Why intermediate representations exist

Imagine compiling three programming languages—Rust, Swift, and a hypothetical language called Nova—to three processor architectures: x86-64, ARM64, and WebAssembly.

Without a shared intermediate representation, each source language may need its own compiler backend for each target. That's potentially nine language-to-target combinations.

With a shared IR, each source language can translate into the IR, and each target can have a backend that translates the IR into its target instructions.

Source languages

Rust · Swift · Nova

Frontends

Parsing · type checking · lowering

Shared intermediate representation

Common semantics · analysis · optimization

Backends

Instruction selection · register allocation · code generation

Targets

x86-64 · ARM64 · WebAssembly

Conceptual architecture. Real compilers may use several IRs, and not every frontend can target every IR or backend.

If there are \\(m\\) source languages and \\(n\\) targets, a direct implementation may require roughly \\(m \times n\\) translation paths. A shared IR can reduce this toward \\(m+n\\) components: one frontend per language and one backend per target.

This is an architectural simplification, not a guarantee of lower total engineering effort. The IR must express enough of each source language's semantics and enough of each target's capabilities to make the shared system useful.

#### The five principal benefits

- Separation of concerns: language-specific syntax and type rules can be handled separately from processor-specific code generation.
- Optimization: the compiler can apply transformations to a representation designed for analysis rather than human readability.
- Portability: a common IR can support multiple processors, operating systems, or execution environments.
- Analysis: explicit data dependencies and control flow make it easier to prove properties, detect errors, or understand behavior.
- Reuse: multiple frontends, optimizers, analyzers, and backends can share infrastructure.

IR is therefore not merely a temporary format. It is an architectural boundary between different kinds of reasoning about a program.

### 2. What makes a good IR?

The Wikipedia article emphasizes accuracy, further processing, and independence from particular source and target languages. These are useful starting criteria, but they interact in subtle ways.&#x20;

Intermediate_representation.md

#### Semantic fidelity

An IR must preserve the meaning of the program, including details that affect observable behavior.

For example:

```
int x = a + b;
```

A compiler cannot necessarily replace this operation with arbitrary mathematical addition. Depending on the source language, integer overflow might be undefined, wrapping, trapping, or otherwise constrained. Floating-point arithmetic introduces additional issues involving rounding, NaNs, signed zero, and evaluation order.

A transformation is correct only when the IR's semantics justify it.

#### Analyzability

The representation should make important program properties explicit.

If an IR exposes which instruction defines each value, which operations consume it, and which blocks can reach others, an optimizer can perform dataflow analysis without reconstructing all of that information from source syntax.

#### Transformability

Compiler passes should be able to modify the program without repeatedly rebuilding an entire representation or accidentally violating its invariants.

For example, a compiler may replace an addition with a constant, remove an unused computation, or change a branch. The IR must support these operations and provide a way to check that the resulting program remains structurally valid.

#### Appropriate abstraction level

An IR that is too high-level may hide the details needed for low-level optimization. An IR that is too low-level may discard information needed for high-level optimization.

Consider the expression:

```
matrix_multiply(A, B)
```

A high-level IR could preserve this as a matrix multiplication operation. A lower-level IR might represent loops and indexing explicitly. A machine-oriented IR might represent loads, multiply-add instructions, and register assignments.

The higher-level representation makes it easier to recognize the mathematical operation. The lower-level representations make it easier to reason about memory layout and hardware instructions.

#### Efficiency and stability

An IR must be practical to construct, store, traverse, and transform. Large programs can produce millions of operations, so representation choices influence compile time and memory usage.

For IRs intended as public interchange formats, another criterion matters: versioning and compatibility. A format used across compiler versions or between independently developed tools needs explicit rules for evolution, verification, and interpretation.

There is no single optimal IR. The right design depends on which properties it must preserve, which analyses it must enable, and where it sits in the compilation pipeline.

### 3. The major families of intermediate representation

IRs can be classified along several dimensions. These categories overlap: an IR can be both graph-based and SSA-based, or both typed and designed for a virtual machine.

#### 3.1 Abstract syntax trees

An abstract syntax tree (AST) represents the grammatical structure of a program while omitting many details of its concrete spelling.

For example:

```
result = a + b * c;
```

can be represented as:

Assignment

result

Add

a

Multiply

b

c

The tree captures operator precedence: multiplication occurs inside the addition.

Strengths: ASTs preserve source-level structure and are useful for type checking, diagnostics, refactoring, and transformations that depend on language constructs.

Limitations: Complex expressions and nested control structures can make dataflow analysis difficult. An AST alone does not necessarily make execution order, control-flow edges, or variable definitions explicit.

ASTs are often the first representation in a compiler, but they can also serve as an IR for tools such as linters, formatters, and source-to-source translators.

#### 3.2 Three-address code

Three-address code (TAC) decomposes expressions into simple operations, usually with no more than three named addresses or operands per instruction. The traditional instruction forms include assignments, unary operations, binary operations, and jumps.

Consider:

```
x = (a + b) * (c - d)
```

Its TAC representation could be:

```
t1 = a + b
t2 = c - d
t3 = t1 * t2
x  = t3
```

The temporary variables make intermediate computations explicit. This simplifies constant propagation, common-subexpression elimination, and dependency analysis.

The name does not mean every instruction must literally have three operands. A binary operation commonly has two input operands and one destination; calls and other special operations may have different forms.

TAC is a family of representations rather than one rigid specification. It can be implemented using instruction lists, quadruples, triples, or a graph of operations.

#### 3.3 Control-flow graphs

A control-flow graph (CFG) represents a program as a graph in which nodes are usually basic blocks and directed edges indicate possible transfers of control.

A basic block is a sequence of instructions with a single entry point and no internal branching.

For example:

```
if (x > 0)
    y = x + 1;
else
    y = x - 1;

return y;
```

can be organized into four blocks:

Entry

`x > 0?`

True

`y = x + 1`

False

`y = x - 1`

Merge

`return y`

Schematic CFG; the merge block receives control from either branch.

A CFG supports analyses such as:

- Reachability and unreachable-code detection.
- Dominance: whether every path to a block passes through another block.
- Loop identification and loop-invariant code motion.
- Liveness analysis and register allocation.
- Dataflow propagation across branches.

A CFG describes where execution can go. It does not, by itself, fully describe the values flowing along each edge.

#### 3.4 Static single assignment form (SSA)

Static single assignment (SSA) is one of the most influential IR design techniques. Its central rule is that each SSA value is defined exactly once.

Ordinary code may assign to the same variable multiple times:

```
x = 10
x = x + 5
x = x * 2
```

In SSA form, these become distinct definitions:

```
x1 = 10
x2 = x1 + 5
x3 = x2 * 2
```

The benefit is that each use refers to a specific definition. This simplifies reasoning about dependencies, propagation of constants, and elimination of redundant computations.

##### What happens when control flow merges?

Consider:

```
if (condition)
    x = 10;
else
    x = 20;

use(x);
```

The compiler needs to represent which version of `x` reaches `use`. In a classic SSA representation with explicit merge functions, it can use a \\(\phi\\) (phi) function:

```
then:
    x1 = 10
    goto merge

else:
    x2 = 20
    goto merge

merge:
    x3 = φ(x1, x2)
    use(x3)
```

The \\(\phi\\) function selects the value associated with the predecessor block from which control arrived. It is a representation of a control-flow-dependent choice, not necessarily a machine instruction.

SSA is particularly useful for sparse conditional constant propagation, dead-code elimination, and many forms of dataflow analysis.

LLVM IR is SSA-based, and GCC uses an SSA form of GIMPLE for important optimization passes.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://llvm.org\&sz=32)

LLVM+1

One subtlety: SSA makes ordinary value dependencies explicit, but it does not automatically eliminate all complications caused by memory. If two pointers may refer to the same location, stores and loads still require alias analysis and memory-dependence reasoning.

#### 3.5 Stack-based and register-based bytecode

A virtual-machine instruction set is often an IR intended for execution by an interpreter or for just-in-time compilation.

A stack-based instruction sequence might calculate `a + b` as:

```
LOAD a
LOAD b
ADD
STORE result
```

The `ADD` instruction consumes values from an evaluation stack.

A register-based sequence might instead look like:

```
LOAD r1, a
LOAD r2, b
ADD  r3, r1, r2
STORE result, r3
```

Here, the operands and destination are named explicitly.

| Property            | Stack-based                                        | Register-based                                  |
| ------------------- | -------------------------------------------------- | ----------------------------------------------- |
| Operand naming      | Often implicit in stack position                   | Explicit registers or virtual registers         |
| Instruction size    | Often compact                                      | May require more operand fields                 |
| Dataflow visibility | Must often be reconstructed from stack effects     | Usually more explicit                           |
| Execution           | Natural for a simple interpreter                   | Natural for many JIT optimizers                 |
| Optimization        | Possible, but stack effects complicate some passes | Often convenient for dependency-oriented passes |

These are tendencies, not universal performance laws. Bytecode format, interpreter implementation, JIT strategy, and workload all matter.

Examples include Java bytecode, .NET's Common Intermediate Language (CIL), and Pascal p-code. As your source notes, these can be considered intermediate languages because they sit between a high-level language and native execution.&#x20;

Intermediate_representation.md

#### 3.6 Dataflow graphs and graph IRs

In a dataflow representation, operations are connected according to their inputs and outputs.

For example:

```
       a ──┐
           ├─ Add ──┐
       b ──┘        │
                    ├─ Multiply ── result
       c ───────────┘
```

This represents `result = (a + b) * c`.

Unlike a simple instruction sequence, the graph directly exposes the dependency between the addition and multiplication. Independent operations may be scheduled in parallel, subject to control, memory, and other semantic constraints.

Dataflow graphs are especially useful for:

- Tensor and neural-network computation.
- Hardware synthesis and circuit generation.
- Vectorization and parallel scheduling.
- Dependency-driven transformations.

A graph does not necessarily mean the program is free of control flow. Real dataflow systems may have conditional execution, loops, mutable state, and memory effects. Some use acyclic graphs for individual computations and separate mechanisms for loops and control.

MLIR, discussed below, supports dataflow-oriented representations alongside conventional control flow.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://mlir.llvm.org\&sz=32)

MLIR+1

#### 3.7 Structured, domain-specific, and polyhedral IRs

Some operations are easier to optimize when the IR preserves more structure than ordinary low-level instructions.

For example, a tensor-level operation:

```
C = matmul(A, B)
```

communicates much more than a sequence of scalar multiplications and additions. It tells an optimizer that the computation is matrix multiplication, potentially enabling tiling, fusion, parallelization, and mapping to specialized accelerator instructions.

Similarly, a structured loop representation can make loop bounds, iteration spaces, and array accesses explicit. A polyhedral representation models certain loop computations with mathematical sets and affine relationships. This enables transformations such as loop interchange and tiling when the necessary conditions hold.

The trade-off is that high-level operations require precise semantics and suitable lowering rules. Once a matrix multiplication has been expanded into thousands of low-level instructions, recovering the original operation may be difficult or impossible.

This leads to a general principle:

Preserve useful semantic structure until the compiler has finished exploiting it.

### 4. Lowering: moving between levels of abstraction

A modern compiler often uses several IRs rather than trying to make one representation serve every purpose.

Lowering is the transformation of a program into a representation that exposes lower-level implementation details.

Level 1 — Source-oriented IR

Functions, classes, pattern matching, high-level types

Level 2 — Structured or domain-specific IR

Loops, tensors, vector operations, domain semantics

Level 3 — Low-level, target-independent IR

Explicit control flow, arithmetic, loads, stores, calls

Level 4 — Target-oriented IR

Machine-specific operations, calling conventions, register constraints

Machine code

Encoded instructions for the processor

This diagram is a conceptual hierarchy, not a mandatory sequence. A compiler can skip levels, move between related representations, or repeatedly alternate between optimization and lowering.

#### Example: lowering a loop

A source-level loop:

```
for (int i = 0; i < n; i++) {
    sum += a[i];
}
```

might first be represented as a structured loop operation. At a lower level, it could become explicit basic blocks:

```
entry:
    i = 0
    sum = 0
    goto header

header:
    if i < n goto body
    else goto exit

body:
    value = load a[i]
    sum = sum + value
    i = i + 1
    goto header

exit:
    return sum
```

An SSA version would distinguish each iteration's values and express the loop-carried dependencies using phi nodes or equivalent block arguments.

Later stages might:

1. Determine whether the array accesses are safe to vectorize.
2. Unroll the loop to reduce branch overhead.
3. Generate vector loads and additions where legal.
4. Assign virtual registers to physical registers.
5. Select the target's actual load, arithmetic, and branch instructions.

Each lowering step makes some implementation decisions explicit. It can also remove information, which is why the order of passes matters.

#### Lowering versus optimization

These are related but different activities.

- Lowering changes the abstraction level or representation.
- Optimization transforms a program to improve a chosen objective while preserving the required semantics.

A lowering pass may make an operation more explicit without making it faster. An optimization may change the implementation without changing the abstraction level.

In practice, one pass can do both.

### 5. Case studies: how real compiler systems use IRs

Your source article mentions GCC, LLVM, MLIR, and bytecode systems. Comparing them reveals that IR design is largely about deciding which information belongs at which stage.

#### 5.1 GCC: multiple representations for different jobs

The GNU Compiler Collection (GCC) uses three major intermediate representations: GENERIC, GIMPLE, and RTL.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://gcc.gnu.org\&sz=32)

GCC+1

GENERIC

A language-independent representation that serves as an interface between language frontends and subsequent compiler stages.

GIMPLE

A restricted, three-address-style representation used for many language- and target-independent optimizations. SSA form supports important dataflow analyses.

RTL — Register Transfer Language

A lower-level representation used for machine-oriented optimization and instruction generation.

Machine code

The important design decision is that GCC does not force all optimizations into one universal instruction set.

GIMPLE restricts the complexity of expressions and makes control flow and intermediate values easier to analyze. RTL provides a more machine-oriented view, allowing later stages to reason about the target's instruction patterns and register requirements.

This is a practical example of specialization: different representations make different operations convenient.

Official references: [GIMPLE documentation](https://gcc.gnu.org/onlinedocs/gccint/GIMPLE.html?utm_source=chatgpt.com) and [GCC tree SSA documentation](https://gcc.gnu.org/onlinedocs/gccint/Tree-SSA.html?utm_source=chatgpt.com).

#### 5.2 LLVM: a common low-level representation

LLVM centers on LLVM IR, an SSA-based, typed, low-level representation designed to support optimization and code generation across multiple source languages and targets.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://llvm.org\&sz=32)

LLVM+1

LLVM IR exists in three equivalent forms:

- In-memory representation: compiler data structures used by passes.
- Textual representation: a human-readable assembly-like language.
- Bitcode: a serialized binary form.

These are different encodings of the IR, not three different abstraction levels.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://llvm.org\&sz=32)

LLVM

For example, LLVM IR can explicitly express integer arithmetic:

```
define i32 @add(i32 %a, i32 %b) {
entry:
  %sum = add i32 %a, %b
  ret i32 %sum
}
```

The function accepts two 32-bit integers, adds them, and returns the result.

The IR is more explicit than C about types, values, and operations, but it does not commit to a particular physical register or machine instruction. Those decisions are made later.

LLVM also illustrates why a low-level IR still needs rich semantics. Integer arithmetic, pointer operations, memory accesses, atomic operations, and undefined behavior all affect which transformations are valid. The IR is not simply a list of arithmetic instructions.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://llvm.org\&sz=32)

LLVM+1

Official reference: [LLVM Language Reference Manual](https://llvm.org/docs/LangRef.html?utm_source=chatgpt.com).

#### 5.3 MLIR: multiple abstraction levels in one framework

MLIR takes a different approach. Instead of requiring every operation to be translated into one common, low-level instruction vocabulary as early as possible, it supports multiple abstraction levels within a shared IR framework.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://mlir.llvm.org\&sz=32)

MLIR+1

MLIR organizes extensible operations, types, and attributes into dialects. A dialect defines the vocabulary and semantics for a particular domain or compiler level.

Examples include:

- `arith` for arithmetic operations.
- `affine` for affine computations and structured iteration.
- `linalg` for linear algebra operations.
- `tensor` for tensor abstractions.
- `gpu` for GPU-related operations.
- `llvm` for LLVM-oriented constructs.

These dialects are documented in the [official MLIR dialect reference](https://mlir.llvm.org/docs/Dialects/?utm_source=chatgpt.com).&#x20;

[image](https://www.google.com/s2/favicons?domain=https://mlir.llvm.org\&sz=32)

MLIR

Why is this valuable?

Suppose a compiler is optimizing a neural-network operation. At a high level, it might represent a tensor contraction as a single operation. It can then fuse adjacent operations or choose an appropriate data layout before lowering the computation into loops, vectors, memory operations, and finally machine-oriented instructions.

If the compiler lowered everything immediately into scalar loads, stores, and arithmetic, many of these domain-level opportunities would become harder to recognize.

MLIR therefore treats the transition between abstraction levels as an important part of the compiler's architecture rather than an incidental conversion step.

Official references: [MLIR design rationale](https://mlir.llvm.org/docs/Rationale/Rationale/?utm_source=chatgpt.com) and [MLIR language reference](https://mlir.llvm.org/docs/LangRef/?utm_source=chatgpt.com).

#### Comparison

| Design dimension    | GCC                                                        | LLVM                                                         | MLIR                                                                       |
| ------------------- | ---------------------------------------------------------- | ------------------------------------------------------------ | -------------------------------------------------------------------------- |
| Core approach       | Multiple specialized IRs                                   | Shared low-level SSA IR                                      | Extensible framework for multiple abstraction levels                       |
| Main strength       | Separating general optimization from machine-oriented work | Broad optimization and target-code-generation infrastructure | Preserving and transforming domain-specific structure                      |
| Extensibility model | Compiler passes and representation-specific extensions     | Instructions, types, attributes, intrinsics, and metadata    | Dialects, operations, types, attributes, and interfaces                    |
| Typical role        | General-purpose native compilation                         | General-purpose native compilation and JIT infrastructure    | Domain-specific compilation, heterogeneous targets, and lowering pipelines |

These are architectural distinctions, not mutually exclusive capabilities. LLVM supports extensions, GCC supports multiple optimization levels, and MLIR can lower into LLVM IR. The systems overlap considerably in practice.

### 6. The central problem: preserving semantics

A compiler is not free to transform a program merely because the resulting instructions appear mathematically equivalent.

Consider:

```
int x = a * 2;
```

A compiler might replace multiplication with a left shift. Whether that is valid depends on the source and IR semantics, including the treatment of signed integers, overflow, and the precise shift operation.

Similarly, these two floating-point expressions are not always interchangeable:

```
(a + b) + c
a + (b + c)
```

Floating-point rounding means they can produce different results.

An IR specification must therefore define enough semantics to distinguish legal transformations from illegal ones.

#### The information-preservation problem

There is an important nuance in the claim that a good IR must represent source code “without loss of information.”

A compiler does not necessarily need to preserve every detail of the original source. Whitespace, comments, and some syntactic distinctions may be irrelevant to execution. Conversely, a source-oriented tool may need to preserve those details for diagnostics, debugging, or source reconstruction.

What matters is preserving the information required for the IR's purpose.

For an optimizing compiler, that includes observable behavior and relevant language guarantees. For a source transformation tool, it may also include source locations, symbol identities, and syntactic structure. For a reverse-engineering tool, it may include uncertainty about the recovered program's original types or control flow.

A useful way to think about an IR is as a contract between stages:

1. The producer guarantees that the representation faithfully describes the program.
2. The verifier checks structural and semantic constraints that can be validated.
3. An optimization pass states or relies on preconditions.
4. The pass must produce a result that preserves the required behavior.
5. The next stage interprets the result according to the same documented semantics.

This is why IR verification and compiler correctness are fundamental research topics, rather than merely implementation details.

#### Undefined behavior and optimization

Some source languages allow particular operations to have undefined behavior. An optimizer can use those language rules to justify transformations that would not be valid under a stricter semantics.

That means an IR may encode semantic facts that are not obvious from the source text alone. A seemingly harmless change in the definition of an IR instruction can therefore change the correctness of many optimizations.

LLVM's language reference explicitly distinguishes well-formed IR from text that is merely syntactically accepted, illustrating that parsing is not the same as establishing validity.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://llvm.org\&sz=32)

LLVM

#### How researchers check correctness

Two broad approaches are especially relevant:

- Compiler verification: prove that a compiler, or its important components, preserve semantics under stated assumptions.
- Translation validation: check whether a particular translation or optimization preserves the required semantics.

For example, Alive2 uses bounded translation validation for LLVM transformations. Its research demonstrates how automated checking can uncover incorrect optimizations and ambiguities in IR semantics.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://pldi21.sigplan.org\&sz=32)

PLDI 2021

The broader lesson is that an IR's design cannot be separated from its semantic specification. If the meaning of an operation is ambiguous, every optimizer that uses it inherits that ambiguity.

### 7. IRs beyond conventional compilation

Your Wikipedia article briefly mentions static analysis and reverse engineering. These applications broaden the concept considerably.&#x20;

Intermediate_representation.md

#### Static analysis

A static analyzer tries to infer properties of a program without executing it on every possible input.

Examples include detecting:

- Uninitialized variables.
- Possible null-pointer dereferences.
- Out-of-bounds memory accesses.
- Unreachable code.
- Security vulnerabilities.
- Violations of concurrency rules.

The choice of IR affects which facts can be inferred efficiently. An SSA-based representation is useful for tracing value definitions; a CFG is useful for reasoning about paths; and a memory model is needed to reason about loads, stores, and aliasing.

An analyzer may use a representation specifically designed for its analysis rather than the IR used by a production compiler.

#### Binary analysis and reverse engineering

When the input is already machine code, the task is almost the reverse of conventional compilation.

A tool may decode instructions into a normalized representation, construct a control-flow graph, and use an IR to compare or analyze instructions across architectures.

The REIL and ESIL representations mentioned in your source are examples associated with binary analysis.&#x20;

Intermediate_representation.md

An IR can make different processor instruction sets easier to compare, but it cannot magically recover information that compilation erased. Original variable names, source-level types, and high-level constructs may be unavailable or only partially recoverable.

#### Virtual machines and language interoperability

A virtual-machine IR can serve both as a compiler target and as a program-execution format.

Java bytecode and .NET CIL, for example, provide instruction sets and runtime conventions that decouple source languages from particular processors. Compilers can target a shared runtime environment, which then interprets or compiles the resulting code.

This introduces requirements that are not always central to a native compiler IR:

- Stable format definitions and versioning.
- Runtime type and calling conventions.
- Exception handling and object models.
- Verification of executable code.
- Compatibility between compilers and runtime implementations.

#### Hardware and machine learning

IRs are increasingly important in systems that compile computations to GPUs, specialized accelerators, and hardware circuits.

A domain-specific IR may represent tensor shapes, parallel iteration spaces, data layouts, synchronization, and memory movement. Those concepts can be essential for selecting an efficient hardware implementation.

MLIR's design explicitly targets this kind of multilevel compilation, including high-level dataflow graphs and lower-level target-specific operations.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://mlir.llvm.org\&sz=32)

MLIR+1

### 8. IR design trade-offs worth studying

The most interesting design questions arise when one desirable property conflicts with another.

#### Abstraction versus explicitness

High-level operations preserve intent and enable domain-specific optimization. Low-level operations expose implementation details and enable machine-oriented optimization.

Research question: Which information should be retained, and when should it be lowered?

#### Universality versus specialization

A universal IR reduces the number of separate translation systems. Specialized IRs can encode domain semantics and target capabilities more naturally.

Research question: How can one infrastructure support multiple domains without forcing them into an awkward common model?

#### Optimization freedom versus predictability

Strong semantic guarantees can make program behavior easier to reason about but constrain optimization. Permissive semantics may enable aggressive transformations while making correctness harder to understand.

Research question: How should an IR express undefined behavior, assumptions, effects, and numerical guarantees?

#### Extensibility versus interoperability

A framework that allows arbitrary new operations can support new languages and hardware. But independent tools need to agree on operation semantics before they can safely exchange or transform them.

Research question: How can extensible IRs establish trustworthy contracts between dialects, passes, and toolchains?

#### Information preservation versus compilation cost

Retaining debug information, high-level types, aliasing facts, and source mappings can improve optimization and diagnostics. Maintaining that information may increase memory usage and implementation complexity.

Research question: Which information has enough downstream value to justify its cost?

These tensions are more useful for research than treating ASTs, TAC, SSA, and bytecode as competing formats. They are often solutions to different problems, and many can coexist in a single compiler.

### 9. A practical framework for evaluating an IR

If you are designing an IR or comparing existing ones, I recommend evaluating them against the following criteria.

| Criterion        | Questions to ask                                                                                                         |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------ |
| Semantics        | Are integer arithmetic, floating-point behavior, memory effects, exceptions, and undefined behavior precisely specified? |
| Structure        | Does it represent values, operations, control flow, regions, and dependencies explicitly?                                |
| Types            | Are types static, dynamic, extensible, or partially inferred? Can the IR represent source-language distinctions?         |
| Memory           | How are aliasing, pointers, ownership, mutation, and synchronization modeled?                                            |
| Optimization     | Which transformations are easy to implement? Which invariants must every pass maintain?                                  |
| Lowering         | Can high-level constructs be progressively reduced to target operations without losing essential meaning?                |
| Target support   | Does it model target-independent computation, target-specific operations, or both?                                       |
| Interoperability | Can separate compilers exchange the representation reliably? Are versions and extensions specified?                      |
| Verification     | Can a verifier detect malformed programs and invalid transformations?                                                    |
| Debuggability    | Can developers inspect, print, compare, and trace the IR back to source code?                                            |
| Performance      | What are the memory, compile-time, and optimization costs?                                                               |
| Extensibility    | Can new operations, types, and analysis passes be added without destabilizing the ecosystem?                             |

For an existing compiler, inspect both its IR language reference and the invariants expected by its optimization passes. For a proposed IR, write down the semantic contract before designing the textual syntax. The syntax is usually the easier part.

### 10. Recommended research path

The following progression moves from foundational concepts to modern IR architecture.

[Implementation of Programming Languages - Akash Cherukuri](https://images.openai.com/static-rsc-4/NZuzhqOLBoMOSeoOd4XzPGl4D5b4wvXVfwIYptidWNzG9l3X_BusJV6paaqwu8nZM-U_BGsBXv5NAaLw20ckqYGBJh1FAZ-OatZ7VLTzIIgX6aTGwV6vlwhmPlWWSeZwhRmrOSm_TAQszd3sPP0GPhVjgAFGtKT6pPzcMaZs5HY?purpose=inline)

Stage 1 — Foundational representations

Study ASTs, three-address code, basic blocks, CFGs, dataflow analysis, and SSA. Learn how definitions and uses, dominance, and phi nodes support optimization.

[PPT - LLVM IR PowerPoint Presentation, free download - ID:2196423](https://images.openai.com/static-rsc-4/UyH-5OFvjv_hhOWnPj5IwVXZDJL3b3uh8haiY93T0kBWjhUvfpIkkpkvz1bEU_fuW-GXchHPwRb3rv5M3o4-zllOWcpLlPVavdbmU5yYgz3wb40mfBwbHEJQLlNadRq_Et1ZHTApfAx8XHwCKPhRwiJYMiHqvdy_wGoYpqq2Ggg?purpose=inline)

Stage 2 — LLVM IR and GCC GIMPLE

Read the official specifications, compile small programs, and inspect IR before and after optimization. Compare how each compiler represents control flow, memory, and intermediate values.

Resources: [LLVM LangRef](https://llvm.org/docs/LangRef.html?utm_source=chatgpt.com) · [GIMPLE](https://gcc.gnu.org/onlinedocs/gccint/GIMPLE.html?utm_source=chatgpt.com).

[Lowering Affine Loops to LLVM - MLIR - LLVM Discussion Forums](https://images.openai.com/static-rsc-4/0TWzydipBZdlCI-KEv-SMZ0l2VV62pK-BYPkLd15brPOMM7E6V4O5J348Ojw2dRD4fBuW19lyveYkqvt3rBlS_3hJPuiCX1ItvUsewl8KIC4XuZcDEiXHefmpqeFK1ZdwJ1kQmn1bIBT56_Dzm7V4buYl-tDkzvi7YKxPWvnA5U?purpose=inline)

Stage 3 — MLIR and multilevel compilation

Study dialects, operations, regions, block arguments, rewrite patterns, and progressive lowering. Follow a tensor operation through structured loops and into lower-level operations.

Resources: [MLIR rationale](https://mlir.llvm.org/docs/Rationale/Rationale/?utm_source=chatgpt.com) · [MLIR reference](https://mlir.llvm.org/docs/LangRef/?utm_source=chatgpt.com).

[CS 6120: Provably Correct Peephole Optimizations with Alive](https://images.openai.com/static-rsc-4/z3Lt0BH3ULzgYkabDJ0PnHg_n9Tyyfd-PkqYeckXz_eTokk5PA6PUEg4euXhZd2dAFrGCOU3x8yP-xRiBMAbxh3BN7YLt_OXfV7XraKkYC2WqN28T25B30q7jvMYmH3gJSxdEoyU6dTmyeL3Tm_3Gl8Gsu8DdWmjzyA_2Q9dBBA?purpose=inline)

Stage 4 — Semantics and correctness

Explore formal semantics, equivalence of programs, compiler verification, and translation validation. Investigate how an incorrect optimization can arise from an underspecified operation or an invalid assumption.

Starting point: [Alive2 research paper](https://pldi21.sigplan.org/details/pldi-2021-papers/5/Alive2-Bounded-Translation-Validation-for-LLVM?utm_source=chatgpt.com).

A useful exercise is to compile the same small program at different optimization levels, inspect the generated IR, and record which transformations occur. That makes the connection between representation design and compiler behavior concrete.

### Conclusion

The central idea behind intermediate representations is not simply to translate one language into another. It is to choose a representation that makes the next kind of reasoning possible.

- ASTs preserve syntactic structure.
- Three-address code makes computations explicit.
- CFGs expose control flow.
- SSA makes value dependencies explicit.
- Bytecode provides an instruction set for virtual execution.
- Low-level IRs expose operations useful for machine code generation.
- Domain-specific and multilevel IRs preserve higher-level structure long enough to optimize it.

GCC demonstrates the value of multiple specialized representations; LLVM demonstrates the leverage of a common, well-specified low-level IR; and MLIR demonstrates the benefits of an extensible framework that can preserve and transform several levels of abstraction.

For deeper research, I would focus on three connected questions: how an IR represents semantics, how its structure enables optimization, and how a compiler can establish that transformations preserve behavior. Those questions provide a much stronger basis for evaluating or designing an IR than its syntax alone.

Source note: The original Wikipedia snapshot supplied the initial terminology, examples, and list of compiler systems. Additional details and current design context above are drawn from official LLVM, GCC, and MLIR documentation and the cited compiler-correctness research. Where the expansion goes beyond the supplied article, it is presented as supplementary explanation rather than as a claim made by Wikipedia.
