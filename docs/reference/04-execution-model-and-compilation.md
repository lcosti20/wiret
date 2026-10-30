## 4. Execution model and compilation

> **Provenance.** The supplied Blueprint documentation covers pins, macros, latent nodes and so on, but not the runtime rules below (re-evaluation of pure nodes, how a finished chain returns to a Sequence). Those rules reflect how Blueprints are commonly understood to behave and are specified here as Wiret's own semantics. Check them against Blueprint behaviour if exact compatibility matters.

### 4.1 Two kinds of nodes

Control flows along exec wires, one impure node at a time. Values flow along data wires and are produced by pure nodes on demand or by impure nodes when they run. A graph is therefore executable as a control-flow graph whose operands are small dataflow DAGs.

### 4.2 Exec flow and the continuation stack

Each call frame has a small **continuation stack**. Its entries are either a *continuation* (a place to resume) or a *fault handler marker* (section 4.6).

- Following an exec wire is a jump.
- A chain **ends** where an exec output is unconnected (or a node has no exec output). Ending pops the continuation stack and jumps to the popped continuation. If the stack holds no continuation, the frame ends: an event finishes. A function that declares results must have run `Return` first: the compiler rejects (`E0303`) any path it can prove ends with an empty stack, and warns (`W0302`) where it cannot decide. At run time such a function returns the zero value of every result.
- `Sequence` with `n` outputs pushes continuations for outputs `n-1` down to `1`, then jumps to output `0`. Each chain therefore runs to its end before the next starts, and the last chain runs in tail position with nothing pending.
- `Exit` leaves a macro by jumping to the caller's chain wired to that macro output. Placed on the first output of a `Sequence`, it runs that chain as a subroutine: when the chain ends, the continuation resumes the macro. That is how `ForRange` in section 2.6 works, with no loop primitive and no separate call node.
- `Return` discards the whole frame, including pending continuations.

Because every bytecode label is a type-safe jump target (section 5.5), the stack's depth does not have to be statically known. When the compiler can prove the depth (the common case), the optimiser replaces the push/pop pair with a direct branch, and the generated code looks like structured code.

#### Transition rules

Let `S` be the frame's continuation stack, with the top at the right. Each step below is the complete effect of one event on `S` and on the next node.

| Event | Effect |
| --- | --- |
| Follow an exec wire | `S` unchanged; next node is the wire's target. |
| Chain end | Pop `S`. A continuation `k`: next node is `k`. A handler marker: discard it and keep popping. `S` empty: the frame ends. |
| `Sequence` with `n` outputs | Push the entries of outputs `n-1`, ..., `1` (so output 1 ends up on top); next node is output 0. |
| Macro call site | Inlined, so no stack effect. Data inputs are captured into the expansion's locals; next node is the macro's `Entry` exec output for the exec input that was wired. |
| `Exit o (vals)` | Assign the bound data outputs `vals`, then next node is the caller's target wired to macro output `o`; if `o` is unwired, this is a chain end. **`S` is not touched**: continuations the macro pushed stay pending, and anything the caller's chain pushes sits above them. |
| `Try` | Push a handler marker, then run `body`. |
| Fault | Pop `S` down to the nearest handler marker, discarding every continuation above it, and jump to its handler. No marker: the fiber ends with the fault. |
| `Return` | Discard the frame, including `S`. |

An `Exit` that leaves data outputs unbound keeps their previous values (the zero value if none was assigned), the same persistence rule as other impure outputs (section 4.3). Because `Exit` is a jump and not a call, there is no "return from Exit": the only way back into the macro is a continuation the macro itself pushed.

#### Joins

An exec input with several producers is a **join**. There is no merge of state at a join; the node simply runs when any producer reaches it, and:

- Its pure inputs are evaluated at the join node's own evaluation point (section 4.3), not at the producers. Which producer was taken is not visible to it.
- `S` is whatever the arriving path had. Paths with different stack depths may join; the verifier only requires that every label be a valid jump target (section 5.5).
- Data outputs of impure nodes that sit on only some of the paths into a join are read as "the last value stored, else the zero value". `W0310` fires when the producer does not dominate the reader, which is exactly the situation a join creates; a reader after a join should read a local that every path assigned.
- A back-edge to a join (a loop) re-runs the join and everything after it with the current stored values. Nothing is reset.

