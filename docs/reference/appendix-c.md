## Appendix C. Changes in Draft 0.4

Draft 0.4 responds to a review of Draft 0.3. The table lists each finding, what changed, and where.

| Finding | Change | Section |
| --- | --- | --- |
| Scope exceeds current validation | Implementation tiers; only Tier 0 is a prototype target; exact diagnostics and cross-platform determinism are targets until their tier passes; eager copy for containers in Tier 1 | 1.6, 7.4, 9.3 |
| Canonical ordering hurts readability | Git `textconv` through `wiretc view --flow`, a deterministic flow-order definition, `wiretc diff` defaulting to flow order, and a review trial before storage order is frozen | 2.5, 7, 9.1 |
| Annotation preservation is unclear | Persistent `notes` block; `//` comments are never dropped silently (`W0603`, `--convert-comments`); `@doc` narrowed to short tooltip text | 2.1, 2.3, 2.4, 2.5, 7.1, 7.2 |
| `@pure` lacks a precise contract | Effect-free, deterministic and cacheable defined separately; `@pure` and the new `@reads`; `E0304`, `W0320`; faults are results; native flags split and marked trusted; audit option | 2.4, 3.3, 3.5, 4.3, 4.7, 6.3, 6.6 |
| Determinism is overpromised | Deterministic mode with five conditions and explicit exclusions; specified NaN, `Min`/`Max` and `std.math` behaviour (Provisional); logical heap accounting; cross-platform claim marked a target | 1.2, 3.1, 4.5, 4.10, 7.4 |
| Macro continuations need formal semantics | Transition rules, join rules, a step-by-step `ForRange` trace with the stack after each step, and required macro tests | 3.3, 4.2, 7.4 |
| Identity guarantees exceed file-level evidence | Required, present-uniqueness and operational non-reuse separated; `wiret.ids` registry; `E0140`, `W0202`; unkeyed renames documented as delete plus add | 2.3, 2.4, 7.1, 7.3, 7.5 |
| Layout-box membership is ambiguous | Boxes have ids; `members` is required and authoritative; geometry is drawing only; nesting acyclic; at most one parent; set-merge of members; `W0601`, `W0602` | 2.3, 2.5, 7.1 |

**Considered and not adopted.** Making geometric containment authoritative: it makes a drag or resize change meaning, it needs overlap tie-break rules, and it forces collapsed boxes to derive membership. Keeping `//` comments in the canonical form: comments have no place in the model, so every tool would have to re-attach them to a moving target. Dropping id-sorted storage now: the review trial in 9.1 should decide that from evidence.
