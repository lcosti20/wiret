# State Management in Visual Graphs

State management in visual graphs is the design of how data is stored, updated, propagated, and observed while a visual program executes. It determines what a node knows, when a value becomes available, how changes travel through wires, and how the graph behaves when execution is sequential, event-driven, or asynchronous.

In a visual programming language, wires are not necessarily all the same kind of connection. A wire might carry a value, trigger an operation, represent a dependency, or transport an event. Understanding state management means defining these distinctions precisely and specifying how they interact.

This topic connects several areas of computer science:

- Programming language semantics: what it means for a graph to execute.
- Dataflow programming: how values move between operations.
- Abstract syntax trees (ASTs): how visual structures represent program structure.
- Reactive programming: how changes propagate through dependent computations.
- Concurrency and asynchronous programming: how overlapping operations, events, and delayed results are coordinated.
- State machines: how programs transition between well-defined states.
- Distributed systems: how updates, ordering, and consistency work when execution spans multiple processes.

The central design question is: What is the execution model of the graph, and what guarantees does that model provide about state?

## 1. What counts as state in a visual graph?

State is any information that influences future computation or describes the current condition of a running program. It is useful to distinguish several categories.

[Examples — QtNodes 3.0 documentation](https://images.openai.com/static-rsc-4/WMzxR9swfcHTsbtrNiB2GLry7FZdSmsuSvCFLBpuvm6MBx1ACuxMr9Iu_ht58XEd6qbIIw5sWcCUiKPYFn2lSnLi9tFFvlXkEM70Be6ytuvCwZze0y8F5mKlRXznrfudehD8sJMQQWqvCXP_8jxQdkjwmPNBoav7rw7oXYyBQLo?purpose=inline)

1\. Data values

Values passed between nodes, such as numbers, strings, vectors, objects, and Boolean flags. These might be calculated on demand or stored temporarily.

Example: a node calculates `health - damage` and sends the result to another node.

[Game Development Series Part 2: Choosing a Game Engine - Wasil Zafar](https://images.openai.com/static-rsc-4/2RfEGENTtdsF40r9A8b60QPg-QmKftBoK4xuIi3CRrkzJfwu4mPbgdqqSbEQFWXD1o4FdsLBbZzjGh8weXfNrgEka2L0KIK6a_1JTcxpPdXBH_2EvcOJ2rj4bdnBnZ_sqAEydGtj8f1e2bCT_iC6pRdlPquLMq6zpbrZsh0MU9c?purpose=inline)

2\. Execution state

Information about which operations are ready, running, completed, suspended, or failed.

Example: an execution wire triggers a node that waits for an animation to finish before continuing.

[The Three 'R's of Distributed Event Processing](https://images.openai.com/static-rsc-4/hcM66Nz5_eFzJAp5wZsV0dgwMYE_W81vkwuNmqMblYYwK8CgPlPxMZQMxd5hONpMsaZ4JA4DQa2d8uNARrEN2Cq-tjyuJyKE8m-BOmltKqManZlsrbaqaH0DazFhBkXfmXh97fHtI4p0FabSoIWAmuMOkqf92IxhPpWhM7NcNog?purpose=inline)

3\. Persistent program state

Values retained across execution steps, events, or function calls.

Example: a counter retains its value between button clicks, or an object's position persists between frames.

[Signals vs Query-Based Compilers](https://images.openai.com/static-rsc-4/y1fYNS6J4-H72XUrExENa2X6hn05tFFhf58zKgaFZEBBUP0Aw2ZDeu82xm_2VyJScWgBfHx0--12KNs219lj6tHjLBtIwltcQwNUiG1aNqwBocG1lF4p7O17Tk_Tw_5pw7aDmJaskqhlgOwrofu0lD1pftXy1-joL4w25MbBZM0?purpose=inline)

4\. Dependency and invalidation state

Information about which outputs depend on which inputs, which calculations are stale, and what must be recomputed after a change.

Example: changing a slider invalidates a downstream calculation and refreshes its displayed result.

These categories overlap, but they should not automatically be treated as one mechanism. A graph editor may use data dependencies to calculate values, execution dependencies to schedule operations, and persistent variables to preserve state over time.

## 2. Data wires versus execution wires

One of the most important distinctions in visual programming is between dataflow and control flow.

[Vector+vector changed name - Blueprint - Epic Developer Community Forums](https://images.openai.com/static-rsc-4/mOi_1KSRD0L19Cc-Yf25NcLhyfdGxqA1V8V5mHkyL776FS4-uJF4gTI2gxc2VJJqV9wsTJ-PohVoluyxd_6IRTqNe21ogDyNcM1DhaOrpBsZrFeOuG36cszu6tNEXlL1TLTvM4HzMUa6XR-YMVB_Zx0k98ddXvj_Z6_yl3T5xWQ?purpose=inline)

Dataflow

A wire expresses a relationship between values. The receiving node obtains an input value from a producer.

- What value is supplied?
- When is it calculated?
- Is it cached or recomputed?

[Flow Control and Functions — tharle VFX](https://images.openai.com/static-rsc-4/O4v8ljByZPRyLIfLrlUV8-qzyRrJoOOtSgH8ylMq86euHRCaAOPk2tHMgK15ZLa1QHQo1nBiAU_tFh-UwaVlJhu5QyKi4hSo4J9SqIbXOJmx9-4xkOGOrSLX7ulP3E6EAQpjN-xFuRvPieVYf-fzPXZgscuzOAlwLrof1En0Li0?purpose=inline)

Control flow

A wire expresses which operation should execute next, or which execution path should be activated.

- Which operation runs?
- In what order?
- What happens when execution pauses or branches?

Consider a graph that subtracts damage from a character's health.

- A data wire carries the current health value.
- Another data wire carries the damage amount.
- An arithmetic node computes the difference.
- An execution wire may trigger the operation that stores the new health.
- An event may subsequently notify other nodes that health changed.

These relationships have different semantics. A value being available does not necessarily mean a node should execute, and triggering a node does not necessarily mean all its input values have just changed.

### Three common execution models

| Model               | How computation proceeds                                            | Typical use                                           |
| ------------------- | ------------------------------------------------------------------- | ----------------------------------------------------- |
| Pull-based          | A consumer requests a value from its dependencies.                  | Expressions, lazy evaluation, spreadsheet-like graphs |
| Push-based          | A producer propagates new values to dependent nodes.                | Reactive interfaces, live previews, event propagation |
| Scheduled execution | A runtime schedules nodes or tasks according to control-flow rules. | Visual scripting, workflow graphs, game logic         |

A language can combine all three. For example, an event may schedule a node, that node may pull its inputs, and its output may then push an update to a reactive display.

## 3. State, values, and execution are different things

A major source of complexity is that a graph can have a stable structure while its runtime state changes continuously.

Consider a graph with three nodes:

Variable

## 100

Current health

Subtract

## 25

Damage

Result

## 75

New health

Illustrative example: the graph's topology is unchanged, but its values and execution status can vary.

A runtime should distinguish at least these concepts:

- Graph definition: the nodes, edges, ports, types, and configuration.
- Activation: a particular invocation of a node or subgraph.
- Value: the data produced or consumed by an activation.
- Store: the state retained between activations.
- Scheduler state: which operations are ready, suspended, queued, or complete.
- Execution history: events and transitions that have already occurred.

This distinction becomes especially important when the same node is activated more than once. If a node starts two asynchronous operations, its first invocation must not accidentally consume the second invocation's inputs or overwrite the second invocation's result.

## 4. A taxonomy of state-management models

Different visual programming languages make different choices about where state lives and when it changes.

[Formelverweise zu Vorgänger und Nachfolger in Excel anzeigen | Controlling | Haufe](https://images.openai.com/static-rsc-4/TgNuUAuDXWbU00INKTjC320wP4_vke_CglriophmZKy8_EyUETLAT-DPeXLlnv-Iki_I0B1n88Ak8fm1OVqLp4vUGtfPAzvGyh2wU_lNjpf4nM2sxuzFmjozShIZcZmPd0YH4uzX3ezVQz9OvghP7mDPHSlG_hi1bVBvQSNgtpU?purpose=inline)

A. Demand-driven evaluation

A node computes its value when a consumer requests it. Results may be cached until an input changes.

Common in expression graphs, formula editors, and shader-style computation.

Key question: when is a cached value invalidated?

[Frontiers | Bonsai: an event-based framework for processing and controlling data streams](https://images.openai.com/static-rsc-4/IWMdKjaASpLH86-0VUeK6GTwkKX2pnXEZtXFs8VJVbS43TPxvtVBnM55uXqRPlXsKz0-0FAqYsSck9JoVfz0DSF8HiFzc7wezfxLTbd28c2jPNg-FtceXCY5oITWon7W6nB0pEBLXxGNZb8aeb5Q7rrw3wH9FGx9SWvs8YQsT88?purpose=inline)

B. Reactive state propagation

A change in a source propagates to dependent nodes, which update their outputs or trigger downstream work.

Common in reactive interfaces and interactive data visualization. Reactive Vega, for example, treats data, interaction events, and rendered elements as parts of a streaming dataflow system.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://idl.cs.washington.edu\&sz=32)

UW Interactive Data Lab+1



Key question: how are dependencies, batching, and recomputation managed?

[Using the Flow Control macros in UE4 | by Alexandre Lombard | Medium](https://images.openai.com/static-rsc-4/qrxhh0Wg_7hy8pMrRk4SzO720TdTKKsnWfkHPgZplBEsuoWQeGoN-NbLucR0PeKFeWHoCYfTpDFBsYlLEJgQAOYms4O7VfVDEfKVMq35WaTKYVjZsvyHsxTcq_P5VPFCDi3xk7rps7MlB3kFPhIYjWv9JuL3Ibp1RmLBrEox4dw?purpose=inline)

C. Imperative, event-driven execution

Events trigger explicit operations that read and modify state. Execution order is determined by control-flow rules.

Common in game logic, automation, and interactive applications.

Key question: which state changes are allowed, and in what order?

[Actor Model in Nutshell. Actor Model is a conceptual concurrent… | by Krishna Kumar Tiwari | Medium](https://images.openai.com/static-rsc-4/k-qsejBMMnoWwvPrE23HQu9fX8xIrKcNo0l6NUDC2Ki1G4oPQGQ4MZZql9ccG45fKmdDiG-XvBm4YRhj2m78rIO5B5CziGcvWe5HinzyF-kYXL7zsb_DBdgtpZ7jmH4XQlq7swu7WvlYqMOsTuMhfXxxaQqc0VKy_L4vjnaoinw?purpose=inline)

D. Message-driven asynchronous execution

Nodes exchange messages or events, often through queues. Different nodes may process messages concurrently, so receiving the same sequence does not guarantee that independent branches finish in the same order.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://github.com\&sz=32)

GitHub+1



Key question: how are ordering, backpressure, failures, and concurrent updates handled?

These are not mutually exclusive. A sophisticated graph language may use reactive dataflow for ordinary values, imperative control flow for side effects, and message-driven execution for asynchronous operations.

## 5. How data moves through a graph over time

The most useful way to reason about state management is to follow a value through its entire lifecycle.

Suppose a visual program receives a button-click event, starts a network request, and displays the returned data.

1\. Event received

Click event, activation ID 42

2\. Request activated

Execution state: running

3\. Request suspended

Waiting for an external result

4\. Result received

Activation 42 resumes with its result

5\. State committed

Data stored and display updated

Conceptual lifecycle. A real runtime may merge stages, use callbacks, or schedule each stage separately.

Each stage raises a different question:

1. Input: Is the event a one-time occurrence or a persistent value?
2. Activation: Which invocation owns this operation's local data?
3. Suspension: Which resources and values must remain available while waiting?
4. Resumption: How does the runtime associate the returned result with the correct invocation?
5. Commit: When do downstream nodes observe the new state?

A well-designed language defines these rules rather than leaving them to accidental runtime behavior.

### State transitions

The lifecycle can be represented as a state machine:

Ready

Running

Suspended

Completed / Failed

Illustrative execution states, not a complete transition diagram.

The transitions might be:

- `Ready → Running`: the scheduler activates the node.
- `Running → Suspended`: the node awaits an external result.
- `Suspended → Running`: the awaited operation resumes.
- `Running → Completed`: the node produces its final output.
- `Running → Failed`: an unhandled error occurs.
- `Suspended → Cancelled`: the owning operation is abandoned.

Cancellation, failure, and completion should be distinguishable. Otherwise, downstream nodes may wait forever, interpret a failure as a missing value, or continue using stale results.

## 6. Sequential versus asynchronous execution

This is the heart of your original research note.

### Sequential execution

In a sequential model, operations follow a defined order:

```
Read health
    ↓
Subtract damage
    ↓
Store new health
    ↓
Check whether health <= 0
```

The runtime guarantees that each operation happens after the preceding operation completes. If state changes between steps, those changes have a predictable position in the execution sequence.

However, sequential execution does not necessarily mean that the whole program runs on one thread. It describes ordering guarantees, not necessarily hardware scheduling.

### Asynchronous execution

Now consider a graph that starts two requests:

```
                 ┌── Fetch profile ───┐
Button clicked ──┤                    ├── Combine results
                 └── Fetch inventory ─┘
```

Both requests can be in flight at the same time. The profile might finish before the inventory, or vice versa.

The runtime must decide what the combine node means:

- Wait for both: execute only after both results are available.
- Use whichever arrives: emit a result whenever either input changes, if the operation permits it.
- Latest-value semantics: combine the newest known value from each input.
- Matching-activation semantics: combine results belonging to the same button click.
- Stream semantics: combine items according to a defined ordering or time window.

These alternatives are not interchangeable.

### The stale-result problem

Suppose a user searches for `cat`, then quickly searches for `caterpillar`. The second request finishes first, but the first request finishes later.

Without an explicit policy, the older result might overwrite the newer one.

A robust runtime can use a monotonically increasing request generation:

```
Search "cat"          generation 1
Search "caterpillar"  generation 2

Result generation 2 → accept
Result generation 1 → discard as stale
```

Other valid policies include cancelling the older request or displaying all results with their query identities. The important thing is to make the policy explicit.

Asynchronous dataflow research provides useful concepts here: message ordering, timestamps, progress tracking, and the distinction between data arrival and computation completion. Timely Dataflow, for example, uses timestamps and progress information to reason about which inputs may still arrive.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://timelydataflow.github.io\&sz=32)

timelydataflow\.github.io+1



## 7. Persistent state, transient values, and activation-local state

A language should specify the lifetime and ownership of its values.

| State category      | Lifetime                                                  | Example                         |
| ------------------- | --------------------------------------------------------- | ------------------------------- |
| Input value         | Until replaced or invalidated                             | Current slider value            |
| Activation-local    | One invocation                                            | Damage amount for one collision |
| Persistent variable | Across invocations                                        | Player health                   |
| Cached result       | Until invalidated or evicted                              | Previously computed path        |
| Event or message    | Until consumed, processed, or expired according to policy | Button click                    |
| Stream state        | Across a sequence of messages                             | Running average                 |
| Runtime state       | For as long as the relevant task exists                   | Pending asynchronous request    |

This matters especially when a graph is reentrant—that is, when a new activation can begin before an earlier activation has finished.

For example, a node that stores a single mutable `currentRequest` variable may work for one request at a time but fail when two requests overlap. An activation-local context avoids that collision:

```
Activation 41:
    query = "cat"
    request = pending

Activation 42:
    query = "caterpillar"
    request = pending
```

Each invocation owns its own local inputs and pending work, while shared state is updated according to a separate, explicit policy.

A good rule is: values should have a defined owner, lifetime, and update policy.

## 8. The relationship between ASTs and runtime state

Your note links to the [Abstract syntax tree](https://en.wikipedia.org/wiki/Abstract_syntax_tree?utm_source=chatgpt.com). ASTs are relevant, but they solve a different problem.

An AST represents the syntactic structure of a program. Runtime state describes what happens when that program executes.

For example, the expression:

```
health = health - damage
```

might be represented by an AST containing an assignment node, a subtraction node, and references to two variables. Evaluating it requires a runtime environment that supplies the current values of `health` and `damage`.

A visual graph can have a similar separation:

### Graph definition

Nodes, ports, connections, types, constants, and execution rules.

Interpret, compile, or schedule

### Runtime state

Variable stores, activation contexts, pending tasks, queued events, cached values, and execution status.

There is one important complication: a visual graph is not necessarily a tree. A node can have several incoming and outgoing connections, and graphs may contain cycles. An AST is typically tree-shaped, whereas a visual graph is often more naturally represented by a directed graph or an intermediate representation (IR).

For a graph language, it is therefore useful to distinguish:

- Visual graph: the editable structure presented to the programmer.
- AST or graph IR: the formal representation used for validation, analysis, or compilation.
- Runtime graph: the executable representation, possibly optimized or expanded from the original graph.
- Runtime state: the changing values and execution contexts associated with that representation.

This separation allows a visual editor to rearrange nodes without changing program behavior, and allows a compiler to optimize the graph without changing its defined semantics.

## 9. State management and cycles

Cycles make state management particularly interesting.

Consider a graph that calculates the next position of an object from its current position and velocity:

Current position

## \\(x_t\\)

Update position

\\(x\_{t+1}=x_t+v\Delta t\\)

Next position

## \\(x\_{t+1}\\)

In a stateful simulation, the next position becomes the current position for a later update.

A cycle can have several different meanings:

1. Feedback over time: an output is stored and reused in a later update.
2. Iterative computation: the graph repeats operations until a condition is satisfied.
3. Reactive feedback: a change triggers further changes, potentially creating an infinite update loop.
4. Recursive evaluation: a computation refers back to itself and requires a defined evaluation strategy.

These cases need different runtime semantics.

A particularly useful design concept is a delay node or state boundary. Instead of allowing an instantaneous feedback cycle, a delay node explicitly reads a value from a previous update and writes the new value for a future update.

For example:

```
Previous value ──┐
                 ├── Add ──> Next value
Input ───────────┘                │
    ▲                             │
    └──── State / Delay ◄─────────┘
```

The delay makes the temporal boundary visible. This is especially valuable in simulations, signal processing, and reactive graphs.

Not every cycle should require a delay. Some systems support fixed-point evaluation or specialized cyclic dataflow models. The language must specify which forms of cycles are legal and how they terminate or converge.

## 10. State consistency and update transactions

When several nodes react to the same event, the runtime needs rules for consistency.

Suppose an event updates both a player's health and a health-bar display. Should downstream nodes observe the old health, the new health, or a partially updated combination?

There are several possible models.

| Model                 | Behavior                                                    | Trade-off                                                            |
| --------------------- | ----------------------------------------------------------- | -------------------------------------------------------------------- |
| Immediate mutation    | Each write becomes visible immediately.                     | Simple, but intermediate states can leak into other computations.    |
| Transactional update  | Related changes are committed together.                     | More predictable, but requires transaction boundaries.               |
| Snapshot evaluation   | Nodes read a consistent snapshot of state.                  | Good for deterministic evaluation, but may delay visibility.         |
| Event-sourced updates | State is derived by applying an ordered sequence of events. | Supports replay and auditing, but requires event history management. |

A language might use immediate mutation for local imperative operations while using transactional updates for reactive recomputation.

For reactive graphs, a common approach is to batch changes and evaluate their downstream consequences in a defined update cycle. Reactive Vega illustrates why dependency tracking and incremental propagation matter: its architecture can update affected data and visualization elements without recomputing the entire system.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://idl.cs.washington.edu\&sz=32)

UW Interactive Data Lab+1



This leads to several essential questions:

- Can downstream nodes observe intermediate states?
- If two nodes write the same variable, which write wins?
- Are updates atomic?
- Are duplicate events processed more than once?
- What happens if a node fails after some side effects have already occurred?
- Can an update be rolled back?

These are semantic questions, not merely implementation details.

## 11. A proposed state-management architecture

If you are researching or designing a visual programming language, I would separate state management into five cooperating subsystems.

### 1. State store

Owns persistent variables, object state, and other long-lived values.

### 2. Activation manager

Creates and tracks individual node invocations, their inputs, local values, and continuations.

### 3. Scheduler

Determines which nodes or tasks can execute, handles dependencies, and manages asynchronous suspension and resumption.

### 4. Propagation engine

Delivers values, events, and messages; tracks dependencies; and determines which downstream computations require updates.

### 5. Observability layer

Exposes execution traces, current values, pending work, state changes, and errors to the visual debugger.

These subsystems need not be implemented as separate modules, but keeping their responsibilities conceptually distinct makes the language easier to reason about.

For example, the scheduler decides when a node runs, the activation manager determines which invocation is running, and the state store determines which persistent values it can access.

### Core runtime data structures

A conceptual implementation might include structures like these:

```
Graph
    nodes
    edges
    node_definitions
    dependency_index

Runtime
    persistent_store
    activation_table
    ready_queue
    pending_tasks
    event_queues
    dependency_versions

Activation
    activation_id
    node_id
    input_values
    local_state
    status
    continuation
    error

Value
    type
    payload
    version
    provenance
```

This is illustrative rather than a required architecture.

A version number can help detect stale computations. Provenance can identify which input or activation produced a value. An activation ID can prevent two invocations of the same node from sharing the wrong temporary data.

For concurrent runtimes, additional mechanisms may be needed for synchronization, cancellation, backpressure, and ordering.

## 12. Debugging and inspecting state visually

A visual programming language should ideally make runtime state visible rather than requiring users to infer it from the wiring.

Useful debugging features include:

- Live values: display the latest value at each data output.
- Execution highlighting: show which node is currently running or has just executed.
- Activation tracking: distinguish concurrent invocations of the same node.
- State inspection: examine persistent variables and their owners.
- Event tracing: inspect the order in which events and messages were received and processed.
- Pending-operation indicators: reveal nodes waiting on asynchronous work.
- Dependency visualization: distinguish a stale value from a value that has not yet been computed.
- Time travel: replay recorded events or restore a previous state snapshot, where supported.

One subtle but important design decision is whether the editor shows the latest value, the value associated with the current activation, or the value from a specific point in the execution history. These may all differ.

For example, a node might currently display `75`, while an older asynchronous activation still holds `100` as its input. A debugger that shows only one undifferentiated value can make this situation very difficult to understand.

## 13. Research questions and design checklist

The following questions can help turn your research note into a concrete specification.

## Specification checklist

0 / 10

State ownership

Where does each value live: on a node, in an activation, in a shared store, or in an external resource?

Value availability

Does a node run when its inputs exist, when they change, or only when an execution event triggers it?

Execution order

Which orderings are guaranteed, and which independent operations may run concurrently?

Asynchronous behavior

How are suspension, resumption, cancellation, failure, and stale results handled?

Update consistency

Are changes immediately visible, batched, transactional, or evaluated against snapshots?

Cycles and feedback

Are cycles forbidden, iterative, recursive, or mediated by explicit state boundaries?

Concurrency

How are races, simultaneous writes, message ordering, and repeated activations resolved?

Incremental evaluation

How does the runtime invalidate caches and recompute only affected nodes?

Determinism

Can the same initial state and input events produce different observable outcomes?

Debugging

Can a user inspect values, activations, state transitions, and execution history?

## 14. Further reading

These resources offer complementary perspectives on the problem.

[Dataflow programming](https://en.wikipedia.org/wiki/Dataflow_programming?utm_source=chatgpt.com)

A broad introduction to graphs of computations, input availability, parallel execution, and state in dataflow systems.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://en.wikipedia.org\&sz=32)

Wikipedia



[Dataflow Process Networks — Edward A. Lee](https://ptolemy.berkeley.edu/publications/papers/94/processNets/?utm_source=chatgpt.com)

A foundational treatment of concurrent processes, FIFO communication channels, actor firings, and formal execution models.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://ptolemy.berkeley.edu\&sz=32)

Ptolemy Project



[Timely Dataflow: Core Concepts](https://timelydataflow.github.io/timely-dataflow/chapter_1/chapter_1.html?utm_source=chatgpt.com)

Explains timestamps, progress tracking, and reasoning about the order and completeness of asynchronous computation.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://timelydataflow.github.io\&sz=32)

timelydataflow\.github.io



[Reactive Vega — A Streaming Dataflow Architecture for Declarative Interactive Visualization](https://vis.csail.mit.edu/pubs/reactive-vega.pdf?utm_source=chatgpt.com)

A practical research example of managing interaction events, data dependencies, incremental updates, and rendering within a reactive graph.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://idl.cs.washington.edu\&sz=32)

UW Interactive Data Lab+1



[Semantics of multiway dataflow constraint systems](https://doi.org/10.1016/j.jlamp.2020.100634?utm_source=chatgpt.com)

Explores formal semantics for selecting operations based on global state and update history, especially for interactive user interfaces.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://www.sciencedirect.com\&sz=32)

ScienceDirect



## Conclusion

The key to state management in visual graphs is to define the relationship between values, time, and execution.

A wire alone does not tell you whether a value is persistent, whether an operation executes immediately, whether an update is atomic, or whether an asynchronous result still belongs to the current computation. Those properties belong to the language's execution semantics.

For a research project, I would make the next step a formal model of the runtime: define the graph state, activation state, transition rules, and observable effects. Once those are explicit, questions about asynchronous execution, reactive propagation, cycles, debugging, and optimization become much easier to investigate systematically.