#### Worked trace: one `ForRange` iteration

`SumTo(2)` from section 2.6, after macro expansion. The call site is `loop` with `each -> add` and `done -> ret`. Macro nodes carry path-style ids (`loop/test`, ...). `S` is shown with the top at the right; `[]` is empty. `i` is the macro local, `acc` is the caller's local.

| Step | Node | Action | `S` after |
| --- | --- | --- | --- |
| 1 | `entry` | start; follow to `loop` | `[]` |
| 2 | `loop/init` | `i := 1` | `[]` |
| 3 | `loop/test` | `1 <= 2` is true; follow `then` | `[]` |
| 4 | `loop/seq` | push the entry of output 1 (`loop/bump`); jump to output 0 | `[loop/bump]` |
| 5 | `loop/each_out` | `Exit each (index: i)`: `loop.index := 1`; jump to caller target `add`. `S` untouched | `[loop/bump]` |
| 6 | `add` | `acc := acc + loop.index = 1`. No exec output: chain end, pop `loop/bump` | `[]` |
| 7 | `loop/bump` | `i := 2`; follow to `loop/test` | `[]` |
| 8 | `loop/test`, `loop/seq`, `loop/each_out`, `add` | as steps 3 to 6 with `i = 2`: `acc := 3`; chain end pops `loop/bump` | `[]` |
| 9 | `loop/bump` | `i := 3`; follow to `loop/test` | `[]` |
| 10 | `loop/test` | `3 <= 2` is false; follow `else` | `[]` |
| 11 | `loop/finish` | `Exit done`: jump to caller target `ret` | `[]` |
| 12 | `ret` | `Return(total: acc = 3)`; frame discarded | n/a |

Two properties follow from the trace. The stack is balanced on every iteration (pushed at step 4, popped at step 6), so its depth depends on how deeply loops are nested and not on how many iterations run. And the continuation that resumes the macro after the caller's chain is the one `Sequence` pushed; `Exit` contributes nothing. That is the whole mechanism, which is why `ForRange` needs neither a loop primitive nor a call node.

#### Required macro tests

Section 7.4 requires each of these as a trace test (expected `S` after every step, not only the final result):

1. **Nested loops.** A `ForRange` inside the `each` chain of another. At the inner `each` body, `S` holds the outer `bump` below the inner `bump`; the inner `done` returns to the outer chain's next node.
2. **`Sequence` inside a macro body.** A macro that sequences two `Exit`s, to confirm the later one runs only after the caller's chain for the earlier one has ended.
3. **Early exit.** A `Return` inside the `each` chain discards the pending `bump` with the frame. A caller chain cannot leave a macro any other way; a loop macro that offers `break` as an input does so with a `state` flag the `bump` step checks (**Provisional**: revisit if this proves awkward).
4. **Unwired `Exit`.** `Exit` to an unwired caller output behaves as a chain end and pops a pending continuation if one exists.
5. **Faults.** A fault in the `each` chain with a `Try` outside the loop pops the pending `bump` and everything above the marker; a `Try` entirely inside the `each` chain leaves the macro's continuation untouched.
6. **Join.** Two producers wired to one exec input, and a read of an impure output on a path where its producer did not run (zero value, `W0310`).

### 4.3 Pure nodes and data persistence

- **Evaluation point.** Each time an impure node is about to run, the pure nodes feeding its inputs are evaluated, all at that moment and before the impure node's own effect. Evaluating them performs no writes, so every read of mutable state by those pure nodes sees the same state: the state at the evaluation point. A shared sub-expression is computed once per evaluation point. A pure node feeding two different impure nodes is evaluated at each one, and the two results differ if state changed in between. This is the familiar Blueprint behaviour and it is why `TakeDamage` stores its intermediate result in a local.
- **Order.** Within one evaluation point, inputs are evaluated depth-first in the consumer's pin order from the registry, left to right. A node already evaluated at this point is reused. An implementation may reorder or share work only if no one can tell: results, the choice of fault, and fuel accounting must be as if this order were followed.
- **Faults in pure nodes.** A fault in a pure node is raised at the consumer's evaluation point, before the consumer runs, and it is the first fault in the order above. A pure node whose result nobody demands is not evaluated and cannot fault. `Select`, `And` and `Or` demand all their inputs, so a fault in the untaken side of a `Select` is raised.
- **Impure outputs persist.** A data output of an impure node (a call result, `loop.index`) is stored in a frame slot when the node runs. Any later node may read it. Reading it on a path where the node has not run yet gives the zero value; the compiler warns (`W0310`) when a read is not dominated by the producing node.
- **No short-circuiting.** `And`, `Or` and `Select` evaluate every input. Use `Branch` for conditional evaluation.
- **Macro inputs** are evaluated once, at macro entry, and captured in locals.
- **Cycles** among pure nodes are rejected (`E0301`). Cycles through exec wires are loops and are allowed.

