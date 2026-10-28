# Wiret Formal Grammar and Reference

This document complements the language overview in `docs/index.md` by giving a more formal, reference-oriented description of the Wiret syntax, type model, and runtime contract.

It is intended for:

- parser implementers
- tool authors and code generators
- editors and diff/merge tools
- LLM-based source generation and validation

## 1. Scope

Wiret is a graph-first, text-based language for authoring visual programs as explicit node-and-wire graphs. A `.wiret` file defines a single logical module, and the canonical serialized form is designed to be stable, merge-friendly, and textual enough to be reviewed in Git.

The design goals are:

- one node per line in the canonical representation
- fully-resolved graph structure in source form
- explicit semantic attributes and editor metadata
- deterministic formatting and canonical ordering
- verified bytecode output
- runtime execution from a typed VM with fibers and host integration

## 2. Lexical model

### 2.1 File format

A `.wiret` file is:

- UTF-8 without BOM
- LF line endings
- a single module
- terminated by a final newline

Whitespace is not significant except where it separates tokens.

### 2.2 Comments

Wiret adopts the following comment rules:

- `//` begins a line comment
- comments are trivia and are not semantically significant
- comments may be dropped during canonical formatting
- a comment box is the canonical way to preserve textual comments in the graph

Example:

```wiret
// This is a line comment.
node add = Add<i32>(a: x, b: y)
```

### 2.3 Keywords and identifiers

Identifiers follow:

```ebnf
identifier  = letter_or_underscore , { letter_or_digit_or_underscore } ;
letter_or_underscore = "A".."Z" | "a".."z" | "_" ;
letter_or_digit_or_underscore = letter_or_underscore | "0".."9" ;
```

Keywords are reserved. The canonical grammar reserves the following lexical words:

```text
wiret module use extern const var enum struct interface class
func event macro local node comment dispatcher return as impl
true false null bool i8 u8 i16 u16 i32 u32 i64 u64 f32 f64
string exec array set map delegate dispatcher
```

Newtonian note: the grammar intentionally treats `dispatcher` as both a declaration form and a type constructor.

### 2.4 Qualified names

Qualified names are dot-separated, with the last segment as the entity name:

```ebnf
qualified_name = identifier , { ".", identifier } ;
```

Examples:

```text
game.demo.Player
std.math.Sqrt
host.Log
```

### 2.5 Literals

Wiret supports value literals for text serialization and attribute data:

```ebnf
literal        = integer_literal
               | float_literal
               | boolean_literal
               | null_literal
               | string_literal
               | tuple_literal
               | list_literal
               | map_literal

integer_literal = ["-"], int_text, [ integer_suffix ] ;
float_literal   = ["-"], float_text, [ float_suffix ] ;
boolean_literal = "true" | "false" ;
null_literal    = "null" ;
string_literal  = '"', { string_char }, '"' ;
```

Integer suffixes:

```text
i8 u8 i16 u16 i32 u32 i64 u64
```

Float suffixes:

```text
f32 f64
```

String escapes include:

```text
\\  \\n  \\t  \\"  \\u{XXXX}
```

## 3. Type system

### 3.1 Primitive types

```ebnf
type = primitive_type
     | qualified_name
     | "exec"
     | "array" , "<", type, ">"
     | "set" , "<", type, ">"
     | "map" , "<", type, ",", type, ">"
     | "delegate" , "<", type_list, [ "->", type_list ], ">"
     | "dispatcher" , "<", type_list, ">"

primitive_type = "bool"
                | "i8" | "u8" | "i16" | "u16"
                | "i32" | "u32" | "i64" | "u64"
                | "f32" | "f64"
                | "string"

type_list = "(", [ type, { ",", type } ], ")" ;
```

Notes:

- `exec` is only valid in macro parameters and for `Reroute<exec>`.
- A `delegate` type has a call signature; a `dispatcher` type has no return values.
- `class` and `struct` names resolve as qualified names, including user-defined value/reference types.

### 3.2 Value categories

The language distinguishes:

- data pins: values
- exec pins: control-flow signals

A value may be:

- primitive
- enum
- struct
- class reference
- array/set/map reference
- delegate or dispatcher reference
- host handle

