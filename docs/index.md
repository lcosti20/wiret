# Wiret Language Specification & Reference

**Wiret** is a human-readable, graph-oriented, text-based intermediate representation (IR) and programming language. Designed to bridge visual scripting paradigms (like Unreal Engine Blueprints) with traditional software development workflows, Wiret provides full fidelity for node-graph layouts, strict typing, deterministic compilation to bytecode, and a lightweight, C-embeddable runtime.

---

## 1. Text Syntax Design (`.wiret`)

Wiret syntax combines LLVM-IR explicit SSA/data-flow ordering with GML/DOT-style graph attributes and metadata annotations.

### Key Syntax Concepts

* **Attributes / Metadata (`@...`)**: Placed inside square brackets `[...]` on graphs, nodes, pins, and edges to preserve visual positioning, comments, and runtime annotations without affecting evaluation logic.
* **Flow Execution (`->`)**: Control flow connections between execution pins.
* **Data Flow (`=`)**: Explicit data assignments from source node pins to target inputs.
* **Types**: `exec`, `i32`, `i64`, `f32`, `f64`, `bool`, `string`, `object`, `array<T>`, `any`.

### Example: Standard Class & Function Graph

```wiret
module MathUtils @[version="1.0.0", author="Wiret Team"] {

    // Function Graph Definition
    function CalculateDamage(
        pin exec in_flow,
        pin f32 base_damage @[tooltip="Base attack power"],
        pin f32 armor @[tooltip="Target armor value"],
        pin bool is_critical
    ) -> (
        pin exec out_flow,
        pin f32 final_damage
    ) @[pos={x:100, y:50}, color="#3498db"] 
    {
        // Entry Node
        node Entry = core::entry @[pos={x:0, y:0}] {
            out exec flow -> Branch.flow;
            out f32 base = base_damage;
            out f32 arm = armor;
            out bool crit = is_critical;
        }

        // Branch (If / Else) Node
        node Branch = core::branch @[pos={x:250, y:0}] {
            in exec flow;
            in bool condition = Entry.crit;

            out exec true_branch -> MultCrit.flow;
            out exec false_branch -> ArmorCalc.flow;
        }

        // Multiply Critical Damage Node
        node MultCrit = math::multiply @[pos={x:500, y:-100}] {
            in exec flow;
            in f32 a = Entry.base;
            in f32 b = 2.0;

            out exec flow_out -> ArmorCalc.flow;
            out f32 result;
        }

        // Armor Calculation Node
        node ArmorCalc = math::sub_clamp @[pos={x:750, y:0}] {
            in exec flow;
            in f32 raw_val = select(Entry.crit, MultCrit.result, Entry.base);
            in f32 reduction = Entry.arm;

            out exec flow_out -> Exit.flow;
            out f32 net_damage;
        }

        // Function Return Node
        node Exit = core::return @[pos={x:1000, y:0}] {
            in exec flow;
            in f32 damage_val = ArmorCalc.net_damage;

            out exec out_flow -> super.out_flow;
            out f32 final_damage -> super.final_damage;
        }
    }
}

```

---

## 2. Bytecode Specification (`.wbc`)

Wiret source files compile into binary bytecode files (`.wbc`). The format is designed for fast, single-pass decoding and low memory overhead.

### Binary Layout Structure

```
+-------------------------------------------------------+
| Magic Number: 'W', 'I', 'R', 'E' (4 bytes: 0x57495245) |
+-------------------------------------------------------+
| Version Major (u16) | Version Minor (u16)             |
+-------------------------------------------------------+
| Constant Pool Offset (u32) | Section Count (u32)      |
+-------------------------------------------------------+
| Constant Pool (Strings, Floats, Large Integers)       |
+-------------------------------------------------------+
| Function Headers Table                                |
+-------------------------------------------------------+
| Bytecode Instructions Stream                          |
+-------------------------------------------------------+
| Metadata Table (Strippable for production release)    |
+-------------------------------------------------------+

```

### Instruction Set Architecture (ISA)

Wiret bytecode operates on a stack-based virtual machine with local register windows per frame.