**Calls to pure and reads functions.** A call to a `@pure` or `@reads` function is itself a pure node. When its value is demanded, the callee runs its own exec graph to completion and returns its results, so such a function can contain branches, loops and recursion (`Fib` in section 2.6).

#### Purity levels

"Pure" is three separate guarantees. A function or native provides some of them, and each attribute names what it provides.

| Guarantee | Meaning | `@reads` | `@pure` |
| --- | --- | --- | --- |
| Effect-free | Does not write any state another computation could observe: variables, fields, `state`, containers reachable from outside the call, host state. Writing its own locals is allowed. | yes | yes |
| Deterministic | The same explicit arguments **and the same VM state** give the same result (and the same fault, if any). | yes | yes |
| Cacheable | The result depends only on the explicit arguments and `const`s, so it may be memoised or hoisted across state changes. | no | yes |

Rules:

- **Reads of mutable state.** `GetField`, `GetVar`, `GetState` and dereferencing a class reference or host handle are `reads` operations. They are fine in a `@reads` function and forbidden in a `@pure` one (`E0304`). A struct, enum, string or container passed as an argument is a value and may be read freely, since the caller's copy cannot change under the callee. A class reference may be passed, compared with `Eq` or tested with `IsValid`'s null check, but not dereferenced.
- **Calls.** A `@pure` function may call only `@pure` functions and natives flagged cacheable; a `@reads` function may also call `@reads` functions and natives flagged effect-free. Anything else is `E0304` (reads) or `E0302` (writes or latent).
- **Cacheability is what the optimiser may use.** Common-subexpression elimination across a state change, hoisting out of loops and memoisation apply only to `@pure` calls and `pure`-purity kinds. A `reads` node is never moved across a write to anything it could read.
- **Faults are results, not effects.** A fault is part of what a deterministic function returns: the same arguments fault the same way. So a pure call that may fault is kept when its result is unused (removing it would remove the fault), and it is never reordered past another node that could fault or write when that would change which fault is observed. Fuel exhaustion and an interrupt are not faults of the function; they are the VM's limits (section 5.7) and are exempt.
- **Natives are trusted, not proved.** The VM cannot check a native's flags. A host registers `WR_NATIVE_EFFECT_FREE`, `WR_NATIVE_DETERMINISTIC` and `WR_NATIVE_CACHEABLE` (section 6.6) and is responsible for them. With `WR_CFG_AUDIT_NATIVES`, the VM calls each cacheable native twice and compares the results, and reports `WR_ERR_API` on a mismatch; this finds some false claims and proves none.
- **Warning.** `W0320` fires when a `reads` node, or a call to a `@reads` function, feeds more than one impure consumer, since the consumers may see different values. The usual fix is to store the value in a local first, as `TakeDamage` does.

The compiler, not the verifier, checks effect-freedom and the read restrictions (`E0302`, `E0304`); the verifier only checks that such functions are never latent.

### 4.4 Functions, events, macros and groups

