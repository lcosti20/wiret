## 7. Toolchain

| Command | Purpose |
| --- | --- |
| `wiretc check file.wiret` | Parse, resolve, type-check and validate; print diagnostics (section 4.7). |
| `wiretc fmt file.wiret` | Rewrite in canonical form. `--check` fails if the file is not canonical (for CI). |
| `wiretc build file.wiret -o out.wbc` | Compile and verify. `-O0` / `-O1`, `--embed-source`, `--no-debug`, `--export-all` (export every function, section 5.2; without it only `@export` items are exported). |
| `wiretc dis out.wbc` | Disassemble, with node ids from `wr.debug`. |
| `wiretc view --flow file.wiret` | Print a reading view in flow order (not canonical). Flow order is deterministic: from each `Entry`, depth-first along exec outputs in pin order; a node reached twice is printed at its first visit; each pure node is printed immediately before its first consumer; nodes unreachable from any entry come last, sorted by id. `--dot` exports Graphviz DOT, using `node:pin` ports and one cluster per layout box. |
| `wiretc hash file.wiret` | Print the semantic and layout hashes. |
| `wiretc diff a.wiret b.wiret` | Node-aware semantic diff, printed in flow order: added, removed and rewired nodes; note and layout-only changes reported separately. `--raw` prints the id-ordered text diff. |
| `wiretc ids --check base..head` | Fail if a commit deleted an element whose id is not in `wiret.ids`, or reused a retired id (`E0140`). |
| `wiretc merge base ours theirs` | Git merge driver. Line-merges, then re-validates (duplicate bindings, dangling ids). |
| `wiretc verify out.wbc` | Run only the verifier. |
| wiretc check --json file.wiret | Structured diagnostics, one JSON record per line (section 4.7). |
| wiretc run file.wiret Func args... | Compile with `--export-all` and run any function, event or method on the reference VM with the standard natives, for tests and quick experiments. |
| wiretc svg file.wiret Func | Render a graph to SVG from the layout block, so a pull request can show the diagram next to the text diff. |

Suggested Git setup:

```
# .gitattributes
*.wiret merge=wiret diff=wiret

# .git/config (or ~/.gitconfig); `wiretc init-git` writes it
[diff "wiret"]
    textconv = wiretc view --flow
[merge "wiret"]
    driver = wiretc merge %O %A %B
```

The `textconv` filter changes only what Git displays: `git diff`, `git log -p` and `git blame` see flow-ordered text, while the stored file and `git apply` are unaffected. Use `git diff --no-textconv` for the raw id-ordered diff.

### 7.1 Merge procedure

`wiretc merge` implements the following, and an editor's built-in merge should behave the same way.

1. **Parse** base, ours and theirs into models. If any side does not parse, fall back to a plain text merge and say so.
2. **Match by key.** Declarations are keyed by `@id`, otherwise by name; nodes by node id within their graph; parameters, fields and enum members by `@id`; notes by note id. An element with no `@id` is matched by name, so renaming it appears as a deletion plus an addition (and, if wires named it, as a conflict); this is the cost of `W0202`, and the reason editors always write ids.
3. **Merge each key.** Added on one side only: keep. Deleted on one side and unchanged on the other: delete. Deleted on one side and modified on the other: **conflict**. Modified on both sides: merge *per field*, where each input binding, each exec output, each type argument and each attribute is one field. A field changed on only one side takes that change, the same change on both sides is no change, and different changes to the same field are a conflict.
4. **Merge layout and notes separately.** `place` lines are keyed by node id and `box` lines by box id, and their properties merge independently; a box's `members` merge as a set, so two people adding different members to one box both succeed. A layout disagreement never blocks a merge: the later commit wins and a notice is printed. Notes are keyed by note id and merge per field like nodes, but they are prose: if both sides changed the same note's text differently, that is a conflict and the merge exits non-zero, rather than letting one side's text win silently. Neither kind of conflict affects compilation. After the merge, `W0601`, `W0602` and `W0604` are re-checked.
5. **Validate** the merged model: duplicate ids, an input bound twice, exec targets or pin references that name a node that no longer exists, and every other diagnostic in section 4.7. Violations are reported as **semantic conflicts** keyed by node and pin, so an editor can show them on the graph.
6. **Write** canonical text. Unresolved conflicts are written as conflict markers around the single node line concerned, one line for each side, and the command exits non-zero, so ordinary tools show them too. The merge never silently drops a node, a wire or an unknown attribute.

