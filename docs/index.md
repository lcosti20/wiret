# Wiret Core 0.3
## Proposed Language, Graph Format, Bytecode, and Runtime Specification

**Status:** Proposed  
**Version:** 0.3.0-draft  
**Specification type:** Language and implementation standard  
**Scope:** Graph-native programming language, canonical source format, portable bytecode, and embeddable runtime

---

## 1. Abstract

Wiret is a graph-native programming language designed for visual scripting, deterministic tooling, version-controlled source, automated graph generation, and embedding in host applications.

A Wiret program consists of typed nodes connected by explicit data and execution edges. Its canonical textual representation preserves the program's semantics and stable identities while remaining suitable for human review, source control, and structured editing.

Wiret defines a compilation pipeline from canonical source through a typed intermediate representation into portable bytecode. The bytecode is executed by a sandboxable virtual machine exposed through a C application programming interface.

Wiret is designed around six principles:

1. **Graph-native semantics:** The graph is the program, not merely a visualization of a conventional text program.
2. **Canonical representation:** Equivalent graph documents can be serialized consistently without discarding meaningful identity or metadata.
3. **Explicit execution:** Data dependencies, execution flow, state mutation, and suspension are distinguishable.
4. **Portable execution:** A conforming implementation follows a specified type system, instruction set, and execution model.
5. **Controlled capabilities:** Host resources are accessible only through explicitly granted capabilities.
6. **Versioned evolution:** Changes to syntax, node semantics, bytecode, and runtime APIs are managed independently.

This document defines the proposed Wiret Core 0.3 baseline. Features marked as optional or reserved are not required for initial conformance.

## 2. Conventions and terminology

The terms **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** express normative requirements.

A *graph* is a collection of nodes, pins, connections, and associated declarations.

A *node* is a typed operation or declaration within a graph.

A *pin* is a named input or output of a node. Pins may carry data or execution flow.

A *data edge* connects an output value to an input value.

An *execution edge* connects an execution output to an execution input.

A *pure node* computes a value without observable side effects.

An *effectful node* performs an operation whose execution can affect observable state.

A *module* is a named collection of functions, types, imports, and exports.

A *capability* is an explicitly granted authority to invoke a host operation or access a host-provided resource.

A *fiber* is a resumable unit of execution.

A *conforming implementation* is an implementation that satisfies the requirements for one or more declared conformance levels.

### 2.1 Specification layers

Wiret consists of several related but distinct specifications:

- **Wiret Source:** textual grammar, graph structure, identity, and serialization.
- **Wiret Language:** types, execution semantics, values, errors, and effects.
- **Wiret Bytecode:** binary container, instruction set, calling convention, and verification.
- **Wiret Runtime:** execution, resource management, fibers, and host integration.
- **Wiret ABI:** C interface and native capability registration.
- **Wiret Standard Nodes:** built-in node definitions and their semantics.

A rule in one layer MUST NOT silently override a rule in another. Each layer MUST define its dependencies and version requirements.

## 3. Goals and non-goals

### 3.1 Goals

Wiret Core 0.3 MUST support:

- Typed graph programs with explicit execution and data flow.
- Stable identities for graph objects.
- A canonical textual source representation.
- Deterministic parsing, validation, and canonical formatting.
- Static type checking and graph validation.
- Compilation into portable bytecode.
- Bytecode verification before execution.
- An embeddable runtime with an explicit C API.
- Capability-controlled host integration.
- Defined execution budgets and memory limits.
- Structured diagnostics and source-to-bytecode mappings.
- Machine-readable definitions for built-in nodes.
- Versioned modules and dependencies.

### 3.2 Non-goals

The initial core does not require:

- Full compatibility with Unreal Engine Blueprints.
- A just-in-time compiler.
- Multithreaded execution within a single VM.
- Unrestricted native memory access.
- Arbitrary reflection over host objects.
- A complete object-oriented language.
- A macro system.
- Seamless hot reload of suspended executions.
- A distributed execution protocol.

These features MAY be added by later specifications without weakening the guarantees of the core.

## 4. Architecture

The standard compilation and execution pipeline is:

1. Parse Wiret source.
2. Resolve modules, declarations, node kinds, and imports.
3. Validate graph structure.
4. Perform type checking and effect checking.
5. Lower the graph into a typed intermediate representation.
6. Validate control flow and definite assignment.
7. Optimize the intermediate representation where permitted.
8. Generate bytecode.
9. Verify the generated bytecode.
10. Load the verified module into the runtime.
11. Execute under configured capabilities and resource limits.

The compiler MAY use any internal representation that preserves the required semantics.

The source graph, intermediate representation, and bytecode MUST NOT be assumed to have identical structures.

An implementation MUST distinguish:

- Semantic information.
- Descriptive metadata.
- Editor layout.
- Compiler-generated information.
- Runtime-only state.

Editor layout MUST NOT influence program behavior.

## 5. Files, modules, and projects

### 5.1 Artifact conventions

| Artifact | Extension or name | Purpose |
|---|---|---|
| Source | `.wiret` | Canonical textual source |
| Bytecode | `.wirb` | Portable executable module |
| Project manifest | `wiret.toml` | Project configuration |
| Lockfile | `wiret.lock` | Resolved dependency versions and identities |
| Debug sidecar | `.wdbg` | Optional debug information |
| Runtime library | `libwiret` | Embeddable runtime |

These names are the proposed Core 0.3 conventions.

### 5.2 Module identity

Every module MUST declare a stable logical name. Filesystem paths and display names MUST NOT be treated as the sole source of module identity.

Modules MAY import other modules by logical name and declared version.

The compiler MUST reject unresolved imports and incompatible module interfaces.

### 5.3 Exports and imports

A module MUST explicitly declare the functions and values intended for external use.

Imports MUST identify the required module and its exported declarations. Runtime host functions MUST be imported through declared capabilities.

An implementation MUST NOT grant filesystem, network, process, or other host authority merely because a module imports a standard library.

### 5.4 Lockfiles

A project lockfile SHOULD record:

- Dependency identity.
- Resolved version.
- Content hash.
- Required language and bytecode versions.
- Required features.
- Registry or source origin, where applicable.

A reproducible build SHOULD use locked dependencies rather than resolving unconstrained versions at build time.

## 6. Canonical Wiret source

### 6.1 Source structure

A source file MUST begin with a Wiret language-version declaration.

A module MUST declare its logical name.

Functions and graphs MUST declare stable identities where persistence or external reference is required.

The canonical representation MUST contain sufficient information to reconstruct the graph's semantics without relying on editor state that is not present in the document.

### 6.2 Illustrative syntax

The following example illustrates the proposed node-centric style:

```wiret
wiret 0.3

module "game.damage"

func CalculateDamage(
    base: f32,
    armor: f32,
    critical: bool
) -> (damage: f32) [id = "fn_damage"] {
    node %entry = Entry [id = "entry"]

    node %double = Math.Mul<f32>(
        a: %entry.base,
        b: 2.0
    )

    node %choose = Select<f32>(
        condition: %entry.critical,
        when_true: %double.result,
        when_false: %entry.base
    )

    node %subtract = Math.Sub<f32>(
        a: %choose.result,
        b: %entry.armor
    )

    node %clamp = Math.Max<f32>(
        a: %subtract.result,
        b: 0.0
    )

    node %return = Return(
        damage: %clamp.result
    )

    layout {
        %entry    [x = 0,    y = 0]
        %double   [x = 220,  y = 120]
        %choose   [x = 440,  y = 0]
        %subtract [x = 660,  y = 0]
        %clamp    [x = 880,  y = 0]
        %return   [x = 1100, y = 0]
    }
}
```

This example is illustrative, not a normative parser test. A finalized grammar MUST specify all punctuation, declaration forms, reference syntax, and layout rules.

### 6.3 Node declarations

A node declaration identifies a node kind and its arguments.

Each node MUST have a unique identity within its graph.

Node identities MUST remain stable across formatting and layout changes. A rename or move SHOULD preserve identity when the logical node remains the same.

Deleting a node and creating a semantically different node MUST NOT reuse its identity merely because the new node occupies the same location.

### 6.4 Pin connections

A data input binding MUST be declared on its consumer.

