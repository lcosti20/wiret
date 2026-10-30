## 6. Runtime and embedding API (C)

### 6.1 Design

The API follows the Lua C API's central ideas and fixes the parts that do not suit a statically typed, verified language.

| Lua idea | Wiret version |
| --- | --- |
| No global state; everything hangs off `lua_State` | `wr_Vm` owns the heap, modules and scheduler. A `wr_Fiber` owns one value stack and its frames. Nothing is global, so any number of VMs can coexist. |
| A virtual stack is the only data channel | Same: 1-based indices from the bottom, negative from the top. Slots are **typed**, and `wr_type` tells you what is in one. |
| `lua_call` may longjmp; `lua_pcall` does not | Every call is protected. The VM never unwinds through host frames, and natives report errors by returning `wr_fault(...)`. |
| `luaL_ref` registry | `wr_ref` / `wr_pushref` / `wr_unref` keep a value alive from host code. |
| `lua_Alloc` | `wr_AllocFn` is the only way the VM obtains memory. |
| Coroutines (`lua_resume`) | Fibers. Latent nodes suspend them. The host drives time with `wr_advance`. |
| Userdata | Host handles: `(index, generation)` pairs that become invalid when the host says the object is gone. |

**Conventions.** Functions that can fail return `wr_Status`. A value pushed on the stack is owned by the fiber and may be collected once it is removed. Pointers returned by `wr_to_string` and `wr_to_host` are valid only while the value stays on the stack. A `wr_Vm` and all of its fibers belong to one thread at a time; to use several threads, create one VM per thread. The header is plain C99 and exports only `wr_`-prefixed names.

### 6.2 Status codes

| Status | Meaning |
| --- | --- |
| `WR_OK` | Finished. Results are on the stack. |
| `WR_YIELD` | The fiber suspended (`Delay`, `Yield`, `Await`). It is owned by the scheduler now. |
| `WR_ERR_FAULT` | An uncaught fault. See `wr_fault_info`. |
| `WR_ERR_FUEL` | The fuel budget ran out. Not catchable in Wiret. |
| `WR_ERR_MEM` | The heap limit was hit or the allocator failed. Not catchable. |
| `WR_ERR_LOAD` | The `.wbc` is malformed. |
| `WR_ERR_VERIFY` | The module failed verification (section 5.5). |
| `WR_ERR_LINK` | An import, export or name could not be resolved, or its signature differs. |
| `WR_ERR_API` | The host misused the API: wrong stack type, bad index, yielding across a native. |
| WR\_ERR\_INTERRUPT | Stopped by wr\_interrupt, for example by a wall-clock watchdog. Not catchable. |

### 6.3 The header

```c
/* wiret.h (draft) */
#include <stddef.h>
#include <stdint.h>

#define WR_BYTECODE_VERSION 1
#define WR_MULTRET (-1)

typedef struct wr_Vm     wr_Vm;
typedef struct wr_Fiber  wr_Fiber;
typedef struct wr_Module wr_Module;

typedef enum { WR_OK = 0, WR_YIELD, WR_ERR_FAULT, WR_ERR_FUEL, WR_ERR_MEM,
               WR_ERR_LOAD, WR_ERR_VERIFY, WR_ERR_LINK, WR_ERR_API, WR_ERR_INTERRUPT } wr_Status;

typedef enum { WR_T_NULL, WR_T_BOOL, WR_T_I32, WR_T_I64, WR_T_F32, WR_T_F64,
               WR_T_STRING, WR_T_STRUCT, WR_T_CLASS, WR_T_ARRAY, WR_T_MAP, WR_T_SET,
               WR_T_DELEGATE, WR_T_DISPATCHER, WR_T_HOST, WR_T_SIGNAL,
               WR_T_FAULT } wr_Type;

typedef void *(*wr_AllocFn)(void *ud, void *ptr, size_t old_size, size_t new_size);
typedef int   (*wr_NativeFn)(wr_Fiber *f, void *ud);

typedef struct wr_Error { wr_Status status; int code; char message[256]; } wr_Error;

#define WR_CFG_DETERMINISTIC 1   /* deterministic mode, section 4.10: refuse natives not marked deterministic */
#define WR_CFG_AUDIT_NATIVES 2   /* call cacheable natives twice and compare (section 4.3); a debugging aid */

typedef struct wr_Config {
  size_t   struct_size;                  /* set by wr_config_init; lets the struct grow */
  unsigned flags;                        /* WR_CFG_DETERMINISTIC | WR_CFG_AUDIT_NATIVES */
  wr_AllocFn alloc;  void *alloc_ud;     /* NULL: malloc family            */
  size_t   max_heap_bytes;               /* 0: unlimited                   */
  uint32_t max_stack_slots;              /* per fiber, default 1<<20       */
  uint32_t max_call_depth;               /* default 4096                   */
  uint32_t max_cont_depth;               /* per frame, default 1024        */
  int64_t  default_fuel;                 /* per wr_call / per wake, <0: unlimited */
  void (*on_fault)(wr_Vm *, wr_Fiber *, void *ud);  /* detached fiber faulted */
  void (*on_log)(wr_Vm *, int level, const char *msg, void *ud);
  void *ud;
} wr_Config;
```