### 3.3 Subtyping

Wiret supports nominal subtyping for object/reference types.

Rules:

- a class instance may be passed to a superclass or implemented interface
- a value of an enum may convert to its underlying integer type and back
- a value may not implicitly convert between unrelated types
- explicit conversion is performed through `Convert<From, To>`

## 4. Module grammar

### 4.1 File grammar

```ebnf
file          = "wiret" , int_literal , newline
                , "module" , qualified_name , [ attrs ] , newline
                , { item } ;
```

### 4.2 Top-level items

```ebnf
item          = use_decl
              | extern_decl
              | const_decl
              | var_decl
              | enum_decl
              | struct_decl
              | interface_decl
              | class_decl
              | macro_decl
              | func_decl
              | event_decl ;
```

### 4.3 Use and extern declarations

```ebnf
use_decl      = "use" , qualified_name , [ "as" , identifier ] , newline ;

extern_decl   = "extern" , ( extern_func_decl | extern_type_decl ) , [ attrs ] , newline ;
extern_func_decl = "func" , qualified_name , params , [ results ] ;
extern_type_decl  = "type" , qualified_name ;
```

### 4.4 Constants, vars, and enums

```ebnf
const_decl    = "const" , identifier , ":" , type , "=" , literal , [ attrs ] , newline ;
var_decl      = "var" , identifier , ":" , type , [ "=" , literal ] , [ attrs ] , newline ;

enum_decl     = "enum" , identifier , [ ":" , integer_type ] , [ attrs ] , "{"
                , { enum_member } , "}" ;

enum_member   = identifier , [ "=", int_literal ] , [ attrs ] , newline ;
integer_type  = "i8" | "u8" | "i16" | "u16" | "i32" | "u32" | "i64" | "u64" ;
```

### 4.5 Structs and interfaces

```ebnf
struct_decl   = "struct" , identifier , [ attrs ] , "{"
              , { struct_field } , "}" ;

struct_field  = identifier , ":" , type , [ "=" , literal ] , [ attrs ] , newline ;

interface_decl = "interface" , identifier , [ attrs ] , "{"
               , { interface_func } , "}" ;

interface_func = "func" , identifier , params , [ results ] , [ attrs ] , newline ;
```

### 4.6 Classes

```ebnf
class_decl    = "class" , identifier , [ ":" , qualified_name ]
              , [ "impl" , qualified_name , { ",", qualified_name } ]
              , [ attrs ] , "{"
              , { class_member } , "}" ;

class_member  = field_decl
              | dispatcher_decl
              | func_decl
              | event_decl ;

field_decl    = identifier , ":" , type , [ "=" , literal ] , [ attrs ] , newline ;

dispatcher_decl = "dispatcher" , identifier , params , [ attrs ] , newline ;
```

A class may inherit from a single base class and implement any number of interfaces.

### 4.7 Functions, events, and macros

```ebnf
func_decl     = "func" , identifier , [ type_params ] , params , [ results ] , [ attrs ] , "{", body , "}" ;
event_decl    = "event" , identifier , params , [ attrs ] , "{", body , "}" ;
macro_decl    = "macro" , identifier , [ type_params ] , params , [ results ] , [ attrs ] , "{", body , "}" ;

params        = "(" , [ param , { ",", param } ] , ")" ;
results       = "->" , params ;
param         = identifier , ":" , type , [ "=" , literal ] ;
type_params   = "<", identifier, { ",", identifier }, ">" ;
```

## 5. Graph body grammar

A `func`, `event`, or `macro` body contains declarations and nodes in any order.

```ebnf
body          = { local_decl | node_stmt | comment_box } ;

local_decl    = "local" , identifier , ":" , type , [ "=" , literal ] , newline ;

node_stmt     = "node" , identifier , "=" , kind
              , [ symbol ]
              , [ "<", type, { ",", type }, ">" ]
              , [ "(", [ binding , { ",", binding } ], ")" ]
              , [ exec_output ]
              , [ attrs ]
              , newline ;

binding       = identifier , ":" , ( pin_ref | literal ) ;
pin_ref       = identifier , "." , identifier ;

exec_output   = "->" , target
               | "{", exec_target_map, "}" ;

exec_target_map = identifier , "->" , target , { ",", identifier , "->" , target } ;
target        = identifier , [ ".", identifier ] ;
comment_box   = "comment" , identifier , string_literal , "(" , [ identifier , { ",", identifier } ] , ")" , [ attrs ] , newline ;
```

