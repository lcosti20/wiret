## 3. Types and the built-in node set

### 3.1 Types

| Type | Representation | Notes |
| --- | --- | --- |
| `bool` | i32 (0 or 1) | Default `false`. |
| `i8 u8 i16 u16 i32 u32` | i32 slot | Narrow types wrap on arithmetic (`Convert` is needed to narrow explicitly). Unsigned types use unsigned compare, divide, remainder and shift. |
| `i64 u64` | i64 slot | Same rules. |
| `f32 f64` | IEEE-754 | In deterministic mode, NaN is canonical and arithmetic is fully specified (section 4.10). |
| `vec2 vec3 quat transform` | 2, 3, 4 and 10 `f32` lanes, **unboxed** | Built-in structs that never allocate (section 3.1.1). Equality is component-wise. Default: zero vectors, the identity rotation and the identity transform. |
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

#### 3.1.1 Vectors, rotations and transforms

**Provisional** (Draft 0.13). The prototype implements this section, with tests, except `std.quat.FromEuler`. Game code does vector math at every node of a per-frame graph, and a user `struct Vec3` would allocate a heap record at each `MakeStruct` and `WithField` (section 9.1, item 5). The four built-in types below behave exactly like structs with fixed fields, but the VM holds them unboxed: in a local, on the operand stack, in a struct or class field and in an array element they are their `f32` lanes and nothing else. They are never references, are never null, are not traced by the collector and add no allocation fuel.

| Type | Fields, in order | Default | Literal |
| --- | --- | --- | --- |
| `vec2` | `x y: f32` | `(0, 0)` | `(1.5, -2)` |
| `vec3` | `x y z: f32` | `(0, 0, 0)` | `(0, 1, 0)` |
| `quat` | `x y z w: f32` | `(0, 0, 0, 1)`, the identity rotation | `(0, 0, 0.7071068, 0.7071068)` |
| `transform` | `translation: vec3`, `rotation: quat`, `scale: vec3` | translation `(0, 0, 0)`, identity rotation, scale `(1, 1, 1)` | `((0, 2, 0), (0, 0, 0, 1), (1, 1, 1))` |

A literal is a tuple of number literals (section 2.1), one per field and nested for `transform`. It may stand wherever a literal of the type may: on a pin, as a `const`, `var`, field, parameter, `local` or `state` default. A tuple of the wrong length or with a non-number in it is `E0110`. Wherever this document says *the zero value* of a type (an unbound `Exit` output, a missing map key, `array.new`), a `quat` or `transform` takes the default above, not all-zero lanes, which would not be a rotation. The names are built-in type names, so a user struct or enum may not take them (`E0102`); `Vec2` with a capital letter, as in the examples of this document, is a different name.

**Struct nodes work on them.** `MakeStruct vec3` (inputs `x`, `y`, `z`), `BreakStruct quat`, `GetField vec3.y`, `GetField transform.rotation` and `WithField transform.scale` are the ordinary struct kinds of section 3.3, pure, and compile to the lane instructions of section 5.6 instead of a heap record. `SetField` on one is `E0501`, as on any struct.

**Operators.** The arithmetic kinds of section 3.3 accept them where the table below says so; any other type argument is `E0110`. Every operation on lanes is the `f32` operation of section 4.10, so a division by zero gives an infinity or NaN and never faults.

| Kind | `vec2`, `vec3` | `quat` | `transform` |
| --- | --- | --- | --- |
| `Add Sub Mul Div Min Max` | component-wise | `Mul` only: the Hamilton product, the rotation `b` then `a` | `Mul` only: composition, `b` then `a` |
| `Neg Abs` | component-wise | | |
| `Scale::<T>` (new kind; in `v: T`, `s: f32`; out `result`) | each component times `s` | | |
| `Eq Ne` | component-wise, in field order, with the `f32` rules (a vector holding NaN is not equal to itself) | same | same |