### 7.2 Editing protocol for tools and LLMs

A program that edits a graph (an editor, a refactoring tool, an LLM agent) should not rewrite whole files. `wiretc edit` accepts a list of operations as JSON and applies them to the parsed model:

| Operation | Effect |
| --- | --- |
| `create_node` | Add a node with a kind, type arguments, bindings and exec wiring. The id may be supplied. |
| `bind` / `unbind` | Connect or disconnect a data input. |
| `wire_exec` / `unwire_exec` | Connect or disconnect an exec output. |
| `set_attr` / `remove_attr` | Change an attribute on a node or declaration. |
| `place` | Change a node's or box's entry in the layout block (position, label, colour, and for a box its `members`), and only that. |
| `add_note` / `set_note` / `delete_note` | Create, change or remove a `note` (section 2.3). `delete_node` never deletes notes; it reports them as detached (`W0604`). |
| `delete_node` | Remove a node. Refused while other nodes still reference it, unless `cascade` is set, in which case the removed wires are listed in the reply. |
| `rename` | Rename a declaration, parameter, field or local by its `@id` and rewrite every reference. |

Every request carries `if_hash`, the layout hash of the document the caller last read. If the document has changed since, the request is rejected with `E0900` and the caller must re-read. On success the reply contains the new hash, all diagnostics, and the resulting text diff. A rejected or invalid request changes nothing. Together with the registry (section 3.5), this lets an LLM make precise, checked edits without guessing pin names and without ever producing a file that fails to parse.

**Prompt contract for LLM agents.** Give the agent three things: the registry entries it may use (section 3.5) and the declarations it may call, the target graph in canonical text, and the task. It answers with edit operations or a complete function body, with no layout block and no commentary. The harness runs `wiretc check --json`, feeds any diagnostics back, and repeats for a bounded number of rounds. A result that still has errors is never saved. An agent must not invent pin names or node kinds; unknown names are `E0103` and `E0501`, and the loop reports them back to the agent.

### 7.3 Projects, modules and linking

A project is a directory with a `wiret.toml` manifest and a generated `wiret.lock`.

```
[project]
name     = "mygame"
wiret    = "1"
registry = "wiret.core@1.0"
roots    = ["src"]

[dependencies]
physics = { path = "../physics" }

[capabilities]
allow = ["console.write"]
```

- A module name maps to a path under a root: `game.player` is `src/game/player.wiret`. `use game.player` makes its exports visible, and `Call game.player.Heal` calls one.
- A call to another Wiret module compiles to an import whose `module` field is the callee's module name. The loader resolves an import against the declared exports (flag bit 3, section 5.2) of loaded Wiret modules first (checking the signature), then against registered natives.
- Import cycles between modules are rejected at build time.
- `wiret.lock` records the semantic hash of every dependency and the registry version. `wiretc build` fails if a dependency's hash no longer matches, so a build is reproducible.
- `wiret.ids` is the project's **id registry**, committed next to the manifest: one line per retired id (module, graph, kind of element, id). It is append-only and merges by set union, so two branches that retire different ids never conflict. Editors and `wiretc edit` append to it when they delete an element, and `wiretc ids --check` verifies it in CI (section 2.4). It is what turns "ids are never reused" from a convention into something checkable; a single `.wiret` file cannot offer that on its own.
- `[capabilities] allow` lists what the build permits modules to request. It is a build-time check; the host's `wr_grant` calls are the runtime authority.

### 7.4 Conformance

An implementation claims one or more levels:

