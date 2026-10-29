# C Foreign Function Interface (FFI)

A Foreign Function Interface (FFI) is a mechanism that allows code written in one programming language to call functions, exchange data, and sometimes manipulate objects implemented in another language. It is a foundational technology for embedding scripting languages in game engines, extending applications with plugins, and connecting high-level languages to native libraries.

For your research into visual programming languages, text-based graph representations, and AI-friendly syntax design, the central question is:

How should a programming language represent calls to external engine APIs so that those calls are safe, understandable, serializable, and easy for both humans and AI systems to generate?

This is more than a syntax problem. A robust FFI needs to define how functions are discovered, how values cross language boundaries, how engine objects are represented, and how foreign calls behave at runtime.

## 1. The basic concept

Suppose a game engine implements a native C++ function:

```
void SetPlayerHealth(Entity* player, float health);
```

A scripting language such as Lua might want to invoke it like this:

```
SetPlayerHealth(player, 75.0)
```

The Lua runtime cannot simply execute the C++ function by interpreting that expression. Some integration layer must connect the Lua call to the native function, convert or validate its arguments, invoke the implementation using the correct calling convention, and translate the result back into a Lua value if necessary.

Scripting or visual program

`SetPlayerHealth(player, 75.0)`

FFI binding / adapter

Resolve function · Validate types · Convert arguments · Check permissions

Native engine API

C / C++ / C# / engine runtime

The diagram represents the logical flow. The implementation can vary considerably: a Lua C API wrapper might use explicit adapters, a dynamic FFI might call native functions through generated call stubs, and a managed runtime might use marshaling and runtime interop.

An FFI is not necessarily a single standardized technology. It is a broad category of mechanisms with different capabilities, performance characteristics, and safety guarantees.

## 2. Why FFI matters for a visual programming language

Imagine a visual programming language in which nodes represent functions, data, and control flow. Its textual representation might contain:

```
node SetPlayerHealth {
    target: Entity
    health: Float
}
```

That declares a node's shape, but not necessarily what executes when the node runs. The language needs a way to associate the declaration with a real engine function.

A complete system must answer several questions:

- Binding: Which native function implements the node?
- Typing: Which foreign types correspond to the language's types?
- Calling: How are arguments, return values, errors, and callbacks handled?
- Lifetime: Who owns the objects and memory passed across the boundary?
- Availability: Which engine version or platform provides the function?
- Security: Which native operations is a script allowed to invoke?
- Serialization: How does a graph retain a stable reference to the binding when saved to a text file?

These requirements suggest treating FFI as a first-class part of the language's execution model, rather than merely allowing arbitrary native function calls inside expressions.

## 3. Three distinct approaches to binding foreign code

The term FFI is often used broadly, but it helps to distinguish three architectures.

