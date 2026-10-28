# Wiret Language Design — Core Specification (Draft 0.1)

**Status:** Design proposal synthesizing and refining the two submitted drafts.  
**Goals:** Graph-first visual language with a canonical, diffable text representation (WGT); compiles to verified portable bytecode (WBC); executes in a small, embeddable, capability-based runtime (WRT).

## 1. Design principles (summary)

1. The visual graph is the source of truth. WGT is its durable, human- and machine-readable form.
2. Semantics (nodes, pins, edges, types, operations) are completely separate from presentation (position, title, color, groups, comments).
3. Stable, persistent IDs for nodes, pins, edges, and graphs. IDs never change because of layout or label edits.
4. Canonical serialization: same graph → same text (ordering, formatting, attribute order).
5. Explicit types, explicit execution vs data flow, no silent coercions beyond documented lossless conversions.
6. Deterministic compilation by default. Same normalized source + compiler version + features → equivalent bytecode.
7. Host capabilities are explicit imports, never ambient.
8. Every diagnostic points to a concrete graph location (module, graph, node, pin, edge).
9. Verifier rejects malformed or untrusted bytecode before execution.
10. First implementation prioritizes round-trip fidelity, validation, and reviewable diffs over performance.

## 2. Text syntax — Wiret Graph Text (WGT)

### 2.1 File model

- One module per `.wrt` file.
- Module name is a dotted identifier (`game.player`, `math.utils`).
- Optional project files: `wiret.toml`, `wiret.lock`, `.wbc` (bytecode), `.wdbg` (debug sidecar).

### 2.2 Grammar (illustrative EBNF)

```ebnf
document     = "wiret", version, newline, "module", ident, [attrs], newline, {decl} ;
decl         = import | type | const | graph | meta ;
import       = "import", string, ["as", ident], [attrs], newline ;
type         = "type", ident, "=", type_expr, [attrs], newline ;
const        = "const", ident, ":", type_expr, "=", literal, [attrs], newline ;
graph        = "graph", kind, ident, "(", [params], ")", ["->", type_expr], [attrs], "{", {item}, "}" ;
kind         = "function" | "event" | "macro" ;
item         = node | edge | region | note | meta ;
node         = "node", ident, ":", operation, [pin_list], [attrs], newline ;
pin_list     = "(", pin, {",", pin}, ")" ;
pin          = ("in" | "out"), ident, ":", type_expr, ["=", literal], [attrs] ;
edge         = "edge", ident, ":", ("exec" | "data"), endpoint, "->", endpoint, [attrs], newline ;
endpoint     = ident, ".", ident ;   /* node.pin or graph.param */
region       = "region", ident, [attrs], "{", {item}, "}" ;
note         = "note", ident, string, [attrs], newline ;
meta         = "meta", ident, "=", value, newline ;
attrs        = "[", attr, {",", attr}, "]" ;
attr         = ident, "=", value ;
```

- Whitespace is insignificant except that top-level declarations are newline-terminated outside balanced `()[]{}`.
- `#` starts a line comment.
- Strings use JSON-compatible escaping.
- Numeric literals are locale-independent.
- Recommended indentation: two spaces. Canonical writers emit a final newline and stable declaration order (creation order preferred).

### 2.3 Core types (portable)

`void`, `bool`, `i32`, `i64`, `u32`, `u64`, `f32`, `f64`, `string` (UTF-8, value), `bytes`, `option<T>`, `array<T>`, `map<K,V>` (K hashable), `struct Name`, `handle<Name>`, `func<(T…)->R>`.

Extensions (vectors, entities, etc.) must declare stable type IDs and host-boundary rules.

### 2.4 Example (clamp)

```wiret
wiret 0.2
module demo.math [target="portable"]

graph function clamp01(value: f32) -> f32 [public=true, id="g_clamp"] {
  node n_zero: core.f32.const (out value: f32 = 0.0)
    [id="n_zero", title="Zero", pos=[80, 220]]

  node n_one: core.f32.const (out value: f32 = 1.0)
    [id="n_one", title="One", pos=[80, 340]]

  node n_low: core.f32.max (
    in a: f32, in b: f32, out value: f32
  ) [id="n_low", title="Clamp min", pos=[340, 220]]

  node n_high: core.f32.min (
    in a: f32, in b: f32, out value: f32
  ) [id="n_high", title="Clamp max", pos=[570, 220]]

  node n_ret: core.return (in value: f32)
    [id="n_ret", title="Return", pos=[800, 220]]

  edge e1: data n_zero.value -> n_low.b
  edge e2: data n_low.value  -> n_high.a
  edge e3: data n_one.value  -> n_high.b
  edge e4: data n_high.value -> n_ret.value

  meta layout.graph [zoom=0.9, pan=[0,0], grid=16]
}
```