`Lt Le Gt Ge`, `Rem` and the bit kinds do not accept them. `Mul` means composition on `quat` and `transform` because that is what multiplying them means in every engine's math library; its order is the matrix order, so `Mul::<quat>(.a <- turn, .b <- tilt)` tilts first and then turns, and `Call std.transform.Apply` with `Mul::<transform>(a, b)` gives the same point as applying `b` and then `a`.

**Definitions.** Each formula is evaluated in the order written, left to right, with no fused multiply-add (section 4.10), so results are the same on every platform in deterministic mode. `u` is the vector part `(q.x, q.y, q.z)` of a quaternion.

| Operation | Result |
| --- | --- |
| `std.vec.Dot::<vec3>(a, b)` | `(a.x*b.x + a.y*b.y) + a.z*b.z`; for `vec2` the first sum |
| `std.vec.Cross(a, b)` (vec3) | `(a.y*b.z - a.z*b.y, a.z*b.x - a.x*b.z, a.x*b.y - a.y*b.x)` |
| `std.vec.PerpDot(a, b)` (vec2) | `a.x*b.y - a.y*b.x` |
| `std.vec.LengthSquared::<T>(v)`, `Length`, `Distance` | `Dot(v, v)`; `Sqrt` of it; `Length(a - b)` |
| `std.vec.Normalize::<T>(v)` | with `n = Length(v)`: each component divided by `n` when `n > 0`, otherwise the zero vector (also for NaN). Never faults. |
| `std.vec.Lerp::<T>(a, b, t)` | each component `a + (b - a) * t`; `t` is not clamped |
| `std.vec.Reflect::<T>(v, n)` | `v - Scale(n, 2 * Dot(v, n))`; `n` is expected to be unit length |
| `Mul::<quat>(a, b)` | `x = ((a.w*b.x + a.x*b.w) + a.y*b.z) - a.z*b.y`, `y = ((a.w*b.y - a.x*b.z) + a.y*b.w) + a.z*b.x`, `z = ((a.w*b.z + a.x*b.y) - a.y*b.x) + a.z*b.w`, `w = ((a.w*b.w - a.x*b.x) - a.y*b.y) - a.z*b.z` |
| `std.quat.Rotate(q, v)` | with `t = Scale(Cross(u, v), 2)`: `(v + Scale(t, q.w)) + Cross(u, t)`. Exact for a unit `q`; `Rotate` does not normalise. |
| `std.quat.Conjugate(q)`, `Inverse(q)` | `(-q.x, -q.y, -q.z, q.w)`; the conjugate with each component divided by the four-component dot product of `q` with itself when that is `> 0`, otherwise the identity |
| `std.quat.Normalize(q)` | as for vectors over four components, but the identity when the length is not `> 0` |
| `std.quat.FromAxisAngle(axis: vec3, angle: f32)` | with `n = Normalize(axis)`, `h = angle * 0.5`: `(n.x * Sin(h), n.y * Sin(h), n.z * Sin(h), Cos(h))`; the identity when `n` is zero |
| `std.quat.FromEuler(angles: vec3, order: std.quat.EulerOrder)` | `angles.x`, `.y`, `.z` are rotations about the x, y and z axes. `order` is one of `XYZ XZY YXZ YZX ZXY ZYX`, naming the axis applied first: `XYZ` is `Mul(Mul(qz, qy), qx)`, each factor from `FromAxisAngle` |
| `std.quat.Slerp(a, b, t)` | with `d` the four-component dot product: when `d < 0`, `b` and `d` are negated. When `d > 0.9995` the result is `Normalize` of the component-wise `Lerp`; otherwise, with `th = Acos(d)`, it is `a * (Sin((1 - t) * th) / Sin(th)) + b * (Sin(t * th) / Sin(th))` per component |
| `std.quat.Angle(a, b)` | `2 * Acos(Min(Abs(d), 1))`, `d` as for `Slerp`: the angle between two rotations, so `q` and `-q` (the same rotation) give 0 |
| `std.transform.Apply(t, p)` | `t.translation + Rotate(t.rotation, t.scale * p)`, with `*` component-wise |
| `std.transform.ApplyVector(t, v)` | `Rotate(t.rotation, t.scale * v)`: a direction, without translation |
| `Mul::<transform>(a, b)` | translation `Apply(a, b.translation)`, rotation `Mul::<quat>(a.rotation, b.rotation)`, scale `a.scale * b.scale` |
| `std.transform.Inverse(t)` | rotation `r = Conjugate(t.rotation)`, scale `s` with each component `1 / t.scale` (0 where that component is 0), translation `s * Rotate(r, -t.translation)` |

