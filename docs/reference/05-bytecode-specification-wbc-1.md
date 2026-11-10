## 5. Bytecode specification (WBC 1)

### 5.1 Design summary

WBC is a **typed stack machine** with per-function typed locals, in the spirit of WebAssembly's encoding and the JVM's object model. Two decisions follow from graphs rather than structured source:

- **Flat code with labels, not structured blocks.** Exec wiring can form loops with several entry points and merges (irreducible control flow). WebAssembly's `block`/`loop` nesting would force a restructuring pass, which would make bytecode unrelated to the graph. WBC uses plain branches to labels, as the JVM does.
- **The operand stack is empty at every label.** Each impure node is one block that starts and ends with an empty operand stack, and only locals carry values between blocks. Locals have fixed declared types and are zero-initialised, so the verifier needs no stack maps, no merge of type states and no definite-assignment analysis. Verification is a single linear pass, and *any* label is a type-safe jump target, which is what makes the dynamic continuation stack (section 4.2) safe.

All multi-byte fixed-width values are little-endian. Section 5.1.1 fixes how each kind of number is encoded; in short, container fields are fixed-width, instruction immediates are LEB128, and branch offsets are fixed-width.

#### 5.1.1 Primitive encodings

| Name | Encoding | Used for |
| --- | --- | --- |
| `u8` | One byte. | Flags, kinds, type codes, opcodes, and the `kind` and `flags` immediates of `suspend` and `delegate.new`. |
| `u32` | Exactly 4 bytes, little-endian. | Every `u32` in sections 5.2 and 5.3: header fields, section sizes, `vec` counts, type, function, global and data indices, local counts, `max_stack`, `max_cont`. Fixed width lets a writer patch sizes and counts without moving bytes. |
| `uleb` | Unsigned LEB128, at most 5 bytes. | Instruction immediates that are indices or counts: local, global, function, type, field, slot and data indices, the count `n` of `br_table`, and the sub-opcode after the `FB` prefix. |
| `sleb32` / `sleb64` | Signed LEB128, at most 5 / 10 bytes. | The immediates of `i32.const` and `i64.const`. |
| `f32` / `f64` | The IEEE 754 binary32 / binary64 bit pattern, 4 / 8 bytes, little-endian. | The immediates of `f32.const` and `f64.const`. |
| `L` (branch offset) | Exactly 4 bytes, little-endian, two's complement `s32`. **Not** LEB128. | Every branch target, in section 5.6. |

**LEB128.** A writer emits the shortest form. A reader accepts a longer form with redundant bytes, up to the maximum length, and rejects a form that is longer than the maximum or whose final byte has unused bits that are not zero (unsigned) or not equal to the sign bit (signed). The verifier counts a rejected number as a decoding failure (section 5.5, rule 2).

**Floating-point constants.** The bit pattern is stored and loaded unchanged, so `-0` and every NaN payload survive. A writer emits a NaN with no source payload as the quiet NaN `7FC00000` (f32) or `7FF8000000000000` (f64).

**`const` in globals and field defaults** is 8 bytes, little-endian. An `i32`, `bool`, narrow integer or `f32` occupies the low 4 bytes and the high 4 bytes are zero (the verifier rejects anything else); a narrow integer holds its value as a sign-extended `i32` and must be in range for its type; `bool` is 0 or 1. An `i64` or `f64` fills all 8 bytes. A `string` is a `u32` data index (4 bytes). References have no bytes.

**Branch offsets.** `L` is a byte count, added to the position of the first byte after the whole instruction. For `br`, `br_if` and `cont.push` that is the end of the offset; for `try.push` it is the end of the `local` immediate that follows `L`; for `br_table` it is the end of `Ldefault`, and every label of one `br_table` is measured from there. Positions ("pc") are byte offsets from the start of the function's `code` bytes. An offset of 0 targets the next instruction. The target must be the first byte of an instruction in the same body, so a target equal to the code length is invalid. A fixed 4-byte offset lets an emitter write a placeholder and patch it in one pass, with no size relaxation, at a cost of up to 3 bytes per branch over LEB128. For `br_table` the verifier checks that `n` labels fit in the remaining code bytes before reading them.