| Level | Requirements |
| --- | --- |
| Reader | Parses `.wiret`, preserves unknown attributes, and round-trips canonical files byte for byte. |
| Editor | Reader, plus writes canonical form, preserves ids, and computes both hashes. |
| Compiler | Editor, plus produces exactly the diagnostics of section 4.7 for the tiers it claims (section 1.6) and emits verifiable `.wbc` with the lowering of section 4.8. Until Tier 0 has passed, the codes and records are the target, not a frozen contract. |
| Runtime | Verifies before running, enforces limits, implements the instruction semantics of section 5 including value semantics (4.9), and the C API of section 6. |

A shared test suite should cover at least: formatter idempotence (`fmt(fmt(x)) == fmt(x)`); one failing graph for each diagnostic code; golden bytecode for `TakeDamage` and `SumTo`; verifier negative tests and a fuzzer for malformed `.wbc`; arithmetic edge cases (division by zero, `INT_MIN / -1`, saturating truncation, shift masking); a container alias test (copy an array, change the copy, check the original, and check that appending in a loop does not copy on each iteration); determinism in deterministic mode (section 4.10): identical fuel counts, results and faults for a recorded input log on at least two architectures and two compilers, including NaN, `-0`, `Min`/`Max` and `std.math` golden vectors; C API lifetime tests; and semantic-hash stability under layout-only edits.

Add the macro trace tests of section 4.2 (nested loops, `Sequence` inside macros, early exit, unwired `Exit`, faults, joins), the purity tests of section 4.3 (a `@pure` function that reads a field is `E0304`; a `@reads` function sees the state at each consumer's evaluation point; the first fault in evaluation order is the one reported), and identity tests (reusing a retired id is `E0140`; a rename of an element with `@id` merges as a rename; a comment is never dropped without `W0603`; a box with a member outside its rectangle keeps the member). Add two metamorphic tests to the suite: reversing the node order of a graph, and deleting its layout block, must change neither the semantic hash nor a byte of the compiled instruction stream. Add a negative test that a non-latent function containing `suspend` fails verification, and a test that a layout-only edit never changes the semantic hash.

### 7.5 Contract for graph editors

An editor that reads and writes `.wiret` files must:

1. **Preserve ids.** Never regenerate node, box, note, parameter or declaration ids on load or save; generate an `@id` only for an element that has none, and append every id you retire to `wiret.ids`.
2. **Write canonical form** with the shared formatter, so opening and saving an unchanged graph produces a byte-identical file and an empty diff.
3. **Lay out only what has no layout.** Auto-place nodes that lack a `place` line and leave every other position alone.
4. **Preserve unknown data**: unknown attributes, unknown layout properties and unknown custom sections. Preserve notes, show detached ones, and offer to convert `//` comments into notes rather than discarding them. Save box `members` as the user left them, whatever the rectangles say.
5. **Insert conversions explicitly.** When a connection needs a conversion, add a real `Convert` node; never change a wire's type silently.
6. **Never delete wires silently.** If a pin changes type or disappears, keep the wire visible as an error and let the user decide.
7. **Show diagnostics on the graph**, using the `node` and `pin` of each record from `wiretc check --json`.
8. **Keep personal view state out of the file.** Zoom, scroll, selection, open tabs and panel layout go in a separate workspace file (for example `.wiret-workspace`) that is excluded from Git.
9. **Use the debug data** when attached to a runtime: node-level breakpoints from `wr.debug`, and wire values from `wr_getpin`.
10. **Run with `--export-all`.** To run or debug a function, build the module with `--export-all` (section 5.2) so any function can be called by name, and never ship that build.

### 7.6 Reference implementation

This specification should be built alongside a small reference implementation, not after it. The suggested scope is a parser, canonical printer, checker, compiler to WBC, verifier, disassembler and interpreter, written for clarity rather than speed, together with the corpus described in 7.4. Each section of this document should carry a status (specified, implemented, or tested) and the status should be updated as the reference grows. An independently developed design, compared in Appendix B, already has such a reference (about 2,500 lines of Python, with a fuzz test that rejects thousands of corrupted modules); its test corpus and CLI conventions are good starting points to port.