| Construct | Semantics |
| --- | --- |
| Function | Callable, may recurse, returns results. A function that may suspend is declared `@latent`, and the compiler checks the declaration (`E0201`): a function that contains a latent node, or calls a latent function or event, must be latent. A latent function is never `@pure` or `@reads`. Unlike Blueprint functions, Wiret allows this, but only when it is declared. |
| Event | A function with no results, intended as an entry point. Events are implicitly latent. Invoked by the host (`wr_push_func` plus `wr_call` or `wr_start`) or by `Call` from another latent graph. |
| Macro | Expanded in place before type-checking the caller's body. Macro locals are renamed per expansion, so two expansions never share state; `state` slots are one per expansion site. After expansion, node ids are path-style (`loop/test`), and each macro exec pin gets a synthetic stub id (`loop!each`), so debug data and diagnostics point into the macro's own nodes. A macro may not expand itself, directly or indirectly (`E0401`). |
| Collapsed group | Editor-only. A layout `box` with `collapsed = true` and explicit `members` is drawn as a single node whose pins are the wires crossing the box edge. The compiler sees the flat graph. |

### 4.5 Latent nodes and fibers

Every call runs on a **fiber**: its own value stack and call frames, heap-allocated and owned by the VM. A latent node (`Delay`, `Yield`, `Await`) compiles to `suspend`, which parks the whole fiber, including every frame beneath it, until its wake condition. The fiber resumes at the next instruction with all frames intact. Rules:

- **Latency is declared and checked.** Latent nodes (`Delay`, `Yield`, `Await`) and calls to latent functions or events are allowed only inside latent functions and events (`E0201` otherwise). The verifier enforces the same rule on bytecode: `suspend` and calls to a callee flagged latent appear only in functions flagged latent. A call to a non-latent function therefore can never suspend. A host can call a non-latent export with `wr_call` and rely on getting `WR_OK` or an error, never `WR_YIELD`.
- Latent nodes are rejected inside `@pure` functions (`E0302`) and inside natives (natives cannot suspend in version 1; see section 6.6).
- A fiber can only suspend if every frame between it and its base is a Wiret frame. A native that calls back into Wiret and then yields would have to unwind a C frame, which the VM refuses (`WR_ERR_API`), as Lua does for yielding across a C call.
- Time is virtual. `Delay` waits for virtual seconds that advance only when the host calls `wr_advance`. Wake order is by wake time, then by fiber creation order, so scheduling is deterministic. The full list of conditions for replay is in section 4.10.

### 4.6 Faults

A **fault** is a runtime error: null dereference, array index out of range, integer divide by zero, failed `ref.cast`, stack overflow, `Throw`, or an error returned by a native. Faults are catchable with `Try`. `Try` lowers to a *handler marker* pushed on the continuation stack. On a fault, the VM pops the stack down to the nearest marker, stores the fault in a local, clears the operand stack, and jumps to the handler. Normal chain ends discard markers while looking for the next continuation.

A `Try` body must be properly nested: the nodes reachable from `body` must not also be reachable from outside it (`E0412`). Without that rule a stale marker could survive past the end of the region.

Some faults cannot be caught: fuel exhausted, memory limit exceeded, and a fiber killed by the host. These end the fiber and are reported to the host.

**Provisional.** Catchable faults are the least proven part of this design. If prototyping shows that the nesting rule `E0412` rejects graphs that users find natural, `Try` and `Throw` move to a later version. Every fault would then end its fiber and be reported to the host with a node-level traceback (section 6.9), which is a complete and simpler model on its own.

### 4.7 Diagnostics

| Code | Meaning |
| --- | --- |
| `E0101` / `E0102` | Binding or exec target names an unknown node / duplicate node id. |
| `E0103` | Unknown pin on a node. |
| `E0110` | Wire type mismatch (and no supertype relation). |
| `E0111` | The same input pin is bound twice. |
| `E0120` | Exec output wired to a data pin, or a data wire to an exec pin. |
| `E0121` | An exec output is listed twice. |
| `E0301` | Cycle among pure nodes. |
| `E0302` | `@pure` or `@reads` function writes variables, fields or state, contains a latent node, or (`@reads`) calls a function that is neither `@reads` nor `@pure`. |
| `E0304` | `@pure` function reads variables, fields or state, dereferences a class reference or host handle, or calls anything that is not `@pure`. |
| `E0401` | Macro expands itself. |
| `E0412` | `Try` body is not properly nested. |
| `E0501` / `E0502` | Unresolved symbol / missing type argument. |
| `W0201` | Input left unbound and no declared default. |
| `W0301` | Node unreachable from any entry. |
| `W0302` | Chain can end in a function that declares results. |
| `W0310` | Read of an impure output not dominated by its producer. |
| E0130 | Container mutation node does not target a place (local, variable or field). |
| E0900 | Edit rejected: the document changed since the hash the edit was based on (section 7.2). |
| E0201 | A function that is not latent contains a latent node or calls a latent function or event. |
| E0303 | A path provably ends, with no pending continuation, in a function that declares results and has not returned. |
| E0140 | A node, box, note or `@id` reuses an id recorded as retired in `wiret.ids` (section 7.3). |
| W0202 | Element has no `@id`, or the file is not in a project and non-reuse cannot be checked (section 2.4). |
| W0320 | A `reads` node feeds more than one impure consumer (section 4.3). |
| W0601 | A box lists a member id that names no node or box. |
| W0602 | A node or box is listed as a member of more than one box. |
| W0603 | `wiretc fmt` would drop a `//` comment (section 2.1). |
| W0604 | A note's `on` target no longer exists. |