### 5.2 Container

```
module  = magic version flags section*
magic   = 00 57 42 43            ; NUL 'W' 'B' 'C'
version = u32 (little endian)    ; 1
flags   = u32                    ; bit 0: has embedded source (wr.graph); bits 1-31: required features, unknown bits are rejected; bit 1: lane types (5.3)
section = id:u8 size:u32 payload ; ids ascending, custom sections (id 0) anywhere
vec(X)  = n:u32 X*               name = vec(u8)  ; UTF-8, no NUL
```

| Id | Section | Contents |
| --- | --- | --- |
| 0 | Custom | `name:name` then payload. Unknown custom sections are skipped. |
| 1 | Type | `vec(typeentry)` |
| 2 | Import | `vec(module:name field:name kind:u8=0 type:u32 flags:u8)`; kind 0 is a function. Flags: bit 0 pure, bit 1 reserved. `module` names a Wiret module or a host namespace; resolution order is in section 7.3. |
| 3 | Function | `vec(typeidx:u32 flags:u8)` for each defined function. Flags: bit 0 pure, bit 1 latent, bit 2 event; the verifier rejects any other bit, a function that is both pure and latent, and an event that is not latent or has results. Function indices count imports first. |
| 4 | Global | `vec(valtype mut:u8 init:const)` |
| 5 | Export | `vec(name kind:u8 index:u32 flags:u8)`; kind 0 func, 1 global, 2 type. Flags: bit 0 event, 1 latent, 2 pure, 3 declared (the source marks it `@export`). Methods are exported as `Class.Method`. Which entries are present depends on the export mode, below. |
| 6 | Data | `vec(vec(u8))`: string constants, UTF-8. |
| 7 | Code | `vec(body)` where `body = size:u32 locals:vec(count:u32 valtype) max_stack:u32 max_cont:u32 code:bytes` |

A `const` is 8 bytes (numeric bit pattern), or a `u32` data index for `string`, or empty for references (always null); the exact layout is in section 5.1.1.

**Export modes.** A normal build writes an export entry only for what the source marks `@export`, and sets flag bit 3 on each. An `--export-all` build (section 7) also writes an entry for every `func`, `event` and method, so that the editor can run any function by name; entries for `@export` items still carry bit 3, the others do not. Macros are inlined and never exported, and `var`s and types are exported only when marked `@export`. An enum has no type entry (it is its underlying integer), so it is never exported, and `@export` on one is `W0203`. Export mode is a build option, not part of the source: it does not change the semantic hash or any function body, and `wr.meta` records which mode was used. The export table is the only thing that differs. **Linking** from another Wiret module resolves an import only against entries with bit 3 set, so `--export-all` does not make `@private` or unmarked functions importable by other modules. The host sees every entry, and tests bit 3 (`WR_EXPORT_DECLARED`, section 6) to find the public surface. `--export-all` builds are for development; release pipelines should build without it.

### 5.3 Value types and type entries

| Code | Value type |  | Code | Storage-only type |
| --- | --- | --- | --- | --- |
| `7F` | i32 (also bool and all narrow integers) |  | `78` | i8 (loads sign-extend, stores truncate) |
| `7E` | i64 |  | `77` | i16 (same) |
| `7D` | f32 |  |  |  |
| `76` | vec2 (2 `f32` lanes) |  |  |  |
| `75` | vec3 (3 lanes) |  |  |  |
| `74` | quat (4 lanes) |  |  |  |
| `73` | transform (10 lanes: translation, rotation, scale) |  |  |  |
| `7C` | f64 |  |  |  |
| `6E` | string (never null) |  |  |  |
| `6B t` | nullable reference to type index `t` (class, struct, array, map, set, interface, delegate, dispatcher) |  |  |  |
| `6A` | fault |  |  |  |
| `69` | signal |  |  |  |
| `6D` | anyref (top of the reference types) |  |  |  |

