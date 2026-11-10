# Wiret Language Specification

*Draft 0.13: text syntax, bytecode (WBC) and embedding API for a text-based visual scripting language*

> **Status.** This is a design draft, not an implementation. Nothing here has been run through a real parser, verifier or VM, so treat the grammar and opcode tables as a starting point to test, not a frozen standard. Where I went beyond your reference documents (mainly Blueprint runtime behaviour that the supplied documentation does not spell out), the text says so.

**Draft 0.2.** Revised after comparing three independent proposals (Appendix A lists every change and where it came from). The largest semantic change: `array`, `set` and `map` are now **value types** with copy-on-write, as arrays are in Blueprints (section 4.9). New material: a machine-readable node registry (3.5), a merge and editing protocol for tools and LLMs (7.1, 7.2), cross-module linking and a project manifest (7.3), capabilities, feature bits, interrupts and statistics (5.2, 5.4, 6.5, 6.10), and conformance levels (7.4).

**Draft 0.3.** Incorporates the strongest parts of an independently developed design (Appendix B). Layout moves out of node lines into a per-graph `layout` block, so moving a node and rewiring it no longer touch the same line (2.3, 2.5, 7.1). Macros gain persistent `state` slots (2.3, 4.4). Latency becomes an explicit, compiler- and verifier-checked property of a function (4.4, 4.5, 5.5). Debug data now maps pins to locals, and hosts can probe pin values (5.4, 6.10). The host ABI is hardened (6.3, 6.5, 6.6). Merging is specified as a keyed, node-level operation (7.1). A contract for graph editors and a recommended reference-implementation path are added (7.5, 7.6).

**Draft 0.4.** Responds to a review of 0.3 (Appendix C). The scope is now cut into implementation tiers, and only Tier 0 is a prototype target (1.6). Evaluation is specified step by step, with an explicit evaluation point, fault ordering and join behaviour (4.2, 4.3). `@pure` is split into a precise contract plus a new `@reads` level (2.4, 4.3). Macro `Exit` has transition rules and a worked continuation-stack trace (4.2). Determinism is a defined mode with stated conditions and exclusions rather than a blanket claim (4.10). Persistent `notes` replace silently dropped comments (2.1, 2.3). Identity rules say what a single file can and cannot guarantee, and a project id registry supplies non-reuse (2.3, 2.4, 7.3). Layout-box membership is always explicit (2.3). Git diffs default to flow order while storage stays sorted by id (2.5, 7).

**Draft 0.5.** Records three decisions made while building the editor (Appendix D). `--export-all` builds export every function so the editor can run any of them, while release builds still export only `@export` items (2.4, 5.2). Saved text is never aligned on `=` (or on `at` in the layout block), because aligning breaks the one-line-diff rule (2.5). The binary details the draft left open are fixed: number encodings, branch offsets, and the layouts of `wr.debug` and `wr.pins` (5.1.1, 5.4.1).

**Draft 0.6.** Three syntax changes make graphs easier to scan (Appendix E). Every generic argument list is introduced by `::`, as in `Add::<i32>`, `macro ForEach::<T>` and `array::<i32>`, so a node line like `node x = NodeType::<a, b> sym` cannot be misread as a comparison (2.2, 2.3). A node's inputs move out of call-style parentheses onto their own lines below the node, `.pin <- value`, mirroring the `->` of exec wires (2.3, 2.5). Metadata that never changes compiled output is written `#[doc("...")]` on its own line above what it describes, while `@` is kept for semantic attributes such as `@pure`; notes become `#[note("...")]` lines and the `markup` block is removed (2.4).

**Draft 0.7.** Records decisions made while adding structs and enums to the prototype (Appendix F). An enum value is written `Mode.Chase`, on pins, as defaults and in `@cases` (2.1, 2.3). Struct nodes name their struct, and field nodes the field too: `MakeStruct Vec2`, `GetField Vec2.x` (2.3, 3.3). Reading a struct is `pure`, also in a `@pure` function, since a struct is a value (3.3, 4.3). Struct fields and enum members keep their written order in the canonical form (2.5). A struct's default value comes from its field defaults, stored in its type entry (3.1, 5.3), and struct equality compares field by field (4.9). A struct may not hold itself by value (`E0503`; 2.2, 4.7, 5.5).

**Draft 0.8.** Records decisions made while adding maps, sets, container equality, ids and merging to the prototype (Appendix G). Map and set nodes have fixed pins, and the mutators that may change nothing say whether they did (3.3). Every NaN is the same map key or set item (3.1). Container equality calls one native per container kind, which takes `anyref` and declares its fuel cost (3.4, 4.9, 5.7). `@id`s and `W0202` are required only in a project (2.4, 4.7), and `wiret.ids` has a fixed line format (7.3). A merge matches an element to the same element after it gains an `@id`, carries renames across, lets the incoming side win layout disagreements, and marks a deleted-versus-modified node as a whole block (7.1).