Angles are radians. Rotations are unit quaternions; the functions that build them return unit ones, and `Mul` keeps a product within rounding of unit, which `std.quat.Normalize` corrects when a long chain drifts. `Eq` compares components, so `q` and `-q` are different values that rotate the same way; use `Angle` to compare rotations.

A `transform` is translation, rotation and scale, the form an editor shows and an animation blends. It cannot represent shear, so `Mul` and `Inverse` are exact only when the scale of the left (outer) transform is uniform or the rotation of the right is the identity; otherwise they give the nearest transform without shear, as Unreal's `FTransform` does. Hosts whose own transform is a matrix (Godot's `Transform3D`, a 4×4 world matrix) convert at the boundary, and a script that needs shear uses a host type.

**No coordinate convention.** Nothing above names an up axis or a handedness. The quaternion algebra is the same in a left-handed and a right-handed frame, so a host passes its own components through unchanged and its "up" stays its own (`(0, 1, 0)` in Godot and Unity, `(0, 0, 1)` in Unreal). A function that needs a convention, such as a look-at rotation or the Euler order an engine's inspector uses, is a host native.

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
| `vec2`, `vec3`, `quat`, `transform` | string | The literal form of section 3.1.1, each component written as `Convert::<f32, string>` writes it: `(0.0, 1.5, 0.0)`, `((0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), (1.0, 1.0, 1.0))`. |
| `vec2` / `vec3` | `vec3` / `vec2` | Adds `z = 0` / drops `z`. There is no other conversion between the vector types. |
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
| `Format "template"` | pure; in one per placeholder; out `result: string` | Text from a template: `Format "{n} items, {left} left"(.n <- ..., .left <- ...)`. Each `{name}` is an input, in the order of first appearance, and `{{` and `}}` are literal braces. An input takes the type of what is bound to it, which must be `bool`, a number, a vector type of section 3.1.1 or `string` (`E0110`), and is written as `Convert::<T, string>` would write it; an unbound input is empty text. A malformed template is `E0501`. It compiles to the same `Concat` and conversion calls as the nodes it replaces. |
| `GetState` / `SetState` | `value` | Persistent slots declared with `state` (section 2.3). `SetState` is impure. |

**Arithmetic, comparison, logic** (all pure)

| Kinds | Types | Notes |
| --- | --- | --- |
| `Add Sub Mul Div Rem Min Max` | `<T>` any number | Integer `Div`/`Rem` fault on zero. Integer overflow wraps. |
| `Neg Abs` | `<T>` any signed number or float | Input `value`. |
| `Eq Ne` | `<T>` number, bool, string, enum, struct, `vec2`, `vec3`, `quat`, `transform`, class, array, set, map (compared element-wise) | Output `bool`. |
| `Scale::<T>` | `<T>` `vec2` or `vec3` | In `v`, `s: f32`. The vector types also take `Add Sub Mul Div Min Max Neg Abs`, and `quat` and `transform` take `Mul`, as section 3.1.1 lists. |
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

- `std.math`: `Sqrt`, `Pow`, `Sin`, `Cos`, `Acos`, `Atan2`, `Floor`, `Ceil`, `Round`, `Clamp::<T>`, `Lerp`, ... (pure).
- `std.vec`, `std.quat`, `std.transform`: the vector, rotation and transform functions of section 3.1.1, and the enum `std.quat.EulerOrder` (pure). The compiler lowers the ones with a lane instruction (section 5.6) to it, so a `Call std.vec.Dot::<vec3>` costs what `Add::<f32>` does; the ones built on `Sin`, `Cos` and `Acos` are natives.
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
