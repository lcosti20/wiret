## Appendix B. Changes in Draft 0.3

Draft 0.3 takes the strongest parts of an independently developed design that comes with a working Python reference implementation (parser, formatter, checker, compiler, verifier, VM and a fuzz test). The table lists what was adopted and why.

| Change | Section | Reason |
| --- | --- | --- |
| Layout moves into a per-graph `layout` block (`place` and `box` lines); node lines carry no positions; auto-placement; personal view state kept out of the file | 2.3, 2.4, 2.5, 7.5 | Fixes a real flaw in 0.2, where `@ed` shared a line with a node's wiring so a move and a rewire of the same node conflicted. |
| `state` slots for macros and graphs; path-style node ids after expansion; synthetic exec-pin stub ids | 2.3, 4.4, 4.8, 5.4 | `DoOnce` and `FlipFlop` had no mechanism in 0.2. Path ids give debug data and diagnostics an address inside macros. |
| Declared and checked latency: `@latent`, `E0201`, function-section flags, a verifier rule | 2.4, 4.4, 4.5, 5.2, 5.5, 6.8 | A non-latent export can no longer suspend, so a host can rely on `wr_call`. This also mirrors Blueprint's restriction on latent nodes. |
| Pin-level debug data (`wr.pins`), `-Og`, and `wr_getpin` | 4.8, 5.4, 6.10 | Lets an editor show values on wires and a host log the inputs of a failing node. |
| Host ABI hardening: `struct_size`, deterministic mode and native flag, `WR_LOAD_BORROW` | 6.3, 6.4, 6.5, 6.6 | Structs can grow without breaking old hosts; replay cannot depend on a hidden clock; one image can serve several VMs. |
| Keyed, node-level merge with per-field rules and conflict markers | 7.1 | Merges on the model rather than on text lines. |
| Structured diagnostics (`check --json`), `E0303`, an editor contract and an LLM prompt contract; `run` and `svg` commands | 4.7, 7.2, 7.5 | Closed loops for editors and agents. |
| Reference-implementation path, section status, metamorphic hash tests | 7.4, 7.6 | The compared design found bugs by running its spec; this one has not yet. |

**Considered and not adopted.** Sigils (`%node`, `@symbol`, `$local`) and multi-line node blocks: they make each node several lines (a 10-node function became about 50 lines), and bare identifiers are already unambiguous by position. Reference-type containers: they contradict the project's decision that arrays copy by value (section 4.9). Compile-time duplication of nodes for `Sequence` with a nesting limit: kept the runtime continuation stack, recorded as an open question (9.1). Raising errors from natives with a longjmp-style API: natives return `wr_fault` instead, which is safe with C++ and with natives that hold resources. An `any` boxing type: typed wildcards and explicit `Convert` nodes are kept. Preserving node order and inserting after the origin node: two people inserting after the same node collide in a line merge, so canonical order stays sorted by id. Dropping catchable faults: kept `Try`, but marked it Provisional (4.6).

### Corrections after porting examples

The Draft 0.3 examples were hand-ported into the compared design's reference compiler and VM. The semantics agreed in most respects, and two flaws in this specification were found and fixed:

- **`@pure` no longer means having no exec pins.** It means no observable effects. The body of a pure function is still an exec graph, so a pure function can branch and recurse. Under the earlier definition a recursive pure function such as `Fib` could not be written, because `Select` evaluates both inputs and the recursion would never end. `Entry` and `Return` now always carry exec wires (sections 2.4, 3.3, 4.3, 4.7).
- **`Emit` is removed.** A `Sequence` whose first output is an `Exit` already runs the caller's chain as a subroutine and then continues, which is all `Emit` did. `ForRange` and the lowering steps are rewritten accordingly (sections 2.6, 3.3, 4.2, 4.8, 5.8).

The port also confirmed that re-evaluating pure nodes behaves as section 4.3 describes, that a non-latent function calling a latent one is rejected with the same code (`E0201`), and that arrays in the compared design alias on assignment, which is the behaviour section 4.9 replaces.
