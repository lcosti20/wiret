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
| `struct` | immutable heap record with value semantics | Equality is structural, field by field. "Setting" a field makes a new struct (`WithField`). Default: each field's declared default, else that field type's default. |
| `class` | nullable reference | Equality is identity. Default `null`. |
| `array::<T>` | growable, zero-based; **value type** | Copied on assignment, argument passing and return. The VM copies lazily (copy-on-write, section 4.9), so two variables never alias one array. Equality is element-wise. |
| `set::<T>`, `map::<K,V>` | insertion-ordered; **value types** | Same copy rules as arrays. Iteration order is insertion order, never hash order. Keys are primitives, `string`, enums or structs of those. Every NaN is the same key, also inside a struct key, so a NaN key can be found again. Equality ignores order. |
| `delegate::<(A)->(R)>` | reference to a function plus optional bound receiver | Single-cast. |
| `dispatcher::<(A)>` | reference to an ordered handler list | Multicast; the `dispatcher` member of a class. |
| `extern type` | host handle (index plus generation) | `IsValid` is false once the host destroys the object. |
| `std.Signal`, `std.Fault` | built-in opaque handles | Used by `Await` and `Try`. A `std.Signal` may be a parameter, result, local, `state` or `var`, but not a struct field or a container item, and has no `Eq`. Its default is null. `std.Fault` is internal to the lowering of `Try` and `Throw` and is not written in source. |

Wires connect a source pin to a destination pin of the **same type**, or of a **supertype** (a class wire may feed a pin of its superclass or of an interface it implements). There is no other implicit conversion.

### 3.2 Conversions

The editor, like Blueprint's, offers to insert a conversion node when you connect two compatible but different types. In Wiret that node is real and visible in the text: `Convert::<From, To>`.

| From | To | Behaviour |
| --- | --- | --- |
| integer | integer | Wraps (truncates, or sign/zero-extends). |
| integer | float | Nearest representable value. |
| float | integer | Truncates toward zero, **saturating**; NaN becomes 0. Never faults. |
| f64 / f32 | f32 / f64 | IEEE demote / promote. |
| bool | integer | 0 or 1. |
| integer | bool | Non-zero is true. |
| enum | its own underlying integer type, and back | Back-conversion does not check that the value names a member. Reaching another integer type takes a second `Convert`. |
| bool, integer, float | string | Culture-independent decimal text. Floats use the shortest text that round-trips. |
| string | number or bool | Not a `Convert`. Use `std.string.TryParse::<T>`, which returns `(ok: bool, value: T)`. |

### 3.3 Built-in node kinds

Pin names are fixed per kind. Pure binary operators use inputs `a`, `b` and output `result`. `T` is the type argument. "Impure" kinds have the exec input `in` unless noted.

**Control flow**

| Kind | Pins | Behaviour |
| --- | --- | --- |
| `Entry` | out: the graph's parameters; exec out `then` | Starts a function or event. In a macro, has one exec output per `exec` parameter. |
| `Return` | in: the graph's results | Leaves the function. `Return` has an exec input in every function, including `@pure` ones: a pure function's exec flow is internal and invisible to its callers. |
| `Branch` | in `cond: bool`; exec out `then`, `else` | Two-way choice. |
| `Sequence` | `@count(n)`; exec out `then0` .. `then{n-1}` | Runs `then0`'s chain to its end, then `then1`'s, and so on. |
| `Switch::<T>` | in `value: T`; `@cases(...)`; exec out `case0`.., `default` | `T` is an integer, enum, string or bool. |
| `Select::<T>` | pure; in `cond`, `a`, `b`; out `result` | Lazy: evaluates `cond`, then only the input it chooses (`a` when `cond` is true), so a fault in the other is never raised (section 4.3). |
| `Try` | exec out `body`, `fault`, `then`; out `message: string`, `code: i32` | Runs `body`. A catchable fault inside it goes to `fault`, with `message` and `code` set from the fault. When the body's chain or the fault chain ends, `then` runs, as code after a try/catch would. Section 4.6. |
| `Throw` | in `message: string`, `code: i32` (default 0) | Raises a catchable fault. No exec out. Use non-negative codes; the built-in faults use negative ones (section 4.6). |
| `Delay` | in `seconds: f64`; exec out `then` | **Latent.** Suspends the fiber for virtual time. |
| `Yield` | exec out `then` | **Latent.** Resumes on the next `wr_advance`. |
| `Await` | in `signal: std.Signal`; exec out `then` | **Latent.** Resumes when the host fires the signal. |
| `Macro` | symbol: macro name; pins from its signature | Inlined at compile time. |
| `Exit` | symbol: macro exec output; in: its data outputs | Macro-only. Leaves the macro through that exec output (a jump) and assigns the data outputs bound on the node. It never changes the continuation stack, so a continuation the macro pushed stays pending. On the first output of a Sequence it runs the caller's chain as a subroutine (see ForRange in section 2.6 and the trace in section 4.2). |
| `Leave` | as `Exit` | Macro-only. Like `Exit`, but first discards every continuation the macro has pushed since it was entered, and everything the caller's chains pushed above them, so the macro is over: nothing it left pending runs (section 4.2). A loop's `break` input is wired to `Leave done`. |
| `Reroute::<T>` | in `in`, out `out` | Visual only. |