### 6.4 VM lifecycle

```c
void       wr_config_init(wr_Config *cfg);          /* fill defaults */
wr_Vm     *wr_vm_new(const wr_Config *cfg);         /* NULL on allocation failure */
void       wr_vm_free(wr_Vm *vm);                   /* frees fibers, modules, heap */
void      *wr_vm_userdata(wr_Vm *vm);
double     wr_vm_time(wr_Vm *vm);                   /* virtual seconds */

wr_Fiber  *wr_fiber_new(wr_Vm *vm);
void       wr_fiber_free(wr_Fiber *f);              /* not while RUNNING */
typedef enum { WR_FIBER_READY, WR_FIBER_RUNNING, WR_FIBER_SUSPENDED,
               WR_FIBER_DONE, WR_FIBER_FAULTED } wr_FiberStatus;
wr_FiberStatus wr_fiber_status(wr_Fiber *f);
void       wr_fiber_kill(wr_Fiber *f);              /* ends it without running handlers */
```

**ABI stability.** Structs that cross the API (`wr_Config`, `wr_HostType`, `wr_FaultInfo`, `wr_Stats`) begin with `size_t struct_size`, filled in by the matching `*_init` function or by the caller. The VM reads only as many bytes as the caller declared and treats missing trailing fields as zero, so a host built against an older header keeps working against a newer library. In a VM created with `WR_CFG_DETERMINISTIC`, wall-clock budgets (`wr_interrupt`) still work, but registering a native that is neither `WR_NATIVE_DETERMINISTIC` nor `WR_NATIVE_CACHEABLE` fails with `WR_ERR_LINK`, so a replay cannot silently depend on a clock or a random source.

### 6.5 Modules

```c
#define WR_LOAD_BORROW    2   /* keep a pointer to the caller's bytes instead of copying; one image can be loaded into several VMs */
#define WR_LOAD_LAZY_LINK 1   /* unresolved imports fault when called, not at load */

wr_Status wr_module_load(wr_Vm *vm, const void *bytes, size_t len, const char *name,
                         unsigned flags, wr_Module **out, wr_Error *err);
wr_Status wr_module_load_file(wr_Vm *vm, const char *path, unsigned flags,
                              wr_Module **out, wr_Error *err);
void      wr_module_release(wr_Vm *vm, wr_Module *m);
const char *wr_module_hash(wr_Module *m, int which);   /* 0 semantic, 1 layout; hex */

typedef struct wr_ExportInfo {
  const char *name;        /* "SumTo", "Player.TakeDamage" */
  const char *signature;   /* "(i32)->(i32)" */
  unsigned    flags;       /* WR_EXPORT_EVENT | _LATENT | _PURE */
} wr_ExportInfo;
void wr_module_each_export(wr_Module *m, void (*fn)(const wr_ExportInfo *, void *), void *ud);
```

Loading decodes, **verifies**, then links. Link resolves each import against natives registered with `wr_register` and compares signatures; any mismatch is `WR_ERR_LINK`, with the offending name in `err->message`. A module cannot reach any capability the host did not register. Loading the same bytes twice gives two independent instances with separate globals.

**Capabilities and linking.** An import can carry `@capability("console.write")` in source. The compiler lists every required capability in the `wr.caps` section, so a host can inspect a module before it runs anything. Nothing is granted by default.

```c
wr_Status wr_grant(wr_Vm *vm, const char *capability);
void      wr_module_each_capability(wr_Module *m, void (*fn)(const char *cap, void *), void *ud);
wr_Status wr_link(wr_Vm *vm);     /* resolve imports left pending by WR_LOAD_LAZY_LINK */
```

An import whose capability is not granted fails the load with `WR_ERR_LINK`, naming the capability. Imports between Wiret modules are resolved against the exports of modules already loaded, then against natives (section 7.3). To load modules that depend on each other in any order, pass `WR_LOAD_LAZY_LINK` to each and call `wr_link` once.