An execution connection MUST be declared on its source, or represented through an equivalent canonical connection construct defined by the grammar.

Each ordinary data input MUST have at most one connected source. An unconnected input MUST use its declared default, if any, or produce a validation error if no valid default exists.

A data output MAY feed multiple inputs.

Execution outputs MUST follow the connection cardinality declared by the node registry.

Implicit connections based on pin names, editor positions, or node creation order MUST NOT be permitted.

### 6.5 Layout

Layout information MUST be stored separately from semantic content.

Layout MAY contain positions, dimensions, grouping, comments, colors, and editor presentation hints.

A compiler MUST ignore layout when generating executable behavior.

A formatter MUST NOT discard recognized layout information when performing a source-preserving operation.

### 6.6 Canonical formatting

A canonical formatter MUST:

- Produce stable indentation and line endings.
- Use deterministic escaping and literal formatting.
- Serialize unordered attributes in a defined order.
- Preserve semantically meaningful sequence ordering.
- Preserve stable IDs.
- Preserve supported metadata.
- Avoid transformations that change observable behavior.

Canonical formatting MUST be idempotent:

`format(format(source)) = format(source)`

Byte-for-byte canonical output is required for equivalent canonical documents under the same language and formatter version.

Canonicalization MUST NOT blindly reorder nodes by ID when doing so would alter execution semantics or meaningful source ordering.

## 7. Graph model

### 7.1 Graph elements

A graph contains:

- Node declarations.
- Input and output pins.
- Data connections.
- Execution connections.
- Graph parameters and results.
- Optional metadata and layout.

Every pin MUST have a stable name within its node definition.

The node registry MUST specify pin types, cardinality, default values, effects, and execution behavior.

### 7.2 Structural validation

A graph validator MUST reject:

- Duplicate node IDs.
- Duplicate pin declarations.
- Unknown node kinds.
- Unknown required pins.
- Invalid connection targets.
- Incompatible connection types.
- Invalid execution connection cardinality.
- Missing required inputs.
- Illegal entry or return structures.
- Unsupported semantic attributes.
- Invalid graph suspension behavior.

Cycles in data dependencies MUST be rejected unless the relevant graph construct explicitly defines iterative or feedback semantics.

Execution cycles MAY be valid, provided their control flow is well-formed and their execution is subject to runtime resource limits.

### 7.3 Stable identities

Stable identities SHOULD be used for:

- Modules.
- Functions.
- Graphs.
- Nodes.
- Persistent pins.
- Struct fields.
- Exports.
- Debug mappings.

Human-readable names and persistent IDs serve different purposes and MUST remain distinct.

Renaming an identifier SHOULD preserve its stable identity. A type change, node replacement, or pin replacement MUST follow the applicable compatibility rules.

## 8. Type system

### 8.1 Primitive types

The proposed primitive types are:

- `bool`
- `i8`, `i16`, `i32`, `i64`
- `u8`, `u16`, `u32`, `u64`
- `f32`, `f64`
- `string`
- `bytes`

Integer types have explicit width and signedness.

Floating-point types use IEEE-754 representations, subject to the arithmetic and determinism rules of this specification.

Strings represent valid UTF-8 text. Bytes represent arbitrary binary data.

### 8.2 Composite types

The core type system defines or reserves the following forms:

- `array<T>`
- `map<K, V>`
- `set<T>`
- `struct Name`
- `enum Name`
- `option<T>`
- `class Name`
- `handle<Name>`
- `func<(T...) -> R>`

Support for each composite type MUST be declared by the relevant conformance profile.

### 8.3 Conversion rules

Implicit lossy conversions MUST NOT occur.

Conversions that can lose precision, overflow, or change signedness MUST use explicit conversion operations with documented behavior.

A compiler MUST reject ambiguous type inference when the intended type cannot be uniquely determined.

### 8.4 Optional values

`option<T>` represents either a present value of type `T` or the absence of a value.

Absence MUST NOT be conflated with a valid default value of `T`.

Nullable class references, if supported, MUST be distinguished from ordinary non-null references in the type system.

### 8.5 Dynamic values

An unrestricted dynamically typed `any` value is not required by Core 0.3.

