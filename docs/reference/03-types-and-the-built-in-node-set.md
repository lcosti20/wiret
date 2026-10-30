## 3. Types and the built-in node set

### 3.1 Types

| Type | Representation | Notes |
| --- | --- | --- |
| `bool` | i32 (0 or 1) | Default `false`. |
| `i8 u8 i16 u16 i32 u32` | i32 slot | Narrow types wrap on arithmetic (`Convert` is needed to narrow explicitly). Unsigned types use unsigned compare, divide, remainder and shift. |
| `i64 u64` | i64 slot | Same rules. |
| `f32 f64` | IEEE-754 | In deterministic mode, NaN is canonical and arithmetic is fully specified (section 4.10). |
| `string` | immutable UTF-8 reference | Never null; default is the empty string. Indexing is by byte offset via `std.string`. |
| `enum` | its underlying integer (default `i32`) | Names are kept in the `name` custom section for editors and reflection. |
| `struct` | immutable heap record with value semantics | Equality is structural. "Setting" a field makes a new struct (`WithField`). |
| `class` | nullable reference | Equality is identity. Default `null`. |
| `array<T>` | growable, zero-based; **value type** | Copied on assignment, argument passing and return. The VM copies lazily (copy-on-write, section 4.9), so two variables never alias one array. Equality is element-wise. |
| `set<T>`, `map<K,V>` | insertion-ordered; **value types** | Same copy rules as arrays. Iteration order is insertion order, never hash order. Keys are primitives, `string`, enums or structs of those. Equality ignores order. |
| `delegate<(A)->(R)>` | reference to a function plus optional bound receiver | Single-cast. |
| `dispatcher<(A)>` | reference to an ordered handler list | Multicast; the `dispatcher` member of a class. |
| `extern type` | host handle (index plus generation) | `IsValid` is false once the host destroys the object. |
| `std.Signal`, `std.Fault` | built-in opaque classes | Used by `Await` and `Try`. |

Wires connect a source pin to a destination pin of the **same type**, or of a **supertype** (a class wire may feed a pin of its superclass or of an interface it implements). There is no other implicit conversion.

### 3.2 Conversions

The editor, like Blueprint's, offers to insert a conversion node when you connect two compatible but different types. In Wiret that node is real and visible in the text: `Convert<From, To>`.

| From | To | Behaviour |
| --- | --- | --- |
| integer | integer | Wraps (truncates, or sign/zero-extends). |
| integer | float | Nearest representable value. |
| float | integer | Truncates toward zero, **saturating**; NaN becomes 0. Never faults. |
| f64 / f32 | f32 / f64 | IEEE demote / promote. |
| bool | integer | 0 or 1. |
| integer | bool | Non-zero is true. |
| enum | its integer type, and back | Back-conversion does not check that the value names a member. |
| bool, integer, float | string | Culture-independent decimal text. Floats use the shortest text that round-trips. |
| string | number or bool | Not a `Convert`. Use `std.string.TryParse<T>`, which returns `(ok: bool, value: T)`. |

### 3.3 Built-in node kinds

Pin names are fixed per kind. Pure binary operators use inputs `a`, `b` and output `result`. `T` is the type argument. "Impure" kinds have the exec input `in` unless noted.

**Control flow**

| Kind | Pins | Behaviour |
| --- | --- | --- |
| `Entry` | out: the graph's parameters; exec out `then` | Starts a function or event. In a macro, has one exec output per `exec` parameter. |
| `Return` | in: the graph's results | Leaves the function. `Return` has an exec input in every function, including `@pure` ones: a pure function's exec flow is internal and invisible to its callers. |
| `Branch` | in `cond: bool`; exec out `then`, `else` | Two-way choice. |
| `Sequence` | `@count(n)`; exec out `then0` .. `then{n-1}` | Runs `then0`'s chain to its end, then `then1`'s, and so on. |
| `Switch<T>` | in `value: T`; `@cases(...)`; exec out `case0`.., `default` | `T` is an integer, enum, string or bool. |
| `Select<T>` | pure; in `cond`, `a`, `b`; out `result` | Both `a` and `b` are evaluated (they are pure). |
| `Try` | exec out `body`, `fault`, `then`; out `message: string`, `code: i32` | Runs `body`. Normal end goes to `then`. A catchable fault inside it goes to `fault`. |
| `Throw` | in `message: string`, `code: i32` | Raises a catchable fault. No exec out. |
| `Delay` | in `seconds: f64`; exec out `then` | **Latent.** Suspends the fiber for virtual time. |
| `Yield` | exec out `then` | **Latent.** Resumes on the next `wr_advance`. |
| `Await` | in `signal: std.Signal`; exec out `then` | **Latent.** Resumes when the host fires the signal. |
| `Macro` | symbol: macro name; pins from its signature | Inlined at compile time. |
| `Exit` | symbol: macro exec output; in: its data outputs | Macro-only. Leaves the macro through that exec output (a jump) and assigns the data outputs bound on the node. It never changes the continuation stack, so a continuation the macro pushed stays pending. On the first output of a Sequence it runs the caller's chain as a subroutine (see ForRange in section 2.6 and the trace in section 4.2). |
| `Reroute<T>` | in `in`, out `out` | Visual only. |