### 6.6 Natives and host types

```c
#define WR_NATIVE_EFFECT_FREE   1   /* writes nothing observable; may read VM or host state; callable from @reads graphs */
#define WR_NATIVE_DETERMINISTIC 2   /* same arguments and same VM state give the same result */
#define WR_NATIVE_CACHEABLE     4   /* depends only on its arguments; implies 1 and 2; callable from @pure graphs */

/* name: "host.Log"; sig uses Wiret type syntax: "(string)->()", "(i32,f32)->(bool)" */
wr_Status wr_register(wr_Vm *vm, const char *name, const char *sig,
                      wr_NativeFn fn, void *ud, unsigned flags);

/* A native receives its arguments at stack indices 1..n, already checked against
   the registered signature. It pushes its results and returns how many it pushed,
   or returns wr_fault(...). */
int wr_fault(wr_Fiber *f, const char *fmt, ...);   /* returns -1 */

typedef struct wr_HostType {
  size_t      struct_size;                            /* sizeof(wr_HostType), set by the caller */
  const char *name;                                   /* "engine.Actor" */
  void (*finalize)(wr_Vm *, void *ptr, void *ud);     /* called when the last handle is collected */
  void *ud;
} wr_HostType;
wr_Status wr_register_type(wr_Vm *vm, const wr_HostType *t);
void      wr_push_host(wr_Fiber *f, const char *type, void *ptr);  /* same ptr, same identity */
void     *wr_to_host(wr_Fiber *f, int idx, const char *type);      /* NULL if wrong type or invalidated */
void      wr_host_invalidate(wr_Vm *vm, void *ptr);   /* the host destroyed it: IsValid becomes false */
```

The flags are claims by the host; the VM cannot verify them (section 4.3, "Natives are trusted, not proved"). `WR_NATIVE_CACHEABLE` without the other two bits is rejected at registration.

Natives cannot suspend in version 1. Host-side asynchronous work is modelled by returning a `std.Signal` (created with `wr_push_signal`) and firing it later; the graph uses `Await`. A native may call back into Wiret with `wr_call`, but the nested call cannot suspend (it would report `WR_ERR_API`).

### 6.7 The stack

```c
int  wr_gettop(wr_Fiber *f);              void wr_settop(wr_Fiber *f, int idx);
void wr_pop(wr_Fiber *f, int n);          void wr_pushvalue(wr_Fiber *f, int idx);
void wr_remove(wr_Fiber *f, int idx);     void wr_insert(wr_Fiber *f, int idx);
void wr_replace(wr_Fiber *f, int idx);
int  wr_checkstack(wr_Fiber *f, int extra);          /* 0 if it cannot grow */

wr_Type     wr_type(wr_Fiber *f, int idx);
const char *wr_typename(wr_Fiber *f, int idx);       /* "i32", "game.demo.Player", "array<i32>" */

void wr_push_bool(wr_Fiber *f, int b);    void wr_push_i32(wr_Fiber *f, int32_t v);
void wr_push_i64(wr_Fiber *f, int64_t v); void wr_push_f32(wr_Fiber *f, float v);
void wr_push_f64(wr_Fiber *f, double v);
void wr_push_string(wr_Fiber *f, const char *s, size_t len);   /* copies */
void wr_push_null(wr_Fiber *f, const char *type);              /* typed null reference */
void wr_push_signal(wr_Fiber *f);

int         wr_to_bool(wr_Fiber *f, int idx);       int32_t wr_to_i32(wr_Fiber *f, int idx);
int64_t     wr_to_i64(wr_Fiber *f, int idx);        float   wr_to_f32(wr_Fiber *f, int idx);
double      wr_to_f64(wr_Fiber *f, int idx);
const char *wr_to_string(wr_Fiber *f, int idx, size_t *len);   /* valid while on the stack */
```

The `wr_to_*` functions return 0 or NULL when the slot has another type; use `wr_type` to branch. Narrow integer parameters (`u8`, `i16`, ...) are pushed and read as `i32`.

**Objects and containers.** All look-ups are by name and return `wr_Status`.