### 5.1 Kind and symbol conventions

```ebnf
kind          = identifier ;
symbol        = qualified_name | identifier ;
```

Examples:

```wiret
node add = Add<i32>(a: left.value, b: right.value)
node call = Call std.math.Sqrt(value: x)
node field = GetField health (obj: actor)
node emit = Emit each (index: loop.index)
```

### 5.2 Exec wiring

Exec wiring is always written on the producer side:

```wiret
node branch = Branch(cond: cond.value) { then -> on_true, else -> on_false }
node store = SetLocal acc (value: sum.result) -> next
```

The shorthand form:

```wiret
-> target
```

is valid only when exactly one exec output is present.

### 5.3 Data wiring

A data wire is represented as a binding of an input pin to an output pin:

```wiret
node add = Add<i32>(a: cur.value, b: 1)
```

The right-hand side may be:

- another node output: `node.pin`
- a literal: `42`, `true`, `"text"`

### 5.4 Pin naming rules

Rules:

1. node ids are unique within a graph
2. a node id is not a display name; it is a stable identity for diffs
3. a pin reference must target an output pin in the same graph
4. entry parameters appear as `entry.param_name`
5. `self` is the implicit receiver parameter of a method

## 6. Attributes and metadata

### 6.1 Attribute grammar

```ebnf
attrs            = { attr } ;
attr             = "@", identifier , [ "(", [ arg, { ",", arg } ], ")" ] ;
arg              = [ identifier , ":" ] , value ;
value            = literal | identifier | tuple | list | map ;

tuple            = "(", [ value, { ",", value } ], ")" ;
list             = "[", [ value, { ",", value } ], "]" ;
map              = "{", [ entry, { ",", entry } ], "}" ;
entry            = value , ":" , value ;
```

### 6.2 Semantic attributes

These attributes may change compiled behavior:

```text
@id("...")
@pure
@final
@private
@export
@inline
@deprecated("msg")
@count(n)
@cases(v0, v1, ...)
@disabled
```

### 6.3 Editor and documentation attributes

These do not change the semantic meaning of the graph:

```text
@ed(...)
@doc("text")
@category("Math")
@keywords("a", "b")
```

Examples:

```wiret
node set_new = SetLocal new_hp (value: sub.result) -> store
  @ed(pos: (160, 0))

func Clamp01(v: f32) -> (result: f32) @pure

class Player @id("player_class") {
  ...
}
```

### 6.4 Attribute preservation rules

- unknown attributes are preserved in source if they are encountered during parsing
- order of repeated attributes is preserved
- unsafe attributes are those whose names begin with a capital letter
- tools must not silently drop unknown attributes
- namespaced keys like `@x.acme.review(...)` are reserved for third-party extensions

## 7. Canonical form and stable serialization

Wiret defines a canonical textual form, generated by `wiretc fmt` and expected by editors and merge tooling.

### 7.1 Canonical ordering rules

The canonical writer guarantees:

1. UTF-8 NFC, LF line endings, two-space indentation, final newline
2. declarations sorted by kind and then by name
3. body items sorted by `local`, then nodes by node id, then comments by id
4. bindings emitted in pin order for the node kind
5. semantic attributes sorted alphabetically before editor metadata
6. `@ed` emitted last, after exec targets
7. defaulted bindings omitted from the output
8. line comments removed

### 7.2 Semantic and layout hashes

Two SHA-256 hashes are defined over the canonical file:

- semantic hash: excludes editing metadata, docs, categories, keywords, comment boxes, and `Reroute` nodes
- layout hash: includes the whole canonical file

This enables:

- behavior-only CI checks
- visual/editor parity checks
- merge safety and graph identity tracking

## 8. Built-in node reference

### 8.1 Core control flow nodes