A future extension MAY define a tagged dynamic-value type. Such a type MUST preserve memory safety and MUST NOT bypass bytecode verification.

### 8.6 Generic operations

Generic node definitions MAY use type parameters.

The initial compiler MAY implement supported generic operations through monomorphization.

A compiler MUST resolve generic types before producing executable bytecode unless the bytecode specification explicitly supports runtime generic operations.

## 9. Values and memory semantics

### 9.1 Value types

Primitive values, records, enumerations, and collections have value semantics.

Assignment MUST preserve the logical value at the time of assignment.

### 9.2 Reference types

Class instances and opaque host handles have reference identity.

Copying a reference MUST NOT implicitly clone the referenced object.

Object lifetime and host ownership MUST be defined by the type and runtime API contracts.

### 9.3 Copy-on-write collections

Arrays, maps, and sets use value semantics. Implementations SHOULD use copy-on-write or another optimization that preserves those semantics.

For example:

```text
a = [1, 2, 3]
b = a
b = Array.Add(b, 4)
```

The observable result MUST be:

```text
a = [1, 2, 3]
b = [1, 2, 3, 4]
```

Internal storage MAY be shared until a mutation requires a distinct representation.

### 9.4 Collection operations

Array indexing MUST be bounds-checked.

Map lookup MUST distinguish a missing key from a present key whose value equals the type's default.

Set membership and map lookup MUST use defined key equality and hashing rules.

Iteration order MUST be deterministic:

- Arrays iterate by index.
- Maps iterate in insertion order.
- Sets use a defined canonical ordering or another explicitly specified deterministic iteration rule.

The standard library MUST define equality and mutation behavior for each supported collection type.

Host code MUST NOT mutate internal collection storage outside the runtime's ownership and synchronization rules.

## 10. Execution semantics

### 10.1 Execution flow

Execution flow determines the order of effectful operations.

Control-flow nodes MUST lower into explicit control-flow structures.

A function's execution MUST begin at its designated entry point.

Every terminating path MUST:

- Return the declared results;
- Propagate a runtime fault;
- Terminate according to a defined void-function rule; or
- Suspend where suspension is permitted.

A non-void function MUST NOT fall through without returning its declared results.

### 10.2 Data evaluation

A data connection establishes a dependency, not an execution event.

Pure nodes compute outputs from inputs according to their declared semantics.

Effectful nodes execute only through their defined execution path or another explicitly specified invocation mechanism.

The compiler MUST NOT infer that a data wire executes an effectful node.

### 10.3 Pure nodes

A pure node MUST NOT perform externally observable side effects, mutate state, or suspend.

Pure nodes MUST be deterministic with respect to their declared inputs and defined immutable environment.

A pure node MUST NOT conceal a time-dependent, random, or mutable host-state read.

Such dependencies MUST be represented by explicit effectful operations.

### 10.4 Effects

Every node and function MUST declare or inherit an effect classification.

The core classifications are:

- **Pure:** deterministic computation without observable side effects.
- **State read:** reads explicitly defined mutable state.
- **State write:** modifies identified state.
- **External effect:** invokes a host capability or performs an observable external operation.
- **Suspending:** may yield control and resume later.

A function MUST NOT claim to be pure if any reachable operation violates purity.

Effect checking MUST account for transitive function calls and native capability declarations.

### 10.5 Evaluation and optimization

The compiler MAY reorder, combine, or eliminate pure computations only where the transformation preserves observable behavior.

It MUST NOT reorder effectful operations when their order is semantically observable.

The compiler MUST NOT duplicate an effectful operation as an optimization unless the language explicitly defines the operation as safely duplicable.

Caching and common-subexpression elimination MUST respect mutation, effect, and lifetime boundaries.

### 10.6 Branching and sequencing

Branching nodes MUST evaluate the condition according to their defined semantics and select exactly the specified branch.

Sequence nodes MUST execute branches in their declared order.

A switch operation MUST define behavior for unmatched values and any default branch.

Execution ordering MUST NOT depend on node layout, serialization order, hash-map iteration, or unspecified scheduler behavior.

### 10.7 Loops and termination

Loops MUST be represented by valid control flow or standardized loop nodes.