```c
wr_Status wr_push_new(wr_Fiber *f, wr_Module *m, const char *type);  /* class, struct or "array<i32>" ... */
wr_Status wr_getfield(wr_Fiber *f, int idx, const char *field);      /* pushes the field */
wr_Status wr_setfield(wr_Fiber *f, int idx, const char *field);      /* pops a value; a struct slot is replaced by the updated copy */

int       wr_array_len(wr_Fiber *f, int idx);
wr_Status wr_array_get(wr_Fiber *f, int idx, int i);                 /* pushes element */
wr_Status wr_array_set(wr_Fiber *f, int idx, int i);                 /* pops value */
wr_Status wr_array_push(wr_Fiber *f, int idx);                       /* pops value */
int       wr_map_len(wr_Fiber *f, int idx);
wr_Status wr_map_get(wr_Fiber *f, int idx);    /* key on top is replaced by the value; pushes found flag */
wr_Status wr_map_set(wr_Fiber *f, int idx);    /* pops value, then key */
wr_Status wr_map_key_at(wr_Fiber *f, int idx, int i);                /* insertion order */

int  wr_ref(wr_Fiber *f);                      /* pops the top value; returns a ref (> 0) */
void wr_pushref(wr_Fiber *f, int ref);
void wr_unref(wr_Vm *vm, int ref);
```

Containers on the stack follow the value rules of section 4.9. `wr_pushvalue` duplicates a slot and marks a container shared, and so do `wr_ref` and `wr_pushref`. The mutators above (`wr_array_set`, `wr_array_push`, `wr_map_set`) operate on the slot at `idx`; when the container is shared they replace that slot with an updated copy, exactly as `wr_setfield` does for a struct. A copy kept earlier, on the stack or in the registry, never sees the change.

### 6.8 Calling Wiret and running fibers

```c
wr_Status wr_push_func(wr_Fiber *f, wr_Module *m, const char *name);     /* "SumTo", "Player.OnTick" */
wr_Status wr_push_virtual(wr_Fiber *f, int obj_idx, const char *method); /* resolves the override */

wr_Status wr_call(wr_Fiber *f, int nargs, int nresults);   /* run now, on the caller's thread */
wr_Status wr_start(wr_Fiber *f, int nargs);                /* queue; runs during wr_advance */
wr_Status wr_advance(wr_Vm *vm, double dt);                /* advance virtual time, run what is ready */
void      wr_signal_fire(wr_Vm *vm, int signal_ref);       /* wake fibers awaiting it */
```

Calling protocol, as in Lua: push the function, push the arguments left to right, call. `wr_call` pops the function and arguments. On `WR_OK` it pushes `nresults` results (or all of them for `WR_MULTRET`). On `WR_YIELD` the fiber is suspended; when the scheduler later finishes it (`wr_fiber_status` becomes `WR_FIBER_DONE`) the results are on that fiber's stack. A fiber runs one call at a time; reuse it after it is `DONE` by clearing its stack with `wr_settop(f, 0)`.

`wr_advance` is deterministic. It adds `dt` to the virtual clock, wakes timers whose time has come (ordered by wake time, then by fiber creation order), and runs each woken or queued fiber until it suspends again or finishes. Each run gets `default_fuel`. A fault in a detached fiber is passed to `on_fault`.

Latency is part of a function's contract (section 4.5). `wr_call` on an export that is **not** flagged `WR_EXPORT_LATENT` returns `WR_OK` or an error and never `WR_YIELD`. Only latent exports and events can suspend, and a host that calls one with `wr_call` must be prepared for `WR_YIELD`.

### 6.9 Faults and tracebacks

```c
typedef struct wr_Frame {
  const char *function;   /* "game.demo.Player.TakeDamage" */
  const char *node;       /* node id from wr.debug, or NULL */
  uint32_t    pc;
} wr_Frame;

typedef struct wr_FaultInfo {
  size_t      struct_size;   /* set by the caller before the call */
  wr_Status   status;     /* WR_ERR_FAULT, WR_ERR_FUEL, ... */
  int32_t     code;       /* from Throw, or a built-in fault code */
  const char *message;    /* valid until the fiber's next call */
  int         nframes;
} wr_FaultInfo;

int wr_fault_info(wr_Fiber *f, wr_FaultInfo *out);        /* 0 if there is none */
int wr_frame_info(wr_Fiber *f, int level, wr_Frame *out); /* level 0 is the faulting frame */
```

Because `wr_Frame` carries the node id, a host can report `Player.TakeDamage, node store: null reference` and an editor can highlight that node.

### 6.10 Resource control and debugging