```text
Entry
Return
Branch
Sequence
Switch<T>
Select<T>
Try
Throw
Delay
Yield
Await
Macro
Emit
Exit
Reroute<T>
```

### 8.2 Variables and objects

```text
GetLocal / SetLocal
GetVar / SetVar
GetField
SetField
WithField
MakeStruct / BreakStruct
New
Cast
IsValid
Convert<From, To>
```

### 8.3 Arithmetic and logic

```text
Add Sub Mul Div Rem Min Max
Neg Abs
Eq Ne
Lt Le Gt Ge
And Or Xor Not
BitAnd BitOr BitXor BitNot Shl Shr
```

### 8.4 Containers

```text
MakeArray<T>
ArrayGet<T> / ArrayLength<T>
ArraySet<T> / ArrayAdd<T> / ArrayInsert<T> / ArrayRemove<T> / ArrayClear<T>
MapFind<K,V>
MapHas / MapLength / MapKeyAt / MapValueAt
MapSet / MapRemove / MapClear
SetHas / SetLength / SetAt / SetAdd / SetRemove / SetClear
```

### 8.5 Calls and events

```text
Call
CreateDelegate
Invoke<D>
Bind / Unbind
Broadcast
```

## 9. Runtime reference model

### 9.1 Execution units

Wiret execution occurs in a VM with:

- `wr_Vm`: global VM state
- `wr_Fiber`: one execution thread / coroutine-like unit
- `wr_Module`: compiled module with exports, imports, types, and code

At runtime, a fiber owns:

- call frames
- a stack
- a continuation stack for exec flow
- fault handlers
- local state

### 9.2 Host integration

The C API is exposed through `wiret.h`.

Key concepts:

```c
wr_Status wr_module_load(...);
wr_Status wr_call(...);
wr_Status wr_start(...);
wr_Status wr_advance(...);
wr_Status wr_register(...);
wr_Status wr_register_type(...);
```

The host interacts with the VM by:

- loading modules
- registering natives
- pushing values to a fiber stack
- invoking functions
- receiving results and faults
- driving time for latent execution

### 9.3 Fault model

Common fault classes include:

- null dereference
- bad index
- divide by zero
- failed cast
- stack overflow
- host-driven aborts
- native-reported errors

Faults can be caught by `Try`, except for:

- fuel exhaustion
- memory exhaustion
- host-killed fibers

## 10. Bytecode model

### 10.1 Container layout

The bytecode format is a typed object container, roughly analogous to a compact, graph-aware WASM/JVM-like module.

```ebnf
module    = magic, version, flags, { section } ;
magic     = 0x00, 0x57, 0x42, 0x43 ;
version   = u32 ;
flags     = u32 ;
```

The file contains sections such as:

- custom section `name`
- type table
- import list
- function table
- export list
- data section
- code bodies
- debug metadata and embedded source

### 10.2 Custom sections

The following custom sections are defined:

```text
name
wr.debug
wr.graph
wr.meta
wr.reflect
```

These carry:

- function and type names
- node id to code-offset mapping
- embedded canonical source text
- semantic/layout hashes
- reflection metadata and docs

### 10.3 Verification

Before running any module, a conforming VM verifies:

- section ordering and integrity
- valid instruction decoding
- branch target validity
- stack discipline at labels
- type consistency
- return arity correctness
- maximum stack/continuation constraints
- latent-node rules

## 11. Formal grammar summary

This condensed grammar captures the main language structure.

