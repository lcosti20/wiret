## Appendix D. Changes in Draft 0.5

Draft 0.5 brings the specification in line with decisions made while building the editor and its reference tooling. The table lists each change and where it is.

| Change | Detail | Section |
| --- | --- | --- |
| Export modes | The spec exported only `@export` items. The editor must run any function, so `--export-all` builds export every `func`, `event` and method. Export flag bit 3 marks the declared ones, cross-module linking uses only those, and hosts see `WR_EXPORT_DECLARED`. Release builds still export only `@export`. | 2.4, 5.2, 6, 7, 7.5 |
| No `=` alignment | The spec's examples padded node ids so `=` lined up. Saved text never does that: one long id would change every line and break the one-line-diff rule. Canonical rule 10 forbids padding, also for `at` in the layout block; the examples are de-aligned. | 2.5, 2.6 |
| Binary details | Fixed: encoding of each number kind (`u32` fixed-width in the container, LEB128 for instruction immediates, IEEE bit patterns for floats, 8-byte `const` layout), branch offsets (fixed 4-byte `s32`, measured from the end of the instruction, pc-relative to the function's code), and the layouts of `wr.debug`, `wr.pins` and the `.wdbg` sidecar. Layouts of the other custom sections remain open. | 5.1.1, 5.2, 5.4.1, 9.2 |

**Considered and not adopted.** LEB128 branch offsets: they need size relaxation when an offset's length changes, for a few bytes saved per branch. Exporting `@private` items to other modules under `--export-all`: it would let a development build link in ways a release build cannot.