The compiler MUST validate their structural consistency.

The runtime MUST enforce execution budgets so that an infinite loop cannot consume unbounded execution time.

The language MUST NOT imply that every valid program terminates.

## 11. Numeric behavior and determinism

### 11.1 Integer arithmetic

Integer overflow behavior MUST be defined for every arithmetic operation.

The standard library SHOULD provide explicit wrapping and checked operations.

Signed overflow MUST NOT depend on undefined behavior in the host implementation language.

Integer division by zero MUST produce a defined runtime fault.

### 11.2 Floating-point arithmetic

Floating-point operations MUST specify their treatment of:

- NaN.
- Positive and negative infinity.
- Signed zero.
- Rounding.
- Exceptional operations.
- Comparisons involving NaN.

Strict deterministic mode MUST prohibit compiler transformations that change observable floating-point results beyond the guarantees of the selected arithmetic profile.

### 11.3 Environmental inputs

Time, randomness, filesystem access, networking, and external service responses MUST be supplied through explicit capabilities.

A reproducible execution profile requires equivalent bytecode, inputs, capability results, and scheduling decisions.

Wiret MUST NOT promise identical results when the environment or external inputs differ.

### 11.4 Deterministic builds

A deterministic build SHOULD produce identical bytecode from identical canonical source, dependency versions, compiler settings, and compiler version.

The compiler MUST document any source of nondeterminism that prevents this guarantee.

## 12. Error handling

### 12.1 Compile-time diagnostics

Compilation failures MUST produce structured diagnostics where practical.

Diagnostics SHOULD identify:

- A stable error code.
- A human-readable message.
- The relevant module and graph.
- Node or pin identity.
- Source location.
- Suggested corrective action, where appropriate.

Diagnostic wording MAY change between compiler versions; stable error codes SHOULD remain consistent within a compatibility series.

### 12.2 Runtime faults

Runtime faults MUST be distinguishable from successful return values.

Examples include:

- Invalid arithmetic operations.
- Bounds violations.
- Missing required values.
- Explicitly thrown faults.
- Host capability failures.
- Invalid external data.

Catchable faults MUST be distinguished from fatal VM failures.

### 12.3 Fatal failures

Malformed bytecode, verifier failures, internal VM corruption, and certain resource-limit failures MUST NOT be treated as ordinary successful returns.

The runtime MUST define which failures can be caught by a Wiret program and which require terminating the current execution.

A fatal VM failure MUST NOT permit execution to continue in an invalid machine state.

## 13. Bytecode container

### 13.1 File identity

The portable bytecode extension is `.wirb`.

The proposed magic is the five-byte sequence:

```text
00 57 49 52 42
```

This corresponds to `\0WIRB`.

The final container standard MUST explicitly fix the header layout, including the byte count, rather than relying on textual notation alone.

### 13.2 Header fields

The proposed header contains:

| Field | Width | Meaning |
|---|---:|---|
| Magic | 5 bytes | Container identification |
| Format major | 16 bits | Incompatible format version |
| Format minor | 16 bits | Compatible format revision |
| Flags | 32 bits | Defined container flags |
| Header size | 32 bits | Total header size |
| Section count | 32 bits | Number of sections |

Multibyte integer fields use little-endian encoding.

The exact byte offsets, reserved fields, alignment requirements, and length constraints MUST be fixed by the final binary-format specification.

### 13.3 Sections

The proposed section identifiers are:

- `TYPE`: type descriptors.
- `IMPT`: imported modules and capabilities.
- `FUNC`: function signatures, locals, and control-flow metadata.
- `CODE`: instruction streams and basic-block tables.
- `CNST`: constants.
- `EXPT`: exported declarations.
- `DATA`: immutable data.
- `DBG`: source and node mappings.
- `META`: compiler and module metadata.

`TYPE`, `IMPT`, `FUNC`, and `CODE` are required in the initial proposed format. Other sections are optional unless a module declares that they are required.

Each section MUST be length-delimited.

A loader MUST validate section boundaries and lengths before reading section contents.

Unknown optional sections MAY be skipped. Unknown required sections MUST cause a load failure.

