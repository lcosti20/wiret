# Making the Asymmetry Work: Text Syntax for a Blueprint-Style VPL

Blueprints' wiring rules are asymmetric, and that asymmetry maps well onto text.

|  | Many-to-one | One-to-many |
| --- | --- | --- |
| **Data** | No: an input has exactly one source | Yes: an output can feed many inputs |
| **Exec** | Yes: many exec outputs can merge into one input | No: an output has exactly one target |

So each layer is a tree in one direction and only "breaks" in the other:

- **Data** is a tree when read backward from inputs, so nested expressions work. The only problem is a shared output (fan-out).
- **Exec** is a chain when read forward, so sequential statements work. The only problem is a merge (fan-in).

That reduces the problem to two cases, and each can get its own mechanism.

## Data fan-out: one output, many inputs

Example: `Health - Damage` feeds both `SetHealth` and a `Branch`.

### A. Implicit-parameter block (preferred)

Write the source once, then open a block where it's available under a fixed implicit name (like Kotlin's `it`). No developer-invented names, and the source reads first, matching how the wire leaves the node.

```
(Health - Damage) => {
  SetHealth(it)
  Branch(it <= 0) {
    true:  Destroy(self)
    false: Print("Alive")
  }
}
```

Nested blocks shadow `it`. If you need the outer value, use `it^` (or `it^2`), or fall back to option D. The block scope also tells the reader exactly where the shared value is used.

### B. Structural deduplication

If a pure, deterministic node appears twice with identical inputs, the compiler merges them:

```
SetHealth(Health - Damage)
Branch((Health - Damage) <= 0) { ... }
```

This is the most natural to write, but it has caveats:

- Round-tripping is lossy: two visually separate `Add` nodes with the same inputs collapse into one.
- It's only safe for deterministic nodes. `RandomFloat()` twice must stay two nodes, so you need an explicit `fresh RandomFloat()` or a node-level `deterministic` flag.
- It doesn't help for impure data nodes (anything with a side effect that returns a value).

### C. Positional back-reference

Pure expressions can be statements, and `^` means the previous one:

```
Health - Damage
SetHealth(^)
Branch(^^ <= 0) { ... }
```

Compact but fragile: inserting a line silently rewires things. Best avoided.

### D. Anonymous tags (fallback only)

```
(Health - Damage) as #1
...
Branch(#1 <= 0)
```

This is a name in disguise, but it's rarely needed, only when A's nesting gets awkward. It maps directly to a Reroute node.

### Multi-output nodes

Pins already have intrinsic names, so use them instead of inventing variables. Outputs of the block's node are addressed by pin name:

```
LineTrace(start, end) => {
  Branch(hit) {
    true: SpawnDecal(at = location, facing = normal)
  }
}
```

Here `hit`, `location`, and `normal` come from the node definition, not the developer. When two multi-output nodes are nested, qualify with the node name: `LineTrace.location`.

## Exec fan-in: many outputs, one input

### A. Structured continuation (covers most real cases)

Anything after a branching block is the merge target of every arm that falls through. This is the same rule as dedent in Python or code after `}` in C.

```
Branch(Health <= 0) {
  true:  Print("Dead")
  false: Print("Alive")
}
Delay(1.0)          # both arms merge here
Print("Done")
```

Arms that end in a terminating node (`Destroy`, `Return`, `break`, `continue`) simply don't merge. Fan-in costs nothing in syntax, and the graph compiler makes the two arms' `then` pins both wire into `Delay.exec`.

### B. Loops as first-class blocks

Back edges are fan-in too (the loop head gets entry plus repeat edges):

```
loop {
  Branch(Done) { true: break }
  DoWork()
  Delay(0.5)
}
```

`break` and `continue` target the nearest loop, with no labels needed. The back edge is implied by the block.

### C. Anonymous join marker (for irreducible cases)

Occasionally a graph jumps into the middle of another path and can't be expressed as nested blocks. Mark the target with a `join` and point at it with a numbered reference:

```
Branch(A) {
  true:  Foo() ; goto join#1
  false: Bar()
}
Baz()
join#1: Qux()
```

Like data tag D, this is a last resort, and the formatter can detect when it's needed and emit it automatically. Alternatively the tool could refuse to emit it and duplicate the code instead, but that changes graph identity.

## Putting it together

```
Event BeginPlay
loop {
  (Health - Damage) => {
    SetHealth(it)
    Branch(it <= 0) {
      true:  Destroy(self) ; break
      false: Print("Alive")
    }
  }
  Delay(1.0)                 # exec merge and loop back edge are implicit
}
```

There are no node names, and only the rare irreducible case needs explicit tags.

## Rules to nail down

- **Evaluation order of pure nodes.** In Blueprints, a pure node is evaluated when its consumer executes, and re-evaluated per consumer. A shared `=>` block should pin down whether it computes once at block entry (usually what people expect) or per use. Making it "once at entry" and requiring an explicit `inline` modifier for re-evaluation is the cleaner contract.
- **Impure data nodes** (those with exec pins whose outputs are used more than once) should always be written as a statement with a block, never deduplicated.
- **Round-trip stability.** Since nodes have no names, the editor needs a way to keep positions across edits. The usual answer is a sidecar layout file keyed by structural path (e.g. `loop[0]/Branch/true[1]`) or auto-generated hidden IDs.
- **Formatter as canonicalizer.** If the text has several equivalent forms (B vs A, `it` vs tag), the formatter should always normalize to one, so diffs stay clean.

## Recommendation

Use **A (`=>` block with implicit `it`)** for data fan-out, **structured continuation** for exec fan-in, and reserve **tags and joins** as machine-generated escape hatches. That keeps the 95% case readable as ordinary code and confines the "graph-ness" to the few places where it actually exists.

Next steps could include an EBNF grammar for this syntax, or a worked example of how a tricky graph (say, a `ForEach` with early break plus shared outputs) would be lowered to and from nodes.
