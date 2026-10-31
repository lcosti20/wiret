# Wiret Language Specification

*Draft 0.5: text syntax, bytecode (WBC) and embedding API for a text-based visual scripting language*

> **Status.** This is a design draft, not an implementation. Nothing here has been run through a real parser, verifier or VM, so treat the grammar and opcode tables as a starting point to test, not a frozen standard. Where I went beyond your reference documents (mainly Blueprint runtime behaviour that the supplied documentation does not spell out), the text says so.

**Draft 0.2.** Revised after comparing three independent proposals (Appendix A lists every change and where it came from). The largest semantic change: `array`, `set` and `map` are now **value types** with copy-on-write, as arrays are in Blueprints (section 4.9). New material: a machine-readable node registry (3.5), a merge and editing protocol for tools and LLMs (7.1, 7.2), cross-module linking and a project manifest (7.3), capabilities, feature bits, interrupts and statistics (5.2, 5.4, 6.5, 6.10), and conformance levels (7.4).

**Draft 0.3.** Incorporates the strongest parts of an independently developed design (Appendix B). Layout moves out of node lines into a per-graph `layout` block, so moving a node and rewiring it no longer touch the same line (2.3, 2.5, 7.1). Macros gain persistent `state` slots (2.3, 4.4). Latency becomes an explicit, compiler- and verifier-checked property of a function (4.4, 4.5, 5.5). Debug data now maps pins to locals, and hosts can probe pin values (5.4, 6.10). The host ABI is hardened (6.3, 6.5, 6.6). Merging is specified as a keyed, node-level operation (7.1). A contract for graph editors and a recommended reference-implementation path are added (7.5, 7.6).

**Draft 0.4.** Responds to a review of 0.3 (Appendix C). The scope is now cut into implementation tiers, and only Tier 0 is a prototype target (1.6). Evaluation is specified step by step, with an explicit evaluation point, fault ordering and join behaviour (4.2, 4.3). `@pure` is split into a precise contract plus a new `@reads` level (2.4, 4.3). Macro `Exit` has transition rules and a worked continuation-stack trace (4.2). Determinism is a defined mode with stated conditions and exclusions rather than a blanket claim (4.10). Persistent `notes` replace silently dropped comments (2.1, 2.3). Identity rules say what a single file can and cannot guarantee, and a project id registry supplies non-reuse (2.3, 2.4, 7.3). Layout-box membership is always explicit (2.3). Git diffs default to flow order while storage stays sorted by id (2.5, 7).

**Draft 0.5.** Records three decisions made while building the editor (Appendix D). `--export-all` builds export every function so the editor can run any of them, while release builds still export only `@export` items (2.4, 5.2). Saved text is never aligned on `=` (or on `at` in the layout block), because aligning breaks the one-line-diff rule (2.5). The binary details the draft left open are fixed: number encodings, branch offsets, and the layouts of `wr.debug` and `wr.pins` (5.1.1, 5.4.1).

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