[\[View 37+\] Imagem De Lua Cheia Png](https://images.openai.com/static-rsc-4/VeBMssyPjD7Mc5LgO6Qe7mLB5xTfD_MZZYdLbtxJeMJqBTJE30hujzIxqpbuh0FqhhpIMl4SXAEuRm1kYOqO-PYpej-_egYCv2AiWpRfphNwUDqjcgIGJWNJWkqPIkuOGzOVBgnAZd34u6MkdKJ34kooUDLm21g7UbsPlLWpGqM?purpose=inline)

A. Explicit native bindings

The engine or library author writes a C-compatible adapter that registers functions with the scripting runtime. This is the traditional Lua C API approach.

Best for: embedding, controlled APIs, portability, and carefully designed wrappers.

Lua's official manual documents the C API used by the host program to interact with the interpreter.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://www.lua.org\&sz=32)

Lua+1



[ITC](https://images.openai.com/static-rsc-4/Q5TrnnemkAbDjWz-Op-wSMdhBEsnrvdL9VVVZkTiL0kfwYp-IAShumDRpUrLANF40XWob0gXo7bDqvRHtCFwTdg22h63P3oOwC-Y8zuYIykQA_siybiMH6uaZPdywH2bpW-OyV0SsM5U_yxM_zZgeOxG37NS9EROYTKxYl_iCsw?purpose=inline)

B. Dynamic native FFI

The scripting environment dynamically loads native libraries, resolves symbols, and uses type declarations to call functions directly. A separate wrapper for every function may not be necessary.

Best for: C libraries, rapid prototyping, and low-level native integration.

This approach places more responsibility on correct type declarations, ABI compatibility, memory handling, and pointer safety.

[How can I move all actors? - Blueprint - Epic Developer Community Forums](https://images.openai.com/static-rsc-4/dygEKdfTSZyZ05z-GO2E6kWO6wc6UvzfGZhYSxDap4G4G7A3CVYPMCoL0iDPPSN4S5TauS5BjPiHY0CwXDjcBPTBEpi2MJi0pxWzwBAeBuVWW3LVL6QGGFTJ2u7__IGhZCBW0tWvEI2Vx3YyOmRNBPx15np1PYrnWEw3nvBkyYw?purpose=inline)

C. Reflected or generated bindings

The engine exposes a selected API through metadata, reflection, or generated wrapper code. A visual editor can inspect this information to construct typed nodes.

Best for: visual programming, engine APIs, editor tooling, and version-aware node generation.

Unreal Engine's `UFUNCTION` and `BlueprintCallable` mechanism is a practical example of exposing selected C++ functions to Blueprint graphs.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://dev.epicgames.com\&sz=32)

Epic Developer Community+1



These approaches are not mutually exclusive. A game engine could expose most gameplay functions through reflection, provide generated wrappers for frequently used APIs, and reserve dynamic FFI for advanced native integrations.

## 4. Lua: the practical model for a game engine

Lua is especially relevant because it is designed to be embedded in applications. The host application controls the interpreter and chooses which C functions to make available.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://www.lua.org\&sz=32)

Lua+1



### 4.1 Registering a native function

A simplified C binding might look like this:

```
#include <lua.h>
#include <lauxlib.h>

static int l_add(lua_State *L) {
    lua_Integer a = luaL_checkinteger(L, 1);
    lua_Integer b = luaL_checkinteger(L, 2);

    lua_pushinteger(L, a + b);
    return 1;
}

void register_math_api(lua_State *L) {
    lua_register(L, "add", l_add);
}
```

Lua code can then call:

```
local result = add(20, 22)
```

The adapter `l_add` does not have the same signature as an ordinary C function like `int add(int, int)`. Instead, it follows Lua's C-function protocol: it receives a `lua_State`, reads arguments from the Lua stack, pushes results onto that stack, and returns the number of results.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://www.lua.org\&sz=32)

Lua+1



This distinction is important: the binding adapter is itself a function in the runtime's calling convention. It mediates between two different execution models.

### 4.2 Exposing engine objects

A game engine needs to expose more than simple numbers and strings. Consider an entity with a native representation:

```
struct Entity {
    float health;
};
```

A script might write:

```
player:set_health(75.0)
print(player:get_health())
```

The Lua value `player` generally should not be a copy of the native object. Instead, it can be userdata that represents or references the engine-owned entity. Metatables can define operations and behavior for that userdata.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://www.lua.org\&sz=32)

Lua+1



A robust engine binding needs to determine:

- Whether the object is owned by the engine or the script.
- Whether the object remains valid after its entity is destroyed.
- Whether the script may retain the reference across frames.
- Whether the object can be accessed from another thread.
- What happens when a stale or incompatible object is passed to a function.

A raw pointer is not a sufficient object model. It identifies an address, but it does not establish that the object is alive, that the caller has permission to use it, or that the address still represents the same entity.

### 4.3 Why Lua bindings are often hand-written

Hand-written adapters can enforce engine-specific rules, validate arguments, translate errors, and preserve object lifetime guarantees. They can also simplify complicated C++ APIs into a scripting-friendly surface.

The trade-off is maintenance: large engines may have thousands of functions, making manual wrapper authoring expensive. Reflection and code generation can automate much of this work.

## 5. C versus C++ versus C# interop

These three targets have different constraints, even when the source language is the same.

| Target | Typical integration mechanism                       | Main challenge                                                          |
| ------ | --------------------------------------------------- | ----------------------------------------------------------------------- |
| C      | C ABI, exported functions, function pointers        | Correct types, ownership, and calling convention                        |
| C++    | C wrappers, reflection, generated adapters          | Complex types, templates, exceptions, and compiler-specific ABI details |
| C#     | Managed interop, P/Invoke, runtime or engine bridge | Marshaling, managed object lifetime, and runtime boundaries             |

The C ABI is a common interoperability target because C has a relatively stable binary interface across supported platforms. C++ does not have one universally consistent ABI across popular compiler implementations, so exporting a narrow C-compatible interface is often preferable.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://learn.microsoft.com\&sz=32)

Microsoft Learn+1



For C#, .NET supports Platform Invocation Services (P/Invoke) for native calls. Modern .NET also supports source-generated interop through `LibraryImport`, reducing some runtime stub-generation overhead and making interop code more explicit.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://learn.microsoft.com\&sz=32)

Microsoft Learn+1



One important distinction: calling a C function from a C# application and exposing C# engine objects to Lua are different problems. The latter requires a managed-runtime bridge, which may use reflection, generated wrappers, or an engine-specific embedding layer.

## 6. The most important technical design problems

An FFI is easy to demonstrate with a function that adds two integers. It becomes much harder when it has to support a production game engine.

### 6.1 Type mapping and marshaling

The foreign function and the scripting runtime may represent the same logical value differently. Marshaling converts values between these representations.

| Native type   | Possible language-level type |
| ------------- | ---------------------------- |
| `int32_t`     | `Int32`                      |
| `float`       | `Float32`                    |
| `const char*` | `String`                     |
| `Vector3`     | `Vector3` value              |
| `Entity*`     | `Entity` reference           |
| `void` return | No return value              |

The mapping is not always one-to-one. A C string is not the same as an arbitrary Unicode string, and a native pointer is not automatically a safe object reference. Struct layout, alignment, encoding, nullability, and ownership all matter. .NET's native interop guidance emphasizes matching native signatures and choosing appropriate representations.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://learn.microsoft.com\&sz=32)

Microsoft Learn+1



### 6.2 Memory ownership and lifetimes

Every pointer or resource crossing the boundary needs an ownership contract.

Common policies include:

- Borrowed: the caller may use the value temporarily but must not free it.
- Owned: the receiver is responsible for releasing the resource.
- Shared: multiple parties may retain references under defined rules.
- Handle-based: the language receives an opaque identifier instead of a raw pointer.

For game engines, borrowed references and engine-managed handles are often preferable to transferring ownership of engine objects to a garbage-collected script.

### 6.3 Errors and exceptions

Native code may report errors through return codes, error objects, exceptions, or engine-specific mechanisms. The scripting language needs a consistent policy for representing failures.

For example, a binding could return a result:

```
result: Result<Float32, EngineError>
```

Alternatively, the runtime might translate failures into exceptions or graph-level error outputs. The critical requirement is that C++ exceptions must not accidentally cross an incompatible C ABI boundary.

### 6.4 Callbacks and asynchronous execution

Interoperability is bidirectional. A native engine may invoke script functions in response to collisions, timers, input events, or network messages.

The binding system must manage callback lifetimes, garbage collection, thread affinity, reentrancy, and cancellation. An asynchronous operation may need to become a promise, future, coroutine, or explicit event node rather than a normal synchronous function call.

### 6.5 Performance

Each transition may require argument conversion, runtime checks, allocation, and dispatch. In a game loop, thousands of small calls per frame can make these costs significant.

Potential optimizations include generated stubs, cached function references, batched operations, direct calls for compatible signatures, and specialized representations for frequently used engine types.

Importantly, a direct FFI is not automatically faster than a wrapper. Generated or hand-written wrappers can be efficient, and the correct choice depends on the runtime and workload.

## 7. How this connects to visual programming and text-based graph formats

This is arguably the most important part of your research.

A serialized visual program should not need to embed a native function's memory address, compiler-specific symbol, or runtime pointer. Those are implementation details that may change between builds.

Instead, the text format should reference a logical API declaration, and the engine should resolve that declaration to an executable binding.

For example, a hypothetical format might support:

```
module engine.gameplay

external function set_player_health(
    player: Entity,
    health: Float32
) -> Unit {
    binding: "engine.entity.set_health"
    effects: [mutates(player)]
    thread: game
}
```

This is an illustrative proposal, not a standardized FFI syntax. Its important properties are:

- The function has a stable logical name.
- Its parameters and return type are explicit.
- Its native implementation is identified separately.
- Its side effects are documented.
- Its threading requirement is machine-readable.

The compiler or graph editor could use this declaration to construct a typed node, validate connections, display tooltips, and emit the correct runtime call.

### A recommended separation of concerns

Layer 1 — API schema

Names, types, defaults, nullability, ownership, effects, permissions, and documentation.

Layer 2 — Binding implementation

Native symbol, reflection lookup, generated wrapper, marshaling, and runtime dispatch.

Layer 3 — Program representation

Stable node IDs, typed connections, control flow, serialized graph structure, and source locations.

Keeping these layers separate lets the same API schema power several front ends: a visual editor, a text editor, an AI code generator, and runtime introspection tools.

It also avoids a common design mistake: conflating the identity of a function in a program with the way that function happens to be implemented in one engine build.

## 8. API metadata: the bridge between native code and graph nodes

A visual programming editor needs much more information than a function's C signature. It needs enough metadata to decide how the function should appear and behave in a graph.

Consider this native declaration:

```
void SpawnProjectile(
    Entity* owner,
    Vector3 position,
    Vector3 direction,
    float speed
);
```

A graph-oriented schema might describe it as:

```
id: engine.combat.spawn_projectile
version: 1

parameters:
  - name: owner
    type: Entity
    ownership: borrowed
    nullable: false

  - name: position
    type: Vector3

  - name: direction
    type: Vector3

  - name: speed
    type: Float32
    constraints:
      minimum: 0

returns: Unit

effects:
  - world.spawn
thread: game
```

This example uses YAML only to illustrate the metadata concept; a real format could use a compact custom syntax.

The metadata allows the editor to create a node with four inputs and an execution output. It could also generate type checks, document constraints, and warn if the node is used on an inappropriate thread.

This approach has a close real-world analogue in Unreal Engine's reflection system: C++ declarations annotated with `UFUNCTION` metadata can be exposed to Blueprint graphs, while specifiers control how those functions are presented and used.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://dev.epicgames.com\&sz=32)

Epic Developer Community+1



## 9. Design questions for an AI-friendly FFI

If an LLM is generating the text representation of a graph, an FFI schema should minimize the amount of information the model must infer.

| Design choice           | Recommended direction                    | Why it helps                                        |
| ----------------------- | ---------------------------------------- | --------------------------------------------------- |
| Function identification | Stable, fully qualified IDs              | Avoids ambiguous names and accidental substitutions |
| Types                   | Explicit, canonical types                | Reduces invented conversions                        |
| Overloads               | Explicit signatures or distinct IDs      | Prevents choosing the wrong overload                |
| Optional parameters     | Explicit defaults and nullability        | Prevents implicit argument assumptions              |
| Outputs                 | Explicit return and output parameters    | Makes graph connections deterministic               |
| Ownership               | Machine-readable lifetime rules          | Reduces unsafe pointer use                          |
| Effects                 | Declared mutation and execution behavior | Helps validate graph semantics                      |
| Availability            | Version and platform constraints         | Detects unavailable engine APIs                     |
| Permissions             | Explicit capability requirements         | Prevents accidental access to restricted functions  |
| Errors                  | Explicit error and failure semantics     | Makes control flow predictable                      |

A particularly valuable feature would be binding resolution as a compile-time validation step. The model proposes a logical function ID, and the compiler checks whether that ID exists, whether its argument types match, and whether the current engine exposes it.

That is safer than asking the model to reproduce a C++ declaration accurately or guess which overload a textual name refers to.

### An additional opportunity: machine-readable effects

Consider two functions:

```
math.normalize(vector: Vector3) -> Vector3
world.destroy(entity: Entity) -> Unit
```

The first is normally a pure calculation. The second mutates the game world and invalidates an entity's existence.

If the language records these effects explicitly, its graph editor can distinguish pure data nodes from executable nodes. An optimizer can avoid reordering unsafe operations, and an AI generator can reason about execution dependencies more reliably.

Effects could include:

- Pure computation.
- Mutation of an object or global state.
- World creation or destruction.
- File, network, or device access.
- Suspension or asynchronous execution.
- Thread affinity.
- Potential failure.

This is a useful extension of conventional FFI design because it makes behavioral contracts available to both static analysis and graph construction.

## 10. Recommended architecture

For a new visual programming language targeting a game engine, I would favor a schema-first, generated-binding architecture with an explicit C ABI fallback.

1\. Define the API schema

Use a canonical declaration format for function identity, types, defaults, ownership, effects, threading, and errors.

2\. Generate bindings and graph metadata

Produce wrappers, validation code, editor node definitions, documentation, and type information from the same source.

3\. Validate before execution

Check signatures, capabilities, API versions, type conversions, and threading restrictions before dispatching a call.

4\. Keep implementation replaceable

Permit the same logical function to use a hand-written Lua adapter, generated C wrapper, reflection-based dispatcher, or managed C# bridge without changing the serialized graph.

I would also make the following choices:

- Use stable logical IDs rather than raw native symbol names as serialized references.
- Prefer engine-managed handles over arbitrary pointers in the language's public type system.
- Treat native C++ as an implementation detail behind generated wrappers or reflection wherever practical.
- Keep dynamic FFI available as an advanced escape hatch, not the default interface for ordinary gameplay code.
- Make unsupported signatures fail explicitly instead of silently approximating their semantics.
- Version the API schema and define what happens when a referenced function disappears or changes its signature.

This approach is more work to design initially than exposing raw function pointers, but it offers much better portability, tooling, static validation, and AI-generated program reliability.

## 11. Further reading

These are useful primary sources for deepening the research.

[The Programming Language Lua](https://images.openai.com/static-rsc-4/_x9LKFTL2n_fCJAyIw_fKWU9HXng3_ufhb1MTr13RYq2ZaRpfVMmcaDjSShpM1M9vOF3d6xJTvEtXQhBdfCkolQLmYWIfE2Lvik7t0MnaTWJdzyS0XPfPOhPQd9EluuLpGMdEHQKE8owCuiE-ABarrdqlSU1jyhmbZ2D4FNJrew?purpose=inline)

Lua — Reference manual and C API

The canonical starting point for embedding Lua, registering native functions, managing the Lua stack, and exposing userdata.

[Lua 5.5 Reference Manual](https://www.lua.org/manual/5.5/manual.html?utm_source=chatgpt.com)

[Unreal Engine 5 Blueprint Mastery: - FlippedNormals](https://images.openai.com/static-rsc-4/AokPwGFwjUs0ryocDci2tmRNlBUZ9QBf_3sGwjueSf0VLFaA-P52u_zy90h_1zWb6pZFOde8D5-cmskyME6JyfYiDXhCsTSbe3P0Qy06YACMc8Ty9PNHJ4u4sSf6G6Xzi5Hby0fLAYQ65Yu2plhafemrbHgny5wm6Ov8o2xwmWg?purpose=inline)

Unreal Engine — Reflection and Blueprint exposure

A real example of native engine functions being exposed as typed visual-programming nodes.

[UFunctions](https://dev.epicgames.com/documentation/unreal-engine/ufunctions-in-unreal-engine?utm_source=chatgpt.com)

[Reflection System](https://dev.epicgames.com/documentation/unreal-engine/reflection-system-in-unreal-engine?utm_source=chatgpt.com)

[Desarrollo C# y .NET para empresas](https://images.openai.com/static-rsc-4/VmepVvKSkCNiHqChvDOgM-eMVGov2FWuzXhmzdN3PpI_xUZYWafz0xtK14SCuocBOmhAOXIiSoDuQVt5Ii9fPEuaDMlMtJ0WNnVJza6thWWXCKzbW7Vyh4Bt2N5wjqV-5R7FpgIeeH-a60nQ6qDK6np46wY6xOl5oaflCprEZaY?purpose=inline)

.NET — Native interoperability

Useful for understanding managed-to-native marshaling, ABI constraints, source-generated bindings, and lifetime safety.

[Native interoperability ABI support](https://learn.microsoft.com/dotnet/standard/native-interop/abi-support?utm_source=chatgpt.com)

[Native interoperability best practices](https://learn.microsoft.com/dotnet/standard/native-interop/best-practices?utm_source=chatgpt.com)

[C plain logo - free Icon PNG, SVG](https://images.openai.com/static-rsc-4/e2ru3mAxEBSv5pSBVoBJLJj-L7kvzXrdjjKyZfgYJ7O1bvX1DlKWq42V3CzAO0OSeBWxMYWnpsa8WJc0MbOTiQztJLPGhxBWXQADXA-32LJqydAYHgl6-t6P6YG4XUGEtlKXD3HKRmnLFp2oQk2aYGcu1lISSzI8KwXMZKZcPqg?purpose=inline)

Foreign function interface — General overview

A broader taxonomy of mechanisms for invoking functions across programming language boundaries.

[Wikipedia overview](https://en.wikipedia.org/wiki/Foreign_function_interface?utm_source=chatgpt.com)

## 12. Open research directions

The remaining question is how general-purpose the FFI should be versus how much it should specialize for the graph language and engine.

These are useful directions to explore next.

Which part should the research develop next?

A concrete FFI declaration syntax and type system

Lua/C/C++ binding implementation details

Mapping external functions into serialized visual graph nodes

Ownership, capabilities, effects, and safety

Comparison of Lua, Unreal Blueprints, and C# interop

What runtime should the design target?

Native C/C++ engine

Managed C# engine

Both native and managed engines

Develop this direction

> Expand the C Foreign Function Interface research into a detailed technical proposal. Focus: comparison of Lua, Unreal Blueprints, and C# interop. Target runtime: both native and managed engines. Include examples, design trade-offs, and a recommended architecture.

# Technical Proposal: A Unified FFI for Visual Programming Languages

Research specification · Version 0.1 · October 2026

## Executive summary

The proposed system is a schema-first Foreign Function Interface (FFI) that lets a visual programming language call functions implemented in C, C++, C#, and embedded scripting runtimes, without tying its serialized program format to any one engine or runtime.

The design takes inspiration from three established approaches:

- Lua: embedding a lightweight scripting language in a host application and explicitly registering native functions.
- Unreal Blueprints: exposing reflected engine functions as typed visual nodes.
- C# interop: using declared signatures, generated marshaling code, and a defined native ABI.

Lua's C API provides a well-established model for exchanging values between a host and an embedded interpreter. Unreal's reflection system shows how function metadata can drive a visual programming environment. .NET's native interoperability guidance recommends a C ABI for many native interop scenarios, particularly because C++ does not have a universally consistent ABI across compilers.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://www.lua.org\&sz=32)

Lua+2



The proposal combines these ideas into a system with five central properties:

1. One logical API schema for every engine, regardless of its implementation language.
2. Stable serialized identifiers for functions, types, and graph nodes.
3. Generated or reflected bindings instead of manually duplicating metadata.
4. Explicit safety contracts for ownership, effects, threading, errors, and permissions.
5. Multiple backends for native C/C++, managed C#, and embedded Lua.

The key architectural decision is to distinguish what a function means from how it executes.

A graph should refer to a logical operation such as `engine.entity.set_health`, not a C++ mangled symbol, a C# reflection token, a Lua stack index, or a runtime function pointer.

That separation is the foundation for portability, versioning, static validation, and reliable AI-generated programs.

## 1. Goals and non-goals

### 1.1 Goals

The FFI should support:

- Calling native C functions and selected C++ engine APIs.
- Calling managed C# methods through a managed-runtime bridge.
- Registering Lua functions and exposing native functions to Lua.
- Representing foreign functions as typed nodes in a visual graph.
- Serializing external calls in a deterministic text format.
- Generating binding code and editor metadata from a shared schema.
- Validating API availability and signatures before execution.
- Supporting synchronous calls, callbacks, asynchronous operations, and engine events.
- Handling object handles, memory ownership, and engine thread affinity.
- Producing useful diagnostics for humans and LLM-based program generators.

### 1.2 Non-goals

The initial design should not attempt to:

- Call every arbitrary C++ or C# function automatically.
- Make unsafe native code memory-safe merely by wrapping it.
- Guarantee identical performance across runtimes.
- Serialize raw pointers, runtime addresses, or process-specific handles.
- Expose all engine internals to untrusted scripts.
- Standardize every possible engine API into one universal object model.

Instead, it should define a small, predictable interoperability contract that engines can implement in different ways.

## 2. Comparison of the three reference architectures

[The Programming Language Lua](https://images.openai.com/static-rsc-4/_x9LKFTL2n_fCJAyIw_fKWU9HXng3_ufhb1MTr13RYq2ZaRpfVMmcaDjSShpM1M9vOF3d6xJTvEtXQhBdfCkolQLmYWIfE2Lvik7t0MnaTWJdzyS0XPfPOhPQd9EluuLpGMdEHQKE8owCuiE-ABarrdqlSU1jyhmbZ2D4FNJrew?purpose=inline)

## Lua: embedded runtime and explicit adapters

Primary model: host-controlled registration

Lua gives the host application control over the interpreter and its exposed APIs. C functions are registered as Lua-callable functions; native values are converted through the Lua C API.

Strengths

- Small embedding surface.
- Straightforward host-controlled API exposure.
- Flexible dynamic values and callbacks.
- Useful for gameplay scripting and runtime extensibility.

Limitations

- Bindings and type information may need to be authored separately.
- Dynamic typing shifts many errors to runtime.
- Native object lifetime and engine-thread rules require deliberate design.

[Lua 5.5 Reference Manual](https://www.lua.org/manual/5.5/manual.html?utm_source=chatgpt.com)

[The Blueprint Editor interface - Blueprints Visual Scripting for Unreal Engine - Second Edition \[Book\]](https://images.openai.com/static-rsc-4/YFifa3VEplAoAuEeJE3kuk_zpSzWCpa0WsQZUcH1u3zJ7lWUIFEDi5jpMsMaFQHVmxP8iiNESCPRLCtt3mgjaFxQAKDI91xIXURkSscHfVXA_9UntsUGygovxHjqpOckWxBxrsWjgb6eDRMUCfBdwvr36FADH6Q--5GAab64lGM?purpose=inline)

## Unreal Blueprints: reflection-driven visual API

Primary model: metadata-driven nodes

Unreal's `UFUNCTION` declarations and specifiers expose selected functions to reflection and, where appropriate, Blueprint graphs. The engine can use metadata to create callable nodes, display parameter pins, and enforce engine-specific conventions.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://dev.epicgames.com\&sz=32)

Epic Developer Community+1



Strengths

- Native declarations can drive visual-node generation.
- Types and engine objects are integrated into the editor.
- The engine can enforce domain-specific rules and conventions.
- Networking and event-related features can be reflected in API metadata.

Limitations

- The reflection model is tied to Unreal's object system and build tooling.
- Ordinary C++ functions are not automatically Blueprint-callable.
- Metadata conventions are not directly portable to another engine.

[Unreal Engine UFunctions](https://dev.epicgames.com/documentation/unreal-engine/ufunctions-in-unreal-engine?utm_source=chatgpt.com)

[Grow Programming Proficiency: C# | Go1](https://images.openai.com/static-rsc-4/1j1EH8UEI6S8Ghr_WMk9NkuVMh-LxdIrG_o0oT6wrKHRnbjHw5Ha5OLMe0meAJytT3N__NI78x3PGR6Fb_3zGi-zqefUrC7_EIOOgmVFNnu10a6cm9BvAj2D_QHLTFg5Z8TqzM8kbj1tk5HMEmRYVdJsI-Q8sXIR0ZzaOpgBOo8?purpose=inline)

## C# interop: declared signatures and generated marshaling

Primary model: ABI declarations and runtime bridges

.NET P/Invoke describes how managed code invokes native functions. On .NET 7 and later, `LibraryImport` can use source generation to produce interop stubs. Microsoft's guidance recommends matching native signatures and using appropriate lifetime-management types such as `SafeHandle` for owned unmanaged resources.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://learn.microsoft.com\&sz=32)

Microsoft Learn+1



Strengths

- Explicit signatures and compile-time tooling.
- Strong integration with managed types and runtime services.
- Generated marshaling can reduce boilerplate.
- Suitable for engines with managed gameplay APIs.

Limitations

- Native and managed representations still need careful conversion.
- P/Invoke primarily solves managed-to-native calls, not arbitrary dynamic invocation of C# methods from an external graph runtime.
- Reflection, generated delegates, or an engine bridge are needed to expose managed functions as graph nodes.

[.NET Native Interoperability](https://learn.microsoft.com/dotnet/standard/native-interop?utm_source=chatgpt.com)

### 2.1 What the comparison tells us

These are not three interchangeable FFIs.

| Dimension                          | Lua                                 | Unreal Blueprints                          | C# interop                                  |
| ---------------------------------- | ----------------------------------- | ------------------------------------------ | ------------------------------------------- |
| Primary abstraction                | Script-callable function            | Reflected engine function                  | Declared managed/native signature           |
| Typical discovery                  | Registration                        | Reflection metadata                        | Declarations, reflection, generators        |
| Type discipline                    | Usually dynamic at script boundary  | Engine-reflected types                     | Strong static types at C# boundary          |
| Node generation                    | Requires extra metadata or wrappers | Native editor capability                   | Requires an additional graph metadata layer |
| Memory management                  | Host and Lua integration rules      | Engine object and garbage-collection rules | Managed GC plus native ownership rules      |
| Cross-engine portability           | Moderate with a common API layer    | Low outside Unreal's model                 | Moderate through a common ABI               |
| Best contribution to this proposal | Embedding and adapters              | Reflection and node metadata               | ABI contracts and generated bindings        |

The recommended design should borrow the embedding model from Lua, the metadata model from Blueprints, and the signature and marshaling discipline from C# interop.

## 3. Proposed architecture

The proposed system has six layers. The first three define the contract; the remaining layers implement, validate, and execute it.

### Layer 1 — Serialized program

Textual graph · Stable node IDs · Typed edges

### Layer 2 — Canonical API schema

Signatures · Types · Effects · Ownership · Versioning

### Layer 3 — Resolver and validator

Type checking · Capability checks · API compatibility

### Layer 4 — Binding adapters

Generated wrappers · Reflection · Manual adapters

Native

C / C++ ABI

Embedded

Lua / Luau

Managed

C# / CLR

### Layer 1 — Serialized program

This is the persistent representation of the visual program. It should contain logical API references, arguments, connections, and graph-specific metadata.

It should not contain runtime pointers, native addresses, generated thunk addresses, or unstable reflection tokens.

### Layer 2 — Canonical API schema

This describes the callable operation independently of its implementation. The same schema can generate a Lua adapter, a C ABI wrapper, a C# bridge, and an editor node.

### Layer 3 — Resolver and validator

The resolver connects a logical function ID to an installed implementation. The validator checks signatures, engine versions, platform availability, permissions, and graph-level constraints before execution.

### Layer 4 — Binding adapters

An adapter converts from the language's canonical value representation into the representation expected by the implementation. It also converts results and failures back into canonical values.

### Layer 5 — Runtime dispatch

This layer invokes the adapter and enforces execution policies such as thread affinity, reentrancy, cancellation, and asynchronous scheduling.

### Layer 6 — Engine implementation

The final operation may be implemented in C, C++, C#, Lua, or another supported language. The engine owns its actual runtime objects and internal invariants.

Important architectural choice: the canonical schema is the authority for graph semantics, but it need not be the only source of truth for the native implementation. An existing engine can retain its C++ declarations or C# API and generate schema metadata from them.

## 4. The canonical API declaration format

The proposal uses a small, declarative syntax called `extern` below as an illustrative notation. It is not an existing standard.

The design goal is to express the complete callable contract with minimal ambiguity.

### 4.1 Example: a gameplay function

```
module engine.gameplay

extern function engine.entity.set_health@1(
    entity: Handle<engine.Entity>,
    health: Float32
) -> Result<Unit, EngineError> {
    implementation: auto

    effects: [mutates(entity)]
    thread: game
    capability: gameplay.write
}
```

This declaration specifies:

- A stable function ID: `engine.entity.set_health`.
- An explicit signature version: `@1`.
- A typed entity handle and a 32-bit floating-point input.
- An explicit result type that can represent failure.
- A mutation effect.
- A required execution thread.
- A capability required to invoke the operation.

The keyword `auto` means the resolver may select an implementation registered by the engine. An implementation could be generated, discovered through reflection, or registered manually.

A stable ID should identify the logical operation, not its implementation language. For example, both a C++ method and a C# method may implement the same logical operation when their observable contracts match.

### 4.2 Why explicit types matter

A language should not treat all numeric values as interchangeable.

For example:

- `Int32` is not automatically equivalent to `UInt32`.
- `Float32` is not automatically equivalent to `Float64`.
- `Handle<Entity>` is not equivalent to `Handle<Component>`.
- `String` is not automatically equivalent to `CString`.
- `Unit` is not equivalent to a nullable result.

Implicit conversions should be limited to conversions with defined semantics. Lossy conversions, ownership transfers, and pointer reinterpretations should require explicit operations or be rejected.

### 4.3 Overloads and defaults

Suppose a native library contains:

```
void SetScale(float uniform_scale);
void SetScale(float x, float y, float z);
```

The serialized graph should not refer only to `SetScale`, because that name does not identify a unique signature.

Instead, it should refer to a stable ID such as:

```
engine.transform.set_uniform_scale
engine.transform.set_scale_xyz
```

The engine may still map these IDs to overloaded native functions. The distinction belongs in the schema, where it is explicit and stable.

Defaults should also be declared in the schema rather than inferred from native code at runtime. That makes generated graphs deterministic even when the engine language has different default-argument semantics.

### 4.4 Metadata is part of the contract

The schema should distinguish three classes of metadata:

| Class        | Examples                              | Purpose                     |
| ------------ | ------------------------------------- | --------------------------- |
| Semantic     | Types, errors, mutation, ownership    | Defines program meaning     |
| Execution    | Thread, async behavior, cancellation  | Defines runtime behavior    |
| Presentation | Category, tooltip, icon, display name | Defines editor presentation |

This separation allows the editor to change its appearance without changing program semantics. Conversely, a change to the return type or ownership contract can be detected as an API compatibility change.

## 5. A portable type system for foreign APIs

The most difficult part of cross-language interoperability is not calling the function. It is defining which values can cross the boundary and what those values mean.

I recommend defining a canonical type system with three levels.

### 5.1 Level A — Portable value types

These are the easiest types to support across all three approaches.

| Canonical type                  | Intended meaning                  |
| ------------------------------- | --------------------------------- |
| `Bool`                          | Boolean value                     |
| `Int32`, `Int64`                | Signed fixed-width integer        |
| `UInt32`, `UInt64`              | Unsigned fixed-width integer      |
| `Float32`, `Float64`            | IEEE-style floating-point value   |
| `String`                        | Validated Unicode text            |
| `Bytes`                         | Arbitrary byte sequence           |
| `Vector2`, `Vector3`, `Vector4` | Defined numeric vector types      |
| `Quaternion`                    | Defined quaternion representation |
| `Result<T,E>`                   | Value or defined failure          |
| `Array<T>`                      | Typed sequence                    |
| `Option<T>`                     | Explicit presence or absence      |

These types can be copied by value, with specified conversions and serialization rules.

A canonical `Vector3`, for example, should define its component precision and layout semantics. The system must not assume that every engine uses the same struct packing or coordinate conventions.

### 5.2 Level B — Engine object references

Engine objects should normally be represented by typed handles.

```
Handle<engine.Entity>
Handle<engine.Transform>
Handle<engine.AudioSource>
```

A handle is an opaque runtime reference to an engine-owned object. Its representation might be an integer index plus a generation counter, a managed object reference, a native pointer hidden behind a registry, or another engine-specific representation.

The serialized program should not contain the actual handle value. It should contain a reference to the operation that produces or consumes a handle, with runtime values supplied during execution.

For example:

```
SpawnEntity(...) -> Handle<engine.Entity>
SetHealth(entity: Handle<engine.Entity>, health: Float32)
```

The resolver must verify that a supplied handle is valid and belongs to the expected type. A generation counter or equivalent mechanism can help detect stale references after an object is destroyed.

### 5.3 Level C — Explicitly unsafe foreign values

Some APIs genuinely require pointers, raw buffers, function pointers, native struct layouts, or other low-level representations.

These should be represented by explicit unsafe types or an escape-hatch API, not silently folded into ordinary types.

```
UnsafePointer<T>
NativeBuffer
FunctionPointer<Signature>
```

Their use should require an explicit capability or unsafe declaration. They may also be restricted to particular backends because they cannot be meaningfully serialized or interpreted portably.

Recommendation: make Level A the default, Level B the standard way to interact with engine objects, and Level C an advanced opt-in facility.

## 6. Backend design: native C and C++

The native backend should provide a stable C ABI around the selected C++ implementation.

Microsoft's .NET ABI documentation explicitly recommends C-compatible exports for many C++ interoperability scenarios because C++ does not define one universal ABI across the major supported compiler implementations.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://learn.microsoft.com\&sz=32)

Microsoft Learn+1



### 6.1 Example native implementation

The internal engine implementation can remain idiomatic C++:

```
class Entity {
public:
    void SetHealth(float health);
};
```

The generated C ABI should expose an explicit interface:

```
typedef uint64_t EngineEntityHandle;

typedef enum EngineStatus {
    ENGINE_OK = 0,
    ENGINE_INVALID_HANDLE = 1,
    ENGINE_INVALID_ARGUMENT = 2,
    ENGINE_INTERNAL_ERROR = 3
} EngineStatus;

EngineStatus engine_entity_set_health(
    EngineEntityHandle entity,
    float health
);
```

The wrapper would:

1. Resolve the opaque entity handle.
2. Check whether the entity is alive and valid.
3. Validate the health value according to engine rules.
4. Call the internal C++ method.
5. Convert the result into an `EngineStatus`.
6. Prevent any C++ exception from escaping through the C ABI.

This is illustrative C API design, not a complete implementation.

### 6.2 Why opaque handles are preferable

A raw `Entity*` is convenient inside C++, but exposing it directly creates problems:

- A pointer can become stale after object destruction.
- The consumer may not know which allocator owns it.
- A pointer does not encode the entity's semantic type.
- A raw address cannot be serialized across process runs.
- A foreign runtime may not understand the object's lifetime.

A handle registry creates an indirection layer. That adds a lookup cost, but it lets the engine invalidate handles, check types, and hide implementation details.

For frequently used internal operations, a generated backend may optimize dispatch while preserving the same external contract.

### 6.3 When to use Lua's C API directly

If the engine embeds Lua, it can expose the native wrapper through Lua's C API:

```
static int l_set_health(lua_State *L)
{
    /* Read and validate the entity userdata. */
    /* Read and validate the numeric health argument. */
    /* Call engine_entity_set_health(...). */
    /* Return results or raise a Lua error. */
    return 0;
}
```

The body is intentionally schematic: the implementation must define the exact userdata layout, handle lookup, error conversion, and stack protocol.

Lua's official manual specifies that a C function called by Lua receives arguments on the Lua stack and returns its results by pushing values and returning a result count.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://www.lua.org\&sz=32)

Lua+1



The important distinction is that the Lua adapter is not the engine API itself. It is one implementation of the binding contract.

### 6.4 Advantages and trade-offs

| Decision                   | Benefit                               | Cost                              |
| -------------------------- | ------------------------------------- | --------------------------------- |
| Stable C ABI               | Cross-compiler interoperability       | Extra wrapper layer               |
| Opaque handles             | Lifetime checks and portability       | Lookup overhead                   |
| Generated wrappers         | Reduced repetitive code               | More tooling and build complexity |
| Manual wrappers            | Maximum control                       | Maintenance burden                |
| Reflection-based discovery | Fast integration with engine metadata | Depends on the reflection system  |

For a new engine, generated wrappers are the default I would choose, with hand-written adapters available for special cases.

## 7. Backend design: managed C# engines

The managed backend needs a different strategy because C# methods live inside a managed runtime, not necessarily in a native library with exported C symbols.

There are two distinct cases:

1. The C# engine hosts the graph runtime in the same managed process.
2. A separate native or scripting runtime needs to call into C#.

These cases should not be forced through the same mechanism.

### 7.1 Case A: graph runtime hosted in C\#

If the graph runtime itself runs in .NET, the engine can expose a generated registry of typed delegates.

For example, a managed implementation might be:

```
public static class EntityApi
{
    public static EngineResult SetHealth(
        EntityHandle entity,
        float health)
    {
        if (!EntityRegistry.TryResolve(entity, out var target))
            return EngineResult.InvalidHandle;

        target.Health = health;
        return EngineResult.Success;
    }
}
```

A generated registry could associate the logical ID with the method:

```
registry.Register(
    "engine.entity.set_health",
    EntityApi.SetHealth);
```

This is conceptual code; the actual registry should use a statically defined signature rather than accepting arbitrary delegates without validation.

The graph interpreter can resolve the ID to a typed delegate and invoke it using canonical argument values.

The main benefit is that ordinary gameplay calls do not have to cross a native ABI boundary. The cost is that the graph runtime must be integrated with the managed runtime and its type system.

### 7.2 Case B: native code needs to call C\#

If a C or C++ runtime must call into a managed engine, there are several possible mechanisms:

- A managed host that exposes a narrow C-compatible entry point.
- Generated unmanaged-callable stubs.
- A runtime-specific hosting interface.
- An IPC boundary when in-process integration is unsuitable.

The appropriate choice depends on whether the managed runtime is already hosted, whether it can be initialized safely from the native application, and whether callbacks into managed code are required.

A conceptual managed-to-native declaration using .NET 7+ might look like this:

```
using System.Runtime.InteropServices;

internal static partial class NativeEngine
{
    [LibraryImport("engine_native",
        EntryPoint = "engine_entity_set_health")]
    internal static partial int SetHealth(
        ulong entity,
        float health);
}
```

This example shows the opposite direction: managed C# calling a native C ABI function. It illustrates the value of generated interop declarations, but it is not itself a native-to-managed bridge.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://learn.microsoft.com\&sz=32)

Microsoft Learn+1



To expose managed functions to a native caller, the engine must supply the appropriate hosting or unmanaged-callable mechanism.

### 7.3 Do not equate C# reflection with native interop

C# reflection can discover managed methods, but discovery does not automatically solve:

- Marshaling between native and managed values.
- Invoking methods on the correct engine thread.
- Managing delegates and object lifetimes.
- Handling exceptions and cancellation.
- Exposing a stable binary interface to C++.

For a managed-only engine, reflection plus generated delegates may be enough. For a mixed native/managed engine, a narrow C ABI is a useful interchange boundary, while managed-only calls can remain within .NET.

### 7.4 Managed backend recommendation

Use a two-path architecture:

- Managed fast path: direct typed delegate or generated managed call.
- Native interop path: generated binding through the engine's stable C ABI.

Both paths resolve from the same logical API schema. That avoids imposing native marshaling overhead on every managed gameplay call.

## 8. Backend design: Lua and Lua-like scripting

Lua is best treated as a host-controlled scripting backend, rather than as the universal type system for all external calls.

The host should expose a curated set of functions and types. Each registered function maps to a schema ID and a binding adapter.

### 8.1 Two possible exposure strategies

Strategy A — Named wrappers

Expose functions directly:

```
local ok = engine.entity.set_health(player, 75.0)
```

This is intuitive and aligns with Lua's normal function-call model. It is also easy to debug.

Strategy B — Generic dispatch

Use a central invocation interface:

```
local result = engine.call(
    "engine.entity.set_health",
    player,
    75.0
)
```

This makes it easy to invoke dynamically discovered APIs and build generic tooling, but it loses some IDE assistance and can make errors harder to locate.

I recommend using named wrappers for normal scripts and reserving generic dispatch for reflection tools, testing, debugging, and dynamic extensions.

### 8.2 The scripting representation of engine objects

Lua's full userdata is useful for representing engine-managed objects because the host controls the underlying memory and can define behavior through metatables. Light userdata, by contrast, is a raw pointer value and does not provide the same owned-memory or finalization behavior.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://www.lua.org\&sz=32)

Lua+1



The engine should therefore expose an `Entity` userdata that wraps an opaque handle or managed reference rather than treating an arbitrary native pointer as a normal script value.

For example:

```
local player = world.get_player()
player:set_health(75.0)
```

The adapter validates the userdata, resolves the current engine entity, and dispatches the operation.

### 8.3 Sandboxing and script permissions

Embedding Lua does not automatically make an application secure. The host controls which libraries and engine operations are exposed.

If scripts are generated by an LLM, downloaded, or authored by less-trusted users, the engine should use a restricted environment:

- Expose only approved APIs.
- Apply execution budgets and memory limits.
- Restrict file, network, and process access.
- Validate object handles on every relevant call.
- Prevent scripts from retaining invalid pointers.
- Enforce engine thread and permission constraints.

The Luau runtime, for example, explicitly documents sandboxing mechanisms intended for embedded environments.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://luau.org\&sz=32)

Luau



The broader design principle is that permissions belong to the runtime and binding registry, not merely to the text syntax.

## 9. Runtime dispatch and execution semantics

The system should not resolve a function ID to an arbitrary address and call it immediately. Resolution and execution should be separate stages.

### 9.1 Resolution

At load or compilation time, the resolver verifies that:

- The logical function ID exists.
- The declared signature is compatible with the installed implementation.
- The implementation is available for the current engine version and platform.
- Required capabilities are granted.
- The adapter supports the required argument and result types.

The resolver can then cache a binding descriptor or a typed callable.

### 9.2 Invocation

At runtime, the invocation pipeline should be:

1\. Validate arguments

Check value types, nullability, ranges, and handle validity.

2\. Enforce policy

Check permissions, thread affinity, and call budgets.

3\. Marshal values

Convert canonical values into backend-specific representations.

4\. Invoke adapter

Call the generated, reflected, or hand-written binding.

5\. Convert outcome

Map return values and failures into canonical result types.

6\. Record diagnostics

Attach function ID, source node, and error context.

For performance-sensitive builds, some of these checks may be proven statically and omitted from the hot path. Dynamic handles, untrusted inputs, and security-sensitive operations should still receive the necessary runtime checks.

### 9.3 Synchronous versus asynchronous functions

The schema should explicitly distinguish synchronous and asynchronous operations.

For example:

```
extern function engine.asset.load(
    path: String
) -> Task<Result<AssetHandle, EngineError>> {
    effects: [asset.read]
    thread: any
}
```

This says the function returns a task representing eventual completion rather than returning an asset handle immediately.

The graph runtime can represent this using a suspension point, an event continuation, or a typed task output.

An API should not silently turn a synchronous node into an asynchronous one because that changes execution order and graph semantics.

### 9.4 Callbacks and events

Callbacks introduce a lifetime problem because native code may retain a callback after the original graph execution has finished.

The schema should describe:

- Callback signature.
- Whether callbacks can occur multiple times.
- Whether callbacks may execute on another thread.
- How the callback is unregistered.
- Whether cancellation is supported.
- Whether callback ordering is guaranteed.

For game engines, it is usually preferable to turn engine events into registered subscriptions or event nodes rather than passing arbitrary function pointers through the graph format.

## 10. Memory ownership, lifetime, and failure handling

This area deserves stricter rules than most conventional FFI designs because graph programs are frequently edited, reloaded, hot-reloaded, and generated automatically.

### 10.1 Ownership rules

Every reference-bearing API parameter should specify one of the following policies:

| Policy     | Meaning                                                                     |
| ---------- | --------------------------------------------------------------------------- |
| `borrowed` | The callee may use the value temporarily but does not acquire ownership.    |
| `owned`    | Ownership is transferred under a defined release contract.                  |
| `shared`   | Multiple parties may retain a reference under a defined lifetime mechanism. |
| `weak`     | The reference does not keep the target alive; resolution may fail.          |
| `handle`   | The value is an opaque engine identifier resolved by the runtime.           |

These are proposed schema terms, not universal C ABI annotations.

A graph language should not infer ownership from a raw pointer type or assume that garbage collection on the scripting side controls the lifetime of native engine objects.

### 10.2 Failure model

I recommend standardizing a small set of error categories:

```
BindingNotFound
SignatureMismatch
InvalidArgument
InvalidHandle
PermissionDenied
WrongThread
OperationCancelled
NativeFailure
InternalError
```

Backends may supply more detailed diagnostic information, but the language should have a common representation.

The error should also identify the logical function and source node. For example:

```
InvalidHandle:
  function: engine.entity.set_health
  node: node_0182
  parameter: entity
  detail: The entity was destroyed before invocation.
```

This makes the failure useful to a developer and to an AI agent attempting to repair a graph.

### 10.3 Exceptions must stop at the appropriate boundary

A C++ exception should not escape a C ABI function. A managed exception should not escape an unmanaged-callable boundary without a defined translation. A Lua error should be caught or propagated according to the host's protected-call policy.

Each backend adapter must translate implementation-specific failures into the common error model.

Not every error should be treated as recoverable. A missing handle may produce an error output; a violated internal invariant may require terminating the current script or reporting a fatal engine error.

### 10.4 Hot reload

When an API module changes, the runtime must decide what happens to active calls and retained references.

Recommended policy:

- Resolve function IDs again when loading or recompiling a graph.
- Keep active invocations bound to a valid implementation for their duration.
- Invalidate or migrate stale handles according to explicit engine rules.
- Reject incompatible signatures rather than guessing a conversion.
- Version callbacks and task continuations so they cannot resume into incompatible code.

The system should never assume that a pointer or function address remains valid across hot reload.

## 11. Versioning and compatibility

A stable FFI needs to survive engine updates without silently changing the meaning of existing graphs.

### 11.1 Separate logical identity from implementation version

Consider this declaration:

```
engine.entity.set_health@1
```

The `@1` denotes the schema contract version, not necessarily the engine's software release number.

The implementation may change internally from C++ to C#, or from a manual wrapper to a generated wrapper, without requiring a new contract version if the observable behavior remains compatible.

A contract version should change when the meaning of the interface changes in a way that matters to callers.

### 11.2 Compatibility rules

| Change                                                     | Default policy                                            |
| ---------------------------------------------------------- | --------------------------------------------------------- |
| Change internal native implementation                      | Compatible                                                |
| Optimize generated wrapper                                 | Compatible                                                |
| Improve error diagnostics without changing error semantics | Compatible                                                |
| Add an optional parameter with a defined default           | Potentially compatible; validate graph and overload rules |
| Change `Float32` to `Float64`                              | Requires explicit compatibility analysis                  |
| Change ownership from borrowed to owned                    | Breaking                                                  |
| Change synchronous to asynchronous                         | Breaking                                                  |
| Change required capability                                 | Security-relevant compatibility change                    |
| Remove a function ID                                       | Breaking                                                  |
| Change a parameter's semantic meaning                      | Breaking, even if its type is unchanged                   |

A major design principle is that compatibility is semantic, not merely syntactic. Two declarations with identical parameter types can still be incompatible if one changes ownership, side effects, threading, or failure behavior.

### 11.3 Missing APIs

If an engine update removes a function, the graph editor should not replace it automatically with a similarly named function.

Instead, it should report an unresolved binding, provide the expected signature, and optionally offer explicit migration candidates.

This is especially important for AI-generated graphs: a plausible name match is not evidence that two engine functions are equivalent.

## 12. Security and capability design

The FFI is a natural security boundary because it mediates access to the engine and, potentially, the operating system.

I recommend a capability-based model. A capability is an explicit permission to invoke a category of operations.

For example:

```
capability gameplay.read
capability gameplay.write
capability asset.read
capability network.send
capability filesystem.write
```

A function can declare its required capability:

```
extern function engine.asset.load(path: String)
    -> Task<Result<AssetHandle, EngineError>> {
    capability: asset.read
}
```

This is only a sketch of the declaration syntax. A real implementation would also specify whether capabilities are inherited, scoped to a graph, or granted to a particular runtime environment.

### 12.1 Why an allowlist is better than unrestricted FFI

Unrestricted dynamic FFI may permit arbitrary native library loading, pointer manipulation, and invocation of functions with incorrectly declared signatures.

A safer architecture exposes only functions registered in the API schema. Advanced users can opt into lower-level native interfaces, but those interfaces should be visibly marked as unsafe and subject to stricter permission rules.

For untrusted or AI-generated programs, the default should be:

- No arbitrary library loading.
- No arbitrary pointer construction.
- No unrestricted filesystem or process access.
- No automatic elevation of capabilities.
- No implicit execution on privileged engine threads.

The compiler can validate declared capabilities, but the runtime must enforce them. Static validation alone is insufficient when permissions can change or values can originate from untrusted sources.

## 13. Graph serialization and bidirectional text synchronization

Because the FFI is intended for a visual programming language with a text representation, the graph serializer needs its own contract.

The file should identify nodes by stable IDs and identify foreign operations by schema IDs.

For example:

```
graph PlayerController {
    node node_01: event.begin_play

    node node_02: engine.entity.set_health@1 {
        entity = ref(player)
        health = literal(Float32, 75.0)
    }

    connect node_01.exec -> node_02.exec
}
```

This is an illustrative syntax. Its purpose is to show that the graph refers to the logical function and expresses typed arguments separately from the implementation.

### 13.1 What belongs in the graph file?

The file should contain:

- Stable graph and node identifiers.
- Logical function IDs and contract versions.
- Typed literal values and references.
- Data-flow and execution-flow connections.
- Optional editor layout metadata.
- Optional source locations or comments.

It should not contain:

- Native pointers.
- Runtime delegate instances.
- Process-specific object handles.
- Compiler-generated addresses.
- Cached function pointers.
- Implementation-specific marshaling objects.

### 13.2 What belongs in the schema registry?

The registry should contain:

- Canonical signatures.
- Type definitions.
- Ownership and nullability contracts.
- Effect declarations.
- Execution and permission requirements.
- Implementation mappings.
- API versions and deprecation metadata.
- Documentation and presentation hints.

The registry may be generated from C++ reflection, C# source declarations, Lua registration tables, or hand-authored metadata. Regardless of its origin, the output should conform to one canonical schema.

### 13.3 Bidirectional synchronization rules

When a user edits the graph visually, the serializer should update the textual representation without changing logical function IDs.

When a user edits the text, the parser should validate the same schema and reconstruct the corresponding graph.

If a function's signature changes, the editor should display the incompatibility rather than silently repairing the graph through an undocumented conversion.

This provides an important guarantee: the graph and text are two representations of the same program, not two separate sources of truth for API semantics.

## 14. Recommended implementation strategy

I would implement this architecture incrementally, beginning with the smallest subset that can prove the cross-backend contract.

### Phase 1 — Canonical schema and validator

Foundation

Implement stable IDs, fixed-width primitive types, typed handles, function signatures, return types, and basic errors.

Acceptance criteria: a graph with an unknown function, incorrect type, or incompatible signature fails validation before execution.

### Phase 2 — C ABI backend

Generate wrappers for a small set of native functions and implement opaque handles and error conversion.

Acceptance criteria: the same graph can call a C function and a C++ implementation behind the C ABI without changing its serialized node ID.

### Phase 3 — Managed C# backend

Implement a typed registry and generated managed delegates. Add a C ABI bridge for functions that must cross into native code.

Acceptance criteria: the same schema contract works with a managed-only function and a native-backed function.

### Phase 4 — Lua integration

Generate named Lua wrappers from the canonical schema, and represent engine objects through validated userdata or handle wrappers.

Acceptance criteria: Lua and the visual graph invoke the same logical operations and produce equivalent results for the supported type subset.

### Phase 5 — Production hardening

Add capability enforcement, async operations, callbacks, hot reload, API migrations, fuzz testing, and performance benchmarks.

Acceptance criteria: invalid handles, revoked permissions, wrong-thread calls, stale bindings, and incompatible API versions fail deterministically.

### 14.1 Testing requirements

The same behavioral test suite should run against each backend.

For a logical function such as `engine.entity.set_health`, tests should verify:

- Correct input and output values.
- Rejection of incorrect types.
- Rejection of invalid handles.
- Identical documented error categories.
- Enforcement of thread restrictions.
- Correct behavior when the entity is destroyed.
- Compatibility checks during schema upgrades.
- Equivalent observable semantics between native, managed, and Lua implementations.

Performance tests should separately measure resolution, argument marshaling, invocation, and result conversion. A single end-to-end timing is not enough to identify which layer dominates the cost.

## 15. Final design recommendation

The strongest design is a language-neutral API schema with backend-specific execution adapters.

I would make the following architectural choices normative for the first version.

| Concern             | Recommended decision                                   |
| ------------------- | ------------------------------------------------------ |
| Public API identity | Stable, fully qualified logical IDs                    |
| API metadata        | Canonical, machine-readable schema                     |
| Native interop      | Stable C ABI around C++ implementations                |
| Managed interop     | Typed delegates or generated managed calls             |
| Lua integration     | Host-controlled registration and generated wrappers    |
| Visual nodes        | Generated from schema metadata                         |
| Object references   | Typed, opaque engine handles                           |
| Memory ownership    | Explicit lifetime contracts                            |
| Error handling      | Common result and diagnostic model                     |
| Threading           | Explicit execution requirements                        |
| Security            | Runtime-enforced capabilities                          |
| Versioning          | Versioned contracts and explicit migrations            |
| Performance         | Generated adapters and optional direct-call fast paths |
| AI generation       | Stable IDs, explicit types, deterministic validation   |

### The most important trade-off

There are two extremes to avoid.

At one extreme, exposing every native function directly creates a fragile interface tied to compiler ABIs, runtime details, and unsafe memory conventions.

At the other extreme, forcing every operation through a fully generic reflection dispatcher can introduce unnecessary runtime overhead and obscure useful type information.

The recommended compromise is a schema-first, generated-by-default, reflection-assisted architecture:

- Use reflection to discover eligible functions where the engine supports it.
- Generate adapters and typed metadata during the build.
- Use hand-written wrappers for APIs that need special ownership or lifetime rules.
- Use direct typed calls where safe and efficient.
- Preserve the same logical schema and serialized graph format across all implementations.

This is a practical synthesis of Lua's embedding model, Unreal's reflection-driven node exposure, and .NET's explicit interop contracts.

## 16. Further research

The following primary references are the best starting points for validating and extending this proposal.

Lua and embedded scripting

[Lua 5.5 Reference Manual](https://www.lua.org/manual/5.5/manual.html?utm_source=chatgpt.com)

C API, value stack, userdata, error handling, garbage collection, and coroutines.

Unreal reflection and visual nodes

[UFunctions in Unreal Engine](https://dev.epicgames.com/documentation/unreal-engine/ufunctions-in-unreal-engine?utm_source=chatgpt.com)

[Reflection System in Unreal Engine](https://dev.epicgames.com/documentation/unreal-engine/reflection-system-in-unreal-engine?utm_source=chatgpt.com)

Native function metadata, Blueprint exposure, and engine-managed reflection.

C# and native ABI interoperability

[Native interoperability ABI support](https://learn.microsoft.com/dotnet/standard/native-interop/abi-support?utm_source=chatgpt.com)

[Native interoperability best practices](https://learn.microsoft.com/dotnet/standard/native-interop/best-practices?utm_source=chatgpt.com)

[P/Invoke source generation](https://learn.microsoft.com/dotnet/standard/native-interop/pinvoke-source-generation?utm_source=chatgpt.com)

ABI compatibility, signature declarations, marshaling, generated stubs, and resource lifetime.

## 17. Open design decisions

Before treating this as a formal specification, I would resolve three remaining questions:

1. Should the canonical schema be a standalone source language or generated metadata? A standalone schema makes API contracts portable, while generated metadata can integrate more easily with existing C++ and C# codebases. A hybrid is likely the best default.
2. Should the runtime use a uniform value representation or typed generated calls? A uniform representation simplifies implementation, while typed calls generally allow stronger checking and more optimization. A hybrid—with uniform values at the registry boundary and generated typed adapters at invocation—is a promising compromise.
3. How much unsafe interop should the language expose? Hiding raw pointers and arbitrary native calls makes graph programs easier to validate, but systems programmers may need a controlled escape hatch.

My recommendation is to start with a strict, portable core and make backend-specific capabilities explicit extensions. That keeps the initial language small enough to specify rigorously while leaving room for native performance, managed runtime integration, and embedded scripting.

The decisive principle is this: the FFI should define a stable semantic contract between the program and the engine, not merely provide a mechanism for jumping from one runtime into another.