| Opcode | Mnemonic | Operands | Description |
| --- | --- | --- | --- |
| `0x00` | `NOP` | None | No operation |
| `0x01` | `PUSH_I32` | `i32_val` | Push 32-bit integer onto evaluation stack |
| `0x02` | `PUSH_F32` | `f32_val` | Push 32-bit float onto evaluation stack |
| `0x03` | `PUSH_CONST` | `const_idx (u16)` | Push constant from Constant Pool |
| `0x10` | `LOAD_LOCAL` | `slot (u16)` | Load variable from local register slot |
| `0x11` | `STORE_LOCAL` | `slot (u16)` | Store top of stack to local register slot |
| `0x20` | `ADD_F32` | None | Pop `b`, pop `a`, push `a + b` |
| `0x21` | `SUB_F32` | None | Pop `b`, pop `a`, push `a - b` |
| `0x22` | `MUL_F32` | None | Pop `b`, pop `a`, push `a * b` |
| `0x23` | `DIV_F32` | None | Pop `b`, pop `a`, push `a / b` |
| `0x30` | `JUMP` | `offset (i32)` | Unconditional branch |
| `0x31` | `JUMP_IF_FALSE` | `offset (i32)` | Pop condition; jump if zero/false |
| `0x40` | `CALL` | `func_idx (u32)` | Call Wiret function |
| `0x41` | `CALL_HOST` | `host_fn_idx (u32)` | Call host C function via binding |
| `0x50` | `RETURN` | None | Return from function frame |

---

## 3. C Runtime API Design

The Wiret Runtime C API follows Lua's stack-based host interop pattern for safety, performance, and simplicity.

```c
/* wiret.h - Host API Header */
#ifndef WIRET_H
#define WIRET_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Opaque state types */
typedef struct wiret_State wiret_State;
typedef int (*wiret_CFunction)(wiret_State* L);

/* Basic State Management */
wiret_State* wiret_newstate(void);
void wiret_close(wiret_State* L);

/* Bytecode Loading and Execution */
int wiret_loadbuffer(wiret_State* L, const char* buffer, size_t size, const char* name);
int wiret_loadfile(wiret_State* L, const char* filename);
int wiret_pcall(wiret_State* L, int nargs, int nresults);

/* Stack Push Operations */
void wiret_pushnil(wiret_State* L);
void wiret_pushinteger(wiret_State* L, int64_t n);
void wiret_pushnumber(wiret_State* L, double n);
void wiret_pushboolean(wiret_State* L, int b);
void wiret_pushlstring(wiret_State* L, const char* s, size_t len);
void wiret_pushcfunction(wiret_State* L, wiret_CFunction fn);

/* Stack Retrieval & Type Querying */
int wiret_type(wiret_State* L, int idx);
int64_t wiret_tointeger(wiret_State* L, int idx);
double wiret_tonumber(wiret_State* L, int idx);
int wiret_toboolean(wiret_State* L, int idx);
const char* wiret_tostring(wiret_State* L, int idx, size_t* len);

/* Registration & Bindings */
void wiret_register(wiret_State* L, const char* name, wiret_CFunction fn);
void wiret_pop(wiret_State* L, int n);

#ifdef __cplusplus
}
#endif

#endif /* WIRET_H */

```

---

## 4. Comprehensive Example: C Host Integration

The following program initializes the runtime, registers a native C function (`Host_PrintLog`), loads compiled bytecode, calls a Wiret function graph, and reads the return value back into C.

```c
#include <stdio.h>
#include <stdlib.h>
#include "wiret.h"

// Host function exposed to Wiret graphs
static int Host_PrintLog(wiret_State* L) {
    size_t len;
    const char* msg = wiret_tostring(L, 1, &len);
    printf("[HOST LOG]: %s\n", msg);
    wiret_pushboolean(L, 1); // Return success
    return 1; // Number of return values
}

int main(int argc, char** argv) {
    // 1. Initialize Runtime State
    wiret_State* L = wiret_newstate();
    if (!L) {
        fprintf(stderr, "Failed to create Wiret VM instance.\n");
        return 1;
    }

    // 2. Register Host Functions
    wiret_register(L, "host_print_log", Host_PrintLog);

    // 3. Load Compiled Wiret Bytecode
    if (wiret_loadfile(L, "MathUtils.wbc") != 0) {
        fprintf(stderr, "Error loading script: %s\n", wiret_tostring(L, -1, NULL));
        wiret_close(L);
        return 1;
    }

    // 4. Push Arguments onto Stack for `CalculateDamage`
    // Arguments: base_damage=100.0, armor=25.0, is_critical=true
    wiret_pushnumber(L, 100.0);
    wiret_pushnumber(L, 25.0);
    wiret_pushboolean(L, 1);

    // 5. Call `CalculateDamage` with 3 args and 1 expected result
    if (wiret_pcall(L, 3, 1) != 0) {
        fprintf(stderr, "Execution error: %s\n", wiret_tostring(L, -1, NULL));
        wiret_close(L);
        return 1;
    }

    // 6. Retrieve Result from Stack
    if (wiret_type(L, -1) == 2 /* NUMBER */) {
        double result = wiret_tonumber(L, -1);
        printf("Final Calculated Damage: %.2f\n", result);
    }
    wiret_pop(L, 1);

    // 7. Cleanup VM State
    wiret_close(L);
    return 0;
}

```