**Variables, fields and objects**

| Kind | Pins | Behaviour |
| --- | --- | --- |
| `GetLocal` / `SetLocal` | `value` | Locals declared with `local`. `SetLocal` is impure. |
| `GetVar` / `SetVar` | `value` | Module-level `var`. |
| `GetField` | symbol: `Vec2.x` on a struct, `Player.health` on a class (section 2.3, rule 3); in `obj`; out `value` | On a struct, `pure`: a struct is a value and cannot change under the reader. On a class reference, a pure node with `reads` purity (section 4.3): re-evaluated at each consumer and sees the state at that consumer's evaluation point. Faults on a null class reference. Not allowed in a `@pure` function (`E0304`). |
| `SetField` | in `obj`, `value` | Impure; classes only. On a struct it is `E0501`: use `WithField`. |
| `WithField` | pure; symbol `Vec2.x`; in `obj`, `value`; out `result` | Returns a copy of a struct with one field replaced. |
| `MakeStruct` | pure; symbol: the struct; in: one pin per field, in declaration order; out `result` | An unbound input takes the field's declared default, else its type's default, so it never warns `W0201`. |
| `BreakStruct` | pure; symbol: the struct; in `obj`; out: one pin per field | |
| `New` | out `result`; exec out `then` | Allocates a class instance with declared defaults. Impure because it creates identity. |
| `Cast` | pure; symbol: the class to cast to (`Cast Boss`); in `obj: anyref` (any object); out `result` of that class, `ok: bool` | `result` is null when the cast fails. |
| `IsValid` | pure; in `obj: anyref`; out `result: bool` | Non-null and, for host handles, still alive. |
| `Convert::<From, To>` | pure; in `value`; out `result` | See section 3.2. |
| `Format "template"` | pure; in one per placeholder; out `result: string` | Text from a template: `Format "{n} items, {left} left"(.n <- ..., .left <- ...)`. Each `{name}` is an input, in the order of first appearance, and `{{` and `}}` are literal braces. An input takes the type of what is bound to it, which must be `bool`, a number or `string` (`E0110`), and is written as `Convert::<T, string>` would write it; an unbound input is empty text. A malformed template is `E0501`. It compiles to the same `Concat` and conversion calls as the nodes it replaces. |
| `GetState` / `SetState` | `value` | Persistent slots declared with `state` (section 2.3). `SetState` is impure. |

**Arithmetic, comparison, logic** (all pure)

| Kinds | Types | Notes |
| --- | --- | --- |
| `Add Sub Mul Div Rem Min Max` | `<T>` any number | Integer `Div`/`Rem` fault on zero. Integer overflow wraps. |
| `Neg Abs` | `<T>` any signed number or float | Input `value`. |
| `Eq Ne` | `<T>` number, bool, string, enum, struct, class, array, set, map (compared element-wise) | Output `bool`. |
| `Lt Le Gt Ge` | `<T>` number, string (ordinal), enum | Output `bool`. |
| `And Or Xor Not` | bool | `And` and `Or` short-circuit: `b` is evaluated only when `a` does not decide the result (section 4.3). |
| `BitAnd BitOr BitXor BitNot Shl Shr` | `<T>` integer | Shift counts are masked to the type's width. |

**Containers**

| Kind | Notes |
| --- | --- |
| `MakeArray::<T>` | Pure. `@count(n)`, inputs `item0` ... |
| `ArrayGet::<T>`, `ArrayLength::<T>` | Pure. Out-of-range index is a fault. |
| `ArraySet::<T>`, `ArrayAdd::<T>`, `ArrayInsert::<T>`, `ArrayRemove::<T>`, `ArrayClear::<T>` | Impure. They change a **place**: the symbol names a local, a module variable, or a field. Examples: `ArrayAdd::<i32> acc` with input `.item <- x`, and `ArrayAdd::<i32> Player.items` with inputs `.obj <- p` and `.item <- x`. Targeting anything else, such as a call result, is `E0130`. Arrays are value types (section 4.9), so no other variable sees the change. |
| `MapFind::<K,V>` | Pure. In `map`, `key`; out `value`, `found`. A missing key gives the zero value and `found = false`. |
| `MapHas`, `MapLength`, `MapKeyAt`, `MapValueAt` | Pure. In `map`, plus `key` (`MapHas`) or `index` (the `At` kinds); out `result`, `length`, `key` and `value`. The `At` kinds index by insertion order, which is how `ForEachMap` is built; an out-of-range index is a fault. |
| `MapSet`, `MapRemove`, `MapClear` | Impure, and change a place exactly like the array mutators: `MapSet::<string, i32> counts` with inputs `.key` and `.value`. Setting a key that is present keeps its position. `MapRemove` has the output `removed`, false when the key was absent. |
| `SetHas`, `SetLength`, `SetAt` | Pure. In `set`, plus `item` or `index`; out `result`, `length` and `item`. |
| `SetAdd`, `SetRemove`, `SetClear` | Impure place mutators with the input `item`. `SetAdd` has the output `added` and `SetRemove` the output `removed`, false when nothing changed. The outputs are the flags that `map.remove`, `set.add` and `set.remove` return (section 5.6). |
| `std.array.Append::<T>`, `std.array.With::<T>`, ... | Pure functional forms that return the updated container and change nothing, for use inside `@pure` functions. |