Diagnostics are structured records, not only text: `code`, `severity`, `message`, `module`, `graph`, `node` and `pin`. `wiretc check --json` prints one record per line. An editor uses `node` and `pin` to highlight the exact place on the graph, and an LLM agent feeds the records back to itself until the check is clean (section 7.2). Diagnostics that arise inside an expanded macro carry the path-style node id (section 4.4).

### 4.8 Lowering a graph to bytecode

1. **Expand macros** into the caller, giving every inlined node a path-style id. Entry inputs become locals, `state` slots become hidden fields or globals, and `Exit` becomes a jump plus local assignments.
2. **Assign locals.** Parameters first, then declared `local`s, then one slot for each data output of each impure node that is read by another node, then temporaries.
3. **Form blocks.** Each impure node starts a block labelled with its node id. The block evaluates the pure subgraph for its inputs in dependency order, using `local.tee` for shared values, performs the operation, stores outputs, and ends with the exec transfer.
4. **Emit exec transfers.** A single target becomes `br` (omitted when the target is next in layout). `Branch` becomes `br_if`. `Switch` becomes `br_table` (or a compare chain for strings). `Sequence` and `Try` use the continuation instructions.
5. **Optimise.** Constant folding, removal of unread locals, branch threading, layout so fall-through follows the exec wire, and replacement of statically balanced `cont.push` / `cont.pop` by `br`. At `-Og` nothing that would hide a pin value is removed: every pin of every node is kept in a local, for debugging.
6. **Record debug data.** Each block's start offset is mapped to its node id (`wr.debug`), and each pin's local to its node and pin name (`wr.pins`).
7. **Verify** the result with the same verifier the VM runs at load time (section 5.5). A compiler bug can therefore never produce an unsafe module.

### 4.9 Containers have value semantics

`array<T>`, `set<T>` and `map<K,V>` are value types, as arrays are in Blueprints. Assigning one, passing it to a function, storing it in a field or returning it gives the receiver its own logical copy, and changing one never changes another. Two variables never alias one array.

Copying eagerly would make a loop that appends to an array quadratic, so the VM implements the rule as **copy-on-write** with a single `shared` flag per container object:

- **Fresh containers are unshared.** `array.new`, `array.clone` and the result of any mutating instruction start unshared.
- **Letting a reference escape marks sharing.** When the value of a container variable, field, parameter or element is bound to anything that can retain it (another variable or field, a call argument, a return value, a macro input), the compiler emits `ref.share` after the read. `ref.share` sets the flag and returns the same reference. Read-only nodes (`ArrayGet`, `ArrayLength`, `MapFind`, ...) do not need it.
- **Mutating instructions return the container.** `array.push` and the other mutators take the container and return one. If it is unshared they change it in place and return the same reference. If it is shared they change a fresh copy and return that. The compiler stores the result back into the place being changed, which is how `ArrayAdd<i32> acc (item: x)` works.
- **A mutation node reads its own place without marking it.** A loop that keeps adding to a local array therefore changes it in place, at constant cost per iteration, as long as nothing else has read it.
- **The flag is never cleared.** A holder that still points at a shared object copies it once on its next mutation and then owns an unshared copy. That costs at most one extra copy per sharing event and needs no reference counts, so the tracing collector is unchanged and every run behaves identically.