### 2.5 Execution + data example

```wiret
wiret 0.2
module demo.greeting

graph function greet(name: string) -> void [public=true, id="g_greet"] {
  node n_entry: core.entry () [id="n_entry", pos=[64,120]]
  node n_pfx:   core.string.const (out value: string = "Hello, ") [id="n_pfx", pos=[80,300]]
  node n_join:  core.string.concat (in left: string, in right: string, out value: string)
    [id="n_join", pos=[340,300]]
  node n_log:   host.console.write (in value: string) [id="n_log", capability="console.write", pos=[600,160]]
  node n_exit:  core.exit () [id="n_exit", pos=[840,160]]

  edge x1: exec n_entry.then -> n_log.exec
  edge x2: exec n_log.then   -> n_exit.exec
  edge d1: data n_pfx.value  -> n_join.left
  edge d2: data g_greet.name -> n_join.right
  edge d3: data n_join.value -> n_log.value
}
```

### 2.6 Edge and pin rules (summary)

- `exec` edges connect execution pins only; fan-out requires an explicit sequence/fork node.
- `data` edges connect compatible data pins; single-input pins accept at most one incoming edge unless the operation defines merge semantics.
- Cycles in pure data flow are illegal unless expressed through loop/phi nodes.
- Unconnected required inputs are errors (or use declared defaults).
- Every executable path must terminate, return, or yield according to graph kind.

### 2.7 Metadata namespaces

`layout.*`, `editor.*`, `doc.*`, `debug.*`, `vendor.<name>.*`. Unknown metadata must be preserved by tools that do not understand it. Only semantic attributes and `id` affect program meaning.

### 2.8 Canonical formatting rules

UTF-8 + LF, two-space indent, stable declaration order, fixed attribute order (semantic → id → title → layout → extensions), lowercase booleans, canonical numeric form, no ID regeneration, preserve unknown attributes. Canonical writers are required; parsers tolerate harmless whitespace differences.

## 3. Compilation model (brief)

1. Parse WGT → preserve IDs and metadata.
2. Lower to **Typed Graph IR (TGIR)**: resolve types, validate pins/edges, convert control-flow nodes into basic blocks with explicit terminators, introduce block parameters for path-dependent values (SSA-like).
3. Emit **WBC** (verified binary) + optional debug mapping.

Pure data nodes are evaluated on demand in dependency order. Effectful nodes execute only when their exec input is reached; the compiler may not reorder observable effects.

## 4. Bytecode specification — Wiret Bytecode (WBC)

### 4.1 Goals

Portable, versioned, easily verified, compact enough for embedding. Not a direct dump of WGT. Prefer verification simplicity and debuggability over extreme density in the first version.

### 4.2 Binary layout

All multi-byte integers are unsigned LEB128 unless fixed-width is stated.

**Header (fixed):**

| Field          | Size     | Meaning                          |
|----------------|----------|----------------------------------|
| Magic          | 4 bytes  | `WBC\0`                          |
| Major          | u16 LE   | Incompatible format version      |
| Minor          | u16 LE   | Compatible additions             |
| Flags          | u32 LE   | Feature bits                     |
| Header size    | u32 LE   | Length of header                 |
| Section count  | u32 LE   | Number of sections               |

**Sections** (ascending ID order, length-delimited):

| ID | Name  | Required | Contents                                      |
|----|-------|----------|-----------------------------------------------|
| 1  | STRS  | yes      | UTF-8 string table                            |
| 2  | TYPE  | yes      | Type descriptors                              |
| 3  | IMPT  | yes      | Imported modules / host capabilities          |
| 4  | CNST  | yes      | Constants                                     |
| 5  | FUNC  | yes      | Function signatures, register counts, locals  |
| 6  | CODE  | yes      | Instructions + basic-block tables             |
| 7  | EXPT  | no       | Exports                                       |
| 8  | DATA  | no       | Immutable data blobs                          |
| 9  | DBG   | no       | Node IDs, source spans, instruction→node map  |
| 10 | META  | no       | Compiler ID, source hash, features, etc.      |