**Variables, fields and objects**

| Kind | Pins | Behaviour |
| --- | --- | --- |
| `GetLocal` / `SetLocal` | `value` | Locals declared with `local`. `SetLocal` is impure. |
| `GetVar` / `SetVar` | `value` | Module-level `var`. |
| `GetField` | in `obj`; out `value` | Pure node with `reads` purity (section 4.3): re-evaluated at each consumer and sees the state at that consumer's evaluation point. Faults on a null class reference. Not allowed in a `@pure` function (`E0304`). |
| `SetField` | in `obj`, `value` | Impure. On a struct use `WithField`. |
| `WithField` | pure; in `obj`, `value`; out `result` | Returns a copy of a struct with one field replaced. |
| `MakeStruct` / `BreakStruct` | one pin per field | Pure. |
| `New` | out `result`; exec out `then` | Allocates a class instance with declared defaults. Impure because it creates identity. |
| `Cast` | pure; in `obj`; out `result`, `ok: bool` | `result` is null when the cast fails. |
| `IsValid` | pure; in `obj`; out `result: bool` | Non-null and, for host handles, still alive. |
| `Convert<From, To>` | pure; in `value`; out `result` | See section 3.2. |
| GetState / SetState | value | Persistent slots declared with state (section 2.3). SetState is impure. |

**Arithmetic, comparison, logic** (all pure)

| Kinds | Types | Notes |
| --- | --- | --- |
| `Add Sub Mul Div Rem Min Max` | `<T>` any number | Integer `Div`/`Rem` fault on zero. Integer overflow wraps. |
| `Neg Abs` | `<T>` any signed number or float | Input `value`. |
| `Eq Ne` | `<T>` number, bool, string, enum, struct, class, array, set, map (compared element-wise) | Output `bool`. |
| `Lt Le Gt Ge` | `<T>` number, string (ordinal), enum | Output `bool`. |
| `And Or Xor Not` | bool | Not short-circuiting. |
| `BitAnd BitOr BitXor BitNot Shl Shr` | `<T>` integer | Shift counts are masked to the type's width. |

**Containers**

| Kind | Notes |
| --- | --- |
| `MakeArray<T>` | Pure. `@count(n)`, inputs `item0` ... |
| `ArrayGet<T>`, `ArrayLength<T>` | Pure. Out-of-range index is a fault. |
| `ArraySet<T>`, `ArrayAdd<T>`, `ArrayInsert<T>`, `ArrayRemove<T>`, `ArrayClear<T>` | Impure. They change a **place**: the symbol names a local, a module variable, or a field. Examples: `ArrayAdd<i32> acc (item: x)` and `ArrayAdd<i32> Player.items (obj: p, item: x)`. Targeting anything else, such as a call result, is `E0130`. Arrays are value types (section 4.9), so no other variable sees the change. |
| `MapFind<K,V>` | Pure. Out: `value`, `found`. A missing key gives the zero value and `found = false`. |
| `MapHas`, `MapLength`, `MapKeyAt`, `MapValueAt` | Pure. The `At` kinds index by insertion order, which is how `ForEach` over a map is built. |
| `MapSet`, `MapRemove`, `MapClear` | Impure, and change a place exactly like the array mutators. |
| `SetHas`, `SetLength`, `SetAt` / `SetAdd`, `SetRemove`, `SetClear` | Same pattern. |
| `std.array.Append<T>`, `std.array.With<T>`, ... | Pure functional forms that return the updated container and change nothing, for use inside `@pure` functions. |