```ebnf
file          = "wiret" , int_literal , newline
              , "module" , qualified_name , [ attrs ] , newline
              , { item } ;

item          = use_decl
              | extern_decl
              | const_decl
              | var_decl
              | enum_decl
              | struct_decl
              | interface_decl
              | class_decl
              | macro_decl
              | func_decl
              | event_decl ;

use_decl      = "use" , qualified_name , [ "as" , identifier ] , newline ;
extern_decl   = "extern" , ( "func" , qualified_name , params , [ results ]
                    | "type" , qualified_name ) , [ attrs ] , newline ;

const_decl    = "const" , identifier , ":" , type , "=" , literal , [ attrs ] , newline ;
var_decl      = "var" , identifier , ":" , type , [ "=" , literal ] , [ attrs ] , newline ;

enum_decl     = "enum" , identifier , [ ":" , integer_type ] , [ attrs ] , "{"
              , { identifier , [ "=", int_literal ] , [ attrs ] , newline } , "}" ;

struct_decl   = "struct" , identifier , [ attrs ] , "{"
              , { identifier , ":" , type , [ "=" , literal ] , [ attrs ] , newline } , "}" ;

interface_decl = "interface" , identifier , [ attrs ] , "{"
              , { "func" , identifier , params , [ results ] , [ attrs ] , newline } , "}" ;

class_decl    = "class" , identifier , [ ":" , qualified_name ]
              , [ "impl" , qualified_name , { ",", qualified_name } ]
              , [ attrs ] , "{"
              , { field_decl | dispatcher_decl | func_decl | event_decl } , "}" ;

macro_decl    = "macro" , identifier , [ type_params ] , params , [ results ] , [ attrs ] , "{", body , "}" ;
func_decl     = "func" , identifier , [ type_params ] , params , [ results ] , [ attrs ] , "{", body , "}" ;
event_decl    = "event" , identifier , params , [ attrs ] , "{", body , "}" ;

body          = { local_decl | node_stmt | comment_box } ;
node_stmt     = "node" , identifier , "=" , kind
              , [ symbol ]
              , [ "<", type, { ",", type }, ">" ]
              , [ "(", [ binding , { ",", binding } ], ")" ]
              , [ exec_output ]
              , [ attrs ]
              , newline ;

binding       = identifier , ":" , ( pin_ref | literal ) ;
pin_ref       = identifier , "." , identifier ;
exec_output   = "->" , target
               | "{", identifier , "->" , target , { ",", identifier , "->" , target }, "}" ;
target        = identifier , [ ".", identifier ] ;
comment_box   = "comment" , identifier , string_literal , "(" , [ identifier , { ",", identifier } ], ")" , [ attrs ] , newline ;

attrs         = { attr } ;
attr          = "@", identifier , [ "(", [ arg, { ",", arg } ], ")" ] ;
arg           = [ identifier , ":" ] , value ;
value         = literal | identifier | tuple | list | map ;

tuple         = "(", [ value, { ",", value } ], ")" ;
list          = "[", [ value, { ",", value } ], "]" ;
map           = "{", [ value , ":" , value , { ",", value , ":" , value } ], "}" ;
```

## 12. Reference notes

### 12.1 Why text-first graph syntax is valuable

A text-based graph language is not a compromise. It gives you:

- branch-friendly versioning in Git
- editor neutrality and portability
- deterministic canonical output
- easier diffing and semantic merge support
- better LLM tooling and code generation
- a straightforward bridge from visual graphs to bytecode and runtime

### 12.2 Design trade-offs

The design intentionally favors:

- explicitness over inference
- determinism over convenience
- canonical serialization over ad hoc editing layouts
- verified execution over flexible-but-unsafe runtime behavior

This is a deliberate choice: a visual data flow language can be very expressive, but it becomes much more useful when it remains inspectable, stable, and reviewable as plain text.

### 12.3 Recommended implementation order

A practical implementation should proceed in this order:

1. lexer and parser
2. canonical formatter
3. semantic resolver and type checker
4. validator and graph checks
5. lowering to bytecode
6. verifier
7. interpreter/VM
8. runtime C API integration
9. editor metadata and debugger support

## 13. Summary

Wiret is intentionally built as a text-first IR for graph programs:

- source is graph text and metadata
- the canonical form is stable and reviewable
- bytecode is typed, verified, and portable
- the VM is embeddable and sandboxable through a C API
- the final model is friendly to both humans and machines

The formal grammar above gives the structural basis for implementing the language, while the broader specification in `docs/index.md` covers the richer design intent, semantics, runtime, and bytecode sections.

In short, Wiret aims to be the textual form of a visual scripting language without losing the strengths that make text-based systems easy to review, store, compile, and generate.

---

This reference is a companion doc to the language overview in `docs/index.md`.