| Code | Type entry | Body |
| --- | --- | --- |
| `60` | func | `params:vec(valtype) results:vec(valtype)` |
| `5F` | struct | `fields:vec(field)` |
| `5E` | array | `elem:storagetype` |
| `5D` | map | `key:valtype value:valtype` |
| `5C` | set | `elem:valtype` |
| `5B` | class | `flags:u8 super:u32 interfaces:vec(iface:u32 impl:vec(funcidx)) fields:vec(field) vtable:vec(funcidx)`. `super` is 0 for none, else type index + 1. Flag bit 0 marks a host type: then a `name` follows and there are no fields. `fields` are the class's own; inherited fields come first in the layout. `vtable` holds the full slot list: the superclass's slots, with overrides replacing inherited slots, then the class's new methods ordered by name. |
| `5A` | interface | `methods:vec(functype:u32)`; the method index is the dispatch slot. A function type here leaves out the receiver. A class entry's `interfaces` lists every interface the class implements, including those of its superclasses, each with the function implementing each method, so `call_interface` never walks the hierarchy. The verifier requires a class to keep its superclass's interfaces, and each implementation to take the class or a superclass as its receiver, to have the method's function type after it, and not to be latent. |
| `59` | delegate | `functype:u32` |
| `58` | dispatcher | `functype:u32` (no results) |

**Lane types.** `76` to `73` are the built-in types of section 3.1.1. Each is one operand-stack entry and one local to the verifier, whatever its lane count, so `max_stack` counts entries; an implementation sizes its slots from the types the verifier computes. They are value types, never references: they are not subtypes of `anyref`, `ref.*` instructions reject them, and stack maps skip them. A module that uses one, in a type entry, local, global or instruction, sets container flag bit 1, so a VM without them rejects it at load instead of failing later. A constant of a lane type is its `f32` lanes in field order, each 4 bytes little-endian.

`field = storagetype flags:u8 [const]` where flag bit 0 says a default value follows. In a struct entry only number, string and lane-type fields carry one. A struct's default value holds each field's default, else that field type's default (a nested struct's own default, an empty array); the VM builds struct locals and globals from it.

### 5.4 Custom sections defined by this version

