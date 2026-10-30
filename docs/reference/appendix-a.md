## Appendix A. Changes in Draft 0.2

Three independent proposals were reviewed against Draft 0.1. This table records what changed and why.

| Change | Section | Source |
| --- | --- | --- |
| `array`, `set`, `map` become value types with copy-on-write; mutators return the container; `ref.share`; place-based mutation nodes; structural equality | 3.1, 3.3, 4.9, 5.6, 6.7 | Decision by the project owner: Blueprints copy arrays by value. Replaces 0.1's aliasing arrays. |
| Machine-readable node registry | 3.5 | Proposal 1 (operation registry), without its per-node pin lists. |
| Merge procedure and editing protocol with a document-hash precondition | 7.1, 7.2 | Proposal 1 (merge and AI editing sections). |
| Cross-module linking, project manifest and lockfile | 7.3 | A gap in 0.1; manifest and lock idea from Proposal 1. |
| `@id` on parameters, results, fields, enum members and locals | 2.4 | Review of rename handling. |
| Capabilities, `wr.caps`, required-feature bits in the header | 2.4, 5.2, 5.4, 6.5 | Proposal 1. |
| `wr_interrupt`, `wr_get_stats`, `.wdbg` sidecar | 5.4, 6.10 | Proposal 1. |
| Conformance levels and shared test suite | 7.4 | Proposal 1. |

**Considered and not adopted.** Pins re-declared on every node and ids on every edge (Proposals 1 and 3): they lengthen every line, create a second source of truth next to the registry, and make sequentially numbered ids collide across Git branches. Creation-order canonical layout (Proposals 1 and 3): every addition lands at the end of the file, so concurrent additions conflict. Register-based bytecode (Proposals 1 and 3): the stack form with typed locals is denser and verifies in one pass. Optional async (Proposals 1 and 3): latent nodes are core to the target. Handle-based host API with retain and release (Proposals 1 and 3): the Lua-style stack avoids a second lifetime system next to the garbage collector. Expressions inside bindings and exec pins on arithmetic nodes (Proposal 2): they break the one-node-per-operation, pure-versus-impure model.