The final standard MUST assign numeric section IDs and specify each section's binary schema.

## 14. Virtual machine

### 14.1 Execution model

Wiret Core 0.3 uses a typed stack virtual machine with explicit local slots and basic blocks.

Each function declares:

- Parameter types.
- Result types.
- Local-slot types.
- Operand-stack requirements.
- Basic blocks.
- Instructions and terminators.
- Exception metadata where supported.
- Suspension metadata where supported.

### 14.2 Control flow

Each basic block MUST have exactly one terminator.

All branch targets MUST identify valid block boundaries.

Stack states at control-flow merge points MUST be compatible.

Every function MUST have a valid entry block.

The verifier MUST reject invalid control flow.

### 14.3 Calling convention

Function calls MUST use a defined calling convention.

The bytecode specification MUST define argument order, result order, local-slot initialization, return behavior, and stack restoration.

Calls to imported host functions MUST match the declared signature and capability requirements.

### 14.4 Instruction set

The initial instruction set SHOULD include:

- Constant loading.
- Local-slot loading and storing.
- Defined arithmetic operations.
- Comparisons.
- Conditional and unconditional branches.
- Function calls and returns.
- Stack operations required by the chosen encoding.
- Collection operations supported by the core.
- Capability calls.
- Fault propagation and raising.
- Fiber suspension and resumption operations where supported.

Every instruction MUST have a defined encoding, operand schema, type behavior, stack effect, control-flow behavior, and failure behavior.

An implementation MUST NOT assign private meanings to standardized opcode values.

## 15. Bytecode verification

A module MUST be verified before execution.

The verifier MUST validate:

1. Container magic and version.
2. Header and section bounds.
3. Required sections and features.
4. Type descriptors.
5. Function signatures.
6. Instruction encodings.
7. Local-slot indices.
8. Operand-stack consistency.
9. Control-flow targets.
10. Call signatures.
11. Import declarations.
12. Capability references.
13. Return and termination behavior.
14. Suspension constraints.
15. Constant and data references.

The verifier MUST reject invalid bytecode rather than relying on runtime checks as the sole safety mechanism.

The verifier SHOULD compute or validate upper bounds on stack depth and other statically measurable resources.

A successfully verified module MUST still execute under runtime quotas. Verification does not eliminate the possibility of excessive computation or memory consumption.

## 16. Runtime model

### 16.1 Runtime objects

The runtime defines three primary opaque objects:

- `wr_Vm`: VM configuration, capabilities, memory management, and shared execution state.
- `wr_Module`: a loaded and verified module.
- `wr_Fiber`: a resumable execution unit with its own execution state.

The implementation MAY use additional internal objects.

### 16.2 Execution outcomes

Execution MUST distinguish at least:

- Completed successfully.
- Suspended.
- Failed with a runtime fault.
- Cancelled.
- Terminated because of a fatal VM failure.

These outcomes MUST NOT be conflated.

### 16.3 Fibers

A fiber contains sufficient state to resume execution consistently after suspension.

Suspension MUST occur only at defined suspension points.

The runtime MUST define the lifetime of values, references, and host resources across suspension.

Cancellation MUST be observable according to a documented policy. Cleanup handlers and resource release MUST follow defined rules.

### 16.4 Resource budgets

The runtime MUST support an instruction or fuel budget.

It SHOULD support configurable limits for:

- Allocated memory.
- Operand-stack depth.
- Call-stack depth.
- Fiber count.
- Module size.
- Collection sizes.
- Host-call execution.

Budget exhaustion MUST produce a defined result and MUST NOT leave the VM in an invalid state.

## 17. C embedding API

The runtime SHOULD expose a stable C ABI with opaque handles.

An illustrative interface is:

```c
typedef struct wr_Vm wr_Vm;
typedef struct wr_Module wr_Module;
typedef struct wr_Fiber wr_Fiber;

wr_Status wr_vm_create(
    const wr_VmConfig *config,
    wr_Vm **out_vm
);

wr_Status wr_module_load(
    wr_Vm *vm,
    const uint8_t *bytes,
    size_t length,
    wr_Module **out_module
);

wr_Status wr_call(
    wr_Vm *vm,
    wr_Module *module,
    const char *export_name,
    const wr_Value *args,
    size_t arg_count,
    wr_Value *results,
    size_t result_capacity,
    size_t *result_count
);

wr_Status wr_start(
    wr_Vm *vm,
    wr_Module *module,
    const char *export_name,
    const wr_Value *args,
    size_t arg_count,
    wr_Fiber **out_fiber
);

wr_Status wr_advance(
    wr_Vm *vm,
    wr_Fiber *fiber,
    uint64_t instruction_budget
);

wr_Status wr_cancel(
    wr_Vm *vm,
    wr_Fiber *fiber
);

void wr_vm_destroy(wr_Vm *vm);
```

This interface is illustrative. It is not a finalized ABI or compiled header.

### 17.1 Ownership

The ABI specification MUST define ownership for every object and value.

Borrowed pointers MUST have documented validity periods.

Owned values MUST have an explicit release mechanism or documented ownership transfer.

The runtime MUST NOT retain borrowed memory beyond its permitted lifetime.

### 17.2 Error boundaries

The runtime MUST NOT allow C++ exceptions or Wiret runtime traps to unwind through the C ABI.

All externally observable errors MUST be returned through documented status values and structured error information.

### 17.3 Native capabilities

Native functions MUST be registered explicitly.

Each registration MUST specify:

- Capability name.
- Function signature.
- Effect classification.
- Suspension behavior.
- Error behavior.
- Ownership and lifetime requirements.
- Any relevant resource limits.

The runtime MUST reject calls to unavailable capabilities.

## 18. Security

Wiret is intended to support execution of scripts that may not be trusted.

A conforming sandboxed runtime MUST provide:

- Bytecode verification.
- Bounds-checked access to VM-managed memory.
- Explicit capability registration.
- Instruction or fuel limits.
- Defined memory limits.
- Controlled cancellation.
- Defined error and cleanup behavior.
- Isolation from arbitrary host pointers and ambient authority.

The core MUST NOT implicitly grant access to the filesystem, network, operating system processes, or arbitrary native functions.

Security depends on both the VM and the capabilities supplied by the host. A host that registers unrestricted native functions can undermine the sandbox's intended restrictions.

## 19. Standard node registry

Each standard node MUST have a machine-readable definition.

A registry entry MUST identify:

- Stable node-kind ID.
- Canonical name.
- Semantic version.
- Type parameters.
- Input and output pins.
- Execution pins.
- Default values.
- Effect classification.
- Suspension behavior.
- Error behavior.
- Lowering rules.
- Documentation.
- Compatibility requirements.

The registry MUST be usable by the editor, compiler, validator, documentation generator, and structured-editing tools.

The registry is authoritative for node interfaces. Informal examples MUST NOT override its normative definitions.

### 19.1 Built-in node families

The initial standard library SHOULD prioritize:

- Entry and return nodes.
- Branch and sequence nodes.
- Typed arithmetic and comparison.
- Boolean operations.
- Explicit conversion.
- Array, map, and set operations.
- Struct and enum operations.
- Explicit state access.
- Capability calls.
- Fault handling.
- Fiber and suspension operations, where supported.

A standard node SHOULD lower to existing bytecode instructions whenever possible. New VM instructions SHOULD be introduced only when they provide a clear implementation or semantic benefit.

## 20. Editing, merging, and automated generation

Wiret editing tools MUST operate on stable graph identities and the canonical semantic model.

Structured patches SHOULD include:

- Expected document or semantic hash.
- Target module and graph identity.
- Target node or pin identity.
- Requested operation.
- Replacement content.
- Conflict policy.

A patch whose preconditions do not match the current document MUST be rejected or returned for reconciliation.

A tool MUST NOT silently overwrite concurrent changes.

### 20.1 Merge behavior

Merging MUST distinguish semantic changes from layout-only changes.

Layout-only conflicts MAY be resolved independently where doing so does not alter program meaning.

Conflicts involving types, connections, node semantics, execution order, or identities MUST be reported explicitly when automatic resolution could change behavior.

### 20.2 AI-generated graphs

AI tools SHOULD generate graphs using the same grammar, registry, and validation rules as other tools.