Unknown optional sections are skipped; unknown required sections or malformed lengths cause load failure. Indexes are bounds-checked before allocation.

### 4.3 Execution model

Typed **register VM**. Each function declares a register count and typed register map. Instructions operate on numbered registers. Frames are created on call. Control flow uses an explicit block table; every block has exactly one terminator; no fall-through.

### 4.4 Instruction families (illustrative)

- Constants: `const.i32`, `const.f32`, `const.string`, `const.null`
- Moves / selection: `move`, `select`, `phi.copy`
- Integer / float arithmetic and comparisons (with explicit wrap vs checked variants where relevant)
- Strings, arrays, maps (bounds- and type-checked)
- Calls: `call`, `call.import`, `call.indirect`
- Handles / casts: `handle.get/set`, `type.test`, `cast.checked`
- Control: `br`, `br_if`, `switch`, `return`, `unreachable`
- Optional: structured exceptions, `yield`/`resume` for cooperative async
- Debug: `trap`, `debug.break`

Opcodes are permanently assigned within a major version. Unknown or reserved opcodes trap. The verifier checks every operand and type before execution.

### 4.5 Verification requirements

Structural validity, type safety of registers/constants/calls/returns/branches, single terminator per block, import signature matching, resource limits, no illegal host access or use of uninitialized registers. Verification must succeed before any module initialization or execution. Untrusted `.wbc` files are assumed hostile.

### 4.6 Versioning & security

Major version = incompatible change. Minor = optional features. Required features are declared in the header. Semantic changes to existing opcodes are forbidden. Configurable fuel, memory, recursion, and allocation limits. Deterministic mode disables ambient time/randomness unless supplied as imports and defines map iteration order.

## 5. Runtime API — Wiret Runtime (WRT)

### 5.1 Goals

Small, stable C ABI suitable for embedding in engines, tools, and host applications. Opaque handles, explicit ownership, length-delimited strings, status codes, protected execution, capability-checked imports.

### 5.2 Core types and status

```c
typedef struct wrt_vm      wrt_vm;
typedef struct wrt_module  wrt_module;
typedef struct wrt_value   wrt_value;
typedef struct wrt_error   wrt_error;

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
```

Configuration includes ABI version, memory/instruction/call-depth limits, feature flags, and user data.

### 5.3 Essential API surface

**VM lifecycle**  
`wrt_vm_create`, `wrt_vm_destroy`, `wrt_vm_set_limits`, `wrt_vm_collect_garbage`, `wrt_vm_cancel`, `wrt_vm_get_stats`

**Modules**  
`wrt_module_load` (bytes), optional `wrt_module_load_file`, `wrt_module_unload`, `wrt_module_find_export`, `wrt_module_get_info`

**Values**  
Constructors/readers for primitives, `wrt_value_retain` / `wrt_value_release`, length-delimited string/bytes access, typed collection accessors, typed host handles.

**Host imports**  
Register named functions with canonical signatures, capability IDs, and purity/async/deterministic flags. Protected invocation; errors do not unwind through the C ABI.

**Execution**  
`wrt_call` (and optional async/continuation entry points), fuel/cancellation hooks, structured error objects that can carry module/function/offset/node-ID information when debug data is present.

**Diagnostics**  
Error code, message, stack trace, source location, graph node ID.

### 5.4 Ownership and threading (first version)

- VM owns loaded modules unless a retained handle is returned.
- Destroying a VM invalidates all handles derived from it.
- Returned owned values must be released by the caller.
- Borrowed slices are valid only until the next API call on the owning object (or until a host callback returns).
- Default: single-thread-affine VMs. Multiple VMs may run concurrently. Values and modules are not assumed thread-safe.
- Host callbacks must not throw C++/language exceptions across the ABI boundary.

### 5.5 Host callback shape (conceptual)

```c
typedef wrt_status (*wrt_host_fn)(
    wrt_call_context *ctx,
    const wrt_value *args, size_t argc,
    wrt_value *out_result,
    wrt_error **out_error);
```

The runtime supplies a protected context; the host returns status + optional owned error.

### 5.6 Engine integration

Engine-specific functionality lives in separate import modules (`engine.actor`, `engine.input`, …). Graphs that require engine types declare the required target environment and fail clearly when the imports are absent.

## 6. Minimal conformance

- **Text Reader**: parses supported WGT and preserves unknown metadata.
- **Editor**: preserves IDs, ng Wiret_Language_Specifications_Proposal_3.md…]()