**Calls and events**

| Kind | Pins | Behaviour |
| --- | --- | --- |
| `CallParent` | symbol: the method's name; its parameters (no `self`) and results | Only in a method that overrides one of a base class (`E0501` otherwise). Calls the nearest base class's version on the method's own `self`, directly, not through the vtable. Pure or impure as that version is. |
| `Call` | symbol: function, method or extern; its parameters and results | Pure node if the callee is `@pure`, `@reads`, or a native flagged effect-free; otherwise impure. A method call has `self` as its first input; dispatch is virtual unless `@final`, and via the interface when the symbol names an interface method. |
| `CreateDelegate` | pure; symbol: function, method or event; in `target` for a method; out `result` | Binds a function (and receiver) into a delegate, whose type is the function's signature without the receiver. A method delegate calls the target's own override. A `@latent` func, a native or an extern cannot be bound (`E0501`); an event can (see `Invoke`). |
| `Invoke::<D>` | `D` is a delegate type; in `delegate`, `arg0`, `arg1`, ...; out `result0`, ... | Impure. Never suspends: a delegate of an event starts it on a new fiber, queued for the next `wr_advance`. A null delegate faults. |
| `Bind`, `Unbind` | symbol: the dispatcher, `Class.Name`; in `obj`, `handler: delegate` | Impure. Binding a handler that is already bound (same function and receiver) does nothing; `Unbind` removes it. |
| `Broadcast` | symbol: dispatcher; in `obj` plus the arguments, named as in the dispatcher | Impure. Handlers bound when the broadcast starts run in bind order; an event handler starts on a new fiber. A fault in one handler is reported to the host and does not stop the others. |

### 3.4 The standard library

The VM ships these namespaces as natives (callable through `Call`) and as Wiret source:

- `std.math`: `Sqrt`, `Pow`, `Sin`, `Cos`, `Atan2`, `Floor`, `Ceil`, `Round`, `Clamp::<T>`, `Lerp`, ... (pure).
- `std.string`: `Concat`, `Length`, `Substring`, `Find`, `Format`, `TryParse::<T>`, `Split`, ... (pure).
- `std.array`, `std.set`, `std.map`: `Equals` (two `anyref`, section 4.9), `Sort::<T>` (stable, caller supplies a comparison delegate), `IndexOf::<T>`, ...
- `std.fault`: `Make(message, code) -> fault`, `Message(fault) -> string`, `Code(fault) -> i32` (pure). The compiler calls them to lower `Throw` and the outputs of `Try`; they are not nodes in the palette.
- `std.signal`: `New() -> std.Signal` and `Fire(signal)` (both impure). `Fire` does what `wr_signal_fire` does (section 6.8).
- `std.random`: an explicit-state generator class (`New`, `NextI32`, `NextF64`). There is **no ambient randomness, clock or I/O**. The host provides any of those as natives, which keeps modules replayable.
- `std.flow` (macros written in Wiret): `ForRange`, `ForEach::<T>`, `ForEachMap::<K,V>`, `While`, `DoOnce`, `DoN`, `Gate`, `FlipFlop`, `MultiGate`, `Retriggerable`. Each loop has a `break` exec input besides `in`: wiring a chain inside the loop to it ends the loop at once and runs `done`. `ForEachMap::<K,V>` takes `map` and has the exec outputs `each` and `done` and the data outputs `key`, `value` and `index`, in insertion order.

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

- A `.wiret` file never re-declares the pins of a registry kind. This keeps node statements short and the registry the one source of truth. Pins that depend on attributes (`@count`, `@cases`) are described in the registry by a pin pattern such as `then{i}`.
- Functions, methods, events and `extern func` declarations get generated registry entries from their signatures plus `#[doc]` and `#[category]`, so the same palette and tooling cover user and host code.
- `purity` is one of `impure`, `reads` (a pure node that reads mutable state, such as `GetField`, `GetVar`, `GetState`) or `pure`. Only `pure` kinds may appear in a `@pure` function; `pure` and `reads` kinds may appear in a `@reads` function.
- Display names are for editors and may be localised. They never appear in `.wiret`.
- The registry name and version are recorded in `wr.meta` and in the project lockfile (section 7.3). An unknown kind is `E0501`.