```c
void    wr_set_fuel(wr_Fiber *f, int64_t units);   int64_t wr_get_fuel(wr_Fiber *f);
size_t  wr_mem_used(wr_Vm *vm);
typedef enum { WR_GC_COLLECT, WR_GC_STEP, WR_GC_STOP, WR_GC_RESTART } wr_GcOp;
size_t  wr_gc(wr_Vm *vm, wr_GcOp op, size_t arg);

#define WR_HOOK_NODE 1   /* a node starts executing */
#define WR_HOOK_CALL 2
#define WR_HOOK_RETURN 4
#define WR_HOOK_FAULT 8
#define WR_HOOK_BREAK 16 /* a breakpoint was hit */
typedef void (*wr_HookFn)(wr_Fiber *f, int event, const wr_Frame *frame, void *ud);
void      wr_set_hook(wr_Vm *vm, wr_HookFn fn, int mask, void *ud);
wr_Status wr_set_breakpoint(wr_Vm *vm, wr_Module *m, const char *function,
                            const char *node_id, int enabled);
```

The collector is a precise tracing GC. It is non-moving in version 1, but the API never exposes object addresses, so a moving or generational collector can be added later. Hooks run inline on the fiber's thread; a debugger front end blocks inside the hook while the user inspects the stack. Breakpoints work by patching a `brk` instruction (opcode `0F`) over the first instruction of the node's block.

```c
void wr_interrupt(wr_Vm *vm);     /* the only thread-safe call */

typedef struct wr_Stats {
  size_t   struct_size;   /* set by the caller before the call */
  size_t   heap_bytes;  size_t   live_objects;
  uint64_t fuel_used;   uint32_t fibers;  uint32_t modules;
} wr_Stats;
void wr_get_stats(const wr_Vm *vm, wr_Stats *out);
```

Fuel is deterministic but does not bound wall-clock time. `wr_interrupt` may be called from any thread, for example by a watchdog; running fibers stop at the next call or backward branch with `WR_ERR_INTERRUPT`. It is the single exception to the rule that a VM belongs to one thread at a time.

```c
/* Push the last value of a node's output pin in stack frame `level` (0 = top frame).
   Works on suspended or faulted fibers and from hooks. Returns WR_ERR_API if the pin's
   value was not kept (see wr.pins and -Og). */
wr_Status wr_getpin(wr_Fiber *f, int level, const char *node, const char *pin);
```

With `-Og` builds, an editor can show the live value on every wire of a paused graph, and a host can log the inputs of a failing node. The node name is path-style inside macros (`loop/test`).

### 6.11 Example host

```c
#include <stdio.h>
#include <wiret.h>

static int host_log(wr_Fiber *f, void *ud) {
  size_t n; const char *s = wr_to_string(f, 1, &n);
  fwrite(s, 1, n, stdout); fputc('\n', stdout);
  return 0;                                   /* pushed no results */
}

int main(void) {
  wr_Config cfg; wr_config_init(&cfg);
  cfg.default_fuel = 1000000;                 /* sandbox: bounded work per call */
  wr_Vm *vm = wr_vm_new(&cfg);
  wr_register(vm, "host.Log", "(string)->()", host_log, NULL, 0);

  wr_Module *mod; wr_Error err;
  if (wr_module_load_file(vm, "demo.wbc", 0, &mod, &err) != WR_OK) {
    fprintf(stderr, "load failed: %s\n", err.message);
    return 1;
  }

  wr_Fiber *f = wr_fiber_new(vm);

  /* int total = SumTo(10); */
  wr_push_func(f, mod, "SumTo");
  wr_push_i32(f, 10);
  if (wr_call(f, 1, 1) == WR_OK)
    printf("SumTo(10) = %d\n", wr_to_i32(f, -1));      /* 55 */
  wr_settop(f, 0);

  /* Player p = new Player(); bool died = p.TakeDamage(150); */
  wr_push_new(f, mod, "Player");                         /* index 1 */
  wr_push_virtual(f, 1, "TakeDamage");                   /* index 2: the function */
  wr_pushvalue(f, 1);                                    /* self */
  wr_push_i32(f, 150);                                   /* amount */
  if (wr_call(f, 2, 1) == WR_OK)                         /* logs "Player died" */
    printf("died = %d\n", wr_to_bool(f, -1));            /* 1 */
  else {
    wr_FaultInfo fi; wr_fault_info(f, &fi);
    fprintf(stderr, "fault: %s\n", fi.message);
  }

  wr_fiber_free(f);
  wr_module_release(vm, mod);
  wr_vm_free(vm);
  return 0;
}
```

A typical game loop adds one call per frame: `wr_advance(vm, dt)`. Events are started with `wr_start`, or with `wr_call` when the caller wants the first segment to run synchronously.
