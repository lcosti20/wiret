## 9. Open questions and next steps

### 9.1 Decisions I would revisit once there is a prototype

1. **Pure-node re-evaluation.** It matches Blueprints and is easy to compile, but it is a known source of surprises (a random-number node feeding two consumers gives two values). Alternatives are caching per event, or an explicit `Latch` node. The compiler could also warn when an impure-reading pure node feeds more than one impure consumer.
2. **Canonical order by node id.** It gives the best merges but a flow-hostile file. Section 2.5 already moves review to flow-ordered diffs (textconv and `wiretc diff`). Before freezing storage order, run a **review trial** on a real corpus: the same pull requests reviewed with raw id-ordered diffs, flow-ordered textconv diffs and `wiretc diff`, measuring review time, defects found, and merge-conflict rate of id-sorted versus flow-ordered storage. Keep id-sorted storage if the flow-ordered views close the readability gap. If not, an optional `@order(n)` hint (derived from flow order and ignored by the semantic hash) could be added at the cost of noisier diffs.
3. **Nesting rule for `Try`.** `E0412` is conservative. It may reject graphs that users find natural. A region-aware lowering could allow more.
4. **Immutable structs.** `WithField` allocates. Escape analysis in the optimiser should remove most of that, but it should be measured.
5. **Generics by monomorphisation.** Simple and fast, but code size grows with instantiations. Shared generic code with a type descriptor argument is the alternative.
6. **Cooperative-only natives.** Natives cannot suspend. Real engines often want a latent native (async I/O). The `Signal` pattern covers it, but with more ceremony.

Three further questions are open.

- **Stack versus register bytecode.** A register machine gives every pin its own register, which makes value probes trivial and avoids stack bookkeeping. The stack form is denser and easier to emit, and `wr.pins` with `-Og` recovers most of the debugging benefit. A benchmark of both on a real corpus should decide; the graph-to-block lowering would not change.
- **Explicit latency.** Declaring `@latent` gives hosts a hard guarantee but spreads through call chains like `async`. Revisit it if users find it burdensome.
- **Continuations at run time or compile time.** Section 4.2 keeps pending exec continuations on a runtime stack. The alternative, duplicating shared nodes at compile time, needs no such stack but can multiply code and needs a nesting limit.

### 9.2 Not covered in this draft

- Byte layouts of the custom sections `name`, `wr.meta`, `wr.reflect`, `wr.caps` and `wr.graph` (including the deflate framing of `wr.graph`). Only `wr.debug` and `wr.pins` are fixed (section 5.4.1).
- Exact pin lists and bodies for every `std.*` function and `std.flow` macro, and string `Format` syntax.
- Interface method call nodes beyond `Call`, enum `Switch` ergonomics, and `Format Text`-style nodes.
- Blueprint features that are really engine features: timelines, construction scripts, components, replication, soft references and data tables. These would be host-provided natives and extern types, or a layer on top of Wiret.
- Hot reload and state migration (the `@id` attributes are there to make this possible), serialisation of suspended fibers for save games, multi-threaded VMs, a wire protocol for remote debugging, and a WebAssembly backend or JIT.

### 9.3 Suggested build order

The steps below follow the tiers of section 1.6. Steps 1 to 3 and the interpreter half of step 4 are Tier 0; classes, async, `Try`, copy-on-write, the full C API and the debugger wait until Tier 1 is passing.

1. Parser, printer and formatter with round-trip tests. Use the canonical form of section 2.6 (id-sorted, no alignment) as the first golden file and add a test that `fmt(fmt(x)) == fmt(x)`.
2. Resolver, type checker and graph validator, driven by the diagnostics table.
3. Lowering, the verifier and the disassembler. Section 5.8 gives expected output for `TakeDamage` and `SumTo`.
4. A bytecode interpreter with fuel counting, then the C API and the host example in 6.11.
5. The standard library and `std.flow` macros, written in Wiret wherever possible so they double as tests.
6. Debug data, hooks and breakpoints, then the editor integration.