**Calls and events**

| Kind | Pins | Behaviour |
| --- | --- | --- |
| `Call` | symbol: function, method or extern; its parameters and results | Pure node if the callee is `@pure`, `@reads`, or a native flagged effect-free; otherwise impure. A method call has `self` as its first input; dispatch is virtual unless `@final`, and via the interface when the symbol names an interface method. |
| `CreateDelegate` | pure; symbol: function; optional `target`; out `result` | Binds a function (and receiver) into a delegate. |
| `Invoke<D>` | `D` is a delegate type; in `delegate` plus the arguments | Impure. |
| `Bind`, `Unbind` | symbol: dispatcher; in `obj`, `handler: delegate` | Impure. |
| `Broadcast` | symbol: dispatcher; in `obj` plus the arguments | Impure. Handlers run in bind order. A fault in one handler is reported to the host and does not stop the others. |

### 3.4 The standard library

The VM ships these namespaces as natives (callable through `Call`) and as Wiret source:

- `std.math`: `Sqrt`, `Pow`, `Sin`, `Cos`, `Atan2`, `Floor`, `Ceil`, `Round`, `Clamp<T>`, `Lerp`, ... (pure).
- `std.string`: `Concat`, `Length`, `Substring`, `Find`, `Format`, `TryParse<T>`, `Split`, ... (pure).
- `std.array`, `std.map`: `Equals`, `Sort<T>` (stable, caller supplies a comparison delegate), `IndexOf<T>`, ...
- `std.random`: an explicit-state generator class (`New`, `NextI32`, `NextF64`). There is **no ambient randomness, clock or I/O**. The host provides any of those as natives, which keeps modules replayable.
- `std.flow` (macros written in Wiret): `ForRange`, `ForEach<T>`, `ForEachMap<K,V>`, `While`, `DoOnce`, `DoN`, `Gate`, `FlipFlop`, `MultiGate`, `Retriggerable`.

### 3.5 The node registry

The kinds in section 3.3 and every `std.*` function are described by a **registry**: a versioned, machine-readable JSON file that ships with the compiler (`wiretc schema --json` prints it). The registry, not the prose tables in this document, is the authority on pin names, pin types, defaults, purity and display names. Editors build their palettes from it, the compiler uses it to expand a `Kind` into pins, and LLM tooling should read it instead of guessing pin names.

```json
{ "registry": "wiret.core", "version": "1.0",
  "kinds": [
    { "kind": "Branch", "display": "Branch", "category": "Flow", "purity": "impure",
      "pins": [
        { "name": "in",   "dir": "in",  "type": "exec" },
        { "name": "cond", "dir": "in",  "type": "bool", "default": false },
        { "name": "then", "dir": "out", "type": "exec" },
        { "name": "else", "dir": "out", "type": "exec" } ] },
    { "kind": "Add", "display": "Add", "category": "Math", "purity": "pure",
      "typeParams": { "T": "number" },
      "pins": [
        { "name": "a",      "dir": "in",  "type": "T", "default": 0 },
        { "name": "b",      "dir": "in",  "type": "T", "default": 0 },
        { "name": "result", "dir": "out", "type": "T" } ] }
  ] }
```

Rules:

- A `.wiret` file never re-declares the pins of a registry kind. This keeps one line per node and one source of truth. Pins that depend on attributes (`@count`, `@cases`) are described in the registry by a pin pattern such as `then{i}`.
- Functions, methods, events and `extern func` declarations get generated registry entries from their signatures plus `@doc` and `@category`, so the same palette and tooling cover user and host code.
- `purity` is one of `impure`, `reads` (a pure node that reads mutable state, such as `GetField`, `GetVar`, `GetState`) or `pure`. Only `pure` kinds may appear in a `@pure` function; `pure` and `reads` kinds may appear in a `@reads` function.
- Display names are for editors and may be localised. They never appear in `.wiret`.
- The registry name and version are recorded in `wr.meta` and in the project lockfile (section 7.3). An unknown kind is `E0501`.