| Name | Purpose |
| --- | --- |
| `name` | Names of functions, locals, types, fields and enum members, for tools and reflection. |
| `wr.debug` | Maps code offsets to graph position. For each function: its graph item id, a string table of node ids and pin names (path-style after macro expansion, such as `loop/test`), and a list of `(pc_delta, node)` entries. Drives node-level breakpoints, stepping and tracebacks. Layout in section 5.4.1. |
| `wr.pins` | For each function: a list of `(local, node, pin)` triples, naming the node output pin that each local holds (`node` and `pin` are indices into that function's `wr.debug` string table). Complete for `-Og` builds; otherwise it lists the pins that survive optimisation. Lets an editor show the value on a wire and lets the host call `wr_getpin`. |
| `wr.graph` | The canonical `.wiret` text, deflate-compressed. Lets a debugger or editor open a `.wbc` it did not build. |
| `wr.meta` | Module id, compiler and registry versions, **semantic hash** and **layout hash** (section 2.5), source hash. |
| `wr.reflect` | Attribute data for the host: `#[doc]`, `#[category]`, parameter names and defaults. |
| `wr.caps` | Every capability the module's imports require, so a host can inspect or refuse a module before loading it. |

**Sidecar.** `wiretc build --sidecar` writes `wr.debug`, `wr.pins`, `wr.graph` and `wr.reflect` to a separate `out.wdbg` file instead of embedding them. `wr.meta` in both files carries the same module id and semantic hash, so a debugger can match them. Release builds can ship the small `.wbc` alone. A `.wdbg` file uses the container of section 5.2 with the magic `00 57 44 47` (NUL 'W' 'D' 'G'), `version` 1 and `flags` 0, and holds only custom sections.

#### 5.4.1 Layout of `wr.debug` and `wr.pins`

Debug data is strippable and never affects safety, so it uses compact numbers: inside these two sections every integer is a `uleb` (section 5.1.1), a `uvec(X)` is a `uleb` count followed by that many `X`, and a `str` is a `uleb` byte length followed by UTF-8 bytes with no NUL. The custom-section header (`name:name`) is the container's, as in section 5.2. A reader that finds either section malformed ignores it and reports a warning; the module still loads.

```
wr.debug = version:uleb funcs:uvec(dfunc)            ; version = 1
dfunc    = funcidx:uleb item:str strings:uvec(str) entries:uvec(entry)
entry    = pc_delta:uleb node:uleb

wr.pins  = version:uleb funcs:uvec(pfunc)            ; version = 1
pfunc    = funcidx:uleb pins:uvec(pin)
pin      = local:uleb node:uleb pin:uleb
```

- **`funcidx`** is an index in the function index space (imports first, section 5.2) and must name a defined function. `dfunc` records appear in ascending `funcidx`, at most once each. Functions without debug data are simply absent.
- **`item`** is the function's graph item id: its `@id` if it has one, otherwise its qualified name (`game.demo.Player.TakeDamage`).
- **`strings`** is a per-function table of distinct strings, in order of first use. An entry's `node` is an index into it and names a node id. Nodes that come from a macro expansion are path-style: the macro node's id, then `/`, then the inner node's id, nested as deep as the expansion (`loop/test`, `outer/inner/test`). `wr.pins` uses the same table for both node ids and pin names.
- **`entries`** map code to nodes. The first entry's `pc` is its `pc_delta`; every later `pc` is the previous `pc` plus `pc_delta`, and every later `pc_delta` is at least 1, so `pc` values strictly increase. Each `pc` is the first byte of an instruction. An entry covers its `pc` up to the next entry's `pc`, and the last one covers up to the end of the function's code; bytes before the first entry belong to no node. The compiler writes a new entry each time the node that produced the instructions changes, so one node can have several entries (a loop body reached again, or a pure node evaluated at two consumers). Instructions that evaluate a pure node are attributed to that pure node. A breakpoint on a node goes at the `pc` of each of its entries.
- **`pins`** in `wr.pins` list, per function, which node output pin each local holds. `local` is the function-wide local index used by `local.get` (parameters first, then declared and compiler-made locals). `node` and `pin` index the `strings` table of the same function in `wr.debug`, so a function with a `wr.pins` record must have a `wr.debug` record, and `--no-debug` drops both. Triples are sorted ascending by `(local, node, pin)`. A local may appear more than once when optimisation lets two pins share it. Pins that are never held in a local are not listed, which at `-Og` is none of them.

The layouts of `name`, `wr.meta`, `wr.reflect`, `wr.caps` and `wr.graph` are not yet fixed (section 9.2).

### 5.5 Verification

A conforming VM verifies every module before running any of it. The verifier makes one linear pass over each function and requires all of the following.

1. **Structure.** Sections are in order and sizes agree; every index is in range; exports are unique; the class hierarchy is acyclic; no struct type holds itself by value, directly or through other struct fields (a field that is an array of it is allowed); each vtable entry and interface implementation has the required signature. A type reference may point to a later type entry.
2. **Decoding.** Every instruction decodes; every branch target is an instruction boundary inside the same function. A first pass collects the set of labels.
3. **Empty stack at labels.** The operand stack is empty before every label, after `br`, `br_table`, `return`, `throw`, `unreachable`, and after `cont.pop` (which falls through only when no continuation exists). A branch may only occur when its own operands are the entire stack: `br_if` with exactly one `i32` on the stack, `br_table` likewise.
4. **Typing.** Each instruction's operands match its signature (section 5.6). References follow subtyping: a class is a subtype of its superclass chain and interfaces; every reference type is a subtype of `anyref`; null has every reference type. `local.*` and `global.*` match the declared types.
5. **Returns.** At `return` the stack holds exactly the function's result types.
6. **Limits.** The computed maximum operand stack height is at most `max_stack`. `try.push` names a local of type `fault`.
7. **Suspension and latency.** `suspend`, and any call to a function flagged latent, appear only in functions that are themselves flagged latent. A function flagged pure is never latent. `suspend` executes with only its operands on the stack. A non-latent function therefore cannot suspend, however deeply it calls.

Stack maps for the GC are derived by the verifier at call, allocation and suspend points and cached.

### 5.6 Instruction set

Notation: `[in] -> [out]`. `L` is a branch target, an `s32` offset relative to the end of the instruction. `T` is a type index and `f` a field index. Unless stated, a null reference operand faults.

**Control (00 to 0F)**

| Op | Mnemonic | Immediates | Stack |
| --- | --- | --- | --- |
| 00 | `unreachable` |  | faults |
| 01 | `nop` |  |  |
| 02 | `br` | L |  |
| 03 | `br_if` | L | `[i32]` -> `[]` |
| 04 | `br_table` | n, L0 ... Ln-1, Ldefault | `[i32]` -> `[]` |
| 05 | `return` |  | `[results]` -> |
| 06 | `call` | func | `[params]` -> `[results]` |
| 07 | `call_virtual` | T (declaring class), slot | `[recv, args]` -> `[results]` |
| 08 | `call_interface` | T (interface), method | `[recv, args]` -> `[results]` |
| 09 | `call_delegate` | T (func type) | `[delegate, args]` -> `[results]` |
| 0A | `cont.push` | L |  |
| 0B | `cont.pop` |  | Jumps to the top continuation; discards handler markers on the way; falls through if none. |
| 0C | `try.push` | L, local | Pushes a handler marker. On a fault the VM stores the fault in `local`, unwinds to the marker, clears the operand stack and jumps to L. |
| 0D | `suspend` | kind: 0 yield, 1 timer, 2 signal | `[]`, `[f64]` or `[signal]` -> `[]` |
| 0E | `throw` |  | `[fault]` -> . A `fault` is made with the native `std.fault.Make` and read with `std.fault.Message` and `std.fault.Code` (section 3.4). The type `fault` appears only in locals and function types. |
| 0F | `brk` |  | Reserved for debuggers. Never appears in a file. |
| 17 | `cont.depth` |  | `[]` -> `[i32]`: the number of entries on the frame's continuation stack, handler markers included. |
| 18 | `cont.trunc` |  | `[i32 n]` -> `[]`: discards the entries above the first `n`; nothing when `n` is negative or not below the depth. `Leave` uses the pair (section 4.2). |

**Variables and constants (10 to 2F)**

| Op | Mnemonic | Immediates | Stack |
| --- | --- | --- | --- |
| 10 | `drop` |  | `[t]` -> `[]` |
| 11 | `select` |  | `[t, t, i32]` -> `[t]`; first operand when the condition is non-zero. With two references the result has their common type: one if the other is its subtype, else `anyref`. This is how `Cast T` lowers without a branch: `ref.test T`, then `select` between the object and `ref.null T`, then `ref.cast T`, which cannot fault on either. |
| 12 / 13 / 14 | `local.get` / `.set` / `.tee` | index |  |
| 15 / 16 | `global.get` / `.set` | index |  |
| 20 / 21 | `i32.const` / `i64.const` | s32 / s64 | `[]` -> `[i32]` / `[i64]` |
| 22 / 23 | `f32.const` / `f64.const` | 4 / 8 bytes |  |
| 24 | `string.const` | data index | `[]` -> `[string]` |
| 25 | `ref.null` | T | `[]` -> `[ref T]` |
| 26 | `ref.is_null` |  | `[ref]` -> `[i32]` |
| 27 | `ref.eq` |  | `[ref, ref]` -> `[i32]`, identity. |
| 28 | `ref.cast` | T | `[ref]` -> `[ref T]`; faults unless null or an instance of T. |
| 29 | `ref.test` | T | `[ref]` -> `[i32]`; null gives 0. |
| 2A | `ref.valid` |  | `[ref]` -> `[i32]`; non-null and, for host handles, alive. |
| 2B | ref.share |  | \[ref\] -> \[ref\]. Marks an array, set or map object as shared (section 4.9) and returns the same reference. No effect on other references. |

**Numeric.** Four 32-slot blocks. The opcode is the block base plus the index in the table; for example `i32.add` is `30 + 0B = 3B`.

| Block | Base | Operations (index order) |
| --- | --- | --- |
| `i32.` | 30 | 0 `eqz`, 1 `eq`, 2 `ne`, 3 `lt_s`, 4 `lt_u`, 5 `gt_s`, 6 `gt_u`, 7 `le_s`, 8 `le_u`, 9 `ge_s`, 10 `ge_u`, 11 `add`, 12 `sub`, 13 `mul`, 14 `div_s`, 15 `div_u`, 16 `rem_s`, 17 `rem_u`, 18 `and`, 19 `or`, 20 `xor`, 21 `shl`, 22 `shr_s`, 23 `shr_u`, 24 `neg`, 25 `not`, 26 `extend8_s`, 27 `extend16_s` |
| `i64.` | 50 | Same indices, plus 28 `extend32_s`. Comparisons and `eqz` return `i32`. |
| `f32.` | 70 | 0 `eq`, 1 `ne`, 2 `lt`, 3 `gt`, 4 `le`, 5 `ge`, 6 `add`, 7 `sub`, 8 `mul`, 9 `div`, 10 `min`, 11 `max`, 12 `neg`, 13 `abs`, 14 `sqrt`, 15 `ceil`, 16 `floor`, 17 `trunc`, 18 `nearest`, 19 `copysign` |
| `f64.` | 90 | Same as f32. |

Integer `div` and `rem` by zero fault. `INT_MIN / -1` yields `INT_MIN` and the remainder is 0 (no fault). Shift counts are masked to the width. `min`/`max` return NaN if either operand is NaN. Narrow integer types are produced by `and` with a mask (unsigned) or `extend8_s`/`extend16_s` (signed) after arithmetic.

**Conversions (B0 to C8)**

| Op | Mnemonic | Op | Mnemonic | Op | Mnemonic |
| --- | --- | --- | --- | --- | --- |
| B0 | `i32.wrap_i64` | BB | `f32.convert_i32_s` | C3 | `f32.demote_f64` |
| B1 | `i64.extend_i32_s` | BC | `f32.convert_i32_u` | C4 | `f64.promote_f32` |
| B2 | `i64.extend_i32_u` | BD | `f32.convert_i64_s` | C5 | `i32.reinterpret_f32` |
| B3 / B4 | `i32.trunc_f32_s` / `_u` | BE | `f32.convert_i64_u` | C6 | `i64.reinterpret_f64` |
| B5 / B6 | `i32.trunc_f64_s` / `_u` | BF / C0 | `f64.convert_i32_s` / `_u` | C7 | `f32.reinterpret_i32` |
| B7 / B8 | `i64.trunc_f32_s` / `_u` | C1 / C2 | `f64.convert_i64_s` / `_u` | C8 | `f64.reinterpret_i64` |
| B9 / BA | `i64.trunc_f64_s` / `_u` |  |  |  |  |

All `trunc` instructions are **saturating** and map NaN to 0. They never fault.

**Objects and containers (D0 to F8)**

| Op | Mnemonic | Imm | Stack |
| --- | --- | --- | --- |
| D0 | `struct.new` | T | `[fields...]` -> `[ref]` |
| D1 / D2 | `struct.get` / `struct.with` | T, f | `[ref]` -> `[v]` / `[ref, v]` -> `[ref']` (copy with one field replaced) |
| D3 | `class.new` | T | `[]` -> `[ref]`, fields set to declared defaults, dispatchers empty. |
| D4 / D5 | `class.get` / `class.set` | T, f | `[ref]` -> `[v]` / `[ref, v]` -> `[]` |
| D6 | `array.new` | T | `[i32 length]` -> `[ref]`, filled with the element type's zero value (the identity for `quat` and `transform`, section 3.1.1), unshared. An array of a lane type stores its lanes packed, with no per-element object. |
| D7 | `array.len` |  | `[ref]` -> `[i32]` |
| D8 | `array.get` | T | `[ref, i32]` -> `[v]` (bounds-checked) |
| D9 | `array.set` | T | `[ref, i32, v]` -> `[ref']` |
| DA / DB | `array.push` / `array.insert` | T | `[ref, v]` / `[ref, i32, v]` -> `[ref']` |
| DC / DD | `array.remove` / `array.clear` | T | `[ref, i32]` / `[ref]` -> `[ref']` |
| DE | `array.clone` | T | `[ref]` -> `[ref']`, a fresh unshared copy. |
| E0 | `map.new` | T | `[]` -> `[ref]` |
| E1 | `map.find` | T | `[ref, key]` -> `[value, i32 found]` |
| E2 / E3 / E4 | `map.set` / `map.remove` / `map.has` | T | `[ref, key, v]` -> `[ref']` / `[ref, key]` -> `[ref', i32 was present]` / `[ref, key]` -> `[i32]` |
| E5 / E8 | `map.len` / `map.clear` | T | `[ref]` -> `[i32]` / `[ref]` -> `[ref']` |
| E6 / E7 | `map.key_at` / `map.value_at` | T | `[ref, i32]` -> `[k]` / `[v]`, insertion order. |
| E9 / EA / EB / EC | `set.new` / `.add` / `.remove` / `.has` | T | `add` and `remove` return `[ref', i32 changed]`; `has` returns `[i32]`. |
| ED / EE / EF | `set.len` / `set.at` / `set.clear` | T | as for maps |
| F0 | `string.concat` |  | `[string, string]` -> `[string]` |
| F1 | `string.len` |  | `[string]` -> `[i32]` (bytes) |
| F2 / F3 | `string.eq` / `string.cmp` |  | `[string, string]` -> `[i32]`; `cmp` is -1, 0 or 1 (ordinal bytes). |
| F4 | `delegate.new` | func, flags | `[]` or `[recv]` -> `[ref]`. Flag bit 0: bind a receiver as the first argument. Flag bit 1 (with bit 0): bind the receiver's override of `func`, as `call_virtual` would choose. The result's type is the module's delegate type for `func`'s signature without the receiver; the verifier requires one to exist. A latent function that is not an event cannot be bound. `call_delegate` on a delegate of an event queues the event on a new fiber and returns at once. |
| F5 / F6 | `dispatcher.bind` / `.unbind` | T | `[ref, delegate]` -> `[]` |
| F7 | `dispatcher.broadcast` | T | `[ref, args]` -> `[]`. Runs handlers in bind order; a handler's fault is reported to the host and does not stop the others. |
| FB | *prefix* |  | Next byte is a LEB128 sub-opcode: the lane instructions below. Sub-opcodes not listed are reserved. |

**Lane instructions (FB 00 to FB 7F).** Four 32-slot blocks, laid out like the numeric blocks: the sub-opcode is the block base plus the index, so `v3.add` is `FB 23`. All are pure, never fault (an `f32` division by zero gives an infinity or NaN), and compute exactly the formulas of section 3.1.1 in the order given there. `make` pops one value per field in field order; `get` and `with` take a `u8` field index immediate (`v3.get 1` reads `y`; `t.get 1` reads the rotation). Comparisons return `i32`.

| Block | Base | Operations (index order) and stack effect where not `[T, T] -> [T]` |
| --- | --- | --- |
| `v2.` | 00 | 0 `make` `[f32, f32] -> [v2]`, 1 `get` f `[v2] -> [f32]`, 2 `with` f `[v2, f32] -> [v2]`, 3 `add`, 4 `sub`, 5 `mul`, 6 `div`, 7 `min`, 8 `max`, 9 `neg` `[v2] -> [v2]`, 10 `abs` (same), 11 `scale` `[v2, f32] -> [v2]`, 12 `eq` and 13 `ne` `-> [i32]`, 14 `dot` `-> [f32]`, 15 `len` and 16 `lensq` `[v2] -> [f32]`, 17 `normalize` `[v2] -> [v2]`, 18 `lerp` `[v2, v2, f32] -> [v2]`, 19 `reflect`, 20 `perpdot` `-> [f32]` |
| `v3.` | 20 | Indices 0 to 19 as for `v2` (with three `f32` for `make`), then 20 `cross`, 21 `from_v2` `[v2] -> [v3]`, 22 `to_v2` `[v3] -> [v2]` |
| `q.` | 40 | 0 `make` (four `f32`), 1 `get` f, 2 `with` f, 3 `mul`, 4 `conj` `[q] -> [q]`, 5 `inverse` (same), 6 `normalize` (same), 7 `dot` `-> [f32]`, 8 `eq`, 9 `ne`, 10 `rotate` `[q, v3] -> [v3]` |
| `t.` | 60 | 0 `make` `[v3, q, v3] -> [t]`, 1 `get` f, 2 `with` f, 3 `mul`, 4 `inverse` `[t] -> [t]`, 5 `apply` and 6 `apply_vector` `[t, v3] -> [v3]`, 7 `eq`, 8 `ne` |

Every sub-opcode here is below `80`, so it encodes in one byte after `FB`. `FromAxisAngle`, `FromEuler`, `Slerp` and `Angle` are `std.quat` natives, since they need `Sin`, `Cos` and `Acos`.

All other opcodes are invalid. Everything else a node needs (string formatting, math, sorting) is a native in `std.*`, which keeps the instruction set small and lets embedders replace library functions.

### 5.7 Fuel

Each instruction costs 1 unit, a lane instruction included; `call`, `call_virtual`, `call_interface` and `call_delegate` cost 5; allocation adds 1 per 64 bytes (rounded up). Natives cost what they declare at registration, which may depend on their arguments (the container `Equals` natives: section 4.9). When a fiber's fuel reaches 0 it stops with `WR_ERR_FUEL`, which is not catchable. Counting is exact and deterministic, so fuel is a valid replay and billing unit.

### 5.8 Disassembly

`wiretc dis` prints the bytecode with node ids recovered from `wr.debug`. The two listings below are the compiled forms of `TakeDamage` and `SumTo` from section 2.6 (at `-O1`; at `-O0` the loop keeps its `cont.push` / `cont.pop` pair).

```
func game.demo.Player.TakeDamage (ref Player, i32) -> (i32)
  locals: 2:i32 new_hp
.set_new:
  local.get 0
  class.get Player.health
  local.get 1
  i32.sub
  local.set 2
.store:
  local.get 0
  local.get 2
  class.set Player.health
.chk:
  local.get 2
  i32.const 0
  i32.le_s
  br_if .log_dead
.ret_alive:
  i32.const 0
  return
.log_dead:
  string.const 0          ; "Player died"
  call host.Log
  i32.const 1
  return

func game.demo.SumTo (i32) -> (i32)
  locals: 1:i32 acc, 2:i32 loop.i, 3:i32 loop.last, 4:i32 loop.index
  local.get 0
  local.set 3             ; loop.last = n   (loop.first = 1 folded into the next line)
  i32.const 1
  local.set 2             ; loop.i = first
.test:
  local.get 2
  local.get 3
  i32.le_s
  br_if .body
  local.get 1             ; ret: total = acc
  return
.body:
  local.get 2
  local.set 4             ; Exit each: index = i
  local.get 1
  local.get 4
  i32.add
  local.set 1             ; add: acc = acc + index
  local.get 2
  i32.const 1
  i32.add
  local.set 2             ; bump
  br .test
```

Example encodings: `local.get 1` is `12 01`, `i32.const 1` is `20 01`, `i32.le_s` is `37`, `i32.add` is `3B`, and `br` back 10 bytes (the offset counts from the end of the instruction) is `02 F6 FF FF FF`.