A generated graph MUST pass ordinary parsing, type checking, structural validation, and compilation before it can be considered valid.

AI-generated output MUST NOT receive special semantic privileges or bypass runtime security restrictions.

## 21. Compatibility and versioning

Wiret uses separate versions for:

- Source language.
- Bytecode format.
- Standard node semantics.
- Runtime ABI.
- Extensions and capabilities.

### 21.1 Source compatibility

A source-format change that makes previously valid source invalid or changes its interpretation MUST be treated as a breaking change.

A migration tool MAY update source, but it MUST report transformations that could affect observable behavior.

### 21.2 Bytecode compatibility

A bytecode major-version change MAY alter the container or instruction semantics incompatibly.

A minor-version change MUST preserve the compatibility guarantees defined by the container specification.

Unknown required features MUST cause an explicit compatibility failure.

### 21.3 Node compatibility

Changing a node's observable behavior MUST NOT be treated as a harmless documentation update.

A semantic change SHOULD require a new node kind or an explicitly versioned migration.

### 21.4 ABI compatibility

An incompatible C ABI change MUST increment the ABI major version.

Runtime libraries MUST document which ABI versions they support.

### 21.5 Metadata compatibility

Unknown descriptive metadata SHOULD be preserved when a tool edits and serializes a document.

Unknown semantic constructs MUST NOT be interpreted by guesswork.

## 22. Conformance

Wiret defines four proposed conformance levels.

### Level 1: Source

Requires:

- Parsing.
- Canonical formatting.
- Stable identity handling.
- Graph validation.
- Metadata preservation.

### Level 2: Compiler

Requires Level 1 and:

- Type checking.
- Effect checking.
- Control-flow validation.
- Standard node lowering.
- Defined diagnostics.
- Deterministic compilation under the declared build profile.

### Level 3: Runtime

Requires:

- Bytecode loading and verification.
- Instruction semantics.
- Calling conventions.
- Runtime faults.
- Resource budgets.
- Capability enforcement.
- Required C ABI behavior.

### Level 4: Full implementation

Requires all preceding levels and:

- Project manifests and dependency resolution.
- Debug mappings.
- Structured patching.
- Merge support.
- End-to-end compatibility tests.

A conforming implementation MUST document its conformance level, supported features, version compatibility, and known limitations.

## 23. Required test suite

A Core 0.3 implementation SHOULD include tests for:

- Grammar acceptance and rejection.
- Canonical formatting and round-tripping.
- Stable identities under rename and layout changes.
- Duplicate IDs and invalid connections.
- Type inference and invalid conversions.
- Pure-node optimization.
- Effect ordering.
- Integer overflow and division by zero.
- Floating-point edge cases.
- Unicode string behavior.
- Collection value semantics.
- Map and set iteration.
- Invalid bytecode and malformed sections.
- Stack verification and invalid branch targets.
- Capability denial.
- Instruction-budget exhaustion.
- Memory limits.
- Suspension, cancellation, and resumption.
- C ABI ownership and error behavior.
- Stale patch rejection.
- Compiler and runtime compatibility.

The suite MUST distinguish normative requirements from implementation-specific performance tests.

## 24. Implementation roadmap

The recommended development sequence is:

1. Freeze the grammar, graph model, IDs, type rules, effects, and errors.
2. Implement parsing, validation, canonical formatting, and round-trip tests.
3. Implement a small typed compiler and reference interpreter.
4. Finalize the binary container, instruction set, and verifier.
5. Implement the portable runtime and resource limits.
6. Implement the stable C ABI and native capability registration.
7. Add collections, fibers, suspension, and advanced standard nodes.
8. Add manifests, dependency locking, debug tooling, and structured patches.
9. Expand into classes, interfaces, advanced generics, reflection, and hot reload only after their semantics are specified and tested.

Each stage SHOULD have conformance tests before the next stage becomes a required dependency.

## 25. Open issues required before standardization

This proposal establishes an architectural baseline but is not yet a complete implementable standard.

The following work remains necessary:

1. Finalize the complete source grammar and parser conformance suite.
2. Define exact numeric opcode assignments and binary section schemas.
3. Specify the complete typed