Consequences:

- `ForEach` iterates the array as it was when the loop started, because a macro input is captured (and so marked shared) at entry. Changing the variable inside the body does not disturb the iteration.
- A struct that contains a container holds it by shared reference. Because every read marks it shared, nothing can change a struct through its array.
- Containers of containers follow the same rule at each level: reading an element that is itself a container marks it shared.
- Classes, delegates and host handles stay reference types. An `array<Player>` copies the references, not the players.
- The optimiser removes a `ref.share` when liveness analysis shows the source holder is dead after the read, which is the common case when a function builds a local array and returns it.
- `Eq` and `Ne` on containers are structural (element-wise for arrays; set and map equality ignores insertion order) and compile to calls to `std.array.Equals`, `std.set.Equals` and `std.map.Equals`.

### 4.10 Deterministic mode

Repeatable execution is a mode, not a property of every run. A VM created with `WR_CFG_DETERMINISTIC` promises: for the same `.wbc`, the same configuration, and the same **input log** (the ordered sequence of host API calls with their arguments, plus every value a native returned), every fiber executes the same instructions, consumes the same fuel and produces the same results and faults. Outside this mode the language is still memory-safe but promises no repeatability.

The mode requires all of the following.

1. **Deterministic natives only.** `wr_register` refuses a native without `WR_NATIVE_DETERMINISTIC` (section 6.6). A native that returns host-dependent data (time, input, files) is not flagged; in a replay its result must come from the input log.
2. **Floating point is specified** (**Provisional**):
   - `f32` and `f64` use IEEE-754 binary32 and binary64 with round-to-nearest-even for `+ - * /`, `Sqrt`, `Floor`, `Ceil` and conversions. No fused multiply-add contraction, no extended-precision intermediates, no flush-to-zero; subnormals are kept.
   - Every operation that produces a NaN produces the canonical quiet NaN (`0x7FC00000`, `0x7FF8000000000000`), so NaN payloads and signs are never observable. `Eq` with a NaN is false, `Ne` is true, and `Lt Le Gt Ge` are false. `Min` and `Max` return NaN if either input is NaN (not IEEE minNum), and order `-0` before `+0`.
   - `Round` rounds half away from zero. Float to string uses the shortest round-trip text (section 3.2).
   - `std.math` functions that are not exactly rounded by IEEE (`Sin`, `Cos`, `Pow`, `Atan2`, `Exp`, `Log`, ...) use the VM's bundled implementation with a fixed algorithm and evaluation order, not the platform's `libm`. Outside the mode they may call `libm`, and their last bits may differ between platforms.
3. **Defined iteration and scheduling order.** Maps and sets iterate in insertion order. Fibers wake by wake time, then fiber creation order (section 4.5). Fibers made runnable at the same `wr_advance` run in that order, each until it suspends, finishes or runs out of fuel; there is no time-sliced preemption. Waiters on a signal resume in the order they began waiting. Dispatcher handlers run in bind order.
4. **Host events enter only at API boundaries.** The host affects a VM only through API calls (`wr_call`, `wr_advance`, firing a signal, `wr_grant`, ...), and the sequence of those calls is the input log. A native may call back into Wiret only with a call that is itself part of the log.
5. **Limits are logical.** Fuel counts instructions (section 5.7). `max_heap_bytes` is charged by the VM's own accounting of object sizes, not by what the allocator returns, so a memory-limit fault happens at the same instruction on every platform (**Provisional**).

Excluded from the guarantee:

- **`wr_interrupt`** is driven by a thread or a wall clock. In deterministic mode an interrupt still stops the fiber with `WR_ERR_INTERRUPT`, but the run is marked non-replayable in `wr_get_stats`. Use fuel for limits that must replay.
- **Unlogged host callbacks**: a native whose result is not in the log, or that reads state outside the VM.
- **Host `finalize` callbacks**, which run when the collector frees a host handle. Collection timing is not observable from Wiret, but it is not specified either.
- **Differences in the host environment** that the VM does not control: a different allocator that fails earlier than the logical limit, a different build of the same natives.

The claim of identical results on every platform is a **target** until the conformance suite (section 7.4) passes the same golden traces on at least two CPU architectures and two compilers.