**Draft 0.9.** Node statements change shape, following the research note on text syntax for a Blueprint-style language (Appendix H). A node's inputs are written in parentheses, comma separated with a trailing comma allowed, and a node without inputs is written `Entry()` (2.3). A node's metadata lines move to its line in the layout block (2.3, 2.4). A node that exactly one input reads, with no exec pins and no semantic attribute, is written inline in that input and named by its position, `show.message` (2.3, 2.5); such names are never retired (7.3). The verifier rejects unknown function flags and an event with results (5.2).

**Draft 0.13.** Adds the built-in types `vec2`, `vec3`, `quat` and `transform` for game scripting (Appendix L). They behave like structs with fixed `f32` fields, but the VM holds them unboxed, so per-frame vector math never allocates (3.1.1, 5.3). Tuple literals such as `(0, 1, 0)` write them (2.1). The arithmetic kinds work on them component-wise, `Mul` composes rotations and transforms, and `std.vec`, `std.quat` and `std.transform` are defined by formulas with a fixed evaluation order, so results are deterministic (3.1.1, 4.10). New lane instructions in the `FB` prefix space (5.6) and `wr_push_vec3`-style host calls (6.7) complete it. The prototype implements all of it except `std.quat.FromEuler`; it stays **Provisional** until a native VM has run it.

**Draft 0.12.** Takes the last group of changes from the review (Appendix K). A node that reads mutable state and is evaluated again at two consumers that run one after the other is the error `E0320` unless it is stored in a local or marked `@live` (2.4, 4.3). `Leave` ends a macro early, and every `std.flow` loop has a `break` input (3.3, 3.4, 4.2). A wire from a declared node with one data output leaves the output out, `.value <- hp` (2.3). Enum values are written `Mode::Chase`, so a node may share an enum's name (2.1, 2.3). Keywords are contextual, and only `true`, `false` and `null` are reserved (2.1).

**Draft 0.11.** Makes the text shorter to write and easier to read, following the same review (Appendix J). An inline node with one data output no longer names it (`Convert::<i32, string>(...)`, not `(...).result`). A function with one result that is a single expression is written `= value`, with its parameters named bare. A `Format` node builds text from a template, replacing chains of `Concat` and `Convert`. Each graph opens with its `flow` block, so it reads as the order in which it runs and then the nodes. A `//` comment directly above a declaration, statement, input or wire is kept, through formatting, editing and merges (2.1, 2.3, 2.5, 3.3).

**Draft 0.10.** Removes four ways for a correct-looking graph to fail, following a review of Draft 0.9 (Appendix I). `Select` evaluates only the input it chooses, and `And` and `Or` short-circuit, so a fault in an unchosen input is never raised (3.3, 4.3). Reading an impure output that its producer does not dominate is the error `E0310` instead of a silent zero (4.2, 4.3). A layout line whose name is no longer a node, as a hand edit that moves an inline node leaves behind, is kept and reported as `W0605` instead of making the file unreadable (2.3). A promoted inline node never takes a live or retired id (2.3). Members of a class are always written qualified, `GetField Player.health` (2.3, 3.3).

**Implementation status.** Nothing in this document is implemented. Parts expected to change after prototyping are marked **Provisional**: catchable faults (4.6), the copy-on-write rules for containers (4.9), the deterministic-mode floating-point rules (4.10), and the choice of a stack rather than a register machine (9.1). Guarantees about exact diagnostics and cross-platform determinism are targets until the tier in section 1.6 that contains them has passed its tests.

## Contents

- [1. Overview](reference/01-overview.md)
- [2. Text syntax](reference/02-text-syntax.md)
- [3. Types and the built-in node set](reference/03-types-and-the-built-in-node-set.md)
- [4. Execution model and compilation](reference/04-execution-model-and-compilation.md)
- [5. Bytecode specification (WBC 1)](reference/05-bytecode-specification-wbc-1.md)
- [6. Runtime and embedding API (C)](reference/06-runtime-and-embedding-api-c.md)
- [7. Toolchain](reference/07-toolchain.md)
- [8. Versioning and compatibility](reference/08-versioning-and-compatibility.md)
- [9. Open questions and next steps](reference/09-open-questions-and-next-steps.md)
- [Appendix A. Changes in Draft 0.2](reference/appendix-a.md)
- [Appendix B. Changes in Draft 0.3](reference/appendix-b.md)
- [Appendix C. Changes in Draft 0.4](reference/appendix-c.md)
- [Appendix D. Changes in Draft 0.5](reference/appendix-d.md)
- [Appendix E. Changes in Draft 0.6](reference/appendix-e.md)
- [Appendix F. Changes in Draft 0.7](reference/appendix-f.md)
- [Appendix G. Changes in Draft 0.8](reference/appendix-g.md)
- [Appendix H. Changes in Draft 0.9](reference/appendix-h.md)
- [Appendix I. Changes in Draft 0.10](reference/appendix-i.md)
- [Appendix J. Changes in Draft 0.11](reference/appendix-j.md)
- [Appendix K. Changes in Draft 0.12](reference/appendix-k.md)
- [Appendix L. Changes in Draft 0.13](reference/appendix-l.md)
