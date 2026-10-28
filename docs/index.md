[Wiret_Language_Specifications_Proposal_1.md](https://github.com/user-attachments/files/34054793/Wiret_Language_Specifications_Proposal_1.md)

# Wiret Language Specification

## Design proposal --- version 0.1 (draft)

**Status:** Proposed architecture, not an implemented or stable
standard\
**Audience:** language implementers, editor authors, compiler/runtime
developers, and AI tooling\
**Primary goal:** a canonical, diffable textual representation of visual
programs that compiles to portable bytecode and executes inside an
embeddable runtime.

------------------------------------------------------------------------

## 1. Executive summary

Wiret is a **graph-first programming language with a canonical textual
interchange format**. It is not intended to be a language people
normally type by hand. Its source file is the durable representation of
a visual graph: nodes, typed pins, execution-flow edges, data-flow
edges, comments, groups, layout, and editor metadata.

Wiret borrows four ideas from existing systems:

-   From visual scripting systems such as Unreal Engine Blueprints:
    execution wires, data pins, events, functions, macros, node-based
    control flow, latent operations, and user-facing node titles.
-   From LLVM IR and JVM/Wasm: an explicit, typed, verifiable
    intermediate representation, defined control-flow blocks,
    deterministic validation, and a separate executable bytecode format.
-   From DOT and GML: a compact graph description with attributes,
    nested metadata, and stable node/edge identities.
-   From the Lua C API: a small embeddable runtime with explicit state
    ownership, host callbacks, value conversion, protected calls, and
    extension points.

The key architectural decision is to separate **meaning** from
**presentation**. The graph's semantics are expressed by nodes, pins,
edges, types, and control-flow rules. Editor placement, comment boxes,
node colors, collapsed groups, and preferred display names are metadata.
They are serialized so collaborators see the same graph, but they do not
change program behavior.

Wiret has three layers:

1.  **Wiret Graph Text (WGT):** readable, canonical text used in source
    control and by editor/AI tools.
2.  **Wiret Bytecode (WBC):** compact, validated, versioned executable
    representation.
3.  **Wiret Runtime (WRT):** an embeddable VM with host bindings,
    garbage collection, scheduling, diagnostics, and sandbox controls.

The proposed implementation lowers the visual graph to a typed,
block-based IR, validates it, then emits WBC. The text format is not
itself the bytecode and should not be executed directly in production.

------------------------------------------------------------------------

## 2. Design principles

1.  **Graph is the source of truth.** The editor loads and saves WGT;
    users should not need to hand-edit it.
2.  **Readable diffs.** One node, pin, edge, or layout change should
    usually affect a small number of lines.
3.  **Stable identity.** Node and edge IDs persist across renames and
    layout changes. IDs are not array positions.
4.  **Canonical serialization.** Equivalent documents have one preferred
    spelling and ordering. This reduces noisy Git diffs and makes
    model-generated edits easier to review.
5.  **Explicit types.** Pins have declared types or an explicitly
    inferable type variable. No silent coercions beyond documented
    conversions.
6.  **Separate execution and data flow.** Execution edges sequence
    effects; data edges carry values. A data dependency alone does not
    imply execution.
7.  **Friendly editor labels, formal operations.** A node may display
    "Add", while its semantic operation is `core.i32.add`.
8.  **Presentation survives compilation round trips.** Layout metadata
    remains in WGT and in optional debug sidecar sections of WBC, even
    though it is not executed.
9.  **Deterministic builds by default.** Same normalized source,
    compiler version, target features, and imports produce equivalent
    bytecode.
10. **Host capabilities are explicit.** File access, networking, clocks,
    and engine APIs are imported capabilities, not ambient powers.
11. **Errors should be explainable visually.** Every diagnostic can
    point to a file, node, pin, edge, or graph region.
12. **Extensible without making the core ambiguous.** Namespaced node
    operations and metadata allow engine-specific extensions while
    preserving a small portable core.

------------------------------------------------------------------------

## 3. File model and naming

A project may contain:

-   `.wrt` --- Wiret Graph Text source.
-   `.wbc` --- compiled Wiret Bytecode module.
-   `.wdbg` --- optional debug/source map and graph metadata sidecar.
-   `wiret.lock` --- optional resolved dependency and compiler lockfile.
-   `wiret.toml` --- project settings, target features, and import
    declarations.

A source file contains one module. Modules may declare public functions,
event graphs, types, constants, and imports. File names are not semantic
identifiers; module names are.

### 3.1 Module identity

A module uses a dotted, case-sensitive identifier such as `game.player`
or `tools.math`. Public names are exported explicitly. Imported names
are qualified to avoid accidental ambiguity.

### 3.2 IDs

Use UUIDs or compact, globally unique stable IDs. The examples use
readable IDs such as `n_start` and `e_01`; production editors should use
UUIDv7 or another stable identifier scheme. IDs must remain stable when
nodes move, labels change, or unrelated nodes are inserted. A duplicated
node receives new IDs for the node, its pins, and its incident edges.

Node IDs are local to a graph; graph IDs are local to a module; an
optional project-level identity can be stored in metadata. Pin IDs are
stable within a node and should usually be symbolic (`exec_out`,
`value`) rather than generated opaque values.

------------------------------------------------------------------------

## 4. Wiret Graph Text (WGT)

### 4.1 Syntax overview

WGT uses a small, line-oriented declaration syntax inspired by assembly
IR and graph-description languages. It is intentionally **not XML or
JSON**: punctuation is lightweight, declarations have visible names, and
nested metadata is only used where hierarchy is helpful.

Core constructs:

-   `module` --- module header and target language version.
-   `import` --- imported module or host capability.
-   `type` and `const` --- type and constant declarations.
-   `graph` --- a function, event graph, or macro graph.
-   `node` --- a graph operation with typed pins and attributes.
-   `edge` --- execution or data connection.
-   `region` --- optional visual grouping and structured control-flow
    grouping.
-   `meta` --- presentation or tool metadata.
-   `note` --- editor comment/annotation.

The grammar below is illustrative EBNF; implementation details should be
fixed by the parser specification.

``` ebnf
document      = header, { declaration } ;
header        = "wiret", version, newline, "module", identifier, [ attributes ], newline ;
declaration   = importDecl | typeDecl | constDecl | graphDecl | metaDecl ;
importDecl    = "import", string, [ "as", identifier ], [ attributes ], newline ;
typeDecl      = "type", identifier, "=", typeExpr, [ attributes ], newline ;
constDecl     = "const", identifier, ":", typeExpr, "=", literal, [ attributes ], newline ;
graphDecl     = "graph", graphKind, identifier, "(", [ params ], ")", [ returnType ], [ attributes ], block ;
block         = "{", newline, { graphItem }, "}" ;
graphItem     = nodeDecl | edgeDecl | regionDecl | noteDecl | metaDecl ;
nodeDecl      = "node", identifier, ":", operation, [ pinBlock ], [ attributes ], newline ;
pinBlock      = "(", [ pinDecl, { ",", pinDecl } ], ")" ;
pinDecl       = pinDirection, identifier, ":", typeExpr, [ "=", literal ], [ attributes ] ;
edgeDecl      = "edge", identifier, ":", edgeKind, endpoint, "->", endpoint, [ attributes ], newline ;
endpoint      = identifier, ".", identifier ;
edgeKind      = "exec" | "data" ;
regionDecl    = "region", identifier, [ attributes ], block ;
noteDecl      = "note", identifier, string, [ attributes ], newline ;
metaDecl      = "meta", identifier, "=", value, newline ;
attributes    = "[", attribute, { ",", attribute }, "]" ;
attribute     = identifier, "=", value ;
pinDirection  = "in" | "out" ;
graphKind     = "function" | "event" | "macro" ;
returnType    = "->", typeExpr ;
```

Whitespace is insignificant between tokens. Newlines terminate top-level
declarations unless the parser is inside a balanced `()`, `[]`, or `{}`
construct. `#` starts a line comment outside strings. Strings use
JSON-compatible escaping, but the document is not JSON. Numeric literals
must be locale-independent.

### 4.2 Example: a small function

``` wiret
wiret 0.1
module demo.math [target="portable"]

graph function clamp01(value: f32) -> f32 [public=true, id="g_clamp"] {
  node n_zero: core.f32.const (
    out value: f32 = 0.0
  ) [id="n_zero", title="Zero", pos=[80, 220]]

  node n_one: core.f32.const (
    out value: f32 = 1.0
  ) [id="n_one", title="One", pos=[80, 340]]

  node n_low: core.f32.max (
    in a: f32,
    in b: f32,
    out value: f32
  ) [id="n_low", title="Clamp minimum", pos=[340, 220]]

  node n_high: core.f32.min (
    in a: f32,
    in b: f32,
    out value: f32
  ) [id="n_high", title="Clamp maximum", pos=[570, 220]]

  node n_return: core.return (
    in value: f32
  ) [id="n_return", title="Return", pos=[800, 220]]

  edge e_01: data n_zero.value -> n_low.b
  edge e_02: data n_low.value -> n_high.a
  edge e_03: data n_one.value -> n_high.b
  edge e_04: data n_high.value -> n_return.value

  meta graph.layout [zoom=0.9, pan=[0, 0], grid=16]
}
```

The example intentionally exposes graph structure rather than pretending
to be conventional source code. The editor can render each `node` as a
card, each `edge` as a wire, and each `pos` as its saved location. The
`title` is a presentation label; `core.f32.min` is the semantic
operation.

### 4.3 Example: execution flow and data flow

``` wiret
wiret 0.1
module demo.greeting

graph function greet(name: string) -> void [public=true, id="g_greet"] {
  node n_entry: core.entry () [id="n_entry", pos=[64, 120]]
  node n_prefix: core.string.const (
    out value: string = "Hello, "
  ) [id="n_prefix", pos=[80, 300]]
  node n_join: core.string.concat (
    in left: string,
    in right: string,
    out value: string
  ) [id="n_join", pos=[340, 300]]
  node n_log: host.console.write (
    in value: string
  ) [id="n_log", capability="console.write", pos=[600, 160]]
  node n_exit: core.exit () [id="n_exit", pos=[840, 160]]

  edge x_01: exec n_entry.then -> n_log.exec
  edge x_02: exec n_log.then -> n_exit.exec
  edge d_01: data n_prefix.value -> n_join.left
  edge d_02: data g_greet.name -> n_join.right
  edge d_03: data n_join.value -> n_log.value
}
```

A graph's entry and exit pins are implicit only where the operation
definition says so. In this example, `core.entry`, `host.console.write`,
and `core.exit` declare their execution pins in the operation registry.
The data input `g_greet.name` is a graph argument endpoint.

### 4.4 Types and values

The portable core type set:

-   `bool`
-   `i32`, `i64`
-   `u32`, `u64`
-   `f32`, `f64`
-   `string` (UTF-8, immutable value semantics)
-   `bytes`
-   `void`
-   `option<T>`
-   `array<T>`
-   `map<K,V>` where `K` is a permitted hashable type
-   `struct Name`
-   `handle<Name>` for opaque host-managed objects
-   `func<(T1, ...)->R>` for function references

Extensions may add vector, color, transform, entity, or engine-specific
types. Such types must declare stable type IDs, serialization rules,
equality semantics where applicable, and whether they can cross the host
boundary.

Numeric conversions are explicit nodes unless the language version
defines a lossless implicit conversion. Integer overflow behavior is
operation-specific and must be defined; the recommended core uses
wrapping integer arithmetic for `*.add.wrap` and checked/trapping
arithmetic for `*.add.checked`. Floating-point behavior follows IEEE 754
except where a named operation documents otherwise. Strings are UTF-8
and are not implicitly converted to numbers.

### 4.5 Node operation names

Operations are namespaced and versioned through the module/registry, for
example:

-   `core.i32.add`
-   `core.f32.multiply`
-   `core.branch`
-   `core.loop`
-   `core.call`
-   `core.return`
-   `core.array.get`
-   `host.console.write`
-   `engine.actor.get_location`

The operation registry defines each operation's semantic ID, display
name, input/output pins, types, default values, execution behavior,
purity, effects, compiler lowering, and compatibility policy. The text
file must not redefine the meaning of a built-in operation. Unknown
operations are preserved by editors as opaque nodes but cannot be
compiled without a registered definition.

### 4.6 Edges and pin rules

-   `exec` edges connect execution output pins to execution input pins.
-   `data` edges connect compatible data output pins to data input pins.
-   A pin may declare `multiplicity="one"` or `"many"`. Default is one.
-   A single-input data pin may have at most one incoming edge unless
    its operation defines merge semantics.
-   Execution output fan-out is prohibited by default; use an explicit
    `core.sequence` or `core.fork` node so ordering/concurrency is
    visible.
-   Cycles in data flow are invalid unless represented through an
    explicit loop, phi/merge operation, or stateful node.
-   Execution cycles are allowed only when the cycle contains a
    recognized loop/yield boundary or the graph's
    structured-control-flow rules explicitly permit it.
-   Unconnected input pins use declared defaults or cause a validation
    error.
-   An edge must reference existing endpoints and match their pin kinds
    and types.
-   Every executable path must terminate, return, or yield according to
    the graph kind.

### 4.7 Metadata and layout

Metadata is divided into namespaces:

-   `layout.*` --- position, size, zoom, pan, routing hints, z-order.
-   `editor.*` --- selected tab, collapsed state, color, comment
    visibility.
-   `doc.*` --- descriptions, tooltips, examples, author notes.
-   `debug.*` --- breakpoints, watch expressions, trace labels.
-   `vendor.<name>.*` --- extension-owned metadata.

Recommended layout attributes:

``` wiret
[id="...", title="...", pos=[x, y], size=[w, h], color="#RRGGBB",
 collapsed=false, z=0]
```

Only the `id` and operation-specific semantic attributes are needed for
program meaning. Layout values are preserved in the canonical source,
but ignored by bytecode execution. Unknown metadata must be preserved on
save by tools that do not understand it.

### 4.8 Canonical formatting

To minimize merge conflicts, conforming writers should:

1.  Emit UTF-8, LF line endings, and a final newline.
2.  Use two spaces per indentation level.
3.  Emit graph items in stable declaration order, preferably by
    persistent creation order rather than alphabetical order.
4.  Emit attributes in a fixed order: semantic attributes, `id`, title,
    layout, then extension metadata.
5.  Use canonical numeric formatting and lowercase booleans.
6.  Never reorder nodes solely by screen position.
7.  Keep each node and edge declaration on one line when it fits; use a
    multiline pin block for readability.
8.  Preserve unknown metadata and unknown attributes exactly where
    feasible.
9.  Avoid regenerating IDs on save.
10. Use a formatter version field only when formatting behavior changes
    materially.

Canonical formatting is a writer requirement, not a semantic
requirement. Parsers should accept harmless whitespace differences.

------------------------------------------------------------------------

## 5. Semantic model and compilation

### 5.1 Three representations

Compilation proceeds through:

1.  **WGT parse tree** --- preserves declarations, IDs, comments, and
    metadata.
2.  **Typed Graph IR (TGIR)** --- validates pins and edges, resolves
    types, computes data dependencies, and lowers graph control flow
    into basic blocks.
3.  **Wiret Bytecode (WBC)** --- verified executable module, with
    optional debug/source mapping.

TGIR is SSA-like for values: each produced value has one definition, and
control-flow merges use explicit block parameters (phi-like values). The
editor graph need not expose SSA to users; it is a compiler
representation used for predictable execution.

### 5.2 Control flow

Every function lowers to basic blocks with explicit terminators. A block
may end with:

-   `br block`
-   `br_if condition, true_block, false_block`
-   `switch value, cases..., default_block`
-   `return value`
-   `throw exception`
-   `yield resume_block` (for cooperative suspension)
-   `unreachable`

The editor's `Branch`, `Switch`, `Loop`, and `Sequence` nodes lower to
these operations. A `Loop` becomes a cycle of basic blocks with a back
edge. A data value that differs by incoming path becomes a block
parameter.

### 5.3 Evaluation order

Wiret uses explicit execution flow for effects. Pure data nodes are
evaluated when their outputs are needed, in dependency order. If two
pure nodes have no dependency, the compiler may evaluate them in either
order. Pure operations must not observe or mutate host state.

Impure operations execute only when their execution input is reached.
Their data inputs are evaluated according to the operation's declared
policy. The compiler may not reorder effectful operations across
observable effects. If deterministic ordering matters, connect them
through execution pins or an explicit sequence node.

### 5.4 Errors

Compilation diagnostics use stable codes and structured locations:

``` text
WRT-TYPE-014: input pin 'b' expects f32 but received i32
  at demo.math::g_clamp / node n_low / pin b
  hint: insert core.i32.to_f32 or change the source pin type
```

Runtime errors include module, function, instruction offset, node ID
(when debug data exists), stack trace, and an optional host error
payload. A host can choose whether an unhandled error aborts the current
call, is delivered to an error callback, or terminates an isolated VM
instance.

------------------------------------------------------------------------

## 6. Wiret Bytecode (WBC)

### 6.1 Goals

WBC is a portable, versioned binary format optimized for safe
validation, compact loading, and predictable execution. It is not a
direct serialization of WGT. It resembles a small typed stack/register
VM with explicit basic blocks and constant pools. A first implementation
should favor easy verification and debugging over extreme code density.

### 6.2 Module binary layout

All multibyte integers use unsigned LEB128 unless a fixed-width field is
explicitly stated. The header is fixed-width:

  Field                Size Meaning
  --------------- --------- ------------------------------------
  Magic             4 bytes ASCII `WBC\0`
  Major              u16 LE Incompatible format version
  Minor              u16 LE Backward-compatible format version
  Flags              u32 LE Feature bits
  Header size        u32 LE Header length in bytes
  Section count      u32 LE Number of sections

Each section is encoded as `section_id:u8`, `section_flags:u8`,
`payload_length:uleb128`, `payload`. Sections must not overlap, must fit
within the file, and must appear in ascending section ID order in
canonical files. Unknown optional sections are skipped; unknown required
sections cause a load error.

Initial section IDs:

  -----------------------------------------------------------------------------
                     ID Section          Required         Contents
  --------------------- ---------------- ---------------- ---------------------
                      1 `STRS`           yes              UTF-8 string table

                      2 `TYPE`           yes              Type descriptors

                      3 `IMPT`           yes              Imported modules and
                                                          host capabilities

                      4 `CNST`           yes              Constants

                      5 `FUNC`           yes              Function signatures
                                                          and locals/register
                                                          counts

                      6 `CODE`           yes              Instructions and
                                                          basic-block tables

                      7 `EXPT`           no               Exported
                                                          functions/types

                      8 `DATA`           no               Immutable data blobs

                      9 `DBG`            no               Node IDs, source
                                                          spans,
                                                          instruction-to-node
                                                          mapping

                     10 `META`           no               Compiler/build
                                                          metadata
  -----------------------------------------------------------------------------

The section payloads are length-delimited. Parsers must reject
out-of-bounds indexes, invalid UTF-8 where required, duplicate mandatory
sections, malformed LEB128 encodings, unsupported required features, and
unreasonable declared sizes before allocating large buffers.

### 6.3 Execution model

WBC uses a **typed register VM**. Each function declares a register
count and typed register map. Instructions read/write numbered
registers. Registers are function-local; calls create frames. Values are
tagged runtime values, but the verifier ensures instruction/register
type compatibility before execution.

Each function contains a block table. A block has an ID, instruction
range, and exactly one terminator. Branch targets must refer to known
blocks. Control flow is not allowed to fall through from one block into
another.

### 6.4 Instruction encoding

Each instruction begins with an opcode byte followed by opcode-specific
operands. Register indexes, constant indexes, function indexes, and
block IDs are ULEB128. Signed integer immediates use SLEB128. Type IDs
are ULEB128. The verifier checks every operand before execution.

Illustrative opcode families:

  -----------------------------------------------------------------------
  Family                  Representative opcodes  Semantics
  ----------------------- ----------------------- -----------------------
  Constants               `const.i32`,            Load a constant
                          `const.f32`,            
                          `const.string`,         
                          `const.null`            

  Moves                   `move`                  Copy a value

  Integer                 `i32.add.wrap`,         Typed integer
                          `i32.add.checked`,      operations
                          `i32.sub`, `i32.mul`,   
                          `i32.eq`                

  Float                   `f32.add`, `f32.mul`,   IEEE 754 operations
                          `f32.div`, `f32.lt`,    
                          `f32.eq`                

  Strings                 `str.concat`, `str.eq`, UTF-8 string operations
                          `str.len`               

  Collections             `array.new`,            Collection operations
                          `array.get`,            with bounds/type checks
                          `array.set`, `map.get`, 
                          `map.set`               

  Data flow               `copy`, `select`,       Value
                          `phi.copy`              movement/selection

  Calls                   `call`, `call.import`,  Local, host-import, and
                          `call.indirect`         function-reference
                                                  calls

  Objects                 `handle.get`,           Typed handles and
                          `handle.set`,           runtime type checks
                          `type.test`,            
                          `cast.checked`          

  Exceptions              `try.begin`, `try.end`, Optional structured
                          `throw`, `catch`        exception handling

  Control                 `br`, `br_if`,          Explicit block
                          `switch`, `return`,     terminators
                          `unreachable`           

  Async                   `yield`, `await`,       Optional cooperative
                          `resume`                scheduling extension

  Debug                   `trap`, `debug.break`   Trap and optional
                                                  debugger hook
  -----------------------------------------------------------------------

The final opcode table must assign numeric opcode values permanently
within a major version. Reserved opcodes must trap when executed. An
implementation must not silently reinterpret an unknown opcode.

### 6.5 Example: bytecode listing

The following is a human-readable disassembly, not the binary wire
encoding:

``` text
.func 0 demo.math::clamp01 (f32) -> f32
.reg 0 f32       ; argument value
.reg 1 f32       ; zero
.reg 2 f32       ; one
.reg 3 f32       ; max(value, zero)
.reg 4 f32       ; min(previous, one)

block0:
  const.f32 r1, 0.0
  const.f32 r2, 1.0
  f32.max r3, r0, r1
  f32.min r4, r3, r2
  return r4
```

Disassembly should show source graph node IDs when debug information is
available:

``` text
  f32.max r3, r0, r1  ; node=n_low "Clamp minimum"
```

### 6.6 Verification

A module must be verified before execution. Verification includes:

-   Structural validity of header, sections, lengths, tables, and
    indexes.
-   Type validity of registers, constants, calls, returns, and branches.
-   Valid block boundaries and exactly one terminator per block.
-   Import declarations matching the host's registered signatures and
    capabilities.
-   Stack/frame/resource limits and feature compatibility.
-   Valid exception regions and async state transitions if those
    features are enabled.
-   No illegal access to host handles or uninitialized registers.

The verifier must not trust compiler-produced bytecode. It should be
safe to load untrusted `.wbc` files. Validation should complete before
module initialization wherever possible.

### 6.7 Versioning and compatibility

-   A major version changes when old readers cannot safely interpret the
    format.
-   A minor version adds optional sections or instructions that older
    readers can skip or reject based on feature flags.
-   Required features are listed in the header; a loader rejects modules
    requiring unsupported features.
-   Semantic changes to an existing opcode are forbidden. Introduce a
    new opcode or major version instead.
-   WGT and WBC have independent version numbers.
-   Compiler builds should embed a compiler ID, source hash,
    operation-registry version, target features, and deterministic-build
    flag in `META`.

### 6.8 Security and determinism

The VM should support configurable limits for instruction count/fuel,
recursion depth, memory, allocation count, string/collection size, and
wall-clock cancellation checks. Wall-clock time is a host policy, not a
language semantic. Host imports are capability-checked. A deterministic
mode disables ambient clock/random access unless supplied as explicit
imports and defines deterministic iteration order for maps. No bytecode
should gain arbitrary native memory access by default.

------------------------------------------------------------------------

## 7. Wiret Runtime (WRT) embedding API

### 7.1 API goals

The C ABI is the stable embedding boundary. Higher-level wrappers can be
added for Rust, C++, C#, Java, and other hosts. The API uses opaque
handles, explicit ownership, length-delimited strings, status codes, and
protected execution calls.

A recommended initial C header shape:

``` c
#ifndef WIRET_H
#define WIRET_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct wrt_vm wrt_vm;
typedef struct wrt_module wrt_module;
typedef struct wrt_value wrt_value;
typedef struct wrt_error wrt_error;
typedef struct wrt_host_fn wrt_host_fn;

typedef enum {
    WRT_OK = 0,
    WRT_E_INVALID_ARGUMENT,
    WRT_E_OUT_OF_MEMORY,
    WRT_E_PARSE,
    WRT_E_VERIFY,
    WRT_E_IMPORT,
    WRT_E_TYPE,
    WRT_E_RUNTIME,
    WRT_E_TRAP,
    WRT_E_LIMIT,
    WRT_E_CANCELLED
} wrt_status;

typedef struct {
    uint32_t abi_version;
    uint64_t max_memory_bytes;
    uint64_t max_instructions;
    uint32_t max_call_depth;
    uint32_t flags;
    void *user_data;
} wrt_config;

typedef enum {
    WRT_VAL_VOID, WRT_VAL_BOOL, WRT_VAL_I32, WRT_VAL_I64,
    WRT_VAL_U32, WRT_VAL_U64, WRT_VAL_F32, WRT_VAL_F64,
    WRT_VAL_STRING, WRT_VAL_BYTES, WRT_VAL_HANDLE, WRT_VAL_ARRAY
} wrt_value_kind;

typedef struct {
    const char *data;
    size_t length;
} wrt_slice;

typedef struct {
    wrt_value_kind kind;
    union {
        uint8_t boolean;
        int32_t i32;
        int64_t i64;
        uint32_t u32;
        uint64_t u64;
        float f32;
        double f64;
        uint64_t opaque_id;
    } as;
} wrt_primitive;

typedef struct {
    const char *name;
    const char *signature;   /* canonical signature, e.g. "(string)->void" */
    uint32_t capability_id;
    uint32_t flags;           /* pure, async, deterministic, etc. */
    void *function;           /* implementation-specific callback pointer */
} wrt_import_desc;

wrt_status wrt_vm_create(const wrt_config *config, wrt_vm **out_vm);
void wrt_vm_destroy(wrt_vm *vm);

wrt_status wrt_vm_register_import(
    wrt_vm *vm, const wrt_import_desc *desc);

wrt_status wrt_module_load(
    wrt_vm *vm, const uint8_t *bytes, size_t length,
    wrt_module **out_module, wrt_error **out_error);

wrt_status wrt_module_unload(wrt_vm *vm, wrt_module *module);

wrt_status wrt_module_find_export(
    wrt_module *module, wrt_slice name, void **out_function);

wrt_status wrt_call(
    wrt_vm *vm, wrt_module *module, void *function,
    const wrt_primitive *args, size_t arg_count,
    wrt_primitive *out_result, wrt_error **out_error);

void wrt_error_destroy(wrt_error *error);
wrt_slice wrt_error_message(const wrt_error *error);
wrt_slice wrt_error_stacktrace(const wrt_error *error);

#ifdef __cplusplus
}
#endif
#endif
```

This header is a shape proposal, not a finalized ABI. In production,
avoid exposing `void *` function pointers as long-lived public
identities; use typed opaque function handles. The simple
`wrt_primitive` structure only covers primitives. Strings, arrays,
bytes, and host objects need owned value handles or a callback-scoped
borrowed-value API. The ABI must specify lifetime, thread safety, and
allocator behavior before implementation.

### 7.2 Recommended API surface

The first stable release should include these groups:

**VM lifecycle** - `wrt_vm_create`, `wrt_vm_destroy` -
`wrt_vm_set_limits` - `wrt_vm_collect_garbage` - `wrt_vm_cancel` -
`wrt_vm_get_stats`

**Modules** - `wrt_module_load_bytes` - `wrt_module_load_file` (optional
convenience API) - `wrt_module_unload` - `wrt_module_get_info` -
`wrt_module_find_export`

**Values** - constructors and readers for each primitive type -
`wrt_value_retain`, `wrt_value_release` - string/bytes access as
length-delimited slices - typed array/map accessors - host-handle
creation and retrieval with type tags

**Host imports** - register/unregister named host functions with typed
signatures - declare capabilities and deterministic/pure/async flags -
provide per-VM user data and per-import user data - protected callback
invocation and error propagation

**Execution** - `wrt_call` - `wrt_call_async` / continuation API if
async is enabled - instruction/fuel budgets - cancellation and deadline
hooks - trace/debug hooks

**Diagnostics** - structured error code, message, stack trace, source
location, graph node ID - verifier diagnostics and warnings - logging
callback

### 7.3 Ownership rules

Recommended ownership contract:

-   The VM owns modules loaded into it unless the API explicitly returns
    a retained module handle.
-   Destroying a VM invalidates all module, function, and borrowed-value
    handles from that VM.
-   Returned owned values must be released by the caller.
-   Borrowed string/byte slices remain valid only until the next API
    call on the owning handle or until the callback returns, as
    documented.
-   A host callback may not retain a borrowed value unless it calls
    `retain`.
-   Errors are immutable owned objects and must be destroyed.
-   No memory allocated by one runtime allocator may be freed directly
    by the host unless a matching release API is called.

### 7.4 Host callback model

A host import declares its exact signature and required capability.
Example conceptual callback:

``` c
static wrt_status console_write(
    wrt_call_context *ctx,
    const wrt_value *args,
    size_t argc,
    wrt_value *out_result,
    wrt_error **out_error)
{
    wrt_slice text = wrt_value_as_string(args[0]);
    fwrite(text.data, 1, text.length, stdout);
    *out_result = wrt_value_void();
    return WRT_OK;
}
```

The real ABI should avoid returning structs by value across all platform
boundaries if portability becomes problematic. The host callback
executes inside a protected runtime boundary. If it fails, it returns a
status and optional error; it must not unwind a C++ exception or
language exception through the C ABI. The runtime should detect
re-entrant calls and either support them explicitly or reject them with
a documented status.

### 7.5 Threading

The initial policy should be conservative:

-   A VM instance is single-thread-affine by default.
-   Multiple VMs may execute concurrently.
-   A VM may opt into serialized cross-thread calls if the
    implementation supports it.
-   Values and module handles are not assumed thread-safe.
-   Parallel graph execution is a future opt-in feature, not implicit
    behavior from graph fan-out.
-   Async operations suspend through explicit continuations/scheduler
    integration; they do not secretly create threads.

This keeps semantics predictable and avoids data races in host objects.

### 7.6 Garbage collection and host objects

Use a tracing garbage collector for Wiret-managed reference values, with
explicit roots at active frames, globals, retained host values, and
registered host roots. Hosts should not depend on finalizer timing. Host
objects are represented by typed opaque handles and optional
retain/release callbacks. The runtime must define whether a host handle
is weak, strong, or borrowed; default to strong references with explicit
release semantics.

### 7.7 Engine integration

For game-engine embedding, expose engine-specific imports in separate
modules such as `engine.actor`, `engine.input`, and `engine.ui`. Do not
bake engine object layouts into the portable VM. An engine import
registry defines pin signatures, display labels, editor categories,
capability requirements, and runtime callbacks. A graph that uses
engine-only types should declare its target environment and fail clearly
when loaded in a VM without those imports.

------------------------------------------------------------------------

## 8. Editor behavior and collaboration

### 8.1 Graph editor contract

The editor should treat WGT as canonical storage, not merely an export
format. It must preserve IDs and unknown metadata. Editing a node's
position should update only layout attributes. Changing a display title
should not change the operation name. A semantic edit should update the
graph structure and, when necessary, the operation-specific attributes.

### 8.2 Merge strategy

Text merge is useful but cannot fully resolve concurrent graph edits.
The recommended merge algorithm is:

1.  Perform a normal three-way text merge.
2.  Parse the result and identify duplicate IDs, missing endpoints,
    invalid pins, and conflicting single-input connections.
3.  If valid, canonicalize and open normally.
4.  If conflicts are semantic, present a graph-aware merge view keyed by
    stable IDs.
5.  Never silently discard an edge, node, or unknown metadata to "fix" a
    conflict.

To reduce churn, the editor should not reorder unrelated nodes or
regenerate identifiers. Layout conflicts may use last-writer-wins only
as an explicit user choice; semantic conflicts should require
resolution.

### 8.3 AI generation and editing

AI tools should interact with a schema-aware editing API when possible,
not regenerate an entire file from scratch. The editing API should
support operations such as:

-   create node with operation ID and initial pin values
-   connect output to input
-   set node property
-   move node
-   add comment/group
-   validate graph
-   format canonical WGT

Each operation should return diagnostics and a minimal diff. The tool
should be able to request the operation registry and graph schema rather
than guessing pin names. For robust automated edits, include an expected
document hash or revision token so stale changes can be rejected.

### 8.4 Stable visual rendering

To ensure collaborators see the same graph:

-   Persist node positions, dimensions where relevant, group bounds,
    comment placement, routing hints, zoom, and pan.
-   Define coordinate units and the editor's layout grid in project
    settings.
-   Store layout metadata separately from semantics conceptually, even
    if serialized in the same file.
-   Avoid automatic layout on every open; offer it as a command.
-   Specify the editor version or layout algorithm version when geometry
    interpretation changes.
-   Use deterministic pin ordering and stable wire routing where
    possible.

Exact pixel identity across different fonts, DPI scales, and editor
versions cannot be guaranteed solely by the file format. Wiret should
guarantee the same **logical layout coordinates and graph structure**,
while editors may differ slightly in rasterization.

------------------------------------------------------------------------

## 9. Standard library proposal

The portable standard library should be small and explicit.

### `core`

Primitive arithmetic, comparisons, conversion, boolean logic, strings,
arrays, maps, option values, errors, control flow, function calls, and
basic math.

### `core.io`

No ambient I/O by default. Optional host-provided capabilities for
streams and file access.

### `core.time`

Clock access through an imported capability, not an implicit global
clock.

### `core.random`

Randomness through an explicit RNG state or host capability.
Deterministic seeded RNG should be available.

### `core.async`

Only if the scheduler and continuation ABI are implemented. Async is not
implied by latent-looking nodes in an editor.

### `host.*`

Host-registered APIs. Host modules publish signatures, capability
requirements, deterministic/pure flags, and documentation.

### `engine.*`

Optional engine integrations. These are not part of portable core and
should be versioned separately.

------------------------------------------------------------------------

## 10. Minimal conformance requirements

An implementation can claim **Wiret Text Reader** conformance if it
parses the supported WGT version and preserves unknown metadata.

It can claim **Wiret Editor** conformance if it preserves stable IDs,
graph semantics, metadata, and canonical serialization.

It can claim **Wiret Compiler** conformance if it validates graph
typing/control flow and emits WBC accepted by a conforming verifier.

It can claim **Wiret Runtime** conformance if it verifies WBC,
implements the required core opcodes, enforces declared limits, and
provides the documented C ABI semantics.

A full conformance suite should include: - parser and formatter golden
tests - type-checking and invalid-edge tests - graph-to-block lowering
tests - bytecode verification fuzzing - cross-platform serialization
fixtures - runtime arithmetic, control flow, errors, and resource-limit
tests - C ABI ownership and callback tests - deterministic build
checks - round-trip tests proving layout/metadata preservation

------------------------------------------------------------------------

## 11. Recommended implementation roadmap

### Phase 1 --- stable graph interchange

Define the WGT grammar, core type system, operation registry schema,
stable IDs, canonical formatter, diagnostics, and graph validation.
Build a CLI that parses, validates, formats, and produces graph
summaries. Do not start with bytecode optimization.

### Phase 2 --- compiler and interpreter

Implement TGIR, typed basic blocks, a register-based WBC instruction
set, verifier, disassembler, and a reference interpreter. Keep the first
opcode set small and fully specified.

### Phase 3 --- embedding API

Stabilize the C ABI, import registry, owned/borrowed values, error
handling, limits, cancellation, and host callbacks. Add examples in C
and C++.

### Phase 4 --- visual editor

Build graph loading/saving, deterministic layout metadata, node registry
discovery, diagnostics overlay, breakpoints, and graph-aware merge
support.

### Phase 5 --- engine and AI integrations

Add engine-specific node packs, schema-aware editing operations, AI
change proposals, validation feedback, and reviewable minimal diffs.

### Phase 6 --- portability and security

Fuzz parsers/verifiers, add bytecode compatibility tests, sandbox
profiles, deterministic execution mode, and conformance suites before
treating WBC as a stable interchange artifact.

------------------------------------------------------------------------

## 12. Open decisions before freezing version 1.0

The following should be decided through prototypes rather than
prematurely frozen:

1.  Whether strings and collections are immutable values, mutable
    references, or both.
2.  Whether exceptions are core or replaced by explicit `result<T, E>`
    values.
3.  Whether async/latent nodes use continuations, coroutines, or a
    scheduler-owned task type.
4.  Whether WBC is register-based (recommended for graph/SSA lowering)
    or stack-based (simpler encoding but less direct for graph values).
5.  The exact binary section schema, opcode numbers, and canonical
    LEB128 rules.
6.  The complete C ABI ownership model and whether the runtime embeds a
    GC or uses reference counting.
7.  Whether graph-level parallelism exists, and what memory model it
    promises.
8.  How user-defined structs, generics, interfaces, and versioned type
    evolution work.
9.  Whether source compatibility is guaranteed across operation registry
    versions.
10. The security profile for untrusted user-created graphs and bytecode.

**Recommendation:** ship a narrow, strongly specified core first. The
most important early success metric is not raw runtime speed; it is that
the editor can round-trip graphs without losing identity or layout, Git
diffs remain reviewable, and the verifier can reject malformed programs
predictably.

---

# Wiret: Language and Runtime Design (Notes)

My recommendation is to design Wiret as a graph-native intermediate language with a human-readable, canonical text representation, rather than as a conventional programming language that happens to describe graphs.

That distinction is important. Wiret needs to serve three audiences simultaneously:

* Visual editor users need familiar nodes, pins, execution wires, comments, groups, and predictable graph layouts.

* Developers using Git need stable identifiers, readable diffs, reliable merges, and minimal unrelated changes when a graph is edited.

* Compilers and AI agents need explicit types, well-defined semantics, deterministic serialization, and a format that can be parsed and generated without guessing.

I've prepared a first-pass specification covering the text syntax, compiler architecture, bytecode format, embeddable C runtime API, and collaboration model.

Wiret Language Specification — Draft 0.1

Markdown document · approximately 43 KB

Includes grammar, graph examples, bytecode sections and opcodes, a C API proposal, validation rules, editor metadata, and an implementation roadmap. Download the Wiret specification

The design draws on the resources you supplied: Unreal Engine Blueprints for visual graph concepts, LLVM IR and the JVM/Wasm specifications for compilation and execution, DOT and GML for graph serialization, and the Lua C API for embedding. The document is a proposed design, not a claim of compatibility with those existing formats.

## 1. The proposed architecture

Wiret Graph Editor

Nodes, pins, wires, comments, groups, visual layout

Wiret Graph Text (WGT)

Canonical, readable, version-control-friendly source

Typed Graph IR (TGIR)

Type checking, control-flow analysis, SSA-like values, basic blocks

Wiret Bytecode (WBC)

Portable binary modules with explicit types and verified instructions

Wiret Runtime (WRT)

Embeddable VM, host imports, memory management, diagnostics and execution limits

The most important design choice is that the graph is the source of truth, and the text is its canonical serialization. Users can work entirely in the visual editor, while Git and AI tools operate on the same underlying representation.

## 2. What the text should look like

I recommend named declarations, explicit node operations, typed pins, explicit edges, and lightweight attributes.

For example, a graph that adds two numbers could look like this:

wiret

```
wiret 0.1
module demo.math

graph function add(a: f32, b: f32) -> f32 [id="g_add"] {
  node n_add: core.f32.add (
    in a: f32,
    in b: f32,
    out value: f32
  ) [id="n_add", title="Add", pos=[320, 160]]

  node n_return: core.return (
    in value: f32
  ) [id="n_return", pos=[560, 160]]

  edge d_01: data g_add.a -> n_add.a
  edge d_02: data g_add.b -> n_add.b
  edge d_03: data n_add.value -> n_return.value
}
```

This syntax has several useful properties:

* `core.f32.add` specifies what the operation means.

* `title="Add"` specifies what the editor displays.

* `pos=[320, 160]` preserves the node's position.

* The edges explicitly connect named pins.

* Stable IDs let tools identify nodes even after they move or change labels.

Unlike JSON, the document reads like a description of a graph. Unlike ordinary source code, it retains the information needed to reconstruct the visual editor.

## 3. Three rules I'd establish early

First, separate semantics from presentation. Node operations, types, connections, and control flow determine behavior. Layout, colors, comments, and editor preferences are stored alongside them but do not change execution. Preserve unknown metadata when files are loaded and saved.

Second, make the format deterministic. Saving an unchanged graph should not reorder nodes, regenerate IDs, or modify unrelated metadata. This is essential for meaningful Git diffs and reliable AI-generated patches.

Third, make validation part of the language design. Invalid connections, incompatible pin types, missing required inputs, unsupported node operations, and malformed bytecode should produce structured errors tied to specific nodes and pins. The runtime must verify bytecode rather than trusting the compiler.

## 4. What the specification covers

| Component      | Proposed design                                                                       |
| -------------- | ------------------------------------------------------------------------------------- |
| Text syntax    | WGT declarations, typed pins, graph edges, attributes, metadata, canonical formatting |
| Compiler       | Typed Graph IR, explicit control-flow blocks, SSA-like value handling                 |
| Bytecode       | Versioned WBC binary modules, typed register VM, opcode families, verification        |
| Embedding      | C ABI, VM lifecycle, host imports, values, errors, resource limits                    |
| Collaboration  | Stable IDs, graph-aware merging, layout persistence, schema-aware AI editing          |
| Implementation | Conformance testing, security considerations, staged development roadmap              |

The bytecode and C API sections are architectural proposals; their binary encodings, exact opcode assignments, ownership details, and ABI signatures need to be finalized and tested before declaring a stable 1.0 specification.

My strongest recommendation: implement the text format, node registry, stable identities, and round-trip behavior first. Once the editor can serialize and reconstruct a graph without losing semantic or visual information, the compiler and runtime can evolve behind that stable foundation.
